# Gemini 키가 없으면 로그인된 Antigravity CLI로 동작한다(듣기 제외).
$env:STRUDEL_LOCAL_AI = '1'
python -m streamlit run "$PSScriptRoot\app.py" --server.address 127.0.0.1
