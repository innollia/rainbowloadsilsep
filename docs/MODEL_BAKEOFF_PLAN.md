# 모델 대결 계획 (가격대별로 누가 음악을 잘 만드나)

olmuse 작업실의 편집 루프(편집 → 브라우저 실행 → 녹음 → 듣기/측정 → 다음 라운드)를 그대로 쓰고, 그 안의 모델만 바꿔 가며 같은 과제를 풀린다. 이 문서는 무엇을 쓰고 어떻게 잴지 정한다. 도구는 `bakeoff/`에 구현됐다(3.3, 10절).

> **2026-11-07 사용자 결정으로 바뀐 점** (아래 본문은 이 결정에 맞춰 고쳤다)
> - OpenRouter 키는 `~/.all-tomorrow/key-pool.env`의 `OPENROUTER_API_KEY`. 이미 충전돼 잔액 약 **$9.8**이고, 이번 실험에 다 써도 된다. 값은 출력·로그·커밋하지 않는다.
> - **Gemini 모델은 이 PC의 agy CLI(Antigravity)**, **GPT 모델은 이 PC의 codex CLI(OpenAI Codex, 구독)**로 부른다. CLI 모델 원가는 $0으로 적고 보고서에 "구독"으로 구분한다. CLI 모델은 비싼 등급(gpt-5.6-terra)도 반복을 줄이지 않고 같은 배정(8과제 × 3회)으로 돌린다.
> - OpenRouter 돈은 나머지 모델(무료·초저가·중가, Claude Haiku/Sonnet)에 쓰고, 남는 예산만큼 반복을 늘렸다(4절).
> - 사람 블라인드 청취는 `https://olmuse.app/listen`(pages/listen.py) 페이지로 여러 명이 한다(6절).
> - Gemini 직접 API 지갑은 쓰지 않는다. 그래서 Gemini도 소리를 직접 듣지 않고 측정 분석으로 판단한다.

**총예산: OpenRouter 잔액 약 $9.8 + CLI 구독.** 원래 상한 2만원(실사용 약 $13)에 맞춘 배정을 위 결정대로 다시 짰다(8절).

가격과 모델 이름은 2026-11-07에 `https://openrouter.ai/api/v1/models`에서 받은 목록(460개)을 기준으로 했다. 실행 직전에 같은 API로 다시 받아 표를 갱신한다.

---

## 1. 무엇으로 붙일까: OpenRouter를 주력으로

**추천: OpenRouter.** 한 키·한 주소로 닫힌 모델(GPT, Gemini, Claude)과 열린 모델(DeepSeek, Qwen, GLM, Kimi, MiniMax)을 모두 부를 수 있고, 응답마다 실제 청구액(`usage.cost`)이 붙어 와서 "호출당 원가"를 따로 계산하지 않아도 된다.

| 항목 | OpenRouter | Hugging Face Inference Providers |
|---|---|---|
| API 형태 | OpenAI 호환 `POST https://openrouter.ai/api/v1/chat/completions` | OpenAI 호환 `POST https://router.huggingface.co/v1/chat/completions` |
| 모델 범위 | 닫힌 모델 + 열린 모델 460개 | 열린 가중치 모델 위주(협력사 경유). GPT·Claude·Gemini 없음 |
| 모델 목록 API | `GET /api/v1/models` (키 없이). `pricing.prompt`·`pricing.completion`은 **토큰당 USD 문자열**(×1e6 하면 1M 토큰당). `supported_parameters`에 `structured_outputs`·`response_format`·`reasoning` 표시. `reasoning.mandatory`로 생각 끄기 가능 여부 표시. `pricing.overrides`는 긴 입력일 때 단가(모르는 조건은 무시) | 모델 페이지·Hub API에서 제공자별로 따로 봐야 함 |
| 구조화 출력 | `response_format: {type: "json_schema", json_schema: {strict: true, schema}}`. `provider.require_parameters: true`로 지원 제공자에게만 보냄 | 제공자마다 다름 |
| 호출당 원가 | 응답 `usage.cost`에 항상 포함. 나중에 `/api/v1/generation?id=`로도 조회 | 응답에 원가 없음. 결제 페이지의 월별 모델·제공자 집계로만 봄(API 집계는 Enterprise) |
| 결제 | 크레딧 선불. 한 번에 최소 $5. 카드 수수료 5.5%, 최소 $0.80(그래서 $10 충전도 수수료 $0.80, 청구 $10.80). 모델 단가는 제공자 정가 그대로. 키마다 지출 한도(`limit`) 설정 가능 | 제공자 정가 그대로(수수료 없음). 무료 계정은 포함 크레딧 없음(크레딧 구매 필요), PRO는 월 $2 포함 |
| 무료 모델 | `:free` 모델 있음. 분당 20회, 하루 50회(누적 구매 $10 미만) / 1,000회($10 이상) | 무료 계정 포함 크레딧이 없어짐 |
| 속도 제한 확인 | `GET /api/v1/key` 의 `free_model_daily_requests` | 없음 |

