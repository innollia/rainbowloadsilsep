# 에셋 작업실 Unreal Engine 5 내보내기 명세

[GAME_ASSET_PLAN](GAME_ASSET_PLAN.md)은 Unreal을 정하지 않는다. 엔진 내보내기에 대해 정한 것은 "승인하면 엔진을 포함한 같은 경로·형식으로 게임 폴더에 바로 쓴다"(4절 쓰기), "에디터로 돌아가면 새 소리가 들린다"(8절 순서 9), "보드의 주인은 브라우저다"뿐이고, [WORK_PLAN](WORK_PLAN.md) 6-6은 Unreal을 "Godot과 같은 데이터(`dynamics`)를 엔진별 재생기로 옮기는" 나중 일로만 적는다. 그래서 Unreal 내보내기는 Godot 내보내기(`godot.js`)와 같은 모양으로 만든다. 화면 규칙은 [UI_LESSONS](UI_LESSONS.md)를 따른다.

전제:
- 쓰는 사람은 게임잼 팀원이고 Blueprint만 쓰는 프로젝트다. C++ 컴파일, 유료 플러그인, 미들웨어(FMOD, Wwise)를 쓰지 않는다.
- 파일은 브라우저가 만든다. 새 파일 `studio_frontend/asset_studio/unreal.js`가 `window.unrealExport.build(project) → [{ path, text }]`를 내놓고, 입력 `project`는 `godotExport.build`에 넘기는 것과 같다. `.uasset`은 브라우저가 만들지 않는다. 에셋은 묶음에 든 Python 가져오기 스크립트가 Unreal 안에서 만든다.
- 확인된 엔진은 Unreal Engine 5.8.4(내장 Python 3.11.8)뿐이다. 다른 버전은 가져오기 스크립트의 사전 점검(F절)이 판단한다.
- 화면에서 보이는 변화는 기존 "게임 엔진" 선택 칸의 선택지 하나 `Unreal Engine 5`뿐이다. 새 창, 줄, 패널, 단추, 문구 키를 만들지 않는다.
- 동적 소리 편집 화면에 Unreal 용어(MetaSound 등)를 올리지 않는다.
- 아래에서 **확인됨**은 이 PC의 UE 5.8.4에서 실행해 본 것, *(소스)*는 설치된 엔진 소스에서 읽은 것, **미확인**은 실행하지 않은 것이다. 실행 결과는 I0, 뺀 것은 I4에 있다.

## A. 묶음의 모양

### A1. 경로

모든 경로는 `.uproject`가 있는 폴더(프로젝트 뿌리) 기준이다. 프로젝트 뿌리 바로 아래에는 파일을 하나도 두지 않는다. 그 자리는 프로젝트 자신의 파일(에이전트 문서 `CLAUDE.md` 등, `.mcp.json`)이 쓴다. Olmuse가 쓰는 것은 폴더 두 개, `OlmuseAudio/`와 `Plugins/OlmuseAudio/` 아래뿐이다. zip을 프로젝트 뿌리에 풀거나 프로젝트 뿌리를 게임 폴더로 연결하면 그대로 제자리다. Godot 내보내기의 경로는 바뀌지 않는다.

| zip·폴더 안 경로 | 내용 | 만드는 곳 | 생성 조건 |
|---|---|---|---|
| `OlmuseAudio/game-audio.spec.json`, `OlmuseAudio/CREDITS.md`, `OlmuseAudio/lint-report.json`, `OlmuseAudio/<root>/…/<id>.<format>` | 엔진과 무관한 파일. 내용은 Godot·엔진 없음일 때와 같고 앞에 `OlmuseAudio/`가 붙는다 | app.js `bundleFiles` (앞머리는 `unrealExport.ROOT`) | 엔진이 Unreal일 때 |
| `Plugins/OlmuseAudio/OlmuseAudio.uplugin` | 코드 모듈 없는 콘텐츠 전용 플러그인 설명(A2) | unreal.js | 항상 |
| `Plugins/OlmuseAudio/Content/Python/init_unreal.py` | 에디터 시작 때 자동 실행, 가져오기와 감시(D절) | unreal_py.js → unreal.js | 항상 |
| `Plugins/OlmuseAudio/Content/Python/olmuse_unreal.py` | 가져오기 본체(E절). 모든 프로젝트에 같은 글자 | unreal_py.js → unreal.js | 항상 |
| `OlmuseAudio/README.md` | 처음 보는 팀원용 사용법(H절) | unreal.js | 항상 |
| `Plugins/OlmuseAudio/olmuse_build.json` | 이 프로젝트의 소리·동적 소리 데이터(C절) | unreal.js | 항상. **배열의 마지막 항목** |

- `olmuse_build.json`을 마지막에 두는 이유: 게임 폴더 쓰기는 배열 순서대로 쓰고, 소리 파일이 엔진 파일보다 먼저다. 에디터 쪽 감시는 이 파일이 바뀐 것을 보고 움직이므로, 이 파일이 쓰일 때는 WAV가 이미 다 쓰여 있다.
- 동적 소리가 없어도 다섯 파일은 나간다. 그때 `dynamics`는 빈 배열이고 일반 소리 가져오기만 한다.
- 가져오기가 만드는 파일(`Plugins/OlmuseAudio/imported.json`, `Saved/Olmuse/last_import.json`, `Content/Olmuse/…`)은 unreal.js가 내놓지 않는다. 그래서 zip을 다시 풀거나 승인으로 다시 써도 이 파일들은 덮이지 않는다.
- 묶음은 `Content/Python/`(프로젝트 자신의 `init_unreal.py` 자리)과 `Config/`에 아무것도 쓰지 않는다. 프로젝트의 `init_unreal.py`와 이 플러그인의 것은 둘 다 돈다(**확인됨**).
- **남의 파일을 덮지 않는다.** 게임 폴더에 쓰기 전에 app.js가 `OlmuseAudio/`와 `Plugins/OlmuseAudio/`를 본다. 그 폴더가 있는데 Olmuse가 쓴 표시(`Plugins/OlmuseAudio/olmuse_build.json`, `OlmuseAudio/game-audio.spec.json` 중 그 폴더의 것)가 없으면 아무것도 쓰지 않고 "게임 폴더에 쓰지 못함" 안내에 그 폴더 이름을 넣어 멈춘다. 이름을 바꿔 쓰지 않는다(바꾼 이름은 가져오기 스크립트가 찾지 못한다). Olmuse가 쓴 폴더 안의 파일은 지금처럼 덮어쓴다.
- 소리 파일은 `Content/` 밖(`OlmuseAudio/…`)에 둔다. `Content/` 안의 WAV는 Unreal이 스스로 가져오지 않거나(이미 있던 파일, `-unattended`) 클릭을 기다리는 알림을 띄운다(**확인됨**). 가져오기는 언제나 스크립트가 한다(**확인됨**: 명령줄 실행, 에디터 실행 둘 다).

### A2. 플러그인 설명

```json
{ "FileVersion": 3, "Version": 1, "VersionName": "1.0", "FriendlyName": "Olmuse Audio",
  "Description": "Sounds made with Olmuse. Content only, no code modules.", "Category": "Audio", "CreatedBy": "Olmuse",
  "CanContainContent": true, "IsBetaVersion": false, "Installed": false,
  "Plugins": [ { "Name": "PythonScriptPlugin", "Enabled": true, "TargetAllowList": ["Editor"] },
               { "Name": "Metasound", "Enabled": true } ] }
```

- **확인됨:** `Modules`가 없는 이 모양은 `.uproject`에 적지 않아도 마운트되고, C++ 빌드를 부르지 않으며, 창이 있는 평범한 에디터 시작에서도 아무것도 묻지 않는다. 플러그인의 `Content/Python/init_unreal.py`는 Python 플래그 없이 실행된다. PythonScriptPlugin을 `.uproject`에 적지 않은 빈 프로젝트에서도 Python이 켜졌다.
- `TargetAllowList: ["Editor"]`: PythonScriptPlugin은 기본으로 꺼진 플러그인이고 Runtime 모듈(`PythonScriptPluginPreload`)이 있다 *(소스)*. 이 의존을 게임 대상에도 걸면 Blueprint 전용 프로젝트의 패키징이 "PythonScriptPlugin plugin is enabled"로 임시 C++ 대상(코드 빌드)을 요구한다 *(소스: UnrealBuildTool `NativeProjects.RequiresTempTargetForCodePlugin`)*. 엔진 플러그인 `PythonFoundationPackages`가 같은 모양을 쓴다. Metasound는 기본으로 켜진 플러그인이라 게임에 원래 들어간다. 이 플러그인 자체는 콘텐츠 에셋이 없고(에셋은 `/Game/Olmuse`) `Content/Python/*.py`는 에셋이 아니다. 패키징 확인은 I2의 4번.
- **미확인:** `.uproject`가 PythonScriptPlugin을 명시적으로 끈 경우, 에디터 설정 "Enable Python Override"를 끈 경우. 그때의 안내는 H절 README에 있다.
- 실행 중인 에디터는 새로 생긴 `Plugins/OlmuseAudio`를 올리지 않는다(**확인됨**: 15초 동안 그 init 스크립트가 돌지 않고 플러그인 목록에도 없었다). 처음 한 번은 에디터를 다시 열어야 한다.

