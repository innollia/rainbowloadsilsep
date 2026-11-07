// Game sound asset board: front-end shell on stand-in data. No server calls; requests are simulated with timers.
(() => {
  const $ = (id) => document.getElementById(id);
  const { GAME, BRIEF, CATEGORIES, ASSETS, PROFILE, LICENSES } = window.STUDIO_DATA;
  const ICONS = {
    play: '<path d="M7 4.5v15l12-7.5z" fill="currentColor" stroke="none"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor" stroke="none"/>',
    back: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    music: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
    send: '<path d="M12 19V5M6 11l6-6 6 6"/>',
    sound: '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16.5 9a4 4 0 0 1 0 6"/>',
    muted: '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="m17 9.5 5 5M22 9.5l-5 5"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    prev: '<path d="M15 6l-6 6 6 6"/>',
    next: '<path d="m9 6 6 6-6 6"/>',
    check: '<path d="m5 13 4 4 10-11"/>',
    flag: '<path d="M6 21V4h12l-3 4 3 4H6"/>',
  };
  const setIcon = (el, name) => { el.innerHTML = `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`; };
  const iconButton = (name, label, fn, cls = 'iconBtn') => { const b = el('button', cls); setIcon(b, name); b.setAttribute('aria-label', label); b.title = label; b.onclick = fn; return b; };
  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  const STATUS = { pending: '대기', draft: '확인 필요', approved: '승인', flagged: '수정 표시', working: '수정 중', review: '검토 대기' };
  const color = (cat) => CATEGORIES.find((c) => c.id === cat)?.hue || 'var(--text3)';
  const seconds = (s) => (s < 10 ? s.toFixed(s < 1 ? 2 : 1) : s.toFixed(0)) + '초';
  const stems = ['#E8AE72', '#87B9E8', '#8CCDB2', '#C7A0E8', '#F3C978'];

  /* ---------- state ---------- */
  const assets = ASSETS.map((d) => ({ ...d, status: d.sample ? 'draft' : 'pending', versions: [], current: 0, next: null, showNext: false, chat: [], progress: 0 }));
  const byId = (id) => assets.find((a) => a.id === id);
  let stage = 'sample', filter = { cat: null, status: null }, focused = null, anchor = null, openAsset = null, detailTab = 'chat';
  const selected = new Set();

  function make(a, change = {}, note = '첫 버전') {
    const sound = synth.render(a, change);
    a.versions.push({ sound, note, change, at: new Date(), peaks: synth.peaks(sound.mix, 200), measure: synth.measure(sound) });
    a.current = a.versions.length - 1;
  }
  assets.filter((a) => a.sample).forEach((a) => make(a));
  const version = (a) => a.versions[a.current];
  const heard = (a) => (a.next && a.showNext ? a.next : version(a));

  function lint(a) {
    if (!a.versions.length) return [];
    const m = heard(a).measure, out = [];
    if (m.peak > -1) out.push({ level: 'error', rule: '최대 소리', text: `${m.peak.toFixed(1)} dB, 상한 -1.0 dB`, fix: '전체 음량을 낮춰 주세요.' });
    if (a.music && (m.loud > -16 || m.loud < -24)) out.push({ level: 'error', rule: '음악 음량', text: `${m.loud.toFixed(1)} LUFS, 범위 -24 ~ -16`, fix: '믹스 음량을 맞춰 주세요.' });
    if (!a.music && !a.loop && m.seconds > 2) out.push({ level: 'warn', rule: '길이', text: `${m.seconds.toFixed(1)}초, 권장 2초 이하`, fix: '꼬리를 줄여 주세요.' });
    if (m.lead > 50) out.push({ level: 'warn', rule: '앞 무음', text: `${m.lead.toFixed(0)} ms, 권장 50 ms 이하`, fix: '시작을 앞당겨 주세요.' });
    return out;
  }

  /* ---------- audio ---------- */
  let ctx = null, master = null, analyser = null, player = null, queue = null;
  function audio() {
    if (!ctx) {
      ctx = new AudioContext(); master = ctx.createGain(); analyser = ctx.createAnalyser();
      analyser.fftSize = 1024; analyser.smoothingTimeConstant = 0.7;
      master.connect(analyser); analyser.connect(ctx.destination);
    }
    if (ctx.state === 'suspended') ctx.resume();
    return ctx;
  }
  function stopSound() {
    if (player) { player.nodes.forEach((n) => { n.onended = null; try { n.stop(); } catch { /* already over */ } }); player = null; }
    markPlaying();
  }
  function play(a, opts = {}) {
    if (!a.versions.length) return;
    audio(); stopSound();
    const v = heard(a), sound = v.sound, nodes = [], gains = {};
    for (const s of sound.stems) {
      const buffer = ctx.createBuffer(1, s.data.length, sound.rate); buffer.copyToChannel(s.data, 0);
      const src = ctx.createBufferSource(), gain = ctx.createGain();
      src.buffer = buffer; src.loop = !!opts.loop; src.connect(gain); gain.connect(master);
      gain.gain.value = stemLevel(s.name); gains[s.name] = gain;
      nodes.push(src);
    }
    const at = ctx.currentTime + 0.01;
    nodes.forEach((n) => n.start(at, opts.from || 0));
    player = { asset: a, nodes, gains, at: at - (opts.from || 0), length: sound.seconds, loop: !!opts.loop };
    nodes[0].onended = () => { if (player?.nodes[0] === nodes[0]) { player = null; markPlaying(); opts.done?.(); } };
    markPlaying();
  }
  const position = () => (player ? ((ctx.currentTime - player.at) % player.length + player.length) % player.length : 0);
  function markPlaying() {
    document.querySelectorAll('.tile.playing').forEach((t) => t.classList.remove('playing'));
    const a = player?.asset;
    if (a) tileOf(a)?.classList.add('playing');
    $('nowPlaying').textContent = a ? a.name : '';
    setIcon($('playAll'), queue ? 'stop' : 'play');
    $('playAll').setAttribute('aria-label', queue ? '전체 듣기 멈춤' : '전체 듣기');
    document.querySelector('.dWave')?.classList.toggle('on', !!a);
  }

  /* ---------- board ---------- */
  const tileOf = (a) => document.querySelector(`.tile[data-id="${a.id}"]`);
  const visible = () => assets.filter((a) => (!filter.cat || a.cat === filter.cat) && (!filter.status || a.status === filter.status));
  const ready = (list) => list.filter((a) => a.versions.length);

  function drawPeaks(canvas, peaks, hue, cut) {
    const ratio = devicePixelRatio || 1, W = canvas.clientWidth, H = canvas.clientHeight;
    if (!W) return;
    canvas.width = W * ratio; canvas.height = H * ratio;
    const g = canvas.getContext('2d');
    g.scale(ratio, ratio);
    const n = Math.floor(W / 3), top = Math.max(1, ...peaks);
    for (let i = 0; i < n; i++) {
      const value = peaks[Math.floor(i / n * peaks.length)] / top, h = Math.max(1.5, value * (H - 8));
      g.fillStyle = hue; g.globalAlpha = 0.9;
      g.fillRect(i * 3, (H - h) / 2, 2, h);
    }
    if (cut) { g.globalAlpha = 1; g.fillStyle = '#FF9B9B'; cut(g, W, H); }
  }
  const resolved = (hue) => (hue.startsWith('var(') ? getComputedStyle(document.documentElement).getPropertyValue(hue.slice(4, -1)) : hue);

  function makeTile(a) {
    const t = el('div', 'tile'); t.dataset.id = a.id; t.dataset.status = a.status; t.tabIndex = a.versions.length || a.status === 'pending' ? 0 : -1;
    t.setAttribute('role', 'button'); t.setAttribute('aria-label', `${a.name}, ${STATUS[a.status]}`);
    t.style.setProperty('--c', color(a.cat));
    if (a.music) t.classList.add('wide');
    if (selected.has(a.id)) t.classList.add('selected');
    if (player?.asset === a) t.classList.add('playing');
    if (a.versions.length) t.append(el('canvas'));
    if (a.status === 'working') { const bar = el('div', 'bar'); bar.style.setProperty('--p', a.progress); t.append(bar); }
    if (a.status === 'review') {
      const row = el('div', 'ab');
      const old = el('button', '', '이전'), fresh = el('button', '', '새 버전');
      const pick = (next) => (e) => { e.stopPropagation(); a.showNext = next; drawTile(a); play(a); old.setAttribute('aria-pressed', String(!next)); fresh.setAttribute('aria-pressed', String(next)); };
      old.onclick = pick(false); fresh.onclick = pick(true);
      old.setAttribute('aria-pressed', String(!a.showNext)); fresh.setAttribute('aria-pressed', String(a.showNext));
      const keep = iconButton('check', '채택', (e) => { e.stopPropagation(); settle(a, true); }, 'keep');
      const drop = iconButton('close', '버림', (e) => { e.stopPropagation(); settle(a, false); }, 'drop');
      row.append(old, fresh, keep, drop); t.append(row);
    }
    const meta = el('div', 'meta'), name = el('span', 'name', a.name), sub = el('div', 'sub');
    const v = a.versions.length ? heard(a) : null;
    sub.append(el('span', '', v ? seconds(v.measure.seconds) : STATUS[a.status]), el('span', '', a.status === 'working' ? '수정 중' : v && a.versions.length > 1 ? `v${a.current + 1}` : ''));
    meta.append(name, sub); t.append(meta, el('i', 'state'));
    const problems = lint(a);
    if (problems.length) { const worst = problems.some((p) => p.level === 'error'); t.append(el('span', 'lintMark' + (worst ? '' : ' warn'), String(problems.length))); }
    t.addEventListener('pointerenter', () => hoverStart(a));
    t.addEventListener('pointerleave', hoverEnd);
    t.addEventListener('click', (e) => clickTile(a, e));
    t.addEventListener('dblclick', () => a.versions.length && openDetail(a));
    t.addEventListener('focus', () => { focused = a.id; syncDock(); });
    return t;
  }
  const drawTile = (a) => { const c = tileOf(a)?.querySelector('canvas'); if (c) drawPeaks(c, heard(a).peaks, resolved(color(a.cat))); };

  function renderBoard() {
    const box = $('board'), top = box.scrollTop; box.textContent = '';
    box.append(...banner());
    for (const c of CATEGORIES) {
      const list = visible().filter((a) => a.cat === c.id);
      if (!list.length) continue;
      const group = el('div', 'group'), h = el('h2'), dot = el('i');
      group.style.setProperty('--c', c.hue);
      h.append(dot, c.name, el('span', '', String(list.length)));
      const grid = el('div', 'grid');
      grid.append(...list.map(makeTile));
      group.append(h, grid); box.append(group);
    }
    box.scrollTop = top;
    assets.filter((a) => a.versions.length).forEach(drawTile);
    renderSide(); renderHeader(); syncDock();
  }
  function banner() {
    if (stage !== 'sample') return [];
    const samples = assets.filter((a) => a.sample), done = samples.filter((a) => a.status === 'approved').length, rest = assets.filter((a) => a.status === 'pending').length;
    const box = el('div', 'note'); box.style.cssText = 'display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:6px';
    const text = el('span', '', done === samples.length ? `샘플 ${samples.length}개를 모두 승인했어요. 이 스타일로 나머지 ${rest}개를 만듭니다.` : `샘플 ${samples.length}개 중 ${done}개 승인. 들어 보고 승인하면 나머지 ${rest}개를 같은 스타일로 만듭니다.`);
    text.style.flex = '1';
    const all = el('button', 'ghost', '샘플 모두 승인'); all.onclick = () => { samples.forEach((a) => { if (a.status === 'draft') a.status = 'approved'; }); renderBoard(); };
    const go = el('button', 'primary', '나머지 만들기'); go.id = 'expandBtn'; go.disabled = done !== samples.length; go.onclick = expand;
    box.append(text, all, go);
    return [box];
  }
  function renderSide() {
    const side = $('side'); side.textContent = '';
    const item = (label, count, active, fn, hue) => {
      const b = el('button'); b.setAttribute('aria-pressed', String(active)); b.onclick = fn;
      if (hue) { const d = el('i', 'dot'); d.style.setProperty('--c', hue); b.append(d); }
      b.append(el('span', 'name', label), el('span', 'n', String(count)));
      return b;
    };
    side.append(el('h2', '', '분류'), item('전체', assets.length, !filter.cat, () => { filter.cat = null; renderBoard(); }));
    for (const c of CATEGORIES) side.append(item(c.name, assets.filter((a) => a.cat === c.id).length, filter.cat === c.id, () => { filter.cat = filter.cat === c.id ? null : c.id; renderBoard(); }, c.hue));
    side.append(el('h2', '', '상태'));
    for (const [id, label] of Object.entries(STATUS)) {
      const n = assets.filter((a) => a.status === id).length;
      if (n) side.append(item(label, n, filter.status === id, () => { filter.status = filter.status === id ? null : id; renderBoard(); }));
    }
  }
  function renderHeader() {
    $('gameName').textContent = GAME + ' ▾';
    const order = [['brief', '설명'], ['sample', '샘플 확인'], ['expand', '확장'], ['export', '내보내기']], at = order.findIndex(([id]) => id === stage);
    $('stages').textContent = '';
    order.forEach(([, label], i) => { const li = el('li', i < at ? 'done' : '', label); if (i === at) li.setAttribute('aria-current', 'step'); $('stages').append(li); });
    const approved = assets.filter((a) => a.status === 'approved').length;
    $('counts').textContent = `전체 ${assets.length} · 승인 ${approved}`;
    const all = ready(assets).flatMap(lint), errors = all.filter((p) => p.level === 'error').length;
    $('lintCount').hidden = !all.length; $('lintCount').textContent = String(all.length); $('lintCount').className = 'badge' + (errors ? '' : ' warn');
    const waiting = assets.filter((a) => a.status === 'review').length;
    $('review').hidden = !waiting || !!openAsset; $('reviewText').textContent = `검토 ${waiting}개`;
  }
  function syncDock() {
    const count = selected.size, target = focused && byId(focused);
    $('selCount').hidden = !count; $('selCount').textContent = `${count}개 선택`;
    $('ask').placeholder = count ? `선택한 ${count}개에 보낼 요청` : target?.versions.length ? `${target.name}에 보낼 요청` : '에셋을 골라 요청을 보내세요';
    $('send').disabled = !count && !target?.versions.length;
  }

  /* ---------- pointer ---------- */
  let hoverTimer = 0, lassoing = false;
  function hoverStart(a) {
    if (lassoing || !$('hoverPlay').checked || !a.versions.length || queue) return;
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => { if (player?.asset !== a) play(a); }, 140);
  }
  function hoverEnd() { clearTimeout(hoverTimer); }
  function clickTile(a, e) {
    if (a.status === 'pending') return;
    if (e.ctrlKey || e.metaKey) { toggle(a); anchor = a.id; }
    else if (e.shiftKey && anchor) {
      const list = visible(), from = list.indexOf(byId(anchor)), to = list.indexOf(a);
      list.slice(Math.min(from, to), Math.max(from, to) + 1).filter((x) => x.versions.length).forEach((x) => selected.add(x.id));
      refreshSelection();
    } else {
      anchor = a.id; focused = a.id;
      if (selected.size) { selected.clear(); refreshSelection(); }
      play(a);
    }
    syncDock();
  }
  function toggle(a) { if (selected.has(a.id)) selected.delete(a.id); else selected.add(a.id); refreshSelection(); }
  function refreshSelection() { document.querySelectorAll('.tile').forEach((t) => t.classList.toggle('selected', selected.has(t.dataset.id))); syncDock(); }

  $('board').addEventListener('pointerdown', (e) => {
    if (e.button || e.target.closest('.tile, button')) return;
    const x0 = e.clientX, y0 = e.clientY, base = new Set(e.ctrlKey ? selected : []), box = $('lasso');
    lassoing = true;
    const move = (ev) => {
      const l = Math.min(x0, ev.clientX), t = Math.min(y0, ev.clientY), r = Math.max(x0, ev.clientX), b = Math.max(y0, ev.clientY);
      box.hidden = false; box.style.cssText = `left:${l}px;top:${t}px;width:${r - l}px;height:${b - t}px`;
      selected.clear(); base.forEach((id) => selected.add(id));
      document.querySelectorAll('.tile').forEach((tile) => {
        const q = tile.getBoundingClientRect();
        if (q.left < r && q.right > l && q.top < b && q.bottom > t && byId(tile.dataset.id).versions.length) selected.add(tile.dataset.id);
      });
      refreshSelection();
    };
    const up = () => { lassoing = false; box.hidden = true; removeEventListener('pointermove', move); removeEventListener('pointerup', up); };
    addEventListener('pointermove', move); addEventListener('pointerup', up);
  });

  /* ---------- keyboard ---------- */
  function neighbour(key) {
    const tiles = [...document.querySelectorAll('.tile')], now = tileOf(byId(focused) || {}) || tiles[0];
    if (!now) return null;
    const at = tiles.indexOf(now);
    if (key === 'ArrowRight') return tiles[at + 1];
    if (key === 'ArrowLeft') return tiles[at - 1];
    const q = now.getBoundingClientRect(), mid = q.left + q.width / 2;
    const rows = tiles.filter((t) => { const r = t.getBoundingClientRect(); return key === 'ArrowDown' ? r.top > q.bottom - 4 : r.bottom < q.top + 4; });
    const line = key === 'ArrowDown' ? Math.min(...rows.map((t) => t.getBoundingClientRect().top)) : Math.max(...rows.map((t) => t.getBoundingClientRect().top));
    return rows.filter((t) => t.getBoundingClientRect().top === line).sort((a, b) => Math.abs(a.getBoundingClientRect().left + a.offsetWidth / 2 - mid) - Math.abs(b.getBoundingClientRect().left + b.offsetWidth / 2 - mid))[0];
  }
  addEventListener('keydown', (e) => {
    if ($('dialog').open || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
    if (openAsset) {
      if (e.key === 'Escape') closeDetail();
      if (e.code === 'Space') { e.preventDefault(); toggleDetailPlay(); }
      if (e.key === 'ArrowLeft') step(-1);
      if (e.key === 'ArrowRight') step(1);
      return;
    }
    const a = focused && byId(focused);
    if (e.key.startsWith('Arrow')) {
      e.preventDefault();
      const next = neighbour(e.key);
      if (next) { next.focus(); next.scrollIntoView({ block: 'nearest' }); const n = byId(next.dataset.id); focused = n.id; if (n.versions.length) play(n); else stopSound(); }
    } else if (e.code === 'Space' && a) { e.preventDefault(); if (player?.asset === a) stopSound(); else play(a); }
    else if (e.key === 'Enter' && a?.versions.length) openDetail(a);
    else if (e.key.toLowerCase() === 'a' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); ready(visible()).forEach((x) => selected.add(x.id)); refreshSelection(); }
    else if (e.key.toLowerCase() === 'a' && a) setStatus(a, 'approved');
    else if (e.key.toLowerCase() === 'r' && a) setStatus(a, 'flagged');
    else if (e.key === 'Escape') { selected.clear(); refreshSelection(); }
  });
  function setStatus(a, status) { if (a.status === 'draft' || a.status === 'approved' || a.status === 'flagged') { a.status = a.status === status ? 'draft' : status; const id = a.id; renderBoard(); tileOf(byId(id))?.focus(); } }

  /* ---------- simulated work ---------- */
  function changeFrom(text) {
    const has = (...w) => w.some((x) => text.includes(x));
    return { shift: has('높', '밝', '가볍', '귀엽') ? 1.25 : has('낮', '묵직', '무겁', '어둡') ? 0.8 : 1.1, stretch: has('짧') ? 0.7 : has('길') ? 1.4 : 0.95, level: has('작', '조용', '낮춰') ? 0.6 : has('크', '세게') ? 1.2 : 0.85 };
  }
  function request(list, text) {
    const change = changeFrom(text);
    list.forEach((a, i) => {
      a.status = 'working'; a.progress = 0;
      a.chat.push({ me: true, text });
      const total = 1100 + i * 420 + Math.random() * 900, begun = performance.now();
      const tick = () => {
        a.progress = Math.min(1, (performance.now() - begun) / total);
        tileOf(a)?.querySelector('.bar')?.style.setProperty('--p', a.progress);
        if (a.progress < 1) { setTimeout(tick, 120); return; }
        const sound = synth.render(a, change);
        a.next = { sound, note: text, change, at: new Date(), peaks: synth.peaks(sound.mix, 200), measure: synth.measure(sound) };
        a.showNext = true; a.status = 'review';
        a.chat.push({ text: '새 버전을 만들었어요. 이전과 비교해 보세요.' });
        renderOpen(a);
      };
      tick();
    });
    selected.clear(); renderOpen();
  }
  function renderOpen(a) { if (openAsset && (!a || a === openAsset)) renderDetail(); else if (!openAsset) renderBoard(); else renderHeader(); }
  function settle(a, keep) {
    if (keep && a.next) { a.versions.push(a.next); a.current = a.versions.length - 1; }
    a.next = null; a.showNext = false; a.status = keep ? 'approved' : 'draft';
    if (player?.asset === a) stopSound();
    renderOpen();
  }
  function expand() {
    stage = 'expand'; stopSound();
    const rest = assets.filter((a) => a.status === 'pending');
    toast(`샘플 스타일로 ${rest.length}개를 만듭니다`);
    rest.forEach((a, i) => setTimeout(() => {
      make(a); a.status = 'draft';
      const t = tileOf(a);
      if (t && !openAsset) { const fresh = makeTile(a); fresh.classList.add('arrive'); t.replaceWith(fresh); drawTile(a); renderSide(); renderHeader(); }
      if (i === rest.length - 1) renderOpen();
    }, 200 + i * 110));
    renderBoard();
  }

  /* ---------- dock ---------- */
  $('playAll').onclick = () => {
    if (queue) { queue = null; stopSound(); return; }
    const list = ready(visible());
    if (!list.length) return;
    queue = { list, at: 0 };
    const next = () => {
      if (!queue || queue.at >= queue.list.length) { queue = null; markPlaying(); return; }
      const a = queue.list[queue.at++];
      tileOf(a)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      play(a, { done: () => setTimeout(next, 260) });
      if (a.music || a.loop) { const mine = a; setTimeout(() => { if (queue && player?.asset === mine) { stopSound(); next(); } }, 3500); }
    };
    next();
  };
  $('askForm').onsubmit = (e) => {
    e.preventDefault();
    const text = $('ask').value.trim(); if (!text) return;
    const list = selected.size ? [...selected].map(byId) : focused ? [byId(focused)] : [];
    const usable = list.filter((a) => a?.versions.length && a.status !== 'working');
    if (!usable.length) return;
    $('ask').value = ''; request(usable, text);
  };
  $('acceptAll').onclick = () => { assets.filter((a) => a.status === 'review').forEach((a) => settle(a, true)); };
  $('rejectAll').onclick = () => { assets.filter((a) => a.status === 'review').forEach((a) => settle(a, false)); };

  /* ---------- detail ---------- */
  let stemState = {}, liveRaf = 0;
  const stemLevel = (name) => {
    const list = Object.values(stemState), anySolo = list.some((s) => s.solo), s = stemState[name] || { gain: 1 };
    return s.mute || (anySolo && !s.solo) ? 0 : s.gain;
  };
  const applyStems = () => { if (player) for (const [name, g] of Object.entries(player.gains)) g.gain.value = stemLevel(name); };
  const transition = (fn) => (document.startViewTransition && !matchMedia('(prefers-reduced-motion: reduce)').matches ? document.startViewTransition(fn) : fn());

  function showDetail(on) {
    $('boardView').hidden = on; $('detailView').hidden = !on; $('dock').hidden = on;
  }
  function openDetail(a) {
    const tile = tileOf(a);
    if (tile) tile.style.viewTransitionName = 'zoom';
    transition(() => {
      if (tile) tile.style.viewTransitionName = '';
      stopSound(); openAsset = a; stemState = {}; detailTab = 'chat'; showDetail(true); renderDetail();
    });
  }
  function closeDetail() {
    const a = openAsset; stopSound();
    document.querySelector('.dWave')?.style.setProperty('view-transition-name', 'zoom');
    transition(() => {
      openAsset = null; showDetail(false); renderBoard();
      const t = tileOf(a); if (t) { t.style.viewTransitionName = 'zoom'; t.focus(); setTimeout(() => { t.style.viewTransitionName = ''; }, 400); }
    });
  }
  function step(by) {
    const list = ready(visible()), at = list.indexOf(openAsset), next = list[(at + by + list.length) % list.length];
    if (next) { stopSound(); openAsset = next; focused = next.id; stemState = {}; renderDetail(); }
  }
  function toggleDetailPlay() { if (player?.asset === openAsset) stopSound(); else play(openAsset, { loop: !!(openAsset.loop || openAsset.music) }); renderPlayButton(); }
  function renderPlayButton() { const b = $('dPlay'); if (b) { setIcon(b, player?.asset === openAsset ? 'stop' : 'play'); b.setAttribute('aria-label', player ? '정지' : '재생'); } }

  function renderDetail() {
    const a = openAsset, v = heard(a), m = v.measure, box = $('detailView'), problems = lint(a);
    box.textContent = '';
    const main = el('div', 'dMain'), head = el('div', 'dHead');
    const title = el('div'); title.style.minWidth = '0'; title.append(el('h1', '', a.name), el('div', 'file', `${a.id}.wav`));
    const play = iconButton('play', '재생', toggleDetailPlay); play.id = 'dPlay'; play.classList.add('primary');
    const approve = el('button', a.status === 'approved' ? '' : 'primary', a.status === 'approved' ? '승인됨' : '승인');
    approve.onclick = () => { a.status = a.status === 'approved' ? 'draft' : 'approved'; renderDetail(); };
    approve.disabled = a.status === 'working' || a.status === 'review';
    head.append(iconButton('back', '보드로', closeDetail, 'ghost iconBtn'), title, el('span', 'spacer'), iconButton('prev', '이전 에셋', () => step(-1), 'ghost iconBtn'), iconButton('next', '다음 에셋', () => step(1), 'ghost iconBtn'), play, approve);
    const facts = el('p', 'dFacts');
    for (const f of [seconds(m.seconds), `최대 ${m.peak.toFixed(1)} dB`, `음량 ${m.loud.toFixed(1)} LUFS`, a.loop ? '루프' : '한 번 재생', STATUS[a.status]]) facts.append(el('span', '', f));
    const wave = el('div', 'dWave'), canvas = el('canvas'); wave.append(canvas);
    wave.onclick = (e) => { const r = wave.getBoundingClientRect(); window.setTimeout(renderPlayButton); playFrom((e.clientX - r.left) / r.width * m.seconds); };
    if (a.status === 'review') {
      const row = el('div', 'tile'); row.style.cssText = 'height:auto;background:none;overflow:visible;margin-top:8px';
      const ab = el('div', 'ab'); ab.style.position = 'static';
      const old = el('button', '', '이전'), fresh = el('button', '', '새 버전');
      old.onclick = () => { a.showNext = false; renderDetail(); }; fresh.onclick = () => { a.showNext = true; renderDetail(); };
      old.setAttribute('aria-pressed', String(!a.showNext)); fresh.setAttribute('aria-pressed', String(a.showNext));
      ab.append(old, fresh, iconButton('check', '채택', () => settle(a, true), 'keep'), iconButton('close', '버림', () => settle(a, false), 'drop'));
      row.append(ab); wave.after(row);
      main.append(head, facts, wave, row);
    } else main.append(head, facts, wave);
    const spec = el('canvas', 'dSpec'); spec.id = 'dSpec'; spec.setAttribute('aria-label', '주파수'); main.append(spec);
    const th = el('div', 'dTrackHead'); th.append(el('h2', '', `트랙 ${v.sound.stems.length}개`)); main.append(th);
    v.sound.stems.forEach((s, i) => main.append(stemRow(s, i)));
    box.append(main, sidePanel(a, problems));
    requestAnimationFrame(() => {
      const hue = resolved(color(a.cat));
      drawPeaks(canvas, v.peaks, hue, problems.some((p) => p.rule === '최대 소리') ? (g, W, H) => { g.fillRect(0, 0, W, 2); g.fillRect(0, H - 2, W, 2); } : null);
      document.querySelectorAll('.stem').forEach((row, i) => drawPeaks(row.querySelector('canvas'), synth.peaks(v.sound.stems[i].data, 160), stems[i % stems.length]));
    });
    renderPlayButton(); renderHeader();
  }
  function playFrom(at) { play(openAsset, { from: at, loop: !!(openAsset.loop || openAsset.music) }); }
  function stemRow(s, i) {
    const st = stemState[s.name] ||= { mute: false, solo: false, gain: 1 };
    const row = el('div', 'stem'), name = el('div', 'sName'), dot = el('i'); dot.style.setProperty('--c', stems[i % stems.length]);
    name.append(dot, s.name);
    const mute = iconButton(st.mute ? 'muted' : 'sound', `${s.name} ${st.mute ? '켜기' : '끄기'}`, () => { st.mute = !st.mute; applyStems(); setIcon(mute, st.mute ? 'muted' : 'sound'); mute.setAttribute('aria-pressed', String(st.mute)); }, 'iconBtn mute');
    mute.setAttribute('aria-pressed', String(st.mute));
    const solo = el('button', 'solo', 'S'); solo.title = '혼자 듣기'; solo.setAttribute('aria-label', `${s.name} 혼자 듣기`); solo.setAttribute('aria-pressed', String(st.solo)); solo.style.padding = '0';
    solo.onclick = () => { st.solo = !st.solo; solo.setAttribute('aria-pressed', String(st.solo)); applyStems(); };
    const gain = el('input'); gain.type = 'range'; gain.min = 0; gain.max = 1.5; gain.step = 0.01; gain.value = st.gain; gain.setAttribute('aria-label', `${s.name} 음량`);
    gain.oninput = () => { st.gain = +gain.value; applyStems(); };
    row.append(name, el('canvas'), mute, solo, gain);
    return row;
  }
  function sourceOf(a) {
    return a.layers.map((l) => {
      if (l.kind === 'tone') return `// ${a.name}\nsweep(${l.from}, ${l.to}, ${l.len}) |> ${l.wave}(%) * adsr(0, ${l.len}, 0, 0) * ${l.gain} |> out(%)`;
      if (l.kind === 'noise') return `noise() |> lp(%, ${Math.round(l.cutoff * 8000)}) * ar(${l.attack}, ${l.len}) * ${l.gain} |> out(%)`;
      if (l.kind === 'drums') return `// ${l.stem}\nn"bd ~ bd ~" |> kick(@.trig) |> bus("drums")`;
      return `// ${l.stem}\nn"${l.notes.slice(0, 8).filter((x) => x != null).join(' ')}" |> ${l.wave}(@.freq) * adsr(@.gate) |> bus("${l.stem}")`;
    }).join('\n\n');
  }
  function sidePanel(a, problems) {
    const side = el('div', 'dSide'), tabs = el('div', 'tabs'), body = el('div', 'tabBody');
    tabs.setAttribute('role', 'tablist');
    for (const [id, label] of [['chat', '대화'], ['code', '코드'], ['versions', `버전 ${a.versions.length}`], ['lint', `린트${problems.length ? ' ' + problems.length : ''}`], ['license', '저작권']]) {
      const b = el('button', '', label); b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', String(id === detailTab));
      b.onclick = () => { detailTab = id; renderDetail(); }; tabs.append(b);
    }
    if (detailTab === 'chat') {
      if (!a.chat.length) body.append(el('p', 'msg ai', `${a.name}을(를) 어떻게 바꿀지 말해 주세요.`));
      a.chat.forEach((m) => body.append(el('div', 'msg ' + (m.me ? 'me' : 'ai'), m.text)));
    } else if (detailTab === 'code') body.append(el('pre', 'code', sourceOf(a)));
    else if (detailTab === 'versions') {
      [...a.versions].reverse().forEach((v) => {
        const i = a.versions.indexOf(v), row = el('div', 'lineItem'), text = el('span', 'grow', `v${i + 1} · ${v.note}`);
        row.append(text, iconButton('play', '듣기', () => { a.current = i; renderDetail(); play(a); }, 'ghost iconBtn'));
        if (i === a.current) row.append(el('span', 'tag', '현재'));
        body.append(row);
      });
    } else if (detailTab === 'lint') {
      if (!problems.length) body.append(el('p', 'msg ai', '규칙을 모두 통과했어요.'));
      problems.forEach((p) => {
        const row = el('div', 'rule ' + p.level), t = el('div'); t.append(el('b', '', p.rule), p.text + ' ', el('small', '', p.fix)); row.append(el('i'), t); body.append(row);
      });
    } else {
      LICENSES.forEach((l) => { const row = el('div', 'lineItem'); row.append(el('span', 'grow', `${l.name} · ${l.use}`), el('span', 'tag', l.license)); body.append(row); });
      const copy = el('button', '', '저작권 전체 복사'); copy.onclick = copyLicenses; body.append(copy);
    }
    const dock = el('form', 'detailDock'), input = el('input'); input.placeholder = '이 에셋에 보낼 요청'; input.setAttribute('aria-label', '이 에셋에 보낼 요청');
    const send = iconButton('send', '보내기', null); send.type = 'submit';
    dock.onsubmit = (e) => { e.preventDefault(); const t = input.value.trim(); if (t && a.status !== 'working') request([a], t); };
    dock.append(input, send);
    side.append(tabs, body, dock);
    return side;
  }
  function liveLoop() {
    liveRaf = requestAnimationFrame(liveLoop);
    if (player) {
      const a = player.asset, t = tileOf(a), p = position() / player.length;
      let head = t?.querySelector('.ph');
      if (t && !head) { head = el('div', 'ph'); head.style.cssText = 'position:absolute;top:0;width:2px;height:62px;background:#F5F5F5;pointer-events:none'; t.append(head); }
      if (head) head.style.left = p * 100 + '%';
    } else document.querySelectorAll('.ph').forEach((x) => x.remove());
    const wave = document.querySelector('.dWave');
    if (wave) {
      let head = wave.querySelector('.ph');
      if (!head) { head = el('div', 'ph'); head.style.cssText = 'position:absolute;top:0;bottom:0;width:2px;background:#F5F5F5;pointer-events:none'; wave.append(head); }
      head.hidden = !player; if (player) head.style.left = position() / player.length * 100 + '%';
    }
    const c = $('dSpec');
    if (c) {
      const W = c.clientWidth, H = c.clientHeight;
      if (c.width !== W) { c.width = W; c.height = H; }
      const g = c.getContext('2d'); g.clearRect(0, 0, W, H);
      if (analyser && player) {
        const raw = new Uint8Array(analyser.frequencyBinCount); analyser.getByteFrequencyData(raw);
        g.fillStyle = resolved(color(player.asset.cat));
        const n = 72, w = W / n;
        for (let i = 0; i < n; i++) { const b = raw[Math.floor(1.5 * (raw.length / 1.5) ** (i / n))] / 255; g.fillRect(i * w, H - b * H, Math.max(1, w - 2), b * H); }
      }
    }
  }

  /* ---------- dialogs ---------- */
  const dlg = $('dialog');
  dlg.addEventListener('click', (e) => {
    if (e.target !== dlg) return;
    const q = dlg.getBoundingClientRect();
    if (e.clientX < q.left || e.clientX > q.right || e.clientY < q.top || e.clientY > q.bottom) dlg.close();
  });
  function openDialog(title) {
    dlg.textContent = '';
    dlg.append(iconButton('close', '닫기', () => dlg.close(), 'ghost iconBtn dlgClose'), el('h2', '', title));
  }
  function toast(text) {
    const t = $('toast'); t.textContent = text; t.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, 2200);
  }
  async function copy(text, done) {
    try { await navigator.clipboard.writeText(text); }
    catch {
      const area = el('textarea'); area.value = text; (dlg.open ? dlg : document.body).append(area); area.select(); document.execCommand('copy'); area.remove();
    }
    toast(done);
  }
  const licenseText = () => `${GAME} 소리 에셋 저작권 고지\n\n` + LICENSES.map((l) => `${l.name}\n  용도: ${l.use}\n  라이선스: ${l.license}\n  저작권자: ${l.holder}`).join('\n\n') + '\n';
  const copyLicenses = () => copy(licenseText(), '저작권 고지를 복사했어요');

  const specExample = () => JSON.stringify({ game: GAME, assets: [
    { id: 'sfx_ui_click', name: '클릭', category: 'ui', length: 0.1, description: '가볍고 나무 느낌' },
    { id: 'sfx_combat_parry', name: '패링', category: 'combat', length: 0.3, description: '금속 울림이 짧게' },
    { id: 'bgm_garden', name: '정원', category: 'bgm', length: 60, loop: true, description: '잔잔한 하프와 현악' },
  ] }, null, 2);
  const specPrompt = () => `당신은 이 게임의 음악 작업 담당입니다. 지금까지의 음악 작업 맥락을 바탕으로 게임 소리 명세서를 JSON으로 작성해 주세요.

게임: ${GAME}
설명: ${BRIEF}

규칙:
- 분류는 ${CATEGORIES.map((c) => c.id).join(', ')} 중 하나입니다.
- id는 효과음 sfx_, 환경음 amb_, 음악 bgm_ 로 시작하는 소문자 영문입니다.
- length는 초 단위 목표 길이입니다. 효과음은 2초 이하입니다.
- 최대 소리 -1.0 dBTP 이하, 음악 음량 -24 ~ -16 LUFS를 지킵니다.
- 저작권이 불분명한 곡이나 샘플을 참조하지 않습니다. 사용 가능한 도구와 음원: ${LICENSES.map((l) => `${l.name}(${l.license})`).join(', ')}.

JSON만 출력하세요. 형식:
${specExample()}`;

  function specDialog() {
    openDialog('명세');
    let tab = 'send';
    const body = el('div'), tabs = el('div', 'tabs'); tabs.style.padding = '0 0 0';
    const paint = () => {
      tabs.textContent = ''; body.textContent = '';
      for (const [id, label] of [['send', '프롬프트 보내기'], ['receive', '명세 받기']]) { const b = el('button', '', label); b.setAttribute('aria-selected', String(tab === id)); b.onclick = () => { tab = id; paint(); }; tabs.append(b); }
      if (tab === 'send') {
        body.append(el('p', '', '음악 작업을 하던 에이전트에게 붙여 넣으세요.'));
        const area = el('textarea'); area.value = specPrompt(); area.readOnly = true; area.setAttribute('aria-label', '프롬프트');
        const row = el('div', 'dlgRow'), b = el('button', 'primary', '프롬프트 복사'); b.id = 'copyPrompt'; b.onclick = () => copy(specPrompt(), '프롬프트를 복사했어요');
        row.append(b); body.append(area, row);
      } else receive(body);
    };
    dlg.append(tabs, el('div'), body); body.style.marginTop = '12px'; paint(); dlg.showModal();
  }
  function receive(body) {
    body.append(el('p', '', '에이전트가 준 명세를 붙여 넣으세요.'));
    const area = el('textarea'); area.id = 'specIn'; area.setAttribute('aria-label', '명세');
    const out = el('div'), row = el('div', 'dlgRow'), sample = el('button', 'ghost', '예시 넣기');
    const check = () => { out.textContent = ''; if (area.value.trim()) out.append(...planSpec(area.value)); };
    area.oninput = check; sample.onclick = () => { area.value = specExample(); check(); };
    row.append(sample); body.append(area, row, out);
  }
  function planSpec(text) {
    let spec;
    try { spec = JSON.parse(text); } catch (e) { return [el('p', 'note err', `JSON이 아니에요: ${e.message}`)]; }
    if (!Array.isArray(spec.assets)) return [el('p', 'note err', 'assets 목록이 없어요.')];
    const cats = CATEGORIES.map((c) => c.id), bad = spec.assets.filter((x) => !/^(sfx|amb|bgm)_[a-z0-9_]+$/.test(x.id || '') || !cats.includes(x.category));
    if (bad.length) return [el('p', 'note err', `규칙에 맞지 않는 항목 ${bad.length}개: ${bad.map((x) => x.id || '이름 없음').join(', ')}`)];
    const ids = new Set(spec.assets.map((x) => x.id)), added = spec.assets.filter((x) => !byId(x.id)), changed = spec.assets.filter((x) => byId(x.id) && byId(x.id).name !== x.name), kept = spec.assets.filter((x) => byId(x.id) && byId(x.id).name === x.name), gone = assets.filter((a) => !ids.has(a.id));
    const out = [el('h3', '', `추가 ${added.length} · 변경 ${changed.length} · 유지 ${kept.length} · 삭제 ${gone.length}`)];
    const line = (tag, cls, text) => { const r = el('div', 'lineItem'); r.append(el('span', 'tag ' + cls, tag), el('span', 'grow', text)); return r; };
    added.forEach((x) => out.push(line('추가', 'add', `${x.name} · ${x.id}`)));
    changed.forEach((x) => out.push(line('변경', 'chg', `${byId(x.id).name} → ${x.name}`)));
    gone.slice(0, 6).forEach((a) => out.push(line('삭제', 'del', a.name)));
    if (gone.length > 6) out.push(el('p', '', `외 ${gone.length - 6}개 삭제`));
    const row = el('div', 'dlgRow'), run = el('button', 'primary', '이 명세로 작업 시작'), keep = el('button', '', '삭제 없이 추가만');
    const apply = (remove) => {
      added.forEach((x) => { const a = { id: x.id, name: x.name, cat: x.category, music: false, layers: [{ kind: 'tone', from: 500, to: 700, len: Math.min(0.6, x.length || 0.3), wave: 'triangle', gain: 0.4, at: 0 }], status: 'draft', versions: [], current: 0, next: null, showNext: false, chat: [], progress: 0 }; assets.push(a); make(a, {}, '명세에서 생성'); });
      changed.forEach((x) => { byId(x.id).name = x.name; });
      if (remove) gone.forEach((a) => assets.splice(assets.indexOf(a), 1));
      dlg.close(); renderBoard(); toast(`명세를 적용했어요. 새 에셋 ${added.length}개`);
    };
    run.onclick = () => apply(true); keep.onclick = () => apply(false);
    row.append(run, keep); out.push(row);
    return out;
  }
  function lintDialog() {
    openDialog(`린트 · ${PROFILE.name}`);
    const items = ready(assets).flatMap((a) => lint(a).map((p) => ({ a, ...p })));
    if (!items.length) dlg.append(el('p', '', '모든 에셋이 규칙을 통과했어요.'));
    items.sort((x, y) => (x.level === y.level ? 0 : x.level === 'error' ? -1 : 1)).forEach((p) => dlg.append(problemRow(p)));
    dlg.append(el('h3', '', '적용 규칙'));
    PROFILE.rules.forEach((r) => { const row = el('div', 'rule'), t = el('div', '', r.text); row.append(el('i'), t); dlg.append(row); });
    dlg.showModal();
  }
  function problemRow(p) {
    const row = el('div', 'rule ' + p.level), t = el('div'); t.style.flex = '1'; t.append(el('b', '', `${p.a.name} · ${p.rule}`), p.text);
    const go = el('button', 'ghost', '보기'); go.onclick = () => { dlg.close(); openDetail(p.a); detailTab = 'lint'; renderDetail(); };
    row.append(el('i'), t, go); return row;
  }
  function exportDialog() {
    openDialog('내보내기');
    const errors = ready(assets).flatMap((a) => lint(a).filter((p) => p.level === 'error').map((p) => ({ a, ...p })));
    const undone = assets.filter((a) => a.status !== 'approved');
    if (errors.length) { dlg.append(el('p', 'note err', `린트 오류 ${errors.length}개를 고쳐야 내보낼 수 있어요.`)); errors.forEach((p) => dlg.append(problemRow(p))); }
    else if (undone.length) dlg.append(el('p', 'note', `아직 승인되지 않은 에셋 ${undone.length}개는 빠집니다.`));
    dlg.append(el('h3', '', '묶음에 들어가는 것'));
    for (const t of ['승인한 소리 파일', '명세 game-audio.spec.json', '린트 보고서', 'CREDITS.md와 라이선스 원문']) dlg.append(Object.assign(el('div', 'lineItem'), { textContent: t }));
    dlg.append(el('h3', '', '저작권'));
    LICENSES.forEach((l) => { const r = el('div', 'lineItem'); r.append(el('span', 'grow', `${l.name} · ${l.use}`), el('span', 'tag', l.license)); dlg.append(r); });
    const row = el('div', 'dlgRow'), go = el('button', 'primary', '묶음 내보내기'), lic = el('button', '', '저작권 전체 복사');
    go.disabled = !!errors.length; go.onclick = () => { dlg.close(); stage = 'export'; renderHeader(); toast('껍데기라 실제 파일은 아직 만들지 않아요'); };
    lic.onclick = copyLicenses; row.append(go, lic); dlg.append(row);
    dlg.showModal();
  }
  function gameDialog() {
    openDialog(GAME);
    dlg.append(el('p', '', BRIEF), el('p', '', `린트 프로필: ${PROFILE.name}`));
    const b = el('button', '', '샘플 단계부터 다시'); b.onclick = () => location.reload(); dlg.append(b);
    dlg.showModal();
  }

  /* ---------- host page ---------- */
  const inHost = window.parent !== window;
  $('backBtn').onclick = () => { stopSound(); queue = null; if (inHost) parent.postMessage({ type: 'asset:back' }, '*'); };
  addEventListener('message', (e) => {
    if (e.data?.type === 'asset:measure') {
      const tiles = [...document.querySelectorAll('.tile')].slice(0, 40).map((t) => { const q = t.getBoundingClientRect(); return { x: q.left, y: q.top, w: q.width, h: q.height, c: resolved(color(byId(t.dataset.id).cat)) }; });
      e.source?.postMessage({ type: 'asset:tiles', tiles }, '*');
    }
    if (e.data?.type === 'asset:hide') { queue = null; stopSound(); }
  });

  /* ---------- start ---------- */
  setIcon($('backBtn'), 'music'); setIcon($('send'), 'send'); setIcon($('playAll'), 'play');
  $('specBtn').onclick = specDialog; $('lintBtn').onclick = lintDialog; $('exportBtn').onclick = exportDialog; $('gameName').onclick = gameDialog;
  addEventListener('resize', () => { if (openAsset) renderDetail(); else assets.filter((a) => a.versions.length).forEach(drawTile); });
  renderBoard(); liveLoop();
  window.assetStudio = { assets, selected, lint, position: () => position() };
})();
