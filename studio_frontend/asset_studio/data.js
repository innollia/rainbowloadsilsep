// Stand-in project for the front-end shell. Nothing here reaches a server; the backend replaces this file.
(() => {
  const tone = (from, to, len, wave = 'sine', gain = 0.5, at = 0) => ({ kind: 'tone', from, to, len, wave, gain, at });
  const noise = (len, cutoff = 0.5, gain = 0.5, attack = 0.002, at = 0) => ({ kind: 'noise', len, cutoff, gain, attack, at });
  const seq = (notes, wave, gain, step, len) => ({ kind: 'seq', notes, wave, gain, step, len });
  const drums = (kick, hat, gain, step) => ({ kind: 'drums', kick, hat, gain, step });
  // An unbroken bed for ambience. Swells are [cycles per loop, depth, phase] so they meet themselves at the seam.
  const bed = (stem, len, cutoff, gain, swells) => ({ kind: 'bed', stem, len, cutoff, gain, swells, at: 0 });
  // Irregular placement that still repeats exactly, so a loop has no audible pulse of its own.
  const scatter = (count, seconds, make) => Array.from({ length: count }, (_, i) => make(0.2 + ((i + 1) * 0.618034 % 1) * (seconds - 0.9), i));

  // Shown text is { en, ko }; ids and stem keys stay fixed because code and saved state use them.
  const L = (en, ko) => ({ en, ko });
  const sfx = (id, name, cat, layers, opts = {}) => ({ id, name, cat, layers, music: false, ...opts });
  const bgm = (id, name, tempo, root, mood, opts = {}) => {
    const step = 60 / tempo / 2, up = (o) => root + o;
    const prog = mood === 'dark' ? [0, 0, -4, -2] : [0, 5, -3, 7];
    const notes = (shape) => prog.flatMap((p) => shape.map((o) => (o == null ? null : up(p + o))));
    return {
      id, name, cat: 'bgm', music: true, tempo, layers: [
        { stem: 'drums', ...drums('x...x...x...x...', 'x.x.x.x.x.x.x.x.', 0.55, step) },
        { stem: 'bass', ...seq(notes([-24, null, -24, -12, -24, null, -17, null]), 'saw', 0.3, step, step * 0.9) },
        { stem: 'chords', ...seq(notes([0, null, null, null, 7, null, null, null]), 'triangle', 0.22, step, step * 3.6) },
        { stem: 'melody', ...seq(notes([12, 15, 19, null, 15, 12, null, 10]), 'square', 0.1, step, step * 0.8) },
      ], ...opts,
    };
  };

  const CATEGORIES = [
    { id: 'ui', name: L('UI', 'UI'), hue: 'var(--ui)' },
    { id: 'combat', name: L('Combat', '전투'), hue: 'var(--combat)' },
    { id: 'char', name: L('Character', '캐릭터'), hue: 'var(--char)' },
    { id: 'env', name: L('Ambience', '환경'), hue: 'var(--env)' },
    { id: 'bgm', name: L('Music', '음악'), hue: 'var(--bgm)' },
  ];

  const ASSETS = [
    sfx('sfx_ui_click', L('Click', '클릭'), 'ui', [tone(1800, 900, 0.05, 'square', 0.35)], { sample: true }),
    sfx('sfx_ui_confirm', L('Confirm', '확인'), 'ui', [tone(660, 660, 0.08, 'triangle', 0.5), tone(990, 990, 0.16, 'triangle', 0.5, 0.08)]),
    sfx('sfx_ui_cancel', L('Cancel', '취소'), 'ui', [tone(500, 300, 0.2, 'triangle', 0.5)]),
    sfx('sfx_ui_open', L('Menu open', '메뉴 열기'), 'ui', [tone(300, 900, 0.14, 'sine', 0.5), noise(0.12, 0.3, 0.1)]),
    sfx('sfx_ui_slide', L('Slide', '슬라이드'), 'ui', [noise(0.2, 0.15, 0.3, 0.05)]),
    sfx('sfx_ui_coin', L('Coin', '코인'), 'ui', [tone(988, 988, 0.07, 'square', 0.3), tone(1319, 1319, 0.3, 'square', 0.3, 0.07)], { sample: true }),
    sfx('sfx_ui_fail', L('Fail', '실패'), 'ui', [tone(220, 110, 0.5, 'saw', 0.4)]),
    sfx('sfx_ui_levelup', L('Level up', '레벨 업'), 'ui', [261, 329, 392, 523, 659].map((f, i) => tone(f, f, 0.22, 'triangle', 0.4, i * 0.09))),
    sfx('sfx_combat_swing', L('Sword swing', '칼 휘두르기'), 'combat', [noise(0.22, 0.4, 0.5, 0.06)], { sample: true }),
    sfx('sfx_combat_hit', L('Hit', '타격'), 'combat', [noise(0.1, 0.8, 0.6), tone(160, 60, 0.16, 'sine', 0.7)], { sample: true }),
    sfx('sfx_combat_hurt', L('Hurt', '피격'), 'combat', [noise(0.12, 0.5, 0.4), tone(320, 130, 0.25, 'saw', 0.3)]),
    sfx('sfx_combat_block', L('Shield block', '방패 막기'), 'combat', [tone(1200, 800, 0.1, 'square', 0.3), noise(0.08, 0.9, 0.4)]),
    sfx('sfx_combat_explosion', L('Explosion', '폭발'), 'combat', [noise(1.1, 0.3, 1.5), tone(90, 30, 0.9, 'sine', 1.1)]),
    sfx('sfx_combat_cast', L('Spell cast', '마법 시전'), 'combat', [tone(200, 1400, 0.6, 'sine', 0.4), noise(0.6, 0.6, 0.12, 0.2)]),
    sfx('heal_sfx', L('Heal', '치유'), 'combat', [523, 659, 784, 1047].map((f, i) => tone(f, f, 0.5, 'sine', 0.3, i * 0.1))),
    sfx('sfx_combat_arrow', L('Arrow', '화살'), 'combat', [noise(0.2, 0.7, 0.3, 0.01), tone(900, 500, 0.15, 'sine', 0.2, 0.09)], { noLicense: true }),
    sfx('sfx_char_step', L('Footstep', '발소리'), 'char', [noise(0.07, 0.25, 0.5), tone(120, 70, 0.08, 'sine', 0.5)], { sample: true }),
    sfx('sfx_char_jump', L('Jump', '점프'), 'char', [tone(280, 760, 0.2, 'square', 0.3)]),
    sfx('sfx_char_land', L('Land', '착지'), 'char', [noise(0.1, 0.2, 0.6), tone(100, 50, 0.14, 'sine', 0.7)]),
    sfx('sfx_char_dash', L('Dash', '대시'), 'char', [noise(0.3, 0.5, 0.5, 0.08)]),
    sfx('sfx_char_pickup', L('Pick up', '줍기'), 'char', [tone(660, 1100, 0.14, 'triangle', 0.5)]),
    sfx('amb_wind', L('Wind', '바람'), 'env', [bed('wind', 8, 0.05, 0.75, [[1, 0.35, 0], [3, 0.2, 1.3]]), bed('gust', 8, 0.22, 0.12, [[2, 0.6, 0.4], [5, 0.3, 2]])], { sample: true, loop: true }),
    sfx('amb_rain', L('Rain', '빗소리'), 'env', [bed('rain_streaks', 8, 0.7, 0.16, [[1, 0.12, 0]]), bed('rain_floor', 8, 0.12, 0.28, [[2, 0.15, 0.7]]), ...scatter(22, 8, (at, i) => ({ ...noise(0.03, 0.8, 0.14 + (i % 3) * 0.05, 0.001, at), stem: 'raindrops' }))], { loop: true }),
    sfx('amb_fire', L('Campfire', '모닥불'), 'env', [bed('fire_bed', 8, 0.04, 0.6, [[1, 0.25, 0], [3, 0.15, 1]]), ...scatter(14, 8, (at, i) => ({ ...noise(0.03 + (i % 3) * 0.02, 0.9, 0.2 + (i % 4) * 0.08, 0.001, at), stem: 'crackle' }))], { loop: true }),
    sfx('amb_cave', L('Cave', '동굴'), 'env', [bed('cave_echo', 8, 0.025, 0.9, [[1, 0.3, 0]]), ...scatter(4, 8, (at, i) => ({ ...tone(1400 - i * 120, 1100 - i * 100, 0.2, 'sine', 0.14), at, stem: 'drips' }))], { loop: true }),
    sfx('sfx_env_drop', L('Water drop', '물방울'), 'env', [tone(900, 1700, 0.09, 'sine', 0.6)]),
    bgm('bgm_title', L('Title', '타이틀'), 92, 57, 'bright', { sample: true, loud: 1.7, loop: true }),
    bgm('bgm_town', L('Town', '마을'), 84, 60, 'bright', { loop: true }),
    bgm('bgm_battle', L('Battle', '전투'), 138, 57, 'dark', { sample: true, loop: true }),
    bgm('bgm_boss', L('Boss', '보스'), 152, 52, 'dark', { loop: true }),
    bgm('bgm_win', L('Victory', '승리'), 120, 64, 'bright'),
    bgm('bgm_lose', L('Defeat', '패배'), 72, 52, 'dark'),
  ];

  const PROFILES = [
    { id: 'mobile', name: L('Mobile', '모바일'), loud: [-20, -16] },
    { id: 'console', name: L('Console', '콘솔'), loud: [-26, -22] },
    { id: 'wide', name: L('Wide', '넓게'), loud: [-26, -14] },
  ];
  // The AI's own checklist. Users never see or edit this; `applies` narrows a rule.
  const RULES = [
    { id: 'peak', name: L('Peak', '최대 소리'), unit: 'dB', limit: -1, level: 'error', fix: true, read: (m) => m.peak, bad: (v, r) => v > r.limit, hint: L('True peak ceiling', 'true peak 상한') },
    { id: 'clip', name: L('Clipping', '클리핑'), unit: L('', '개'), limit: 0, level: 'error', fix: true, read: (m) => m.clips, bad: (v, r) => v > r.limit, hint: L('Clipped samples', '찌그러진 샘플 수') },
    { id: 'loud', name: L('Music loudness', '음악 음량'), unit: 'LUFS', range: [-20, -16], level: 'error', fix: true, applies: (a) => a.music, read: (m) => m.loud, bad: (v, r) => v < r.range[0] || v > r.range[1], hint: L('Integrated loudness of the track', '곡 전체 평균 음량') },
    { id: 'dur', name: L('Length', '길이'), unit: L('s', '초'), limit: 2, level: 'warn', applies: (a) => !a.music && !a.loop, read: (m) => m.seconds, bad: (v, r) => v > r.limit, hint: L('Max SFX length', '효과음 최대 길이') },
    { id: 'lead', name: L('Leading silence', '앞 무음'), unit: 'ms', limit: 50, level: 'warn', fix: true, applies: (a) => !a.loop, read: (m) => m.lead, bad: (v, r) => v > r.limit, hint: L('Sounds late when triggered', '눌렀을 때 늦게 들림') },
    { id: 'tail', name: L('Trailing silence', '뒤 무음'), unit: 'ms', limit: 200, level: 'warn', fix: true, applies: (a) => !a.loop, read: (m) => m.tail, bad: (v, r) => v > r.limit, hint: L('Wasted file length', '쓸데없는 파일 길이') },
    { id: 'dc', name: 'DC', unit: '', limit: 0.002, level: 'warn', read: (m) => m.dc, bad: (v, r) => v > r.limit, hint: L('Waveform offset', '파형 중심 치우침') },
    { id: 'seam', name: L('Loop seam', '루프 이음새'), unit: L('x', '배'), limit: 3, level: 'warn', applies: (a) => a.loop, read: (m) => m.seam, bad: (v, r) => v > r.limit, hint: L('Click when it repeats', '반복될 때 나는 튐') },
    { id: 'wrap', name: L('Seam level gap', '이음매 음량 차'), unit: 'dB', limit: 3, level: 'warn', applies: (a) => a.loop && !a.music, read: (m) => m.wrap, bad: (v, r) => v > r.limit, hint: L('A level jump between end and start makes the loop audible', '끝과 처음의 음량이 다르면 반복이 들림') },
    { id: 'steady', name: L('Dropout', '끊김'), unit: 'dB', limit: 12, level: 'warn', applies: (a) => a.loop && !a.music, read: (m) => m.dip, bad: (v, r) => v > r.limit, hint: L('Ambience must not fade out midway', '환경음은 중간에 잦아들면 안 됨') },
    { id: 'name', name: L('Name', '이름'), text: true, level: 'error', read: (m, a) => /^(sfx|amb|bgm)_[a-z0-9_]+$/.test(a.id), hint: L('Starts with sfx_, amb_ or bgm_', 'sfx_, amb_, bgm_ 로 시작') },
    { id: 'lic', name: L('License', '저작권'), text: true, level: 'error', read: (m, a) => !a.noLicense && (!a.imported || !!a.license), hint: L('Tools and sources recorded', '사용 도구·음원 기록') },
  ];

  const LICENSES = [
    { name: 'nkido (Akkado, Cedar)', license: 'MIT', holder: 'Moritz Laass', use: L('Sound synthesis engine', '소리 합성 엔진') },
    { name: 'VCSL', license: 'CC0-1.0', holder: 'Versilian Studios', use: L('Instrument samples', '악기 샘플') },
    { name: 'Kenney Audio', license: 'CC0-1.0', holder: 'Kenney.nl', use: L('SFX source material', '효과음 재료') },
    { name: 'wasm-media-encoders', license: 'MIT', holder: 'arseneyr', use: L('OGG and MP3 export', 'OGG·MP3 내보내기') },
    { name: 'LAME', license: 'LGPL-2.0', holder: 'The LAME Project', use: L('MP3 encoder', 'MP3 인코더') },
    { name: 'libvorbis', license: 'BSD-3-Clause', holder: 'Xiph.Org Foundation', use: L('OGG Vorbis encoder', 'OGG Vorbis 인코더') },
  ];

  window.STUDIO_DATA = { bed, music: bgm, GAME: L('Starlight Garden', '별빛 정원'), BRIEF: L('A calm fantasy collecting game. Cute and warm.', '잔잔한 판타지 수집 게임. 귀엽고 따뜻하게.'), CATEGORIES, ASSETS, PROFILES, RULES, LICENSES };
})();
