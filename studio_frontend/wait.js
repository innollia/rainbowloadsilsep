// The wait while the AI works, drawn as a tiny step sequencer: four rows of pads in the track colours
// (melody, pad, bass, drums from the top). The beat the AI writes stays on the pads between steps.
// editing: a cursor walks the columns and writes the beat in · verifying: a fast scan runs over it
// listening: the playhead steps at tempo and every hit pad jumps · signal: the columns turn into level meters
// analyzing: a lens glides from spot to spot and lights what it looks at.
// Reduced motion stays alive with fades only: nothing slides, grows or glows, and it steps slower.
(() => {
  const COLS = 12, ROWS = 4, CW = 10, CH = 8, GX = 3, GY = 2, PAD = 4;
  const GW = COLS * CW + (COLS - 1) * GX, GH = ROWS * CH + (ROWS - 1) * GY, W = GW + PAD * 2, H = GH + PAD * 2;
  const ROW_INK = ['--melody', '--pad', '--bass', '--drums'];
  const METER_INK = ['--drums', '--warn', '--ok', '--ok'];
  const INKS = [...new Set([...ROW_INK, ...METER_INK, '--text', '--raised'])];
  const calm = matchMedia('(prefers-reduced-motion: reduce)');
  const cx = (c) => PAD + c * (CW + GX), cy = (r) => PAD + r * (CH + GY);
  const cells = Array.from({ length: ROWS * COLS }, (_, i) => ({ r: Math.floor(i / COLS), c: i % COLS, on: false, at: -99, hit: -99 }));
  const at = (r, c) => cells[r * COLS + c];
  const level = new Array(COLS).fill(0), peak = new Array(COLS).fill(0);
  const ease = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));
  let canvas = null, ctx = null, dpr = 0, raf = 0, stage = '', t0 = 0, prev = 0, ink = {}, seed = 7;
  let step = -1, from = 0, to = 0, bumpAt = -99, lens = { c: 0, r: 0, pc: 0, pr: 0, hit: true };
  const rand = () => ((seed = (seed * 1103515245 + 12345) >>> 0) / 2 ** 32);

  // A beat that sounds like one: drums on the beat, bass on the downbeats, a sparse pad, a busy melody.
  function note(r, c) {
    const x = rand();
    if (r === 3) return c % 4 === 0 || (c % 4 === 2 && x < 0.4) || x < 0.08;
    if (r === 2) return c % 3 === 0 ? x < 0.8 : x < 0.12;
    if (r === 1) return c % 6 === 0 ? x < 0.7 : x < 0.06;
    return x < 0.38;
  }
  function write(c, now, stagger) {
    for (let r = 0; r < ROWS; r++) {
      const p = at(r, c), on = note(r, c);
      if (on !== p.on) { p.on = on; p.at = now + (on ? r * stagger : 0); } else if (on) p.hit = now + r * stagger;
    }
  }
  // A step that starts after editing (or after a reload) still has a beat to play.
  function ensure(now) {
    if (cells.filter((p) => p.on).length >= 10) return;
    for (let c = 0; c < COLS; c++) for (let r = 0; r < ROWS; r++) { const p = at(r, c); p.on = note(r, c); p.at = now + c * 0.03 + r * 0.01; }
  }
  const hitCol = (c, now) => { for (let r = 0; r < ROWS; r++) at(r, c).hit = now; };

  // Boxes get the same corner as the rest of the page: corner-shape squircle, a superellipse with exponent 4.
  function squircle(x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2); ctx.beginPath();
    for (const [qx, qy, a0] of [[x + w - r, y + h - r, 0], [x + r, y + h - r, 0.5], [x + r, y + r, 1], [x + w - r, y + r, 1.5]]) {
      for (let i = 0; i <= 6; i++) {
        const t = (a0 + i / 12) * Math.PI, c = Math.cos(t), s = Math.sin(t);
        ctx.lineTo(qx + r * Math.sign(c) * Math.sqrt(Math.abs(c)), qy + r * Math.sign(s) * Math.sqrt(Math.abs(s)));
      }
    }
    ctx.closePath();
  }
  function box(x, y, w, h, r, fill, alpha) { if (alpha <= 0.003) return; ctx.globalAlpha = Math.min(1, alpha); ctx.fillStyle = fill; squircle(x, y, w, h, r); ctx.fill(); }
  function ring(x, y, w, h, r, alpha) {
    if (alpha <= 0.003) return;
    box(x, y, w, h, r, ink['--text'], alpha * 0.06);
    ctx.globalAlpha = Math.min(1, alpha * 0.9); ctx.strokeStyle = ink['--text']; ctx.lineWidth = 1.5; squircle(x, y, w, h, r); ctx.stroke();
  }
  const column = (c, alpha, fill) => (fill ? box(cx(c) - 2, PAD - 2, CW + 4, GH + 4, 4, ink['--text'], alpha * 0.13) : ring(cx(c) - 2.5, PAD - 2.5, CW + 5, GH + 5, 4.5, alpha));

  // One pad. o.dim fades it back, o.white is how far a hit turns it white.
  function pad(p, now, still, o) {
    const x = cx(p.c), y = cy(p.r), age = now - p.at;
    let h = now - p.hit; if (h < 0) h = 99;
    const fl = still ? (h < 0.15 ? h / 0.15 : Math.exp(-(h - 0.15) * 3)) : Math.exp(-h * 7);
    box(x, y, CW, CH, 3, ink['--raised'], 1);
    if (!p.on && h < 2) box(x, y, CW, CH, 3, ink['--text'], fl * 0.18);
    let vis, sc = 1;
    if (p.on) {
      if (age < 0) return;
      vis = still ? Math.min(1, age / 0.4) : Math.min(1, age / 0.06);
      if (!still) sc = 1 - Math.exp(-8 * age) * Math.cos(16 * age);
    } else {
      vis = Math.max(0, 1 - age / (still ? 0.4 : 0.16));
      if (!still) sc = vis;
    }
    if (vis <= 0) return;
    if (!still) sc += 0.32 * Math.exp(-h * 9) * Math.cos(h * 18);
    const w = CW * sc, hh = CH * sc, px = x + (CW - w) / 2, py = y + (CH - hh) / 2, color = ink[ROW_INK[p.r]];
    if (!still && fl > 0.05) { ctx.shadowColor = color; ctx.shadowBlur = 9 * fl; }
    box(px, py, w, hh, 3 * sc, color, vis * (0.6 + 0.4 * fl) * o.dim);
    ctx.shadowBlur = 0;
    box(px, py, w, hh, 3 * sc, ink['--text'], vis * fl * o.white * o.dim);
  }
  function grid(now, still, dimOf, white = 0.35) { for (const p of cells) pad(p, now, still, { dim: dimOf ? dimOf(p) : 1, white }); }

  function editing(now, s, still) {
    const len = still ? 0.5 : 0.22, n = Math.floor(s / len), c = n % COLS, f = (s - n * len) / len;
    if (n !== step) { step = n; from = to; to = c; write(c, now, still ? 0.08 : 0.04); }
    grid(now, still);
    // The cursor never rests: it walks to the next column and, from the last one, swings back like a carriage return.
    if (still) { column(from, 1 - f); column(to, f); }
    else column(c === COLS - 1 ? c * (1 - ease(f)) : c + f, 1);
  }
  function verifying(now, s, still) {
    ensure(now);
    if (still) {
      const len = 0.4, n = Math.floor(s / len), f = (s - n * len) / len;
      if (n !== step) { step = n; from = to; to = n % COLS; hitCol(to, now); }
      grid(now, still, null, 0.6);
      column(from, 1 - f, true); column(to, f, true);
      return;
    }
    const period = 0.9, sweep = 0.7, n = Math.floor(s / period), k = s - n * period;
    const x = k < sweep ? k / sweep : -1, c = Math.min(COLS - 1, Math.floor(x * COLS));
    if (x >= 0 && n * COLS + c !== step) { step = n * COLS + c; hitCol(c, now); }
    grid(now, still, null, 0.6);
    if (x < 0) return;
    const hx = PAD - 3 + x * (GW + 3);
    box(hx - 16, PAD - 3, 18, GH + 6, 4, ink['--text'], 0.07);
    box(hx - 7, PAD - 3, 9, GH + 6, 4, ink['--text'], 0.08);
    box(hx, PAD - 3, 3, GH + 6, 1.5, ink['--text'], 0.95);
  }
  function listening(now, s, still) {
    ensure(now);
    const len = still ? 0.5 : 0.25, n = Math.floor(s / len), f = (s - n * len) / len;
    if (n !== step) {
      step = n; from = to; to = n % COLS;
      hitCol(to, now);
      if (at(ROWS - 1, to).on) bumpAt = now;
    }
    if (still) { grid(now, still); column(from, 1 - f, true); column(to, f, true); return; }
    ctx.save(); ctx.translate(0, -1.5 * Math.exp(-(now - bumpAt) * 12)); grid(now, still); ctx.restore();
    column(to < from ? to : from + (to - from) * ease(f / 0.3), 1, true);
  }
  function signal(now, s, still) {
    const dt = Math.min(0.1, Math.max(0, now - prev)), sp = still ? 0.6 : 1, beat = still ? 0 : Math.exp(-(s % 0.5) * 7);
    for (let c = 0; c < COLS; c++) {
      const wob = Math.abs(Math.sin(s * 3.1 * sp + c * 0.9) * Math.sin(s * 1.7 * sp + c * 2.3));
      const target = ROWS * Math.min(1, 0.12 + 0.62 * wob + 0.35 * beat * (1 - c / COLS));
      const rate = target > level[c] ? (still ? 3 : 18) : (still ? 2 : 6);
      level[c] += (target - level[c]) * (1 - Math.exp(-dt * rate));
      peak[c] = Math.max(level[c], peak[c] - dt * 2.2);
      for (let r = 0; r < ROWS; r++) {
        const x = cx(c), y = cy(r), amt = Math.max(0, Math.min(1, level[c] - (ROWS - 1 - r)));
        box(x, y, CW, CH, 3, ink['--raised'], 1);
        box(x, y, CW, CH, 3, ink[METER_INK[r]], amt * 0.9);
      }
      if (!still) box(cx(c), PAD + GH - (peak[c] / ROWS) * GH - 1, CW, 2, 1, ink['--text'], 0.75);
    }
  }
  function analyzing(now, s, still) {
    ensure(now);
    const period = still ? 1.2 : 0.85, glide = still ? 1.2 : 0.35, n = Math.floor(s / period), k = s - n * period, g = still ? k / period : ease(k / glide);
    if (n !== step) {
      step = n; lens.pc = lens.c; lens.pr = lens.r; lens.hit = 0;
      let best = -1;
      for (let i = 0; i < 4; i++) {
        const c = Math.floor(rand() * (COLS - 2)), r = Math.floor(rand() * (ROWS - 1));
        if (c === lens.c && r === lens.r) continue;
        let cnt = 0; for (let dc = 0; dc < 3; dc++) for (let dr = 0; dr < 2; dr++) cnt += at(r + dr, c + dc).on;
        if (cnt > best) { best = cnt; lens.c = c; lens.r = r; }
      }
    }
    // Once there, it reads the spot column by column.
    const look = still ? 0.35 : glide, gap = still ? 0.25 : 0.12;
    while (lens.hit < 3 && k >= look + lens.hit * gap) { for (let dr = 0; dr < 2; dr++) at(lens.r + dr, lens.c + lens.hit).hit = now; lens.hit++; }
    const inside = (p, c, r) => (p.c >= c && p.c < c + 3 && p.r >= r && p.r < r + 2 ? 1 : 0);
    const lc = lens.pc + (lens.c - lens.pc) * g, lr = lens.pr + (lens.r - lens.pr) * g;
    const cover = (p) => Math.max(0, 1 - Math.max(Math.max(lc - p.c, p.c - (lc + 2)), Math.max(lr - p.r, p.r - (lr + 1)), 0));
    grid(now, still, (p) => 0.3 + 0.7 * (still ? (1 - g) * inside(p, lens.pc, lens.pr) + g * inside(p, lens.c, lens.r) : cover(p)));
    const lensAt = (c, r, a) => ring(cx(0) + c * (CW + GX) - 2.5, cy(0) + r * (CH + GY) - 2.5, 3 * CW + 2 * GX + 5, 2 * CH + GY + 5, 5, a);
    if (still) { lensAt(lens.pc, lens.pr, 1 - g); lensAt(lens.c, lens.r, g); } else lensAt(lc, lr, 1);
  }
  const STAGES = { editing, verifying, listening, signal, analyzing };

  function fit() {
    const d = devicePixelRatio || 1;
    if (d === dpr) return;
    dpr = d; canvas.width = Math.round(W * d); canvas.height = Math.round(H * d); ctx.setTransform(d, 0, 0, d, 0, 0);
  }
  function frame(ms) {
    raf = requestAnimationFrame(frame);
    const now = ms / 1000;
    if (!t0) t0 = now;
    fit(); ctx.clearRect(0, 0, W, H);
    STAGES[stage](now, now - t0, calm.matches);
    ctx.globalAlpha = 1; prev = now;
  }
  window.waitAnim = {
    mount(box) {
      canvas = document.createElement('canvas'); canvas.className = 'waitAnim'; canvas.setAttribute('aria-hidden', 'true');
      canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
      ctx = canvas.getContext('2d'); box.prepend(canvas);
    },
    // Called on every render while the AI works; a new step restarts its moves but keeps the written beat.
    run(next) {
      if (!ctx) return;
      next = STAGES[next] ? next : 'editing';
      const st = getComputedStyle(document.documentElement);
      for (const name of INKS) ink[name] = st.getPropertyValue(name).trim() || '#C4C4C4';
      if (next !== stage || !raf) { stage = next; t0 = 0; step = -1; from = to = 0; lens.hit = 3; }
      if (!raf) raf = requestAnimationFrame(frame);
    },
    stop() { cancelAnimationFrame(raf); raf = 0; },
  };
})();
