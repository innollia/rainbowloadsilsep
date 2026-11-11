"""What asking for sounds costs in the asset room (quote.js, and app.js where it is shown), under Node: the number in
the five labels that carry one, the draft picker that follows a count written in the request (in the dock and in the
open sound), the request that waits when the assistant's answer costs more than the number that was showing at the
press and is later made as that answer asked, a price that has not come, putting an answer back, the approved sounds
a new one is told to stay close to, and several sounds changed at once that each end on their own. The page runs on
the stand-in DOM of the generator's tests, with the scripts index.html names, so quote.js is loaded the way the
browser loads it."""
import json, re

import test_asset_gen_js as genjs  # the generator's harness: both clocks, the API in memory, the stand-in DOM

ROOT, HELPERS, DOM, node = genjs.ROOT, genjs.HELPERS, genjs.DOM, genjs.node
MODULES = ("data.js", "synth.js", "importer.js", "measure.js", "store.js", "gen.js", "quote.js")


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def scripts():
    """The scripts of index.html, in the order the page loads them."""
    return re.findall(r'<script src="([^"?]+)', read("index.html"))


def run(body):
    """quote.js beside the modules it works with, then `body`, which fills `out`."""
    src = "globalThis.window = globalThis;\n" + "\n;\n".join(read(f) for f in MODULES) + "\n;\n" + HELPERS
    return node(src + "\n(async () => {\nconst out = {};\nconst Q = window.assetQuote;\n" + body + "\nconsole.log(JSON.stringify(out));\n})().catch((e) => { console.error(e); process.exit(1); });")


def run_page(body, before=""):
    """The page as index.html loads it, app.js last. `before` runs before app.js: what the page finds when it starts."""
    files = scripts()
    assert files[-1] == "app.js"
    src = "globalThis.window = globalThis;\n" + "\n;\n".join(read(f) for f in files[:-1]) + "\n;\n" + HELPERS
    src += "\nconst INDEX_HTML = " + json.dumps(read("index.html")) + ";\n" + DOM + "\n;\n" + before + "\n;\n" + read("app.js")
    return node(src + "\n;(async () => {\nconst out = {};\n" + body + "\nconsole.log(JSON.stringify(out));\n})().catch((e) => { console.error(e); process.exit(1); });")


# A board that was saved on an earlier visit: five sounds made by the generator (their patch is known), a sound that
# was brought in, and three empty slots. Approved: the wind, the title music, two effects and the brought-in sound.
SAVED = r"""
const WAV = wavOf(440), FACTS = M.measure(M.readWav(WAV)), OUTLINE = S.peaksOf(M.readWav(WAV).chans, 200);
const madeVer = (id) => ({ id, at: 1, note: { key: 'fromPrompt' }, engine: 'nkido', job: id, parent: null, draft: { k: 1, n: 1 }, source: 'PATCH ' + id, seconds: FACTS.seconds, bpm: null,
  prompt: 'PROMPT ' + id, model: 'model-x', sources: [NKIDO], measure: FACTS, issues: [], peaks: OUTLINE, key: 'ver:' + id, stems: [], rate: 48000, channels: 1, bits: 16, bytes: WAV.length, sha256: sha(WAV) });
const broughtIn = (id) => ({ ...madeVer(id), note: { key: 'importedNote' }, engine: 'import', job: null, draft: null, source: null, prompt: null, model: null, sources: [{ name: 'mine.wav', license: 'CC0', holder: 'me', use: 'Imported sound' }] });
const onBoard = (id, cat, status, versions = [], more = {}) => ({ id, name: id, cat, key: 'k-' + id, status, versions, current: 0, drafts: [], pick: -1, chat: [], music: cat === 'bgm', loop: cat === 'env' || cat === 'bgm', layers: [], hasSource: false, ...more });
const BOARD = { v: 2, game: 'Moon Farm', brief: 'calm', platform: 'mobile', demo: false, stage: 'expand', loud: [-20, -16], trash: [], assets: [
  onBoard('amb_wind', 'env', 'approved', [madeVer('v-wind')]), onBoard('bgm_title', 'bgm', 'approved', [madeVer('v-title')]),
  onBoard('sfx_one', 'ui', 'approved', [madeVer('v-one')]), onBoard('sfx_two', 'ui', 'approved', [madeVer('v-two')]), onBoard('sfx_three', 'ui', 'draft', [madeVer('v-three')]),
  onBoard('sfx_mine', 'combat', 'approved', [broughtIn('v-mine')], { imported: true, file: 'mine.wav', license: 'CC0', holder: 'me' }),
  onBoard('sfx_hit', 'combat', 'pending'), onBoard('sfx_block', 'combat', 'pending'), onBoard('sfx_new', 'ui', 'pending'),
] };
disk.stores.set('board', new Map([['board', BOARD]]));
disk.stores.set('audio', new Map(BOARD.assets.flatMap((a) => a.versions).map((v) => [v.key, new Blob([WAV])])));
"""
# The page inside the host page, whose assistant answers what is typed in the dock.
HOST = "const hostBox = []; own('parent', { postMessage: (m) => hostBox.push(m) });"
# Hands and eyes for a test. x picks the focused tile (or lets it go) without playing it; the dial is the draft picker
# of the dock and seg the label beside it; write() types into the dock's input the way a browser reports typing.
TOOLS = r"""
    T.slow = 10;
    await settle(); await advance(0);
    const $ = (id) => document.getElementById(id), tiles = () => document.querySelectorAll('.tile'), tileOf = (id) => document.querySelector('.tile[data-id="' + id + '"]');
    const said = () => ($('toast').hidden ? null : $('toast').textContent);
    const statusOf = (...ids) => ids.map((id) => tileOf(id).dataset.status);
    const key = (k, target = document.body) => tellWindow('keydown', { key: k, code: k, target });
    const pick = (...ids) => { for (const id of ids) { tileOf(id).focus(); key('x'); } };
    const picked = () => tiles().filter((t) => t.classList.contains('selected')).map((t) => t.dataset.id).sort();
    const seg = () => $('draftSlot').querySelector('.segLabel').textContent;
    const radios = () => $('draftSlot').querySelectorAll('[role=radio]');
    const dial = () => +radios().find((b) => b.getAttribute('aria-checked') === 'true').textContent;
    const setDial = (i) => radios()[i - 1].click();
    const write = (text) => { $('ask').value = text; $('ask').fire('input'); };
    const send = async () => { $('askForm').fire('submit'); await settle(); await advance(0); };
    const tell = (data) => tellWindow('message', { data, source: parent, origin: location.origin });
    const quotes = () => api.paths().filter((p) => p.startsWith('GET /quote')).length;
    const hand = async (kind = 'acct', sub = 'acct:me') => { const n = quotes(); tell({ type: 'asset:token', token: tokenOf(kind, sub), ttl: 900, api: BASE }); await until(() => quotes() > n); };
    const onDisk = (id) => { const b = disk.stores.get('board').get('board'); return b && b.assets.find((a) => a.id === id); };
    const picksOf = (id) => tileOf(id).querySelectorAll('[data-pick]').map((b) => b.textContent);
    const trash = async (id) => { tileOf(id).fire('contextmenu', { clientX: 0, clientY: 0 }); $('tileMenu').querySelectorAll('button').find((b) => b.textContent.startsWith('Move to trash')).click(); await settle(); };
    // Every element whose own text names credits, by id or class.
    const numbered = () => { const hit = []; const walk = (n) => { for (const c of n.children) { if (/credit|크레딧/.test(c.childNodes.filter((x) => x.nodeType === 3).map((x) => x.textContent).join(''))) hit.push(c.id || c.className); walk(c); } }; walk(document.body); return hit.sort(); };
"""
AGENT = r"""
    const agentAsked = () => hostBox.filter((m) => m.type === 'asset:agent');
    const answer = async (reply, actions) => { tell({ type: 'asset:agent_reply', n: agentAsked().at(-1).payload.n, status: 'done', reply, actions }); await settle(); await advance(0); };
    tell({ type: 'asset:ai', on: true });
"""
HELD_EN = ("That takes more credits than the number that was showing, so nothing has started. The sounds are picked and your words are back in the box, "
           "with the new number beside the draft count. Send it as it is to make them.")


# ---------- quote.js by itself ----------

def test_three_sounds_in_two_drafts_read_six_and_a_free_or_unpriced_label_has_no_number():
    got = run(r"""
    const words = (label, n) => label + ' · ' + n + ' 크레딧';
    const p = page({ assets: [] });
    out.noPrice = [Q.label('시안', p.gen.quoteOf(3, 2), words), Q.number(p.gen.quoteOf(3, 2))];   // no token yet
    await p.token();
    out.six = [Q.label('시안', p.gen.quoteOf(3, 2), words), Q.number(p.gen.quoteOf(3, 2))];
    out.rest = Q.label('나머지 만들기', p.gen.quoteOf(24, 1), words);
    out.nothing = [Q.label('시안', p.gen.quoteOf(0, 2), words), Q.number(null)];                    // nothing picked: nothing to price
    // A session that pays nothing shows no number.
    const f = page({ assets: [] }); f.api.free = true; f.api.unit = 0;
    await f.token('pw', 'pw:room');
    out.free = [Q.label('시안', f.gen.quoteOf(3, 2), words), Q.number(f.gen.quoteOf(3, 2)), f.gen.quoteOf(3, 2).free];
    out.same = p.gen.quoteOf(3, 2).credits;                                                         // the sum generate() sends
    """)
    assert got["noPrice"] == ["시안", None]
    assert got["six"] == ["시안 · 6 크레딧", 6] and got["rest"] == "나머지 만들기 · 24 크레딧" and got["same"] == 6
    assert got["nothing"] == ["시안", None] and got["free"] == ["시안", None, True]


