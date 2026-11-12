// The categories a new board starts with, and the words the room shows for rules and licences.
(() => {
  // Shown text is { en, ko }; ids stay fixed because code and saved state use them.
  const L = (en, ko) => ({ en, ko });

  const CATEGORIES = [
    { id: 'ui', name: L('UI', 'UI'), hue: 'var(--ui)' },
    { id: 'combat', name: L('Combat', '전투'), hue: 'var(--combat)' },
    { id: 'char', name: L('Character', '캐릭터'), hue: 'var(--char)' },
    { id: 'env', name: L('Ambience', '환경'), hue: 'var(--env)' },
    { id: 'bgm', name: L('Music', '음악'), hue: 'var(--bgm)' },
  ];

  // What each rule is called, by rule id. Which sounds a rule covers, its limit and its level are measure.js's
  // (assetMeasure.RULES and PROFILES): the page, the command line and the server all judge with that one table.
  const RULE_TEXT = {
    peak: { name: L('Peak', '최대 소리'), unit: 'dB', hint: L('True peak ceiling', 'true peak 상한') },
    clip: { name: L('Clipping', '클리핑'), unit: L('', '개'), hint: L('Clipped samples', '찌그러진 샘플 수') },
    loud: { name: L('Music loudness', '음악 음량'), unit: 'LUFS', hint: L('Integrated loudness of the track', '곡 전체 평균 음량') },
    dur: { name: L('Length', '길이'), unit: L('s', '초'), hint: L('Max SFX length', '효과음 최대 길이') },
    lead: { name: L('Leading silence', '앞 무음'), unit: 'ms', hint: L('Sounds late when triggered', '눌렀을 때 늦게 들림') },
    tail: { name: L('Trailing silence', '뒤 무음'), unit: 'ms', hint: L('Wasted file length', '쓸데없는 파일 길이') },
    dc: { name: 'DC', unit: '', hint: L('Waveform offset', '파형 중심 치우침') },
    seam: { name: L('Loop seam', '루프 이음새'), unit: L('x', '배'), hint: L('Click when it repeats', '반복될 때 나는 튐') },
    wrap: { name: L('Seam level gap', '이음매 음량 차'), unit: 'dB', hint: L('A level jump between end and start makes the loop audible', '끝과 처음의 음량이 다르면 반복이 들림') },
    steady: { name: L('Dropout', '끊김'), unit: 'dB', hint: L('Ambience must not fade out midway', '환경음은 중간에 잦아들면 안 됨') },
    name: { name: L('Name', '이름'), unit: '', hint: L('Follows the id rule (Settings)', 'ID 규칙을 따름(설정)') },
    lic: { name: L('License', '저작권'), unit: '', hint: L('Tools and sources recorded', '사용 도구·음원 기록') },
  };

  const LICENSES = [
    { name: 'nkido (Akkado, Cedar)', license: 'MIT', holder: 'Moritz Laass', use: L('Sound synthesis engine', '소리 합성 엔진') },
    { name: 'VCSL', license: 'CC0-1.0', holder: 'Versilian Studios', use: L('Instrument samples', '악기 샘플') },
    { name: 'Kenney Audio', license: 'CC0-1.0', holder: 'Kenney.nl', use: L('SFX source material', '효과음 재료') },
    { name: 'wasm-media-encoders', license: 'MIT', holder: 'arseneyr', use: L('OGG and MP3 export', 'OGG·MP3 내보내기') },
    { name: 'LAME', license: 'LGPL-2.0', holder: 'The LAME Project', use: L('MP3 encoder', 'MP3 인코더') },
    { name: 'libvorbis', license: 'BSD-3-Clause', holder: 'Xiph.Org Foundation', use: L('OGG Vorbis encoder', 'OGG Vorbis 인코더') },
  ];

  window.STUDIO_DATA = { CATEGORIES, RULE_TEXT, LICENSES };
})();
