# 에셋 작업실 보드 동기화 명세

같은 구글 계정으로 여러 컴퓨터에서 에셋 작업실(`studio_frontend/asset_studio/`)의 같은 보드를 열고 함께 고치는 일을 정한다. 생성·토큰·요금은 [ASSET_BACKEND_SPEC](ASSET_BACKEND_SPEC.md)을 그대로 따르고, 이 문서는 그 위에 보드 보관과 동기화를 더한다. 화면 규칙은 [UI_LESSONS](UI_LESSONS.md)를 따른다.

전제:
- 로그인한 계정(토큰 `kind` = `acct`)의 보드는 서버가 보관한다. 계정 없는 사용(비밀번호 세션, 로그아웃, 토큰 없음, 로컬 실행에서 동기화 끔)은 지금처럼 브라우저 IndexedDB만 쓰고, 그 경로의 코드와 시험은 바뀌지 않는다.
- 보드를 통째로 올리거나 덮어쓰는 라우트는 없다. 서버는 레코드 단위 조건부 쓰기(CAS)만 받는다. 병합은 브라우저가 3-way로 한다.
- 남의 작업이 조용히 사라지지 않는다: 서버는 모르는 값 위에 쓰지 않고, 덮인 값은 이력에 남고, 삭제는 표식이고, 같은 필드 충돌에서 진 쪽에는 바로 알린다.
- 서버는 집 PC 한 대(API 프로세스 하나, 작업자 1, SQLite)다. 새 의존성, 웹소켓, SSE는 쓰지 않는다. 알림은 짧은 폴링이다.
- 소리 바이트는 레코드에 넣지 않고 sha256 주소로 따로 둔다. 레코드는 그것이 가리키는 바이트가 서버에 있은 뒤에만 올라간다.
- '빈 보드로 처음부터'와 '샘플 단계부터 다시'는 동기화 중인 보드를 지우지 않는다. 누른 기기만 다른 보드로 옮긴다.
- 다른 계정의 팀원 참가(초대)는 이번에 만들지 않는다. 권한 판정은 처음부터 '보드 구성원인가'로 하여 초대를 더해도 구조가 바뀌지 않는다.
- 새 창, 패널, 줄, 단추를 만들지 않는다. 새 화면 요소는 L절의 목록뿐이다.

## A. 파일, 프로세스, 설정

- **새 파일:** `asset_boards.py`(저장소 `BoardStore`, 레코드 검증, 바이트 파일, 문구 `TEXT`), `studio_frontend/asset_studio/board.js`(순수 함수: 레코드 펴기·합치기·적용), `studio_frontend/asset_studio/sync.js`(동기화 엔진), `tools/board_admin.py`(운영 도구). `asset_boards.py`는 streamlit을 import하지 않고, import할 때 파일을 열거나 스레드를 띄우지 않는다.
- **프로세스:** 기존 `asset_api` 프로세스 안에서 돈다. `real_deps()`가 `BoardStore`를 만들어 `Deps.boards`에 넣고 lifespan이 닫는다. `Deps.boards`가 없으면 보드 라우트는 모두 404 `not_found`다(기존 시험이 그대로 돈다).
- **저장소 규칙:** `GenStore`와 같다. 연결 하나(`check_same_thread=False, isolation_level=None`), WAL, `busy_timeout` 10초, `threading.Lock` 하나, 쓰기는 `begin immediate`. `GenStore`와 다른 파일, 다른 연결, 다른 잠금이다. 잠금이나 트랜잭션을 쥔 채 파일 I/O, 해시 계산, 직렬화를 하지 않는다.
- **터널:** 라우트가 모두 `/api/asset/` 아래라 ingress를 고치지 않는다.

| 이름 | 기본값 |
|---|---|
| `OLMUSE_BOARD_SYNC` | `0`. `1`일 때만 보드 라우트가 일한다. 아니면 모든 보드 라우트가 403 `sync_off` |
| `OLMUSE_BOARD_ACCOUNTS` | 빈 값 = 모든 계정. 쉼표로 나눈 이메일 목록이면 토큰 `email`(소문자·trim)이 목록에 있는 계정만. 나머지는 403 `sync_off`. 목록은 메모리에만 둔다 |
| `OLMUSE_BOARD_DB` | `asset-gen.db`와 같은 폴더의 `asset-boards.sqlite3`. 운영은 `.studio-data/asset-boards.sqlite3`, 로컬·fake 실행(생성 DB의 apart 규칙)은 `.studio-data/local/asset-boards.sqlite3` |
| `OLMUSE_BOARD_BLOBS` | DB 옆 `asset-blobs/` 폴더 |
| `OLMUSE_BOARD_LIMITS` | 아래 상수를 `이름=값,…`으로 덮는다 |

- **파일 이름:** DB `asset-boards.sqlite3`(이름이 `*.sqlite*`라 `server_ops.backup_sqlite`의 하루 백업에 들어간다). 잠금 파일은 `asset-boards.lock`, 시작 횟수 파일은 `asset-boards.boots`다. 이 둘의 이름에 `.sqlite`를 넣지 않는다. 백업 글롭이 잡힌 잠금 파일을 DB로 열면 오류로 멈춰 이름순으로 뒤인 DB의 백업이 빠진다. 두 번째 프로세스는 `StoreTaken`.
- **바이트 파일:** 완성 `asset-blobs/<sha 앞 2자>/<sha>`, 올리는 중 `asset-blobs/part/<board>-<sha>.part`. 렌더 폴더(`asset-renders`) 안에 두지 않는다(`recover()`가 모르는 폴더를 지운다).

**상수(`asset_boards.Limits`)**

| 이름 | 값 |
|---|---|
| `PROTO` | 1 |
| `RECORD_MAX` | 1 200 000 바이트(레코드 `data`의 UTF-8 JSON) |
| `OPS_MAX` | 요청당 연산 400 |
| `CHANGES_MAX` | 응답의 `changes` 약 1 000 000 바이트. 담을 행이 있으면 크기와 상관없이 첫 행은 담는다 |
| `RECORDS_PER_BOARD` | 20 000 |
| `TEXT_PER_BOARD` | 64 MB(그 보드의 `rec.data`와 `rec_hist.data` 길이 합. 넘는 쓰기는 `board_full`. 이력은 레코드마다 `HISTORY_PER_RECORD`와 함께 오래된 것부터 잘라 이 안에 둔다) |
| `HISTORY_PER_RECORD` | 20 (레코드마다 덮인 이전 값을 이만큼 둔다) |
| `CHUNK_MAX` | 1 000 000 바이트(조각 하나) |
| `BLOB_MAX` | 60 MB(바이트 하나) |
| `BOARD_BYTES` | 2 GB |
| `ACCOUNT_BYTES` | 4 GB(계정이 구성원인 보드들의 `bytes` 합 + 그 계정의 part 파일. 넘으면 409 `board_full`) |
| `PARTS_PER_ACCOUNT` | 4(동시에 있는 part 파일. 넘는 새 바이트는 503 `busy`) |
| `ALL_BYTES` | 20 GB(`asset-blobs` 전체, part 포함) |
| `FREE_MIN` | 4 GB. 볼륨 여유가 이보다 적으면 올리기와 레코드를 쓰는 sync를 503 `busy`로 거절(받기만 하는 sync는 받는다. 생성이 쉬는 2 GB보다 먼저 멈춘다) |
| `BOARDS_PER_ACCOUNT` | 20 |
| `PART_AGE` | 86 400초. 이보다 오래된 part 파일은 다음 `blobs` 확인 요청 때와 시작할 때 지운다 |
| `PEER_GONE` | 90초. 이만큼 sync가 없는 기기는 '없음'으로 본다 |
| `RATES` 추가 | `board` 600/60초, `blob` 900/60초(계정 합산, 기존 통과 따로 센다) |

## B. 신원과 권한

- 보드 라우트는 `kind`가 `acct`인 토큰만 받는다. `pw` 토큰은 403 `acct_only`(비밀번호 세션의 owner는 접속 IP 해시라 교실 전체가 한 보드가 된다).
- 계정 = 토큰 `sub`(`acct:<HMAC>`). 이메일은 디스크에 쓰지 않는다(`OLMUSE_BOARD_ACCOUNTS` 비교에만 메모리에서 쓴다).
- 보드 id는 브라우저가 만든 32 hex 난수다. 권한은 `member` 표에 그 계정의 행이 있는가로만 본다. 보드가 없거나 구성원이 아니면 둘 다 404 `no_board`(존재를 흘리지 않는다).
- **모양 검사(DB와 파일 경로에 닿기 전):** 경로와 본문의 `board`는 `^[0-9a-f]{32}$`, `sha`는 `^[0-9a-f]{64}$`, `dev`는 `^[0-9a-f]{16}$`, `since`·`base`·`at`·`size`·`job`의 정수는 0 이상 2^53 미만, `size ≤ BLOB_MAX`. 아니면 400 `bad_request`. part·blob 파일 경로는 이 검사를 지난 값으로만 만든다.
- 계정 키는 `Api.caller`가 돌려준 `who.owner`(= `acct` 토큰의 `sub`)만 쓴다. 본문의 어떤 값도 계정이나 구성원을 정하지 않는다.
- 상태를 바꾸는 라우트는 모두 POST다(PUT·DELETE는 Origin 검사를 타지 않는다).
- 기기 id `dev`: 브라우저가 DB마다 한 번 만든 16 hex. 요청 본문에 싣는다. 서버는 레코드에 마지막으로 쓴 `dev`와 `owner`를 적는다.

## C. HTTP API (접두사 `/api/asset`)

