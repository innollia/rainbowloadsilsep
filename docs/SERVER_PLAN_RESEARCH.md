# 서버 구조개편 조사: Streamlit 이후, 서버 운영, 사용자 데이터

조사일 2026-11-09. 현재 구조는 코드에서 읽은 것이다. 가격과 제도는 웹에서 찾은 것이고 출처는 맨 끝에 있다. 가격은 바뀌므로 결제 전 공식 페이지에서 다시 본다.

## 결론

- Streamlit은 떠난다. 화면은 이미 `studio_frontend/`의 자체 JS라서 Streamlit이 하는 일은 "1초마다 앱 전체를 다시 돌려 상태를 건네는 다리"뿐이다. 이 다리가 확장·재시작·로그인 문제의 원인이다.
- 가장 작은 이동: FastAPI 한 프로세스가 같은 정적 화면을 내주고 JSON API(+진행 상황은 폴링 또는 SSE)를 연다. `studio_backend.py`의 모델 라우터·Jobs·크레딧 로직은 그대로 쓴다.
- 돈과 관련된 진실은 지금처럼 Lambda+DynamoDB 장부에 둔다. 작업 기록·사용량·곡은 새 서버의 DB에 둔다. 작업이 메모리에만 있어 재시작 때 사라지는 것을 먼저 고친다.
- 서버는 집 PC+터널에서 서울 리전 VPS 한 대(Lightsail 등, 월 $5~12)로 옮긴다. 컨테이너 플랫폼·Lambda는 몇 분짜리 AI 작업과 맞지 않거나 비용 계산이 복잡하다.
- 결제는 Buy Me a Coffee(후원 도구)로는 판매 서비스가 되기 어렵다. 사업자등록 여부를 먼저 정해야 한다. 국내 사업자면 토스페이먼츠, 해외 판매 위주면 MoR(Paddle 등)이 후보다. Stripe는 한국 법인으로 가입이 안 된다.

## 현재 구조 (코드에서 확인한 것)

| 영역 | 지금 | 근거 파일 |
|---|---|---|
| 호스팅 | 이 Windows PC에서 `streamlit run app.py`(127.0.0.1:8501). Cloudflare 이름 있는 터널 `olmuse`가 olmuse.app으로 연결. 터널이 죽으면 루프가 다시 띄우고, all-tomorrow DP7 감시가 사이트가 안 열리면 스크립트를 다시 돌린다. Dockerfile 없음. README의 Streamlit Cloud 안내는 예전 내용 | `run_public.ps1`, `~/.cloudflared/olmuse.yml` |
| 화면 | `studio_frontend/`(app.js 1200줄 등)를 `components.declare_component`로 띄움. 브라우저→Python은 `streamlit:setComponentValue`(event_id, action, payload), Python→브라우저는 `streamlit:render` 인자 | `app.py` 290행, `studio_frontend/app.js` 239·293행 |
| 진행 상황 전달 | `@st.fragment(run_every=1)`로 열린 탭마다 1초에 한 번 서버 코드가 돈다 | `app.py` 367행 |
| 로그인 | `st.login("google")`(OIDC, `.streamlit/secrets.toml`)과 선생님 비밀번호(`STUDIO_PASSWORD`, 크레딧 안 씀). 비밀번호는 세션당 5번, 전체 시간당 20번 틀리면 잠긴다(`server_ops.PasswordGate`). 비밀번호 세션의 운영자 키 지출은 하루 최악 0.60달러로 묶인다(`STRUDEL_OPERATOR_DAILY_USD`) | `app.py` `login_screen`, `server_ops.py` |
| 작업 | `Jobs.jobs[owner]` 메모리 딕셔너리 + daemon 스레드. 에셋 에이전트(`Agents`)도 같은 방식. 작업 화면·진행 중 차감·하루 호출 수는 `JobStore`(SQLite `.studio-data/jobs.sqlite3`)에도 쓴다. 재시작하면 `running` 작업을 `failed`로 닫고 끝나지 않은 차감을 한 번 환불한다. 이메일은 장부와 같은 HMAC 키로만 저장하고, 끝난 결과는 30일 뒤 지운다 | `studio_backend.py` `JobStore`, `asset_agent.py` |
| 운영 | 로그는 `.studio-data/logs/olmuse.log`(하루 단위, 7일 보관, 이메일·키 가림). SQLite는 매일 `.studio-data/backups/날짜/`로 백업 API 복사(14일). 장부 DynamoDB는 PITR, ALERT 경보·예산 알림 메일 | `server_ops.py`, `tools/backup_data.py`, `deploy/credits/deploy.ps1` |
| 크레딧 | 진짜 장부는 Lambda Function URL + DynamoDB 1테이블(`strudel-credits`, 서울). 차감은 호출 전, 실패하면 환불, ref로 멱등, 이메일은 HMAC 키로만 저장. 개발·시험은 SQLite `LocalLedger` | `credits.py`, `deploy/credits/` |
| 결제 | BMC 결제 → 블로그 `bmc-webhook` Lambda → 장부 `/webhooks/bmc`. 메시지의 단어 코드로 계정을 찾고, 못 찾으면 "결제 찾기". 1달러당 20크레딧 | `docs/CREDITS.md`, `deploy/credits/README.md` |
| 곡·프로젝트 | 브라우저 localStorage/IndexedDB에만 있다. 다른 기기에서 이어 하기 없음(EDGE_CASES 12번) | `docs/EDGE_CASES.md` |
| 다른 페이지 | 아케이드·BLACK BOX 09는 Streamlit 위젯으로 만든 페이지(`runpy`로 실행) | `arcade_page.py`, `blackbox_page.py` |