### A3. 에셋 위치와 이름

- 일반 소리: `/Game/Olmuse/Audio/<asset>` (SoundWave). 분류별 폴더 규칙(`folders: cat|kind`)은 Unreal 쪽에서는 쓰지 않고 한 폴더에 둔다.
- 동적 소리: `/Game/Olmuse/Dynamic/MS_<이름>` (MetaSound Source). `<이름>`은 동적 소리 id에 아래 이름 규칙 1~3을 따로 적용한 것이다(소리 이름과 겹쳐도 폴더가 달라 괜찮다).
- 동적 소리의 그래프 입력 이름(Blueprint가 부르는 이름): 파라미터 id가 `^[A-Za-z_][A-Za-z0-9_]*$`이면 그대로, 아니면 이름 규칙 1~3을 적용한 것. 한 동적 소리 안에서 대소문자 무시로 겹치면 해시를 붙인다. `olmuse_build.json`의 `params[].input`과 README 표에 적는다.
- 플러그인 콘텐츠(`/OlmuseAudio/…`)에 두지 않는다. 플러그인 경로에서는 에셋 레지스트리를 먼저 훑지 않으면 있는 에셋을 없다고 답한다(**확인됨**). `/Game/…`에 두어야 프로젝트의 다른 에셋과 같이 소스 관리에 들어간다.

이름 규칙(unreal.js가 정하고 `olmuse_build.json`의 `asset`에 적는다):
1. `slug(s)` = `[A-Za-z0-9_]` 말고는 전부 `_`로 바꾸고, 앞뒤 `_`를 떼고, 비면 `x`. godot.js의 `slug`와 같은 함수다.
2. 소리 id의 slug가 id와 다르거나(한글, `.`, `-`, 공백이 있었다), 앞서 지은 이름과 대소문자 무시로 겹치면 `_` + id의 FNV-1a 32비트 해시 앞 6자리(소문자 16진)를 붙인다.
3. 60자를 넘으면 slug의 앞 53자 + `_` + 해시 6자리. 그래도 앞서 지은 이름과 겹치면(해시까지 같은 경우) `_2`, `_3`…을 붙인다.
4. 원래 id와 표시 이름은 에셋 메타데이터 태그 `OlmuseId`, `OlmuseName`에 둔다.

근거(**확인됨**): Unreal은 한글, 영문, 숫자, `_`, `-`는 그대로 두고 공백·`.`·`(`·`)`·`!`·`&`는 말없이 `_`로 바꾼다. 그래서 `a b.wav`와 `a_b.wav`가 같은 에셋이 되어 뒤의 것이 앞의 것을 덮는다. 한글 이름은 가져오기는 되지만 쿠킹·패키징·소스 관리에서의 동작은 **미확인**이라 쓰지 않는다. 가져오기 스크립트는 실제로 생긴 경로를 `imported_object_paths`에서 읽고 이름을 예측하지 않는다.

## B. app.js와 그 밖의 바뀌는 곳

줄 번호는 지금 작업본 기준이다. 구현 때는 글자로 찾는다.

| 곳 | 지금 | 바꾼 뒤 |
|---|---|---|
| app.js:1882 | `opt(t('engine'), 'engine', [['none', t('engineNone')], ['godot', 'Godot 4']]);` | `[['none', t('engineNone')], ['godot', 'Godot 4'], ['unreal', 'Unreal Engine 5']]` |
| app.js:2547 주석 | "…and the Godot files when they are asked for." | "…and the engine files (Godot or Unreal) when they are asked for." |
| app.js:2573~2577 | `if (exportOpts.engine === 'godot') { if (!window.godotExport) throw new Error('godot.js'); const project = …; for (…) files.push(…) }` | `const lib = { godot: 'godotExport', unreal: 'unrealExport' }[exportOpts.engine];` `if (lib) { if (!window[lib]) throw new Error(exportOpts.engine + '.js'); const project = …(지금 줄 그대로); for (const f of window[lib].build(project)) files.push({ path: f.path, bytes: utf8(f.text) }); }`. 스크립트가 안 실렸으면 지금처럼 오류로 알리고, 엔진 파일 없이 조용히 나가지 않는다. `project.assets[].file`은 지금처럼 `exportPath(a)`(앞머리 없음)를 넘긴다. 앞머리는 unreal.js가 붙인다 |
| `bundleFiles` 안, 엔진 파일을 더하기 **전** | 명세·CREDITS·lint·소리 파일이 뿌리 기준 경로 | 엔진이 `unreal`이면 그때까지 모인 파일 모두의 `path` 앞에 `window.unrealExport.ROOT`(`'OlmuseAudio/'`)를 붙인다. 엔진 파일(`Plugins/…`, `OlmuseAudio/README.md`)은 unreal.js가 준 경로 그대로. `godot`·`none`은 지금 그대로 |
| 게임 폴더 쓰기(`toFolder`/`writeFiles`) | 같은 이름이면 덮어씀 | 엔진이 `unreal`이면 쓰기 전에 A1의 "남의 파일을 덮지 않는다" 점검: 연결한 폴더에 `OlmuseAudio`가 있는데 `OlmuseAudio/game-audio.spec.json`이 없거나, `Plugins/OlmuseAudio`가 있는데 `Plugins/OlmuseAudio/olmuse_build.json`이 없으면 하나도 쓰지 않고 지금의 "게임 폴더에 쓰지 못함" 안내로 멈춘다(문구 키는 새로 만들지 않고 폴더 이름을 이유 자리에 넣는다) |
| app.js:2033, 2043 | `/\.(md|txt|gd|tscn|tres|cfg)$/i` | `/\.(md|txt|gd|tscn|tres|cfg|py|uplugin)$/i` (내보낸 zip을 다시 열 때 "모르는 형식"으로 세지 않는다. `olmuse_build.json`은 `.json`이라 이미 걸러지고, 명세는 이름 `game-audio.spec.json`으로 먼저 찾으므로 헷갈리지 않는다) |
| app.js:2623~2629 (`readFolder`) | 어느 깊이에서든 숨김 폴더와 `node_modules`만 건너뜀 | 그대로 두고, **맨 위(`path === ''`)에서만** `Content`, `Plugins`, `Config`, `Intermediate`, `Saved`, `DerivedDataCache`, `Binaries`, `Build`도 건너뛴다. Unreal 프로젝트 뿌리를 연결했을 때 5000개 상한을 엔진 폴더가 먹지 않게 한다. 다른 깊이의 같은 이름 폴더는 그대로 읽는다. 주석에 같은 말을 더한다 |
| 연결한 폴더 읽기(명세 찾기) | 뿌리의 `game-audio.spec.json`과 그 경로 기준 소리 파일 | 뿌리에 `game-audio.spec.json`이 없고 `OlmuseAudio/game-audio.spec.json`이 있으면 그것을 명세로 읽고, 소리 파일 경로는 `OlmuseAudio/` 기준으로 맞춘다(내보낸 경로에서 앞머리를 떼어 보드의 `exportPath`와 맞춘다). 뿌리에 있으면 지금 그대로 |
| index.html:69 다음 | | `<script src="unreal_py.js"></script>`, `<script src="unreal.js"></script>` (이 순서) |

- 문구 표(app.js:137·288)는 건드리지 않는다. `Unreal Engine 5`는 `Godot 4`처럼 글자로 둔다. `bundleGodot`류의 쓰지 않는 키를 Unreal용으로 만들지 않는다(묶음 목록은 사용자가 뺀 것이다).
- 모르는 `engine` 값이 저장본·명세에서 들어오면 지금처럼 `select`가 빈 칸이 된다. 이번 일에서 고치지 않는다.
- `game-audio.spec.json`의 `export.engine`에 `"unreal"`이 실린다. 명세 형식 자체는 바뀌지 않는다.

### B1. 게임 폴더 연결과 Unreal

