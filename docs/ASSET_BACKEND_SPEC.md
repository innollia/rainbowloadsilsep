# 에셋 작업실 생성 백엔드 명세

에셋 작업실(`studio_frontend/asset_studio/`)의 소리 생성, 전송, 요금, 측정을 정한다. 일의 순서와 끝난 기준은 [GAME_ASSET_PLAN](GAME_ASSET_PLAN.md) 8절의 순서 4~6, 화면 규칙은 [UI_LESSONS](UI_LESSONS.md)를 따른다.

전제:
- 보드, 버전, 소리 바이트는 브라우저 IndexedDB에만 있다. 서버는 보드를 갖지 않고 생성 결과만 만료 때까지 둔다. 만료 뒤에는 다시 받을 수 없다.
- 생성과 소리 전송은 FastAPI HTTP로만 한다. Streamlit은 서명 토큰을 에셋 작업실 iframe에 넘기는 일만 한다.
- 에이전트 호출(`asset_agent.py`)은 그대로 두고 생성 작업과 분리한다. 생성 작업 하나는 소리 하나의 시안 하나다.
- `game-audio.spec.json`은 지금 화면이 내보내는 모양 그대로다. 버전 레코드는 보드 스냅샷에만 있다.
- `analyze_audio.py`는 읽지도 고쳐 쓰지도 않는다.
- 새 창, 패널, 줄, 단추를 만들지 않는다. 화면 변화는 기존 요소의 글자와 `#toast` 문구뿐이다.

## A. 프로세스와 배포

- **파일(저장소 루트, 모두 streamlit을 import하지 않는다):** `asset_token.py`(서명, 검증, 호스트 도우미), `asset_jobs.py`(저장소, 요금, 큐, 작업자, 청소기), `asset_generate.py`(프롬프트, 묻기·렌더·다듬기·측정·고치기 루프, `FakeModel`, `FakeEngine`), `asset_api.py`(`create_app(deps)`와 모듈 수준 `app`).
- **프로세스:** `python -m uvicorn asset_api:app --host 127.0.0.1 --port 8502 --workers 1 --no-access-log`. 큐가 메모리에 있으므로 worker는 1개다. `/docs`와 `/openapi.json`은 끈다.
- **설정:** env, 그다음 `~/.all-tomorrow` 파일에서 읽는다. `st.secrets`는 읽지 않는다.

| 이름 | 기본값 |
|---|---|
| `OLMUSE_GEN_BASE_URL` | `sb.OpenRouter.URL` (나중에 LiteLLM 프록시 주소) |
| `OLMUSE_GEN_KEY` | env `OPENROUTER_API_KEY`, 없으면 `key-pool.env`의 같은 이름 (`tools/akkado_trial.py`의 `key()`와 같은 읽기) |
| `OLMUSE_GEN_MODEL` | `sb.DEFAULT_CHOICE` |
| `STRUDEL_CREDITS_URL`, `STRUDEL_CREDITS_TOKEN` 또는 파일 `strudel-credits.token`, `strudel-credits.pepper`, `STRUDEL_LOCAL_LEDGER` | `credits.open_ledger`에 넘긴다 |
| `OLMUSE_GEN_DB` | `.studio-data/asset-gen.db` (API 전용. `jobs.sqlite3`는 열지 않는다) |
| `OLMUSE_RENDERS` | `.studio-data/asset-renders` |
| `OLMUSE_API_HOSTS` | `olmuse.app,127.0.0.1:8502,localhost:8502` |
| `OLMUSE_API_ORIGINS` | `https://olmuse.app` |
| `OLMUSE_ASSET_TOKEN_SECRET` | 없으면 파일 `.studio-data/asset_token.key` |
| `OLMUSE_NODE` | `node` |
| `OLMUSE_GEN_FAKE` | 없음. `1`이면 대본 모델과 사인파 엔진을 쓴다 |
| 한도 | E절 표 |

- **`run_api.ps1`(새 파일):** `while ($true)` 루프. 8502가 이미 듣고 있으면 5초 쉬고 다시 본다. 아니면 uvicorn을 띄우고, 끝나면 2초 뒤 다시 띄운다. 콘솔은 `.studio-data\logs\api\console.out.log`, `console.err.log`.
- **`run_public.ps1`:**
  - 전체 실행은 API를 멈추지 않는다. 명령줄에 `run_api.ps1`이 든 powershell 프로세스가 하나도 없을 때만 `Env:OLMUSE_GEN_FAKE`를 지우고 `run_api.ps1`을 숨김 창으로 띄운다. 서버 감시가 이 스크립트를 다시 돌려도 진행 중인 유료 작업이 죽지 않는다.
  - 새 스위치 `-ApiOnly`만 `run_api.ps1` 루프와 8502 리스너를 멈추고 다시 띄운 뒤 끝낸다. `-ServerOnly`는 지금처럼 Streamlit만 다시 띄운다.
- **Cloudflare ingress(운영자 단계):** `~/.cloudflared/olmuse.yml`의 기존 hostname 규칙 앞에 아래를 넣고 터널을 다시 띄운다. 접두사는 벗기지 않는다. iframe이 같은 출처라 운영에서는 CORS가 필요 없다.
  ```
  - hostname: olmuse.app
    path: ^/api/asset/
    service: http://127.0.0.1:8502
  ```
  확인: `cloudflared tunnel --config <yml> ingress validate`, `cloudflared tunnel --config <yml> ingress rule https://olmuse.app/api/asset/health`.
- **서버 감시(운영자 단계):** all-tomorrow의 `olmuse` 감시는 `https://olmuse.app/_stcore/health`만 본다. `https://olmuse.app/api/asset/health`를 감시 대상에 더한다. 죽은 API는 `run_api.ps1` 루프가 살린다.
- **로컬 개발:** `run_local.ps1`이 API도 띄우고 `OLMUSE_API_ORIGINS=http://127.0.0.1:8501,http://localhost:8501`을 준다. 토큰 메시지의 `api`는 로컬에서 `http://127.0.0.1:8502/api/asset`, 운영에서 `/api/asset`이다. 출처 목록에 olmuse.app이 아닌 항목이 있을 때만 CORS 미들웨어를 붙인다.
- **상태 확인:** `GET /api/asset/health`, 인증 없음. `{ok, model, engine, node, ledger, queued, running, disk_free_mb}`. 참·거짓과 개수만 담는다.
- **로그:** `server_ops.setup_logging(".studio-data/logs/api")`. Streamlit의 `logs/olmuse.log`와 다른 폴더라 자정 회전이 서로를 막지 않는다. 이메일, 토큰, 키, 요청 글, 모델 원문은 로그에 쓰지 않는다.
- **다른 서버로 옮길 때:** env와 리버스 프록시의 경로 규칙 하나(`/api/asset/` → 8502)를 옮긴다. `nkido.run_caged`는 Windows 작업 개체를 쓰므로 Linux에서는 같은 제한(시간, 메모리, 자식 프로세스 금지)을 새로 써야 하고 nkido의 Linux 빌드와 Node가 필요하다. 이 명세의 범위 밖이다.

## B. 토큰

- **모양:** `b64url(JSON payload) + "." + b64url(HMAC-SHA256(secret, payload 부분))`. 표준 라이브러리만 쓴다.
- **비밀:** `OLMUSE_ASSET_TOKEN_SECRET`, 없으면 `.studio-data/asset_token.key`(난수 32바이트, 먼저 뜬 프로세스가 배타 생성). 읽지도 만들지도 못하면 API는 뜨지 않는다.
- **payload:** `{v:1, aud:"asset", kind:"acct"|"pw", sub, email?, lang, iat, exp}`, `exp = iat + 900`.
  - `acct`: `sub = jobs().store.owner(email)`(`acct:<key>`). 장부 Lambda가 이메일로만 차감하므로 `email`을 넣는다. API는 이메일을 메모리에만 둔다.
  - `pw`(선생님 비밀번호 또는 `LOCAL_AI`): `sub = "pw:" + st.session_state.studio_owner`, 이메일 없음.