def test_an_answer_that_costs_more_than_the_label_showed_waits_until_it_is_sent_again_as_it_is():
    got = run(r"""
    const quote = (items, drafts, unit = 1, more = {}) => ({ items, drafts, unit, credits: unit == null ? null : items * drafts * unit, free: false, known: unit != null, ...more });
    const TEXT = '시안 4개로 더 밝게';
    let q = Q.create();
    // 6 was on the label when send was pressed. The answer wants the three in four drafts: 12 is more, so it waits,
    // and what the answer asked for (which sounds, in which words) is kept beside it.
    const PLAN = { remakes: [[['a', 'b'], '더 밝게'], [['c'], '조금만 더 밝게']], fills: [] };
    out.first = q.send(TEXT, ['a', 'b', 'c'], quote(3, 2));
    out.none = [q.held, q.plan];
    out.answer = q.answer(['a', 'b', 'c'], TEXT, quote(3, 4), PLAN);
    out.held = q.held;
    out.plan = q.plan;
    q.held.ids.push('z');                                                             // a copy: the state is its own
    out.still = [q.changed(TEXT, ['c', 'b', 'a']), q.held];                           // the same words and sounds, in any order
    // Sent again as it is while the label says less than it takes (it changed under the request): it goes on waiting.
    out.under = [q.send(TEXT, ['b', 'a', 'c'], quote(3, 2), quote(3, 4)), q.send(TEXT, ['b', 'a', 'c'], quote(3, 4, null), quote(3, 4, null)), q.held, q.plan === PLAN];
    out.again = q.send(TEXT, ['b', 'a', 'c'], quote(3, 4), quote(3, 4));              // the label says what it takes: no assistant
    out.after = [q.held, q.plan, q.send(TEXT, ['a', 'b', 'c'], quote(3, 4), quote(3, 4))]; // once: the next one is asked again
    // Part of it was made some other way meanwhile: what is left costs less than the label says, and is made.
    q = Q.create(); q.send(TEXT, ['a'], quote(1, 2)); q.answer(['a', 'b', 'c'], TEXT, quote(3, 2));
    out.less = [q.plan, q.send(TEXT, ['a', 'b', 'c'], quote(3, 2), quote(2, 2)).via];
    // Within the number: it starts and nothing waits.
    q = Q.create();
    q.send('softer', ['a', 'b'], quote(2, 2));
    out.within = [q.answer(['a', 'b'], 'softer', quote(2, 2)), q.answer(['a'], 'softer', quote(1, 2)), q.held];
    // Other words, or other sounds picked, let a waiting request go. So does drop().
    const hold = () => { const x = Q.create(); x.send('all louder', ['a'], quote(1, 1)); x.answer(['a', 'b'], 'all louder', quote(2, 1)); return x; };
    let x = hold(); out.words = [x.changed('all much louder', ['a', 'b']), x.held];
    x = hold(); out.sounds = [x.changed('all louder', ['a']), x.held, hold().changed('all louder', ['a', 'b', 'c'])];
    x = hold(); out.other = [x.send('all louder', ['a']).via, x.held];                 // sent with other sounds picked: asked again
    x = hold(); x.drop(); out.dropped = x.held;
    // A session that pays nothing is never held. With no price read, no label carried a number: nothing that costs
    // credits starts, whether the price is still unknown at the answer or has come by then.
    q = Q.create(); q.send('more', ['a'], quote(1, 1, 0, { free: true }));
    out.free = [q.answer(['a', 'b', 'c'], 'more', quote(3, 4, 0, { free: true })), q.held];
    q = Q.create(); q.send('more', ['a'], quote(1, 2, null));
    out.unpriced = [q.answer(['a'], 'more', quote(1, 2, null)), q.answer(['a', 'b'], 'more', quote(2, 2, null)), q.answer(['a'], 'more', quote(1, 2, 1)), q.answer(['a'], 'more', quote(1, 2, 0, { free: true }))];
    // Nothing was on the label (nothing picked, or the session paid nothing then): whatever costs credits waits.
    q = Q.create(); q.send('everything again', [], quote(0, 2));
    out.nothing = [q.answer(['a'], 'everything again', quote(1, 2)), q.held];
    q = Q.create(); q.send('again', ['a'], quote(1, 1, 0, { free: true }));
    out.wasFree = q.answer(['a'], 'again', quote(1, 1));
    out.fits = [Q.fits(quote(1, 1), null), Q.fits(null, null), Q.fits(quote(3, 2), quote(3, 2)), Q.fits(quote(3, 2, 2), quote(3, 2, 1)),
      Q.fits(quote(1, 1, null), quote(4, 4)), Q.fits(quote(1, 1), quote(4, 4, null)), Q.fits(quote(0, 2), null), Q.fits(quote(3, 4, 0, { free: true }), null)];
    """)
    text = "시안 4개로 더 밝게"
    plan = {"remakes": [[["a", "b"], "더 밝게"], [["c"], "조금만 더 밝게"]], "fills": []}
    assert got["first"] == {"via": "agent"} and got["none"] == [None, None] and got["answer"] == "hold"
    assert got["held"] == {"ids": ["a", "b", "c"], "text": text} and got["plan"] == plan      # held is { ids, text }; the plan is beside it
    assert got["still"] == [True, {"ids": ["a", "b", "c"], "text": text}]
    assert got["under"] == [{"via": "hold"}, {"via": "hold"}, {"ids": ["a", "b", "c"], "text": text}, True]
    assert got["again"] == {"via": "direct", "ids": ["a", "b", "c"], "text": text, "plan": plan} and got["after"] == [None, None, {"via": "agent"}]
    assert got["less"] == [None, "direct"]
    assert got["within"] == ["start", "start", None]
    assert got["words"] == [False, None] and got["sounds"] == [False, None, False] and got["other"] == ["agent", None] and got["dropped"] is None
    assert got["free"] == ["start", None] and got["unpriced"] == ["hold", "hold", "hold", "start"]
    assert got["nothing"] == ["hold", {"ids": ["a"], "text": "everything again"}] and got["wasFree"] == "hold"
    # the price went up between the press and the answer: it waits. A price that is not known fits nothing and nothing fits it.
    assert got["fits"] == [False, True, True, False, False, False, True, True]


def test_examples_are_approved_patches_of_the_kinds_asked_for_first_and_three_at_most():
    got = run(r"""
    const one = (name, kind, source = 'PATCH ' + name, more = {}) => ({ name, kind, loop: kind !== 'sfx', source, facts: { seconds: 1 }, extra: 'not sent', ...more });
    const pool = [one('wind', 'amb'), one('title', 'music'), one('click', 'sfx'), one('step', 'sfx'), one('coin', 'sfx'), one('rain', 'amb')];
    const names = (list) => list.map((e) => e.name);
    out.sfx = names(Q.examples(['sfx', 'sfx'], pool));                    // the same kind first
    out.amb = names(Q.examples(['amb'], pool));                           // then the others, in board order
    out.mixed = names(Q.examples(['sfx', 'amb', 'sfx', 'music'], pool));  // one of each kind asked for, the most asked first
    out.two = names(Q.examples(['sfx', 'sfx', 'amb'], pool));
    out.none = [Q.examples(['sfx'], []), Q.examples(['sfx'], null), Q.examples(null, null)];
    out.shape = Q.examples(['sfx'], pool)[0];
    // A sound without a patch (brought in, or from the built-in synth) is not an example, nor is a patch too long to send.
    const odd = [one('mine', 'sfx', null), one('old', 'sfx', '', { source: undefined }), one('blank', 'sfx', '   '), one('long', 'sfx', 'x'.repeat(Q.SOURCE_CAP + 1)), one('fits', 'sfx', 'x'.repeat(Q.SOURCE_CAP)), one('wind', 'amb')];
    out.usable = names(Q.examples(['sfx'], odd));
    out.max = [Q.MAX_EXAMPLES, names(Q.examples(['sfx'], pool, 1))];
    // What gen.js sends of them is the same three.
    out.sent = G.shapeExamples(Q.examples(['sfx', 'sfx'], pool)).map((e) => e.name);
    """)
    assert got["sfx"] == ["click", "step", "coin"] and got["amb"] == ["wind", "rain", "title"]
    assert got["mixed"] == ["click", "wind", "title"] and got["two"] == ["click", "wind", "step"]
    assert got["none"] == [[], [], []]
    assert got["shape"] == {"name": "click", "kind": "sfx", "loop": False, "source": "PATCH click", "facts": {"seconds": 1}}
    assert got["usable"] == ["fits", "wind"] and got["max"] == [3, ["click"]] and got["sent"] == ["click", "step", "coin"]


# ---------- the page ----------

