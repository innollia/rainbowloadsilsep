# Gemini 키가 없으면 로그인된 Antigravity CLI로 동작한다(듣기 제외).
$env:STRUDEL_LOCAL_AI = '1'
$env:STRUDEL_LOCAL_LEDGER = '1'  # 원격 장부 설정이 없으면 .studio-data\credits.sqlite 를 쓴다(이 PC 전용)
python -m streamlit run "$PSScriptRoot\app.py" --server.address 127.0.0.1 --server.headless true
