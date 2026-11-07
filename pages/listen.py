"""olmuse 블라인드 청취 (/listen). 로그인 없이 열리고, 듣는 사람은 이름이나 별명만 적는다.

모델 대결(docs/MODEL_BAKEOFF_PLAN.md 6절)의 클립을 모델 이름 없이 사람마다 다른 무작위 순서로 들려주고
1~10점을 받는다. 표는 이 PC의 .studio-data/listen.sqlite에 바로 저장된다(저장 단추 없음).
모델 이름을 밝힌 결과는 STUDIO_PASSWORD를 넣어야 보인다.
"""
import hmac
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bakeoff"))

from listen_store import Votes, clean_name, load_manifest, order_for, progress, tally  # noqa: E402

st.set_page_config(page_title="olmuse · 블라인드 청취", page_icon="🎧")
st.title("블라인드 청취")

manifest = load_manifest()
if not manifest or not manifest.get("tasks"):
    st.info("아직 들을 클립이 없어요. 준비되면 이 주소에서 다시 열어 주세요.")
    st.stop()

votes = Votes()
LETTERS = "ABCDEFGHIJ"
SCORES = list(range(1, 11))


def table(rows: list[dict]):
    """A small plain table; names are escaped so a nickname cannot break the layout."""
    if not rows:
        return
    clean = lambda v: "-" if v is None else " ".join(str(v).replace("|", "/").split())  # noqa: E731
    head = list(rows[0])
    st.markdown("\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
                          + ["| " + " | ".join(clean(r[h]) for h in head) + " |" for r in rows]))


def password():
    value = os.environ.get("STUDIO_PASSWORD")
    if value:
        return value
    try:
        return str(st.secrets.get("STUDIO_PASSWORD", ""))
    except Exception:
        return ""


st.write("과제마다 같은 요청으로 만든 곡이 여러 개 있어요. 누가 만들었는지는 숨겨져 있어요. "
         "끝까지 들어 보고 1(별로)~10(아주 좋음)점을 골라 주세요. 고르는 즉시 저장돼요.")
name = clean_name(st.text_input("이름이나 별명", key="listen_name", max_chars=40))
if not name:
    st.caption("이름을 적으면 클립이 나와요. 같은 이름으로 다시 오면 이어서 할 수 있어요.")
else:
    mine = votes.mine(name)

    def keep(task_id, clip_id, field):
        key = f"{field}|{task_id}|{clip_id}"
        value = st.session_state.get(key)
        if field == "score":
            votes.save(name, task_id, clip_id, score=value if isinstance(value, int) else None)
        else:
            votes.save(name, task_id, clip_id, mismatch=bool(value))

    rated = sum(1 for v in mine.values() if v["score"] is not None)
    total = sum(len(t["clips"]) for t in manifest["tasks"])
    st.progress(rated / total if total else 0, text=f"{rated}/{total}개 들음")
    for n, task in enumerate(manifest["tasks"], 1):
        st.subheader(f"{n}. {task['genre']}")
        st.caption(f"요청: {task['text']}")
        for letter, clip in zip(LETTERS, order_for(name, task)):
            saved = mine.get((task["id"], clip["clip"]), {})
            score_key, miss_key = f"score|{task['id']}|{clip['clip']}", f"mismatch|{task['id']}|{clip['clip']}"
            if score_key not in st.session_state and saved.get("score"):
                st.session_state[score_key] = saved["score"]
            if miss_key not in st.session_state:
                st.session_state[miss_key] = bool(saved.get("mismatch"))
            with st.container(border=True):
                st.markdown(f"**곡 {letter}**")
                st.html(f'<audio controls preload="none" style="width:100%" src="/app/static/bakeoff/{clip["file"]}"></audio>')
                st.pills("점수", SCORES, key=score_key, on_change=keep, args=(task["id"], clip["clip"], "score"),
                         label_visibility="collapsed")
                st.checkbox("요청과 안 맞음", key=miss_key, on_change=keep, args=(task["id"], clip["clip"], "mismatch"))

st.divider()
st.subheader("결과")
everyone = votes.all()
rows = progress(manifest, everyone)
if rows:
    table([{"이름": r["voter"], "들은 곡": f"{r['rated']}/{r['total']}"} for r in rows])
else:
    st.caption("아직 표가 없어요.")
secret = password()
entered = st.text_input("결과 보기 비밀번호", type="password", key="listen_result_pw")
if entered and secret and hmac.compare_digest(entered.encode(), secret.encode()):
    result = tally(manifest, everyone)
    st.write(f"청취자 {result['voters']}명. 강도는 같은 과제 안에서 점수를 맞대어 본 Bradley–Terry 값(평균 1).")
    table([{"모델": r["model"], "강도": None if r["bt"] is None else round(r["bt"], 2),
            "평균 점수": None if r["mean"] is None else round(r["mean"], 2), "표": r["n"],
            "요청과 안 맞음": r["mismatch"]} for r in result["models"]])
    if result["consistency"]:
        st.caption("같은 곡을 두 번 들었을 때 점수 차이(작을수록 일관됨)")
        table([{"이름": c["voter"], "과제": c["task"], "점수 차": c["gap"]} for c in result["consistency"]])
elif entered:
    st.error("비밀번호가 맞지 않아요.")