### 지금 구조의 위험

- (해결됨) 재시작 때 작업과 하루 호출 수가 사라지고 차감이 환불되지 않던 문제는 `JobStore`로 고쳤다. 남은 것: 생성 중 서버를 강제로 죽였다 살려 실제 장부에 환불 기록이 남는지 실측.
- 탭마다 1초 재실행이라 사용자 수에 비례해 CPU가 늘어난다. Streamlit은 세션 상태가 프로세스 메모리에 있어 서버를 두 대로 늘리려면 고정 세션(sticky)과 외부 상태 저장소가 필요하다. 그래도 400~500명 규모에서 막혔다는 보고가 있다.
- `st.login`은 범위(scope) 지정과 액세스 토큰을 못 주고, 1.57에서 로그인 쿠키가 30일 대신 브라우저 세션 쿠키가 되는 문제가 보고됐다. 로그인 동작을 우리가 고칠 수 없다.
- 집 PC가 꺼지거나 재부팅·업데이트되면 유료 서비스가 멈춘다. 같은 PC에서 다른 작업도 돈다.

## 목표 구조

| 층 | 목표 | 바꾸는 이유 |
|---|---|---|
| 화면 | `studio_frontend/` 그대로. Streamlit 다리(`toHost`, `onRender`)만 `fetch` 기반 작은 모듈로 바꾼다 | 화면은 이미 독립적이다 |
| API 서버 | FastAPI(Starlette) + uvicorn 한 프로세스. 정적 파일, `/api/*` JSON, 진행 상황은 `GET /api/job` 폴링(1초) 또는 SSE | 요청마다 필요한 함수만 돈다. 시간 제한·오류 처리를 직접 정한다 |
| 작업 실행 | 처음엔 같은 프로세스의 스레드를 유지하되 작업 상태를 DB에 쓴다. 시작할 때 `running`으로 남은 작업은 "중단"으로 닫고 차감분 환불. 사용자가 늘면 Postgres 기반 큐(procrastinate, PgQueuer 등)로 별도 워커 프로세스 | Redis를 새로 들이지 않고 재시작 안전성부터 얻는다 |
| 로그인 | Authlib(이미 requirements에 있음)로 구글 로그인, 서명된 세션 쿠키. 선생님 비밀번호 모드 유지. `owner = "acct:" + email` 규칙 유지 | 쿠키 수명·로그아웃·인앱 브라우저 처리를 우리가 정한다 |
| 돈 장부 | 지금 Lambda+DynamoDB 유지. 새 결제 수단 웹훅도 같은 Lambda에 추가 | 이미 멱등·동시성·감사 기록이 있다. 옮길 이유가 없다 |
| 서비스 DB | 작업 기록, 하루 사용량, 곡·프로젝트 동기화. 서버 한 대면 SQLite(디스크 백업 포함)로 시작, 서버가 둘 이상이 되면 Postgres(Neon·Supabase·RDS) | 돈이 아닌 데이터는 서버 가까이 둔다 |
| 호스팅 | 서울 리전 VPS 1대(Lightsail 등). 앞단은 지금 Cloudflare(터널 또는 DNS) 그대로 | 몇 분짜리 작업에 시간 제한이 없고, 비용이 고정이다 |
| 아케이드·BLACK BOX | 결정 필요(열린 질문 4) | Streamlit 위젯으로 만든 페이지라 그대로는 못 옮긴다 |

