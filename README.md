# strudel 딸깍이

코드를 보지 않고 자연어로 Strudel 음악을 만드는 작업실이다. 기존 아케이드와 BLACK BOX 09는 설정 → 게임하기에 있다.

## 실행

```powershell
pip install -r requirements.txt
$env:GEMINI_API_KEY = '내 키'
.
un_local.ps1
```

키가 없으면 `run_local.ps1`은 로그인된 Antigravity CLI(`agy`)로 코드를 수정한다. CLI에는 오디오 입력이 없어서 `ear.py`가 실제 캡처를 측정한 템포·음·대역 표를 대신 넘긴다. 결과는 "측정 분석"으로 표시한다. `STRUDEL_ENGINE=agy`로 강제할 수 있다. AI 없이도 재생, 믹서, 저장은 동작한다.

## Streamlit Cloud 배포

share.streamlit.io에서 이 저장소의 `main`, `app.py`를 연결하고 Secrets에 아래를 넣는다.

```toml
GEMINI_API_KEY = "..."
STUDIO_PASSWORD = "..."
```

학교 Gemini 키는 `SCHOOL_GEMINI_API_KEY`로 넣는다(Secrets, 로컬은 `~/.all-tomorrow/key-pool.env`). 둘 다 있으면 학교 키를 먼저 쓴다.

Claude는 `ANTHROPIC_API_KEY`로 넣는다(기본 모델 `claude-sonnet-5-5`, `CLAUDE_MODEL`로 변경). `AI_PROVIDER=claude` 또는 `gemini`로 고를 수 있고, 지정이 없으면 학교 Gemini, Gemini, Claude 키 순으로 쓴다. Claude와 agy에는 오디오 입력이 없어 `ear.py` 측정표로 판단하며 "측정 분석"으로 표시한다.

`STUDIO_PASSWORD`가 없으면 공개 URL에서 키가 쓰이지 않도록 AI가 꺼진다. 선택 값은 `GEMINI_MODEL`, `STRUDEL_DAILY_CALLS`다.

프로젝트는 브라우저에 저장되므로 다른 기기로 옮길 때는 프로젝트 내보내기와 파일 불러오기를 쓴다.

## 시험

```powershell
python -m pytest -q tests
python tests/e2e_studio.py
```

## 코드 직접 수정

상단의 코드 버튼(Ctrl+E)에서 곡 전체를 편집한다. Ctrl+Enter로 실행하고, 실행에 실패하면 트랙과 줄을 표시하고 적용하지 않는다.

## 라이선스