Hugging Face를 주력으로 하지 않는 이유: 기준선(Claude·Gemini)과 GPT를 같은 경로로 비교할 수 없고, 호출당 원가가 응답에 없어 "점수/달러"를 재기 어렵다. **Hugging Face Inference Endpoints**(전용 GPU 시간제)는 대결에서 열린 모델이 이겨 "직접 띄워 고정 원가로 쓰자"가 나올 때 다시 본다. 대결 단계에서는 쓰지 않는다.

참고: OpenRouter 목록 항목에 `hugging_face_id`가 있어 열린 모델이 HF의 어떤 가중치인지 바로 이어진다(예: `z-ai/glm-5.3` → `zai-org/GLM-5.3`).

---

## 2. 후보 모델 11개

같은 편집 프롬프트·같은 생각 강도(`medium`)·같은 라운드 수로 돌린다. 가격은 1M 토큰당 USD(OpenRouter 표시가).

연결 방식(사용자 결정 반영):
- **Gemini 3.8 Flash는 agy CLI**(`--model gemini-3.8-flash-medium`)로 돌린다. 구독이라 원가 $0. agy에는 오디오 입력이 없어 듣기는 다른 후보와 같은 측정 분석이다. agy의 에이전트가 도구를 쓰려다 거절당해 빈 답으로 끝나면(시범에서 두 번 봄) 같은 대화에서 "JSON만 답하라"고 한 번 더 묻는다. 모델의 답을 다시 받는 재시도가 아니라 CLI 고리를 마무리하는 것이라 실패로 세지 않는다.
- **GPT-5.6 Luna·Terra는 codex CLI**(`codex exec -m <모델> -c model_reasoning_effort="medium" --output-schema`)로 돌린다. 구독이라 원가 $0. 토큰 수는 codex의 `turn.completed` 사용량으로 남긴다.
- **나머지는 OpenRouter 경유**. Claude Haiku·Sonnet도 같은 모델·같은 프롬프트라 비교에 문제가 없다. 원가는 OpenRouter `usage.cost`로 잰다.
- **Opus 5.5는 뺀다.** 작업당 최대 약 $0.70. 비싼 쪽 천장은 Sonnet·GPT-5.6 Terra로 본다.

| 가격대 | 모델 (연결 / id) | 입력 | 출력 | 고른 이유 |
|---|---|---|---|---|
| 무료 | OR `nvidia/nemotron-3.5-super-vl:free` | 0 | 0 | 무료 중 `structured_outputs`를 지원하는 큰 모델. 무료가 쓸 만한지의 바닥선 |
| 초저가 | OR `deepseek/deepseek-v4.1-flash` | 0.051 | 0.567 | 가장 싼 축의 최신 코딩 강자 |
| 초저가 | OR `qwen/qwen3.8-flash` | 0.15 | 0.47 | Qwen 최신 Flash |
| 초저가 | OR `z-ai/glm-5.3` | 0.07 | 1.4 | 코딩 평판이 좋은 GLM 최신판. 생각이 필수(`mandatory`)라 출력이 길 수 있음 |
| 초저가 | codex `gpt-5.6-luna` (구독) | (0.2) | (1.2) | OpenAI 저가 줄. 괄호는 API 정가, 실제 원가 $0 |
| 중가 | OR `minimax/minimax-m3` | 0.3 | 1.2 | 에이전트·코딩 특화 중가 |
| 중가 | OR `anthropic/claude-haiku-5.5` (기준선) | 0.1 | 0.5 | 지금 작업실의 싼 선택지 |
| 중가 | OR `moonshotai/kimi-k2.7-code` | 0.6 | 3.5 | 코드 전용 Kimi. 생각 필수 |
| 중가 | agy `gemini-3.8-flash` (기준선, 현재 기본값, 구독) | (0.825) | (4.125) | 제품 기본 모델 |
| 고가 | OR `anthropic/claude-sonnet-5.5` (기준선) | 2 | 10 | 지금 1크레딧 기준 모델 |
| 고가 | codex `gpt-5.6-terra` (구독) | (2) | (12) | OpenAI 상위 줄 |