`ROUTES` 튜플에 더한다. 검사 순서(Host → POST의 Origin → Content-Length → 토큰 → 한도 → 본문 → JSON)와 본문 상한 1.6 MB·30초는 그대로다. 보드·바이트 라우트의 일은 공용 스레드가 아니라 자기 `Lane("board", 4, 16)`에서 돈다(줄이 차면 503 `busy`). 한 계정의 폭주나 보드 잠금 대기가 생성 상태 조회·소리 받기를 막지 않는다. 조각 올리기 라우트만 본문을 JSON으로 읽지 않고 날 바이트로 받는다(`RAW_ROUTES = {"board_chunk"}`, `serve`가 그 이름이면 `parse`를 건너뛰고 `raw`를 그대로 넘긴다). 모든 응답은 기존 `NoStore`를 지난다. 요청 본문에 `v`가 있고 `PROTO`와 다르면 409 `upgrade`.

| 경로 | 메서드 | Api 이름 | 통 | 본문 → 응답 |
|---|---|---|---|---|
| `/boards` | GET | `boards` | board | → `{epoch, home, boards:[{id, name, live, changed, made}]}`. 구성원인 보드, `changed` 내림차순. `name`은 `meta/game`의 `game` 값(문자열 또는 `{en,ko}`), `live`는 휴지통 밖 소리 수, 시각은 서버 초 |
| `/boards` | POST | `board_make` | board | `{v, board, first, home}` → `{board, created, epoch}`. 아래 규칙 |
| `/boards/{board}/open` | POST | `board_open` | board | `{v}` → `{home}`. `acct.home`을 이 보드로 |
| `/boards/{board}/sync` | POST | `board_sync` | board | D절 |
| `/boards/{board}/blobs` | POST | `board_blobs` | blob | `{v, shas:[≤200]}` → `{have:[sha], part:{sha: 받은 바이트 수}}` |
| `/boards/{board}/blobs/{sha}` | POST | `board_chunk` | blob | 쿼리 `at`, `size`, 본문 날 바이트(≤`CHUNK_MAX`, `application/octet-stream`) → `{at}`(다음 오프셋) 또는 `{done:true}` |
| `/boards/{board}/blobs/{sha}/job` | POST | `board_job` | blob | `{v, job, stem:n|null}` → `{done:true}`. F절 |
| `/boards/{board}/blobs/{sha}` | GET | `board_blob` | blob | → 파일 전체(`FileResponse`, `ETag: <sha>`, `X-Content-Type-Options: nosniff`). 이 보드에 연결된 sha만 |

**`POST /boards` 규칙(한 트랜잭션)**
- `board`가 이미 있고 구성원이면 `{board, created:false}`(재시도 멱등). 있는데 구성원이 아니면 404.
- `first:true`이고 이 계정이 구성원인 보드가 하나라도 있으면 만들지 않고 `{board: home(없으면 changed가 가장 최근인 보드), created:false}`. 계정의 첫 보드는 서버가 하나만 만든다.
- 아니면 만든다. 만든 계정이 `member(role='owner')`. `home:true`이거나 계정에 home이 없으면 `acct.home`을 이 보드로.
- 계정의 보드가 `BOARDS_PER_ACCOUNT`면 409 `board_full {limit}`.

**오류(모두 `{"error":{code, message, ...}}`, 문장은 `asset_boards.TEXT` en/ko를 `refusal`이 먼저 찾는다)**

| 상태 | code | 뜻 |
|---|---|---|
| 400 | `bad_request` `{field}` | 본문 모양 |
| 400 | `bad_blob` | 다 받은 바이트의 sha256이 주소와 다르다. part 파일을 지운다 |
| 403 | `acct_only` | 계정 토큰이 아니다 |
| 403 | `sync_off` | 스위치가 꺼졌거나 허용 목록 밖 |
| 404 | `no_board` | 보드가 없거나 구성원이 아니다 |
| 404 | `not_found` | 바이트 없음, `Deps.boards` 없음, `job` 복사 불가 |
| 409 | `upgrade` | 규약 버전이 다르다 |
| 409 | `offset` `{at}` | 조각의 `at`이 서버 part 파일 크기와 다르다 |
| 409 | `board_full` `{limit}` | 보드 바이트, 보드 글 바이트, 레코드 수, 계정 바이트, 계정 보드 수 상한 |
| 413 | `too_large` | 본문, 조각, 바이트 하나(`size > BLOB_MAX`) |
| 429 | `rate` `{retry_after}` | 기존 규칙 |
| 503 | `busy` `{retry_after}` | 디스크 여유 부족, `ALL_BYTES`, `PARTS_PER_ACCOUNT`, `board` Lane 줄 |

로그에는 라우트 이름, 보드 id, 개수, 바이트 수만 쓴다. 레코드 내용, 이름, 요청 글은 쓰지 않는다.

## D. 서버 저장소와 sync

### D1. 표

```sql
create table if not exists info    (k text primary key, v text not null);          -- epoch, boots
create table if not exists board   (id text primary key, owner text not null, name text not null default 'null',
                                    made integer not null, changed integer not null,
                                    head integer not null default 0, bytes integer not null default 0);
create table if not exists member  (board text not null, owner text not null, role text not null, joined integer not null,
                                    primary key (board, owner));
create index if not exists member_owner on member (owner);
create table if not exists acct    (owner text primary key, home text);
create table if not exists rec     (board text not null, kind text not null, uid text not null, rev integer not null,
                                    born integer not null, at integer not null, dev text not null, owner text not null,
                                    gone integer not null default 0, live integer not null default 0, data text not null,
                                    primary key (board, kind, uid));
create unique index if not exists rec_rev on rec (board, rev);
create table if not exists rec_hist(board text not null, kind text not null, uid text not null, rev integer not null,
                                    at integer not null, dev text not null, owner text not null, gone integer not null,
                                    data text not null, primary key (board, kind, uid, rev));
create table if not exists blob    (sha text primary key, bytes integer not null, at integer not null);
create table if not exists uses    (board text not null, sha text not null, at integer not null, primary key (board, sha));
```

- `rec.data`는 정규 직렬화(`json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))`, `board.canon`과 같은 바이트)로 둔다. 정규화, 크기 재기(`RECORD_MAX`는 이 UTF-8 바이트 수), sha 뽑기는 잠금 밖에서 하고, 잠금 안에서는 저장된 글과 문자열로만 비교한다. 브라우저의 `fit`은 `RECORD_MAX - 4096`을 목표로 한다(수 표기 차이 여유).
- `rec.rev`는 그 보드의 `head`를 1 올린 값이고 같은 트랜잭션에서 쓴다. `born`은 처음 생긴 rev(목록 순서), `at`은 서버 초, `live`는 kind가 asset이고 gone이 아니고 `data.trashedAt`이 없으면 1.
- 행을 덮거나 gone으로 바꾸기 전에 지금 행을 `rec_hist`에 넣고, 그 레코드의 이력이 `HISTORY_PER_RECORD`를 넘으면 가장 오래된 것을 지운다. 같은 트랜잭션이다.
- 삭제는 `gone=1`이고 `data`는 마지막 값을 그대로 둔다. 삭제 표식은 지우지 않는다.
- **epoch:** 시작할 때 `info.boots`와 `asset-boards.boots` 파일 값을 비교한다. 같으면 둘 다 1 올린다. 다르거나 파일이 없으면(DB가 백업에서 돌아왔다) `info.epoch`를 새 난수로 바꾸고 둘을 맞춘다. 모든 응답에 `epoch`를 싣는다.
- **접속 흔적(메모리만):** `seen[board][dev] = 서버 시각`. sync 때마다 고친다. API가 뜬 뒤 `PEER_GONE`초 동안은 응답의 `up`(뜬 뒤 지난 초)으로 클라이언트가 넘겨받기를 쉰다.

### D2. 레코드 종류

| kind | uid | data |
|---|---|---|
| `meta` | `game` | `{game, brief, platform, loud, demo, stage}` |
| `meta` | `rules` | `{idRule, exportOpts}` |
| `cat` | 분류 id(슬러그) | `{id, name, kind, hue, parent, refs}` |
| `ref` | 레퍼런스 id(`r…`) | 지금 레퍼런스 필드 + 파일이 있으면 `sha256`, `bytes` |
| `dyn` | 동적 소리 id | `{id, name, type, bpm, beats, params(각 항목에서 value 뺌), layers}` |
| `asset` | `a.key` | 아래 |

에셋 data: `{id, name, cat, music, loop, when, description, length, prompt, tempo, sample, layers, imported, file, license, holder, guessed, autoCat, ref, trashedAt|null, status, cur(현재 버전 id|null), work|null, versions:[버전 레코드], drafts:[버전 레코드], chat, refs(from이 'asset'인 것만)}`.
- 버전 레코드는 `assetStore.record(v)`에서 `at`을 수(`+v.at`)로 바꾼 것이다. 모든 문자열은 `gen.js`의 `paired`로 짝 없는 서로게이트를 바꾼 뒤 싣는다.
- `work` = `{request, kind, who, dev, mode, text, n, at, before, jobs:[{id, k}]}`. `jobs[].got`은 기기 값이라 싣지 않는다.
- **기기 값(싣지 않음):** `progress`, `source`, `hasSource`, `current`(인덱스), `pick`, 프로젝트·분류에서 복사된 `refs`, `agentLog`, `dynamics[].params[].value`, `gameDir`, `req:` 본문, localStorage 값, 필터·선택·포커스.
- **허용 목록:** 에셋 data의 필드는 위 목록뿐이다. `snapshot()`의 에셋 항목에 위 목록에도 기기 값 목록에도 없는 필드가 있으면 시험이 실패한다.
- `fit(data)`: 직렬화가 `RECORD_MAX`를 넘으면 `cur`가 아닌 버전의 `prompt`, 그다음 `source`를 오래된 것부터 뺀다. 결정적이다. 받는 쪽은 같은 id의 버전 객체를 이미 갖고 있으면 그것을 둔다.

