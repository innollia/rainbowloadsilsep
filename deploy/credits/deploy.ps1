# strudel 딸깍이 크레딧 장부 Lambda 배포/갱신. 재실행 안전. 끝에 url 한 줄만 출력한다.
# 비밀값은 ~/.all-tomorrow 의 파일에서만 읽고 출력하지 않는다. 임시 파일은 %TEMP% 에 만들고 지운다.
# 운영 안전장치(무료 범위): DynamoDB 시점 복구, Lambda 동시 실행 한도, ALERT 로그 경보, 월 5달러 예산 알림.
# 경보·예산 메일은 -AlertEmail (기본: git config user.email). SNS 메일 구독은 받은 메일의 확인 링크를 눌러야 시작된다.
param([int]$CreditsPerUsd = 20, [int]$FreeCredits = 20, [string]$AlertEmail = "", [int]$ReservedConcurrency = 10, [int]$BudgetUsd = 5)
$ErrorActionPreference = "Continue"
$here = $PSScriptRoot; $R = "ap-northeast-2"; $N = "strudel-credits"; $AT = "$HOME\.all-tomorrow"
$tmp = Join-Path $env:TEMP "strudel-credits-deploy"; New-Item -ItemType Directory -Force $tmp | Out-Null
function Rand { $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | % { $_.ToString("x2") }) }
function Ensure($f) { if (-not (Test-Path $f)) { Set-Content -NoNewline -Encoding ascii $f (Rand) }; (Get-Content $f -Raw).Trim() }
$token = Ensure "$AT\strudel-credits.token"
$adminToken = Ensure "$AT\strudel-credits-admin.token"   # 쿠폰 발행·보류 결제 조회 전용. 웹 서버에는 넣지 않는다(tools/coupon.py만 읽음)
$pepper = Ensure "$AT\strudel-credits.pepper"
function PoolValue($name) {
  if (-not (Test-Path "$AT\key-pool.env")) { return $null }
  $l = Get-Content "$AT\key-pool.env" | ? { $_ -match "^\s*$name\s*=" } | Select-Object -Last 1
  if ($l) { ($l -replace "^\s*$name\s*=\s*", '').Trim().Trim('"', "'") }
}
$sec = PoolValue "STRUDEL_BMC_WEBHOOK_SECRET"; if (-not $sec) { $sec = PoolValue "BMC_WEBHOOK_SECRET" }
if (-not $sec) { throw "key-pool.env 에 STRUDEL_BMC_WEBHOOK_SECRET 또는 BMC_WEBHOOK_SECRET 이 없다" }

aws dynamodb describe-table --table-name $N --region $R --query Table.TableStatus --output text 2>$null | Out-Null
if (-not $?) {
  aws dynamodb create-table --table-name $N --region $R --attribute-definitions AttributeName=pk,AttributeType=S AttributeName=sk,AttributeType=S --key-schema AttributeName=pk,KeyType=HASH AttributeName=sk,KeyType=RANGE --billing-mode PAY_PER_REQUEST --output text | Out-Null
  aws dynamodb wait table-exists --table-name $N --region $R
}
# 시점 복구(PITR): 최근 35일 안의 어느 시점으로든 테이블을 되돌릴 수 있다. 비용은 테이블 크기(GB)에 비례(장부는 KB 단위)
aws dynamodb update-continuous-backups --table-name $N --region $R --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true --output text | Out-Null
$pitr = aws dynamodb describe-continuous-backups --table-name $N --region $R --query ContinuousBackupsDescription.PointInTimeRecoveryDescription.PointInTimeRecoveryStatus --output text
"pitr: $pitr"
$tableArn = aws dynamodb describe-table --table-name $N --region $R --query Table.TableArn --output text

