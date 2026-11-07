# 먼저 이 창에서 키를 넣는다: $env:GEMINI_API_KEY = '...'
$env:STRUDEL_LOCAL_AI = '1'
python -m streamlit run "$PSScriptRoot\app.py" --server.address 127.0.0.1
