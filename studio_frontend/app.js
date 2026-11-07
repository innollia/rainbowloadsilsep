// Music room UI. Holds projects in this browser, drives the sandboxed engine,
// and reports candidates back to Python, which owns every AI limit.
(() => {
  const $ = (id) => document.getElementById(id);
  const STORE = 'strudel-ddalkkak-v1';
  const SAMPLES = 'github:tidalcycles/dirt-samples';
  const ROLE = { drums: '●', bass: '▂', melody: '♪', pad: '≈', other: '◆' };
  const CSP = "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob: data:; connect-src https://raw.githubusercontent.com blob: data:; media-src blob: data: https:; worker-src blob: data:;";
  const DEFAULT_TRACKS = [
    { id: 'drums', role: 'drums', code: 'stack(s("bd*4").gain(.6), s("~ cp ~ cp").gain(.45), s("hh*8").gain(.25))' },
    { id: 'bass', role: 'bass', code: 'note("<c2 c2 eb2 g1>*2").s("sawtooth").lpf(600).decay(.2).sustain(.3).gain(.4)' },
    { id: 'melody', role: 'melody', code: 'note("c4 eb4 g4 bb4 g4 eb4").s("triangle").gain(.3).delay(.3)' },
  ];
  const dlg = $('dialog');
  const el = (tag, props = {}, ...kids) => { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; };

  /* ---------- language ---------- */
  const i18n = window.studioI18n, { t, raw } = i18n;
  let pendingLang = '';
  function applyStatic() {
    document.documentElement.lang = i18n.lang;
    document.querySelectorAll('[data-i18n]').forEach((e) => { e.textContent = t(e.dataset.i18n); });
    document.querySelectorAll('[data-i18n-aria]').forEach((e) => e.setAttribute('aria-label', t(e.dataset.i18nAria)));
    document.querySelectorAll('[data-i18n-title]').forEach((e) => { e.title = t(e.dataset.i18nTitle); });
  }
  applyStatic();

  const ICONS = {
    play: '<path d="M7 4.5v15l12-7.5z" fill="currentColor" stroke="none"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor" stroke="none"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    code: '<path d="m8 8-4 4 4 4M16 8l4 4-4 4M14 5l-4 14"/>',
    auto: '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>',
    settings: '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
    sound: '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16.5 9a4 4 0 0 1 0 6M19 6.5a8 8 0 0 1 0 11"/>',
    muted: '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="m17 9.5 5 5M22 9.5l-5 5"/>',
    restore: '<path d="M4 12a8 8 0 1 0 2.5-5.8L4 8.5"/><path d="M4 4v4.5h4.5"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    send: '<path d="M12 19V5M6 11l6-6 6 6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    download: '<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>',
    game: '<path d="M7 8h10a5 5 0 0 1 4.7 6.7l-.8 2.1a2.5 2.5 0 0 1-4.1.9L14.5 15.5h-5l-2.3 2.2a2.5 2.5 0 0 1-4.1-.9l-.8-2.1A5 5 0 0 1 7 8z"/><path d="M8 10v3.5M6.2 11.750h3.6M15.5 11h.01M17.5 13h.01"/>',
    upload: '<path d="M12 20V9M7 13l5-5 5 5M5 4h14"/>',
  };
  const setIcon = (e, name) => { e.innerHTML = `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`; };
  const iconLabel = (e, name, label) => { setIcon(e, name); e.setAttribute('aria-label', label); e.title = label; };
  document.querySelectorAll('[data-icon]').forEach((e) => setIcon(e, e.dataset.icon));
  const NOTE = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
  const noteName = (m) => NOTE[((Math.round(m) % 12) + 12) % 12] + (Math.floor(Math.round(m) / 12) - 1);

  /* ---------- pure model ---------- */
  const uid = () => Math.random().toString(36).slice(2, 10);
  const snapshot = (p) => ({ bpm: p.bpm, head: p.head || '', tracks: p.tracks.map((tr) => ({ ...tr })) });

  function newProject(name) {
    const p = { id: uid(), name, bpm: 120, tracks: DEFAULT_TRACKS.map((d) => ({ ...d, name: t('role_' + d.role) })), mix: {}, chat: [], versions: [], versionId: '' };
    addVersion(p, t('v_default'), 'user');
    return p;
  }
  function addVersion(p, summary, by) {
    const v = { id: uid(), at: Date.now(), summary, by, ...snapshot(p) };
    p.versions.push(v);
    if (p.versions.length > 100) p.versions.shift();
    p.versionId = v.id;
    return v;
  }
  const mixOf = (p, id) => p.mix[id] || { mute: false, gain: 1 };

  const { compose, songText, parseSong, locate, clean } = window.songCode;

  /* ---------- storage ---------- */
  let db = { current: '', projects: [] };
  let dirty = false;
  function load() {
    try { const stored = localStorage.getItem(STORE); if (stored) db = JSON.parse(stored); } catch { /* starts fresh */ }
    if (!db.projects.length) { const p = newProject(t('first_song')); db = { current: p.id, projects: [p] }; }
  }
  function showSave(text, color = '') { $('saveState').textContent = text; $('saveState').style.color = color; }
  function persist() {
    try {
      localStorage.setItem(STORE, JSON.stringify(db));
      dirty = false; showSave(t('saved'));
      return true;
    } catch {
      showSave(t('save_failed'), 'var(--err)');
      return false;
    }
  }
  function touched() {
    dirty = true; showSave(t('saving'));
    clearTimeout(touched.t); touched.t = setTimeout(persist, 400);
  }
  const project = () => db.projects.find((p) => p.id === db.current);

  /* ---------- streamlit bridge ---------- */
  const toHost = (type, extra) => window.parent.postMessage({ isStreamlitMessage: true, type, ...extra }, '*');
  const send = (action, payload) => toHost('streamlit:setComponentValue', { dataType: 'json', value: { event_id: uid(), action, payload } });
  function fit() {
    let h = 860;
    try { h = Math.max(560, window.parent.innerHeight - Math.max(0, window.frameElement.getBoundingClientRect().top) - 8); } catch { /* keeps default */ } // the 8px is what Streamlit adds under the frame
    if (h === fit.last) return;
    fit.last = h;
    toHost('streamlit:setFrameHeight', { height: h });
    $('app').style.height = h + 'px';
  }

  /* ---------- engines ---------- */
  const engines = {};
  const waiters = new Map();
  let strudelText = '', engineSrc = '';
  let samplesOk = true;

  function createEngine(mode) {
    engines[mode]?.frame.remove();
    const frame = document.createElement('iframe');
    frame.sandbox = 'allow-scripts';
    frame.allow = 'autoplay';
    frame.hidden = true;
    frame.title = mode;
    frame.srcdoc = `<!doctype html><html data-mode="${mode}"><head><meta http-equiv="Content-Security-Policy" content="${CSP}"></head><body><scr` + `ipt>${engineSrc.replace(/<\/script/gi, '<\\/script')}</scr` + 'ipt></body></html>';
    let ready; const whenReady = new Promise((r) => { ready = r; });
    engines[mode] = { frame, whenReady, ready };
    document.body.append(frame);
    return whenReady;
  }
  const postTo = (mode, m) => engines[mode].frame.contentWindow.postMessage(m, '*');
  const engineText = (type) => ({ type, noPattern: t('no_pattern') });
  function ask(mode, m, reply, ms) {
    return new Promise((resolve, reject) => {
      const id = uid();
      const timer = setTimeout(() => { waiters.delete(id); reject(new Error('timeout')); }, ms);
      waiters.set(id, { reply, resolve: (v) => { clearTimeout(timer); resolve(v); } });
      postTo(mode, { ...m, id });
    });
  }
  // A candidate is proven in a throwaway frame first, so a hung pattern cannot touch the live song.
  async function probe(code) {
    await engines.probe.whenReady;
    try {
      const r = await ask('probe', { type: 'probe', code }, 'probed', 4000);
      return r.ok ? { ok: r.events > 0, error: r.events > 0 ? '' : t('no_events') } : { ok: false, error: r.error };
    } catch {
      createEngine('probe').catch(() => {});
      return { ok: false, error: t('timeout4') };
    }
  }

  let playing = false, startedAt = 0, cycles = 0, bands = null, trackEvents = {};
  addEventListener('message', (e) => {
    const m = e.data;
    if (m?.type === 'streamlit:render') { onRender(m.args || {}); return; }
    const entry = Object.entries(engines).find(([, v]) => v.frame.contentWindow === e.source);
    if (!entry) return;
    const [mode, eng] = entry;
    if (m.type === 'loaded') postTo(mode, { ...engineText('boot'), strudel: strudelText, samples: SAMPLES });
    else if (m.type === 'ready') { if (mode === 'live') { samplesOk = m.samplesOk; soundNames = m.sounds || []; editor?.setSounds(soundNames); } eng.ready(); render(); }
    else if (m.type === 'boot-error') say('error', t('boot_error') + m.message);
    else if (m.type === 'tick') { cycles = m.cycles; bands = m.bands; }
    else if (m.type === 'events') trackEvents = m.tracks;
    else if (m.type === 'runtime-error') say('error', t('runtime_error') + m.message);
    else if (m.id && waiters.get(m.id)?.reply === m.type) { const w = waiters.get(m.id); waiters.delete(m.id); w.resolve(m); }
  });

  function pushMix() {
    const p = project(), mix = {};
    for (const tr of p.tracks) { const s = mixOf(p, tr.id); mix[tr.id] = s.mute ? 0 : s.gain; }
    postTo('live', { type: 'mix', mix });
  }
  async function startLive(code) {
    const r = await ask('live', { type: 'apply', code }, 'applied', 8000);
    if (r.ok) { if (!playing) startedAt = performance.now(); playing = true; renderPlay(); }
    return r;
  }
  async function play() {
    await engines.live.whenReady;
    pushMix();
    const r = await startLive(compose(project(), true));
    if (!r.ok) say('error', t('play_failed') + r.error);
    return r.ok;
  }
  function stop() {
    if (engines.live) postTo('live', { type: 'stop' });
    playing = false; bands = null; trackEvents = {}; renderPlay();
  }

  /* ---------- AI job handling ---------- */
  let job = null, handledSeq = '', shownMsg = {};
  let localStage = '';

  function wavFrom(pcm, rate) {
    const bytes = pcm.byteLength, buf = new ArrayBuffer(44 + bytes), v = new DataView(buf);
    const text = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
    text(0, 'RIFF'); v.setUint32(4, 36 + bytes, true); text(8, 'WAVEfmt '); v.setUint32(16, 16, true);
    v.setUint16(20, 1, true); v.setUint16(22, 2, true); v.setUint32(24, rate, true); v.setUint32(28, rate * 4, true);
    v.setUint16(32, 4, true); v.setUint16(34, 16, true); text(36, 'data'); v.setUint32(40, bytes, true);
    new Uint8Array(buf, 44).set(new Uint8Array(pcm));
    let s = ''; const b = new Uint8Array(buf);
    for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode.apply(null, b.subarray(i, i + 32768));
    return btoa(s);
  }
  const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

  async function handleCandidate(j) {
    const c = j.candidate, p = project();
    const report = (extra) => send('feedback', { job_id: j.id, seq: c.seq, ...extra });
    const proved = await probe(compose({ bpm: c.bpm, tracks: c.tracks }, true));
    if (!proved.ok) { report({ ok: false, error: proved.error }); return; }
    p.bpm = c.bpm; p.tracks = c.tracks;
    if (!await play()) { report({ ok: false, error: t('play_failed_short') }); return; }
    addVersion(p, c.summary || t('v_edit'), 'ai');
    touched(); render();
    if (c.listen) report(await listenBack(p));
    else report({ ok: true });
  }
  // Records a stretch of the real output so the AI can hear its own edit.
  async function listenBack(p) {
    const seconds = Math.min(16, Math.max(8, 2 * 240 / p.bpm));
    const from = (performance.now() - startedAt) / 1000;
    const span = `${mmss(from)}–${mmss(from + seconds)}`;
    localStage = t('listening_span', { span });
    $('listenBand').textContent = localStage; $('listenBand').hidden = false; renderProgress();
    try {
      const r = await ask('live', { type: 'capture', seconds }, 'captured', (seconds + 6) * 1000);
      if (r.error) throw new Error(r.error);
      localStage = ''; renderProgress();
      return { ok: true, wav: wavFrom(r.pcm, r.sampleRate), span };
    } catch {
      localStage = '';
      return { ok: true, wav: '' };
    } finally { $('listenBand').hidden = true; }
  }

  function onRender(args) {
    fit();
    if (args.lang === pendingLang) pendingLang = '';
    if (!pendingLang && i18n.pick(args.lang) && args.lang !== i18n.lang) setLang(args.lang);
    aiEnabled = !!args.ai_enabled; engineName = args.engine || '';
    fillChoices(args.choices);
    account = args.account || null; showCredits();
    if (args.server_error && args.server_error !== lastServerError) say('error', args.server_error);
    lastServerError = args.server_error || '';
    const j = args.job;
    job = j;
    if (j) {
      shownMsg[j.id] ??= 0;
      for (const m of j.messages.slice(shownMsg[j.id])) say(m.kind, m.text, m.detail);
      shownMsg[j.id] = j.messages.length;
      const key = j.candidate && `${j.id}:${j.candidate.seq}`;
      if (key && key !== handledSeq && j.status === 'running') { handledSeq = key; handleCandidate(j); }
    }
    renderProgress();
    $('send').disabled = !aiEnabled;
  }
  let aiEnabled = false, lastServerError = '', engineName = '', choicesKey = '', account = null, welcomed = false;
  const modelCost = (id) => account?.prices.models[id] ?? 2;
  const callCost = () => modelCost($('modelPick').value) + (account.prices.efforts[$('effortPick').value] ?? 0);
  // Most a request can cost: the first call, then one edit and one measurement per extra round.
  const worstCost = () => (account ? callCost() * (1 + 2 * (db.autoRounds || 0) + (db.autoRounds ? 1 : 0)) : 0);
  function showCredits() {
    $('creditBtn').hidden = !account;
    if (!account) { $('costHint').textContent = ''; return; }
    $('creditBtn').textContent = t('credits_btn', { n: account.credits });
    $('creditBtn').classList.toggle('low', account.credits < worstCost());
    $('costHint').textContent = t('cost_hint', { n: worstCost() });
    if (account.free && !welcomed) { welcomed = true; say('status', t('welcome', { n: account.credits })); }
    if (dlg.open && dlg.dataset.kind === 'credits') creditBody();
  }
  function creditBody() {
    const box = dlg.querySelector('.creditBody'); if (!box) return;
    const table = el('div', { className: 'creditTable' });
    for (const o of $('modelPick').options) table.append(el('span', { textContent: o.textContent }), el('b', { textContent: `${modelCost(o.value)}` }));
    table.append(el('span', { textContent: t('deep') }), el('b', { textContent: `+${account.prices.efforts.high}` }));
    const out = el('button', { className: 'ghost', textContent: t('logout'), onclick: () => { dlg.close(); send('logout', {}); } });
    box.replaceChildren(
      el('p', { className: 'creditBig', textContent: t('credit_big', { n: account.credits }) }),
      el('p', { className: 'note', textContent: t('credit_how') }),
      table, creditBuy(), creditHistory(), out);
  }
  function creditBuy() {
    const code = el('button', { className: 'ghost creditCode', textContent: account.code, title: t('copy') });
    code.onclick = () => navigator.clipboard?.writeText(account.code).then(() => { code.textContent = t('copied'); setTimeout(() => (code.textContent = account.code), 1200); });
    const go = el('a', { className: 'primaryLink', href: account.buy_url, target: '_blank', rel: 'noopener', textContent: t('top_up') });
    return el('div', { className: 'creditBuy' }, el('p', { textContent: t('credit_buy', { n: account.per_usd }) }), code, go);
  }
  function creditHistory() {
    const list = el('div', { className: 'creditHistory' }, el('h3', { textContent: t('history') }));
    const note = (text) => list.append(el('p', { className: 'note', textContent: text }));
    if (!account.history) note(t('loading'));
    else if (!account.history.length) note(t('none_yet'));
    else for (const h of account.history.slice(0, 30)) {
      list.append(el('div', { className: 'lineItem' },
        el('span', { className: 'grow', textContent: `${raw('kind_' + h.kind) || h.kind} · ${String(h.at).slice(0, 16).replace('T', ' ')}` }),
        el('b', { textContent: `${h.amount > 0 ? '+' : ''}${h.amount}` })));
    }
    return list;
  }
  function creditDialog() {
    openDialog(t('credits_title')); dlg.dataset.kind = 'credits';
    dlg.append(el('div', { className: 'creditBody' }));
    creditBody(); dlg.showModal();
    send('account', {});
  }
  function fillChoices(choices) {
    const key = JSON.stringify(choices || null);
    if (key === choicesKey) return;
    choicesKey = key;
    $('modelTools').hidden = !choices;
    if (!choices) return;
    const fill = (box, list, saved, fallback) => {
      box.replaceChildren(...list.map((o) => el('option', { value: o.id, textContent: o.label })));
      box.value = list.some((o) => o.id === saved) ? saved : fallback;
    };
    fill($('modelPick'), choices.models, db.model, choices.model);
    fill($('effortPick'), choices.efforts, db.effort, choices.effort);
  }

  function renderProgress() {
    const running = job?.status === 'running';
    $('progress').hidden = !running;
    if (!running) return;
    const stage = localStage || raw('stage_' + job.stage) || job.stage;
    $('progressText').textContent = job.auto ? t('round', { stage, i: job.iteration, n: job.limit }) : stage;
  }

  /* ---------- rendering ---------- */
  let selected = null;

  function say(kind, text, detail) {
    const p = project();
    p.chat.push({ kind, text, detail, at: Date.now() });
    if (p.chat.length > 500) p.chat.shift();
    appendMsg({ kind, text, detail }); touched();
  }
  function appendMsg(m) {
    const d = el('div', { className: 'msg ' + m.kind });
    if (m.detail) d.append(el('details', {}, el('summary', { textContent: m.text }), el('div', { textContent: m.detail })));
    else d.textContent = m.text;
    $('log').append(d); $('log').scrollTop = 1e9;
  }
  function seedOf(p) {
    if (p.artSeed != null) return p.artSeed;
    let h = 0; for (const c of p.id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return h;
  }
  function renderArt(p) {
    const seed = seedOf(p);
    if (renderArt.seed === seed) return;
    renderArt.seed = seed;
    $('art').innerHTML = albumArt.make(seed).svg;
  }
  function pickArt(p, seed) {
    p.artHistory ||= [seedOf(p)];
    p.artSeed = seed;
    if (!p.artHistory.includes(seed)) p.artHistory.push(seed);
    if (p.artHistory.length > 30) p.artHistory.shift();
    touched(); render();
  }
  // Past covers stand on a shelf; one comes out at a time, and pulling it out twice puts it on the song.
  function artDialog() {
    const p = project(), list = [...(p.artHistory || [seedOf(p)])].reverse(), now = seedOf(p);
    const div = (className) => el('div', { className });
    const shelf = div('shelf'), rack = div('rack'), track = div('rackTrack'), plank = div('plank'), bar = div('shelfBar');
    const label = el('span'), use = button(t('use_art'), () => { pickArt(p, list[at]); close(); });
    use.className = 'primary'; use.id = 'shelfUse';
    shelf.setAttribute('role', 'dialog'); shelf.setAttribute('aria-modal', 'true'); shelf.setAttribute('aria-label', t('past_art'));
    let at = Math.max(0, list.indexOf(now));
    const slot = 36, side = 24, lps = list.map((seed, i) => {
      const b = el('button', { className: 'lp', innerHTML: `<svg viewBox="0 0 100 100" aria-hidden="true">${albumArt.make(seed).svg}</svg>` });
      b.setAttribute('aria-label', t('art_n', { n: list.length - i }));
      b.style.animationDelay = `${Math.min(i, 24) * 28}ms`;
      b.onclick = () => { if (i === at) use.click(); else show(i); };
      track.append(b);
      return b;
    });
    function show(i) {
      at = Math.max(0, Math.min(list.length - 1, i));
      lps.forEach((b, k) => { b.classList.toggle('out', k === at); b.classList.toggle('after', k > at); b.setAttribute('aria-current', String(k === at)); });
      track.style.transform = `translateX(${rack.clientWidth / 2 - at * slot - side - 120}px)`;
      label.textContent = `${at + 1} / ${list.length}`;
      use.disabled = list[at] === now; use.textContent = list[at] === now ? t('current_cover') : t('use_art');
      lps[at].focus({ preventScroll: true });
    }
    function close() { removeEventListener('resize', fitShelf); shelf.remove(); $('art').focus({ preventScroll: true }); }
    const fitShelf = () => show(at);
    shelf.onkeydown = (e) => {
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowRight') { e.preventDefault(); show(at + 1); } else if (e.key === 'ArrowLeft') { e.preventDefault(); show(at - 1); }
    };
    let wheelAt = 0;
    shelf.onwheel = (e) => { e.preventDefault(); const stamp = performance.now(); if (stamp - wheelAt > 90) { wheelAt = stamp; show(at + Math.sign(e.deltaY || e.deltaX)); } };
    shelf.onclick = (e) => { if (e.target === shelf) close(); };
    const shut = iconButton('close', t('close'), close); shut.classList.add('ghost', 'shelfClose');
    bar.append(label, use);
    rack.append(track); shelf.append(shut, rack, plank, bar);
    $('app').after(shelf);
    addEventListener('resize', fitShelf);
    show(at);
  }
  function renderPlay() { iconLabel($('play'), playing ? 'stop' : 'play', playing ? t('stop') : t('play')); }
  function trackRow(p, tr) {
    const s = mixOf(p, tr.id);
    const row = el('div', { className: 'track' + (selected && selected !== tr.id ? ' locked' : '') });
    row.style.setProperty('--tc', `var(--${ROLE[tr.role] ? tr.role : 'other'})`);
    row.innerHTML = '<button class="pick"><span class="icon" aria-hidden="true"></span><span></span></button><div class="pattern"><canvas height="44"></canvas></div><button class="mute"></button><input type="range" min="0" max="1.5" step="0.01">';
    const [pick, , mute, gain] = row.children;
    pick.querySelector('.icon').textContent = ROLE[tr.role] || ROLE.other;
    pick.lastChild.textContent = tr.name;
    pick.title = `${tr.name} (${raw('role_' + tr.role) || raw('role_other')})`;
    pick.setAttribute('aria-pressed', String(selected === tr.id));
    pick.onclick = () => { selected = selected === tr.id ? null : tr.id; render(); };
    iconLabel(mute, s.mute ? 'muted' : 'sound', t(s.mute ? 'unmute_x' : 'mute_x', { name: tr.name }));
    mute.setAttribute('aria-pressed', String(s.mute));
    mute.onclick = () => { p.mix[tr.id] = { ...s, mute: !s.mute }; pushMix(); touched(); render(); };
    gain.value = s.gain; gain.setAttribute('aria-label', t('vol_x', { name: tr.name }));
    gain.disabled = !!tr.raw; mute.disabled = !!tr.raw;
    gain.oninput = () => { p.mix[tr.id] = { ...mixOf(p, tr.id), gain: +gain.value }; pushMix(); };
    gain.onchange = touched;
    row.dataset.track = tr.id;
    return row;
  }
  const liveTracks = (p) => p.tracks.filter((tr) => !tr.raw);
  function renderTracks(p) {
    $('tracks').replaceChildren(...p.tracks.map((tr) => trackRow(p, tr)));
    const live = liveTracks(p), allOff = live.length > 0 && live.every((tr) => mixOf(p, tr.id).mute);
    iconLabel($('allMute'), allOff ? 'muted' : 'sound', allOff ? t('all_on') : t('all_off'));
    $('allMute').setAttribute('aria-pressed', String(allOff));
    $('allMute').disabled = !live.length;
  }
  $('allMute').onclick = () => {
    const p = project(), live = liveTracks(p), off = !live.every((tr) => mixOf(p, tr.id).mute);
    for (const tr of live) p.mix[tr.id] = { ...mixOf(p, tr.id), mute: off };
    pushMix(); touched(); render();
  };
  function render() {
    const p = project(); if (!p) return;
    $('songTitle').textContent = p.name;
    const v = p.versions.find((x) => x.id === p.versionId);
    $('songMeta').textContent = (v ? v.summary : '') + (samplesOk ? '' : t('no_samples'));
    if (document.activeElement !== $('bpm')) $('bpm').value = p.bpm;
    renderArt(p); renderTracks(p); syncEditor();
    const sel = selected && p.tracks.find((x) => x.id === selected);
    $('targetChip').hidden = !sel; if (sel) $('targetChip').textContent = t('target', { name: sel.name });
    $('autoRounds').value = db.autoRounds || 0;
    $('autoHint').textContent = db.autoRounds ? t('auto_on', { n: db.autoRounds }) : t('auto_off');
    $('ask').placeholder = aiEnabled ? t('ask_ph') : t('ask_ph_off');
    if (tab === 'score' && scoreShown !== p.versionId) showScore();
  }
  function renderChat() { $('log').textContent = ''; project().chat.forEach(appendMsg); }

  const calm = matchMedia('(prefers-reduced-motion: reduce)');

  function drawLoop() {
    requestAnimationFrame(drawLoop);
    if (document.hidden) return;
    drawLoop.n = (drawLoop.n || 0) + 1;
    if (drawLoop.n % 2) return; // about 30fps
    const c = $('viz'), g = c.getContext('2d');
    if (c.width !== c.clientWidth) c.width = c.clientWidth;
    g.clearRect(0, 0, c.width, c.height);
    if (bands) {
      const w = c.width / bands.length;
      g.fillStyle = '#F5F5F5';
      bands.forEach((b, i) => { const h = b / 255 * c.height; g.fillRect(i * w, c.height - h, Math.max(1, w - 2), h); });
    }
    if (playing) {
      const s = (performance.now() - startedAt) / 1000;
      $('clock').textContent = mmss(s);
      $('bar').textContent = t('bar_n', { n: Math.max(1, Math.floor(cycles) + 1) });
    }
    albumArt.move($('art'), cycles, bands, !playing || calm.matches);
    const phase = cycles - Math.floor(cycles);
    for (const row of $('tracks').children) {
      const cv = row.querySelector('canvas'); if (!cv) continue;
      const list = (trackEvents[row.dataset.track] || []).slice(0, 256);
      const color = getComputedStyle(row).getPropertyValue('--tc');
      drawTrack(cv, list, color, playing ? phase : null);
    }
  }

  // One cycle of a track: pitch sets height, drums get a labelled lane per sound, brightness is gain.
  function drawTrack(cv, list, color, phase) {
    const ratio = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
    if (!W) return;
    if (cv.width !== Math.round(W * ratio) || cv.height !== Math.round(H * ratio)) { cv.width = Math.round(W * ratio); cv.height = Math.round(H * ratio); }
    const x = cv.getContext('2d');
    x.setTransform(ratio, 0, 0, ratio, 0, 0);
    x.clearRect(0, 0, W, H);
    x.fillStyle = 'rgba(255,255,255,.1)';
    for (let beat = 1; beat < 4; beat++) x.fillRect(beat / 4 * W, 0, 1, H);
    const pitches = list.map((e) => e[2]).filter((n) => n != null);
    const lanes = [...new Set(list.filter((e) => e[2] == null).map((e) => e[4]))];
    const rows = (pitches.length ? 1 : 0) + lanes.length || 1;
    const laneH = (H - 4) / rows, pitchTop = 2;
    const low = pitches.length ? Math.min(...pitches) : 0, high = pitches.length ? Math.max(...pitches) : 0;
    const range = Math.max(high - low, 12), base = low - (range - (high - low)) / 2;
    x.font = '600 10px "Noto Sans KR",sans-serif'; x.textBaseline = 'middle';
    for (const [b, e, pitch, gain, sound] of list) {
      const left = b * W, width = Math.max(2, (e - b) * W - 1);
      const lane = pitch == null ? lanes.indexOf(sound) + (pitches.length ? 1 : 0) : 0;
      const h = pitch == null ? Math.max(4, laneH - 2) : Math.max(5, laneH / 6);
      const y = pitch == null ? 2 + lane * laneH + (laneH - h) / 2 : pitchTop + (1 - (pitch - base) / range) * (laneH - h);
      x.globalAlpha = 0.35 + 0.65 * Math.min(1, (typeof gain === 'number' ? gain : 1) / 0.6);
      x.fillStyle = color;
      x.fillRect(left, y, width, h);
      x.globalAlpha = 1;
      if (pitch != null && width > 26) { x.fillStyle = '#F5F5F5'; x.fillText(noteName(pitch), left + 3, Math.max(7, y - 6 < 2 ? y + h + 6 : y - 6)); }
    }
    x.fillStyle = '#C4C4C4';
    lanes.forEach((name, i) => { if (rows > 1 || lanes.length) x.fillText(name, 3, 2 + (i + (pitches.length ? 1 : 0) + .5) * laneH); });
    if (phase != null) { x.fillStyle = '#F5F5F5'; x.fillRect(phase * W, 0, 2, H); }
  }

  /* ---------- dialogs ---------- */
  const button = (label, fn) => el('button', { textContent: label, onclick: fn });
  const heading = (tag, text) => el(tag, { textContent: text });
  const row = (text, ...actions) => el('div', { className: 'row' }, el('div', { className: 'grow', textContent: text }), ...actions);
  function iconButton(name, label, fn) { const b = button('', fn); b.className = 'iconBtn'; iconLabel(b, name, label); return b; }
  function openDialog(title) {
    dlg.textContent = ''; dlg.dataset.kind = '';
    const x = iconButton('close', t('close'), () => dlg.close()); x.classList.add('ghost', 'dlgClose');
    dlg.append(x, heading('h2', title));
  }
  dlg.addEventListener('click', (e) => { // clicks on the backdrop land on the dialog itself, outside its box
    if (e.target !== dlg) return;
    const box = dlg.getBoundingClientRect();
    if (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom) dlg.close();
  });
  function saveFile(name, text) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' })); a.download = name; a.click();
  }
  function switchTo(id) { stop(); db.current = id; selected = null; editorDirty = false; touched(); render(); renderChat(); if (dlg.open) dlg.close(); }

  // Plays a saved version without touching the project. Closing the dialog returns to what was playing.
  let audition = null;
  function endAudition() { if (audition) iconLabel(audition.button, 'play', t('listen')); audition = null; }
  const resume = async (back) => { if (back) await play(); else { stop(); pushMix(); } };
  async function listenTo(v, b) {
    if (audition?.id === v.id) { const back = audition.back; endAudition(); await resume(back); return; }
    const back = audition ? audition.back : playing;
    endAudition();
    await engines.live.whenReady;
    const p = project(); // an audition plays every track, whatever is muted in the mixer
    postTo('live', { type: 'mix', mix: Object.fromEntries(v.tracks.map((tr) => [tr.id, mixOf(p, tr.id).gain])) });
    const r = await startLive(compose(v, true));
    if (!r.ok) { b.title = t('play_failed') + r.error; b.style.color = 'var(--err)'; return; }
    iconLabel(b, 'stop', t('stop')); audition = { id: v.id, button: b, back };
  }
  dlg.addEventListener('close', () => {
    if (!audition) return;
    const back = audition.back; audition = null;
    resume(back);
  });

  function projectDialog() {
    const p = project(); openDialog(t('project'));
    const name = el('input', { type: 'text', value: p.name });
    name.setAttribute('aria-label', t('song_name'));
    name.oninput = () => { p.name = name.value.slice(0, 80) || t('untitled'); touched(); render(); };
    dlg.append(name);
    for (const x of db.projects) if (x !== p) dlg.append(row(x.name, iconButton('folder', t('open_x', { name: x.name }), () => switchTo(x.id))));
    dlg.append(row('', iconButton('plus', t('new_song'), () => { const n = newProject(t('new_song_name')); db.projects.push(n); switchTo(n.id); }),
      iconButton('upload', t('import_file'), importFile), iconButton('download', t('export_project'), () => saveFile(`${p.name}.ddalkkak.json`, JSON.stringify(p)))));
    dlg.append(heading('h3', t('prev_versions')));
    for (const v of [...p.versions].reverse().slice(0, 30)) dlg.append(versionRow(p, v));
    dlg.showModal();
  }
  function versionRow(p, v) {
    const back = iconButton('restore', t('restore'), async () => {
      endAudition();
      p.bpm = v.bpm; p.head = v.head || ''; p.tracks = v.tracks.map((tr) => ({ ...tr })); addVersion(p, t('restored', { s: v.summary }), 'user');
      touched(); render(); dlg.close(); if (playing) await play();
    });
    back.disabled = v.id === p.versionId;
    const hear = iconButton('play', t('listen'), () => listenTo(v, hear));
    hear.disabled = job?.status === 'running'; // auto-improve captures the live output
    return row(`${new Date(v.at).toLocaleString(i18n.lang === 'ko' ? 'ko-KR' : 'en-US')} · ${v.summary}`, hear, back);
  }
  function importFile() {
    const input = el('input', { type: 'file', accept: '.json,.js,.txt,.strudel' });
    input.onchange = async () => {
      const text = await input.files[0].text();
      let n;
      try {
        n = JSON.parse(text);
        if (!Array.isArray(n.tracks) || typeof n.bpm !== 'number') throw 0;
        n = { ...newProject(n.name || t('imported_song')), bpm: n.bpm, tracks: n.tracks, mix: n.mix || {}, chat: n.chat || [], versions: n.versions || [], id: uid() };
      } catch {
        n = newProject(input.files[0].name);
        const parsed = parseSong(text, n);
        n.bpm = parsed.bpm; n.head = parsed.head; n.tracks = parsed.tracks.map(clean);
        addVersion(n, t('imported_code'), 'user');
      }
      db.projects.push(n); switchTo(n.id);
    };
    input.click();
  }
  function settingsDialog() {
    openDialog(t('settings'));
    const scale = el('select');
    scale.setAttribute('aria-label', t('font_size'));
    for (const v of [100, 125, 150, 200]) scale.add(new Option(v + '%', v));
    scale.value = db.scale || 100;
    scale.onchange = () => { db.scale = +scale.value; applyScale(); touched(); };
    dlg.append(row(t('font_size'), scale));
    const langPick = el('select');
    langPick.setAttribute('aria-label', t('language'));
    langPick.add(new Option('English', 'en')); langPick.add(new Option('한국어', 'ko'));
    langPick.value = i18n.lang;
    langPick.onchange = () => { const next = langPick.value; pendingLang = next; setLang(next); send('lang', { lang: next }); settingsDialog(); };
    dlg.append(row(t('language'), langPick));
    dlg.append(row(aiEnabled ? t('ai_on', { e: engineName }) : t('ai_off')));
    dlg.append(heading('h3', t('tips')));
    for (const [what, how] of raw('tip_list')) dlg.append(el('div', { className: 'row' }, el('b', { textContent: what }), how));
    dlg.append(heading('h3', t('misc')));
    dlg.append(row('', button(t('play_game'), () => { stop(); persist(); dlg.close(); send('game', {}); })));
    if (!dlg.open) dlg.showModal();
  }
  /* ---------- code editor ---------- */
  let soundNames = [], editor = null, editorOpen = false, editorDirty = false, editorBase = '';
  const codeNote = (text, tone) => { $('codeNote').textContent = text; $('codeNote').style.color = tone ? `var(--${tone})` : ''; $('codeReload').hidden = true; };

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      document.head.append(el('script', { src, onload: resolve, onerror: reject }));
    });
  }
  function fillEditor() {
    editorBase = songText(project());
    editor.set(editorBase);
    editorDirty = false;
    codeNote('');
  }
  async function toggleCode(open = !editorOpen) {
    editorOpen = open;
    $('app').classList.toggle('coding', open);
    $('codePanel').hidden = !open;
    if (!open) return;
    if (!editor) {
      codeNote(t('editor_loading'));
      try { await loadScript('vendor/editor.js'); } catch { codeNote(t('editor_failed'), 'err'); return; }
      editor = CodeEditor.create($('codeHost'), {
        doc: '', onRun: applyCode, onStop: stop,
        onChange: () => { editorDirty = editor.text() !== editorBase; if (editorDirty) $('codeNote').textContent = t('unsaved_edit'); },
      });
      editor.setSounds(soundNames);
    }
    if (!editorDirty) fillEditor();
    editor.focus();
  }
  // Probes tracks alone to find the failing one, then marks its line in the editor.
  async function explainFailure(trial, error) {
    for (const tr of trial.tracks) {
      const alone = await probe(compose({ bpm: trial.bpm, tracks: [tr] }, true));
      if (alone.ok) continue;
      const pos = locate(trial, tr, alone.error);
      editor.showError(pos);
      const line = editor.text().slice(0, pos).split('\n').length;
      return t('line_err', { name: tr.name, line, err: alone.error });
    }
    return error;
  }
  async function applyCode() {
    const p = project();
    await engines.probe.whenReady;
    editor.clearError();
    const trial = parseSong(editor.text(), p);
    codeNote(t('checking'));
    const r = await probe(compose(trial, true));
    if (!r.ok) { const why = await explainFailure(trial, r.error); codeNote(t('run_failed', { why }), 'err'); return; }
    p.bpm = trial.bpm; p.head = trial.head; p.tracks = trial.tracks.map(clean);
    selected = p.tracks.some((x) => x.id === selected) ? selected : null;
    addVersion(p, t('v_code_edit'), 'user');
    editorBase = songText(p);
    if (editor.text() !== editorBase) editor.set(editorBase); // unnamed $: becomes a named track here
    editorDirty = false;
    touched(); render();
    if (await play()) codeNote(trial.tracks[0].raw ? t('applied_raw') : t('applied'), 'ok');
  }
  function syncEditor() {
    if (!editor) return;
    const now = songText(project());
    if (now === editorBase) return;
    if (!editorDirty) { fillEditor(); return; }
    codeNote(t('song_changed'), 'warn');
    $('codeReload').hidden = false;
  }

  function applyScale() { document.documentElement.style.fontSize = (18 * (db.scale || 100) / 100) + 'px'; }

  /* ---------- controls ---------- */
  function submit() {
    const text = $('ask').value.trim(); const p = project();
    if (!text || !aiEnabled || job?.status === 'running') return;
    if (account && account.credits < callCost()) { say('error', t('low_credits')); creditDialog(); return; }
    const history = p.chat.filter((m) => ['user', 'reply', 'change', 'heard', 'measured'].includes(m.kind)).slice(-10)
      .map((m) => ({ role: m.kind === 'user' ? 'user' : 'assistant', text: m.detail ? m.text + ' ' + m.detail : m.text }));
    say('user', text); $('ask').value = '';
    send('generate', { text, tracks: p.tracks, bpm: p.bpm, target: selected, auto: !!db.autoRounds, rounds: db.autoRounds || 0, model: $('modelPick').value, effort: $('effortPick').value, base_version: p.versionId, history, lang: i18n.lang });
  }
  $('askForm').onsubmit = (e) => { e.preventDefault(); submit(); };
  $('ask').onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); } };
  $('stopAi').onclick = () => send('cancel', {});
  $('play').onclick = () => (playing ? stop() : play());
  $('modelPick').onchange = (e) => { db.model = e.target.value; touched(); showCredits(); };
  $('effortPick').onchange = (e) => { db.effort = e.target.value; touched(); showCredits(); };
  $('creditBtn').onclick = creditDialog;
  $('autoRounds').oninput = (e) => { db.autoRounds = +e.target.value; touched(); render(); showCredits(); };
  $('projectBtn').onclick = projectDialog;
  $('settingsBtn').onclick = settingsDialog;
  $('codeRun').onclick = applyCode;
  $('codeExport').onclick = () => saveFile(`${project().name}.strudel.js`, songText(project()));
  $('codeImport').onclick = importFile;
  $('codeReload').onclick = fillEditor;
  const art = $('art'); let artHold = 0, artHeld = false;
  const newArt = () => pickArt(project(), Math.floor(Math.random() * 2 ** 32));
  art.onpointerdown = () => { artHeld = false; artHold = setTimeout(() => { artHeld = true; artDialog(); }, 500); };
  art.onpointerup = art.onpointerleave = art.onpointercancel = () => clearTimeout(artHold);
  art.oncontextmenu = (e) => e.preventDefault();
  art.onclick = () => { if (!artHeld) newArt(); artHeld = false; };
  art.onkeydown = (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault(); e.stopPropagation();
    if (e.shiftKey) artDialog(); else newArt();
  };

  let tab = 'tracks', lastTab = 'tracks', scoreShown = '';
  function showScore() {
    const p = project(), song = { name: p.name, bpm: p.bpm, tracks: p.tracks.map((tr) => ({ ...tr })) };
    scoreShown = p.versionId;
    window.studioScore?.mount($('scorePanel'), {
      song, onError: (text) => say('error', text),
      position: () => ({ playing: playing && !audition, cycles }),
      query: async (bars, from = 0) => {
        await engines.probe.whenReady;
        try { return await ask('probe', { type: 'score', code: compose(song, true), cycles: bars, from }, 'scored', 8000); }
        catch (e) { createEngine('probe').catch(() => {}); throw e; }
      },
    });
  }
  function setTab(name) {
    tab = name; if (name !== 'code') lastTab = name;
    for (const [id, n] of [['tabTracks', 'tracks'], ['tabScore', 'score'], ['tabCode', 'code']]) $(id).setAttribute('aria-selected', String(name === n));
    $('tracks').hidden = name !== 'tracks'; $('scorePanel').hidden = name !== 'score'; $('allMute').hidden = name !== 'tracks';
    if ((name === 'code') !== editorOpen) toggleCode(name === 'code');
    if (name === 'score' && scoreShown !== project().versionId) showScore();
  }
  $('tabTracks').onclick = () => setTab('tracks');
  $('tabScore').onclick = () => setTab('score');
  $('tabCode').onclick = () => setTab('code');
  $('volume').oninput = () => engines.live && postTo('live', { type: 'volume', value: +$('volume').value });
  let bpmWait = 0;
  function setBpm(value) { // stepping presses collapse into one version
    const p = project(), v = Math.min(400, Math.max(20, +value || p.bpm));
    p.bpm = v; $('bpm').value = v;
    clearTimeout(bpmWait);
    bpmWait = setTimeout(async () => { addVersion(p, `BPM ${v}`, 'user'); touched(); render(); if (playing) await play(); }, 350);
  }
  $('bpm').onchange = () => setBpm($('bpm').value);
  $('bpmDown').onclick = () => setBpm(+$('bpm').value - 10);
  $('bpmUp').onclick = () => setBpm(+$('bpm').value + 10);
  addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'e') { e.preventDefault(); setTab(editorOpen ? lastTab : 'code'); }
    if (e.code === 'Space' && !dlg.open && !e.target.isContentEditable && !/INPUT|TEXTAREA|SELECT|BUTTON/.test(e.target.tagName)) { e.preventDefault(); $('play').click(); }
  });
  const setWidth = (w) => { const v = Math.min(640, Math.max(320, w)); document.documentElement.style.setProperty('--chat', v + 'px'); $('divider').setAttribute('aria-valuenow', v); };
  $('divider').onpointerdown = (e) => {
    const move = (ev) => setWidth(innerWidth - ev.clientX);
    addEventListener('pointermove', move);
    addEventListener('pointerup', () => removeEventListener('pointermove', move), { once: true });
    e.preventDefault();
  };
  $('divider').onkeydown = (e) => {
    const now = $('chat').offsetWidth;
    if (e.key === 'ArrowLeft') setWidth(now + 20);
    if (e.key === 'ArrowRight') setWidth(now - 20);
  };

  /* ---------- game sound screen ---------- */
  const frame = $('assetFrame');
  let assetOpen = false, morphing = false;
  function barPieces() { // the coloured track bars become the flying pieces
    const out = [];
    for (const r of $('tracks').children) {
      const cv = r.querySelector('canvas'); if (!cv) continue;
      const q = cv.getBoundingClientRect(); if (!q.width) continue;
      const c = getComputedStyle(r).getPropertyValue('--tc'), n = 10, w = q.width / n;
      for (let i = 0; i < n; i++) out.push({ x: q.left + i * w, y: q.top + 8, w: w - 3, h: q.height - 16, c });
    }
    return out.length ? out : Array.from({ length: 24 }, (_, i) => ({ x: 40 + (i % 8) * 60, y: 300 + (i >> 3) * 40, w: 54, h: 30, c: '#C4C4C4' }));
  }
  const tileRects = () => new Promise((resolve) => {
    const done = (e) => { if (e.data?.type === 'asset:tiles') { removeEventListener('message', done); resolve(e.data.tiles); } };
    addEventListener('message', done);
    frame.contentWindow.postMessage({ type: 'asset:measure' }, '*');
    setTimeout(() => { removeEventListener('message', done); resolve([]); }, 400);
  });
  async function morph(from, to, opening) {
    const box = $('morph'); box.textContent = ''; box.hidden = false;
    const veil = el('div', { className: 'veil' }); box.append(veil);
    const count = Math.max(from.length, to.length), jobs = [];
    veil.animate([{ opacity: opening ? 0 : 1 }, { opacity: opening ? 1 : 0 }], { duration: 620, fill: 'both', easing: 'ease-in-out' });
    for (let i = 0; i < count; i++) {
      const a = from[i % from.length], b = to[i % to.length], piece = document.createElement('b');
      piece.style.cssText = `width:${a.w}px;height:${a.h}px;background:${a.c}`;
      box.append(piece);
      const place = (r, extra = '') => `translate(${r.x}px,${r.y}px) ${extra} scale(${r.w / a.w},${r.h / a.h})`;
      const mid = { x: (a.x + b.x) / 2 + (Math.random() - 0.5) * 240, y: (a.y + b.y) / 2 + (Math.random() - 0.5) * 240, w: a.w, h: a.h };
      jobs.push(piece.animate([
        { transform: place(a, 'rotate(0deg)'), background: a.c },
        { transform: place(mid, `rotate(${(Math.random() - 0.5) * 50}deg)`), offset: 0.5 },
        { transform: place(b, 'rotate(0deg)'), background: b.c },
      ], { duration: 640, delay: Math.random() * 180, fill: 'both', easing: 'cubic-bezier(.65,0,.25,1)' }).finished);
    }
    await Promise.all(jobs);
  }
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  async function openAssets(still) {
    stop();
    if (!frame.getAttribute('src')) { frame.src = `asset_studio/index.html?lang=${i18n.lang}`; await new Promise((r) => { frame.onload = r; }); }
    frame.classList.add('waiting'); frame.hidden = false;
    await wait(60);
    const targets = await tileRects();
    if (!still && targets.length) await morph(barPieces(), targets, true);
    assetOpen = true; frame.classList.remove('waiting');
    await wait(230);
    frame.contentWindow.focus();
  }
  async function closeAssets(still) {
    frame.contentWindow.postMessage({ type: 'asset:hide' }, '*');
    const targets = await tileRects();
    frame.classList.add('waiting');
    assetOpen = false;
    if (!still && targets.length) await morph(targets, barPieces(), false);
    frame.hidden = true;
  }
  async function showAssets(open) {
    if (morphing || open === assetOpen) return;
    morphing = true;
    await (open ? openAssets : closeAssets)(calm.matches);
    $('morph').hidden = true; $('morph').textContent = '';
    morphing = false;
  }
  $('assetBtn').onclick = () => showAssets(true);
  addEventListener('message', (e) => { if (e.data?.type === 'asset:back') showAssets(false); });

  window.studioEditor = () => editor;

  // Language follows Streamlit (args.lang); the header picker asks Streamlit to switch.
  function setLang(next) {
    if (!i18n.pick(next) || next === i18n.lang) return;
    i18n.lang = next;
    applyStatic(); renderPlay(); render(); renderProgress(); showCredits();
    if (dlg.open) dlg.close();
    if (tab === 'score') showScore(); else scoreShown = '';
    if (frame.getAttribute('src')) frame.contentWindow?.postMessage({ type: 'asset:lang', lang: next }, '*');
    for (const mode of Object.keys(engines)) postTo(mode, engineText('lang'));
  }
  // Until Streamlit echoes the new language back, older renders must not switch it back.

  /* ---------- start ---------- */
  (async () => {
    load(); applyScale(); render(); renderChat();
    addEventListener('resize', fit);
    try { window.parent.addEventListener('resize', fit); } catch { /* cross-origin host */ }
    requestAnimationFrame(drawLoop);
    toHost('streamlit:componentReady', { apiVersion: 1 });
    [strudelText, engineSrc] = await Promise.all(['vendor/strudel.js', 'engine.js'].map((f) => fetch(f).then((r) => r.text())));
    createEngine('live'); createEngine('probe');
  })();
  addEventListener('beforeunload', () => { if (dirty) persist(); });
})();