빠진 것과 이유: `claude-opus-5-5`(예산), `gemma-4-31b-it:free`(무료지만 `json_schema` 미지원), `cohere/north-mini-code:free`(구조화 출력 표시 없음), `gpt-5.5-pro` 계열(출력 1M당 $180), `claude-fable-*`(사용자 지시 없이 쓰지 않음), DeepSeek V4 Pro·Qwen 3.8 Max 등 같은 회사의 상위 모델(예산 안에서 회사당 한 줄만).

---

## 3. 코드에 붙일 자리

### 3.1 지금 흐름 (studio_backend.py)

- `Router`(443행): 키 묶음(`{"gemini", "claude"}`)을 들고, 요청이 고른 `model`이 `MODEL_CHOICES`(30행)에 있고 그 공급자 키가 있으면 그 엔진을 만든다. 없으면 기본 공급자.
- 엔진 모양은 `name`, `hears`, `edit(prompt) -> dict`, `listen(wav, prompt) -> dict` 네 개뿐이다.
  - `Gemini`(305행): urllib로 `generateContent`, `responseSchema`로 JSON 강제, 오디오를 `inlineData`로 보내 **직접 듣는다**(`hears=True`).
  - `Claude`(383행): SDK, `output_config.format=json_schema`(`strict_schema(plain_schema(...))`), 재시도 0, 시스템 프롬프트 캐시. 오디오 입력이 없어 `measured_prompt()`가 `ear.describe(wav)` 측정표를 붙여 판단(`hears=False`, 화면에는 "측정 분석").
  - 실패는 모두 `ModelError(key)`. 자동 재시도 없음(재시도는 돈).
- `Jobs._loop`(875행): `_next_candidate` → `edit_prompt()`로 편집 호출 → `merge_candidate()` 검사 → 브라우저가 실행하고 결과·녹음 WAV를 `feedback`으로 돌려줌 → 실행 실패면 오류를 붙여 다시 편집(`MAX_ERROR_FIXES=2`, 작업 전체 편집 상한은 라운드+1+2).
- `_judge`(929행): `signal_report()`(무음·클리핑·피크) → `listen_prompt()`로 한 번 듣기 호출 → `score`, `problems`, `goal_met`.
- `_next_round`(955행): `goal_met`이거나 문제가 없거나 `score >= GOOD_SCORE(85)`면 끝. 아니면 `MIN_GAIN(3)` 미만 개선이면 멈추고 가장 좋았던 라운드로 되돌림(`_keep_best`).
- `_ask`(824행): 로그인 사용자면 `credits.call_cost(model, effort)`로 호출 전에 차감, 모델 실패면 환불. `credits.MODEL_COST`에 없는 모델은 2크레딧.
- `app.py choose_model()`: `secret()`이 설정 → `~/.all-tomorrow/key-pool.env` 순으로 키를 찾는다.

### 3.2 붙일 모양

1. **`class OpenRouter`** (studio_backend.py, `Claude` 다음). 새 의존성 없이 `Gemini`처럼 urllib로 쓴다.
   - `name = "OpenRouter"`, `hears = False`. `listen()`은 `measured_prompt(wav, prompt)`를 써서 Claude와 같은 "측정 분석"으로 표시한다. 소리를 직접 듣는 척하지 않는다.
   - 요청 본문: `model`, `messages=[{system: SYSTEM}, {user: prompt}]`, `response_format={"type": "json_schema", "json_schema": {"name": "edit"|"listen", "strict": True, "schema": strict_schema(plain_schema(schema))}}`, `provider={"require_parameters": True}`(구조화 출력을 지키는 제공자로만), `reasoning={"effort": effort}`(모델이 지원할 때), `max_tokens=16000`. Anthropic 모델에는 시스템 메시지에 `cache_control`을 붙여 직접 연결과 같은 캐시 이득을 받는다.
   - 대체 모델(`models` 목록)·자동 재시도는 쓰지 않는다. 다른 모델로 몰래 넘어가면 대결이 무의미해진다.
   - 응답의 `usage`(입력·출력·생각 토큰, `cost`)와 실제로 답한 `model`·`provider`를 `self.last_usage`에 남긴다. 제품 쪽은 이 값을 쓰지 않고, 대결 도구가 읽는다.
   - 오류 매핑: 401/403 → `openrouter_key`, 402(크레딧 부족) → `openrouter_credits`, 429 → `openrouter_quota`, 그 밖의 HTTP → `openrouter_http`, 연결 → `openrouter_conn`, JSON 파싱 → `openrouter_parse`, `finish_reason == "length"` → `openrouter_cut`. `MSG`의 `en`·`ko`에 같은 키를 넣는다.
   - `redact()`에 `sk-or-` 로 시작하는 키 무늬를 추가한다.