## 선택지 비교

### 1. 앱 틀

| 선택지 | 비용 | 작업량 | 위험 |
|---|---|---|---|
| Streamlit 유지 + 고정 세션·외부 상태 | 0 | 중간(상태를 다 밖으로 빼야 함) | 1초 재실행·로그인 제약은 그대로 |
| FastAPI가 같은 화면 + JSON API (추천) | 0 | 중간: `app.py` 다시 쓰기, `app.js` 다리 교체, 로그인 | 다리 교체 중 화면 흐름 회귀. e2e 시험으로 막는다 |
| Next.js 등 새 프런트 + Python API | 0 | 큼: 화면 2400줄 재작성 | 이미 된 화면을 다시 만든다 |
| FluxLit처럼 Streamlit 옆에 API 붙이기 | 0 | 작음 | 핵심 문제(재실행, 메모리 상태)가 남는다 |

### 2. 서버 운영 (월 비용은 출처의 2026년 수치, 대략)

| 선택지 | 월 비용 | 작업량 | 몇 분짜리 AI 작업 | 위험 |
|---|---|---|---|---|
| 집 PC + Cloudflare 터널 (지금) | 전기료 | 없음 | 제한 없음 | PC 끄기·재부팅·다른 작업과 충돌. 유료 서비스로는 약함 |
| VPS 1대: Lightsail 서울 $5~12, Hetzner €4~7(유럽) (추천: Lightsail 서울) | $5~12 | 작음: systemd 또는 Docker 하나 | 제한 없음 | 서버 관리(업데이트·백업)를 직접. 멈춰 있어도 과금 |
| Fly.io / Railway / Render | 작은 상시 인스턴스 $5~7, Railway Pro $20 | 작음 | 대체로 가능 | 2026년 장애 보고(Railway 8시간 등). 무료 등급은 잠든다 |
| Cloud Run | 최소 인스턴스 1개를 켜 두면 인스턴스 요금 상시 | 중간 | 요청 최대 60분. 축소 때 연결 끊김 | 백그라운드 스레드는 인스턴스 기반 과금이어야 안전 |
| Lambda + API Gateway | 사용량 비례(작음) | 큼: 작업을 단계별로 쪼개야 함 | API Gateway 29초, 함수 최대 15분 | 자동 개선 여러 회차를 한 호출에 못 담는다 |

### 3. 데이터 위치

| 데이터 | 추천 위치 | 다른 후보 |
|---|---|---|
| 크레딧 잔액·차감·환불·결제 | DynamoDB 장부(지금) | Postgres로 합치기: 이전 비용만 들고 얻는 게 적다 |
| 작업 기록·하루 사용량 | 서버 DB(SQLite → Postgres) | DynamoDB에 같이: 질의가 불편 |
| 곡·프로젝트 | 서버 DB + 큰 파일은 S3 | 지금처럼 브라우저만: 기기 이동 불가 |
| 계정 | 구글 이메일 → HMAC 키(지금 방식 유지) | 평문 이메일 저장은 하지 않는다 |

관리형 Postgres: Supabase 무료는 500MB이고 1주 쉬면 멈춘다. Pro $25/월. Neon 무료 512MB, 쉬면 0으로 줄었다가 바로 깨어난다. RDS는 가장 작은 것도 상시 과금이다. 서버 한 대 단계에서는 필요 없다.