def test_the_labels_carry_a_number_which_comes_with_an_account_and_follows_a_changed_price():
    got = run_page(TOOLS + r"""
    // No token: nothing has a number.
    out.off = [seg(), $('fillBtn').textContent, numbered()];
    // A session that pays nothing: the price is read once, and still nothing has a number.
    api.free = true; api.unit = 0;
    await hand('pw', 'pw:room');
    pick('sfx_one', 'sfx_two', 'sfx_three'); setDial(2);
    out.free = [seg(), $('fillBtn').textContent, numbered(), api.paths()];
    // The token becomes an account's: the price is read again and the numbers appear. 3 sounds x 2 drafts is 6.
    api.free = false; api.unit = 1;
    await hand('acct', 'acct:me');
    out.acct = [seg(), $('fillBtn').textContent, numbered(), api.paths()];
    setDial(3); out.three = seg();
    pick('sfx_three'); out.two = seg();                                   // one sound let go: 2 x 3
    pick('sfx_three'); setDial(2);
    // The same token again (a renewal) reads no price and keeps the numbers.
    tell({ type: 'asset:token', token: tokenOf('acct', 'acct:me', 'next'), ttl: 900, api: BASE }); await settle();
    out.renewed = [seg(), quotes()];
    // The brought-in sound, opened: "like this" fills the two empty slots of its group, and the picker there is for one sound.
    tileOf('sfx_mine').focus(); key('Enter', tileOf('sfx_mine'));
    await until(() => !!$('likeThis'));
    out.open = [$('likeThis').textContent, document.querySelector('.dTools .segLabel').textContent, numbered()];
    key('Escape'); await settle();
    // The price is not what the button showed: nothing is made, the new number is shown, and nothing is sent again.
    api.unit = 3;
    $('fillBtn').click();
    await until(() => api.posted('/jobs').length === 1 && quotes() === 3);
    await settle(); await advance(0);
    out.changed = { button: $('fillBtn').textContent, seg: seg(), said: said(), expected: api.posted('/jobs')[0].expect_credits, status: statusOf('sfx_hit', 'sfx_block', 'sfx_new') };
    await advance(10000);
    out.notAgain = [api.posted('/jobs').length, statusOf('sfx_hit', 'sfx_block', 'sfx_new'), $('fillBtn').textContent];
    """, before=SAVED)
    assert got["off"] == ["Drafts", "Make all", []]
    assert got["free"] == ["Drafts", "Make all", [], ["GET /quote?items=1&drafts=1"]]
    assert got["acct"] == ["Drafts · 6 credits", "Make all · 3 credits", ["fillBtn", "segLabel"], ["GET /quote?items=1&drafts=1"] * 2]
    assert got["three"] == "Drafts · 9 credits" and got["two"] == "Drafts · 6 credits" and got["renewed"] == ["Drafts · 6 credits", 2]
    # only the picker's label, #fillBtn and #likeThis name credits here (#expandBtn is on the sample board, below)
    assert got["open"] == ["Drafts in this feel · 2 credits", "Drafts · 2 credits", ["fillBtn", "likeThis", "segLabel", "segLabel"]]
    assert got["changed"] == {"button": "Make all · 9 credits", "seg": "Drafts · 18 credits", "said": "server says quote_changed", "expected": 3, "status": ["pending"] * 3}
    assert got["notAgain"] == [1, ["pending"] * 3, "Make all · 9 credits"]


def test_the_make_button_of_an_empty_sound_shows_what_its_one_draft_takes_and_asks_for_exactly_that():
    """#makeOne spends a credit like the other buttons that make sounds, so it carries the same number by the same path:
    none without a token or in a session that pays nothing, the price of one draft for an account, and the new number
    where it stands when the price changes."""
    got = run_page(TOOLS + r"""
    const open = async (id) => { tileOf(id).focus(); key('Enter', tileOf(id)); await until(() => !!$('makeOne')); };
    await open('sfx_hit');
    out.off = [$('makeOne').textContent, numbered()];
    api.free = true; api.unit = 0;
    await hand('pw', 'pw:room');
    out.free = [$('makeOne').textContent, numbered()];
    api.free = false; api.unit = 2;
    await hand('acct', 'acct:me');
    out.acct = [$('makeOne').textContent, numbered().includes('makeOne'), $('makeOne').dataset.quote, document.querySelectorAll('#makeOne').length];
    // The picker beside the box is for a request written there. The button makes one draft whatever it says.
    document.querySelector('.dTools').querySelectorAll('[role=radio]')[2].click();
    out.dial = [document.querySelector('.dTools .segLabel').textContent, $('makeOne').textContent];
    $('makeOne').click();
    await until(() => api.posted('/jobs').length === 1);
    const sent = api.posted('/jobs')[0];
    out.made = [sent.items.map((i) => i.id), sent.drafts, sent.expect_credits, !!$('makeOne')];
    """, before=SAVED)
    assert got["off"] == ["Make it", []] and got["free"] == ["Make it", []]
    assert got["acct"] == ["Make it · 2 credits", True, "makeOne", 1]
    assert got["dial"] == ["Drafts · 6 credits", "Make it · 2 credits"]
    assert got["made"] == [["sfx_hit"], 1, 2, False]


def test_the_sample_board_prices_the_rest_and_one_credit_is_said_in_the_singular():
    got = run_page(TOOLS + r"""
    await hand();
    out.rest = [$('expandBtn').textContent, $('expandBtn').disabled, seg(), numbered()];
    tiles().find((t) => t.dataset.status === 'draft').focus();
    out.one = seg();                                                      // the focused sound is the one a request is for
    """)
    assert got["rest"] == ["Make the rest · 24 credits", True, "Drafts", ["expandBtn"]]
    assert got["one"] == "Drafts · 1 credit"


def test_a_number_of_drafts_in_the_words_moves_the_picker_and_filling_asks_with_examples():
    got = run_page(TOOLS + r"""
    await hand();
    pick('sfx_one', 'sfx_two', 'sfx_three'); setDial(2);
    out.start = [dial(), seg()];
    // The picker follows the words as they are typed, and the label says what that costs.
    write('시안 4개로 더 밝게'); out.four = [dial(), seg()];
    write('3 drafts, softer'); out.three = [dial(), seg()];
    write('9 drafts, softer'); out.most = dial();
    write('softer'); out.back = [dial(), seg()];                          // no number in the words: the number picked by hand
    // A number picked by hand after the words were written stands until the words change.
    write('3 drafts, softer'); setDial(1); out.byHand = [dial(), seg()];
    write('3 drafts, softer and'); out.words = dial();
    write(''); setDial(2);
    // The button fills the empty slots, one draft each whatever the picker says, with approved patches to go by:
    // effects first (they are what is asked for), three at most, and never the brought-in sound, which has no patch.
    $('fillBtn').click();
    await until(() => api.posted('/jobs').length === 1);
    const fill = api.posted('/jobs')[0];
    out.fill = { items: fill.items.map((i) => [i.id, i.mode, i.kind]), drafts: fill.drafts, credits: fill.expect_credits, examples: fill.examples.map((e) => [e.name, e.kind, e.source]), facts: fill.examples.every((e) => e.facts.seconds > 0) };
    // A change asked for in words: the picker's number at the press, and no examples (it starts from the sound's own patch).
    write('3 drafts, softer');
    await send();
    await until(() => api.posted('/jobs').length === 2);
    const change = api.posted('/jobs')[1];
    out.change = { items: change.items.map((i) => [i.id, i.mode, i.change, i.base.source]), drafts: change.drafts, credits: change.expect_credits, examples: change.examples, ask: $('ask').value, dial: dial() };
    """, before=SAVED)
    assert got["start"] == [2, "Drafts · 6 credits"]
    assert got["four"] == [4, "Drafts · 12 credits"] and got["three"] == [3, "Drafts · 9 credits"] and got["most"] == 4
    assert got["back"] == [2, "Drafts · 6 credits"] and got["byHand"] == [1, "Drafts · 3 credits"] and got["words"] == 3
    assert got["fill"] == {"items": [["sfx_hit", "make", "sfx"], ["sfx_block", "make", "sfx"], ["sfx_new", "make", "sfx"]], "drafts": 1, "credits": 3, "facts": True,
                           "examples": [["sfx_one", "sfx", "PATCH v-one"], ["sfx_two", "sfx", "PATCH v-two"], ["amb_wind", "amb", "PATCH v-wind"]]}
    assert got["change"] == {"items": [[i, "revise", "3 drafts, softer", "PATCH v-" + i[4:]] for i in ("sfx_one", "sfx_two", "sfx_three")], "drafts": 3, "credits": 9, "examples": [],
                             "ask": "", "dial": 2}


def test_only_a_count_moves_the_picker_and_a_draft_called_by_its_number_or_a_length_does_not():
    got = run_page(TOOLS + r"""
    await hand();
    pick('sfx_three'); setDial(1);
    const after = (w) => { write(w); return dial(); };
    out.counts = ['시안 3개', '시안을 2개로', '3개의 시안으로', '2가지 버전', '후보 3가지', '2 drafts of a soft bell', 'brighter, 2 drafts', '3 options please', '2 versions', '12 drafts', '시안 12개로'].map(after);
    // The room numbers the drafts of a sound 1 to 4, so one is talked about by its number. That, and a length, is no count.
    out.names = ['시안 2가 제일 좋아, 그걸 더 밝게', 'I like option 3, make it a bit longer', 'take draft 2 and soften it', 'make the draft 30 seconds long', '시안 30초 길이로', '0 drafts', 'softer'].map(after);
    out.label = seg();
    """, before=SAVED)
    assert got["counts"] == [3, 2, 3, 2, 3, 2, 2, 3, 2, 4, 4]          # more than four is four, and never the last digit of a longer number
    assert got["names"] == [1] * 7 and got["label"] == "Drafts · 1 credit"
    assert "(?<" not in read("app.js")                                   # no look-behind: older Safari does not read it