**서버의 내용 검증(모두 `{bad:code}`로 그 연산만 거절)**
- kind가 표에 없음 `kind`, uid가 64자 `[A-Za-z0-9_.:-]`가 아님 `uid`, data가 객체가 아님 `data`, 크기 초과 `too_large`, UTF-8로 못 쓰는 글자 `text`.
- asset 쓰기에서 지금 행의 `versions` id 중 하나라도 새 data에 없으면 `versions`(버전 목록은 줄지 않는다).
- asset의 gone은 지금 행의 `data.trashedAt`이 있거나 uid가 `s_`로 시작할 때(손대지 않은 샘플)만 받는다. 아니면 `trash_first`.
- 보드의 레코드 수 초과는 `board_full`.

### D3. `POST /boards/{board}/sync`

요청: `{v, dev, since, ops:[op]}`. op = `{kind, uid, base, data}` 또는 `{kind, uid, base, gone:true}`. `base`는 이 기기가 아는 그 레코드의 rev(없으면 0).

응답: `{epoch, now, up, head, next, more, peers:[{dev, age}], results:[result], changes:[{kind, uid, rev, born, at, dev, gone, data}]}`.

한 요청 = 한 트랜잭션(보드 저장소 잠금 안):
1. 보드가 없거나 구성원이 아니면 404 `no_board`.
2. `ops`를 순서대로. 지금 행의 rev를 `cur`(없으면 0)로 읽는다.
   - 내용이 같으면(둘 다 gone이거나, 키를 정렬한 직렬화가 같으면) 쓰지 않고 `{same: cur}`. 응답을 잃은 뒤의 재시도가 여기로 온다. 변경 id 표가 필요 없다.
   - `base != cur`면 쓰지 않고 `{conflict:{rev, dev, gone, data}}`.
   - 서버가 data에서 뽑은 sha(버전·시안의 `sha256`, `stems[].sha256`, ref의 `sha256`) 중 지금 행의 data에 없던 것(이번 쓰기가 새로 가리키는 것)이 이 보드의 `uses`에 없으면 쓰지 않고 `{need:[sha]}`. 이미 행에 있던 sha는 다시 보지 않는다(자가 치유로 `uses`가 지워진 sha 때문에 그 소리의 글 편집이 영영 막히지 않게).
   - 검증 실패는 `{bad:code}`.
   - 아니면 이력에 넣고 `head += 1`, 그 rev로 upsert, `{rev, at}`. `meta/game`이면 `board.name`도, 모든 쓰기에서 `board.changed`도 고친다.
3. `rev > since`인 행을 rev 순으로, 이번 요청이 쓴 행은 빼고, `CHANGES_MAX`까지 `changes`에 담는다. `next`는 담은(또는 건너뛴) 마지막 rev, 더 없으면 `head`. `more`는 남았는지다. 채번과 쓰기가 한 트랜잭션이고 쓰기가 잠금 하나로 줄을 서므로 커서가 아직 안 보이는 행을 지나치지 않는다.
4. `peers`는 `seen[board]`에서 요청한 기기를 뺀 것, `age`는 초.

## E. 브라우저 엔진

### E1. 모듈

- `board.js`(UMD, `window.assetBoard`, Node 시험): `canon(x)`(키 정렬 JSON), `toRecords(snapshot)` → `Map("<kind>/<uid>" → data)`, `fit`, `merge3(kind, base, mine, theirs, mineWins)`, `sane(asset)`, `patch(model, kind, uid, data|null)`(살아 있는 객체를 제자리에서 고친다), `fixIds(model, shadow)`, `pristine(snapshot)`, `shasOf(kind, data)`, `remoteKeys(sync)`, `revertFields(before, after, now)`.
- `sync.js`(UMD, `window.assetSync`): `create(deps)`. deps = `store`, `call`(gen.js가 내주는 같은 401 처리), `snapshot()`, `model()`(패치할 배열과 스칼라 접근자), `quiet()`(다시 그려도 되는가), `redraw(list)`, `lost(info)`, `sha256`, `now`, 타이머.
- script 순서: `data, synth, importer, godot, refs, measure, store, board, gen, sync, quote, app`.

### E2. 브라우저 저장

- 계정 없는 보드 DB: localStorage `asset-sync.anon`이 가리키는 이름, 없으면 지금의 `olmuse-asset-board`.
- 계정 보드 DB: `olmuse-asset-board.<who16>.<보드 id 앞 12자>`. 샘플 보드(아직 서버 보드가 아님): `olmuse-asset-board.<who16>.d<난수 6자>`. 잠금 이름은 DB 이름과 같다. `who16`은 토큰 `sub`의 SHA-256 앞 16 hex(`gen.js`의 who와 같은 값).
- localStorage `asset-sync` = `{v:1, anon, accts:{<who16>:{db}}}`. 지금 열 DB를 가리키는 포인터일 뿐이다. 읽기·쓰기가 안 되거나 비면 부팅이 `indexedDB.databases()`로 `olmuse-asset-board` 로 시작하는 DB의 `sync` 키를 읽어 그 계정의 것 중 `sync.at`이 가장 큰 DB를 연다. `databases()`가 없으면 서버 home을 받는다.
- `board` 저장소의 키 `sync`(계정 DB에만): `{v:1, who, board, made, epoch, cursor, dev, pulled, seed, shadow:{"<kind>/<uid>":{rev, born, dev, json}}, at}`. `made`는 `POST /boards`가 성공했는가, `pulled`는 첫 내려받기를 끝냈는가, `seed`는 'blank'|'sample'|null.
- **`sync` 키는 보드 레코드와 같은 트랜잭션에 쓴다**(`writeBoard`가 `deps.extra()`의 키를 함께 put). 따로 쓰이면 shadow만 앞선 상태가 '내가 되돌렸다'로 읽힌다.
- 보낼 큐는 두지 않는다. 보낼 것은 매번 `toRecords(snapshot())`과 shadow의 차이로 다시 계산한다.

### E3. 한 바퀴(`tick`)

1. 돌 조건: 토큰이 `acct`, 토큰의 who가 `sync.who`와 같음, `store.writable`, 복원이 `failed`가 아님, 보드 레코드가 있음. 아니면 아무것도 보내지 않는다(빈 화면이 '전부 삭제'로 올라가지 않는다).
2. `made`가 거짓이면 `POST /boards`를 먼저 한다(E5의 규칙대로 `first`, `home`). 단 `seed`가 'sample'이고 보드가 `pristine`이면 아무것도 하지 않는다(손대지 않은 샘플은 서버 보드가 되지 않는다).
3. **받은 뒤 보낸다.** 보낼 것이 있어도 먼저 `ops:[]`로 받을 것을 다 받고(`more`가 거짓이 될 때까지) 병합한 뒤 차이를 계산한다.
4. `cur = toRecords(snapshot())`. `toRecords`가 `paired`와 `fit`을 이미 적용한 값을 내므로 shadow(보낸 값)와 같은 모양으로 비교한다(`fit`이 뺀 프롬프트 때문에 같은 레코드가 매 바퀴 dirty가 되지 않는다). dirty = shadow와 `canon`이 다른 것 + shadow에서 살아 있는데 `cur`에 없는 것.
   - 사라진 asset은 gone이 아니라 `trashedAt = now`로 고쳐 다시 넣고 휴지통에 되살린다. asset의 gone은 `sync.purge(keys)`(휴지통의 영구 삭제·비우기, 손대지 않은 샘플 치우기)가 표시한 것만 보낸다.
   - 사라진 cat, ref, dyn은 gone으로 보낸다.
   - 글 입력칸이 잡혀 있으면 직전 바퀴와 값이 같은 레코드만 보낸다.
5. dirty 레코드의 `shasOf` 중 서버에 있다고 모르는 것은 F절대로 먼저 올리고, 덜 올라간 레코드는 이번 바퀴에서 뺀다.
6. 연산 순서: `meta` → 새 `cat`(부모 먼저) → `asset` → `ref`·`dyn` → gone 연산. 한 요청에 `OPS_MAX`와 `RECORD_MAX` 합 1.2 MB까지 담고, 나눌 때 gone 연산은 마지막 요청에 둔다(분류 id 바꾸기의 '새 분류 → 소속 변경 → 옛 분류 삭제'가 이 순서로 보인다).
7. `results`:
   - `{rev}`·`{same}`: shadow를 **보낸 값**과 그 rev로(요청 중에 또 고친 것은 dirty로 남는다).
   - `{conflict}`: `merge3(kind, shadow, 내 값, 서버 값, mineWins = (conflict.dev === sync.dev))` → 결과를 patch하고 shadow를 서버 값·rev로. 다음 바퀴에 새 base로 올라간다.
   - `{need}`: 그 sha를 '서버에 있다'에서 빼고 다음 바퀴에 올린다.
   - `{bad:'trash_first'}`: 그 소리를 휴지통으로 넣어 다시 보낸다.
   - `{bad:'versions'}`: 내 값에 없는 shadow의 버전을 다시 넣어(합집합, G절 순서) 다음 바퀴에 보낸다. 다른 필드의 내 편집은 그대로다(`mend`가 로컬 바이트 없는 버전을 뗀 경우가 여기로 온다).
   - 다른 `bad`(`too_large`, `text`, `uid`, `kind`, `data`, `board_full`): 내 값을 되돌리지 않는다. 그 레코드를 (key, 보낸 값의 canon 해시)로 '막힘'에 두고 값이 바뀔 때까지 다시 보내지 않으며 토스트 `syncFull`(board_full) 또는 `syncLost`. 막힌 레코드가 있으면 보드 목록 상태 글은 '동기화됨'이 아니다.
8. `changes`마다 `merge3(kind, shadow, 내 값, 서버 값, mineWins = (change.dev === sync.dev))` → 결과가 내 값과 다르면 patch, shadow는 서버 값으로. 내 dev가 쓴 되울림은 '남의 변경'으로 세지 않는다(토스트, 다시 그리기 없음).
9. `more`가 거짓이면 수리: `fixIds`(G절), 없는 분류를 가리키는 소리의 `fitCat`, `sane`. 수리 결과는 다음 바퀴에 보통 변경으로 올라간다. `more`가 참인 동안에는 수리하지 않는다.
10. `cursor = next`, `store.saveBoard()`(보드 레코드와 `sync`가 한 트랜잭션).
11. `epoch`가 `sync.epoch`와 다르거나 `head < cursor`면 shadow와 cursor를 버리고 0부터 다시 받는다. 이때만 같은 필드 충돌에서 내 값이 이긴다(복원된 서버보다 기기가 새것이다). 버전은 합집합이라 줄지 않는다.

