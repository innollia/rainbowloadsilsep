# strudel 딸깍이 크레딧 장부 Lambda 배포/갱신. 재실행 안전. 끝에 url 한 줄만 출력한다.
# 비밀값은 ~/.all-tomorrow 의 파일에서만 읽고 출력하지 않는다. 임시 파일은 %TEMP% 에 만들고 지운다.
param([int]$CreditsPerUsd = 20, [int]$FreeCredits = 20)
$ErrorActionPreference = "Continue"
$here = $PSScriptRoot; $R = "ap-northeast-2"; $N = "strudel-credits"; $AT = "$HOME\.all-tomorrow"
$tmp = Join-Path $env:TEMP "strudel-credits-deploy"; New-Item -ItemType Directory -Force $tmp | Out-Null
function Rand { $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | % { $_.ToString("x2") }) }
function Ensure($f) { if (-not (Test-Path $f)) { Set-Content -NoNewline -Encoding ascii $f (Rand) }; (Get-Content $f -Raw).Trim() }
$token = Ensure "$AT\strudel-credits.token"
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

Compress-Archive -Force "$here\lambda_function.py" "$tmp\fn.zip"
@{ Variables = @{ TABLE = $N; APP_TOKEN = $token; PEPPER = $pepper; BMC_WEBHOOK_SECRET = $sec;
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
Start-Sleep 10   # 설정 갱신 직후 몇 초는 옛 환경 변수로 응답한다(bmc-webhook 2026-10-29 실측)
$url = aws lambda get-function-url-config --function-name $N --region $R --query FunctionUrl --output text
"url: $url"