def test_a_count_the_picker_had_not_followed_at_the_press_waits_and_one_it_had_followed_starts():
    """Spec I: "시안 4개" in the words moves the picker to 4, and need is more than shown, so it is held. shown is the
    number beside the draft count at the press, read before the words move the picker."""
    got = run_page(TOOLS + AGENT + r"""
    await hand();
    const TEXT = '시안 4개로 더 밝게';
    pick('sfx_three'); setDial(2);
    // The words are in the box and the label has not followed them (they got there without the browser saying so).
    $('ask').value = TEXT;
    out.atPress = [seg(), dial()];
    await send();
    out.sent = [$('ask').value, agentAsked().length, api.posted('/jobs').length];
    // The assistant wants that one sound remade. Four drafts of it are 4 credits; 2 was showing.
    await answer('Remaking it.', [{ op: 'revise', assets: ['sfx_three'], text: '더 밝게' }]);
    out.held = { said: said(), ask: $('ask').value, picked: picked(), seg: seg(), dial: dial(), posts: api.posted('/jobs').length, status: statusOf('sfx_three') };
    // The same words and the same sound again: no assistant, four drafts.
    await send();
    await until(() => api.posted('/jobs').length === 1);
    let body = api.posted('/jobs')[0];
    out.direct = { agent: agentAsked().length, items: body.items.map((i) => [i.id, i.mode, i.change]), drafts: body.drafts, credits: body.expect_credits, ask: $('ask').value, dial: dial(), status: statusOf('sfx_three') };
    // Typed the way a browser reports it, the picker follows as the words are written: the label says 4 at the press,
    // so the same answer starts at once.
    pick('sfx_three'); pick('sfx_one');
    write(TEXT);
    out.typed = [seg(), dial(), picked()];
    await send();
    await answer('Remaking it.', [{ op: 'revise', assets: ['sfx_one'], text: '더 밝게' }]);
    await until(() => api.posted('/jobs').length === 2);
    body = api.posted('/jobs')[1];
    out.atOnce = { agent: agentAsked().length, items: body.items.map((i) => i.id), drafts: body.drafts, credits: body.expect_credits, said: said(), ask: $('ask').value };
    """, before=SAVED + HOST)
    text = "시안 4개로 더 밝게"
    assert got["atPress"] == ["Drafts · 2 credits", 2] and got["sent"] == ["", 1, 0]
    assert got["held"] == {"said": HELD_EN, "ask": text, "picked": ["sfx_three"], "seg": "Drafts · 4 credits", "dial": 4, "posts": 0, "status": ["draft"]}
    assert got["direct"] == {"agent": 1, "items": [["sfx_three", "revise", "더 밝게"]], "drafts": 4, "credits": 4, "ask": "", "dial": 2, "status": ["working"]}
    assert got["typed"] == ["Drafts · 4 credits", 4, ["sfx_one"]]
    assert got["atOnce"] == {"agent": 2, "items": ["sfx_one"], "drafts": 4, "credits": 4, "said": "Remaking it.", "ask": ""}


def test_the_picker_goes_by_the_box_in_front_so_the_label_at_a_press_is_never_less_than_what_is_asked_for():
    """Two boxes, one picker: the dock's and the open sound's. Words written in one must not leave the other's label on
    a number its own words do not ask for."""
    got = run_page(TOOLS + r"""
    await hand();
    const open = async (id) => { tileOf(id).focus(); key('Enter', tileOf(id)); await until(() => !!document.querySelector('.detailDock')); };
    const box = () => document.querySelector('.detailDock').querySelector('textarea');
    const inSound = () => [+document.querySelector('.dTools').querySelectorAll('[role=radio]').find((b) => b.getAttribute('aria-checked') === 'true').textContent, document.querySelector('.dTools .segLabel').textContent];
    const type = (text) => { box().value = text; box().oninput(); };
    pick('sfx_one', 'sfx_two'); setDial(1);
    write('3 drafts, softer');
    out.dock = [dial(), seg()];
    // Another sound is opened and something else is written there: its picker goes by those words.
    await open('sfx_three');
    out.opened = inSound();
    type('louder'); out.other = inSound();
    type('2 drafts, louder'); out.two = inSound();
    // Back on the board the dock's words are still there, and the picker is back on what they ask for.
    key('Escape'); await settle();
    out.back = { dial: dial(), seg: seg(), ask: $('ask').value, picked: picked() };
    await send();
    await until(() => api.posted('/jobs').length === 1);
    let body = api.posted('/jobs')[0];
    out.charged = { items: body.items.map((i) => i.id), drafts: body.drafts, credits: body.expect_credits, dial: dial() };
    // The sound again: the words written there are still in its box, and its picker follows them again.
    await open('sfx_three');
    out.again = [box().value, ...inSound()];
    document.querySelector('.detailDock').fire('submit');
    await until(() => api.posted('/jobs').length === 2);
    body = api.posted('/jobs')[1];
    out.fromSound = { items: body.items.map((i) => i.id), drafts: body.drafts, credits: body.expect_credits };
    // Afterwards the dock is empty: its picker is on the number picked by hand, which is also what is saved.
    key('Escape'); await settle();
    key('Escape'); pick('sfx_mine', 'amb_wind');
    out.after = { dial: dial(), seg: seg(), ask: $('ask').value, saved: localStorage.getItem('asset-drafts') };
    // A number picked by hand over the words of one box stands there until those words change, whatever the other box did.
    write('4 drafts, warmer'); setDial(2);
    await open('bgm_title'); type('3 drafts'); key('Escape'); await settle();
    out.byHand = [dial(), seg()];
    write('4 drafts, warmer and'); out.reworded = dial();
    """, before=SAVED)
    assert got["dock"] == [3, "Drafts · 6 credits"]
    assert got["opened"] == [1, "Drafts · 1 credit"] and got["other"] == [1, "Drafts · 1 credit"] and got["two"] == [2, "Drafts · 2 credits"]
    assert got["back"] == {"dial": 3, "seg": "Drafts · 6 credits", "ask": "3 drafts, softer", "picked": ["sfx_one", "sfx_two"]}
    assert got["charged"] == {"items": ["sfx_one", "sfx_two"], "drafts": 3, "credits": 6, "dial": 1}      # what the label said at the press
    assert got["again"] == ["2 drafts, louder", 2, "Drafts · 2 credits"]
    assert got["fromSound"] == {"items": ["sfx_three"], "drafts": 2, "credits": 2}
    assert got["after"] == {"dial": 1, "seg": "Drafts · 2 credits", "ask": "", "saved": "1"}
    assert got["byHand"] == [2, "Drafts · 4 credits"] and got["reworded"] == 4


def test_in_the_open_sound_a_count_the_picker_had_not_followed_at_the_press_starts_nothing_until_it_is_sent_again():
    got = run_page(TOOLS + r"""
    await hand();
    setDial(1);
    tileOf('sfx_three').focus(); key('Enter', tileOf('sfx_three'));
    await until(() => !!document.querySelector('.detailDock'));
    const box = () => document.querySelector('.detailDock').querySelector('textarea'), label = () => document.querySelector('.dTools .segLabel').textContent;
    box().value = '4 drafts, brighter';                                   // in the box without the browser saying so
    out.atPress = label();
    document.querySelector('.detailDock').fire('submit');
    await settle(); await advance(0);
    out.first = { said: said(), posts: api.posted('/jobs').length, label: label(), words: box().value };
    document.querySelector('.detailDock').fire('submit');
    await until(() => api.posted('/jobs').length === 1);
    out.second = { drafts: api.posted('/jobs')[0].drafts, credits: api.posted('/jobs')[0].expect_credits };
    """, before=SAVED)
    assert got["atPress"] == "Drafts · 1 credit"
    assert got["first"] == {"said": HELD_EN, "posts": 0, "label": "Drafts · 4 credits", "words": "4 drafts, brighter"}
    assert got["second"] == {"drafts": 4, "credits": 4}