2. **`Router`**: `openrouter_key` 인자를 받아 `self.keys["openrouter"]`에 넣고, `engine()`에 `provider == "openrouter"` 갈래를 추가한다. 모델 id는 OpenRouter 이름 그대로(`deepseek/deepseek-v4.1-flash`) 쓰고 `MODEL_CHOICES` 항목의 `provider`로 구분한다.
3. **대결 모델은 공개 서버에 안 보이게**: `BAKEOFF_CHOICES`를 따로 두고 `STRUDEL_LOCAL_AI=1`일 때만 `MODEL_CHOICES`에 합친다(공개 서버는 이 값을 켜지 않는다는 app.py 주석과 같은 원칙). 대결이 끝나 공개할 모델을 고르면 그 모델만 `MODEL_CHOICES`로 옮긴다.
4. **app.py `choose_model()`**: `openrouter_key = secret("OPENROUTER_API_KEY")`를 `STRUDEL_LOCAL_AI=1`일 때만 읽어 `Router`에 넘긴다. 키는 `~/.all-tomorrow/key-pool.env`에 `OPENROUTER_API_KEY` 이름으로 들어 있다. 코드·문서·로그 어디에도 값을 적지 않는다.
5. **credits.py `MODEL_COST`**: 대결 중에는 로컬이라 장부를 쓰지 않으므로 손대지 않는다. 공개할 모델이 정해지면 대결에서 잰 "작업당 평균 원가"를 Sonnet 원가와 비교해 크레딧 값을 정한다(1크레딧 = Sonnet 한 호출이라는 기존 기준 유지).
6. **Gemini도 `last_usage`**: 직접 연결 원가를 같은 방식으로 재려고 `Gemini._call`은 `usageMetadata`를 `self.last_usage`에 남긴다(Claude 직접 연결도 같은 모양으로 맞춰 둔다). 동작은 바뀌지 않는다.
7. 단위 시험(tests/test_studio_backend.py): 가짜 HTTP 서버로 OpenRouter 성공·402·429·잘린 응답·스키마 깨진 응답, `Router`가 키 없을 때 OpenRouter 모델을 내주지 않는 것, 공개 모드에서 `BAKEOFF_CHOICES`가 안 보이는 것.

### 3.3 대결 도구 (새 파일, 제품 코드와 분리)

- `bakeoff/tasks.json`: 고정 과제, 고정 4트랙 곡, 모델별 연결·배정·작업당 최대 원가, 심판, 예산 규칙(4·8절).
- `bakeoff/core.py`: 설정·결과 파일 읽기, 키 읽기(값은 어디에도 쓰지 않음), `CodexCli` 엔진, 호출을 기록하는 `Recorder`, 성공·실패·기반 실패 판정.
- `bakeoff/harness.py` + `harness_app.py`: 진짜 `app.py`를 그대로 띄우되 엔진만 `Recorder`로 감싼 대결 엔진으로 바꾼다. 제품의 작업 루프·한도·프롬프트는 그대로이고, 벽시계 한도만 모든 모델에 똑같이 15분으로 늘렸다(CLI 시작 시간은 모델 탓이 아니므로). 작업이 끝나면 상태·메시지·고치기 수·최종 곡을 끝 줄로 남긴다.
- `bakeoff/run.py`: `python bakeoff/run.py --models ... --tasks ... --reps N --workers N`. 작업실 서버를 일꾼 수만큼 띄우고(Playwright + 헤드리스 Chrome) 실제 작업실 화면으로 과제를 보낸다. 실행·녹음은 진짜 브라우저 Strudel이 한다. 호출마다 시각, 걸린 시간, `last_usage`, 받은 JSON, 녹음 WAV(라운드별)를 `bakeoff/results/<모델>/<과제>-<반복>.jsonl`·`-r<라운드>.wav`로 저장한다. 끝 줄이 있는 작업은 건너뛰고(이어 하기), 기반 실패는 한 번만 다시 돌린다(이전 시도는 `old/`에 남아 원가에 계속 잡힌다). 예산 멈춤(8.4절)도 여기서 한다. `--dry-run`은 남은 작업과 모델별 상한만 보여 준다.
- `bakeoff/referee.py`: 성공한 작업의 최종 WAV(되돌림이 있으면 가장 좋았던 라운드의 WAV)를 심판 모델에 고정 프롬프트로 채점시킨다(5절). `results/referee.jsonl`, 이미 채점한 곡은 건너뜀.
- `bakeoff/report.py`: 지표 표(`results/report.md`, `report.json`)와 점수 대 원가 그림(`score_vs_cost.svg`), 결선 6모델.
- `bakeoff/clips.py`: 결선 모델의 ★ 공통 과제 곡을 같은 길이·같은 음량(-16 LUFS)으로 맞춰 무작위 이름의 mp3로 `static/bakeoff/`에 둔다(`/app/static/bakeoff/`로 제공). 모델 대응표는 이 PC의 `results/listen/manifest.json`에만 있다.
- `pages/listen.py` + `bakeoff/listen_store.py`: 사람 블라인드 청취 페이지(6절).
- `results/`와 `static/bakeoff/`는 커밋하지 않는다(.gitignore).
- 긴 실행은 본 세션에서 백그라운드로 돌리고, 결과 분석만 따로 맡긴다.