- **작업의 주인(`owner`):** `acct`는 `sub` 그대로다. `pw`는 `"pwip:" + hex(HMAC-SHA256(secret, 접속 IP))[:16]`이다. 접속 IP는 소켓 상대가 127.0.0.1일 때만 `CF-Connecting-IP` 헤더, 아니면 소켓 상대 주소다. `studio_owner`는 새로고침마다 바뀌므로 한도에 쓰지 않는다. 한 교실은 한 묶음이 된다.
- **작업 접근:** `acct` 작업은 `owner == sub`일 때만 보인다. `pw` 작업은 128비트 작업 id를 내는 모든 `pw` 토큰이 읽고 받고 취소한다.
- **발급:** `ai_ready`일 때만. `asset_token.session_token(state, kind, sub, email, lang, now)`가 `st.session_state`에 토큰을 두고, 남은 시간이 300초 미만이거나 `kind`·`sub`가 바뀌면 다시 서명한다. `render()`는 `asset_token={token, ttl, api}`를 넘긴다. `ttl`은 서버 시계로 잰 남은 초다.
- **iframe으로:** 호스트 `studio_frontend/app.js`가 `{type:'asset:token', token, ttl, api}`를 `targetOrigin = location.origin`으로 보낸다. 보내는 때는 `asset:ready`를 받았을 때, 토큰 문자열이 바뀌었을 때, `asset:token?`을 받았을 때다. 기존 메시지는 `'*'`를 쓰지만 이 메시지는 쓰지 않는다.
- **iframe 안:** `e.source === parent && e.origin === location.origin`인 메시지만 받는다. 토큰은 메모리에만 두고 `Authorization: Bearer`로 보낸다. payload를 풀어 `kind`와 `sub`만 읽는다.
- **갱신:** 프레임은 토큰을 받은 순간의 `performance.now()`를 적고, 거기서 `ttl - 60`초가 지나면 `asset:token?`을 보낸다. `exp`를 `Date.now()`와 비교하지 않는다(브라우저 시계가 틀려도 된다).
  - 401을 받으면 `asset:token?`을 보내고 문자열이 다른 토큰을 10초까지 기다려 한 번 다시 보낸다. 그래도 401이거나 토큰이 오지 않으면 멈춤 상태가 된다.
  - 멈춤 상태에서는 폴링을 쉬고(타일은 작업 중 그대로) 새 생성을 받지 않으며 토스트 `genPaused`를 한 번 띄운다. 새 토큰이 오면 풀린다. 서버의 작업은 계속 돈다.
- **잔액 표시(호스트):** `asset_token.adopt_credits(state, job_snap, agent_view)`가 작업·에이전트 보기의 `credits`를 `studio_account`에 옮기되 보기마다 한 번만 옮긴다(작업은 `(id, calls)`, 에이전트는 `n`을 `state`에 기억). `render()`는 지금의 두 덮어쓰기 대신 이 함수를 부른다. 프레임의 `asset:account`가 부른 `account` 액션의 새 잔액이 다음 실행에서 옛 값으로 돌아가지 않는다.

## C. HTTP API (접두사 `/api/asset`)

**공통**
- `/health`를 뺀 모든 요청에 Bearer 토큰이 필요하다.
- 검사 순서: Host 허용 목록(403 `bad_host`) → POST의 `Origin` 허용 목록(403 `bad_origin`) → `Content-Length` 1 600 000바이트 초과(413 `too_large`) → 토큰(401 `no_token`, `bad_token`, `token_expired`) → 요청 한도(429 `rate`) → 본문을 상한까지만 읽기(413) → JSON 객체(400 `bad_request`, `{field}`).
- 오류는 항상 `{"error": {"code", "message", ...extras}}`. `message`는 토큰의 언어로 쓰고 `sb.msg` 키가 있으면 그것을 쓴다. 500은 `{"error":{"code":"internal","message"}}`이고 추적 정보가 없다.
- 모든 응답에 `Cache-Control: no-store`. 429에는 `retry_after`(초)와 `Retry-After` 헤더를 넣는다.
- 요청 한도(메모리, 분당): `owner`별 생성+취소 10, 견적 30, 상태 120, 소리+스템 600. 인증에 실패한 요청은 IP별 60까지 401을 받고 넘으면 429다. 인증된 요청은 IP로 세지 않는다.

**엔드포인트**
1. `GET /health`: A절.
2. `GET /quote?items=N&drafts=D`(`items` 1..64, `drafts` 1..4) → 200 `{items, drafts, unit, credits, free, balance|null, left_today, room, ok, reason|null}`. `free`는 `pw`에서 참이다. `room`은 이 주인이 지금 더 넣을 수 있는 작업 수다. `ok:false`면 `reason`에 3번 표의 코드가 온다. 잔액은 E절의 캐시에서 온다.
3. `POST /jobs`:
   ```
   {request_id (클라이언트 uuid, <=64), expect_credits (정수, 필수), drafts: 1..4, lang,
    project: {game (<=200), style (<=1000), platform: "mobile"|"console"|"wide", loud: [lo, hi]},
    examples: [{name (<=80), kind, loop, source (<=4000), facts}],          // <=3, 승인된 소리
    items: [{ref (브라우저 에셋 key, <=40), mode: "make"|"revise", kind: "sfx"|"amb"|"music", loop,
             id (<=64), name (<=80), when (<=300), description (<=2000), seconds|null, bpm|null,
             references: [...],                                             // sb.clean_references, <=8
             style_ref: {name (<=80), seconds, loop, facts} | null,
             base: {source (<=20000), seconds, bpm} | {facts} | null, change (<=2000)}]}   // <=64
   ```
   - `facts`는 G절 측정 필드 이름의 숫자만 남긴다. 모르는 키는 버리고, 타입이 틀리면 400이다.
   - 작업 하나의 프롬프트에 들어가는 `REQUEST`(project + examples + item 하나)의 직렬화 길이는 48 000자 이하다. 넘으면 413 `too_large` `{ref}`.
   - 작업 수는 `items x drafts`이고 `room` 이하여야 한다.
   - 200: `{batch, replayed, quote:{items, drafts, unit, credits, free}, jobs:[{id, ref, k, n, status:"queued"}]}`.
   - 같은 `(owner, request_id)`가 다시 오면 처음의 응답을 그대로 돌려주고 아무것도 만들지 않는다(`replayed:true`). 본문 sha256이 다르면 409 `request_mismatch`. 취소 표식이 있으면 410 `request_cancelled`.
   - 거절은 전부 아니면 전무다.

| 상태 | code | extras |
|---|---|---|
| 402 | `no_credits` | `{balance, credits}` |
| 409 | `quote_changed` (`expect_credits`가 서버 견적과 다름. 0과 유료의 차이도 포함) | `{quote}` |
| 429 | `daily_limit`, `account_limit`, `session_limit`, `operator_limit` | `{left_today}` |
| 429 | `too_many_active` | `{room}` |
| 429 | `fetch_first` (받지 않은 결과가 주인 몫을 채움), `refund_limit`, `rate` | `{retry_after}` |
| 503 | `busy`, `no_model`, `no_engine`, `no_ledger` | |

4. `POST /jobs/status`: 본문은 `{ids:[<=256]}` 또는 `{request_id}`.
   - `ids` → 200 `{credits|null, jobs:[view]}`. `credits`는 캐시의 잔액이다. 이 엔드포인트는 장부를 부르지 않는다.
   - `request_id` → 200 `{known, cancelled, jobs:[view]}`. 그 요청을 받은 적이 없으면 `known:false`.
   ```
   view = {id, ref, k, n, batch,
           status: "queued"|"running"|"done"|"failed"|"cancelled"|"gone"|"forbidden"|"unknown",
           stage: "writing"|"rendering"|"checking"|"fixing", attempt, position, progress (0..1),
           error: {code, message}, refund: "none"|"pending"|"done", expires (epoch 초), result}
   result (받기 전) = {seconds, rate: 48000, channels, bits, bytes, sha256, stems: [{n, bytes, sha256}]}
   result (받은 뒤) = 위 + {engine: "nkido", model, prompt, source, bpm, stems[].label, measure,
                          issues: [{id, level, value, limit}], repairs, sources: [{name, license, holder, use}]}
   ```
   - `forbidden`: 행은 있으나 주인이나 종류가 다르다. `gone`: 바이트를 지운 뒤의 흔적 행이며 `refund`가 `done`(환불됨) 또는 `none`(받아 간 결과)이다. `unknown`: 행이 없다. 이 셋은 `{id, status, refund}`만 담는다.
   - 받기 전에는 `source`, `prompt`, 스템 이름, `measure`를 주지 않는다. 소리 파일을 내주기 시작한 뒤에만 준다.
5. `GET /jobs/{id}/sound` → 200 `audio/wav`, 파일 전체, `ETag: <sha256>`, `X-Content-Type-Options: nosniff`. `Range`는 무시하고 `Accept-Ranges`를 보내지 않는다. 오류: 409 `not_ready`, 404 `not_found`, 403 `forbidden`.
   - 본문을 내보내기 전에 `update gen set delivered=? where id=? and status='done' and delivered is null`로 받음 표시를 하고, 같은 문장에서 `charge`가 `charged`면 `kept`로 바꾼다. 이 갱신과 D절의 미수령 만료 갱신은 같은 행에서 하나만 이긴다. 받은 뒤에도 만료 전에는 다시 받을 수 있다.
