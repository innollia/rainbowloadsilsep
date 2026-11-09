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
    help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .8-1 1.7M12 17h.01"/>',
    expand: '<path d="M14 4h6v6M20 4l-7 7M10 20H4v-6M4 20l7-7"/>',
    solo: '<path d="M4 15v-3a8 8 0 0 1 16 0v3"/><rect x="3" y="14" width="4" height="6" rx="1.5"/><rect x="17" y="14" width="4" height="6" rx="1.5"/>',
    muted: '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="m17 9.5 5 5M22 9.5l-5 5"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    prev: '<path d="M15 6l-6 6 6 6"/>',
    next: '<path d="m9 6 6 6-6 6"/>',
    check: '<path d="m5 13 4 4 10-11"/>',
    flag: '<path d="M6 21V4h12l-3 4 3 4H6"/>',
    upload: '<path d="M12 15V4M7 8l5-5 5 5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1"/>',
  };
  const setIcon = (el, name) => { el.innerHTML = `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`; };
  const iconButton = (name, label, fn, cls = 'iconBtn') => { const b = el('button', cls); setIcon(b, name); b.setAttribute('aria-label', label); b.title = label; b.onclick = fn; return b; };
  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  /* ---------- language ---------- */
  // The host page picks the language with ?lang= and can change it later with an asset:lang message.
  const LANGS = ['en', 'ko'];
  let lang = new URLSearchParams(location.search).get('lang');
  if (!LANGS.includes(lang)) lang = 'en';
  const TEXT = {
    en: {
      docTitle: 'Game sound assets', menu: 'Menu', settings: 'Settings', language: 'Language', gameInfo: 'Game info', stagesLabel: 'Progress', help: 'How to use', spec: 'Spec', export: 'Export',
      backToMusic: 'To music studio', category: 'Category', board: 'Asset board', playAll: 'Play all', stopAll: 'Stop playing all', hoverPlay: 'Play on hover',
      acceptAll: 'Keep all', rejectAll: 'Discard all', selectAll: 'Select all', deselect: 'Deselect', approve: 'Approve', approved: 'Approved', clear: 'Clear',
      ask: 'Edit request', send: 'Send',
      status: { pending: 'Pending', draft: 'Needs check', approved: 'Approved', flagged: 'Flagged', working: 'Revising', review: 'In review' },
      sec: (s) => `${s}s`,
      previous: 'Previous', newVersion: 'New version', keep: 'Keep', drop: 'Discard',
      approveAll: 'Approve all', leftToCheck: (n) => `${n} assets left to check.`,
      samplesDone: (n, rest) => `All ${n} samples approved. The other ${rest} will be made in this style.`,
      samplesProgress: (n, done, rest) => `${done} of ${n} samples approved. Listen and approve them, and the other ${rest} will be made in the same style.`,
      makeRest: 'Make the rest', all: 'All', statusHead: 'Status',
      stages: { brief: 'Brief', sample: 'Samples', expand: 'Expand', export: 'Export' },
      counts: (n, ok) => `${n} total · ${ok} approved`, reviewCount: (n) => `${n} to review`, selected: (n) => `${n} selected`,
      askSelected: (n) => `Request for the ${n} selected`, askOne: (name) => `Request for ${name}`, askNone: 'Pick an asset to send a request',
      drafts: 'Drafts', draftCount: (i) => `${i}`, draftCountLabel: 'Number of drafts', draftNote: (text, k) => `${text} · draft ${k}`,
      madeDrafts: (n) => `Made ${n} drafts. Listen and keep one.`, madeOne: 'Made a new version. Compare it with the previous one.',
      expanding: (n) => `Making ${n} in the sample style`, firstVersion: 'First version', fromSpec: 'Created from spec',
      play: 'Play', stop: 'Stop', toBoard: 'Back to board', prevAsset: 'Previous asset', nextAsset: 'Next asset',
      peak: (v) => `Peak ${v} dB`, loud: (v) => `Loudness ${v} LUFS`, loop: 'Loop', oneShot: 'One shot', spectrum: 'Spectrum',
      tracks: (n) => `${n} track${n === 1 ? '' : 's'}`,
      stemOn: (s) => `Unmute ${s}`, stemOff: (s) => `Mute ${s}`, stemSolo: (s) => `Solo ${s}`, stemGain: (s) => `${s} volume`,
      stems: { drums: 'Drums', bass: 'Bass', chords: 'Chords', melody: 'Melody', wind: 'Wind', gust: 'Gusts', rain_streaks: 'Rain streaks', rain_floor: 'Rain bed', raindrops: 'Raindrops', fire_bed: 'Fire bed', crackle: 'Crackle', cave_echo: 'Cave echo', drips: 'Drips', noise_layer: 'Noise layer', main: 'Main' },
      toneLayer: (i) => `Tone layer ${i}`,
      tabChat: 'Chat', tabCode: 'Code', tabVersions: (n) => `Versions ${n}`, tabLicense: 'Licenses',
      chatEmpty: (name) => `Tell me how to change ${name}.`, listen: 'Listen', current: 'Current', copyLicenses: 'Copy all licenses',
      askThis: 'Request for this asset', close: 'Close',
      licenseTitle: (g) => `${g} sound asset license notice`, use: 'Use', license: 'License', holder: 'Holder', copiedLicenses: 'Copied the license notice',
      example: { style: 'Warm wooden percussion and harp, combat not too heavy', assets: [
        { name: 'Click', when: 'Pressing a menu button', description: 'Light, wooden' },
        { name: 'Parry', when: 'The moment an enemy attack is blocked', description: 'Short metallic ring' },
        { name: 'Garden', when: 'Garden screen', description: 'Calm harp and strings' },
      ] },
      specPrompt: (p) => `Please write a game sound spec as JSON. This spec goes into a sound production tool that makes the assets.

Based on the design docs and code of the game you are working on, list every sound the game needs. Do not invent values that have no basis; leave them null, and put anything that needs deciding in questions.

Fields
- game: game name
- platform: main device, one of ${p.platforms}
- style: overall sound direction of the game, one or two sentences
- assets: list of sounds
  - id: lowercase English starting with sfx_ for effects, amb_ for ambience, bgm_ for music. If the code already uses a name, keep it
  - name: human-readable name
  - category: one of ${p.cats}
  - length: target length (seconds). Effects at most ${p.dur}s, ambience an unbroken loop of 8 or 16 seconds
  - loop: whether it repeats. Always true for ambience
  - when: the moment in the game when it plays
  - description: what it sounds like
- questions: things the user must decide

Do not reference tracks or samples with unclear licenses. Available materials: ${p.licenses}.

Reply only with JSON in the format below, no explanation.
${p.form}`,
      sendPrompt: 'Send prompt', receiveSpec: 'Receive spec', pasteToAgent: 'Paste this into the agent that worked on the music.', prompt: 'Prompt',
      copyPrompt: 'Copy prompt', copiedPrompt: 'Copied the prompt', pasteSpec: 'Paste the spec the agent gave you.', insertExample: 'Insert example',
      notJson: (m) => `Not JSON: ${m}`, noAssets: 'There is no assets list.', badItems: (n, list) => `${n} items break the rules: ${list}`, noName: 'no name',
      planSummary: (a, c, k, g) => `Add ${a} · Change ${c} · Keep ${k} · Remove ${g}`, tagAdd: 'Add', tagChange: 'Change', tagRemove: 'Remove',
      moreRemoved: (n) => `${n} more removed`, startWithSpec: 'Start with this spec', addOnly: 'Add only, remove nothing',
      specApplied: (n) => `Spec applied. ${n} new assets`,
      exportIssues: (n, names) => `${n} assets with spec issues will also be exported: ${names}`, exportUnapproved: (n) => `${n} unapproved assets will be left out.`,
      inBundle: 'In the bundle', bundleItems: ['Approved sound files audio/*.wav', 'Spec game-audio.spec.json, which Import reads back', 'CREDITS.md and lint-report.json'], licenses: 'Licenses',
      exportBundle: 'Export bundle', exported: (n) => `Bundled ${n} sounds`, restart: 'Start again from samples',
      importShort: 'Import', importTitle: 'Bring in what you already have', importIntro: 'Already made sounds, or have a list of what the game needs? Start from there.',
      dropHere: 'Drop sound files, a folder or an exported bundle',
      importFilesHead: 'Sound files', importFilesHelp: 'wav, mp3 or ogg, several at once. You can also drop a whole folder anywhere on this screen. Name and category are guessed from the file and folder names; fix them right here.',
      pickFiles: 'Choose files', pickFolder: 'Choose a folder',
      importBundleHead: 'Exported bundle', importBundleHelp: 'The .zip that Export made, or its unzipped folder. You carry on where you left off.', pickBundle: 'Open bundle',
      importListHead: 'List of sounds the game needs', importListHelp: 'One per line, or CSV with a header (id, name, category, when, description). They go on the board as empty slots for the AI to fill.',
      listPlaceholder: 'Button click\nSword hit, combat, short and dry\nbgm_title\nForest, ambience', listCount: (n) => `${n} sounds`, addSlots: (n) => `Add ${n} empty slot${n === 1 ? '' : 's'}`,
      justImported: 'Just brought in', imported: 'Brought in', importedN: (n) => `Brought in ${n} sound${n === 1 ? '' : 's'}`, bundleLoaded: (g, n) => `Opened ${g}: ${n} assets`,
      slotsAdded: (n) => `Added ${n} empty slots`, nothingToImport: 'No sound files, bundle or list found here',
      nameLabel: 'Name', guessed: 'Guessed, check it', licenseLater: 'License (fill in later)', holderLater: 'Holder', licenseOf: (n) => `License of ${n}`,
      importedLicense: 'You brought this sound in, so its license is yours to record. It goes into CREDITS.md.', noLicenseYet: 'license not recorded',
      originHead: 'Source', fillLeft: (n) => `${n} empty slot${n === 1 ? '' : 's'} to make.`, fillAll: 'Fill with AI', filling: (n) => `Making ${n}`,
      likeThis: 'Drafts in this feel', likeName: (n) => `${n} (like)`, likeMade: (n) => `Making ${n} in this feel`, promptHead: 'AI prompt',
      fromPrompt: 'Made from the prompt', importedNote: 'Brought in', fromBundle: 'From the bundle', importHint: 'Already have sounds or a sound list? Drop them here or import them.',
      fillPrompt: (p) => `Make the game sound "${p.name}" (${p.id}, ${p.cat}) for ${p.game}.\n${p.when ? `When it plays: ${p.when}\n` : ''}${p.description ? `What it sounds like: ${p.description}\n` : ''}Form: ${p.loop ? 'seamless loop' : 'one shot'}${p.length ? `, about ${p.length}s` : ''}.${p.style ? `\nGame sound direction: ${p.style}` : ''}${p.ref}`,
      refPrompt: (r) => `\n\nReference: make it in the feel of "${r.name}", the user's own sound (${r.file}). Measured from that file:\n- length ${r.seconds}s, ${r.loop ? 'loop' : 'one shot'}\n- peak ${r.peak} dB, loudness ${r.loud} LUFS\n- energy: low (<250 Hz) ${r.low}% · mid ${r.mid}% · high (>4 kHz) ${r.high}%, brightness about ${r.bright} Hz\n- leading silence ${r.lead} ms, trailing silence ${r.tail} ms\nStay close to its length, loudness and band balance. Do not copy it.`,
      importing: (i, n) => `Bringing in ${i} of ${n}`, skipped: (n, why) => `Skipped ${n}: ${why}`,
      whyType: (n) => `${n} not sound files`, whyBig: (n) => `${n} over 50 MB or past 500 MB in all`, whyBad: (n) => `${n} could not be read`, whyMany: (n) => `${n} past the first 2000`,
      pruned: (n) => `Storage was full, so ${n} old discarded drafts were cleared.`, saveFull: 'Storage is full and the board could not be saved. Export a bundle to keep it.',
      tutorialTitle: 'How to make game sounds',
      steps: [
        ['Bring in what you have', 'Already have sounds, a list of the sounds the game needs, or a bundle exported here? Import puts them on the board.'],
        ['Get a spec', 'From Spec in the top-right menu, copy the prompt, send it to the AI that has the game design doc, and paste back the spec it returns.'],
        ['Check samples', 'Key sounds come first. Hover over a tile to listen, then approve.'],
        ['Make the rest', 'The rest are made at once in the style of the approved samples.'],
        ['Revise', 'Clicking a tile selects it and plays it. Pick several and write what to change. Raise the draft count to compare several options. Press and hold to open it large.'],
        ['Export', 'Approved sounds are bundled with the license notice. The AI finishes spec checks before it hands over a sound.'],
      ],
    },
    ko: {
      docTitle: '게임 소리 에셋', menu: '메뉴', settings: '설정', language: '언어', gameInfo: '게임 정보', stagesLabel: '진행 단계', help: '사용법', spec: '명세', export: '내보내기',
      backToMusic: '음악 작업실로', category: '분류', board: '에셋 보드', playAll: '전체 듣기', stopAll: '전체 듣기 멈춤', hoverPlay: '올리면 듣기',
      acceptAll: '모두 채택', rejectAll: '모두 버림', selectAll: '전체 선택', deselect: '선택 해제', approve: '승인', approved: '승인됨', clear: '해제',
      ask: '수정 요청', send: '보내기',
      status: { pending: '대기', draft: '확인 필요', approved: '승인', flagged: '수정 표시', working: '수정 중', review: '검토 대기' },
      sec: (s) => `${s}초`,
      previous: '이전', newVersion: '새 버전', keep: '채택', drop: '버림',
      approveAll: '전부 승인', leftToCheck: (n) => `확인할 에셋 ${n}개가 남았어요.`,
      samplesDone: (n, rest) => `샘플 ${n}개를 모두 승인했어요. 이 스타일로 나머지 ${rest}개를 만듭니다.`,
      samplesProgress: (n, done, rest) => `샘플 ${n}개 중 ${done}개 승인. 들어 보고 승인하면 나머지 ${rest}개를 같은 스타일로 만듭니다.`,
      makeRest: '나머지 만들기', all: '전체', statusHead: '상태',
      stages: { brief: '설명', sample: '샘플 확인', expand: '확장', export: '내보내기' },
      counts: (n, ok) => `전체 ${n} · 승인 ${ok}`, reviewCount: (n) => `검토 ${n}개`, selected: (n) => `${n}개 선택`,
      askSelected: (n) => `선택한 ${n}개에 보낼 요청`, askOne: (name) => `${name}에 보낼 요청`, askNone: '에셋을 골라 요청을 보내세요',
      drafts: '시안', draftCount: (i) => `${i}개`, draftCountLabel: '시안 개수', draftNote: (text, k) => `${text} · 시안 ${k}`,
      madeDrafts: (n) => `시안 ${n}개를 만들었어요. 들어 보고 하나를 채택하세요.`, madeOne: '새 버전을 만들었어요. 이전과 비교해 보세요.',
      expanding: (n) => `샘플 스타일로 ${n}개를 만듭니다`, firstVersion: '첫 버전', fromSpec: '명세에서 생성',
      play: '재생', stop: '정지', toBoard: '보드로', prevAsset: '이전 에셋', nextAsset: '다음 에셋',
      peak: (v) => `최대 ${v} dB`, loud: (v) => `음량 ${v} LUFS`, loop: '루프', oneShot: '한 번 재생', spectrum: '주파수',
      tracks: (n) => `트랙 ${n}개`,
      stemOn: (s) => `${s} 켜기`, stemOff: (s) => `${s} 끄기`, stemSolo: (s) => `${s} 혼자 듣기`, stemGain: (s) => `${s} 음량`,
      stems: { drums: '드럼', bass: '베이스', chords: '화음', melody: '멜로디', wind: '바람', gust: '바람결', rain_streaks: '빗줄기', rain_floor: '빗소리 바닥', raindrops: '빗방울', fire_bed: '불꽃 바닥', crackle: '타닥', cave_echo: '동굴 울림', drips: '물방울', noise_layer: '잡음 층', main: '본체' },
      toneLayer: (i) => `음 층 ${i}`,
      tabChat: '대화', tabCode: '코드', tabVersions: (n) => `버전 ${n}`, tabLicense: '저작권',
      chatEmpty: (name) => `${name}을(를) 어떻게 바꿀지 말해 주세요.`, listen: '듣기', current: '현재', copyLicenses: '저작권 전체 복사',
      askThis: '이 에셋에 보낼 요청', close: '닫기',
      licenseTitle: (g) => `${g} 소리 에셋 저작권 고지`, use: '용도', license: '라이선스', holder: '저작권자', copiedLicenses: '저작권 고지를 복사했어요',
      example: { style: '따뜻한 나무 타악기와 하프 중심, 전투도 무겁지 않게', assets: [
        { name: '클릭', when: '메뉴 버튼을 누를 때', description: '가볍고 나무 느낌' },
        { name: '패링', when: '적 공격을 막는 순간', description: '금속 울림이 짧게' },
        { name: '정원', when: '정원 화면', description: '잔잔한 하프와 현악' },
      ] },
      specPrompt: (p) => `게임 소리 명세서를 JSON으로 작성해 주세요. 이 명세서를 소리 제작 도구에 넣어 에셋을 만듭니다.

맡고 있는 게임의 기획서와 코드를 근거로, 게임에 필요한 소리를 빠짐없이 적어 주세요. 근거가 없는 값은 지어내지 말고 null로 두고, 정해야 할 것은 questions에 적어 주세요.

항목
- game: 게임 이름
- platform: ${p.platforms} 중 주요 기기
- style: 게임 전체의 소리 방향, 한두 문장
- assets: 소리 목록
  - id: 효과음 sfx_, 환경음 amb_, 음악 bgm_ 로 시작하는 소문자 영문. 코드에 이미 쓰는 이름이 있으면 그대로
  - name: 사람이 읽을 이름
  - category: ${p.cats} 중 하나
  - length: 목표 길이(초). 효과음은 ${p.dur}초 이하, 환경음은 끊기지 않는 반복 구간 8초나 16초
  - loop: 반복 재생 여부. 환경음은 언제나 true
  - when: 게임의 어떤 순간에 나는 소리인지
  - description: 어떤 소리인지
- questions: 사용자가 정해야 할 것

저작권이 불분명한 곡이나 샘플은 참조하지 마세요. 쓸 수 있는 재료는 ${p.licenses}입니다.

설명 없이 아래 형식의 JSON만 답해 주세요.
${p.form}`,
      sendPrompt: '프롬프트 보내기', receiveSpec: '명세 받기', pasteToAgent: '음악 작업을 하던 에이전트에게 붙여 넣으세요.', prompt: '프롬프트',
      copyPrompt: '프롬프트 복사', copiedPrompt: '프롬프트를 복사했어요', pasteSpec: '에이전트가 준 명세를 붙여 넣으세요.', insertExample: '예시 넣기',
      notJson: (m) => `JSON이 아니에요: ${m}`, noAssets: 'assets 목록이 없어요.', badItems: (n, list) => `규칙에 맞지 않는 항목 ${n}개: ${list}`, noName: '이름 없음',
      planSummary: (a, c, k, g) => `추가 ${a} · 변경 ${c} · 유지 ${k} · 삭제 ${g}`, tagAdd: '추가', tagChange: '변경', tagRemove: '삭제',
      moreRemoved: (n) => `외 ${n}개 삭제`, startWithSpec: '이 명세로 작업 시작', addOnly: '삭제 없이 추가만',
      specApplied: (n) => `명세를 적용했어요. 새 에셋 ${n}개`,
      exportIssues: (n, names) => `규격 문제가 남은 에셋 ${n}개도 함께 나갑니다: ${names}`, exportUnapproved: (n) => `아직 승인되지 않은 에셋 ${n}개는 빠집니다.`,
      inBundle: '묶음에 들어가는 것', bundleItems: ['승인한 소리 파일 audio/*.wav', '명세 game-audio.spec.json (가져오기로 다시 읽음)', 'CREDITS.md와 lint-report.json'], licenses: '저작권',
      exportBundle: '묶음 내보내기', exported: (n) => `소리 ${n}개를 묶었어요`, restart: '샘플 단계부터 다시',
      importShort: '가져오기', importTitle: '이미 만든 작업 가져오기', importIntro: '만들어 둔 소리나 게임에 필요한 소리 목록이 있으면 거기서 시작하세요.',
      dropHere: '소리 파일, 폴더, 내보낸 묶음을 여기에 놓으세요',
      importFilesHead: '소리 파일', importFilesHelp: 'wav, mp3, ogg 여러 개를 한 번에. 폴더째 이 화면 아무 데나 끌어다 놓아도 돼요. 이름과 분류는 파일·폴더 이름으로 짐작하니 여기서 바로 고치세요.',
      pickFiles: '파일 고르기', pickFolder: '폴더 고르기',
      importBundleHead: '내보낸 묶음', importBundleHelp: '내보내기로 받은 .zip이나 그 압축을 푼 폴더. 하던 데서 이어서 합니다.', pickBundle: '묶음 열기',
      importListHead: '게임에 필요한 소리 목록', importListHelp: '한 줄에 하나, 또는 머리줄(id, name, category, when, description)이 있는 CSV. 빈 칸으로 올라가고 AI가 채웁니다.',
      listPlaceholder: '버튼 클릭\n칼 타격, 전투, 짧고 건조하게\nbgm_title\n숲, 환경', listCount: (n) => `소리 ${n}개`, addSlots: (n) => `빈 칸 ${n}개 올리기`,
      justImported: '방금 가져온 소리', imported: '직접 가져옴', importedN: (n) => `소리 ${n}개를 가져왔어요`, bundleLoaded: (g, n) => `${g} 묶음을 열었어요. 에셋 ${n}개`,
      slotsAdded: (n) => `빈 칸 ${n}개를 올렸어요`, nothingToImport: '소리 파일, 묶음, 목록을 찾지 못했어요',
      nameLabel: '이름', guessed: '짐작한 분류예요, 확인하세요', licenseLater: '라이선스 (나중에 적어도 돼요)', holderLater: '저작권자', licenseOf: (n) => `${n} 라이선스`,
      importedLicense: '직접 가져온 소리라 라이선스는 직접 적어 주세요. CREDITS.md에 들어갑니다.', noLicenseYet: '라이선스 기록 없음',
      originHead: '출처', fillLeft: (n) => `만들 빈 칸 ${n}개.`, fillAll: 'AI로 채우기', filling: (n) => `${n}개를 만드는 중`,
      likeThis: '이 느낌으로 시안', likeName: (n) => `${n} 느낌`, likeMade: (n) => `이 느낌으로 ${n}개를 만들어요`, promptHead: 'AI 프롬프트',
      fromPrompt: '프롬프트로 생성', importedNote: '직접 가져옴', fromBundle: '묶음에서 가져옴', importHint: '이미 만든 소리나 소리 목록이 있나요? 여기에 끌어다 놓거나 가져오세요.',
      fillPrompt: (p) => `${p.game}에 쓸 게임 소리 "${p.name}"(${p.id}, ${p.cat})를 만들어 주세요.\n${p.when ? `나는 때: ${p.when}\n` : ''}${p.description ? `어떤 소리: ${p.description}\n` : ''}형태: ${p.loop ? '끊김 없는 반복' : '한 번 재생'}${p.length ? `, 약 ${p.length}초` : ''}.${p.style ? `\n게임 소리 방향: ${p.style}` : ''}${p.ref}`,
      refPrompt: (r) => `\n\n기준 소리: 사용자가 가져온 "${r.name}"(${r.file})의 느낌으로 만들어 주세요. 그 파일을 잰 값:\n- 길이 ${r.seconds}초, ${r.loop ? '반복' : '한 번 재생'}\n- 최대 ${r.peak} dB, 음량 ${r.loud} LUFS\n- 에너지: 저역(250 Hz 아래) ${r.low}% · 중역 ${r.mid}% · 고역(4 kHz 위) ${r.high}%, 밝기 약 ${r.bright} Hz\n- 앞 무음 ${r.lead} ms, 뒤 무음 ${r.tail} ms\n길이, 음량, 대역 균형을 비슷하게 맞추되 그대로 베끼지는 마세요.`,
      importing: (i, n) => `가져오는 중 ${i}/${n}`, skipped: (n, why) => `${n}개 건너뜀: ${why}`,
      whyType: (n) => `소리 파일 아님 ${n}`, whyBig: (n) => `50MB 넘음·합계 500MB 넘음 ${n}`, whyBad: (n) => `읽지 못함 ${n}`, whyMany: (n) => `2000개 넘음 ${n}`,
      pruned: (n) => `저장 공간이 모자라 오래된 버린 시안 ${n}개를 정리했어요.`, saveFull: '저장 공간이 가득 차 자동 저장하지 못했어요. 내보내기로 묶음을 받아 두세요.',
      tutorialTitle: '게임 소리 만드는 법',
      steps: [
        ['가진 것 가져오기', '만들어 둔 소리, 게임에 필요한 소리 목록, 여기서 내보낸 묶음이 있으면 가져오기로 보드에 올려요.'],
        ['명세 받기', '오른쪽 위 메뉴의 명세에서 프롬프트를 복사해 게임 기획서를 가진 AI에게 보내고, 돌아온 명세를 붙여 넣어요.'],
        ['샘플 확인', '대표 소리가 먼저 나와요. 타일에 마우스를 올려 듣고 승인하세요.'],
        ['나머지 만들기', '승인한 샘플의 스타일로 나머지를 한 번에 만들어요.'],
        ['고치기', '타일을 누르면 선택되고 소리가 나요. 여러 개를 고르고 바꿀 내용을 적으세요. 시안 개수를 늘리면 여러 안을 비교해 고를 수 있어요. 길게 누르면 크게 열려요.'],
        ['내보내기', '승인한 소리를 저작권 고지와 함께 묶어요. 규격 검사는 AI가 소리를 내놓기 전에 끝내요.'],
      ],
    },
  };
  const t = (key, ...args) => { const v = TEXT[lang][key] ?? TEXT.en[key]; return typeof v === 'function' ? v(...args) : v; };
  const tr = (...args) => t(...args); // for scopes where t is a tile
  const tx = (v) => (v && typeof v === 'object' ? v[lang] ?? v.en : v); // data fields shaped { en, ko }; plain strings pass through
  const nm = (x) => tx(x.name);
  const statusText = (s) => t('status')[s];
  const stemName = (key) => { const m = /^tone_layer_(\d+)$/.exec(key); return m ? t('toneLayer', m[1]) : t('stems')[key] ?? key; };
  const noteText = (n) => (typeof n === 'string' ? n : n.key === 'draft' ? t('draftNote', n.text, n.k) : t(n.key));
  const chatText = (m) => (m.ai === 'drafts' ? t('madeDrafts', m.n) : m.ai === 'one' ? t('madeOne') : m.text);
  function applyStatic() {
    document.documentElement.lang = lang; document.title = t('docTitle');
    document.querySelectorAll('[data-i18n]').forEach((e) => { e.textContent = t(e.dataset.i18n); });
    document.querySelectorAll('[data-i18n-aria]').forEach((e) => e.setAttribute('aria-label', t(e.dataset.i18nAria)));
    document.querySelectorAll('[data-i18n-title]').forEach((e) => { e.title = t(e.dataset.i18nTitle); });
  }
  const color = (cat) => CATEGORIES.find((c) => c.id === cat)?.hue || 'var(--text3)';
  const seconds = (s) => t('sec', s < 10 ? s.toFixed(s < 1 ? 2 : 1) : s.toFixed(0));
  const stems = ['#E8AE72', '#87B9E8', '#8CCDB2', '#C7A0E8', '#F3C978'];

  /* ---------- state ---------- */
  const assets = ASSETS.map((d) => ({ ...d, status: d.sample ? 'draft' : 'pending', versions: [], current: 0, drafts: [], pick: -1, chat: [], progress: 0 }));
  const byId = (id) => assets.find((a) => a.id === id);
  let stage = 'sample', filter = { cat: null, status: null, imported: false }, focused = null, anchor = null, openAsset = null, detailTab = 'chat';
  // The board starts on stand-in work. The first import of the user's own work replaces it.
  let game = GAME, brief = BRIEF, platform = 'mobile', demo = true;
  const selected = new Set();
  let drafts = 1;

  /* ---------- AI self-check: nothing reaches the user before it has been through this ---------- */
  const MAX_CHECKS = 6;
  const rules = RULES.map((r) => ({ ...r }));
  const rule = (id) => rules.find((r) => r.id === id);
  const broken = (a, m) => rules.filter((r) => (!r.applies || r.applies(a)) && (r.text ? !r.read(m, a) : r.bad(r.read(m, a), r)));
  const build = (a, change, note) => { const sound = synth.render(a, change); return { sound, note, change, at: new Date(), peaks: synth.peaks(sound.mix, 200), measure: synth.measure(sound) }; };
  // Stands in for the AI reworking its own result; the backend replaces this with a model call.
  function reworked(m, change, left) {
    const next = { ...change }, has = (id) => left.some((r) => r.id === id);
    if (has('loud')) { const [low, high] = rule('loud').range; next.level = (next.level ?? 1) * 10 ** (((low + high) / 2 - m.loud) / 20); }
    if (has('peak') || has('clip')) next.ceiling = 10 ** ((rule('peak').limit - 0.2) / 20);
    if (has('dc')) next.dc = true;
    if (has('lead') || has('tail')) {
      const [front = 0, back = 0] = next.trim || [];
      next.trim = [front + (has('lead') ? Math.max(0, m.lead / 1000 - 0.005) : 0), back + (has('tail') ? Math.max(0, m.tail / 1000 - 0.05) : 0)];
    }
    return next;
  }
  // Stands in for the AI renaming the file and recording its sources.
  function repaired(a, left) {
    if (left.some((r) => r.id === 'name')) {
      const old = a.id; a.id = `sfx_${old.replace(/_sfx$/, '')}`;
      if (focused === old) focused = a.id;
    }
    // A brought-in sound's license is the user's to record, so the AI does not fill it in.
    if (left.some((r) => r.id === 'lic') && !a.imported) a.noLicense = false;
    return left.some((r) => r.text && !(r.id === 'lic' && a.imported));
  }
  function checked(a, change, note) {
    let v = build(a, change, note);
    for (let i = 0; i < MAX_CHECKS; i++) {
      const left = broken(a, v.measure);
      if (!left.length) break;
      const named = repaired(a, left), next = reworked(v.measure, v.change, left);
      if (!named && JSON.stringify(next) === JSON.stringify(v.change)) break;
      v = build(a, next, note);
    }
    return v;
  }
  function make(a, change = {}, note = { key: 'firstVersion' }) {
    a.versions.push(checked(a, change, note));
    a.current = a.versions.length - 1;
  }
  const version = (a) => a.versions[a.current];
  // A restored version is only its recipe (change + note); it is rendered the first time it is heard.
  const filled = (a, v) => {
    if (v && !v.sound) { const sound = synth.render(a, v.change); Object.assign(v, { sound, peaks: synth.peaks(sound.mix, 200), measure: synth.measure(sound) }); }
    return v;
  };
  const heard = (a) => filled(a, (a.pick >= 0 && a.drafts[a.pick]) || version(a));
  const issues = (a) => (a.versions.length ? broken(a, heard(a).measure) : []);
  const approve = (a) => { a.status = 'approved'; };
  assets.filter((a) => a.sample).forEach((a) => make(a));

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
    const v = heard(a), sound = v.sound, nodes = [], gains = {}, loop = opts.loop ?? !!a.loop;
    for (const s of sound.stems) {
      const buffer = ctx.createBuffer(1, s.data.length, sound.rate); buffer.copyToChannel(s.data, 0);
      const src = ctx.createBufferSource(), gain = ctx.createGain();
      src.buffer = buffer; src.loop = loop; src.connect(gain); gain.connect(master);
      gain.gain.value = stemLevel(s.name); gains[s.name] = gain;
      nodes.push(src);
    }
    const at = ctx.currentTime + 0.01;
    nodes.forEach((n) => n.start(at, opts.from || 0));
    player = { asset: a, nodes, gains, at: at - (opts.from || 0), length: sound.seconds, loop, hover: !!opts.hover };
    nodes[0].onended = () => { if (player?.nodes[0] === nodes[0]) { player = null; markPlaying(); opts.done?.(); } };
    markPlaying();
  }
  const position = () => (player ? ((ctx.currentTime - player.at) % player.length + player.length) % player.length : 0);
  function markPlaying() {
    document.querySelectorAll('.tile.playing').forEach((t) => t.classList.remove('playing'));
    const a = player?.asset;
    if (a) tileOf(a)?.classList.add('playing');
    $('nowPlaying').textContent = a ? nm(a) : '';
    setIcon($('playAll'), queue ? 'stop' : 'play');
    $('playAll').setAttribute('aria-label', queue ? t('stopAll') : t('playAll'));
    document.querySelector('.dWave')?.classList.toggle('on', !!a);
  }

  /* ---------- board ---------- */
  const tileOf = (a) => document.querySelector(`.tile[data-id="${a.id}"]`);
  const visible = () => assets.filter((a) => (!filter.cat || a.cat === filter.cat) && (!filter.status || a.status === filter.status) && (!filter.imported || a.imported));
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
    t.setAttribute('role', 'button'); t.setAttribute('aria-label', `${nm(a)}, ${statusText(a.status)}`);
    t.style.setProperty('--c', color(a.cat));
    if (a.music) t.classList.add('wide');
    if (selected.has(a.id)) t.classList.add('selected');
    if (player?.asset === a) t.classList.add('playing');
    if (a.versions.length) t.append(el('canvas'));
    if (a.imported) { t.classList.add('imported'); t.append(el('span', 'origin', tr('imported'))); }
    if (a.status === 'working') { const bar = el('div', 'bar'); bar.style.setProperty('--p', a.progress); t.append(bar); }
    if (a.status === 'review') {
      t.append(reviewRow(a, () => { drawTile(a); play(a); }));
    }
    const meta = el('div', 'meta'), name = el('span', 'name', nm(a)), sub = el('div', 'sub');
    const v = a.versions.length ? heard(a) : null;
    sub.append(el('span', '', v ? seconds(v.measure.seconds) : statusText(a.status)), el('span', '', a.status === 'working' ? statusText('working') : v && a.versions.length > 1 ? `v${a.current + 1}` : ''));
    meta.append(name, sub); t.append(meta, el('i', 'state'));
    t.addEventListener('pointerenter', () => hoverStart(a));
    t.addEventListener('pointerleave', hoverEnd);
    t.addEventListener('click', (e) => clickTile(a, e));
    t.addEventListener('pointerdown', (e) => hold(a, t, e));
    t.addEventListener('contextmenu', (e) => e.preventDefault());
    t.addEventListener('focus', () => { focused = a.id; syncDock(); });
    return t;
  }
  // Pick the previous version or one of the drafts, then keep or drop.
  function reviewRow(a, picked) {
    const row = el('div', 'ab');
    const option = (label, i) => {
      const b = el('button', '', label); b.dataset.pick = i; b.setAttribute('aria-pressed', String(a.pick === i));
      b.onclick = (e) => {
        e.stopPropagation(); a.pick = i;
        row.querySelectorAll('[data-pick]').forEach((x) => x.setAttribute('aria-pressed', String(+x.dataset.pick === i)));
        picked();
      };
      return b;
    };
    row.append(option(t('previous'), -1), ...a.drafts.map((_, i) => option(a.drafts.length > 1 ? String(i + 1) : t('newVersion'), i)));
    row.append(iconButton('check', t('keep'), (e) => { e.stopPropagation(); settle(a, true); }, 'keep'), iconButton('close', t('drop'), (e) => { e.stopPropagation(); settle(a, false); }, 'drop'));
    return row;
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
      h.append(dot, tx(c.name), el('span', '', String(list.length)));
      const pickable = ready(list);
      if (pickable.length) {
        const all = el('button', 'ghost', pickable.every((x) => selected.has(x.id)) ? t('deselect') : t('selectAll'));
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
  function importHint() {
    const box = el('div', 'note importHint'), text = el('span', '', t('importHint')), b = el('button', 'primary', t('importShort'));
    text.style.flex = '1'; b.id = 'importHintBtn'; b.prepend(Object.assign(el('span', 'importIco'), { innerHTML: `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS.upload}</svg>` }));
    b.onclick = () => importDialog(); box.append(text, b);
    return box;
  }
  function banner() {
    const unchecked = assets.filter((a) => a.status === 'draft');
    const box = el('div', 'note'); box.style.cssText = 'display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:6px';
    const all = el('button', 'ghost', t('approveAll')); all.id = 'approveAll'; all.onclick = () => { unchecked.forEach(approve); renderBoard(); };
    if (stage !== 'sample') {
      const out = [], empty = assets.filter((a) => a.status === 'pending');
      if (empty.length) {
        const row = box.cloneNode(), text = el('span', '', t('fillLeft', empty.length)), go = el('button', 'primary', t('fillAll'));
        text.style.flex = '1'; go.id = 'fillBtn'; go.onclick = () => fill(empty); row.append(text, go); out.push(row);
      }
      if (unchecked.length) {
        const text = el('span', '', t('leftToCheck', unchecked.length)); text.style.flex = '1';
        box.append(text, all); out.push(box);
      }
      return out;
    }
    if (demo) return [importHint(), sampleBanner(box, all)];
    return [sampleBanner(box, all)];
  }
  function sampleBanner(box, all) {
    const samples = assets.filter((a) => a.sample), done = samples.filter((a) => a.status === 'approved').length, rest = assets.filter((a) => a.status === 'pending').length;
    const text = el('span', '', done === samples.length ? t('samplesDone', samples.length, rest) : t('samplesProgress', samples.length, done, rest));
    text.style.flex = '1';
    const go = el('button', 'primary', t('makeRest')); go.id = 'expandBtn'; go.disabled = done !== samples.length; go.onclick = expand;
    box.append(text, all, go);
    return box;
  }
  function renderSide() {
    const side = $('side'); side.textContent = '';
    const item = (label, count, active, fn, hue) => {
      const b = el('button'); b.setAttribute('aria-pressed', String(active)); b.onclick = fn;
      if (hue) { const d = el('i', 'dot'); d.style.setProperty('--c', hue); b.append(d); }
      b.append(el('span', 'name', label), el('span', 'n', String(count)));
      return b;
    };
    side.append(el('h2', '', t('category')), item(t('all'), assets.length, !filter.cat, () => { filter.cat = null; renderBoard(); }));
    for (const c of CATEGORIES) side.append(item(tx(c.name), assets.filter((a) => a.cat === c.id).length, filter.cat === c.id, () => { filter.cat = filter.cat === c.id ? null : c.id; renderBoard(); }, c.hue));
    side.append(el('h2', '', t('statusHead')));
    for (const [id, label] of Object.entries(t('status'))) {
      const n = assets.filter((a) => a.status === id).length;
      if (n) side.append(item(label, n, filter.status === id, () => { filter.status = filter.status === id ? null : id; renderBoard(); }));
    }
    const mine = assets.filter((a) => a.imported).length;
    if (mine) side.append(el('h2', '', t('originHead')), item(t('imported'), mine, filter.imported, () => { filter.imported = !filter.imported; renderBoard(); }));
  }
  function renderHeader() {
    $('gameTitle').textContent = tx(game);
    const order = Object.entries(t('stages')), at = order.findIndex(([id]) => id === stage);
    $('stages').textContent = '';
    order.forEach(([, label], i) => { const li = el('li', i < at ? 'done' : '', label); if (i === at) li.setAttribute('aria-current', 'step'); $('stages').append(li); });
    const approved = assets.filter((a) => a.status === 'approved').length;
    $('counts').textContent = t('counts', assets.length, approved);
    const waiting = assets.filter((a) => a.status === 'review').length;
    $('review').hidden = !waiting || !!openAsset; $('reviewText').textContent = t('reviewCount', waiting);
    autosave();
  }
  function syncDock() {
    const count = selected.size, target = focused && byId(focused);
    $('selCount').hidden = !count; $('selCount').textContent = t('selected', count);
    $('selAll').hidden = $('selApprove').hidden = $('selClear').hidden = !count;
    document.body.classList.toggle('selecting', !!count);
    $('ask').placeholder = count ? t('askSelected', count) : target?.versions.length ? t('askOne', nm(target)) : t('askNone');
    $('send').disabled = !count && !target?.versions.length;
  }

  /* ---------- pointer ---------- */
  let hoverTimer = 0, lassoing = false;
  function hoverStart(a) {
    if (lassoing || !$('hoverPlay').checked || !a.versions.length || queue) return;
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => { if (player?.asset !== a) play(a, { hover: true }); }, 140);
  }
  // A loop has no end of its own, so one started by hovering stops with the hover.
  function hoverEnd() { clearTimeout(hoverTimer); if (player?.hover && player.loop) stopSound(); }
  const HOLD_MS = 450;
  let held = false;
  function hold(a, t, e) {
    held = false;
    if (e.button || !a.versions.length || e.target.closest('.ab')) return;
    const x0 = e.clientX, y0 = e.clientY;
    const end = () => { clearTimeout(timer); t.classList.remove('pressing'); removeEventListener('pointerup', end); removeEventListener('pointercancel', end); removeEventListener('pointermove', move); };
    const move = (ev) => { if (Math.hypot(ev.clientX - x0, ev.clientY - y0) > 8) end(); };
    const timer = setTimeout(() => { end(); held = true; openDetail(a); }, HOLD_MS);
    t.classList.add('pressing');
    addEventListener('pointerup', end); addEventListener('pointercancel', end); addEventListener('pointermove', move);
  }
  function clickTile(a, e) {
    if (held) { held = false; return; }
    if (!a.versions.length) return;
    if (e.shiftKey && anchor) {
      const list = visible(), from = list.indexOf(byId(anchor)), to = list.indexOf(a);
      list.slice(Math.min(from, to), Math.max(from, to) + 1).filter((x) => x.versions.length).forEach((x) => selected.add(x.id));
      refreshSelection();
    } else {
      const on = !selected.has(a.id);
      toggle(a); anchor = a.id; focused = on ? a.id : null;
      if (on) play(a); else if (player?.asset === a) stopSound();
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
    else if (e.key.toLowerCase() === 'x' && a?.versions.length) toggle(a);
    else if (e.key.toLowerCase() === 'a' && a) setStatus(a, 'approved');
    else if (e.key.toLowerCase() === 'r' && a) setStatus(a, 'flagged');
    else if (e.key === 'Escape') { selected.clear(); refreshSelection(); }
  });
  function setStatus(a, status) { if (a.status === 'draft' || a.status === 'approved' || a.status === 'flagged') { a.status = a.status === status ? 'draft' : status; const id = a.id; renderBoard(); tileOf(byId(id))?.focus(); } }

  /* ---------- simulated work ---------- */
  function changeFrom(text) {
    const low = text.toLowerCase(), has = (...w) => w.some((x) => low.includes(x));
    return { shift: has('높', '밝', '가볍', '귀엽', 'high', 'bright', 'light', 'cute') ? 1.25 : has('낮', '묵직', '무겁', '어둡', 'low', 'heavy', 'dark', 'deep') ? 0.8 : 1.1, stretch: has('짧', 'short') ? 0.7 : has('길', 'long') ? 1.4 : 0.95, level: has('작', '조용', '낮춰', 'quiet', 'soft', 'lower') ? 0.6 : has('크', '세게', 'loud', 'strong') ? 1.2 : 0.85 };
  }
  const SPREAD = [[1, 1], [0.89, 1.15], [1.12, 0.88], [0.8, 1.3]];
  const MAX_DRAFTS = SPREAD.length;
  // "시안 3개" in the request wins over the picker, so it can be asked for in plain words.
  function draftsWanted(text) {
    const said = text.match(/(?:시안|후보|drafts?|options?)\D{0,3}([1-9])|([1-9])\s*(?:개|가지)\s*(?:의\s*)?(?:시안|후보|버전)|([1-9])\s*(?:drafts?|options?|versions?)\b/i);
    return Math.min(MAX_DRAFTS, said ? +(said[1] || said[2] || said[3]) : drafts);
  }
  function draftPicker() {
    const box = el('label', 'draftPick', t('drafts')), pick = el('select');
    for (let i = 1; i <= MAX_DRAFTS; i++) pick.append(Object.assign(el('option', '', t('draftCount', i)), { value: i }));
    pick.value = drafts; pick.setAttribute('aria-label', t('draftCountLabel'));
    pick.onchange = () => { drafts = +pick.value; };
    box.append(pick); return box;
  }
  function request(list, text) {
    const change = changeFrom(text), count = draftsWanted(text);
    drafts = 1; $('draftSlot').replaceChildren(draftPicker());
    list.forEach((a, i) => {
      a.status = 'working'; a.progress = 0;
      a.chat.push({ me: true, text });
      const total = 1100 + i * 420 + count * 300 + Math.random() * 900, begun = performance.now();
      const tick = () => {
        a.progress = Math.min(1, (performance.now() - begun) / total);
        tileOf(a)?.querySelector('.bar')?.style.setProperty('--p', a.progress);
        if (a.progress < 1) { setTimeout(tick, 120); return; }
        a.drafts = SPREAD.slice(0, count).map(([shift, stretch], k) => checked(a, { ...change, shift: change.shift * shift, stretch: change.stretch * stretch }, count > 1 ? { key: 'draft', text, k: k + 1 } : text));
        a.pick = 0; a.status = 'review';
        a.chat.push(count > 1 ? { ai: 'drafts', n: count } : { ai: 'one' });
        renderOpen(a);
      };
      tick();
    });
    selected.clear(); renderOpen();
  }
  function renderOpen(a) { if (openAsset && (!a || a === openAsset)) renderDetail(); else if (openAsset) renderHeader(); else renderBoard(); }
  function settle(a, keep) {
    const chosen = keep ? a.drafts[a.pick] : null;
    if (chosen) { a.versions.push(...a.drafts.filter((v) => v !== chosen), chosen); a.current = a.versions.length - 1; } // the others stay in the history
    a.drafts = []; a.pick = -1; a.status = keep ? 'approved' : 'draft';
    if (player?.asset === a) stopSound();
    renderOpen();
  }
  function expand() {
    stage = 'expand'; stopSound();
    const rest = assets.filter((a) => a.status === 'pending');
    toast(t('expanding', rest.length));
    rest.forEach((a, i) => setTimeout(() => {
      const t = tileOf(a);
      make(a); a.status = 'draft';
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
  $('selAll').onclick = () => { ready(visible()).forEach((x) => selected.add(x.id)); renderBoard(); };
  $('selClear').onclick = () => { selected.clear(); renderBoard(); };
  $('selApprove').onclick = () => { [...selected].map(byId).filter((a) => a.status === 'draft' || a.status === 'flagged').forEach(approve); selected.clear(); renderBoard(); };
  $('acceptAll').onclick = () => { assets.filter((a) => a.status === 'review').forEach((a) => settle(a, true)); };
  $('rejectAll').onclick = () => { assets.filter((a) => a.status === 'review').forEach((a) => settle(a, false)); };

  /* ---------- detail ---------- */
  let stemState = {};
  const stemLevel = (name) => {
    const list = Object.values(stemState), anySolo = list.some((s) => s.solo), s = stemState[name] || { gain: 1 };
    return s.mute || (anySolo && !s.solo) ? 0 : s.gain;
  };
  const applyStems = () => { if (player) for (const [name, g] of Object.entries(player.gains)) g.gain.value = stemLevel(name); };
  const transition = (fn) => (document.startViewTransition && !matchMedia('(prefers-reduced-motion: reduce)').matches ? document.startViewTransition(fn) : fn());

  function showDetail(on) {
    $('boardView').hidden = on; $('detailView').hidden = !on; $('dock').hidden = on;
  }
  let walk = [];
  function openDetail(a) {
    const tile = tileOf(a);
    walk = ready(visible());
    if (!walk.includes(a)) walk.unshift(a);
    if (tile) tile.style.viewTransitionName = 'zoom';
    transition(() => {
      if (tile) tile.style.viewTransitionName = '';
      stopSound(); openAsset = a; focused = a.id; stemState = {}; detailTab = 'chat'; showDetail(true); renderDetail();
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
    const list = walk.filter((a) => assets.includes(a) && a.versions.length), at = list.indexOf(openAsset), next = list[(at + by + list.length) % list.length];
    if (next) { stopSound(); openAsset = next; focused = next.id; stemState = {}; renderDetail(); }
  }
  function toggleDetailPlay() { if (player?.asset === openAsset) stopSound(); else play(openAsset, { loop: !!(openAsset.loop || openAsset.music) }); renderPlayButton(); }
  function renderPlayButton() { const b = $('dPlay'); if (b) { setIcon(b, player?.asset === openAsset ? 'stop' : 'play'); b.setAttribute('aria-label', player ? t('stop') : t('play')); } }

  function renderDetail() {
    const a = openAsset, v = heard(a), m = v.measure, box = $('detailView'), left = issues(a);
    box.textContent = '';
    const main = el('div', 'dMain'), head = el('div', 'dHead');
    const title = el('div'); title.style.cssText = 'min-width:0;flex:1';
    // Name and category apply as they are typed; there is nothing to save.
    const name = el('input', 'dName'); name.value = nm(a); name.setAttribute('aria-label', t('nameLabel'));
    name.oninput = () => { a.name = name.value; renderHeader(); };
    const h1 = el('h1'); h1.append(name);
    const fileRow = el('div', 'file', a.imported && a.file ? `${a.file} → ${a.id}.wav` : `${a.id}.wav`);
    title.append(h1, fileRow);
    const play = iconButton('play', t('play'), toggleDetailPlay); play.id = 'dPlay'; play.classList.add('primary');
    const approveBtn = el('button', a.status === 'approved' ? '' : 'primary', a.status === 'approved' ? t('approved') : t('approve'));
    approveBtn.onclick = () => { if (a.status === 'approved') a.status = 'draft'; else approve(a); renderDetail(); };
    approveBtn.disabled = a.status === 'working' || a.status === 'review';
    head.append(iconButton('back', t('toBoard'), closeDetail, 'ghost iconBtn'), title, iconButton('prev', t('prevAsset'), () => step(-1), 'ghost iconBtn'), iconButton('next', t('nextAsset'), () => step(1), 'ghost iconBtn'), play, approveBtn);
    const facts = el('p', 'dFacts');
    facts.append(catPicker(a, () => renderDetail()));
    if (a.imported) facts.append(el('span', 'originTag', t('imported')));
    for (const f of [seconds(m.seconds), t('peak', m.peak.toFixed(1)), t('loud', m.loud.toFixed(1)), a.loop ? t('loop') : t('oneShot'), statusText(a.status)]) facts.append(el('span', '', f));
    if (a.imported) { const like = el('button', '', t('likeThis')); like.id = 'likeThis'; like.onclick = () => likeThis(a); facts.append(like); }
    const wave = el('div', 'dWave'), canvas = el('canvas'); wave.append(canvas);
    wave.onclick = (e) => { const r = wave.getBoundingClientRect(); window.setTimeout(renderPlayButton); playFrom((e.clientX - r.left) / r.width * m.seconds); };
    if (a.status === 'review') {
      const row = el('div', 'tile'); row.style.cssText = 'height:auto;background:none;overflow:visible;margin-top:8px';
      const ab = reviewRow(a, renderDetail); ab.style.position = 'static';
      row.append(ab); wave.after(row);
      main.append(head, facts, wave, row);
    } else main.append(head, facts, wave);
    const spec = el('canvas', 'dSpec'); spec.id = 'dSpec'; spec.setAttribute('aria-label', t('spectrum')); main.append(spec);
    const th = el('div', 'dTrackHead'); th.append(el('h2', '', t('tracks', v.sound.stems.length))); main.append(th);
    v.sound.stems.forEach((s, i) => main.append(stemRow(s, i)));
    box.append(main, sidePanel(a));
    requestAnimationFrame(() => {
      const hue = resolved(color(a.cat));
      drawPeaks(canvas, v.peaks, hue);
      document.querySelectorAll('.stem').forEach((row, i) => drawPeaks(row.querySelector('canvas'), synth.peaks(v.sound.stems[i].data, 160), stems[i % stems.length]));
    });
    renderPlayButton(); renderHeader();
  }
  function playFrom(at) { play(openAsset, { from: at, loop: !!(openAsset.loop || openAsset.music) }); }
  function stemRow(s, i) {
    const st = stemState[s.name] ||= { mute: false, solo: false, gain: 1 };
    const row = el('div', 'stem'), name = el('div', 'sName'), dot = el('i'); dot.style.setProperty('--c', stems[i % stems.length]);
    const label = stemName(s.name);
    name.append(dot, label);
    const mute = iconButton(st.mute ? 'muted' : 'sound', st.mute ? t('stemOn', label) : t('stemOff', label), () => { st.mute = !st.mute; applyStems(); setIcon(mute, st.mute ? 'muted' : 'sound'); mute.setAttribute('aria-pressed', String(st.mute)); }, 'iconBtn mute');
    mute.setAttribute('aria-pressed', String(st.mute));
    const solo = iconButton('solo', t('stemSolo', label), null, 'iconBtn solo'); solo.setAttribute('aria-pressed', String(st.solo));
    solo.onclick = () => { st.solo = !st.solo; solo.setAttribute('aria-pressed', String(st.solo)); applyStems(); };
    const gain = el('input'); gain.type = 'range'; gain.min = 0; gain.max = 1.5; gain.step = 0.01; gain.value = st.gain; gain.setAttribute('aria-label', t('stemGain', label));
    gain.oninput = () => { st.gain = +gain.value; applyStems(); };
    row.append(name, el('canvas'), mute, solo, gain);
    return row;
  }
  function sourceOf(a) {
    if (a.source) return `// ${a.file || `${a.id}.wav`}\nsample("${a.id}.wav") |> out(%)`;
    return (a.layers || []).map((l) => {
      if (l.kind === 'bed') return `// ${stemName(l.stem)}\nnoise() |> lp(%, ${Math.round(l.cutoff * 8000)}) * ${l.gain} |> out(%)`;
      if (l.kind === 'tone') return `// ${nm(a)}\nsweep(${l.from}, ${l.to}, ${l.len}) |> ${l.wave}(%) * adsr(0, ${l.len}, 0, 0) * ${l.gain} |> out(%)`;
      if (l.kind === 'noise') return `noise() |> lp(%, ${Math.round(l.cutoff * 8000)}) * ar(${l.attack}, ${l.len}) * ${l.gain} |> out(%)`;
      if (l.kind === 'drums') return `// ${stemName(l.stem)}\nn"bd ~ bd ~" |> kick(@.trig) |> bus("drums")`;
      return `// ${stemName(l.stem)}\nn"${l.notes.slice(0, 8).filter((x) => x != null).join(' ')}" |> ${l.wave}(@.freq) * adsr(@.gate) |> bus("${l.stem}")`;
    }).join('\n\n');
  }
  function sidePanel(a) {
    const side = el('div', 'dSide'), tabs = el('div', 'tabs'), body = el('div', 'tabBody');
    tabs.setAttribute('role', 'tablist');
    for (const [id, label] of [['chat', t('tabChat')], ['code', t('tabCode')], ['versions', t('tabVersions', a.versions.length)], ['license', t('tabLicense')]]) {
      const b = el('button', '', label); b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', String(id === detailTab));
      b.onclick = () => { detailTab = id; renderDetail(); }; tabs.append(b);
    }
    if (detailTab === 'chat') {
      if (!a.chat.length) body.append(el('p', 'msg ai', t('chatEmpty', nm(a))));
      a.chat.forEach((m) => body.append(el('div', 'msg ' + (m.me ? 'me' : 'ai'), chatText(m))));
    } else if (detailTab === 'code') {
      if (a.prompt) { const p = el('pre', 'code prompt', a.prompt); p.id = 'promptText'; body.append(el('h3', 'tabHead', t('promptHead')), p); }
      body.append(el('pre', 'code', sourceOf(a)));
    }
    else if (detailTab === 'versions') {
      [...a.versions].reverse().forEach((v) => {
        const i = a.versions.indexOf(v), row = el('div', 'lineItem'), text = el('span', 'grow', `v${i + 1} · ${noteText(v.note)}`);
        row.append(text, iconButton('play', t('listen'), () => { a.current = i; renderDetail(); play(a); }, 'ghost iconBtn'));
        if (i === a.current) row.append(el('span', 'tag', t('current')));
        body.append(row);
      });
    } else {
      if (a.imported) body.append(el('p', 'msg ai', t('importedLicense')), ...licenseFields(a));
      else body.append(...licenseRows());
      const copy = el('button', '', t('copyLicenses')); copy.onclick = copyLicenses; body.append(copy);
    }
    const dock = el('form', 'detailDock'), input = el('input'); input.placeholder = t('askThis'); input.setAttribute('aria-label', t('askThis'));
    const send = iconButton('send', t('send'), null); send.type = 'submit';
    dock.onsubmit = (e) => { e.preventDefault(); const t = input.value.trim(); if (t && a.status !== 'working') request([a], t); };
    dock.append(draftPicker(), input, send);
    side.append(tabs, body, dock);
    return side;
  }
  function liveLoop() {
    requestAnimationFrame(liveLoop);
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
  let reopen = null; // redraws the open dialog in a new language
  dlg.addEventListener('click', (e) => {
    if (e.target !== dlg) return;
    const q = dlg.getBoundingClientRect();
    if (e.clientX < q.left || e.clientX > q.right || e.clientY < q.top || e.clientY > q.bottom) dlg.close();
  });
  function openDialog(title) {
    dlg.textContent = '';
    dlg.append(iconButton('close', t('close'), () => dlg.close(), 'ghost iconBtn dlgClose'), el('h2', '', title));
  }
  // ms 0 keeps it up until the next toast (progress).
  function toast(text, ms = 2200) {
    const t = $('toast'); t.textContent = text; t.hidden = false;
    clearTimeout(toast.t); if (ms) toast.t = setTimeout(() => { t.hidden = true; }, ms);
  }
  async function copy(text, done) {
    try { await navigator.clipboard.writeText(text); }
    catch {
      const area = el('textarea'); area.value = text; (dlg.open ? dlg : document.body).append(area); area.select(); document.execCommand('copy'); area.remove();
    }
    toast(done);
  }
  const licenseText = () => `${t('licenseTitle', tx(game))}\n\n` + [...LICENSES.map((l) => `${l.name}\n  ${t('use')}: ${tx(l.use)}\n  ${t('license')}: ${l.license}\n  ${t('holder')}: ${l.holder}`), ...assets.filter((a) => a.imported).map((a) => `${a.file || a.id} (${nm(a)})\n  ${t('license')}: ${a.license || t('noLicenseYet')}\n  ${t('holder')}: ${a.holder || '-'}`)].join('\n\n') + '\n';
  const copyLicenses = () => copy(licenseText(), t('copiedLicenses'));
  const licenseRows = () => LICENSES.map((l) => { const r = el('div', 'lineItem'); r.append(el('span', 'grow', `${l.name} · ${tx(l.use)}`), el('span', 'tag', l.license)); return r; });

  const specExample = () => {
    const ex = t('example'), ids = [['sfx_ui_click', 'ui', 0.1, false], ['sfx_combat_parry', 'combat', 0.3, false], ['bgm_garden', 'bgm', 60, true]];
    return JSON.stringify({ game: tx(game), platform: 'mobile', style: ex.style, assets: ids.map(([id, category, length, loop], k) => ({ id, name: ex.assets[k].name, category, length, loop, when: ex.assets[k].when, description: ex.assets[k].description })), questions: [] }, null, 2);
  };
  const specForm = () => JSON.stringify({ game: '', platform: '', style: '', assets: [{ id: '', name: '', category: '', length: 0, loop: false, when: '', description: '' }], questions: [] }, null, 2);
  // Only what this tool knows goes in. The game itself is the other agent's to fill in.
  const specPrompt = () => t('specPrompt', {
    platforms: PROFILES.map((f) => f.id).filter((id) => id !== 'wide').join(', '),
    cats: CATEGORIES.map((c) => c.id).join(', '),
    dur: rule('dur').limit,
    licenses: LICENSES.map((l) => `${l.name}(${l.license})`).join(', '),
    form: specForm(),
  });

  function specDialog(tab = 'send', draft = '') {
    openDialog(t('spec'));
    reopen = () => specDialog(tab, $('specIn')?.value || draft);
    const body = el('div'), tabs = el('div', 'tabs'); tabs.style.padding = '0 0 0';
    const paint = () => {
      tabs.textContent = ''; body.textContent = '';
      for (const [id, label] of [['send', t('sendPrompt')], ['receive', t('receiveSpec')]]) { const b = el('button', '', label); b.setAttribute('aria-selected', String(tab === id)); b.onclick = () => { tab = id; paint(); }; tabs.append(b); }
      if (tab === 'send') {
        body.append(el('p', '', t('pasteToAgent')));
        const area = el('textarea'); area.value = specPrompt(); area.readOnly = true; area.setAttribute('aria-label', t('prompt'));
        const row = el('div', 'dlgRow'), b = el('button', 'primary', t('copyPrompt')); b.id = 'copyPrompt'; b.onclick = () => copy(specPrompt(), t('copiedPrompt'));
        row.append(b); body.append(area, row);
      } else receive(body, draft);
    };
    dlg.append(tabs, el('div'), body); body.style.marginTop = '12px'; paint(); dlg.showModal();
  }
  function receive(body, draft = '') {
    body.append(el('p', '', t('pasteSpec')));
    const area = el('textarea'); area.id = 'specIn'; area.setAttribute('aria-label', t('spec')); area.value = draft;
    const out = el('div'), row = el('div', 'dlgRow'), sample = el('button', 'ghost', t('insertExample'));
    const check = () => { out.textContent = ''; if (area.value.trim()) out.append(...planSpec(area.value)); };
    area.oninput = check; sample.onclick = () => { area.value = specExample(); check(); };
    row.append(sample); body.append(area, row, out); check();
  }
  function planSpec(text) {
    let spec;
    try { spec = JSON.parse(text); } catch (e) { return [el('p', 'note err', t('notJson', e.message))]; }
    if (!Array.isArray(spec.assets)) return [el('p', 'note err', t('noAssets'))];
    const cats = CATEGORIES.map((c) => c.id), bad = spec.assets.filter((x) => !/^(sfx|amb|bgm)_[a-z0-9_]+$/.test(x.id || '') || !cats.includes(x.category));
    if (bad.length) return [el('p', 'note err', t('badItems', bad.length, bad.map((x) => x.id || t('noName')).join(', ')))];
    const ids = new Set(spec.assets.map((x) => x.id)), added = spec.assets.filter((x) => !byId(x.id)), changed = spec.assets.filter((x) => byId(x.id) && nm(byId(x.id)) !== x.name), kept = spec.assets.filter((x) => byId(x.id) && nm(byId(x.id)) === x.name), gone = assets.filter((a) => !ids.has(a.id));
    const out = [el('h3', '', t('planSummary', added.length, changed.length, kept.length, gone.length))];
    const line = (tag, cls, text) => { const r = el('div', 'lineItem'); r.append(el('span', 'tag ' + cls, tag), el('span', 'grow', text)); return r; };
    added.forEach((x) => out.push(line(t('tagAdd'), 'add', `${x.name} · ${x.id}`)));
    changed.forEach((x) => out.push(line(t('tagChange'), 'chg', `${nm(byId(x.id))} → ${x.name}`)));
    gone.slice(0, 6).forEach((a) => out.push(line(t('tagRemove'), 'del', nm(a))));
    if (gone.length > 6) out.push(el('p', '', t('moreRemoved', gone.length - 6)));
    const row = el('div', 'dlgRow'), run = el('button', 'primary', t('startWithSpec')), keep = el('button', '', t('addOnly'));
    const apply = (remove) => {
      const target = PROFILES.find((f) => f.id === spec.platform);
      if (target) { rule('loud').range = [...target.loud]; platform = target.id; }
      if (spec.game) game = spec.game;
      if (spec.style) brief = spec.style;
      demo = false;
      added.forEach((x) => { const a = { id: x.id, name: x.name, cat: x.category, music: false, loop: !!x.loop || x.id.startsWith('amb_'), layers: x.id.startsWith('amb_') ? [STUDIO_DATA.bed(x.name, x.length >= 16 ? 16 : 8, 0.1, 0.4, [[1, 0.25, 0], [3, 0.15, 1]])] : [{ kind: 'tone', from: 500, to: 700, len: Math.min(0.6, x.length || 0.3), wave: 'triangle', gain: 0.4, at: 0 }], status: 'draft', versions: [], current: 0, drafts: [], pick: -1, chat: [], progress: 0 }; assets.push(a); make(a, {}, { key: 'fromSpec' }); });
      changed.forEach((x) => { byId(x.id).name = x.name; });
      if (remove) gone.forEach((a) => assets.splice(assets.indexOf(a), 1));
      dlg.close(); renderBoard(); toast(t('specApplied', added.length));
    };
    run.onclick = () => apply(true); keep.onclick = () => apply(false);
    row.append(keep, run); out.push(row);
    return out;
  }
  function exportDialog() {
    openDialog(t('export')); reopen = exportDialog;
    const going = assets.filter((a) => a.status === 'approved'), undone = assets.filter((a) => a.status !== 'approved');
    const left = going.filter((a) => issues(a).length);
    if (left.length) dlg.append(el('p', 'note err', t('exportIssues', left.length, left.map(nm).join(', '))));
    if (undone.length) dlg.append(el('p', 'note', t('exportUnapproved', undone.length)));
    dlg.append(el('h3', '', t('inBundle')));
    for (const item of t('bundleItems')) dlg.append(Object.assign(el('div', 'lineItem'), { textContent: item }));
    dlg.append(el('h3', '', t('licenses')));
    dlg.append(...licenseRows());
    const row = el('div', 'dlgRow'), go = el('button', 'primary', t('exportBundle')), lic = el('button', '', t('copyLicenses'));
    go.id = 'exportGo'; go.onclick = () => { dlg.close(); stage = 'export'; renderHeader(); exportBundle(); };
    lic.onclick = copyLicenses; row.append(lic, go); dlg.append(row);
    dlg.showModal();
  }
  function gameDialog() {
    openDialog(tx(game)); reopen = gameDialog;
    dlg.append(el('p', '', tx(brief)));
    const b = el('button', '', t('restart')); b.onclick = async () => { await forget(); location.reload(); }; dlg.append(b);
    dlg.showModal();
  }

  function settingsDialog() {
    openDialog(t('settings')); reopen = settingsDialog;
    const pick = el('select'); pick.id = 'langPick'; pick.setAttribute('aria-label', t('language'));
    pick.add(new Option('English', 'en')); pick.add(new Option('한국어', 'ko')); pick.value = lang;
    // In the music studio the host owns the language, so the choice also goes up to it.
    pick.onchange = () => { if (inHost) parent.postMessage({ type: 'asset:setlang', lang: pick.value }, '*'); setLang(pick.value); };
    const row = el('div', 'lineItem'); row.append(el('span', 'grow', t('language')), pick);
    const hover = el('input'); hover.type = 'checkbox'; hover.checked = $('hoverPlay').checked;
    hover.onchange = () => { $('hoverPlay').checked = hover.checked; };
    const row2 = el('label', 'lineItem'); row2.append(el('span', 'grow', t('hoverPlay')), hover);
    dlg.append(row, row2); if (!dlg.open) dlg.showModal();
  }

  /* ---------- header menu ---------- */
  const menu = $('menu'), menuBtn = $('menuBtn');
  function toggleMenu(open = menu.hidden) {
    menu.hidden = !open; menuBtn.setAttribute('aria-expanded', String(open));
    if (open) menu.querySelector('button').focus();
  }
  menuBtn.onclick = (e) => { e.stopPropagation(); toggleMenu(); };
  menu.onclick = (e) => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    toggleMenu(false);
    ({ settings: settingsDialog, spec: () => specDialog(), game: gameDialog, help: tutorial })[b.dataset.act]();
  };
  addEventListener('click', (e) => { if (!menu.hidden && !e.target.closest('.menuWrap')) toggleMenu(false); });
  menu.addEventListener('keydown', (e) => {
    const items = [...menu.querySelectorAll('button')], i = items.indexOf(document.activeElement);
    if (e.key === 'Escape') { toggleMenu(false); menuBtn.focus(); }
    else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus(); }
  });

  function tutorial() {
    openDialog(t('tutorialTitle')); reopen = tutorial;
    const list = el('ol', 'steps');
    for (const [what, how] of t('steps')) { const li = el('li'); li.append(el('b', '', what), el('span', '', how)); list.append(li); }
    const row = el('div', 'dlgRow'), b = el('button', 'primary', t('importShort')); b.id = 'tutorialImport';
    b.onclick = () => { dlg.close(); importDialog(); };
    row.append(b); dlg.append(list, row); dlg.showModal();
  }

  /* ---------- bringing existing work in ---------- */
  const { AUDIO, SPEC } = importer;
  const blank = (o) => ({ status: 'pending', versions: [], current: 0, drafts: [], pick: -1, chat: [], progress: 0, music: false, loop: false, layers: [], ...o });
  const takenIds = () => new Set(assets.map((a) => a.id));
  const base = (path) => path.split(/[\\/]/).pop();
  const stem = (path) => base(path).replace(/\.[^.]+$/, '');
  // Leaves the stand-in board the first time the user's own work comes in.
  function leaveDemo(name) {
    if (!demo) return;
    demo = false; stopSound(); queue = null; selected.clear(); filter = { cat: null, status: null, imported: false };
    assets.length = 0; stage = 'expand';
    if (name) { game = name; brief = ''; }
  }
  // Decoded at the synth's rate so a brought-in sound plays, measures and renders like a made one.
  async function decode(bytes) {
    const ac = new OfflineAudioContext(1, 1, 22050);
    const buf = await ac.decodeAudioData(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
    const data = new Float32Array(buf.length);
    for (let c = 0; c < buf.numberOfChannels; c++) { const ch = buf.getChannelData(c); for (let i = 0; i < data.length; i++) data[i] += ch[i] / buf.numberOfChannels; }
    return data;
  }
  function fromAudio(a, data, note) {
    a.source = data; a.layers = [];
    const sound = synth.render(a);
    a.versions = [{ sound, note: { key: note }, change: {}, at: new Date(), peaks: synth.peaks(sound.mix, 200), measure: synth.measure(sound) }];
    a.current = 0;
  }
  // Every way in ends here: picked files, a dropped folder, a zip, or an unzipped bundle.
  // Sizes are checked before anything is read, so a 10 GB file or a folder of photos cannot freeze the tab.
  const { LIMITS } = importer;
  const tally = () => ({ type: 0, big: 0, bad: 0, many: 0 });
  function skippedText(sk) {
    const why = [['whyType', sk.type], ['whyBig', sk.big], ['whyBad', sk.bad], ['whyMany', sk.many]].filter(([, n]) => n).map(([k, n]) => t(k, n));
    const n = sk.type + sk.big + sk.bad + sk.many;
    return n ? t('skipped', n, why.join(', ')) : '';
  }
  const report = (done, sk) => { const extra = skippedText(sk); toast(extra ? `${done} · ${extra}` : done, extra ? 6000 : 2200); };
  async function intake(entries) {
    const found = [], sk = tally();
    let total = 0;
    for (const e of entries.filter((x) => !importer.junk(x.path))) {
      const zipped = /\.zip$/i.test(e.path), size = e.size || 0;
      if (!zipped && !AUDIO.test(e.path) && !/\.json$/i.test(e.path)) { if (!/\.(md|txt)$/i.test(e.path)) sk.type++; continue; }
      if (size > (zipped ? LIMITS.total : LIMITS.file) || total + size > LIMITS.total) { sk.big++; continue; }
      total += size;
      if (!zipped) { found.push(e); continue; }
      try {
        const inside = await importer.unzip(await e.bytes(), LIMITS.file);
        sk.big += inside.skipped.filter((x) => x.why === 'big').length; sk.bad += inside.skipped.filter((x) => x.why === 'bad').length;
        for (const z of inside) {
          if (importer.junk(z.path)) continue;
          if (AUDIO.test(z.path) || /\.json$/i.test(z.path)) found.push({ path: z.path, size: z.size, bytes: async () => z.bytes });
          else if (!/\.(md|txt)$/i.test(z.path)) sk.type++;
        }
      } catch { sk.bad++; }
    }
    const spec = found.find((e) => base(e.path) === SPEC) || found.find((e) => /\.json$/i.test(e.path));
    if (spec) {
      let parsed = null;
      try { parsed = JSON.parse(new TextDecoder().decode(await spec.bytes())); } catch { /* not a bundle */ }
      if (parsed && Array.isArray(parsed.assets)) return openBundle(parsed, found, sk);
    }
    let sounds = found.filter((e) => AUDIO.test(e.path));
    sk.type += found.length - sounds.length;
    if (sounds.length > LIMITS.count) { sk.many += sounds.length - LIMITS.count; sounds = sounds.slice(0, LIMITS.count); }
    if (!sounds.length) { toast([t('nothingToImport'), skippedText(sk)].filter(Boolean).join(' · '), 5000); return; }
    return addSounds(sounds, sk);
  }
  // One file at a time, with a breath between them so the progress can paint.
  const breathe = () => new Promise((r) => setTimeout(r, 0));
  async function addSounds(files, sk = tally()) {
    const dirs = files.map((f) => f.path.split('/')), root = dirs.every((d) => d.length > 1 && d[0] === dirs[0][0]) ? dirs[0][0] : '';
    const added = [];
    let left = false, taken = null;
    for (const [i, f] of files.entries()) {
      if (files.length > 1) { toast(t('importing', i + 1, files.length), 0); await breathe(); }
      try {
        const data = await decode(await f.bytes()), path = root ? f.path.slice(root.length + 1) : f.path, secs = data.length / 22050;
        if (!data.length) throw new Error('empty');
        if (!left) { leaveDemo(root); left = true; taken = takenIds(); }
        const { cat, sure } = importer.guessCategory(path, secs), name = importer.guessName(path);
        const loopy = cat === 'env' || cat === 'bgm' || /loop/i.test(path);
        const a = blank({ id: importer.makeId(name, cat, taken), name, cat, music: cat === 'bgm', loop: loopy, imported: true, file: f.path, license: '', holder: '', guessed: !sure, status: 'approved' });
        fromAudio(a, data, 'importedNote');
        assets.push(a); added.push(a);
      } catch { sk.bad++; }
    }
    if (added.length && stage === 'sample') stage = 'expand';
    renderOpen();
    report(added.length ? t('importedN', added.length) : t('nothingToImport'), sk);
    if (added.length) importDialog(added);
  }
  // A bundle this screen exported: the spec says what each sound is, the audio files are the sounds.
  async function openBundle(spec, files, sk = tally()) {
    leaveDemo();
    assets.length = 0; selected.clear(); stopSound();
    game = spec.game || game; brief = spec.style || '';
    const target = PROFILES.find((f) => f.id === spec.platform);
    if (target) { platform = target.id; rule('loud').range = [...target.loud]; }
    let done = 0;
    for (const x of spec.assets) {
      if (spec.assets.length > 1) { toast(t('importing', ++done, spec.assets.length), 0); await breathe(); }
      if (!x || !x.id) continue;
      const audio = files.find((f) => AUDIO.test(f.path) && ((x.file && f.path.endsWith(x.file)) || stem(f.path) === x.id));
      const a = blank({ id: x.id, name: x.name || x.id, cat: CATEGORIES.some((c) => c.id === x.category) ? x.category : importer.guessCategory(x.id, x.length || 0).cat,
        loop: !!x.loop, music: x.category === 'bgm', when: x.when || '', description: x.description || '', length: x.length ?? null,
        imported: x.origin === 'imported', file: x.source_file || '', license: x.license || '', holder: x.holder || '', prompt: x.prompt || '' });
      if (audio) {
        try { fromAudio(a, await decode(await audio.bytes()), a.imported ? 'importedNote' : 'fromBundle'); a.status = x.status === 'approved' || !x.status ? 'approved' : 'draft'; }
        catch { sk.bad++; }
      }
      assets.push(a);
    }
    stage = 'expand'; renderOpen();
    report(t('bundleLoaded', tx(game), assets.length), sk);
  }
  // The pasted list becomes empty slots that "Fill with AI" makes.
  function addSlots(list) {
    leaveDemo();
    const taken = takenIds();
    for (const x of list) {
      const id = x.id && !taken.has(x.id) ? (taken.add(x.id), x.id) : importer.makeId(x.name, x.cat, taken);
      assets.push(blank({ id, name: x.name, cat: x.cat, loop: x.loop, music: x.cat === 'bgm', when: x.when, description: x.description, length: x.length }));
    }
    if (stage === 'sample') stage = 'expand';
    renderOpen(); toast(t('slotsAdded', list.length));
  }

  /* ---------- filling empty slots, optionally in the feel of a brought-in sound ---------- */
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const referenceFor = (a) => (a.ref && byId(a.ref)) || assets.find((r) => r.imported && r.versions.length && r.cat === a.cat) || null;
  function promptFor(a, ref) {
    let refText = '';
    if (ref) {
      const m = heard(ref).measure, r1 = (v) => Math.round(v * 10) / 10;
      refText = t('refPrompt', { name: nm(ref), file: ref.file || `${ref.id}.wav`, seconds: r1(m.seconds), loop: !!ref.loop, peak: r1(m.peak), loud: r1(m.loud), low: m.low, mid: m.mid, high: m.high, bright: m.bright, lead: Math.round(m.lead), tail: Math.round(m.tail) });
    }
    const cat = CATEGORIES.find((c) => c.id === a.cat);
    return t('fillPrompt', { name: nm(a), id: a.id, cat: cat ? tx(cat.name) : a.cat, game: tx(game), when: a.when, description: a.description, loop: !!a.loop, length: a.length, style: tx(brief), ref: refText });
  }
  // Stands in for the model that reads the prompt; it at least follows the reference's length and band balance.
  function layersFor(a, m) {
    if (a.cat === 'bgm') { a.music = true; return STUDIO_DATA.music(a.id, a.name, 100, 57, 'bright').layers; }
    if (a.loop) return [STUDIO_DATA.bed('main', (a.length || m?.seconds || 8) >= 12 ? 16 : 8, m ? clamp(m.bright / 6000, 0.03, 0.6) : 0.1, 0.4, [[1, 0.25, 0], [3, 0.15, 1]])];
    const len = clamp(m ? m.seconds : a.length || 0.3, 0.05, 2), f = m ? clamp(m.bright, 150, 3000) : 600, airy = m ? m.high / 100 : 0.3;
    return [{ kind: 'tone', from: f * 1.2, to: f * 0.8, len, wave: 'triangle', gain: 0.45 * (1 - airy / 2), at: 0 }, { kind: 'noise', len: len * 0.8, cutoff: clamp(airy + 0.2, 0.1, 0.95), gain: 0.35 * (0.3 + airy), attack: 0.002, at: 0 }];
  }
  function fill(list, ref) {
    list.forEach((a) => {
      const r = ref || referenceFor(a);
      if (r) a.ref = r.id;
      a.prompt = promptFor(a, r);
      if (!a.layers?.length) a.layers = layersFor(a, r && heard(r).measure);
      a.status = 'working'; a.progress = 0;
      if (inHost) parent.postMessage({ type: 'asset:prompt', id: a.id, prompt: a.prompt }, '*');
    });
    toast(t('filling', list.length));
    list.forEach((a, i) => setTimeout(() => { make(a, {}, { key: 'fromPrompt' }); a.status = 'draft'; a.progress = 1; renderOpen(); }, 300 + i * 120));
    renderOpen();
  }
  function likeThis(ref) {
    let list = assets.filter((a) => a.status === 'pending' && a.cat === ref.cat);
    if (!list.length) {
      const a = blank({ id: importer.makeId(`${nm(ref)} like`, ref.cat, takenIds()), name: t('likeName', nm(ref)), cat: ref.cat, loop: !!ref.loop, music: !!ref.music });
      assets.push(a); list = [a];
    }
    closeDetail(); fill(list, ref); toast(t('likeMade', list.length));
  }

  /* ---------- import dialog ---------- */
  function catPicker(a, done) {
    const pick = el('select', 'catPick' + (a.guessed ? ' unsure' : ''));
    for (const c of CATEGORIES) pick.append(Object.assign(el('option', '', tx(c.name)), { value: c.id }));
    pick.value = a.cat; pick.setAttribute('aria-label', t('category'));
    if (a.guessed) pick.title = t('guessed');
    pick.onchange = () => { a.cat = pick.value; a.guessed = false; pick.classList.remove('unsure'); if (a.cat === 'bgm') a.music = true; done?.(); };
    return pick;
  }
  function licenseFields(a) {
    const field = (key, label) => { const i = el('input', 'licIn'); i.value = a[key] || ''; i.placeholder = label; i.setAttribute('aria-label', label); i.oninput = () => { a[key] = i.value.trim(); autosave(); }; return i; };
    return [field('license', t('licenseLater')), field('holder', t('holderLater'))];
  }
  function importDialog(just = []) {
    openDialog(t('importTitle')); reopen = () => importDialog(just);
    dlg.append(el('p', '', t('importIntro')));
    if (just.length) {
      dlg.append(el('h3', '', t('justImported')));
      const box = el('div', 'justList');
      for (const a of just) {
        const row = el('div', 'lineItem justRow'), name = el('input', 'grow'); name.value = nm(a); name.setAttribute('aria-label', t('nameLabel'));
        name.oninput = () => { a.name = name.value; renderBoard(); };
        const [lic] = licenseFields(a);
        row.append(name, catPicker(a, renderBoard), lic, el('span', 'tag', base(a.file)));
        box.append(row);
      }
      dlg.append(box);
    }
    const section = (head, help, ...buttons) => { const s = el('section', 'importPart'), row = el('div', 'dlgRow'); row.style.justifyContent = 'flex-start'; row.append(...buttons); s.append(el('h3', '', head), el('p', '', help), row); return s; };
    const pickFiles = el('button', 'primary', t('pickFiles')); pickFiles.id = 'pickFiles'; pickFiles.onclick = () => $('importFiles').click();
    const pickFolder = el('button', '', t('pickFolder')); pickFolder.id = 'pickFolder'; pickFolder.onclick = () => $('importFolder').click();
    const pickBundle = el('button', '', t('pickBundle')); pickBundle.id = 'pickBundle'; pickBundle.onclick = () => $('importFiles').click();
    dlg.append(section(t('importFilesHead'), t('importFilesHelp'), pickFiles, pickFolder), section(t('importBundleHead'), t('importBundleHelp'), pickBundle));
    const area = el('textarea'); area.id = 'listIn'; area.placeholder = t('listPlaceholder'); area.setAttribute('aria-label', t('importListHead')); area.style.minHeight = '110px';
    const add = el('button', 'primary', t('addSlots', 0)); add.id = 'addSlots'; add.disabled = true;
    const count = el('span', 'listCount');
    area.oninput = () => { const n = importer.parseList(area.value).length; add.textContent = t('addSlots', n); add.disabled = !n; count.textContent = n ? t('listCount', n) : ''; };
    add.onclick = () => { const list = importer.parseList(area.value); if (!list.length) return; dlg.close(); addSlots(list); };
    const list = section(t('importListHead'), t('importListHelp'), count, add); list.insertBefore(area, list.lastChild);
    dlg.append(list);
    if (!dlg.open) dlg.showModal();
  }
  const fileEntry = (f, path) => ({ path, size: f.size, bytes: async () => new Uint8Array(await f.arrayBuffer()) });
  const filesOf = (input) => [...input.files].map((f) => fileEntry(f, f.webkitRelativePath || f.name));
  for (const id of ['importFiles', 'importFolder']) $(id).onchange = (e) => { const list = filesOf(e.target); e.target.value = ''; if (dlg.open) dlg.close(); intake(list); };
  // A dropped folder arrives as directory entries; walk them so nested files keep their folder path.
  async function walkEntry(entry, out) {
    if (entry.isFile) { const f = await new Promise((ok, no) => entry.file(ok, no)); out.push(fileEntry(f, entry.fullPath.replace(/^\//, ''))); return; }
    const reader = entry.createReader();
    for (;;) { const batch = await new Promise((ok, no) => reader.readEntries(ok, no)); if (!batch.length) break; for (const e of batch) await walkEntry(e, out); }
  }
  let dragDepth = 0;
  const carriesFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
  addEventListener('dragenter', (e) => { if (!carriesFiles(e)) return; dragDepth++; $('dropZone').hidden = false; });
  addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $('dropZone').hidden = true; });
  addEventListener('dragover', (e) => { if (carriesFiles(e)) e.preventDefault(); });
  addEventListener('drop', async (e) => {
    if (!carriesFiles(e)) return;
    e.preventDefault(); dragDepth = 0; $('dropZone').hidden = true;
    const entries = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry?.()).filter(Boolean), out = [];
    if (entries.length) for (const x of entries) await walkEntry(x, out);
    else out.push(...[...e.dataTransfer.files].map((f) => fileEntry(f, f.name)));
    if (dlg.open) dlg.close();
    intake(out);
  });

  /* ---------- export ---------- */
  function exportBundle() {
    const going = assets.filter((a) => a.status === 'approved' && a.versions.length), utf8 = (s) => new TextEncoder().encode(s);
    const spec = {
      game: tx(game), platform, style: tx(brief) || '',
      assets: assets.map((a) => {
        const v = a.versions.length ? heard(a) : null;
        return { id: a.id, name: nm(a), category: a.cat, length: v ? Math.round(v.measure.seconds * 100) / 100 : a.length ?? null, loop: !!a.loop, when: a.when || '', description: a.description || '',
          file: going.includes(a) ? `audio/${a.id}.wav` : null, status: a.status === 'approved' ? 'approved' : a.versions.length ? 'draft' : 'pending',
          origin: a.imported ? 'imported' : 'made', ...(a.imported ? { source_file: a.file || '', license: a.license || '', holder: a.holder || '' } : {}), ...(a.prompt ? { prompt: a.prompt } : {}) };
      }),
      questions: [],
    };
    const credits = `# ${tx(game)}\n\n${licenseText().split('\n').slice(2).join('\n')}`;
    const lint = going.map((a) => ({ id: a.id, issues: issues(a).map((r) => r.id) }));
    const files = [{ path: SPEC, bytes: utf8(JSON.stringify(spec, null, 2)) }, { path: 'CREDITS.md', bytes: utf8(credits) }, { path: 'lint-report.json', bytes: utf8(JSON.stringify(lint, null, 2)) },
      ...going.map((a) => ({ path: `audio/${a.id}.wav`, bytes: importer.encodeWav(heard(a).sound.mix, heard(a).sound.rate) }))];
    const link = el('a'); link.href = URL.createObjectURL(importer.zip(files));
    link.download = `${(tx(game) || 'game').replace(/[\\/:*?"<>|\s]+/g, '-')}-audio.zip`;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    toast(t('exported', going.length));
  }

  /* ---------- autosave: the board survives a reload, a closed tab and a trip to the game ---------- */
  // IndexedDB holds the board as recipes (each version is its change + note, re-rendered when heard) and every
  // brought-in sound as a Blob. Nothing to press: every change is written shortly after it happens.
  const SAVE_DB = 'olmuse-asset-board';
  let dbOpen = null, saveTimer = 0, chain = Promise.resolve(), paused = true, warnedFull = false;
  const savedAudio = new Set();
  const idb = () => (dbOpen ||= new Promise((ok, no) => {
    const r = indexedDB.open(SAVE_DB, 1);
    r.onupgradeneeded = () => { r.result.createObjectStore('board'); r.result.createObjectStore('audio'); };
    r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); r.onblocked = () => no(new Error('blocked'));
  }));
  const done = (q) => new Promise((ok, no) => { q.oncomplete = () => ok(); q.onerror = () => no(q.error); q.onabort = () => no(q.error || new Error('abort')); });
  const asked = (q) => new Promise((ok, no) => { q.onsuccess = () => ok(q.result); q.onerror = () => no(q.error); });
  const keyOf = (a) => (a.key ||= `k${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`);
  const recipe = (v) => ({ change: v.change, note: v.note, at: v.at });
  function snapshot() {
    return {
      v: 1, game, brief, platform, demo, stage, loud: [...rule('loud').range],
      assets: assets.map((a) => {
        const { versions, drafts: options, source, progress, ...rest } = a;
        // Work that was still running comes back as it was before the request; it can be asked again.
        const status = a.status === 'working' ? (versions.length ? 'draft' : 'pending') : a.status;
        return { ...rest, key: source ? keyOf(a) : a.key, status, versions: versions.map(recipe), drafts: status === 'review' ? options.map(recipe) : [], pick: status === 'review' ? a.pick : -1, hasSource: !!source };
      }),
    };
  }
  async function write() {
    const data = snapshot(), d = await idb(), keep = new Set(assets.filter((a) => a.source).map(keyOf));
    const q = d.transaction(['board', 'audio'], 'readwrite');
    q.objectStore('board').put(data, 'board');
    for (const a of assets) if (a.source && !savedAudio.has(a.key)) q.objectStore('audio').put(new Blob([a.source]), a.key);
    for (const k of savedAudio) if (!keep.has(k)) q.objectStore('audio').delete(k);
    await done(q);
    savedAudio.clear(); keep.forEach((k) => savedAudio.add(k));
  }
  // Oldest versions that are not the one in use go first: drafts that lost a comparison stay in the history.
  function prune() {
    const old = assets.flatMap((a) => a.versions.map((v) => ({ a, v })).filter((x) => x.v !== x.a.versions[x.a.current])).sort((x, y) => x.v.at - y.v.at);
    const cut = old.slice(0, Math.max(1, Math.ceil(old.length / 2)));
    for (const { a, v } of cut) { const now = a.versions[a.current]; a.versions.splice(a.versions.indexOf(v), 1); a.current = a.versions.indexOf(now); }
    return old.length ? cut.length : 0;
  }
  const full = (e) => e && (e.name === 'QuotaExceededError' || /quota/i.test(e.message || ''));
  async function job() {
    try { await write(); navigator.storage?.persist?.().catch(() => {}); }
    catch (e) {
      if (!full(e)) return;
      let cleared = 0;
      for (let n = prune(); n; n = prune()) {
        cleared += n;
        try { await write(); toast(t('pruned', cleared), 5000); return; } catch (again) { if (!full(again)) return; }
      }
      if (!warnedFull) { warnedFull = true; toast(t('saveFull'), 8000); }
    }
  }
  // Writes queue up one after another, so an older snapshot never lands after a newer one.
  function saveNow() {
    clearTimeout(saveTimer);
    if (!paused) chain = chain.then(job, job);
    return chain;
  }
  function autosave() { if (paused) return; clearTimeout(saveTimer); saveTimer = setTimeout(saveNow, 500); }
  addEventListener('pagehide', saveNow);
  document.addEventListener('visibilitychange', () => { if (document.hidden) saveNow(); });
  async function restore() {
    let data = null;
    const blobs = new Map();
    try {
      const d = await Promise.race([idb(), new Promise((_, no) => setTimeout(() => no(new Error('slow')), 3000))]);
      const q = d.transaction(['board', 'audio']);
      data = await asked(q.objectStore('board').get('board'));
      const keys = await asked(q.objectStore('audio').getAllKeys()), values = await asked(q.objectStore('audio').getAll());
      keys.forEach((k, i) => blobs.set(k, values[i]));
    } catch { return false; }
    if (!data || !Array.isArray(data.assets)) return false;
    ({ game, brief, platform, demo, stage } = data);
    if (Array.isArray(data.loud)) rule('loud').range = data.loud;
    assets.length = 0;
    for (const x of data.assets) {
      const { hasSource, ...a } = x;
      a.progress = 0;
      if (hasSource) {
        const blob = blobs.get(a.key);
        let source = null;
        try { source = blob && new Float32Array(await blob.arrayBuffer()); } catch { /* unreadable blob */ }
        if (source) { a.source = source; savedAudio.add(a.key); }
        else Object.assign(a, { versions: [], drafts: [], pick: -1, current: 0, status: 'pending' }); // the browser dropped the audio
      }
      assets.push(a);
    }
    return true;
  }
  // "Start again from samples" really starts again.
  async function forget() {
    paused = true; clearTimeout(saveTimer); await chain;
    try { const q = (await idb()).transaction(['board', 'audio'], 'readwrite'); q.objectStore('board').clear(); q.objectStore('audio').clear(); await done(q); } catch { /* nothing saved */ }
  }

  /* ---------- host page ---------- */
  const inHost = window.parent !== window;
  $('backBtn').onclick = () => { stopSound(); queue = null; saveNow(); if (inHost) parent.postMessage({ type: 'asset:back' }, '*'); };
  addEventListener('message', (e) => {
    if (e.data?.type === 'asset:measure') {
      const tiles = [...document.querySelectorAll('.tile')].slice(0, 40).map((t) => { const q = t.getBoundingClientRect(); return { x: q.left, y: q.top, w: q.width, h: q.height, c: resolved(color(byId(t.dataset.id).cat)) }; });
      e.source?.postMessage({ type: 'asset:tiles', tiles }, '*');
    }
    if (e.data?.type === 'asset:hide') { queue = null; stopSound(); saveNow(); }
  });
  function setLang(next) {
    if (!LANGS.includes(next)) return;
    lang = next; applyStatic();
    const typed = document.querySelector('.detailDock input')?.value;
    $('draftSlot').replaceChildren(draftPicker());
    if (openAsset) { renderDetail(); const input = document.querySelector('.detailDock input'); if (input && typed) input.value = typed; } else renderBoard();
    markPlaying();
    if (dlg.open && reopen) { const again = reopen; dlg.close(); again(); }
  }
  addEventListener('message', (e) => { if (e.data?.type === 'asset:lang') setLang(e.data.lang); });

  /* ---------- start ---------- */
  applyStatic();
  setIcon($('backBtn'), 'music'); setIcon($('send'), 'send'); setIcon($('playAll'), 'play'); setIcon($('exportBtn'), 'download'); setIcon($('menuBtn'), 'menu');
  document.querySelectorAll('[data-icon]').forEach((s) => setIcon(s, s.dataset.icon));
  $('importBtn').querySelector('.importIco').innerHTML = `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS.upload}</svg>`; $('importBtn').onclick = () => importDialog();
  $('exportBtn').onclick = exportDialog;
  addEventListener('resize', () => { if (openAsset) renderDetail(); else assets.filter((a) => a.versions.length).forEach(drawTile); });
  $('draftSlot').append(draftPicker());
  (async () => {
    await restore().catch(() => false);
    paused = false; renderBoard(); liveLoop();
    let seen = false;
    try { seen = !!localStorage.getItem('asset-tutorial-seen'); localStorage.setItem('asset-tutorial-seen', '1'); } catch { /* shows again next time */ }
    if (!seen) tutorial();
  })();
})();