---

## 4. 고정 과제 세트 (8개)와 배정

모두 자동 모드(`auto=True`), 라운드 2(`DEFAULT_ROUNDS`), 생각 강도 `medium`, 언어 `ko`. 1~6번은 빈 곡에서 시작, 7~8번은 `bakeoff/tasks.json`에 고정한 4트랙 곡에서 시작한다. **★표 4개는 공통 과제**로, 모든 모델이 돌리고 사람 청취도 이것으로 한다.

| # | 장르 | 요청 문장 | 보는 것 |
|---|---|---|---|
| 1★ | 하우스 | 120BPM 하우스. 4박 킥, 오프비트 하이햇, 통통 튀는 베이스 | 기본 박자·장르 문법 |
| 2★ | 로파이 힙합 | 비 오는 밤 공부할 때 듣는 로파이. 느슨한 드럼, 따뜻한 재즈 코드 | 스윙·코드 진행·분위기 |
| 3 | 앰비언트 | 드럼 없이 천천히 숨 쉬듯 변하는 앰비언트 패드와 멀리서 들리는 종소리 | 리듬 없는 곡, 변화 |
| 4★ | 신스팝 | 80년대 신스팝. 밝은 아르페지오와 귀에 남는 4마디 멜로디 | 멜로디 기억성 |
| 5 | 테크노 | 어두운 미니멀 테크노, 반복되며 조금씩 필터가 열리는 신스 | 시간에 따른 변조 |
| 6 | 칩튠 | 8비트 게임 배경음악. 모험을 떠나는 느낌 | 음색 선택·악곡 구조 |
| 7★ | 편집(트랙 지정) | (고정 곡의 bass 트랙만) 베이스를 더 그루비하게, 다른 트랙은 건드리지 마 | 지정 트랙만 고치는 규율 |
| 8 | 편집(전체) | (고정 곡 전체) 이 곡을 반으로 느린 템포의 슬픈 발라드로 바꿔 | 큰 구조 변경 |

모델별 배정(가격이 높을수록 작업 수를 줄임):

| 묶음 | 모델 | 과제 | 반복 | 작업 수 |
|---|---|---|---|---|
| CLI(구독, 원가 $0) | gemini 3.8 flash(agy), gpt-5.6 luna·terra(codex) | 8개 전부 | 3 | 각 24 |
| OpenRouter 싼 모델 | nemotron free, deepseek v4.1 flash, qwen3.8 flash, minimax m3, haiku 5.5 | 8개 전부 | 3 | 각 24 |
| OpenRouter 생각이 긴 모델 | glm-5.3 | 8개 전부 | 2 | 16 |
| OpenRouter 비싼 중가 | kimi k2.7 code | 8개 전부 | 1 | 8 |
| OpenRouter 고가 | sonnet 5.5 | ★ 공통 4개 | 2 | 8 |
| **합계** | | | | **224작업** |

남는 OpenRouter 예산으로 싼 모델 반복을 2 → 3, glm 1 → 2, sonnet 1 → 2로 늘렸다(8절). 반복이 1~3회라 통계 구간이 넓다. 이 대결은 "후보를 거르는 1차 선별"이고, 차이가 작으면 동점으로 본다(7절). 결선에 오른 모델을 더 돌릴 필요가 생기면 예비비(8절) 안에서 공통 과제 반복만 늘린다.

---

## 5. 측정 지표

한 작업 = 과제 하나를 한 번 끝까지 돌린 것.