6. `GET /jobs/{id}/stems/{n}`: 5번과 같다. 번호로 고르고, 스템 하나만 받아도 받음 표시가 된다.
7. `POST /jobs/cancel`: `{ids}` 또는 `{request_id}` → 200 `{jobs:[view]}`. 멱등이다. 생성 한도에 같이 센다. 받은 적 없는 `request_id`면 취소 표식을 남겨 늦게 도착한 원래 POST가 410을 받게 한다.

린트, 받음 확인(ack), 무료 재렌더 엔드포인트는 없다.

## D. 생성 작업의 일생

- **상태:** `queued -> running (writing -> rendering -> checking -> [fixing -> rendering -> checking] 최대 2번) -> done | failed | cancelled`. 바이트를 지우면 행은 `gone`이 된다.
- **id:** 서버가 만든 128비트 난수. 폴더 이름으로도 쓴다.
- **루프**(`asset_generate.run(job, deps, report)`), `REPAIRS = 2`, 모델 호출은 최대 3번:
  1. **묻기.** 작업마다 `sb.OpenRouter(key, model, effort="low", base_url=..., system=<asset_engine/akkado_guide.md>, timeout=min(120, 남은 시간))` 하나(`last_usage`가 인스턴스별이다). 추론 강도는 `low`로 고정한다. 기본 강도에서는 답이 잘리는 일이 있었고 요청당 시간이 2.7배였다(`tools/akkado_trial.py`로 잰 값). 스키마는 `tools/akkado_trial.py`의 `{source, seconds, bpm}`.
     - `sb.transient` 오류는 3초 뒤 한 번 다시 하고 시도로 세지 않는다. 파싱 오류와 빈 source는 시도 한 번이다.
     - 호출마다 `last_usage["cost"]`를 더해 행의 `usd`에 쓴다.
  2. **자르기와 사전 검사.** `seconds`는 `SECONDS_CAP = {sfx: 10, amb: 30, music: 30}`과 최소 0.1로 자른다. `bpm`은 20..400의 유한한 수가 아니면 `None`이다. source의 `bus(N`과 `mixer(N`에서 서로 다른 N이 8개를 넘으면 nkido를 돌리지 않고 고치기 사유(`too many stems`)로 넘긴다.
  3. **렌더.** `threading.Semaphore(RENDER_SLOTS = 2)` 안에서 `nkido.render_mended(source, seconds, bpm)`. 내장 이름과 겹친 변수 이름은 어댑터가 모델을 다시 부르지 않고 고치며, 돌려준 source(고친 것)를 결과의 `source`로 저장한다. nkido가 렌더는 했지만 경고를 낸 경우는 `RenderError(kind="warning")`이고 고치기 사유다. 임시 폴더 볼륨의 빈 공간이 2 GB 미만이면 렌더하지 않고 `failed: busy`로 끝낸다. `missing-engine`은 작업을 `no_engine`으로 끝내고 health의 `engine`을 거짓으로 바꾸며, 그 뒤 생성 요청은 503을 받는다.
  4. **원본 측정.** `node tools/asset_lint.js --json --kind K [--loop] --loud lo,hi <wav>`, 제한 20초.
  5. **다듬기**(numpy와 soundfile, 측정값을 쓰는 산술만). 같은 자르기와 게인을 마스터와 스템에 준다. DC 제거. 루프가 아니면 앞 무음 50 ms 초과를 5 ms로, 뒤 무음 200 ms 초과를 50 ms로 자르고 자른 끝에 5 ms 페이드. 음악은 `project.loud`의 가운데로 맞추되 -1.2 dBTP를 넘기지 않는다. 그 밖은 -1 dBTP를 넘으면 -1.2로 내리고 -12 미만이면 -3으로 올린다. 입력의 샘플 형식으로 쓴다. 서버는 루프를 접지 않는다(가이드가 패치 안에서 잇는다).
  6. **최종 측정과 린트.** 같은 명령줄.
- **고치기를 부르는 결함:** `RenderError`(`kind: line N: message`. timeout에는 "too heavy, simplify"를 붙인다. `missing-engine`은 제외), 무음(원본 `sample_peak` -40 dBFS 미만), 원본의 클립 샘플 8개 초과, 루프 아닌 효과음의 `end`가 -40 dBFS 초과, 이름 붙은 스템이 2개 미만인 음악, 요청 길이의 2배를 벗어난 길이, 루프 `seam` 한도 초과, 다듬은 뒤에도 남은 error 수준 린트 문제.
- **되묻는 글:** 원래 요청, 이어서 "Your previous patch: ```...``` It failed: <결함>. Fix it and return the whole patch again."
- **결과:** 결함 없는 첫 시도에서 멈춘다. 끝까지 결함이 있으면 렌더되고 무음이 아니며 error 수준 문제가 없는 가장 늦은 시도가 `done`이고 남은 것은 `issues`에 담는다. 그런 시도가 없으면 `failed: make_failed`다. error 수준 문제가 있는 소리는 `done`이 되지 않는다.
- **프롬프트:** 고정 지시 줄, 이어서 JSON 블록 `REQUEST` 하나(project, item, references, `style_ref`, `examples`). 사용자 글은 이 블록 안에만 들어간다.
  - 시안: "Option k of n; options must differ clearly; option 1 is the most literal."
  - 수정: `base.source`를 코드 블록으로 넣고 "The user wants: <change>. Change only what that needs. Return the whole patch."
  - source가 없는 base(예전 소리, 가져온 소리)는 `base.facts`를 보내 그 느낌으로 새로 만든다.
  - 서버는 입력(`input`)을 작업이 끝날 때 지운다.
- **시간 제한:** 모델 호출 120초, 렌더 30초(어댑터), 측정 20초, 작업은 집어 든 때부터 300초(단계마다 먼저 확인, `failed: timeout`). 2시간 넘게 기다린 작업은 `failed: busy`.
- **모델 차단기:** 키, 크레딧, 할당량 오류가 3번 이어지면 60초 동안 집어 들기를 쉬고 생성 요청은 503 `no_model`을 받는다. 그 오류를 만난 작업은 `failed: no_model`이고 기다리는 작업은 그대로 둔다.
- **동시성:** 작업자 스레드 `GEN_WORKERS = 6`, 렌더 2개. nkido는 `BELOW_NORMAL_PRIORITY_CLASS`로 돈다.
  - 전체 대기 상한 `QUEUE_CAP = 400`(넘으면 503 `busy`).
  - 주인별 활성(대기+실행) 상한은 `min(OWNER_ACTIVE = 64, max(4, (400 - 전체 대기) // 4))`이고 넘으면 429 `too_many_active`. 한 주인은 남은 자리의 4분의 1까지만 차지한다.
- **집는 순서:** 빈 작업자는 실행 중인 작업이 가장 적은 주인에게서 집는다. 주인 안에서는 `(묶음 순서, k, item 순번)`이라 모든 소리의 시안 1이 시안 2보다 먼저다. 받지 않은 결과가 `OWNER_UNFETCHED_BYTES = 512 MB`(`pw` 전체는 1 GB)를 채운 주인은 건너뛴다.
- **집기:** 한 트랜잭션에서 `update gen set status='running', charge=?, charge_at=?, started=? where id=? and status='queued' and cancel=0`과 일일 계수 증가를 같이 쓴다. `charge`는 `acct`면 `pending`, `pw`면 `none`이다. 바뀐 행이 0이면 그 작업을 버린다. 차감(E절)은 이 커밋 뒤에 한다.
- **끝 상태 전이:** `done`, `failed`, `cancelled`로 가는 모든 전이는 조건 갱신 하나다(`where status='running'`, `done`에는 `and cancel=0`도). `charge`의 다음 값도 같은 문장에서 쓴다. 갱신에 진 쪽은 자기 파일을 지우고 장부를 건드리지 않는다.
- **취소:** 대기 중이면 조건 갱신으로 바로 `cancelled`(차감도 계수도 없음). 실행 중이면 `cancel=1`만 쓰고, 보기는 그때부터 `status:"cancelled", refund:"pending"`을 낸다. 작업자는 단계 사이마다 깃발을 보고, 진행 중이던 모델 응답을 버리고 `cancelled`로 전이한 뒤 환불한다. 취소 요청은 장부를 부르지 않는다.
- **작업자 예외:** 작업자 루프는 `run()`을 `try/except BaseException`으로 감싸 `failed: internal`과 환불로 끝내고 다음 작업으로 넘어간다.
- **저장소:** `class GenStore`, 자기 파일 `asset-gen.db`(WAL, `busy_timeout` 10초), `threading.Lock` 하나. `JobStore`를 상속하지 않고 `jobs.sqlite3`를 쓰지 않으므로 음악 화면의 계수와 차감 기록에 닿지 않는다. 파일 이름이 `*.sqlite*`가 아니어서 `server_ops.backup_sqlite`가 요청 글과 source를 백업에 남기지 않는다.
  - `gen(id pk, owner, cls, batch, request_id, ref, k, n, ord, status, stage, attempt, error, view, input, cancel, charge, charge_at, est, usd, bytes, created, started, finished, delivered, seen, expires)`, 색인 `(owner, status)`, `(request_id)`.
  - `req(owner, request_id, body_sha, batch, response, cancelled, created, primary key (owner, request_id))`.
  - `counts(day, name, n, primary key (day, name))`. `day`는 주입한 시계의 `date.today().isoformat()`이고 지난 날짜 행은 청소기가 지운다.
  - `charge` 값: `none`(차감 안 함), `pending`(차감 호출 중), `charged`, `unknown`(장부가 답하지 않음), `refund_due`, `refunded`, `kept`(받아 간 결과).
  - 잠금이나 쓰기 트랜잭션을 쥔 채로는 장부, 모델, 렌더, Node를 부르지 않는다.