`studio_frontend/vendor/strudel.js`는 [Strudel](https://codeberg.org/uzu/strudel)의 번들이며 AGPL-3.0이다(`STRUDEL-LICENSE`). 배포 시 소스 공개 조건이 적용된다. `vendor/editor.js`는 CodeMirror 6(MIT) 번들이다. 샘플은 실행할 때 tidalcycles/dirt-samples에서 불러오며 저장소에 포함하지 않는다.

---

# 기존 게임 안내

# YOUR ARCADE — Godot HTML 게임 자동 등록 Streamlit 앱

GitHub의 `static/games/` 밑에 게임 폴더를 통째로 넣으면 사이트에서 자동 검색해서 목록에 띄웁니다. 업로드 UI나 DB는 없습니다. **BLACK BOX 09** 규칙 추론 게임도 사이드바에서 계속 플레이할 수 있습니다.

## 게임 추가 방법 (이것만 하면 됩니다)

1. Godot에서 **Web(HTML5)** 형식으로 내보냅니다. 가능하면 `Thread Support`를 끈 **싱글 스레드** 빌드를 사용하세요.
2. 생성된 HTML, JS, WASM, PCK, PNG 등 파일을 **이름을 바꾸지 않고** 한 폴더 안에 넣습니다.
3. 폴더 통째로 `static/games/내게임이름/`에 복사한 후 GitHub에 커밋/푸시합니다.
4. Streamlit Community Cloud의 배포가 완료되면 게임 카드가 자동으로 생깁니다. 앱 소스 수정은 필요 없습니다.

```text
your-repository/
├── app.py                     # Streamlit 진입점
├── arcade_page.py             # 게임 목록 + 플레이어
├── blackbox_page.py           # BLACK BOX 09 (기존 게임)
├── catalog.py                 # 자동 파일 탐색 로직
├── engine.py                  # BLACK BOX 09 추론 엔진
├── requirements.txt
├── .streamlit/
│   └── config.toml            # [server] enableStaticServing=true
└── static/
    └── games/
        ├── demo-switchboard/  # 포함된 HTML 테스트 게임, 삭제 가능
        │   ├── index.html
        │   ├── cover.svg
        │   └── game.json
        ├── 내첫번째게임/
        │   ├── index.html
        │   ├── index.js
        │   ├── index.wasm
        │   ├── index.pck
        │   └── index.png
        └── 내두번째게임/
            ├── MyGame.html
            ├── MyGame.js
            ├── MyGame.wasm
            └── MyGame.pck
```

**중요:** `index.html`이 아니라 `MyGame.html`처럼 다른 이름이어도 자동으로 찾습니다. 폴더 안에 `build/` 같은 한 단계 더 깊은 내보내기 경로가 있어도 찾습니다. 원본 내보내기 파일명이나 위치를 임의로 바꾸지 마세요.

### 선택 사항: 게임명, 소개, 커버 지정

`static/games/내게임이름/game.json` 파일을 추가하면 메타데이터를 표시할 수 있습니다. 없어도 폴더명으로 카드가 자동 생성됩니다.

```json
{
  "title": "나의 게임",
  "description": "두 명이 협력하여 물건을 찾는 퍼즐 게임",
  "genre": "협동 퍼즐",
  "tags": ["2인", "퍼즐"],
  "entry": "index.html",
  "cover": "cover.png",
  "height": 720,
  "order": 10
}
```

- `entry`: **선택**. HTML이 여럿일 때 사용할 진입점. 생략 시 자동 선택.
- `cover`: **선택**. 폴더 내부의 이미지 파일. 생략 시 `cover.png`, `thumbnail.jpg`, `icon.png` 등을 탐색하거나 기본 커버 사용.
- `height`: 임베드 높이(px), 기본 700 / 420~1200으로 제한.
- `order`: 정렬 순서, 숫자가 작을수록 먼저 나옴.
- `hidden: true`: 폴더를 남겨 두고 목록에서만 숨김.

## Streamlit Community Cloud 배포

1. GitHub 저장소에 이 프로젝트의 모든 파일을 올립니다 (숨김 폴더 `.streamlit/` 포함).
2. https://share.streamlit.io/ 에서 저장소를 연결합니다.
3. **Main file path** 를 `app.py`로 지정합니다.
4. 배포되면 `/`는 자동 아케이드, 사이드바에서 `BLACK BOX 09`로 전환할 수 있습니다.

로컬 실행:

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## 기술적 주의사항

- **Godot 4.3 이상 싱글 스레드 Web 내보내기를 권장합니다.** 멀티스레드 빌드나 웹 GDExtension 활성화 빌드에는 COOP/COEP 교차 출처 격리 헤더가 필요할 수 있습니다. Streamlit의 기본 정적 파일 서버가 이를 직접 설정하는 방식은 제공하지 않으므로 그런 빌드는 별도 호스팅이나 Godot PWA 서비스워커 우회 설정이 필요할 수 있습니다.
- HTML을 실행하는 서버와 WASM/PCK/JS가 같은 출처 및 같은 경로 계층에 있어야 합니다. 이 프로젝트는 Streamlit의 **정적 파일 서빙** 기능(`/app/static/games/...`)을 사용해 해결합니다.
- 큰 `.wasm`/`.pck` 파일을 많이 GitHub에 넣으면 GitHub 용량 및 Streamlit Community Cloud 리소스 제한에 걸릴 수 있습니다. 이 방법은 소수~중간 규모의 게임 보관함에 적합합니다.
- **게임 파일은 신뢰할 수 있는 것만 올리세요.** 같은 출처에서 실행되는 HTML/JS이므로 공개된 앱의 정적 페이지에서 실행됩니다.
- 저장소에 파일을 커밋/푸시해야 영구적으로 배포됩니다. 로컬 파일을 Streamlit 앱에 단순 업로드하는 방식은 아닙니다.
- 개발 중 문제가 있으면 게임을 새 창으로 열어 브라우저 개발자 도구의 Network/Console에서 404, WASM MIME, SharedArrayBuffer 오류를 확인하세요.

## 검증

```bash
python -m pip install pytest
python -m pytest -q
```

공식 문서:
- Streamlit static file serving: https://docs.streamlit.io/develop/concepts/configuration/serving-static-files
- Godot 4.5 Web export: https://docs.godotengine.org/en/4.5/tutorials/export/exporting_for_web.html

## 내 PC에서 공개

`run_public.ps1`은 `~/.all-tomorrow/key-pool.env`의 키와 `STUDIO_PASSWORD`로 서버를 띄우고 Cloudflare 임시 터널을 연다. 주소는 실행할 때마다 바뀌고, PC가 켜져 있고 이 터미널이 살아 있는 동안만 접속된다. 일일 호출 한도는 200회다. 코드를 고친 뒤 주소를 유지하려면 `run_public.ps1 -ServerOnly`로 앱만 재시작한다.
