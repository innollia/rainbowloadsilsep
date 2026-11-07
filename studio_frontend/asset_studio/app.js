// Game sound asset board: front-end shell on stand-in data. No server calls; requests are simulated with timers.
(() => {
  const $ = (id) => document.getElementById(id);
  const { GAME, BRIEF, CATEGORIES, ASSETS, PROFILES, RULES, LICENSES } = window.STUDIO_DATA;
  const ICONS = {
    play: '<path d="M7 4.5v15l12-7.5z" fill="currentColor" stroke="none"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor" stroke="none"/>',
    back: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    music: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
    send: '<path d="M12 19V5M6 11l6-6 6 6"/>',
    sound: '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16.5 9a4 4 0 0 1 0 6M19 6.5a8 8 0 0 1 0 11"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    download: '<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>',
    spec: '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 12h7M9 16h7"/>',
    lint: '<path d="M4 6h9M4 12h9M4 18h6"/><path d="m15 17 2.5 2.5L22 14"/>',
    expand: '<path d="M14 4h6v6M20 4l-7 7M10 20H4v-6M4 20l7-7"/>',
    solo: '<path d="M4 15v-3a8 8 0 0 1 16 0v3"/><rect x="3" y="14" width="4" height="6" rx="1.5"/><rect x="17" y="14" width="4" height="6" rx="1.5"/>',
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

  /* ---------- lint rules ---------- */
  let profile = PROFILES[0].id, lintOpen = false, lintFocus = null, lintFilter = 'all', lintRule = null;
  const rules = RULES.map((r) => ({ ...r, on: true }));
  const fmt = (r, v) => (r.text ? (v ? '통과' : '위반') : r.id === 'dc' || r.id === 'seam' ? v.toFixed(3) : r.id === 'dur' ? v.toFixed(2) : r.unit === 'dB' || r.unit === 'LUFS' ? v.toFixed(1) : Math.round(v).toString());
  const limitText = (r) => (r.text ? '' : r.range ? `${r.range[0]} ~ ${r.range[1]}` : `${r.id === 'peak' ? '≤ ' : '≤ '}${r.limit}${r.unit ? ' ' + r.unit : ''}`);
  const applies = (r, a) => r.on && (!r.applies || r.applies(a));
  function check(r, a) {
    if (!applies(r, a)) return null;
    const value = r.read(heard(a).measure, a), failed = r.text ? !value : r.bad(value, r);
    return { value, failed, waived: failed && (!!a.waived?.[r.id] || a.status === 'approved'), level: r.level };
  }
  function lint(a) {
    if (!a.versions.length) return [];
    const out = [];
    for (const r of rules) {
      const c = check(r, a);
      if (!c?.failed || c.waived) continue;
      out.push({ id: r.id, level: r.level, rule: r.name, canFix: !!r.fix, text: r.text ? r.hint : `${fmt(r, c.value)}${r.unit ? ' ' + r.unit : ''}, 기준 ${limitText(r)}`, fix: r.hint });
    }
    return out;
  }
  // Repairs what needs no AI: level, and trimming silence. Everything goes in as a new version.
  function autoFix(a) {
    const m = heard(a).measure, get = (id) => rules.find((r) => r.id === id), base = version(a).change || {}, change = { ...base };
    const fixes = lint(a).filter((p) => p.canFix).map((p) => p.id);
    if (!fixes.length) return false;
    let gain = 0;
    if (fixes.includes('loud')) { const r = get('loud').range; gain = (r[0] + r[1]) / 2 - m.loud; }
    const peakRoom = get('peak').limit - 0.2 - m.peak;
    if (fixes.includes('peak') || fixes.includes('clip') || m.peak + gain > get('peak').limit) gain = Math.min(gain || peakRoom, peakRoom);
    if (gain) change.level = (base.level ?? 1) * 10 ** (gain / 20);
    if (fixes.includes('lead') || fixes.includes('tail')) {
      change.trim = [fixes.includes('lead') ? Math.max(0, m.lead / 1000 - 0.005) : 0, fixes.includes('tail') ? Math.max(0, m.tail / 1000 - 0.05) : 0];
    }
    make(a, change, '자동 수정: ' + fixes.map((id) => get(id).name).join(', '));
    if (a.status === 'approved') a.status = 'draft';
    return true;
  }
  const whyWaived = (a, r) => a.waived?.[r.id] || '승인하며 넘김';
  const openIssues = (a) => rules.map((r) => [r, check(r, a)]).filter(([, c]) => c?.failed);
  function approve(a) {
    const left = lint(a).length;
    a.status = 'approved';
    if (left) toast(`린트 ${left}개를 넘기고 승인했어요`);
  }
  const failing = (a) => rules.map((r) => check(r, a)).filter((c) => c?.failed && !c.waived);
  const severity = (a) => { const f = failing(a); return f.some((c) => c.level === 'error') ? 0 : f.length ? 1 : a.waived && Object.keys(a.waived).length ? 2 : 3; };

  function renderLint() {
    const box = $('lintView'), keep = box.querySelector('.lTableWrap')?.scrollTop || 0, sideKeep = box.querySelector('.lSide')?.scrollTop || 0;
    box.textContent = '';
    const list = ready(assets), errors = list.filter((a) => severity(a) === 0), warns = list.filter((a) => severity(a) === 1), waived = list.filter((a) => severity(a) === 2), clean = list.filter((a) => severity(a) === 3);
    const top = el('div', 'lTop');
    const total = (cls, n, label, id) => {
      const b = el('button', 'lTotal ' + cls); b.setAttribute('aria-pressed', String(lintFilter === id));
      b.append(el('b', '', String(n)), el('span', '', label)); b.onclick = () => { lintFilter = lintFilter === id ? 'all' : id; renderLint(); }; return b;
    };
    top.append(total('error', errors.length, '오류', 'error'), total('warn', warns.length, '경고', 'warn'), total('ok', clean.length, '통과', 'ok'));
    if (waived.length) top.append(total('', waived.length, '예외', 'waived'));
    const gate = el('span', 'lGate', errors.length ? '남은 오류는 내보낼 때 다시 알려 드려요' : '남은 오류가 없어요');
    const select = el('select'); select.setAttribute('aria-label', '린트 프로필');
    for (const f of PROFILES) select.add(new Option(`프로필: ${f.name}`, f.id));
    if (!PROFILES.some((f) => f.id === profile)) select.add(new Option('프로필: 사용자 지정', 'custom'));
    select.value = profile;
    select.onchange = () => { profile = select.value; const f = PROFILES.find((x) => x.id === profile); rules.find((r) => r.id === 'loud').range = [...f.loud]; afterLint(); };
    const fixable = list.filter((a) => lint(a).some((p) => p.canFix)), fix = el('button', 'primary', fixable.length ? `자동 수정 ${fixable.length}개` : '자동 수정');
    fix.id = 'fixAll'; fix.disabled = !fixable.length; fix.onclick = () => { fixable.forEach(autoFix); toast(`${fixable.length}개를 고쳐 새 버전으로 넣었어요`); afterLint(); };
    const report = el('button', '', '보고서 복사'); report.onclick = () => copy(lintReport(), '린트 보고서를 복사했어요');
    top.append(gate, el('span', 'spacer'), select, report, fix);

    const wrap = el('div', 'lTableWrap'), table = el('table', 'lint'), head = el('tr'), body = el('tbody'), shown = rules.filter((r) => r.on);
    const name = el('th', '', `에셋 ${list.length}`); name.onclick = () => { lintRule = null; renderLint(); };
    head.append(name);
    for (const r of shown) {
      const count = list.filter((a) => check(r, a)?.failed).length, th = el('th'); th.title = r.hint;
      th.append(r.name, el('small', '', count ? `위반 ${count}` : limitText(r) || '규칙')); if (lintRule === r.id) th.setAttribute('aria-sort', 'other');
      th.onclick = () => { lintRule = lintRule === r.id ? null : r.id; renderLint(); }; head.append(th);
    }
    const thead = el('thead'); thead.append(head); table.append(thead);
    const rows = list.filter((a) => (lintFilter === 'all' || lintFilter === ['error', 'warn', 'waived', 'ok'][severity(a)]) && (!lintRule || check(rules.find((r) => r.id === lintRule), a)?.failed))
      .sort((x, y) => severity(x) - severity(y) || assets.indexOf(x) - assets.indexOf(y));
    for (const a of rows) {
      const tr = el('tr', a === lintFocus ? 'on' : ''), first = el('td'), dot = el('i'), pick = el('input'); dot.style.setProperty('--c', color(a.cat));
      pick.type = 'checkbox'; pick.checked = selected.has(a.id); pick.setAttribute('aria-label', `${a.name} 선택`);
      pick.onclick = (e) => e.stopPropagation(); pick.onchange = () => toggle(a);
      first.append(pick, dot, a.name); tr.append(first);
      for (const r of shown) {
        const c = check(r, a), td = el('td');
        if (!c) { td.className = 'none'; td.textContent = '·'; }
        else { td.textContent = fmt(r, c.value); td.className = c.waived ? 'waived' : c.failed ? c.level : 'pass'; if (c.waived) td.title = `예외: ${whyWaived(a, r)}`; }
        tr.append(td);
      }
      tr.onclick = () => { lintFocus = a; focused = a.id; play(a); renderLint(); };
      tr.ondblclick = () => openDetail(a);
      body.append(tr);
    }
    table.append(body); wrap.append(table);
    if (!rows.length) wrap.append(el('p', 'lEmpty', '조건에 맞는 에셋이 없어요.'));
    box.append(top, wrap, lintSide(list), lintStrip());
    box.querySelector('.lTableWrap').scrollTop = keep; box.querySelector('.lSide').scrollTop = sideKeep;
    renderHeader();
  }
  function afterLint() { renderLint(); }
  function lintStrip() {
    const strip = el('div', 'lStrip'), a = lintFocus && ready(assets).includes(lintFocus) ? lintFocus : null;
    if (!a) { strip.append(el('span', 'lGate', '행을 누르면 듣고, 위반을 고치거나 예외로 둘 수 있어요. 빨간 칸은 오류, 노란 칸은 경고입니다.')); return strip; }
    const issues = el('div', 'lIssues'), done = el('span', 'lGate', '위반이 없어요');
    strip.append(el('h3', '', a.name));
    for (const r of rules) {
      const c = check(r, a); if (!c?.failed) continue;
      const row = el('span', 'lIssue ' + (c.waived ? 'waived' : c.level)); row.append(el('i'), r.text ? r.name : `${r.name} ${fmt(r, c.value)}${r.unit ? ' ' + r.unit : ''}`);
      if (c.waived) {
        const reason = a.waived?.[r.id], undo = el('button', '', reason ? '예외 해제' : '승인 취소');
        undo.onclick = () => { if (reason) delete a.waived[r.id]; else a.status = 'draft'; afterLint(); }; row.append(undo);
      } else {
        if (r.fix) { const b = el('button', '', '자동 수정'); b.onclick = () => { autoFix(a); afterLint(); }; row.append(b); }
        else if (!r.text) { const b = el('button', '', 'AI에게 맡기기'); b.onclick = () => { request([a], `${r.name} 기준에 맞게 고쳐 줘`); }; row.append(b); }
        const w = el('button', '', '예외'); w.onclick = () => waive(a, r); row.append(w);
      }
      issues.append(row);
    }
    if (!issues.children.length) issues.append(done);
    const more = el('button', 'ghost', '자세히'); more.onclick = () => openDetail(a);
    strip.append(issues, more);
    return strip;
  }
  function waive(a, r) {
    openDialog(`${a.name} · ${r.name} 예외`);
    dlg.append(el('p', '', '왜 예외로 두는지 적어 주세요. 린트 보고서에 함께 남습니다.'));
    const input = el('input'); input.style.cssText = 'width:100%;height:44px;background:var(--raised);border:0;border-radius:8px;padding:0 10px'; input.setAttribute('aria-label', '예외 사유');
    const row = el('div', 'dlgRow'), ok = el('button', 'primary', '예외로 두기');
    ok.onclick = () => { const why = input.value.trim(); if (!why) { input.focus(); return; } (a.waived ||= {})[r.id] = why; dlg.close(); afterLint(); };
    input.onkeydown = (e) => { if (e.key === 'Enter') ok.click(); };
    row.append(ok); dlg.append(input, row); dlg.showModal(); input.focus();
  }
  function lintSide(list) {
    const side = el('aside', 'lSide');
    side.append(el('h3', '', '음량 분포'));
    side.append(chart(list));
    side.append(el('h3', '', '규칙'));
    for (const r of rules) {
      const row = el('div', 'ruleRow'), on = el('input'); on.type = 'checkbox'; on.checked = r.on; on.setAttribute('aria-label', `${r.name} 사용`);
      on.onchange = () => { r.on = on.checked; afterLint(); };
      const label = el('div', 'rName'); label.append(r.name, el('small', '', r.hint));
      const level = el('select'); level.setAttribute('aria-label', `${r.name} 수준`); level.add(new Option('오류', 'error')); level.add(new Option('경고', 'warn')); level.value = r.level;
      level.onchange = () => { r.level = level.value; afterLint(); };
      row.append(on, label, level);
      if (!r.text) {
        const box = el('div', 'rLimits'); box.style.gridColumn = '2 / 4';
        const number = (value, set) => { const i = el('input'); i.type = 'number'; i.step = 'any'; i.value = value; i.setAttribute('aria-label', `${r.name} 기준값`); i.onchange = () => { set(+i.value); if (r.id === 'loud') profile = 'custom'; afterLint(); }; return i; };
        if (r.range) box.append(number(r.range[0], (v) => { r.range[0] = v; }), '~', number(r.range[1], (v) => { r.range[1] = v; }));
        else box.append(number(r.limit, (v) => { r.limit = v; }));
        box.append(r.unit);
        row.append(box);
      }
      side.append(row);
    }
    return side;
  }
  function chart(list) {
    const NS = 'http://www.w3.org/2000/svg', W = 300, H = 180, pad = 22;
    const svg = document.createElementNS(NS, 'svg'); svg.id = 'lChart'; svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', '가로 음량, 세로 최대 소리 분포');
    const X = [-44, -6], Y = [-30, 10];
    const px = (v) => pad + (v - X[0]) / (X[1] - X[0]) * (W - pad - 8), py = (v) => H - pad - (v - Y[0]) / (Y[1] - Y[0]) * (H - pad - 8);
    const add = (tag, attrs, text) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); if (text != null) n.textContent = text; svg.append(n); return n; };
    const loud = rules.find((r) => r.id === 'loud'), peak = rules.find((r) => r.id === 'peak');
    add('rect', { x: px(loud.range[0]), y: 8, width: px(loud.range[1]) - px(loud.range[0]), height: H - pad - 8, fill: 'rgba(199,160,232,.16)' });
    add('line', { x1: pad, x2: W - 8, y1: py(peak.limit), y2: py(peak.limit), stroke: '#FF9B9B', 'stroke-dasharray': '4 3' });
    add('line', { x1: pad, x2: W - 8, y1: H - pad, y2: H - pad, stroke: '#363636' });
    add('line', { x1: pad, x2: pad, y1: 8, y2: H - pad, stroke: '#363636' });
    add('text', { x: W - 8, y: H - 8, 'text-anchor': 'end' }, '음량 LUFS');
    add('text', { x: pad + 4, y: 16 }, '최대 dB');
    add('text', { x: W - 8, y: py(peak.limit) - 4, 'text-anchor': 'end' }, `상한 ${peak.limit}`);
    for (const a of list) {
      const m = heard(a).measure, bad = failing(a).length > 0;
      const dot = add('circle', { cx: Math.min(W - 8, Math.max(pad, px(m.loud))), cy: Math.max(8, Math.min(H - pad, py(m.peak))), r: a === lintFocus ? 6 : 4, fill: resolved(color(a.cat)), stroke: bad ? '#F5F5F5' : 'none', 'stroke-width': 1.2 });
      const t = document.createElementNS(NS, 'title'); t.textContent = `${a.name}: ${m.loud.toFixed(1)} LUFS, ${m.peak.toFixed(1)} dB`; dot.append(t);
      dot.addEventListener('click', () => { lintFocus = a; focused = a.id; play(a); renderLint(); });
    }
    return svg;
  }
  function lintReport() {
    const list = ready(assets), lines = [`# ${GAME} 린트 보고서`, '', `프로필: ${PROFILES.find((f) => f.id === profile)?.name || '사용자 지정'}`, `검사 ${list.length}개, 미생성 ${assets.length - list.length}개 제외`, ''];
    for (const a of list) {
      const items = openIssues(a);
      if (!items.length) continue;
      lines.push(`## ${a.name} (${a.id})`);
      for (const [r, c] of items) lines.push(`- ${c.waived ? '예외' : c.level === 'error' ? '오류' : '경고'} ${r.name}: ${fmt(r, c.value)} ${r.unit || ''}${c.waived ? ` (사유: ${whyWaived(a, r)})` : ''}`);
      lines.push('');
    }
    return lines.join('\n');
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
    if (a.versions.length) {
      t.append(iconButton('check', `${a.name} 선택`, (e) => { e.stopPropagation(); toggle(a); anchor = a.id; }, 'tileBtn tileCheck'), iconButton('expand', `${a.name} 자세히`, (e) => { e.stopPropagation(); openDetail(a); }, 'tileBtn tileOpen'));
      t.querySelector('.tileCheck').addEventListener('dblclick', (e) => e.stopPropagation());
      t.querySelector('.tileOpen').addEventListener('dblclick', (e) => e.stopPropagation());
    }
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
      const pickable = ready(list);
      if (pickable.length) {
        const all = el('button', 'ghost', pickable.every((x) => selected.has(x.id)) ? '선택 해제' : '전체 선택');
        all.onclick = () => { const off = pickable.every((x) => selected.has(x.id)); pickable.forEach((x) => (off ? selected.delete(x.id) : selected.add(x.id))); renderBoard(); };
        h.append(all);
      }
      const grid = el('div', 'grid');
      grid.append(...list.map(makeTile));
      group.append(h, grid); box.append(group);
    }
    box.scrollTop = top;
    assets.filter((a) => a.versions.length).forEach(drawTile);
    renderSide(); renderHeader(); syncDock();
  }
  function banner() {
    const unchecked = assets.filter((a) => a.status === 'draft');
    const box = el('div', 'note'); box.style.cssText = 'display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:6px';
    const all = el('button', 'ghost', '전부 승인'); all.id = 'approveAll'; all.onclick = () => { unchecked.forEach(approve); renderBoard(); };
    if (stage !== 'sample') {
      if (!unchecked.length) return [];
      const text = el('span', '', `확인할 에셋 ${unchecked.length}개가 남았어요.`); text.style.flex = '1';
      box.append(text, all);
      return [box];
    }
    const samples = assets.filter((a) => a.sample), done = samples.filter((a) => a.status === 'approved').length, rest = assets.filter((a) => a.status === 'pending').length;
    const text = el('span', '', done === samples.length ? `샘플 ${samples.length}개를 모두 승인했어요. 이 스타일로 나머지 ${rest}개를 만듭니다.` : `샘플 ${samples.length}개 중 ${done}개 승인. 들어 보고 승인하면 나머지 ${rest}개를 같은 스타일로 만듭니다.`);
    text.style.flex = '1';
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
    $('gameTitle').textContent = GAME;
    const order = [['brief', '설명'], ['sample', '샘플 확인'], ['expand', '확장'], ['export', '내보내기']], at = order.findIndex(([id]) => id === stage);
    $('stages').textContent = '';
    order.forEach(([, label], i) => { const li = el('li', i < at ? 'done' : '', label); if (i === at) li.setAttribute('aria-current', 'step'); $('stages').append(li); });
    const approved = assets.filter((a) => a.status === 'approved').length;
    $('counts').textContent = `전체 ${assets.length} · 승인 ${approved}`;
    const all = ready(assets).flatMap(lint), errors = all.filter((p) => p.level === 'error').length;
    $('lintCount').hidden = !all.length; $('lintCount').textContent = String(all.length); $('lintCount').className = 'badge' + (errors ? '' : ' warn');
    $('lintBtn').setAttribute('aria-pressed', String(lintOpen));
    const waiting = assets.filter((a) => a.status === 'review').length;
    $('review').hidden = !waiting || !!openAsset; $('reviewText').textContent = `검토 ${waiting}개`;
  }
  function syncDock() {
    const count = selected.size, target = focused && byId(focused);
    $('selCount').hidden = !count; $('selCount').textContent = `${count}개 선택`;
    $('selAll').hidden = $('selApprove').hidden = $('selClear').hidden = !count;
    $('detailBtn').hidden = !!count || lintOpen || !target?.versions.length;
    document.body.classList.toggle('selecting', !!count);
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
    if (lintOpen) {
      const rows = [...assets].filter((x) => x.versions.length).sort((x, y) => severity(x) - severity(y) || assets.indexOf(x) - assets.indexOf(y));
      if (e.key === 'Escape') toggleLint(false);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); const at = rows.indexOf(lintFocus); lintFocus = rows[Math.max(0, Math.min(rows.length - 1, at + (e.key === 'ArrowDown' ? 1 : -1)))]; play(lintFocus); renderLint(); document.querySelector('tr.on')?.scrollIntoView({ block: 'nearest' }); }
      if (e.code === 'Space' && lintFocus) { e.preventDefault(); if (player) stopSound(); else play(lintFocus); }
      if (e.key === 'Enter' && lintFocus) openDetail(lintFocus);
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
    else if (e.key.toLowerCase() === 'x' && a?.versions.length) toggle(a);
    else if (e.key.toLowerCase() === 'a' && a) setStatus(a, 'approved');
    else if (e.key.toLowerCase() === 'r' && a) setStatus(a, 'flagged');
    else if (e.key === 'Escape') { selected.clear(); refreshSelection(); }
  });
  function setStatus(a, status) { if (a.status === 'draft' || a.status === 'approved' || a.status === 'flagged') { if (status === 'approved' && a.status !== 'approved') approve(a); else a.status = a.status === status ? 'draft' : status; const id = a.id; renderBoard(); tileOf(byId(id))?.focus(); } }

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
  function renderOpen(a) { if (openAsset && (!a || a === openAsset)) renderDetail(); else if (openAsset) renderHeader(); else if (lintOpen) renderLint(); else renderBoard(); }
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
  $('selAll').onclick = () => { ready(lintOpen ? assets : visible()).forEach((x) => selected.add(x.id)); lintOpen ? renderLint() : renderBoard(); };
  $('selClear').onclick = () => { selected.clear(); lintOpen ? renderLint() : renderBoard(); };
  $('selApprove').onclick = () => { [...selected].map(byId).filter((a) => a.status === 'draft' || a.status === 'flagged').forEach(approve); selected.clear(); lintOpen ? renderLint() : renderBoard(); };
  $('detailBtn').onclick = () => { const a = focused && byId(focused); if (a?.versions.length) openDetail(a); };
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
    $('boardView').hidden = on || lintOpen; $('lintView').hidden = on || !lintOpen; $('detailView').hidden = !on; $('dock').hidden = on;
  }
  let walk = [];
  function openDetail(a, tab = 'chat') {
    const tile = tileOf(a);
    walk = lintOpen ? ready(assets).sort((x, y) => severity(x) - severity(y) || assets.indexOf(x) - assets.indexOf(y)) : ready(visible());
    if (!walk.includes(a)) walk.unshift(a);
    if (tile) tile.style.viewTransitionName = 'zoom';
    transition(() => {
      if (tile) tile.style.viewTransitionName = '';
      stopSound(); openAsset = a; focused = a.id; stemState = {}; detailTab = tab; showDetail(true); renderDetail();
    });
  }
  function closeDetail() {
    const a = openAsset; stopSound();
    document.querySelector('.dWave')?.style.setProperty('view-transition-name', 'zoom');
    transition(() => {
      openAsset = null; showDetail(false); if (lintOpen) renderLint(); else renderBoard();
      const t = tileOf(a); if (t) { t.style.viewTransitionName = 'zoom'; t.focus(); setTimeout(() => { t.style.viewTransitionName = ''; }, 400); }
    });
  }
  function step(by) {
    const list = walk.filter((a) => assets.includes(a) && a.versions.length), at = list.indexOf(openAsset), next = list[(at + by + list.length) % list.length];
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
    const approveBtn = el('button', a.status === 'approved' ? '' : 'primary', a.status === 'approved' ? '승인됨' : '승인');
    approveBtn.onclick = () => { if (a.status === 'approved') a.status = 'draft'; else approve(a); renderDetail(); };
    approveBtn.disabled = a.status === 'working' || a.status === 'review';
    head.append(iconButton('back', '보드로', closeDetail, 'ghost iconBtn'), title, el('span', 'spacer'), iconButton('prev', '이전 에셋', () => step(-1), 'ghost iconBtn'), iconButton('next', '다음 에셋', () => step(1), 'ghost iconBtn'), play, approveBtn);
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
    const solo = iconButton('solo', `${s.name} 혼자 듣기`, null, 'iconBtn solo'); solo.setAttribute('aria-pressed', String(st.solo));
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
      const passed = openIssues(a).filter(([, c]) => c.waived);
      if (!problems.length && !passed.length) body.append(el('p', 'msg ai', '규칙을 모두 통과했어요.'));
      passed.forEach(([r, c]) => { const row = el('div', 'rule'), t = el('div'); t.append(el('b', '', r.name), `${r.text ? r.hint : fmt(r, c.value) + ' ' + r.unit} `, el('small', '', whyWaived(a, r))); row.append(el('i'), t); body.append(row); });
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

  const specExample = () => JSON.stringify({ game: GAME, style: '따뜻한 나무 타악기와 하프 중심, 전투도 무겁지 않게', assets: [
    { id: 'sfx_ui_click', name: '클릭', category: 'ui', length: 0.1, loop: false, when: '메뉴 버튼을 누를 때', description: '가볍고 나무 느낌' },
    { id: 'sfx_combat_parry', name: '패링', category: 'combat', length: 0.3, loop: false, when: '적 공격을 막는 순간', description: '금속 울림이 짧게' },
    { id: 'bgm_garden', name: '정원', category: 'bgm', length: 60, loop: true, when: '정원 화면', description: '잔잔한 하프와 현악' },
  ], questions: [] }, null, 2);
  const specPrompt = () => {
    const rule = (id) => rules.find((r) => r.id === id), loud = rule('loud').range;
    return `${GAME}에 들어갈 소리 명세서를 JSON으로 작성해 주세요. 이 명세서대로 소리 에셋을 만듭니다.

게임 설명: ${BRIEF}

지금까지 본 기획, 코드, 음악 작업을 근거로 게임에 실제로 필요한 소리만 적어 주세요. 근거가 없는 값은 지어내지 말고 null로 두고, 정해야 할 것은 questions에 적어 주세요.

항목
- style: 게임 전체의 소리 방향, 한두 문장
- id: 효과음 sfx_, 환경음 amb_, 음악 bgm_ 로 시작하는 소문자 영문. 게임 코드에 이미 쓰는 이름이 있으면 그대로
- name: 한국어 이름
- category: ${CATEGORIES.map((c) => c.id).join(', ')} 중 하나
- length: 목표 길이(초)
- loop: 반복 재생 여부
- when: 게임의 어떤 순간에 나는 소리인지
- description: 어떤 소리인지

기준
- 최대 소리 ${rule('peak').limit} dB 이하
- 음악 음량 ${loud[0]} ~ ${loud[1]} LUFS
- 효과음 ${rule('dur').limit}초 이하
- 사용할 수 있는 재료: ${LICENSES.map((l) => `${l.name}(${l.license})`).join(', ')}
- 저작권이 불분명한 곡이나 샘플은 참조하지 않기

설명 없이 아래 형식의 JSON만 답해 주세요. 값은 예시이니 그대로 쓰지 마세요.
${specExample()}`;
  };

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
  function toggleLint(on = !lintOpen) {
    lintOpen = on; stopSound();
    if (openAsset) { openAsset = null; }
    showDetail(false);
    if (on) renderLint(); else renderBoard();
    renderHeader();
  }
  function problemRow(p) {
    const row = el('div', 'rule ' + p.level), t = el('div'); t.style.flex = '1'; t.append(el('b', '', `${p.a.name} · ${p.rule}`), p.text);
    const go = el('button', 'ghost', '보기'); go.onclick = () => { dlg.close(); openDetail(p.a, 'lint'); };
    row.append(el('i'), t, go); return row;
  }
  function exportDialog() {
    openDialog('내보내기');
    const going = assets.filter((a) => a.status === 'approved'), undone = assets.filter((a) => a.status !== 'approved');
    const flagged = going.map((a) => ({ a, items: openIssues(a) })).filter((x) => x.items.length);
    const count = (level) => flagged.reduce((n, x) => n + x.items.filter(([, c]) => c.level === level).length, 0);
    if (flagged.length) {
      dlg.append(el('p', 'note err', `승인한 에셋에 린트 오류 ${count('error')}개, 경고 ${count('warn')}개가 남아 있어요. 이대로 내보낼 수 있습니다.`));
      flagged.forEach(({ a, items }) => dlg.append(problemRow({ a, level: items.some(([, c]) => c.level === 'error') ? 'error' : 'warn', rule: items.map(([r]) => r.name).join(', '), text: '' })));
    }
    if (undone.length) dlg.append(el('p', 'note', `아직 승인되지 않은 에셋 ${undone.length}개는 빠집니다.`));
    dlg.append(el('h3', '', '묶음에 들어가는 것'));
    for (const t of ['승인한 소리 파일', '명세 game-audio.spec.json', '린트 보고서', 'CREDITS.md와 라이선스 원문']) dlg.append(Object.assign(el('div', 'lineItem'), { textContent: t }));
    dlg.append(el('h3', '', '저작권'));
    LICENSES.forEach((l) => { const r = el('div', 'lineItem'); r.append(el('span', 'grow', `${l.name} · ${l.use}`), el('span', 'tag', l.license)); dlg.append(r); });
    const row = el('div', 'dlgRow'), go = el('button', 'primary', '묶음 내보내기'), lic = el('button', '', '저작권 전체 복사');
    go.id = 'exportGo'; go.onclick = () => { dlg.close(); stage = 'export'; renderHeader(); toast('껍데기라 실제 파일은 아직 만들지 않아요'); };
    lic.onclick = copyLicenses; row.append(go, lic); dlg.append(row);
    dlg.showModal();
  }
  function gameDialog() {
    openDialog(GAME);
    dlg.append(el('p', '', BRIEF), el('p', '', `린트 프로필: ${PROFILES.find((f) => f.id === profile)?.name || '사용자 지정'}`));
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
  setIcon($('backBtn'), 'music'); setIcon($('send'), 'send'); setIcon($('playAll'), 'play'); setIcon($('gameName'), 'folder'); setIcon($('specBtn'), 'spec'); setIcon($('exportBtn'), 'download');
  $('lintBtn').insertAdjacentHTML('afterbegin', `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS.lint}</svg>`);
  $('specBtn').onclick = specDialog; $('lintBtn').onclick = () => toggleLint(); $('exportBtn').onclick = exportDialog; $('gameName').onclick = gameDialog;
  addEventListener('resize', () => { if (openAsset) renderDetail(); else assets.filter((a) => a.versions.length).forEach(drawTile); });
  renderBoard(); liveLoop();
  window.assetStudio = { assets, selected, lint, position: () => position() };
})();
