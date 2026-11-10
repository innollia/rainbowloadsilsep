// Game sound asset board: front-end shell on stand-in data. No server calls; requests are simulated with timers.
(() => {
  const $ = (id) => document.getElementById(id);
  const { GAME, BRIEF, CATEGORIES, ASSETS, PROFILES, RULES, LICENSES } = window.STUDIO_DATA;
  // Groups belong to the project: a spec or the user can add, rename and remove them. kind says how a sound in it behaves.
  const KIND_OF = { ui: 'sfx', combat: 'sfx', char: 'sfx', env: 'amb', bgm: 'music' };
  const KINDS = ['sfx', 'amb', 'music'];
  const HUES = ['#E8AE72', '#87B9E8', '#8CCDB2', '#C7A0E8', '#F3C978', '#F29BB2', '#9FD36B', '#7FD1D9', '#E89A7F', '#B7B3F2'];
  let cats = CATEGORIES.map((c) => ({ ...c, kind: KIND_OF[c.id] || 'sfx' }));
  const catOf = (id) => cats.find((c) => c.id === id);
  const kindOf = (id) => catOf(id)?.kind || KIND_OF[id] || 'sfx';
  const slugOf = (text) => String(text ?? '').replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
  function addCat(name, kind = 'sfx', id, parent) {
    const taken = new Set(cats.map((c) => c.id)), own = id || slugOf(tx(name)).join('_') || 'group', base = parent && !id ? `${parent}_${own}` : own;
    let cid = base, k = 2;
    while (taken.has(cid)) cid = `${base}_${k++}`;
    const c = { id: cid, name, kind: KINDS.includes(kind) ? kind : 'sfx', hue: HUES[cats.length % HUES.length] };
    if (parent && catOf(parent)) c.parent = parent;
    cats.push(c);
    return c;
  }
  // A group can sit inside another (music > forest); its export folder is the parent's folder plus its own name.
  const parentOf = (c) => (c?.parent && c.parent !== c.id ? catOf(c.parent) : null);
  function chainOf(c) { const out = []; for (let x = c; x && out.length < 12 && !out.includes(x); x = parentOf(x)) out.unshift(x); return out; }
  const depthOf = (c) => chainOf(c).length - 1;
  const under = (id, top) => chainOf(catOf(id)).some((x) => x.id === top);
  const folderOf = (c) => chainOf(c).map((x, i, all) => { const up = all[i - 1]; return up && x.id.startsWith(up.id + '_') ? x.id.slice(up.id.length + 1) : x.id; }).join('/');
  // Parents first, each followed by its own children.
  function catTree() {
    const out = [], walk = (pid) => cats.filter((c) => (parentOf(c)?.id || null) === pid && !out.includes(c)).forEach((c) => { out.push(c); walk(c.id); });
    walk(null);
    return out.concat(cats.filter((c) => !out.includes(c)));
  }
  // The importer guesses one of the starting group ids; land it on a group of the same kind this project has.
  const fitCat = (id) => catOf(id)?.id || cats.find((c) => c.kind === (KIND_OF[id] || 'sfx'))?.id || cats[0]?.id || addCat(id || 'sounds', KIND_OF[id]).id;
  let idRule = { pattern: '{kind}_{name}', sep: '_', prefix: { sfx: 'sfx', amb: 'amb', music: 'bgm' }, check: true };
  const escRe = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  function makeId(name, cat, taken) {
    taken ||= new Set(assets.map((a) => a.id));
    const sep = idRule.sep, pre = idRule.prefix[kindOf(cat)] || kindOf(cat), words = slugOf(name);
    if (words[0] === pre) words.shift();
    const catSlug = slugOf(cat).join(sep) || 'group', nameSlug = words.join(sep) || catSlug;
    const base = idRule.pattern.replace(/\{kind\}/g, pre).replace(/\{cat\}/g, catSlug).replace(/\{name\}/g, nameSlug).slice(0, 64) || nameSlug;
    let id = base, k = 2;
    while (taken.has(id)) id = `${base}${sep}${k++}`;
    taken.add(id);
    return id;
  }
  function idOk(id) {
    if (!idRule.check) return !!id;
    const sep = escRe(idRule.sep), word = '[a-z0-9]+', alt = (list) => `(?:${[...new Set(list.filter(Boolean))].map(escRe).join('|')})`;
    const src = idRule.pattern.split(/(\{kind\}|\{cat\}|\{name\})/).map((p) => (p === '{kind}' ? alt(Object.values(idRule.prefix))
      : p === '{cat}' ? alt(cats.map((c) => slugOf(c.id).join(idRule.sep))) : p === '{name}' ? `${word}(?:${sep}${word})*` : escRe(p))).join('');
    try { return new RegExp(`^${src}(?:${sep}\\d+)?$`).test(id); } catch { return true; }
  }
  const idRuleText = () => idRule.pattern.replace('{kind}', `(${Object.entries(idRule.prefix).map(([k, p]) => `${p}=${k}`).join(', ')})`).replace('{cat}', '<category id>').replace('{name}', `<lowercase english words joined by "${idRule.sep}">`);
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
    clip: '<path d="M20 11.5l-8 8a5 5 0 0 1-7-7l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7L9.7 17.2a1.7 1.7 0 0 1-2.4-2.4L15 7.2"/>',
    link: '<path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    prev: '<path d="M15 6l-6 6 6 6"/>',
    next: '<path d="m9 6 6 6-6 6"/>',
    check: '<path d="m5 13 4 4 10-11"/>',
    flag: '<path d="M6 21V4h12l-3 4 3 4H6"/>',
    upload: '<path d="M12 15V4M7 8l5-5 5 5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    folderPlus: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M12 11v6M9 14h6"/>',
    ref: '<path d="M20 11.5l-8 8a5 5 0 0 1-7-7l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7L9.7 17.2a1.7 1.7 0 0 1-2.4-2.4L15 7.2"/>',
    agent: '<path d="M12 3a7 7 0 0 1 7 7v3a7 7 0 0 1-14 0v-3a7 7 0 0 1 7-7z"/><path d="M9 11h.01M15 11h.01M9.5 15c1.5 1 3.5 1 5 0"/>',
    undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
    gear: '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
  };
  const setIcon = (el, name) => { el.innerHTML = `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`; };
  const iconButton = (name, label, fn, cls = 'iconBtn') => { const b = el('button', cls); setIcon(b, name); b.setAttribute('aria-label', label); b.title = label; b.onclick = fn; return b; };
  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  /* ---------- language ---------- */
  // The host page picks the language with ?lang= and can change it later with an asset:lang message.
  const LANGS = ['en', 'ko'];
  let lang = new URLSearchParams(location.search).get('lang');
  if (!LANGS.includes(lang)) lang = 'ko';
  const TEXT = {
    en: {
      docTitle: 'Game sound assets',
      deleteItem: 'Delete', trashed: (n) => `Moved ${n} to the trash`, trashHead: 'Trash', trashEmpty: 'The trash is empty.', restore: 'Put back', restoreAll: 'Put all back', deleteForever: 'Delete for good', emptyTrash: 'Empty trash',
      tagTrash: 'To trash', specAppliedTrash: (n, g) => `Spec applied: ${n} added, ${g} not in the spec moved to the trash`,
      addSound: 'Add', newSound: 'New sound', addCat: 'Add group', newCat: 'New group', catSettings: 'Group settings', kindLabel: 'Kind',
      kinds: { sfx: 'Effect', amb: 'Ambience', music: 'Music' }, catIdHelp: 'Lowercase English. Sounds in the group follow it.', deleteCat: 'Delete group',
      refs: 'References', refsN: (n) => `References ${n}`, refsProject: 'Project references', refsOf: (x) => `References · ${x}`,
      refsHelp: { project: 'Everything here reaches every sound in the project.', cat: 'Everything here reaches every sound in this group and the groups inside it.', asset: 'References for this sound only. Project and group references are listed below.' },
      refEmpty: 'No references yet.', refAdd: 'Add', refAddFile: 'Add files', refFileKinds: 'Sound, MIDI, ABC, MusicXML. Files can also be dropped here.', refAddLink: 'Add link', refAddNote: 'Add note',
      refNotePh: 'What it should sound like, what to avoid…', refTakePh: 'What to take from this reference', refRemove: 'Remove reference', refInherited: 'Also applies here',
      refFromProject: 'Project', refKinds: { audio: 'Sound', midi: 'MIDI', score: 'Score', text: 'Note', link: 'Link' },
      refBadType: 'not a sound, MIDI or score file', refTooBig: 'file too large', refBadLink: 'Enter a link starting with http:// or https://', refAdded: (n) => `Added ${n} reference${n > 1 ? 's' : ''}`,
      refGone: 'This file was not kept in the browser.', refCannotPlay: 'The browser cannot play this file.',
      agentPh: 'Ask in words (references, groups, names, how sounds should change)…', agentThinking: 'Thinking…', agentUndo: 'Undo', agentUndone: 'Undone',
      agentUpgraded: (m) => `The default model failed, so a stronger model (${m}) answered instead.`,
      agentDid: (n) => `${n} change${n === 1 ? '' : 's'} made`, agentFailed: (x) => `Could not answer: ${x}`,
      agentLocal: 'AI is not connected here, so I only understand links, notes ("note: …") and remakes of the picked sounds.', agentNoted: 'Saved it as a reference.', agentRemake: (n) => `Remaking ${n} sound${n === 1 ? '' : 's'}.`,
      parentCat: 'Inside', noParent: 'Top level', addSubCat: 'Add a group inside', foldersKind: 'A folder per kind (sfx, amb, music)', rootFolder: 'Audio folder',
      rulesHead: 'Use the file rules your agent knows', rulesHelp: 'If an AI agent worked on this game, copy this prompt to it and paste its answer below. It sets the id rule, folders and groups from the names the game already uses.',
      copyRules: 'Copy prompt', pasteRules: "Paste the agent's answer (JSON)", rulesId: 'ID rule', rulesFilesTag: 'Files', rulesFiles: (n) => `${n} files get their group and name`, applyRules: 'Apply the rules',
      rulesEmpty: 'The answer has no rules, groups or files this screen can use.', rulesApplied: 'Applied the file rules',
      jevSorting: (n) => `Sorting ${n} sounds into groups…`, jevSorted: (n, m) => `Sorted ${n} sounds (${m} moved)`, jevOff: 'Automatic sorting is not available here; the groups are guessed from the names.',
      rulesPrompt: (p) => `Some of this game's sounds were just brought into a sound tool. You worked on this game, so tell the tool how its audio files are named and stored. Reply with only this JSON:
${p.form}

- id_rule.pattern: how a file name (without extension) is built from {kind}, {cat} and {name}, e.g. "{kind}_{cat}_{name}". It must contain {name}.
- id_rule.sep: the character between words. id_rule.prefix: the word {kind} becomes for sfx, amb (looping ambience) and music.
- folders.root: the folder that holds the game's audio. folders.by: "category" (a folder per group), "kind" (sfx/amb/music folders) or "none".
- categories: the groups the game uses. id in lowercase english; kind is sfx, amb or music; parent is the id of the group it sits in (e.g. a region's music inside bgm), or leave it empty.
- files: each file below with its group id, and the id the game knows it by if that differs from the file name.

Groups the tool has now: ${p.cats}
Files:
${p.files}`,
      catNotEmpty: 'Move or delete the sounds in it first.', moveTo: 'Move to', deleteSound: 'Move to trash', deleteMany: (n) => `Move ${n} to trash`, confirmDelete: (n) => `Delete ${n}? This cannot be undone.`,
      idRule: 'ID rule', idHelp: 'Pattern can use {kind} (prefix of the kind), {cat} (group id) and {name} (the name in English words).', idPattern: 'Pattern', idSep: 'Separator', idPrefix: 'Prefix',
      idCheck: 'Flag ids that break the rule', idExample: (s, n) => `Example: ${s} · ${n} ids break it now`, idRenameAll: 'Rename every id by the rule', idRenamed: (n) => `Renamed ${n} ids`,
      specKeepsAudio: (n) => `${n} sounds already made stay as they are. Items not in the spec go to the trash and can be put back.`, specNewCats: (list) => `New groups: ${list}`, specIdWarn: (n, list) => `${n} ids don't follow the id rule; they are kept as given: ${list}`,
      exportFormat: 'Files', fmt: 'Format', rate: 'Sample rate', bits: 'Bit depth', quality: 'Quality', qualities: { high: 'High', mid: 'Medium', low: 'Small' },
      folders: 'Folders', foldersFlat: 'One folder', foldersCat: 'A folder per group', engine: 'Game engine', engineNone: 'None (files only)',
      bundleAudio: (p) => `Approved sounds, ${p}`, bundleGodot: 'Godot 4: a plugin and a scene per dynamic sound (godot/)', encoding: (i, n) => `Converting ${i} of ${n}…`, exportFailed: (m) => `Export failed: ${m}`,
      dynHead: 'Dynamic sounds', addDyn: 'Add dynamic sound', newDyn: 'New dynamic sound', dynType: 'Type', dynTypes: { ambience: 'Layered ambience', music: 'Adaptive music' }, dynLayers: (n) => `${n} layers`,
      params: 'Game values', addParam: 'Add value', param: 'Value', paramDefault: 'Starting value', intensity: 'Intensity', layersHead: 'Layers', addLayer: 'Add layer', always: 'Always on',
      roles: { bed: 'Loop', scatter: 'Now and then', stem: 'Music stem' }, onRange: 'Fades in', fadeFrom: 'Silent at', fadeTo: 'Full at', gap: 'Gap s', beatsPerBar: 'Beats per bar',
      dynNoSounds: 'Make or import some sounds first; layers are made of them.', dynHelp: 'Move a value to hear the layers change. The game sets the same values, for example set_param("intensity", 0.8) in Godot.',
      specField: { name: 'name', category: 'category', length: 'length', loop: 'loop', when: 'when', description: 'description' }, openAsset: 'Open', rename: 'Rename', unapprove: 'Cancel approval', menu: 'Menu', settings: 'Settings', language: 'Language', gameInfo: 'Game info', stagesLabel: 'Progress', total: (n) => `${n} in all`, approvedOf: (a, n) => `${a} of ${n} approved`, help: 'How to use', spec: 'Spec', export: 'Export',
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
      tabChat: 'Chat', tabTracks: 'Tracks', tabCode: 'Code', tabVersions: 'Versions',
      chatEmpty: (name) => `Tell me how to change ${name}.`, listen: 'Listen', current: 'Current', copyLicenses: 'Copy all licenses',
      askThis: 'What should change?', close: 'Close',
      licenseTitle: (g) => `${g} sound asset license notice`, use: 'Use', license: 'License', holder: 'Holder', copiedLicenses: 'Copied the license notice',
      example: { style: 'Warm wooden percussion and harp, combat not too heavy', assets: [
        { name: 'Click', when: 'Pressing a menu button', description: 'Light, wooden' },
        { name: 'Parry', when: 'The moment an enemy attack is blocked', description: 'Short metallic ring' },
        { name: 'Garden', when: 'Garden screen', description: 'Calm harp and strings' },
      ] },
      specPrompt: (p) => `Please write a game sound spec as JSON. This spec goes into a sound production tool that makes the assets.

First settle the hand-over points a sound designer would need when taking over: overall mood and reference games or music, how realistic or stylised, what must never be heard, what comes first in the mix (effects, music, voice). Take each from the design docs, the code and what the user has already told you in your conversations. Ask the user only about points none of these settle, one at a time, with a few short options and the one you recommend. If everything is settled, ask nothing. If you cannot ask the user, put the open points in questions.

Then, based on the design docs, the code, your conversations with the user and any answers, list every sound the game needs. Do not invent values that have no basis; leave them null, and put anything that still needs deciding in questions.

Fields
- game: game name
- platform: main device, one of ${p.platforms}
- style: overall sound direction of the game, one or two sentences, including the settled hand-over points
- references: notes and links every sound should follow, each { name, note, url }. One per settled hand-over point (name the point, note the decision), plus reference tracks or pages the user named (url)
- categories: sound groups for this game, each { id, name, kind } with kind sfx (effect), amb (ambience) or music. Start from ${p.cats} and add, rename or drop groups to fit the game
- assets: list of sounds
  - id: ${p.idRule}. If the code already uses a name, keep it
  - name: human-readable name
  - category: one of the categories ids
  - length: target length (seconds). Effects at most ${p.dur}s, ambience an unbroken loop of 8 or 16 seconds
  - loop: whether it repeats. Always true for ambience
  - when: the moment in the game when it plays
  - description: what it sounds like
- questions: things the user must decide

Do not reference tracks or samples with unclear licenses. Available materials: ${p.licenses}.

When that is done, reply only with JSON in the format below, no explanation.
${p.form}`,
      sendPrompt: 'Copy prompt', receiveSpec: 'Receive spec', pasteToAgent: 'Paste this into the AI agent working on your game.', prompt: 'Prompt',
      copyPrompt: 'Copy prompt', copiedPrompt: 'Copied the prompt', pasteSpec: 'Paste the spec the agent gave you.', insertExample: 'Insert example',
      notJson: (m) => `Not JSON: ${m}`, noAssets: 'There is no assets list.', badItems: (n, list) => `${n} items break the rules: ${list}`, noName: 'no name',
      planSummary: (a, c, k, g) => `Add ${a} · Change ${c} · Keep ${k} · To trash ${g}`, tagAdd: 'Add', tagChange: 'Change', tagRemove: 'Remove',
      moreRemoved: (n) => `${n} more removed`, startWithSpec: 'Start with this spec', addOnly: 'Add only, remove nothing',
      specApplied: (n) => `Spec applied. ${n} new assets`,
      exportIssues: (n, names) => `${n} assets with spec issues will also be exported: ${names}`, exportUnapproved: (n) => `${n} unapproved assets will be left out.`,
      gameFolder: 'Game folder', folderHelp: 'Link it and every approval is written straight into the game with these settings.', linkFolder: 'Link folder',
      folderLinked: (n) => `Linked to ${n}. Approving writes there.`, unlinkFolder: 'Unlink', folderFailed: (m) => `Could not write to the game folder: ${m}`, folderDenied: 'No permission to write to the folder.',
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
      noLicenseYet: 'license not recorded',
      originHead: 'Source', fillLeft: (n) => `${n} empty slot${n === 1 ? '' : 's'} to make.`, fillAll: 'Fill with AI', filling: (n) => `Making ${n}`,
      likeThis: 'Drafts in this feel', likeName: (n) => `${n} (like)`, likeMade: (n) => `Making ${n} in this feel`, promptHead: 'AI prompt',
      fromPrompt: 'Made from the prompt', importedNote: 'Brought in', fromBundle: 'From the bundle', importHint: 'Already have sounds or a sound list? Drop them here or use Import at the top.',
      fillPrompt: (p) => `Make the game sound "${p.name}" (${p.id}, ${p.cat}) for ${p.game}.\n${p.when ? `When it plays: ${p.when}\n` : ''}${p.description ? `What it sounds like: ${p.description}\n` : ''}Form: ${p.loop ? 'seamless loop' : 'one shot'}${p.length ? `, about ${p.length}s` : ''}.${p.style ? `\nGame sound direction: ${p.style}` : ''}${p.ref}`,
      refPrompt: (r) => `\n\nReference: make it in the feel of "${r.name}", the user's own sound (${r.file}). Measured from that file:\n- length ${r.seconds}s, ${r.loop ? 'loop' : 'one shot'}\n- peak ${r.peak} dB, loudness ${r.loud} LUFS\n- energy: low (<250 Hz) ${r.low}% · mid ${r.mid}% · high (>4 kHz) ${r.high}%, brightness about ${r.bright} Hz\n- leading silence ${r.lead} ms, trailing silence ${r.tail} ms\nStay close to its length, loudness and band balance. Do not copy it.`,
      importing: (i, n) => `Bringing in ${i} of ${n}`, skipped: (n, why) => `Skipped ${n}: ${why}`,
      whyType: (n) => `${n} not sound files`, whyBig: (n) => `${n} over 50 MB or past 500 MB in all`, whyBad: (n) => `${n} could not be read`, whyMany: (n) => `${n} past the first 2000`,
      pruned: (n) => `Storage was full, so ${n} old discarded drafts were cleared.`, saveFull: 'Storage is full and the board could not be saved. Export a bundle to keep it.',
      tutorialTitle: 'How to make game sounds',
      steps: [
        ['Bring in what you have', 'Already have sounds, a list of the sounds the game needs, or a bundle exported here? Import puts them on the board.'],
        ['Get a spec', 'From Spec in the top-right menu, copy the prompt, send it to the AI agent working on your game, and paste back the spec it returns.'],
        ['Check samples', 'Key sounds come first. Hover over a tile to listen, then approve.'],
        ['Make the rest', 'The rest are made at once in the style of the approved samples.'],
        ['Revise', 'Clicking a tile selects it and plays it. Pick several and write what to change. Raise the draft count to compare several options. Press and hold to open it large.'],
        ['Export', 'Approved sounds are bundled with the license notice. The AI finishes spec checks before it hands over a sound.'],
      ],
    },
    ko: {
      docTitle: '게임 소리 에셋',
      deleteItem: '지우기', trashed: (n) => `${n}개 다 휴지통에 처박아 뒀어~`, trashHead: '휴지통', trashEmpty: '휴지통이 텅 비었잖아, 바보야.', restore: '복원', restoreAll: '전체 복원', deleteForever: '영구 삭제', emptyTrash: '휴지통 비우기',
      tagTrash: '휴지통으로', specAppliedTrash: (n, g) => `명세 반영해 줬어. ${n}개 추가하고, 명세에 없는 ${g}개는 휴지통에 버렸으니까 알아 둬~`,
      addSound: '추가', newSound: '새 소리', addCat: '분류 추가', newCat: '새 분류', catSettings: '분류 설정', kindLabel: '종류',
      kinds: { sfx: '효과음', amb: '환경음', music: '음악' }, catIdHelp: '소문자 영문만 써. 분류 안 소리도 다 따라 바뀌니까.', deleteCat: '분류 지우기',
      refs: '레퍼런스', refsN: (n) => `레퍼런스 ${n}`, refsProject: '프로젝트 레퍼런스', refsOf: (x) => `레퍼런스 · ${x}`,
      refsHelp: { project: '여기에 넣으면 프로젝트의 모든 소리에 다 적용된다고~', cat: '여기에 넣으면 이 분류랑 안쪽 분류의 모든 소리에 다 적용돼.', asset: '이 소리만의 레퍼런스야. 프로젝트랑 분류 레퍼런스는 아래에 있잖아, 눈 크게 떠~' },
      refEmpty: '아직 레퍼런스가 하나도 없잖아, 허접~', refAdd: '추가', refAddFile: '파일 추가', refFileKinds: '소리, MIDI, ABC, MusicXML. 여기로 그냥 끌어다 놓기나 해~', refAddLink: '링크 추가', refAddNote: '메모 추가',
      refNotePh: '이런 느낌으로, 이건 피해서…', refTakePh: '이 레퍼런스에서 가져올 점', refRemove: '레퍼런스 삭제', refInherited: '상위에서 적용된 레퍼런스',
      refFromProject: '프로젝트', refKinds: { audio: '소리', midi: 'MIDI', score: '악보', text: '메모', link: '링크' },
      refBadType: '소리나 MIDI, 악보 파일이 아니잖아, 바보야!', refTooBig: '파일이 너무 크잖아, 무식하긴~', refBadLink: 'http://나 https://로 시작하는 링크를 넣으란 말이야, 허접~', refAdded: (n) => `레퍼런스 ${n}개 넣어 줬어~`,
      refGone: '이 파일은 브라우저에 남아 있지도 않잖아.', refCannotPlay: '브라우저가 이 파일을 재생 못 한다잖아, 허접~',
      agentPh: 'AI에게 요청 (레퍼런스, 분류, 이름, 소리 수정)…', agentThinking: '생각하는 중…', agentUndo: '되돌리기', agentUndone: '되돌렸어요',
      agentUpgraded: (m) => `원래 모델이 허접하게 실패해서 훨씬 더 좋은 상위 모델(${m})이 대신 나섰어♡ 고마운 줄 알아~`,
      agentDid: (n) => `${n}가지나 바꿔 줬어, 감사하라고~`, agentFailed: (x) => `답하지 못했어요: ${x}`,
      agentLocal: '여기선 AI 연결이 안 돼서 링크, 메모("메모: …"), 고른 소리 다시 만들기밖에 못 알아듣거든?', agentNoted: '레퍼런스로 저장해 뒀어~', agentRemake: (n) => `소리 ${n}개 다시 만들어 줄게.`,
      parentCat: '상위 분류', noParent: '없음(최상위)', addSubCat: '하위 분류 추가', foldersKind: '종류별 폴더(sfx, amb, music)', rootFolder: '소리 폴더',
      rulesHead: '에이전트가 아는 파일 규칙 쓰기', rulesHelp: '이 게임 작업한 AI 에이전트 있으면 이 프롬프트 보내고 답을 아래에 붙여 넣어 봐. 게임이 이미 쓰는 이름에 맞춰서 ID 규칙, 폴더, 분류를 바꿔 줄 테니까.',
      copyRules: '프롬프트 복사', pasteRules: '에이전트의 답(JSON)이나 여기에 붙여 넣어 봐~', rulesId: 'ID 규칙', rulesFilesTag: '파일', rulesFiles: (n) => `파일 ${n}개의 분류랑 이름을 맞춰 줄게.`, applyRules: '규칙 적용',
      rulesEmpty: '답에 이 화면이 쓸 규칙이나 분류, 파일이 하나도 없잖아, 바보야.', rulesApplied: '파일 규칙 적용해 줬어~',
      jevSorting: (n) => `소리 ${n}개를 분류하는 중…`, jevSorted: (n, m) => `소리 ${n}개를 분류했어요(${m}개 옮김)`, jevOff: '여기선 자동 분류를 못 써서 그냥 이름으로 대충 짐작해 줬어~',
      rulesPrompt: (p) => `이 게임의 소리 일부를 방금 소리 도구로 가져왔습니다. 이 게임을 작업했으니 소리 파일의 이름과 저장 규칙을 도구에 알려 주세요. 아래 JSON만 답해 주세요.
${p.form}

- id_rule.pattern: 확장자를 뺀 파일 이름이 {kind}, {cat}, {name}으로 어떻게 만들어지는지. 예: "{kind}_{cat}_{name}". {name}이 꼭 들어가야 합니다.
- id_rule.sep: 단어 사이 문자. id_rule.prefix: sfx, amb(반복 환경음), music일 때 {kind} 자리에 들어가는 말.
- folders.root: 게임 소리를 담는 폴더. folders.by: "category"(분류마다 폴더), "kind"(sfx/amb/music 폴더), "none"(한 폴더).
- categories: 게임이 쓰는 분류. id는 영어 소문자, kind는 sfx, amb, music 중 하나, parent는 이 분류가 들어가는 상위 분류 id(예: 지역별 음악은 bgm 안), 없으면 비웁니다.
- files: 아래 파일마다 분류 id, 그리고 게임 안에서 부르는 id가 파일 이름과 다르면 그 id.

도구에 지금 있는 분류: ${p.cats}
파일:
${p.files}`,
      catNotEmpty: '안에 있는 소리부터 옮기든가 지우든가 해, 바보야.', moveTo: '분류 옮기기', deleteSound: '휴지통으로', deleteMany: (n) => `${n}개 휴지통으로`, confirmDelete: (n) => `${n}개 진짜 지울 거야? 되돌리지도 못하는데~?`,
      idRule: 'ID 규칙', idHelp: '형식엔 {kind}(종류 접두사), {cat}(분류 ID), {name}(영문 이름)을 쓸 수 있으니까 잘 외워 둬.', idPattern: '형식', idSep: '구분 기호', idPrefix: '접두사',
      idCheck: '규칙에 안 맞는 ID 표시', idExample: (s, n) => `예: ${s} · 지금 규칙에 안 맞는 ID ${n}개`, idRenameAll: '모든 ID를 규칙에 맞게 변경', idRenamed: (n) => `ID ${n}개 바꿔 줬어~`,
      specKeepsAudio: (n) => `이미 만든 소리 ${n}개는 그대로 둘게. 명세에 없는 건 휴지통으로 가지만 복원할 순 있어.`, specNewCats: (list) => `새 분류: ${list}`, specIdWarn: (n, list) => `ID ${n}개가 ID 규칙과 달라요. 받은 그대로 씁니다: ${list}`,
      exportFormat: '파일', fmt: '형식', rate: '샘플레이트', bits: '비트', quality: '품질', qualities: { high: '높음', mid: '보통', low: '낮음' },
      folders: '폴더', foldersFlat: '한 폴더', foldersCat: '분류별 폴더', engine: '게임 엔진', engineNone: '없음(파일만)',
      bundleAudio: (p) => `승인한 소리, ${p}`, bundleGodot: 'Godot 4: 플러그인과 동적 소리마다 장면 하나(godot/)', encoding: (i, n) => `변환 중 ${i}/${n}…`, exportFailed: (m) => `내보내기 실패: ${m}`,
      dynHead: '동적 소리', addDyn: '동적 소리 추가', newDyn: '새 동적 소리', dynType: '종류', dynTypes: { ambience: '레이어 환경음', music: '적응형 음악' }, dynLayers: (n) => `레이어 ${n}개`,
      params: '파라미터', addParam: '파라미터 추가', param: '파라미터', paramDefault: '기본값', intensity: '강도', layersHead: '레이어', addLayer: '레이어 추가', always: '항상',
      roles: { bed: '루프', scatter: '랜덤 재생', stem: '스템' }, onRange: '페이드 인 구간', fadeFrom: '최소 볼륨 지점', fadeTo: '최대 볼륨 지점', gap: '간격(초)', beatsPerBar: '마디당 박 수',
      dynNoSounds: '소리부터 만들거나 가져오라고. 레이어는 그 소리로 만드는 거잖아, 허접~', dynHelp: '파라미터를 움직여 봐, 레이어 바뀌는 게 들리지? 게임에서도 같은 파라미터를 넣는 거야. 예: Godot에서 set_param("intensity", 0.8).',
      specField: { name: '이름', category: '분류', length: '길이', loop: '반복', when: '재생 시점', description: '설명' }, openAsset: '열기', rename: '이름 바꾸기', unapprove: '승인 취소', menu: '메뉴', settings: '설정', language: '언어', gameInfo: '게임 정보', stagesLabel: '진행 상황', total: (n) => `전체 ${n}`, approvedOf: (a, n) => `${n}개 중 ${a}개 승인`, help: '사용법', spec: '명세', export: '내보내기',
      backToMusic: '음악 작업실로', category: '분류', board: '에셋 보드', playAll: '전체 재생', stopAll: '전체 재생 정지', hoverPlay: '마우스 오버 시 재생',
      acceptAll: '전체 채택', rejectAll: '전체 버림', selectAll: '전체 선택', deselect: '선택 해제', approve: '승인', approved: '승인됨', clear: '해제',
      ask: '수정 요청', send: '보내기',
      status: { pending: '대기', draft: '확인 필요', approved: '승인', flagged: '수정 표시', working: '수정 중', review: '검토 대기' },
      sec: (s) => `${s}초`,
      previous: '이전', newVersion: '새 버전', keep: '채택', drop: '버림',
      approveAll: '전체 승인', leftToCheck: (n) => `확인할 에셋이 아직 ${n}개나 남았잖아, 빨리 해~`,
      samplesDone: (n, rest) => `샘플 ${n}개 다 승인했네? 이 스타일로 나머지 ${rest}개도 만들어 줄게~`,
      samplesProgress: (n, done, rest) => `샘플 ${n}개 중에 겨우 ${done}개 승인했네. 들어 보고 다 승인하면 나머지 ${rest}개도 같은 스타일로 만들어 줄게~`,
      makeRest: '나머지 만들기', all: '전체', statusHead: '상태',
      counts: (n, ok) => `전체 ${n} · 승인 ${ok}`, reviewCount: (n) => `검토 ${n}개`, selected: (n) => `${n}개 선택`,
      askSelected: (n) => `선택한 ${n}개에 보낼 요청`, askOne: (name) => `${name}에 보낼 요청`, askNone: '에셋을 골라서 요청을 보내 봐, 허접~',
      drafts: '시안', draftCount: (i) => `${i}개`, draftCountLabel: '시안 개수', draftNote: (text, k) => `${text} · 시안 ${k}`,
      madeDrafts: (n) => `시안 ${n}개 만들어 줬으니까 들어 보고 하나 골라 봐~`, madeOne: '새 버전 만들어 줬어~ 이전 거랑 비교나 해 봐♡',
      expanding: (n) => `샘플 스타일로 ${n}개 만들어 줄게~`, firstVersion: '첫 버전', fromSpec: '명세에서 생성',
      play: '재생', stop: '정지', toBoard: '보드로', prevAsset: '이전 에셋', nextAsset: '다음 에셋',
      peak: (v) => `최대 ${v} dB`, loud: (v) => `음량 ${v} LUFS`, loop: '루프', oneShot: '한 번 재생', spectrum: '스펙트럼',
      tracks: (n) => `트랙 ${n}개`,
      stemOn: (s) => `${s} 켜기`, stemOff: (s) => `${s} 끄기`, stemSolo: (s) => `${s} 혼자 듣기`, stemGain: (s) => `${s} 음량`,
      stems: { drums: '드럼', bass: '베이스', chords: '화음', melody: '멜로디', wind: '바람', gust: '돌풍', rain_streaks: '빗줄기', rain_floor: '빗소리 베이스', raindrops: '빗방울', fire_bed: '불 베이스', crackle: '탁탁 튀는 소리', cave_echo: '동굴 울림', drips: '물방울', noise_layer: '노이즈 레이어', main: '메인' },
      toneLayer: (i) => `톤 레이어 ${i}`,
      tabChat: '대화', tabTracks: '트랙', tabCode: '코드', tabVersions: '버전',
      chatEmpty: (name) => `${name}을(를) 어떻게 바꿀지 말해 봐~`, listen: '듣기', current: '현재', copyLicenses: '저작권 전체 복사',
      askThis: '이거 어떻게 고쳐줄까? 허접~', close: '닫기',
      licenseTitle: (g) => `${g} 소리 에셋 저작권 고지`, use: '용도', license: '라이선스', holder: '저작권자', copiedLicenses: '저작권 고지 복사해 뒀어~',
      example: { style: '따뜻한 나무 타악기와 하프 중심, 전투도 무겁지 않게', assets: [
        { name: '클릭', when: '메뉴 버튼을 누를 때', description: '가볍고 나무 느낌' },
        { name: '패링', when: '적 공격을 막는 순간', description: '금속 울림이 짧게' },
        { name: '정원', when: '정원 화면', description: '잔잔한 하프와 현악' },
      ] },
      specPrompt: (p) => `게임 소리 명세서를 JSON으로 작성해 주세요. 이 명세서를 소리 제작 도구에 넣어 에셋을 만듭니다.

먼저 사운드 디자이너가 작업을 넘겨받을 때 알아야 할 것을 정리해 주세요: 전체 분위기와 참고할 게임이나 음악, 얼마나 사실적이거나 과장할지, 절대 들리면 안 되는 소리, 믹스에서 무엇이 먼저인지(효과음, 음악, 목소리). 각각 기획서, 코드, 사용자와 이미 나눈 대화에서 찾아 채우세요. 그 어디에서도 정해지지 않은 것만 사용자에게 한 번에 하나씩, 짧은 선택지 몇 개와 추천 답을 붙여 물어보세요. 다 정해져 있으면 묻지 마세요. 사용자에게 물을 수 없으면 정해지지 않은 것을 questions에 적어 주세요.

그다음 기획서, 코드, 사용자와의 대화와 답을 근거로 게임에 필요한 소리를 빠짐없이 적어 주세요. 근거가 없는 값은 지어내지 말고 null로 두고, 아직 정해야 할 것은 questions에 적어 주세요.

항목
- game: 게임 이름
- platform: ${p.platforms} 중 주요 기기
- style: 게임 전체의 소리 방향, 한두 문장. 정리한 인수인계 내용을 담아서
- references: 모든 소리가 따를 메모와 링크, 각각 { name, note, url }. 정리한 인수인계 항목마다 하나(name은 항목, note는 정해진 내용), 사용자가 말한 참고곡이나 페이지는 url로
- categories: 이 게임의 소리 분류. 각각 { id, name, kind }, kind는 sfx(효과음), amb(환경음), music(음악). ${p.cats}에서 시작해 게임에 맞게 더하고 바꾸고 빼세요
- assets: 소리 목록
  - id: ${p.idRule}. 코드에 이미 쓰는 이름이 있으면 그대로
  - name: 사람이 읽을 이름
  - category: categories의 id 중 하나
  - length: 목표 길이(초). 효과음은 ${p.dur}초 이하, 환경음은 끊기지 않는 반복 구간 8초나 16초
  - loop: 반복 재생 여부. 환경음은 언제나 true
  - when: 게임의 어떤 순간에 나는 소리인지
  - description: 어떤 소리인지
- questions: 사용자가 정해야 할 것

저작권이 불분명한 곡이나 샘플은 참조하지 마세요. 쓸 수 있는 재료는 ${p.licenses}입니다.

정리가 끝나면 설명 없이 아래 형식의 JSON만 답해 주세요.
${p.form}`,
      sendPrompt: '프롬프트 복사', receiveSpec: '명세 받기', pasteToAgent: '게임 작업하는 AI 에이전트한테 그대로 붙여 넣어~', prompt: '프롬프트',
      copyPrompt: '프롬프트 복사', copiedPrompt: '프롬프트 복사해 뒀어~', pasteSpec: '에이전트가 준 명세 여기다 붙여 넣어~', insertExample: '예시 넣기',
      notJson: (m) => `JSON이 아니에요: ${m}`, noAssets: 'assets 목록도 없잖아~?', badItems: (n, list) => `규칙에 맞지 않는 항목 ${n}개: ${list}`, noName: '이름 없음',
      planSummary: (a, c, k, g) => `추가 ${a} · 변경 ${c} · 유지 ${k} · 휴지통 ${g}`, tagAdd: '추가', tagChange: '변경', tagRemove: '삭제',
      moreRemoved: (n) => `외 ${n}개 삭제`, startWithSpec: '이 명세로 작업 시작', addOnly: '삭제 없이 추가만',
      specApplied: (n) => `명세를 적용했어요. 새 에셋 ${n}개`,
      exportIssues: (n, names) => `규격 문제가 남은 에셋 ${n}개도 함께 나갑니다: ${names}`, exportUnapproved: (n) => `아직 승인 안 한 에셋 ${n}개는 빼 버릴 거야~`,
      gameFolder: '게임 폴더', folderHelp: '연결해 두면 승인할 때마다 이 설정대로 게임 폴더에 바로 써 줄게~', linkFolder: '폴더 연결',
      folderLinked: (n) => `${n} 폴더에 연결됨. 승인하면 바로 저장돼~`, unlinkFolder: '연결 끊기', folderFailed: (m) => `게임 폴더에 못 썼어: ${m}`, folderDenied: '폴더에 쓸 권한이 없어~',
      inBundle: '묶음에 들어가는 것', bundleItems: ['승인한 소리 파일 audio/*.wav', '명세 game-audio.spec.json (가져오기로 다시 읽음)', 'CREDITS.md와 lint-report.json'], licenses: '저작권',
      exportBundle: '묶음 내보내기', exported: (n) => `소리 ${n}개 묶어 줬어~`, restart: '샘플 단계부터 다시',
      importShort: '가져오기', importTitle: '이미 만든 작업 가져오기', importIntro: '만들어 둔 소리나 게임에 필요한 소리 목록 있으면 거기서 시작해 봐~',
      dropHere: '소리 파일이나 폴더, 내보낸 묶음을 여기다 놔 봐~',
      importFilesHead: '소리 파일', importFilesHelp: 'wav, mp3, ogg 여러 개를 한 번에! 폴더째 이 화면 아무 데나 끌어다 놔도 돼~ 이름이랑 분류는 파일·폴더 이름으로 대충 짐작하니까 여기서 바로 고치라고♡',
      pickFiles: '파일 고르기', pickFolder: '폴더 고르기',
      importBundleHead: '내보낸 묶음', importBundleHelp: '내보내기로 받은 .zip이나 그 압축 푼 폴더야. 하던 데서 이어서 해 줄게~', pickBundle: '묶음 열기',
      importListHead: '게임에 필요한 소리 목록', importListHelp: '한 줄에 하나, 아니면 머리줄(id, name, category, when, description) 있는 CSV야. 빈 칸으로 올라가고 AI가 채워 줄 거야~',
      listPlaceholder: '버튼 클릭\n칼 타격, 전투, 짧고 건조하게\nbgm_title\n숲, 환경', listCount: (n) => `소리 ${n}개`, addSlots: (n) => `빈 칸 ${n}개 올리기`,
      justImported: '방금 가져온 소리', imported: '직접 가져옴', importedN: (n) => `소리 ${n}개 가져왔어~`, bundleLoaded: (g, n) => `${g} 묶음을 열었어요. 에셋 ${n}개`,
      slotsAdded: (n) => `빈 칸 ${n}개 올려 뒀어~`, nothingToImport: '소리 파일도 묶음도 목록도 못 찾겠는데~?',
      nameLabel: '이름', guessed: '대충 짐작한 분류니까 똑바로 확인해~', licenseLater: '라이선스 (나중에 적어도 돼요)', holderLater: '저작권자', licenseOf: (n) => `${n} 라이선스`,
      noLicenseYet: '라이선스 기록 없음',
      originHead: '출처', fillLeft: (n) => `만들 빈 칸 ${n}개야~`, fillAll: 'AI로 채우기', filling: (n) => `${n}개를 만드는 중`,
      likeThis: '이 느낌으로 시안', likeName: (n) => `${n} 느낌`, likeMade: (n) => `이 느낌으로 ${n}개 만들어 줄게~`, promptHead: 'AI 프롬프트',
      fromPrompt: '프롬프트로 생성', importedNote: '직접 가져옴', fromBundle: '묶음에서 가져옴', importHint: '이미 만든 소리나 소리 목록 있어? 여기다 끌어다 놓든가 위쪽 가져오기를 눌러 봐~',
      fillPrompt: (p) => `${p.game}에 쓸 게임 소리 "${p.name}"(${p.id}, ${p.cat})를 만들어 주세요.\n${p.when ? `나는 때: ${p.when}\n` : ''}${p.description ? `어떤 소리: ${p.description}\n` : ''}형태: ${p.loop ? '끊김 없는 반복' : '한 번 재생'}${p.length ? `, 약 ${p.length}초` : ''}.${p.style ? `\n게임 소리 방향: ${p.style}` : ''}${p.ref}`,
      refPrompt: (r) => `\n\n기준 소리: 사용자가 가져온 "${r.name}"(${r.file})의 느낌으로 만들어 주세요. 그 파일을 잰 값:\n- 길이 ${r.seconds}초, ${r.loop ? '반복' : '한 번 재생'}\n- 최대 ${r.peak} dB, 음량 ${r.loud} LUFS\n- 에너지: 저역(250 Hz 아래) ${r.low}% · 중역 ${r.mid}% · 고역(4 kHz 위) ${r.high}%, 밝기 약 ${r.bright} Hz\n- 앞 무음 ${r.lead} ms, 뒤 무음 ${r.tail} ms\n길이, 음량, 대역 균형을 비슷하게 맞추되 그대로 베끼지는 마세요.`,
      importing: (i, n) => `가져오는 중 ${i}/${n}`, skipped: (n, why) => `${n}개 건너뜀: ${why}`,
      whyType: (n) => `소리 파일 아님 ${n}`, whyBig: (n) => `50MB 넘음·합계 500MB 넘음 ${n}`, whyBad: (n) => `읽지 못함 ${n}`, whyMany: (n) => `2000개 넘음 ${n}`,
      pruned: (n) => `저장 공간이 모자라서 옛날에 버린 시안 ${n}개는 치워 버렸어~`, saveFull: '저장 공간이 꽉 차서 자동 저장 못 했거든? 내보내기로 묶음부터 받아 둬~',
      tutorialTitle: '게임 소리 만드는 법',
      steps: [
        ['가진 것 가져오기', '만들어 둔 소리나 게임에 필요한 소리 목록, 여기서 내보낸 묶음 있으면 가져오기로 보드에 올려 봐~'],
        ['명세 받기', '오른쪽 위 메뉴의 명세에서 프롬프트 복사해서 게임 작업하는 AI 에이전트한테 보내고, 돌아온 명세를 붙여 넣어 봐~'],
        ['샘플 확인', '대표 소리가 먼저 나와~ 타일에 마우스 올려서 들어 보고 승인해♡'],
        ['나머지 만들기', '승인한 샘플 스타일로 나머지도 한 번에 만들어 줄게~'],
        ['고치기', '타일 누르면 선택되고 소리가 나~ 여러 개 고르고 바꿀 내용 적어 봐. 시안 개수 늘리면 여러 안 비교해서 고를 수 있고, 길게 누르면 크게 열려♡'],
        ['내보내기', '승인한 소리를 저작권 고지랑 같이 묶어 줄게~ 규격 검사는 AI가 소리 내놓기 전에 다 끝내 두거든.'],
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
  const color = (cat) => catOf(cat)?.hue || 'var(--text3)';
  const secNum = (s, like = s) => s.toFixed(like < 1 ? 2 : like < 10 ? 1 : 0); // a position reads to the length's precision
  const seconds = (s) => t('sec', secNum(s));
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
  Object.assign(rule('name'), { read: (m, a) => idOk(a.id), hint: { en: 'Follows the id rule (Settings)', ko: 'ID 규칙을 따름(설정)' } });
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
      const old = a.id; a.id = makeId(nm(a), a.cat, new Set(assets.filter((x) => x !== a).map((x) => x.id)));
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
  const approve = (a) => { a.status = 'approved'; toFolder([a]); };
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
    renderPlayButton();
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
    const state = el('i', 'state'); state.title = statusText(a.status);
    if (a.status === 'approved') setIcon(state, 'check');
    meta.append(name, sub); t.append(meta, state);
    t.addEventListener('pointerenter', () => hoverStart(a));
    t.addEventListener('pointerleave', hoverEnd);
    t.addEventListener('click', (e) => clickTile(a, e));
    t.addEventListener('pointerdown', (e) => hold(a, t, e));
    t.addEventListener('contextmenu', (e) => { e.preventDefault(); tileMenu(a, e.clientX, e.clientY); });
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
    syncRefs();
    const box = $('board'), top = box.scrollTop; box.textContent = '';
    box.append(...banner());
    box.append(dynSection());
    for (const c of catTree()) {
      const list = visible().filter((a) => a.cat === c.id);
      if (!list.length && (filter.status || filter.imported || (filter.cat && !under(c.id, filter.cat)))) continue;
      const group = el('div', depthOf(c) ? 'group sub' : 'group'), h = el('h2'), dot = el('i');
      group.style.setProperty('--c', c.hue); group.style.setProperty('--depth', depthOf(c)); group.dataset.cat = c.id;
      h.append(dot);
      if (parentOf(c)) h.append(el('small', 'catPath', chainOf(c).slice(0, -1).map((x) => tx(x.name)).join(' › ') + ' ›'));
      const pickable = ready(list), title = el('b', 'catName', tx(c.name));
      // Clicking the group name selects every sound in it (again: deselects); Ctrl+A selects the whole board.
      if (pickable.length) { title.title = pickable.every((x) => selected.has(x.id)) ? t('deselect') : t('selectAll'); title.onclick = () => { const off = pickable.every((x) => selected.has(x.id)); pickable.forEach((x) => (off ? selected.delete(x.id) : selected.add(x.id))); renderBoard(); }; }
      h.append(title, el('span', '', String(list.length)));
      const add = iconButton('plus', t('addSound'), () => addSound(c.id), 'ghost iconBtn addSound');
      const more = iconButton('gear', t('catSettings'), () => catDialog(c), 'ghost iconBtn catGear');
      const refB = iconButton('ref', t('refsOf', tx(c.name)), () => refDialog({ type: 'cat', c }), 'ghost iconBtn catRef');
      if (refCount({ type: 'cat', c })) { refB.append(el('span', 'refN', String(refCount({ type: 'cat', c })))); refB.classList.add('has'); }
      h.append(refB);
      h.append(add, more);
      h.addEventListener('contextmenu', (e) => { e.preventDefault(); e.stopPropagation(); catMenu(c, e.clientX, e.clientY); });
      const grid = el('div', 'grid');
      grid.append(...list.map(makeTile));
      group.append(h, grid); box.append(group);
    }
    if (!filter.status && !filter.imported) box.append(iconButton('folderPlus', t('addCat'), newCat, 'ghost iconBtn addCat'));
    box.scrollTop = top;
    assets.filter((a) => a.versions.length).forEach(drawTile);
    renderSide(); renderHeader(); syncDock();
  }
  function importHint() {
    const box = el('div', 'banner importHint'), text = el('span', '', t('importHint'));
    text.style.flex = '1'; box.append(text);
    return box;
  }
  function banner() {
    const unchecked = assets.filter((a) => a.status === 'draft');
    const box = el('div', 'banner'); box.style.cssText = 'display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:6px';
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
  const STATUS_HUE = { approved: 'var(--ok)', draft: 'var(--warn)', review: 'var(--work)', working: 'var(--work)', flagged: 'var(--err)', pending: 'var(--disabled)' };
  function renderSide() {
    const side = $('side'); side.textContent = '';
    // Below 900px the list narrows to a rail of dots and counts; the name stays in the tooltip and label.
    const item = (label, count, active, fn, hue, mark) => {
      const b = el('button'); b.setAttribute('aria-pressed', String(active)); b.onclick = fn; b.title = label; b.setAttribute('aria-label', `${label} ${count}`);
      if (hue) { const d = el('i', mark ? 'dot railOnly' : 'dot'); d.style.setProperty('--c', hue); b.append(d); }
      else if (mark) { const d = el('i', 'railOnly railIco'); setIcon(d, mark); b.append(d); }
      b.append(el('span', 'name', label), el('span', 'n', String(count)));
      return b;
    };
    side.append(el('h2', '', t('category')), item(t('all'), assets.length, !filter.cat, () => { filter.cat = null; renderBoard(); }, 'var(--text)', true));
    for (const c of catTree()) { const b = item(tx(c.name), assets.filter((a) => under(a.cat, c.id)).length, filter.cat === c.id, () => { filter.cat = filter.cat === c.id ? null : c.id; renderBoard(); }, c.hue); b.style.paddingLeft = `${12 + depthOf(c) * 14}px`; b.oncontextmenu = (e) => { e.preventDefault(); e.stopPropagation(); catMenu(c, e.clientX, e.clientY); }; side.append(b); }
    side.append(iconButton('folderPlus', t('addCat'), newCat, 'iconBtn addCat'));
    side.append(el('h2', '', t('statusHead')));
    for (const [id, label] of Object.entries(t('status'))) {
      const n = assets.filter((a) => a.status === id).length;
      if (n) side.append(item(label, n, filter.status === id, () => { filter.status = filter.status === id ? null : id; renderBoard(); }, STATUS_HUE[id], true));
    }
    if (trash.length) { side.append(el('h2', '', t('trashHead'))); side.append(item(t('trashHead'), trash.length, false, trashDialog, null, 'trash')); }
    const mine = assets.filter((a) => a.imported).length;
    if (mine) side.append(el('h2', '', t('originHead')), item(t('imported'), mine, filter.imported, () => { filter.imported = !filter.imported; renderBoard(); }, null, 'upload'));
  }
  function renderHeader() {
    $('gameTitle').textContent = tx(game);
    const summary = renderProgress(), total = assets.length;
    const count = $('progressCount'), approved = assets.filter((a) => a.status === 'approved').length;
    count.innerHTML = `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS.check}</svg>`;
    count.append(`${approved}/${total}`); count.title = summary; count.setAttribute('aria-label', t('approvedOf', approved, total));
    const waiting = assets.filter((a) => a.status === 'review').length;
    $('review').hidden = !waiting || !!openAsset; $('reviewText').textContent = t('reviewCount', waiting);
    autosave();
  }
  // One pad per sound, like the music screen's wait sequencer: four rows filled column by column from the left,
  // approved first, then waiting for a check, being made, flagged; what is not made yet stays an empty pad.
  // Beside it, approved out of all. A pad filters the board by its status.
  const PAD_ORDER = ['approved', 'draft', 'review', 'working', 'flagged', 'pending'];
  function renderProgress() {
    const box = $('progress'), pads = box.querySelector('.pads'), total = assets.length;
    const list = PAD_ORDER.flatMap((s) => assets.filter((a) => a.status === s));
    // Four rows like the sequencer; more rows only when the pads would get thinner than 4px.
    const W = parseFloat(getComputedStyle(box).maxWidth) || 160, H = 38, GX = 3, GY = 2;
    let rows = 4, cols = 1, cw = 10;
    for (; rows <= 8; rows++) { cols = Math.max(1, Math.ceil(total / rows)); cw = Math.min(10, (W - (cols - 1) * GX) / cols); if (cw >= 4) break; }
    rows = Math.min(rows, 8);
    const ch = Math.min(8, (H - (rows - 1) * GY) / rows);
    pads.style.gridTemplateRows = `repeat(${rows}, ${ch}px)`; pads.style.gridAutoColumns = `${Math.max(1.5, cw)}px`;
    // Pads are reused so a sound being made keeps pulsing through re-renders.
    while (pads.children.length > list.length) pads.lastChild.remove();
    while (pads.children.length < list.length) pads.append(el('i'));
    list.forEach((a, i) => { const p = pads.children[i]; p.className = `s-${a.status}`; p.dataset.s = a.status; p.title = `${nm(a)} · ${statusText(a.status)}`; });
    pads.classList.toggle('filtering', !!filter.status); pads.dataset.f = filter.status || '';
    const all = PAD_ORDER.map((s) => [s, list.filter((a) => a.status === s).length]).filter(([, n]) => n);
    const summary = `${all.map(([s, n]) => `${statusText(s)} ${n}`).join(' · ')} (${t('total', total)})`;
    box.setAttribute('aria-label', `${t('stagesLabel')}: ${summary}`);
    // The whole 44px row takes the click: the pad under the pointer, or the column it is in.
    box.onclick = (e) => {
      const hit = e.target.closest('#progress i') || [...pads.children].find((p) => { const r = p.getBoundingClientRect(); return e.clientX >= r.left - GX / 2 && e.clientX <= r.right + GX / 2; });
      if (!hit) return;
      filter.status = filter.status === hit.dataset.s ? null : hit.dataset.s; renderBoard();
    };
    return summary;
  }
  function syncDock() {
    const count = selected.size, target = focused && byId(focused);
    $('selCount').hidden = !count; $('selCount').textContent = t('selected', count);
    $('selAll').hidden = $('selApprove').hidden = $('selClear').hidden = !count;
    document.body.classList.toggle('selecting', !!count);
    $('ask').placeholder = count ? t('askSelected', count) : target?.versions.length ? t('askOne', nm(target)) : t('agentPh');
    $('send').disabled = agentBusy;
  }

  /* ---------- pointer ---------- */
  let hoverTimer = 0, lassoing = false;
  function hoverStart(a) {
    if (lassoing || !hoverOn || !a.versions.length || queue) return;
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
    const x0 = e.clientX, y0 = e.clientY, ring = holdRing(x0, y0, color(a.cat));
    const end = () => { clearTimeout(timer); t.classList.remove('pressing'); ring.remove(); removeEventListener('pointerup', end); removeEventListener('pointercancel', end); removeEventListener('pointermove', move); };
    const move = (ev) => { if (Math.hypot(ev.clientX - x0, ev.clientY - y0) > 8) end(); else ring.style.translate = `${ev.clientX}px ${ev.clientY}px`; };
    const timer = setTimeout(() => { end(); held = true; openDetail(a); }, HOLD_MS);
    t.style.setProperty('--hold', HOLD_MS + 'ms'); t.classList.add('pressing');
    addEventListener('pointerup', end); addEventListener('pointercancel', end); addEventListener('pointermove', move);
  }
  function holdRing(x, y, hue) {
    const ring = el('div', 'holdRing'); ring.style.translate = `${x}px ${y}px`; ring.style.setProperty('--hold', HOLD_MS + 'ms'); ring.style.setProperty('--c', hue);
    ring.innerHTML = '<svg viewBox="0 0 48 48" aria-hidden="true"><circle class="track" cx="24" cy="24" r="20"/><circle class="fill" cx="24" cy="24" r="20" pathLength="100"/></svg>';
    document.body.append(ring); return ring;
  }
  // One sound at a time, for people without an agent writing a spec: an empty slot named in place.
  function addSound(cat) {
    leaveDemoKeep();
    const name = t('newSound'), a = blank({ id: makeId(name, cat), name, cat, music: kindOf(cat) === 'music', loop: kindOf(cat) !== 'sfx' });
    assets.push(a); if (stage === 'sample' && !assets.some((x) => x.sample)) stage = 'expand';
    filter = { cat: null, status: null, imported: false }; renderBoard();
    const tile = tileOf(a); tile?.scrollIntoView({ block: 'nearest' }); renameTile(a, true);
  }
  // Leaving the stand-in board by building one's own keeps what is there (unlike an import, which replaces it).
  function leaveDemoKeep() { if (demo) demo = false; }
  function newCat() { const c = addCat(t('newCat')); renderBoard(); catDialog(c, true); }
  function catDialog(c, fresh = false) {
    openDialog(t('catSettings')); reopen = () => catDialog(c);
    const name = el('input'); name.value = tx(c.name); name.setAttribute('aria-label', t('nameLabel'));
    name.oninput = () => { c.name = name.value; renderBoard(); };
    const kind = el('select'); kind.setAttribute('aria-label', t('kindLabel'));
    KINDS.forEach((k) => kind.add(new Option(t('kinds')[k], k))); kind.value = c.kind;
    kind.onchange = () => { c.kind = kind.value; assets.filter((a) => a.cat === c.id).forEach((a) => { a.music = c.kind === 'music'; if (c.kind !== 'sfx') a.loop = true; }); renderBoard(); };
    const id = el('input'); id.value = c.id; id.setAttribute('aria-label', 'id'); id.title = t('catIdHelp');
    id.onchange = () => {
      const next = slugOf(id.value).join('_');
      if (!next || catOf(next)) { id.value = c.id; return; }
      assets.filter((a) => a.cat === c.id).forEach((a) => { a.cat = next; });
      cats.filter((x) => x.parent === c.id).forEach((x) => { x.parent = next; });
      if (filter.cat === c.id) filter.cat = next;
      c.id = next; id.value = next; renderBoard();
    };
    const row = (label, input) => { const r = el('label', 'lineItem'); r.append(el('span', 'grow', label), input); return r; };
    const up = el('select'); up.setAttribute('aria-label', t('parentCat'));
    up.add(new Option(t('noParent'), ''));
    catTree().filter((x) => x !== c && !under(x.id, c.id)).forEach((x) => up.add(new Option('\u00a0\u00a0'.repeat(depthOf(x)) + tx(x.name), x.id)));
    up.value = c.parent || '';
    up.onchange = () => { if (up.value) c.parent = up.value; else delete c.parent; renderBoard(); };
    const child = el('button', '', t('addSubCat'));
    child.onclick = () => { const n = addCat(t('newCat'), c.kind, undefined, c.id); renderBoard(); catDialog(n, true); };
    const del = el('button', 'ghost', t('deleteCat'));
    del.onclick = () => {
      if (assets.some((a) => a.cat === c.id) || cats.some((x) => x.parent === c.id)) { toast(t('catNotEmpty'), 3000); return; }
      cats.splice(cats.indexOf(c), 1); if (filter.cat === c.id) filter.cat = null; dlg.close(); renderBoard();
    };
    const foot = el('div', 'dlgRow'); foot.append(del, child);
    dlg.append(row(t('nameLabel'), name), row(t('kindLabel'), kind), row(t('parentCat'), up), row('ID', id), foot);
    if (!dlg.open) dlg.showModal();
    if (fresh) { name.focus(); name.select(); }
  }
  // Right-click actions on several tiles act on the whole selection when the clicked tile is part of it.
  const targetsOf = (a) => (selected.has(a.id) && selected.size > 1 ? [...selected].map(byId).filter(Boolean) : [a]);
  function moveTo(list, cat) {
    list.forEach((a) => { a.cat = cat; a.music = kindOf(cat) === 'music'; if (kindOf(cat) !== 'sfx') a.loop = true; a.guessed = false; delete a.autoCat; });
    renderBoard();
  }
  // Nothing is deleted straight away: removed sounds go to the trash and can be put back.
  let trash = [];
  function toTrash(list) {
    if (!list.length) return;
    if (list.some((a) => a === player?.asset)) stopSound();
    list.forEach((a) => { selected.delete(a.id); const i = assets.indexOf(a); if (i >= 0) assets.splice(i, 1); a.trashedAt = Date.now(); trash.push(a); });
  }
  function removeAssets(list) { toTrash(list); renderBoard(); toast(t('trashed', list.length), 4000); }
  function restoreFromTrash(list) {
    const taken = new Set(assets.map((a) => a.id));
    list.forEach((a) => {
      trash.splice(trash.indexOf(a), 1); delete a.trashedAt;
      if (!catOf(a.cat)) a.cat = fitCat(a.cat);
      if (taken.has(a.id)) a.id = makeId(nm(a), a.cat, taken); else taken.add(a.id);
      assets.push(a);
    });
  }
  function trashDialog() {
    openDialog(t('trashHead')); reopen = trashDialog;
    if (!trash.length) dlg.append(el('p', 'note', t('trashEmpty')));
    for (const a of [...trash].reverse()) {
      const r = el('div', 'lineItem'), back = el('button', '', t('restore')), gone = el('button', 'ghost', t('deleteForever'));
      back.onclick = () => { restoreFromTrash([a]); renderBoard(); trashDialog(); };
      gone.onclick = () => { if (!confirm(t('confirmDelete', 1))) return; trash.splice(trash.indexOf(a), 1); renderBoard(); trashDialog(); };
      r.append(el('span', 'grow', `${nm(a)} · ${tx(catOf(a.cat)?.name ?? a.cat)}${a.versions.length ? '' : ` · ${statusText('pending')}`}`), back, gone);
      dlg.append(r);
    }
    if (trash.length) {
      const foot = el('div', 'dlgRow'), all = el('button', '', t('restoreAll')), empty = el('button', 'ghost', t('emptyTrash'));
      all.onclick = () => { restoreFromTrash([...trash]); renderBoard(); dlg.close(); };
      empty.onclick = () => { if (!confirm(t('confirmDelete', trash.length))) return; trash = []; renderBoard(); dlg.close(); };
      foot.append(empty, all); dlg.append(foot);
    }
    if (!dlg.open) dlg.showModal();
  }

  // Right-click on a tile: the common actions in one place.
  const tileCtx = el('div'); tileCtx.id = 'tileMenu'; tileCtx.setAttribute('role', 'menu'); tileCtx.hidden = true; document.body.append(tileCtx);
  const tileSub = el('div'); tileSub.id = 'tileSub'; tileSub.setAttribute('role', 'menu'); tileSub.hidden = true; document.body.append(tileSub);
  function closeSub() { tileSub.hidden = true; tileCtx.querySelector('.hasSub')?.setAttribute('aria-expanded', 'false'); }
  const closeTileMenu = () => { tileCtx.hidden = true; closeSub(); };
  // The group list opens beside the menu like a folder: hover or click on "Move to".
  function openSub(anchor, many, focus) {
    tileSub.textContent = '';
    for (const c of catTree()) {
      const b = el('button'), d = el('i', 'dot'); b.setAttribute('role', 'menuitem');
      b.disabled = many.every((x) => x.cat === c.id);
      d.style.setProperty('--c', c.hue); b.append(d, el('span', 'grow', tx(c.name)));
      b.style.paddingLeft = `${12 + depthOf(c) * 16}px`;
      b.onclick = () => { closeTileMenu(); moveTo(many, c.id); };
      tileSub.append(b);
    }
    anchor.setAttribute('aria-expanded', 'true'); tileSub.hidden = false;
    const r = anchor.getBoundingClientRect(), m = tileCtx.getBoundingClientRect(), q = tileSub.getBoundingClientRect();
    tileSub.style.left = (m.right + q.width + 4 <= innerWidth ? m.right - 4 : Math.max(8, m.left - q.width + 4)) + 'px';
    tileSub.style.top = Math.max(8, Math.min(r.top - 6, innerHeight - q.height - 8)) + 'px';
    if (focus) tileSub.querySelector('button:not(:disabled)')?.focus();
  }
  tileSub.addEventListener('keydown', (e) => {
    const items = [...tileSub.querySelectorAll('button:not(:disabled)')], i = items.indexOf(document.activeElement);
    if (e.key === 'Escape' || e.key === 'ArrowLeft') { e.preventDefault(); e.stopPropagation(); closeSub(); tileCtx.querySelector('.hasSub')?.focus(); }
    else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus(); }
  });
  function tileMenu(a, x, y) {
    tileCtx.textContent = '';
    const item = (label, key, fn, off = false) => {
      const b = el('button'); b.setAttribute('role', 'menuitem'); b.disabled = off;
      b.append(el('span', 'grow', label)); if (key) b.append(el('kbd', '', key));
      b.onclick = () => { closeTileMenu(); fn(); }; b.onpointerenter = closeSub; tileCtx.append(b);
    };
    const canApprove = a.status === 'draft' || a.status === 'flagged';
    const many = targetsOf(a);
    item(t('openAsset'), 'Enter', () => openDetail(a), !a.versions.length);
    item(t('rename'), 'F2', () => renameTile(a));
    if (a.status === 'approved') item(t('unapprove'), 'A', () => { a.status = 'draft'; renderBoard(); });
    else item(t('approve'), 'A', () => { approve(a); renderBoard(); }, !canApprove);
    const mv = el('button', 'hasSub'), ico = el('span', 'subIco');
    mv.setAttribute('role', 'menuitem'); mv.setAttribute('aria-haspopup', 'menu'); mv.setAttribute('aria-expanded', 'false');
    setIcon(ico, 'folder'); mv.append(ico, el('span', 'grow', t('moveTo')), el('span', 'chev', '›'));
    mv.openSub = (focus) => openSub(mv, many, focus);
    mv.onclick = () => mv.openSub(true); mv.onpointerenter = () => mv.openSub(false);
    tileCtx.append(mv);
    tileCtx.append(el('div', 'ctxSep'));
    item(many.length > 1 ? t('deleteMany', many.length) : t('deleteSound'), 'Del', () => removeAssets(many));
    tileCtx.hidden = false;
    const q = tileCtx.getBoundingClientRect();
    tileCtx.style.left = Math.min(x, innerWidth - q.width - 8) + 'px'; tileCtx.style.top = Math.min(y, innerHeight - q.height - 8) + 'px';
    focused = a.id; tileCtx.querySelector('button:not(:disabled)')?.focus();
  }
  // The same menu with plain rows: [label, key, action, disabled] or null for a line.
  function menuAt(x, y, rows) {
    tileCtx.textContent = ''; closeSub();
    for (const row of rows) {
      if (!row) { tileCtx.append(el('div', 'ctxSep')); continue; }
      const [label, key, fn, off] = row, b = el('button'); b.setAttribute('role', 'menuitem'); b.disabled = !!off;
      b.append(el('span', 'grow', label)); if (key) b.append(el('kbd', '', key));
      b.onclick = () => { closeTileMenu(); fn(); }; tileCtx.append(b);
    }
    tileCtx.hidden = false;
    const q = tileCtx.getBoundingClientRect();
    tileCtx.style.left = Math.min(x, innerWidth - q.width - 8) + 'px'; tileCtx.style.top = Math.min(y, innerHeight - q.height - 8) + 'px';
    tileCtx.querySelector('button:not(:disabled)')?.focus();
  }
  function catMenu(c, x, y) {
    const full = assets.some((a) => a.cat === c.id) || cats.some((x) => x.parent === c.id);
    menuAt(x, y, [
      [t('newSound'), '', () => addSound(c.id)],
      [t('addSubCat'), '', () => { const n = addCat(t('newCat'), c.kind, undefined, c.id); renderBoard(); catDialog(n, true); }],
      [t('refs'), '', () => refDialog({ type: 'cat', c })],
      null,
      [t('rename'), '', () => catDialog(c, true)],
      [t('catSettings'), '', () => catDialog(c)],
      null,
      [t('deleteCat'), '', () => { cats.splice(cats.indexOf(c), 1); if (filter.cat === c.id) filter.cat = null; renderBoard(); }, full],
    ]);
  }
  function boardMenu(x, y) {
    const many = ready(visible()).length;
    menuAt(x, y, [
      [t('addCat'), '', newCat],
      [t('importShort'), '', () => importDialog()],
      [t('selectAll'), 'Ctrl+A', () => { ready(visible()).forEach((a) => selected.add(a.id)); refreshSelection(); }, !many],
      null,
      [t('refsProject'), '', () => refDialog({ type: 'project' })],
      [t('export'), '', exportDialog],
    ]);
  }
  for (const id of ['board', 'side']) $(id).addEventListener('contextmenu', (e) => { if (e.target.closest('.tile, .dynCard')) return; e.preventDefault(); boardMenu(e.clientX, e.clientY); });
  addEventListener('pointerdown', (e) => { if (!tileCtx.hidden && !e.target.closest('#tileMenu, #tileSub')) closeTileMenu(); }, true);
  addEventListener('scroll', closeTileMenu, true);
  tileCtx.addEventListener('keydown', (e) => {
    const items = [...tileCtx.querySelectorAll('button:not(:disabled)')], i = items.indexOf(document.activeElement);
    if (e.key === 'Escape') { e.stopPropagation(); closeTileMenu(); tileOf(byId(focused))?.focus(); }
    else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); closeSub(); items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus(); }
    else if (e.key === 'ArrowRight' && document.activeElement?.openSub) { e.preventDefault(); document.activeElement.openSub(true); }
  });
  // Edits the name in place on the tile: Enter or leaving keeps it, Escape puts the old one back.
  function renameTile(a, renamingNew = false) {
    const tile = tileOf(a), label = tile?.querySelector('.name');
    if (!label) return;
    const input = el('input', 'renameIn'); input.value = nm(a); input.setAttribute('aria-label', t('rename'));
    let done = false;
    const finish = (keep) => {
      if (done) return; done = true;
      const value = input.value.trim();
      if (keep && value && value !== nm(a)) { a.name = value; if (renamingNew) a.id = makeId(value, a.cat, new Set(assets.filter((x) => x !== a).map((x) => x.id))); }
      renderBoard(); tileOf(byId(a.id))?.focus();
    };
    input.onkeydown = (e) => { e.stopPropagation(); if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) finish(true); if (e.key === 'Escape') finish(false); };
    input.onblur = () => finish(true);
    ['pointerdown', 'click'].forEach((type) => input.addEventListener(type, (e) => e.stopPropagation()));
    label.replaceWith(input); input.focus(); input.select();
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
      if (e.key.toLowerCase() === 'a' && !e.ctrlKey && !e.metaKey) toggleApprove(openAsset);
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
    else if (e.key === 'F2' && a) { e.preventDefault(); renameTile(a); }
    else if (e.key === 'Delete' && a) { e.preventDefault(); removeAssets(targetsOf(a)); }
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
    // The sounds asked about stay selected until something else is picked, so the batch is not lost.
    if (list.length > 1) { selected.clear(); list.forEach((a) => selected.add(a.id)); }
    renderOpen();
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
  // The assistant: whatever is typed below goes to it. It answers with changes the board applies at once,
  // and every answer that changed something can be undone. Without AI it understands links, notes and remakes.
  let agentLog = [], agentBusy = false, agentOn = false, agentN = 0;
  const agentWaits = new Map();
  const pickedSounds = () => (selected.size ? [...selected].map(byId) : focused ? [byId(focused)] : []).filter(Boolean);
  function boardState() {
    const brief1 = (r) => ({ kind: r.kind, name: r.name, ...(r.url ? { url: r.url } : {}), ...(r.note ? { note: r.note } : {}), ...(r.summary ? { facts: r.summary } : {}) });
    return {
      game: tx(game), brief: tx(brief) || '', platform,
      references: projectRefs.map(brief1),
      cats: catTree().map((c) => ({ id: c.id, name: tx(c.name), kind: c.kind, ...(c.parent ? { parent: c.parent } : {}), ...(c.refs?.length ? { references: c.refs.map(brief1) } : {}) })),
      assets: assets.map((a) => ({ id: a.id, name: nm(a), cat: a.cat, status: a.status, ...(a.description ? { description: a.description } : {}), ...(a.when ? { when: a.when } : {}),
        ...(a.versions.length ? { seconds: Math.round(heard(a).measure.seconds * 10) / 10 } : {}), ...(ownRefs(a).length ? { references: ownRefs(a).map(brief1) } : {}) })),
      selected: pickedSounds().map((a) => a.id),
    };
  }
  // Without AI: a link or a "note:" line becomes a reference for the picked sounds (or the project); anything else
  // remakes the picked sounds the way the old box did.
  function localAgent(text) {
    const picked = pickedSounds(), url = text.match(/https?:\/\/\S+/i)?.[0], note = text.match(/^\s*(?:메모|참고|레퍼런스|note|reference)\s*[:：]\s*(.+)$/is)?.[1];
    const targets = picked.length ? picked.map((a) => 'asset:' + a.id) : ['project'];
    if (url || note) return { reply: t('agentNoted'), questions: [], actions: targets.map((target) => ({ op: 'add_ref', target, kind: url ? 'link' : 'text', url: url || '', text: url ? text.replace(url, '').trim() : note.trim(), name: '', assets: [] })) };
    const usable = picked.filter((a) => a.versions.length && a.status !== 'working');
    if (usable.length) return { reply: t('agentRemake', usable.length), questions: [], actions: [{ op: 'revise', assets: usable.map((a) => a.id), text }] };
    return { reply: t('agentLocal'), actions: [], questions: [] };
  }
  function askAgent(text) {
    if (!agentOn || window.parent === window) return Promise.resolve(localAgent(text));
    const n = `${Date.now()}:${++agentN}`;
    return new Promise((ok, no) => {
      const timer = setTimeout(() => { agentWaits.delete(n); no(new Error('timeout')); }, 240000);
      agentWaits.set(n, { ok: (v) => { clearTimeout(timer); ok(v); }, no: (e) => { clearTimeout(timer); no(e); } });
      parent.postMessage({ type: 'asset:agent', payload: { n, text, state: boardState() } }, '*');
    });
  }
  addEventListener('message', (e) => {
    if (e.source !== window.parent) return;
    if (e.data?.type === 'asset:ai') agentOn = !!e.data.on;
    if (e.data?.type === 'asset:agent_reply') {
      const w = agentWaits.get(e.data.n);
      if (!w || e.data.status === 'working') return;
      agentWaits.delete(e.data.n);
      if (e.data.status === 'failed') w.no(new Error(e.data.error || 'failed')); else w.ok(e.data);
    }
  });
  if (window.parent !== window) parent.postMessage({ type: 'asset:ready' }, '*');
  // Applies the answer's changes and returns how to put things back (remakes have their own keep/discard).
  function applyActions(actions) {
    const before = { cats: JSON.stringify(cats), projectRefs: JSON.stringify(projectRefs), brief, sel: new Set(selected),
      assets: assets.map((a) => [a, { name: a.name, cat: a.cat, description: a.description, when: a.when, music: a.music, loop: a.loop, refs: JSON.stringify(ownRefs(a)) }]) };
    let n = 0;
    const remakes = [];
    for (const x of actions || []) {
      const list = (x.assets || []).map(byId).filter(Boolean);
      const target = String(x.target || ''), scope = target === 'project' ? { type: 'project' } : target.startsWith('cat:') && catOf(target.slice(4)) ? { type: 'cat', c: catOf(target.slice(4)) } : target.startsWith('asset:') && byId(target.slice(6)) ? { type: 'asset', a: byId(target.slice(6)) } : null;
      if (x.op === 'add_ref' && scope) { addRef(scope, { id: newRefId(), kind: x.kind === 'link' && x.url ? 'link' : 'text', name: x.name || (x.url ? x.url.replace(/^https?:\/\/(www\.)?/i, '').slice(0, 60) : String(x.text || '').slice(0, 40)), note: x.text || '', url: x.url || '', at: Date.now(), by: 'agent' }); n++; }
      else if (x.op === 'remove_ref' && scope) { const r = refList(scope).find((y) => (y.name || '').toLowerCase() === String(x.name || '').toLowerCase()); if (r) { dropRef(scope, r); n++; } }
      else if (x.op === 'move' && catOf(x.cat)) { list.forEach((a) => { a.cat = x.cat; a.music = kindOf(x.cat) === 'music'; if (kindOf(x.cat) !== 'sfx') a.loop = true; a.guessed = false; delete a.autoCat; }); n += list.length; }
      else if (x.op === 'rename' && list[0] && x.name) { list[0].name = x.name; n++; }
      else if (x.op === 'describe') { list.forEach((a) => { a.description = x.text || ''; }); n += list.length; }
      else if (x.op === 'set_when') { list.forEach((a) => { a.when = x.text || ''; }); n += list.length; }
      else if (x.op === 'add_cat' && x.cat && !catOf(slugOf(x.cat).join('_'))) { addCat(x.name || x.cat, x.kind, slugOf(x.cat).join('_'), catOf(x.parent) ? x.parent : undefined); n++; }
      else if (x.op === 'set_brief') { brief = x.text || ''; n++; }
      else if (x.op === 'select') { selected.clear(); list.forEach((a) => selected.add(a.id)); }
      else if (x.op === 'revise') remakes.push([list.filter((a) => a.versions.length && a.status !== 'working'), x.text || '']);
    }
    syncRefs(); renderBoard();
    for (const [list, text] of remakes) if (list.length) request(list, text);
    if (!n) return null;
    return () => {
      cats = JSON.parse(before.cats); projectRefs = JSON.parse(before.projectRefs); brief = before.brief;
      for (const [a, f] of before.assets) { const { refs, ...rest } = f; Object.assign(a, rest); a.refs = [...(a.refs || []).filter((r) => r.from !== 'asset'), ...JSON.parse(refs)]; }
      selected.clear(); before.sel.forEach((id) => selected.add(id));
      syncRefs(); renderBoard();
    };
  }
  // No window of its own: the answer shows in the toast (with undo), a hand-over question sits in the dock's input row.
  function say(text, undo) {
    toast(text, undo ? 8000 : 4000);
    if (undo) { const u = el('button', 'ghost', t('agentUndo')); u.onclick = () => { undo(); autosave(); toast(t('agentUndone')); }; $('toast').append(' ', u); }
  }
  async function sendAgent(text) {
    if (agentBusy) return;
    agentLog.push({ me: true, text });
    agentBusy = true; syncDock(); toast(t('agentThinking'), 0);
    try {
      const answer = await askAgent(text);
      const undo = applyActions(answer.actions);
      agentLog.push({ text: answer.reply || '' });
      const reply = answer.reply || t('agentDid', (answer.actions || []).length);
      say(answer.upgraded ? `${t('agentUpgraded', answer.upgraded)} ${reply}` : reply, undo);
    } catch (e) { say(t('agentFailed', e.message || e)); }
    agentBusy = false; syncDock(); autosave();
  }
  // Enter that only ends a Korean syllable must not send the form (same as the music screen).
  document.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.isComposing || e.keyCode === 229) && e.target.matches?.('input')) e.preventDefault(); }, true);
  $('askForm').onsubmit = (e) => {
    e.preventDefault();
    const text = $('ask').value.trim(); if (!text || agentBusy) return;
    $('ask').value = '';
    sendAgent(text);
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
    document.body.classList.toggle('inDetail', on); // the header turns into the detail's navigation
  }
  let walk = [];
  function openDetail(a) {
    const tile = tileOf(a);
    walk = ready(visible());
    if (!walk.includes(a)) walk.unshift(a);
    if (tile) tile.style.viewTransitionName = 'zoom';
    transition(() => {
      if (tile) tile.style.viewTransitionName = '';
      stopSound(); openAsset = a; focused = a.id; stemState = {}; detailTab = 'tracks'; showDetail(true); renderDetail();
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

  // Laid out like the music screen: play, name and approve on one line, the sound under them, then tabs (tracks,
  // code, versions) across the full width. The side is the conversation, with the references above its input.
  // Licences are not per sound: they are all in the export dialog, copied at once.
  function renderDetail() {
    const a = openAsset, v = heard(a), m = v.measure, box = $('detailView');
    const typed = document.querySelector('.detailDock textarea')?.value || '';
    box.textContent = '';
    const multi = v.sound.stems.length > 1, tab = detailTab === 'tracks' && !multi ? 'versions' : detailTab;
    const main = el('div', 'dMain' + (tab === 'code' ? ' coding' : '')), head = el('div', 'dHead');
    const play = iconButton('play', t('play'), toggleDetailPlay, 'iconBtn dPlay'); play.id = 'dPlay';
    const title = el('div', 'dTitle');
    // Name and category apply as they are typed; there is nothing to save.
    const name = el('input', 'dName'); name.value = nm(a); name.setAttribute('aria-label', t('nameLabel'));
    name.oninput = () => { a.name = name.value; renderHeader(); };
    const facts = el('div', 'dFacts');
    facts.append(catPicker(a, () => renderDetail()));
    if (a.imported) { const like = el('button', 'ghost', t('likeThis')); like.id = 'likeThis'; like.onclick = () => likeThis(a); facts.append(like); }
    title.append(name, facts);
    head.append(play, title, approveButton(a));
    const wave = el('div', 'dWave'), canvas = el('canvas'), time = el('span', 'dTime', seconds(m.seconds)); time.id = 'dTime'; time.dataset.len = m.seconds; wave.append(canvas, time);
    wave.onclick = (e) => { const r = wave.getBoundingClientRect(); window.setTimeout(renderPlayButton); playFrom((e.clientX - r.left) / r.width * m.seconds); };
    main.append(head, wave);
    if (a.status === 'review') {
      const row = el('div', 'tile'); row.style.cssText = 'height:auto;background:none;overflow:visible;margin-top:8px';
      const ab = reviewRow(a, renderDetail); ab.style.position = 'static';
      row.append(ab); main.append(row);
    }
    const tabs = el('div', 'tabs'), body = el('div', 'dTab');
    tabs.setAttribute('role', 'tablist');
    for (const [id, label] of [...(multi ? [['tracks', t('tabTracks')]] : []), ['code', t('tabCode')], ['versions', t('tabVersions')]]) {
      const b = el('button', '', label); b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', String(id === tab));
      b.onclick = () => { detailTab = id; renderDetail(); }; tabs.append(b);
    }
    if (tab === 'code') {
      if (a.prompt) {
        const fold = el('details', 'promptFold'), sum = el('summary'), full = el('pre', 'code prompt', a.prompt); full.id = 'promptText';
        sum.append(el('b', '', t('promptHead')), el('span', '', a.prompt.split('\n')[0]));
        fold.append(sum, full); body.append(fold);
      }
      const code = el('pre', 'codeView'); for (const line of sourceOf(a).split('\n')) code.append(el('span', 'ln', line || ' '));
      body.append(code);
    } else if (tab === 'versions') {
      [...a.versions].reverse().forEach((ver) => {
        const i = a.versions.indexOf(ver), row = el('div', 'lineItem'), text = el('span', 'grow', `v${i + 1} · ${noteText(ver.note)}`);
        row.append(iconButton('play', t('listen'), () => { a.current = i; renderDetail(); play(a); }, 'ghost iconBtn'), text);
        if (i === a.current) row.append(el('span', 'tag', t('current')));
        body.append(row);
      });
    } else v.sound.stems.forEach((st, i) => body.append(stemRow(st, i)));
    main.append(tabs, body);
    box.append(main, chatPanel(a, typed));
    requestAnimationFrame(() => {
      const hue = resolved(color(a.cat));
      drawPeaks(canvas, v.peaks, hue);
      document.querySelectorAll('.stem').forEach((row, i) => drawPeaks(row.querySelector('canvas'), synth.peaks(v.sound.stems[i].data, 160), stems[i % stems.length]));
    });
    renderPlayButton(); renderHeader();
  }
  // One raised button: approve, or, once approved, a green "approved" that takes it back. A approves from the keyboard.
  function approveButton(a) {
    const done = a.status === 'approved', b = el('button', 'dApprove' + (done ? ' done' : ''));
    setIcon(b, 'check'); b.append(done ? t('approved') : t('approve'));
    b.setAttribute('aria-pressed', String(done)); if (done) b.title = t('unapprove');
    b.disabled = a.status === 'working' || a.status === 'review';
    b.onclick = () => toggleApprove(a);
    return b;
  }
  function toggleApprove(a) {
    if (a.status === 'working' || a.status === 'review') return;
    if (a.status === 'approved') a.status = 'draft'; else approve(a);
    renderDetail();
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
  // The conversation: the log, the references as chips, then the clip and the draft count, then the request.
  // Files dropped anywhere on it become references of this sound.
  function chatPanel(a, typed = '') {
    const side = el('div', 'dSide'), body = el('div', 'tabBody');
    a.chat.forEach((msg) => body.append(el('div', 'msg ' + (msg.me ? 'me' : 'ai'), chatText(msg))));
    const tools = el('div', 'dTools');
    const refs = refSlot({ type: 'asset', a }, { bare: true, tools, redraw: redrawChat });
    const busy = a.status === 'working';
    const seg = el('div', 'draftSeg'); seg.setAttribute('role', 'radiogroup'); seg.setAttribute('aria-label', t('draftCountLabel'));
    seg.append(el('span', 'segLabel', t('drafts')));
    for (let i = 1; i <= MAX_DRAFTS; i++) {
      const b = el('button', '', String(i)); b.type = 'button'; b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', String(drafts === i));
      b.setAttribute('aria-label', t('draftCount', i));
      b.onclick = () => { drafts = i; seg.querySelectorAll('[role=radio]').forEach((x, k) => x.setAttribute('aria-checked', String(k + 1 === i))); };
      seg.append(b);
    }
    tools.append(seg);
    const dock = el('form', 'detailDock'), input = el('textarea'); input.rows = 2; input.value = typed;
    input.placeholder = t('askThis'); input.setAttribute('aria-label', t('askThis'));
    const send = iconButton('send', t('send'), null); send.type = 'submit'; send.disabled = busy;
    const go = () => { const text = input.value.trim(); if (text && a.status !== 'working') request([a], text); };
    // Enter sends, Shift+Enter breaks the line; nothing is sent while a Korean syllable is still being composed.
    input.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); go(); } };
    dock.onsubmit = (e) => { e.preventDefault(); go(); };
    dock.append(input, send);
    side.append(body);
    if (busy) side.append(el('div', 'dWorking', `${statusText('working')}…`));
    side.append(refs, tools, dock);
    requestAnimationFrame(() => { body.scrollTop = body.scrollHeight; });
    return side;
  }
  function redrawChat() {
    const old = document.querySelector('.dSide'); if (!old || !openAsset) return;
    const typed = old.querySelector('.detailDock textarea')?.value || '';
    old.replaceWith(chatPanel(openAsset, typed));
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
      // Where it is out of how long it is; stopped, just the length.
      const time = $('dTime'), len = +time?.dataset.len;
      if (time) time.textContent = player?.asset === openAsset ? `${secNum(position(), len)} / ${seconds(len)}` : seconds(len);
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

  const specExample = () => {
    const ex = t('example'), ids = [['sfx_ui_click', 'ui', 0.1, false], ['sfx_combat_parry', 'combat', 0.3, false], ['bgm_garden', 'bgm', 60, true]];
    return JSON.stringify({ game: tx(game), platform: 'mobile', style: ex.style, assets: ids.map(([id, category, length, loop], k) => ({ id, name: ex.assets[k].name, category, length, loop, when: ex.assets[k].when, description: ex.assets[k].description })), questions: [] }, null, 2);
  };
  const specForm = () => JSON.stringify({ game: '', platform: '', style: '', references: [{ name: '', note: '', url: '' }], categories: [{ id: '', name: '', kind: '', parent: '' }], assets: [{ id: '', name: '', category: '', length: 0, loop: false, when: '', description: '' }], questions: [] }, null, 2);
  // Only what this tool knows goes in. The game itself is the other agent's to fill in.
  const specPrompt = () => t('specPrompt', {
    platforms: PROFILES.map((f) => f.id).filter((id) => id !== 'wide').join(', '),
    cats: cats.map((c) => `${c.id}(${c.kind})`).join(', '),
    idRule: idRuleText(),
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
  // Spec field -> asset field. Sound already made stays; a changed field shapes the next edit.
  const SPEC_KEYS = { name: 'name', category: 'cat', length: 'length', loop: 'loop', when: 'when', description: 'description' };
  const specDiff = (a, x) => Object.keys(SPEC_KEYS).filter((k) => {
    if (!(k in x)) return false;
    // Length matches what export writes: the asked length if one was given, else the measured one.
    const made = a.versions.length ? Math.round(heard(a).measure.seconds * 100) / 100 : null;
    const now = k === 'name' ? nm(a) : k === 'length' ? a.length ?? made : a[SPEC_KEYS[k]];
    return k === 'loop' ? !!now !== !!x.loop : (now ?? '') !== (x[k] ?? '');
  });
  function planSpec(text) {
    let spec;
    try { spec = JSON.parse(text); } catch (e) { return [el('p', 'note err', t('notJson', e.message))]; }
    if (!Array.isArray(spec.assets)) return [el('p', 'note err', t('noAssets'))];
    const seen = new Set(), bad = spec.assets.filter((x) => !x || typeof x.id !== 'string' || !x.id.trim() || seen.has(x.id) || !seen.add(x.id));
    if (bad.length) return [el('p', 'note err', t('badItems', bad.length, bad.map((x) => x?.id || t('noName')).join(', ')))];
    const specCats = Array.isArray(spec.categories) ? spec.categories.filter((c) => c && c.id) : [];
    const newCats = [...new Set([...specCats.map((c) => c.id), ...spec.assets.map((x) => x.category).filter(Boolean)])].filter((id) => !catOf(id));
    const offRule = spec.assets.filter((x) => !idOk(x.id));
    const ids = new Set(spec.assets.map((x) => x.id)), added = spec.assets.filter((x) => !byId(x.id)), changed = spec.assets.filter((x) => byId(x.id) && specDiff(byId(x.id), x).length), kept = spec.assets.filter((x) => byId(x.id) && !specDiff(byId(x.id), x).length), gone = assets.filter((a) => !ids.has(a.id));
    const out = [el('h3', '', t('planSummary', added.length, changed.length, kept.length, gone.length))];
    const made = assets.filter((a) => a.versions.length && ids.has(a.id)).length;
    if (made) out.push(el('p', 'note', t('specKeepsAudio', made)));
    if (newCats.length) out.push(el('p', 'note', t('specNewCats', newCats.join(', '))));
    if (offRule.length) out.push(el('p', 'note', t('specIdWarn', offRule.length, offRule.slice(0, 6).map((x) => x.id).join(', '))));
    const line = (tag, cls, text) => { const r = el('div', 'lineItem'); r.append(el('span', 'tag ' + cls, tag), el('span', 'grow', text)); return r; };
    added.forEach((x) => out.push(line(t('tagAdd'), 'add', `${x.name} · ${x.id}`)));
    changed.forEach((x) => out.push(line(t('tagChange'), 'chg', `${nm(byId(x.id))}: ${specDiff(byId(x.id), x).map((k) => t('specField')[k]).join(', ')}`)));
    gone.slice(0, 6).forEach((a) => out.push(line(t('tagTrash'), 'del', nm(a))));
    if (gone.length > 6) out.push(el('p', '', t('moreRemoved', gone.length - 6)));
    const row = el('div', 'dlgRow'), run = el('button', 'primary', t('startWithSpec')), keep = el('button', '', t('addOnly'));
    const apply = (remove) => {
      const target = PROFILES.find((f) => f.id === spec.platform);
      if (target) { rule('loud').range = [...target.loud]; platform = target.id; }
      if (spec.game) game = spec.game;
      if (spec.style) brief = spec.style;
      if (Array.isArray(spec.references)) {
        projectRefs = projectRefs.filter((r) => r.by !== 'spec');
        for (const r of spec.references) if (r && (r.note || r.url)) projectRefs.push({ id: newRefId(), kind: r.url ? 'link' : 'text', name: String(r.name || '').slice(0, 80), note: String(r.note || ''), url: String(r.url || ''), at: Date.now(), by: 'spec' });
        syncRefs();
      }
      demo = false;
      for (const c of specCats) { const have = catOf(c.id); if (have) { if (c.name) have.name = c.name; if (KINDS.includes(c.kind)) have.kind = c.kind; } else addCat(c.name || c.id, c.kind, c.id); }
      for (const c of specCats) if (c.parent && catOf(c.parent) && !under(c.parent, c.id)) catOf(c.id).parent = c.parent;
      for (const id of newCats) if (!catOf(id)) addCat(id, KIND_OF[id] || (spec.assets.find((x) => x.category === id)?.loop ? 'amb' : 'sfx'), id);
      added.forEach((x) => { x.category ||= cats[0].id; const amb = kindOf(x.category) === 'amb'; const a = { id: x.id, name: x.name, cat: x.category, music: kindOf(x.category) === 'music', loop: !!x.loop || amb, layers: amb ? [STUDIO_DATA.bed(x.name, x.length >= 16 ? 16 : 8, 0.1, 0.4, [[1, 0.25, 0], [3, 0.15, 1]])] : [{ kind: 'tone', from: 500, to: 700, len: Math.min(0.6, x.length || 0.3), wave: 'triangle', gain: 0.4, at: 0 }], status: 'draft', versions: [], current: 0, drafts: [], pick: -1, chat: [], progress: 0, length: x.length, when: x.when || '', description: x.description || '' }; assets.push(a); make(a, {}, { key: 'fromSpec' }); });
      changed.forEach((x) => { const a = byId(x.id); for (const k of specDiff(a, x)) a[SPEC_KEYS[k]] = k === 'loop' ? !!x.loop : x[k] ?? ''; });
      if (remove) toTrash(gone);
      dlg.close(); renderBoard(); toast(remove && gone.length ? t('specAppliedTrash', added.length, gone.length) : t('specApplied', added.length), 5000);
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
    dlg.append(el('h3', '', t('exportFormat')));
    const opt = (label, key, choices) => {
      const s = el('select'); s.setAttribute('aria-label', label);
      choices.forEach(([v, l]) => s.add(new Option(l, v))); s.value = String(exportOpts[key]);
      s.onchange = () => { exportOpts[key] = /^\d+$/.test(s.value) ? +s.value : s.value; autosave(); exportDialog(); };
      const r = el('label', 'lineItem'); r.append(el('span', 'grow', label), s); dlg.append(r);
    };
    opt(t('fmt'), 'format', [['wav', 'WAV'], ['ogg', 'OGG Vorbis'], ['mp3', 'MP3']]);
    opt(t('rate'), 'rate', [[44100, '44.1 kHz'], [48000, '48 kHz'], [22050, '22.05 kHz']]);
    if (exportOpts.format === 'wav') opt(t('bits'), 'bits', [[16, '16 bit'], [24, '24 bit']]);
    else opt(t('quality'), 'quality', [['high', t('qualities').high], ['mid', t('qualities').mid], ['low', t('qualities').low]]);
    opt(t('folders'), 'folders', [['flat', t('foldersFlat')], ['cat', t('foldersCat')], ['kind', t('foldersKind')]]);
    const root = el('input'); root.value = exportOpts.root || 'audio'; root.setAttribute('aria-label', t('rootFolder'));
    root.onchange = () => { exportOpts.root = root.value.trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '') || 'audio'; autosave(); exportDialog(); };
    { const r = el('label', 'lineItem'); r.append(el('span', 'grow', t('rootFolder')), root); dlg.append(r); }
    opt(t('engine'), 'engine', [['none', t('engineNone')], ['godot', 'Godot 4']]);
    // Chrome and Edge can write straight into the game: linked once, every approval lands there with the settings above.
    if ('showDirectoryPicker' in window) {
      const r = el('div', 'lineItem'), b = el('button', gameDir ? 'ghost' : '', gameDir ? t('unlinkFolder') : t('linkFolder'));
      b.id = 'folderLink'; b.onclick = gameDir ? () => { gameDir = null; keepDir(null); exportDialog(); } : linkFolder;
      r.append(el('span', 'grow', gameDir ? t('folderLinked', gameDir.name) : t('folderHelp')), b);
      dlg.append(el('h3', '', t('gameFolder')), r);
    }
    dlg.append(el('h3', '', t('inBundle')));
    for (const item of [t('bundleAudio', exportPath({ id: '<id>', cat: '<group>' })), ...t('bundleItems').slice(1), ...(exportOpts.engine === 'godot' ? [t('bundleGodot')] : [])]) dlg.append(Object.assign(el('div', 'lineItem'), { textContent: item }));
    // Every licence in one place, as CREDITS.md will read, copied at once. A sound brought in from outside gets its
    // licence and holder typed here, and the text follows as they are typed.
    const credits = el('section', 'credits'), head = el('h3', 'creditsHead'), text = el('pre', 'code creditsText');
    head.append(el('span', 'grow', t('licenses')), iconButton('copy', t('copyLicenses'), copyLicenses, 'ghost iconBtn'));
    const refresh = () => { text.textContent = licenseText(); };
    credits.append(head);
    for (const a of assets.filter((x) => x.imported)) { const r = el('div', 'lineItem creditRow'); r.append(el('span', 'grow', a.file ? base(a.file) : a.id), ...licenseFields(a, refresh)); credits.append(r); }
    credits.append(text); refresh(); dlg.append(credits);
    const row = el('div', 'dlgRow'), go = el('button', 'primary', t('exportBundle'));
    go.id = 'exportGo'; go.onclick = () => { dlg.close(); stage = 'export'; renderHeader(); exportBundle().catch((e) => toast(t('exportFailed', e.message || e), 6000)); };
    row.append(go); dlg.append(row);
    if (!dlg.open) dlg.showModal();
  }
  function gameDialog() {
    openDialog(tx(game)); reopen = gameDialog;
    dlg.append(el('p', '', tx(brief)));
    const b = el('button', '', t('restart')); b.onclick = async () => { await forget(); location.reload(); }; dlg.append(b);
    dlg.showModal();
  }

  let hoverOn = true;
  function settingsDialog() {
    openDialog(t('settings')); reopen = settingsDialog;
    const pick = el('select'); pick.id = 'langPick'; pick.setAttribute('aria-label', t('language'));
    pick.add(new Option('English', 'en')); pick.add(new Option('한국어', 'ko')); pick.value = lang;
    // In the music studio the host owns the language, so the choice also goes up to it.
    pick.onchange = () => { if (inHost) parent.postMessage({ type: 'asset:setlang', lang: pick.value }, '*'); setLang(pick.value); };
    const row = el('div', 'lineItem'); row.append(el('span', 'grow', t('language')), pick);
    const hover = el('input'); hover.type = 'checkbox'; hover.checked = hoverOn;
    hover.onchange = () => { hoverOn = hover.checked; };
    const row2 = el('label', 'lineItem'); row2.append(el('span', 'grow', t('hoverPlay')), hover);
    dlg.append(row, row2, el('h3', '', t('idRule')), el('p', 'note', t('idHelp')));
    const field = (label, value, set, width) => { const i = el('input'); i.value = value; i.setAttribute('aria-label', label); if (width) i.style.width = width; i.oninput = () => { set(i.value); example(); }; const r = el('label', 'lineItem'); r.append(el('span', 'grow', label), i); dlg.append(r); return i; };
    const pat = field(t('idPattern'), idRule.pattern, (v) => { idRule.pattern = v.trim() || '{name}'; }, '200px');
    const sep = el('select'); sep.setAttribute('aria-label', t('idSep')); [['_', 'snake_case'], ['-', 'kebab-case'], ['.', 'dot.case']].forEach(([v, l]) => sep.add(new Option(l, v))); sep.value = idRule.sep;
    sep.onchange = () => { idRule.sep = sep.value; idRule.pattern = idRule.pattern.replace(/\}[_.-]/g, '}' + sep.value).replace(/[_.-]\{/g, sep.value + '{'); pat.value = idRule.pattern; example(); };
    const sepRow = el('label', 'lineItem'); sepRow.append(el('span', 'grow', t('idSep')), sep); dlg.append(sepRow);
    for (const k of KINDS) field(`${t('idPrefix')} · ${t('kinds')[k]}`, idRule.prefix[k] ?? '', (v) => { idRule.prefix[k] = slugOf(v).join('') || k; }, '120px');
    const check = el('input'); check.type = 'checkbox'; check.checked = idRule.check; check.onchange = () => { idRule.check = check.checked; renderBoard(); };
    const checkRow = el('label', 'lineItem'); checkRow.append(el('span', 'grow', t('idCheck')), check); dlg.append(checkRow);
    const ex = el('p', 'note'); dlg.append(ex);
    function example() { ex.textContent = t('idExample', makeId('Sword swing', cats.find((c) => c.kind === 'sfx')?.id || cats[0]?.id || 'ui', new Set()), assets.filter((a) => !idOk(a.id)).length); }
    example();
    const redo = el('button', '', t('idRenameAll'));
    redo.onclick = () => {
      const taken = new Set(); let n = 0;
      for (const a of assets) { const old = a.id; a.id = makeId(nm(a), a.cat, taken); if (a.id !== old) { n++; selected.delete(old); dynamics.forEach((d) => d.layers.forEach((l) => { if (l.asset === old) l.asset = a.id; })); } }
      renderBoard(); example(); toast(t('idRenamed', n));
    };
    const foot = el('div', 'dlgRow'); foot.append(redo); dlg.append(foot);
    if (!dlg.open) dlg.showModal();
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
    ({ settings: settingsDialog, spec: () => specDialog(), game: gameDialog, help: tutorial, refs: () => refDialog({ type: 'project' }) })[b.dataset.act]();
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
      if (!zipped && !AUDIO.test(e.path) && !/\.json$/i.test(e.path)) { if (!/\.(md|txt|gd|tscn|tres|cfg)$/i.test(e.path)) sk.type++; continue; }
      if (size > (zipped ? LIMITS.total : LIMITS.file) || total + size > LIMITS.total) { sk.big++; continue; }
      total += size;
      if (!zipped) { found.push(e); continue; }
      try {
        const inside = await importer.unzip(await e.bytes(), LIMITS.file);
        sk.big += inside.skipped.filter((x) => x.why === 'big').length; sk.bad += inside.skipped.filter((x) => x.why === 'bad').length;
        for (const z of inside) {
          if (importer.junk(z.path)) continue;
          if (AUDIO.test(z.path) || /\.json$/i.test(z.path)) found.push({ path: z.path, size: z.size, bytes: async () => z.bytes });
          else if (!/\.(md|txt|gd|tscn|tres|cfg)$/i.test(z.path)) sk.type++;
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
        const guess = importer.guessCategory(path, secs), cat = fitCat(guess.cat), sure = guess.sure, name = importer.guessName(path);
        const loopy = kindOf(cat) !== 'sfx' || /loop/i.test(path);
        const a = blank({ id: makeId(name, cat, taken), name, cat, music: kindOf(cat) === 'music', loop: loopy, imported: true, file: f.path, license: '', holder: '', guessed: !sure, status: 'approved' });
        fromAudio(a, data, 'importedNote');
        assets.push(a); added.push(a);
      } catch { sk.bad++; }
    }
    if (added.length && stage === 'sample') stage = 'expand';
    renderOpen();
    report(added.length ? t('importedN', added.length) : t('nothingToImport'), sk);
    if (added.length) { importDialog(added); askJev(added); }
  }
  // A bundle this screen exported: the spec says what each sound is, the audio files are the sounds.
  async function openBundle(spec, files, sk = tally()) {
    leaveDemo();
    assets.length = 0; selected.clear(); stopSound();
    game = spec.game || game; brief = spec.style || '';
    const target = PROFILES.find((f) => f.id === spec.platform);
    if (target) { platform = target.id; rule('loud').range = [...target.loud]; }
    if (Array.isArray(spec.categories) && spec.categories.length) cats = spec.categories.filter((c) => c && c.id).map((c, i) => ({ id: c.id, name: c.name || c.id, kind: KINDS.includes(c.kind) ? c.kind : 'sfx', hue: c.color || CATEGORIES.find((d) => d.id === c.id)?.hue || HUES[i % HUES.length], ...(c.parent ? { parent: c.parent } : {}) }));
    if (spec.id_rule?.pattern) idRule = { ...idRule, ...spec.id_rule, prefix: { ...idRule.prefix, ...spec.id_rule.prefix } };
    if (spec.export) exportOpts = { ...exportOpts, ...spec.export };
    dynamics = Array.isArray(spec.dynamics) ? spec.dynamics.map(dynFromSpec) : [];
    const backRefs = (list) => (Array.isArray(list) ? list : []).filter((r) => r && (r.kind === 'text' || r.kind === 'link')).map((r) => ({ id: newRefId(), kind: r.kind, name: String(r.name || ''), note: String(r.note || ''), url: String(r.url || ''), at: Date.now() }));
    projectRefs = backRefs(spec.references);
    for (const c of spec.categories || []) if (c?.references && catOf(c.id)) catOf(c.id).refs = backRefs(c.references);
    let done = 0;
    for (const x of spec.assets) {
      if (spec.assets.length > 1) { toast(t('importing', ++done, spec.assets.length), 0); await breathe(); }
      if (!x || !x.id) continue;
      const audio = files.find((f) => AUDIO.test(f.path) && ((x.file && f.path.endsWith(x.file)) || stem(f.path) === x.id));
      const a = blank({ id: x.id, name: x.name || x.id, cat: catOf(x.category) ? x.category : fitCat(importer.guessCategory(x.id, x.length || 0).cat),
        loop: !!x.loop, music: kindOf(x.category) === 'music', when: x.when || '', description: x.description || '', length: x.length ?? null,
        imported: x.origin === 'imported', file: x.source_file || '', license: x.license || '', holder: x.holder || '', prompt: x.prompt || '' });
      a.refs = backRefs(x.references).map((r) => ({ ...r, from: 'asset' }));
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
      const cat = fitCat(x.cat), id = x.id && !taken.has(x.id) ? (taken.add(x.id), x.id) : makeId(x.name, cat, taken);
      assets.push(blank({ id, name: x.name, cat, loop: x.loop, music: kindOf(cat) === 'music', when: x.when, description: x.description, length: x.length }));
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
    const cat = catOf(a.cat);
    return t('fillPrompt', { name: nm(a), id: a.id, cat: cat ? tx(cat.name) : a.cat, game: tx(game), when: a.when, description: a.description, loop: !!a.loop, length: a.length, style: tx(brief), ref: refText });
  }
  // Stands in for the model that reads the prompt; it at least follows the reference's length and band balance.
  function layersFor(a, m) {
    if (kindOf(a.cat) === 'music') { a.music = true; return STUDIO_DATA.music(a.id, a.name, 100, 57, 'bright').layers; }
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
      const a = blank({ id: makeId(`${nm(ref)} like`, ref.cat), name: t('likeName', nm(ref)), cat: ref.cat, loop: !!ref.loop, music: !!ref.music });
      assets.push(a); list = [a];
    }
    closeDetail(); fill(list, ref); toast(t('likeMade', list.length));
  }

  /* ---------- references ---------- */
  // A reference belongs to the project, a group or one sound. Project and group references are copied into every
  // sound they cover (from says where each copy came from), so each sound carries its own complete list.
  let projectRefs = [];
  const refBlobs = new Map(), savedRefs = new Set();
  const newRefId = () => `r${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
  const ownRefs = (a) => (a.refs || []).filter((r) => r.from === 'asset');
  const tagged = (list, from) => (list || []).map((r) => ({ ...r, from }));
  const scopeRefs = (a) => [...tagged(projectRefs, 'project'), ...chainOf(catOf(a.cat)).flatMap((c) => tagged(c.refs, 'cat:' + c.id))];
  function syncRefs(list = assets) { for (const a of list) a.refs = [...scopeRefs(a), ...ownRefs(a)]; }
  const refList = (scope) => (scope.type === 'project' ? projectRefs : scope.type === 'cat' ? (scope.c.refs ||= []) : ownRefs(scope.a));
  function addRef(scope, r) {
    if (scope.type === 'asset') (scope.a.refs ||= []).push({ ...r, from: 'asset' });
    else refList(scope).push(r);
    syncRefs(); autosave();
  }
  function dropRef(scope, r) {
    if (scope.type === 'asset') scope.a.refs = (scope.a.refs || []).filter((x) => !(x.id === r.id && x.from === 'asset'));
    else { const list = refList(scope), i = list.findIndex((x) => x.id === r.id); if (i >= 0) list.splice(i, 1); }
    syncRefs(); autosave();
  }
  const refKeys = () => new Set([...projectRefs, ...cats.flatMap((c) => c.refs || []), ...[...assets, ...trash].flatMap(ownRefs)].map((r) => r.key).filter(Boolean));
  const unzipFor = async (bytes) => (await importer.unzip(bytes, LIMITS.file)).map((z) => ({ path: z.path, bytes: async () => z.bytes }));
  async function refFromFile(name, bytes) {
    const kind = refKit.kindOf(name);
    if (!kind) throw new Error(t('refBadType'));
    if (bytes.length > LIMITS.file) throw new Error(t('refTooBig'));
    const facts = kind === 'audio' ? refKit.audioFacts(await decode(bytes), 22050) : kind === 'midi' ? refKit.midiFacts(bytes) : await refKit.scoreFacts(name, bytes, unzipFor);
    const id = newRefId(), key = 'ref:' + id;
    refBlobs.set(key, bytes);
    return { id, kind, name, note: '', url: '', key, facts, summary: refKit.summary(kind, facts), at: Date.now() };
  }
  async function addRefFiles(scope, files, redraw) {
    let bad = 0;
    for (const f of files) {
      try { addRef(scope, await refFromFile(base(f.path), await f.bytes())); } catch (e) { bad++; toast(`${base(f.path)}: ${e.message || e}`, 4000); }
    }
    if (files.length - bad) toast(t('refAdded', files.length - bad));
    if (redraw) { renderBoardQuiet(); redraw(); } else { renderBoard(); refDialog(scope); }
  }
  let refAudio = null;
  function playRef(r, button) {
    if (refAudio) { refAudio.pause(); URL.revokeObjectURL(refAudio.src); const was = refAudio.ref; refAudio = null; if (was === r.id) { setIcon(button, 'play'); return; } }
    const bytes = refBlobs.get(r.key); if (!bytes) { toast(t('refGone'), 3000); return; }
    stopSound();
    refAudio = new Audio(URL.createObjectURL(new Blob([bytes]))); refAudio.ref = r.id;
    refAudio.onended = () => { setIcon(button, 'play'); refAudio = null; };
    refAudio.play().catch(() => toast(t('refCannotPlay'), 3000));
    setIcon(button, 'stop');
  }
  const fromLabel = (from) => (from === 'project' ? t('refFromProject') : from?.startsWith('cat:') ? tx(catOf(from.slice(4))?.name ?? from.slice(4)) : '');
  function refRow(r, scope) {
    const row = el('div', 'refRow'), head = el('div', 'refHead');
    head.append(el('span', 'tag ref-' + r.kind, t('refKinds')[r.kind] || r.kind));
    if (r.kind === 'link' && /^https?:\/\//i.test(r.url)) { const a = el('a', 'grow', r.name || r.url); a.href = r.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; head.append(a); }
    else head.append(el('span', 'grow refName', r.name || t('refKinds').text));
    if (!scope) head.append(el('span', 'tag', fromLabel(r.from)));
    if (r.kind === 'audio' && r.key) { const b = iconButton('play', t('listen'), () => playRef(r, b), 'ghost iconBtn'); head.append(b); }
    if (scope) head.append(iconButton('close', t('refRemove'), () => { dropRef(scope, r); renderBoard(); refDialog(scope); }, 'ghost iconBtn'));
    row.append(head);
    if (r.summary) row.append(el('div', 'refFacts', r.summary));
    if (scope) {
      // The note says what to take from this reference; it is kept as it is typed.
      const note = el('textarea', 'refNote'); note.value = r.note || ''; note.placeholder = r.kind === 'text' ? t('refNotePh') : t('refTakePh'); note.setAttribute('aria-label', t('refTakePh'));
      note.oninput = () => { r.note = note.value; syncRefs(); autosave(); };
      row.append(note);
    } else if (r.note) row.append(el('div', 'refFacts', r.note));
    return row;
  }
  // References as a slot: chips you can drop files on. A chip opens its note under the row; + adds a file, a link
  // or a note in place. References inherited from the category or the project show dimmed, without a remove.
  // Bare, it is the attachment row of a conversation: chips only when there are any, and the add button is the
  // clip in the conversation's tools (opts.tools).
  let refOpen = '';
  const REF_ICON = { audio: 'sound', midi: 'music', score: 'music', link: 'link', text: 'spec' };
  function refSlot(scope, opts = {}) {
    const bare = !!opts.bare;
    const slot = el('div', 'refSlot' + (bare ? ' bare' : '')), row = el('div', 'refChips'), extra = el('div', 'refMore');
    if (!bare) { const head = el('span', 'refLabel'); setIcon(head, 'ref'); head.append(t('refs')); head.title = t('refsHelp')[scope.type]; row.append(head); }
    const redraw = opts.redraw || (() => { const next = refSlot(scope); slot.replaceWith(next); return next; });
    const inherited = scope.type === 'asset' ? scopeRefs(scope.a) : scope.type === 'cat' ? [...tagged(projectRefs, 'project'), ...chainOf(scope.c).slice(0, -1).flatMap((c) => tagged(c.refs, 'cat:' + c.id))] : [];
    const chip = (r, own) => {
      const b = el('button', 'refChip ref-' + r.kind + (own ? '' : ' inherited') + (refOpen === r.id ? ' open' : ''));
      const kind = el('span', 'kind'); setIcon(kind, REF_ICON[r.kind] || 'ref');
      b.append(kind, el('span', 'name', r.name || t('refKinds').text));
      b.title = `${t('refKinds')[r.kind] || r.kind} · ` + (own ? (r.summary || r.note || r.name || '') : `${fromLabel(r.from)} · ${r.name || ''}`);
      b.setAttribute('aria-expanded', String(refOpen === r.id));
      b.onclick = () => { refOpen = refOpen === r.id ? '' : r.id; redraw(); };
      row.append(b);
    };
    refList(scope).forEach((r) => chip(r, true));
    inherited.forEach((r) => chip(r, false));
    const pick = el('input'); pick.type = 'file'; pick.multiple = true; pick.accept = refKit.ACCEPT; pick.hidden = true;
    pick.onchange = () => { const files = [...pick.files].map((f) => fileEntry(f, f.name)); pick.value = ''; addRefFiles(scope, files, redraw); };
    const add = bare ? iconButton('clip', `${t('refs')} ${t('refAdd')}`, null, 'ghost iconBtn refClip') : iconButton('plus', t('refAdd'), null, 'ghost iconBtn refPlus');
    const menu = el('div', 'refAddMenu' + (bare ? ' up' : '')); menu.hidden = true; menu.setAttribute('role', 'menu');
    const field = (kind) => {
      extra.textContent = ''; menu.hidden = true;
      const box = kind === 'link' ? el('input') : el('textarea');
      if (kind === 'link') { box.type = 'url'; box.placeholder = 'https://'; } else box.placeholder = t('refNotePh');
      box.setAttribute('aria-label', kind === 'link' ? t('refAddLink') : t('refAddNote'));
      const done = () => {
        const text = box.value.trim(); if (!text) return;
        if (kind === 'link') {
          if (!/^https?:\/\/\S+$/i.test(text)) { toast(t('refBadLink'), 3000); return; }
          addRef(scope, { id: newRefId(), kind: 'link', name: text.replace(/^https?:\/\/(www\.)?/i, '').slice(0, 60), url: text, note: '', at: Date.now() });
        } else addRef(scope, { id: newRefId(), kind: 'text', name: text.split('\n')[0].slice(0, 40), note: text, url: '', at: Date.now() });
        renderBoardQuiet(); redraw();
      };
      // Enter adds a link; a note takes Ctrl+Enter or leaving the box. Esc drops it.
      box.onkeydown = (e) => {
        if (e.isComposing) return;
        if (e.key === 'Escape') { e.preventDefault(); extra.textContent = ''; }
        else if (e.key === 'Enter' && (kind === 'link' || e.ctrlKey || e.metaKey)) { e.preventDefault(); done(); }
      };
      if (kind === 'text') box.onblur = done;
      extra.append(box); box.focus();
    };
    for (const [kind, label] of [['file', t('refAddFile')], ['link', t('refAddLink')], ['text', t('refAddNote')]]) {
      const b = el('button', '', label); b.setAttribute('role', 'menuitem');
      b.onclick = () => (kind === 'file' ? (menu.hidden = true, pick.click()) : field(kind));
      menu.append(b);
    }
    add.onclick = () => { menu.style.left = add.offsetLeft + 'px'; menu.hidden = !menu.hidden; };
    if (bare) opts.tools.prepend(add, menu, pick); else row.append(add, menu, pick);
    if (!bare && !refList(scope).length && !inherited.length) row.append(el('span', 'refHint', t('refEmpty')));
    if (row.children.length) slot.append(row);
    slot.append(extra);
    const opened = [...refList(scope).map((r) => [r, true]), ...inherited.map((r) => [r, false])].find(([r]) => r.id === refOpen);
    if (opened) {
      const [r, own] = opened, card = el('div', 'refCard');
      if (r.kind === 'link' && /^https?:\/\//i.test(r.url)) { const link = el('a', '', r.url); link.href = r.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; card.append(link); }
      if (r.summary) card.append(el('div', 'refFacts', r.summary));
      const tools = el('div', 'refTools');
      if (r.kind === 'audio' && r.key) { const b = iconButton('play', t('listen'), () => playRef(r, b), 'ghost iconBtn'); tools.append(b); }
      if (own) {
        // The note says what to take from this reference; it is kept as it is typed.
        const note = el('textarea', 'refNote'); note.value = r.note || ''; note.placeholder = r.kind === 'text' ? t('refNotePh') : t('refTakePh'); note.setAttribute('aria-label', t('refTakePh'));
        note.oninput = () => { r.note = note.value; syncRefs(); autosave(); };
        card.append(note);
        tools.append(iconButton('trash', t('refRemove'), () => { dropRef(scope, r); refOpen = ''; renderBoardQuiet(); redraw(); }, 'ghost iconBtn'));
      } else {
        if (r.note) card.append(el('div', 'refFacts', r.note));
        card.append(el('div', 'refFacts', fromLabel(r.from)));
      }
      card.prepend(tools);
      slot.append(card);
    }
    if (bare) return slot; // the whole conversation takes dropped files (see the window's drop)
    slot.ondragover = (e) => { if ([...e.dataTransfer.types].includes('Files')) { e.preventDefault(); e.stopPropagation(); slot.classList.add('over'); } };
    slot.ondragleave = () => slot.classList.remove('over');
    slot.ondrop = (e) => {
      e.preventDefault(); e.stopPropagation(); slot.classList.remove('over');
      const files = [...e.dataTransfer.files].map((f) => fileEntry(f, f.name));
      if (files.length) addRefFiles(scope, files, redraw);
    };
    return slot;
  }
  // The board under the detail view keeps its reference counts without being redrawn on top of it.
  function renderBoardQuiet() { if (!openAsset) renderBoard(); }
  let refScope = null; // the open reference panel takes dropped files instead of the import
  function refDialog(scope) {
    const title = scope.type === 'project' ? t('refsProject') : t('refsOf', scope.type === 'cat' ? tx(scope.c.name) : nm(scope.a));
    openDialog(title); reopen = () => refDialog(scope); refScope = scope;
    dlg.addEventListener('close', () => { if (refScope === scope) refScope = null; if (refAudio) { refAudio.pause(); refAudio = null; } renderBoardQuiet(); }, { once: true });
    dlg.append(el('p', 'note', t('refsHelp')[scope.type]), refSlot(scope));
    if (!dlg.open) dlg.showModal();
  }
  const refCount = (scope) => refList(scope).length;
  const refSpec = (r) => ({ kind: r.kind, name: r.name, ...(r.url ? { url: r.url } : {}), ...(r.note ? { note: r.note } : {}), ...(r.summary ? { facts: r.facts } : {}), ...(r.from && r.from !== 'asset' ? { from: r.from } : {}) });

  /* ---------- import dialog ---------- */
  function catPicker(a, done) {
    const pick = el('select', 'catPick' + (a.guessed ? ' unsure' : ''));
    for (const c of catTree()) pick.append(Object.assign(el('option', '', '\u00a0\u00a0'.repeat(depthOf(c)) + tx(c.name)), { value: c.id }));
    pick.value = a.cat; pick.setAttribute('aria-label', t('category'));
    if (a.guessed) pick.title = t('guessed');
    pick.onchange = () => { a.cat = pick.value; a.guessed = false; delete a.autoCat; pick.classList.remove('unsure'); a.music = kindOf(a.cat) === 'music'; done?.(); };
    return pick;
  }
  function licenseFields(a, after) {
    const field = (key, label) => { const i = el('input', 'licIn'); i.value = a[key] || ''; i.placeholder = label; i.setAttribute('aria-label', label); i.oninput = () => { a[key] = i.value.trim(); autosave(); after?.(); }; return i; };
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
    dlg.append(rulesPart());
    const area = el('textarea'); area.id = 'listIn'; area.placeholder = t('listPlaceholder'); area.setAttribute('aria-label', t('importListHead')); area.style.minHeight = '110px';
    const add = el('button', 'primary', t('addSlots', 0)); add.id = 'addSlots'; add.disabled = true;
    const count = el('span', 'listCount');
    area.oninput = () => { const n = importer.parseList(area.value).length; add.textContent = t('addSlots', n); add.disabled = !n; count.textContent = n ? t('listCount', n) : ''; };
    add.onclick = () => { const list = importer.parseList(area.value); if (!list.length) return; dlg.close(); addSlots(list); };
    const list = section(t('importListHead'), t('importListHelp'), count, add); list.insertBefore(area, list.lastChild);
    dlg.append(list);
    if (!dlg.open) dlg.showModal();
  }
  // An agent that worked on the game knows its file names and folders; its answer sets the id rule, folders and groups.
  const rulesForm = () => JSON.stringify({ id_rule: { pattern: '{kind}_{name}', sep: '_', prefix: { sfx: 'sfx', amb: 'amb', music: 'bgm' } }, folders: { root: 'audio', by: 'category' }, categories: [{ id: '', name: '', kind: 'sfx', parent: '' }], files: [{ path: '', category: '', id: '' }] }, null, 2);
  const rulesPrompt = () => t('rulesPrompt', { form: rulesForm(), cats: catTree().map((c) => `${folderOf(c)}(${c.kind})`).join(', '), files: assets.filter((a) => a.imported && a.file).map((a) => a.file).slice(0, 200).join('\n') || '-' });
  const fileMatch = (path) => assets.find((a) => a.file && (a.file === path || a.file.endsWith('/' + path) || path.endsWith('/' + a.file))) || assets.find((a) => a.file && base(a.file) === base(String(path)));
  function renameAsset(a, id) { for (const d of dynamics) for (const l of d.layers) if (l.asset === a.id) l.asset = id; selected.delete(a.id); a.id = id; }
  function planRules(text) {
    let r;
    try { r = JSON.parse(text.replace(/^\s*```(?:json)?|```\s*$/g, '')); } catch (e) { return [el('p', 'note err', t('notJson', e.message))]; }
    if (!r || typeof r !== 'object' || Array.isArray(r)) return [el('p', 'note err', t('rulesEmpty'))];
    const rule0 = r.id_rule && typeof r.id_rule.pattern === 'string' && /\{name\}/.test(r.id_rule.pattern) ? r.id_rule : null;
    const by = { category: 'cat', kind: 'kind', none: 'flat' }[r.folders?.by];
    const groups = (Array.isArray(r.categories) ? r.categories : []).filter((c) => c && typeof c.id === 'string' && slugOf(c.id).length).map((c) => ({ ...c, id: slugOf(c.id).join('_') }));
    const files = (Array.isArray(r.files) ? r.files : []).filter((f) => f && typeof f.path === 'string').map((f) => ({ ...f, a: fileMatch(f.path) })).filter((f) => f.a);
    if (!rule0 && !by && !r.folders?.root && !groups.length && !files.length) return [el('p', 'note err', t('rulesEmpty'))];
    const out = [], line = (tag, text) => { const x = el('div', 'lineItem'); x.append(el('span', 'tag chg', tag), el('span', 'grow', text)); return x; };
    if (rule0) out.push(line(t('rulesId'), r.id_rule.pattern));
    if (by || r.folders?.root) out.push(line(t('folders'), `${r.folders.root || exportOpts.root || 'audio'}/${by === 'cat' ? '<group>/' : by === 'kind' ? '<sfx|amb|music>/' : ''}<id>`));
    const fresh = groups.filter((c) => !catOf(c.id));
    if (fresh.length) out.push(line(t('tagAdd'), fresh.map((c) => (c.parent ? `${c.parent}/${c.id}` : c.id)).join(', ')));
    if (files.length) out.push(line(t('rulesFilesTag'), t('rulesFiles', files.length)));
    const row = el('div', 'dlgRow'), go = el('button', 'primary', t('applyRules'));
    go.onclick = () => {
      if (rule0) idRule = { ...idRule, pattern: rule0.pattern.trim(), sep: typeof rule0.sep === 'string' && rule0.sep.length <= 3 ? rule0.sep : idRule.sep, prefix: { ...idRule.prefix, ...(rule0.prefix && typeof rule0.prefix === 'object' ? rule0.prefix : {}) } };
      if (by) exportOpts.folders = by;
      if (typeof r.folders?.root === 'string' && r.folders.root.trim()) exportOpts.root = r.folders.root.trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
      for (const c of groups) { const have = catOf(c.id); if (have) { if (c.name) have.name = c.name; if (KINDS.includes(c.kind)) have.kind = c.kind; } else addCat(c.name || c.id, c.kind, c.id); }
      for (const c of groups) { const p = c.parent && slugOf(c.parent).join('_'); if (p && catOf(p) && !under(p, c.id)) catOf(c.id).parent = p; }
      const taken = new Set(assets.map((a) => a.id));
      for (const f of files) {
        const cat = f.category && slugOf(f.category).join('_');
        if (cat && catOf(cat)) moveTo([f.a], cat);
        const id = typeof f.id === 'string' ? f.id.trim() : '';
        if (id && id !== f.a.id && !taken.has(id)) { taken.delete(f.a.id); taken.add(id); renameAsset(f.a, id); }
      }
      // A file the agent named no id for keeps the game's own name when that name already fits the rule.
      for (const a of assets.filter((x) => x.imported && x.file && !files.some((f) => f.a === x && f.id))) {
        const own = stem(a.file);
        if (own !== a.id && idOk(own) && !taken.has(own)) { taken.delete(a.id); taken.add(own); renameAsset(a, own); }
      }
      rulesDraft = ''; dlg.close(); renderBoard(); toast(t('rulesApplied'), 4000);
    };
    row.append(go); out.push(row);
    return out;
  }
  let rulesDraft = '';
  function rulesPart() {
    const s = el('section', 'importPart'), row = el('div', 'dlgRow'), area = el('textarea'), out = el('div');
    row.style.justifyContent = 'flex-start';
    const cp = el('button', '', t('copyRules')); cp.id = 'copyRules'; cp.onclick = () => copy(rulesPrompt(), t('copiedPrompt'));
    area.id = 'rulesIn'; area.placeholder = t('pasteRules'); area.setAttribute('aria-label', t('pasteRules')); area.style.minHeight = '90px'; area.value = rulesDraft;
    const check = () => { rulesDraft = area.value; out.textContent = ''; if (area.value.trim()) out.append(...planRules(area.value)); };
    area.oninput = check;
    row.append(cp); s.append(el('h3', '', t('rulesHead')), el('p', '', t('rulesHelp')), row, area, out); check();
    return s;
  }
  // Without an agent, Jev sorts the imported files on the server: each file picks one of the five usual groups,
  // a special group already in use, or "other" (then a special group or unsorted). The answer replaces the guess
  // unless the user picked a group for that sound first.
  const SPECIAL = { voice: ['Voice', '목소리', 'sfx'], vehicle: ['Vehicles', '탈것', 'sfx'], machine: ['Machines', '장치', 'sfx'], magic: ['Magic', '마법', 'sfx'], item: ['Items', '아이템', 'sfx'], creature: ['Creatures', '생물', 'sfx'], weather: ['Weather', '날씨', 'amb'], cinematic: ['Cinematic', '연출', 'sfx'], horror: ['Horror', '공포', 'sfx'], sport: ['Sports', '스포츠', 'sfx'], unsorted: ['Unsorted', '미분류', 'sfx'] };
  const asking = new Map();
  function askJev(list) {
    if (window.parent === window || !list.length) return;
    const n = `${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
    list.forEach((a) => { a.autoCat = true; });
    asking.set(n, list); setTimeout(() => asking.delete(n), 180000);
    window.parent.postMessage({ type: 'asset:classify', payload: { n, files: list.map((a) => ({ path: a.file, secs: Math.round(heard(a).measure.seconds * 10) / 10 })) } }, '*');
    toast(t('jevSorting', list.length), 0);
  }
  function classified(m) {
    const list = asking.get(m.n);
    if (!list) return;
    asking.delete(m.n);
    if (!m.ok) { list.forEach((a) => { delete a.autoCat; }); toast(t('jevOff'), 3000); return; }
    let moved = 0;
    for (const a of list) {
      const g = m.groups?.[a.file];
      if (!a.autoCat || !g || !assets.includes(a)) continue;
      const cat = catOf(g) ? g : SPECIAL[g] ? addCat({ en: SPECIAL[g][0], ko: SPECIAL[g][1] }, SPECIAL[g][2], g).id : KIND_OF[g] ? fitCat(g) : null;
      delete a.autoCat;
      if (!cat) continue;
      a.guessed = false;
      if (cat === a.cat) continue;
      moved++;
      a.cat = cat; a.music = kindOf(cat) === 'music'; if (kindOf(cat) !== 'sfx') a.loop = true;
      renameAsset(a, makeId(nm(a), cat, new Set(assets.filter((x) => x !== a).map((x) => x.id))));
    }
    renderBoard();
    if (dlg.open && $('rulesIn')) reopen?.();
    toast(t('jevSorted', list.length, moved), 4000);
  }
  addEventListener('message', (e) => { if (e.source === window.parent && e.data?.type === 'asset:classified') classified(e.data); });
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
  // Over the conversation of an open sound, dropped files become its references; anywhere else they are imported.
  const chatUnder = (e) => { const side = openAsset && document.querySelector('.dSide'), r = side?.getBoundingClientRect(); return r && e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom ? side : null; };
  const dragEnd = () => { dragDepth = 0; $('dropZone').hidden = true; document.querySelector('.dSide.over')?.classList.remove('over'); };
  addEventListener('dragenter', (e) => { if (!carriesFiles(e)) return; dragDepth++; $('dropZone').hidden = !!chatUnder(e); });
  addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) dragEnd(); });
  addEventListener('dragover', (e) => {
    if (!carriesFiles(e)) return;
    e.preventDefault();
    const side = chatUnder(e); document.querySelector('.dSide')?.classList.toggle('over', !!side); $('dropZone').hidden = !!side;
  });
  addEventListener('drop', async (e) => {
    if (!carriesFiles(e)) return;
    const toChat = !!chatUnder(e);
    e.preventDefault(); dragEnd();
    const entries = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry?.()).filter(Boolean), out = [];
    if (entries.length) for (const x of entries) await walkEntry(x, out);
    else out.push(...[...e.dataTransfer.files].map((f) => fileEntry(f, f.name)));
    if (refScope && dlg.open) { addRefFiles(refScope, out); return; }
    if (toChat && openAsset) { addRefFiles({ type: 'asset', a: openAsset }, out, redrawChat); return; }
    if (dlg.open) dlg.close();
    intake(out);
  });

  /* ---------- export ---------- */
  let exportOpts = { format: 'wav', rate: 48000, bits: 16, quality: 'high', folders: 'flat', root: 'audio', engine: 'none' };
  const exportPath = (a) => {
    const c = catOf(a.cat), dir = exportOpts.folders === 'cat' ? (c ? folderOf(c) : a.cat) : exportOpts.folders === 'kind' ? kindOf(a.cat) : '';
    return [exportOpts.root || 'audio', dir, `${a.id}.${exportOpts.format}`].filter(Boolean).join('/');
  };
  // Sounds are made at the synth's rate; the chosen rate comes from the browser's own resampler.
  async function resample(data, from, to) {
    if (from === to) return data;
    const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(data.length * to / from)), to), buf = off.createBuffer(1, data.length, from);
    buf.copyToChannel(data, 0);
    const src = off.createBufferSource(); src.buffer = buf; src.connect(off.destination); src.start();
    return (await off.startRendering()).getChannelData(0);
  }
  // OGG and MP3 come from wasm-media-encoders (LAME and libvorbis built to WebAssembly), loaded the first time they are asked for.
  let encLib = null;
  const loadEncoders = () => (encLib ||= new Promise((ok, no) => {
    const s = document.createElement('script'); s.src = 'vendor/WasmMediaEncoder.min.js';
    s.onload = () => ok(window.WasmMediaEncoder); s.onerror = () => { encLib = null; no(new Error('encoder script')); }; document.head.append(s);
  }));
  const wasmBytes = {};
  async function encode(data, rate) {
    const fmt = exportOpts.format;
    if (fmt === 'wav') return importer.encodeWav(data, rate, exportOpts.bits);
    const lib = await loadEncoders(), mime = fmt === 'mp3' ? 'audio/mpeg' : 'audio/ogg';
    wasmBytes[fmt] ||= await (await fetch(`vendor/${fmt}.wasm`)).arrayBuffer();
    const enc = await lib.createEncoder(mime, wasmBytes[fmt].slice(0));
    const q = { high: [2, 6], mid: [4, 4], low: [6, 2] }[exportOpts.quality] || [2, 6];
    enc.configure({ channels: 1, sampleRate: rate, vbrQuality: fmt === 'mp3' ? q[0] : q[1] });
    const parts = [], take = (u) => { if (u.length) parts.push(u.slice()); };
    take(enc.encode([data])); take(enc.finalize());
    const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0)); let at = 0;
    for (const p of parts) { out.set(p, at); at += p.length; }
    return out;
  }
  // Spec, credits and lint for every approved sound, the audio of `list`, and the Godot files when they are asked for.
  async function bundleFiles(list) {
    const going = assets.filter((a) => a.status === 'approved' && a.versions.length), utf8 = (s) => new TextEncoder().encode(s);
    const spec = {
      game: tx(game), platform, style: tx(brief) || '',
      references: projectRefs.map(refSpec),
      categories: cats.map((c) => ({ id: c.id, name: tx(c.name), kind: c.kind, parent: c.parent, folder: folderOf(c), color: c.hue.startsWith('#') ? c.hue : undefined, ...(c.refs?.length ? { references: c.refs.map(refSpec) } : {}) })),
      id_rule: idRule, export: exportOpts,
      dynamics: dynamics.map(dynToSpec),
      assets: assets.map((a) => {
        const v = a.versions.length ? heard(a) : null;
        return { id: a.id, name: nm(a), category: a.cat, length: v ? Math.round(v.measure.seconds * 100) / 100 : a.length ?? null, loop: !!a.loop, when: a.when || '', description: a.description || '',
          file: going.includes(a) ? exportPath(a) : null, status: a.status === 'approved' ? 'approved' : a.versions.length ? 'draft' : 'pending',
          ...(ownRefs(a).length ? { references: ownRefs(a).map(refSpec) } : {}),
          origin: a.imported ? 'imported' : 'made', ...(a.imported ? { source_file: a.file || '', license: a.license || '', holder: a.holder || '' } : {}), ...(a.prompt ? { prompt: a.prompt } : {}) };
      }),
      questions: [],
    };
    const credits = `# ${tx(game)}\n\n${licenseText().split('\n').slice(2).join('\n')}`;
    const lint = going.map((a) => ({ id: a.id, issues: issues(a).map((r) => r.id) }));
    const files = [{ path: SPEC, bytes: utf8(JSON.stringify(spec, null, 2)) }, { path: 'CREDITS.md', bytes: utf8(credits) }, { path: 'lint-report.json', bytes: utf8(JSON.stringify(lint, null, 2)) }];
    let n = 0;
    for (const a of list) {
      if (list.length > 1) { toast(t('encoding', ++n, list.length), 0); await breathe(); }
      const s = heard(a).sound;
      files.push({ path: exportPath(a), bytes: await encode(await resample(s.mix, s.rate, exportOpts.rate), exportOpts.rate) });
    }
    if (exportOpts.engine === 'godot') {
      if (!window.godotExport) throw new Error('godot.js');
      const project = { game: tx(game), assets: going.map((a) => ({ id: a.id, name: nm(a), category: a.cat, loop: !!a.loop, file: exportPath(a), seconds: heard(a).measure.seconds })), dynamics: dynamics.map(dynToSpec) };
      for (const f of window.godotExport.build(project)) files.push({ path: f.path, bytes: utf8(f.text) });
    }
    return files;
  }
  async function exportBundle() {
    const going = assets.filter((a) => a.status === 'approved' && a.versions.length), files = await bundleFiles(going);
    const link = el('a'); link.href = URL.createObjectURL(importer.zip(files));
    link.download = `${(tx(game) || 'game').replace(/[\\/:*?"<>|\s]+/g, '-')}-audio.zip`;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    toast(t('exported', going.length));
  }

  /* ---------- game folder: approved sounds written straight into the game (File System Access, Chrome and Edge) ---------- */
  // The folder is linked once from the export dialog and kept in the board's IndexedDB. Approving writes the sound at
  // its export path and rewrites the spec, CREDITS and lint report beside it; nothing is ever deleted there.
  let gameDir = null, folderAsk = null, folderTimer = 0, folderChain = Promise.resolve();
  const folderWaiting = new Set();
  async function keepDir(dir) {
    try { const q = (await idb()).transaction('board', 'readwrite'); if (dir) q.objectStore('board').put(dir, 'gameDir'); else q.objectStore('board').delete('gameDir'); await done(q); }
    catch { /* the link lasts this visit only */ }
  }
  function toFolder(list) {
    if (!gameDir || !list.length) return;
    list.forEach((a) => folderWaiting.add(a));
    // Asked during the click that approved: after a reload the browser lets go of the folder and only asks again inside one.
    folderAsk ||= gameDir.requestPermission({ mode: 'readwrite' }).catch(() => 'denied');
    clearTimeout(folderTimer); folderTimer = setTimeout(() => { folderChain = folderChain.then(flushFolder); }, 200);
  }
  async function flushFolder() {
    const list = [...folderWaiting].filter((a) => a.status === 'approved' && a.versions.length && assets.includes(a)), ask = folderAsk;
    folderWaiting.clear(); folderAsk = null;
    if (!gameDir || !list.length) return;
    try {
      if ((await ask) !== 'granted') throw new Error(t('folderDenied'));
      await writeFiles(gameDir, await bundleFiles(list));
      if (list.length > 1) $('toast').hidden = true;
    } catch (e) { toast(t('folderFailed', e.message || e), 6000); }
  }
  async function writeFiles(dir, files) {
    for (const f of files) {
      const parts = f.path.split('/'), name = parts.pop();
      let d = dir; for (const part of parts) d = await d.getDirectoryHandle(part, { create: true });
      const w = await (await d.getFileHandle(name, { create: true })).createWritable();
      await w.write(f.bytes); await w.close();
    }
  }
  // What the folder already has, read like an import: the spec at its top and sound files below, skipping hidden
  // folders (.godot, .git) and node_modules.
  async function readFolder(dir, path = '', out = [], budget = { n: 5000 }) {
    for await (const [name, h] of dir.entries()) {
      if (--budget.n < 0) break;
      const at = path ? `${path}/${name}` : name;
      if (h.kind === 'directory') { if (!/^\.|^node_modules$/.test(name)) await readFolder(h, at, out, budget); continue; }
      if (AUDIO.test(name) || (!path && name === SPEC)) out.push(fileEntry(await h.getFile(), at));
    }
    return out;
  }
  async function linkFolder() {
    let dir;
    try { dir = await window.showDirectoryPicker({ id: 'olmuse-game', mode: 'readwrite' }); }
    catch (e) { if (e?.name !== 'AbortError') toast(t('folderFailed', e.message || e), 6000); return; }
    gameDir = dir; keepDir(dir);
    // A board still on the stand-in samples starts from what the folder has; a board with work in it fills the folder.
    if (demo) {
      const found = await readFolder(dir).catch(() => []);
      if (found.length) { if (dlg.open) dlg.close(); await intake(found); } else exportDialog();
      return;
    }
    exportDialog();
    toFolder(assets.filter((a) => a.status === 'approved'));
  }

  /* ---------- dynamic sounds: layers of existing sounds driven by game parameters ---------- */
  let dynamics = [];
  const DB_FLOOR = -80;
  const dynId = () => { const taken = new Set(dynamics.map((d) => d.id)); let k = dynamics.length + 1; while (taken.has(`dyn_${k}`)) k++; return `dyn_${k}`; };
  // A layer is silent below on[0] and full from on[1] (reversed when on[0] > on[1]); its curve in dB is what engines get.
  const layerLevel = (l, d) => {
    const p = d.params.find((x) => x.id === l.param);
    if (!p) return 1;
    const [a, b] = l.on || [0, 1], v = p.value ?? p.default ?? 0;
    if (a === b) return v >= a ? 1 : 0;
    return Math.max(0, Math.min(1, (v - a) / (b - a)));
  };
  const curveOf = (l) => {
    const [a, b] = l.on || [0, 1];
    return [0, 0.25, 0.5, 0.75, 1].map((k) => [Math.round((a + (b - a) * k) * 1000) / 1000, k ? Math.round(20 * Math.log10(k) * 10) / 10 : DB_FLOOR]).sort((x, y) => x[0] - y[0]);
  };
  const dynToSpec = (d) => ({
    id: d.id, name: d.name, type: d.type, params: d.params.map(({ id, name, min, max, default: def }) => ({ id, name, min, max, default: def })),
    ...(d.type === 'music' ? { bpm: d.bpm, beats_per_bar: d.beats || 4 } : {}),
    layers: d.layers.filter((l) => byId(l.asset)).map((l) => ({ asset: l.asset, role: l.role, param: l.param || null, on: l.on, curve: l.param ? curveOf(l) : [[0, 0], [1, 0]], ...(l.role === 'scatter' ? { scatter: l.scatter } : {}) })),
  });
  const dynFromSpec = (x) => ({
    id: x.id, name: x.name || x.id, type: x.type === 'music' ? 'music' : 'ambience', bpm: x.bpm || 100, beats: x.beats_per_bar || 4,
    params: (x.params || []).map((p) => ({ ...p, value: p.default ?? 0 })),
    layers: (x.layers || []).map((l) => ({ asset: l.asset, role: l.role || 'bed', param: l.param || '', on: l.on || [0, 1], scatter: l.scatter || { min_gap: 2, max_gap: 8, pitch: [0.9, 1.1], pan: [-0.8, 0.8] } })),
  });
  function dynSection() {
    const box = el('div', 'group dynGroup'), h = el('h2');
    h.append(el('i'), t('dynHead'), el('span', '', String(dynamics.length)));
    h.append(iconButton('plus', t('addDyn'), newDynamic, 'ghost iconBtn addSound'));
    const grid = el('div', 'grid');
    for (const d of dynamics) {
      const card = el('button', 'dynCard'); card.onclick = () => dynDialog(d);
      card.append(el('span', 'name', d.name), el('span', 'sub', `${t('dynTypes')[d.type]} · ${t('dynLayers', d.layers.length)}`));
      if (dynPlayer?.d === d) card.classList.add('playing');
      grid.append(card);
    }
    box.append(h); if (dynamics.length) box.append(grid);
    return box;
  }
  function newDynamic() {
    const d = { id: dynId(), name: t('newDyn'), type: 'ambience', bpm: 100, beats: 4, params: [{ id: 'intensity', name: t('intensity'), min: 0, max: 1, default: 0.5, value: 0.5 }], layers: [] };
    const beds = assets.filter((a) => a.versions.length && a.loop && kindOf(a.cat) === 'amb').slice(0, 2);
    beds.forEach((a, i) => d.layers.push({ asset: a.id, role: 'bed', param: i ? 'intensity' : '', on: [0.3, 0.8], scatter: { min_gap: 2, max_gap: 8, pitch: [0.9, 1.1], pan: [-0.8, 0.8] } }));
    dynamics.push(d); renderBoard(); dynDialog(d);
  }
  let dynPlayer = null;
  function dynStop() {
    if (!dynPlayer) return;
    clearTimeout(dynPlayer.timer); dynPlayer.timers.forEach(clearTimeout);
    dynPlayer.nodes.forEach((n) => { try { n.stop(); } catch { /* over */ } });
    dynPlayer = null;
  }
  const bufferOf = (a) => { const s = heard(a).sound, b = ctx.createBuffer(1, s.mix.length, s.rate); b.copyToChannel(s.mix, 0); return b; };
  function dynStart(d) {
    audio(); stopSound(); dynStop();
    const at = ctx.currentTime + 0.05, p = { d, nodes: [], gains: [], timers: [] };
    for (const l of d.layers) {
      const a = byId(l.asset); if (!a?.versions.length) continue;
      const g = ctx.createGain(); g.gain.value = layerLevel(l, d); g.connect(master); p.gains.push([l, g]);
      if (l.role === 'scatter') {
        const fire = () => {
          if (dynPlayer !== p) return;
          const src = ctx.createBufferSource(), pan = ctx.createStereoPanner(), s = l.scatter, r = (lo, hi) => lo + Math.random() * (hi - lo);
          src.buffer = bufferOf(a); src.playbackRate.value = r(...(s.pitch || [1, 1])); pan.pan.value = r(...(s.pan || [0, 0]));
          src.connect(pan); pan.connect(g); src.start(); p.nodes.push(src);
          p.timers.push(setTimeout(fire, r(s.min_gap, s.max_gap) * 1000));
        };
        p.timers.push(setTimeout(fire, Math.random() * 1000 * (l.scatter.min_gap || 1)));
      } else {
        const src = ctx.createBufferSource(); src.buffer = bufferOf(a); src.loop = true; src.connect(g); src.start(at); p.nodes.push(src);
      }
    }
    dynPlayer = p;
  }
  const dynLevels = () => dynPlayer?.gains.forEach(([l, g]) => g.gain.setTargetAtTime(layerLevel(l, dynPlayer.d), ctx.currentTime, 0.15));
  function dynDialog(d) {
    openDialog(t('dynHead')); reopen = () => dynDialog(d);
    dlg.onclose = () => { dynStop(); dlg.onclose = null; renderBoard(); };
    // The board card follows every change, so nothing waits on the dialog's close event.
    const redraw = () => { const top = dlg.scrollTop; dlg.textContent = ''; build(); dlg.scrollTop = top; renderBoard(); };
    const row = (label, ...kids) => { const r = el('label', 'lineItem'); r.append(el('span', 'grow', label), ...kids); dlg.append(r); return r; };
    const input = (value, set, type = 'text', width) => { const i = el('input'); i.type = type; i.value = value; if (type === 'number') i.step = 'any'; if (width) i.style.width = width; i.oninput = () => { set(type === 'number' ? +i.value : i.value); dynLevels(); autosave(); }; return i; };
    const select = (value, choices, set) => { const s = el('select'); choices.forEach(([v, l]) => s.add(new Option(l, v))); s.value = value; s.onchange = () => { set(s.value); dynLevels(); autosave(); }; return s; };
    function build() {
      dlg.append(iconButton('close', t('close'), () => { dynStop(); dlg.close(); renderBoard(); }, 'ghost iconBtn dlgClose'), el('h2', '', t('dynHead')));
      const playing = dynPlayer?.d === d, play = el('button', 'primary', playing ? t('stop') : t('play'));
      play.onclick = () => { if (dynPlayer?.d === d) dynStop(); else dynStart(d); redraw(); };
      const top = el('div', 'dlgRow'); top.style.justifyContent = 'flex-start'; top.append(play); dlg.append(top);
      row(t('nameLabel'), input(d.name, (v) => { d.name = v; renderBoard(); }));
      row('id', input(d.id, (v) => { d.id = slugOf(v).join('_') || d.id; }, 'text', '160px'));
      row(t('dynType'), select(d.type, Object.entries(t('dynTypes')), (v) => { d.type = v; d.layers.forEach((l) => { if (v === 'music') l.role = 'stem'; else if (l.role === 'stem') l.role = 'bed'; }); redraw(); }));
      if (d.type === 'music') { row('BPM', input(d.bpm, (v) => { d.bpm = v; }, 'number', '90px')); row(t('beatsPerBar'), input(d.beats || 4, (v) => { d.beats = v; }, 'number', '90px')); }
      dlg.append(el('h3', '', t('params')));
      for (const p of d.params) {
        const slider = el('input'); slider.type = 'range'; slider.min = p.min; slider.max = p.max; slider.step = (p.max - p.min) / 100; slider.value = p.value ?? p.default;
        slider.setAttribute('aria-label', p.name); slider.oninput = () => { p.value = +slider.value; dynLevels(); };
        const name = input(p.name, (v) => { p.name = v; }, 'text', '120px'), def = input(p.default, (v) => { p.default = v; }, 'number', '70px'); def.title = t('paramDefault');
        const del = iconButton('close', t('deleteItem'), () => { d.params.splice(d.params.indexOf(p), 1); d.layers.forEach((l) => { if (l.param === p.id) l.param = ''; }); redraw(); }, 'ghost iconBtn');
        const r = el('div', 'lineItem'); r.append(el('code', '', p.id), name, slider, def, del); dlg.append(r);
      }
      const addP = el('button', 'ghost', '+ ' + t('addParam'));
      addP.onclick = () => { const taken = new Set(d.params.map((p) => p.id)); let k = d.params.length + 1; while (taken.has(`param_${k}`)) k++; d.params.push({ id: `param_${k}`, name: `${t('param')} ${k}`, min: 0, max: 1, default: 0, value: 0 }); redraw(); };
      dlg.append(addP, el('h3', '', t('layersHead')));
      const usable = assets.filter((a) => a.versions.length);
      if (!usable.length) dlg.append(el('p', 'note', t('dynNoSounds')));
      const roles = Object.entries(t('roles')).filter(([r]) => (d.type === 'music' ? r === 'stem' : r !== 'stem'));
      for (const l of d.layers) {
        const r = el('div', 'lineItem dynLayer');
        const pick = select(l.asset, usable.map((a) => [a.id, nm(a)]), (v) => { l.asset = v; if (dynPlayer?.d === d) dynStart(d); });
        const role = select(l.role, roles, (v) => { l.role = v; if (dynPlayer?.d === d) dynStart(d); redraw(); });
        const param = select(l.param || '', [['', t('always')], ...d.params.map((p) => [p.id, p.name])], (v) => { l.param = v; redraw(); });
        const del = iconButton('close', t('deleteItem'), () => { d.layers.splice(d.layers.indexOf(l), 1); if (dynPlayer?.d === d) dynStart(d); redraw(); }, 'ghost iconBtn');
        r.append(pick, role, param);
        if (l.param) { const a = input(l.on[0], (v) => { l.on[0] = v; }, 'number', '64px'), b = input(l.on[1], (v) => { l.on[1] = v; }, 'number', '64px'); a.title = t('fadeFrom'); b.title = t('fadeTo'); r.append(el('span', 'tag', t('onRange')), a, b); }
        if (l.role === 'scatter') { const a = input(l.scatter.min_gap, (v) => { l.scatter.min_gap = v; }, 'number', '56px'), b = input(l.scatter.max_gap, (v) => { l.scatter.max_gap = v; }, 'number', '56px'); r.append(el('span', 'tag', t('gap')), a, b); }
        r.append(del); dlg.append(r);
      }
      const addL = el('button', 'ghost', '+ ' + t('addLayer')); addL.disabled = !usable.length;
      addL.onclick = () => { const a = usable[0]; d.layers.push({ asset: a.id, role: d.type === 'music' ? 'stem' : a.loop ? 'bed' : 'scatter', param: d.params[0]?.id || '', on: [0, 1], scatter: { min_gap: 2, max_gap: 8, pitch: [0.9, 1.1], pan: [-0.8, 0.8] } }); redraw(); };
      const foot = el('div', 'dlgRow'), del = el('button', 'ghost', t('deleteItem'));
      del.onclick = () => { if (!confirm(t('confirmDelete', 1))) return; dynStop(); dynamics.splice(dynamics.indexOf(d), 1); dlg.close(); renderBoard(); };
      foot.append(del); dlg.append(addL, el('p', 'note', t('dynHelp')), foot);
    }
    build();
    if (!dlg.open) dlg.showModal();
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
      v: 1, game, brief, platform, demo, stage, loud: [...rule('loud').range], cats, idRule, exportOpts, projectRefs, agentLog: agentLog.slice(-30),
      trash: trash.map((a) => { const { versions, drafts: options, source, progress, ...rest } = a; return { ...rest, key: source ? keyOf(a) : a.key, status: a.status === 'working' || a.status === 'review' ? (versions.length ? 'draft' : 'pending') : a.status, versions: versions.map(recipe), drafts: [], pick: -1, hasSource: !!source }; }),
      dynamics: dynamics.map((d) => ({ ...d, params: d.params.map((p) => ({ ...p })) })),
      assets: assets.map((a) => {
        const { versions, drafts: options, source, progress, ...rest } = a;
        // Work that was still running comes back as it was before the request; it can be asked again.
        const status = a.status === 'working' ? (versions.length ? 'draft' : 'pending') : a.status;
        return { ...rest, key: source ? keyOf(a) : a.key, status, versions: versions.map(recipe), drafts: status === 'review' ? options.map(recipe) : [], pick: status === 'review' ? a.pick : -1, hasSource: !!source };
      }),
    };
  }
  async function write() {
    syncRefs();
    const data = snapshot(), d = await idb(), keep = new Set([...assets, ...trash].filter((a) => a.source).map(keyOf));
    const q = d.transaction(['board', 'audio'], 'readwrite');
    q.objectStore('board').put(data, 'board');
    for (const a of [...assets, ...trash]) if (a.source && !savedAudio.has(a.key)) q.objectStore('audio').put(new Blob([a.source]), a.key);
    for (const k of savedAudio) if (!keep.has(k)) q.objectStore('audio').delete(k);
    // Reference files share the store under ref: keys; one dropped from every list is deleted with the next save.
    const refsKept = refKeys();
    for (const k of refsKept) if (!savedRefs.has(k) && refBlobs.has(k)) q.objectStore('audio').put(new Blob([refBlobs.get(k)]), k);
    for (const k of savedRefs) if (!refsKept.has(k)) q.objectStore('audio').delete(k);
    await done(q);
    savedAudio.clear(); keep.forEach((k) => savedAudio.add(k));
    savedRefs.clear(); refsKept.forEach((k) => savedRefs.add(k));
    for (const k of [...refBlobs.keys()]) if (!refsKept.has(k)) refBlobs.delete(k);
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
      gameDir = (await asked(q.objectStore('board').get('gameDir'))) || null;
      const keys = await asked(q.objectStore('audio').getAllKeys()), values = await asked(q.objectStore('audio').getAll());
      keys.forEach((k, i) => blobs.set(k, values[i]));
    } catch { return false; }
    if (!data || !Array.isArray(data.assets)) return false;
    ({ game, brief, platform, demo, stage } = data);
    if (Array.isArray(data.loud)) rule('loud').range = data.loud;
    if (Array.isArray(data.cats) && data.cats.length) cats = data.cats;
    if (data.idRule) idRule = data.idRule;
    if (data.exportOpts) exportOpts = { ...exportOpts, ...data.exportOpts };
    projectRefs = Array.isArray(data.projectRefs) ? data.projectRefs : [];
    agentLog = Array.isArray(data.agentLog) ? data.agentLog : [];
    for (const [k, blob] of blobs) if (String(k).startsWith('ref:')) { try { refBlobs.set(k, new Uint8Array(await blob.arrayBuffer())); savedRefs.add(k); } catch { /* unreadable blob */ } }
    if (Array.isArray(data.dynamics)) dynamics = data.dynamics;
    assets.length = 0; trash = [];
    for (const x of [...data.assets, ...(data.trash || []).map((y) => ({ ...y, inTrash: true }))]) {
      const { hasSource, ...a } = x;
      a.progress = 0;
      if (hasSource) {
        const blob = blobs.get(a.key);
        let source = null;
        try { source = blob && new Float32Array(await blob.arrayBuffer()); } catch { /* unreadable blob */ }
        if (source) { a.source = source; savedAudio.add(a.key); }
        else Object.assign(a, { versions: [], drafts: [], pick: -1, current: 0, status: 'pending' }); // the browser dropped the audio
      }
      if (a.inTrash) { delete a.inTrash; trash.push(a); } else assets.push(a);
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
    if (e.data?.type === 'asset:hide') { queue = null; stopSound(); dynStop(); saveNow(); }
  });
  function setLang(next) {
    if (!LANGS.includes(next)) return;
    lang = next; applyStatic();
    $('draftSlot').replaceChildren(draftPicker());
    if (openAsset) renderDetail(); else renderBoard(); // the detail keeps a typed request across the redraw
    markPlaying();
    if (dlg.open && reopen) { const again = reopen; dlg.close(); again(); }
  }
  addEventListener('message', (e) => { if (e.data?.type === 'asset:lang') setLang(e.data.lang); });

  /* ---------- start ---------- */
  applyStatic();
  setIcon($('backBtn'), 'music'); setIcon($('send'), 'send'); setIcon($('playAll'), 'play'); setIcon($('exportBtn'), 'download'); setIcon($('menuBtn'), 'menu'); setIcon($('boardBack'), 'back'); setIcon($('prevAsset'), 'prev'); setIcon($('nextAsset'), 'next');
  document.querySelectorAll('[data-icon]').forEach((s) => setIcon(s, s.dataset.icon));
  $('importBtn').querySelector('.importIco').innerHTML = `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS.upload}</svg>`; $('importBtn').onclick = () => importDialog();
  $('exportBtn').onclick = exportDialog;
  $('boardBack').onclick = $('gameTitle').onclick = () => { if (openAsset) closeDetail(); };
  $('prevAsset').onclick = () => step(-1); $('nextAsset').onclick = () => step(1);
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
