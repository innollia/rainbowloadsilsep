"""olmuse 블라인드 청취 (/listen). 로그인 없이 열리고, 듣는 사람은 이름이나 별명만 적는다.

같은 요청으로 만든 곡 두 개를 들려주고 더 듣기 좋은 쪽만 고르게 한다. 장르를 몰라도 고를 수 있다.
모델 이름은 숨기고, 순서는 사람마다 다르다. 고르는 즉시 이 PC의 .studio-data/listen.sqlite에 저장된다.
가끔 앞서 고른 쌍을 좌우를 바꿔 다시 내서, 같은 답이 나오는지(일관성)를 본다.
모델 이름을 밝힌 결과는 STUDIO_PASSWORD를 넣어야 보인다.

화면은 휴대폰(375px) 먼저: 큰 재생 단추가 달린 곡 카드(components.html 한 iframe 안에 A·B를 함께 두어
한쪽을 틀면 다른 쪽이 멈춘다)와 높이 60px짜리 선택 단추. 두 곡을 다 틀어 보기 전에는 선택 단추를 흐리게만
보여 준다(누르는 것은 막지 않는다). 플레이어는 같은 출처 iframe이라 부모 문서 body에 표시만 단다.
"""
import hmac
import html
import json
import os
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bakeoff"))

from listen_store import GENRE_HINT, Pairs, clean_name, load_manifest, pair_queue, tally_pairs  # noqa: E402

st.set_page_config(page_title="olmuse · 블라인드 청취", page_icon="🎧", layout="centered")

A_COLOR, B_COLOR = "#FF8A5B", "#5BC8FF"
HEADPHONES = ("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
              "stroke='black' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M3 14v-2a9 9 0 0 1 18 0v2'/%3E"
              "%3Cpath d='M21 15a2 2 0 0 1-2 2h-1v-5h1a2 2 0 0 1 2 2zM3 15a2 2 0 0 0 2 2h1v-5H5a2 2 0 0 0-2 2z'/%3E%3C/svg%3E")