| 지표 | 정의 | 출처 |
|---|---|---|
| 실행 성공률 | 작업이 실행되는 곡을 남기고 끝난 비율(`done` 또는 라운드 소진 `limit`). `fix_limit`·`run_failed`·`ModelError`는 실패 | 작업 최종 상태 |
| 첫 시도 성공률 | 첫 편집 결과가 고치기 없이 바로 실행된 비율 | `Progress.fixes` |
| 고치기 횟수 | 작업당 실행 오류·형식 오류로 다시 부른 수의 평균 | `Progress.fixes` |
| 형식 오류율 | 응답 JSON 파싱·스키마·`merge_candidate` 거절 비율 | Recorder 기록 |
| 무음·클리핑 | 최종 곡의 `signal_report` 무음·클리핑 비율 | `signal_report()` |
| 심판 점수 (주 지표) | 최종 WAV를 심판이 0~100으로 채점. 심판 A: `gemini-3.8-flash`(agy CLI, 구독)가 `ear.describe` 측정표로 채점(직접 API를 쓰지 않기로 해서 소리를 직접 듣지 않음). 심판 B: `qwen/qwen3.8-flash`(OpenRouter)가 같은 측정표로 채점. 둘 다 짧은 고정 프롬프트(요청 문장 + "얼마나 요청을 만족하고 듣기 좋은가"), 모델 이름·자기 평가는 주지 않고 긴 `SYSTEM`도 붙이지 않음 | `referee.py` |
| 자기 점수 | 모델이 자기 `listen`에서 매긴 점수. 순위에는 쓰지 않고 "자기 평가가 얼마나 후한가"(자기 점수 − 심판 점수)만 본다 | Recorder 기록 |
| 걸린 시간 | 작업 전체 벽시계 시간, 모델 호출 시간 합 | Recorder 기록 |
| 호출당·작업당 원가 | OpenRouter는 응답 `usage.cost` 합. Gemini 직접은 응답 토큰 × 직접 API 단가 | Recorder 기록 |
| 점수/달러 | 평균 심판 점수 ÷ 작업당 평균 원가. 무료 모델은 따로 표시 | `report.py` |

심판 편향 주의: 심판 A(Gemini)는 후보이기도 하고, 심판 B(Qwen)도 후보다. 둘 다 자기 계열을 후하게 볼 수 있어, 두 심판 순위가 크게 엇갈리는 모델은 사람 청취에서 반드시 다룬다. 최종 판단은 사람이 한다.

공정성 규칙:
- 모든 모델에 같은 `SYSTEM`, 같은 `edit_prompt`·`listen_prompt`, 같은 라운드·생각 강도. 생각을 끌 수 없는 모델(`reasoning.mandatory`)은 그대로 두고 표에 표시.
- 순위 비교는 같은 과제끼리만 한다. 고가 모델은 ★ 공통 4과제만 돌렸으므로, 모델 간 전체 순위는 ★ 공통 4과제 점수로 매기고, 나머지 과제는 싼·중가 모델끼리 보조 비교에 쓴다.
- 작업 순서는 모델·과제를 섞어 무작위로(시간대에 따른 제공자 속도 차이를 고르게).
- 모델 실패는 재실행하지 않고 실패로 센다. 우리 쪽 문제(브라우저 멈춤, 무료 모델 429, 네트워크)는 "기반 실패"로 따로 표시하고 한 번만 다시 돌린다.

---

## 6. 사람 블라인드 청취 (꼭 필요함)

"음악이 좋은가"는 측정·심판 모델로 판정할 수 없다. 이 단계는 **사람이 직접 들어야 하며, 자동 결과만으로 우승을 정하지 않는다.**

