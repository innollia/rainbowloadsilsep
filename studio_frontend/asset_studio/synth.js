// The sound of a legacy version (the stand-in sounds boards saved by earlier pages still hold), synthesised from its
// layers so tiles, waveforms and measurements are real signals.
(() => {
  const RATE = 22050;
  const FOLD = 0.5; // seconds rendered past a loop and folded back onto its head
  const hz = (m) => 440 * 2 ** ((m - 69) / 12);
  const osc = (wave, phase) => {
    const t = phase % 1;
    if (wave === 'square') return t < 0.5 ? 1 : -1;
    if (wave === 'saw') return 2 * t - 1;
    if (wave === 'triangle') return 4 * Math.abs(t - 0.5) - 1;
    return Math.sin(2 * Math.PI * t);
  };

  function tone(out, l, shift, stretch) {
    const start = Math.floor(l.at * RATE), n = Math.floor(l.len * stretch * RATE);
    let phase = 0;
    for (let i = 0; i < n && start + i < out.length; i++) {
      const p = i / n, f = (l.from + (l.to - l.from) * p) * shift;
      phase += f / RATE;
      out[start + i] += osc(l.wave, phase) * l.gain * (1 - p) ** 1.6 * Math.min(1, i / 40);
    }
  }
  // Seeded white noise in [-1, 1), so a re-render of the same asset is the same sound.
  const whiteFrom = (seed) => { let random = seed; return () => { random = (random * 16807) % 2147483647; return random / 1073741824 - 1; }; };
  function noise(out, l, stretch, seed) {
    const next = whiteFrom(seed);
    let low = 0;
    const start = Math.floor(l.at * RATE), n = Math.floor(l.len * stretch * RATE), rise = Math.max(1, l.attack * RATE);
    for (let i = 0; i < n && start + i < out.length; i++) {
      low += (next() - low) * l.cutoff;
      const env = Math.min(1, i / rise) * (1 - i / n) ** (l.len > 1 ? 0.5 : 1.6);
      out[start + i] += low * l.gain * env * (1 + (1 - l.cutoff));
    }
  }
  // Ambience never fades: it runs for the whole buffer, and render() folds the overrun back onto the head.
  function bed(out, l, shift, stretch, seed) {
    const period = l.len * stretch * RATE, cutoff = Math.min(0.98, l.cutoff * shift);
    const next = whiteFrom(seed);
    let low = 0;
    for (let i = 0; i < 2000; i++) low += (next() - low) * cutoff;
    for (let i = 0; i < out.length; i++) {
      low += (next() - low) * cutoff;
      let swell = 1;
      for (const [cycles, depth, phase] of l.swells) swell += depth * Math.sin(2 * Math.PI * cycles * i / period + phase);
      out[i] += low * l.gain * swell * (1 + (1 - l.cutoff));
    }
  }
  function seq(out, l, shift, stretch) {
    l.notes.forEach((note, i) => {
      if (note == null) return;
      const f = hz(note) * shift;
      tone(out, { at: i * l.step, len: l.len, from: f, to: f, wave: l.wave, gain: l.gain }, 1, stretch);
    });
  }
  function drums(out, l, seed) {
    const bars = Math.ceil(out.length / RATE / (l.step * l.kick.length));
    for (let bar = 0; bar < bars; bar++) {
      for (let i = 0; i < l.kick.length; i++) {
        const at = (bar * l.kick.length + i) * l.step;
        if (l.kick[i] === 'x') tone(out, { at, len: 0.16, from: 130, to: 45, wave: 'sine', gain: l.gain * 1.3 }, 1, 1);
        if (l.hat[i] === 'x') noise(out, { at, len: 0.04, cutoff: 0.95, gain: l.gain * 0.3, attack: 0.001 }, 1, seed + i + 1);
      }
    }
  }

  // A sound the user brought in. A request plays it faster or slower, which moves pitch and length together.
  function fromSource(asset, change) {
    const src = asset.source, speed = (change.shift ?? 1) / (change.stretch ?? 1);
    const length = Math.max(1, Math.floor(src.length / speed)), data = new Float32Array(length);
    for (let i = 0; i < length; i++) { const at = i * speed, j = Math.floor(at), f = at - j; data[i] = (src[j] || 0) * (1 - f) + (src[j + 1] || 0) * f; }
    return finish([{ name: 'main', data }], length, change, change.level ?? 1);
  }
  function render(asset, change = {}) {
    if (asset.source) return fromSource(asset, change);
    const shift = change.shift ?? 1, stretch = change.stretch ?? 1, level = (change.level ?? 1) * (asset.loud ?? 1);
    const end = (l) => {
      if (l.kind === 'seq') return l.notes.length * l.step;
      if (l.kind === 'drums') return 8 * l.kick.length * l.step / 4;
      return l.at + l.len * stretch;
    };
    const beds = asset.layers.filter((l) => l.kind === 'bed');
    const seconds = beds.length ? Math.max(...beds.map((l) => l.len * stretch)) : Math.max(0.06, ...asset.layers.map(end));
    const length = Math.ceil((seconds + (asset.music || asset.loop ? 0 : 0.03)) * RATE);
    const fold = beds.length ? Math.ceil(FOLD * RATE) : 0;
    const groups = [];
    asset.layers.forEach((l, i) => {
      const name = l.stem || (asset.layers.length > 1 ? (l.kind === 'noise' ? 'noise_layer' : `tone_layer_${i + 1}`) : 'main');
      let g = groups.find((x) => x.name === name);
      if (!g) { g = { name, data: new Float32Array(length + fold) }; groups.push(g); }
      if (l.kind === 'bed') bed(g.data, l, shift, stretch, 7919 + i * 131 + Math.round(shift * 100));
      else if (l.kind === 'tone') tone(g.data, l, shift, stretch);
      else if (l.kind === 'noise') noise(g.data, l, stretch, 7919 + i * 131 + Math.round(shift * 100));
      else if (l.kind === 'seq') seq(g.data, l, shift, stretch);
      else drums(g.data, l, 104729 + i);
    });
    // Equal power, because the two sides are unrelated noise. The first sample is the natural next sample after the last.
    if (fold) {
      for (const g of groups) {
        for (let i = 0; i < fold; i++) {
          const t = i / fold * Math.PI / 2;
          g.data[i] = g.data[i] * Math.sin(t) + g.data[length + i] * Math.cos(t);
        }
        g.data = g.data.slice(0, length);
        const mean = g.data.reduce((sum, v) => sum + v, 0) / length;
        for (let i = 0; i < length; i++) g.data[i] -= mean;
      }
    }
    return finish(groups, length, change, level);
  }
  function finish(groups, length, change, level) {
    const mix = new Float32Array(length);
    for (const g of groups) for (let i = 0; i < length; i++) { g.data[i] *= level; mix[i] += g.data[i]; }
    if (change.ceiling) {
      for (let i = 0; i < length; i++) {
        const v = Math.abs(mix[i]);
        if (v > change.ceiling) { const g = change.ceiling / v; mix[i] *= g; for (const x of groups) x.data[i] *= g; }
      }
    }
    if (change.dc) {
      const mean = mix.reduce((sum, v) => sum + v, 0) / length;
      for (let i = 0; i < length; i++) { mix[i] -= mean; groups[0].data[i] -= mean; }
    }
    if (change.trim) {
      const from = Math.floor(change.trim[0] * RATE), to = length - Math.floor(change.trim[1] * RATE);
      for (const g of groups) g.data = g.data.slice(from, to);
      return { rate: RATE, seconds: (to - from) / RATE, stems: groups, mix: mix.slice(from, to) };
    }
    return { rate: RATE, seconds: length / RATE, stems: groups, mix };
  }

  function measure(sound) {
    const { mix, rate } = sound;
    let peak = 0, sum = 0, total = 0, lead = -1, last = 0, clips = 0;
    for (let i = 0; i < mix.length; i++) {
      const v = Math.abs(mix[i]);
      peak = Math.max(peak, v); sum += v * v; total += mix[i];
      if (v >= 1) clips++;
      if (v > 0.003) { if (lead < 0) lead = i; last = i; }
    }
    const db = (v) => 20 * Math.log10(Math.max(v, 1e-6));
    const rms = (from, count) => { let e = 0; for (let i = from; i < from + count; i++) e += mix[i] * mix[i]; return Math.sqrt(e / count); };
    const span = Math.min(Math.floor(0.25 * rate), Math.floor(mix.length / 2)), frames = [];
    for (let i = 0; i + span <= mix.length; i += span) frames.push(rms(i, span));
    // A seam is judged against how steeply this sound moves anyway, so noise is not punished for being noise.
    const slopes = new Float32Array(mix.length - 1);
    for (let i = 1; i < mix.length; i++) slopes[i - 1] = Math.abs(mix[i] - mix[i - 1]);
    slopes.sort();
    const steep = Math.max(slopes[Math.floor(slopes.length * 0.99)], 1e-4);
    return {
      peak: db(peak), loud: db(Math.sqrt(sum / mix.length)) - 0.7, seconds: sound.seconds, clips,
      lead: Math.max(0, lead) / rate * 1000, tail: (mix.length - 1 - last) / rate * 1000,
      dc: Math.abs(total / mix.length), seam: Math.abs(mix[0] - mix[mix.length - 1]) / steep,
      wrap: Math.abs(db(rms(0, span)) - db(rms(mix.length - span, span))), dip: db(Math.sqrt(sum / mix.length)) - db(Math.min(...frames)),
      ...bands(mix, rate),
    };
  }
  // Where the energy sits: share below 250 Hz, 250 Hz to 4 kHz, above 4 kHz, and a brightness from the zero-crossing rate.
  function bands(mix, rate) {
    const k = (f) => 1 - Math.exp(-2 * Math.PI * f / rate);
    const a = k(250), b = k(4000);
    let l1 = 0, l2 = 0, low = 0, mid = 0, high = 0, cross = 0;
    for (let i = 0; i < mix.length; i++) {
      const x = mix[i]; l1 += (x - l1) * a; l2 += (x - l2) * b;
      low += l1 * l1; mid += (l2 - l1) ** 2; high += (x - l2) ** 2;
      if (i && (x >= 0) !== (mix[i - 1] >= 0)) cross++;
    }
    const all = low + mid + high || 1, pct = (v) => Math.round(v / all * 100);
    return { low: pct(low), mid: pct(mid), high: pct(high), bright: Math.round(cross / Math.max(1, mix.length) * rate / 2) };
  }

  function peaks(data, count) {
    const size = Math.max(1, Math.floor(data.length / count)), out = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      let m = 0;
      for (let j = i * size; j < Math.min(data.length, (i + 1) * size); j += 2) m = Math.max(m, Math.abs(data[j]));
      out[i] = m;
    }
    return out;
  }
  window.synth = { render, measure, peaks };
})();