**순서 규칙(어기면 오류 없이 틀린다)**
- 받은 뒤 보낸다(3).
- shadow와 cursor를 보드 레코드보다 먼저 저장하지 않는다(E2).
- 같은 필드 충돌에서 서버 값의 `dev`가 내 기기면 내 값이 이긴다. 응답을 잃은 내 이전 쓰기가 돌아와 그 뒤의 내 편집을 되돌리지 않게 한다.

**주기:** 최근 30초 안에 내 쪽이나 남의 변경이 있었으면 2초, 없으면 5초, 숨은 탭 15초. 내 변경은 0.8초 모아 보내고 요청 사이는 1초 이상 띄운다. 한 번에 요청 하나. 실패는 2·4·8…30초로 늘리고 429는 `retry_after`만큼 쉰다.

**다시 그리기:** 데이터와 shadow는 받는 즉시 고친다. 그리기는 `#ask`가 아닌 글 입력칸에 포커스가 있거나, 한글 조합 중이거나, 포인터를 누르고 있거나, 타일 메뉴가 열려 있으면 미루고 0.5초마다 다시 본다. 열린 상세의 소리가 바뀌었으면 `renderDetail`, 아니면 `renderBoard`. 에셋·버전·분류·레퍼런스·동적 소리 객체는 바꿔 끼우지 않는다(gen.js의 폴링, 열린 상세, 선택, 재생, 풀어 둔 소리가 이어진다). 열린 대화상자는 다시 그리지 않는다.

### E4. 고치는 지점(app.js, store.js, gen.js)

- `store.js`: `create({name, extra, remote, fetch, pending})`. `name`이 DB와 잠금 이름이다(기본 `olmuse-asset-board`). `extra()`는 보드와 한 트랜잭션에 쓸 키들. `read()`가 같은 트랜잭션에서 `sync`를 읽고 `remote(sync)`(= `board.remoteKeys`: shadow의 버전·시안·레퍼런스가 쓰는 키)를 `mend`의 `present`에 합친다. 서버에 있는 소리는 로컬에 바이트가 없어도 떼지 않는다. `bytes(key)`가 로컬에 없으면 `fetch(key)`로 받아 `saveBlob`한다. `pending`이 참인 동안 쓰기와 입력을 막는다(`guard`에 토스트 `syncJoin`). 계정 DB에서는 `prune`을 하지 않는다. 인자를 주지 않으면 지금과 한 글자도 다르게 움직이지 않는다.
- `gen.js`: `call`을 내준다(날 바이트 본문과 GET 바이트 응답 포함). `work.dev`를 쓴다. `deps.dev`가 있으면(동기화 모드) `mine(w)`는 `w.dev === deps.dev`일 때만 참이고 `dev`가 없는 기록은 남의 것이다. `deps.dev`가 없으면 지금 그대로다. 계정 DB에 묶는 순간(E5) 그 DB의 `dev` 없는 `work`에 자기 `dev`를 적는다(같은 계정의 두 기기가 같은 요청을 둘 다 다시 보내거나 취소하지 않게). `deps.ready()`가 있으면 `attach`·`reattach`·넘겨받기는 그것이 풀린 뒤에만 돈다: 이번 방문의 첫 받기(`more` 거짓까지)가 끝난 뒤다(넘겨받기로 `work.dev`가 바뀐 소리를 옛 기기가 부팅 직후 취소·되돌리지 않게). `deps.claim(group)`이 있으면 POST 전에 기다린다(H절). 넘겨받기(H절).
- `app.js`: 접근자(`model()`)와 연결만 둔다. 병합·펴기 로직은 `board.js`에 둔다. 통째로 갈아 끼우던 지점은 동기화 모드에서 자리 고치기로 바꾼다: 에이전트 되돌리기의 `cats`·`projectRefs` 교체, `openBundle`의 `cats`·`dynamics`·`projectRefs` 교체, `applySnapshot`의 에셋 교체(동기화 중에는 `patch`만 쓴다).
- 모든 에셋이 `key`를 갖는다(`toRecords`가 `keyOf`를 부른다). 모듈 로드 때 만드는 샘플 에셋은 `key = 's_' + 샘플 id`, 그 첫 legacy 버전 id는 `'sv_' + key`로 고정한다.
- 새 동적 소리 id는 `dyn_<난수 6자>`. 레퍼런스 파일을 올릴 때 `sha256`, `bytes`를 레코드에 적는다.

### E5. 부팅, 첫 연결, 계정 전환, 로그아웃

부팅: 호스트가 주는 `signed`와 localStorage의 마지막 who로 DB를 고르고 store를 만든다(없으면 계정 없는 보드). 토큰이 오면 엔진을 붙인다. 토큰의 who가 연 DB의 `sync.who`와 다르면 포인터를 고치고 프레임을 새로고침한다. 새로고침이 10초 안에 3번이면 멈추고 계정 없는 보드로 둔다(sessionStorage 횟수).

'손대지 않은 샘플'(`pristine`) = demo이고, 휴지통·레퍼런스·동적 소리가 없고, 모든 에셋이 sample이며 버전이 legacy뿐이고 work가 없다. 손대지 않은 샘플 보드는 서버에 올리지 않는다.

토큰(`acct`)이 처음 왔을 때, 이 계정의 DB가 없으면 `GET /boards`:

| 이 브라우저에 열린 보드 | 서버(이 계정) | 동작 |
|---|---|---|
| 손대지 않은 샘플 | 보드 없음 | 그대로 로컬. 손대지 않은 동안 30초마다 `GET /boards`를 다시 보고, 보드가 생겼으면 다음 줄처럼 옮긴다(`quiet()`일 때). 샘플이 아니게 되는 순간 그 DB를 계정에 묶고 `POST /boards {first:true}`. 다른 보드가 돌아오면 넷째 줄 |
| 손대지 않은 샘플 | 보드 있음 | home DB를 만들어 포인터를 옮기고 새로고침. `pulled`가 될 때까지 `pending`. 샘플은 올리지 않는다 |
| 실제 작업 | 보드 없음 | 열린 DB를 그 자리에서 계정에 묶고(`sync` 기록) `POST /boards {first:true}`. 그것이 home이 된다. `asset-sync.anon`을 새 이름으로 바꿔 계정 없는 보드는 새로 시작한다 |
| 실제 작업 | 보드 있음(또는 `first`가 다른 보드를 돌려줌) | 합치지 않는다. 열린 DB를 자기 보드 id 그대로 **별도 보드**로 묶어(`sync.made`는 거짓으로 두고 다음 `POST /boards`는 `{first:false, home:false}`) 올리기 전용 엔진(받기·patch 없음, 모두 base 0으로 보내고 바이트를 올림)에 맡기고, 화면은 home DB로 옮긴다(새로고침). 토스트 `localKept`. 올리기 전용 엔진은 그 DB의 `sync.made && 보낼 것 0`이 될 때까지 같은 페이지에서 돈다. 닫혀도 다음 부팅이 `databases()`에서 다 못 올린 계정 DB를 찾아 잇는다 |
| 이 계정 DB의 복원이 `failed` | 보드 있음 | 새 이름의 DB를 같은 보드에 묶고 새로고침해 서버에서 다시 받는다 |

- 첫 내려받기를 아직 못 한 계정 DB(`pulled` 거짓)는 서버에 닿을 때까지 입력을 받지 않는다. 한 번 받은 DB는 서버 없이 열고 고친다.
- 계정마다 DB가 따로라 A의 보드가 B의 서버 보드로 올라가지 않는다.
- 로그아웃·비밀번호 세션: 호스트의 `signed`가 거짓이거나 `pw` 토큰이 왔는데 계정 DB가 열려 있으면 포인터의 who를 비우고 새로고침해 계정 없는 보드를 보인다. 계정 DB는 지우지 않는다.
- 로그인돼 있는데 토큰이 없으면(AI 준비 안 됨) 마지막 계정 DB를 로컬로 쓴다. 변경은 토큰이 올 때 올라간다.
- 403 `sync_off`를 받으면 그 방문은 조용히 로컬로 돈다(토스트 없음).
- 409 `upgrade`면 동기화를 멈추고 로컬로만 저장하며 토스트 `syncOld`.

## F. 소리 바이트

- **주소:** 내용의 sha256. 버전 키 `ver:<id>` → `v.sha256`, 스템 → `stems[].sha256`, `ref:<id>` → `ref.sha256`. 비어 있으면 올리는 기기가 계산해 레코드에 적는다. legacy 버전과 옛 Float32 소스(`k…`)는 올리지 않는다.
- **올리기 순서:** 동시 1개. 현재 버전 마스터 → 시안 마스터 → 다른 마스터 → 스템 → 레퍼런스 파일.
  1. `POST …/blobs {shas}`로 이 보드에 없는 것만 고른다(`part`에 이어 할 오프셋).
  2. 내 생성 작업의 결과면 `POST …/blobs/{sha}/job`으로 서버 안 복사를 먼저 한다. 서버는 그 작업이 같은 계정의 done 작업이고 렌더 폴더의 파일 sha256이 주소와 같을 때만 `asset-blobs`로 복사한다. 아니면 404이고 3으로 간다.
  3. `CHUNK_MAX` 조각을 `at` 순서로. 서버는 part 파일에 붙이고 `at + 길이 == size`가 되면 파일 전체 sha256을 다시 계산해 같을 때만 `os.replace`로 제자리에 옮긴 뒤 `blob`·`uses` 행을 쓴다. 파일이 먼저, 행이 나중이다. 다르면 400 `bad_blob`.