- **바이트:** `.studio-data/asset-renders/<작업 id>/master.wav`, `stem-<n>.wav`. 시안 하나는 최대 30초, 스템 8개다.
- **만료:** 받지 않은 `done`은 끝난 뒤 `UNFETCHED_TTL = 3600`초에 환불하고 지운다. 받은 결과는 끝난 뒤 `RESULT_TTL = 86400`초에 지운다. 지운 행은 `gone` 흔적으로 7일 남기고 `view`와 `input`을 비운다. `req` 행은 48시간 둔다.
- **청소기**(시작할 때와 60초마다):
  1. `started`가 360초보다 오래됐고 살아 있는 작업자가 쥐지 않은 `running` 행을 조건 갱신으로 `failed: timeout`.
  2. 2시간 넘은 `queued`를 `failed: busy`.
  3. E절의 환불 재시도.
  4. 두 만료. 미수령 만료는 `update gen set status='gone' where id=? and status='done' and delivered is null`이고, 같은 문장에서 `charge`가 `charged`면 `refund_due`로 바꾼다.
  5. 디스크: 렌더 폴더 합계가 `DISK_CAP = 4 GB`를 넘으면 받아 간 결과 중 마지막 상태 조회(`seen`)가 600초 넘게 지난 것을 오래된 순으로 `gone`(`refund:"none"`)으로 만든다. `seen`은 상태 조회 때 메모리에 적고 청소기가 DB에 옮긴다. 재시작 직후에는 지금 시각으로 본다. 그래도 넘거나 디스크 빈 공간이 2 GB 미만이면 집어 들기를 쉬고 생성 요청은 503 `busy`를 받는다. 받지 않은 결과는 만료 전에 지우지 않는다.
- **재시작:** 작업자를 띄우기 전에 `queued`와 `running` 행을 모두 `failed: restarted`로 바꾸고, `charge`가 `pending`이면 `unknown`, `charged`면 `refund_due`로 바꾼다. 환불 대상은 행의 `status`가 아니라 `charge` 값으로 정한다. `done` 결과는 남는다. 이메일이 디스크에 없으므로 다시 큐에 넣지 않는다. 10분 넘은 임시 폴더 `olmuse-nkido-*`와 행이 없는 렌더 폴더를 지운다.

## E. 크레딧과 한도

- **값:** `asset_jobs.py`의 `DRAFT_CREDITS = 1` 하나. 소리 하나의 시안 하나가 단위이고 AI의 고치기 시도는 그 안에 든다. `pw`는 0이다.
- **견적:** `items x drafts x DRAFT_CREDITS`. `/quote`와 생성이 같은 함수를 쓴다.
- **잔액 캐시:** 주인별로 장부의 마지막 답(`ledger.account`, `charge`, `refund_key`가 돌려준 잔액)을 메모리에 둔다. `/quote`와 생성만, 캐시가 60초보다 오래됐을 때 `ledger.account(email)`을 부른다. `LedgerError`면 503 `no_ledger`.
- **받아들이기**(전부 아니면 전무):
  1. 본문 검증, 견적 계산, `expect_credits` 비교(409).
  2. `acct`면 잔액을 캐시에서 읽는다. 필요하면 여기서 장부를 부른다. 잠금 밖이다.
  3. `store.lock`을 한 번 쥐고 `begin immediate` ... `commit` 안에서 SQL만으로: `req` 재생 확인 → `잔액 - 예약 >= 견적`(402. 예약은 이 주인의 `queued` 수와 `charge='pending'` 수) → 아래 표의 통마다 `오늘 쓴 양 + 활성 + 새 작업 <= 한도` → 활성 상한 → 미수령 몫(`fetch_first`) → 환불 한도 → 달러 상한 → `req`와 `gen` 행 삽입.
  - 동시에 집힌 작업 때문에 더 받아들인 경우는 집을 때의 402가 막는다.

| 통(계수 이름) | env | 기본값 |
|---|---|---|
| 계정별 시안 (`d:<owner>`) | `OLMUSE_GEN_ACCOUNT_DAILY` | 200 |
| 계정 전체 시안 (`d:members`) | `OLMUSE_GEN_DAILY` | 1000 |
| 비밀번호 세션 IP 묶음별 시안 (`d:<owner>`) | `OLMUSE_GEN_PW_DAILY` | 120 |
| 비밀번호 세션 전체 시안 (`d:teachers`) | `OLMUSE_GEN_PW_ALL_DAILY` | 240 |
| 비밀번호 세션 달러 (`usd:pw`, 백만분의 1달러) | `OLMUSE_GEN_PW_DAILY_USD` | 0.60 |
| 생성 전체 달러 (`usd:all`) | `OLMUSE_GEN_DAILY_USD` | 5.00 |

- **일일 계수:** 집을 때 쓴다. 대기 중 취소는 아무것도 쓰지 않는다.
- **달러:** 집을 때 `est = 3 x GEN_CALL_USD[model]`을 `usd:all`에(`pw`면 `usd:pw`에도) 더하고, 작업이 끝나면 실제 `usd`와의 차이로 바로잡는다. `GEN_CALL_USD = {"deepseek/deepseek-v4.1-flash": 0.009}`, 표에 없는 모델은 0.03이다. 음악 화면의 `operator_microusd`와는 별개의 계수라 에셋 시안이 음악 화면을 끄지 못한다. `usd:pw`가 차면 `pw`의 생성 요청은 429 `operator_limit`이고 `pw`의 대기 작업은 `failed: operator_limit`이다. `usd:all`이 차면 집어 들기를 쉬고 생성 요청은 429 `operator_limit`이다.
- **차감:** 집기 커밋 뒤 작업자가 `ledger.charge(email, 1, "gen:" + id)`를 부른다. `LedgerError`면 3초, 10초 뒤 같은 ref로 다시 부른다(장부는 ref로 멱등).
  - 성공 → `charge='charged'`.
  - 402 → 그 작업은 `failed: no_credits`, `charge='none'`. 그 주인의 남은 대기 작업도 차감 없이 `no_credits`로 끝낸다.
  - 세 번 다 `LedgerError` → `failed: no_ledger`, `charge='unknown'`, `charge_at`은 마지막 시도 시각.
- **환불**(`ledger.refund_key(key, 1, "gen:" + id)`, 한 번씩). 대상: `failed`, 실행 중 취소, 재시작, 미수령 만료.
  - 환불을 부르는 것은 둘뿐이다. 그 작업을 쥔 작업자가 자기 차감 호출이 답한 뒤에 부른다. 청소기는 `charge`가 `refund_due`·`unknown`·`pending`이고 살아 있는 작업자가 쥐지 않았으며 `charge_at`이 90초보다 오래된 행에 부른다.
  - 장부는 차감 기록이 없는 ref의 환불에 200만 돌려주고 아무 표시도 남기지 않는다. 그래서 차감 호출이 아직 처리 중일 수 있는 동안에는 환불을 보내지 않는다. 90초는 장부 Lambda의 실행 제한 15초와 클라이언트 제한 10초보다 길다.
  - 답이 오면 `charge='refunded'`. `LedgerError`면 값을 그대로 두고(`refund:"pending"`) 청소기가 다시 한다.
  - 받음 표시가 된 행(`kept`)은 환불하지 않는다. 환불한 ref는 다시 차감하지 않는다(환불된 작업은 끝 상태다).
