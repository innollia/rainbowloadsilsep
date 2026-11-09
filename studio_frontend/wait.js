// The wait while the AI works, drawn as music: a small staff that shows which step is running.
// editing: notes are written in one by one · verifying: a fast playhead runs through them
// listening: a slow playhead plays them and each sounds a ring · signal: the notes turn into level meters
// analyzing: a loupe goes from note to note. Reduced motion gets the still staff.
(() => {
  const W = 168, H = 36, GAP = 5, MID = H / 2, STEP = GAP / 2;
  const COLOR = { editing: '--melody', verifying: '--bass', listening: '--pad', signal: '--drums', analyzing: '--warn' };
  const still = matchMedia('(prefers-reduced-motion: reduce)');
  let canvas = null, ctx = null, stage = 'editing', raf = 0, t0 = 0, notes = [], seed = 1, nextAt = 0;
  const rand = () => ((seed = (seed * 1103515245 + 12345) >>> 0) / 2 ** 32);
  // A short tune that moves mostly by steps, like a melody being written.
  const pitch = (prev) => Math.max(-4, Math.min(4, prev + [-2, -1, -1, 0, 1, 1, 2][Math.floor(rand() * 7)]));
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#C4C4C4';

  function reset() {
    notes = []; seed = 7; let p = 0;
    for (let x = 14; x < W - 24; x += 13) { p = pitch(p); notes.push({ x, p, born: -1 }); }
  }
  function head(x, y, r, fill) {
    ctx.save(); ctx.translate(x, y); ctx.rotate(-0.35); ctx.beginPath(); ctx.ellipse(0, 0, r * 1.3, r, 0, 0, Math.PI * 2);
    ctx.fillStyle = fill; ctx.fill(); ctx.restore();
    ctx.beginPath(); ctx.moveTo(x + r * 1.15, y); ctx.lineTo(x + r * 1.15, y - 11); ctx.strokeStyle = fill; ctx.lineWidth = 1; ctx.stroke();
  }
  function staff(line) {
    ctx.strokeStyle = line; ctx.lineWidth = 1; ctx.globalAlpha = 0.45;
    for (let i = -2; i <= 2; i++) { const y = Math.round(MID + i * GAP) + 0.5; ctx.beginPath(); ctx.moveTo(2, y); ctx.lineTo(W - 2, y); ctx.stroke(); }
    ctx.globalAlpha = 1;
  }
  function draw(now) {
    const s = (now - t0) / 1000, ink = css(COLOR[stage] || COLOR.editing), line = css('--text3');
    ctx.clearRect(0, 0, W, H); staff(line);
    if (stage === 'editing' && !still.matches) {
      // The pen writes a new note at the right; the page slides left.
      if (s >= nextAt) { nextAt = s + 0.38; notes.push({ x: W - 18, p: pitch(notes.at(-1)?.p ?? 0), born: s }); }
      for (const n of notes) n.x -= 0.55;
      notes = notes.filter((n) => n.x > 6);
      for (const n of notes) { const age = n.born < 0 ? 1 : Math.min(1, (s - n.born) / 0.18); head(n.x, MID - n.p * STEP, 2.6 * (0.6 + 0.4 * age), ink); }
      if (Math.floor(s * 3) % 2) { ctx.fillStyle = ink; ctx.fillRect(W - 9, MID - 9, 1.5, 18); }
    } else if (stage === 'signal' && !still.matches) {
      for (const n of notes) {
        const lvl = 0.35 + 0.65 * Math.abs(Math.sin(s * 5.3 + n.x * 0.21) * Math.sin(s * 2.1 + n.p));
        const h = lvl * (H - 8); ctx.fillStyle = ink; ctx.globalAlpha = 0.85; ctx.fillRect(n.x - 2.5, H - 4 - h, 5, h);
      }
      ctx.globalAlpha = 1;
    } else {
      const sweep = stage === 'verifying' ? 0.9 : stage === 'listening' ? 2.6 : 0;
      const at = sweep && !still.matches ? ((s % sweep) / sweep) * W : -99;
      const focus = stage === 'analyzing' && !still.matches ? notes[Math.floor(s * 1.6) % notes.length] : null;
      for (const n of notes) {
        const y = MID - n.p * STEP, passed = at - n.x;
        const lit = passed >= 0 && passed < 14, big = focus === n;
        head(n.x, y + (stage === 'listening' && lit ? -1.5 : 0), big ? 3.4 : 2.6, lit || big || still.matches || !sweep && !focus ? ink : line);
        if (stage === 'listening' && passed >= 0 && passed < 40) {
          ctx.beginPath(); ctx.arc(n.x, y, 3 + passed * 0.35, 0, Math.PI * 2); ctx.strokeStyle = ink; ctx.globalAlpha = 1 - passed / 40; ctx.stroke(); ctx.globalAlpha = 1;
        }
      }
      if (sweep && at >= 0) { ctx.fillStyle = ink; ctx.globalAlpha = 0.8; ctx.fillRect(at, 3, 1.5, H - 6); ctx.globalAlpha = 1; }
      if (focus) { ctx.beginPath(); ctx.arc(focus.x, MID - focus.p * STEP, 8, 0, Math.PI * 2); ctx.strokeStyle = ink; ctx.lineWidth = 1.5; ctx.stroke(); }
    }
    raf = still.matches ? 0 : requestAnimationFrame(draw);
  }
  window.waitAnim = {
    mount(box) {
      canvas = document.createElement('canvas'); canvas.className = 'waitAnim'; canvas.setAttribute('aria-hidden', 'true');
      const dpr = devicePixelRatio || 1; canvas.width = W * dpr; canvas.height = H * dpr; canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
      ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr); box.prepend(canvas); reset(); t0 = performance.now();
    },
    // Called on every render while the AI works; only a change of step restarts the picture.
    run(next) {
      if (!ctx) return;
      if (next !== stage || !raf) { if (next !== stage) { stage = next; reset(); nextAt = 0; t0 = performance.now(); } cancelAnimationFrame(raf); raf = requestAnimationFrame(draw); }
    },
    stop() { cancelAnimationFrame(raf); raf = 0; },
  };
})();
