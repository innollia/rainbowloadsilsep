"""BLACK BOX 09 — interactive scientific deduction game for Streamlit Cloud.

Run: streamlit run app.py
Only requires the public Streamlit package. No accounts, APIs or databases.
"""
from __future__ import annotations

import json
import secrets
from html import escape

import streamlit as st

from engine import (
    ALL,
    LEVELS,
    RULES,
    apply,
    best_experiment,
    candidates,
    consistent,
    distinguishing_input,
    grade,
    info_gain,
    lit,
    mini,
    secret_for,
)

st.set_page_config(page_title="BLACK BOX 09 · 규칙 추론 실험실", page_icon="◈", layout="wide", initial_sidebar_state="expanded")

STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Noto+Sans+KR:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], [data-testid="stApp"] {font-family:'Noto Sans KR',sans-serif;}
.main .block-container {max-width: 1080px; padding-top: 2.2rem; padding-bottom: 4rem;}
[data-testid="stSidebar"] {border-right:1px solid #23303A;}
[data-testid="stVerticalBlockBorderWrapper"] {border-color:#22343B;}
[data-testid="stMetricValue"] {font-family:'DM Mono',monospace; color:#B3F36A;}
.stButton button {border-radius:10px; min-height:2.65rem; font-weight:650; border-color:#364750;}
.stButton button:hover {border-color:#B3F36A; color:#B3F36A;}
.stButton button[kind="primary"] {background:#B3F36A; color:#0A1512; border-color:#B3F36A;}
.stButton button[kind="primary"]:hover {background:#D3FFA7; color:#0A1512;}
[data-testid="stDownloadButton"] button {background:#152A2A;}
.lab-eyebrow {font-family:'DM Mono',monospace; color:#B3F36A; letter-spacing:.23em; font-size:.76rem; margin-bottom:.7rem;}
.lab-title {font-weight:850; letter-spacing:-.045em; font-size:clamp(2.1rem,5vw,4.25rem); line-height:1.08; margin:.08rem 0 .65rem 0; color:#F4FAF2;}
.lab-title .accent {color:#B3F36A;}
.lab-subtitle {font-size:1rem; color:#A0B2B4; line-height:1.75; margin:0 0 1rem;}
.lab-rule {height:1px; background:linear-gradient(90deg,#B3F36A 0%,#2C4444 65%,transparent); margin:1.45rem 0 1.8rem;}
.lab-section {font-family:'DM Mono',monospace; color:#B3F36A; font-size:.75rem; letter-spacing:.14em; margin:0 0 .7rem;}
.lab-small {color:#8B9FA4; font-size:.85rem; line-height:1.65;}
.tag {display:inline-block; padding:.33rem .65rem; border:1px solid #37504F; border-radius:8px; margin:.14rem .32rem .16rem 0; font-size:.82rem; color:#BED5CE; background:#112321;}
.tag.dead {border-color:#2B3539; color:#687B80; background:#111A1E; text-decoration:line-through;}
.label-line {font-family:'DM Mono',monospace; color:#819A9C; font-size:.72rem; letter-spacing:.17em; margin-bottom:.68rem;}
.lamp-grid {display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; width:min(100%,310px); margin:.6rem auto 1rem;}
.lamp {height:74px; border:1px solid #2D484B; border-radius:11px; display:flex; align-items:center; justify-content:center; background:linear-gradient(145deg,#16242B,#0B151B); position:relative;}
.lamp:after {content:'';width:23px;height:23px;border-radius:50%;background:#293E42; box-shadow:inset 0 2px 4px #091418;}
.lamp.on {background:linear-gradient(145deg,#19342D,#173024);border-color:#659E56;box-shadow:inset 0 0 16px #284B2B;}
.lamp.on:after {background:#B3F36A;box-shadow:0 0 13px #A7F37B8C,0 0 27px #6CBB5366;}
.instrument {border:1px solid #263B40;border-radius:14px;background:#0F1A1F;padding:1.1rem 1.1rem .6rem;}
.blank-screen {display:flex;align-items:center;justify-content:center;min-height:240px;color:#6D8289;text-align:center;font-family:'DM Mono',monospace;line-height:1.8;font-size:.85rem;}
.status-line {border:1px solid #3D5F4B;background:#12251E;padding:.8rem 1rem;border-radius:9px;color:#C6E9CC;font-size:.88rem;line-height:1.7;}
.lab-footer {font-family:'DM Mono',monospace; font-size:.69rem; color:#5E777A; letter-spacing:.07em; margin-top:3rem;}
</style>
"""
st.markdown(STYLES, unsafe_allow_html=True)


def make_run(level: int, seed: int) -> dict:
    return {
        "secret": secret_for(level, seed),
        "input": (1 << 0) | (1 << 3) | (1 << 4),
        "observations": [],
        "hints": 0,
        "mistakes": 0,
        "solved": False,
        "surrendered": False,
        "last_wrong": None,
        "feedback": "",
    }


def boot() -> None:
    if "bb_seed" not in st.session_state:
        st.session_state.bb_seed = secrets.randbelow(1_000_000)
        st.session_state.bb_runs = {}
        st.session_state.bb_unlocked = 0
        st.session_state.bb_level = 0
        st.session_state.bb_flash = ""
        st.session_state.bb_seed_input = st.session_state.bb_seed
    for i in range(st.session_state.bb_unlocked + 1):
        if i not in st.session_state.bb_runs:
            st.session_state.bb_runs[i] = make_run(i, st.session_state.bb_seed)


def reset_session() -> None:
    for key in tuple(st.session_state.keys()):
        if str(key).startswith("bb_") or str(key).startswith("guess_"):
            del st.session_state[key]
    boot()


def restart_with_seed() -> None:
    seed = int(st.session_state.bb_seed_input)
    st.session_state.bb_seed = seed
    st.session_state.bb_runs = {0: make_run(0, seed)}
    st.session_state.bb_unlocked = 0
    st.session_state.bb_level = 0
    st.session_state.bb_flash = "이 시드에서 실험실을 다시 열었어."


def set_input(level: int, mask: int) -> None:
    st.session_state.bb_runs[level]["input"] = mask


def toggle(level: int, index: int) -> None:
    run = st.session_state.bb_runs[level]
    if not run["solved"]:
        run["input"] ^= 1 << index


def do_experiment(level: int) -> None:
    run = st.session_state.bb_runs[level]
    if run["solved"]:
        return
    x = run["input"]
    if any(o["input"] == x for o in run["observations"]):
        st.session_state.bb_flash = "이미 이 입력을 관측했어. 실험 횟수에는 포함하지 않았어."
        return
    before = consistent(candidates(level), run["observations"])
    y = apply(run["secret"], x)
    run["observations"].append({"input": x, "output": y, "gain": round(info_gain(before, x), 3)})
    after = consistent(candidates(level), run["observations"])
    cut = len(before) - len(after)
    st.session_state.bb_flash = f"관측 성공 · {cut}개 가설 배제 · 잔여 {len(after)}개"


def ask_hint(level: int) -> None:
    run = st.session_state.bb_runs[level]
    remain = consistent(candidates(level), run["observations"])
    rec = best_experiment(remain, [o["input"] for o in run["observations"]])
    if rec:
        mask, bits = rec
        run["input"] = mask
        run["hints"] += 1
        st.session_state.bb_flash = f"정보이론이 고른 실험을 입력판에 올렸어. 기대 정보량 {bits:.2f} bit · 힌트 비용 16점"
    else:
        st.session_state.bb_flash = "남은 가설을 구분할 추가 입력이 없어."


def guess(level: int) -> None:
    run = st.session_state.bb_runs[level]
    if run["solved"]:
        return
    if not run["observations"]:
        st.session_state.bb_flash = "먼저 적어도 한 번은 실험해야 해. 무작정 추측은 실험이 아니니까."
        return
    choice = st.session_state.get(f"guess_{level}")
    if choice == run["secret"]:
        run["solved"] = True
        run["feedback"] = "confirmed"
        if level < len(LEVELS) - 1:
            st.session_state.bb_unlocked = max(st.session_state.bb_unlocked, level + 1)
            if level + 1 not in st.session_state.bb_runs:
                st.session_state.bb_runs[level + 1] = make_run(level + 1, st.session_state.bb_seed)
        st.session_state.bb_flash = f"법칙 확인 완료 · {grade(len(run['observations']), run['hints'], run['mistakes'])}점 확보"
    else:
        run["mistakes"] += 1
        run["last_wrong"] = choice
        run["feedback"] = "rejected"
        st.session_state.bb_flash = "최종 판정이 틀렸어. 관측과 아직 모순되지 않는 가설일 수도 있으니, 반례를 찾아봐."


def surrender(level: int) -> None:
    run = st.session_state.bb_runs[level]
    if run["solved"]:
        return
    run["solved"] = True
    run["surrendered"] = True
    run["feedback"] = "surrendered"
    if level < len(LEVELS) - 1:
        st.session_state.bb_unlocked = max(st.session_state.bb_unlocked, level + 1)
        if level + 1 not in st.session_state.bb_runs:
            st.session_state.bb_runs[level + 1] = make_run(level + 1, st.session_state.bb_seed)
    st.session_state.bb_flash = "정답을 공개했어. 이 단계의 점수는 0점이야."


def jump_next(level: int) -> None:
    st.session_state.bb_level = min(level + 1, st.session_state.bb_unlocked)
    st.session_state.bb_flash = ""


def lamp_html(mask: int) -> str:
    spans = "".join(
        f'<div class="lamp {"on" if lit(mask, r, c) else ""}" '
        f'aria-label="{r + 1}행 {c + 1}열 {"켜짐" if lit(mask, r, c) else "꺼짐"}"></div>'
        for r in range(3) for c in range(3)
    )
    return f'<div class="lamp-grid" role="img" aria-label="3행 3열 출력 격자">{spans}</div>'


def export_json(level: int, run: dict) -> str:
    # Do not disclose the secret in exports before it has been solved or surrendered.
    payload = {
        "game": "BLACK BOX 09",
        "protocol": level + 1,
        "seed": st.session_state.bb_seed,
        "candidate_names": [RULES[k].name for k in candidates(level)],
        "observations": [
            {"input": o["input"], "output": o["output"],
             "input_view": mini(o["input"]), "output_view": mini(o["output"]),
             "information_gain_bits": o["gain"]}
            for o in run["observations"]
        ],
        "solved": run["solved"],
        "score": 0 if run["surrendered"] else grade(len(run["observations"]), run["hints"], run["mistakes"]) if run["solved"] else None,
        "rule": run["secret"] if run["solved"] else None,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


boot()

# ───────────────────── Sidebar ─────────────────────
with st.sidebar:
    st.markdown('<div class="lab-eyebrow">RESEARCH DIVISION / 09</div>', unsafe_allow_html=True)
    st.markdown("### 관측실 운영판")
    st.caption("같은 시드에서는 같은 숨은 법칙이 배정돼.")
    st.number_input("재현할 세계선 번호", min_value=0, max_value=999999, step=1, key="bb_seed_input")
    st.button("이 번호로 다시 시작", on_click=restart_with_seed, use_container_width=True)
    unlocked = st.session_state.bb_unlocked
    choice_levels = list(range(unlocked + 1))
    st.radio(
        "프로토콜",
        choice_levels,
        key="bb_level",
        format_func=lambda x: LEVELS[x]["title"] + (" ✓" if st.session_state.bb_runs[x]["solved"] else ""),
    )
    st.divider()
    completed = [r for r in st.session_state.bb_runs.values() if r["solved"]]
    total = sum(0 if r["surrendered"] else grade(len(r["observations"]), r["hints"], r["mistakes"]) for r in completed)
    st.metric("완료한 프로토콜", f"{len(completed)} / {len(LEVELS)}")
    st.metric("누적 점수", f"{total:,}")
    st.button("새 세계선 시작", on_click=reset_session, use_container_width=True)
    st.caption("점수와 기록은 현재 브라우저 연결에만 유지돼. 새로고침하면 초기화될 수 있어.")

level = st.session_state.bb_level
run = st.session_state.bb_runs[level]
observations = run["observations"]
remain = consistent(candidates(level), observations)

st.markdown('<div class="lab-eyebrow">ANOMALY DETECTION // INTERACTIVE RESEARCH GAME</div>', unsafe_allow_html=True)
st.markdown('<div class="lab-title">BLACK BOX <span class="accent">09</span></div>', unsafe_allow_html=True)
st.markdown('<div class="lab-subtitle">아홉 개의 전구. 하나의 숨은 법칙. 더 적은 실험으로 세계가 어떻게 작동하는지 밝혀내.</div>', unsafe_allow_html=True)
st.markdown('<div class="lab-rule"></div>', unsafe_allow_html=True)

hdr_l, hdr_r = st.columns([3, 1])
with hdr_l:
    st.markdown(f"### {LEVELS[level]['title']}")
    st.write(LEVELS[level]["subtitle"])
with hdr_r:
    st.metric("생존 가설", f"{len(remain)} / {len(candidates(level))}")
st.caption(LEVELS[level]["brief"])

if st.session_state.bb_flash:
    st.markdown(f'<div class="status-line">{escape(st.session_state.bb_flash)}</div>', unsafe_allow_html=True)

st.write("")

if run["solved"]:
    title = RULES[run["secret"]].name
    explanation = RULES[run["secret"]].explanation
    if run["surrendered"]:
        st.warning(f"정답 공개: **{title}** · {explanation}")
    else:
        st.success(f"법칙 확정: **{title}** · {explanation}")
        cols = st.columns(3)
        cols[0].metric("획득 점수", grade(len(observations), run["hints"], run["mistakes"]))
        cols[1].metric("실험 횟수", len(observations))
        cols[2].metric("오답 / 힌트", f"{run['mistakes']} / {run['hints']}")
    with st.expander("검증용 반례 보기", expanded=False):
        other = next((k for k in candidates(level) if k != run["secret"]), None)
        if other:
            distinct = distinguishing_input(run["secret"], other)
            if distinct is not None:
                st.write(f"**{RULES[other].name}** 가설과 진짜 법칙은 이 입력에서 갈라져.")
                col1, col2, col3 = st.columns(3)
                col1.caption("입력")
                col1.markdown(lamp_html(distinct), unsafe_allow_html=True)
                col2.caption(f"진짜 · {title}")
                col2.markdown(lamp_html(apply(run["secret"], distinct)), unsafe_allow_html=True)
                col3.caption(f"거짓 · {RULES[other].name}")
                col3.markdown(lamp_html(apply(other, distinct)), unsafe_allow_html=True)
    if level + 1 <= st.session_state.bb_unlocked and level + 1 < len(LEVELS):
        st.button("다음 프로토콜 진입 →", type="primary", on_click=jump_next, args=(level,))
    elif level == len(LEVELS) - 1 and len(completed) == len(LEVELS):
        st.balloons()
        st.markdown("### 관측실 폐쇄 승인")
        st.write("관리국은 마지막으로 이런 문서를 남겼어. *'규칙을 이해한 사람에게 규칙 설명서를 주는 것은 예산 낭비다.'*")

lab_tab, notes_tab, guide_tab = st.tabs(["◈  실험실", "▤  관측 기록", "◇  가설 목록"])

with lab_tab:
    col_left, col_right = st.columns([1, 1], gap="large")
    with col_left:
        st.markdown('<div class="lab-section">01 // INPUT TERMINAL</div>', unsafe_allow_html=True)
        st.write("**실험할 입력** · 칸을 눌러 전구를 켜거나 꺼")
        for r in range(3):
            ccols = st.columns(3, gap="small")
            for c in range(3):
                idx = r * 3 + c
                active = lit(run["input"], r, c)
                with ccols[c]:
                    st.button(
                        "●" if active else "·",
                        key=f"bit_{level}_{idx}",
                        use_container_width=True,
                        disabled=run["solved"],
                        on_click=toggle,
                        args=(level, idx),
                        help=f"{r + 1}행 {c + 1}열 · {'켜짐' if active else '꺼짐'}",
                    )
        st.caption("입력 예시를 눌러 빠르게 전구 배치를 바꿀 수도 있어.")
        pcols = st.columns(4, gap="small")
        presets = [("한 점", 1 << 0), ("대각", 0b100010001), ("삼각", 0b000011001), ("모두", ALL)]
        for col, (label, mask) in zip(pcols, presets):
            with col:
                st.button(label, key=f"preset_{level}_{label}", disabled=run["solved"], use_container_width=True, on_click=set_input, args=(level, mask))
        st.write("")
        st.button("입력 투입 → 결과 관측", type="primary", key=f"fire_{level}", use_container_width=True,
                  disabled=run["solved"], on_click=do_experiment, args=(level,))
        st.button("최적 실험 추천 (−16점)", key=f"hint_{level}", use_container_width=True,
                  disabled=run["solved"] or len(remain) <= 1, on_click=ask_hint, args=(level,))
    with col_right:
        st.markdown('<div class="lab-section">02 // OUTPUT MONITOR</div>', unsafe_allow_html=True)
        st.write("**마지막 관측 결과**")
        if observations:
            last = observations[-1]
            st.markdown('<div class="instrument">' + lamp_html(last["output"]) + '</div>', unsafe_allow_html=True)
            st.caption(f"관측 #{len(observations):02d} · 입력 {mini(last['input'])}")
            st.caption(f"정보량 {last['gain']:.2f} bit")
        else:
            st.markdown('<div class="instrument"><div class="blank-screen">NO SIGNAL<br>입력 투입을 기다리는 중</div></div>', unsafe_allow_html=True)
        st.write("")
        st.markdown('<div class="lab-section">03 // DIAGNOSTICS</div>', unsafe_allow_html=True)
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("실험", len(observations))
        col_b.metric("힌트", run["hints"])
        col_c.metric("추정 점수", 0 if run["surrendered"] else grade(len(observations), run["hints"], run["mistakes"]))
        st.progress((len(candidates(level)) - len(remain)) / (len(candidates(level)) - 1), text="가설 배제율")

    st.divider()
    st.markdown('<div class="lab-section">04 // HYPOTHESIS ELIMINATION</div>', unsafe_allow_html=True)
    st.write("**남아 있는 법칙**")
    chips = "".join(f'<span class="tag {"" if key in remain else "dead"}">{escape(RULES[key].name)}</span>' for key in candidates(level))
    st.markdown(chips, unsafe_allow_html=True)
    st.caption("관측과 모순되는 가설은 취소선으로 표시돼. 정답을 추측하기 전에는 여러 입력을 시험해봐.")

    with st.container(border=True):
        st.markdown("#### 최종 판정")
        st.selectbox("기계가 따르는 법칙을 골라", options=list(candidates(level)),
                     format_func=lambda key: RULES[key].name, key=f"guess_{level}",
                     disabled=run["solved"])
        st.button("이 법칙으로 확정", key=f"submit_{level}", type="primary", use_container_width=True,
                  disabled=run["solved"], on_click=guess, args=(level,))
        if not run["solved"]:
            with st.expander("정답 공개 · 해당 라운드 포기"):
                st.write("정답을 공개하고 다음 단계로 진행할 수 있어. 이 단계의 점수는 0점이야.")
                st.button("정답을 공개할래", on_click=surrender, args=(level,), key=f"giveup_{level}")

with notes_tab:
    st.markdown("#### 실험 노트")
    if observations:
        logs = []
        for idx, ob in enumerate(observations, start=1):
            remaining_after = consistent(candidates(level), observations[:idx])
            logs.append({
                "#": idx,
                "입력": mini(ob["input"]),
                "출력": mini(ob["output"]),
                "정보량(bit)": ob["gain"],
                "잔여 가설": len(remaining_after),
            })
        st.dataframe(logs, hide_index=True, use_container_width=True)
        st.write("관측된 정보만으로 설명 가능한 가설은 아래처럼 좁혀져.")
        st.markdown(" · ".join(f"**{RULES[k].name}**" for k in remain))
    else:
        st.info("아직 관측 기록이 없어. 실험실에서 입력을 투입해 봐.")
    st.download_button("이 프로토콜의 관측 기록 JSON", data=export_json(level, run),
                       file_name=f"blackbox09_protocol_{level+1}.json", mime="application/json",
                       use_container_width=True)
    st.caption("정답은 해당 프로토콜을 완료했을 때만 JSON 파일에 들어가. 기록과 점수는 서버 DB에 저장되지 않아.")

with guide_tab:
    st.markdown("#### 이 장치의 작동 방식")
    st.write("아홉 개 전구의 입력을 투입하면 블랙박스가 출력 전구 아홉 개를 돌려줘. 각 프로토콜에는 **항상 같은 하나의 규칙**이 적용돼. 같은 입력은 같은 출력이야.")
    st.write("관측 결과로 불가능한 규칙을 지우고, 충분히 확신하면 최종 판정을 내려. 1회 이상 실험한 뒤에만 판정할 수 있어.")
    st.markdown("#### 이번 프로토콜의 후보 법칙")
    for key in candidates(level):
        with st.expander(RULES[key].name + "  ·  " + RULES[key].short):
            st.write(RULES[key].explanation)
    st.markdown("#### 점수")
    st.write("100점에서 **첫 실험 이후 추가 실험 1회당 12점**, 최적 실험 추천 1회당 16점, 오답 1회당 18점을 차감해. 최저점은 0점이며 포기하면 그 단계는 0점이야.")
    st.markdown("#### 가설을 시험하는 요령")
    st.write("대칭인 입력은 서로 다른 규칙이 같은 출력을 내기 쉬워. **비대칭인 입력**, **총 켜짐 개수가 다른 입력**을 비교하면 규칙이 갈라져. 추천 버튼은 남은 규칙을 가장 잘 구분할 입력을 정보이론으로 골라줘.")

st.markdown('<div class="lab-footer">BLACK BOX 09 // NO API KEY REQUIRED // PER-SESSION EXPERIMENT // 3×3 SYSTEM</div>', unsafe_allow_html=True)