st.html(f"""<style>
header[data-testid="stHeader"], #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], [data-testid="stSidebarCollapsedControl"] {{ display: none !important; }}
html, body, .stApp, [data-testid="stAppViewContainer"] {{ background: #0f0f0f !important; }}
.stApp {{ color: #f2f2f2; }}
.block-container, [data-testid="stMainBlockContainer"] {{
  max-width: 720px !important; padding: 20px 16px 72px !important; margin: 0 auto; }}
.olm-hero {{ display: flex; align-items: center; gap: 12px; margin: 4px 0 6px; }}
.olm-hero .ic {{ width: 44px; height: 44px; border-radius: 14px; display: grid; place-items: center;
  background: linear-gradient(135deg, {A_COLOR}, {B_COLOR}); flex: none; }}
.olm-hero .ic i {{ width: 24px; height: 24px; background: #0f0f0f;
  -webkit-mask: url("{HEADPHONES}") center / contain no-repeat; mask: url("{HEADPHONES}") center / contain no-repeat; }}
.olm-hero h1 {{ font-size: 28px; line-height: 1.15; margin: 0; padding: 0; font-weight: 800; letter-spacing: -0.02em; }}
.olm-lead {{ font-size: 17px; line-height: 1.6; color: #c9c9c9; margin: 6px 0 4px; }}
.olm-lead b {{ color: #fff; }}
.olm-progress {{ margin: 6px 0 2px; }}
.olm-progress .row {{ display: flex; justify-content: space-between; align-items: baseline; font-size: 15px; color: #aaa; }}
.olm-progress .row b {{ font-size: 20px; color: #fff; font-weight: 800; }}
.olm-progress .bar {{ height: 8px; border-radius: 99px; background: #262626; overflow: hidden; margin-top: 8px; }}
.olm-progress .bar i {{ display: block; height: 100%; border-radius: 99px;
  background: linear-gradient(90deg, {A_COLOR}, {B_COLOR}); }}
.olm-task {{ background: #181818; border: 1px solid #2a2a2a; border-radius: 20px; padding: 18px; margin-top: 6px; }}
.olm-chip {{ display: inline-block; font-size: 15px; font-weight: 800; padding: 6px 12px; border-radius: 99px;
  background: #2a2a2a; color: #fff; }}
.olm-hint {{ font-size: 16px; line-height: 1.55; color: #cfcfcf; margin: 10px 0 0; }}
.olm-req {{ margin-top: 12px; padding: 12px 14px; border-left: 3px solid #555; background: #121212; border-radius: 0 12px 12px 0;
  font-size: 15px; line-height: 1.55; color: #e6e6e6; word-break: keep-all; overflow-wrap: anywhere; }}
.olm-req small {{ display: block; font-size: 12px; color: #888; font-weight: 700; letter-spacing: .04em; margin-bottom: 2px; }}
.olm-ask {{ font-size: 18px; font-weight: 800; text-align: center; margin: 4px 0 0; }}
.olm-nudge {{ font-size: 14px; color: #9a9a9a; text-align: center; margin: 2px 0 0; transition: opacity .3s; }}
body.olm-heard .olm-nudge {{ opacity: 0; }}
.olm-done {{ text-align: center; padding: 28px 16px; background: #181818; border-radius: 20px; border: 1px solid #2a2a2a; }}
.olm-done b {{ font-size: 22px; display: block; margin-bottom: 6px; }}
.olm-sec {{ font-size: 20px; font-weight: 800; margin: 8px 0 0; }}
iframe[title="streamlit_components_v1.html"], [data-testid="stIFrame"] {{ border: 0; }}

/* 이름 입력 */
.st-key-listen_name input, .st-key-listen_result_pw input {{ font-size: 18px !important; min-height: 56px; }}
.st-key-listen_name label p, .st-key-listen_result_pw label p {{ font-size: 16px !important; font-weight: 700; color: #ddd; }}
.st-key-listen_name [data-baseweb="input"], .st-key-listen_result_pw [data-baseweb="input"] {{ border-radius: 14px; }}

/* 선택 단추 */
.st-key-olm_choices button {{ min-height: 60px; border-radius: 16px; font-size: 18px; font-weight: 800;
  border: 2px solid #3a3a3a; background: #1c1c1c; color: #fff; transition: opacity .25s, transform .1s, background .2s; }}
.st-key-olm_choices button p {{ font-size: 18px !important; font-weight: 800; }}
.st-key-olm_choices button:active {{ transform: scale(.98); }}
.st-key-olm_choices [class*="st-key-pick-left"] button {{ border-color: {A_COLOR}; color: {A_COLOR}; }}
.st-key-olm_choices [class*="st-key-pick-right"] button {{ border-color: {B_COLOR}; color: {B_COLOR}; }}
@media (hover: hover) {{
  .st-key-olm_choices [class*="st-key-pick-left"] button:hover {{ background: {A_COLOR}; color: #0f0f0f; }}
  .st-key-olm_choices [class*="st-key-pick-right"] button:hover {{ background: {B_COLOR}; color: #0f0f0f; }}
  .st-key-olm_choices [class*="st-key-pick-same"] button:hover {{ background: #333; border-color: #777; color: #fff; }}
}}
.st-key-olm_choices button:focus:not(:active) {{ box-shadow: none; }}
body:not(.olm-heard) .st-key-olm_choices button {{ opacity: .5; }}
.st-key-olm_choices [data-testid="stHorizontalBlock"] {{ gap: 10px; }}
@media (max-width: 640px) {{
  .st-key-olm_choices [data-testid="stHorizontalBlock"] {{ flex-direction: column; gap: 10px; }}
  .st-key-olm_choices [data-testid="stColumn"] {{ width: 100% !important; flex: 1 1 auto !important; min-width: 100% !important; }}
}}

/* 결과 표가 휴대폰에서 넘치지 않게 */
.st-key-olm_results table {{ display: block; max-width: 100%; overflow-x: auto; font-size: 14px; border-collapse: collapse; }}
.st-key-olm_results th, .st-key-olm_results td {{ padding: 6px 10px; white-space: nowrap; }}
.st-key-olm_results td:first-child {{ white-space: normal; word-break: break-all; min-width: 120px; }}
</style>""")