- 결선 6모델: 자동 지표에서 가격대별 1등(무료·초저가·중가·고가) + 현재 기본값 `gemini-3.8-flash` + `claude-sonnet-5.5`(겹치면 다음 순위로 채움).
- 결선 6모델의 8과제 전부 × 녹음된 반복 전부(최대 3회)의 최종 곡(과제·반복마다 곡 세트 하나, 모델 3개 이상일 때만). sonnet은 비공통 4과제도 2회씩 돌려 넣는다. 처음엔 ★ 공통 4과제 × 첫 반복 24개였는데, 같은 곡이 너무 자주 나와 2026-11-08 사용자 요청으로 늘렸다. 기존 클립 이름은 그대로라 앞선 투표도 센다. 비공통 과제에는 sonnet 곡이 없다. 클립은 같은 길이(녹음 구간 그대로)로 자르고 음량을 맞춘다(LUFS 정규화).
- 만들기: `python bakeoff/clips.py`(결선은 `report.json`에서, 또는 `--models`로 지정). 무작위 이름의 mp3가 `static/bakeoff/`에 생기고, 다시 만들면 예전 클립은 지워진다.
- 페이지: **`https://olmuse.app/listen`** (`pages/listen.py`). 로그인 없이 열리고, 사람마다 이름이나 별명만 적는다. 과제별로 클립을 사람마다 다른(같은 이름이면 늘 같은) 무작위 순서의 "곡 A~G"로만 보여 준다. 모델 이름·가격·심판 점수는 숨긴다. 청취자는 곡마다 1~10점을 고르고 "요청과 안 맞음"을 표시할 수 있다. 고르는 즉시 이 PC의 `.studio-data/listen.sqlite`에 저장된다(저장 단추 없음). 같은 이름으로 다시 오면 이어서 한다.
- 결과: 같은 페이지 아래에 누가 몇 곡 들었는지는 늘 보이고, 모델 이름을 밝힌 결과는 `STUDIO_PASSWORD`를 넣어야 보인다. 모든 표가 모였는지는 그 진행표로 보고 연다.
- 집계: 같은 청취자·같은 과제 안에서 점수를 쌍대 비교(이기면 1, 같으면 0.5)로 바꿔 Bradley–Terry 강도를 구한다. 청취자가 여럿이면 합친다. 평균 점수와 "안 맞음" 수도 함께 본다.
- 같은 쌍을 좌우 바꿔 다시 묻는 일관성 확인은 2026-11-08 사용자 결정으로 없앴다.
- 청취는 돈이 들지 않는다(이미 녹음된 WAV).

---

## 7. 판정 방법

1. **자격**: 실행 성공률 75% 이상, 형식 오류율 25% 이하인 모델만 순위에 올린다(작업 수가 적어 기준을 조금 낮춤).
2. **자동 순위**: ★ 공통 4과제에서 두 심판 평균 점수의 평균과 부트스트랩 95% 구간. 구간이 겹치면 동점으로 본다.
3. **가격 효율**: 심판 점수 대 작업당 원가의 파레토 앞줄(더 싸면서 더 잘하는 모델이 없는 모델)을 표시.
4. **최종**: 사람 블라인드 점수로 결선 순위를 정한다. 자동 순위와 다르면 사람 순위를 따른다.
5. **바꿀지 판단 기준**:
   - 기본 모델 교체: 사람 점수에서 현재 기본값(`gemini-3.8-flash`)보다 높거나 같고, 작업당 원가가 같거나 낮으면 교체 후보.
   - 싼 선택지 추가: Sonnet과 사람 점수가 동점(구간 안)이면서 원가가 1/5 이하인 모델은 공개 선택지에 추가할 후보. 크레딧 값은 3.2의 5번대로 정한다.
   - 아무 모델도 기준선을 못 넘으면 그 사실을 결과로 남기고 지금 구성을 유지한다.
   - 반복이 적어 결론이 동점으로만 나오면, 그 동점 모델들만 예비비로 공통 과제 반복을 늘려 다시 본다.

---

## 8. 예산 배분 (OpenRouter 잔액 약 $9.8 + CLI 구독)

### 8.1 가정

- 라운드 2 자동 작업 하나가 **최대** 편집 5회 + 듣기 3회 = 8호출. 호출당 입력 약 7천 토큰(시스템 프롬프트 약 1.4만 자 ≈ 4천 토큰 + 곡·대화), 출력 약 3천 토큰(생각 포함) → 작업당 최대 입력 56k, 출력 24k. 생각이 필수인 GLM-5.3은 출력 3배, Kimi K2.7 Code는 2배로 잡았다.
- 아래 금액은 모두 이 **최대치**다. 대부분의 작업은 일찍 끝나 실제로는 더 적다. 시범 실측: qwen3.8-flash 과제 1 한 작업이 $0.014(편집 한 번이 생각으로 16k 토큰을 다 써 잘림), 호출당 50~150초.
- 심판 호출은 짧은 프롬프트(측정표 포함 입력 약 3천 토큰, 출력 약 500 토큰).

### 8.2 지갑

| 지갑 | 금액 | 비고 |
|---|---|---|
| OpenRouter 크레딧 | 잔액 약 $9.80 (이미 충전) | `GET /api/v1/credits`. 키 자체 한도는 $50으로 잡혀 있고 이 키로는 바꿀 수 없어, 잔액이 사실상의 한도다 |
| agy CLI (Gemini) | 구독, 원가 $0 | 후보 gemini-3.8-flash + 심판 A |
| codex CLI (GPT) | 구독, 원가 $0 | 후보 gpt-5.6-luna, gpt-5.6-terra |