$roleArn = aws iam get-role --role-name "$N-role" --query Role.Arn --output text 2>$null
if (-not $?) {
  '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' | Set-Content -Encoding ascii "$tmp\trust.json"
  $roleArn = aws iam create-role --role-name "$N-role" --assume-role-policy-document "file://$tmp\trust.json" --query Role.Arn --output text
  aws iam attach-role-policy --role-name "$N-role" --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  Start-Sleep 10
}
"{`"Version`":`"2012-10-17`",`"Statement`":[{`"Effect`":`"Allow`",`"Action`":[`"dynamodb:GetItem`",`"dynamodb:PutItem`",`"dynamodb:DeleteItem`",`"dynamodb:Query`",`"dynamodb:ConditionCheckItem`"],`"Resource`":`"$tableArn`"}]}" | Set-Content -Encoding ascii "$tmp\ddb.json"
aws iam put-role-policy --role-name "$N-role" --policy-name ddb --policy-document "file://$tmp\ddb.json"

Compress-Archive -Force -Path "$here\lambda_function.py", "$here\words_en.txt" -DestinationPath "$tmp\fn.zip"
@{ Variables = @{ TABLE = $N; APP_TOKEN = $token; ADMIN_TOKEN = $adminToken; PEPPER = $pepper; BMC_WEBHOOK_SECRET = $sec;
    CREDITS_PER_USD = "$CreditsPerUsd"; FREE_CREDITS = "$FreeCredits" } } | ConvertTo-Json -Compress | Set-Content -Encoding ascii "$tmp\env.json"
try {
  aws lambda get-function --function-name $N --region $R --query Configuration.State --output text 2>$null | Out-Null
  if (-not $?) {
    aws lambda create-function --function-name $N --region $R --runtime python3.12 --handler lambda_function.lambda_handler --role $roleArn --zip-file "fileb://$tmp\fn.zip" --timeout 15 --memory-size 256 --environment "file://$tmp\env.json" --query State --output text | Out-Null
    if (-not $?) { Start-Sleep 10; aws lambda create-function --function-name $N --region $R --runtime python3.12 --handler lambda_function.lambda_handler --role $roleArn --zip-file "fileb://$tmp\fn.zip" --timeout 15 --memory-size 256 --environment "file://$tmp\env.json" --query State --output text | Out-Null }
    aws lambda wait function-active --function-name $N --region $R
  } else {
    aws lambda update-function-code --function-name $N --region $R --zip-file "fileb://$tmp\fn.zip" --query LastUpdateStatus --output text | Out-Null
    aws lambda wait function-updated --function-name $N --region $R
    aws lambda update-function-configuration --function-name $N --region $R --timeout 15 --memory-size 256 --environment "file://$tmp\env.json" --query LastUpdateStatus --output text | Out-Null
    aws lambda wait function-updated --function-name $N --region $R
  }
} finally { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }

aws lambda get-function-url-config --function-name $N --region $R --query FunctionUrl --output text 2>$null | Out-Null
if (-not $?) {
  aws lambda create-function-url-config --function-name $N --region $R --auth-type NONE --output text | Out-Null
  aws lambda add-permission --function-name $N --region $R --statement-id url --action lambda:InvokeFunctionUrl --principal "*" --function-url-auth-type NONE --output text 2>$null | Out-Null
  aws lambda add-permission --function-name $N --region $R --statement-id url-invoke --action lambda:InvokeFunction --principal "*" --invoked-via-function-url --output text 2>$null | Out-Null
}
# 동시 실행 한도: 토큰 없는 요청이 몰려도 이 함수가 동시에 도는 수를 묶는다(0원). 계정 전체 한도가 작으면
# (새 계정은 10) 예약하면 나머지가 10 아래로 내려가 거절되므로 건너뛴다.
$accountLimit = [int](aws lambda get-account-settings --region $R --query AccountLimit.ConcurrentExecutions --output text)
if ($accountLimit -ge ($ReservedConcurrency + 10)) {
  aws lambda put-function-concurrency --function-name $N --region $R --reserved-concurrent-executions $ReservedConcurrency --output text | Out-Null
  "concurrency: $ReservedConcurrency"
} else { "concurrency: skipped (account limit $accountLimit)" }

# ALERT 로그(보류 결제, 쿠폰 발행 등) → 메트릭 → 경보 → SNS 메일. 예산 알림도 같은 메일로. 모두 무료 범위.
if (-not $AlertEmail) { $AlertEmail = (git config user.email 2>$null) }
if ($AlertEmail) {
  $account = aws sts get-caller-identity --query Account --output text
  $topic = aws sns create-topic --name olmuse-alerts --region $R --query TopicArn --output text
  $subs = aws sns list-subscriptions-by-topic --topic-arn $topic --region $R --query "Subscriptions[?Endpoint=='$AlertEmail'].SubscriptionArn" --output text
  if (-not $subs) { aws sns subscribe --topic-arn $topic --protocol email --notification-endpoint $AlertEmail --region $R --output text | Out-Null; "alert email: confirmation sent" }
  $group = "/aws/lambda/$N"
  aws logs create-log-group --log-group-name $group --region $R 2>$null | Out-Null
  aws logs put-retention-policy --log-group-name $group --retention-in-days 90 --region $R | Out-Null
  aws logs put-metric-filter --log-group-name $group --region $R --filter-name alert --filter-pattern ALERT --metric-transformations metricName=CreditsAlert,metricNamespace=olmuse,metricValue=1,defaultValue=0
  aws cloudwatch put-metric-alarm --region $R --alarm-name strudel-credits-alert --namespace olmuse --metric-name CreditsAlert --statistic Sum --period 300 --evaluation-periods 1 --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold --treat-missing-data notBreaching --alarm-actions $topic
  "alarm: strudel-credits-alert"
  aws budgets describe-budget --account-id $account --budget-name olmuse-monthly 2>$null | Out-Null
  if (-not $?) {
    New-Item -ItemType Directory -Force $tmp | Out-Null
    @{ BudgetName = "olmuse-monthly"; BudgetLimit = @{ Amount = "$BudgetUsd"; Unit = "USD" }; TimeUnit = "MONTHLY"; BudgetType = "COST" } | ConvertTo-Json -Compress | Set-Content -Encoding ascii "$tmp\budget.json"
    ConvertTo-Json -Depth 5 -Compress @(
      @{ Notification = @{ NotificationType = "ACTUAL"; ComparisonOperator = "GREATER_THAN"; Threshold = 80; ThresholdType = "PERCENTAGE" }; Subscribers = @(@{ SubscriptionType = "EMAIL"; Address = $AlertEmail }) },
      @{ Notification = @{ NotificationType = "FORECASTED"; ComparisonOperator = "GREATER_THAN"; Threshold = 100; ThresholdType = "PERCENTAGE" }; Subscribers = @(@{ SubscriptionType = "EMAIL"; Address = $AlertEmail }) }
    ) | Set-Content -Encoding ascii "$tmp\notes.json"
    aws budgets create-budget --account-id $account --budget "file://$tmp\budget.json" --notifications-with-subscribers "file://$tmp\notes.json"
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
  }
  "budget: olmuse-monthly $BudgetUsd USD"
} else { "alerts: skipped (no -AlertEmail)" }

Start-Sleep 10   # 설정 갱신 직후 몇 초는 옛 환경 변수로 응답한다(bmc-webhook 2026-10-29 실측)
$url = aws lambda get-function-url-config --function-name $N --region $R --query FunctionUrl --output text
"url: $url"