manifest = load_manifest()
st.html('<div class="olm-hero"><div class="ic"><i></i></div><h1>블라인드 청취</h1></div>')
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


PLAYER = """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{background:#0f0f0f;color:#f2f2f2;font-family:"Source Sans Pro",-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;overflow:hidden}
.grid{display:grid;grid-template-columns:1fr;gap:12px;padding:2px}
@media(min-width:600px){.grid{grid-template-columns:1fr 1fr}}
.card{background:#181818;border:2px solid #2a2a2a;border-radius:20px;padding:16px;display:flex;align-items:center;gap:16px;transition:border-color .2s,background .2s}
.card.on{border-color:var(--c);background:#1d1d1d}
.play{flex:none;width:72px;height:72px;border-radius:50%;border:0;background:var(--c);color:#0f0f0f;display:grid;place-items:center;cursor:pointer;transition:transform .1s}
.play:active{transform:scale(.94)}
.play svg{width:32px;height:32px}
.body{flex:1;min-width:0}
.top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.name{font-size:22px;font-weight:800;color:var(--c)}
.heard{font-size:13px;font-weight:700;color:#8a8a8a;display:flex;align-items:center;gap:4px;white-space:nowrap}
.heard svg{width:16px;height:16px}
.card.done .heard{color:#cfcfcf}
.bar{position:relative;height:10px;border-radius:99px;background:#2c2c2c;margin-top:12px;cursor:pointer;touch-action:none}
.bar i{position:absolute;left:0;top:0;bottom:0;width:0;border-radius:99px;background:var(--c)}
.time{display:flex;justify-content:space-between;font-size:13px;color:#9a9a9a;margin-top:6px;font-variant-numeric:tabular-nums}
</style></head><body><div class="grid" id="g"></div><script>
const CLIPS = __CLIPS__;
const ICON = {
  play:'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg>',
  pause:'<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1.2"/><rect x="14" y="5" width="4" height="14" rx="1.2"/></svg>',
  load:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M12 3a9 9 0 1 0 9 9"><animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur=".9s" repeatCount="indefinite"/></path></svg>',
  ear:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>'
};
const g = document.getElementById('g');
let parentBody = null;
try { parentBody = window.parent.document.body; parentBody.classList.remove('olm-heard'); } catch (e) {}
const fmt = s => isFinite(s) ? Math.floor(s/60) + ':' + String(Math.floor(s%60)).padStart(2,'0') : '-:--';
const players = CLIPS.map(c => {
  const el = document.createElement('div');
  el.className = 'card'; el.style.setProperty('--c', c.color);
  el.innerHTML = `<button class="play" aria-label="곡 ${c.label} 재생">${ICON.play}</button>
    <div class="body"><div class="top"><span class="name">곡 ${c.label}</span><span class="heard">아직 안 들음</span></div>
    <div class="bar" role="slider" aria-label="곡 ${c.label} 위치"><i></i></div>
    <div class="time"><span class="cur">0:00</span><span class="dur">-:--</span></div></div>`;
  g.appendChild(el);
  const a = new Audio(); a.preload = 'metadata'; a.src = c.src;
  const btn = el.querySelector('.play'), fill = el.querySelector('.bar i'), bar = el.querySelector('.bar');
  const p = {c, el, a, heard: false};
  const paint = () => {
    btn.innerHTML = a.paused ? ICON.play : ICON.pause;
    btn.setAttribute('aria-label', `곡 ${c.label} ${a.paused ? '재생' : '정지'}`);
    el.classList.toggle('on', !a.paused);
  };
  btn.onclick = () => {
    if (a.paused) { players.forEach(o => { if (o !== p) o.a.pause(); }); a.play().catch(() => paint()); }
    else a.pause();
    paint();
  };
  a.addEventListener('play', () => { players.forEach(o => { if (o !== p) o.a.pause(); }); paint(); });
  a.addEventListener('pause', paint);
  a.addEventListener('ended', () => { a.currentTime = 0; paint(); });
  a.addEventListener('waiting', () => { if (!a.paused) btn.innerHTML = ICON.load; });
  a.addEventListener('playing', paint);
  a.addEventListener('loadedmetadata', () => { el.querySelector('.dur').textContent = fmt(a.duration); });
  a.addEventListener('timeupdate', () => {
    fill.style.width = (a.duration ? 100 * a.currentTime / a.duration : 0) + '%';
    el.querySelector('.cur').textContent = fmt(a.currentTime);
    if (!p.heard && a.currentTime > 3) { p.heard = true; el.classList.add('done');
      el.querySelector('.heard').innerHTML = ICON.ear + '들었어요'; check(); }
  });
  const seek = e => { const r = bar.getBoundingClientRect();
    const x = Math.min(Math.max(0, (e.clientX - r.left) / r.width), 1);
    if (a.duration) a.currentTime = x * a.duration; };
  bar.addEventListener('pointerdown', e => { bar.setPointerCapture(e.pointerId); seek(e);
    bar.onpointermove = seek; bar.onpointerup = () => { bar.onpointermove = null; }; });
  return p;
});
function check() { if (parentBody && players.every(p => p.heard)) parentBody.classList.add('olm-heard'); }
function fit() { try { const h = Math.ceil(g.getBoundingClientRect().height + 4) + 'px';
  window.frameElement.style.height = h; const w = window.frameElement.parentElement.style;
  w.setProperty('height', h, 'important'); w.setProperty('flex', '0 0 ' + h, 'important'); } catch (e) {} }
new ResizeObserver(fit).observe(g); fit();
</script></body></html>"""


