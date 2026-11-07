# BLACK BOX 09 — 규칙 추론 실험실

**9칸의 입력을 실험해 숨겨진 변환 법칙을 알아내는 관찰형 퍼즐 게임.**

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB) ![Streamlit](https://img.shields.io/badge/Streamlit-App-FF4B4B)

## 무엇을 할 수 있나

- **3×3 입력·출력 격자**를 직접 조작하는 블랙박스 실험
- 회전/반사/확산/이웃 XOR/생명 게임 등 **16가지 독립적인 법칙**
- 관측 결과와 모순되는 가설을 자동 제거하는 **추론 엔진**
- 현재 남은 후보를 가장 잘 구분하는 입력을 찾는 **최대 정보량 실험 추천**
- 총 4단계, 점수, 포기/정답 공개, 반례 비교, JSON 관측 기록 다운로드
- 서버, 계정, 외부 API, 데이터베이스 및 별도 비밀키 **불필요**

## 로컬 실행

Python 3.11 이상 권장.

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Community Cloud 배포

1. 이 폴더의 **내용물**을 새 GitHub 저장소의 최상위에 올린다 (`app.py`, `engine.py`, `requirements.txt`, `.streamlit/config.toml`).
2. [share.streamlit.io](https://share.streamlit.io/)에서 GitHub 계정으로 로그인하고 **Create app**을 선택한다.
3. Repository와 Branch를 선택하고 **Main file path를 `app.py`**로 지정한 다음 Deploy 한다.
4. 발급된 `*.streamlit.app` 주소에서 게임을 즐길 수 있다.

## 검증

```bash
python -m pip install pytest
python -m pytest -q
```

## 프로젝트 구조

```
blackbox09/
├── app.py                   # UI + 각 세션의 진행 상황
├── engine.py                # 부작용 없는 법칙, 일관성 검사, 정보량 연산
├── requirements.txt         # Streamlit 버전 범위
├── .streamlit/config.toml   # 다크 테마
├── tests/test_engine.py     # 법칙·추론 검증
└── README.md
```

## 운영 메모

- 진행 상황과 실험 기록은 Streamlit의 `st.session_state`에 보관된다. **새로고침/연결 종료 시 사라질 수 있으며 서버 간 공유되지 않는다.**
- 사용자가 제출한 입력은 원격 API에 전송되지 않는다. 기본 Streamlit 서비스의 표준 연결 외에 앱 자체의 별도 데이터 수집은 없다.
- 숨은 법칙은 시드를 이용해 정해져 같은 시드/라운드 조합으로 재현할 수 있다. 왼쪽 패널의 **재현할 세계선 번호**에 입력해 동일한 과제를 다시 시작할 수 있다.
- 외부 Google Fonts가 로드되지 않으면 시스템 글꼴을 사용한다. 게임 동작에는 영향을 주지 않는다.
