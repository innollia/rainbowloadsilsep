// Seeded album art. The seed picks a drawing method, then every number in it.
// Elements carry data-* motion hints; app.js moves them from song position and real output.
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

  // A smooth random surface; several methods read their shapes off it.
  function surface(r) {
    const waves = Array.from({ length: 4 }, () => [0.02 + r() * 0.07, 0.02 + r() * 0.07, r() * 6.28]);
    return (x, y) => waves.reduce((sum, [a, b, c]) => sum + Math.sin(x * a + y * b + c), 0) / waves.length;
  }

  const METHODS = {
    contour(r, ink, bg) {
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
    truchet(r, ink, bg) {
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
  };

  window.albumArt = {
    methods: Object.keys(METHODS),
    make(seed) {
      const names = this.methods, method = names[(seed >>> 0) % names.length];
      const r = random(seed);
      const [bg, ...ink] = PALETTES[Math.floor(r() * PALETTES.length)];
      return { method, svg: `<rect width="100" height="100" fill="${bg}"/>${METHODS[method](r, ink, bg, `art${seed >>> 0}`)}` };
    },
    // Motion comes only from arguments: stopped or silent songs stay still.
    move(root, cycles, bands, still) {
      for (const el of root.querySelectorAll('[data-spin],[data-flow],[data-pulse]')) {
        const d = el.dataset;
        if (still) { el.removeAttribute('transform'); continue; }
        const cx = +(d.cx || 50), cy = +(d.cy || 50);
        const level = bands && d.band ? bands[+d.band] / 255 : 0;
        const size = 1 + level * +(d.pulse || 0) + (d.pulse ? Math.sin(cycles * Math.PI * 2) * 0.012 : 0);
        const shift = d.flow ? (cycles * +d.flow) % +d.period : 0;
        const turn = cycles * +(d.spin || 0);
        el.setAttribute('transform', `translate(${n(cx + shift)} ${cy}) rotate(${n(turn)}) scale(${n(size)}) translate(${-cx} ${-cy})`);
      }
    },
  };
})();