- **연결할 폴더:** `.uproject`가 있는 폴더. README와 이 명세가 그렇게 안내한다. 화면 문구는 바꾸지 않는다.
- **쓰는 것:** 지금과 같은 것을 `OlmuseAudio/` 아래에 쓴다. 승인할 때마다 명세·CREDITS·lint, 방금 승인한 소리 파일, 그리고 A1의 Unreal 파일 다섯 개 전부를 다시 쓴다. 지우는 일은 없다. 프로젝트 뿌리 바로 아래에는 쓰지 않는다.
- **처음 쓴 뒤:** 에디터를 한 번 다시 열어야 `init_unreal.py`가 돈다(**확인됨**: 실행 중인 에디터는 새 플러그인 폴더를 올리지 않는다). 열면 첫 틱에 가져온다(D1).
- **쓰기와 가져오기가 겹칠 때:** 브라우저가 쓰는 동안 Unreal이 같은 WAV를 읽고 있어 쓰기가 실패하면, 지금처럼 브라우저가 "게임 폴더에 쓰지 못함" 안내를 띄운다. 다시 승인하면 다시 쓴다. Unreal 쪽에서 파일을 못 읽은 소리는 E1의 실패 처리대로 다음 가져오기에서 다시 시도된다.
- **에디터가 열린 채 두 번째 내보내기:** `init_unreal.py`가 띄운 감시가 `olmuse_build.json`의 바뀐 시각과 크기를 2초마다 보고, 바뀐 뒤 1.5초 동안 더 안 바뀌면 가져오기를 한 번 돈다. 바뀐 WAV만 다시 가져오고(내용 해시 비교), 데이터가 바뀐 동적 소리만 고쳐 짓는다(E3). 결과는 Output Log에 한 줄로 남는다. 사용자가 누를 것은 없다(**확인됨**: I2 3번, MetaSound 에디터에 그 에셋이 열려 있어도 4.7초 뒤 고쳐 지음).
- **Python 파일이 바뀐 경우:** 감시가 가져오기를 부를 때마다 `importlib.reload(olmuse_unreal)`로 새 글자를 읽는다. `init_unreal.py` 자체가 바뀐 것은 다음 에디터 시작에 반영된다.
- **PIE(에디터에서 플레이) 중:** 가져오기를 미루고 PIE가 끝난 뒤 돈다(**확인됨**: PIE 중 8초 동안 안 돌고, 끝난 뒤 8초 안에 돌았다).
- 설정·동적 소리만 바꾸고 승인하지 않으면 폴더는 옛것 그대로다(지금 Godot과 같다).

## C. `olmuse_build.json` (unreal.js가 계산하는 것)

계산은 JS가 하고 Python은 받은 숫자로 그래프만 짓는다. 그래야 숫자 규칙을 Node 단위 시험으로 다 본다.

```json
{
  "olmuse_unreal": 1,
  "game": "숲의 노래",
  "tested_engine": "5.8",
  "content_root": "/Game/Olmuse",
  "sounds": [
    { "id": "amb_wind", "name": "바람", "file": "OlmuseAudio/audio/amb_wind.wav", "asset": "amb_wind", "loop": true }
  ],
  "dynamics": [
    { "id": "dyn_1", "name": "숲", "asset": "MS_dyn_1", "type": "ambience",
      "params": [ { "id": "intensity", "input": "intensity", "name": "강도", "min": 0, "max": 1, "default": 0.5 } ],
      "fade_seconds": 0.8, "bar_seconds": null,
      "layers": [
        { "sound": "amb_wind", "role": "bed", "param": null, "scale": 0, "offset": 1, "volume": 1 },
        { "sound": "sfx_bird", "role": "scatter", "param": "intensity", "scale": 1, "offset": 0, "volume": 1,
          "scatter": { "min_gap": 2, "max_gap": 8, "semitones": [-1.824, 1.65], "pan": [-0.8, 0.8] } }
      ],
      "skipped": [ { "sound": "amb_rain", "why": "not_approved" } ],
      "hash": "a1b2c3d4" }
  ]
}
```

규칙(godot.js 2.4절의 다듬기 규칙을 그대로 따르고, 다른 곳만 적는다):
- `sounds`: `project.assets`(승인한 소리) 전부. `file` = `OlmuseAudio/` + 그 소리의 `file`(프로젝트 뿌리 기준). `loop` = 소리의 `loop` 표시 그대로. bed·stem으로 쓰인다고 켜지 않는다: 그래프 안의 반복은 Wave Player의 `Loop`가 맡고(**확인됨**), SoundWave의 `looping`을 켜면 게임이 그 소리를 한 번 울리려고 직접 틀 때도 끝없이 돈다.
- `dynamics`: `id`가 없는 동적 소리는 빼고, `id`가 없는 파라미터도 뺀다(godot.js와 같다). 뺀 것은 맨 위 `dropped`(`{name, why: "no_id"}`)와 그 동적 소리의 `dropped_params`(이름 목록)에 남고 README에 적힌다. 둘 다 빈 때는 키를 쓰지 않는다.
- 파라미터: `min` 기본 0, `max` 기본 1, `default` 기본 0.
- `role`: `scatter`·`stem` 말고는 `bed`. `param`: 그 동적 소리의 params에 없으면 `null`(그 레이어는 미리 듣기처럼 늘 `volume`으로 울린다).
- 레이어 음량은 화면 미리 듣기와 같은 **선형 진폭** 모양이다: `level = clamp(p·scale + offset, 0, 1) · volume`. `scale = 1/(on1−on0)`, `offset = −on0·scale`. on0 > on1이면 그대로 거꾸로 된다. on0 == on1이면 on0 = on1 − 0.0001로 계산한다(계단. 미리 듣기처럼 값이 on 이상이면 최대). `param`이 `null`이면 `scale 0, offset 1`. 숫자는 소수 6자리. Godot의 다섯 점 dB 보간은 쓰지 않는다(G절).
- `volume` = 명세의 `volume`(gain). 0 이하면 0.
- `fade_seconds`: 환경음은 0.8. 음악은 `fade_beats(1) × 60 / bpm`.
- `bar_seconds`: 음악만 `beats_per_bar × 60 / bpm`, 환경음은 `null`. `bpm` 없으면 120, `beats_per_bar`는 1 이상 정수(godot.js와 같다).
- scatter: `min_gap ≥ 0.05`(없으면 2), `max_gap ≥ min_gap`(없으면 8), pitch 없으면 `[1,1]`, pan 없으면 `[0,0]`, 작은 값 먼저, pan은 −1~1로 자름. pitch 배수는 `12·log2(배수)` 반음으로 바꿔 `semitones`에 적는다. 0 이하인 배수는 1로 본다.
- `hash`의 FNV-1a는 UTF-8 바이트에 대해 계산한다. 이름 규칙의 해시 6자리는 같은 함수의 앞 6자리다.
- 건너뛰기: 레이어의 소리가 `project.assets`에 없으면 `not_approved`, 레이어가 동적 소리 하나에 8개를 넘으면 9번째부터 `too_many_layers`. 건너뛴 것은 `skipped`와 README에 남는다.
- `hash`: 그 동적 소리 항목(`hash` 제외)을 키 정렬 JSON으로 만든 글자의 FNV-1a 32비트 16진. 가져오기가 고쳐 지을지 정하는 데 쓴다.
- 같은 입력이면 글자 단위로 같은 출력이 나온다. 줄바꿈은 `\n`.

## D. 사용자가 하는 일과 자동 실행

### D1. 단계

1. 게임 폴더를 연결했으면: 승인하면 끝. 처음 한 번만 에디터를 다시 연다.
2. zip이면: zip 안의 것을 `.uproject`가 있는 폴더에 **바로** 풀고(zip 이름의 새 폴더를 만들지 않는다) 에디터를 연다(열려 있었으면 다시 연다). 풀고 나면 `.uproject` 옆에 `Plugins/OlmuseAudio/OlmuseAudio.uplugin`이 있어야 한다.

가져오기는 에디터 시작 때 저절로 돈다. 메뉴, 단추, 명령이 필요 없다. 플러그인이 다른 깊이에 풀리면 아무 일도 일어나지 않고 알림도 없으므로, README 맨 앞이 이 확인 한 줄이다(H절).

### D2. `init_unreal.py`

