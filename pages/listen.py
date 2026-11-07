"""olmuse 블라인드 청취 (/listen). 로그인 없이 열리고, 듣는 사람은 이름이나 별명만 적는다.

같은 요청으로 만든 곡 두 개를 들려주고 더 듣기 좋은 쪽만 고르게 한다. 장르를 몰라도 고를 수 있다.
모델 이름은 숨기고, 순서는 사람마다 다르다. 고르는 즉시 이 PC의 .studio-data/listen.sqlite에 저장된다.
가끔 앞서 고른 쌍을 좌우를 바꿔 다시 내서, 같은 답이 나오는지(일관성)를 본다.
모델 이름을 밝힌 결과는 STUDIO_PASSWORD를 넣어야 보인다.
"""
import hmac
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bakeoff"))

from listen_store import GENRE_HINT, Pairs, clean_name, load_manifest, pair_queue, tally_pairs  # noqa: E402

st.set_page_config(page_title="olmuse · 블라인드 청취", page_icon="🎧")
st.title("블라인드 청취")

manifest = load_manifest()
if not manifest or not manifest.get("tasks"):
    st.info("아직 들을 곡이 없어요. 준비되면 이 주소에서 다시 열어 주세요.")
    st.stop()

pairs = Pairs()
tasks = {t["id"]: t for t in manifest["tasks"]}
files = {c["clip"]: c["file"] for t in manifest["tasks"] for c in t["clips"]}


def table(rows: list[dict]):
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


def player(clip: str):
    st.html(f'<audio controls preload="none" style="width:100%" src="/app/static/bakeoff/{files[clip]}"></audio>')


st.write("같은 요청으로 AI들이 만든 곡 두 개를 들려드려요. 누가 만들었는지는 숨겨져 있어요. "
         "장르를 몰라도 괜찮아요. **둘 중 더 듣기 좋은 쪽**만 골라 주세요. 하고 싶은 만큼만 하면 돼요.")
name = clean_name(st.text_input("이름이나 별명", key="listen_name", max_chars=40))
if not name:
    st.caption("이름을 적으면 시작해요. 같은 이름으로 다시 오면 이어서 할 수 있어요.")
else:
    queue = pair_queue(name, manifest)
    done = pairs.done(name)
    left_over = [q for q in queue if (q["task"], q["left"], q["right"], q["repeat"]) not in done]
    st.progress(1 - len(left_over) / len(queue), text=f"{len(queue) - len(left_over)}/{len(queue)}쌍")
    if not left_over:
        st.success("전부 들었어요. 고마워요!")
    else:
        item = left_over[0]
        task = tasks[item["task"]]
        with st.container(border=True):
            st.markdown(f"**{task['genre']}** · {GENRE_HINT.get(task['genre'], '')}")
            st.caption(f"요청: {task['text']}")
            a, b = st.columns(2)
            with a:
                st.markdown("**곡 A**")
                player(item["left"])
            with b:
                st.markdown("**곡 B**")
                player(item["right"])
            choice = st.columns(3)
            for col, label, winner in zip(choice, ("A가 더 좋아", "비슷해", "B가 더 좋아"), ("left", "same", "right")):
                if col.button(label, key=f"pick-{winner}-{len(done)}", use_container_width=True):
                    pairs.save(name, item, winner)
                    st.rerun()

st.divider()
st.subheader("결과")
everyone = pairs.all()
counts = {}
for p in everyone:
    counts[p["voter"]] = counts.get(p["voter"], 0) + 1
if counts:
    table([{"이름": v, "고른 쌍": n} for v, n in sorted(counts.items())])
else:
    st.caption("아직 표가 없어요.")
secret = password()
entered = st.text_input("결과 보기 비밀번호", type="password", key="listen_result_pw")
if entered and secret and hmac.compare_digest(entered.encode(), secret.encode()):
    result = tally_pairs(manifest, everyone)
    st.write(f"청취자 {result['voters']}명, 선택 {result['choices']}번. 강도는 Bradley–Terry 값(평균 1, 높을수록 많이 이김).")
    table([{"모델": r["model"], "강도": None if r["bt"] is None else round(r["bt"], 2),
            "승률": f"{100 * r['win_rate']:.0f}%", "대결 수": r["n"]} for r in result["models"]])
    if result["consistency"]:
        st.caption("같은 쌍을 좌우 바꿔 다시 들었을 때 같은 답을 고른 횟수")
        table([{"이름": c["voter"], "같은 답": f"{c['same']}/{c['repeats']}"} for c in result["consistency"]])
elif entered:
    st.error("비밀번호가 맞지 않아요.")
