# Keeps the asset generation API (asset_api.py) up on 127.0.0.1, on port 8502 unless OLMUSE_API_PORT names another.
# run_public.ps1 starts this loop in a hidden window with that variable removed, so the public API is always on 8502,
# and leaves it alone on later runs; `run_public.ps1 -ApiOnly` is what stops it and starts it again.
# -Public changes nothing here. It is the word run_public.ps1 knows its own loop by, so that a loop somebody runs by hand
# on another port, or a window that only has this file's name in its command line, is never taken for it.
# One uvicorn worker, because the job queue lives in that process's memory. --no-proxy-headers, because the API reads the
# visitor's address from CF-Connecting-IP itself and uvicorn must not put an X-Forwarded-For in the peer's place.
# The API writes its own rotating log in .studio-data\logs\api\olmuse.log; the two console files keep the last start.
param([switch]$Public)
$logs = Join-Path $PSScriptRoot '.studio-data\logs\api'; New-Item -ItemType Directory -Force $logs | Out-Null
# The port, read the way asset_token.api_port reads it: the API works out the Hosts it answers to from the same variable.
$port = 8502
$said = "$env:OLMUSE_API_PORT".Trim()
if ($said -match '^[0-9]{1,5}$' -and [int]$said -ge 1 -and [int]$said -le 65535) { $port = [int]$said }
$stranger = 0  # the pid of a program on the port that is not this API, once it was written down
# Seconds before the next start. Longer while starts keep ending at once: see the end of the loop.
$rest = 2
while ($true) {
  # Something already listens on the port: look again in 5 seconds instead of starting a second API beside it.
  $held = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($held) {
    # It may be another program that took the port while the API was down (a Streamlit app moves up to 8502 when 8501
    # is taken). The API cannot start then, and that is written down once instead of waiting without a word.
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($held.OwningProcess)" -ErrorAction SilentlyContinue
    if ($owner -and $held.OwningProcess -ne $stranger -and $owner.CommandLine -notmatch 'asset_api:app') {
      $stranger = $held.OwningProcess
      Add-Content (Join-Path $logs 'console.err.log') "$(Get-Date -Format s) ALERT port $port is held by pid $stranger ($($owner.Name)), which is not the asset API; the API cannot start" -ErrorAction SilentlyContinue
    }
    Start-Sleep 5; continue
  }
  $began = Get-Date
  $api = Start-Process python -PassThru -WindowStyle Hidden -WorkingDirectory $PSScriptRoot -RedirectStandardOutput (Join-Path $logs 'console.out.log') -RedirectStandardError (Join-Path $logs 'console.err.log') -ArgumentList '-m', 'uvicorn', 'asset_api:app', '--host', '127.0.0.1', '--port', "$port", '--workers', '1', '--no-access-log', '--no-proxy-headers'
  $api.WaitForExit()
  # An API that ended within half a minute did not start (its database is held by another process, its token key cannot
  # be read), and every such start writes to the log. The rest doubles up to a minute while that goes on, and is two
  # seconds again after a start that held.
  $quick = ((Get-Date) - $began).TotalSeconds -lt 30
  if (-not $quick) { $rest = 2 }
  Start-Sleep $rest
  if ($quick) { $rest = [Math]::Min(60, $rest * 2) }
}