- 에디터 시작 때 실행된다(**확인됨**). 명령줄 실행에서는 아무것도 하지 않는다. 판별: `'-run=' in unreal.SystemLibrary.get_command_line().lower()`(**확인됨**: 명령줄 실행에서 전체 명령줄을 돌려준다. `unreal.is_editor()`는 명령줄 실행에서도 True라 쓸 수 없다).
- 자기 안에서 바로 가져오지 않고 `unreal.register_slate_post_tick_callback`으로 첫 틱에 돈다. 틱 콜백 안의 가져오기·MetaSound 짓기·저장은 **확인됨**(창 있는 에디터, `-nullrhi` 에디터 둘 다).
- 같은 콜백이 B1의 감시를 맡는다. 2초마다 파일 시각을 보는 것 말고는 일하지 않는다(바뀐 것을 본 뒤에는 0.25초마다).
- PIE 판별: `unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor()`(**확인됨**). 이 호출은 명령줄 실행에서 엔진을 죽이므로(**확인됨**: `EXCEPTION_ACCESS_VIOLATION`) 명령줄 판별 뒤에만 부른다.
- 맨 앞에서 `sys.dont_write_bytecode = True`를 둔다. 플러그인 폴더에 `__pycache__`가 생겨 소스 관리에 섞이지 않게 한다(**확인됨**).
- 콜백 안의 모든 일은 `try`로 감싼다. 예외가 나면 `Saved/Olmuse/last_import.json`에 오류를 쓰고 `Olmuse:` 로그 두 줄(한국어, 영어)을 남긴 뒤, 그 `olmuse_build.json`(같은 시각·크기)으로는 다시 시도하지 않는다. 다음 승인(파일이 바뀜)이나 에디터 재시작 때 다시 돈다. 매 틱 같은 오류를 되풀이하지 않는다.
- 시험 전용(README에 적지 않는다): 환경 변수 `OLMUSE_QUIT_AFTER=N`이면 가져오기마다 결과를 `Saved/Olmuse/watch_run_<n>.json`으로 복사하고, `OLMUSE_AFTER_IMPORT`가 가리키는 `.py`를 `runpy`로 돌리고, N번째 가져오기 뒤 에디터를 닫는다. 540초가 지나도 닫는다.

## E. 가져오기 본체 `olmuse_unreal.py`

`run(project_dir) -> dict` 하나를 내놓는다. `__main__`으로 실행하면 `unreal.Paths.project_dir()`로 같은 일을 한다(명령줄 시험용). 결과는 언제나 `Saved/Olmuse/last_import.json`에 쓴다(에디터 실행의 종료 코드는 스크립트가 실패해도 0이라 믿을 수 없다, **확인됨**).

### E1. 순서

1. 사전 점검(F절). 실패하면 여기서 멈추고 아무 에셋도 건드리지 않는다.
2. `olmuse_build.json`을 읽는다. 기록 파일 `Plugins/OlmuseAudio/imported.json`(소리별 WAV 해시와 실제 에셋 경로, 동적 소리별 `hash`)을 읽는다. 없으면 빈 기록.
3. 소리: 파일이 없으면 `missing`으로 적고 넘어간다. 해시가 기록과 같고 에셋이 있으면 넘어간다. 아니면 한 번의 `import_asset_tasks` 호출로 모두 가져온다(`automated=True, replace_existing=True, save=True, destination_path=/Game/Olmuse/Audio, destination_name=asset`). **확인됨**: 같은 경로에 다시 가져오면 중복 없이 그 자리에서 바뀌고, 그 에셋을 가리키는 MetaSound와 Blueprint의 참조가 유지된다.
4. 가져온 SoundWave마다 `looping`을 `loop` 값으로 다시 넣고 저장한다. 다시 가져오기는 `looping`을 False로 되돌리므로 매번 해야 한다(**확인됨**). 메타데이터 `OlmuseId`, `OlmuseName`도 매번 넣는다.
5. 동적 소리: `hash`가 기록과 같고 에셋이 있고 그 소리들이 이번에 새로 생기지 않았으면 넘어간다. 소리만 바뀐 경우도 넘어간다(MetaSound는 같은 경로의 웨이브를 계속 가리킨다, **확인됨**). 아니면 E3대로 짓거나 고쳐 짓는다.
6. 기록 파일을 쓰고, Output Log에 `LogPython` 한 줄 요약을 남긴다. 예: `Olmuse: 소리 3개 가져옴, 동적 소리 1개 고침, 건너뜀 1개(파일 없음: amb_rain). 자세한 것: Saved/Olmuse/last_import.json`.

중간에 실패할 때:
- 소리 하나가 실패하면(파일이 잠김, 읽을 수 없는 형식, `imported_object_paths`가 빔) 그 소리만 `failed`와 이유를 결과에 적고 나머지는 계속한다. 기록에는 **성공한 것만** 새 해시로 적는다. 실패한 소리는 기록이 옛것이라 다음 가져오기에서 다시 시도된다.
- 동적 소리 하나가 실패하면 그것만 건너뛰고(F절의 노드 점검을 통과해도 연결이 실패할 수 있다) 기록의 그 `hash`를 바꾸지 않는다.
- 고쳐 짓기(E3)는 먼저 같은 그래프를 저장하지 않는 임시 빌더에 다 지어 보고, 모든 호출이 `SUCCEEDED`일 때만 그 에셋을 고친다. 에셋을 고치다 실패하면 저장하지 않고 `unreal.EditorLoadingAndSavingUtils.reload_packages([그 패키지])`로 디스크의 옛것을 다시 읽어 메모리의 반쯤 고친 상태를 버린다(**확인됨**: 저장하지 않은 입력 삭제가 되돌아온다). 임시 빌더는 성공이든 실패든 `finally`에서 등록을 푼다.
- 기록 파일과 결과 파일은 `finally`에서 쓴다. 스크립트가 예외로 끝나도 그때까지 성공한 것이 기록된다.
- 사용자에게 보이는 실패 문구는 한 줄이고, 할 일을 말한다. 예: `Olmuse: 소리 1개를 가져오지 못했습니다(amb_rain: 파일을 열 수 없음). Olmuse에서 다시 승인하거나 에디터를 다시 열면 다시 시도합니다.` 영어 줄을 바로 밑에 하나 더.

에셋을 지우지 않는다. 보드에서 뺀 소리·동적 소리의 에셋은 프로젝트에 남는다(GAME_ASSET_PLAN 4절: 승인 취소나 삭제는 파일을 지우지 않는다). 소리 id가 바뀌면 새 이름의 에셋이 생기고 옛 에셋은 남는다.

`/Game/Olmuse/` 안의 에셋은 Olmuse가 다시 쓴다:
- SoundWave는 WAV가 바뀌면 새로 가져오므로 손으로 바꾼 설정(압축, Sound Class 등)이 사라진다(다시 가져오기가 새 객체를 만든다, **확인됨**: `looping`이 되돌아감). README가 "설정은 이 에셋을 쓰는 Audio Component·Blueprint 쪽에서 하라"고 알린다.
- MetaSound는 데이터(`hash`)가 바뀐 것만 고쳐 짓고, 고칠 때 지우는 것은 `OlmuseNodes`에 적힌 노드와 Olmuse가 만든 그래프 입력뿐이다. 손으로 더한 노드는 남지만 연결이 끊길 수 있다. 패키지가 `unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()`에 있으면(저장하지 않은 편집) 고치지 않고 `skipped: unsaved_edits`로 적는다. 이 목록 읽기는 **확인됨**, MetaSound 에디터에서 손으로 고친 것이 이 목록에 오르는지는 **미확인**이다(빌더로 고친 것은 명령줄 실행에서 오르지 않았다). 그래서 README의 "설정을 바꾸지 말고 복사본을 고친다"가 주된 보호다.

### E2. MetaSound 그래프 (동적 소리 하나)

`MetaSoundBuilderSubsystem.create_source_builder(name, STEREO, False)`로 짓고 `MetaSoundEditorSubsystem.build_to_asset(...)` 뒤에 반드시 `EditorAssetLibrary.save_asset`(build_to_asset은 파일을 쓰지 않는다, **확인됨**). 사용한 노드의 핸들은 메타데이터 태그 `OlmuseNodes`에, Olmuse가 만든 그래프 입력 이름은 `OlmuseInputs`에 남긴다(**확인됨**). 빌더는 순환 연결을 거부하지 않으므로(**확인됨**) 그래프에 고리를 만들지 않는다.

노드는 `add_node_by_class_name(MetasoundFrontendClassName(namespace, name, variant), 1)`. 숫자 리터럴은 `create_float_meta_sound_literal(x)[0]`(Time 핀에도 들어간다), 웨이브는 `create_object_meta_sound_literal(wave)`(튜플이 아니다). Float 출력을 Time 입력에 잇는 것은 안 되므로 시간은 RandomTime으로 뽑는다(**확인됨**).