def test_an_answer_over_the_number_is_held_then_made_without_the_assistant_and_three_sounds_end_one_by_one():
    got = run_page(TOOLS + AGENT + r"""
    await hand();
    const THREE = ['sfx_one', 'sfx_two', 'sfx_three'];
    // One sound picked, two drafts. "시안 4개" in the words moves the picker to 4: the label says 4 credits.
    pick('sfx_three'); setDial(2);
    out.start = [seg(), dial()];
    write('시안 4개로 더 밝게');
    out.typed = [seg(), dial()];
    await send();
    out.sent = [$('ask').value, dial(), agentAsked().length, agentAsked()[0].payload.text, agentAsked()[0].payload.state.selected];
    // The assistant wants three sounds remade, and renames one. 3 x 4 = 12 is more than the 4 that was showing.
    await answer('Remaking three sounds.', [{ op: 'rename', assets: ['sfx_two'], name: 'Two' }, { op: 'revise', assets: THREE, text: '더 밝게' }]);
    out.held = { said: said(), undo: !!$('toast').querySelector('button'), ask: $('ask').value, picked: picked(), seg: seg(), dial: dial(), posts: api.posted('/jobs').length, status: statusOf(...THREE),
      renamed: tileOf('sfx_two').querySelector('.name').textContent };
    // The toast goes, and another one comes: the request still waits.
    await advance(9000);
    out.quiet = [said(), $('ask').value, picked(), seg()];
    await trash('sfx_new');
    out.other = [said(), $('ask').value, picked(), seg()];
    // Sent again as it is: the assistant is not asked a second time, and the three are made in four drafts, each
    // changed in the words the assistant gave, not in the sentence that was typed.
    await send();
    await until(() => api.posted('/jobs').length === 1);
    const body = api.posted('/jobs')[0];
    out.direct = { agent: agentAsked().length, items: body.items.map((i) => [i.id, i.mode, i.change]), drafts: body.drafts, credits: body.expect_credits, ask: $('ask').value, dial: dial(), status: statusOf(...THREE), said: said() };
    // The same words once more go to the assistant: nothing waits any longer.
    write('시안 4개로 더 밝게'); await send();
    out.asksAgain = agentAsked().length;
    await answer('They are being made.', []);
    // The three end one by one, and each waits for its own pick.
    const jobsOf = (id) => [...api.jobs.values()].filter((j) => j.ref === 'k-' + id).map((j) => j.id);
    out.turns = [];
    for (const id of ['sfx_two', 'sfx_one', 'sfx_three']) {
      jobsOf(id).forEach((j) => api.finish(j));
      await advance(1500);
      await until(() => tileOf(id).dataset.status === 'review');
      out.turns.push(statusOf(...THREE));
    }
    out.picks = THREE.map(picksOf);
    out.jobs = THREE.map((id) => jobsOf(id).length);
    """, before=SAVED + HOST)
    text = "시안 4개로 더 밝게"
    assert got["start"] == ["Drafts · 2 credits", 2] and got["typed"] == ["Drafts · 4 credits", 4]
    assert got["sent"] == ["", 2, 1, text, ["sfx_three"]]
    # nothing started: the three are picked, the words are back, the label says what it costs, and the rename can be undone
    assert got["held"] == {"said": HELD_EN + " Undo", "undo": True, "ask": text, "picked": ["sfx_one", "sfx_three", "sfx_two"], "seg": "Drafts · 12 credits", "dial": 4, "posts": 0,
                           "status": ["approved", "approved", "draft"], "renamed": "Two"}
    assert got["quiet"] == [None, text, ["sfx_one", "sfx_three", "sfx_two"], "Drafts · 12 credits"]
    assert got["other"] == ["Moved 1 to the trash", text, ["sfx_one", "sfx_three", "sfx_two"], "Drafts · 12 credits"]
    assert got["direct"] == {"agent": 1, "items": [[i, "revise", "더 밝게"] for i in ("sfx_one", "sfx_two", "sfx_three")], "drafts": 4, "credits": 12, "ask": "", "dial": 2,
                             "status": ["working"] * 3, "said": None}
    assert got["asksAgain"] == 2
    assert got["turns"] == [["working", "review", "working"], ["review", "review", "working"], ["review", "review", "review"]]
    assert got["picks"] == [["Previous", "1", "2", "3", "4"]] * 3 and got["jobs"] == [4, 4, 4]


def test_a_held_request_is_let_go_by_other_sounds_or_other_words_and_a_free_session_is_never_held():
    got = run_page(TOOLS + AGENT + r"""
    await hand();
    const HELD = """ + json.dumps(HELD_EN) + r""";
    // One made sound picked; the assistant also wants two empty slots made: 3 credits is more than the 1 showing.
    pick('sfx_three');
    write('make these brighter'); await send();
    await answer('Making three.', [{ op: 'revise', assets: ['sfx_three', 'sfx_hit', 'sfx_block'], text: 'brighter' }]);
    await advance(600);                                                   // the board is saved as it is now
    await until(() => (disk.stores.get('board').get('board').agentLog || []).length === 2);
    out.held = [said(), picked(), seg(), api.posted('/jobs').length, onDisk('sfx_hit').description ?? null, onDisk('sfx_hit').chat.length, statusOf('sfx_three', 'sfx_hit', 'sfx_block')];
    // Other sounds picked let it go: the same words are a new question to the assistant.
    pick('sfx_block');
    out.fewer = seg();
    await send();
    out.letGo = [agentAsked().length, api.posted('/jobs').length, $('ask').value];
    // Two are picked now, and the assistant wants the three again: held again.
    await answer('Making three.', [{ op: 'revise', assets: ['sfx_three', 'sfx_hit', 'sfx_block'], text: 'brighter' }]);
    out.heldAgain = [said(), picked(), $('ask').value];
    // Other words let it go too. The three are picked now, so this time the answer costs what the label shows and starts,
    // in the words the assistant gave each action.
    write('make these much brighter');
    await send();
    out.reworded = agentAsked().length;
    await answer('Making three.', [{ op: 'revise', assets: ['sfx_three'], text: 'much brighter' }, { op: 'revise', assets: ['sfx_hit', 'sfx_block'], text: 'a bright hit' }]);
    await until(() => api.posted('/jobs').length === 2);
    out.started = { said: said(), posts: api.posted('/jobs').map((b) => [b.items.map((i) => [i.id, i.mode, i.mode === 'revise' ? i.change : i.description]), b.drafts, b.expect_credits]), status: statusOf('sfx_three', 'sfx_hit', 'sfx_block'), ask: $('ask').value };
    // A session that pays nothing: the answer wants more sounds than were picked, and they start at once.
    api.free = true; api.unit = 0;
    await hand('pw', 'pw:room');
    key('Escape'); pick('sfx_one');                                       // Escape lets every picked sound go
    out.freeSeg = [seg(), picked()];
    write('louder'); await send();
    await answer('Remaking two.', [{ op: 'revise', assets: ['sfx_one', 'sfx_two'], text: 'louder' }]);
    await until(() => api.posted('/jobs').length === 3);
    out.free = { said: said(), items: api.posted('/jobs')[2].items.map((i) => i.id), credits: api.posted('/jobs')[2].expect_credits, ask: $('ask').value };
    """, before=SAVED + HOST)
    three = ["sfx_block", "sfx_hit", "sfx_three"]
    # held: the empty slots are as they were (not described, nothing in their conversation), and nothing is working
    assert got["held"] == [HELD_EN, three, "Drafts · 3 credits", 0, None, 0, ["draft", "pending", "pending"]]
    assert got["fewer"] == "Drafts · 2 credits" and got["letGo"] == [2, 0, ""]
    assert got["heldAgain"] == [HELD_EN, three, "make these brighter"]
    assert got["reworded"] == 3
    assert got["started"] == {"said": "Making three.", "ask": "", "status": ["working"] * 3,
                              "posts": [[[["sfx_three", "revise", "much brighter"]], 1, 1], [[["sfx_hit", "make", "a bright hit"], ["sfx_block", "make", "a bright hit"]], 1, 2]]}
    assert got["freeSeg"] == ["Drafts", ["sfx_one"]]
    assert got["free"] == {"said": "Remaking two.", "items": ["sfx_one", "sfx_two"], "credits": 0, "ask": ""}


# The empty slots carry the descriptions of the plan they came from.
PLANNED = r"""
BOARD.assets.find((a) => a.id === 'sfx_hit').description = 'Sword hit, combat, short and dry';
BOARD.assets.find((a) => a.id === 'sfx_block').description = 'Shield block, a dull thud';
"""


def test_a_held_request_sent_again_is_made_in_the_words_of_the_answer_and_never_from_the_sentence_in_the_box():
    got = run_page(TOOLS + AGENT + r"""
    await hand();
    const described = () => ['sfx_hit', 'sfx_block', 'sfx_new'].map((id) => onDisk(id).description ?? null);
    // Nothing is picked: the label has no number, so whatever the answer wants made waits.
    out.before = [seg(), picked()];
    write('fill in the empty ones, and brighten three'); await send();
    await answer('Making four.', [
      { op: 'describe', assets: ['sfx_new'], text: 'a soft confirm blip' },
      { op: 'revise', assets: ['sfx_three'], text: 'a touch brighter' },
      { op: 'revise', assets: ['sfx_hit'], text: 'heavy sword on metal, short, dry' },
      { op: 'revise', assets: ['sfx_block', 'sfx_new'], text: '' }]);
    await advance(600);
    await until(() => onDisk('sfx_new').description === 'a soft confirm blip');
    out.held = { said: said(), picked: picked(), seg: seg(), posts: api.posted('/jobs').length, described: described(), chat: onDisk('sfx_hit').chat.length };
    // Sent again as it is. Each sound is asked for in the words the answer gave its action; an action without words
    // makes its slots from the descriptions they have. The change is one request and the new sounds are another.
    await send();
    await until(() => api.posted('/jobs').length === 2);
    await settle(); await advance(0); await settle();
    out.posts = api.posted('/jobs').map((b) => [b.items.map((i) => [i.id, i.mode, i.mode === 'revise' ? i.change : i.description]), b.drafts, b.expect_credits]);
    out.agent = agentAsked().length;
    await advance(600);
    await until(() => onDisk('sfx_hit').status === 'working' && onDisk('sfx_new').status === 'working');
    out.after = { described: described(), three: onDisk('sfx_three').description ?? null, ask: $('ask').value, status: statusOf('sfx_three', 'sfx_hit', 'sfx_block', 'sfx_new') };
    const sentence = JSON.stringify(api.posted('/jobs')).includes('fill in the empty ones');
    out.sentence = [sentence, JSON.stringify(disk.stores.get('board').get('board').assets.map((a) => [a.description, a.chat])).includes('fill in the empty ones')];
    """, before=SAVED + PLANNED + HOST)
    four = ["sfx_block", "sfx_hit", "sfx_new", "sfx_three"]
    assert got["before"] == ["Drafts", []]
    assert got["held"] == {"said": HELD_EN + " Undo", "picked": four, "seg": "Drafts · 4 credits", "posts": 0, "chat": 0,
                           "described": ["Sword hit, combat, short and dry", "Shield block, a dull thud", "a soft confirm blip"]}
    assert got["posts"] == [[[["sfx_three", "revise", "a touch brighter"]], 1, 1],
                            [[["sfx_hit", "make", "heavy sword on metal, short, dry"], ["sfx_block", "make", "Shield block, a dull thud"],
                              ["sfx_new", "make", "a soft confirm blip"]], 1, 3]]
    assert got["agent"] == 1
    # the plan's description stands where the answer gave no words, and the user's sentence is nowhere in what was sent or saved
    assert got["after"] == {"described": ["heavy sword on metal, short, dry", "Shield block, a dull thud", "a soft confirm blip"], "three": None, "ask": "", "status": ["working"] * 4}
    assert got["sentence"] == [False, False]


