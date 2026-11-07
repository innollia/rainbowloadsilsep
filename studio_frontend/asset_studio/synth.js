// Placeholder sound for the shell, synthesised from data.js so tiles, waveforms and measurements are real signals.
(() => {
  const RATE = 22050;
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
  function noise(out, l, stretch, seed) {
    let random = seed, low = 0;
    const start = Math.floor(l.at * RATE), n = Math.floor(l.len * stretch * RATE), rise = Math.max(1, l.attack * RATE);
    for (let i = 0; i < n && start + i < out.length; i++) {
      random = (random * 16807) % 2147483647;
      const white = random / 1073741824 - 1;
      low += (white - low) * l.cutoff;
      const env = Math.min(1, i / rise) * (1 - i / n) ** (l.len > 1 ? 0.5 : 1.6);
      out[start + i] += low * l.gain * env * (1 + (1 - l.cutoff));
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

  function render(asset, change = {}) {
    const shift = change.shift ?? 1, stretch = change.stretch ?? 1, level = (change.level ?? 1) * (asset.loud ?? 1);
    const end = (l) => {
      if (l.kind === 'seq') return l.notes.length * l.step;
      if (l.kind === 'drums') return 8 * l.kick.length * l.step / 4;
      return l.at + l.len * stretch;
    };
    const seconds = Math.max(0.06, ...asset.layers.map(end));
    const length = Math.ceil((seconds + (asset.music || asset.loop ? 0 : 0.03)) * RATE);
    const groups = [];
    asset.layers.forEach((l, i) => {
      const name = l.stem || (asset.layers.length > 1 ? (l.kind === 'noise' ? '잡음 층' : `음 층 ${i + 1}`) : '본체');
      let g = groups.find((x) => x.name === name);
      if (!g) { g = { name, data: new Float32Array(length) }; groups.push(g); }
      if (l.kind === 'tone') tone(g.data, l, shift, stretch);
      else if (l.kind === 'noise') noise(g.data, l, stretch, 7919 + i * 131 + Math.round(shift * 100));
      else if (l.kind === 'seq') seq(g.data, l, shift, stretch);
      else drums(g.data, l, 104729 + i);
    });
    const mix = new Float32Array(length);
    for (const g of groups) for (let i = 0; i < length; i++) { g.data[i] *= level; mix[i] += g.data[i]; }
    return { rate: RATE, seconds: length / RATE, stems: groups, mix };
  }

  function measure(sound) {
    let peak = 0, sum = 0, lead = -1;
    const { mix, rate } = sound;
    for (let i = 0; i < mix.length; i++) {
      const v = Math.abs(mix[i]);
      peak = Math.max(peak, v); sum += v * v;
      if (lead < 0 && v > 0.003) lead = i;
    }
    const db = (v) => 20 * Math.log10(Math.max(v, 1e-6));
    return { peak: db(peak), loud: db(Math.sqrt(sum / mix.length)) - 0.7, seconds: sound.seconds, lead: Math.max(0, lead) / rate * 1000 };
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
