// The one measuring and linting implementation. The asset room, tools/asset_lint.js and the server all run
// readWav -> measure -> lint from this file, so the same bytes get the same verdict everywhere.
(function (factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  const root = typeof window !== 'undefined' ? window : typeof self !== 'undefined' ? self : null;
  if (root) root.assetMeasure = api;
})(function () {
  'use strict';

  const FLOOR = -120; // dB reported for digital silence
  const QUIET = -70; // LUFS reported when nothing passes the absolute gate
  const CLIP = 32767 / 32768;
  const db = (v) => 20 * Math.log10(Math.max(v, 1e-6));

  /* ---------- WAV ---------- */
  // PCM 8, 16, 24 and 32 bit integers and 32 (or 64) bit floats, any channel count. Integer full scale becomes 1.
  // Throws for anything it cannot read as it was meant: other formats, samples padded into wider slots, and floats that are not finite numbers.
  function readWav(bytes) {
    const u8 = bytes instanceof Uint8Array ? bytes : ArrayBuffer.isView(bytes) ? new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength) : new Uint8Array(bytes || 0);
    const v = new DataView(u8.buffer, u8.byteOffset, u8.byteLength), size = u8.length;
    const tag = (at) => String.fromCharCode(u8[at], u8[at + 1], u8[at + 2], u8[at + 3]);
    if (size < 12 || tag(0) !== 'RIFF' || tag(8) !== 'WAVE') throw new Error('not a WAV file');
    // Whether a chunk starts here: four printable characters, then a size that fits in what is left of the file.
    const chunkAt = (at) => at + 8 <= size && [0, 1, 2, 3].every((k) => u8[at + k] >= 0x20 && u8[at + k] < 0x7f) && at + 8 + v.getUint32(at + 4, true) <= size;
    let fmt = null, data = null;
    for (let at = 12; at + 8 <= size;) {
      const id = tag(at), body = at + 8;
      let len = v.getUint32(at + 4, true);
      if (id === 'fmt ' && len >= 16 && body + 16 <= size) {
        const type = v.getUint16(body, true);
        // WAVE_FORMAT_EXTENSIBLE keeps the real type in the first two bytes of its sub-format.
        fmt = { type: type === 0xfffe && len >= 40 && body + 26 <= size ? v.getUint16(body + 24, true) : type, channels: v.getUint16(body + 2, true), rate: v.getUint32(body + 4, true), align: v.getUint16(body + 12, true), bits: v.getUint16(body + 14, true) };
      } else if (id === 'data' && !data) {
        // A writer that could not go back to fill in the size leaves all ones or 0. Either way the samples run to the end of the file.
        if (!len && body < size && !chunkAt(body)) len = size - body;
        data = { at: body, len: Math.min(len, size - body) };
      }
      at = body + len + (len & 1);
    }
    if (!fmt || !data) throw new Error(`WAV has no ${fmt ? 'data' : 'fmt'} chunk`);
    const { type, channels, rate, align, bits } = fmt, width = bits / 8;
    // Infinity and NaN are a render that blew up. Read as silence they would pass every check, so they are refused. Past float32 range counts too.
    const finite = (x) => { if (!Number.isFinite(Math.fround(x))) throw new Error('WAV holds non-finite samples'); return x; };
    const read = type === 1 ? {
      8: (at) => (u8[at] - 128) / 128,
      16: (at) => v.getInt16(at, true) / 32768,
      24: (at) => ((u8[at] | u8[at + 1] << 8 | u8[at + 2] << 16) << 8 >> 8) / 8388608,
      32: (at) => v.getInt32(at, true) / 2147483648,
    }[bits] : type === 3 ? { 32: (at) => finite(v.getFloat32(at, true)), 64: (at) => finite(v.getFloat64(at, true)) }[bits] : null;
    // A block align that disagrees with the bit depth means padded samples (24 bits in 4 bytes): read at the plain width they would be noise.
    if (!read || !channels || !rate || (align && align !== width * channels)) throw new Error(`unsupported WAV format (type ${type}, ${bits} bit, ${channels} channels, ${rate} Hz, ${align} bytes a frame)`);
    const frames = Math.floor(data.len / (width * channels)), chans = Array.from({ length: channels }, () => new Float32Array(frames));
    for (let i = 0, at = data.at; i < frames; i++) for (let c = 0; c < channels; c++, at += width) chans[c][i] = read(at);
    return { rate, bits, chans };
  }

  /* ---------- true peak ---------- */
  // Three points between every pair of samples, from a windowed sinc. The samples are the fourth point, so true peak is never below sample peak.
  // Before the first sample and after the last there is silence, as when the sound is started and stopped. A sound that begins or ends
  // away from zero therefore reads up to about 1 dB over its sample peak there. A loop is read the same way: its first start is such a jump.
  const OVER = 4, HALF = 8;
  const TAPS = [1, 2, 3].map((p) => {
    const taps = Float64Array.from({ length: 2 * HALF }, (_, k) => {
      const t = k - HALF + 1 - p / OVER; // from the point being read to the sample this tap weighs
      return Math.sin(Math.PI * t) / (Math.PI * t) * (0.5 + 0.5 * Math.cos(Math.PI * t / HALF));
    });
    const sum = taps.reduce((a, b) => a + b, 0);
    return taps.map((w) => w / sum);
  });
  const REACH = Math.max(...TAPS.map((taps) => taps.reduce((a, b) => a + Math.abs(b), 0)));
  const BLOCK = 64;
  // The largest magnitude of one channel at 4x, starting from `best` (a peak already known).
  function truePeak(x, n, best) {
    const blocks = Math.ceil(n / BLOCK), tops = new Float64Array(blocks + 2); // tops[b + 1] belongs to block b; silence pads both ends
    for (let i = 0; i < n; i++) { const a = Math.abs(x[i]), b = Math.floor(i / BLOCK) + 1; if (a > tops[b]) tops[b] = a; }
    for (let b = 0; b < blocks; b++) {
      // No in-between point can exceed the loudest sample in reach times the taps' total weight, so quiet stretches are skipped.
      if (Math.max(tops[b], tops[b + 1], tops[b + 2]) * REACH <= best) continue;
      for (let i = b * BLOCK, stop = Math.min(n, i + BLOCK); i < stop; i++) {
        const base = i - HALF + 1, from = Math.max(0, -base), to = Math.min(2 * HALF, n - base);
        for (const taps of TAPS) {
          let y = 0;
          for (let k = from; k < to; k++) y += x[base + k] * taps[k];
          if (y < 0) y = -y;
          if (y > best) best = y;
        }
      }
    }
    return best;
  }

  /* ---------- loudness ---------- */
  // BS.1770 integrated loudness. The K weighting is designed for the file's own rate; at 48 kHz it is the published pair of filters.
  // Every channel counts with weight 1 (mono and stereo are what this room makes).
  function loudness(chans, n, rate) {
    const k1 = Math.tan(Math.PI * 1681.974450955533 / rate), q1 = 0.7071752369554196, vh = 10 ** (3.999843853973347 / 20), vb = vh ** 0.4996667741545416, d1 = 1 + k1 / q1 + k1 * k1;
    const b0 = (vh + vb * k1 / q1 + k1 * k1) / d1, b1 = 2 * (k1 * k1 - vh) / d1, b2 = (vh - vb * k1 / q1 + k1 * k1) / d1, a1 = 2 * (k1 * k1 - 1) / d1, a2 = (1 - k1 / q1 + k1 * k1) / d1;
    const k2 = Math.tan(Math.PI * 38.13547087602444 / rate), q2 = 0.5003270373238773, d2 = 1 + k2 / q2 + k2 * k2, c1 = 2 * (k2 * k2 - 1) / d2, c2 = (1 - k2 / q2 + k2 * k2) / d2;
    // A 400 ms block starts every 100 ms, so a block is four steps. Only the energy of each step is kept, however long the file is.
    const step = Math.max(1, Math.round(0.1 * rate)), block = 4 * step, steps = new Float64Array(Math.ceil(n / step));
    for (const x of chans) {
      let s1 = 0, s2 = 0, t1 = 0, t2 = 0;
      for (let s = 0, i = 0; i < n; s++) {
        let energy = 0;
        for (const stop = Math.min(n, i + step); i < stop; i++) {
          const u = x[i], y = b0 * u + s1;
          s1 = b1 * u - a1 * y + s2; s2 = b2 * u - a2 * y;
          const z = y + t1;
          t1 = -2 * y - c1 * z + t2; t2 = y - c2 * z;
          energy += z * z;
        }
        steps[s] += energy;
      }
    }
    const lufs = (power) => (power > 0 ? Math.max(QUIET, -0.691 + 10 * Math.log10(power)) : QUIET);
    if (n < block) return lufs(steps.reduce((a, b) => a + b, 0) / n); // too short for one block: the level of the whole sound, ungated
    const powers = [];
    for (let s = 0; (s + 4) * step <= n; s++) powers.push((steps[s] + steps[s + 1] + steps[s + 2] + steps[s + 3]) / block);
    const mean = (gate) => { let sum = 0, count = 0; for (const p of powers) if (p > gate) { sum += p; count++; } return count ? sum / count : 0; };
    const absolute = 10 ** ((QUIET + 0.691) / 10);
    return lufs(mean(Math.max(absolute, mean(absolute) / 10))); // the relative gate sits 10 LU under what passed the absolute one
  }

  /* ---------- the rest ---------- */
  // The slope 99 in 100 of this channel's steps stay under. A long file has millions of steps, so no sorted copy is made:
  // they are counted into bins twice, the second time inside the bin the first count picked. The answer is that small bin's lower edge.
  const BINS = 65536;
  function steepOf(x, n) {
    const counts = new Uint32Array(BINS), rank = Math.floor((n - 1) * 0.99);
    let low = 0, width = 0;
    for (let i = 1; i < n; i++) { const d = Math.abs(x[i] - x[i - 1]); if (d > width) width = d; }
    for (let round = 0; round < 2 && width > 0; round++) {
      const scale = BINS / width;
      let under = 0, bin = 0;
      counts.fill(0);
      for (let i = 1; i < n; i++) {
        const d = Math.abs(x[i] - x[i - 1]);
        if (d < low) under++; else counts[Math.min(BINS - 1, Math.floor((d - low) * scale))]++;
      }
      while (bin < BINS - 1 && under + counts[bin] <= rank) under += counts[bin++];
      low += bin / scale; width /= BINS;
    }
    return low;
  }
  // A seam is judged against how steeply this sound moves anyway, so noise is not punished for being noise.
  const seamOf = (x, n) => Math.abs(x[0] - x[n - 1]) / Math.max(steepOf(x, n), 1e-4);
  // Where the energy sits: share below 250 Hz, 250 Hz to 4 kHz, above 4 kHz, and a brightness from the zero-crossing rate.
  function bands(mix, n, rate) {
    const k = (f) => 1 - Math.exp(-2 * Math.PI * f / rate);
    const a = k(250), b = k(4000);
    let l1 = 0, l2 = 0, low = 0, mid = 0, high = 0, cross = 0;
    for (let i = 0; i < n; i++) {
      const x = mix[i]; l1 += (x - l1) * a; l2 += (x - l2) * b;
      low += l1 * l1; mid += (l2 - l1) ** 2; high += (x - l2) ** 2;
      if (i && (x >= 0) !== (mix[i - 1] >= 0)) cross++;
    }
    const all = low + mid + high || 1, pct = (v) => Math.round(v / all * 100);
    return { low: pct(low), mid: pct(mid), high: pct(high), bright: Math.round(cross / n * rate / 2) };
  }

  // sound is what readWav returns: { rate, bits, chans: [Float32Array] }.
  // peak, sample_peak, loud, clips, lead, tail, dc, seam and end look at every channel; wrap, dip and the bands look at the mono sum.
  function measure(sound) {
    const chans = sound.chans || [], rate = sound.rate, channels = chans.length, bits = sound.bits ?? null;
    if (!(rate > 0)) throw new Error('measure needs a sample rate');
    const n = channels ? Math.min(...chans.map((c) => c.length)) : 0, seconds = n / rate;
    // Nothing to measure in no samples or one: a fixed silent result.
    if (n < 2) return { peak: FLOOR, loud: QUIET, seconds, clips: 0, lead: 0, tail: 0, dc: 0, seam: 0, wrap: 0, dip: 0, low: 0, mid: 0, high: 0, bright: 0, rate, channels, bits, sample_peak: FLOOR, end: FLOOR };
    // A frame clips when a channel sits on the rail: the 16-bit one for every format but 8-bit, whose own top value (127/128) is lower.
    const rail = Math.min(CLIP, bits > 1 ? 1 - 2 ** (1 - bits) : 1);
    let top = 0, clips = 0, lead = -1, last = 0;
    for (let i = 0; i < n; i++) {
      let a = 0;
      for (let c = 0; c < channels; c++) { const x = Math.abs(chans[c][i]); if (x > a) a = x; }
      if (a > top) top = a;
      if (a >= rail) clips++;
      if (a > 0.003) { if (lead < 0) lead = i; last = i; }
    }
    const ending = Math.min(n, Math.max(1, Math.round(0.05 * rate)));
    let over = top, dc = 0, seam = 0, end = 0;
    for (const x of chans) {
      over = truePeak(x, n, over);
      let sum = 0, energy = 0;
      for (let i = 0; i < n; i++) sum += x[i];
      for (let i = n - ending; i < n; i++) energy += x[i] * x[i];
      if (!Number.isFinite(sum)) over = Infinity; // a NaN or infinite sample: no peak can be given, and lint counts that as over
      dc = Math.max(dc, Math.abs(sum / n)); end = Math.max(end, Math.sqrt(energy / ending)); seam = Math.max(seam, seamOf(x, n));
    }
    let mix = chans[0];
    if (channels > 1) {
      mix = new Float32Array(n);
      for (const x of chans) for (let i = 0; i < n; i++) mix[i] += x[i] / channels;
    }
    const rms = (from, count) => { let e = 0; for (let i = from; i < from + count; i++) e += mix[i] * mix[i]; return Math.sqrt(e / count); };
    const span = Math.max(1, Math.min(Math.floor(0.25 * rate), Math.floor(n / 2)));
    let faintest = Infinity;
    for (let i = 0; i + span <= n; i += span) faintest = Math.min(faintest, rms(i, span));
    return {
      peak: db(over), loud: loudness(chans, n, rate), seconds, clips,
      lead: Math.max(0, lead) / rate * 1000, tail: (n - 1 - last) / rate * 1000,
      dc, seam, wrap: Math.abs(db(rms(0, span)) - db(rms(n - span, span))), dip: db(rms(0, n)) - db(faintest),
      ...bands(mix, n, rate),
      rate, channels, bits, sample_peak: db(top), end: db(end),
    };
  }

  /* ---------- rules ---------- */
  const PROFILES = [
    { id: 'mobile', loud: [-20, -16] },
    { id: 'console', loud: [-26, -22] },
    { id: 'wide', loud: [-26, -14] },
  ];
  const ID_RULE = { pattern: '{kind}_{name}', sep: '_', prefix: { sfx: 'sfx', amb: 'amb', music: 'bgm' }, check: true };
  // A rule from a spec may leave parts out; the rest is the default, the way the asset room merges it.
  const ruleOf = (r) => ({
    pattern: r && typeof r.pattern === 'string' && r.pattern ? r.pattern : ID_RULE.pattern, sep: r && typeof r.sep === 'string' ? r.sep : ID_RULE.sep,
    prefix: { ...ID_RULE.prefix, ...(r && r.prefix) }, check: r && r.check !== undefined ? !!r.check : ID_RULE.check,
  });
  const slugOf = (text) => String(text ?? '').replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
  const escRe = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // idRule = { pattern, sep, prefix, check }. {cat} is any of catIds; with check off only an empty id is wrong.
  function idOk(id, idRule, catIds) {
    const rule = ruleOf(idRule);
    if (!rule.check) return !!id;
    const sep = escRe(rule.sep), word = '[a-z0-9]+', alt = (list) => `(?:${[...new Set(list.filter(Boolean))].map(escRe).join('|')})`;
    // A separator of nothing, or of letters and digits only, cannot be told from the words: the name is then one run of them.
    // Written as one run it accepts the same ids, and a wrong id is turned down at once instead of after every way of splitting it.
    const name = /^[a-z0-9]*$/.test(rule.sep) ? word : `${word}(?:${sep}${word})*`;
    const src = rule.pattern.split(/(\{kind\}|\{cat\}|\{name\})/).map((p) => (p === '{kind}' ? alt(Object.values(rule.prefix))
      : p === '{cat}' ? alt((catIds || []).map((c) => slugOf(c).join(rule.sep))) : p === '{name}' ? name : escRe(p))).join('');
    try { return typeof id === 'string' && new RegExp(`^${src}(?:${sep}\\d+)?$`).test(id); } catch { return true; }
  }

  // facts say what the sound is: { kind: 'sfx'|'amb'|'music' (or music: true), loop, id, sources }.
  const music = (f) => f.kind === 'music' || f.music === true;
  const over = (v, limit) => v > limit;
  // Ids and limits as the asset room has always had them. `text` rules judge the record, not the sound.
  const RULES = [
    { id: 'peak', level: 'error', limit: -1, fix: true, read: (m) => m.peak, bad: over },
    { id: 'clip', level: 'error', limit: 0, fix: true, read: (m) => m.clips, bad: over },
    { id: 'loud', level: 'error', range: [-20, -16], fix: true, applies: music, read: (m) => m.loud, bad: (v, range) => v < range[0] || v > range[1] },
    { id: 'dur', level: 'warn', limit: 2, applies: (f) => !music(f) && !f.loop, read: (m) => m.seconds, bad: over },
    { id: 'lead', level: 'warn', limit: 50, fix: true, applies: (f) => !f.loop, read: (m) => m.lead, bad: over },
    { id: 'tail', level: 'warn', limit: 200, fix: true, applies: (f) => !f.loop, read: (m) => m.tail, bad: over },
    { id: 'dc', level: 'warn', limit: 0.002, read: (m) => m.dc, bad: over },
    { id: 'seam', level: 'warn', limit: 3, applies: (f) => !!f.loop, read: (m) => m.seam, bad: over },
    { id: 'wrap', level: 'warn', limit: 3, applies: (f) => !!f.loop && !music(f), read: (m) => m.wrap, bad: over },
    { id: 'steady', level: 'warn', limit: 12, applies: (f) => !!f.loop && !music(f), read: (m) => m.dip, bad: over },
    { id: 'name', level: 'error', text: true, read: (m, f) => f.id, bad: (v, limit, o) => !idOk(v, o.idRule, o.catIds) },
    { id: 'lic', level: 'error', text: true, limit: 1, read: (m, f) => (Array.isArray(f.sources) ? f.sources.length : 0), bad: (v, limit) => v < limit },
  ];
  for (const list of [RULES, PROFILES]) list.forEach((x) => { Object.freeze(x.range || x.loud || x); Object.freeze(x); });
  Object.freeze(ID_RULE.prefix); Object.freeze(ID_RULE);

  // opts = { profile | loud: [low, high], idRule, catIds }. Returns [{ id, level, value, limit }], an empty list when all is well.
  // Nothing passes for want of an answer. Every rule that applies is judged: a missing id is a `name` issue, missing sources a `lic` issue,
  // and a measurement that is missing or not a finite number (no `m` at all, a NaN, an infinite peak) is an issue of its rule with value null.
  function lint(facts, m, opts) {
    const f = facts || {}, o = opts || {}, out = [];
    const profile = PROFILES.find((p) => p.id === o.profile);
    const range = Array.isArray(o.loud) && o.loud.length === 2 ? [o.loud[0], o.loud[1]] : [...(profile ? profile.loud : RULES.find((r) => r.id === 'loud').range)];
    for (const r of RULES) {
      if (r.applies && !r.applies(f)) continue;
      const value = r.read(m || {}, f), known = r.text ? value != null : Number.isFinite(value);
      const limit = r.id === 'loud' ? range : r.id === 'name' ? ruleOf(o.idRule).pattern : r.limit;
      if ((!r.text && !known) || r.bad(value, limit, o)) out.push({ id: r.id, level: r.level, value: known ? value : null, limit });
    }
    return out;
  }

  return { readWav, measure, RULES, PROFILES, ID_RULE, idOk, lint };
});
