// Stand-in project for the front-end shell. Nothing here reaches a server; the backend replaces this file.
(() => {
  const tone = (from, to, len, wave = 'sine', gain = 0.5, at = 0) => ({ kind: 'tone', from, to, len, wave, gain, at });
  const noise = (len, cutoff = 0.5, gain = 0.5, attack = 0.002, at = 0) => ({ kind: 'noise', len, cutoff, gain, attack, at });
  const seq = (notes, wave, gain, step, len) => ({ kind: 'seq', notes, wave, gain, step, len });
  const drums = (kick, hat, gain, step) => ({ kind: 'drums', kick, hat, gain, step });

  const sfx = (id, name, cat, layers, opts = {}) => ({ id, name, cat, layers, music: false, ...opts });
  const bgm = (id, name, tempo, root, mood, opts = {}) => {
    const step = 60 / tempo / 2, up = (o) => root + o;
    const prog = mood === 'dark' ? [0, 0, -4, -2] : [0, 5, -3, 7];
    const notes = (shape) => prog.flatMap((p) => shape.map((o) => (o == null ? null : up(p + o))));
    return {
      id, name, cat: 'bgm', music: true, tempo, layers: [
        { stem: '드럼', ...drums('x...x...x...x...', 'x.x.x.x.x.x.x.x.', 0.55, step) },
        { stem: '베이스', ...seq(notes([-24, null, -24, -12, -24, null, -17, null]), 'saw', 0.3, step, step * 0.9) },
        { stem: '화음', ...seq(notes([0, null, null, null, 7, null, null, null]), 'triangle', 0.22, step, step * 3.6) },
        { stem: '멜로디', ...seq(notes([12, 15, 19, null, 15, 12, null, 10]), 'square', 0.1, step, step * 0.8) },
      ], ...opts,
    };
  };

  const CATEGORIES = [
    { id: 'ui', name: 'UI', hue: 'var(--ui)' },
    { id: 'combat', name: '전투', hue: 'var(--combat)' },
    { id: 'char', name: '캐릭터', hue: 'var(--char)' },
    { id: 'env', name: '환경', hue: 'var(--env)' },
    { id: 'bgm', name: '음악', hue: 'var(--bgm)' },
  ];

  const ASSETS = [
    sfx('sfx_ui_click', '클릭', 'ui', [tone(1800, 900, 0.05, 'square', 0.35)], { sample: true }),
    sfx('sfx_ui_confirm', '확인', 'ui', [tone(660, 660, 0.08, 'triangle', 0.5), tone(990, 990, 0.16, 'triangle', 0.5, 0.08)]),
    sfx('sfx_ui_cancel', '취소', 'ui', [tone(500, 300, 0.2, 'triangle', 0.5)]),
    sfx('sfx_ui_open', '메뉴 열기', 'ui', [tone(300, 900, 0.14, 'sine', 0.5), noise(0.12, 0.3, 0.1)]),
    sfx('sfx_ui_slide', '슬라이드', 'ui', [noise(0.2, 0.15, 0.3, 0.05)]),
    sfx('sfx_ui_coin', '코인', 'ui', [tone(988, 988, 0.07, 'square', 0.3), tone(1319, 1319, 0.3, 'square', 0.3, 0.07)], { sample: true }),
    sfx('sfx_ui_fail', '실패', 'ui', [tone(220, 110, 0.5, 'saw', 0.4)]),
    sfx('sfx_ui_levelup', '레벨 업', 'ui', [261, 329, 392, 523, 659].map((f, i) => tone(f, f, 0.22, 'triangle', 0.4, i * 0.09))),
    sfx('sfx_combat_swing', '칼 휘두르기', 'combat', [noise(0.22, 0.4, 0.5, 0.06)], { sample: true }),
    sfx('sfx_combat_hit', '타격', 'combat', [noise(0.1, 0.8, 0.6), tone(160, 60, 0.16, 'sine', 0.7)], { sample: true }),
    sfx('sfx_combat_hurt', '피격', 'combat', [noise(0.12, 0.5, 0.4), tone(320, 130, 0.25, 'saw', 0.3)]),
    sfx('sfx_combat_block', '방패 막기', 'combat', [tone(1200, 800, 0.1, 'square', 0.3), noise(0.08, 0.9, 0.4)]),
    sfx('sfx_combat_explosion', '폭발', 'combat', [noise(1.1, 0.3, 1.5), tone(90, 30, 0.9, 'sine', 1.1)]),
    sfx('sfx_combat_cast', '마법 시전', 'combat', [tone(200, 1400, 0.6, 'sine', 0.4), noise(0.6, 0.6, 0.12, 0.2)]),
    sfx('heal_sfx', '치유', 'combat', [523, 659, 784, 1047].map((f, i) => tone(f, f, 0.5, 'sine', 0.3, i * 0.1))),
    sfx('sfx_combat_arrow', '화살', 'combat', [noise(0.2, 0.7, 0.3, 0.01), tone(900, 500, 0.15, 'sine', 0.2, 0.09)], { noLicense: true }),
    sfx('sfx_char_step', '발소리', 'char', [noise(0.07, 0.25, 0.5), tone(120, 70, 0.08, 'sine', 0.5)], { sample: true }),
    sfx('sfx_char_jump', '점프', 'char', [tone(280, 760, 0.2, 'square', 0.3)]),
    sfx('sfx_char_land', '착지', 'char', [noise(0.1, 0.2, 0.6), tone(100, 50, 0.14, 'sine', 0.7)]),
    sfx('sfx_char_dash', '대시', 'char', [noise(0.3, 0.5, 0.5, 0.08)]),
    sfx('sfx_char_pickup', '줍기', 'char', [tone(660, 1100, 0.14, 'triangle', 0.5)]),
    sfx('amb_wind', '바람', 'env', [noise(3, 0.06, 0.5, 0.8)], { sample: true, loop: true }),
    sfx('amb_rain', '빗소리', 'env', [noise(3, 0.7, 0.2, 0.3)], { loop: true }),
    sfx('amb_fire', '모닥불', 'env', [noise(3, 0.1, 0.3, 0.4), noise(0.05, 0.9, 0.4, 0.002, 0.7), noise(0.05, 0.9, 0.3, 0.002, 1.9)], { loop: true }),
    sfx('amb_cave', '동굴', 'env', [noise(3, 0.03, 0.6, 1), tone(1400, 1100, 0.2, 'sine', 0.2, 1.4)], { loop: true }),
    sfx('sfx_env_drop', '물방울', 'env', [tone(900, 1700, 0.09, 'sine', 0.6)]),
    bgm('bgm_title', '타이틀', 92, 57, 'bright', { sample: true, loud: 1.7, loop: true }),
    bgm('bgm_town', '마을', 84, 60, 'bright', { loop: true }),
    bgm('bgm_battle', '전투', 138, 57, 'dark', { sample: true, loop: true }),
    bgm('bgm_boss', '보스', 152, 52, 'dark', { loop: true }),
    bgm('bgm_win', '승리', 120, 64, 'bright'),
    bgm('bgm_lose', '패배', 72, 52, 'dark'),
  ];

  const PROFILES = [
    { id: 'mobile', name: '모바일', loud: [-20, -16] },
    { id: 'console', name: '콘솔', loud: [-26, -22] },
    { id: 'wide', name: '넓게', loud: [-26, -14] },
  ];
  // The AI's own checklist. Users never see or edit this; `applies` narrows a rule.
  const RULES = [
    { id: 'peak', name: '최대 소리', unit: 'dB', limit: -1, level: 'error', fix: true, read: (m) => m.peak, bad: (v, r) => v > r.limit, hint: 'true peak 상한' },
    { id: 'clip', name: '클리핑', unit: '개', limit: 0, level: 'error', fix: true, read: (m) => m.clips, bad: (v, r) => v > r.limit, hint: '찌그러진 샘플 수' },
    { id: 'loud', name: '음악 음량', unit: 'LUFS', range: [-20, -16], level: 'error', fix: true, applies: (a) => a.music, read: (m) => m.loud, bad: (v, r) => v < r.range[0] || v > r.range[1], hint: '곡 전체 평균 음량' },
    { id: 'dur', name: '길이', unit: '초', limit: 2, level: 'warn', applies: (a) => !a.music && !a.loop, read: (m) => m.seconds, bad: (v, r) => v > r.limit, hint: '효과음 최대 길이' },
    { id: 'lead', name: '앞 무음', unit: 'ms', limit: 50, level: 'warn', fix: true, read: (m) => m.lead, bad: (v, r) => v > r.limit, hint: '눌렀을 때 늦게 들림' },
    { id: 'tail', name: '뒤 무음', unit: 'ms', limit: 200, level: 'warn', fix: true, applies: (a) => !a.loop, read: (m) => m.tail, bad: (v, r) => v > r.limit, hint: '쓸데없는 파일 길이' },
    { id: 'dc', name: 'DC', unit: '', limit: 0.002, level: 'warn', read: (m) => m.dc, bad: (v, r) => v > r.limit, hint: '파형 중심 치우침' },
    { id: 'seam', name: '루프 이음새', unit: '', limit: 0.1, level: 'warn', applies: (a) => a.loop, read: (m) => m.seam, bad: (v, r) => v > r.limit, hint: '반복될 때 나는 튐' },
    { id: 'name', name: '이름', text: true, level: 'error', read: (m, a) => /^(sfx|amb|bgm)_[a-z0-9_]+$/.test(a.id), hint: 'sfx_, amb_, bgm_ 로 시작' },
    { id: 'lic', name: '저작권', text: true, level: 'error', read: (m, a) => !a.noLicense, hint: '사용 도구·음원 기록' },
  ];

  const LICENSES = [
    { name: 'nkido (Akkado, Cedar)', license: 'MIT', holder: 'Moritz Laass', use: '소리 합성 엔진' },
    { name: 'VCSL', license: 'CC0-1.0', holder: 'Versilian Studios', use: '악기 샘플' },
    { name: 'Kenney Audio', license: 'CC0-1.0', holder: 'Kenney.nl', use: '효과음 재료' },
  ];

  window.STUDIO_DATA = { GAME: '별빛 정원', BRIEF: '잔잔한 판타지 수집 게임. 귀엽고 따뜻하게.', CATEGORIES, ASSETS, PROFILES, RULES, LICENSES };
})();
