// Music room UI. Holds projects in this browser, drives the sandboxed engine,
// and reports candidates back to Python, which owns every AI limit.
(() => {
  const $ = (id) => document.getElementById(id);
  const STORE = 'strudel-ddalkkak-v1';
  const SAMPLES = 'github:tidalcycles/dirt-samples';
  const ROLE = { drums: ['드럼', '●'], bass: ['베이스', '▂'], melody: ['멜로디', '♪'], pad: ['패드', '≈'], other: ['기타', '◆'] };
  const CSP = "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob: data:; connect-src https://raw.githubusercontent.com blob: data:; media-src blob: data: https:; worker-src blob: data:;";
  const DEFAULT_TRACKS = [
    { id: 'drums', name: '드럼', role: 'drums', code: 'stack(s("bd*4").gain(.6), s("~ cp ~ cp").gain(.45), s("hh*8").gain(.25))' },
    { id: 'bass', name: '베이스', role: 'bass', code: 'note("<c2 c2 eb2 g1>*2").s("sawtooth").lpf(600).decay(.2).sustain(.3).gain(.4)' },
    { id: 'melody', name: '멜로디', role: 'melody', code: 'note("c4 eb4 g4 bb4 g4 eb4").s("triangle").gain(.3).delay(.3)' },
  ];

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
  const setIcon = (el, name) => { el.innerHTML = `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`; };
  const iconLabel = (el, name, label) => { setIcon(el, name); el.setAttribute('aria-label', label); el.title = label; };
  document.querySelectorAll('[data-icon]').forEach((el) => setIcon(el, el.dataset.icon));
  const NOTE = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
  const noteName = (m) => NOTE[((Math.round(m) % 12) + 12) % 12] + (Math.floor(Math.round(m) / 12) - 1);

  /* ---------- pure model ---------- */
  const uid = () => Math.random().toString(36).slice(2, 10);
  const snapshot = (p) => ({ bpm: p.bpm, head: p.head || '', tracks: p.tracks.map((t) => ({ ...t })) });

  function newProject(name) {
    const p = { id: uid(), name, bpm: 120, tracks: DEFAULT_TRACKS.map((t) => ({ ...t })), mix: {}, chat: [], versions: [], versionId: '' };
    addVersion(p, '기본 곡', 'user');
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
    try { const raw = localStorage.getItem(STORE); if (raw) db = JSON.parse(raw); } catch { /* starts fresh */ }
    if (!db.projects.length) { const p = newProject('첫 곡'); db = { current: p.id, projects: [p] }; }
  }
  function persist() {
    try {
      localStorage.setItem(STORE, JSON.stringify(db));
      dirty = false; $('saveState').textContent = '저장됨'; $('saveState').style.color = '';
      return true;
    } catch {
      $('saveState').textContent = '저장 실패 · 설정에서 내보내기'; $('saveState').style.color = 'var(--err)';
      return false;
    }
  }
  function touched() {
    dirty = true; $('saveState').textContent = '저장 중'; $('saveState').style.color = '';
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
      return r.ok ? { ok: r.events > 0, error: r.events > 0 ? '' : '소리 이벤트가 없어' } : { ok: false, error: r.error };
    } catch {
      createEngine('probe').catch(() => {});
      return { ok: false, error: '코드가 4초 안에 끝나지 않아 멈췄어' };
    }
  }

  let playing = false, startedAt = 0, cycles = 0, bands = null, trackEvents = {};
  addEventListener('message', (e) => {
    const m = e.data;
    if (m?.type === 'streamlit:render') { onRender(m.args || {}); return; }
    const entry = Object.entries(engines).find(([, v]) => v.frame.contentWindow === e.source);
    if (!entry) return;
    const [mode, eng] = entry;
    if (m.type === 'loaded') postTo(mode, { type: 'boot', strudel: strudelText, samples: SAMPLES });
    else if (m.type === 'ready') { if (mode === 'live') { samplesOk = m.samplesOk; soundNames = m.sounds || []; editor?.setSounds(soundNames); } eng.ready(); render(); }
    else if (m.type === 'boot-error') say('error', '음악 엔진을 시작하지 못했어: ' + m.message);
    else if (m.type === 'tick') { cycles = m.cycles; bands = m.bands; }
    else if (m.type === 'events') trackEvents = m.tracks;
    else if (m.type === 'runtime-error') say('error', '실행 오류: ' + m.message);
    else if (m.id && waiters.get(m.id)?.reply === m.type) { const w = waiters.get(m.id); waiters.delete(m.id); w.resolve(m); }
  });

  function pushMix() {
    const p = project(), mix = {};
    for (const t of p.tracks) { const s = mixOf(p, t.id); mix[t.id] = s.mute ? 0 : s.gain; }
    postTo('live', { type: 'mix', mix });
  }
  async function play() {
    await engines.live.whenReady;
    const p = project();
    pushMix();
    const r = await ask('live', { type: 'apply', code: compose(p, true) }, 'applied', 8000);
    if (!r.ok) { say('error', '재생 실패: ' + r.error); return false; }
    if (!playing) startedAt = performance.now();
    playing = true; renderPlay();
    return true;
  }
  function stop() {
    if (engines.live) postTo('live', { type: 'stop' });
    playing = false; bands = null; trackEvents = {}; renderPlay();
  }

  /* ---------- AI job handling ---------- */
  let job = null, handledSeq = '', shownMsg = {}, busyFeedback = false;
  const STAGE = { editing: '코드 수정', verifying: '실행 확인', listening: '듣는 중', signal: '신호 검사', analyzing: '결과 분석' };
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
    const trial = { bpm: c.bpm, tracks: c.tracks };
    const proved = await probe(compose(trial, true));
    if (!proved.ok) { report({ ok: false, error: proved.error }); return; }
    p.bpm = c.bpm; p.tracks = c.tracks;
    const applied = await play();
    if (!applied) { report({ ok: false, error: '재생에 실패했어' }); return; }
    addVersion(p, c.summary || '수정', 'ai');
    touched(); render();
    if (!c.listen) { report({ ok: true }); return; }
    const seconds = Math.min(16, Math.max(8, 2 * 240 / p.bpm));
    const from = (performance.now() - startedAt) / 1000;
    const span = `${mmss(from)}–${mmss(from + seconds)}`;
    localStage = `${span} 듣는 중`;
    $('listenBand').textContent = localStage; $('listenBand').hidden = false; renderProgress();
    try {
      const r = await ask('live', { type: 'capture', seconds }, 'captured', (seconds + 6) * 1000);
      if (r.error) throw new Error(r.error);
      localStage = ''; renderProgress();
      report({ ok: true, wav: wavFrom(r.pcm, r.sampleRate), span });
    } catch (e) {
      localStage = '';
      report({ ok: true, wav: '' });
    } finally { $('listenBand').hidden = true; }
  }

  function onRender(args) {
    fit();
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
  const MODEL_COST = (id) => account?.prices.models[id] ?? 2;
  // Most a request can cost: the first call, then one edit and one measurement per extra round.
  const worstCost = () => {
    if (!account) return 0;
    const per = MODEL_COST($('modelPick').value) + (account.prices.efforts[$('effortPick').value] ?? 0);
    return per * (1 + 2 * (db.autoRounds || 0) + (db.autoRounds ? 1 : 0));
  };
  function showCredits() {
    $('creditBtn').hidden = !account;
    if (!account) { $('costHint').textContent = ''; return; }
    $('creditBtn').textContent = `크레딧 ${account.credits}`;
    $('creditBtn').classList.toggle('low', account.credits < worstCost());
    $('costHint').textContent = `최대 ${worstCost()} 크레딧`;
    if (account.free && !welcomed) { welcomed = true; say('status', `무료 체험 크레딧 ${account.credits}개가 들어왔어. 쓴 만큼만 빠지고, 실패한 호출은 돌려줘.`); }
    if ($('dialog').open && $('dialog').dataset.kind === 'credits') creditBody();
  }
  const KIND = { free: '무료 체험', buy: '충전', charge: '사용', refund: '돌려받음', reversal: '환불 취소' };
  function creditBody() {
    const box = $('dialog').querySelector('.creditBody'); if (!box) return;
    box.textContent = '';
    const big = document.createElement('p'); big.className = 'creditBig'; big.textContent = `${account.credits} 크레딧`;
    const how = document.createElement('p'); how.className = 'note';
    how.textContent = '요청 한 번에 AI를 1번 부르고, 자동 개선을 켜면 회차마다 고치기와 측정이 1번씩 더해져. 부른 만큼만 빠지고 실패한 호출은 돌려줘.';
    const table = document.createElement('div'); table.className = 'creditTable';
    for (const o of $('modelPick').options) table.append(Object.assign(document.createElement('span'), { textContent: o.textContent }), Object.assign(document.createElement('b'), { textContent: `${MODEL_COST(o.value)}` }));
    table.append(Object.assign(document.createElement('span'), { textContent: '깊게 추론' }), Object.assign(document.createElement('b'), { textContent: `+${account.prices.efforts.high}` }));
    const buy = document.createElement('div'); buy.className = 'creditBuy';
    const text = document.createElement('p');
    text.textContent = `Buy Me a Coffee에서 후원하면 1달러당 ${account.per_usd} 크레딧이 들어와. 메시지 칸에 아래 코드를 적거나, 이 계정 이메일(${account.email})로 결제해 줘.`;
    const code = document.createElement('button'); code.className = 'ghost creditCode'; code.textContent = account.code; code.title = '복사';
    code.onclick = () => navigator.clipboard?.writeText(account.code).then(() => { code.textContent = '복사했어'; setTimeout(() => (code.textContent = account.code), 1200); });
    const go = document.createElement('a'); go.className = 'primaryLink'; go.href = account.buy_url; go.target = '_blank'; go.rel = 'noopener'; go.textContent = '충전하러 가기';
    buy.append(text, code, go);
    const list = document.createElement('div'); list.className = 'creditHistory';
    const head = document.createElement('h3'); head.textContent = '내역';
    list.append(head);
    if (!account.history) list.append(Object.assign(document.createElement('p'), { className: 'note', textContent: '불러오는 중…' }));
    else if (!account.history.length) list.append(Object.assign(document.createElement('p'), { className: 'note', textContent: '아직 없어.' }));
    else for (const h of account.history.slice(0, 30)) {
      const row = document.createElement('div'); row.className = 'lineItem';
      row.append(Object.assign(document.createElement('span'), { className: 'grow', textContent: `${KIND[h.kind] || h.kind} · ${String(h.at).slice(0, 16).replace('T', ' ')}` }), Object.assign(document.createElement('b'), { textContent: `${h.amount > 0 ? '+' : ''}${h.amount}` }));
      list.append(row);
    }
    const out = document.createElement('button'); out.className = 'ghost'; out.textContent = '로그아웃';
    out.onclick = () => { $('dialog').close(); send('logout', {}); };
    box.append(big, how, table, buy, list, out);
  }
  function creditDialog() {
    openDialog('크레딧'); $('dialog').dataset.kind = 'credits';
    const box = document.createElement('div'); box.className = 'creditBody'; $('dialog').append(box);
    creditBody(); $('dialog').showModal();
    send('account', {});
  }
  function fillChoices(choices) {
    const key = JSON.stringify(choices || null);
    if (key === choicesKey) return;
    choicesKey = key;
    $('modelTools').hidden = !choices;
    if (!choices) return;
    const fill = (box, list, saved, fallback) => {
      box.replaceChildren(...list.map((o) => Object.assign(document.createElement('option'), { value: o.id, textContent: o.label })));
      box.value = list.some((o) => o.id === saved) ? saved : fallback;
    };
    fill($('modelPick'), choices.models, db.model, choices.model);
    fill($('effortPick'), choices.efforts, db.effort, choices.effort);
  }

  function renderProgress() {
    const running = job?.status === 'running';
    $('progress').hidden = !running;
    if (!running) return;
    const stage = localStage || STAGE[job.stage] || job.stage;
    $('progressText').textContent = job.auto ? `${stage} · ${job.iteration}/${job.limit}회차` : stage;
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
    const d = document.createElement('div');
    d.className = 'msg ' + m.kind;
    if (m.detail) {
      const box = document.createElement('details'), head = document.createElement('summary'), body = document.createElement('div');
      head.textContent = m.text; body.textContent = m.detail;
      box.append(head, body); d.append(box);
    } else d.textContent = m.text;
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
    const make = (tag, cls) => { const e = document.createElement(tag); if (cls) e.className = cls; return e; };
    const shelf = make('div', 'shelf'), rack = make('div', 'rack'), track = make('div', 'rackTrack'), plank = make('div', 'plank'), bar = make('div', 'shelfBar');
    const label = make('span'), use = button('이 그림으로 바꾸기', () => { pickArt(p, list[at]); close(); });
    use.className = 'primary'; use.id = 'shelfUse';
    shelf.setAttribute('role', 'dialog'); shelf.setAttribute('aria-modal', 'true'); shelf.setAttribute('aria-label', '지난 그림');
    let at = Math.max(0, list.indexOf(now));
    const slot = 36, side = 24, lps = list.map((seed, i) => {
      const b = make('button', 'lp');
      b.innerHTML = `<svg viewBox="0 0 100 100" aria-hidden="true">${albumArt.make(seed).svg}</svg>`;
      b.setAttribute('aria-label', `그림 ${list.length - i}`);
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
      use.disabled = list[at] === now; use.textContent = list[at] === now ? '지금 커버' : '이 그림으로 바꾸기';
      lps[at].focus({ preventScroll: true });
    }
    function close() { removeEventListener('resize', fitShelf); shelf.remove(); $('art').focus({ preventScroll: true }); }
    const fitShelf = () => show(at);
    shelf.onkeydown = (e) => {
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowRight') { e.preventDefault(); show(at + 1); } else if (e.key === 'ArrowLeft') { e.preventDefault(); show(at - 1); }
    };
    let wheelAt = 0;
    shelf.onwheel = (e) => { e.preventDefault(); const t = performance.now(); if (t - wheelAt > 90) { wheelAt = t; show(at + Math.sign(e.deltaY || e.deltaX)); } };
    shelf.onclick = (e) => { if (e.target === shelf) close(); };
    const shut = iconButton('close', '닫기', close); shut.classList.add('ghost', 'shelfClose');
    bar.append(label, use);
    rack.append(track); shelf.append(shut, rack, plank, bar);
    $('app').after(shelf);
    addEventListener('resize', fitShelf);
    show(at);
  }
  function renderPlay() { iconLabel($('play'), playing ? 'stop' : 'play', playing ? '정지' : '재생'); }
  function renderTracks(p) {
    const box = $('tracks'); box.textContent = '';
    for (const t of p.tracks) {
      const [label, icon] = ROLE[t.role] || ROLE.other;
      const s = mixOf(p, t.id);
      const row = document.createElement('div');
      row.className = 'track' + (selected && selected !== t.id ? ' locked' : '');
      row.style.setProperty('--tc', `var(--${ROLE[t.role] ? t.role : 'other'})`);
      row.innerHTML = '<button class="pick"><span class="icon" aria-hidden="true"></span><span></span></button><div class="pattern"><canvas height="44"></canvas></div><button class="mute"></button><input type="range" min="0" max="1.5" step="0.01">';
      const [pick, , mute, gain] = row.children;
      pick.querySelector('.icon').textContent = icon;
      pick.lastChild.textContent = t.name;
      pick.title = `${t.name} (${label})`;
      pick.setAttribute('aria-pressed', String(selected === t.id));
      pick.onclick = () => { selected = selected === t.id ? null : t.id; render(); };
      iconLabel(mute, s.mute ? 'muted' : 'sound', `${t.name} ${s.mute ? '켜기' : '끄기'}`);
      mute.setAttribute('aria-pressed', String(s.mute));
      mute.onclick = () => { p.mix[t.id] = { ...s, mute: !s.mute }; pushMix(); touched(); render(); };
      gain.value = s.gain; gain.setAttribute('aria-label', `${t.name} 음량`);
      gain.disabled = !!t.raw; mute.disabled = !!t.raw;
      gain.oninput = () => { p.mix[t.id] = { ...mixOf(p, t.id), gain: +gain.value }; pushMix(); };
      gain.onchange = touched;
      row.dataset.track = t.id;
      box.append(row);
    }
    const live = p.tracks.filter((t) => !t.raw), allOff = live.length > 0 && live.every((t) => mixOf(p, t.id).mute);
    iconLabel($('allMute'), allOff ? 'muted' : 'sound', allOff ? '전체 켜기' : '전체 끄기');
    $('allMute').setAttribute('aria-pressed', String(allOff));
    $('allMute').disabled = !live.length;
  }
  $('allMute').onclick = () => {
    const p = project(), live = p.tracks.filter((t) => !t.raw), off = !live.every((t) => mixOf(p, t.id).mute);
    for (const t of live) p.mix[t.id] = { ...mixOf(p, t.id), mute: off };
    pushMix(); touched(); render();
  };
  function render() {
    const p = project(); if (!p) return;
    $('songTitle').textContent = p.name;
    const v = p.versions.find((x) => x.id === p.versionId);
    $('songMeta').textContent = (v ? v.summary : '') + (samplesOk ? '' : ' · 샘플을 불러오지 못해 합성음만 나와');
    if (document.activeElement !== $('bpm')) $('bpm').value = p.bpm;
    renderArt(p); renderTracks(p); syncEditor();
    const t = selected && p.tracks.find((x) => x.id === selected);
    $('targetChip').hidden = !t; if (t) $('targetChip').textContent = `대상: ${t.name} (나머지는 잠김)`;
    $('autoRounds').value = db.autoRounds || 0;
    $('autoHint').textContent = db.autoRounds ? `최대 ${db.autoRounds}번 더 고쳐` : '꺼짐';
    $('ask').placeholder = aiEnabled ? '바꿀 내용이나 궁금한 걸 말해 줘' : 'AI 연결 안 됨 · 재생과 믹서는 쓸 수 있어';
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
      $('bar').textContent = `${Math.max(1, Math.floor(cycles) + 1)}마디`;
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
  const dlg = $('dialog');
  function button(label, fn) { const b = document.createElement('button'); b.textContent = label; b.onclick = fn; return b; }
  function row(text, ...actions) {
    const r = document.createElement('div'); r.className = 'row';
    const t = document.createElement('div'); t.className = 'grow'; t.textContent = text; r.append(t, ...actions); return r;
  }
  function iconButton(name, label, fn) { const b = button('', fn); b.className = 'iconBtn'; iconLabel(b, name, label); return b; }
  function openDialog(title) {
    dlg.textContent = ''; dlg.dataset.kind = '';
    const x = iconButton('close', '닫기', () => dlg.close()); x.classList.add('ghost', 'dlgClose');
    dlg.append(x, heading('h2', title));
  }
  dlg.addEventListener('click', (e) => { // clicks on the backdrop land on the dialog itself, outside its box
    if (e.target !== dlg) return;
    const box = dlg.getBoundingClientRect();
    if (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom) dlg.close();
  });
  function heading(tag, text) { const h = document.createElement(tag); h.textContent = text; return h; }
  function saveFile(name, text) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' })); a.download = name; a.click();
  }
  function switchTo(id) { stop(); db.current = id; selected = null; editorDirty = false; touched(); render(); renderChat(); if (dlg.open) dlg.close(); }

  // Plays a saved version without touching the project. Closing the dialog returns to what was playing.
  let audition = null;
  function endAudition() { if (audition) iconLabel(audition.button, 'play', '듣기'); audition = null; }
  async function listenTo(v, b) {
    if (audition?.id === v.id) { const back = audition.back; endAudition(); if (back) await play(); else { stop(); pushMix(); } return; }
    const back = audition ? audition.back : playing;
    endAudition();
    await engines.live.whenReady;
    const p = project(); // an audition plays every track, whatever is muted in the mixer
    postTo('live', { type: 'mix', mix: Object.fromEntries(v.tracks.map((t) => [t.id, mixOf(p, t.id).gain])) });
    const r = await ask('live', { type: 'apply', code: compose(v, true) }, 'applied', 8000);
    if (!r.ok) { b.title = '재생 실패: ' + r.error; b.style.color = 'var(--err)'; return; }
    if (!playing) startedAt = performance.now();
    playing = true; renderPlay();
    iconLabel(b, 'stop', '정지'); audition = { id: v.id, button: b, back };
  }
  dlg.addEventListener('close', () => {
    if (!audition) return;
    const back = audition.back; audition = null;
    if (back) play(); else { stop(); pushMix(); }
  });

  function projectDialog() {
    const p = project(); openDialog('프로젝트');
    const name = document.createElement('input'); name.type = 'text'; name.value = p.name; name.setAttribute('aria-label', '곡 이름');
    name.oninput = () => { p.name = name.value.slice(0, 80) || '이름 없는 곡'; touched(); render(); };
    dlg.append(name);
    for (const x of db.projects) if (x !== p) dlg.append(row(x.name, iconButton('folder', `${x.name} 열기`, () => switchTo(x.id))));
    dlg.append(row('', iconButton('plus', '새 곡 만들기', () => { const n = newProject('새 곡'); db.projects.push(n); switchTo(n.id); }),
      iconButton('upload', '파일 불러오기', importFile), iconButton('download', '프로젝트 내보내기', () => saveFile(`${p.name}.ddalkkak.json`, JSON.stringify(p)))));
    dlg.append(heading('h3', '이전 버전'));
    for (const v of [...p.versions].reverse().slice(0, 30)) {
      const b = iconButton('restore', '복구', async () => {
        endAudition();
        p.bpm = v.bpm; p.head = v.head || ''; p.tracks = v.tracks.map((t) => ({ ...t })); addVersion(p, `복구: ${v.summary}`, 'user');
        touched(); render(); dlg.close(); if (playing) await play();
      });
      if (v.id === p.versionId) b.disabled = true;
      const hear = iconButton('play', '듣기', () => listenTo(v, hear));
      hear.disabled = job?.status === 'running'; // auto-improve captures the live output
      dlg.append(row(`${new Date(v.at).toLocaleString('ko-KR')} · ${v.summary}`, hear, b));
    }
    dlg.showModal();
  }
  function importFile() {
    const input = document.createElement('input'); input.type = 'file'; input.accept = '.json,.js,.txt,.strudel';
    input.onchange = async () => {
      const text = await input.files[0].text();
      let n;
      try {
        n = JSON.parse(text);
        if (!Array.isArray(n.tracks) || typeof n.bpm !== 'number') throw 0;
        n = { ...newProject(n.name || '불러온 곡'), bpm: n.bpm, tracks: n.tracks, mix: n.mix || {}, chat: n.chat || [], versions: n.versions || [], id: uid() };
      } catch {
        n = newProject(input.files[0].name);
        const parsed = parseSong(text, n);
        n.bpm = parsed.bpm; n.head = parsed.head; n.tracks = parsed.tracks.map(clean);
        addVersion(n, '불러온 코드', 'user');
      }
      db.projects.push(n); switchTo(n.id);
    };
    input.click();
  }
  function settingsDialog() {
    const p = project(); openDialog('설정');
    const scale = document.createElement('select'); scale.setAttribute('aria-label', '글자 크기');
    for (const v of [100, 125, 150, 200]) scale.add(new Option(v + '%', v));
    scale.value = db.scale || 100;
    scale.onchange = () => { db.scale = +scale.value; applyScale(); touched(); };
    dlg.append(row('글자 크기', scale));
    dlg.append(row(aiEnabled ? `AI 연결됨 (${engineName})` : 'AI 연결 안 됨: 서버 설정을 확인해 줘.'));
    dlg.append(heading('h3', '알아두면 좋은 기능'));
    for (const [what, how] of [
      ['앨범 커버 누르기', '새 그림으로 바뀌어.'],
      ['앨범 커버 길게 누르기', '지난 그림 책장이 열려. 하나씩 꺼내 보고 고를 수 있어.'],
      ['트랙 이름 누르기', '그 트랙만 AI가 고치도록 지정해.'],
      ['자동 개선', '막대를 끌어 최대 몇 번 더 고칠지 정해. 고칠 게 없거나 더 나아지지 않으면 그 전에 멈추고, 가장 점수가 높았던 버전을 남겨. 호출 5회, 5분, 회당 16초까지 들어.'],
      ['프로젝트 폴더', '곡 전환, 이전 버전 듣기와 복구, 파일 내보내기가 여기 있어.'],
      ['코드 버튼 (Ctrl+E)', '곡의 코드를 보고 고쳐. Ctrl+Enter로 실행해.'],
      ['저장', '바뀔 때마다 이 브라우저에 자동으로 저장돼.'],
    ]) { const r = row(''); r.textContent = ''; const b = document.createElement('b'); b.textContent = what; r.append(b, how); dlg.append(r); }
    dlg.append(heading('h3', '기타'));
    dlg.append(row('', button('게임하기', () => { stop(); persist(); dlg.close(); send('game', {}); })));
    dlg.showModal();
  }
  /* ---------- code editor ---------- */
  let soundNames = [], editor = null, editorOpen = false, editorDirty = false, editorBase = '';
  const codeNote = (text, tone) => { $('codeNote').textContent = text; $('codeNote').style.color = tone ? `var(--${tone})` : ''; $('codeReload').hidden = true; };

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const tag = document.createElement('script'); tag.src = src; tag.onload = resolve; tag.onerror = reject; document.head.append(tag);
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
    $('codeBtn').setAttribute('aria-pressed', String(open));
    $('codePanel').hidden = !open;
    if (!open) return;
    if (!editor) {
      codeNote('편집기를 불러오는 중이야.');
      try { await loadScript('vendor/editor.js'); } catch { codeNote('편집기를 불러오지 못했어.', 'err'); return; }
      editor = CodeEditor.create($('codeHost'), {
        doc: '', onRun: applyCode, onStop: stop,
        onChange: () => { editorDirty = editor.text() !== editorBase; if (editorDirty) $('codeNote').textContent = '실행 전 변경 있음'; },
      });
      editor.setSounds(soundNames);
    }
    if (!editorDirty) fillEditor();
    editor.focus();
  }
  // Probes tracks alone to find the failing one, then marks its line in the editor.
  async function explainFailure(trial, error) {
    for (const t of trial.tracks) {
      const alone = await probe(compose({ bpm: trial.bpm, tracks: [t] }, true));
      if (alone.ok) continue;
      const pos = locate(trial, t, alone.error);
      editor.showError(pos);
      const line = editor.text().slice(0, pos).split('\n').length;
      return `${t.name} ${line}번째 줄: ${alone.error}`;
    }
    return error;
  }
  async function applyCode() {
    const p = project();
    await engines.probe.whenReady;
    editor.clearError();
    const trial = parseSong(editor.text(), p);
    codeNote('확인하는 중이야.');
    const r = await probe(compose(trial, true));
    if (!r.ok) { const why = await explainFailure(trial, r.error); codeNote('실행 실패, 적용 안 함 · ' + why, 'err'); return; }
    p.bpm = trial.bpm; p.head = trial.head; p.tracks = trial.tracks.map(clean);
    selected = p.tracks.some((t) => t.id === selected) ? selected : null;
    addVersion(p, '코드 직접 수정', 'user');
    editorBase = songText(p);
    if (editor.text() !== editorBase) editor.set(editorBase); // unnamed $: becomes a named track here
    editorDirty = false;
    touched(); render();
    if (await play()) codeNote(trial.tracks[0].raw ? '적용했어. 트랙으로 나누지 못해 전체 곡 하나로 재생해.' : '적용했어.', 'ok');
  }
  function syncEditor() {
    if (!editor) return;
    const now = songText(project());
    if (now === editorBase) return;
    if (!editorDirty) { fillEditor(); return; }
    codeNote('곡이 바뀌었어. 편집 중인 내용은 그대로 뒀어.', 'warn');
    $('codeReload').hidden = false;
  }

  function applyScale() { document.documentElement.style.fontSize = (18 * (db.scale || 100) / 100) + 'px'; }

  /* ---------- controls ---------- */
  function submit() {
    const text = $('ask').value.trim(); const p = project();
    if (!text || !aiEnabled || job?.status === 'running') return;
    if (account && account.credits < MODEL_COST($('modelPick').value) + (account.prices.efforts[$('effortPick').value] ?? 0)) { say('error', '크레딧이 모자라. 위쪽 크레딧 버튼에서 충전할 수 있어.'); creditDialog(); return; }
    const history = p.chat.filter((m) => ['user', 'reply', 'change', 'heard', 'measured'].includes(m.kind)).slice(-10)
      .map((m) => ({ role: m.kind === 'user' ? 'user' : 'assistant', text: m.detail ? m.text + ' ' + m.detail : m.text }));
    say('user', text); $('ask').value = '';
    send('generate', { text, tracks: p.tracks, bpm: p.bpm, target: selected, auto: !!db.autoRounds, rounds: db.autoRounds || 0, model: $('modelPick').value, effort: $('effortPick').value, base_version: p.versionId, history });
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
  $('codeBtn').onclick = () => toggleCode();
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

  let tab = 'tracks', scoreShown = '';
  function showScore() {
    const p = project(), song = { name: p.name, bpm: p.bpm, tracks: p.tracks.map((t) => ({ ...t })) };
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
    tab = name;
    $('tabTracks').setAttribute('aria-selected', String(name === 'tracks'));
    $('tabScore').setAttribute('aria-selected', String(name === 'score'));
    $('tracks').hidden = name !== 'tracks'; $('scorePanel').hidden = name !== 'score'; $('allMute').hidden = name !== 'tracks';
    if (name === 'score' && scoreShown !== project().versionId) showScore();
  }
  $('tabTracks').onclick = () => setTab('tracks');
  $('tabScore').onclick = () => setTab('score');
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
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'e') { e.preventDefault(); toggleCode(); }
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
    for (const row of $('tracks').children) {
      const cv = row.querySelector('canvas'); if (!cv) continue;
      const q = cv.getBoundingClientRect(); if (!q.width) continue;
      const c = getComputedStyle(row).getPropertyValue('--tc'), n = 10, w = q.width / n;
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
    const veil = document.createElement('div'); veil.className = 'veil'; box.append(veil);
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
  async function showAssets(open) {
    if (morphing || open === assetOpen) return;
    morphing = true;
    const still = calm.matches;
    if (open) {
      stop();
      if (!frame.getAttribute('src')) { frame.src = 'asset_studio/index.html'; await new Promise((r) => { frame.onload = r; }); }
      frame.classList.add('waiting'); frame.hidden = false;
      await wait(60);
      const targets = await tileRects();
      if (!still && targets.length) await morph(barPieces(), targets, true);
      assetOpen = true; frame.classList.remove('waiting');
      await wait(230);
      frame.contentWindow.focus();
    } else {
      frame.contentWindow.postMessage({ type: 'asset:hide' }, '*');
      const targets = await tileRects();
      frame.classList.add('waiting');
      assetOpen = false;
      if (!still && targets.length) await morph(targets, barPieces(), false);
      frame.hidden = true;
    }
    $('morph').hidden = true; $('morph').textContent = '';
    morphing = false;
  }
  $('assetBtn').onclick = () => showAssets(true);
  addEventListener('message', (e) => { if (e.data?.type === 'asset:back') showAssets(false); });

  window.studioEditor = () => editor;

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
