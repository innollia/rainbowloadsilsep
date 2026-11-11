# Gemini 키가 없으면 로그인된 Antigravity CLI로 동작한다(듣기 제외).
$env:STRUDEL_LOCAL_AI = '1'
$env:STRUDEL_LOCAL_LEDGER = '1'  # 원격 장부 설정이 없으면 .studio-data\credits.sqlite 를 쓴다(이 PC 전용)
# The page's port: 8501, or the next free one when 8501 is taken (this PC serves the public site there). Streamlit is
# told the port, because left to itself it moves up one port at a time and would take 8502, which is the public API's.
$page = 8501
while ($page -eq 8502 -or (Get-NetTCPConnection -LocalPort $page -State Listen -ErrorAction SilentlyContinue)) { $page++ }
# The asset room's generation API (asset_api.py) runs for as long as this script does, on a port of its own: 8502 is the
# public API's on this PC, and the ports from 8501 up are the ones Streamlit apps take. Windows is asked for a free port,
# which comes from far above those, and app.py and the API read it from OLMUSE_API_PORT.
$probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$probe.Start(); $port = $probe.LocalEndpoint.Port; $probe.Stop()
$env:OLMUSE_API_PORT = "$port"
# The page is on another port than the API, so the API is told which pages may ask it. Set $env:OLMUSE_GEN_FAKE = '1'
# first to try it without a model key.
$env:OLMUSE_API_ORIGINS = "http://127.0.0.1:$page,http://localhost:$page"
# Its rows, its results and its log (logs\api beside the database) stay apart from the public API's. An API that opens a database fails what is running in it
# and deletes the results it does not know, and this run pays into this PC's own ledger file, not the real one.
$env:OLMUSE_GEN_DB = Join-Path $PSScriptRoot '.studio-data\local\asset-gen.db'
$env:OLMUSE_RENDERS = Join-Path $PSScriptRoot '.studio-data\local\asset-renders'
$api = Start-Process python -PassThru -NoNewWindow -WorkingDirectory $PSScriptRoot -ArgumentList '-m', 'uvicorn', 'asset_api:app', '--host', '127.0.0.1', '--port', "$port", '--workers', '1', '--no-access-log', '--no-proxy-headers'
try {
  python -m streamlit run "$PSScriptRoot\app.py" --server.address 127.0.0.1 --server.port $page --server.headless true
}
finally {
  if ($api) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
  # A public run from this same window must not inherit the local pages, the local files or the local port.
  Remove-Item Env:OLMUSE_API_ORIGINS, Env:OLMUSE_GEN_DB, Env:OLMUSE_RENDERS, Env:OLMUSE_API_PORT -ErrorAction SilentlyContinue
}