### 4. 결제

| 선택지 | 조건 | 비용 | 맞는 경우 |
|---|---|---|---|
| Buy Me a Coffee (지금) | 개인 가능 | 5% + 결제 수수료(약 2.9%+30¢, 해외 +1%), 출금 최소 $10 | 후원. 코드 붙여넣기 방식이라 결제 실수가 계속 생긴다(EDGE_CASES 7번). 한국 출금 조건은 찾지 못했다 |
| 토스페이먼츠 | 사업자등록, 통신판매업 신고(면제 기준 있으나 PG가 번호를 요구할 수 있음), PG·카드사 심사 | 가입비 22만 원, 연 11만 원(부가세 별도). 카드 3.4%, 휴대폰 결제 디지털 콘텐츠 7% | 국내 사용자 중심 |
| MoR: Paddle 등 | 판매자 대신 세금·환불·분쟁 처리. 한국 소득세·사업자등록 의무는 남는다는 설명이 있다 | Paddle 5% + $0.50 | 해외 사용자 중심 |
| Stripe 직접 | 한국 법인으로 가입 불가. 미국 등 해외 법인이 있어야 한다 | — | 해외 법인을 둘 때 |

어떤 결제든 웹훅은 지금 장부 Lambda에 `/webhooks/<결제사>`로 붙인다. 결제 id로 멱등 처리, 환불 이벤트로 회수하는 구조는 이미 BMC용으로 있다.

### 5. 개인정보 (작은 서비스도 면제 없음)

- 개인정보 처리방침을 공개해야 한다. 수집 항목(구글 이메일, 결제 이메일 HMAC, 곡·대화 내용), 목적, 보유 기간, 파기 방법을 적는다.
- 사용자 입력을 Anthropic·Google·OpenRouter 등 해외 API로 보내고 AWS·Cloudflare를 쓰므로 국외 이전(처리위탁·보관) 항목을 처리방침에 적는다: 이전받는 자, 국가, 목적, 보유 기간, 거부 방법과 효과.
- 지금 장부가 이메일 평문을 남기지 않는 방식은 그대로 둔다. 서버 DB를 새로 만들어도 같은 원칙을 쓴다.
- 이용약관, 환불 규정(디지털 콘텐츠 청약철회 제한 고지 포함)이 결제 전 필요하다. 세부 조문은 법제처·개인정보위 원문으로 다시 확인한다.

### 6. 가져다 쓸 수 있는 것

- 딱 맞는 오픈소스(Python + 크레딧 + AI 생성 + 결제)는 찾지 못했다. Fastro(무료 FastAPI 백엔드)는 크레딧이 유료판에만 있다. Open SaaS는 크레딧·결제가 있지만 Node(Wasp)다.
- 그래서 틀은 Authlib 공식 `fastapi-google-login` 예제를 따르고, 크레딧은 이미 있는 `credits.py`+Lambda 장부를 쓴다. 이게 가장 적게 만든다.
- 큐가 필요해지면 Postgres만 쓰는 procrastinate나 PgQueuer를 가져온다. ARQ는 유지보수 모드라는 보고가 있어 피한다.

## 추천 이전 순서

각 단계는 앞 단계가 끝난 뒤 시작한다. 날짜는 적지 않는다.

1. **작업 상태를 디스크에 쓰기 (Streamlit 그대로)** — 완료(`JobStore`, `tests/test_job_store.py` 통과). 남은 것: 강제 종료 후 환불 실측.
   바꾼 것: `studio_backend.py`의 `Job`·`Jobs.counts`, `asset_agent.py`의 `Agents`를 SQLite 행으로 저장. 시작 시 `running` 작업을 "중단"으로 닫고 차감 ref를 환불.
   끝난 기준: 생성 중 서버를 강제로 죽이고 다시 띄우면 작업이 "중단됨"으로 보이고 장부에 환불 기록이 있다. 단위 시험 통과.