def players(left: str, right: str):
    clips = [{"label": "A", "color": A_COLOR, "src": f"/app/static/bakeoff/{files[left]}"},
             {"label": "B", "color": B_COLOR, "src": f"/app/static/bakeoff/{files[right]}"}]
    components.html(PLAYER.replace("__CLIPS__", json.dumps(clips)), height=240)


st.html('<p class="olm-lead">같은 요청으로 AI들이 만든 곡 두 개를 들려드려요. 누가 만들었는지는 숨겨져 있어요. '
        '장르를 몰라도 괜찮아요. <b>둘 중 더 듣기 좋은 쪽</b>만 골라 주세요. 하고 싶은 만큼만 하면 돼요.</p>')
name = clean_name(st.text_input("이름이나 별명", key="listen_name", max_chars=40, placeholder="예: 민지"))
if not name:
    st.caption("이름을 적으면 시작해요. 같은 이름으로 다시 오면 이어서 할 수 있어요.")
else:
    queue = pair_queue(name, manifest)
    done = pairs.done(name)
    left_over = [q for q in queue if (q["task"], q["left"], q["right"], q["repeat"]) not in done]
    finished = len(queue) - len(left_over)
    if not left_over:
        st.html(f'<div class="olm-done"><b>전부 들었어요. 고마워요!</b>{len(queue)}쌍을 모두 골랐어요.</div>')
    else:
        item = left_over[0]
        task = tasks[item["task"]]
        st.html(f'<div class="olm-progress"><div class="row"><span><b>{finished + 1}</b> 번째 쌍</span>'
                f'<span>{finished}/{len(queue)} 완료</span></div>'
                f'<div class="bar"><i style="width:{100 * finished / len(queue):.1f}%"></i></div></div>'
                f'<div class="olm-task"><span class="olm-chip">{html.escape(task["genre"])}</span>'
                f'<p class="olm-hint">{html.escape(GENRE_HINT.get(task["genre"], ""))}</p>'
                f'<div class="olm-req"><small>요청</small>{html.escape(task["text"])}</div></div>')
        players(item["left"], item["right"])
        st.html('<p class="olm-ask">어느 쪽이 더 듣기 좋았나요?</p>'
                '<p class="olm-nudge">두 곡을 모두 들어 보고 골라 주세요</p>')
        with st.container(key="olm_choices"):
            choice = st.columns(3)
            for col, label, winner in zip(choice, ("A가 더 좋아", "비슷해", "B가 더 좋아"), ("left", "same", "right")):
                if col.button(label, key=f"pick-{winner}-{len(done)}", use_container_width=True):
                    pairs.save(name, item, winner)
                    st.rerun()

st.divider()
with st.container(key="olm_results"):
    st.html('<p class="olm-sec">결과</p>')
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
