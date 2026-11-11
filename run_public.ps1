# Serves the app from this PC at https://olmuse.app through the named Cloudflare tunnel 'olmuse' (~/.cloudflared/olmuse.yml).
# -ServerOnly restarts just the app, so code changes go live while the tunnel stays.
# -ApiOnly restarts just the asset generation API (run_api.ps1, port 8502) and ends. Nothing else ever stops that API:
# a job somebody paid for may be running in it, and the server watch reruns this script whenever the site stops answering.
param([switch]$ServerOnly, [switch]$ApiOnly)
$apiLoop = Join-Path $PSScriptRoot 'run_api.ps1'
function Stop-Server {
  Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
function Get-ApiLoop {
  # The loop is the powershell Start-Api started: this folder's run_api.ps1 as its -File, with -Public after it. A window
  # that only has the file's name in its command line, or a loop somebody runs by hand on another port, is not the loop:
  # it neither keeps a full run from starting the API nor is it stopped by -ApiOnly.
  $mark = '-File\s+"?' + [regex]::Escape($apiLoop) + '"?\s+-Public(\s|$)'
  Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match $mark }
}
function Start-Api {
  # The public API never runs on the scripted model, and it is always on its own port, where the tunnel sends /api/asset.
  Remove-Item Env:OLMUSE_GEN_FAKE, Env:OLMUSE_API_PORT -ErrorAction SilentlyContinue
  Start-Process powershell -WindowStyle Hidden -WorkingDirectory $PSScriptRoot -ArgumentList '-NoProfile', '-File', "`"$apiLoop`"", '-Public'
}
$pool = Join-Path $HOME '.all-tomorrow\key-pool.env'
$line = Get-Content $pool | Where-Object { $_ -match '^(export\s+)?STUDIO_PASSWORD=' } | Select-Object -First 1
if (-not $line) { throw 'STUDIO_PASSWORD is missing from key-pool.env' }
$env:STUDIO_PASSWORD = $line.Split('=', 2)[1].Trim()
$env:STRUDEL_CREDITS_URL = 'https://6wasuz6jowaayhoedd4h3vmthe0alpoq.lambda-url.ap-northeast-2.on.aws'  # 장부. 토큰은 ~/.all-tomorrow/strudel-credits.token
$env:STRUDEL_DAILY_CALLS = '200'
$env:OLMUSE_SKILL_ROUTER = '1'  # 상황에 맞는 음악 조각만 넣는다 (skill_router.py)
Remove-Item Env:STRUDEL_LOCAL_AI -ErrorAction SilentlyContinue
Remove-Item Env:STRUDEL_LOCAL_LEDGER -ErrorAction SilentlyContinue  # the public run never falls back to a local ledger
if ($ApiOnly) {
  # A program that is not the API may hold the port (a Streamlit app moves up to 8502 when 8501 is taken). It is looked
  # for before anything is stopped, and it is never stopped from here: an API is known by its command line alone.
  $strangers = @(Get-NetTCPConnection -LocalPort 8502 -State Listen -ErrorAction SilentlyContinue | Where-Object {
    (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)" -ErrorAction SilentlyContinue).CommandLine -notmatch 'asset_api:app' })
  # The loop goes first, or it would start the API again the moment the API stops.
  Get-ApiLoop | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  # The API that listens, and one that is still starting and does not listen yet.
  Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'asset_api:app' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Api
  if ($strangers) { throw "Port 8502 is held by pid $($strangers[0].OwningProcess), which is not the asset API. It was left running; the API loop is up and takes the port once it is free." }
  return
}
if (-not $ServerOnly) {
  # The DP7 server watch (all-tomorrow config/infrastructure.json 'olmuse') reruns this script whenever olmuse.app
  # stops answering. Retire any earlier loop and its tunnel first so only one copy keeps running.
  Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -match 'run_public\.ps1' -and $_.CommandLine -notmatch '-ServerOnly'
  } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" | Where-Object { $_.CommandLine -match 'olmuse' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  # The asset API is started only when its loop is not there at all. A loop that is there is left as it is.
  if (-not (Get-ApiLoop)) { Start-Api }
}
# Scripts and styles carry a content hash so a browser never pairs a new page with an old cached script.
python (Join-Path $PSScriptRoot 'tools\stamp_assets.py')
# A copy of the SQLite files before each start; the app makes one a day while it runs (server_ops.start_daily_backup).
python (Join-Path $PSScriptRoot 'tools\backup_data.py')
# The app writes its own rotating log in .studio-data\logs\olmuse.log; this file only keeps the console of the last start.
$logs = Join-Path $PSScriptRoot '.studio-data\logs'; New-Item -ItemType Directory -Force $logs | Out-Null
function Start-App {
  Start-Process python -WindowStyle Hidden -WorkingDirectory $PSScriptRoot -RedirectStandardOutput (Join-Path $logs 'console.out.log') -RedirectStandardError (Join-Path $logs 'console.err.log') -ArgumentList '-m', 'streamlit', 'run', 'app.py', '--server.address', '127.0.0.1', '--server.port', '8501', '--server.headless', 'true'
}
Stop-Server
Start-App
if ($ServerOnly) { return }
$tunnel = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $tunnel) { $tunnel = "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe" }
# cloudflared sometimes crashes; restart it (and the app if it died) instead of leaving olmuse.app down.
$config = Join-Path $HOME '.cloudflared\olmuse.yml'
try {
  while ($true) {
    if (-not (Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue)) { Start-App }
    & $tunnel tunnel --config $config run olmuse 2>&1 | Select-Object -Last 3
    Write-Host "$(Get-Date -Format s) tunnel exited ($LASTEXITCODE), restarting in 5s"
    Start-Sleep 5
  }
}
finally { Stop-Server }