- **환불 한도:** 사용자 쪽 원인의 환불(`make_failed`, `timeout`, 실행 중 취소, 미수령 만료)은 주인별로 센다. 시간당 `REFUND_HOURLY = 12`(메모리), 하루 `REFUND_DAILY = 24`(`rf:<owner>`)를 넘으면 생성 요청은 429 `refund_limit`이다. 이런 환불은 전체 통(`d:members`, `d:teachers`)에서 1을 도로 빼고 주인 통에는 남긴다. 그 밖의 끝(`no_model`, `no_engine`, `no_ledger`, `no_credits`, `operator_limit`, `restarted`, `internal`, `busy`)은 세지 않고 두 통 모두에서 뺀다.
- **멱등:** `request_id`는 같은 묶음을 가리키고 ref `gen:<작업 id>`는 장부에서 차감과 환불 모두 멱등이다. 다시 보낸 POST나 작업자 충돌이 두 번 차감하지 못한다.

## F. 브라우저

**새 파일**(`studio_frontend/asset_studio/`, 모두 UMD. `indexedDB`, `fetch`, 시계, `navigator.locks`를 주입받아 Node 시험에서 돈다): `store.js`(`window.assetStore`: 스냅샷 올리기, 쓰기, 복원, 잠금, 소리 풀기), `gen.js`(`window.assetGen`: 토큰, 단가, 생성, 폴링, 다시 붙기, 알림), `quote.js`(`window.assetQuote`: 글자의 숫자, 보류, 예시 고르기). `app.js`는 이들을 부른다. `index.html`의 script 태그는 그 파일을 처음 쓰는 패키지가 넣는다(`measure.js`와 `store.js`는 F1).

**버전 레코드**(보드 스냅샷 안)
```
{id, at, note, change,                       // change는 예전 합성 레시피에만 있다
 engine: "legacy"|"import"|"nkido", job, parent, draft: {k, n},
 source, seconds, bpm, prompt, model,
 sources: [{name, license, holder, use}],
 measure, issues, peaks (200개),              // 타일은 소리를 풀지 않고 이것으로 그린다
 key: "ver:<id>", stems: [{label, key: "ver:<id>:s<n>", bytes, sha256}],
 rate, channels, bits, bytes, sha256}
```
- 서버가 만든 버전의 `id`는 작업 id다. 두 번 받아도 하나다.
- **작업 기록**(에셋마다, POST 전에 쓴다): `a.work = {request, kind, who, mode, text, n, at, before, jobs: [{id, k, got}]}`. `who`는 토큰 `sub`의 SHA-256 앞 16자, `before`는 요청 전 status다.
- **요청 본문:** POST에 보낼 문자열 그대로를 `board` 저장소의 키 `req:<request>`에 요청당 한 번 둔다. 작업 id를 저장한 뒤 지운다. 다시 보낼 때 보드에서 본문을 새로 만들지 않는다.

**IndexedDB**
- DB는 `olmuse-asset-board` 버전 1, 저장소 `board`와 `audio` 그대로다. 스키마 업그레이드는 없다. 버전과 스템 Blob은 `audio`에 `ver:` 키로 들어간다.
- 스냅샷은 `v:2`다. `assetStore.upgradeSnapshot(data)`는 `v`가 없거나 1이면 `{change, note, at}` 버전마다 `id`, `engine:"legacy"`, `sources`를 붙인다. 만든 소리에는 내장 합성기 항목, 가져온 소리에는 그 `license`·`holder`(없으면 `[]`)를 넣는다.
- `v:2`를 처음 쓸 때 같은 트랜잭션에서 예전 레코드를 키 `board.v1`에 복사하고, 그 뒤 복원이 한 번 성공하면 지운다.
- legacy 버전은 지금처럼 `synth.render`로 그린다(`a.key` 아래 Float32 `a.source` 포함). 기존 보드는 그대로 열린다.
- 새로 가져오는 파일은 원본 바이트를 `engine:"import"` 버전으로 저장한다.
- `snapshot()`은 `a.work`가 있으면 `working`을 유지하고, 검토 중인 시안도 버전 레코드로 담는다.

**쓰기**
- `saveBoard()`: `board` 저장소만 여는 작은 트랜잭션에 스냅샷 하나를 쓰고 성공 여부를 참·거짓으로 돌려준다. 항상 Blob보다 먼저 쓴다.
- `saveBlob(key, blob)`: Blob 하나에 트랜잭션 하나. 끝난 키만 `saved` 집합에 넣는다.
- 참조가 없는 키의 삭제는 별도 트랜잭션이고 `saveBoard()`가 성공한 뒤에만 한다.
- Blob 쓰기가 용량 때문에 실패하면 `blobFull`을 세우고 기존 `saveFull` 토스트를 한 번 띄운다. `blobFull`인 동안 새 생성을 받지 않는다. Blob 쓰기가 다시 성공하면 풀린다.
- `prune()`은 legacy 버전만 줄인다. `nkido`와 `import` 버전은 자리 때문에 지우지 않는다.

**복원**
- `restore()`의 결과는 `empty`, `restored`, `failed` 셋이다. DB 열기 3초 초과, 읽기 오류, `upgradeSnapshot` 예외는 `failed`다.
- `failed`면 그 방문 내내 `paused = true`다. 자동 저장, 생성, 키 삭제를 하지 않고 토스트 `loadFailed`를 한 번 띄운다. 저장된 보드를 샘플 보드로 덮어쓰지 않는다.
- 읽는 것은 키 목록, `ref:` Blob, legacy `a.key` Blob이다. `ver:` Blob은 처음 쓸 때 읽는다.
- `ver:` Blob이 없는 버전은 그 버전만 다룬다. `a.work`에 그 id가 남아 있으면 다시 받고, 아니면 그 버전만 뺀다. 현재 버전이었으면 남은 것 중 가장 새 버전으로 옮기고, 하나도 없으면 `pending`이다. 같은 에셋의 다른 버전과 Blob은 건드리지 않는다.

**소리와 재생**
- 메모리 모양: `{rate, channels, seconds, chans: [Float32Array], mix, stems: [{name, chans, data}]}`. `mix`와 `data`는 모노 합이라 모노 코드가 그대로 돈다. legacy는 `chans = [mix]`, 22050 Hz다.
- `filled(a, v)`는 `engine`으로 갈린다. legacy는 지금처럼 `synth.render`한다. `nkido`와 `import`는 렌더하지 않고 저장된 `peaks`와 `measure`를 건드리지 않으며 `sound`가 없을 수 있는 `v`를 돌려준다.
- `ensureSound(v)`는 async이고 한 번만 푼다. WAV는 `assetMeasure.readWav`(정확한 샘플), 그 밖의 형식은 `OfflineAudioContext(2, 1, 48000)`의 `decodeAudioData`로 푼다.
- `ensureSound`를 기다리는 곳: `play`, 상세 화면, 내보내기, `dynStart`(레이어의 소리를 모두 준비한 뒤 시작하고 `bufferOf`는 준비된 소리만 읽는다). 타일, 린트, 명세의 길이, `boardState`, `classify`, `promptFor`는 저장된 `peaks`와 `measure`만 읽는다.
- `play`가 async가 되므로 재생 요청 번호를 두어 늦게 풀린 마우스 오버 재생이 나중 재생을 덮지 않게 한다.
- `nkido` 버전의 재생(타일, 마우스 오버, 모두 재생, 상세, 다이내믹)은 마스터 채널을 `createBuffer(chans.length, n, rate)`로 튼다. 스템은 트랙 탭에서 하나라도 솔로, 음소거, 음량 변경이 걸렸을 때만 튼다. 스템은 마스터 리미터 앞에서 잡히고 `out()`으로 바로 보낸 소리가 빠져 있어 합이 마스터와 다르다. 스템이 0개면 마스터를 스템 하나로 보여 준다.
- 내보내기: `resample`과 `encode`는 채널별로 돈다. `importer.encodeWav`는 배열 하나 또는 채널 배열을 받는다. 서버 버전을 48 kHz WAV, 같은 비트 깊이로 내보내면 저장된 마스터 바이트를 그대로 쓴다.

**생성.** `request()`, `fill()`, `expand()`, `likeThis()`의 타이머를 `assetGen.generate(list, {mode, text, drafts})`로 바꾼다. `#fillBtn`, `#expandBtn`, `#likeThis`로 시작한 채우기는 소리당 시안 1개이고, 독과 상세의 입력으로 시작한 것은 선택기의 시안 수를 쓴다.
1. 멈춤 상태, 잠금 없음, `paused`, `blobFull`, 토큰 없음이면 받지 않는다(토큰 없음은 기존 AI 꺼짐 토스트).
2. 본문 문자열을 만들어 `req:<request>`에 쓰고 에셋마다 `a.work`를 쓴 뒤 `await saveBoard()`. 거짓이면 되돌리고 `saveFull` 토스트를 띄우며 POST하지 않는다.
3. 저장한 문자열 그대로 POST한다. 200이면 id를 `a.work.jobs`에 넣고 `saveBoard()`, `req:` 키 삭제, 폴링 시작.
4. 409 `quote_changed`: 되돌리고 `/quote`를 다시 받아 글자의 숫자를 고치고 서버 `message`를 토스트로 띄운다. 자동으로 다시 보내지 않는다. 402, 410, 413, 429, 503: 되돌리고 `message` 토스트. 응답을 받지 못하면 기록을 그대로 두고 다시 붙기 절차로 푼다.