- **중복:** 같은 sha는 파일 하나. 다른 보드에만 있는 sha는 `blobs` 확인에서 '없다'고 답해 바이트를 실제로 보내게 하고, 다 받은 뒤 파일은 다시 쓰지 않고 `uses`만 더한다(sha만 알아서는 남의 소리를 받지 못한다).
- **이어 하기:** part 파일 크기가 진행 상태다. 브라우저는 `part`의 오프셋이나 409 `offset`의 `at`부터 잇는다. 서버는 part 파일 하나(`board`, `sha`)마다 메모리 잠금을 두고 크기 확인·덧붙이기·완성 검사를 그 잠금 안에서 한다(보드 저장소 잠금과는 따로). 잠금이 잡혀 있으면 기다리지 않고 409 `offset`(지금 크기). 같은 보드에 같은 파일을 두 기기가 동시에 올려도 part가 섞이지 않는다.
- **받기:** 늦게 받는다. `store.bytes(key)`가 로컬에 없으면 `GET …/blobs/{sha}`로 받아 sha를 확인하고(다르면 한 번 더) 로컬에 저장한다. 남의 변경을 받은 뒤 그 에셋의 현재 버전과 시안 마스터 중 4 MB 이하는 뒤에서 미리 받는다(동시 2개). 스템과 큰 파일은 들을 때 받는다. 레퍼런스 파일은 연 기기가 들을 때 받는다.
- **자가 치유:** `blob` 행은 있는데 파일이 없으면 GET은 404를 주고 그 sha의 `blob`·`uses` 행을 지운다. 다음 확인에서 없다고 나와 바이트를 가진 기기가 다시 올린다(sync는 그 레코드의 쓰기 상태와 상관없이 로컬에 바이트가 있는 shadow의 sha를 30분마다 `blobs`로 확인한다). 받는 쪽은 404인 버전을 레코드에서 떼지 않고 그 방문 동안 '소리 없음'으로 둔다. 어느 기기에도 바이트가 없으면 그 버전은 소리 없이 남는다(D3의 `need`는 새 sha만 보므로 그 소리의 다른 편집은 계속 올라간다).
- **삭제:** 이번에는 서버에서 바이트를 지우지 않는다. 어떤 브라우저의 `dropUnused`도 서버 삭제로 번지지 않는다. `BOARD_BYTES`에 닿으면 409 `board_full`, 그 레코드는 그 기기에만 남고 토스트 `syncFull`(한 번). 글자 변경은 계속 동기화된다.

## G. 병합 규칙

`merge3` 기본: 한쪽만 바꾼 필드는 그쪽 값. 둘 다 바꿔 값이 다르면 서버 값(먼저 도착한 쪽)이 남고 진 쪽 화면에 바로 보이며 토스트 `syncLost`(소리 이름 포함, 몇 초에 한 번까지). 예외: 서버 값의 `dev`가 내 기기면 내 값.

| 대상 | 단위 | 둘이 동시에 바꿨을 때 |
|---|---|---|
| 게임 이름, 설명, 플랫폼, 음량 범위, stage | `meta/game` 필드별 | 다른 필드는 둘 다. 같은 필드는 먼저 도착 |
| demo | `meta/game` | 한 번 false면 false |
| id 규칙, 내보내기 옵션 | `meta/rules` 필드 둘(각각 통째) | 같은 필드는 먼저 도착 |
| 분류 | `cat/<id>` 필드별, 분류 안 refs는 통째 | 같은 id를 둘이 만들면 한 분류. id 바꾸기는 E3의 연산 순서로 올라가고, 받는 쪽은 `more`가 거짓일 때만 `fitCat`으로 고친다 |
| 프로젝트 레퍼런스 | `ref/<id>` 필드별 | 추가는 둘 다 남는다. 같은 메모는 먼저 도착 |
| 동적 소리 | `dyn/<id>` 필드별, params·layers는 통째 | 슬라이더 위치는 기기 값 |
| 소리의 글자·분류·반복·라이선스 등 | asset 필드별 | 다른 필드는 둘 다 |
| 버전 목록 | `versions` | id 합집합. 줄지 않는다(서버도 거절). 서버 순서 뒤에 내 것만의 버전 |
| 현재 버전, 승인 상태, 작업 기록 | `{status, cur, work}` 한 묶음 | 먼저 도착. 진 쪽에 토스트 |
| 시안 | `drafts` id 집합 3-way | 한쪽이 채택(시안이 모두 버전이 됨)하고 다른 쪽이 버리면 시안은 버전으로 남고 묶음은 먼저 도착 쪽 |
| 시안 고르기 | 기기 값 | 싣지 않는다 |
| 휴지통 넣기·되살리기 | `trashedAt` 필드 | 넣기와 다른 필드 편집은 둘 다 적용 |
| 영구 삭제·비우기 | gone(CAS) | 편집이나 되살리기가 먼저면 삭제가 conflict로 막혀 남는다. 삭제가 먼저면 편집한 쪽에서 사라지고 `syncGone`. 낡은 기기가 되살리지 못한다 |
| 타일 대화 | 덧붙이기 | 공통 앞부분 + 서버 것 + 내 것 |
| 에셋 자기 레퍼런스 | `refs`(from asset) id 집합 3-way | 같은 항목은 먼저 도착 |

- **`sane(asset)`(병합 뒤 항상):** `cur`가 버전에 없으면 가장 새 버전. 시안이 없는데 review면 버전 있으면 draft, 없으면 pending. 시안이 있는데 review·working이 아니면 review. 버전이 있는데 pending이면 draft.
- **`fixIds`(화면 id 겹침):** 휴지통 밖 소리끼리 `a.id`가 같으면 `born`이 작은 쪽(아직 서버에 없는 것은 무한대, 같으면 key 순)이 그 id를 갖고 나머지는 `makeId`로 다시 짓는다. 모든 기기가 같은 결과를 낸다. `more`가 거짓일 때만 돈다.
- **에이전트 되돌리기(동기화 모드):** 클로저가 답 이전 값과 답이 쓴 값을 필드 단위로 쥐고, `revertFields`가 지금도 답이 쓴 값 그대로인 필드만 되돌린다. 그 사이 남이 바꾼 필드, 남이 더한 분류·레퍼런스, `work`가 있는 소리는 그대로다. 남의 변경이 들어와도 토스트를 걷지 않는다. 계정 없는 보드는 지금 클로저 그대로다.
- **휴지통(동기화 모드):** `toTrash`는 시안을 버리지 않고 그 소리의 버전으로 옮긴다. `clearBoard`는 손대지 않은 샘플 소리만 `sync.purge`로 지우고 나머지는 모두 휴지통으로 보낸다. 손대지 않은 샘플 소리 = `s_` key이고 레코드가 모듈 로드 때의 그 샘플 레코드와 `canon`이 같다(버전만 legacy인 것으로는 부족하다: 다른 기기가 이름만 바꾼 샘플이 지워지지 않게). 계정 없는 보드에서는 둘 다 지금 그대로다.
- **cat·ref·dyn의 삭제(gone) 병합:** base가 있고 한쪽이 삭제, 다른 쪽이 편집이면 먼저 도착한 쪽이 이긴다(편집이 먼저면 삭제한 쪽에 되살아나고 `syncLost`, 삭제가 먼저면 편집한 쪽에서 사라지고 `syncGone`). base가 없는 쪽(그 레코드를 처음 만드는 기기)의 값은 서버의 gone을 이긴다(지운 분류 id를 다시 만드는 경우). 같은 결과를 모든 기기가 낸다.
- **묶음 열기(동기화 모드):** 휴지통 밖 소리가 있는 보드에서는 열지 않고 토스트 `bundleNeedsBlank`. 빈 보드에서는 지금처럼 연다(`openBundle`의 교체는 레코드별 연산으로 올라간다).

## H. 만드는 중인 소리

- **선점:** 동기화 모드에서 `gen.ask`는 POST 전에 `deps.claim(group)`을 기다린다. sync가 그 소리들의 레코드(`work`에 `dev`, status working)를 바로 보낸다. conflict이고 서버의 `work`가 다른 기기 것이면 그 소리를 `undo`하고 서버 값을 patch한 뒤 토스트 `genTaken`. 서버에 닿지 않으면 생성하지 않고 `syncOff`. 소리 하나를 만드는 기기는 하나이고 둘이 같이 돈을 내지 않는다.
- **누가 다루나:** `work.dev`가 자기인 기기만 폴링·수령·다시 붙기·취소를 한다. 다른 기기에는 진행률 없는 working으로 보이고 다시 요청할 수 없다.
- **결과:** 만든 기기가 받는다 → 로컬 저장 → F절의 올리기(서버 안 복사 먼저) → 시안·status·`work` 지움이 한 레코드로 올라간다. 다른 기기는 보드 보관소에서 바이트를 받으므로 작업 결과의 만료와 다른 계정의 `forbidden`에 걸리지 않는다.
- **넘겨받기:** 같은 계정의 다른 기기가 60초마다 남의 dev의 작업 id를 한 번에 묶어 상태를 묻는다. 다음이 모두 참이면 `work.dev`를 자기로 바꾸는 CAS 쓰기를 한다: 그 dev가 `peers`에 없거나 `age > PEER_GONE`, 응답의 `up > PEER_GONE`, 작업이 모두 끝남(done·failed·cancelled·gone). 작업 id가 없는 기록은 레코드 `at`(서버 시각) 뒤 10분이 지나야 하고 `request_id`로 물어 넘겨받는다. 이긴 기기만 지금의 다시 붙기 흐름으로 받는다. 진 기기는 아무 작업도 취소하지 않는다.
- **남이 휴지통에 넣으면:** 만든 기기가 그 변경을 받는 순간 자기 작업을 취소한다(환불은 기존 규칙).
- **보드를 옮길 때:** 이 기기의 작업은 취소하지 않는다. 다른 기기가 넘겨받거나, 같은 보드로 돌아오면 dev가 같아 이어진다.

## I. '빈 보드로 처음부터'와 '샘플 단계부터 다시'