### 8.3 모델별 예상 비용 (OpenRouter만)

| 가격대 | 모델 | 작업당 최대 | 작업 수 | 최대 비용 |
|---|---|---|---|---|
| 무료 | nemotron-3.5-super-vl:free | $0 | 24 | $0.00 |
| 초저가 | deepseek-v4.1-flash | $0.017 | 24 | $0.41 |
| 초저가 | qwen3.8-flash | $0.020 | 24 | $0.48 |
| 초저가 | glm-5.3 | $0.105 | 16 | $1.68 |
| 중가 | minimax-m3 | $0.046 | 24 | $1.10 |
| 중가 | claude-haiku-5.5 | $0.018 | 24 | $0.43 |
| 중가 | kimi-k2.7-code | $0.20 | 8 | $1.60 |
| 고가 | claude-sonnet-5.5 | $0.35 | 8 | $2.80 |
| 심판 | B: qwen3.8-flash 측정 판단 (성공한 곡 최대 224곡) | $0.0007 | 224 | $0.16 |
| | **OpenRouter 합계(최대)** | | | **$8.66** |
| | **예비비** (잔액 $9.80 − 최대 합계) | | | **$1.14** |

CLI 모델(gemini-3.8-flash 24, gpt-5.6-luna 24, gpt-5.6-terra 24작업)과 심판 A는 $0(구독). 구독 사용 한도에 걸리면 그 호출은 "기반 실패"로 한 번만 다시 돈다.

예비비 쓰는 곳(순서대로): ① 기반 실패 재실행 ② 실측 원가가 예상보다 크게 나온 모델의 부족분 ③ 동점 결선 모델의 공통 과제 반복 추가.

### 8.4 넘침 방지

- 키 한도를 $10로 거는 대신(이 키로는 못 바꿈) 잔액 자체가 상한이다. 잔액이 바닥나면 402가 나고 `openrouter_credits`로 멈춘다(재시도 없음).
- `run.py`는 OpenRouter 작업마다 시작 전에 ① 그 모델의 누적 원가(이전 시도 포함)가 8.3 최대 비용 × 1.3을 넘었으면 그 모델의 남은 작업을 멈추고 `results/budget_stops.jsonl`에 "예산 초과"로 남기고 ② 계정 잔액이 $0.20 밑이면 모든 OpenRouter 작업을 멈춘다. `referee.py`도 심판 B에 같은 규칙을 쓴다.

---

## 9. 순서와 끝난 기준

| 순서 | 할 일 | 끝난 기준 |
|---|---|---|
| 1 | OpenRouter 키 등록·충전 | 끝남: `key-pool.env`에 `OPENROUTER_API_KEY`, 잔액 약 $9.8 (`GET /api/v1/credits`). 키 한도는 $50으로 잡혀 있어 run.py의 예산 멈춤이 대신한다(8.4) |
| 2 | `OpenRouter` 엔진·`Router` 갈래·`BAKEOFF_CHOICES`·`last_usage` 추가와 단위 시험 | 끝남: 단위 시험 통과, 공개 모드에서 대결 모델이 안 보임 |
| 3 | `bakeoff/` 도구(tasks, run, referee, report, clips, 청취 페이지)와 예산 멈춤 | 끝남: 가짜 엔진으로 과제 2개가 끝까지 돌고 기록·WAV·누적 원가가 남음, 가짜 원가로 예산 멈춤이 걸림(tests/test_bakeoff.py) |
| 4 | 시범: OpenRouter 1모델 + agy 1모델 + codex 1모델 × 과제 1 × 반복 1 | 세 연결 모두 실제 작업실로 끝까지 돌고 기록·WAV·원가가 남음. 나머지 모델의 첫 작업은 본 실행 앞부분이 시범을 겸한다 |
| 5 | 본 실행(백그라운드): `python bakeoff/run.py --workers 4 --finish` | 224작업이 모두 성공·실패·기반 실패·예산 초과 중 하나로 끝나고, 이어서 심판 채점·보고서·청취 클립까지 만들어짐 |
| 6 | 심판 채점·자동 보고서 | 모델별 지표 표, 점수 대 원가 그림, 결선 6모델, 지갑별 실제 지출 |
| 7 | 사람 블라인드 청취(`https://olmuse.app/listen`) | 모든 청취자가 모든 클립에 점수를 매김(페이지 진행표), 일관성 확인 클립 결과 포함 |
| 8 | 판정·반영 계획 | 7절 기준에 따른 결론(교체·추가·유지)과 `MODEL_COST` 제안 값이 결과 문서에 적힘 |
