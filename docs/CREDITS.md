# 로그인과 크레딧

## 흐름

1. 첫 화면에서 구글 계정으로 로그인한다. 처음 로그인한 계정에 무료 20 크레딧이 들어간다.
2. AI를 부를 때마다 그 호출 값만큼 빠진다. 호출이 실패하면 돌려준다. 크레딧이 모자라면 부르기 전에 멈춘다.
3. 위쪽 `크레딧` 버튼에서 남은 양, 호출당 값, 내역, 충전 코드가 보인다.
4. 충전은 Buy Me a Coffee 결제다. 1달러당 20 크레딧. 메시지에 계정의 `SD-XXXXXX` 코드가 있어야 그 계정에 들어간다. 코드가 없으면 블로그 후원으로만 처리된다. 결제는 블로그의 `bmc-webhook`이 받아 코드 건만 장부로 넘긴다(`deploy/credits/README.md`).
5. 선생님 비밀번호로 연 작업실은 크레딧을 쓰지 않는다.

## 값 (호출 1번당)

| 모델 | 크레딧 |
|---|---|
| Haiku 5.5, Gemini 3.8 Flash | 1 |
| Sonnet 5.5 | 1 |
| Opus 5.5 | 3 |
| 추론 "깊게" | +1 |

요청 한 번은 호출 1번이다. 자동 개선을 켜면 회차마다 고치기와 측정이 1번씩이라, 최대 `값 × 2 × (회차 + 1)`. 입력창 위에 최대 크레딧이 보인다. 값은 `credits.py`의 `MODEL_COST`, `EFFORT_EXTRA`에서 바꾼다.

### 근거: 2026-11-07 실측

4트랙 곡에 고치기, 측정, 고치기 3번 호출. 시스템 프롬프트 캐시를 켠 뒤 측정했다. 측정 스크립트는 남기지 않았고, 단가는 조사 노트의 공식 가격표다.

| 모델 | 빠르게 | 보통 | 깊게 |
|---|---|---|---|
| Haiku 5.5 | $0.0009 | $0.0006 | $0.0009 |
| Sonnet 5.5 | $0.0189 (캐시 첫 쓰기 포함) | $0.0068 | $0.0122 |
| Opus 5.5 | $0.0395 (캐시 첫 쓰기 포함) | $0.0260 | $0.0294 |

1 크레딧 = 5센트, BMC 수수료(약 15%) 뺀 4.25센트. Sonnet 한 번의 최악 원가(약 2센트)의 두 배, Opus 3 크레딧(12.75센트)은 Opus 최악 원가(약 4센트)의 세 배다. 무료 20 크레딧의 원가는 사용자 1명당 Sonnet 기준 약 0.2~0.4달러.

## 운영 설정

| 이름 | 위치 | 뜻 |
|---|---|---|
| `[auth]` | `.streamlit/secrets.toml` 또는 Cloud Secrets | 구글 로그인. 아래 예시 |
| `STRUDEL_CREDITS_URL` | 환경 변수 또는 Secrets. `run_public.ps1`이 넣는다 | 장부 Lambda 주소. 없으면 이 PC의 `.studio-data/credits.sqlite`만 쓴다 |
| `STRUDEL_CREDITS_TOKEN` | Secrets. 이 PC에서는 `~/.all-tomorrow/strudel-credits.token` | 장부 호출 토큰 |
| `STRUDEL_BUY_URL` | 선택 | 기본 `https://buymeacoffee.com/innollia` |
| `STRUDEL_CREDITS_PER_USD` | 선택 | 화면에 보이는 값. Lambda의 `CREDITS_PER_USD`와 같아야 한다 |

장부 서버는 `deploy/credits/README.md`.

### 구글 로그인 준비 (사람이 할 일)

아직 설정되지 않았다. 아래를 마치기 전에는 공개 서버에서 로그인과 크레딧이 동작하지 않는다.

1. Google Cloud Console → API 및 서비스 → OAuth 동의 화면을 외부로 만든다.
2. 사용자 인증 정보 → OAuth 클라이언트 ID → 웹 애플리케이션.
3. 승인된 리디렉션 URI에 `https://olmuse.app/oauth2callback`을 넣는다. 로컬 시험이면 `http://localhost:8501/oauth2callback`도 넣는다.
4. 받은 클라이언트 ID와 시크릿을 secrets에 넣는다.

```toml
[auth]
redirect_uri = "https://olmuse.app/oauth2callback"
cookie_secret = "<긴 무작위 문자열>"
client_id = "<클라이언트 ID>"
client_secret = "<클라이언트 시크릿>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

공개 주소는 `https://olmuse.app`이다. `run_public.ps1`이 이 PC의 이름 있는 cloudflared 터널 `olmuse`(`~/.cloudflared/olmuse.yml`)를 띄운다. 주소가 고정이라 리디렉션 URI는 한 번만 넣으면 된다.

### 로컬 시험

`STRUDEL_LOCAL_AI=1`이고 구글 설정이 없을 때만 `STRUDEL_DEV_EMAIL`이 로그인한 계정 대신 쓰인다. 공개 서버(`run_public.ps1`)는 `STRUDEL_LOCAL_AI`를 지운다.