| 부분 | 노드 (namespace, name, variant) 와 핀 | 상태 |
|---|---|---|
| 그래프 입력 | 파라미터마다 `add_graph_input_node(input, 'Float', default)` | **확인됨** |
| 범위 자르기 | 입력 → `Clamp, Clamp, Float` (In, Min, Max → Value) | **확인됨** (`UE, Clamp`는 없다) |
| bed·stem 재생 | `UE, Wave Player, Stereo`: Play ← OnPlay, Loop = true, Wave Asset | **확인됨** |
| 레이어 음량 | `p·scale` (`UE, Multiply, Float`) `+ offset` (`UE, Add, Float`) → Clamp(0,1) → `×volume` → `UE, InterpTo, Audio` (Target, Interp Time = `fade_seconds` → Value) → `UE, Multiply, Audio by Float` 좌·우. `param`이 없으면 Multiply에 `volume` 숫자 | **확인됨** (짓기). InterpTo는 첫 목표를 바로 잡고 직선으로 간다 *(소스)* |
| 섞기 | `UE, Add, Audio`를 사슬로 이어 출력 좌·우로 | **확인됨** (8개 레이어) |
| 음악 마디 맞춤 | `UE, TriggerRepeat` (Start ← OnPlay, Period = `bar_seconds`, RepeatOut) → 파라미터마다 `Value, Value, Float` (Set ← RepeatOut, Init Value·Target Value ← 자른 값 → Output Value) | **확인됨** (짓기). TriggerRepeat는 시작 순간에 한 번 울리고 Value는 Init Value로 시작한다 *(소스)* |
| scatter 간격 | 주기 `P = (min_gap+max_gap)/2`. OnPlay → `UE, Trigger Delay` (P) → TriggerRepeat(Period P) → RepeatOut마다 `UE, RandomTime` (0 ~ `(max_gap−min_gap)/2`)를 뽑아 두 번째 Trigger Delay의 Delay Time으로 → 그 Out이 쏘기. 이웃한 간격은 min_gap~max_gap 안(가운데가 잦은 삼각 분포), 첫 재생은 시작 뒤 P~max_gap | **확인됨** (짓기) |
| scatter 재생 | `UE, Wave Player, Mono`: Play ← 쏘기, Wave Asset | **확인됨** (짓기). 울리는 중에 Play가 오면 처음부터 다시 *(소스)* |
| scatter 피치 | `UE, RandomFloat` (Next ← 쏘기, Min·Max = `semitones`) → Pitch Shift | **확인됨** (짓기) |
| scatter 좌우 | Mono 출력 → `UE, Stereo Panner` (In, Pan Amount ← RandomFloat(`pan`) → Out Left, Out Right) | **확인됨** (짓기) |
| scatter 음량 | 위 레이어 음량을 좌·우에 곱한다 | **확인됨** |

"짓기"는 노드가 들어가고 연결이 모두 `SUCCEEDED`이며 저장되고 다시 열린다는 뜻이다. 들리는 결과는 I3에서 사람이 확인한다. 그래프 짓기가 실패하면 그 동적 소리만 건너뛰고 이유를 결과 파일과 로그에 적는다. 레이어의 소리가 없거나 가져오지 못했으면 그 레이어만 빼고 `layers_left_out`에 적는다.

### E3. 다시 짓기

- 에셋이 없으면 `build_to_asset` 후 `save_asset`.
- 있으면 지우지 않는다. 먼저 같은 그래프를 저장하지 않는 임시 빌더(`OlmuseTrial_…`)에 다 지어 본다. 다 되면 `find_or_begin_building(ms)`로 그 에셋에 붙은 빌더를 얻고, `OlmuseNodes`의 노드를 지우고, `OlmuseInputs`의 그래프 입력을 지우고, OnPlay 입력과 출력 노드를 찾아 다시 채운 뒤 저장한다(**확인됨**: 두 번 고쳐 지어도 노드 수가 늘지 않고, 그 MetaSound를 가리키던 Blueprint가 참조를 잃지 않는다).
- 같은 이름에 `build_to_asset`을 다시 부르는 것, `delete_asset` 뒤 다시 짓는 것은 쓰지 않는다(앞은 실패하고 오류 줄을 남기며, 뒤는 지운 척만 하고 열려 있던 Blueprint의 참조를 끊는다, **확인됨**).
- 존재 확인 전에 `scan_paths_synchronous(['/Game/Olmuse'], True)`를 부른다.
- 처음 고쳐 지을 때 텍스트 내보내기의 노드·연결 수가 파라미터마다 하나씩 준다(**확인됨**: 37→36, 46→45). 그래프 입력을 지우고 다시 만들 때 엔진이 붙여 두었던 입력 템플릿 노드가 다시 생기지 않는 것으로 보인다. Olmuse 노드 수(`OlmuseNodes`)와 그래프 입력은 그대로이고, 그 뒤로는 줄지도 늘지도 않는다. MetaSound 에디터에서 깨진 핀이 없는지는 I3에서 본다.

### E4. 두 번 돌려도 같은 결과

같은 묶음으로 가져오기를 두 번 돌리면 두 번째는: 가져온 소리 0개, 고친 동적 소리 0개, 에셋 목록·`.uasset` 파일 목록이 같고, MetaSound의 노드 수가 같다. 이것을 I2의 헤드리스 시험이 확인한다.

## F. 엔진 버전이 바뀌었을 때

가져오기는 무엇이든 쓰기 전에 사전 점검을 한다. 점검이 하나라도 실패하면 아무 에셋도 만들거나 고치지 않고, 쉬운 말 한 줄과 무엇이 없는지를 남긴 뒤 멈춘다.

점검 항목:
1. `unreal.SystemLibrary.get_engine_version()`을 읽어 결과에 적는다(**확인됨**: `5.8.4-58902052+++UE5+Release-5.8`). `tested_engine`(5.8)과 주 버전이 다르면 경고 한 줄만 남기고 계속한다.
2. 이 스크립트가 쓰는 `unreal`의 이름이 다 있는지 `hasattr`로 본다: `AssetImportTask`, `AssetToolsHelpers`, `EditorAssetLibrary`, `AssetRegistryHelpers`, `MetaSoundBuilderSubsystem`, `MetaSoundEditorSubsystem`, `MetasoundFrontendClassName`, `MetaSoundOutputAudioFormat`, `MetaSoundNodeHandle`.
3. 두 서브시스템이 `None`이 아닌지.
4. 임시 빌더 `OlmuseCheck` 하나를 만들어(저장하지 않고 끝에 등록을 푼다) E2에서 쓰는 노드 클래스 열네 가지를 하나씩 `add_node_by_class_name`으로 넣어 보고, 쓰는 핀 이름을 `find_node_input_by_name`/`find_node_output_by_name`으로 찾아 본다. 결과가 `SUCCEEDED`가 아니면 실패.

소리 가져오기(1·2의 앞 네 이름)는 되고 MetaSound 쪽(나머지)만 안 되면: 소리는 가져오고 동적 소리는 하나도 짓지 않는다. 로그 문구:

- `Olmuse: 이 Unreal 버전(5.x.y)에서는 동적 소리를 만들 수 없어 소리 파일만 가져왔습니다. 없는 것: <이름>. Olmuse에서 다시 내보내거나 Unreal 5.8을 쓰세요.`
- `Olmuse: 이 Unreal 버전(5.x.y)에서는 소리를 가져올 수 없어 아무것도 바꾸지 않았습니다. 없는 것: <이름>.`
- 영어 줄을 바로 밑에 같은 뜻으로 하나 더 남긴다.

모달 창(`EditorDialog`)은 띄우지 않는다. 시작 때마다 막히기 때문이다.

## G. Godot 대응표

Godot 런타임(godot.js)이 하는 일 전부와 Unreal에서의 짝. "같음"은 들리는 결과가 같은 것, "다름"은 결과가 달라지는 것, "뺌"은 Unreal 묶음에 없는 것이다.

