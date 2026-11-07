# Serves the app from this PC through a Cloudflare quick tunnel. The URL changes on every start.
$pool = Join-Path $HOME '.all-tomorrow\key-pool.env'
$line = Get-Content $pool | Where-Object { $_ -match '^(export\s+)?STUDIO_PASSWORD=' } | Select-Object -First 1
if (-not $line) { throw 'STUDIO_PASSWORD is missing from key-pool.env' }
$env:STUDIO_PASSWORD = $line.Split('=', 2)[1].Trim()
$env:STRUDEL_DAILY_CALLS = '200'
Remove-Item Env:STRUDEL_LOCAL_AI -ErrorAction SilentlyContinue
$server = Start-Process python -PassThru -WindowStyle Hidden -WorkingDirectory $PSScriptRoot -ArgumentList '-m', 'streamlit', 'run', 'app.py', '--server.address', '127.0.0.1', '--server.port', '8501', '--server.headless', 'true'
$tunnel = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $tunnel) { $tunnel = "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe" }
try { & $tunnel tunnel --url http://127.0.0.1:8501 }
finally { Stop-Process -Id $server.Id -Force }
