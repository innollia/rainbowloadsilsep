// Reads a reference file into the few facts an AI can use: sound (length, level, brightness, tempo),
// MIDI (tempo, metre, range, the opening notes), ABC and MusicXML scores (title, key, metre, parts, opening notes).
(() => {
  const NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B'];
  const noteName = (n) => `${NAMES[n % 12]}${Math.floor(n / 12) - 1}`;
  const KEYS = { '-7': 'Cb', '-6': 'Gb', '-5': 'Db', '-4': 'Ab', '-3': 'Eb', '-2': 'Bb', '-1': 'F', 0: 'C', 1: 'G', 2: 'D', 3: 'A', 4: 'E', 5: 'B', 6: 'F#', 7: 'C#' };
  const AUDIO = /\.(wav|mp3|ogg|oga|flac|m4a|aac|webm|opus)$/i, MIDI = /\.(mid|midi)$/i, SCORE = /\.(abc|musicxml|mxl|xml)$/i;
  const kindOf = (name) => (AUDIO.test(name) ? 'audio' : MIDI.test(name) ? 'midi' : SCORE.test(name) ? 'score' : '');
  const db = (x) => (x > 0 ? 20 * Math.log10(x) : -120);

  // data: mono samples at rate.
  function audioFacts(data, rate) {
    let peak = 0, sum = 0, cross = 0;
    for (let i = 0; i < data.length; i++) { const v = data[i]; peak = Math.max(peak, Math.abs(v)); sum += v * v; if (i && (v >= 0) !== (data[i - 1] >= 0)) cross++; }
    const seconds = data.length / rate, rms = Math.sqrt(sum / Math.max(1, data.length));
    const bright = Math.round((cross / 2) / Math.max(seconds, 1e-3));
    // Tempo: autocorrelation of the rise in a 10 ms energy envelope, searched between 60 and 180 BPM.
    const hop = Math.round(rate / 100), env = [];
    for (let i = 0; i + hop <= data.length; i += hop) { let e = 0; for (let k = i; k < i + hop; k++) e += data[k] * data[k]; env.push(Math.sqrt(e / hop)); }
    const rise = env.map((v, i) => Math.max(0, v - (env[i - 1] ?? v)));
    let bpm = 0, best = 0;
    if (seconds >= 4) for (let lag = 33; lag <= 100; lag++) {
      let c = 0; for (let i = lag; i < rise.length; i++) c += rise[i] * rise[i - lag];
      if (c > best) { best = c; bpm = Math.round(6000 / lag); }
    }
    const facts = { seconds: +seconds.toFixed(2), loud_db: +db(rms).toFixed(1), peak_db: +db(peak).toFixed(1), brightness_hz: bright };
    if (bpm) facts.tempo_bpm = bpm;
    return facts;
  }

  function midiFacts(bytes) {
    const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const str = (o, n) => String.fromCharCode(...bytes.subarray(o, o + n));
    if (str(0, 4) !== 'MThd') throw new Error('not a MIDI file');
    const tracks = v.getUint16(10), division = v.getUint16(12);
    let pos = 8 + v.getUint32(4), tempo = 500000, sig = '', key = '', total = 0, low = 127, high = 0, count = 0;
    const names = [], programs = new Set(), byTrack = [];
    for (let t = 0; t < tracks && pos + 8 <= bytes.length; t++) {
      if (str(pos, 4) !== 'MTrk') break;
      const end = pos + 8 + v.getUint32(pos + 4);
      let p = pos + 8, tick = 0, status = 0;
      const notes = [];
      const vlq = () => { let n = 0, b; do { b = bytes[p++]; n = (n << 7) | (b & 0x7f); } while (b & 0x80 && p < end); return n; };
      while (p < end) {
        tick += vlq();
        let s = bytes[p];
        if (s & 0x80) { status = s; p++; } else s = status;
        if (s === 0xff) {
          const type = bytes[p++], len = vlq(), at = p; p += len;
          if (type === 0x51 && tempo === 500000) tempo = (bytes[at] << 16) | (bytes[at + 1] << 8) | bytes[at + 2];
          if (type === 0x58 && !sig) sig = `${bytes[at]}/${2 ** bytes[at + 1]}`;
          if (type === 0x59 && !key) key = `${KEYS[(bytes[at] << 24) >> 24] || ''}${bytes[at + 1] ? 'm' : ''}`;
          if (type === 0x03 && len) names.push(new TextDecoder().decode(bytes.subarray(at, at + len)).trim());
        } else if (s === 0xf0 || s === 0xf7) { p += vlq(); }
        else {
          const hi = s & 0xf0, a = bytes[p++], b = hi === 0xc0 || hi === 0xd0 ? 0 : bytes[p++];
          if (hi === 0x90 && b > 0) { count++; low = Math.min(low, a); high = Math.max(high, a); if (notes.length < 32) notes.push(a); }
          if (hi === 0xc0) programs.add(a + 1);
        }
      }
      total = Math.max(total, tick); byTrack.push(notes); pos = end;
    }
    const busiest = byTrack.reduce((x, y) => (y.length > x.length ? y : x), []);
    const facts = { tempo_bpm: Math.round(60000000 / tempo), tracks, notes: count, seconds: division & 0x8000 ? 0 : +(total / division * tempo / 1e6).toFixed(1) };
    if (sig) facts.metre = sig;
    if (key) facts.key = key;
    if (count) facts.range = `${noteName(low)}-${noteName(high)}`;
    if (names.length) facts.track_names = names.slice(0, 8);
    if (programs.size) facts.gm_programs = [...programs].slice(0, 8);
    if (busiest.length) facts.opening = busiest.map(noteName).join(' ');
    return facts;
  }

  function abcFacts(text) {
    const field = (k) => (text.match(new RegExp(`^${k}:\\s*(.+)$`, 'm')) || [])[1]?.trim();
    const body = text.split(/^K:.*$/m)[1] || '';
    const facts = { format: 'ABC' };
    for (const [k, name] of [['T', 'title'], ['M', 'metre'], ['L', 'unit'], ['Q', 'tempo'], ['K', 'key'], ['C', 'composer']]) { const x = field(k); if (x) facts[name] = x; }
    facts.notes = (body.replace(/%.*$/gm, '').replace(/"[^"]*"|![^!]*!|\[[A-Za-z]:[^\]]*\]/g, '').match(/[A-Ga-g][,']*/g) || []).length;
    const first = body.split('\n').map((l) => l.trim()).find((l) => l && !/^[A-Za-z]:/.test(l) && !l.startsWith('%'));
    if (first) facts.opening = first.slice(0, 80);
    return facts;
  }

  function xmlFacts(text) {
    const doc = new DOMParser().parseFromString(text, 'application/xml');
    if (doc.querySelector('parsererror') || !doc.querySelector('score-partwise, score-timewise')) throw new Error('not MusicXML');
    const q = (s) => doc.querySelector(s)?.textContent?.trim();
    const facts = { format: 'MusicXML' };
    const title = q('work-title') || q('movement-title'); if (title) facts.title = title;
    const parts = [...doc.querySelectorAll('part-list score-part part-name')].map((x) => x.textContent.trim()).filter(Boolean);
    if (parts.length) facts.parts = parts.slice(0, 8);
    const fifths = q('key fifths'); if (fifths != null) facts.key = `${KEYS[+fifths] || fifths}${q('key mode') === 'minor' ? 'm' : ''}`;
    const beats = q('time beats'), type = q('time beat-type'); if (beats) facts.metre = `${beats}/${type}`;
    const tempo = doc.querySelector('sound[tempo]')?.getAttribute('tempo'); if (tempo) facts.tempo_bpm = Math.round(+tempo);
    const notes = [...doc.querySelectorAll('note')];
    facts.notes = notes.filter((n) => !n.querySelector('rest')).length;
    const first = doc.querySelector('part');
    const STEP = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
    const opening = [...(first?.querySelectorAll('note') || [])].filter((n) => n.querySelector('pitch') && !n.querySelector('chord')).slice(0, 24)
      .map((n) => noteName(STEP[n.querySelector('step').textContent] + (+(n.querySelector('alter')?.textContent || 0)) + 12 * (+n.querySelector('octave').textContent + 1)));
    if (opening.length) facts.opening = opening.join(' ');
    return facts;
  }

  async function scoreFacts(name, bytes, unzip) {
    if (/\.mxl$/i.test(name)) {
      const files = await unzip(bytes);
      const container = files.find((f) => /META-INF\/container\.xml$/i.test(f.path));
      const root = container && new TextDecoder().decode(await container.bytes()).match(/full-path="([^"]+)"/)?.[1];
      const main = files.find((f) => f.path === root) || files.find((f) => /\.(xml|musicxml)$/i.test(f.path) && !/META-INF/i.test(f.path));
      if (!main) throw new Error('no score inside');
      return xmlFacts(new TextDecoder().decode(await main.bytes()));
    }
    const text = new TextDecoder().decode(bytes);
    return /\.abc$/i.test(name) || /^X:\s*\d/m.test(text) ? abcFacts(text) : xmlFacts(text);
  }

  // One line a person (and the agent) can read.
  function summary(kind, f) {
    if (!f) return '';
    const parts = [];
    if (f.title) parts.push(f.title);
    if (f.seconds) parts.push(`${f.seconds}s`);
    if (f.tempo_bpm) parts.push(`${f.tempo_bpm} BPM`);
    if (f.metre) parts.push(f.metre);
    if (f.key) parts.push(f.key);
    if (kind === 'audio') parts.push(`${f.loud_db} dB`, `~${f.brightness_hz} Hz`);
    if (f.range) parts.push(f.range);
    if (f.parts) parts.push(f.parts.join(', '));
    if (f.notes) parts.push(`${f.notes} notes`);
    return parts.join(' · ');
  }

  window.refKit = { kindOf, audioFacts, midiFacts, scoreFacts, summary, ACCEPT: '.wav,.mp3,.ogg,.oga,.flac,.m4a,.aac,.webm,.opus,.mid,.midi,.abc,.musicxml,.mxl,.xml' };
})();