2. **FastAPI 서버를 옆에 세우기**
   바꾸는 것: 새 `server.py`. `studio_frontend/`를 정적으로 내주고 `app.py`의 `handle()` 분기(submit, cancel, feedback, find, classify, asset 등)를 `/api/action`으로 옮긴다. `setting()`·`secret()`·`ledger()`·`jobs()`는 그대로 가져온다.
   끝난 기준: 로컬에서 비밀번호 모드로 같은 화면이 뜨고 AI 생성·취소·크레딧 조회가 된다.

3. **화면 다리 교체**
   바꾸는 것: `studio_frontend/app.js`의 `toHost`/`onRender`를 `fetch` 모듈로. 진행 상황은 1초 폴링으로 시작(SSE는 나중). 새로고침 후 이어받기 유지.
   끝난 기준: `tests/e2e_studio.py`가 새 서버로 통과. 두 탭에서 같은 계정 작업이 보인다.

4. **구글 로그인 옮기기**
   바꾸는 것: Authlib + 서명 세션 쿠키(비밀키는 key-pool), 로그아웃, 인앱 브라우저 안내, 무료 크레딧 계정 열기. 구글 콘솔에 새 콜백 주소 추가.
   끝난 기준: 로그인·로그아웃·재방문 유지가 되고, 기존 사용자의 크레딧 잔액이 그대로 보인다(같은 이메일 → 같은 HMAC 키).

5. **olmuse.app 전환**
   바꾸는 것: `run_public.ps1`이 uvicorn을 띄우고 터널 대상을 새 포트로. `requirements.txt`에 fastapi·uvicorn. 아케이드·BLACK BOX는 열린 질문 4의 결정대로.
   끝난 기준: olmuse.app에서 Streamlit 프로세스 없이 전 기능이 돈다. 이전 쿠키로 들어온 사용자는 다시 로그인만 하면 된다.

6. **서울 VPS로 이사**
   바꾸는 것: 배포 스크립트 하나(Docker 또는 systemd), 비밀값은 서버 환경 변수, SQLite 매일 S3 백업, Cloudflare 터널 또는 DNS를 VPS로. DP7 감시 대상 주소 갱신.
   끝난 기준: 집 PC를 꺼도 olmuse.app이 동작하고, 배포 한 줄로 새 코드가 올라가며, 백업에서 복원해 본 기록이 있다.

7. **곡·프로젝트 서버 저장**
   바꾸는 것: projects 테이블과 `/api/projects`, 브라우저 저장과 병합. 처리방침에 항목 추가.
   끝난 기준: 다른 기기에서 같은 계정으로 들어가면 곡이 보이고, 오프라인 편집이 덮이지 않는다.

8. **결제 전환**
   바꾸는 것: 정한 결제사의 결제창 + 장부 Lambda에 웹훅·환불 처리. 코드 붙여넣기 대신 로그인 계정에 바로 들어간다. BMC는 후원용으로 남기거나 닫는다.
   끝난 기준: 시험 모드 결제 → 크레딧 증가, 환불 → 크레딧 회수, 둘 다 장부 기록. 같은 웹훅 두 번에도 한 번만 반영.

9. **법·운영 문서**
   바꾸는 것: 개인정보 처리방침(국외 이전 포함), 이용약관, 환불 규정, 화면 바닥 링크.
   끝난 기준: 결제 화면에서 세 문서로 갈 수 있고, 내용이 실제 수집 항목·외부 API 목록과 맞는다.

10. **필요할 때만: 워커 분리**
    조건: 동시 작업이 한 프로세스로 버거울 때. Postgres로 옮기고 procrastinate 등으로 API와 워커를 나눈다.
    끝난 기준: API를 재시작해도 워커의 작업이 이어진다.

## 열린 질문 (사용자가 정할 것)