# Nine more empty slots: with the three of the board, twelve sounds that are not made yet.
MANY = r"""
for (let i = 1; i <= 9; i++) BOARD.assets.push(onBoard('sfx_slot' + i, 'ui', 'pending'));
"""


def test_an_answer_that_changes_many_sounds_one_by_one_is_one_request_for_the_changes_and_one_for_the_new_sounds():
    """The API takes ten requests a minute from a session. An answer with an action for every sound (seventeen here)
    must not be seventeen requests: the changes go out together and the new sounds together, each sound with the
    words of its own action, so none of them is turned away for asking too often."""
    got = run_page(TOOLS + AGENT + r"""
    api.free = true; api.unit = 0;
    await hand('pw', 'pw:room');
    const MADE = ['amb_wind', 'bgm_title', 'sfx_one', 'sfx_two', 'sfx_three'], EMPTY = ['sfx_hit', 'sfx_block', 'sfx_new', ...Array.from({ length: 9 }, (_, i) => 'sfx_slot' + (i + 1))];
    // As the API does: the eleventh request of a minute is turned away.
    let posts = 0;
    api.hook = (call, h) => (call.method === 'POST' && call.path === '/jobs' && ++posts > 10 ? h.err(429, 'rate', { retry_after: 40 }, { 'Retry-After': '40' }) : null);
    write('make every sound fit its name'); await send();
    await answer('Making them.', [...MADE, ...EMPTY].map((id) => ({ op: 'revise', assets: [id], text: 'words for ' + id })));
    await until(() => api.posted('/jobs').length >= 2);
    await settle(); await advance(0); await settle();
    out.posts = api.posted('/jobs').map((b) => [[...new Set(b.items.map((i) => i.mode))], b.items.map((i) => i.id), b.drafts]);
    out.words = api.posted('/jobs').flatMap((b) => b.items).every((i) => (i.mode === 'revise' ? i.change : i.description) === 'words for ' + i.id);
    out.status = [...new Set(statusOf(...MADE, ...EMPTY))];
    out.said = said();
    out.kept = EMPTY.every((id) => onDisk(id).description === 'words for ' + id) && [...MADE, ...EMPTY].every((id) => onDisk(id).chat.some((c) => c.me && c.text === 'words for ' + id));
    """, before=SAVED + MANY + HOST)
    assert got["posts"] == [[["revise"], ["amb_wind", "bgm_title", "sfx_one", "sfx_two", "sfx_three"], 1],
                            [["make"], ["sfx_hit", "sfx_block", "sfx_new"] + ["sfx_slot%d" % i for i in range(1, 10)], 1]]
    assert got["words"] is True and got["status"] == ["working"] and got["said"] == "Making them." and got["kept"] is True


def test_undo_on_a_held_answer_puts_its_other_changes_back_and_the_request_goes_on_waiting():
    got = run_page(TOOLS + AGENT + r"""
    await hand();
    const THREE = ['sfx_one', 'sfx_two', 'sfx_three'], name = (id) => tileOf(id).querySelector('.name').textContent;
    pick('sfx_three'); setDial(2);
    write('brighter'); await send();
    await answer('Remaking three.', [{ op: 'rename', assets: ['sfx_two'], name: 'Two' }, { op: 'revise', assets: THREE, text: 'brighter, all three' }]);
    out.held = [said(), picked(), seg(), name('sfx_two')];
    $('toast').querySelector('button').click();                           // undo
    await settle();
    // The rename is put back. The sounds stay picked and the words stay in the box: the toast said to send them as they are.
    out.undone = [said(), picked(), seg(), $('ask').value, name('sfx_two')];
    await send();
    await until(() => api.posted('/jobs').length === 1);
    const body = api.posted('/jobs')[0];
    out.direct = { agent: agentAsked().length, items: body.items.map((i) => [i.id, i.change]), drafts: body.drafts, credits: body.expect_credits };
    """, before=SAVED + HOST)
    three = ["sfx_one", "sfx_three", "sfx_two"]
    assert got["held"] == [HELD_EN + " Undo", three, "Drafts · 6 credits", "Two"]
    assert got["undone"] == ["Undone", three, "Drafts · 6 credits", "brighter", "sfx_two"]
    assert got["direct"] == {"agent": 1, "items": [[i, "brighter, all three"] for i in ("sfx_one", "sfx_two", "sfx_three")], "drafts": 2, "credits": 6}


def test_what_was_written_and_picked_while_the_assistant_was_thinking_is_left_alone_when_its_answer_costs_too_much():
    got = run_page(TOOLS + AGENT + r"""
    await hand();
    pick('sfx_three');
    write('make these brighter'); await send();
    // The assistant is still thinking: other words are written and another sound is picked.
    write('note: keep the tail short');
    pick('sfx_one');
    out.meanwhile = [$('ask').value, picked(), seg()];
    await answer('Making three.', [{ op: 'rename', assets: ['sfx_two'], name: 'Two' }, { op: 'revise', assets: ['sfx_three', 'sfx_hit', 'sfx_block'], text: 'brighter' }]);
    out.after = { ask: $('ask').value, picked: picked(), seg: seg(), said: said(), posts: api.posted('/jobs').length, status: statusOf('sfx_three', 'sfx_hit', 'sfx_block'), renamed: tileOf('sfx_two').querySelector('.name').textContent };
    // Nothing waits: the words in the box are a question of their own.
    await send();
    out.next = [agentAsked().length, agentAsked().at(-1).payload.text, agentAsked().at(-1).payload.state.selected, api.posted('/jobs').length];
    """, before=SAVED + HOST)
    over = "That takes more credits than the number that was showing, so nothing has started. What you wrote and picked since then is as you left it. Ask for those sounds again whenever you want them."
    assert got["meanwhile"] == ["note: keep the tail short", ["sfx_one", "sfx_three"], "Drafts · 2 credits"]
    assert got["after"] == {"ask": "note: keep the tail short", "picked": ["sfx_one", "sfx_three"], "seg": "Drafts · 2 credits", "said": over + " Undo", "posts": 0,
                            "status": ["draft", "pending", "pending"], "renamed": "Two"}
    assert got["next"] == [2, "note: keep the tail short", ["sfx_three", "sfx_one"], 0]


def test_a_held_request_whose_sounds_were_started_another_way_is_let_go_and_what_is_left_of_one_is_made():
    got = run_page(TOOLS + AGENT + r"""
    await hand();
    // Nothing picked; the answer wants the two empty combat slots made, and waits.
    write('make the empty combat ones'); await send();
    await answer('Making two.', [{ op: 'revise', assets: ['sfx_hit', 'sfx_block'], text: 'combat hits' }]);
    out.held = [said(), picked(), seg(), $('ask').value];
    // The button makes every empty slot, those two among them: nothing of the request is left to make.
    $('fillBtn').click();
    await until(() => api.posted('/jobs').length === 1);
    await settle(); await advance(0);
    out.filled = [statusOf('sfx_hit', 'sfx_block'), picked(), $('ask').value];
    await send();
    out.asked = { agent: agentAsked().length, text: agentAsked().at(-1).payload.text, posts: api.posted('/jobs').length, ask: $('ask').value, said: said() };
    await answer('They are already being made.', []);
    // A request of which one sound was started another way: the rest of it is made when it is sent again.
    key('Escape'); pick('sfx_one');
    write('all three softer'); await send();
    await answer('Remaking three.', [{ op: 'revise', assets: ['sfx_one', 'sfx_two', 'sfx_three'], text: 'softer' }]);
    out.heldAgain = [said(), picked(), seg()];
    tileOf('sfx_two').focus(); key('Enter', tileOf('sfx_two'));
    await until(() => !!document.querySelector('.detailDock'));
    const box = document.querySelector('.detailDock').querySelector('textarea');
    box.value = 'rounder'; box.oninput();
    document.querySelector('.detailDock').fire('submit');
    await until(() => api.posted('/jobs').length === 2);
    key('Escape'); await settle();
    out.partly = [statusOf('sfx_one', 'sfx_two', 'sfx_three'), picked(), $('ask').value, seg()];
    await send();
    await until(() => api.posted('/jobs').length === 3);
    const body = api.posted('/jobs')[2];
    out.rest = { agent: agentAsked().length, items: body.items.map((i) => [i.id, i.change]), credits: body.expect_credits, ask: $('ask').value };
    """, before=SAVED + HOST)
    assert got["held"] == [HELD_EN, ["sfx_block", "sfx_hit"], "Drafts · 2 credits", "make the empty combat ones"]
    assert got["filled"] == [["working", "working"], ["sfx_block", "sfx_hit"], "make the empty combat ones"]
    # sent again, it is a new question: the words are not swallowed and nothing is asked for twice
    assert got["asked"] == {"agent": 2, "text": "make the empty combat ones", "posts": 1, "ask": "", "said": "Thinking…"}
    assert got["heldAgain"] == [HELD_EN, ["sfx_one", "sfx_three", "sfx_two"], "Drafts · 3 credits"]
    assert got["partly"] == [["approved", "working", "draft"], ["sfx_one", "sfx_three", "sfx_two"], "all three softer", "Drafts · 3 credits"]
    assert got["rest"] == {"agent": 3, "items": [["sfx_one", "softer"], ["sfx_three", "softer"]], "credits": 2, "ask": ""}