**폴링**(페이지에 하나)
- 1.5초마다 `/jobs/status`를 보낸다. 숨겨진 탭은 5초, 모든 작업이 `queued`이고 `position`이 12를 넘으면 3초다. 활성 작업이 없으면 멈춘다. 429면 `retry_after`만큼 쉰다. `progress`가 기존 `.bar --p`를 움직인다.
- `kind`가 지금 토큰과 같고 `acct`면 `who`도 같은 기록만 다룬다. 다른 기록은 토스트도 POST도 없이 그대로 둔다. 그 주인이 다시 오면 붙는다.
- `done`: 마스터와 스템을 받고 sha256을 확인한다(다르면 한 번 다시 받는다). 상태를 한 번 더 받아 전체 `result`로 버전을 만들고 Blob마다 `saveBlob`을 부른다. 모두 성공해야 `got:true`로 바꾸고 `saveBoard()`한다. 실패한 시안은 메모리에서 재생되고 id를 지켜 새로고침 뒤 다시 받는다.
- `got`이 거짓인 시안의 다른 답: `forbidden`은 건너뛰고 둔다. `gone`에 `refund:"done"`이면 `genRefunded` 알림. `gone`에 `refund:"none"`이거나 `unknown`이면 환불이라고 말하지 않고 `genLost` 알림. 뒤의 둘은 기록에서 그 작업을 뺀다.
- 한 에셋의 작업이 모두 끝나면: 버전이 없던 에셋에 시안 하나면 첫 버전이 되고 status는 `draft`다. 그 밖에는 `pick = 0`, status `review`이고 기존 타일별 채택·버리기와 모두 채택·모두 버리기가 그대로 쓰인다. 시안이 0개면 `work.before`로 돌아간다. 그 뒤 `a.work`를 지우고 `asset:account`를 보내 호스트가 기존 `account` 액션을 부르게 한다.
- 알림: 한 폴링 틱의 실패와 환불은 문구 하나로 합친다. 단추가 든 토스트가 떠 있으면 그것이 사라진 뒤에 띄운다.

**다시 붙기**(`restore()`가 `restored`이고 토큰이 온 뒤, 신원이 맞는 기록만)
- id가 있는 기록은 폴링에 넣는다.
- id가 없는 기록은 나이와 상관없이 `POST /jobs/status {request_id}`로 찾는다.
  - `known`이면 id를 저장하고 폴링한다. `cancelled`면 `before`로 돌린다.
  - `known:false`이고 `at`이 10분 안이며 `req:` 본문이 있으면 그 문자열 그대로 POST한다.
  - `known:false`이고 더 오래됐거나 본문이 없으면 `POST /jobs/cancel {request_id}`를 보낸 뒤 `before`로 돌린다.

**예상 크레딧**(기존 요소의 글자만. `free`면 숫자를 붙이지 않는다)
- 단가: 토큰이 처음 올 때와 토큰의 `kind`·`sub`가 이전 토큰과 다를 때마다 `GET /quote?items=1&drafts=1`을 받고 글자를 다시 그린다.
- `assetGen.quoteOf(count, drafts)` 하나를 글자와 `generate()`가 같이 쓴다.
- 시안 선택기의 `segLabel`(독과 상세)은 선택 수 x 시안 수로 "시안 · 6 크레딧"처럼 쓴다. `#fillBtn`, `#expandBtn`, `#likeThis`는 자기 글자에 자기 숫자를 붙인다("나머지 만들기 · 24 크레딧").
- 문장에 적은 시안 수(`draftsWanted(text)`)가 선택기와 다르면 선택기를 그 값으로 옮긴다. 선택기가 시안 수의 유일한 출처다.
- **보류:** 보내기를 누른 순간 `segLabel`의 숫자가 `shown`이다. 에이전트 답의 `revise`(빈 칸 채우기 포함)에 드는 크레딧 `need`가 `shown` 이하이거나 `free`면 바로 시작한다. 넘으면 시작하지 않고 `held = {ids, text}`를 상태에 둔다. 그 소리들을 선택하고 글을 `#ask`에 되돌려 놓고 토스트 `agentHeld`를 띄운다. `segLabel`은 이제 `need`를 보인다. 글과 선택이 그대로인 채 보내기를 누르면 에이전트를 거치지 않고 `generate()`를 부른다. 글이나 선택이 바뀌면 `held`를 버린다. `held`는 토스트가 지워져도 남는다.
- 에이전트 답의 되돌리기는 `a.work`가 있는 소리의 status와 시안을 건드리지 않는다.
- 샘플 후 확장: `examples`는 source가 있는 승인 버전에서 같은 종류를 먼저, 3개까지 고른다.

**탭 두 개:** Web Lock `olmuse-asset-board`. 잠금이 없는 탭은 읽기 전용이다. `assetStore.guard`가 캡처 단계에서 재생(`#playAll`, 타일 마우스 오버), `#exportBtn`과 그 대화상자, `#backBtn`, `#menuBtn` 밖의 클릭, 키, 드롭, 제출을 막고 토스트 `otherTab`을 띄운다. 자동 저장과 생성도 하지 않는다. 잠금을 얻으면 `restore()`를 먼저 돌린 뒤 입력을 받는다.

**취소**는 기존 동작에만 붙인다: 작업 중인 소리를 휴지통으로 옮길 때와 `forget()`.

**새 작업에서 빼는 것:** `changeFrom`, `SPREAD`, `layersFor`, `asset:prompt` 전송, `checked`/`MAX_CHECKS`. `MAX_DRAFTS`는 상수 4다. `checked`는 데모 보드용으로 남는다.

**토스트 문구 키**(`app.js`의 두 언어 표. 흔히 쓰는 말로 쓰고 재촉하지 않는다): `loadFailed`, `otherTab`, `genPaused`, `agentHeld`, `genFailed(n)`, `genRefunded(n)`, `genLost(n)`.

## G. 측정과 린트

- **구현은 하나:** `studio_frontend/asset_studio/measure.js`, 순수 JS, UMD(`window.assetMeasure`와 `module.exports`), 새로 쓴다. 화면, 명령줄, 서버(Node)가 이 파일만 쓴다.
- **API:** `readWav(bytes)`(PCM 8/16/24/32비트 정수와 32비트 float → `{rate, bits, chans}`), `measure({rate, chans})`, `RULES`, `PROFILES`, `idOk(id, idRule, catIds)`, `lint(facts, m, {profile|loud, idRule, catIds})` → `[{id, level, value, limit}]`.
- **필드:** 기존 이름(`peak, loud, seconds, clips, lead, tail, dc, seam, wrap, dip, low, mid, high, bright`)에 `rate, channels, bits, sample_peak, end`를 더한다.
  - `peak`: dBTP, 4배 오버샘플, 채널 중 최대.
  - `loud`: BS.1770 통합 LUFS(파일의 rate에 맞춘 K 가중, 400 ms 블록 75% 겹침, 절대 -70과 상대 -10 게이트). 400 ms 미만이면 게이트 없는 K 가중 레벨.
  - `clips`: |x| >= 32767/32768인 프레임 수. `lead`, `tail`: 채널 최대 절댓값이 0.003을 넘는 구간 기준. `end`: 마지막 50 ms의 RMS dBFS.
  - `dc`, `seam`: 채널 중 최대. `wrap`, `dip`, 대역 값은 모노 합으로 잰다.
  - 샘플이 0개나 1개면 정해진 무음 결과를 돌려준다.
- **규칙과 프로파일**은 지금 `data.js`의 id와 문턱값을 그대로 옮긴다. `data.js`에는 규칙 id별 표시 글만 남고 `app.js`의 `broken()`은 `assetMeasure.lint`를 부른다.