1. 사업자등록을 할 것인가? 개인 후원(BMC) 그대로인지, 국내 사업자(토스페이먼츠)인지, 해외 판매 위주(MoR)인지가 여기서 갈린다.
2. 주 사용자가 국내인가 해외인가? 결제 수단과 서버 위치(서울 vs 유럽 저가 VPS)가 달라진다.
3. 집 PC 운영을 언제까지 둘 것인가? 유료 결제를 열기 전에 VPS로 옮길지, 사용자 수를 보고 옮길지.
4. 아케이드·BLACK BOX 09 페이지는 어떻게 할 것인가? 새 서버로 다시 만들기 / Streamlit으로 따로 남기기 / 빼기.
5. 선생님 비밀번호 모드(크레딧 없이 운영자 키 사용)를 유료화 뒤에도 유지할 것인가?
6. 곡을 서버에 저장할 것인가? 저장하면 처리방침·보관 기간·삭제 요청 처리가 늘어난다.
7. 월 서버 예산 상한은 얼마인가?

## 사용자 결정 (2026-11-09)

- 사업자등록을 한다. 결제는 국내 사업자 기준(토스페이먼츠 등)으로 간다.
- 한국 위주로, 사용자의 게임 개발자 인맥부터 푼다. 잘되면 해외로 간다.
- 집 PC 운영은 사용자 수를 보고 끝낸다. 지금은 서버에 돈을 쓰지 않고, 수익이 나면 재투자한다. 그 전까지는 지금처럼 이 PC와 Cloudflare 터널로 운영한다. 이전 순서 중 돈이 들지 않는 단계(작업 상태를 디스크에 쓰기, FastAPI로 옮기기)만 먼저 할 수 있다.
- 유료화 뒤 선생님 비밀번호 모드 대신 쿠폰으로 크레딧을 넣는 기능을 만든다. 운영자가 쿠폰을 만들어(예: 1만 크레딧) 직접 쓴다.
- 고민 중: 웹앱과 별도로 사용자 컴퓨터에 설치하는 프로그램. 역공학으로 털릴 수 있으니 영업비밀은 서버에 둔다. 비밀이라 할 만큼 대단하지 않은 것은 프로그램에 넣어도 된다.
- 아직 안 정함: 아케이드·BLACK BOX 09 페이지 처리, 곡의 서버 저장.

## 출처