def test_a_held_request_still_shows_what_it_takes_after_words_were_written_in_an_open_sound():
    got = run_page(TOOLS + AGENT + r"""
    await hand();
    pick('sfx_three'); setDial(2);
    write('시안 4개로 더 밝게'); await send();
    await answer('Remaking three.', [{ op: 'revise', assets: ['sfx_one', 'sfx_two', 'sfx_three'], text: '더 밝게' }]);
    out.held = [seg(), dial()];
    // Another sound is opened and something is written there: in that view the picker goes by those words.
    tileOf('amb_wind').focus(); key('Enter', tileOf('amb_wind'));
    await until(() => !!document.querySelector('.detailDock'));
    const box = document.querySelector('.detailDock').querySelector('textarea');
    box.value = 'calmer'; box.oninput();
    out.inSound = document.querySelector('.dTools .segLabel').textContent;
    // Back on the board the request still waits, and the label is back on what it takes: that is what sending it costs.
    key('Escape'); await settle();
    out.back = [seg(), dial(), $('ask').value, picked()];
    await send();
    await until(() => api.posted('/jobs').length === 1);
    out.charged = [api.posted('/jobs')[0].drafts, api.posted('/jobs')[0].expect_credits, agentAsked().length];
    // A number picked by hand while it waits is the number it is made in, and the label says so before the press.
    key('Escape'); pick('sfx_mine');
    write('two more like it'); await send();
    await answer('Making two.', [{ op: 'revise', assets: ['sfx_hit', 'sfx_block'], text: 'like it' }]);
    setDial(3);
    out.byHand = [seg(), dial(), picked()];
    await send();
    await until(() => api.posted('/jobs').length === 2);
    out.made = [api.posted('/jobs')[1].drafts, api.posted('/jobs')[1].expect_credits, agentAsked().length];
    """, before=SAVED + HOST)
    assert got["held"] == ["Drafts · 12 credits", 4] and got["inSound"] == "Drafts · 2 credits"
    assert got["back"] == ["Drafts · 12 credits", 4, "시안 4개로 더 밝게", ["sfx_one", "sfx_three", "sfx_two"]]
    assert got["charged"] == [4, 12, 1]
    assert got["byHand"] == ["Drafts · 6 credits", 3, ["sfx_block", "sfx_hit"]] and got["made"] == [3, 6, 2]


def test_undoing_an_answer_leaves_a_sound_that_is_being_made_exactly_as_its_job_was_asked():
    got = run_page(TOOLS + AGENT + r"""
    await hand();
    pick('sfx_three'); setDial(2);
    write('warmer'); await send();
    await answer('Renamed them, and remaking it warmer.', [{ op: 'rename', assets: ['sfx_three'], name: 'Warm three' }, { op: 'describe', assets: ['sfx_three'], text: 'a warm one' },
      { op: 'rename', assets: ['sfx_two'], name: 'Two' }, { op: 'describe', assets: ['sfx_two'], text: 'the second' }, { op: 'revise', assets: ['sfx_three'], text: 'warmer' }]);
    await until(() => api.posted('/jobs').length === 1);
    const name = (id = 'sfx_three') => tileOf(id).querySelector('.name').textContent;
    out.asked = [statusOf('sfx_three'), name(), name('sfx_two'), said()];
    // The first of its two drafts arrives while it is still being made.
    api.finish('job1');
    await advance(1500);
    await until(() => onDisk('sfx_three').drafts.length === 1 && onDisk('sfx_three').work.jobs[0].got);
    out.before = [onDisk('sfx_three').name, onDisk('sfx_three').description, onDisk('sfx_two').name, onDisk('sfx_two').description, !!$('toast').querySelector('button')];
    $('toast').querySelector('button').click();                           // undo
    await advance(600);
    await until(() => onDisk('sfx_two').name === 'sfx_two');
    const kept = onDisk('sfx_three');
    // The sound that is not being made is as it was. The one that is being made keeps the name and the description
    // its job was asked with, and its job, its draft and its status.
    out.undone = { said: said(), two: [name('sfx_two'), onDisk('sfx_two').description ?? null], name: name(), saved: kept.name, tile: statusOf('sfx_three'), bar: !!tileOf('sfx_three').querySelector('.bar'), status: kept.status,
      description: kept.description ?? null, drafts: kept.drafts.map((v) => v.id), jobs: kept.work.jobs.map((j) => [j.id, j.got]), cancels: api.posted('/jobs/cancel').length };
    // The second draft comes as it would have: the sound waits for a pick between both.
    api.finish('job2');
    await advance(1500);
    await until(() => tileOf('sfx_three').dataset.status === 'review');
    out.came = [picksOf('sfx_three'), name()];
    """, before=SAVED + HOST)
    assert got["asked"] == [["working"], "Warm three", "Two", "Renamed them, and remaking it warmer. Undo"]
    assert got["before"] == ["Warm three", "a warm one", "Two", "the second", True]
    assert got["undone"] == {"said": "Undone", "two": ["sfx_two", None], "name": "Warm three", "saved": "Warm three", "tile": ["working"], "bar": True, "status": "working",
                             "description": "a warm one", "drafts": ["job1"], "jobs": [["job1", True], ["job2", False]], "cancels": 0}
    assert got["came"] == [["Previous", "1", "2"], "Warm three"]


def test_undoing_an_answer_that_moved_a_slot_into_a_new_group_and_started_it_leaves_the_slot_and_its_group():
    got = run_page(TOOLS + AGENT + r"""
    await hand();
    pick('sfx_hit');
    write('make this the title jingle'); await send();
    await answer('Moved it and making it.', [{ op: 'add_cat', cat: 'jingles', name: 'Jingles', kind: 'music' }, { op: 'add_cat', cat: 'stings', name: 'Stings', kind: 'sfx' },
      { op: 'move', assets: ['sfx_hit'], cat: 'jingles' }, { op: 'move', assets: ['sfx_block'], cat: 'stings' }, { op: 'revise', assets: ['sfx_hit'], text: 'a calm title jingle' }]);
    await until(() => api.posted('/jobs').length === 1);
    const item = api.posted('/jobs')[0].items[0];
    out.asked = [item.id, item.kind, item.loop, item.description, statusOf('sfx_hit')];
    const groupOf = (id) => tileOf(id).closest('.group').dataset.cat;
    out.moved = [groupOf('sfx_hit'), groupOf('sfx_block')];
    $('toast').querySelector('button').click();                           // undo
    await advance(600);
    await until(() => onDisk('sfx_block').cat === 'combat');
    const hit = onDisk('sfx_hit');
    // What was charged for is a looping music draft called "a calm title jingle": the slot it comes back to still says so.
    out.undone = { cat: hit.cat, music: hit.music, loop: hit.loop, description: hit.description ?? null, status: hit.status, work: !!hit.work, group: groupOf('sfx_hit'),
      block: [onDisk('sfx_block').cat, groupOf('sfx_block')], groups: disk.stores.get('board').get('board').cats.map((c) => c.id).filter((id) => id === 'jingles' || id === 'stings') };
    """, before=SAVED + HOST)
    assert got["asked"] == ["sfx_hit", "music", True, "a calm title jingle", ["working"]] and got["moved"] == ["jingles", "stings"]
    assert got["undone"] == {"cat": "jingles", "music": True, "loop": True, "description": "a calm title jingle", "status": "working", "work": True, "group": "jingles",
                             "block": ["combat", "combat"], "groups": ["jingles"]}