기존 단추(게임 정보 창의 `#startBlank`와 restart, 안내 창의 `#tutorialBlank`)와 함수(`startBlank`, `takeBlank`, `openBlank`, `forget`)를 그대로 쓰고 동기화 분기만 더한다.

- **계정 없는 보드:** 지금 그대로다(`confirmBlank`, `forget`, 새로고침).
- **동기화 중인 보드(공통):** `forget()`, `store.clear()`, `gen.cancel([...assets, ...trash])`를 부르지 않는다. `confirmBlank`를 띄우지 않는다(지우는 것이 없다). 보드를 옮기기(이 둘과 목록의 '열기') 전에 보낼 것(막힘 제외)을 내보내며 5초까지 기다린다. 다 보냈으면 옮기고, 남았으면 옮기지 않고 토스트 `syncBusy`(연결 끊김이면 `syncOff`). 보내지 않은 변경을 가진 DB를 두고 떠나는 길이 없다. 손대지 않은 샘플 DB는 기다리지 않는다.
- **빈 보드로 처음부터:** 새 보드 id를 만들고 그 DB에 `sync {board, made:false, seed:'blank'}`를 쓰고 포인터를 옮긴 뒤 새로고침한다. 복원이 empty이고 `sync.seed`가 'blank'이면 `openBlank()`(동기화 모드는 `sessionStorage['asset-blank']`·`takeBlank()`를 쓰지 않는다). 첫 tick이 `POST /boards {home:false}`. home은 바뀌지 않으므로 그 뒤 처음 붙는 기기와 팀원은 원래 보드를 연다. 이미 열려 있는 다른 기기의 화면은 바뀌지 않는다. 안내 창의 `#tutorialBlank`도 같다.
- **샘플 단계부터 다시:** 새 샘플 DB(`…d<난수>`, `seed:'sample'`)로 포인터를 옮기고 새로고침한다. 샘플 보드는 서버에 올리지 않고 home을 바꾸지 않는다. 실제 작업이 생기면 `POST /boards {home:false}`로 새 보드가 된다.
- **home이 바뀌는 길:** 계정의 첫 보드와 목록의 '열기'뿐이다. 열면 `POST /boards/{id}/open`으로 home도 그 보드가 된다. 다른 기기의 화면은 바뀌지 않는다.

## J. 계정 없는 사용, 오프라인, 재시작, 보안, 운영

- **오프라인·서버 중단·터널 끊김:** 편집은 로컬에 쌓이고 돌아오면 CAS와 병합으로 올라간다. 20초 넘게 닿지 않으면 토스트 `syncOff` 한 번.
- **토큰 만료:** `gen.call`의 401 규칙(새 토큰 요청 → 멈춤)을 같이 쓴다. 새 토큰이 오면 엔진을 깨운다.
- **API 재시작:** 동기화 상태는 모두 SQLite에 있다. 응답을 잃은 요청은 다시 보내면 `same`으로 끝난다. 올리던 바이트는 part 파일에서 잇는다(덧붙이다 죽어 조각 중간에서 끝난 part도 그 크기에서 잇고, 끝의 sha 검사가 지킨다). 메모리의 접속 흔적, part 잠금, 분당 계수만 사라진다. 재시작 직후 `up < PEER_GONE` 동안은 넘겨받기가 없다.
- **터널 끊김·요청 폭주:** 브라우저는 실패와 503 `busy`를 2·4·8…30초로 늦추고 한 번에 요청 하나다. 서버는 `board`·`blob` 통 한도와 보드 Lane 줄로 막고, 그 둘은 생성 라우트의 스레드와 한도를 쓰지 않는다.
- **백업 복원:** epoch가 바뀌어 모든 기기가 0부터 다시 맞춘다(E3의 11).
- **같은 브라우저의 둘째 탭:** 지금처럼 읽기 전용이고 갱신되지 않는다. 엔진은 잠금을 쥔 탭에서만 돈다.
- **보안:** 보드 글은 지금처럼 텍스트로만 화면에 넣는다. 다른 계정의 글이 들어오는 초대를 넣기 전에 `app.js`가 보드 글을 `innerHTML`로 넣는 곳을 점검한다.
- **운영 도구 `tools/board_admin.py`:** 계정 이메일(+pepper)로 계정 키를 계산해 보드 목록, 레코드 이력 보기, 레코드 하나를 이력의 rev로 되살리기, gone 되살리기, 보드 지우기(행과 그 보드만 쓰는 바이트 파일), 계정의 보드 전부 지우기. 다른 보드가 쓰는 sha는 남긴다.
- **백업:** DB는 기존 하루 백업에 들어간다. `asset-blobs`는 `tools/backup_data.py`가 `OLMUSE_BACKUP_DIR`(없으면 `.studio-data/backups/asset-blobs`)로 없는 파일만 복사한다(sha 이름이라 증분).
- **개인정보처리방침:** `pages/privacy.py`의 '작업물은 브라우저에 저장'·서버 보관 항목·삭제 방법 문장을 고치기 전에는 `OLMUSE_BOARD_ACCOUNTS`로 허용한 계정에만 켠다.

## K. 시험

키 없이, 가짜 시계와 임시 폴더로 돈다.

- **`tests/test_asset_boards.py`(S1):** CAS(맞는 base만 쓴다), 내용이 같은 재시도는 rev를 올리지 않는다, 이력이 쌓이고 `HISTORY_PER_RECORD`에서 잘린다, 삭제 표식과 데이터 보존, 삭제된 레코드에 대한 낡은 편집은 conflict, 버전이 줄어드는 asset 쓰기 거절, 휴지통 밖 asset의 gone 거절(`s_`는 통과), `born` 순서, `CHANGES_MAX`를 넘는 내려받기의 `more`·`next`로 빠짐없이 받기, 채번과 커밋 사이에 주입한 hook에서 다른 요청의 내려받기가 그 행을 건너뛰지 않음, 구성원 아님과 없는 보드가 같은 404, `POST /boards`의 `first`가 두 번째 보드를 만들지 않음과 멱등, 조각의 순서·`offset`·이어 하기·틀린 sha·다른 보드 sha를 '있다'고 안 함·`need`, 상한들, 두 번째 프로세스 `StoreTaken`, DB만 옛것으로 바꾸면 epoch 변경, 트랜잭션 중간과 파일 옮기기·행 쓰기 사이에서 하위 프로세스를 죽여도 rev에 구멍이 없고 다시 올리면 끝남(`tests/test_hard_kill_refund.py` 방식), `server_ops.backup_sqlite`가 잠금·표식 파일을 잡지 않고 잠금을 쥔 채로도 다른 DB를 백업함, 파일 없는 blob의 자가 치유 뒤 그 소리의 글 편집이 `need` 없이 써짐, 모양이 틀린 board·sha(`../`, 대문자, 길이)가 파일을 만들지 않음, 같은 part에 동시 조각 둘이면 하나는 `offset`, `TEXT_PER_BOARD`·`ACCOUNT_BYTES`·`PARTS_PER_ACCOUNT`, 여유 부족 때 받기 전용 sync는 통과, 정규 직렬화 크기가 `board.canon` 바이트 수와 같음(한글·수).
- **`tests/test_asset_board_api.py`(S2, `Bench`):** 검사 순서 불변, POST의 Origin, `pw` 403 `acct_only`, `sync_off`(스위치, 허용 목록), `board`·`blob` 통이 기존 통과 따로 429, 조각 본문 `CHUNK_MAX` 초과 413과 생성 라우트 상한 유지, 날 바이트 라우트가 JSON을 요구하지 않음, no-store·ETag·nosniff, 오류 모양과 언어, `v` 불일치 409, `Deps.boards` 없으면 404, `real_deps`가 로컬 실행을 `.studio-data/local`로 보냄, `job` 복사는 남의 작업·sha 불일치에 404, 보드 Lane이 찼을 때 503이고 그동안 `/jobs/status`가 답함.
- **`tests/test_asset_board_js.py`(C1, Node):** `toRecords → patch` 왕복이 같은 스냅샷을 만들고 객체 동일성이 유지됨, 허용 목록 밖 필드가 있으면 실패, `fit`의 결정성, `merge3`의 G절 표 줄마다와 `mineWins`, `sane`, `fixIds`가 기기 둘에서 같은 결과, `revertFields`, `pristine`, Date인 `at`, `shasOf`.
- **`tests/test_asset_store_js.py`(C2 추가):** 이름 인자로 DB와 잠금이 갈림, `extra`가 보드와 한 트랜잭션(쓰기 실패 때 둘 다 없음), `remote` 키는 `mend`가 떼지 않음, 없는 키를 `fetch`로 받아 저장, `pending` 동안 쓰기·입력 없음, 계정 DB에서 `prune` 없음. 인자 없는 기존 시험은 고치지 않고 통과.
- **`tests/test_asset_gen_js.py`(C3 추가):** `work.dev`가 다른 기록은 폴링·취소·되돌리기에서 빠짐, `claim` 거절이면 POST 없음, `claim`이 없으면 요청 순서가 지금 그대로, 넘겨받기 조건(접속 중인 만든 기기는 넘겨받지 않음, `up` 유예, 진 기기는 취소 없음).
- **`tests/test_asset_sync_js.py`(C4, Node, 주입한 call·가짜 IndexedDB):** 받은 뒤 보내기, 응답 유실 뒤 같은 필드 재편집(내 새 값이 남음), 저장 전 종료 뒤 재방문, n번째 요청 떨어뜨리기, 바이트가 올라가기 전에는 레코드가 나가지 않음, `need` 뒤 다시 올림, 사라진 asset이 휴지통으로 돌아옴, `purge`만 gone을 보냄, 연산 순서와 나누기에서 gone이 마지막, 수리는 `more` 거짓일 때만, epoch 변경, 첫 내려받기 전 쓰기 없음, 보드 레코드 없이 `sync`만 있으면 아무것도 안 보냄, 글 입력 중 보류, 되울림은 알림 없음, 진 변경 알림, `upgrade`·`sync_off` 처리, 올리기 전용 엔진, 포인터가 지워졌을 때 `databases()`로 다시 찾기, `fit`이 줄인 레코드가 다음 바퀴에 dirty가 아님, `bad:'versions'` 뒤 버전이 돌아오고 다른 필드 편집이 남음, 다른 `bad`는 값을 되돌리지 않고 다시 보내지 않음, 손대지 않은 `seed:'sample'` DB는 POST하지 않음, 보낼 것이 남으면 보드를 옮기지 않음, 첫 받기 전 `gen.attach` 없음, `dev` 없는 `work`는 남의 것. 고장 주입 모의실험(응답 유실, 요청 유실, 마지막 원자 저장에서 다시 시작)을 무작위로 3000회 돌려 두 기기와 서버가 같고 수렴 뒤 보낼 것이 0.
- **`tests/test_asset_sync_two.py` + `tests/js/sync_two.js`(X):** 파이썬이 `OLMUSE_GEN_FAKE=1`·`OLMUSE_BOARD_SYNC=1`인 실제 API를 임시 DB·빈 포트의 uvicorn으로 띄우고(`tests/e2e_asset_import.py` 방식) 토큰을 서명해 Node에 넘긴다. Node가 실제 `store.js`·`board.js`·`gen.js`·`sync.js`를 가짜 IndexedDB 위에 기기 A·B(필요하면 C)로 올리고 전역 `fetch`로 붙는다. `tick`은 스크립트가 손으로 돌린다. 공개 서비스의 포트와 DB는 쓰지 않는다. 장면:
  1. A가 실제 보드를 올리고 B(손대지 않은 샘플)가 합류. 합류가 `head`를 올리지 않음.
  2. 새 기기 둘이 동시에 첫 보드를 만들려 함 → 보드 하나.
  3. 서로 다른 필드 동시 편집 → 둘 다 남음.
  4. 같은 필드 동시 편집 → 먼저 도착이 남고 진 쪽 알림.
  5. 응답 버리기 뒤 같은 필드 재편집.
  6. 둘이 같은 이름의 새 소리 → id가 겹치지 않게 같은 결과.
  7. 분류 id 바꾸기 대 그 분류로 소리 옮기기.
  8. 가져온 소리의 바이트가 먼저 오고 sha가 같음, 3 MB 가져오기가 조각 2에서 끊겼다 이어짐.
  9. 휴지통 대 편집, 영구 삭제 대 되살리기, 검토 중 휴지통에 넣어도 시안이 버전으로 남음.
  10. 채택 대 버리기.
  11. 같은 타일 동시 생성 → POST 하나, 시안 도착, 서버 안 복사, B가 들음.
  12. 만든 기기가 멈춘 뒤 넘겨받기(주입한 시계), 접속 중이면 넘겨받지 않음.
  13. 올리는 중 API 재시작 뒤 이어 하기.
  14. 한쪽이 오프라인으로 50번 고친 뒤 다시 붙기.
  15. 에이전트 되돌리기 사이 팀원의 편집이 남음.
  16. 빈 보드로 처음부터 → B의 보드 그대로, 목록에 둘, 새 기기 C는 원래 보드(home)를 엶. 오프라인 A가 누르면 옮기지 않음.
  17. 샘플 단계부터 다시 → 서버 그대로, home 그대로.
  18. 실제 작업이 있는 기기가 보드가 있는 계정에 들어옴 → home을 열고 로컬 보드는 별도 보드로 다 올라감.
  19. 소리가 있는 보드에서 묶음 열기가 막힘.
  20. DB를 옛 파일로 되돌림(epoch).
  21. `v`가 낡은 클라이언트.
  22. B가 샘플 이름만 바꾼 뒤 A가 폴더를 가져옴(`clearBoard`) → 그 샘플은 지워지지 않고 휴지통.
  23. A가 분류를 지우고 B가 같은 분류 이름을 바꿈(두 순서) → 두 기기 같은 결과.
  24. A의 생성 작업을 B가 넘겨받은 뒤 A가 다시 열림 → A가 취소·되돌리기를 하지 않음.
  - 모든 장면의 끝: 두 기기의 `canon(toRecords)`와 서버 레코드가 같고, 수렴 뒤 보낼 것이 0이고, 서버 `head`가 기대한 수다.