Streamlit
- [Streamlit 인증 문서 (st.login, 쿠키 30일)](https://docs.streamlit.io/develop/concepts/connections/authentication)
- [Auth cookie persistence broken in 1.57.0](https://discuss.streamlit.io/t/auth-cookie-persistence-broken-in-1-57-0-starlette-migration/121410)
- [st.login custom scopes 미지원](https://discuss.streamlit.io/t/new-access-token-in-st-login-doesnt-allow-custom-scopes/120621)
- [How to really scale a Streamlit App?](https://discuss.streamlit.io/t/how-to-really-scale-a-streamlit-app/44662)
- [400-500 users getting choked](https://discuss.streamlit.io/t/we-have-400-500-users-using-streamlit-at-scale-but-its-getting-choked/120506)
- [ALB session affinity for Streamlit](https://discuss.streamlit.io/t/how-do-we-configure-alb-session-affinity-to-route-requests-in-a-session-to-the-same-instance/42863)
- [Scale a stateful Streamlit chatbot with ECS and EFS](https://dev.to/aws-builders/scale-a-stateful-streamlit-chatbot-with-aws-ecs-and-efs-48gm)
- [FluxLit 문서](https://fluxlit.readthedocs.io)
- [Why I'll never use Streamlit for production again](https://python.plainenglish.io/why-ill-never-use-streamlit-for-production-again-a-cautionary-tale-aed9c992133d)
- [When other tools win (Streamlit 전체 재실행)](https://theneuralbase.com/streamlit-for-ai/learn/advanced/when-other-tools-win/)

로그인·큐·템플릿
- [Authlib: Google login for FastAPI](https://blog.authlib.org/2020/fastapi-google-login)
- [Authlib FastAPI OAuth Client 문서](https://docs.authlib.org/en/v0.15/client/fastapi.html)
- [Python job queues 정리 (ARQ 유지보수 모드, SAQ)](https://lab.abilian.com/Tech/Python/Useful%20Libraries/Job%20queues)
- [procrastinate 문서](https://procrastinate.readthedocs.io/en/main/discussions.html)
- [PgQueuer](https://hn.jakechampion.name/reader/https://github.com/janbjorge/pgqueuer)
- [Postgres as a job queue 주의점 (Microsoft)](https://techcommunity.microsoft.com/blog/adforpostgresql/potential-consequences-of-using-postgres-as-a-job-queue/4514332)
- [Fastro vs FastroAI](https://benavlabs.github.io/FastAPI-boilerplate/fastro-vs-fastroai/)
- [Open SaaS (wasp-lang)](https://docsearch.algolia.com/mcp/docs/repo/wasp-lang/open-saas)

호스팅
- [Railway vs Render vs Fly.io (findstack)](https://findstack.com/resources/railway-vs-render-vs-fly-io)
- [Fly.io vs Railway vs Render 2026 for AI SaaS](https://dev.to/whoffagents/flyio-vs-railway-vs-render-in-2026-where-to-deploy-your-ai-saas-with-real-numbers-3b0f)
- [Render vs Railway vs Fly.io 2026 (techplained)](https://www.techplained.com/render-vs-railway-vs-flyio)
- [Cloud Run WebSockets (요청 시간 제한 최대 60분)](https://docs.cloud.google.com/run/docs/triggering/websockets)
- [Cloud Run 최소 인스턴스와 과금](https://docs.cloud.google.com/run/docs/configuring/min-instance)
- [Lambda 응답 스트리밍](https://docs.aws.amazon.com/en_gb/lambda/latest/dg/configuration-response-streaming.html)
- [API Gateway 30초 제한과 Function URL](https://codestax.medium.com/hit-a-30s-timeout-heres-how-lambda-function-urls-save-the-day-d2e4912c6882)
- [Lightsail 결제 FAQ(한국어)](https://docs.aws.amazon.com/ko_kr/lightsail/latest/userguide/amazon-lightsail-frequently-asked-questions-faq-billing-and-account-management.html)
- [AWS Lightsail pricing 2026](https://onedollarvps.com/pricing/aws-lightsail-pricing)
- [Hetzner 2026 가격 인상](https://findstack.com/resources/hetzner-price-increase-2026)
- [Hetzner Cloud Review 2026 (Better Stack)](https://betterstack.com/community/guides/web-servers/hetzner-cloud-review/)

DB
- [Supabase 무료 한도 2026](https://automationatlas.io/answers/supabase-free-tier-limits-2026/)
- [Supabase pricing 2026 (jetadmin)](https://www.jetadmin.io/blog/supabase-pricing-2026-guide-to-plans-limits-and-real-world-costs/)
- [Neon: free/low-cost managed Postgres FAQ](https://neon.com/faqs/best-free-low-cost-managed-postgres-services)

결제
- [토스페이먼츠 이용요금](https://www.tosspayments.com/about/fee)
- [토스페이먼츠: 통신판매업신고 방법](https://www.tosspayments.com/blog/articles/sales-registration)
- [2026 통신판매업 신고증 발급 방법 (아임웹)](https://imweb.me/blog?idx=491)
- [Stripe: Korea payment methods](https://stripe.com/en-lu/payment-method/korea)
- [한국에서도 Stripe 사용 가능? (2026)](https://inblog.ai/kr/blog/stripe-in-korea)
- [Paddle vs Lemon Squeezy 2026](https://resources.rework.com/tools/billing-revenue/paddle-vs-lemon-squeezy)
- [Lemon Squeezy vs Stripe in Korea: 세금 문제](https://minbook.vercel.app/en/blog/lemonsqueezy-vs-stripe-korea)
- [Buy Me a Coffee pricing 2026](https://schoolmaker.com/blog/buy-me-a-coffee-pricing)

개인정보
- [서비스를 열기 전에 확인할 다섯 가지 질문 (2026)](https://braindetox.kr/posts/web_service_launch_legal_checklist_2026.html)
- [개인정보위 처리방침 작성지침 개정본](https://m.boannews.com/html/detail.html?idx=129433)
- [개인정보위 맞춤형 처리방침 배포 (2026-02)](https://www.newsseoul.co.kr/news/view/1065584417596816)
- [개정 개인정보 처리방침 작성 방법 (로톡)](https://www.lawtalk.co.kr/posts/85853)
