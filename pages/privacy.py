"""olmuse 개인정보처리방침 (/privacy). 로그인 없이 보인다."""
import streamlit as st

st.set_page_config(page_title="olmuse · 개인정보처리방침", page_icon="◉")
st.title("olmuse 개인정보처리방침")
st.caption("시행일 2026-11-07")
st.markdown("""
olmuse(https://olmuse.app)는 말로 음악과 게임 소리를 만드는 작업실입니다. 필요한 만큼만 받고, 팔거나 광고에 쓰지 않습니다.

### 받는 정보
- **구글 계정 이메일**: 구글 로그인으로 받습니다(openid, email, profile). 크레딧 장부에는 이메일을 그대로 두지 않고, 비밀 값으로 바꾼 해시만 둡니다.
- **크레딧 내역**: 무료 지급, AI 호출 차감·환불, 구매 기록과 계정 충전 코드(SD-로 시작).
- **결제**: Buy Me a Coffee가 처리합니다. olmuse는 카드 정보를 받지 않고, 결제 금액과 메시지 속 충전 코드만 받습니다.
- **만든 곡과 소리**: 작업물은 쓰는 사람의 브라우저에 저장됩니다.

### 쓰는 곳
- 로그인과 크레딧 계산.
- AI 요청: 입력한 문장과 곡 코드는 결과를 만들기 위해 Anthropic(Claude) 또는 Google(Gemini) API로 보냅니다.
- 서비스 운영과 부정 사용 막기.

### 맡기는 곳
- Google: 로그인, Gemini API
- Anthropic: Claude API
- Amazon Web Services(서울 리전): 크레딧 장부
- Cloudflare: 접속 연결
- Buy Me a Coffee: 결제

### 보관과 삭제
크레딧 장부는 계정이 있는 동안 보관합니다. 삭제를 원하면 아래 연락처로 알려 주세요. 확인 후 장부에서 지웁니다. 브라우저에 저장된 작업물은 브라우저 데이터를 지우면 사라집니다.

### 연락
https://buymeacoffee.com/innollia 페이지의 메시지로 연락해 주세요.
""")