| Godot | Unreal | 상태 |
|---|---|---|
| `set_param(id, 값)`, min~max로 자름 | Audio Component의 Set Float Parameter(이름 = `params[].input`, 보통 id 그대로), 그래프 안 Clamp | 같음 (그래프 입력과 Clamp는 **확인됨**, Blueprint 호출은 I3) |
| `set_param`이 표시 이름(대소문자 무시)도 받음 | 입력 이름 하나만. README 표에 입력 이름과 표시 이름을 나란히 적는다 | 다름: 그래프 입력 하나에 이름이 하나다 |
| 파라미터 id에 한글·`.`·`-`가 있어도 그 id로 부름 | 입력 이름은 A3 규칙으로 바꾼 것일 수 있다(README 표에 적힘) | 다름: 영문 밖 그래프 입력 이름은 쿠킹·Blueprint에서 시험하지 않아 쓰지 않는다 |
| 모르는 이름이면 경고 | 모르는 이름일 때의 동작은 엔진이 정한다 | 다름: 경고를 낼 런타임 코드가 없다(C++ 없음) |
| `get_param` | 없음. 값을 넣는 Blueprint가 값을 안다 | 뺌: 되읽기를 줄 런타임 코드를 만들지 않는다(C++ 없음) |
| 신호 `param_changed` | 없음 | 뺌: 값을 바꾸는 쪽이 이미 안다 |
| `play()` / `stop()` / `is_playing()` | Audio Component Play / Stop / Is Playing | 같음 (I3) |
| `play()`·시작 때 페이드 없이 바로 목표 음량 | InterpTo는 첫 목표를 바로 잡는다 *(소스)* | 같음 (귀로는 I3) |
| `stop()`에 페이드아웃 없음 | Stop도 바로 멈춤 | 같음 (I3) |
| `autoplay`(장면에 넣으면 소리 남, 끌 수 있음) | MetaSound를 레벨에 끌어 놓으면 생기는 Ambient Sound의 Auto Activate | 같음 (I3) |
| `bus` 속성(기본 Master) | 기본 출력으로 나감. 바꾸려면 Audio Component 설정 | 같음 |
| `fade_time`, `fade_beats`, `bpm`, `beats_per_bar`를 장면마다 에디터에서 바꿈 | 그래프에 숫자로 박힘. 바꾸려면 Olmuse에서 고쳐 다시 내보냄 | 다름: 그래프 입력을 더 열면 Blueprint 쪽 낱말이 늘어 처음 보는 팀원이 헷갈린다 |
| 인스턴스마다 따로 섞임 | Audio Component마다 따로 | 같음 |
| 위치 없는 소리 | 감쇠를 안 넣으면 2D | 같음 |
| 레이어의 `param`이 그 동적 소리에 없으면 첫 곡선 값(보통 무음) | `param` `null`로 늘 `volume`으로 울림 | 다름: 미리 듣기(늘 울림)에 맞춘다 |
| bed·stem 샘플 단위 동기(`AudioStreamSynchronized`) | 한 그래프 안 Wave Player들을 같은 OnPlay로 시작 | 같음 (동기는 I3에서 귀로) |
| bed·stem 무조건 반복 | Wave Player `Loop` = true | 같음 (**확인됨**) |
| bed·stem 반복은 소리의 `loop` 표시와 상관없음 | Wave Player `Loop`만 켜고 SoundWave `looping`은 건드리지 않음 | 같음 |
| 일반 소리의 반복은 사용자가 Import 탭에서 켬 | SoundWave `looping`을 소리의 `loop`로 넣음 | 다름: Unreal 쪽이 하나 더 해 준다 |
| bed·stem 소리가 모노여도 재생 | Stereo Wave Player에 모노 SoundWave | 같음 (짓기 **확인됨**, Wave Player가 채널을 맞춘다 *(소스)*, 귀로는 I3) |
| 다섯 점 곡선을 dB로 직선 보간 | `on`·`volume`에서 선형 진폭(화면 미리 듣기와 같은 모양) | 다름: 기획안 "듣는 소리와 내보내는 소리가 같아야 한다"를 따라 미리 듣기에 맞춘다 |
| 바닥 −80 dB | 0(무음) | 같음 |
| 페이드 0.8초, 진폭 직선 | InterpTo, 0.8초, 직선 *(소스)* | 같음 (귀로는 I3) |
| 음악: 재생 중 `set_param`을 다음 마디까지 미룸 | TriggerRepeat(마디) + Value 노드 | 같음 (짓기 **확인됨**, 귀로는 I3) |
| 음악: 재생 전 `set_param`은 바로 적용 | Value가 Init Value(재생 전에 넣은 값)로 시작하고 TriggerRepeat가 시작 순간에 한 번 울린다 *(소스)* | 같음 |
| 음악: 페이드 `fade_beats`박 | `fade_seconds` = 박 길이 × 1 | 같음 |
| 음악: 신호 `bar_started`, `music_position()`, `current_bar()`, `bar_length()` | 없음 | 뺌: 그래프 밖으로 마디 신호를 내는 길을 이번에 확인하지 않았고, 런타임 코드(C++)를 만들지 않는다. README가 "마디 신호는 없다"고 적는다 |
| 음악: `stop()`이 밀린 변경을 바로 적용 | Stop이면 그래프가 끝난다 | 뺌: 적용할 대상이 없다 |
| scatter 간격 min_gap~max_gap 무작위, 첫 재생도 한 간격 뒤 | 고정 주기 + 무작위 지연(E2). 간격은 min_gap~max_gap 안이지만 가운데가 잦은 삼각 분포, 첫 재생은 (min_gap+max_gap)/2 ~ max_gap 뒤 | 다름: 고리 없는 그래프로 만들 수 있는 가장 가까운 모양 |
| scatter 피치 무작위 | Pitch Shift 반음 무작위 | 같음 (짓기 **확인됨**, 귀로는 I3) |
| scatter 좌우 무작위(레이어마다 실행 중 버스 + 패너) | 그래프 안 Stereo Panner | 같음, 실행 중 버스는 만들지 않는다 (짓기 **확인됨**, 귀로는 I3) |
| scatter 겹쳐 울림 4개 | Wave Player 하나. 다시 쏘면 앞 소리를 끊고 처음부터 *(소스)* | 다름: 한 그래프에 재생기를 돌려 쓰는 짜임은 이번 범위 밖. 소리가 min_gap보다 길 때만 들린다 |
| scatter 소리가 스테레오여도 재생 | Mono Wave Player에 스테레오 SoundWave | 같음 (짓기 **확인됨**, 채널을 맞춘다 *(소스)*, 귀로는 I3) |
| scatter는 음량 0.0001 이하면 안 쏨 | 쏘되 음량 0을 곱한다 | 같음(들리는 것) |
| scatter 음량은 쏘는 순간에 정해짐 | 울리는 도중에도 음량을 따라감 | 다름 |
| bed·stem 32개 상한 | 동적 소리 하나에 레이어 8개 상한, 넘으면 건너뛰고 README에 적음 | 다름: 8개까지만 시험한다 |
| 건너뛴 레이어를 장면 주석에 남김 | `olmuse_build.json`의 `skipped`, README, 가져오기 결과 | 같음 |
| `layer_target_db`, `layer_current_db`, `eval_curve` (확인용) | 없음 | 뺌: 게임이 쓰는 기능이 아니다 |
| 에디터로 돌아오면 바뀐 파일을 다시 불러옴 | 감시가 다시 가져옴(B1) | 같음 (**확인됨**. PIE 중에는 끝난 뒤로 미룸) |
| 장면·노드 이름 `[A-Za-z0-9_]` | 에셋 이름 A3 규칙 | 같음 |
| `id` 없는 동적 소리·파라미터는 뺌 | 같게 뺌 | 같음 |
| `opts.root`, `opts.prefix` | 없음. 경로는 A1로 고정 | 뺌: Godot 쪽에서도 쓰는 곳이 없다 |

## H. README (`OlmuseAudio/README.md`)

