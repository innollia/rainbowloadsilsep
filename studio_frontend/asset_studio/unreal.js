// Approved sounds and dynamic sounds -> files for an Unreal Engine 5 project (content-only plugin, Python importer, README).
// No DOM here. window.unrealExport.build(project) returns [{ path, text }]; paths are relative to the folder that holds
// the .uproject. The .uasset files are made inside Unreal by the bundled Python importer (unreal_py.js).
// All numbers are worked out here so the importer only wires a graph from them (docs/ASSET_UNREAL_SPEC.md C).
(() => {
  const PLUGIN = 'Plugins/OlmuseAudio';
  // Engine-independent files (spec, credits, lint report, sound files, README) go in this folder beside the
  // .uproject, never at the project top: app.js puts its own files under ROOT when the engine is Unreal.
  const ROOT = 'OlmuseAudio/';
  const MAX_LAYERS = 8;
  const NAME_MAX = 60;

  /* ---------- names (spec A3) ---------- */
  const slug = (s) => String(s || '').replace(/[^A-Za-z0-9_]+/g, '_').replace(/^_+|_+$/g, '') || 'x';
  // FNV-1a 32-bit over the UTF-8 bytes, 8 lowercase hex digits.
  function fnv(s) {
    let h = 0x811c9dc5;
    for (const b of new TextEncoder().encode(String(s))) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; }
    return h.toString(16).padStart(8, '0');
  }
  // One namer per scope (sounds, dynamics, the inputs of one dynamic): names never repeat, ignoring case.
  function namer(keep) {
    const taken = new Set();
    return (id) => {
      const s = slug(id), tag = fnv(id).slice(0, 6);
      let n = keep(id, s) && !taken.has(s.toLowerCase()) ? s : `${s}_${tag}`;
      if (n.length > NAME_MAX) n = `${s.slice(0, NAME_MAX - 7)}_${tag}`;
      for (let k = 2; taken.has(n.toLowerCase()); k++) n = `${n.replace(/_\d+$/, '')}_${k}`;
      taken.add(n.toLowerCase());
      return n;
    };
  }
  const soundNamer = () => namer((id, s) => s === String(id));
  const inputNamer = () => namer((id) => /^[A-Za-z_][A-Za-z0-9_]*$/.test(String(id)));

  /* ---------- numbers ---------- */
  const fin = (v, d) => (Number.isFinite(+v) && v !== null && v !== '' ? +v : d);
  const r6 = (x) => { const v = +(+x).toFixed(6); return Object.is(v, -0) ? 0 : v; };
  const range = (r, a, b) => (Array.isArray(r) && r.length >= 2 && Number.isFinite(+r[0]) && Number.isFinite(+r[1]) ? [+r[0], +r[1]] : [a, b]);

  // Layer level = clamp(p * scale + offset, 0, 1) * volume, the preview's linear shape (spec C).
  function levelLine(on) {
    let [a, b] = range(on, 0, 1);
    if (a === b) a = b - 0.0001; // a step: the preview is full from on[0] on
    const scale = 1 / (b - a);
    return { scale: r6(scale), offset: r6(-a * scale) };
  }

  function scatterOf(sc) {
    sc = sc || {};
    const g0 = Math.max(0.05, fin(sc.min_gap, 2));
    const g1 = Math.max(g0, fin(sc.max_gap, 8));
    const [p0, p1] = range(sc.pitch, 1, 1).map((p) => (p > 0 ? p : 1));
    const [n0, n1] = range(sc.pan, 0, 0);
    const semi = (p) => r6(12 * Math.log2(p));
    return {
      min_gap: r6(g0), max_gap: r6(g1),
      semitones: [semi(Math.min(p0, p1)), semi(Math.max(p0, p1))],
      pan: [r6(Math.max(-1, Math.min(n0, n1))), r6(Math.min(1, Math.max(n0, n1)))],
    };
  }

  // Key-sorted JSON, the text the dynamic's hash is taken over.
  const sorted = (v) => (Array.isArray(v) ? v.map(sorted) : v && typeof v === 'object'
    ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sorted(v[k])])) : v);

  /* ---------- olmuse_build.json ---------- */
  function data(project) {
    const nameSound = soundNamer();
    const sounds = [], byId = new Map();
    for (const a of project.assets || []) {
      if (!a || !a.id || !a.file || byId.has(a.id)) continue;
      const s = { id: String(a.id), name: String(a.name || a.id), file: ROOT + String(a.file).replace(/\\/g, '/').replace(/^\.?\/+/, ''), asset: nameSound(a.id), loop: !!a.loop };
      sounds.push(s); byId.set(s.id, s);
    }
    const nameDyn = soundNamer(), dynamics = [], dropped = [];
    for (const d of project.dynamics || []) {
      if (!d || !d.id) { dropped.push({ name: String((d && d.name) || ''), why: 'no_id' }); continue; }
      const music = d.type === 'music';
      const nameInput = inputNamer();
      const params = [], droppedParams = [];
      for (const p of d.params || []) {
        if (!p || !p.id) { droppedParams.push(String((p && p.name) || '')); continue; }
        params.push({ id: String(p.id), input: nameInput(p.id), name: String(p.name || p.id), min: r6(fin(p.min, 0)), max: r6(fin(p.max, 1)), default: r6(fin(p.default, 0)) });
      }
      const bpm = fin(d.bpm, 0) > 0 ? +d.bpm : 120;
      const beats = Math.max(1, Math.round(fin(d.beats_per_bar, 4)));
      const layers = [], skipped = [];
      for (const l of d.layers || []) {
        const sound = l && l.asset != null ? String(l.asset) : '';
        if (!byId.has(sound)) { skipped.push({ sound, why: 'not_approved' }); continue; }
        if (layers.length >= MAX_LAYERS) { skipped.push({ sound, why: 'too_many_layers' }); continue; }
        const role = l.role === 'scatter' ? 'scatter' : (l.role === 'stem' ? 'stem' : 'bed');
        const param = l.param && params.some((p) => p.id === l.param) ? String(l.param) : null;
        const line = param ? levelLine(l.on) : { scale: 0, offset: 1 };
        const layer = { sound, role, param, scale: line.scale, offset: line.offset, volume: r6(Math.max(0, fin(l.volume, 1))) };
        if (role === 'scatter') layer.scatter = scatterOf(l.scatter);
        layers.push(layer);
      }
      const dyn = {
        id: String(d.id), name: String(d.name || d.id), asset: `MS_${nameDyn(d.id)}`, type: music ? 'music' : 'ambience',
        params, fade_seconds: r6(music ? 60 / bpm : 0.8), bar_seconds: music ? r6(beats * 60 / bpm) : null,
        layers, skipped,
      };
      if (droppedParams.length) dyn.dropped_params = droppedParams;
      dyn.hash = fnv(JSON.stringify(sorted(dyn)));
      dynamics.push(dyn);
    }
    return { olmuse_unreal: 1, game: String(project.game || ''), tested_engine: '5.8', content_root: '/Game/Olmuse', sounds, dynamics, ...(dropped.length ? { dropped } : {}) };
  }

  /* ---------- plugin descriptor (spec A2) ---------- */
  const UPLUGIN = {
    FileVersion: 3, Version: 1, VersionName: '1.0', FriendlyName: 'Olmuse Audio',
    Description: 'Sounds made with Olmuse. Content only, no code modules.', Category: 'Audio', CreatedBy: 'Olmuse',
    CanContainContent: true, IsBetaVersion: false, Installed: false,
    // Python only in the editor: a packaged game does not take PythonScriptPlugin along.
    Plugins: [{ Name: 'PythonScriptPlugin', Enabled: true, TargetAllowList: ['Editor'] }, { Name: 'Metasound', Enabled: true }],
  };

  /* ---------- README (spec H) ---------- */
  const WHY_KO = { not_approved: '승인되지 않은 소리', too_many_layers: `레이어 ${MAX_LAYERS}개 초과` };
  const WHY_EN = { not_approved: 'sound not approved', too_many_layers: `more than ${MAX_LAYERS} layers` };
  const cell = (s) => String(s).replace(/\|/g, '\\|').replace(/\r?\n/g, ' ');

  function readme(b) {
    const dyns = b.dynamics;
    const rows = (ko) => dyns.map((d) => {
      const ps = d.params.map((p) => `\`${p.input}\` (${cell(p.name)}, ${p.min}~${p.max}, ${ko ? '시작' : 'start'} ${p.default})`).join('<br>') || '-';
      const sk = d.skipped.map((s) => `\`${cell(s.sound || '?')}\`: ${(ko ? WHY_KO : WHY_EN)[s.why]}`).join('<br>') || '-';
      const type = d.type === 'music' ? (ko ? '음악' : 'music') : (ko ? '환경음' : 'ambience');
      return `| \`${d.asset}\` | ${cell(d.name)} | ${type} | ${ps} | ${d.layers.length} | ${sk} |`;
    }).join('\n');
    const table = (ko) => (dyns.length
      ? `| ${ko ? '에셋 이름 | 표시 이름 | 종류 | 파라미터 (Blueprint에서 쓸 이름, 표시 이름, 범위, 시작 값) | 레이어 수 | 건너뛴 레이어' : 'Asset | Display name | Type | Parameters (name to use in Blueprint, display name, range, start value) | Layers | Skipped layers'} |\n|---|---|---|---|---|---|\n${rows(ko)}`
      : (ko ? '동적 소리가 없습니다. 일반 소리만 가져옵니다.' : 'No dynamic sounds. Only the sounds are imported.'));
    const sounds = b.sounds.map((s) => `| \`${s.asset}\` | ${cell(s.name)} | \`${cell(s.file)}\` |`).join('\n');
    const soundTable = (ko) => (b.sounds.length ? `| ${ko ? '에셋 이름 | 표시 이름 | 파일' : 'Asset | Display name | File'} |\n|---|---|---|\n${sounds}` : (ko ? '승인한 소리가 없습니다.' : 'No approved sounds.'));
    const lost = [...(b.dropped || []).map((x) => x.name || '?'), ...dyns.flatMap((d) => (d.dropped_params || []).map((n) => `${d.asset}: ${n || '?'}`))];
    const lostLine = (ko) => (lost.length ? `\n${ko ? 'id가 없어 내보내지 않은 동적 소리·파라미터' : 'Left out because they have no id'}: ${lost.map((n) => `\`${cell(n)}\``).join(', ')}\n` : '');
    const d0 = dyns[0], p0 = d0 && d0.params[0];
    const example = (ko) => (d0
      ? (p0
        ? (ko ? `예: \`Spawn Sound 2D\`의 Sound에 \`${d0.asset}\`, 반환된 Audio Component에서 \`Set Float Parameter\` (In Name \`${p0.input}\`, In Float ${p0.max}).`
          : `Example: \`Spawn Sound 2D\` with Sound \`${d0.asset}\`, then \`Set Float Parameter\` on the returned Audio Component (In Name \`${p0.input}\`, In Float ${p0.max}).`)
        : (ko ? `예: \`Spawn Sound 2D\`의 Sound에 \`${d0.asset}\`.` : `Example: \`Spawn Sound 2D\` with Sound \`${d0.asset}\`.`))
      : '');
    return `# ${b.game || 'Olmuse'} - Unreal Engine 5

Unreal Engine 5.8에서 시험했습니다. / Tested with Unreal Engine 5.8.

## 한국어

### 1. 넣는 법
zip 안의 것을 \`.uproject\` 파일이 있는 폴더에 바로 풉니다(zip 이름으로 새 폴더를 만들지 않습니다). 다 풀면 \`.uproject\` 옆에 \`Plugins/OlmuseAudio/OlmuseAudio.uplugin\`이 있어야 합니다. 없으면 한 단계 안쪽 폴더에 풀린 것이니 그 안의 것을 한 단계 위로 옮깁니다. 같은 이름의 파일(\`CREDITS.md\` 등)을 바꿀지 물으면, 그 파일이 Olmuse가 만든 것일 때만 바꿉니다.
그다음 에디터를 엽니다(열려 있었으면 닫고 다시 엽니다). 열면 소리를 저절로 가져옵니다. 결과는 Output Log에서 \`Olmuse\`로 찾습니다.

### 2. 어디에 생기나
\`/Game/Olmuse/Audio\`(소리), \`/Game/Olmuse/Dynamic\`(동적 소리). 이 폴더의 에셋은 Olmuse가 다시 씁니다. 설정은 이 에셋을 쓰는 쪽(Audio Component, Blueprint)에서 바꿉니다. 그래프를 손보고 싶으면 복사본을 만들어 고칩니다.

${soundTable(true)}

### 3. 동적 소리
${table(true)}
${lostLine(true)}
### 4. Blueprint로 쓰는 법
- 동적 소리 에셋을 레벨에 끌어 놓으면 Ambient Sound가 생기고 시작 때 울립니다.
- 또는 \`Spawn Sound 2D\`로 틀고, 반환된 Audio Component에서 \`Set Float Parameter\`를 부릅니다. 이름은 위 표의 "Blueprint에서 쓸 이름"입니다.
${example(true)}
- 환경음은 값을 바꾸면 바로 부드럽게 바뀌고, 음악은 다음 마디 시작에서 바뀝니다.

### 5. 소리를 고친 뒤
- 게임 폴더를 연결했으면 Olmuse에서 승인만 합니다. 에디터를 켜 둔 채로 몇 초 뒤 바뀝니다.
- zip이면 새 zip을 같은 자리에 다시 풀고 에디터를 다시 엽니다.

### 6. 팀 저장소(git 등)에 넣을 것
넣을 것: \`OlmuseAudio/\`(소리 파일, 명세, CREDITS), \`Plugins/OlmuseAudio/\`(그 안의 \`imported.json\` 포함), \`Content/Olmuse/\`. 넣지 않을 것: \`Saved/\`(보통 이미 빠져 있음). 이것들을 같이 올려야 받은 팀원의 에디터가 소리를 다시 가져오지 않습니다. Perforce처럼 파일을 잠그는 소스 관리를 켠 프로젝트에서는 시험하지 않았습니다.

### 7. 안 될 때
- Output Log의 \`Olmuse:\` 줄을 봅니다. 줄이 하나도 없으면 1번의 \`.uplugin\` 위치부터 봅니다.
- Python이 꺼져 있으면 Edit > Plugins에서 "Python Editor Script Plugin"을 켜고 에디터를 다시 엽니다.
- 소리 파일이 OGG·MP3라 가져오지 못했다는 줄이 나오면 Olmuse 내보내기 형식을 WAV로 바꿉니다.
- 자세한 결과는 \`Saved/Olmuse/last_import.json\`에 있습니다.

### 8. 없는 것
음악의 마디 신호(마디가 시작될 때 알려 주는 이벤트)는 이 묶음에 없습니다.

### 9. 라이선스
\`Plugins/OlmuseAudio/\` 안의 스크립트는 Olmuse가 만든 것이며 MIT 조건으로 자유롭게 쓰고 고치고 배포할 수 있습니다. Unreal 내장 기능만 씁니다.

## English

### 1. Install
Unzip straight into the folder that holds your \`.uproject\` file (do not make a new folder named after the zip). Afterwards \`Plugins/OlmuseAudio/OlmuseAudio.uplugin\` must sit next to the \`.uproject\`. If it does not, the files landed one folder too deep: move them up one level. If asked whether to replace a file with the same name (\`CREDITS.md\` and so on), replace it only if Olmuse made it.
Then open the editor (close and reopen it if it was open). Sounds are imported on their own when it opens. Search the Output Log for \`Olmuse\` to see the result.

### 2. Where things go
\`/Game/Olmuse/Audio\` (sounds), \`/Game/Olmuse/Dynamic\` (dynamic sounds). Olmuse rewrites the assets in these folders, so change settings where they are used (Audio Component, Blueprint). To edit a graph by hand, duplicate it first.

${soundTable(false)}

### 3. Dynamic sounds
${table(false)}
${lostLine(false)}
### 4. Using them from Blueprint
- Drag a dynamic sound asset into the level: it becomes an Ambient Sound that plays on start.
- Or play it with \`Spawn Sound 2D\` and call \`Set Float Parameter\` on the returned Audio Component, using the "name to use in Blueprint" from the table above.
${example(false)}
- Ambience follows a new value at once, smoothly; music changes at the start of the next bar.

### 5. After changing sounds
- With a linked game folder, just approve in Olmuse. With the editor open, the change arrives a few seconds later.
- With a zip, unzip the new zip over the same place and reopen the editor.

### 6. What to commit to your team repository (git etc.)
Commit \`OlmuseAudio/\` (sound files, spec, credits), \`Plugins/OlmuseAudio/\` (including its \`imported.json\`), \`Content/Olmuse/\`. Do not commit \`Saved/\` (usually already ignored). Committed together, a teammate's editor does not import the sounds again. Not tested with file-locking source control such as Perforce.

### 7. When it does not work
- Read the \`Olmuse:\` lines in the Output Log. If there are none, check where the \`.uplugin\` is (step 1).
- If Python is off, enable "Python Editor Script Plugin" under Edit > Plugins and reopen the editor.
- If a line says an OGG or MP3 file could not be imported, switch the Olmuse export format to WAV.
- Full results are in \`Saved/Olmuse/last_import.json\`.

### 8. Not included
There is no bar signal (an event when a music bar starts) in this bundle.

### 9. License
The scripts in \`Plugins/OlmuseAudio/\` are generated by Olmuse and are free to use, modify and ship (MIT terms). They use only built-in Unreal features.
`;
  }

  /* ---------- entry ---------- */
  function build(project) {
    const py = window.unrealPy;
    if (!py || !py.INIT || !py.IMPORTER) throw new Error('unreal_py.js');
    const b = data(project || {});
    return [
      { path: `${PLUGIN}/OlmuseAudio.uplugin`, text: JSON.stringify(UPLUGIN, null, 2) + '\n' },
      { path: `${PLUGIN}/Content/Python/init_unreal.py`, text: py.INIT },
      { path: `${PLUGIN}/Content/Python/olmuse_unreal.py`, text: py.IMPORTER },
      { path: `${ROOT}README.md`, text: readme(b) },
      { path: `${PLUGIN}/olmuse_build.json`, text: JSON.stringify(b, null, 2) + '\n' },
    ];
  }

  window.unrealExport = { build, data, slug, fnv, ROOT };
})();