| 규칙 | 한도 | 수준 | 적용 |
|---|---|---|---|
| peak | -1 dBTP | error | 전부 |
| clip | 0 | error | 전부 |
| loud | 프로파일 범위 | error | 음악 |
| dur | 2초 | warn | 음악 아님, 루프 아님 |
| lead | 50 ms | warn | 루프 아님 |
| tail | 200 ms | warn | 루프 아님 |
| dc | 0.002 | warn | 전부 |
| seam | 3배 | warn | 루프 |
| wrap | 3 dB | warn | 음악 아닌 루프 |
| steady | 12 dB | warn | 음악 아닌 루프 |
| name | 프로젝트의 id 규칙(`idOk`) | error | 전부 |
| lic | 현재 버전의 `sources`가 비어 있지 않음 | error | 전부 |

  - 프로파일: mobile [-20, -16], console [-26, -22], wide [-26, -14].
  - `idOk`는 `app.js`의 지금 규칙과 같다: `idRule = {pattern, sep, prefix, check}`, `{cat}`은 `catIds`에서 만들고 `check:false`면 빈 id만 틀린다.
  - `lic`은 `noLicense` 판정을 대신한다. 출처 기록이 없는 에셋은 린트 오류다.
- **명령줄:** `node tools/asset_lint.js <file.wav> [--kind sfx|amb|music] [--loop] [--profile p | --loud lo,hi] [--spec game-audio.spec.json] [--id x] [--sources json] [--json]`.
  - `--spec`이 있으면 그 `id_rule`, `categories`, `platform`으로 판정한다. id(`--id`, 없으면 확장자를 뺀 파일 이름)를 spec의 `assets`에서 찾아 종류(그 category의 `kind`)와 `loop`를 가져온다.
  - `--spec`이 없으면 기본 id 규칙(`{kind}_{name}`, `_`, sfx·amb·bgm)을 쓰고 종류는 접두사에서 온다.
  - `name`은 `--id`나 `--spec`이 있을 때만, `lic`은 `--sources`가 있을 때만 본다. error 수준 문제가 있으면 종료 코드 1.
- **같은 판정:** 화면, 명령줄, 서버가 같은 바이트에 `readWav -> measure -> lint`를 돌린다. WAV 파일에 한해 성립한다. 다른 형식의 가져온 파일은 브라우저가 푼 뒤 재므로 명령줄 경로가 없다.
- **CREDITS:** `licenseText()`는 승인된 에셋의 현재 버전 `sources`를 (name, license, holder)로 합친 목록이다. MP3나 OGG로 내보내면 인코더 항목을 더한다. 서버는 nkido 결과의 `sources`에 `data.js`의 기존 `nkido (Akkado, Cedar)` 항목을 넣는다.

## H. 보안과 남용

- **주입:** 사용자 글은 길이가 정해진 필드로 `REQUEST` JSON 블록 안에만 들어간다. 모델 답은 스키마에 묶이고, 쓰는 출력은 Akkado source뿐이며 `nkido.refuse`와 격리 실행을 거친다. 최악은 틀린 소리나 환불되는 실패다. `source`와 `prompt`는 화면에 `textContent`로만 넣는다.
- **엔진:** 금지 필터(주석 포함 어디든), 빈 임시 폴더, 최소 환경, 30초, 1 GB, 자식 프로세스 금지는 어댑터가 맡는다. API가 더하는 것은 렌더 2개, `SECONDS_CAP`, bpm 범위, 렌더 전 버스 8개 검사, 낮은 우선순위, 임시 볼륨 빈 공간 검사다.
- **크기:** 본문 1 600 000바이트, 작업당 `REQUEST` 48 000자, source 20 000자, 시안당 30초와 스템 8개, 렌더 저장 4 GB, 주인별 미수령 512 MB.
- **공짜 사용 막기:** 받기 전에는 source를 주지 않고 첫 바이트를 내주면 환불이 막힌다. `Range`로 나눠 받아도 같다. 환불로 끝나는 시안은 환불 한도와 생성 전체 달러 상한에 걸린다.
- **큐 독점 막기:** 주인별 활성 상한이 남은 자리의 4분의 1이고 취소도 생성 한도에 센다. 받지 않은 결과는 그 주인의 생성만 막는다.
- **교차 사이트:** Host와 Origin 허용 목록. 쿠키가 없어 저절로 따라가는 권한이 없다.
- **토큰 유출:** 메모리에만 있고 URL과 저장소에 넣지 않으며 15분이다. `acct` 토큰은 그 계정의 일일 한도 안에서 쓰고 그 `sub`의 작업만 받는다. `pw` 토큰은 IP 묶음 한도와 `usd:pw`에 묶이고 id를 아는 `pw` 작업에만 닿는다.
- **익명 방문자:** 정적 화면을 열고 가져오기, 린트, 내보내기를 브라우저 안에서 할 수 있다. `/health` 밖의 모든 API 호출은 401이다.

## I. 시험

키 없이 돈다. 대본 `FakeModel`, `FakeEngine`(`wave`로 만든 `Rendered` 또는 각 `RenderError`, 막히는 렌더, 다른 예외), 주입한 `measure`, `LocalLedger(":memory:")`, 차감이 막히거나 실패하는 장부 fake, 가짜 시계를 쓴다.

- **`tests/test_asset_token.py`(T):** 변조, 만료, `aud`, `kind`. `session_token`은 300초 미만과 `sub` 변경에서만 다시 서명한다. `adopt_credits`: 에이전트 보기의 credits가 20이고 그 뒤 계정 잔액을 8로 갱신하면 이후 호출에서도 8이고, 새 보기(`n` 변경)가 오면 그 값이 된다.
- **`tests/test_asset_jobs.py`(B1):**
  - 집을 때 차감. 실패, 실행 중 취소, 재시작, 미수령 만료에서 환불 한 번. 받은 뒤에는 환불 없음. `LedgerError` 뒤 청소기의 환불 재시도.
  - 차감 호출이 막힌 동안 취소가 와도 환불이 차감보다 먼저 나가지 않고, 차감이 답한 뒤 한 번 환불된다.
  - 차감 세 번 실패 → `unknown`. 90초 전에는 환불 호출이 없고 뒤에는 한 번이다.
  - 막히는 렌더 중 취소 → 끝 상태 `cancelled`, 파일 없음, 환불 한 번. `RenderError`가 아닌 예외 → `failed: internal`, 환불, 작업자는 다음 작업을 집는다.
  - 재시작: `charge`가 `pending`·`charged`인 `queued`·`running` 행이 모두 환불되고 `done` 행은 남는다. 하위 프로세스를 집기 커밋과 차감 사이, 차감과 다음 쓰기 사이에서 죽이는 시험(`tests/test_hard_kill_refund.py`의 방식).
  - `request_id` 재생은 만들지도 차감하지도 않는다. 다른 본문은 409, 취소 표식 뒤의 POST는 410, `status {request_id}`는 `known`을 맞게 답한다.
  - 받아들이기 중 장부가 6초 막혀도 다른 주인의 상태 조회와 생성이 기다리지 않는다.
  - 64 x 4 시안은 모델 호출 전에 거절된다. 주인 상한은 남은 자리의 4분의 1이고 두 주인으로는 `QUEUE_CAP`이 차지 않는다.
  - 두 주인 사이의 공정한 집기, 시안 1 먼저, 렌더 2개 상한. 집을 때 402면 나머지는 차감 없이 실패.
  - 미수령 몫이 찬 주인만 `fetch_first`이고 다른 주인은 생성된다. 미수령은 3600초에 환불되고 지워진다. 디스크 상한은 `seen`이 600초 지난 받은 결과만 지운다. 받음 표시와 미수령 만료는 한 행에서 하나만 이긴다.
  - `refund_limit`. 환불된 시안은 전체 통에서 빠진다. `usd:pw`는 추정 뒤 실제 값으로 바로잡힌다. `usd:all` 상한에서 집기가 쉰다. 대기 취소는 달러를 더하지 않는다.
  - `sub`가 다르고 IP가 같은 `pw` 토큰 둘이 한 통을 쓴다. 360초 넘은 주인 없는 `running`은 실패하고 환불된다.
- **`tests/test_asset_generate.py`(B1):** 고치기는 최대 2번이고 되묻는 글에 이전 source와 결함이 있다. error 수준 결과는 `done`이 되지 않는다. 버스 9개 source는 렌더 없이 결함이 된다. 범위 밖 bpm은 `None`. 사용자 글은 `REQUEST` 블록 안에만 있다.
- **`tests/test_asset_api.py`(B2, `fastapi.testclient`, `create_app(Deps(..., autostart=False))`와 `drain()`):**
  - 토큰 없음 401, Origin 403, Host 403, 초과 413, 인증 실패 61번째 429, 인증된 요청은 IP 한도에 걸리지 않음.
  - 다른 계정의 id는 `forbidden`, 없는 id는 `unknown`, 두 번째 `pw` 토큰으로 `pw` 작업 접근.
  - 생성 → 상태 → 소리 → 스템 → 취소 전체 흐름. 받기 전 상태에는 `source`와 `prompt`가 없고 받은 뒤에는 있다. 스템만 받아도 받음 표시. `Range` 요청에 200 전체. `REQUEST` 48 000자 초과는 413.
  - `expect_credits` 없음 400, 불일치 409 `quote_changed`, 402. 상태 조회는 장부를 부르지 않는다(호출 수를 세는 fake).