한국어 먼저, 영어 같은 내용 뒤에. 처음 보는 팀원이 5분 안에 소리를 내는 것이 기준이다. 전문 낱말은 Unreal 메뉴에 보이는 이름 그대로만 쓴다. 들어갈 것:
1. 넣는 법: zip 안의 것을 `.uproject` 파일이 있는 폴더에 바로 푼다. 다 풀면 `.uproject` 옆에 `Plugins/OlmuseAudio/OlmuseAudio.uplugin`이 있어야 한다(없으면 한 단계 안쪽 폴더에 풀린 것이니 그 안의 것을 한 단계 위로 옮긴다). 같은 이름의 파일(`CREDITS.md` 등)을 바꿀지 물으면, 그 파일이 Olmuse가 만든 것일 때만 바꾼다. 그다음 에디터를 연다(열려 있었으면 닫고 다시 연다). 결과는 Output Log에서 `Olmuse`로 찾는다.
2. 어디에 생기나: `/Game/Olmuse/Audio`, `/Game/Olmuse/Dynamic`. 이 폴더의 에셋은 Olmuse가 다시 쓰므로 설정을 바꾸지 말고, 쓰는 쪽(Audio Component·Blueprint)에서 바꾼다. 그래프를 손보고 싶으면 복사본을 만들어 고친다.
3. 동적 소리 표: 에셋 이름 | 표시 이름 | 종류 | 파라미터(Blueprint에서 쓸 이름, 표시 이름, 범위, 시작 값) | 레이어 수 | 건너뛴 레이어와 이유.
4. Blueprint로 쓰는 법: MetaSound를 레벨에 끌어 놓기, 또는 Spawn Sound 2D → 반환된 Audio Component에 Set Float Parameter(이름은 표의 "Blueprint에서 쓸 이름"). 첫 동적 소리의 첫 파라미터로 실제 이름을 넣은 예.
5. 소리를 고친 뒤: 게임 폴더를 연결했으면 승인만(에디터를 켜 둔 채로 몇 초 뒤 바뀐다), zip이면 새 zip을 같은 자리에 다시 풀고 에디터 다시 열기.
6. 팀 저장소(git 등)에 넣을 것: `OlmuseAudio/`(소리 파일, 명세, CREDITS), `Plugins/OlmuseAudio/`(그 안의 `imported.json` 포함), `Content/Olmuse/`. 넣지 않을 것: `Saved/`(보통 이미 빠져 있음). 이것들을 같이 올려야 받은 팀원의 에디터가 소리를 다시 가져오지 않는다. Perforce처럼 파일을 잠그는 소스 관리를 켠 프로젝트는 시험하지 않았다는 한 줄.
7. 안 될 때: Output Log의 `Olmuse:` 줄을 본다. 줄이 하나도 없으면 1번의 `.uplugin` 위치부터 본다. Python이 꺼져 있으면 Edit > Plugins에서 "Python Editor Script Plugin"을 켜고 다시 연다. 소리 파일이 OGG·MP3라 가져오지 못했다는 줄이 나오면 Olmuse 내보내기 형식을 WAV로 바꾼다.
8. 음악의 마디 신호는 이 묶음에 없다는 한 줄.
9. 라이선스: 생성된 스크립트는 MIT 조건으로 자유롭게 쓴다. Unreal 내장 기능만 쓴다.

내보내기 형식이 OGG·MP3여도 묶음은 그대로 만든다. 가져오기가 실패한 파일은 결과에 `format_not_imported`로 적고 넘어간다(이 빌드에서 OGG·MP3가 들어가는지는 **미확인**).

## I. 확인

### I0. 이 명세가 기대는 실행 결과

이 PC의 UE 5.8.4에서 돌린 것이다. 위 절들의 **확인됨**은 여기서 나왔다.
1. `init_unreal.py`의 틱 콜백 안에서 가져오기와 MetaSound 짓기·저장이 된다(창 있는 에디터, `-nullrhi` 에디터).
2. 창이 있는 평범한 에디터 시작(`-nullrhi`·`-unattended` 없이)에서 새 플러그인과 가져오기가 대화 상자나 알림을 띄우지 않는다.
3. 실행 중인 에디터는 새로 생긴 플러그인 폴더를 올리지 않는다(15초 뒤에도 init 스크립트가 돌지 않고 켜진 플러그인 목록에 없다). 그래서 처음 한 번은 에디터를 다시 연다(B1, D1).
4. 명령줄·PIE 판별은 D2와 같다. PIE 중에 바뀐 `olmuse_build.json`은 PIE가 끝난 뒤 8초 안에 들어왔다.
5. E2 표의 노드와 핀이 모두 들어가고 이어진다. 레이어 8개 그래프(재생기 8, Clamp·InterpTo 8, 곱하기 16, 좌우 Add 사슬 7씩) 384번 호출이 모두 `SUCCEEDED`이고 저장된다.
6. 모노 WAV는 1채널 SoundWave로 들어온다. Stereo 재생기에 모노, Mono 재생기에 스테레오 웨이브를 넣은 그래프가 지어지고 저장된다.
7. 저장하지 않은 빌더 편집을 `reload_packages`가 되돌린다.
8. MetaSound 에디터에 그 에셋이 열려 있어도 E3의 고쳐 짓기가 된다.
9. `get_engine_version()`이 버전 문자열을 준다.
10. `sys.dont_write_bytecode = True`면 `__pycache__`가 생기지 않는다.
11. A2의 `.uplugin`(PythonScriptPlugin에 `TargetAllowList: ["Editor"]`)을 둔 작은 프로젝트를 `RunUAT BuildCookRun -build -cook -stage -pak`로 패키징하면: 미리 빌드된 `UnrealGame.exe`를 그대로 쓰고(C++ 임시 타깃을 만들지 않음), 쿠킹이 0 오류·0 경고로 끝나며(전체 80초), `/Game/Olmuse`의 SoundWave 4개와 MetaSound 2개가 쿠킹되어 들어가고, `.py` 파일과 Python 실행 파일·라이브러리는 하나도 들어가지 않는다. 엔진이 모든 플러그인의 `.uplugin` 설명 파일을 넣으므로 `PythonScriptPlugin.uplugin` 한 장은 들어간다(다른 에디터 전용 플러그인 설명 파일과 같다). 패키징한 게임은 `-nullrhi`로 켜져 MetaSound 엔진을 올리고 스스로 닫히며, `LogPython` 줄이 하나도 없다.

### I1. 단위 시험 (pytest, Unreal 없이)

`tests/test_asset_unreal_js.py`: `tests/test_asset_gen_js.py`의 `node()` 방식으로 `unreal_py.js`와 `unreal.js`만 Node에서 돌린다. 볼 것:
- 출력 경로 다섯 개가 A1과 같고 `olmuse_build.json`이 마지막이다. README만 `OlmuseAudio/` 아래이고 나머지는 `Plugins/OlmuseAudio/` 아래다. `imported.json`, `Content/`, `Config/` 아래 경로는 나가지 않는다. `window.unrealPy`가 없으면 오류.
- `.uplugin`이 A2와 같은 JSON이고 `Modules`가 없으며 PythonScriptPlugin에 `TargetAllowList: ["Editor"]`가 있다.
- 이름 규칙: `amb_wind` 그대로, `bgm.main`·`sfx-hit`·`한글소리`·`a b`는 해시가 붙고 서로 다르며, 대소문자만 다른 두 id가 다른 이름을 받고, 60자 상한. 동적 소리 id와 파라미터 입력 이름에도 같은 규칙.
- `loop`: bed로 쓰인 `loop: false` 소리가 `loop: false`로 나간다. 소리의 `file`이 `OlmuseAudio/`로 시작한다.
- 음량 숫자, godot.js와 같은 다듬기, `fade_seconds`·`bar_seconds`, `skipped`, 동적 소리 0개, 결정성과 `hash`, README 내용.

`tests/test_asset_unreal_py.py`: `unreal_py.js`에서 두 Python 글자를 Node로 꺼내 임시 폴더에 쓰고 `py_compile`, 가짜 `unreal` 모듈로 `run()`과 감시를 돌린다: 처음·두 번째 실행, WAV 하나 바뀜, 파일 없음, 고쳐 짓기, 사전 점검 실패 둘, 버전 경고, 소리 하나 실패, WAV 아님, 임시 빌더 실패, 첫 짓기 실패, 저장 안 한 편집, 도중 예외에도 기록·결과 파일, 음악 그래프에 고리가 없음, 감시가 같은 파일로 두 번 실패하지 않음, PIE 중 미룸, 감시가 진짜 가져오기를 돌리고 닫힘, 명령줄 실행에서 아무것도 안 함.

`tests/test_asset_gen_js.py`(페이지 시험, WP-D): 엔진 선택 칸에 `unreal` / `Unreal Engine 5`가 있다, 고르면 `bundleFiles`에 `Plugins/OlmuseAudio/olmuse_build.json`과 `OlmuseAudio/game-audio.spec.json`이 들어가고 맨 위에 `game-audio.spec.json`·`audio/`가 없다, `window.unrealExport`가 없으면 `bundleFiles`가 오류를 낸다, 그 zip을 다시 열 때 `.py`·`.uplugin`이 "건너뜀"으로 세지지 않는다, 맨 위에 `Content/`·`Saved/`가 있는 폴더를 읽을 때 그 아래를 읽지 않고 `OlmuseAudio/`의 소리는 읽는다, 폴더에 쓰기 전에 Olmuse가 쓰지 않은 같은 이름 파일이 있으면 멈춘다. `PAGE_FILES`와 `tests/test_asset_quote_js.py`의 스크립트 이름 목록에 `unreal_py.js`, `unreal.js`를 `godot.js` 다음에 더한다. 바꾼 뒤 `python tools/stamp_assets.py`.

