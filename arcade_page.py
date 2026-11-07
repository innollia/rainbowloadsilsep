"""Game shelf and full-window player for locally hosted Godot web exports."""
from __future__ import annotations

from html import escape

import streamlit as st

from catalog import discover_games

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Noto+Sans+KR:wght@400;500;600;700;800&display=swap');
[data-testid="stApp"] { font-family:'Noto Sans KR',sans-serif; }
.main .block-container { max-width:1250px; padding-top:2.4rem; }
.shelf-kicker {font-family:'DM Mono',monospace;color:#B3F36A;letter-spacing:.22em;font-size:.78rem;}
.shelf-title {font-size:clamp(2.3rem,5vw,4.5rem);font-weight:800;letter-spacing:-.07em;line-height:1.12;color:#F4FAF2;margin:.42rem 0 .65rem;}
.shelf-title strong{color:#B3F36A;}
.shelf-description {font-size:1.04rem;line-height:1.8;color:#A2B9B5;}
.shelf-divider{height:1px;background:linear-gradient(90deg,#B3F36A,#27433E 60%,transparent);margin:1.6rem 0 2rem;}
.shelf-art {height:186px;border-radius:14px;background:radial-gradient(circle at 60% 40%,#385A3F 0%,transparent 32%),radial-gradient(circle at 30% 70%,#204F58 0%,transparent 42%),linear-gradient(130deg,#162C31,#0D171B);border:1px solid #263A40;display:flex;align-items:center;justify-content:center;}
.shelf-art span {font:700 4rem 'DM Mono',monospace;letter-spacing:-.18em;color:#B3F36A;text-shadow:0 0 30px #85D78A70;}
.game-type{font:500 .72rem 'DM Mono',monospace;color:#B3F36A;letter-spacing:.1em;margin: .85rem 0 .4rem;}
.game-name {font-weight:750;color:#ECF6F0;font-size:1.18rem;letter-spacing:-.04em;line-height:1.5;min-height:1.7rem;}
.game-summary {font-size:.87rem;color:#96ACAC;line-height:1.6;min-height:3.5rem;}
.player-intro{color:#9DB2B3;line-height:1.8;}
.player-hint{font:400 .77rem 'DM Mono',monospace;color:#7F9A9E;margin:.9rem 0;}
.stButton button {min-height:2.65rem;border-radius:10px;font-weight:650;}
.stButton button[kind="primary"] {background:#B3F36A;border-color:#B3F36A;color:#0C1A14;}
.stButton button[kind="primary"]:hover {background:#DBFFC0;border-color:#DBFFC0;color:#0C1A14;}
</style>
""", unsafe_allow_html=True)

st.session_state.setdefault("arcade_selected", None)
games = discover_games()
lookup = {game.id: game for game in games}


def choose(game_id: str | None) -> None:
    st.session_state.arcade_selected = game_id


active_id = st.session_state.arcade_selected
if active_id and active_id in lookup:
    game = lookup[active_id]
    st.markdown('<div class="shelf-kicker">ARCADE // PLAYER MODE</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="shelf-title">{escape(game.title)}</div>', unsafe_allow_html=True)
    st.markdown(f'<p class="player-intro">{escape(game.description)}</p>', unsafe_allow_html=True)
    left, right = st.columns([1, 2], gap="small")
    with left:
        st.button("← 전체 게임 보기", use_container_width=True, on_click=choose, args=(None,))
    with right:
        st.link_button("게임 전체 화면으로 열기 ↗", game.url, use_container_width=True)
    st.markdown('<div class="shelf-divider"></div>', unsafe_allow_html=True)
    st.iframe(game.url, height=game.height, width="stretch", alt=f"{game.title} 플레이 화면")
    st.markdown('<div class="player-hint">ESC / FOCUS: 브라우저 게임 안을 클릭해 키보드를 활성화할 수 있어.</div>', unsafe_allow_html=True)
    st.caption("로딩이 멈추면 게임을 새 창으로 열어봐. 특히 Godot 멀티스레드 웹 빌드는 별도 보안 헤더가 필요할 수 있어.")
else:
    if active_id is not None:
        st.session_state.arcade_selected = None
    st.markdown('<div class="shelf-kicker">COLLECTION / AUTO-DISCOVERY / 01</div>', unsafe_allow_html=True)
    st.markdown('<div class="shelf-title">YOUR <strong>ARCADE.</strong></div>', unsafe_allow_html=True)
    st.markdown('<div class="shelf-description">폴더를 올리면 게임이 등장해. 클릭하면 플레이 시작. 코드는 그대로, 목록은 자동으로.</div>', unsafe_allow_html=True)
    st.markdown('<div class="shelf-divider"></div>', unsafe_allow_html=True)
    col, count = st.columns([4, 1], vertical_alignment="bottom")
    with col:
        query = st.text_input("게임 검색", placeholder="제목·장르·태그로 찾기", label_visibility="collapsed", key="arcade_search")
    with count:
        st.metric("등록된 게임", len(games))
    normalized = query.strip().casefold()
    visible = [game for game in games if not normalized or normalized in " ".join(
        [game.title, game.description, game.genre, game.id, *game.tags]
    ).casefold()]

    if not games:
        st.info("아직 게임이 없어. 저장소의 `static/games/게임폴더/`에 Godot Web 내보내기 파일을 그대로 넣고 커밋하면 자동 등록돼.")
    elif not visible:
        st.info("검색 결과가 없어.")
    else:
        cols_per_row = 3
        for start in range(0, len(visible), cols_per_row):
            columns = st.columns(cols_per_row, gap="large")
            for col, game in zip(columns, visible[start : start + cols_per_row]):
                with col:
                    with st.container(border=True):
                        if game.cover_url:
                            st.image(game.cover_url, use_container_width=True)
                        else:
                            st.markdown('<div class="shelf-art"><span>◈</span></div>', unsafe_allow_html=True)
                        st.markdown(f'<div class="game-type">{escape(game.genre.upper())}</div>', unsafe_allow_html=True)
                        st.markdown(f'<div class="game-name">{escape(game.title)}</div>', unsafe_allow_html=True)
                        st.markdown(f'<div class="game-summary">{escape(game.description)}</div>', unsafe_allow_html=True)
                        if game.tags:
                            st.caption(" · ".join(f"#{tag}" for tag in game.tags))
                        st.button("▶  플레이", key=f"play_{game.id}", use_container_width=True,
                                  type="primary", on_click=choose, args=(game.id,))
        st.caption("게임 목록은 저장소의 폴더 구조에서 직접 생성돼. 게임을 추가하거나 제거한 뒤 GitHub에 푸시하면 배포본에도 반영돼.")

with st.sidebar:
    st.markdown("### ARCADE INDEX")
    st.caption("이 앱은 `static/games/` 하위의 게임 폴더를 자동 탐색해.")
    st.code("static/games/게임이름/index.html", language=None)
    st.caption("파일명이 꼭 index.html일 필요는 없어. 게임 폴더 안의 HTML 파일도 탐색해.")
    st.caption("원하면 game.json으로 이름·설명·표지·순서를 지정할 수 있어.")