- **`tests/test_asset_measure.py`(M, `tests/test_asset_import.py`처럼 Node에 stdin으로):** 997 Hz 풀스케일 모노 사인은 -3.01 LUFS(오차 0.1). fs/4 사인 45도는 true peak가 샘플 피크보다 약 3 dB 높다. clip, lead, tail, dc, seam, `end`, 샘플 0개와 1개. 44.1 kHz와 스테레오. 명령줄 `--json`은 같은 바이트의 모듈 결과와 같다. `--spec`의 id 규칙이 `{kind}_{cat}_{name}`, 접두사 `mus`, `check:false`일 때 `name` 판정이 `idOk`와 같다.
- **`tests/test_asset_store_js.py`(F1, Node, 주입한 저장소):** 저장된 v1 보드를 올리면 에셋과 버전 수가 같고 `board.v1`이 남는다. `upgradeSnapshot` 예외와 읽기 오류는 `failed`이고 그 뒤 쓰기가 없다. Blob 하나의 용량 오류가 보드 레코드 쓰기를 막지 않고 `blobFull`이 선다. 버전 Blob 셋 중 하나가 없으면 그 버전만 빠진다. `prune`은 `nkido` 버전을 지우지 않는다. 잠금 없는 탭의 변경 시도는 아무것도 바꾸지 않고, 잠금을 얻은 뒤 복원된 상태는 저장된 것과 같다. `nkido` 버전의 `filled`는 `peaks`와 `measure`를 바꾸지 않는다.
- **`tests/test_asset_gen_js.py`(F2, Node, 주입한 `fetch`와 시계):** `saveBoard`가 거짓이면 POST가 없다. 저장된 id로 다시 붙기. id 없는 기록은 `known`이면 id를 얻고, 모르고 10분 안이면 저장된 문자열 그대로 다시 보내고, 오래됐으면 취소를 보낸 뒤 `before`로 간다. 신원이 다른 기록은 건드리지 않고 `pw`는 `kind`만 본다. `done`이 시안이 되고 Blob 저장이 끝나야 `got`이다. 전부 실패한 에셋은 `before`로 간다. 401 뒤 토큰 갱신과 멈춤 상태, 브라우저 시계가 20분 앞서도 폴링이 돈다. sha 불일치, `gone`의 두 `refund` 값에 따른 문구, 429 뒤 `retry_after`만큼 쉼. 한 틱의 알림 셋은 문구 하나가 된다.
- **`tests/test_asset_quote_js.py`(F3, Node):** 3 x 2의 글자는 6이다. 문장의 "시안 4개"는 선택기를 4로 옮기고 `need`가 `shown`보다 커서 보류된다. 보류 뒤 같은 글과 선택으로 보내면 에이전트 호출 없이 생성되고, 다른 토스트가 떠도 `held`가 남는다. `likeThis`와 채우기의 글자에 숫자가 있다. 토큰이 `pw`에서 `acct`로 바뀌면 숫자가 나타난다. 409 `quote_changed`는 새 숫자를 보이고 다시 보내지 않는다. 세 에셋이 따로 끝나 각각 `review`가 된다.
- **화면 확인(사람이 한 번, 브라우저 하나, 기본 pytest 밖):** `OLMUSE_GEN_FAKE=1`로 `tests/e2e_asset_import.py`를 돌린다. 위반 WAV를 가져와 타일의 문제 id가 `asset_lint.js --json`과 같은지, 작업 중 새로고침 뒤 타일이 끝나는지 본다.

## J. 작업 패키지

한 파일은 한 패키지에만 든다. 예외는 `studio_frontend/asset_studio/`의 `app.js`, `style.css`, `index.html` 셋으로, F1 → F2 → F3가 차례로 이어받고 동시에 고치지 않는다. 패키지가 더하는 시험은 그 패키지의 시험 파일에 있다. 스크립트 스탬프(`?v=`)는 어느 패키지도 고치지 않는다.

| Id | 혼자 만들거나 고치는 파일 | 의존 | 끝난 기준 |
|---|---|---|---|
| M | `studio_frontend/asset_studio/measure.js`, `tools/asset_lint.js`, `tests/test_asset_measure.py` | 없음 | `python -m pytest -q tests/test_asset_measure.py` 통과. 클립된 WAV에 `node tools/asset_lint.js`가 1로 끝남 |
| T | `asset_token.py`, `app.py`, `studio_frontend/app.js`(호스트), `tests/test_asset_token.py` | 없음 | `python -m pytest -q tests/test_asset_token.py tests/test_studio_backend.py` 통과. `asset:token` 전송이 `location.origin`을 쓰는 것을 grep으로 확인 |
| B1 | `asset_jobs.py`, `asset_generate.py`, `asset_engine/nkido.py`(우선순위 플래그 한 줄), `tests/test_asset_jobs.py`, `tests/test_asset_generate.py` | M | `python -m pytest -q tests/test_asset_jobs.py tests/test_asset_generate.py tests/test_asset_engine.py` 통과 |
| B2 | `asset_api.py`, `tests/test_asset_api.py`, `run_api.ps1`, `run_public.ps1`, `run_local.ps1`, `requirements.txt`(설치된 fastapi, uvicorn, numpy, soundfile, httpx 버전 고정) | T, B1 | `python -m pytest -q tests/test_asset_api.py tests/test_tech_review_fixes.py` 통과. `OLMUSE_GEN_FAKE=1`로 띄운 뒤 `curl 127.0.0.1:8502/api/asset/health`가 `ok` |
| F1 (순서 4) | `store.js`, `importer.js`, 이어받는 셋, `tests/test_asset_store_js.py`. 내용: 버전 레코드, `upgradeSnapshot`, 나눈 쓰기, 세 갈래 복원, `ver:` Blob, 잠금과 읽기 전용, 여러 채널 소리와 마스터 재생, 가져온 파일을 바이트로 | M | `python -m pytest -q tests/test_asset_store_js.py tests/test_asset_import.py` 통과 |
| F2 (순서 5) | `gen.js`, `data.js`, 이어받는 셋, `tests/test_asset_gen_js.py`, `tests/e2e_asset_import.py`. 내용: 생성, 폴링, 다시 붙기, 알림, `measure.js`로 린트 교체, `lic`과 `licenseText()`, 가짜 소리 제거 | F1, T, B2 | `python -m pytest -q tests/test_asset_gen_js.py tests/test_asset_store_js.py tests/test_asset_import.py` 통과. `grep -c "asset:prompt\|SPREAD" studio_frontend/asset_studio/app.js`가 0 |
| F3 (순서 6) | `quote.js`, 이어받는 셋, `tests/test_asset_quote_js.py`. 내용: 글자의 숫자, 문장의 시안 수, 보류, 여러 소리 동시 수정, `examples` | F2 | `python -m pytest -q tests/test_asset_quote_js.py tests/test_asset_gen_js.py tests/test_asset_store_js.py` 통과 |

**통합 단계(패키지가 아니다. 지휘하는 쪽이 한다)**
- F 패키지가 하나 끝날 때마다 `python tools/stamp_assets.py`를 한 번 돌리고 `python -m pytest -q tests/test_stamp_assets.py`를 본다. 호스트 `studio_frontend/index.html`도 `asset_studio/importer.js`를 싣고 있어 같이 바뀐다.
- F3와 화면 확인이 끝난 뒤에 ingress 규칙과 감시 대상을 넣는다. 예상 크레딧이 보이기 전에 운영에서 차감되지 않게 한다. 넣은 뒤 `https://olmuse.app/api/asset/health`가 200이고 `/`가 Streamlit인지 본다.

**관문:** GAME_ASSET_PLAN 8절대로 순서 5 이후는 순서 3(nkido 시험)과 사람의 껍데기 확인이 통과한 뒤에 시작한다. M, T, F1은 그 관문 밖이다. B1과 B2는 fake로 돌지만 순서 5의 일이다.

**확인되지 않은 것**
- 이 터널에서 cloudflared `path` 규칙이 맞게 걸리는지.
- nkido 출력의 비트 깊이. `readWav`는 모든 경우를 읽고, 32비트면 시안당 크기가 두 배가 된다.
- 장부 토큰과 pepper가 `st.secrets` 밖(env, `~/.all-tomorrow`)에서 읽히는지. health의 `ledger`로 드러난다.
- E절 표의 한도 값과 `DRAFT_CREDITS`는 요금 수준이 정해지면 바꾼다.