### I2. 헤드리스 Unreal 시험 (이 PC, pytest가 모으지 않음)

`tools/unreal_check.py [--work 폴더] [--prepare-only]`. 엔진 경로는 env `OLMUSE_UE_CMD`, 없으면 `C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe`. Unreal 실행은 한 번에 하나, 실행마다 600초 상한이고 넘으면 자기가 띄운 프로세스 나무만 끈다. 전체 실행 수는 3번이다.

준비(Unreal 없이): 작업 폴더를 비우고 빈 프로젝트(`"Plugins":[]`인 `.uproject`)와 그 프로젝트 자신의 `Content/Python/init_unreal.py`(마커 파일 하나를 쓰는 것)를 만들고, 고정 입력(일반 소리 4개 — 한글 id 하나, `.`가 든 id 하나, 모노 하나 — 환경음 동적 소리 하나: bed 2 + scatter 1, 음악 동적 소리 하나: stem 2, 한글 id 파라미터)으로 Node에서 `unreal.js`를 돌려 파일을 쓰고, Python `wave`로 48 kHz 16비트 WAV를 `OlmuseAudio/audio/`에 만든다.

1. **명령줄 가져오기:** `-run=pythonscript -script=<Plugins/OlmuseAudio/Content/Python/olmuse_unreal.py> -unattended -nosplash -stdout`. 종료 코드 0, `last_import.json`의 ok, 소리 4개·MetaSound 2개.
2. **확인과 두 번째 가져오기:** 검사 스크립트가 (가) 지금 상태를 읽고 (나) `olmuse_unreal.run()`을 한 번 더 부르고 (다) 다시 읽는다. 판정:
   - SoundWave 4개가 A3 이름으로 있고, `loop`인 것만 `looping True`, 모노 WAV는 1채널.
   - MetaSound Source 2개, `get_graph_input_names()`가 입력 이름 집합 + `UE.Source.OnPlay`, 기본값이 `default`와 같다, `OlmuseNodes`가 비어 있지 않다.
   - 텍스트 내보내기(`AssetExportTask` + `ObjectExporterT3D`)의 노드 수·연결 수.
   - 두 번째 `run()`은 가져온 소리 0, 고친 동적 소리 0, 에셋 목록·노드 수·`.uasset` 파일(이름, 크기, 시각)이 (가)와 같다.
3. **에디터 시작과 감시:** WAV 하나를 다른 길이로, 다른 WAV 하나를 WAV가 아닌 바이트로 바꾸고, 환경음 레이어 하나의 음량을 바꾼 뒤 평범한 에디터 시작(`-nosplash -nullrhi -stdout`, Python 플래그 없음, `OLMUSE_QUIT_AFTER=2`)으로 띄운다. 첫 가져오기 결과(`watch_run_1.json`)가 보이면 음악 파라미터의 기본값을 바꿔 감시가 두 번째로 가져오게 한다. 판정: 스스로 닫힘, 바뀐 WAV 하나만 다시 가져옴(길이 바뀜, `looping` 유지), 덮은 WAV는 `failed`이고 옛 에셋과 기록의 옛 해시가 그대로, 바뀐 동적 소리 하나만 고쳐 지음(Olmuse 노드 수·입력 그대로, 텍스트 내보내기 수는 늘지 않고 주는 것은 파라미터 수 이하, E3), 두 번째 가져오기는 음악 동적 소리만 고치고 새 기본값이 그래프에 있음, 프로젝트 자신의 `init_unreal.py` 마커가 있음, 플러그인에 `__pycache__`가 없음.

패키징(I0-11)은 이 도구에 넣지 않는다. 한 번에 1~2분이고 엔진 설치마다 SDK가 달라 늘 돌릴 시험이 아니다. `.uplugin` 모양을 바꿀 때 손으로 다시 돌린다: 1번 뒤의 작업 폴더에 `Config/DefaultGame.ini`로 `[/Script/UnrealEd.ProjectPackagingSettings]` `+DirectoriesToAlwaysCook=(Path="/Game/Olmuse")`를 두고 `RunUAT.bat BuildCookRun -project=<.uproject> -platform=Win64 -clientconfig=Development -build -cook -stage -pak -archive -archivedirectory=<폴더> -unattended -nop4 -nocompileeditor -skipbuildeditor`, 그다음 `Manifest_UFSFiles_Win64.txt`에 `.py`가 없고 `Content/Olmuse/`가 있는지 본다.

### I3. 사람이 귀와 눈으로 확인할 것 (에디터 창에서)

- bed·stem 반복 지점에서 딸깍 소리가 없는지.
- `intensity`를 0→1로 움직일 때 레이어가 미리 듣기와 같은 모양으로 들어오고 빠지는지, 0.8초 부드럽게가 들리는지.
- 음악에서 값을 바꾸면 다음 마디에 바뀌는지, stem들이 어긋나지 않는지.
- scatter가 간격·피치·좌우를 무작위로 바꾸며 울리는지, 다시 쏠 때 끊기는 소리가 거슬리지 않는지.
- 모노 소리를 bed로, 스테레오 소리를 scatter로 쓴 것이 제대로 들리는지.
- PIE에서 Blueprint의 Set Float Parameter가 실제로 소리를 바꾸는지, Ambient Sound로 놓은 것이 시작 때 울리는지.
- 고쳐 지은 MetaSound를 MetaSound 에디터에서 열어 깨진 핀이나 빈 입력 노드가 없는지(E3).
- 패키징한 게임에서 소리가 나는지(쿠킹·패키징은 I0-11에서 됨, 소리는 듣지 않음).

### I4. 뺀 것

- 헤드리스로 소리를 녹음해 듣기 판정: `spawn_sound2d`로 틀면 `is_playing`은 True이고 `AudioMixerLibrary`의 녹음이 WAV를 쓰지만 모든 표본이 0이다(`UnfocusedVolumeMultiplier=1.0`을 줘도). PIE 월드에서는 `spawn_sound2d`가 None을 준다. 들리는 결과는 I3에서 사람이 본다.
- MetaSound 에디터의 손 편집이 "저장 안 함"으로 잡히는지: 창에서 손으로 고치는 실행을 자동으로 만들 수 없다. 점검(E1)은 두되 README 경고가 주된 보호다.
- 음악 마디 신호, `get_param`, `param_changed`: G절. 그래프 밖으로 값을 내는 런타임 코드(C++)를 만들지 않는다.
- scatter의 균일 분포 간격: 빌더가 고리를 막지 않아 고리 그래프는 짓기는 되지만 엔진이 고리를 어떻게 도는지 확인할 수 없어 쓰지 않는다. 삼각 분포로 바꿨다(G절).
- OGG·MP3 가져오기: 묶음 시험은 WAV만 쓴다. 실패하면 `format_not_imported`로 적힌다.
- `.uproject`가 PythonScriptPlugin을 명시적으로 끈 경우와 Perforce 같은 잠금 소스 관리.

## J. 작업 묶음

두 작업자가 같은 파일을 고치지 않는다.

| 묶음 | 하는 일 | 파일 |
|---|---|---|
| WP-B 묶음 데이터 | `unreal.js`: 경로, `.uplugin`, `olmuse_build.json` 계산(C절, 이름 규칙 A3), README(H절). `window.unrealPy`의 두 글자를 그대로 파일로 내놓는다 | `studio_frontend/asset_studio/unreal.js`, `tests/test_asset_unreal_js.py` |
| WP-C 가져오기 스크립트 | `unreal_py.js`: `window.unrealPy = { INIT, IMPORTER }`, Python 글자를 `String.raw`로. D·E·F절 | `studio_frontend/asset_studio/unreal_py.js`, `tests/test_asset_unreal_py.py` |
| WP-D 화면 연결 | B절의 app.js 변경, index.html 스크립트 두 줄, 시험 두 곳의 스크립트 목록과 I1의 페이지 시험, `python tools/stamp_assets.py`, WORK_PLAN 6-6에 Unreal을 한 줄로 적기 | `studio_frontend/asset_studio/app.js`, `studio_frontend/asset_studio/index.html`, `tests/test_asset_gen_js.py`, `tests/test_asset_quote_js.py`, `docs/WORK_PLAN.md` |
| WP-E 헤드리스 시험 | I2. 고정 입력, 빈 프로젝트 만들기, Unreal 실행 3번, 판정 | `tools/unreal_check.py` |

끝난 기준: I1이 모두 통과하고, I2의 세 실행이 모두 통과하고, I3을 사람이 확인해야 한다고 대화로 알린다.
