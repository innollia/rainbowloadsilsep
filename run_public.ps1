# Serves the app from this PC at https://olmuse.app through the named Cloudflare tunnel 'olmuse' (~/.cloudflared/olmuse.yml).
# -ServerOnly restarts just the app, so code changes go live while the tunnel stays.
param([switch]$ServerOnly)
function Stop-Server {
  Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
$pool = Join-Path $HOME '.all-tomorrow\key-pool.env'
$line = Get-Content $pool | Where-Object { $_ -match '^(export\s+)?STUDIO_PASSWORD=' } | Select-Object -First 1
if (-not $line) { throw 'STUDIO_PASSWORD is missing from key-pool.env' }
$env:STUDIO_PASSWORD = $line.Split('=', 2)[1].Trim()
$env:STRUDEL_CREDITS_URL = 'https://6wasuz6jowaayhoedd4h3vmthe0alpoq.lambda-url.ap-northeast-2.on.aws'  # 장부. 토큰은 ~/.all-tomorrow/strudel-credits.token
$env:STRUDEL_DAILY_CALLS = '200'
$env:OLMUSE_SKILL_ROUTER = '1'  # 상황에 맞는 음악 조각만 넣는다 (skill_router.py)
Remove-Item Env:STRUDEL_LOCAL_AI -ErrorAction SilentlyContinue
if (-not $ServerOnly) {
  # The DP7 server watch (all-tomorrow config/infrastructure.json 'olmuse') reruns this script whenever olmuse.app
  # stops answering. Retire any earlier loop and its tunnel first so only one copy keeps running.
  Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -match 'run_public\.ps1' -and $_.CommandLine -notmatch '-ServerOnly'
  } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" | Where-Object { $_.CommandLine -match 'olmuse' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
Stop-Server
Start-Process python -WindowStyle Hidden -WorkingDirectory $PSScriptRoot -ArgumentList '-m', 'streamlit', 'run', 'app.py', '--server.address', '127.0.0.1', '--server.port', '8501', '--server.headless', 'true'
if ($ServerOnly) { return }
$tunnel = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $tunnel) { $tunnel = "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe" }
# cloudflared sometimes crashes; restart it (and the app if it died) instead of leaving olmuse.app down.
$config = Join-Path $HOME '.cloudflared\olmuse.yml'
try {
  while ($true) {
    if (-not (Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue)) {
      Start-Process python -WindowStyle Hidden -WorkingDirectory $PSScriptRoot -ArgumentList '-m', 'streamlit', 'run', 'app.py', '--server.address', '127.0.0.1', '--server.port', '8501', '--server.headless', 'true'
    }
    & $tunnel tunnel --config $config run olmuse 2>&1 | Select-Object -Last 3
    Write-Host "$(Get-Date -Format s) tunnel exited ($LASTEXITCODE), restarting in 5s"
    Start-Sleep 5
  }
}
finally { Stop-Server }
