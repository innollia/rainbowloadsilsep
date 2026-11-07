// Runs inside the allow-scripts-only sandbox. Generated Strudel code executes here,
// never in the page that holds the Streamlit session.
(() => {
  const mode = document.documentElement.dataset.mode;
  const post = (m) => parent.postMessage({ ...m, engine: mode }, '*');
  const RealCtx = window.AudioContext;
  window.AudioContext = class extends RealCtx {
    constructor(o = {}) { super({ ...o, sampleRate: 48000 }); }
  };
  let tap, analyser, volume, recorder, repl, playing = false, volumeValue = 0.8;
  let lastCycle = null, capture = null, evalError = null;
  globalThis.__mix = {};

  const connect = AudioNode.prototype.connect;
  function ensureTap(ctx) {
    if (tap) return;
    tap = ctx.createGain();
    analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.75;
    analyser.minDecibels = -90;
    analyser.maxDecibels = -5;
    volume = ctx.createGain();
    volume.gain.value = volumeValue;
    connect.call(tap, analyser);
    connect.call(tap, volume);
    connect.call(volume, ctx.destination);
  }
  // Every output Strudel sends to the speakers passes through one tap, so visuals
  // and captures are the real mix, measured before the user's volume knob.
  AudioNode.prototype.connect = function (dest, ...rest) {
    if (dest instanceof AudioDestinationNode && !(this.context instanceof OfflineAudioContext)) { // reverb renders offline
      ensureTap(this.context);
      return connect.call(this, tap, ...rest);
    }
    return connect.call(this, dest, ...rest);
  };

  const WORKLET = `class R extends AudioWorkletProcessor{constructor(){super();this.on=true;this.port.onmessage=()=>{this.on=false}}
  process(i){const c=i[0];if(c&&c.length){this.port.postMessage([c[0].slice(0),(c[1]||c[0]).slice(0)])}else{this.port.postMessage(null)}return this.on}}
  registerProcessor('studio-recorder',R)`;

  async function startCapture(id, seconds) {
    const ctx = strudel.getAudioContext();
    ensureTap(ctx);
    if (!recorder) {
      await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: 'text/javascript' })));
      recorder = true;
    }
    const node = new AudioWorkletNode(ctx, 'studio-recorder', { numberOfInputs: 1, numberOfOutputs: 0, channelCount: 2, channelCountMode: 'explicit' });
    const total = Math.round(seconds * ctx.sampleRate);
    const left = new Float32Array(total), right = new Float32Array(total);
    let n = 0;
    const startCycle = repl.scheduler.now();
    const startTime = ctx.currentTime;
    capture = { id };
    node.port.onmessage = (e) => {
      const frames = e.data ? e.data[0].length : 128;
      const count = Math.min(frames, total - n);
      if (e.data) { left.set(e.data[0].subarray(0, count), n); right.set(e.data[1].subarray(0, count), n); }
      n += count;
      if (n >= total) {
        node.port.postMessage('stop'); node.port.onmessage = null; node.disconnect?.(); tap.disconnect(node);
        capture = null;
        const pcm = new Int16Array(total * 2);
        let peak = 0;
        for (let i = 0; i < total; i++) {
          const a = Math.max(-1, Math.min(1, left[i])), b = Math.max(-1, Math.min(1, right[i]));
          peak = Math.max(peak, Math.abs(a), Math.abs(b));
          pcm[i * 2] = a * 32767; pcm[i * 2 + 1] = b * 32767;
        }
        post({ type: 'captured', id, pcm: pcm.buffer, sampleRate: ctx.sampleRate, peak, startCycle, endCycle: repl.scheduler.now(), startTime, seconds });
      }
    };
    connect.call(tap, node);
  }

  function pitchOf(value) {
    let n = value.note;
    if (typeof n === 'string') { try { n = strudel.noteToMidi(n); } catch (e) { return null; } }
    return Number.isFinite(n) ? n : null;
  }
  // Log-spaced bands from 40 Hz to 16 kHz, so the display spans its width instead of piling up on the low bins.
  function logBands(raw, rate) {
    const bin = rate / 2 / raw.length, out = [];
    for (let i = 0; i < 64; i++) {
      const from = Math.max(1, Math.floor(40 * 400 ** (i / 64) / bin));
      const to = Math.max(from + 1, Math.ceil(40 * 400 ** ((i + 1) / 64) / bin));
      let peak = 0;
      for (let j = from; j < to && j < raw.length; j++) peak = Math.max(peak, raw[j]);
      out.push(peak ? Math.min(255, peak + i * 1.2) : 0); // music falls off with frequency; tilt keeps the top visible
    }
    return out;
  }

  function sendEvents(cycle) {
    const pat = repl.scheduler.pattern;
    if (!pat) return;
    const tracks = {};
    try {
      for (const h of pat.queryArc(cycle, cycle + 1)) {
        const t = h.value && h.value.trk;
        if (!t || !h.whole) continue;
        (tracks[t] ||= []).push([Number(h.whole.begin) - cycle, Number(h.whole.end) - cycle, pitchOf(h.value), h.value.gain ?? 1, h.value.s || '']);
      }
      post({ type: 'events', cycle, tracks });
    } catch (e) { post({ type: 'runtime-error', message: String(e.message || e) }); }
  }

  setInterval(() => {
    if (!repl || !playing) return;
    const cycles = repl.scheduler.now();
    const c = Math.floor(cycles);
    if (c !== lastCycle) { lastCycle = c; sendEvents(c); }
    let bands = null;
    if (analyser) { bands = new Uint8Array(analyser.frequencyBinCount); analyser.getByteFrequencyData(bands); bands = logBands(bands, analyser.context.sampleRate); }
    post({ type: 'tick', cycles, bands });
  }, 50);

  async function boot(sampleBase) {
    let samplesOk = true;
    repl = await strudel.initStrudel({
      onEvalError: (e) => { evalError = String(e.message || e); },
      prebake: async () => {
        if (mode !== 'live') return;
        try { await strudel.samples(sampleBase); } catch (e) { samplesOk = false; }
      },
    });
    // Strudel loads its effect worklets on the first mousedown, which never reaches this hidden frame.
    if (mode === 'live') { document.dispatchEvent(new MouseEvent('mousedown')); await strudel.getAudioContext().audioWorklet; }
    let sounds = [];
    try { sounds = Object.keys(strudel.soundMap.get()).filter((name) => !/^(gm_|wt_|_)/.test(name)).sort(); } catch (e) { /* no sound list */ }
    post({ type: 'ready', samplesOk, sounds });
  }

  const handlers = {
    async probe({ id, code }) {
      evalError = null;
      try {
        const pat = await repl.evaluate(code, false);
        if (evalError) throw new Error(evalError);
        if (!pat || !pat.queryArc) throw new Error(noPattern());
        const haps = pat.queryArc(0, 4);
        post({ type: 'probed', id, ok: true, events: haps.length });
      } catch (e) { post({ type: 'probed', id, ok: false, error: String(e.message || e) }); }
    },
    async score({ id, code, cycles, from = 0 }) {
      evalError = null;
      // A numeric n is a sample index or harmonic count, never a pitch; only a note name in n is one.
      const midiOf = (v) => {
        const raw = v.note ?? (typeof v.n === 'string' ? v.n : undefined);
        if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null;
        if (typeof raw === 'string') { try { return strudel.noteToMidi(raw); } catch { return null; } }
        return typeof v.freq === 'number' && v.freq > 0 ? 69 + 12 * Math.log2(v.freq / 440) : null;
      };
      try {
        const pat = await repl.evaluate(code, false);
        if (evalError) throw new Error(evalError);
        if (!pat || !pat.queryArc) throw new Error(noPattern());
        const tracks = {};
        for (const h of pat.queryArc(from, from + cycles)) {
          // Long notes come back once per cycle with the same whole; hasOnset keeps only the first piece.
          if (!h.hasOnset()) continue;
          const v = h.value && typeof h.value === 'object' ? h.value : { note: h.value };
          // A raw song is not wired with .set({trk}); its one track has the id 'song'.
          (tracks[v.trk ?? 'song'] ??= []).push({
            b: h.whole.begin.valueOf() - from, e: h.whole.end.valueOf() - from, note: midiOf(v),
            s: typeof v.s === 'string' ? v.s : null, gain: typeof v.gain === 'number' ? v.gain : 1,
          });
        }
        post({ type: 'scored', id, ok: true, tracks });
      } catch (e) { post({ type: 'scored', id, ok: false, error: String(e.message || e) }); }
    },
    async apply({ id, code }) {
      evalError = null;
      try {
        await repl.evaluate(code, true);
        if (evalError) throw new Error(evalError);
        await strudel.getAudioContext().resume();
        playing = true; lastCycle = null;
        post({ type: 'applied', id, ok: true, state: strudel.getAudioContext().state });
      } catch (e) { post({ type: 'applied', id, ok: false, error: String(e.message || e) }); }
    },
    stop() { repl.stop(); playing = false; post({ type: 'stopped' }); },
    mix({ mix }) { globalThis.__mix = mix; },
    volume({ value }) { volumeValue = value; if (volume) volume.gain.setTargetAtTime(value, volume.context.currentTime, 0.01); },
    capture({ id, seconds }) { return startCapture(id, seconds).catch((e) => post({ type: 'captured', id, error: String(e.message || e) })); },
    ping({ id }) { post({ type: 'pong', id }); },
  };

  let lang = 'en';
  const noPattern = () => (lang === 'ko' ? '패턴이 만들어지지 않았어' : 'No pattern was produced');
  addEventListener('message', async (e) => {
    if (e.source !== parent) return;
    const m = e.data;
    if (m.lang === 'en' || m.lang === 'ko') lang = m.lang;
    if (m.type === 'lang') return;
    if (m.type === 'boot') {
      const s = document.createElement('script');
      s.src = URL.createObjectURL(new Blob([m.strudel], { type: 'text/javascript' }));
      s.onload = () => boot(m.samples).catch((err) => post({ type: 'boot-error', message: String(err.message || err) }));
      s.onerror = () => post({ type: 'boot-error', message: 'strudel load failed' });
      document.head.append(s);
      return;
    }
    if (repl && handlers[m.type]) handlers[m.type](m);
  });
  post({ type: 'loaded' });
})();
