// Seeded album art. The seed picks a drawing method, then every number in it.
// Elements carry data-* motion hints (spin, pulse, band) so motion can follow the real output without redrawing.
(() => {
  const PALETTES = [
    ['#10131F', '#F2C14E', '#F78154', '#4D9078', '#B4436C'],
    ['#F4E9DA', '#22223B', '#C9594B', '#E0A458', '#3C6E71'],
    ['#0B2A3C', '#3FC1C9', '#F5F5F5', '#FC5185', '#F9ED69'],
    ['#1B2A21', '#A7C957', '#F2E8CF', '#BC4749', '#6A994E'],
    ['#24123A', '#FF6B9D', '#FFC75F', '#C34BFF', '#7DE2D1'],
    ['#E76F51', '#264653', '#F4A261', '#E9C46A', '#FDF0D5'],
    ['#EFEFEA', '#111111', '#D7263D', '#1B998B', '#2E294E'],
    ['#0A0A0A', '#00F5D4', '#F15BB5', '#FEE440', '#9B5DE5'],
  ];

  function random(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const n = (v) => +v.toFixed(2);
  const motion = (m) => Object.entries(m).map(([k, v]) => ` data-${k}="${v}"`).join('');
  const pick = (r, list) => list[Math.floor(r() * list.length)];
  const poly = (pts) => `M${pts.map(([x, y]) => `${n(x)} ${n(y)}`).join('L')}Z`;
  const rgb = (hex) => { const v = parseInt(hex.slice(1), 16); return [v >> 16, (v >> 8) & 255, v & 255]; };
  const light = (hex) => { const [a, b, c] = rgb(hex); return a * 0.3 + b * 0.59 + c * 0.11 > 140; };
  // k < 0 darkens toward black, k > 0 lightens toward white.
  const shade = (hex, k) => '#' + rgb(hex).map((x) => Math.round(k < 0 ? x * (1 + k) : x + (255 - x) * k).toString(16).padStart(2, '0')).join('');
  const text = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  // Many round dots in a few elements: dots of one size share a path of round-capped zero-length strokes.
  function dots(list, color, extra = '') {
    const by = {};
    for (const [x, y, s] of list) { const k = Math.max(1, Math.round(s * 8)); (by[k] ||= []).push(`M${x.toFixed(1)} ${y.toFixed(1)}h.01`); }
    return Object.entries(by).map(([k, d]) => `<path d="${d.join('')}" stroke="${color}" stroke-width="${k / 4}" stroke-linecap="round"${extra}/>`).join('');
  }

  // A smooth random surface; several methods read their shapes off it.
  function surface(r) {
    const waves = Array.from({ length: 4 }, () => [0.02 + r() * 0.07, 0.02 + r() * 0.07, r() * 6.28]);
    return (x, y) => waves.reduce((sum, [a, b, c]) => sum + Math.sin(x * a + y * b + c), 0) / waves.length;
  }

  // What a cover may know about its song: tempo, which parts play, and the name. A missing song falls back to a plain one.
  function songOf(song) {
    const roles = (song?.tracks || []).map((t) => t.role || 'other'), name = String(song?.name || '');
    let hash = 7; for (const c of name) hash = (Math.imul(hash, 31) + c.codePointAt(0)) >>> 0;
    return { bpm: Math.min(220, Math.max(50, +song?.bpm || 120)), roles: roles.length ? roles : ['drums', 'bass', 'melody'], name, hash, chars: [...name].map((c) => c.codePointAt(0)) };
  }

  const METHODS = {
    contour(r, ink) {
      const f = surface(r), count = 15, cx = 30 + r() * 40, cy = 30 + r() * 40;
      let s = '';
      for (let i = 0; i < count; i++) {
        const size = 78 - i * 5;
        let d = '';
        for (let k = 0; k < 64; k++) {
          const a = k / 64 * Math.PI * 2, x = cx + Math.cos(a) * size, y = cy + Math.sin(a) * size;
          const grow = size * (1 + f(x, y) * 0.34);
          d += `${k ? 'L' : 'M'}${n(cx + Math.cos(a) * grow)} ${n(cy + Math.sin(a) * grow)}`;
        }
        s += `<path d="${d}Z" fill="${ink[i % ink.length]}"${i % 2 ? ' fill-opacity=".82"' : ''}/>`;
      }
      return `<g${motion({ cx: n(cx), cy: n(cy), band: 4, pulse: 0.05 })}>${s}</g>`;
    },
    flow(r, ink) {
      const f = surface(r), turn = 2 + r() * 3;
      let s = '';
      for (let i = 0; i < 170; i++) {
        let x = r() * 120 - 10, y = r() * 120 - 10, d = `M${n(x)} ${n(y)}`;
        for (let k = 0; k < 24; k++) { const a = f(x, y) * turn; x += Math.cos(a) * 2.4; y += Math.sin(a) * 2.4; d += `L${n(x)} ${n(y)}`; }
        s += `<path d="${d}" fill="none" stroke="${ink[i % ink.length]}" stroke-width="${n(0.4 + r() * 1.5)}" stroke-opacity="${n(0.45 + r() * 0.55)}" stroke-linecap="round"/>`;
      }
      return `<g${motion({ band: 8, pulse: 0.04 })}>${s}</g>`;
    },
    truchet(r, ink) {
      const cells = 6 + Math.floor(r() * 5), size = 100 / cells, wide = size * (0.2 + r() * 0.16);
      let back = '', lines = '';
      for (let y = 0; y < cells; y++) {
        for (let x = 0; x < cells; x++) {
          const X = x * size, Y = y * size, h = size / 2, sweep = r() < 0.5;
          if (r() < 0.3) back += `<rect x="${n(X)}" y="${n(Y)}" width="${n(size)}" height="${n(size)}" fill="${ink[(x + y) % ink.length]}" fill-opacity=".28"/>`;
          const d = sweep
            ? `M${n(X + h)} ${n(Y)}A${n(h)} ${n(h)} 0 0 1 ${n(X)} ${n(Y + h)}M${n(X + size)} ${n(Y + h)}A${n(h)} ${n(h)} 0 0 0 ${n(X + h)} ${n(Y + size)}`
            : `M${n(X + h)} ${n(Y)}A${n(h)} ${n(h)} 0 0 0 ${n(X + size)} ${n(Y + h)}M${n(X)} ${n(Y + h)}A${n(h)} ${n(h)} 0 0 1 ${n(X + h)} ${n(Y + size)}`;
          lines += `<path d="${d}" fill="none" stroke="${ink[Math.floor(r() * ink.length)]}" stroke-width="${n(wide)}" stroke-linecap="round"/>`;
        }
      }
      return `${back}<g${motion({ band: 6, pulse: 0.03 })}>${lines}</g>`;
    },
    horizon(r, ink, bg, id) {
      const sunX = 25 + r() * 50, sunY = 28 + r() * 18, sun = 15 + r() * 10, f = surface(r);
      let s = `<defs><linearGradient id="${id}" x2="0" y2="1"><stop offset="0" stop-color="${ink[0]}"/><stop offset=".75" stop-color="${ink[1]}"/></linearGradient></defs><rect width="100" height="100" fill="url(#${id})"/>`;
      s += `<circle cx="${n(sunX)}" cy="${n(sunY)}" r="${n(sun)}" fill="${ink[2]}"${motion({ cx: n(sunX), cy: n(sunY), band: 3, pulse: 0.22 })}/>`;
      for (let i = 0; i < 5; i++) s += `<rect x="0" y="${n(sunY + i * sun * 0.2)}" width="100" height="${n(0.5 + i * 0.5)}" fill="${ink[1]}" fill-opacity=".85"/>`;
      for (let l = 0; l < 7; l++) {
        const base = 50 + l * 8, tall = 11 - l;
        let d = `M0 100L0 ${n(base)}`;
        for (let x = 0; x <= 100; x += 2.5) d += `L${x} ${n(base + f(x * 1.6 + l * 40, l * 30) * tall + Math.sin(x * 0.4 + l) * 1.4)}`;
        s += `<path d="${d}L100 100Z" fill="${l % 2 ? ink[3] : bg}" fill-opacity="${n(0.5 + l * 0.08)}"/>`;
      }
      return s;
    },
    bloom(r, ink) {
      const rings = 6;
      let s = '';
      for (let g = 0; g < rings; g++) {
        const count = 7 + Math.floor(r() * 4) + g * 2, far = 50 - g * 7, wide = far * (0.2 + r() * 0.16);
        let petals = '';
        for (let i = 0; i < count; i++) {
          petals += `<path d="M50 50Q${n(50 - wide)} ${n(50 - far * 0.6)} 50 ${n(50 - far)}Q${n(50 + wide)} ${n(50 - far * 0.6)} 50 50Z" transform="rotate(${n(i / count * 360 + g * 11)} 50 50)" fill="${ink[(i + g) % ink.length]}" fill-opacity="${n(0.55 + r() * 0.4)}"/>`;
        }
        s += `<g${motion({ spin: n((g % 2 ? -1 : 1) * (2 + g * 1.5)), band: g * 5, pulse: 0.08 })}>${petals}</g>`;
      }
      return s + `<circle cx="50" cy="50" r="${n(3 + r() * 3)}" fill="${ink[0]}"/>`;
    },
    weave(r, ink) {
      const f = surface(r), sets = [0, 90 + r() * 30];
      let s = '';
      sets.forEach((angle, g) => {
        let lines = '';
        for (let i = 0; i < 46; i++) {
          const base = -20 + i * 3.1;
          let d = '';
          for (let x = -24; x <= 124; x += 3) d += `${x > -24 ? 'L' : 'M'}${x} ${n(base + f(x, base + g * 90) * 16)}`;
          lines += `<path d="${d}" fill="none" stroke="${ink[(i >> 2) % ink.length]}" stroke-width="${n(0.5 + (i % 5) * 0.14)}"/>`;
        }
        s += `<g transform="rotate(${n(angle)} 50 50)"><g${motion({ band: 6 + g * 12, pulse: 0.04 })}>${lines}</g></g>`;
      });
      return s;
    },
    mosaic(r, ink, bg) {
      const leaves = [];
      const cut = (x, y, w, h, depth) => {
        if (depth > 4 || (depth > 1 && r() < 0.2)) { leaves.push([x, y, w, h]); return; }
        const across = w > h ? true : w < h ? false : r() < 0.5, part = 0.35 + r() * 0.3;
        if (across) { cut(x, y, w * part, h, depth + 1); cut(x + w * part, y, w * (1 - part), h, depth + 1); }
        else { cut(x, y, w, h * part, depth + 1); cut(x, y + h * part, w, h * (1 - part), depth + 1); }
      };
      cut(0, 0, 100, 100, 0);
      return leaves.map(([x, y, w, h], i) => {
        const main = ink[Math.floor(r() * ink.length)], other = r() < 0.3 ? bg : ink[Math.floor(r() * ink.length)], m = Math.min(w, h), kind = Math.floor(r() * 4);
        const cx = x + w / 2, cy = y + h / 2;
        let s = `<rect x="${n(x)}" y="${n(y)}" width="${n(w)}" height="${n(h)}" fill="${main}"/>`;
        if (kind === 0) s += `<circle cx="${n(cx)}" cy="${n(cy)}" r="${n(m * 0.36)}" fill="${other}"${motion({ cx: n(cx), cy: n(cy), band: i % 48, pulse: 0.25 })}/>`;
        else if (kind === 1) s += `<path d="M${n(x)} ${n(y)}h${n(m)}a${n(m)} ${n(m)} 0 0 1 ${n(-m)} ${n(m)}Z" fill="${other}"/>`;
        else if (kind === 2) for (let k = 0; k < 6; k++) s += `<rect x="${n(x)}" y="${n(y + (k + 0.25) * h / 6)}" width="${n(w)}" height="${n(h / 14)}" fill="${other}"/>`;
        else s += `<path d="M${n(x)} ${n(y + h)}L${n(x + w)} ${n(y)}V${n(y + h)}Z" fill="${other}" fill-opacity=".85"/>`;
        return s;
      }).join('');
    },
    nebula(r, ink, bg, id) {
      let defs = '', clouds = '', stars = '';
      ink.forEach((color, i) => { defs += `<radialGradient id="${id}${i}"><stop offset="0" stop-color="${color}" stop-opacity=".8"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></radialGradient>`; });
      for (let i = 0; i < 18; i++) clouds += `<circle cx="${n(r() * 100)}" cy="${n(50 + (r() - 0.5) * 80)}" r="${n(14 + r() * 26)}" fill="url(#${id}${i % ink.length})"/>`;
      for (let i = 0; i < 110; i++) stars += `<circle cx="${n(r() * 100)}" cy="${n(r() * 100)}" r="${n(0.12 + r() ** 3 * 0.7)}" fill="#fff" fill-opacity="${n(0.4 + r() * 0.6)}"/>`;
      return `<defs>${defs}</defs><g${motion({ spin: 2 + n(r() * 3), band: 3, pulse: 0.05 })}>${clouds}</g>${stars}`;
    },
    // Stacked pulse lines, each hiding the ones behind it; every part of the song raises its own ridge.
    ridges(r, ink, bg, id, song) {
      const lines = 30 + Math.floor(r() * 14), gap = 68 / lines, rough = 0.25 + song.bpm / 300;
      const peaks = song.roles.map((_, i, all) => [32 + (i + 0.5) / all.length * 36 + (r() - 0.5) * 6, 2 + r() * 5, 0.4 + r()]);
      const lineInk = light(bg) ? ink.filter((c) => !light(c)) : ink.filter((c) => light(c) || c !== bg);
      const pen = lineInk.length ? lineInk : ink;
      let s = '';
      for (let i = 0; i < lines; i++) {
        const y0 = 20 + i * gap, amp = gap * (2.5 + r() * 3);
        const lift = peaks.map(([, , k]) => k * (0.3 + r() * 1.1));
        let d = `M-2 ${n(y0)}`, v = 0;
        for (let x = 0; x <= 100; x += 1.25) {
          const env = x > 16 && x < 84 ? Math.sin((x - 16) / 68 * Math.PI) ** 2 : 0;
          v = v * 0.55 + r() * 0.45;
          let h = 0; peaks.forEach(([px, w], k) => { h += lift[k] * Math.exp(-(((x - px) / w) ** 2)); });
          d += `L${n(x)} ${n(y0 - env * amp * (h + v * rough))}`;
        }
        s += `<g${motion({ cx: 50, cy: n(y0), band: (i * 3) % 40, pulse: 0.06 })}><path d="${d}L102 ${n(y0)}L102 104L-2 104Z" fill="${bg}" stroke="${pen[Math.floor(i / lines * pen.length)]}" stroke-width="${n(0.45 + r() * 0.3)}" stroke-linejoin="round"/></g>`;
      }
      return s;
    },
    // Greedy circle packing; each part of the song paints its circles its own way (drums as cones, bass solid, melody rings).
    packing(r, ink, bg, id, song) {
      const big = 6 + (200 - song.bpm) / 12, found = [];
      for (let t = 0; t < 1400 && found.length < 170; t++) {
        const x = r() * 104 - 2, y = r() * 104 - 2;
        let rad = big * (t < 40 ? 1.9 : 1);
        for (const [cx, cy, cr] of found) { rad = Math.min(rad, Math.hypot(x - cx, y - cy) - cr - 0.7); if (rad < 0.9) break; }
        if (rad >= 0.9) found.push([x, y, rad]);
      }
      found.sort((a, b) => b[2] - a[2]);
      return found.map(([x, y, rad], i) => {
        const role = song.roles[Math.floor(r() * song.roles.length)], c = ink[Math.floor(r() * ink.length)], o = ink[(ink.indexOf(c) + 1 + Math.floor(r() * 3)) % ink.length];
        let s = `<circle cx="${n(x)}" cy="${n(y)}" r="${n(rad)}" fill="${c}"/>`;
        if (role === 'drums') for (let k = 1; k < 4; k++) s += `<circle cx="${n(x)}" cy="${n(y)}" r="${n(rad * (1 - k * 0.24))}" fill="${k % 2 ? o : c}"/>`;
        else if (role === 'melody' || role === 'lead') s = `<circle cx="${n(x)}" cy="${n(y)}" r="${n(rad * 0.84)}" fill="none" stroke="${c}" stroke-width="${n(rad * 0.3)}"/>`;
        else if (role === 'pad' || role === 'chords') s += `<path d="M${n(x - rad)} ${n(y)}A${n(rad)} ${n(rad)} 0 0 0 ${n(x + rad)} ${n(y)}Z" fill="${o}"/>`;
        else if (role === 'vocal') s += `<circle cx="${n(x)}" cy="${n(y)}" r="${n(rad * 0.3)}" fill="${bg}"/>`;
        return i < 28 ? `<g${motion({ cx: n(x), cy: n(y), band: Math.min(63, i * 2), pulse: 0.12 })}>${s}</g>` : s;
      }).join('');
    },
    // Print halftone: two or three screens at different angles, slightly off register, overprinting each other.
    halftone(r, ink, bg, id, song) {
      const f = surface(r), sx = 25 + r() * 50, sy = 25 + r() * 50, rad = 24 + r() * 20, kind = Math.floor(r() * 3);
      const tone = (x, y) => {
        const d = Math.hypot(x - sx, y - sy) / rad;
        const base = kind === 0 ? 1 - d : kind === 1 ? Math.abs(Math.sin(d * 3.2)) : (x + y) / 200;
        return Math.max(0, Math.min(1, base * 0.8 + (f(x, y) + 1) * 0.2));
      };
      const layers = Math.min(3, Math.max(2, song.roles.length)), step = 3 + r() * 1.6, blend = light(bg) ? 'multiply' : 'screen';
      let s = '';
      for (let L = 0; L < layers; L++) {
        const a = ((song.bpm * 7) % 90 + L * 30) * Math.PI / 180, c = Math.cos(a), si = Math.sin(a), ox = (r() - 0.5) * 2.4, oy = (r() - 0.5) * 2.4, list = [];
        for (let i = -40; i <= 40; i++) for (let j = -40; j <= 40; j++) {
          const x = 50 + (i * c - j * si) * step, y = 50 + (i * si + j * c) * step;
          if (x < -3 || x > 103 || y < -3 || y > 103) continue;
          const v = L === 0 ? tone(x, y) : L === 1 ? 1 - tone(x, y) * 0.85 : (f(x + 40, y - 30) + 1) / 2;
          if (v > 0.06) list.push([x + ox, y + oy, step * 0.62 * Math.sqrt(v)]);
        }
        s += `<g style="mix-blend-mode:${blend}"${motion({ band: L * 18 + 2, pulse: 0.03 })}>${dots(list, ink[L])}</g>`;
      }
      return s;
    },
    // Two line screens laid over each other; the slow turn of one makes the interference bands crawl.
    moire(r, ink, bg, id, song) {
      const gap = 1.5 + r() * 1.1, w = n(gap * (0.4 + r() * 0.15)), rings = r() < 0.5;
      const set = (cx, cy) => {
        let d = '';
        if (rings) for (let rad = gap; rad < 150; rad += gap) d += `M${n(cx - rad)} ${n(cy)}a${n(rad)} ${n(rad)} 0 1 0 ${n(2 * rad)} 0a${n(rad)} ${n(rad)} 0 1 0 ${n(-2 * rad)} 0`;
        else for (let y = -60; y < 160; y += gap) d += `M-60 ${n(y)}H160`;
        return d;
      };
      const sets = Math.min(3, Math.max(2, song.roles.length - 1)), tilt = 2 + (song.bpm % 40) / 8;
      let s = '';
      for (let k = 0; k < sets; k++) {
        const cx = rings ? 50 + (r() - 0.5) * 40 : 50, cy = rings ? 50 + (r() - 0.5) * 40 : 50, turn = rings ? 0 : (k - (sets - 1) / 2) * tilt + (r() - 0.5) * 3;
        const body = `<path d="${set(cx, cy)}" fill="none" stroke="${ink[k]}" stroke-width="${w}" transform="rotate(${n(turn)} 50 50)"/>`;
        s += k ? `<g${motion({ spin: n((k % 2 ? 1 : -1) * (1 + r() * 2)), band: k * 12 }) }>${body}</g>` : body;
      }
      if (r() < 0.5) s += `<circle cx="50" cy="50" r="${n(14 + r() * 10)}" fill="${bg}" stroke="${ink[3]}" stroke-width="${n(1 + r() * 2)}"/>`;
      return s;
    },
    // One-dimensional cellular automaton grown row by row; the song name seeds the first row and picks the rule.
    automaton(r, ink, bg, id, song) {
      const RULES = [18, 22, 26, 30, 54, 60, 86, 90, 102, 110, 122, 126, 146, 150, 182];
      const rule = RULES[(song.hash + Math.floor(r() * RULES.length)) % RULES.length], W = 30 + Math.floor(r() * 24), size = 100 / W;
      const row0 = Array(W).fill(0), seeds = 1 + (song.hash % 3);
      for (let k = 0; k < seeds; k++) row0[Math.floor((k + 1) / (seeds + 1) * W) + ((song.chars[k] || 0) % 5) - 2] = 1;
      let row = row0;
      const runs = ink.map(() => []);
      for (let y = 0; y < W + 1; y++) {
        for (let x = 0; x < W;) {
          if (!row[x]) { x++; continue; }
          let e = x; while (e + 1 < W && row[e + 1]) e++;
          const len = e - x + 1, k = len === 1 ? 0 : len < 4 ? 1 : len < 8 ? 2 : 3;
          runs[k].push(`M${n((x + 0.5) * size)} ${n((y + 0.5) * size)}H${n((e + 0.5) * size)}`);
          x = e + 1;
        }
        row = row.map((_, i) => (rule >> ((row[(i + W - 1) % W] << 2) | (row[i] << 1) | row[(i + 1) % W])) & 1);
      }
      const turn = pick(r, [0, 0, 90, 180]);
      return `<g transform="rotate(${turn} 50 50)"><g${motion({ band: 2, pulse: 0.03 })}>${runs.map((d, k) => d.length ? `<path d="${d.join('')}" stroke="${ink[k]}" stroke-width="${n(size * 0.8)}" stroke-linecap="round"/>` : '').join('')}</g></g>`;
    },
    // A damped two-pendulum drawing machine; the tempo sets the frequency ratio, the parts set how many pendulums swing.
    harmonograph(r, ink, bg, id, song) {
      const RATIOS = [[1, 2], [2, 3], [3, 4], [1, 3], [3, 5], [2, 5], [4, 5], [1, 1]];
      const [p, q] = RATIOS[(Math.round(song.bpm / 8) + Math.floor(r() * 2)) % RATIOS.length];
      const swing = Math.min(4, Math.max(2, song.roles.length)), pend = [];
      for (let k = 0; k < swing; k++) pend.push({ axis: k % 2, f: (k % 2 ? q : p) * (k > 1 ? 1 + Math.floor(r() * 2) : 1) + (r() - 0.5) * 0.03, ph: r() * 6.28, a: k > 1 ? 0.25 + r() * 0.3 : 1, d: 0.0015 + r() * 0.0025 });
      const total = Math.max(...[0, 1].map((ax) => pend.filter((x) => x.axis === ax).reduce((s, x) => s + x.a, 0))), scale = 47 / total, steps = 3200, dt = 0.06;
      const paths = ink.map(() => '');
      for (let i = 0; i < steps; i++) {
        const t = i * dt; let x = 0, y = 0;
        for (const pd of pend) { const v = pd.a * Math.sin(pd.f * t + pd.ph) * Math.exp(-pd.d * t * 2.2); if (pd.axis) y += v; else x += v; }
        const part = Math.floor(i / steps * ink.length);
        paths[part] += `${paths[part] ? 'L' : 'M'}${n(50 + x * scale)} ${n(50 + y * scale)}`;
      }
      const thin = n(0.3 + r() * 0.25);
      const defs = paths.map((d, k) => `<path id="${id}h${k}" d="${d}" fill="none"/>`).join('');
      return `<defs>${defs}</defs><g${motion({ spin: n(2 + r() * 3), band: 3, pulse: 0.05 })}>${paths.map((_, k) => `<use href="#${id}h${k}" stroke="${ink[k]}" stroke-width="2.2" stroke-opacity=".1"/><use href="#${id}h${k}" stroke="${ink[k]}" stroke-width="${thin}" stroke-opacity="${n(0.95 - k * 0.1)}"/>`).join('')}</g>`;
    },
    // Voronoi cells around a point of impact, leaded like stained glass; the name sets where the hit landed.
    shatter(r, ink, bg, id, song) {
      const hx = 22 + (song.hash % 56), hy = 22 + ((song.hash >>> 8) % 56), count = 14 + Math.round(song.bpm / 6), sites = [];
      for (let i = 0; i < count; i++) {
        if (i < count * 0.55) { const a = r() * 6.28, d = 2 + r() ** 1.6 * 40; sites.push([hx + Math.cos(a) * d, hy + Math.sin(a) * d]); }
        else sites.push([r() * 100, r() * 100]);
      }
      const clip = (pts, [ax, ay], [bx, by]) => {
        const mx = (ax + bx) / 2, my = (ay + by) / 2, nx = bx - ax, ny = by - ay, side = ([x, y]) => (x - mx) * nx + (y - my) * ny, out = [];
        pts.forEach((p, i) => {
          const q = pts[(i + 1) % pts.length], sp = side(p), sq = side(q);
          if (sp <= 0) out.push(p);
          if ((sp <= 0) !== (sq <= 0)) { const t = sp / (sp - sq); out.push([p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]); }
        });
        return out;
      };
      const lead = n(0.6 + r() * 0.9);
      return sites.map((site, i) => {
        let cell = [[-2, -2], [102, -2], [102, 102], [-2, 102]];
        for (const other of sites) if (other !== site && cell.length) cell = clip(cell, site, other);
        if (cell.length < 3) return '';
        const cx = cell.reduce((s, p) => s + p[0], 0) / cell.length, cy = cell.reduce((s, p) => s + p[1], 0) / cell.length;
        const far = Math.hypot(cx - hx, cy - hy), c = ink[(Math.floor(far / 14) + (r() < 0.25 ? 1 : 0)) % ink.length];
        const inner = cell.map(([x, y]) => [cx + (x - cx) * 0.55, cy + (y - cy) * 0.55]);
        return `<g${motion({ cx: n(cx), cy: n(cy), band: Math.min(63, Math.floor(far)), pulse: 0.08 })}><path d="${poly(cell)}" fill="${c}" stroke="${bg}" stroke-width="${lead}" stroke-linejoin="round"/>${r() < 0.4 ? `<path d="${poly(inner)}" fill="#fff" fill-opacity=".14"/>` : ''}</g>`;
      }).join('');
    },
    // Euclidean rhythm wheels: one ring per part, hits spread as evenly as the steps allow, each ring turning at its own speed.
    euclid(r, ink, bg, id, song) {
      const roles = song.roles.slice(0, 7), steps = song.bpm >= 150 ? 16 : song.bpm >= 100 ? pick(r, [12, 16]) : pick(r, [8, 12]);
      const HITS = { drums: 4, bass: 3, melody: 5, lead: 5, chords: 2, pad: 2, vocal: 3 }, gapR = 38 / roles.length, arc = 360 / steps;
      let s = `<circle cx="50" cy="50" r="47" fill="none" stroke="${ink[0]}" stroke-opacity=".25" stroke-width=".4"/>`;
      roles.forEach((role, i) => {
        const R = 44 - i * gapR, k = Math.min(steps - 1, (HITS[role] || 3) * steps / 8 + Math.floor(r() * 3) - 1 | 0), turn = Math.floor(r() * steps), c = ink[i % ink.length];
        const wide = n(gapR * (0.45 + r() * 0.2));
        let ring = `<circle cx="50" cy="50" r="${n(R)}" fill="none" stroke="${c}" stroke-opacity=".18" stroke-width="${wide}"/>`, hits = [];
        for (let j = 0; j < steps; j++) {
          const a0 = ((j + turn) % steps) * arc - 90, on = ((j * k) % steps) < k;
          const p = (a, rr) => [50 + Math.cos(a * Math.PI / 180) * rr, 50 + Math.sin(a * Math.PI / 180) * rr];
          if (on) {
            const [x0, y0] = p(a0 + arc * 0.08, R), [x1, y1] = p(a0 + arc * 0.92, R);
            ring += `<path d="M${n(x0)} ${n(y0)}A${n(R)} ${n(R)} 0 0 1 ${n(x1)} ${n(y1)}" fill="none" stroke="${c}" stroke-width="${wide}"/>`;
            hits.push(p(a0 + arc / 2, R));
          } else { const [x, y] = p(a0 + arc / 2, R); ring += `<circle cx="${n(x)}" cy="${n(y)}" r="${n(gapR * 0.1)}" fill="${c}"/>`; }
        }
        if (i === 0 && hits.length > 2) s += `<path d="${poly(hits)}" fill="${c}" fill-opacity=".14" stroke="${c}" stroke-opacity=".5" stroke-width=".4"/>`;
        s += `<g${motion({ spin: n((i % 2 ? -1 : 1) * (4 + i * 3)), band: Math.min(63, i * 9), pulse: 0.04 })}>${ring}</g>`;
      });
      return s;
    },
    // A bracketed L-system plant; tempo bends the branching angle, more parts grow it one generation deeper.
    growth(r, ink, bg, id, song) {
      const SYSTEMS = [
        ['X', { X: 'F+[[X]-X]-F[-FX]+X', F: 'FF' }, 25, 5],
        ['F', { F: 'FF+[+F-F-F]-[-F+F+F]' }, 22, 4],
        ['X', { X: 'F[+X][-X]FX', F: 'FF' }, 26, 6],
        ['F', { F: 'F[+F]F[-F]F' }, 26, 4],
        ['X', { X: 'F[+X]F[-X]+X', F: 'FF' }, 20, 6],
      ];
      const [axiom, rules, base, depth] = pick(r, SYSTEMS), deep = depth - (song.roles.length < 3 ? 1 : 0);
      let str = axiom;
      for (let g = 0; g < deep; g++) str = str.replace(/[XF]/g, (c) => rules[c] || c);
      const angle = (base + (song.bpm - 120) / 20 + (r() - 0.5) * 4) * Math.PI / 180, lean = (r() - 0.5) * 0.3;
      let x = 0, y = 0, a = -Math.PI / 2 + lean, lvl = 0;
      const stack = [], segs = [], tips = [];
      for (const c of str) {
        if (c === 'F') { const nx = x + Math.cos(a), ny = y + Math.sin(a); segs.push([x, y, nx, ny, lvl]); x = nx; y = ny; }
        else if (c === '+') a += angle * (0.85 + r() * 0.3);
        else if (c === '-') a -= angle * (0.85 + r() * 0.3);
        else if (c === '[') { stack.push([x, y, a, lvl]); lvl++; }
        else if (c === ']') { tips.push([x, y]); [x, y, a, lvl] = stack.pop(); }
      }
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      for (const [ax, ay, bx, by] of segs) { x0 = Math.min(x0, ax, bx); x1 = Math.max(x1, ax, bx); y0 = Math.min(y0, ay, by); y1 = Math.max(y1, ay, by); }
      const k = Math.min(84 / (x1 - x0 || 1), 84 / (y1 - y0 || 1)), ox = 50 - (x0 + x1) / 2 * k, oy = 94 - y1 * k;
      const levels = [];
      for (const [ax, ay, bx, by, l] of segs) levels[Math.min(l, 5)] = (levels[Math.min(l, 5)] || '') + `M${n(ax * k + ox)} ${n(ay * k + oy)}L${n(bx * k + ox)} ${n(by * k + oy)}`;
      const blossom = tips.filter(() => r() < 0.75).map(([tx, ty]) => [tx * k + ox, ty * k + oy, 0.7 + r() * 1.3]);
      const pen = ink.find((c) => light(c) !== light(bg)) || ink[0], petals = ink.filter((c) => c !== pen);
      const branches = levels.map((d, l) => d ? `<path d="${d}" stroke="${pen}" stroke-width="${n(Math.max(0.35, 2.4 - l * 0.4))}" stroke-linecap="round"/>` : '').join('');
      const moon = `<circle cx="${n(28 + r() * 44)}" cy="${n(26 + r() * 30)}" r="${n(24 + r() * 12)}" fill="${petals[0]}" fill-opacity=".85"/><path d="M0 ${n(94 + 1)}H100V100H0Z" fill="${pen}"/>`;
      return `${moon}<g${motion({ cx: 50, cy: 94, band: 4, pulse: 0.03 })}>${branches}</g><g${motion({ cx: 50, cy: 50, band: 40, pulse: 0.05 })}>${dots(blossom.filter((_, i) => i % 2), petals[1])}${dots(blossom.filter((_, i) => !(i % 2)), petals[2] || petals[1])}</g>`;
    },
    // The cover cut into strips and slid sideways, with a colour-split ghost and smeared rows, like a broken video frame.
    glitch(r, ink, bg, id, song) {
      const shapes = [];
      const parts = Math.max(3, song.roles.length + 1);
      for (let i = 0; i < parts; i++) {
        const kind = i === 0 ? 0 : Math.floor(r() * 4), x = 15 + r() * 70, y = 15 + r() * 70, s = 12 + r() * 24;
        shapes.push(kind === 0 ? ['circle', x, y, s * 1.3] : kind === 1 ? ['rect', x - s, y - s / 3, s * 2, s / 1.5] : kind === 2 ? ['tri', x, y, s] : ['bars', x, y, s]);
      }
      const draw = (color) => shapes.map(([kind, x, y, a, b], i) => {
        const c = color || ink[i % ink.length];
        if (kind === 'circle') return `<circle cx="${n(x)}" cy="${n(y)}" r="${n(a)}" fill="${c}"/>`;
        if (kind === 'rect') return `<rect x="${n(x)}" y="${n(y)}" width="${n(a)}" height="${n(b)}" fill="${c}"/>`;
        if (kind === 'tri') return `<path d="${poly([[x, y - a], [x + a, y + a * 0.7], [x - a, y + a * 0.7]])}" fill="${c}"/>`;
        let d = ''; for (let k = 0; k < 6; k++) d += `M${n(x - a)} ${n(y - a / 2 + k * a / 5)}h${n(a * 2)}`;
        return `<path d="${d}" stroke="${c}" stroke-width="${n(a / 12)}"/>`;
      }).join('');
      const ghost = light(bg) ? ink.find((c) => !light(c)) || ink[0] : ink.find((c) => light(c)) || ink[0];
      let defs = `<g id="${id}g">${draw()}</g><g id="${id}h">${draw(ghost)}</g>`, s = '', y = 0, k = 0, shove = 6 + song.bpm / 8;
      while (y < 100) {
        const h = Math.min(100 - y, 1 + r() ** 2 * 16), dx = r() < 0.45 ? 0 : (r() - 0.5) * shove;
        defs += `<clipPath id="${id}c${k}"><rect y="${n(y)}" width="100" height="${n(h + 0.05)}"/></clipPath>`;
        let strip = '';
        if (dx && r() < 0.5) strip += `<use href="#${id}h" x="${n(dx + (r() - 0.5) * 5)}" opacity=".7"/>`;
        strip += `<use href="#${id}g" x="${n(dx)}"/>`;
        if (r() < 0.12) strip += `<rect x="${n(r() * 60)}" y="${n(y)}" width="100" height="${n(h)}" fill="${pick(r, ink)}"/>`;
        s += `<g clip-path="url(#${id}c${k})"${dx ? motion({ cx: 50, cy: n(y + h / 2), band: 30 + (k % 30), pulse: 0.06 }) : ''}>${strip}</g>`;
        y += h; k++;
      }
      let scan = ''; for (let sy = 0.6; sy < 100; sy += 1.2) scan += `M0 ${n(sy)}H100`;
      return `<defs>${defs}</defs>${s}<path d="${scan}" stroke="${bg}" stroke-opacity=".22" stroke-width=".35"/>`;
    },
    // A recursive-backtracker maze drawn as its corridors, coloured by how far each one is from the entrance.
    maze(r, ink, bg, id, song) {
      const N = Math.min(19, 8 + Math.round(song.bpm / 20)), cell = 100 / N, start = song.hash % (N * N);
      const far = new Array(N * N).fill(-1), segs = [];
      far[start] = 0;
      const stack = [start];
      while (stack.length) {
        const c = stack[stack.length - 1], cx = c % N, cy = (c / N) | 0;
        const next = [[1, 0], [-1, 0], [0, 1], [0, -1]].map(([dx, dy]) => [cx + dx, cy + dy]).filter(([x, y]) => x >= 0 && y >= 0 && x < N && y < N && far[y * N + x] < 0);
        if (!next.length) { stack.pop(); continue; }
        const [x, y] = next[Math.floor(r() * next.length)], id2 = y * N + x;
        far[id2] = far[c] + 1; segs.push([cx, cy, x, y, far[id2]]); stack.push(id2);
      }
      const top = Math.max(...far), bands = 8, paths = Array(bands).fill('');
      for (const [ax, ay, bx, by, d] of segs) { const b = Math.min(bands - 1, Math.floor(d / (top + 1) * bands)); paths[b] += `M${n((ax + 0.5) * cell)} ${n((ay + 0.5) * cell)}L${n((bx + 0.5) * cell)} ${n((by + 0.5) * cell)}`; }
      const end = far.indexOf(top), wide = n(cell * (0.5 + r() * 0.2));
      let s = paths.map((d, b) => `<path d="${d}" stroke="${ink[b % ink.length]}" stroke-width="${wide}" stroke-linecap="round" stroke-opacity="${n(1 - (b >> 2) * 0.25)}"/>`).join('');
      s += `<circle cx="${n((start % N + 0.5) * cell)}" cy="${n(((start / N | 0) + 0.5) * cell)}" r="${n(cell * 0.55)}" fill="${bg}" stroke="${ink[0]}" stroke-width="${n(cell * 0.18)}"${motion({ cx: n((start % N + 0.5) * cell), cy: n(((start / N | 0) + 0.5) * cell), band: 2, pulse: 0.3 })}/>`;
      s += `<circle cx="${n((end % N + 0.5) * cell)}" cy="${n(((end / N | 0) + 0.5) * cell)}" r="${n(cell * 0.45)}" fill="${ink[3]}"/>`;
      return s;
    },
    // An isometric block city whose towers rise like an equaliser; each part of the song lifts its own row.
    iso(r, ink, bg, id, song) {
      const N = 7 + Math.floor(r() * 3), a = 46 / N, top = 34, f = surface(r), rows = song.roles;
      const P = (i, j) => [50 + (i - j) * a, top + (i + j) * a / 2];
      let s = '';
      for (let sum = 0; sum <= 2 * (N - 1); sum++) {
        for (let i = Math.max(0, sum - N + 1); i <= Math.min(N - 1, sum); i++) {
          const j = sum - i, role = rows[j % rows.length];
          const lift = role === 'drums' ? 0.9 : role === 'bass' ? 0.6 : 0.4, h = 2 + 26 * lift * (0.5 + 0.5 * f(i * 9, j * 9)) * (0.6 + r() * 0.5);
          const c = ink[Math.min(ink.length - 1, Math.floor(h / 30 * ink.length))];
          const [ax, ay] = P(i, j), [bx, by] = P(i + 1, j), [cx, cy] = P(i + 1, j + 1), [dx, dy] = P(i, j + 1);
          const up = (pts) => pts.map(([x, y]) => [x, y - h]);
          const block = `<path d="${poly(up([[ax, ay], [bx, by], [cx, cy], [dx, dy]]))}" fill="${shade(c, 0.18)}"/>`
            + `<path d="${poly([[dx, dy - h], [cx, cy - h], [cx, cy], [dx, dy]])}" fill="${shade(c, -0.25)}"/>`
            + `<path d="${poly([[cx, cy - h], [bx, by - h], [bx, by], [cx, cy]])}" fill="${shade(c, -0.5)}"/>`;
          s += `<g${motion({ cx: n(cx), cy: n(cy), band: Math.min(63, (i + j) * 4), pulse: 0.1 })}>${block}</g>`;
        }
      }
      return s;
    },
    // A Penrose rhombus tiling grown by subdividing Robinson triangles; the name moves the centre of the star.
    penrose(r, ink, bg, id, song) {
      const PHI = (1 + Math.sqrt(5)) / 2, cx = 38 + (song.hash % 24), cy = 38 + ((song.hash >>> 6) % 24), R = 92;
      let tris = [];
      for (let i = 0; i < 10; i++) {
        let b = [cx + Math.cos((2 * i - 1) * Math.PI / 10) * R, cy + Math.sin((2 * i - 1) * Math.PI / 10) * R];
        let c = [cx + Math.cos((2 * i + 1) * Math.PI / 10) * R, cy + Math.sin((2 * i + 1) * Math.PI / 10) * R];
        if (i % 2) [b, c] = [c, b];
        tris.push([0, [cx, cy], b, c]);
      }
      const mix = (p, q, t) => [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t];
      for (let g = 0; g < 4 + (song.roles.length > 4 ? 1 : 0); g++) {
        const next = [];
        for (const [kind, A, B, C] of tris) {
          if (!kind) { const P = mix(A, B, 1 / PHI); next.push([0, C, P, B], [1, P, C, A]); }
          else { const Q = mix(B, A, 1 / PHI), S = mix(B, C, 1 / PHI); next.push([1, S, C, A], [1, Q, S, B], [0, S, Q, A]); }
        }
        tris = next;
      }
      const fills = Array(6).fill(''), edges = [], bandsOf = 3 + Math.floor(r() * 3);
      for (const [kind, A, B, C] of tris) {
        if ([A, B, C].every(([x, y]) => Math.hypot(x - cx, y - cy) > 95)) continue;
        const ring = Math.floor(Math.hypot((A[0] + B[0] + C[0]) / 3 - cx, (A[1] + B[1] + C[1]) / 3 - cy) / 10) % bandsOf;
        fills[kind * 3 + (ring % 3)] += poly([A, B, C]);
        edges.push(`M${n(C[0])} ${n(C[1])}L${n(A[0])} ${n(A[1])}L${n(B[0])} ${n(B[1])}`);
      }
      const colours = [ink[0], shade(ink[0], 0.3), ink[1], ink[2], shade(ink[2], -0.3), ink[3]];
      return `<g${motion({ cx: n(cx), cy: n(cy), spin: n(1 + r() * 1.5), band: 2, pulse: 0.03 })}>${fills.map((d, k) => d ? `<path d="${d}" fill="${colours[k]}"/>` : '').join('')}<path d="${edges.join('')}" fill="none" stroke="${bg}" stroke-width="${n(0.35 + r() * 0.4)}" stroke-linejoin="round"/></g>`;
    },
    // A sunflower head: seeds placed by a turning angle near the golden one; the tempo detunes it, so the spiral arms change.
    phyllotaxis(r, ink, bg, id, song) {
      const turn = (137.508 + ((song.bpm % 17) - 8) * 0.035 + (r() - 0.5) * 0.02) * Math.PI / 180, count = 420 + Math.floor(r() * 300);
      const cx = 50 + (r() - 0.5) * 30, cy = 50 + (r() - 0.5) * 30, spread = (62 + r() * 18) / Math.sqrt(count), arm = pick(r, [13, 21, 34]);
      const groups = ink.map(() => []);
      for (let i = 1; i < count; i++) {
        const rad = spread * Math.sqrt(i), a = i * turn;
        groups[(i % arm) % ink.length].push([cx + Math.cos(a) * rad, cy + Math.sin(a) * rad, 0.25 + spread * 0.42 * (0.25 + 0.75 * i / count)]);
      }
      return `<g${motion({ cx: n(cx), cy: n(cy), spin: n((r() < 0.5 ? -1 : 1) * (3 + r() * 4)), band: 3, pulse: 0.06 })}>${groups.map((g, k) => dots(g, ink[k])).join('')}</g>`;
    },
    // A type poster: the song name set huge, repeated, cropped at the edges, part of it in outline, inverted over a disc.
    typo(r, ink, bg, id, song) {
      const word = (song.name.trim() || `${song.bpm} BPM`).toUpperCase(), lines = 4 + Math.floor(r() * 5), size = 100 / lines * 1.12;
      const wide = [...word].reduce((s, c) => s + (c.codePointAt(0) > 0x2e80 ? 1 : 0.66), 0) + 0.66;
      const disc = `<circle cx="${n(30 + r() * 40)}" cy="${n(30 + r() * 40)}" r="${n(22 + r() * 16)}" fill="${ink[3]}"/>`;
      let s = '';
      for (let i = 0; i < lines; i++) {
        const y = (i + 0.86) * 100 / lines, reps = Math.max(2, Math.ceil(130 / (wide * size))), length = reps * wide * size, x = -r() * wide * size;
        const outline = (i + Math.floor(r() * 2)) % 3 === 1, c = ink[i % 3];
        s += `<text x="${n(x)}" y="${n(y)}" font-size="${n(size)}" textLength="${n(length)}" lengthAdjust="spacingAndGlyphs" font-family="'Arial Black','Helvetica Neue',Arial,'Malgun Gothic','Apple SD Gothic Neo',sans-serif" font-weight="900"${outline ? ` fill="none" stroke="${c}" stroke-width="${n(size / 40)}"` : ` fill="${c}"`}${motion({ cx: 50, cy: n(y - size * 0.35), band: (i * 9) % 50, pulse: 0.04 })}>${text(`${word} `.repeat(reps).trim())}</text>`;
      }
      const tilt = pick(r, [0, 0, -90, -8, 6]);
      return `${disc}<g transform="rotate(${tilt} 50 50)" style="mix-blend-mode:difference">${s}</g>`;
    },
    // A lambda-calculus term drawn as a diagram: binders are bars, variables hang from their binder, applications join wires.
    // The song name and the seed write the term together.
    tromp(r, ink, bg, id, song) {
      let term, size;
      for (let tries = 0; tries < 24; tries++) {
        const q = random((song.hash ^ Math.floor(r() * 4294967296)) >>> 0);
        const grow = (depth, bound) => {
          const roll = q();
          if (bound && (depth > 7 || roll < 0.3)) return { v: Math.floor(q() * Math.min(bound, 4)) };
          if (!bound || roll < 0.55) return { lam: grow(depth + 1, bound + 1) };
          return { app: [grow(depth + 1, bound), grow(depth + 1, bound)] };
        };
        term = grow(0, 0);
        const count = (t) => ('v' in t ? 1 : t.lam ? count(t.lam) : count(t.app[0]) + count(t.app[1]));
        size = count(term);
        if (size >= 7 && size <= 34) break;
      }
      const bars = [], wires = ink.map(() => []), links = [];
      const lay = (t, x, y, env) => {
        if ('v' in t) { const [top, c] = env[t.v]; wires[c].push([x, top, x, y]); return [1, 0, x, y, c]; }
        if (t.lam) { const [w, h, ox, oy, c] = lay(t.lam, x, y + 1, [[y, env.length % ink.length], ...env]); bars.push([x, y, x + w - 1]); return [w, h + 1, ox, oy, c]; }
        const [w1, h1, ax, ay, ac] = lay(t.app[0], x, y, env), [w2, h2, bx, by, bc] = lay(t.app[1], x + w1, y, env), low = y + Math.max(h1, h2) + 1;
        wires[ac].push([ax, ay, ax, low]); wires[bc].push([bx, by, bx, low]); links.push([ax, low, bx]);
        return [w1 + w2, Math.max(h1, h2) + 1, ax, low, ac];
      };
      const [W, H, ox, oy, oc] = lay(term, 0, 0, []);
      wires[oc].push([ox, oy, ox, H + 1]);
      const cw = 86 / W, rh = 86 / (H + 1), X = (c) => n(7 + (c + 0.5) * cw), Y = (row) => n(7 + row * rh), thick = n(Math.min(cw, rh) * 0.42);
      const pen = ink.find((c) => light(c) !== light(bg)) || ink[0];
      let s = `<path d="${bars.map(([a, row, b]) => `M${n(7 + (a + 0.1) * cw)} ${Y(row)}H${n(7 + (b + 0.9) * cw)}`).join('')}${links.map(([a, row, b]) => `M${X(a)} ${Y(row)}H${X(b)}`).join('')}" stroke="${pen}" stroke-width="${thick}" stroke-linecap="square"/>`;
      wires.forEach((list, c) => { if (list.length) s += `<g${motion({ band: c * 14 + 2, pulse: 0.03 })}><path d="${list.map(([a, t, , b]) => `M${X(a)} ${Y(t)}V${Y(b)}`).join('')}" stroke="${ink[c] === pen ? shade(pen, light(pen) ? -0.35 : 0.35) : ink[c]}" stroke-width="${thick}"/></g>`; });
      return s;
    },
    // The phase and size of a complex function with a zero for each part and a pole or two: field lines and rings
    // crossing at right angles, the way a complex plot shows them; the tempo sets how many lines leave each zero.
    conformal(r, ink, bg, id, song) {
      const zeros = [], poles = [], G = 48, K = 3 + Math.round(song.bpm / 45), step = 0.3 + r() * 0.25;
      for (let i = 0; i < Math.min(5, Math.max(1, song.roles.length - 1)); i++) zeros.push([15 + r() * 70, 15 + r() * 70]);
      for (let i = 0; i < (song.bpm >= 120 ? 2 : 1); i++) poles.push([15 + r() * 70, 15 + r() * 70]);
      const U = [], V = [];
      for (let j = 0; j <= G; j++) for (let i = 0; i <= G; i++) {
        const x = i / G * 100 + 0.01, y = j / G * 100 + 0.013;
        let ang = 0, mag = 0;
        for (const [a, b] of zeros) { ang += Math.atan2(y - b, x - a); mag += Math.log(Math.hypot(x - a, y - b)); }
        for (const [a, b] of poles) { ang -= Math.atan2(y - b, x - a); mag -= Math.log(Math.hypot(x - a, y - b)); }
        U.push(Math.sin(K * ang)); V.push(Math.sin(Math.PI * mag / step));
      }
      const iso = (F) => {
        let d = '';
        const s = 100 / G, at = (i, j) => F[j * (G + 1) + i];
        for (let j = 0; j < G; j++) for (let i = 0; i < G; i++) {
          const pts = [], X = i * s, Y = j * s;
          const cut = (v0, v1, x0, y0, x1, y1) => { if ((v0 > 0) !== (v1 > 0)) { const t = v0 / (v0 - v1); pts.push(`${(x0 + (x1 - x0) * t).toFixed(1)} ${(y0 + (y1 - y0) * t).toFixed(1)}`); } };
          cut(at(i, j), at(i + 1, j), X, Y, X + s, Y); cut(at(i + 1, j), at(i + 1, j + 1), X + s, Y, X + s, Y + s);
          cut(at(i + 1, j + 1), at(i, j + 1), X + s, Y + s, X, Y + s); cut(at(i, j + 1), at(i, j), X, Y + s, X, Y);
          if (pts.length >= 2) d += `M${pts[0]}L${pts[1]}`;
          if (pts.length === 4) d += `M${pts[2]}L${pts[3]}`;
        }
        return d;
      };
      let s = `<path d="${iso(V)}" fill="none" stroke="${ink[1]}" stroke-width=".7" stroke-linecap="round"/><g${motion({ band: 6, pulse: 0.04 })}><path d="${iso(U)}" fill="none" stroke="${ink[0]}" stroke-width="1.1" stroke-linecap="round"/></g>`;
      s += zeros.map(([x, y], i) => `<circle cx="${n(x)}" cy="${n(y)}" r="2.6" fill="${ink[2]}"${motion({ cx: n(x), cy: n(y), band: i * 10 + 2, pulse: 0.5 })}/>`).join('');
      s += poles.map(([x, y]) => `<circle cx="${n(x)}" cy="${n(y)}" r="3" fill="${bg}" stroke="${ink[3]}" stroke-width="1.4"/>`).join('');
      return s;
    },
    // The chaos game: a point keeps jumping part of the way toward a random corner, with a rule on which corner may
    // come next. One corner per part of the song; the tempo picks the rule.
    chaos(r, ink, bg, id, song) {
      const N = Math.min(6, Math.max(3, song.roles.length + 1)), turn = (song.hash % 628) / 100 + r(), R = 48;
      const OPTIONS = { 3: [[0.5, 0], [0.55, 0]], 4: [[0.5, 1], [0.5, 2], [0.5, 3], [0.6, 0], [0.55, 3]], 5: [[0.618, 0], [0.5, 1], [0.5, 2], [0.6, 1], [0.667, 0]], 6: [[0.667, 0], [0.6, 2], [0.618, 1], [0.5, 1]] }[N];
      const [jump, rule] = OPTIONS[(Math.round(song.bpm / 10) + Math.floor(r() * 2)) % OPTIONS.length];
      const corners = Array.from({ length: N }, (_, k) => [50 + Math.cos(turn + k / N * 6.283) * R, 50 + Math.sin(turn + k / N * 6.283) * R]);
      const banned = (k, last) => rule === 1 ? k === last : rule === 2 ? k === (last + 1) % N : rule === 3 ? k === (last + (N >> 1)) % N : false;
      let x = 50, y = 50, last = 0;
      const seen = new Set(), groups = ink.map(() => []);
      for (let i = 0; i < 6000; i++) {
        let k = Math.floor(r() * N);
        while (banned(k, last)) k = Math.floor(r() * N);
        x += (corners[k][0] - x) * jump; y += (corners[k][1] - y) * jump; last = k;
        const key = Math.round(x * 3) * 1000 + Math.round(y * 3);
        if (i > 20 && !seen.has(key)) { seen.add(key); groups[k % ink.length].push([x, y, 0.36]); }
      }
      return `<g${motion({ spin: n(1 + r() * 2), band: 4, pulse: 0.04 })}>${groups.map((g, k) => dots(g, ink[k])).join('')}</g>`;
    },
    // Arms solved with FABRIK inverse kinematics, each reaching for its own point from a curled start; one arm per part.
    tentacles(r, ink, bg, id, song) {
      const arms = Math.min(8, Math.max(3, song.roles.length + 1)), joints = 12 + Math.round(song.bpm / 14), cx = 50 + (r() - 0.5) * 16, cy = 50 + (r() - 0.5) * 16, body = 9 + r() * 5;
      const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]) || 1e-6, toward = (a, b, len) => { const d = dist(a, b); return [a[0] + (b[0] - a[0]) * len / d, a[1] + (b[1] - a[1]) * len / d]; };
      let s = '';
      for (let i = 0; i < arms; i++) {
        const root = i / arms * 6.283 + r() * 0.4, curl = (r() < 0.5 ? -1 : 1) * (0.18 + r() * 0.14), full = 46 + r() * 16;
        const lens = Array.from({ length: joints }, (_, k) => full / joints * (1.5 - k / joints));
        const pts = [[cx + Math.cos(root) * body, cy + Math.sin(root) * body]];
        let a = root;
        for (const len of lens) { const [px, py] = pts[pts.length - 1]; a += curl; pts.push([px + Math.cos(a) * len, py + Math.sin(a) * len]); }
        const reach = full * (0.45 + r() * 0.3), aim = root + (r() - 0.5) * 1.4, goal = [pts[0][0] + Math.cos(aim) * reach, pts[0][1] + Math.sin(aim) * reach], base = pts[0].slice();
        for (let it = 0; it < 12; it++) {
          pts[pts.length - 1] = goal.slice();
          for (let k = pts.length - 2; k >= 0; k--) pts[k] = toward(pts[k + 1], pts[k], lens[k]);
          pts[0] = base.slice();
          for (let k = 1; k < pts.length; k++) pts[k] = toward(pts[k - 1], pts[k], lens[k - 1]);
        }
        const c = ink[i % ink.length], spot = shade(c, light(c) ? -0.3 : 0.45), wide = 3.6 + r() * 1.6;
        let arm = '';
        for (let k = 0; k < joints; k++) arm += `<path d="M${n(pts[k][0])} ${n(pts[k][1])}L${n(pts[k + 1][0])} ${n(pts[k + 1][1])}" stroke="${c}" stroke-width="${n(wide * (1 - k / joints * 0.8))}" stroke-linecap="round"/>`;
        arm += dots(pts.slice(1, -1).filter((_, k) => k % 2 === 0).map(([x, y], k) => [x, y, wide * 0.17 * (1 - k * 2 / joints * 0.8)]), spot);
        arm += `<circle cx="${n(goal[0])}" cy="${n(goal[1])}" r="1.1" fill="none" stroke="${c}" stroke-width=".4"/>`;
        s += `<g${motion({ cx: n(base[0]), cy: n(base[1]), band: Math.min(63, i * 8 + 2), pulse: 0.07 })}>${arm}</g>`;
      }
      const core = ink.find((c) => light(c) !== light(bg)) || ink[0];
      return s + `<circle cx="${n(cx)}" cy="${n(cy)}" r="${n(body + 1)}" fill="${core}"/><circle cx="${n(cx)}" cy="${n(cy)}" r="${n(body * 0.55)}" fill="${bg}"${motion({ cx: n(cx), cy: n(cy), band: 2, pulse: 0.25 })}/>`;
    },
    // String art: points round a circle, each joined to the point at its index times k; the tempo sets k,
    // so a cardioid, a nephroid or a busier envelope appears.
    strings(r, ink, bg, id, song) {
      const N = 160 + Math.floor(r() * 120), k = 2 + ((song.bpm * 0.05) % 5) + pick(r, [0, 0, 0.5, 1]), R = 46;
      const at = (i, rad, cx = 50, cy = 50) => [cx + Math.cos(i / N * 6.2832 - 1.5708) * rad, cy + Math.sin(i / N * 6.2832 - 1.5708) * rad];
      const layer = (mult, rad, cx, cy, width) => {
        const parts = ink.map(() => '');
        for (let i = 0; i < N; i++) { const [x0, y0] = at(i, rad, cx, cy), [x1, y1] = at(i * mult, rad, cx, cy); parts[Math.floor(i / N * ink.length)] += `M${n(x0)} ${n(y0)}L${n(x1)} ${n(y1)}`; }
        return parts.map((d, c) => `<path d="${d}" stroke="${ink[c]}" stroke-width="${width}" stroke-opacity=".75"/>`).join('');
      };
      let s = `<circle cx="50" cy="50" r="${R}" fill="none" stroke="${ink[0]}" stroke-width=".5"/>`;
      s += `<g${motion({ spin: n((r() < 0.5 ? -1 : 1) * (2 + r() * 3)), band: 3, pulse: 0.04 })}>${layer(k, R, 50, 50, n(0.22 + r() * 0.16))}</g>`;
      if (song.roles.length > 3) s += `<g${motion({ spin: n(-5 - r() * 4), band: 30, pulse: 0.08 })}>${layer(k + 1, 16, 50, 50, 0.2)}</g>`;
      return s;
    },
    // Hitomezashi stitching: each row and column starts its running stitch on or off by one bit of the song name,
    // and the stitches split the cloth into regions that two colours can always fill.
    stitch(r, ink, bg, id, song) {
      const N = 14 + Math.floor(r() * 8), s = 100 / N, bits = [];
      const word = song.chars.length ? song.chars : [song.bpm, song.hash & 255];
      for (const c of word) for (let b = 0; b < 8; b++) bits.push(((c >> b) & 1) ^ (r() < 0.25 ? 1 : 0));
      while (bits.length < 2 * N + 2) bits.push(r() < 0.5 ? 1 : 0);
      const rowBit = Array.from({ length: N + 1 }, (_, j) => bits[j % bits.length]), colBit = Array.from({ length: N + 1 }, (_, i) => bits[(i * 7 + N) % bits.length]);
      const side = [];
      for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
        if (!i && !j) side.push(0);
        else if (!i) side.push(side[(j - 1) * N] ^ ((0 + rowBit[j]) % 2 === 0 ? 1 : 0));
        else side.push(side[j * N + i - 1] ^ ((j + colBit[i]) % 2 === 0 ? 1 : 0));
      }
      const region = new Array(N * N).fill(-1);
      let count = 0;
      for (let k = 0; k < N * N; k++) {
        if (region[k] >= 0) continue;
        const todo = [k]; region[k] = count;
        while (todo.length) {
          const c = todo.pop(), i = c % N, j = (c / N) | 0;
          for (const [di, dj] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
            const a = i + di, b = j + dj, o = b * N + a;
            if (a < 0 || b < 0 || a >= N || b >= N || region[o] >= 0 || side[o] !== side[c]) continue;
            region[o] = count; todo.push(o);
          }
        }
        count++;
      }
      const tone = Array.from({ length: count }, () => Math.floor(r() * 2)), fills = ink.map(() => '');
      for (let j = 0; j < N; j++) for (let i = 0; i < N;) {
        const k = j * N + i, c = side[k] * 2 + tone[region[k]];
        let e = i; while (e + 1 < N && side[j * N + e + 1] * 2 + tone[region[j * N + e + 1]] === c) e++;
        fills[c] += `M${n(i * s)} ${n(j * s)}h${n((e - i + 1) * s + 0.05)}v${n(s + 0.05)}h${n(-(e - i + 1) * s - 0.05)}Z`;
        i = e + 1;
      }
      let thread = '';
      for (let j = 1; j < N; j++) for (let i = rowBit[j] % 2; i < N; i += 2) thread += `M${n(i * s + s * 0.15)} ${n(j * s)}h${n(s * 0.7)}`;
      for (let i = 1; i < N; i++) for (let j = colBit[i] % 2; j < N; j += 2) thread += `M${n(i * s)} ${n(j * s + s * 0.15)}v${n(s * 0.7)}`;
      return fills.map((d, c) => d ? `<path d="${d}" fill="${ink[c]}"/>` : '').join('') + `<g${motion({ band: 3, pulse: 0.02 })}><path d="${thread}" stroke="${bg}" stroke-width="${n(s * 0.22)}" stroke-linecap="round"/></g>`;
    },
    // Demoscene copper bars: shiny gradient bars stacked along a sine, with the song name riding a sine scroller.
    copper(r, ink, bg, id, song) {
      const bars = Math.max(6, song.roles.length * 2 + 2), tall = 6 + r() * 4, wave = 0.45 + song.bpm / 220, amp = 20 + r() * 10, phase = r() * 6.28;
      let defs = '', s = '';
      ink.forEach((c, k) => { defs += `<linearGradient id="${id}b${k}" x2="0" y2="1"><stop offset="0" stop-color="${shade(c, -0.75)}"/><stop offset=".38" stop-color="${c}"/><stop offset=".5" stop-color="${shade(c, 0.75)}"/><stop offset=".62" stop-color="${c}"/><stop offset="1" stop-color="${shade(c, -0.75)}"/></linearGradient>`; });
      for (let k = 0; k < bars; k++) {
        const y = 36 + Math.sin(phase + k * wave) * amp;
        s += `<rect x="0" y="${n(y - tall / 2)}" width="100" height="${n(tall)}" fill="url(#${id}b${k % ink.length})"${motion({ cx: 50, cy: n(y), band: Math.min(63, k * 6), pulse: 0.12 })}/>`;
      }
      const word = (song.name.trim() || `${song.bpm} BPM`).toUpperCase(), letters = [...word].slice(0, 16), cjk = (ch) => ch.codePointAt(0) > 0x2e80;
      const units = letters.reduce((sum, ch) => sum + (cjk(ch) ? 1 : 0.66), 0), size = Math.min(20, 90 / Math.max(3, units));
      const pen = ink.find((c) => light(c) !== light(bg)) || ink[0];
      let scroll = '', x = 50 - units * size / 2;
      letters.forEach((ch, i) => {
        const y = 78 + Math.sin(phase + i * 0.7) * 7, wide = cjk(ch) ? size : size * 0.66;
        scroll += `<text x="${n(x + wide / 2)}" y="${n(y)}" font-size="${n(size)}" text-anchor="middle" font-family="'Arial Black','Helvetica Neue',Arial,'Malgun Gothic','Apple SD Gothic Neo',sans-serif" font-weight="900" fill="${pen}" stroke="${bg}" stroke-width="${n(size / 14)}" paint-order="stroke"${motion({ cx: n(x + wide / 2), cy: n(y - size * 0.35), band: (i * 5) % 60, pulse: 0.15 })}>${text(ch)}</text>`;
        x += wide;
      });
      let lines = ''; for (let y = 0.5; y < 100; y += 1.5) lines += `M0 ${n(y)}H100`;
      return `<defs>${defs}</defs>${s}<path d="${lines}" stroke="${bg}" stroke-opacity=".25" stroke-width=".5"/>${scroll}`;
    },
    // Cubic disarray after Georg Nees: an orderly grid of squares that comes apart toward one edge; faster songs come apart sooner.
    disarray(r, ink, bg, id, song) {
      const N = 10 + Math.floor(r() * 4), s = 76 / N, wild = 0.6 + song.bpm / 150, from = pick(r, [0, 90, 180, 270]), blend = light(bg) ? 'multiply' : 'screen';
      let out = '';
      for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
        const t = (j / (N - 1)) ** 1.6 * wild, x = 12 + i * s + s / 2 + (r() - 0.5) * t * s * 1.2, y = 12 + j * s + s / 2 + (r() - 0.5) * t * s * 0.8;
        const turn = (r() - 0.5) * t * 110, c = ink[Math.min(ink.length - 1, Math.floor(t / wild * ink.length * 0.999))], filled = r() < 0.18 + t * 0.4;
        const square = `<rect x="${n(x - s / 2)}" y="${n(y - s / 2)}" width="${n(s)}" height="${n(s)}" transform="rotate(${n(turn)} ${n(x)} ${n(y)})" ${filled ? `fill="${c}" fill-opacity=".75"` : `fill="none" stroke="${c}" stroke-width="${n(0.5 + t * 0.5)}"`}/>`;
        out += t > wild * 0.75 ? `<g${motion({ cx: n(x), cy: n(y), spin: n((r() - 0.5) * 20 * t), band: Math.min(63, i * 5), pulse: 0.1 })}>${square}</g>` : square;
      }
      return `<g transform="rotate(${from} 50 50)" style="mix-blend-mode:${blend}">${out}</g>`;
    },
    // Marbled paper: colour bands pushed around by a turbulence field; faster songs swirl finer.
    marble(r, ink, bg, id, song) {
      const freq = n(0.012 + song.bpm / 9000 + r() * 0.01), tilt = r() * 180, push = n(26 + r() * 30);
      let bands = '', x = -60;
      while (x < 160) { const w = 2 + r() ** 2 * 14; bands += `<rect x="${n(x)}" y="-60" width="${n(w + 0.3)}" height="220" fill="${pick(r, [...ink, bg])}"/>`; x += w; }
      const veins = Array.from({ length: Math.max(3, song.roles.length * 2) }, () => `<rect x="${n(r() * 160 - 30)}" y="-60" width="${n(0.4 + r() * 0.8)}" height="220" fill="${light(bg) ? '#111' : '#fff'}" fill-opacity=".7"/>`).join('');
      return `<defs><filter id="${id}m" x="-10%" y="-10%" width="120%" height="120%"><feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="3" seed="${Math.floor(r() * 999)}"/><feDisplacementMap in="SourceGraphic" scale="${push}" xChannelSelector="R" yChannelSelector="G"/></filter></defs>`
        + `<g filter="url(#${id}m)"><g transform="rotate(${n(tilt)} 50 50)">${bands}${veins}</g></g>`;
    },
  };

  window.albumArt = {
    methods: Object.keys(METHODS),
    // The seed alone picks the kind of cover; the song (optional: name, bpm, tracks) only tunes it.
    make(seed, song) {
      const names = this.methods, method = names[(seed >>> 0) % names.length];
      const r = random(seed);
      const [bg, ...ink] = PALETTES[Math.floor(r() * PALETTES.length)];
      return { method, svg: `<rect width="100" height="100" fill="${bg}"/>${METHODS[method](r, ink, bg, `art${seed >>> 0}`, songOf(song))}` };
    },
    // Motion comes only from arguments: stopped or silent songs stay still.
    move(root, cycles, bands, still) {
      for (const el of root.querySelectorAll('[data-spin],[data-pulse]')) {
        const d = el.dataset;
        if (still) { el.removeAttribute('transform'); continue; }
        const cx = +(d.cx || 50), cy = +(d.cy || 50);
        const level = bands && d.band ? bands[+d.band] / 255 : 0;
        const size = 1 + level * +(d.pulse || 0) + (d.pulse ? Math.sin(cycles * Math.PI * 2) * 0.012 : 0);
        const turn = cycles * +(d.spin || 0);
        el.setAttribute('transform', `translate(${n(cx)} ${cy}) rotate(${n(turn)}) scale(${size.toFixed(4)}) translate(${-cx} ${-cy})`);
      }
    },
  };
})();