- **실제 브라우저 확인(사람이 한 번, 기본 pytest 밖) `tests/e2e_asset_sync.py`:** fake API와 페이지를 띄우고 같은 계정의 창 둘. 이름을 치는 동안 남의 변경이 와도 입력이 안 끊김, 상세를 연 채 받은 변경이 보임, 이름 바꾸기가 5초 안에 보임, 가져온 소리와 남이 만든 소리가 재생됨, 오프라인 편집이 돌아온 뒤 반영됨, 게임 정보 창의 목록과 '빈 보드로 처음부터'로 옮겼다 돌아옴, 로그아웃하면 계정 없는 보드가 보임.

## L. 새 화면 요소와 바뀌는 뜻

새 요소는 아래뿐이다. 모두 동기화 모드(로그인 계정, 스위치 켜짐)에서만 보인다.

1. **보드 목록.** 어디: 게임 정보 창(`gameDialog`) 안, 설명 아래·기존 단추 위. 제목 '보드' / 'Boards'. 줄마다 '<게임 이름> · 소리 N개 · <마지막 변경 상대 시각>' / '<game> · N sounds · <time>'와 단추 '열기' / 'Open'. 이름이 없으면 '새 게임' / 'New game'. 지금 보드 줄에는 단추 대신 상태 글: '동기화됨' / 'Synced', '보내는 중 · 변경 N · 소리 a/b' / 'Sending · N changes · a/b sounds', '연결 끊김 · 변경은 이 컴퓨터에 있음' / 'Offline · changes are kept on this computer'. 계정의 보드가 하나뿐이면 지금 보드 줄만 보인다. 왜: 보드를 지우지 않고 옮기므로 돌아갈 길이 필요하고, 올라갔는지 볼 곳이 필요하다.
2. **`#toast`의 새 문구(새 요소 아님).**
   - `syncLost`: '다른 컴퓨터에서 먼저 바꿔서 "<이름>"의 변경이 적용되지 않았어요' / 'Changed on another computer first: your change to "<name>" was not applied'
   - `syncGone`: '"<이름>"은 다른 컴퓨터에서 삭제됐어요' / '"<name>" was deleted on another computer'
   - `syncOff`: '서버에 연결되지 않아요. 변경은 이 컴퓨터에 두었다가 연결되면 보내요' / 'Not connected. Changes stay on this computer and are sent when the connection is back'
   - `syncJoin`: '보드를 받는 중이에요' / 'Loading the board'
   - `syncFull`: '보드 저장 공간이 찼어요. 새 소리는 이 컴퓨터에만 있어요' / 'The board is out of space. New sounds stay on this computer only'
   - `syncOld`: '새 버전이 있어요. 새로고침하면 동기화가 이어져요' / 'A new version is out. Reload to keep syncing'
   - `genTaken`: '다른 컴퓨터에서 이미 이 소리를 만들고 있어요' / 'This sound is already being made on another computer'
   - `localKept`: '이 컴퓨터에 있던 보드는 게임 정보의 보드 목록에 올렸어요' / 'The board on this computer was added to the list in Game info'
   - `bundleNeedsBlank`: '묶음은 빈 보드에서 열어요' / 'Open a bundle on an empty board'
   - `boardLimit`: '보드를 더 만들 수 없어요' / 'No more boards can be made'
   - `syncBusy`: '아직 보내는 중이에요. 다 보낸 뒤에 옮길 수 있어요' / 'Still sending. You can switch once it is done'
3. **기존 단추의 뜻 변화(새 요소 아님).** '빈 보드로 처음부터'(게임 정보 창, 안내 창)와 '샘플 단계부터 다시'(게임 정보 창)는 동기화 모드에서 새 보드로 이 기기만 옮기고 확인 창을 띄우지 않는다. 다른 기기와 팀원이 처음 여는 보드(home)는 바뀌지 않는다. 보낼 것이 남아 있으면 옮기지 않는다(I절).

## M. 기한 때문에 뺀 것과 그 대가

