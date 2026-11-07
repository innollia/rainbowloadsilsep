// Seeded album art. The seed picks a drawing method, then every number in it.
// Elements carry data-* motion hints; app.js moves them from song position and real output.
(() => {
  const PALETTE = ['#E8AE72', '#87B9E8', '#C7A0E8', '#8CCDB2', '#F5F5F5', '#FF9B9B'];

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

  const METHODS = {
    rings(r, c) {
      let s = '';
      const count = 4 + Math.floor(r() * 4);
      for (let i = 0; i < count; i++) {
        const radius = 44 - i * (34 / count);
        s += `<circle cx="50" cy="50" r="${n(radius)}" fill="none" stroke="${c()}" stroke-width="${n(1 + r() * 3)}" stroke-dasharray="${n(4 + r() * 16)} ${n(2 + r() * 8)}"${motion({ spin: n((i % 2 ? -1 : 1) * (12 + r() * 30)), band: i * 4, pulse: 0.1 })}/>`;
      }
      return s;
    },
    burst(r, c) {
      let s = '';
      const count = 16 + Math.floor(r() * 32), inner = 10 + r() * 12;
      const spin = (r() < 0.5 ? -1 : 1) * (6 + r() * 14);
      for (let i = 0; i < count; i++) {
        const a = i / count * Math.PI * 2, len = 14 + r() * 26;
        const [x1, y1, x2, y2] = [inner, inner + len].flatMap((d) => [50 + Math.cos(a) * d, 50 + Math.sin(a) * d]);
        s += `<line x1="${n(x1)}" y1="${n(y1)}" x2="${n(x2)}" y2="${n(y2)}" stroke="${c()}" stroke-width="${n(0.8 + r() * 2)}" stroke-linecap="round"${motion({ spin, band: i % 40, pulse: 0.35 })}/>`;
      }
      return s;
    },
    orbits(r, c) {
      let s = '';
      const count = 3 + Math.floor(r() * 3);
      for (let i = 0; i < count; i++) {
        const radius = 12 + i * (32 / count), color = c(), spin = (i % 2 ? -1 : 1) * (20 + r() * 50);
        s += `<circle cx="50" cy="50" r="${n(radius)}" fill="none" stroke="${color}" stroke-opacity=".35" stroke-width=".6"/>`;
        const dots = 1 + Math.floor(r() * 4), start = r() * 6.28;
        for (let d = 0; d < dots; d++) {
          const a = start + d / dots * Math.PI * 2;
          s += `<circle cx="${n(50 + Math.cos(a) * radius)}" cy="${n(50 + Math.sin(a) * radius)}" r="${n(1.5 + r() * 2.5)}" fill="${color}"${motion({ spin })}/>`;
        }
      }
      return s;
    },
    waves(r, c) {
      let s = '';
      const count = 4 + Math.floor(r() * 5), period = 20 + Math.floor(r() * 20);
      for (let i = 0; i < count; i++) {
        const y = 14 + i * (72 / Math.max(1, count - 1)), amp = 2 + r() * 7;
        let d = `M ${-period} ${n(y)}`;
        for (let x = -period; x < 100 + period; x += period) d += ` q ${n(period / 4)} ${n(-amp * 2)} ${n(period / 2)} 0 t ${n(period / 2)} 0`;
        s += `<path d="${d}" fill="none" stroke="${c()}" stroke-width="${n(1 + r() * 2)}"${motion({ flow: n((i % 2 ? -1 : 1) * (8 + r() * 16)), period })}/>`;
      }
      return s;
    },
    polygons(r, c) {
      let s = '';
      const sides = 3 + Math.floor(r() * 5), count = 4 + Math.floor(r() * 5), twist = r() * 0.6;
      for (let i = 0; i < count; i++) {
        const radius = 44 - i * (36 / count);
        const pts = Array.from({ length: sides }, (_, k) => {
          const a = k / sides * Math.PI * 2 + i * twist;
          return `${n(50 + Math.cos(a) * radius)},${n(50 + Math.sin(a) * radius)}`;
        }).join(' ');
        s += `<polygon points="${pts}" fill="none" stroke="${c()}" stroke-width="${n(1 + r() * 2)}" stroke-linejoin="round"${motion({ spin: n((i % 2 ? -1 : 1) * (6 + r() * 20)), band: i * 3, pulse: 0.08 })}/>`;
      }
      return s;
    },
    rose(r, c) {
      let s = '';
      const petals = 3 + Math.floor(r() * 6), layers = 2 + Math.floor(r() * 3);
      for (let l = 0; l < layers; l++) {
        const size = 44 - l * 11;
        let d = '';
        for (let k = 0; k <= 360; k += 2) {
          const t = k * Math.PI / 180, radius = size * Math.cos(petals * t);
          d += `${k ? 'L' : 'M'} ${n(50 + radius * Math.cos(t))} ${n(50 + radius * Math.sin(t))} `;
        }
        s += `<path d="${d}Z" fill="none" stroke="${c()}" stroke-width="${n(0.8 + r() * 1.4)}"${motion({ spin: n((l % 2 ? -1 : 1) * (8 + r() * 14)), band: l * 6, pulse: 0.12 })}/>`;
      }
      return s;
    },
    grid(r, c) {
      let s = '';
      const cells = 4 + Math.floor(r() * 4), size = 84 / cells;
      for (let y = 0; y < cells; y++) {
        for (let x = 0; x < cells; x++) {
          if (r() < 0.25) continue;
          const cx = 8 + (x + 0.5) * size, cy = 8 + (y + 0.5) * size, half = size * (0.18 + r() * 0.24);
          const shape = r() < 0.5
            ? `<rect x="${n(cx - half)}" y="${n(cy - half)}" width="${n(half * 2)}" height="${n(half * 2)}" rx="1"`
            : `<circle cx="${n(cx)}" cy="${n(cy)}" r="${n(half)}"`;
          s += `${shape} fill="${c()}"${motion({ cx: n(cx), cy: n(cy), band: (x + y * cells) % 48, pulse: 0.7 })}/>`;
        }
      }
      return s;
    },
  };

  window.albumArt = {
    methods: Object.keys(METHODS),
    make(seed) {
      const names = this.methods, method = names[(seed >>> 0) % names.length];
      const r = random(seed);
      const pick = PALETTE.slice().sort(() => r() - 0.5).slice(0, 2 + Math.floor(r() * 3));
      const c = () => pick[Math.floor(r() * pick.length)];
      return { method, svg: `<rect width="100" height="100" fill="#191919"/>${METHODS[method](r, c)}` };
    },
    // Motion comes only from arguments: stopped or silent songs stay still.
    move(root, cycles, bands, still) {
      for (const el of root.querySelectorAll('[data-spin],[data-flow],[data-pulse]')) {
        const d = el.dataset;
        if (still) { el.removeAttribute('transform'); continue; }
        const cx = +(d.cx || 50), cy = +(d.cy || 50);
        const level = bands && d.band ? bands[+d.band] / 255 : 0;
        const size = 1 + level * +(d.pulse || 0);
        const shift = d.flow ? (cycles * +d.flow) % +d.period : 0;
        const turn = cycles * +(d.spin || 0);
        el.setAttribute('transform', `translate(${n(cx + shift)} ${cy}) rotate(${n(turn)}) scale(${n(size)}) translate(${-cx} ${-cy})`);
      }
    },
  };
})();
