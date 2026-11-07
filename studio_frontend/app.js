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

  /* ---------- pure model ---------- */
  const uid = () => Math.random().toString(36).slice(2, 10);
  const snapshot = (p) => ({ bpm: p.bpm, tracks: p.tracks.map((t) => ({ ...t })) });

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

  const { compose, songText, parseSong } = window.songCode;

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
      dirty = false; $('saveState').textContent = '저장됨'; $('saveState').style.color = 'var(--ok)';
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
    try { h = Math.max(560, window.parent.innerHeight - Math.max(0, window.frameElement.getBoundingClientRect().top)); } catch { /* keeps default */ }
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
    else if (m.type === 'ready') { if (mode === 'live') samplesOk = m.samplesOk; eng.ready(); render(); }
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
    if (args.server_error && args.server_error !== lastServerError) say('error', args.server_error);
    lastServerError = args.server_error || '';
    const j = args.job;
    job = j;
    if (j) {
      shownMsg[j.id] ??= 0;
      for (const m of j.messages.slice(shownMsg[j.id])) say(m.kind, m.text);
      shownMsg[j.id] = j.messages.length;
      const key = j.candidate && `${j.id}:${j.candidate.seq}`;
      if (key && key !== handledSeq && j.status === 'running') { handledSeq = key; handleCandidate(j); }
    }
    renderProgress();
    $('send').disabled = !aiEnabled;
  }
  let aiEnabled = false, lastServerError = '', engineName = '';

  function renderProgress() {
    const running = job?.status === 'running';
    $('progress').hidden = !running;
    if (!running) return;
    const stage = localStage || STAGE[job.stage] || job.stage;
    $('progressText').textContent = job.auto ? `${stage} · 개선 ${job.iteration}/${job.limit}` : stage;
  }

  /* ---------- rendering ---------- */
  let selected = null, autoMode = false;

  function say(kind, text) {
    const p = project();
    p.chat.push({ kind, text, at: Date.now() });
    if (p.chat.length > 500) p.chat.shift();
    appendMsg({ kind, text }); touched();
  }
  function appendMsg(m) {
    const d = document.createElement('div');
    d.className = 'msg ' + m.kind; d.textContent = m.text;
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
  function renderPlay() {
    $('play').textContent = playing ? '■' : '▶';
    $('play').setAttribute('aria-label', playing ? '정지' : '재생');
  }
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
      mute.textContent = s.mute ? '켜기' : '끄기';
      mute.setAttribute('aria-pressed', String(s.mute));
      mute.setAttribute('aria-label', `${t.name} ${s.mute ? '음소거 해제' : '음소거'}`);
      mute.onclick = () => { p.mix[t.id] = { ...s, mute: !s.mute }; pushMix(); touched(); render(); };
      gain.value = s.gain; gain.setAttribute('aria-label', `${t.name} 음량`);
      gain.disabled = !!t.raw; mute.disabled = !!t.raw;
      gain.oninput = () => { p.mix[t.id] = { ...mixOf(p, t.id), gain: +gain.value }; pushMix(); };
      gain.onchange = touched;
      row.dataset.track = t.id;
      box.append(row);
    }
  }
  function render() {
    const p = project(); if (!p) return;
    $('projectBtn').textContent = p.name + ' ▾';
    $('songTitle').textContent = p.name; $('footTitle').textContent = p.name;
    const v = p.versions.find((x) => x.id === p.versionId);
    $('songMeta').textContent = `${p.bpm} BPM · 마지막 변경: ${v ? v.summary : '-'}` + (samplesOk ? '' : ' · 샘플을 불러오지 못해 합성음만 나와');
    if (document.activeElement !== $('bpm')) $('bpm').value = p.bpm;
    renderArt(p); renderTracks(p); syncEditor();
    const t = selected && p.tracks.find((x) => x.id === selected);
    $('targetChip').hidden = !t; if (t) $('targetChip').textContent = `대상: ${t.name} (나머지는 잠김)`;
    $('autoBtn').textContent = `자동 개선 ${autoMode ? 'ON · 최대 3회' : 'OFF'}`;
    $('autoBtn').setAttribute('aria-pressed', String(autoMode));
    $('ask').placeholder = aiEnabled ? '어떻게 바꿀까? 예: 드럼은 그대로 두고 베이스만 바꿔줘' : 'AI 연결 안 됨 · 재생과 믹서는 쓸 수 있어';
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
      const cv = row.querySelector('canvas'), x = cv.getContext('2d');
      if (cv.width !== cv.clientWidth) cv.width = cv.clientWidth;
      x.clearRect(0, 0, cv.width, cv.height);
      x.fillStyle = getComputedStyle(row).getPropertyValue('--tc');
      const h = cv.height - 12;
      const list = (trackEvents[row.dataset.track] || []).slice(0, 256);
      for (const [b, e] of list) x.fillRect(b * cv.width, 6, Math.max(2, (e - b) * cv.width - 2), h);
      if (playing) { x.fillStyle = '#F5F5F5'; x.fillRect(phase * cv.width, 0, 2, cv.height); }
    }
  }

  /* ---------- dialogs ---------- */
  const dlg = $('dialog');
  function button(label, fn) { const b = document.createElement('button'); b.textContent = label; b.onclick = fn; return b; }
  function row(text, ...actions) {
    const r = document.createElement('div'); r.className = 'row';
    const t = document.createElement('div'); t.className = 'grow'; t.textContent = text; r.append(t, ...actions); return r;
  }
  function heading(tag, text) { const h = document.createElement(tag); h.textContent = text; return h; }
  function saveFile(name, text) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' })); a.download = name; a.click();
  }
  function switchTo(id) { stop(); db.current = id; selected = null; editorDirty = false; touched(); render(); renderChat(); if (dlg.open) dlg.close(); }

  function projectDialog() {
    const p = project(); dlg.textContent = '';
    dlg.append(heading('h2', '프로젝트'));
    const name = document.createElement('input'); name.type = 'text'; name.value = p.name; name.setAttribute('aria-label', '곡 이름');
    name.oninput = () => { p.name = name.value.slice(0, 80) || '이름 없는 곡'; touched(); render(); };
    dlg.append(name);
    dlg.append(row('앨범 아트', button('새로 뽑기', () => { p.artSeed = Math.floor(Math.random() * 2 ** 32); touched(); render(); })));
    for (const x of db.projects) if (x !== p) dlg.append(row(x.name, button('열기', () => switchTo(x.id))));
    dlg.append(row('', button('새 곡', () => { const n = newProject('새 곡'); db.projects.push(n); switchTo(n.id); }),
      button('파일 불러오기', importFile), button('프로젝트 내보내기', () => saveFile(`${p.name}.ddalkkak.json`, JSON.stringify(p)))));
    dlg.append(heading('h3', '이전 버전'));
    for (const v of [...p.versions].reverse().slice(0, 30)) {
      const b = button('복구', async () => {
        p.bpm = v.bpm; p.tracks = v.tracks.map((t) => ({ ...t })); addVersion(p, `복구: ${v.summary}`, 'user');
        touched(); render(); dlg.close(); if (playing) await play();
      });
      if (v.id === p.versionId) b.disabled = true;
      dlg.append(row(`${new Date(v.at).toLocaleString('ko-KR')} · ${v.summary}`, b));
    }
    dlg.append(button('닫기', () => dlg.close()));
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
        n.bpm = parsed.bpm; n.tracks = parsed.tracks;
        addVersion(n, '불러온 코드', 'user');
      }
      db.projects.push(n); switchTo(n.id);
    };
    input.click();
  }
  function settingsDialog() {
    const p = project(); dlg.textContent = '';
    dlg.append(heading('h2', '설정'));
    const scale = document.createElement('select'); scale.setAttribute('aria-label', '글자 크기');
    for (const v of [100, 125, 150, 200]) scale.add(new Option(v + '%', v));
    scale.value = db.scale || 100;
    scale.onchange = () => { db.scale = +scale.value; applyScale(); touched(); };
    dlg.append(row('글자 크기', scale));
    dlg.append(row(aiEnabled ? `AI 연결됨 (${engineName})` : 'AI 연결 안 됨: 서버 설정을 확인해 줘.'));
    dlg.append(row('자동 개선 한도: 개선 3회, 재수정 2회, 호출 5회, 5분, 회당 최대 16초 듣기'));
    dlg.append(row('코드는 상단의 코드 버튼에서 보고 고칠 수 있어.'));
    dlg.append(heading('h3', '기타'));
    dlg.append(row('', button('게임하기', () => { stop(); persist(); dlg.close(); send('game', {}); }), button('닫기', () => dlg.close())));
    dlg.showModal();
  }
  /* ---------- code editor ---------- */
  let editor = null, editorOpen = false, editorDirty = false, editorBase = '';
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
    }
    if (!editorDirty) fillEditor();
    editor.focus();
  }
  // Names the failing track, since the song text and the running code differ line by line.
  async function explainFailure(trial, error) {
    for (const t of trial.tracks) {
      const alone = await probe(compose({ bpm: trial.bpm, tracks: [t] }, true));
      if (!alone.ok) return `${t.name}: ${alone.error}`;
    }
    return error;
  }
  async function applyCode() {
    const p = project();
    await engines.probe.whenReady;
    const trial = parseSong(editor.text(), p);
    codeNote('확인하는 중이야.');
    const r = await probe(compose(trial, true));
    if (!r.ok) { codeNote('실행 실패, 적용 안 함 · ' + await explainFailure(trial, r.error), 'err'); return; }
    p.bpm = trial.bpm; p.tracks = trial.tracks;
    selected = p.tracks.some((t) => t.id === selected) ? selected : null;
    addVersion(p, '코드 직접 수정', 'user');
    editorBase = songText(p);
    editorDirty = editor.text() !== editorBase;
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
    say('user', text); $('ask').value = '';
    send('generate', { text, tracks: p.tracks, bpm: p.bpm, target: selected, auto: autoMode, base_version: p.versionId });
  }
  $('askForm').onsubmit = (e) => { e.preventDefault(); submit(); };
  $('ask').onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); } };
  $('stopAi').onclick = () => send('cancel', {});
  $('play').onclick = () => (playing ? stop() : play());
  $('saveBtn').onclick = persist;
  $('autoBtn').onclick = () => { autoMode = !autoMode; render(); };
  $('projectBtn').onclick = projectDialog;
  $('settingsBtn').onclick = settingsDialog;
  $('codeBtn').onclick = () => toggleCode();
  $('codeRun').onclick = applyCode;
  $('codeExport').onclick = () => saveFile(`${project().name}.strudel.js`, songText(project()));
  $('codeImport').onclick = importFile;
  $('codeReload').onclick = fillEditor;
  $('chatFold').onclick = () => { $('app').classList.add('folded'); $('chatOpen').hidden = false; };
  $('chatOpen').onclick = () => { $('app').classList.remove('folded'); $('chatOpen').hidden = true; };
  $('volume').oninput = () => engines.live && postTo('live', { type: 'volume', value: +$('volume').value });
  $('bpm').onchange = async () => {
    const p = project(), v = Math.min(400, Math.max(20, +$('bpm').value || p.bpm));
    p.bpm = v; addVersion(p, `BPM ${v}`, 'user'); touched(); render(); if (playing) await play();
  };
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

  /* ---------- start ---------- */
  (async () => {
    load(); applyScale(); render(); renderChat();
    addEventListener('resize', fit);
    let wide = innerWidth;
    try { wide = window.parent.innerWidth; } catch { /* uses own width */ }
    if (wide < 1100) $('chatFold').click();
    try { window.parent.addEventListener('resize', fit); } catch { /* cross-origin host */ }
    requestAnimationFrame(drawLoop);
    toHost('streamlit:componentReady', { apiVersion: 1 });
    [strudelText, engineSrc] = await Promise.all(['vendor/strudel.js', 'engine.js'].map((f) => fetch(f).then((r) => r.text())));
    createEngine('live'); createEngine('probe');
  })();
  addEventListener('beforeunload', () => { if (dirty) persist(); });
})();