- 실시간 연결(SSE, 웹소켓, 롱폴) 대신 짧은 폴링. 대가: 남의 변경이 활동 중 최대 2초, 한가할 때 5초, 숨은 탭 15초 늦게 보인다. 지연을 줄이려면 같은 sync 라우트에 이벤트 루프에서 기다리는 `wait` 인자를 더한다(규약은 그대로).
- 다른 계정 초대. 대가: 동시에 같은 보드에서 일하려면 팀원이 같은 구글 계정으로 들어와야 하고, 계정 단위 한도(에이전트 하루 60회·동시 1건, 생성+취소 분당 10, 하루 시안 200, 환불 시간당 12)와 크레딧을 나눠 쓴다. 더할 것: `invite(code_hash, board, role, expires)` 표, `POST /boards/{board}/invites`(owner만, 128비트 코드), `POST /boards/join {code}`(통 `join` 10/분, 틀린 코드는 모두 같은 404), 게임 정보 창의 '초대 링크 복사', 만든 사람이 돌아오지 않는 working을 서버 시각 70분 뒤 누구나 되돌리는 규칙, 방침 문장.
- 글자 단위 공동 편집. 대가: 같은 소리의 같은 필드를 같은 몇 초 안에 둘이 고치면 한쪽이 진다(알림, 이력에 남음).
- 통째 필드(동적 소리의 params·layers, 분류 refs, id 규칙, 내보내기 옵션)의 안쪽 병합. 대가: 같은 것을 동시에 고치면 한쪽이 통째로 진다.
- 버전을 소리 레코드 안에 둔다. 대가: 이름 한 글자도 소리 레코드 전체(보통 수십 KB)가 다시 올라가고, 1.2 MB를 넘는 소리는 현재가 아닌 오래된 버전의 프롬프트와 패치가 다른 컴퓨터에 가지 않는다.
- 서버 바이트 정리, 보드 지우기·이름 바꾸기 화면. 대가: 버린 시안과 떠난 보드의 바이트가 남고 상한에 닿으면 새 소리가 올라가지 않는다. 운영 도구로만 지운다.
- 두 보드 합치기. 대가: 실제 작업이 있던 컴퓨터의 보드는 별도 보드가 되고, 옮기려면 묶음 내보내기 → 빈 보드에서 열기.
- 기기 값: 에이전트 대화, 시안 고르기 위치, 슬라이더 위치, 옛 Float32 소스, 게임 폴더 연결. 대가: 다른 컴퓨터에서 에이전트 대화가 안 보이고, 옛 방식으로 가져온 소리는 소리가 없으며, 팀원이 승인한 소리가 내 게임 폴더에 자동으로 들어오지 않는다.
- AI 준비가 안 된 계정의 동기화(토큰은 `ai_ready`일 때만 나온다). 대가: 모델 키나 장부 설정이 빠진 동안에는 로그인해도 로컬로만 돈다.
- 새 컴퓨터의 오프라인 첫 방문. 대가: 서버가 꺼져 있으면 그 컴퓨터는 계정 보드를 열지 못한다.
- 누가 무엇을 보고 고치는지 표시, 변경 이력 화면. 대가: 같은 소리를 둘이 잡은 것을 미리 모른다. 실수 복구는 휴지통, 에이전트 되돌리기, 운영 도구뿐이다.
- 끊긴 내려받기 잇기. 대가: 큰 파일을 받다 끊기면 처음부터 다시 받는다.
- 둘째 탭 실시간 갱신. 대가: 지금처럼 연 순간의 화면이다.
- 같은 계정 안의 보호. 대가: 같은 계정을 쓰는 사람(팀원 포함)은 그 계정의 모든 보드를 읽고 고치고 영구 삭제할 수 있다. 되돌리기는 운영 도구의 이력(레코드마다 20개)뿐이다.
- 계정 사이 디스크 공평. 대가: `OLMUSE_BOARD_ACCOUNTS`가 비면 허용된 모든 계정이 `ALL_BYTES`와 `FREE_MIN`을 나눠 쓰고, 계정 몇이 `ACCOUNT_BYTES`씩 채우면 나머지 계정의 새 소리가 503으로 올라가지 않는다(글 동기화는 이어진다). 그래서 운영은 허용 목록으로 켠다.
- `POST /boards`의 존재 숨기기. 대가: 남의 보드 id를 알면 '있다'(404)와 '없다'(만들어짐)를 가를 수 있다. id가 128비트 난수라 추측으로는 닿지 않고, 읽기·쓰기 권한은 주지 않는다.
- 서버에서 파일이 사라진 바이트를 가진 기기가 없을 때의 복구. 대가: 그 버전은 소리 없이 남는다(`asset-blobs` 증분 백업에서 운영 도구로 되돌린다).
- 보내지 않은 변경을 남긴 채 보드 옮기기. 대가: 연결이 끊긴 동안이나 큰 소리를 올리는 동안에는 '빈 보드로 처음부터'·'샘플 단계부터 다시'·'열기'가 `syncBusy`/`syncOff`로 막힌다.
- 열린 대화상자 다시 그리기. 대가: 닫았다 열어야 최신이고, 그 대화상자에서 통째 필드를 고치면 base가 맞지 않아 진 쪽 알림이 뜬다.

기한이 더 모자라면 이 순서로 뗀다(앞의 것부터): 넘겨받기(대가: 만든 기기가 떠나면 결과는 1시간 뒤 환불되고 그 기기가 돌아올 때 되돌려진다) → 4 MB 미리 받기(대가: 처음 듣는 소리마다 받는 시간) → 보드 목록의 상대 시각(대가: '새 게임' 여럿을 소리 개수로만 가른다). 최소로 남는 것: sync 라우트, 조각 올리기와 늦게 받기, 서버 안 복사, `work.dev`와 선점, 보드 목록과 상태 글, 빈 보드·샘플의 동기화 분기.

## N. 작업 패키지

한 파일은 한 패키지에만 든다. 패키지가 더하는 시험은 그 패키지의 시험 파일에 있다. 스크립트 스탬프(`?v=`)는 어느 패키지도 고치지 않는다.

| Id | 상태 | 혼자 만들거나 고치는 파일 | 의존 | 끝난 기준 |
|---|---|---|---|---|
| S1 | 설계 | `asset_boards.py`, `tests/test_asset_boards.py` | 없음 | `python -m pytest -q tests/test_asset_boards.py` 통과 |
| S2 | 설계 | `asset_api.py`(ROUTES, RAW_ROUTES, RATES, 보드 Lane, 모양 검사, `Deps.boards`, `real_deps`의 경로·스위치, `refusal`의 문구 찾기, lifespan 닫기, 메모리 접속 흔적), `tests/test_asset_board_api.py` | S1 | `python -m pytest -q tests/test_asset_board_api.py tests/test_asset_api.py tests/test_tech_review_fixes.py` 통과. fake로 띄운 API에 `GET /api/asset/boards`가 토큰 없이 401 |
| C1 | 설계 | `studio_frontend/asset_studio/board.js`, `tests/test_asset_board_js.py` | 없음 | `python -m pytest -q tests/test_asset_board_js.py` 통과 |
| C2 | 설계 | `studio_frontend/asset_studio/store.js`, `tests/test_asset_store_js.py` | 없음 | 그 시험 통과. 기존 시험을 고치지 않음 |
| C3 | 설계 | `studio_frontend/asset_studio/gen.js`, `tests/test_asset_gen_js.py` | 없음 | `python -m pytest -q tests/test_asset_gen_js.py tests/test_asset_quote_js.py` 통과. 기존 시험을 고치지 않음 |
| C4 | 설계 | `studio_frontend/asset_studio/sync.js`, `tests/test_asset_sync_js.py` | C1, C2·C3의 인터페이스(이 문서 E절) | `python -m pytest -q tests/test_asset_sync_js.py` 통과 |
| H | 설계 | `app.py`(에셋 iframe 인자에 `signed` 한 칸), `studio_frontend/app.js`(호스트: `asset:ai`에 `signed`), `tests/test_asset_token.py` | 없음 | 그 시험 통과. `asset:ai` 전송이 `location.origin`을 쓰는 것을 grep으로 확인 |
| U | 설계 | `studio_frontend/asset_studio/app.js`, `index.html`, `style.css`. 내용: DB 고르기와 E5의 흐름, 엔진 붙이기와 조용할 때 그리기, `model()` 접근자, 통째 교체 지점의 동기화 분기, `toTrash`·`clearBoard`·묶음 열기·에이전트 되돌리기의 동기화 분기, I절의 단추 분기, 샘플 key·dyn id, 보드 목록, 문구 | C1~C4, H, S2 | 기존 JS 시험 전부와 `tests/e2e_asset_import.py` 통과 |
| X | 설계 | `tests/test_asset_sync_two.py`, `tests/js/sync_two.js`, `tests/e2e_asset_sync.py` | U | `python -m pytest -q tests/test_asset_sync_two.py` 통과(K절 장면 전부). 브라우저 확인 한 번 |
| O | 설계 | `tools/board_admin.py`, `tests/test_board_admin.py`, `server_ops.py`, `tools/backup_data.py`(바이트 폴더 증분 복사), `run_api.ps1`(`OLMUSE_BOARD_SYNC`, `OLMUSE_BOARD_ACCOUNTS` 전달), `pages/privacy.py`, `docs/ASSET_BACKEND_SPEC.md`(전제의 '보드는 브라우저에만' 줄을 이 문서로 잇기) | S1 | `python -m pytest -q tests/test_board_admin.py` 통과(보드를 지우면 행과 파일이 없어지고 다른 보드가 쓰는 sha는 남음, 이력 rev로 되살리기). 방침 문구는 사용자 승인 뒤 |

- **순서:** S1·C1·C2·C3·H를 같이 → S2·C4 → U → X. O는 배포 전까지.
- **app.js와 gen.js를 고치는 패키지(C3, U)는 그 파일에 커밋되지 않은 다른 변경이 없을 때 시작한다.** `tests/test_asset_gen_js.py`도 그 뒤 판본에 더한다.

**통합 단계(지휘하는 쪽이 한다)**
- 패키지가 끝날 때마다 `python tools/stamp_assets.py`와 `python -m pytest -q tests/test_stamp_assets.py`. `board.js`와 `sync.js`가 스탬프 대상에 들어가는지 본다.
- 배포: API 코드가 바뀌므로 `run_public.ps1 -ApiOnly`(돌고 있던 유료 작업은 실패·환불되므로 작업이 없을 때). `app.py`가 바뀌므로 Streamlit도 다시 띄운다. 처음에는 `OLMUSE_BOARD_SYNC=1`과 `OLMUSE_BOARD_ACCOUNTS`에 쓸 계정만 넣는다. 열려 있던 탭은 새로고침 전까지 동기화 없이 로컬로 돈다.
- **전체가 끝난 기준:** 두 컴퓨터가 같은 계정으로 같은 보드를 열어 한쪽의 변경이 5초 안에 다른 쪽에 보이고, K절 시나리오의 모든 장면에서 두 기기와 서버의 레코드가 같아지며, 계정 없는 브라우저의 기존 시험이 고치지 않고 통과한다.

**확인되지 않은 것**
- 터널을 지난 2초 폴링의 실제 지연과, 이 터널로 큰 소리를 1 MB 조각으로 올리는 속도.
- `serve`가 작업 스레드에서 돌려준 `FileResponse`가 그대로 흐르는지.
- `data.js`의 `ASSETS`에 D2의 허용 목록에 없는 필드가 있는지(C1의 허용 목록 시험이 잡는다).
- 다시 붙은 Streamlit에서 에셋 iframe이 새로 실리는지.
