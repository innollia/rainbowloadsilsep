# 크레딧 장부 (strudel-credits)

Buy Me a Coffee 결제를 olmuse 크레딧으로 바꾸고, 앱이 크레딧을 차감·환불하는 서버다.
AWS Lambda(Function URL, 인증 없음) + DynamoDB 테이블 1개, 리전 `ap-northeast-2`. 함수와 테이블 이름은 둘 다 `strudel-credits`이다.

- 웹훅 URL: `https://6wasuz6jowaayhoedd4h3vmthe0alpoq.lambda-url.ap-northeast-2.on.aws/webhooks/bmc`
- 앱 API: 같은 주소의 `/api/account`, `/api/charge`, `/api/refund`, `/api/history`(POST, `Authorization: Bearer <APP_TOKEN>`). 요청과 응답 형식은 `lambda_function.py` 맨 위에 적어 두었다.

## 구조
- `lambda_function.py`: 표준 라이브러리와 boto3만 쓴다. 테이블 항목 종류는 파일 머리말에 정리했다.
- 이메일은 평문으로 두지 않는다. 계정 키는 `HMAC-SHA256(PEPPER, 이메일)`로 만든다. 결제 기록에는 금액, 통화, 결제 id, 시각만 남긴다.
- 잔액을 바꿀 때는 계정 `ver` 조건과 트랜잭션을 함께 쓴다. 그래서 차감이 동시에 들어와도 잔액이 음수가 되지 않는다. 음수가 될 수 있는 경우는 BMC 환불 이벤트로 크레딧을 회수할 때뿐이다.
- 결제를 계정에 붙이는 순서는 다음과 같다.
  1. 메모, 메시지, 질문 답에 적힌 `SD-XXXXXX` 코드
  2. 구매자 이메일
  3. 둘 다 없으면 주인 없는 결제로 보관한다. 같은 이메일로 `/api/account`를 처음 부를 때 계정에 넣는다.
- USD 결제만 크레딧으로 바꾼다. 다른 통화로 들어온 결제는 기록만 하고 0크레딧으로 처리한다.

## 비밀값 (출력하거나 git에 넣지 않는다)
| 이름 | 위치 |
|---|---|
| APP_TOKEN | `~/.all-tomorrow/strudel-credits.token` (없으면 deploy.ps1이 만든다) |
| PEPPER | `~/.all-tomorrow/strudel-credits.pepper` (없으면 만든다. **바꾸면 기존 계정을 모두 잃는다**) |
| BMC 웹훅 시크릿 | `~/.all-tomorrow/key-pool.env`의 `STRUDEL_BMC_WEBHOOK_SECRET`. 없으면 `BMC_WEBHOOK_SECRET`을 쓴다 |

## 배포
`powershell -ExecutionPolicy Bypass -File deploy/credits/deploy.ps1`
다시 돌려도 안전하다. 실행이 끝나면 `url: ...` 한 줄을 출력한다.

## BMC 웹훅은 블로그 Lambda를 거쳐 온다

BMC 대시보드에 웹훅을 따로 등록하지 않는다(관제 결정, 2026-11-07). 블로그의 `bmc-webhook`(`C:\projects\all-tomorrow\deploy\bmc-webhook`)이 모든 후원을 받고, 서명이 맞으면 메모·메시지·질문 답 어디든 `SD-XXXXXX` 코드가 있는 건만 원문과 서명 그대로 이 Lambda의 `/webhooks/bmc`로 넘긴다. 넘기기가 실패하면 그쪽이 502를 돌려 BMC가 다시 보낸다.

- 그래서 코드 없이 이메일만 맞는 결제는 여기 오지 않는다. 크레딧 구매는 코드가 꼭 있어야 한다. 이 Lambda의 이메일 매칭과 주인 없는 결제 보관은 남아 있지만 지금 경로에서는 쓰이지 않는다.
- 시크릿은 블로그와 같은 `BMC_WEBHOOK_SECRET`이어야 한다. `STRUDEL_BMC_WEBHOOK_SECRET`을 따로 넣지 않는다.
- 블로그 후원자 명단에서 `SD-` 건을 빼는 일은 블로그 쪽 담당이다.
- 2026-11-07 끝까지 시험: 서명한 시험 후원(1 USD, 코드 포함)을 블로그 입구로 보내 이 장부에 +20이 들어오고, 블로그 대기열의 시험 건은 ack로 지웠다.

## 가격 바꾸기
`deploy.ps1 -CreditsPerUsd 25 -FreeCredits 30`처럼 다시 돌린다. 기본값은 둘 다 20이다. 인자 없이 다시 돌리면 20으로 돌아간다.
크레딧은 `floor(금액 USD × CREDITS_PER_USD)`로 계산한다.

## 시험
- 단위 시험: `python -m pytest tests/test_credits_lambda.py -q`. DynamoDB는 메모리 가짜로 바꿔 돌린다.
- 배포 확인(2026-11-07): 시험 계정 `credits-selftest@example.invalid`로 다음을 확인했고 모두 통과했다. 이 시험 계정은 지우지 않고 남겨 두었다(잔액 40, 기록 4건, 시험 결제 1건).
  - 계정 생성
  - 차감, 같은 ref로 두 번 차감해도 한 번만 빠짐, 잔액이 모자라면 402
  - 환불, 같은 ref로 두 번 환불해도 한 번만 돌아옴
  - 서명이 틀린 웹훅은 403
  - 시험 웹훅을 코드로 매칭해 반영하고, 같은 웹훅을 다시 보내도 한 번만 반영
  - history

## 알려진 한계
- 멤버십과 정기 후원은 시작 이벤트(`*.started`)만 크레딧으로 바꾼다. 매달 갱신될 때 들어오는 결제는 반영하지 않는다.