def test_nothing_is_asked_for_while_what_a_draft_costs_has_not_come_and_no_label_can_say_it():
    """The first read of the price fails. An account's labels then carry no number, as a free session's do; the room
    starts nothing from a button, through the assistant or in an open sound until a price has been read. gen.js reads
    it again by itself ten seconds on: the numbers show and the button works, with no reload and no other token."""
    got = run_page(TOOLS + AGENT + r"""
    const NO_PRICE = 'What a draft costs has not come through yet, so nothing has started. Ask again in a moment. Reloading the page reads the price again too.';
    let failed = 0;
    api.hook = (call, { err }) => (call.path.startsWith('/quote') && failed++ === 0 ? err(503, 'busy') : null);
    tell({ type: 'asset:token', token: tokenOf('acct', 'acct:me'), ttl: 900, api: BASE });
    await until(() => quotes() === 1); await settle(); await advance(0);
    pick('sfx_three');
    out.labels = [seg(), $('fillBtn').textContent, numbered()];
    $('fillBtn').click();
    await settle(); await advance(0);
    out.button = [said() === NO_PRICE, api.posted('/jobs').length, statusOf('sfx_hit', 'sfx_block', 'sfx_new')];
    // Through the assistant: what the answer changes is done, the sound is not started, and the toast says why.
    write('brighter'); await send();
    await answer('Remaking it.', [{ op: 'rename', assets: ['sfx_two'], name: 'Two' }, { op: 'revise', assets: ['sfx_three'], text: 'brighter' }]);
    out.agent = [said() === NO_PRICE + ' Undo', api.posted('/jobs').length, statusOf('sfx_three'), tileOf('sfx_two').querySelector('.name').textContent];
    // In the open sound.
    tileOf('sfx_three').focus(); key('Enter', tileOf('sfx_three'));
    await until(() => !!document.querySelector('.detailDock'));
    const box = document.querySelector('.detailDock').querySelector('textarea');
    box.value = 'brighter'; box.oninput();
    document.querySelector('.detailDock').fire('submit');
    await settle(); await advance(0);
    out.sound = [said() === NO_PRICE, api.posted('/jobs').length, statusOf('sfx_three')];
    key('Escape'); await settle();
    out.asked = [quotes(), api.paths().filter((p) => p.startsWith('POST')).length];
    // Ten seconds after the read that failed the price is read again. The labels say the number where they stand
    // (the open sound's too), and the same button now makes the sounds.
    tileOf('sfx_hit').focus(); key('Enter', tileOf('sfx_hit'));
    await until(() => !!$('makeOne'));
    out.waiting = [$('makeOne').textContent, document.querySelector('.dTools .segLabel').textContent];
    await advance(10000);
    await until(() => quotes() === 2); await settle();
    out.healed = [$('makeOne').textContent, document.querySelector('.dTools .segLabel').textContent, quotes()];
    key('Escape'); await settle();
    out.priced = [seg(), $('fillBtn').textContent];
    $('fillBtn').click();
    await until(() => api.posted('/jobs').length === 1);
    out.made = [api.posted('/jobs')[0].items.length, api.posted('/jobs')[0].expect_credits, said() === NO_PRICE];
    await advance(60000);
    out.quiet = quotes();
    """, before=SAVED + HOST)
    assert got["labels"] == ["Drafts", "Make all", []]
    assert got["button"] == [True, 0, ["pending"] * 3]
    assert got["agent"] == [True, 0, ["draft"], "Two"]
    assert got["sound"] == [True, 0, ["draft"]]
    assert got["asked"] == [1, 0]
    assert got["waiting"] == ["Make it", "Drafts"] and got["healed"] == ["Make it · 1 credit", "Drafts · 1 credit", 2]
    assert got["priced"] == ["Drafts · 1 credit", "Make all · 3 credits"] and got["made"] == [3, 3, False] and got["quiet"] == 2


def test_a_room_whose_price_reads_no_api_answers_says_that_making_sounds_is_not_connected():
    """Where no API is behind the address, another server's page comes back to every read of the price. The first
    requests are told that the price has not come. After three such reads the room no longer asks to try again in a
    moment: it says that making sounds is not connected, from a button and through the assistant. The reads go on, and
    once the API is there the same button makes the sounds."""
    got = run_page(TOOLS + AGENT + r"""
    const NO_PRICE = 'What a draft costs has not come through yet, so nothing has started. Ask again in a moment. Reloading the page reads the price again too.';
    const NO_LINK = 'Making sounds is not connected right now, so nothing has started. Everything else here works as usual.';
    let there = false;
    api.hook = (call, { res }) => (call.path.startsWith('/quote') && !there ? res(200) : null);      // 200 and not JSON
    const press = async () => { $('fillBtn').click(); await settle(); await advance(0); };
    tell({ type: 'asset:token', token: tokenOf('acct', 'acct:me'), ttl: 900, api: BASE });
    await until(() => quotes() === 1); await settle(); await advance(0);
    await press();
    out.first = [said() === NO_PRICE, api.posted('/jobs').length];
    await advance(10000); await until(() => quotes() === 2); await settle();
    await press();
    out.second = said() === NO_PRICE;
    await advance(10000); await until(() => quotes() === 3); await settle();
    await press();
    out.third = [said() === NO_LINK, api.posted('/jobs').length, statusOf('sfx_hit', 'sfx_block', 'sfx_new')];
    write('brighter'); await send();
    await answer('Remaking it.', [{ op: 'revise', assets: ['sfx_three'], text: 'brighter' }]);
    out.agent = [said() === NO_LINK, api.posted('/jobs').length, statusOf('sfx_three')];
    there = true;
    await advance(10000); await until(() => quotes() === 4); await settle();
    out.back = $('fillBtn').textContent;
    $('fillBtn').click();
    await until(() => api.posted('/jobs').length === 1);
    out.made = [api.posted('/jobs')[0].items.length, said() === NO_LINK, said() === NO_PRICE];
    """, before=SAVED + HOST)
    assert got["first"] == [True, 0] and got["second"] is True
    assert got["third"] == [True, 0, ["pending"] * 3]
    assert got["agent"] == [True, 0, ["draft"]]
    assert got["back"] == "Make all · 3 credits" and got["made"] == [3, False, False]


# ---------- read from the files ----------

def test_the_page_loads_quote_js_between_the_generator_and_the_page_and_keeps_the_stamps():
    html = read("index.html")
    names = scripts()
    assert names == ["data.js", "synth.js", "importer.js", "godot.js", "refs.js", "measure.js", "store.js", "gen.js", "quote.js", "app.js"]
    # every script is named once, in a whole tag. tools/stamp_assets.py writes a ?v= stamp into each; a tag is right
    # with one (ten hex digits) and without one, and so is the stylesheet's
    for name in names:
        assert len(re.findall(r'<script src="%s(?:\?v=[0-9a-f]{10})?"></script>' % re.escape(name), html)) == 1, name
    assert html.count("<script") == len(names)
    assert len(re.findall(r'href="style\.css(?:\?v=[0-9a-f]{10})?"', html)) == 1
    quote = read("quote.js")
    assert "root.assetQuote = api" in quote and "module.exports = api" in quote                # UMD, as store.js and gen.js
    for outside in ("document", "fetch(", "localStorage", "indexedDB", "setTimeout"):       # it touches neither the page nor the network
        assert outside not in quote, outside


def test_the_words_are_in_both_languages_and_only_the_five_labels_are_priced():
    app = read("app.js")
    for key in ("agentHeld:", "agentOver:", "noPrice:", "noLink:", "withCredits:"):
        assert app.count(key) == 2, key
    # the Korean lines are in the voice of the rest of that table, not in polite speech, and no line hurries anyone
    for key in ("agentHeld", "agentOver", "noPrice", "noLink"):
        en, ko = re.findall(r"%s: '([^']+)'" % key, app)
        assert re.search("[A-Za-z]", en) and not re.search("[가-힣]", en), en
        assert re.search("[가-힣]", ko) and not re.search(r"(요|니다)([.~!?]|$)", ko), ko
        for line in (en, ko):
            assert not re.search(r"hurry|quick|now!|right away|서둘|빨리|얼른|당장", line), line
    assert re.findall(r"agentHeld: '([^']+)'", app)[0] == HELD_EN
    assert "크레딧" in re.findall(r"withCredits: \(label, n\) => `([^`]+)`", app)[1]
    # one sum for the labels and for generate(): the labels are written by priced(), which asks gen.quoteOf()
    assert "assetQuote.label(label, gen.quoteOf(count, n)" in app
    # the page cannot run without quote.js, so nothing in it asks whether quote.js is there
    assert "quoteKit" not in app and "window.assetQuote" not in app and "heldAsk &&" not in app and "if (heldAsk)" not in app
    # the labels that are priced: the picker's, and the four buttons that make sounds by themselves, all by one path
    assert re.findall(r"quoted\(el\('button', '\w+'\), '(\w+)'", app) == ["fillAll", "makeRest", "likeThis", "makeOne"]
    assert "t('makeOne')" not in app
    assert app.count("priced(t('drafts')") == 2 and "el('span', 'segLabel', priced(t('drafts')" in app
    # gen.js reads the price with the token and until it has it; the page draws the labels when the token is taken and
    # whenever gen.js says the price came or changed
    assert "gen.token(e.data).then(drawQuotes)" in app and "onQuote: () => drawQuotes()" in app
    # the picker is the one place the number of drafts is read from
    assert "function draftsWanted(text, box = 'dock') {" in app and "drafts: draftsWanted(" not in app
    # at a press the label's number is read before the words can move the picker, in the dock and in the open sound
    press = app[app.index("$('askForm').onsubmit = (e) => {"):app.index("$('selAll').onclick")]
    assert press.index("const shown = gen.quoteOf(pickedSounds().length, drafts);") < press.index("draftsWanted(text)")
    assert "const shown = gen.quoteOf(1, drafts), n = draftsWanted(text, 'open');" in app
    # a held request sent again is made from what the answer asked for (heldLeft), never from the sentence in the box
    assert "makeAsked(left.remakes, left.fills, n);" in press and "a.description = text" not in press and ", text]]" not in press
    # every way of asking for sounds goes through the page's refuse(), which knows of a price that has not come
    assert app.count("gen.refuse()") == 1 and app.count("gen.why()") == 1
    # putting an answer back skips a sound that is being made, and never writes a sound's status, drafts or pick
    undo = app[app.index("    return () => {", app.index("function applyActions(actions, asked) {")):app.index("function say(text, undo) {")]
    assert "if (a.work) {" in undo and undo.index("if (a.work) {") < undo.index("Object.assign(a, rest)")
    for field in ("status", "drafts", "pick", "versions"):
        assert not re.search(r"\b%s\b" % field, undo), field
