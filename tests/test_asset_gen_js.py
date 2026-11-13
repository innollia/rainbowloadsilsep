"""The asset room's generation client (gen.js) under Node, with fetch, both clocks and the timers handed in: what is
written before a request goes out, the one poller, drafts that count as received only once their sound is on disk,
picking work up again after a reload, whose records are touched, the token (renewal, a 401, the paused state), wrong
bytes, results that are gone, a 429, and the one sentence a look's failures become. At the end the whole page (app.js)
runs on a stand-in DOM, so the wiring is exercised without a browser."""
import json, pathlib, re, subprocess

ROOT = pathlib.Path(__file__).parents[1] / "studio_frontend" / "asset_studio"
FILES = ("data.js", "synth.js", "importer.js", "measure.js", "store.js", "gen.js")

HELPERS = r"""
const G = window.assetGen, M = window.assetMeasure, S = window.assetStore;
const realTimeout = globalThis.setTimeout; // the page test puts the clock below in place of the global timers
const nodeCrypto = require('crypto');
const sha = (u8) => nodeCrypto.createHash('sha256').update(u8).digest('hex');
const BASE = 'https://api.test/api/asset';
const NKIDO = { name: 'nkido (Akkado, Cedar)', license: 'MIT', holder: 'Moritz Laass', use: 'Sound synthesis engine' };

// Both clocks and the timers. Nothing in gen.js runs on real time: advance(ms) runs what falls due, in order.
const T = { mono: 1000, wall: 1700000000000, timers: [], seq: 0, uuid: 0, slow: 0 };
const setT = (fn, ms) => { const t = { id: ++T.seq, at: T.mono + Math.max(0, ms || 0), fn }; T.timers.push(t); return t.id; };
const clearT = (id) => { T.timers = T.timers.filter((t) => t.id !== id); };
// Lets every promise chain run out. T.slow (ms) also waits for real timers, for the test that uses the real store.
const settle = async () => { if (T.slow) await new Promise((ok) => realTimeout(ok, T.slow)); for (let i = 0; i < 40; i++) await new Promise((ok) => setImmediate(ok)); };
// Real waiting, for work that leaves the event loop (the store's transactions, the browser's own SHA-256).
async function until(done, ms = 20000) {
  for (const end = Date.now() + ms; !done();) { if (Date.now() > end) throw new Error('waited too long'); await new Promise((ok) => realTimeout(ok, 5)); }
  await settle();
}
// IndexedDB in memory, enough for store.js: requests answer in the order asked, a turn after the transaction opened.
function tinyIdb(turn = (fn) => realTimeout(fn, 0)) {
  const stores = new Map();
  const transaction = (names) => {
    const q = { error: null, onerror: null, onabort: null, oncomplete: null }, todo = [];
    const ask = (run) => { const r = { result: undefined, error: null, onsuccess: null, onerror: null }; todo.push([r, run]); return r; };
    q.objectStore = (name) => { const m = stores.get(name); return {
      put: (v, k) => ask(() => { m.set(k, v); return k; }), delete: (k) => ask(() => { m.delete(k); }), clear: () => ask(() => { m.clear(); }),
      get: (k) => ask(() => { const v = m.get(k); return v instanceof Blob || v === undefined ? v : structuredClone(v); }), getKey: (k) => ask(() => (m.has(k) ? k : undefined)), getAllKeys: () => ask(() => [...m.keys()].sort()) }; };
    turn(() => { while (todo.length) { const [r, run] = todo.shift(); r.result = run(); if (r.onsuccess) r.onsuccess({ target: r }); } if (q.oncomplete) q.oncomplete({ target: q }); });
    return q;
  };
  const indexedDB = { open() { const r = { result: null, error: null, onsuccess: null, onerror: null, onupgradeneeded: null, onblocked: null };
    turn(() => { r.result = { createObjectStore: (n) => { stores.set(n, new Map()); }, transaction }; if (!stores.size) r.onupgradeneeded({ target: r }); r.onsuccess({ target: r }); }); return r; } };
  return { stores, indexedDB };
}
async function advance(ms) {
  const end = T.mono + ms;
  await settle();
  for (;;) {
    const due = T.timers.filter((t) => t.at <= end).sort((a, b) => a.at - b.at || a.id - b.id)[0];
    if (!due) break;
    T.timers = T.timers.filter((t) => t !== due);
    if (due.at > T.mono) { T.wall += due.at - T.mono; T.mono = due.at; }
    due.fn();
    await settle();
  }
  T.wall += end - T.mono; T.mono = end;
  await settle();
}

const tokenOf = (kind, sub, salt = '') => Buffer.from(JSON.stringify({ v: 1, aud: 'asset', kind, sub, lang: 'ko', iat: 1700000000, exp: 1700000900, ...(kind === 'acct' ? { email: 'a@b.c' } : {}) })).toString('base64url') + '.sig' + salt;
const whoOf = (sub) => sha(Buffer.from(sub)).slice(0, 16);
const wavOf = (hz, n = 480) => importer.encodeWav([Float32Array.from({ length: n }, (_, i) => 0.5 * Math.sin(2 * Math.PI * hz * i / 48000))], 48000, 16);
const slot = (id, more = {}) => ({ id, name: id, key: 'k-' + id, status: 'pending', versions: [], drafts: [], current: 0, pick: -1, progress: 0, chat: [], ...more });
const oldVersion = (id) => ({ id, at: 1, note: null, change: {}, engine: 'legacy', sources: [] });

// The API as asset_api.py answers, in memory. A test moves a job along with finish(id) or set(id, {...}).
//   down: no answer at all.   deny(call): answer 401.   hook(call, { res, raw, err }): answer something else.
function fakeApi(log = []) {
  const api = { calls: [], jobs: new Map(), reqs: new Map(), marks: new Set(), unit: 1, free: false, n: 0, down: false, deny: null, hook: null, log };
  const res = (status, data, headers = {}) => ({ status, headers: { get: (k) => headers[k] ?? null }, json: async () => { if (data === undefined) throw new Error('not json'); return data; }, arrayBuffer: async () => { throw new Error('no bytes'); } });
  const raw = (bytes) => ({ status: 200, headers: { get: () => null }, json: async () => { throw new Error('not json'); }, arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) });
  const err = (status, code, extra = {}, headers = {}) => res(status, { error: { code, message: 'server says ' + code, ...extra } }, headers);
  const priceOf = (items, drafts) => ({ items, drafts, unit: api.unit, credits: items * drafts * api.unit, free: api.free });
  const viewOf = (id) => {
    const j = api.jobs.get(id);
    if (!j) return { id, status: 'unknown', refund: 'none' };
    if (j.status === 'gone' || j.status === 'forbidden') return { id, status: j.status, refund: j.refund };
    const v = { id, ref: j.ref, k: j.k, n: j.n, batch: 'b', status: j.status, refund: j.refund, expires: null };
    if (j.status === 'queued') Object.assign(v, { position: j.position ?? 1, progress: 0 });
    if (j.status === 'running') Object.assign(v, { stage: 'rendering', attempt: 1, progress: j.progress ?? 0.5 });
    if (j.status === 'failed') v.error = { code: j.error || 'make_failed', message: 'server says ' + (j.error || 'make_failed') };
    if (j.status === 'done') {
      const result = { seconds: 0.01, rate: 48000, channels: 1, bits: 16, bytes: j.wav.length, sha256: j.sha || sha(j.wav), stems: j.stems.map((s) => ({ n: s.n, bytes: s.wav.length, sha256: sha(s.wav) })) };
      // The source, the prompt, the stem names and the measurements are only told once the sound went out.
      if (j.delivered) {
        Object.assign(result, { engine: 'nkido', model: 'model-x', prompt: 'PROMPT ' + id, source: 'SOURCE ' + id, bpm: null, measure: M.measure(M.readWav(j.wav)), issues: [], repairs: 0, sources: [NKIDO] });
        result.stems = result.stems.map((s, i) => ({ ...s, label: j.stems[i].label }));
      }
      Object.assign(v, { progress: 1, result });
    }
    return v;
  };
  api.fetch = async (url, init) => {
    if (!url.startsWith(BASE)) throw new Error('wrong url ' + url);
    const path = url.slice(BASE.length), call = { method: init.method, path, token: String(init.headers.Authorization || '').replace('Bearer ', ''), body: init.body, keepalive: !!init.keepalive };
    api.calls.push(call); log.push(init.method + ' ' + path);
    if (api.down) throw new TypeError('Failed to fetch');
    if (api.deny && api.deny(call)) return err(401, 'token_expired');
    const hooked = api.hook && api.hook(call, { res, raw, err });
    if (hooked) return hooked;
    const body = init.body === undefined ? null : JSON.parse(init.body);
    if (path.startsWith('/quote')) return res(200, { ...priceOf(1, 1), balance: 10, left_today: 100, room: 64, ok: true, reason: null });
    if (path === '/jobs') {
      if (api.marks.has(body.request_id)) return err(410, 'request_cancelled');
      const had = api.reqs.get(body.request_id);
      if (had) return res(200, { ...had.answer, replayed: true });
      const price = priceOf(body.items.length, body.drafts);
      if (body.expect_credits !== price.credits) return err(409, 'quote_changed', { quote: price });
      const made = [];
      for (const item of body.items) for (let k = 1; k <= body.drafts; k++) {
        const id = 'job' + (++api.n);
        api.jobs.set(id, { id, ref: item.ref, k, n: body.drafts, status: 'queued', refund: 'none', request: body.request_id, stems: [] });
        made.push({ id, ref: item.ref, k, n: body.drafts, status: 'queued' });
      }
      const answer = { batch: 'b' + api.reqs.size, replayed: false, quote: price, jobs: made };
      api.reqs.set(body.request_id, { answer, body: init.body, cancelled: false });
      return res(200, answer);
    }
    if (path === '/jobs/status') {
      if (body.ids) return res(200, { credits: 9, jobs: body.ids.map(viewOf) });
      const r = api.reqs.get(body.request_id);
      return res(200, { known: !!r, cancelled: api.marks.has(body.request_id) || !!(r && r.cancelled), jobs: r ? r.answer.jobs.map((j) => viewOf(j.id)) : [] });
    }
    if (path === '/jobs/cancel') {
      const stop = (id) => { const j = api.jobs.get(id); if (j && (j.status === 'queued' || j.status === 'running')) j.status = 'cancelled'; };
      if (body.ids) body.ids.forEach(stop);
      else { const r = api.reqs.get(body.request_id); if (r) { r.cancelled = true; r.answer.jobs.forEach((j) => stop(j.id)); } else api.marks.add(body.request_id); }
      return res(200, { jobs: (body.ids || []).map(viewOf) });
    }
    let m = /^\/jobs\/([^/]+)\/sound$/.exec(path);
    if (m) { const j = api.jobs.get(m[1]); if (!j || j.status !== 'done') return err(404, 'not_found'); j.delivered = true; return raw(j.wav); }
    m = /^\/jobs\/([^/]+)\/stems\/(\d+)$/.exec(path);
    if (m) { const j = api.jobs.get(m[1]), s = j && j.status === 'done' && j.stems.find((x) => x.n === +m[2]); if (!s) return err(404, 'not_found'); j.delivered = true; return raw(s.wav); }
    return err(404, 'not_found');
  };
  api.finish = (id, stems = 0, more = {}) => Object.assign(api.jobs.get(id), { status: 'done', wav: wavOf(400 + 20 * api.jobs.get(id).k), stems: Array.from({ length: stems }, (_, i) => ({ n: i + 1, wav: wavOf(150 * (i + 2)), label: 'part ' + (i + 1) })) }, more);
  api.set = (id, more) => Object.assign(api.jobs.get(id), more);
  api.paths = (from = 0) => api.calls.slice(from).map((c) => c.method + ' ' + c.path);
  api.posted = (path) => api.calls.filter((c) => c.method === 'POST' && c.path === path).map((c) => JSON.parse(c.body));
  return api;
}

// What gen.js asks of the store, in memory. Every write is logged with the calls of the API, so their order shows.
function fakeStore(snapshot, log = []) {
  const s = { board: new Map(), audio: new Map(), held: new Map(), saved: new Set(), log, locked: true, ready: true, readOnly: false, paused: false, blobFull: false, failBoard: false, failPut: false, failBlob: () => false };
  Object.defineProperty(s, 'writable', { get: () => s.locked && s.ready && !s.paused });
  s.saveBoard = async () => { if (!s.writable || s.failBoard) { log.push('board refused'); return false; } s.board.set('board', JSON.stringify(snapshot())); log.push('board'); return true; };
  s.saveBlob = async (key, blob) => { if (!s.writable || s.failBlob(key)) { log.push('blob refused ' + key); return false; } s.audio.set(key, blob); s.saved.add(key); s.held.delete(key); log.push('blob ' + key); return true; };
  s.hold = (key, blob) => { s.held.set(key, blob); };
  s.put = async (key, value) => { if (!s.writable || s.failPut) return false; s.board.set(key, value); log.push('put ' + key); return true; };
  s.get = async (key) => s.board.get(key);
  s.del = async (key) => { s.board.delete(key); log.push('del ' + key); return true; };
  return s;
}

// The part of app.js that gen.js talks to. Texts come back as their key (and number), so a test reads what was said.
function page(opts = {}) {
  const log = opts.log || [];
  const p = { assets: opts.assets || [], toasts: [], posts: [], done: [], quotes: 0, renders: 0, busy: false, hidden: false, log };
  const pack = (v) => { const { sound, ...rest } = v; return rest; };
  p.snapshot = () => ({ assets: p.assets.map((a) => ({ ...a, versions: a.versions.map(pack), drafts: a.drafts.map(pack) })) });
  p.store = opts.store || fakeStore(() => p.snapshot(), log);
  p.api = opts.api || fakeApi(log);
  p.gen = G.create({
    store: p.store, assets: () => p.assets, fetch: p.api.fetch,
    now: () => T.mono, wall: () => T.wall, setTimeout: setT, clearTimeout: clearT,
    uuid: () => 'req-' + (++T.uuid), sha256: async (bytes) => sha(bytes), measure: M, peaks: S.peaksOf,
    project: () => ({ game: 'Moon Farm', style: 'calm', platform: 'mobile', loud: [-20, -16] }),
    item: (a, o) => ({ kind: a.music ? 'music' : 'sfx', loop: !!a.loop, id: a.id, name: a.name, description: a.description || '', ...(o.mode === 'revise' ? { change: o.text, base: { source: 'OLD PATCH', seconds: 1, bpm: null } } : {}) }),
    lang: () => 'ko', text: (key, n) => (n === undefined ? key : key + ':' + n),
    toast: (text) => p.toasts.push(text), toastBusy: () => p.busy, post: (type) => p.posts.push(type), hidden: () => p.hidden,
    render: () => { p.renders++; }, done: (a, info) => p.done.push([a.id, info.made]), onQuote: () => { p.quotes++; },
    ...(opts.deps || {}),
  });
  p.token = async (kind = 'acct', sub = 'acct:me', salt = '', ttl = 900) => { const ok = await p.gen.token({ token: tokenOf(kind, sub, salt), ttl, api: BASE }); await settle(); return ok; };
  return p;
}
// The same board on a later visit: what was saved, a new generator, nothing in memory.
function reload(p, opts = {}) {
  const saved = JSON.parse(p.store.board.get('board'));
  const q = page({ assets: saved.assets, api: p.api, log: p.log, ...opts });
  for (const [k, v] of p.store.board) q.store.board.set(k, v);
  for (const [k, v] of p.store.audio) { q.store.audio.set(k, v); q.store.saved.add(k); }
  return q;
}
const work = (a) => (a.work ? { ...a.work, jobs: a.work.jobs.map((j) => ({ ...j })) } : null);
const brief = (a) => ({ status: a.status, versions: a.versions.map((v) => v.id), drafts: a.drafts.map((v) => v.id), pick: a.pick, work: !!a.work });
"""


def node(script, timeout=60, flags=()):
    # stdin: Windows caps a command line at 32K. The timeout turns a promise that never settles into a failure.
    out = subprocess.run(["node", *flags, "-"], input=script, capture_output=True, text=True, encoding="utf-8", check=True, timeout=timeout)
    return json.loads(out.stdout)


def run(body, flags=()):
    """The modules the way the browser loads them, then `body`, which fills `out`. flags: options for node itself."""
    src = "globalThis.window = globalThis;\n" + "\n".join((ROOT / f).read_text(encoding="utf-8") for f in FILES) + HELPERS
    return node(src + "\n(async () => {\nconst out = {};\n" + body + "\nconsole.log(JSON.stringify(out));\n})().catch((e) => { console.error(e); process.exit(1); });", flags=flags)


# A stand-in for the browser, enough for app.js to draw its board and take clicks: elements with children, classes,
# data attributes and simple selectors, a window that can be sent a message, an IndexedDB in memory, the API above as
# fetch, and the clock above in place of the timers. Nothing is laid out and nothing sounds.
DOM = r"""
const camel = (s) => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
class TextNode {
  constructor(text) { this.nodeType = 3; this.textContent = String(text); this.parentNode = null; }
  remove() { const p = this.parentNode; if (p) { p.childNodes = p.childNodes.filter((n) => n !== this); this.parentNode = null; } }
}
// tag, #id, .class, [attr], [attr=value] and :not(:disabled), joined by spaces (inside) and commas (either).
function compound(text) {
  const c = { tag: null, id: null, classes: [], attrs: [], enabled: false };
  const rest = text.replace(/:not\(:disabled\)/g, () => { c.enabled = true; return ''; });
  for (const m of rest.matchAll(/\[([\w-]+)(?:=(?:"([^"]*)"|([^\]]*)))?\]|([#.]?)([\w-]+)/g)) {
    if (m[1]) c.attrs.push([m[1], m[2] ?? m[3]]);
    else if (m[4] === '#') c.id = m[5]; else if (m[4] === '.') c.classes.push(m[5]); else c.tag = m[5].toUpperCase();
  }
  return c;
}
const fits = (e, c) => (!c.tag || e.tagName === c.tag) && (!c.id || e.id === c.id) && c.classes.every((k) => e.classList.contains(k)) && (!c.enabled || !e.disabled)
  && c.attrs.every(([k, v]) => { const got = e.attr(k); return got !== undefined && (v === undefined || String(got) === v); });
function matchesSel(e, selector) {
  return selector.split(',').some((one) => {
    const parts = one.trim().split(/\s+/).map(compound);
    if (!fits(e, parts[parts.length - 1])) return false;
    let x = e.parentNode;
    for (let i = parts.length - 2; i >= 0; i--) { while (x && x.nodeType === 1 && !fits(x, parts[i])) x = x.parentNode; if (!x || x.nodeType !== 1) return false; x = x.parentNode; }
    return true;
  });
}
class El {
  constructor(tag) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.childNodes = []; this.parentNode = null; this.attrs = {}; this.dataset = {}; this.handlers = {};
    this.id = ''; this.className = ''; this.hidden = false; this.disabled = false; this.value = ''; this.html = ''; this.scrollTop = 0;
    this.style = { setProperty(k, v) { this[k] = String(v); }, getPropertyValue(k) { return this[k] ?? ''; }, removeProperty(k) { delete this[k]; } };
    const names = () => this.className.split(/\s+/).filter(Boolean);
    this.classList = {
      add: (...c) => { this.className = [...new Set([...names(), ...c])].join(' '); }, remove: (...c) => { this.className = names().filter((x) => !c.includes(x)).join(' '); },
      contains: (c) => names().includes(c), toggle: (c, on) => { const want = on === undefined ? !names().includes(c) : !!on; this.classList[want ? 'add' : 'remove'](c); return want; },
    };
    if (this.tagName === 'CANVAS') this.getContext = () => new Proxy({}, { get: (t, k) => (k in t ? t[k] : () => {}), set: (t, k, v) => { t[k] = v; return true; } });
  }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  get parentElement() { return this.parentNode; }
  get textContent() { return this.childNodes.map((n) => n.textContent).join(''); }
  set textContent(v) { for (const n of this.childNodes) n.parentNode = null; this.childNodes = []; this.html = ''; if (v != null && v !== '') this.append(String(v)); }
  get innerHTML() { return this.html; }
  set innerHTML(v) { this.textContent = ''; this.html = String(v); }
  get clientWidth() { return 0; }
  get clientHeight() { return 0; }
  get offsetWidth() { return 0; }
  get offsetLeft() { return 0; }
  get scrollHeight() { return 0; }
  take(items) { return items.filter((x) => x != null).map((x) => { const n = typeof x === 'object' ? x : new TextNode(x); if (n.parentNode) n.remove(); n.parentNode = this; return n; }); }
  append(...items) { this.childNodes.push(...this.take(items)); }
  appendChild(n) { this.append(n); return n; }
  prepend(...items) { this.childNodes.unshift(...this.take(items)); }
  insertBefore(n, ref) { const [x] = this.take([n]), i = this.childNodes.indexOf(ref); this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, x); return n; }
  remove() { const p = this.parentNode; if (p) { p.childNodes = p.childNodes.filter((n) => n !== this); this.parentNode = null; } }
  replaceChildren(...items) { this.textContent = ''; this.append(...items); }
  replaceWith(...items) { const p = this.parentNode; if (!p) return; const fresh = p.take(items), i = p.childNodes.indexOf(this); p.childNodes.splice(i, 1, ...fresh); this.parentNode = null; }
  contains(n) { for (let x = n; x; x = x.parentNode) if (x === this) return true; return false; }
  attr(k) { return k.startsWith('data-') ? this.dataset[camel(k.slice(5))] : k === 'id' ? this.id || undefined : k === 'class' ? this.className || undefined : k === 'hidden' || k === 'disabled' ? (this[k] ? '' : undefined) : this.attrs[k]; }
  setAttribute(k, v) { if (k.startsWith('data-')) this.dataset[camel(k.slice(5))] = String(v); else if (k === 'id') this.id = String(v); else if (k === 'class') this.className = String(v); else if (k === 'hidden' || k === 'disabled') this[k] = true; else this.attrs[k] = String(v); }
  getAttribute(k) { return this.attr(k) ?? null; }
  hasAttribute(k) { return this.attr(k) !== undefined; }
  removeAttribute(k) { if (k === 'hidden' || k === 'disabled') this[k] = false; else if (k.startsWith('data-')) delete this.dataset[camel(k.slice(5))]; else delete this.attrs[k]; }
  matches(s) { return matchesSel(this, s); }
  closest(s) { for (let x = this; x && x.nodeType === 1; x = x.parentNode) if (x.matches(s)) return x; return null; }
  querySelectorAll(s) { const out = []; const walk = (n) => { for (const c of n.children) { if (c.matches(s)) out.push(c); walk(c); } }; walk(this); return out; }
  querySelector(s) { return this.querySelectorAll(s)[0] || null; }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  removeEventListener(type, fn) { this.handlers[type] = (this.handlers[type] || []).filter((x) => x !== fn); }
  fire(type, more = {}) {
    const ev = { type, target: this, currentTarget: this, preventDefault() {}, stopPropagation() {}, ...more };
    if (typeof this['on' + type] === 'function') this['on' + type](ev);
    for (const fn of [...(this.handlers[type] || [])]) fn.call(this, ev);
    return ev;
  }
  dispatchEvent(ev) { this.fire(ev.type, ev); return true; }
  click() { if (!this.disabled) this.fire('click'); }
  focus() { document.activeElement = this; this.fire('focus'); }
  blur() {}
  select() {}
  scrollIntoView() {}
  setPointerCapture() {}
  releasePointerCapture() {}
  getBoundingClientRect() { return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0 }; }
  showModal() { this.open = true; }
  close() { if (this.open) { this.open = false; this.fire('close'); } }
  add(option) { this.append(option); }
  cloneNode() { const c = new El(this.tagName); c.id = this.id; c.className = this.className; Object.assign(c.attrs, this.attrs); Object.assign(c.dataset, this.dataset); for (const [k, v] of Object.entries(this.style)) if (typeof v !== 'function') c.style[k] = v; return c; }
}
const html = new El('html'); html.append(new El('head'), new El('body'));
const windowHears = {};
const own = (name, value) => Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
own('document', {
  documentElement: html, head: html.children[0], body: html.children[1], hidden: false, activeElement: null, title: '',
  createElement: (tag) => new El(tag), createTextNode: (text) => new TextNode(text),
  getElementById: (id) => { let hit = null; const walk = (n) => { for (const c of n.children) { if (hit) return; if (c.id === id) { hit = c; return; } walk(c); } }; walk(html); return hit; },
  querySelector: (s) => html.querySelector(s), querySelectorAll: (s) => html.querySelectorAll(s),
  addEventListener() {}, removeEventListener() {}, execCommand: () => true,
});
own('parent', globalThis); // the page is not inside the host page here
own('addEventListener', (type, fn) => { (windowHears[type] ||= []).push(fn); });
own('removeEventListener', (type, fn) => { windowHears[type] = (windowHears[type] || []).filter((x) => x !== fn); });
const tellWindow = (type, ev) => { for (const fn of [...(windowHears[type] || [])]) fn({ type, preventDefault() {}, stopPropagation() {}, ...ev }); };
const keptHere = new Map([['asset-tutorial-seen', '1']]);
own('localStorage', { getItem: (k) => (keptHere.has(k) ? keptHere.get(k) : null), setItem: (k, v) => { keptHere.set(k, String(v)); }, removeItem: (k) => { keptHere.delete(k); } });
own('navigator', { clipboard: { writeText: async () => {} } });
own('location', { search: '?lang=en', origin: 'https://room.test', reload() {} });
own('performance', { now: () => T.mono });
own('requestAnimationFrame', () => 0);
own('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
own('getComputedStyle', () => ({ getPropertyValue: () => '#888888' }));
own('devicePixelRatio', 1);
own('innerWidth', 1280);
own('innerHeight', 800);
own('Option', function (text, value) { const o = new El('option'); o.textContent = text; o.value = value; return o; });
const disk = tinyIdb(setImmediate), api = fakeApi();
own('indexedDB', disk.indexedDB);
own('fetch', api.fetch);
own('setTimeout', setT);
own('clearTimeout', clearT);
// The elements of index.html, nested as they are written there.
(function build(markup) {
  const text = markup.slice(markup.indexOf('<body>') + 6, markup.indexOf('</body>')), single = new Set(['input', 'br', 'img', 'meta', 'link']);
  let at = document.body, last = 0;
  for (const m of text.matchAll(/<(\/?)([a-zA-Z0-9]+)([^>]*)>/g)) {
    const between = text.slice(last, m.index).trim(); last = m.index + m[0].length;
    if (between) at.append(between);
    if (m[1]) { at = at.parentNode; continue; }
    const e = new El(m[2]);
    for (const a of m[3].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) e.setAttribute(a[1], a[2] ?? '');
    at.append(e);
    if (!single.has(m[2].toLowerCase())) at = e;
  }
})(INDEX_HTML);
"""
# A board an earlier page saved while it opened on stand-in sounds (tests/js/legacy_sounds.js), nobody having touched
# it: its eight samples made by the room's own synth (legacy versions, their recipe only) waiting for a check, the
# other sounds empty slots. The page opens it as it opens any saved board.
OLD_BOARD = (pathlib.Path(__file__).parent / "js" / "legacy_sounds.js").read_text(encoding="utf-8") + r"""
{
  const { GAME, BRIEF, ASSETS } = window.LEGACY_SOUNDS;
  const old = (d) => ({ ...structuredClone(d), key: 's_' + d.id, status: d.sample ? 'draft' : 'pending', current: 0, drafts: [], pick: -1, chat: [], hasSource: false,
    versions: d.sample ? [{ id: 'sv_s_' + d.id, at: 0, note: { key: 'firstVersion' }, change: {}, engine: 'legacy', sources: S.sourcesFor(d) }] : [] });
  disk.stores.set('board', new Map([['board', { v: S.SNAPSHOT, game: GAME, brief: BRIEF, platform: 'mobile', demo: true, stage: 'sample', loud: [-20, -16],
    trash: [], projectRefs: [], agentLog: [], dynamics: [], assets: ASSETS.map(old) }]]));
  disk.stores.set('audio', new Map());
}
"""
PAGE_FILES = ("data.js", "synth.js", "importer.js", "godot.js", "unreal_py.js", "unreal.js", "refs.js", "measure.js", "store.js", "board.js", "gen.js", "sync.js", "quote.js")


def run_page(body, before=""):
    """The page as index.html loads it, app.js last, on the stand-in above. `body` presses things and fills `out`.
    `before` runs once the stand-in is up and before app.js: what the page finds when it starts (a host page, a disk)."""
    read = lambda name: (ROOT / name).read_text(encoding="utf-8")  # noqa: E731
    # the scripts the real page names, in its order: a file index.html loads and this does not would go untested
    assert [*PAGE_FILES, "app.js"] == re.findall(r'<script src="([^"?]+)', read("index.html"))
    src ="globalThis.window = globalThis;\n" + "\n;\n".join(read(f) for f in PAGE_FILES) + "\n;\n" + HELPERS
    src += "\nconst INDEX_HTML = " + json.dumps(read("index.html")) + ";\n" + DOM + "\n;\n" + before + "\n;\n" + read("app.js")
    return node(src + "\n;(async () => {\nconst out = {};\n" + body + "\nconsole.log(JSON.stringify(out));\n})().catch((e) => { console.error(e); process.exit(1); });")


# ---------- asking ----------

def test_the_words_and_the_board_are_written_before_anything_is_sent():
    got = run(r"""
    const a = slot('sfx_a'), b = slot('sfx_b'), p = page({ assets: [a, b] });
    await p.token();
    let stored = null, onDisk = null;
    p.api.hook = (call) => { if (call.path === '/jobs') { stored = p.store.board.get('req:req-1'); onDisk = JSON.parse(p.store.board.get('board')).assets.map((x) => [x.status, x.work && x.work.jobs.length]); } };
    const asked = p.gen.generate([a, b], { mode: 'make', text: 'soft', drafts: 2 });
    out.atOnce = [a.status, b.status, !!a.work];        // marked before anything is waited for
    out.result = await asked;
    const posted = p.api.calls.find((c) => c.path === '/jobs');
    out.order = p.log.filter((x) => /^(put|board|del|POST \/jobs$)/.test(x));
    out.same = posted.body === stored;
    out.onDisk = onDisk;
    const body = JSON.parse(posted.body);
    out.body = { request_id: body.request_id, expect_credits: body.expect_credits, drafts: body.drafts, lang: body.lang, project: body.project, refs: body.items.map((i) => i.ref), modes: body.items.map((i) => i.mode), examples: body.examples };
    out.work = work(a);
    out.who = whoOf('acct:me');
    out.left = p.store.board.has('req:req-1');
    out.saved = JSON.parse(p.store.board.get('board')).assets.map((x) => x.work.jobs.map((j) => j.id));
    out.auth = posted.token === tokenOf('acct', 'acct:me');
    """)
    assert got["atOnce"] == ["working", "working", True] and got["result"] == {"ok": True}
    assert got["order"] == ["put req:req-1", "board", "POST /jobs", "board", "del req:req-1"]
    assert got["same"] is True and got["onDisk"] == [["working", 0], ["working", 0]]
    assert got["body"] == {"request_id": "req-1", "expect_credits": 4, "drafts": 2, "lang": "ko", "refs": ["k-sfx_a", "k-sfx_b"], "modes": ["make", "make"], "examples": [],
                           "project": {"game": "Moon Farm", "style": "calm", "platform": "mobile", "loud": [-20, -16]}}
    assert got["work"] == {"request": "req-1", "kind": "acct", "who": got["who"], "mode": "make", "text": "soft", "n": 2, "at": 1700000000000, "before": "pending",
                           "jobs": [{"id": "job1", "k": 1, "got": False}, {"id": "job2", "k": 2, "got": False}]}
    assert got["left"] is False and got["saved"] == [["job1", "job2"], ["job3", "job4"]] and got["auth"] is True


def test_nothing_is_posted_when_the_board_cannot_be_saved():
    got = run(r"""
    const a = slot('sfx_a', { status: 'draft', versions: [oldVersion('v1')] }), p = page({ assets: [a] });
    await p.token();
    p.store.failBoard = true;
    out.result = await p.gen.generate([a], { mode: 'revise', text: 'brighter', drafts: 1 });
    out.posts = p.api.paths().filter((x) => x.startsWith('POST'));
    out.after = brief(a); out.toasts = p.toasts.slice(); out.words = p.store.board.has('req:req-1');
    // The words themselves not fitting is the same refusal.
    p.store.failBoard = false; p.store.failPut = true;
    out.second = await p.gen.generate([a], { mode: 'revise', text: 'brighter', drafts: 1 });
    out.posts2 = p.api.paths().filter((x) => x.startsWith('POST'));
    out.after2 = brief(a);
    """)
    assert got["result"] == {"ok": False, "reason": "saveFull"} and got["posts"] == []
    assert got["after"] == {"status": "draft", "versions": ["v1"], "drafts": [], "pick": -1, "work": False}
    assert got["toasts"] == ["saveFull"] and got["words"] is False
    assert got["second"] == {"ok": False, "reason": "saveFull"} and got["posts2"] == [] and got["after2"] == got["after"]


def test_nothing_new_is_taken_without_a_token_a_lock_a_readable_board_or_room_for_sound():
    got = run(r"""
    const a = slot('sfx_a'), p = page({ assets: [a] });
    out.noToken = [p.gen.why(), await p.gen.generate([a], { mode: 'make', drafts: 1 }), a.status, p.gen.ready];
    await p.token();
    out.ready = [p.gen.why(), p.gen.ready];
    p.store.locked = false; out.otherTab = p.gen.why(); p.store.locked = true;
    p.store.paused = true; out.failed = p.gen.why(); p.store.paused = false;
    p.store.blobFull = true; out.full = [p.gen.why(), (await p.gen.generate([a], { mode: 'make', drafts: 1 })).reason]; p.store.blobFull = false;
    p.store.ready = false; out.reading = [p.gen.why(), p.gen.refuse()]; p.store.ready = true;
    out.toasts = p.toasts; out.status = a.status;
    out.calls = p.api.paths().filter((x) => x !== 'GET /quote?items=1&drafts=1');
    """)
    assert got["noToken"] == ["aiOff", {"ok": False, "reason": "aiOff"}, "pending", False]
    assert got["ready"] == ["", True] and got["otherTab"] == "otherTab" and got["failed"] == "loadFailed"
    assert got["full"] == ["saveFull", "saveFull"] and got["reading"] == ["wait", True]
    assert got["toasts"] == ["aiOff", "saveFull"] and got["status"] == "pending" and got["calls"] == []


def test_a_refusal_puts_the_sounds_back_and_says_what_the_server_said():
    got = run(r"""
    const a = slot('sfx_a'), b = slot('sfx_b', { status: 'approved', versions: [oldVersion('v1')] }), p = page({ assets: [a, b] });
    await p.token();
    out.codes = [];
    for (const [status, code] of [[402, 'no_credits'], [410, 'request_cancelled'], [413, 'too_large'], [429, 'too_many_active'], [503, 'busy']]) {
      p.api.hook = (call, h) => (call.path === '/jobs' ? h.err(status, code) : null);
      const r = await p.gen.generate([a, b], { mode: 'make', drafts: 1 });
      out.codes.push([r.reason, a.status, b.status, !!a.work, p.toasts.at(-1), [...p.store.board.keys()].filter((k) => k.startsWith('req:')).length]);
    }
    out.posts = p.api.posted('/jobs').length;
    // The price changed: the sounds go back, the new price is read and shown, and nothing is sent again by itself.
    p.api.hook = null; p.api.unit = 3;
    const before = p.api.calls.length, quotes = p.quotes;
    const r = await p.gen.generate([a], { mode: 'make', drafts: 2 });
    out.changed = [r.reason, a.status, p.toasts.at(-1), p.api.paths(before), p.gen.quoteOf(1, 2).credits, p.quotes - quotes];
    out.again = [(await p.gen.generate([a], { mode: 'make', drafts: 2 })).ok, JSON.parse(p.api.calls.at(-1).body).expect_credits];
    """)
    assert got["codes"] == [[code, "pending", "approved", False, "server says " + code, 0] for code in ("no_credits", "request_cancelled", "too_large", "too_many_active", "busy")]
    assert got["posts"] == 5
    assert got["changed"] == ["quote_changed", "pending", "server says quote_changed", ["POST /jobs", "GET /quote?items=1&drafts=1"], 6, 1]
    assert got["again"] == [True, 6]


def test_the_price_is_read_with_the_first_token_and_when_the_person_changes():
    got = run(r"""
    const p = page({ assets: [slot('sfx_a')] });
    out.unknown = p.gen.quoteOf(3, 2);
    await p.token('pw', 'pw:one');
    p.api.free = true; p.api.unit = 0;
    await p.token('pw', 'pw:one', 'x');           // the same person with a newer token: the price is not asked again
    out.asked = p.api.paths().length;
    await p.token('pw', 'pw:two');                // another password session
    out.free = p.gen.quoteOf(3, 2);
    p.api.free = false; p.api.unit = 1;
    await p.token('acct', 'acct:me');             // an account: the number appears
    out.paid = p.gen.quoteOf(3, 2);
    out.calls = p.api.paths(); out.quotes = p.quotes;
    """)
    assert got["unknown"] == {"items": 3, "drafts": 2, "unit": None, "credits": None, "free": False, "known": False}
    assert got["asked"] == 1 and got["calls"] == ["GET /quote?items=1&drafts=1"] * 3
    assert got["free"] == {"items": 3, "drafts": 2, "unit": 0, "credits": 0, "free": True, "known": True}
    assert got["paid"] == {"items": 3, "drafts": 2, "unit": 1, "credits": 6, "free": False, "known": True} and got["quotes"] == 3


def test_a_price_that_did_not_come_is_read_again_every_ten_seconds_and_with_every_token_until_it_has():
    """The page turns requests away while no label can say what they take, so a first read that failed must not leave
    the visit without a price: it is read again by itself, and onQuote tells the page the moment it is known."""
    got = run(r"""
    const quotesOf = (p) => p.api.paths().filter((x) => x.startsWith('GET /quote')).length;
    const p = page({ assets: [slot('sfx_a')] });
    let failing = true;
    p.api.hook = (call, h) => (call.path.startsWith('/quote') && failing ? h.err(503, 'busy') : null);
    await p.token();
    out.first = [quotesOf(p), p.gen.unit, p.quotes, p.gen.quoteOf(1, 1).known];
    await advance(9999); out.early = quotesOf(p);
    await advance(1); out.tenOn = [quotesOf(p), p.gen.unit];
    await p.token('acct', 'acct:me', 'newer'); out.withToken = quotesOf(p);      // the same person's next token reads it too
    failing = false;
    await advance(10000);
    out.known = [quotesOf(p), p.gen.unit, p.quotes, p.gen.quoteOf(2, 2).credits];
    await p.token('acct', 'acct:me', 'third'); await advance(60000);
    out.quiet = [quotesOf(p), p.quotes, p.toasts];                                // known: nothing more is read, nothing was said
    // A 429 names its own wait: neither the ten seconds nor a newer token asks before it is over.
    const p2 = page({ assets: [slot('sfx_b')] });
    let limited = 1;
    p2.api.hook = (call, h) => (call.path.startsWith('/quote') && limited-- > 0 ? h.err(429, 'rate', { retry_after: 30 }, { 'Retry-After': '30' }) : null);
    await p2.token();
    await advance(10000);
    await p2.token('acct', 'acct:me', 'newer');
    await advance(19999); out.resting = [quotesOf(p2), p2.gen.unit];
    await advance(1); out.rested = [quotesOf(p2), p2.gen.unit, p2.quotes];
    // A page that is paused (its token ran out and no other came) asks for no price until the next token is here.
    const p3 = page({ assets: [slot('sfx_c')] }), old = tokenOf('acct', 'acct:me');
    p3.api.deny = (call) => call.token === old;
    await p3.token();
    await advance(10000);
    out.paused = [p3.gen.paused, quotesOf(p3)];
    await advance(60000); out.whilePaused = quotesOf(p3);
    await p3.token('acct', 'acct:me', 'fresh');
    out.resumed = [p3.gen.paused, quotesOf(p3), p3.gen.unit, p3.quotes];
    """)
    assert got["first"] == [1, None, 0, False] and got["early"] == 1 and got["tenOn"] == [2, None] and got["withToken"] == 3
    assert got["known"] == [4, {"unit": 1, "free": False}, 1, 4] and got["quiet"] == [4, 1, []]
    assert got["resting"] == [1, None] and got["rested"] == [2, {"unit": 1, "free": False}, 1]
    assert got["paused"] == [True, 1] and got["whilePaused"] == 1 and got["resumed"] == [False, 2, {"unit": 1, "free": False}, 1]


def test_price_reads_that_no_api_answered_three_times_running_say_that_making_sounds_cannot_be_reached():
    """An address with no API behind it answers with another server's page, or not at all. After three such reads in
    a row gen.unreached is true, so the page can say that making sounds is not connected instead of asking to try
    again in a moment. An error the API wrote, a price, or another person's token starts the count again."""
    got = run(r"""
    const p = page({ assets: [slot('sfx_a')] });
    let answer = 'page';
    p.api.hook = (call, h) => (!call.path.startsWith('/quote') ? null : answer === 'page' ? h.res(200) : answer === 'busy' ? h.err(503, 'busy') : null);
    await p.token();
    out.one = p.gen.unreached;
    await advance(10000); out.two = p.gen.unreached;
    await advance(10000); out.three = [p.gen.unreached, p.gen.unit];
    answer = 'busy'; await advance(10000); out.itAnswered = p.gen.unreached;          // an error the API wrote: it is there
    answer = 'price'; p.api.down = true;                                              // no answer at all
    await advance(20000); out.twoSilent = p.gen.unreached;
    await advance(10000); out.threeSilent = p.gen.unreached;
    p.api.down = false;
    await advance(10000); out.priced = [p.gen.unreached, p.gen.unit, p.quotes];
    // Another person's token: their price is read from the start.
    const p2 = page({ assets: [slot('sfx_b')] });
    p2.api.down = true;
    await p2.token();
    await advance(20000); out.other = p2.gen.unreached;
    await p2.token('pw', 'pw:room'); out.fresh = p2.gen.unreached;
    """)
    assert got["one"] is False and got["two"] is False and got["three"] == [True, None]
    assert got["itAnswered"] is False and got["twoSilent"] is False and got["threeSilent"] is True
    assert got["priced"] == [False, {"unit": 1, "free": False}, 1]
    assert got["other"] is True and got["fresh"] is False


def test_what_is_sent_is_cut_to_what_the_api_takes():
    got = run(r"""
    const long = (n) => 'x'.repeat(n), a = slot('sfx_a', { key: 'k'.repeat(60) });
    const p = page({ assets: [a], deps: {
      project: () => ({ game: long(300), style: long(1200), platform: 'handheld', loud: [-10, -30] }),
      item: () => ({ kind: 'laser', loop: 1, id: long(80), name: long(100), when: long(400), description: long(2500) + '\ud83d', seconds: 0, bpm: Infinity, change: long(2100),
        references: [...Array.from({ length: 10 }, (_, i) => ({ kind: 'text', name: 'n' + i, note: long(700) })), { kind: 'video', name: 'no' }],
        style_ref: { name: long(90), seconds: 1.5, loop: 0, facts: { peak: -3, loud: -18, bits: null, extra: 1, seam: NaN } }, base: { source: '   ', facts: { seconds: 2, tail: '9' } } }),
      examples: () => [{ name: 'ok', kind: 'sfx', loop: false, source: 'SRC', facts: { peak: -2 } }, { name: 'huge', kind: 'sfx', source: long(4001) }, { name: 'odd', kind: 'voice', source: 'x' }],
    } });
    await p.token();
    await p.gen.generate([a], { mode: 'revise', text: 'x', drafts: 9 });
    const body = JSON.parse(p.api.calls.find((c) => c.path === '/jobs').body), item = body.items[0];
    out.drafts = body.drafts; out.project = [body.project.game.length, body.project.style.length, body.project.platform, body.project.loud ?? null];
    out.item = { ref: item.ref.length, kind: item.kind, loop: item.loop, id: item.id.length, name: item.name.length, when: item.when.length, description: item.description.length, seconds: item.seconds, bpm: item.bpm, change: item.change.length,
      refs: item.references.length, note: item.references[0].note.length, style: item.style_ref, base: item.base, mode: item.mode };
    out.style = [item.style_ref.name.length, item.style_ref.seconds, item.style_ref.loop, item.style_ref.facts];
    delete out.item.style;
    out.examples = body.examples;
    out.matched = a.work.jobs.length;                // the ref that was sent is the ref the answer is matched by
    out.clip = [G.clip('ab😀cd', 3), G.clip('x\ud800y', 9).length, G.clip(null, 4), G.clip(12345, 3)];
    """)
    assert got["drafts"] == 4 and got["project"] == [200, 1000, "mobile", None]
    assert got["item"] == {"ref": 40, "kind": "sfx", "loop": True, "id": 64, "name": 80, "when": 300, "description": 2000, "seconds": None, "bpm": None, "change": 2000,
                           "refs": 8, "note": 600, "base": {"facts": {"seconds": 2}}, "mode": "revise"}
    assert got["style"] == [80, 1.5, False, {"peak": -3, "loud": -18}]
    assert got["examples"] == [{"name": "ok", "kind": "sfx", "loop": False, "source": "SRC", "facts": {"peak": -2}}]
    assert got["matched"] == 4 and got["clip"] == ["ab", 3, "", "123"]


def test_more_than_64_sounds_go_out_as_several_requests():
    got = run(r"""
    const list = Array.from({ length: 70 }, (_, i) => slot('sfx_' + i)), p = page({ assets: list });
    await p.token();
    out.ok = (await p.gen.generate(list, { mode: 'make', drafts: 1 })).ok;
    out.sizes = p.api.posted('/jobs').map((b) => b.items.length);
    out.requests = [...new Set(list.map((a) => a.work.request))];
    out.jobs = list.every((a) => a.work.jobs.length === 1);
    """)
    assert got == {"ok": True, "sizes": [64, 6], "requests": ["req-1", "req-2"], "jobs": True}


def test_a_sound_whose_item_cannot_be_put_together_goes_back_alone_and_the_others_are_sent():
    """The page's item() may throw for one sound (it once did for a slot that was to be like a sound with nothing to
    measure). That sound goes back to how it was, the others of the request are sent and paid for without it, and
    what is said is that so many drafts could not be made, not that AI is off. It is said after the page's own words
    at the press (the page says "Making 4", or the assistant's reply, right after it asks), so it is what stays up."""
    got = run(r"""
    const bad = new Set(['sfx_b']);
    const item = (a) => { if (bad.has(a.id)) throw new TypeError('nothing to measure'); return { kind: 'sfx', loop: false, id: a.id, name: a.name, description: '' }; };
    const a = slot('sfx_a'), b = slot('sfx_b'), c = slot('sfx_c'), p = page({ assets: [a, b, c], deps: { item } });
    await p.token();
    const sent = () => p.api.posted('/jobs').map((x) => [x.items.map((i) => i.id), x.drafts, x.expect_credits]);
    const reqs = () => [...p.store.board.keys()].filter((k) => k.startsWith('req:'));
    // One of three, two drafts each.
    let asking = p.gen.generate([a, b, c], { mode: 'make', drafts: 2 });
    out.atOnce = [[a, b, c].map((x) => x.status), !!b.work, p.toasts.slice()];
    out.one = { r: await asking, sent: sent(), jobs: [a, b, c].map((x) => (x.work ? x.work.jobs.length : null)), free: p.gen.free(b), toasts: p.toasts.slice(), reqs: reqs() };
    // Every sound of a request: nothing is sent, and nothing is kept to send later.
    const d = slot('sfx_d'), e = slot('sfx_e'); p.assets.push(d, e); bad.add('sfx_d'); bad.add('sfx_e');
    let from = p.api.calls.length; p.toasts.length = 0;
    asking = p.gen.generate([d, e], { mode: 'make', drafts: 1 });
    out.allAtOnce = [[d, e].map(brief), p.toasts.slice()];
    out.all = { r: await asking, calls: p.api.paths(from), toasts: p.toasts.slice(), reqs: reqs() };
    // Sixty-five sounds are two requests. Nothing of the first can be put together: the second is still sent.
    const many = Array.from({ length: 65 }, (_, i) => slot('sfx_m' + i)); p.assets.push(...many); many.slice(0, 64).forEach((x) => bad.add(x.id));
    from = p.api.posted('/jobs').length; p.toasts.length = 0;
    const r = await p.gen.generate(many, { mode: 'make', drafts: 1 });
    out.batches = { r, sent: sent().slice(from), status: [...new Set(many.slice(0, 64).map((x) => x.status))], last: [many[64].status, many[64].work ? many[64].work.jobs.length : null], toasts: p.toasts.slice() };
    // What goes for the whole request (the examples) cannot be put together: none of it is sent.
    const f = slot('sfx_f'), q = page({ assets: [f], deps: { examples: () => { throw new TypeError('no patch'); } } });
    await q.token();
    out.whole = [await q.gen.generate([f], { mode: 'make', drafts: 3 }), q.api.posted('/jobs').length, brief(f), q.toasts];
    """)
    assert got["atOnce"] == [["working", "pending", "working"], False, []]
    assert got["one"] == {"r": {"ok": True}, "sent": [[["sfx_a", "sfx_c"], 2, 4]], "jobs": [2, None, 2], "free": True, "toasts": ["genFailed:2"], "reqs": []}
    back = {"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": False}
    assert got["allAtOnce"] == [[back, back], []]
    assert got["all"] == {"r": {"ok": False, "reason": "body"}, "calls": [], "toasts": ["genFailed:2"], "reqs": []}
    assert got["batches"] == {"r": {"ok": False, "reason": "body"}, "sent": [[["sfx_m64"], 1, 1]], "status": ["pending"], "last": ["working", 1], "toasts": ["genFailed:64"]}
    assert got["whole"] == [{"ok": False, "reason": "body"}, 0, back, ["genFailed:3"]]


def test_sounds_asked_for_together_are_one_request_in_which_each_has_its_own_words():
    """An answer of the assistant may change many sounds, each in other words. They go out as one POST (the API counts
    requests, ten a minute), and every sound's item and job record carry that sound's own words."""
    got = run(r"""
    const made = (id) => slot(id, { status: 'draft', versions: [oldVersion('v-' + id)] });
    const list = [made('sfx_a'), made('sfx_b'), made('sfx_c')], p = page({ assets: list });
    await p.token();
    const words = new Map([[list[0], 'brighter'], [list[1], 'shorter']]);          // none for the third
    out.ok = (await p.gen.generate(list, { mode: 'revise', text: (a) => words.get(a), drafts: 2 })).ok;
    out.posts = p.api.posted('/jobs').map((b) => [b.items.map((i) => [i.id, i.mode, i.change]), b.drafts, b.expect_credits]);
    out.records = list.map((a) => [a.work.request, a.work.text, a.work.jobs.length]);
    for (const id of p.api.jobs.keys()) p.api.finish(id);
    await advance(0);
    out.notes = list.map((a) => a.drafts.map((v) => v.note.text));
    out.status = list.map((a) => a.status);
    """)
    assert got["ok"] is True
    assert got["posts"] == [[[["sfx_a", "revise", "brighter"], ["sfx_b", "revise", "shorter"], ["sfx_c", "revise", ""]], 2, 6]]
    assert got["records"] == [["req-1", "brighter", 2], ["req-1", "shorter", 2], ["req-1", "", 2]]
    assert got["notes"] == [["brighter", "brighter"], ["shorter", "shorter"], ["", ""]] and got["status"] == ["review"] * 3


def test_an_answer_the_api_did_not_write_leaves_the_request_to_be_picked_up_again():
    """The server took the request, but what came back was not its answer: a proxy's 502 or 504, or a 200 cut short.
    That is no refusal. The record and the stored words stay, and the server is asked what it knows of the request."""
    got = run(r"""
    const answers = { 502: () => ({ status: 502, headers: { get: () => null }, json: async () => { throw new Error('<html>'); } }),
      504: () => ({ status: 504, headers: { get: () => null }, json: async () => ({ message: 'Gateway Timeout' }) }),
      cut: () => ({ status: 200, headers: { get: () => null }, json: async () => { throw new Error('Unexpected end of JSON input'); } }),
      empty: () => ({ status: 200, headers: { get: () => null }, json: async () => ({ batch: 'b' }) }) };
    out.cases = {};
    for (const kind of Object.keys(answers)) {
      const api = fakeApi(); let mangle = true;
      const a = slot('sfx_a'), p = page({ assets: [a], api, deps: { fetch: async (url, init) => { const r = await api.fetch(url, init); return mangle && url.endsWith('/jobs') ? answers[kind]() : r; } } });
      await p.token();
      const result = await p.gen.generate([a], { mode: 'make', drafts: 1 }), request = a.work.request;
      const kept = [a.status, work(a).jobs.length, p.store.board.has('req:' + request), JSON.parse(p.store.board.get('board')).assets[0].status, p.toasts.slice(), api.jobs.get('job1').status];
      mangle = false;
      await advance(4999); const early = api.paths().filter((x) => x.startsWith('POST')).length;
      await advance(1);                                         // five seconds on, the server is asked about the request
      const found = [api.posted('/jobs/status').find((x) => x.request_id).request_id === request, work(a).jobs, p.store.board.has('req:' + request), api.posted('/jobs').length, api.posted('/jobs/cancel').length];
      api.finish('job1');
      await advance(1500);
      out.cases[kind] = { result, kept, early, found, after: brief(a), jobs: api.jobs.size };
    }
    """)
    for kind in ("502", "504", "cut", "empty"):
        case = got["cases"][kind]
        assert case["result"] == {"ok": False, "pending": True, "reason": "offline"}, kind
        assert case["kept"] == ["working", 0, True, "working", [], "queued"], kind
        assert case["early"] == 1, kind                         # only the POST itself
        assert case["found"] == [True, [{"id": "job1", "k": 1, "got": False}], False, 1, 0], kind
        assert case["after"] == {"status": "draft", "versions": ["job1"], "drafts": [], "pick": -1, "work": False} and case["jobs"] == 1, kind


def test_nothing_is_sent_in_another_persons_name_when_the_token_changes_before_the_post():
    got = run(r"""
    const me = tokenOf('acct', 'acct:me');
    // The board is still being written when the host page hands in another person's token.
    const a = slot('sfx_a'), p = page({ assets: [a] });
    await p.token('acct', 'acct:me');
    const save = p.store.saveBoard; let swapped = false;
    p.store.saveBoard = async () => { if (!swapped) { swapped = true; await p.token('acct', 'acct:other'); } return save(); };
    out.first = [await p.gen.generate([a], { mode: 'make', drafts: 1 }), brief(a), p.api.posted('/jobs').length, [...p.store.board.keys()].filter((k) => k.startsWith('req:')), p.toasts.slice()];
    out.disk = JSON.parse(p.store.board.get('board')).assets.map((x) => [x.status, 'work' in x]);
    // The token ran out, and the one that comes in its place is another person's: the request is not sent with it.
    const b = slot('sfx_b'), q = page({ assets: [b] });
    await q.token('acct', 'acct:me');
    q.api.deny = (call) => call.path === '/jobs';
    const asked = q.gen.generate([b], { mode: 'make', drafts: 1 });
    await settle();
    out.waiting = [b.status, q.posts.slice()];
    await q.token('acct', 'acct:other');
    out.second = [await asked, brief(b), q.api.calls.filter((c) => c.path === '/jobs').map((c) => (c.token === me ? 'me' : 'other')), q.gen.paused, q.toasts.slice()];
    // A password session is one person whatever its sub: a newer session's token still sends the request.
    const c = slot('sfx_c'), r = page({ assets: [c] });
    await r.token('pw', 'pw:one');
    const save3 = r.store.saveBoard; let swapped3 = false;
    r.store.saveBoard = async () => { if (!swapped3) { swapped3 = true; await r.token('pw', 'pw:two'); } return save3(); };
    out.third = [(await r.gen.generate([c], { mode: 'make', drafts: 1 })).ok, r.api.posted('/jobs').length, work(c).jobs.length];
    """)
    back = {"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": False}
    assert got["first"] == [{"ok": False, "reason": "other"}, back, 0, [], []] and got["disk"] == [["pending", False]]
    assert got["waiting"] == ["working", ["asset:token?"]]
    assert got["second"] == [{"ok": False, "reason": "other"}, back, ["me"], False, []]
    assert got["third"] == [True, 1, 1]


def test_gen_js_reads_in_browsers_without_look_behind_and_still_mends_half_character_pairs():
    # A look-behind in a regular expression is a syntax error in older Safari: the whole file, and with it the room, would not load.
    assert "(?<" not in (ROOT / "gen.js").read_text(encoding="utf-8")
    got = run(r"""
    const codes = (s) => [...s].map((c) => c.codePointAt(0));
    out.clip = [codes(G.clip('a\udc00b', 9)), codes(G.clip('a\ud83db', 9)), codes(G.clip('😀\ud83d', 9)), codes(G.clip('\udc00😀', 9)), codes(G.clip('😀😀', 3)), G.clip('plain', 9)];
    const base = (source) => G.shapeItem('r', { base: { source, seconds: 1, facts: { peak: -3 } }, change: 'x' }, 'revise').base;
    out.base = [Object.keys(base('ok 😀')), Object.keys(base('half \ud83d')), Object.keys(base('half \udc00 low'))];
    out.examples = G.shapeExamples([{ name: 'a', kind: 'sfx', source: 'fine 😀' }, { name: 'b', kind: 'sfx', source: 'bad \udc00' }]).map((e) => e.name);
    """)
    assert got["clip"] == [[97, 0xFFFD, 98], [97, 0xFFFD, 98], [0x1F600, 0xFFFD], [0xFFFD, 0x1F600], [0x1F600], "plain"]
    assert got["base"] == [["source", "seconds", "bpm"], ["facts"], ["facts"]] and got["examples"] == ["a"]


# ---------- the poller ----------

def test_done_becomes_a_draft_and_counts_as_received_only_when_every_blob_is_saved():
    got = run(r"""
    const a = slot('bgm_a', { music: true }), p = page({ assets: [a] });
    await p.token();
    await p.gen.generate([a], { mode: 'make', drafts: 1 });
    const job = a.work.jobs[0], gotAt = [];
    const save = p.store.saveBlob; p.store.saveBlob = async (key, blob) => { gotAt.push([key, job.got, p.store.held.has(key)]); return save(key, blob); };
    await advance(0);
    p.api.set('job1', { status: 'running', progress: 0.4 });
    const from = p.api.calls.length;
    await advance(1500);
    out.making = [a.status, a.progress, a.drafts.length];
    p.api.finish('job1', 2);
    await advance(1500);
    out.calls = p.api.paths(from);
    out.gotAt = gotAt;
    out.after = brief(a);
    const v = a.versions[0];
    out.version = { ...v, peaks: v.peaks.length, measure: Object.keys(v.measure).length > 5 };
    out.sums = [v.sha256 === sha(p.api.jobs.get('job1').wav), v.bytes === p.api.jobs.get('job1').wav.length, v.stems.every((s, i) => s.sha256 === sha(p.api.jobs.get('job1').stems[i].wav))];
    out.audio = [...p.store.audio.keys()].sort();
    out.sameBytes = sha(new Uint8Array(await p.store.audio.get('ver:job1').arrayBuffer())) === sha(p.api.jobs.get('job1').wav);
    out.disk = JSON.parse(p.store.board.get('board')).assets[0];
    out.disk = [out.disk.status, out.disk.versions.map((x) => x.id), 'work' in out.disk];
    out.posts = p.posts; out.done = p.done; out.toasts = p.toasts;
    const quiet = p.api.calls.length;
    await advance(10000);
    out.stopped = p.api.calls.length === quiet;          // nothing left to wait for: the poller is off
    """)
    assert got["making"] == ["working", 0.4, 0]
    assert got["calls"] == ["POST /jobs/status", "POST /jobs/status", "GET /jobs/job1/sound", "GET /jobs/job1/stems/1", "GET /jobs/job1/stems/2", "POST /jobs/status"]
    assert got["gotAt"] == [["ver:job1", False, True], ["ver:job1:s1", False, True], ["ver:job1:s2", False, True]]
    assert got["after"] == {"status": "draft", "versions": ["job1"], "drafts": [], "pick": -1, "work": False}
    v = got["version"]
    assert v["at"] >= 1700000000000 and v["peaks"] == 200 and v["measure"] is True
    assert {k: v[k] for k in ("id", "engine", "job", "parent", "draft", "source", "prompt", "model", "bpm", "key", "rate", "channels", "bits", "note", "issues")} == {
        "id": "job1", "engine": "nkido", "job": "job1", "parent": None, "draft": {"k": 1, "n": 1}, "source": "SOURCE job1", "prompt": "PROMPT job1", "model": "model-x",
        "bpm": None, "key": "ver:job1", "rate": 48000, "channels": 1, "bits": 16, "note": {"key": "fromPrompt"}, "issues": []}
    assert v["sources"] == [{"name": "nkido (Akkado, Cedar)", "license": "MIT", "holder": "Moritz Laass", "use": "Sound synthesis engine"}]
    assert [(s["label"], s["key"]) for s in v["stems"]] == [("part 1", "ver:job1:s1"), ("part 2", "ver:job1:s2")]
    assert got["sums"] == [True, True, True] and got["audio"] == ["ver:job1", "ver:job1:s1", "ver:job1:s2"] and got["sameBytes"] is True
    assert got["disk"] == ["draft", ["job1"], False]
    assert got["posts"] == ["asset:account"] and got["done"] == [["bgm_a", 1]] and got["toasts"] == [] and got["stopped"] is True


def test_a_draft_whose_sound_is_not_on_disk_plays_from_memory_and_is_fetched_again_next_visit():
    got = run(r"""
    const a = slot('sfx_a'), p = page({ assets: [a] });
    await p.token();
    await p.gen.generate([a], { mode: 'make', drafts: 1 });
    p.api.finish('job1', 1);
    p.store.failBlob = (key) => key === 'ver:job1:s1';
    await advance(0);
    out.first = [brief(a), work(a).jobs, [...p.store.held.keys()], [...p.store.saved]];
    const quiet = p.api.calls.length;
    await advance(6000);
    out.quiet = p.api.calls.length === quiet;            // it is not asked for again on this visit
    out.disk = JSON.parse(p.store.board.get('board')).assets[0].work.jobs;
    // Next visit: the record still names the job, and the version without its sound is not there (store.mend drops it).
    const q = reload(p); q.assets[0].versions = []; q.assets[0].status = 'pending';
    await q.token();
    await advance(0);
    out.second = [brief(q.assets[0]), [...q.store.saved].sort()];
    // Had the sound reached the disk later on the first visit (a save that found room), check() would have counted it.
    p.store.failBlob = () => false;
    for (const [key, blob] of [...p.store.held]) await p.store.saveBlob(key, blob);
    out.check = [p.gen.check(), brief(a)];
    """)
    assert got["first"] == [{"status": "draft", "versions": ["job1"], "drafts": [], "pick": -1, "work": True}, [{"id": "job1", "k": 1, "got": False}], ["ver:job1:s1"], ["ver:job1"]]
    assert got["quiet"] is True and got["disk"] == [{"id": "job1", "k": 1, "got": False}]
    assert got["second"] == [{"status": "draft", "versions": ["job1"], "drafts": [], "pick": -1, "work": False}, ["ver:job1", "ver:job1:s1"]]
    assert got["check"] == [True, {"status": "draft", "versions": ["job1"], "drafts": [], "pick": -1, "work": False}]


def test_drafts_of_a_made_sound_wait_for_a_pick_and_a_sound_whose_drafts_all_failed_goes_back():
    got = run(r"""
    const a = slot('sfx_a', { status: 'approved', versions: [oldVersion('v1')] }), b = slot('sfx_b', { status: 'flagged', versions: [oldVersion('v2')] }), c = slot('sfx_c');
    const p = page({ assets: [a, b, c] });
    await p.token();
    await p.gen.generate([a, b], { mode: 'revise', text: 'brighter', drafts: 2 });     // jobs 1, 2 for a and 3, 4 for b
    await p.gen.generate([c], { mode: 'make', text: 'a soft click', drafts: 3 });      // jobs 5, 6, 7
    await advance(0);
    p.api.finish('job2'); p.api.set('job3', { status: 'failed', refund: 'pending' }); p.api.set('job4', { status: 'failed', refund: 'done' });
    await advance(1500);
    out.mid = [brief(a), brief(b), p.toasts.slice()];
    p.api.finish('job1');
    for (const id of ['job7', 'job5', 'job6']) p.api.finish(id);
    await advance(1500);
    out.a = brief(a); out.c = brief(c);
    out.notes = [a.drafts.map((v) => v.note), c.drafts.map((v) => v.note), a.drafts.map((v) => [v.parent, v.draft])];
    out.done = p.done; out.posts = p.posts.length;
    """)
    # b lost both drafts: it is flagged again, as before, and the one look says so in one sentence.
    assert got["mid"] == [{"status": "working", "versions": ["v1"], "drafts": ["job2"], "pick": -1, "work": True},
                          {"status": "flagged", "versions": ["v2"], "drafts": [], "pick": -1, "work": False}, ["genFailed:2 genRefunded:2"]]
    assert got["a"] == {"status": "review", "versions": ["v1"], "drafts": ["job1", "job2"], "pick": 0, "work": False}
    assert got["c"] == {"status": "review", "versions": [], "drafts": ["job5", "job6", "job7"], "pick": 0, "work": False}
    assert got["notes"] == [[{"key": "draft", "text": "brighter", "k": 1}, {"key": "draft", "text": "brighter", "k": 2}],
                            [{"key": "draft", "text": "a soft click", "k": k} for k in (1, 2, 3)], [["v1", {"k": 1, "n": 2}], ["v1", {"k": 2, "n": 2}]]]
    assert got["done"] == [["sfx_b", 0], ["sfx_a", 2], ["sfx_c", 3]] and got["posts"] == 2


def test_the_poller_looks_every_second_and_a_half_and_less_often_when_hidden_or_far_back_in_the_queue():
    got = run(r"""
    const a = slot('sfx_a'), b = slot('sfx_b'), p = page({ assets: [a, b] });
    await p.token();
    await p.gen.generate([a, b], { mode: 'make', drafts: 1 });
    const looks = () => p.api.paths().filter((x) => x === 'POST /jobs/status').length;
    await advance(0); out.first = looks();
    await advance(1499); out.early = looks();
    await advance(1); out.onTime = looks();
    p.api.set('job1', { position: 13 }); p.api.set('job2', { position: 40 });
    await advance(1500); const far = looks();                 // this look learns that both wait far back
    await advance(2999); out.farEarly = looks() - far;
    await advance(1); out.far = looks() - far;
    p.api.set('job1', { position: 12 });
    await advance(3000); const near = looks();                // one of them is near now
    await advance(1500); out.near = looks() - near;
    p.hidden = true;
    await advance(1500); const hid = looks();                 // the look after this one comes five seconds later
    await advance(4999); out.hiddenEarly = looks() - hid;
    await advance(1); out.hidden = looks() - hid;
    out.oneRequest = p.api.posted('/jobs/status').every((b) => b.ids.length === 2);
    """)
    assert got == {"first": 1, "early": 1, "onTime": 2, "farEarly": 0, "far": 1, "near": 1, "hiddenEarly": 0, "hidden": 1, "oneRequest": True}


def test_wrong_bytes_are_fetched_once_more():
    got = run(r"""
    const a = slot('sfx_a'), b = slot('sfx_b'), p = page({ assets: [a, b] });
    await p.token();
    await p.gen.generate([a, b], { mode: 'make', drafts: 1 });
    p.api.finish('job1'); p.api.finish('job2');
    let bad = { job1: 1, job2: 99 };
    p.api.hook = (call, h) => { const m = /^\/jobs\/(job\d)\/sound$/.exec(call.path); if (m && bad[m[1]]-- > 0) return h.raw(new Uint8Array([1, 2, 3])); };
    await advance(0);
    out.fetches = ['job1', 'job2'].map((id) => p.api.paths().filter((x) => x === 'GET /jobs/' + id + '/sound').length);
    out.a = brief(a);
    // Wrong twice: nothing of it is kept, it is said once, and its id stays so that a later visit can try again.
    out.b = [brief(b), work(b).jobs, p.toasts, [...p.store.audio.keys()]];
    const quiet = p.api.calls.length;
    await advance(6000);
    out.quiet = p.api.calls.length === quiet;
    // The record that is left does not lock the sound: it can be asked for again on this visit, and that lets the bad job go.
    p.api.hook = null;
    out.again = [p.gen.free(b), p.gen.free(a), (await p.gen.generate([b], { mode: 'make', drafts: 1 })).ok, work(b).jobs.map((j) => j.id), b.status, p.api.posted('/jobs').length];
    p.api.finish('job3');
    await advance(1500);
    out.made = [brief(b), p.gen.free(b)];
    """)
    assert got["fetches"] == [2, 2] and got["a"] == {"status": "draft", "versions": ["job1"], "drafts": [], "pick": -1, "work": False}
    assert got["b"] == [{"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": True}, [{"id": "job2", "k": 1, "got": False}], ["genFailed:1"], ["ver:job1"]]
    assert got["quiet"] is True
    assert got["again"] == [True, True, True, ["job3"], "working", 2]
    assert got["made"] == [{"status": "draft", "versions": ["job3"], "drafts": [], "pick": -1, "work": False}, True]


def test_results_that_are_gone_are_said_as_refunded_or_as_lost_and_never_both():
    got = run(r"""
    const mk = (id) => slot(id, { status: 'draft', versions: [oldVersion('v-' + id)] });
    const a = mk('sfx_a'), b = mk('sfx_b'), c = mk('sfx_c'), d = mk('sfx_d'), p = page({ assets: [a, b, c, d] });
    await p.token();
    await p.gen.generate([a], { mode: 'revise', text: 'x', drafts: 1 });
    p.api.set('job1', { status: 'gone', refund: 'done' });
    await advance(0);
    out.refunded = [p.toasts.slice(), brief(a)];
    await p.gen.generate([b], { mode: 'revise', text: 'x', drafts: 1 });
    p.api.set('job2', { status: 'gone', refund: 'none' });
    await advance(0);
    out.lost = [p.toasts.slice(1), brief(b)];
    await p.gen.generate([c], { mode: 'revise', text: 'x', drafts: 1 });
    p.api.jobs.delete('job3');
    await advance(0);
    out.unknown = [p.toasts.slice(2), brief(c)];
    // Not this token's to see: no word, no request about it, and the record stays for whoever it belongs to.
    await p.gen.generate([d], { mode: 'revise', text: 'x', drafts: 1 });
    p.api.set('job4', { status: 'forbidden', refund: 'none' });
    await advance(0);
    const quiet = p.api.calls.length;
    await advance(6000);
    out.forbidden = [p.toasts.slice(3), brief(d), work(d).jobs, p.api.calls.length === quiet];
    """)
    back = {"status": "draft", "drafts": [], "pick": -1, "work": False}
    assert got["refunded"] == [["genRefunded:1"], {**back, "versions": ["v-sfx_a"]}]
    assert got["lost"] == [["genLost:1"], {**back, "versions": ["v-sfx_b"]}]
    assert got["unknown"] == [["genLost:1"], {**back, "versions": ["v-sfx_c"]}]
    assert got["forbidden"] == [[], {"status": "working", "versions": ["v-sfx_d"], "drafts": [], "pick": -1, "work": True}, [{"id": "job4", "k": 1, "got": False}], True]


def test_three_notices_of_one_look_are_one_sentence_and_wait_for_a_toast_with_a_button():
    got = run(r"""
    const a = slot('sfx_a', { status: 'draft', versions: [oldVersion('v1')] }), p = page({ assets: [a] });
    await p.token();
    await p.gen.generate([a], { mode: 'revise', text: 'x', drafts: 3 });
    p.api.set('job1', { status: 'failed', refund: 'none' }); p.api.set('job2', { status: 'gone', refund: 'done' }); p.api.set('job3', { status: 'gone', refund: 'none' });
    p.busy = true;                                     // an answer with an undo button is showing
    await advance(0);
    out.held = p.toasts.slice();
    await advance(2000);
    out.still = p.toasts.slice();
    p.busy = false;
    await advance(500);
    out.said = p.toasts.slice(); out.after = brief(a);
    """)
    assert got["held"] == [] and got["still"] == []
    assert got["said"] == ["genFailed:1 genRefunded:1 genLost:1"]
    assert got["after"] == {"status": "draft", "versions": ["v1"], "drafts": [], "pick": -1, "work": False}


def test_a_429_rests_for_as_long_as_the_server_asks():
    got = run(r"""
    const a = slot('sfx_a'), p = page({ assets: [a] });
    await p.token();
    await p.gen.generate([a], { mode: 'make', drafts: 1 });
    let limited = 1;
    p.api.hook = (call, h) => (call.path === '/jobs/status' && limited-- > 0 ? h.err(429, 'rate', { retry_after: 7 }, { 'Retry-After': '7' }) : null);
    const looks = () => p.api.paths().filter((x) => x === 'POST /jobs/status').length;
    await advance(0); out.first = looks();
    await advance(6999); out.resting = looks();
    await advance(1); out.back = looks();
    out.status = a.status; out.toasts = p.toasts;
    """)
    assert got == {"first": 1, "resting": 1, "back": 2, "status": "working", "toasts": []}


def test_a_sound_the_server_could_not_read_just_then_stays_in_its_record_and_is_fetched_after_the_wait_it_named():
    """GET /jobs/{id}/sound and /stems/{n} may answer 503 busy with retry_after: the file is there and the charge is
    kept, so the draft must not be let go. The next look comes no sooner than the server asked, and fetches it."""
    got = run(r"""
    const gets = (p, from = 0) => p.api.paths(from).filter((x) => x.startsWith('GET /jobs')), looks = (p) => p.api.paths().filter((x) => x === 'POST /jobs/status').length;
    const busyOnce = (p, path) => { let n = 1; p.api.hook = (call, h) => (call.path === path && n-- > 0 ? h.err(503, 'busy', { retry_after: 2 }, { 'Retry-After': '2' }) : null); };
    // The master.
    const a = slot('sfx_a'), p = page({ assets: [a] });
    await p.token();
    await p.gen.generate([a], { mode: 'make', drafts: 1 });
    p.api.finish('job1', 1);
    busyOnce(p, '/jobs/job1/sound');
    await advance(0);
    out.busy = [gets(p), brief(a), work(a).jobs, p.toasts.slice(), looks(p)];
    await advance(1999); out.resting = [gets(p).length, looks(p)];             // the usual second and a half is too soon
    await advance(1);
    out.fetched = [gets(p), brief(a), p.toasts, [...p.store.saved].sort()];
    // A stem: the whole draft waits and is fetched again, master and stems.
    const b = slot('sfx_b'), p2 = page({ assets: [b] });
    await p2.token();
    await p2.gen.generate([b], { mode: 'make', drafts: 1 });
    const id = work(b).jobs[0].id;
    p2.api.finish(id, 2);
    busyOnce(p2, '/jobs/' + id + '/stems/2');
    await advance(0);
    out.stemBusy = [gets(p2).length, brief(b).status, work(b).jobs[0].got];
    await advance(1999); out.stemResting = gets(p2).length;
    await advance(1);
    out.stemFetched = [gets(p2).length, brief(b), b.versions[0].stems.length, p2.toasts];
    // A 429 on a sound: this look fetches nothing more, and both drafts come after the rest.
    const c = slot('sfx_c'), d = slot('sfx_d'), p3 = page({ assets: [c, d] });
    await p3.token();
    await p3.gen.generate([c, d], { mode: 'make', drafts: 1 });
    const [jc, jd] = [work(c).jobs[0].id, work(d).jobs[0].id];
    p3.api.finish(jc); p3.api.finish(jd);
    let limited = 1;
    p3.api.hook = (call, h) => (call.path === '/jobs/' + jc + '/sound' && limited-- > 0 ? h.err(429, 'rate', { retry_after: 7 }, { 'Retry-After': '7' }) : null);
    await advance(0);
    out.limited = [gets(p3).length, c.status, d.status];
    await advance(6999); out.limitedResting = gets(p3).length;
    await advance(1);
    out.limitedBack = [gets(p3).length, brief(c).status, brief(d).status, p3.toasts];
    """)
    waiting = {"status": "working", "versions": [], "drafts": [], "pick": -1, "work": True}
    made = lambda job: {"status": "draft", "versions": [job], "drafts": [], "pick": -1, "work": False}  # noqa: E731
    assert got["busy"] == [["GET /jobs/job1/sound"], waiting, [{"id": "job1", "k": 1, "got": False}], [], 1]
    assert got["resting"] == [1, 1]
    assert got["fetched"] == [["GET /jobs/job1/sound", "GET /jobs/job1/sound", "GET /jobs/job1/stems/1"], made("job1"), [], ["ver:job1", "ver:job1:s1"]]
    assert got["stemBusy"] == [3, "working", False] and got["stemResting"] == 3
    assert got["stemFetched"][0] == 6 and got["stemFetched"][1]["status"] == "draft" and got["stemFetched"][1]["work"] is False and got["stemFetched"][2:] == [2, []]
    assert got["limited"] == [1, "working", "working"] and got["limitedResting"] == 1
    assert got["limitedBack"] == [3, "draft", "draft", []]


def test_a_sound_that_came_whole_is_kept_when_the_look_after_it_is_turned_away_and_is_not_fetched_twice():
    """After master and stems have come, the status is read once more. A 429 there, or an answer the API did not
    write, must not throw the bytes away: the next look builds the draft from them and from what it is told of the
    job, and fetches no file a second time."""
    got = run(r"""
    const gets = (p, from = 0) => p.api.paths(from).filter((x) => x.startsWith('GET /jobs'));
    // Once a file of the job has gone out, the next status read is answered by `answer`.
    const turnAway = (p, answer) => { let out = false, n = 1; p.api.hook = (call, h) => { if (call.method === 'GET' && call.path.startsWith('/jobs/')) out = true; return call.path === '/jobs/status' && out && n-- > 0 ? answer(h) : null; }; };
    const a = slot('bgm_a', { music: true }), p = page({ assets: [a] });
    await p.token();
    await p.gen.generate([a], { mode: 'make', drafts: 1 });
    p.api.finish('job1', 2);
    turnAway(p, (h) => h.err(429, 'rate', { retry_after: 7 }, { 'Retry-After': '7' }));
    const from = p.api.calls.length;
    await advance(0);
    out.limited = [p.api.paths(from), brief(a), work(a).jobs, p.toasts.slice()];
    await advance(6999); out.resting = p.api.paths(from).length;
    await advance(1);
    out.calls = p.api.paths(from);
    out.after = brief(a);
    const v = a.versions[0] || { stems: [] }, job = p.api.jobs.get('job1');
    out.version = [v.source, v.prompt, v.stems.map((s) => s.label), v.bytes === job.wav.length, v.sha256 === sha(job.wav)];
    out.saved = [...p.store.saved].sort();
    const onDisk = async (key) => sha(new Uint8Array(await p.store.audio.get(key).arrayBuffer()));
    out.sameBytes = out.saved.length === 3 && [await onDisk('ver:job1') === sha(job.wav), await onDisk('ver:job1:s1') === sha(job.stems[0].wav), await onDisk('ver:job1:s2') === sha(job.stems[1].wav)];
    out.toasts = p.toasts;
    // An answer that is not the API's (a proxy's page): the same, on the usual next look.
    const b = slot('sfx_b'), p2 = page({ assets: [b] });
    await p2.token();
    await p2.gen.generate([b], { mode: 'make', drafts: 1 });
    const id = work(b).jobs[0].id;
    p2.api.finish(id, 1);
    turnAway(p2, (h) => h.res(502));
    await advance(0);
    out.cut = [gets(p2).length, brief(b).status, work(b).jobs[0].got];
    await advance(1500);
    out.cutBack = [gets(p2).length, brief(b), b.versions[0] ? b.versions[0].source : null, p2.toasts];
    """)
    waiting = {"status": "working", "versions": [], "drafts": [], "pick": -1, "work": True}
    made = {"status": "draft", "versions": ["job1"], "drafts": [], "pick": -1, "work": False}
    files = ["GET /jobs/job1/sound", "GET /jobs/job1/stems/1", "GET /jobs/job1/stems/2"]
    assert got["limited"] == [["POST /jobs/status", *files, "POST /jobs/status"], waiting, [{"id": "job1", "k": 1, "got": False}], []]
    assert got["resting"] == 5                                                # it rests for as long as the 429 asked
    assert got["calls"] == ["POST /jobs/status", *files, "POST /jobs/status", "POST /jobs/status"]     # one look more, and no file again
    assert got["after"] == made and got["version"] == ["SOURCE job1", "PROMPT job1", ["part 1", "part 2"], True, True]
    assert got["saved"] == ["ver:job1", "ver:job1:s1", "ver:job1:s2"] and got["sameBytes"] == [True, True, True] and got["toasts"] == []
    assert got["cut"] == [2, "working", False]
    assert got["cutBack"] == [2, made, "SOURCE job1", []]


def test_bytes_kept_for_the_next_look_are_let_go_as_soon_as_their_sound_is_taken_off_the_board():
    """The bytes of a finished job are kept when the status read after them is turned away, for the look that follows.
    A sound moved to the trash has no look to follow: with nothing else being made the poller stops, and the bytes
    used to stay in memory until something else was asked for or the token was renewed. They go with the job's record,
    whether the sound leaves while that read is on its way or after it was turned away. Node runs with --expose-gc:
    a WeakRef to a buffer the API handed over is empty once nothing holds the buffer."""
    got = run(r"""
    const held = async (refs) => { for (let i = 0; i < 5; i++) { await new Promise((ok) => realTimeout(ok, 20)); global.gc(); } await new Promise((ok) => realTimeout(ok, 20)); return refs.map((r) => !!r.deref()); };
    // when the sound goes to the trash: 'during' the status read that is turned away, 'after' it (before the next
    // look), or 'answered': during a read that is answered, which never kept anything.
    async function story(when) {
      const api = fakeApi(), refs = [];
      const a = slot('sfx_a'), p = page({ assets: [a], api, deps: { fetch: async (url, init) => {
        const r = await api.fetch(url, init);
        if (init.method === 'GET' && r.status === 200) { const real = r.arrayBuffer; r.arrayBuffer = async () => { const buf = await real(); refs.push(new WeakRef(buf)); return buf; }; }
        return r;
      } } });
      const trash = () => { p.gen.cancel([a]); p.assets.splice(p.assets.indexOf(a), 1); };
      await p.token();
      await p.gen.generate([a], { mode: 'make', drafts: 1 });
      api.finish('job1', 1);
      let sent = false, n = 1;
      api.hook = (call, h) => {
        if (call.method === 'GET' && call.path.startsWith('/jobs/')) sent = true;
        if (call.path !== '/jobs/status' || !sent || n-- <= 0) return null;
        if (when !== 'after') trash();
        return when === 'answered' ? null : h.err(429, 'rate', { retry_after: 7 }, { 'Retry-After': '7' });
      };
      const from = api.calls.length;
      await advance(0);
      if (when === 'after') { trash(); await settle(); }
      const calls = api.paths(from), now = await held(refs);                // the clock has not moved: no other look has come
      await advance(600000);
      return { calls, watched: refs.length, work: !!a.work, status: a.status, now, later: api.paths(from).length - calls.length };
    }
    out.during = await story('during');
    out.after = await story('after');
    out.answered = await story('answered');
    """, flags=("--expose-gc",))
    calls = ["POST /jobs/status", "GET /jobs/job1/sound", "GET /jobs/job1/stems/1", "POST /jobs/status", "POST /jobs/cancel"]
    gone = {"calls": calls, "watched": 2, "work": False, "status": "pending", "now": [False, False], "later": 0}
    assert got["answered"] == gone
    assert got["during"] == gone
    assert got["after"] == gone


def test_only_the_sounds_that_changed_are_handed_to_the_page_to_draw_again():
    """The page redraws an open sound's view only when that sound is in the list, so a job of another sound ending
    does not take the request being typed there out of its input."""
    got = run(r"""
    const drawn = [], a = slot('sfx_a'), b = slot('sfx_b'), c = slot('sfx_c'), p = page({ assets: [a, b, c], deps: { render: (list) => drawn.push(list.map((x) => x.id)) } });
    await p.token();
    await p.gen.generate([a], { mode: 'make', drafts: 1 });
    await p.gen.generate([b, c], { mode: 'make', drafts: 1 });
    out.asked = drawn.splice(0);
    await advance(0);
    out.looking = drawn.splice(0);                     // a look that ends nothing draws nothing: only the bars move
    p.api.finish('job1');
    await advance(1500);
    out.ended = drawn.splice(0);
    p.api.set('job2', { status: 'failed', refund: 'done' }); p.api.finish('job3');
    await advance(1500);
    out.both = drawn.splice(0);
    """)
    assert got["asked"] == [["sfx_a"], ["sfx_a"], ["sfx_b", "sfx_c"], ["sfx_b", "sfx_c"]]
    assert got["looking"] == [] and got["ended"] == [["sfx_a"]] and got["both"] == [["sfx_b", "sfx_c"]]


def kept_of():
    """app.js's keptOf(a, binned): what the page saves of a sound's status, drafts and pick."""
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    start = app.index("function keptOf(a, binned) {")
    return app[start:app.index("function snapshot() {", start)]


# The board as app.js saves it: keptOf decides what of a sound's drafts goes into the record.
AS_SAVED = r"""
    const bare = (v) => { const { sound, ...rest } = v; return rest; };
    const asSaved = (list) => ({ assets: list.map((x) => { const k = keptOf(x, false); return { ...x, status: k.status, versions: k.versions.map(bare), drafts: k.drafts.map(bare), pick: k.pick }; }) });
"""


def test_a_draft_fetched_again_is_in_the_saved_record_before_its_job_counts_as_received():
    """A visit that could not save two drafts left their ids in the record; the next one fetches them again for a sound
    that is no longer "working". A received (and therefore never refunded) draft must not be on disk as got without
    its record, however early the tab is closed."""
    got = run(kept_of() + AS_SAVED + r"""
    const rec = { request: 'r-1', kind: 'acct', who: whoOf('acct:me'), mode: 'make', text: 'x', n: 2, at: T.wall, before: 'pending', jobs: [{ id: 'job1', k: 1, got: false }, { id: 'job2', k: 2, got: false }] };
    const a = slot('sfx_a', { work: rec }), p = page({ assets: [a] });
    p.snapshot = () => asSaved(p.assets);
    for (const [id, k] of [['job1', 1], ['job2', 2]]) { p.api.jobs.set(id, { id, ref: 'k-sfx_a', k, n: 2, status: 'queued', refund: 'none', stems: [] }); p.api.finish(id); }
    const writes = [], save = p.store.saveBoard; let mid = null;
    p.store.saveBoard = async () => {
      const ok = await save(), x = JSON.parse(p.store.board.get('board')).assets[0], jobs = x.work ? x.work.jobs : [];
      writes.push({ status: x.status, got: jobs.filter((j) => j.got).map((j) => j.id), drafts: x.drafts.map((v) => v.id) });
      if (x.status === 'pending' && jobs.length && jobs.every((j) => j.got)) mid = p.store.board.get('board');
      return ok;
    };
    await p.token(); await advance(0);
    out.writes = writes; out.after = brief(a);
    out.safe = writes.every((w) => w.got.every((id) => w.drafts.includes(id)));
    // The tab was closed right after the second draft was written, before the sound was settled.
    const q = page({ assets: JSON.parse(mid).assets, api: p.api });
    q.snapshot = () => asSaved(q.assets);
    for (const [k, v] of p.store.audio) { q.store.audio.set(k, v); q.store.saved.add(k); }
    out.restored = brief(q.assets[0]);
    const from = p.api.calls.length;
    await q.token(); await advance(0);
    out.settled = [brief(q.assets[0]), p.api.paths(from).filter((x) => x.startsWith('GET /jobs')), JSON.parse(q.store.board.get('board')).assets[0].drafts.map((v) => v.id)];
    """)
    assert got["writes"][0] == {"status": "pending", "got": ["job1"], "drafts": ["job1"]}
    assert got["writes"][1] == {"status": "pending", "got": ["job1", "job2"], "drafts": ["job1", "job2"]}
    assert got["safe"] is True and got["writes"][-1] == {"status": "review", "got": [], "drafts": ["job1", "job2"]}
    review = {"status": "review", "versions": [], "drafts": ["job1", "job2"], "pick": 0, "work": False}
    assert got["after"] == review
    # nothing is fetched twice, and the drafts are put up for a pick instead of being left behind with the record gone
    assert got["restored"] == {"status": "pending", "versions": [], "drafts": ["job1", "job2"], "pick": -1, "work": True}
    assert got["settled"] == [review, [], ["job1", "job2"]]


def test_a_sound_asked_for_again_while_under_review_comes_back_with_a_draft_picked():
    """A sound with no version has no "previous": when the new request fails, it is under review again with the drafts it
    had, and one of them has to be the one heard, also after a reload."""
    got = run(kept_of() + AS_SAVED + r"""
    const draft = (id, k) => ({ id, at: 1, note: null, engine: 'nkido', job: id, draft: { k, n: 2 }, sources: [], measure: { seconds: 1 }, issues: [], peaks: [], key: 'ver:' + id, stems: [] });
    const a = slot('sfx_a', { status: 'review', drafts: [draft('old1', 1), draft('old2', 2)], pick: 1 }), p = page({ assets: [a] });
    p.snapshot = () => asSaved(p.assets);
    await p.token();
    await p.gen.generate([a], { mode: 'make', text: 'again', drafts: 1 });
    const disk = JSON.parse(p.store.board.get('board')).assets[0];
    out.saved = [disk.status, disk.drafts.map((v) => v.id), disk.pick];
    out.binned = keptOf(a, true);
    // The next visit, read from a board an older page wrote without the pick.
    const q = reload(p); q.snapshot = () => asSaved(q.assets);
    q.assets[0].pick = -1;
    await q.token();
    p.api.set('job1', { status: 'failed', refund: 'done' });
    await advance(1500);
    out.after = [brief(q.assets[0]), q.toasts];
    out.idle = keptOf(slot('sfx_x', { status: 'working' }), false).status;     // "working" with no job record is not kept
    """)
    assert got["saved"] == ["working", ["old1", "old2"], 1]
    assert got["binned"] == {"status": "pending", "versions": [], "drafts": [], "pick": -1}
    assert got["after"] == [{"status": "review", "versions": [], "drafts": ["old1", "old2"], "pick": 0, "work": False}, ["genFailed:1 genRefunded:1"]]
    assert got["idle"] == "pending"


def test_work_picked_up_in_the_middle_of_a_look_asks_nothing_twice():
    """The host hands in a newer token about every ten minutes, and each one picks work up again. A look that is under
    way has taken a failed job out of its record but not settled the sound yet: that record is not a request without
    an answer, and asking the server about it would bring every job of the request back."""
    got = run(r"""
    const a = slot('sfx_a'), b = slot('sfx_b'), p = page({ assets: [a, b] });
    await p.token();
    await p.gen.generate([a, b], { mode: 'make', drafts: 1 });           // job1 for a, job2 for b
    p.api.set('job1', { status: 'failed', refund: 'done' }); p.api.finish('job2');
    let release; const slow = new Promise((ok) => { release = ok; });
    p.api.hook = (call, h) => (call.path === '/jobs/job2/sound' ? slow.then(() => { p.api.jobs.get('job2').delivered = true; return h.raw(p.api.jobs.get('job2').wav); }) : null);
    await advance(0);                                                    // the look: one failed, the other's sound is slow to come
    out.mid = [work(a).jobs.length, a.status, b.status];
    await p.token('acct', 'acct:me', 'newer');
    await settle();
    out.asked = p.api.posted('/jobs/status').filter((x) => x.request_id).length;
    out.still = [work(a).jobs.length, work(b).jobs.map((j) => j.id)];
    release();
    await advance(0);
    await advance(6000);
    out.after = [brief(a), brief(b), p.toasts, p.api.paths().filter((x) => x === 'GET /jobs/job2/sound').length, p.api.posted('/jobs/cancel').length];
    """)
    assert got["mid"] == [0, "working", "working"] and got["asked"] == 0 and got["still"] == [0, ["job2"]]
    assert got["after"] == [{"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": False},
                            {"status": "draft", "versions": ["job2"], "drafts": [], "pick": -1, "work": False}, ["genFailed:1 genRefunded:1"], 1, 0]


# ---------- the token ----------

def test_only_the_host_pages_own_message_is_a_token_and_only_kind_and_sub_are_read():
    got = run(r"""
    const parent = {}, other = {};
    out.from = [G.fromHost({ source: parent, origin: 'https://olmuse.app' }, parent, 'https://olmuse.app'), G.fromHost({ source: other, origin: 'https://olmuse.app' }, parent, 'https://olmuse.app'),
      G.fromHost({ source: parent, origin: 'https://evil.example' }, parent, 'https://olmuse.app'), G.fromHost(null, parent, 'x')];
    out.read = [G.readToken(tokenOf('acct', 'acct:me')), G.readToken(tokenOf('pw', 'pw:abc')), G.readToken('garbage'), G.readToken(Buffer.from('{"kind":"admin","sub":"x"}').toString('base64url') + '.s')];
    const p = page({ assets: [] });
    out.bad = [await p.gen.token({ token: 'garbage', ttl: 900, api: BASE }), await p.gen.token({ token: tokenOf('pw', 'pw:x'), ttl: 900 }), await p.gen.token(null), p.gen.ready];
    out.good = [await p.token('acct', 'acct:me'), p.gen.identity, whoOf('acct:me')];
    """)
    assert got["from"] == [True, False, False, False]
    assert got["read"] == [{"kind": "acct", "sub": "acct:me"}, {"kind": "pw", "sub": "pw:abc"}, None, None]
    assert got["bad"] == [False, False, False, False]
    assert got["good"][0] is True and got["good"][1] == {"kind": "acct", "who": got["good"][2]} and len(got["good"][2]) == 16


def test_a_newer_token_is_asked_for_a_minute_before_the_one_in_hand_runs_out():
    got = run(r"""
    const p = page({ assets: [] });
    await p.token('acct', 'acct:me', '', 900);
    await advance(839000); out.early = p.posts.slice();
    await advance(1000); out.asked = p.posts.slice();
    await p.token('acct', 'acct:me', 'next', 600);          // the count starts again from the token that came
    await advance(539000); out.early2 = p.posts.length;
    await advance(1000); out.asked2 = p.posts.length;
    """)
    assert got == {"early": [], "asked": ["asset:token?"], "early2": 1, "asked2": 2}


def test_a_401_asks_for_another_token_tries_once_more_and_pauses_when_none_comes():
    got = run(r"""
    const a = slot('sfx_a'), p = page({ assets: [a] });
    await p.token();
    await p.gen.generate([a], { mode: 'make', drafts: 1 });
    const old = tokenOf('acct', 'acct:me'), looks = () => p.api.calls.filter((c) => c.path === '/jobs/status').map((c) => c.token === old ? 'old' : 'new');
    p.api.deny = (call) => call.token === old;                  // the token in hand has run out on the server
    await advance(0);
    out.asked = [p.posts.slice(), looks(), p.gen.paused];
    await advance(4000);
    await p.token('acct', 'acct:me', 'fresh');                  // the host answers within the ten seconds
    out.retried = [looks(), p.gen.paused, p.toasts.slice()];
    await advance(1500);
    out.goesOn = looks();
    // Again, and this time no token comes: after ten seconds everything stops, and it is said once.
    const fresh = tokenOf('acct', 'acct:me', 'fresh');
    p.api.deny = (call) => call.token === old || call.token === fresh;
    const n = looks().length;
    await advance(1500);                                        // this look gets the 401
    await advance(9999); out.waiting = [p.gen.paused, looks().length - n];
    await advance(1);
    out.paused = [p.gen.paused, p.gen.ready, p.toasts.slice(), a.status, p.gen.why()];
    await advance(60000);
    out.resting = looks().length - n;                           // no polling while paused; the tile stays as it is
    out.refused = [(await p.gen.generate([slot('sfx_b')], { mode: 'make', drafts: 1 })).reason, p.toasts.length];
    await p.token('acct', 'acct:me', 'fresh');                  // the same string again is no new token
    out.same = p.gen.paused;
    p.api.finish('job1');
    await p.token('acct', 'acct:me', 'third');
    await advance(0);
    out.resumed = [p.gen.paused, brief(a), p.toasts.length];
    """)
    assert got["asked"] == [["asset:token?"], ["old"], False]
    assert got["retried"] == [["old", "new"], False, []] and got["goesOn"] == ["old", "new", "new"]
    assert got["waiting"] == [False, 1] and got["paused"] == [True, False, ["genPaused"], "working", "genPaused"]
    assert got["resting"] == 1 and got["refused"] == ["genPaused", 2] and got["same"] is True
    assert got["resumed"] == [False, {"status": "draft", "versions": ["job1"], "drafts": [], "pick": -1, "work": False}, 2]


def test_a_second_401_with_the_new_token_pauses_too():
    got = run(r"""
    const a = slot('sfx_a'), p = page({ assets: [a] });
    await p.token();
    await p.gen.generate([a], { mode: 'make', drafts: 1 });
    p.api.deny = (call) => call.path === '/jobs/status';
    await advance(0);
    await p.token('acct', 'acct:me', 'fresh');
    await advance(0);
    out.paused = [p.gen.paused, p.api.paths().filter((x) => x === 'POST /jobs/status').length, p.toasts];
    """)
    assert got["paused"] == [True, 2, ["genPaused"]]


def test_polling_goes_on_when_the_browsers_clock_is_twenty_minutes_ahead():
    got = run(r"""
    T.wall = (1700000900 + 20 * 60) * 1000;                     // by this clock the token (exp 1700000900) ran out long ago
    const a = slot('sfx_a'), p = page({ assets: [a] });
    await p.token();
    out.taken = [(await p.gen.generate([a], { mode: 'make', drafts: 1 })).ok, p.gen.paused];
    p.api.finish('job1');
    await advance(1500);
    out.after = brief(a); out.asked = p.posts.filter((x) => x === 'asset:token?').length;
    """)
    assert got["taken"] == [True, False] and got["after"] == {"status": "draft", "versions": ["job1"], "drafts": [], "pick": -1, "work": False} and got["asked"] == 0


# ---------- picking work up again ----------

def test_a_record_with_ids_is_polled_again_after_a_reload():
    got = run(r"""
    const a = slot('sfx_a', { status: 'draft', versions: [oldVersion('v1')] }), p = page({ assets: [a] });
    await p.token();
    await p.gen.generate([a], { mode: 'revise', text: 'softer', drafts: 2 });
    p.api.finish('job1');
    await advance(0);                                           // the first draft is on disk, the second still being made
    const q = reload(p), b = q.assets[0];
    out.restored = [brief(b), work(b).jobs];
    const from = p.api.calls.length;
    out.before = p.api.calls.length - from;                     // nothing is asked before a token is there
    await q.token();
    await advance(0);
    out.asked = p.api.posted('/jobs/status').at(-1);
    p.api.finish('job2');
    await advance(1500);
    out.after = brief(b); out.resent = p.api.posted('/jobs').length;
    """)
    assert got["restored"] == [{"status": "working", "versions": ["v1"], "drafts": ["job1"], "pick": -1, "work": True}, [{"id": "job1", "k": 1, "got": True}, {"id": "job2", "k": 2, "got": False}]]
    assert got["before"] == 0 and got["asked"] == {"ids": ["job2"]}
    assert got["after"] == {"status": "review", "versions": ["v1"], "drafts": ["job1", "job2"], "pick": 0, "work": False} and got["resent"] == 1


def test_a_record_whose_jobs_all_ended_before_the_reload_is_settled_when_it_is_picked_up():
    got = run(r"""
    const a = slot('sfx_a'), p = page({ assets: [a] });
    await p.token();
    await p.gen.generate([a], { mode: 'make', text: 'x', drafts: 2 });
    p.api.finish('job1'); p.api.finish('job2');
    // The tab went away after the second sound was written and before the sound was settled.
    const save = p.store.saveBoard; let closed = false;
    p.store.saveBoard = async () => { if (closed) return false; if (a.work && a.work.jobs.every((j) => j.got) && a.status === 'working') closed = true; return save(); };
    await advance(0);
    const q = reload(p), b = q.assets[0];
    out.restored = brief(b);
    await q.token(); await advance(0);
    out.after = brief(b);
    """)
    assert got["restored"] == {"status": "working", "versions": [], "drafts": ["job1", "job2"], "pick": -1, "work": True}
    assert got["after"] == {"status": "review", "versions": [], "drafts": ["job1", "job2"], "pick": 0, "work": False}


def test_a_record_without_ids_gets_them_when_the_server_knows_the_request():
    got = run(r"""
    const a = slot('sfx_a'), b = slot('sfx_b'), p = page({ assets: [a, b] });
    await p.token();
    // The request arrived and was taken, but its answer never came back.
    const real = p.api.fetch; let cut = true;
    p.gen = G.create({ store: p.store, assets: () => p.assets, fetch: async (url, init) => { const r = await real(url, init); if (cut && url.endsWith('/jobs')) throw new TypeError('connection lost'); return r; },
      now: () => T.mono, wall: () => T.wall, setTimeout: setT, clearTimeout: clearT, uuid: () => 'req-' + (++T.uuid), sha256: async (x) => sha(x), measure: M, peaks: S.peaksOf,
      project: () => ({ game: 'g' }), item: (x) => ({ kind: 'sfx', id: x.id, name: x.name }), text: (k) => k, toast: (t) => p.toasts.push(t), render: () => {}, post: (t) => p.posts.push(t) });
    await p.token();
    out.sent = await p.gen.generate([a, b], { mode: 'make', drafts: 1 });
    out.kept = [a.status, work(a).jobs, p.store.board.has('req:req-1'), p.toasts.slice()];
    cut = false;
    const q = reload(p);
    await q.token(); await advance(0);
    out.asked = p.api.posted('/jobs/status').find((x) => x.request_id);
    out.ids = q.assets.map((x) => work(x).jobs);
    out.disk = JSON.parse(q.store.board.get('board')).assets.map((x) => x.work.jobs.map((j) => j.id));
    out.words = q.store.board.has('req:req-1'); out.posts = p.api.posted('/jobs').length;
    p.api.finish('job1'); p.api.finish('job2');
    await advance(1500);
    out.after = q.assets.map(brief);
    """)
    assert got["sent"] == {"ok": False, "pending": True, "reason": "offline"} and got["kept"] == ["working", [], True, []]
    assert got["asked"] == {"request_id": "req-1"}
    assert got["ids"] == [[{"id": "job1", "k": 1, "got": False}], [{"id": "job2", "k": 1, "got": False}]] and got["disk"] == [["job1"], ["job2"]]
    assert got["words"] is False and got["posts"] == 1
    assert got["after"] == [{"status": "draft", "versions": ["job1"], "drafts": [], "pick": -1, "work": False}, {"status": "draft", "versions": ["job2"], "drafts": [], "pick": -1, "work": False}]


def test_an_unknown_request_younger_than_ten_minutes_is_sent_again_word_for_word():
    got = run(r"""
    const a = slot('sfx_a'), p = page({ assets: [a] });
    await p.token();
    p.api.down = true;                                          // the request never reached the server
    out.sent = await p.gen.generate([a], { mode: 'make', text: 'x', drafts: 1 });
    const words = p.store.board.get('req:req-1');
    out.kept = [a.status, typeof words];
    await advance(4999); out.early = p.api.calls.length;
    p.api.down = false;
    await advance(1);                                           // five seconds on, this visit finds out by itself
    out.calls = p.api.paths(out.early);
    out.same = p.api.calls.find((c) => c.path === '/jobs' && c.body).body === words && p.api.reqs.get('req-1').body === words;
    out.after = [work(a).jobs, p.store.board.has('req:req-1')];
    // The same after a reload nine minutes later.
    const b = slot('sfx_b'), p2 = page({ assets: [b] });
    await p2.token(); p2.api.down = true;
    await p2.gen.generate([b], { mode: 'make', drafts: 1 });
    const words2 = p2.store.board.get('req:req-2');
    T.wall += 9 * 60000;
    const q = reload(p2); p2.api.down = false;
    await q.token(); await advance(0);
    out.reloaded = [p2.api.paths().filter((x) => x.startsWith('POST')), p2.api.reqs.get('req-2').body === words2, work(q.assets[0]).jobs.length];
    """)
    assert got["sent"] == {"ok": False, "pending": True, "reason": "offline"} and got["kept"] == ["working", "string"]
    assert got["calls"] == ["POST /jobs/status", "POST /jobs", "POST /jobs/status"] and got["same"] is True
    assert got["after"] == [[{"id": "job1", "k": 1, "got": False}], False]
    assert got["reloaded"] == [["POST /jobs", "POST /jobs/status", "POST /jobs", "POST /jobs/status"], True, 1]


def test_an_unknown_request_that_is_old_or_has_lost_its_words_is_cancelled_and_then_put_back():
    got = run(r"""
    const a = slot('sfx_a', { status: 'approved', versions: [oldVersion('v1')] }), b = slot('sfx_b'), p = page({ assets: [a, b] });
    await p.token(); p.api.down = true;
    await p.gen.generate([a], { mode: 'revise', text: 'x', drafts: 1 });       // req-1, old by the time of the reload
    T.wall += 11 * 60000;
    await p.gen.generate([b], { mode: 'make', drafts: 1 });                     // req-2, young, but its words are gone
    p.store.board.delete('req:req-2');
    const q = reload(p); p.api.down = false;
    let seen = null;
    p.api.hook = (call) => { if (call.path === '/jobs/cancel' && !seen) seen = q.assets.map((x) => x.status); };
    const from = p.api.calls.length;
    await q.token(); await advance(0);
    out.calls = p.api.paths(from).filter((x) => x.startsWith('POST'));
    out.cancels = p.api.posted('/jobs/cancel');
    out.atCancel = seen;                                        // the cancel went out before the sound was put back
    out.after = q.assets.map(brief); out.marks = [...p.api.marks].sort();
    out.words = [...q.store.board.keys()].filter((k) => k.startsWith('req:'));
    out.disk = JSON.parse(q.store.board.get('board')).assets.map((x) => [x.status, 'work' in x]);
    // A request the server has as cancelled goes back the same way, without being asked for again.
    const c = slot('sfx_c'), p3 = page({ assets: [c] });
    await p3.token(); p3.api.down = true;
    await p3.gen.generate([c], { mode: 'make', drafts: 1 });
    p3.api.marks.add('req-3');
    const q3 = reload(p3); p3.api.down = false;
    await q3.token(); await advance(0);
    out.cancelled = [brief(q3.assets[0]), p3.api.paths().filter((x) => x.startsWith('POST'))];
    """)
    assert got["calls"] == ["POST /jobs/status", "POST /jobs/cancel", "POST /jobs/status", "POST /jobs/cancel"]
    assert got["cancels"] == [{"request_id": "req-1"}, {"request_id": "req-2"}] and got["atCancel"] == ["working", "working"]
    assert got["after"] == [{"status": "approved", "versions": ["v1"], "drafts": [], "pick": -1, "work": False}, {"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": False}]
    assert got["marks"] == ["req-1", "req-2"] and got["words"] == [] and got["disk"] == [["approved", False], ["pending", False]]
    assert got["cancelled"] == [{"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": False}, ["POST /jobs", "POST /jobs/status"]]


def test_a_request_sent_again_that_the_server_has_as_cancelled_goes_back_and_is_not_sent_a_third_time():
    """The cancel reached the server after the look that found the request unknown, so the words go out once more
    and come back 410 request_cancelled: the sound is as it was before, with the server's sentence, and that is the end of it."""
    got = run(r"""
    const a = slot('sfx_a', { status: 'approved', versions: [oldVersion('v1')] }), p = page({ assets: [a] });
    await p.token(); p.api.down = true;
    await p.gen.generate([a], { mode: 'revise', text: 'x', drafts: 1 });       // never reached the server
    p.api.down = false;
    p.api.hook = (call) => { if (call.path === '/jobs') p.api.marks.add('req-1'); return null; };
    const from = p.api.calls.length;
    await advance(5000);
    out.calls = p.api.paths(from);
    out.after = [brief(a), p.toasts.slice(), p.store.board.has('req:req-1'), JSON.parse(p.store.board.get('board')).assets.map((x) => [x.status, 'work' in x])];
    await advance(60000);
    out.quiet = p.api.paths(from).length;
    """)
    assert got["calls"] == ["POST /jobs/status", "POST /jobs"]
    assert got["after"] == [{"status": "approved", "versions": ["v1"], "drafts": [], "pick": -1, "work": False}, ["server says request_cancelled"], False, [["approved", False]]]
    assert got["quiet"] == 2


def test_records_of_someone_else_are_left_alone_and_a_password_session_goes_by_kind_only():
    got = run(r"""
    const rec = (kind, sub, more) => ({ request: 'r-' + sub, kind, who: whoOf(sub), mode: 'make', text: '', n: 1, at: T.wall, before: 'pending', jobs: [], ...more });
    const mine = slot('sfx_mine', { status: 'working', work: rec('acct', 'acct:me', { jobs: [{ id: 'jobA', k: 1, got: false }] }) });
    const theirs = slot('sfx_theirs', { status: 'working', work: rec('acct', 'acct:other', { jobs: [{ id: 'jobB', k: 1, got: false }] }) });
    const noIds = slot('sfx_noids', { status: 'working', work: rec('acct', 'acct:other') });
    const pw = slot('sfx_pw', { status: 'working', work: rec('pw', 'pw:session-1', { jobs: [{ id: 'jobC', k: 1, got: false }] }) });
    const p = page({ assets: [mine, theirs, noIds, pw] });
    for (const [id, ref] of [['jobA', 'k-sfx_mine'], ['jobB', 'k-sfx_theirs'], ['jobC', 'k-sfx_pw']]) p.api.jobs.set(id, { id, ref, k: 1, n: 1, status: 'queued', refund: 'none', stems: [] });
    const asked = () => p.api.posted('/jobs/status').flatMap((b) => b.ids || [b.request_id]);
    await p.token('acct', 'acct:me'); await p.gen.attach(); await advance(3000);
    out.me = [[...new Set(asked())], p.api.posted('/jobs/cancel').length, p.api.posted('/jobs').length, p.toasts.slice()];
    out.untouched = [brief(theirs), work(theirs).jobs, brief(noIds), brief(pw)];
    // The other account comes back on this browser: its records are picked up, the old one (never seen by the server) is cancelled.
    T.wall += 11 * 60000;
    const from = p.api.calls.length;
    await p.token('acct', 'acct:other'); await advance(1500);
    out.other = [[...new Set(p.api.calls.slice(from).filter((c) => c.path === '/jobs/status').flatMap((c) => JSON.parse(c.body).ids || [JSON.parse(c.body).request_id]))], brief(noIds), brief(mine)];
    // A password session has a new sub on every reload, so its records go by kind alone, and never to an account.
    const from2 = p.api.calls.length;
    await p.token('pw', 'pw:session-2'); await advance(1500);
    out.pw = [[...new Set(p.api.calls.slice(from2).filter((c) => c.path === '/jobs/status').flatMap((c) => JSON.parse(c.body).ids))], brief(theirs).work, brief(mine).work];
    """)
    assert got["me"] == [["jobA"], 0, 0, []]
    working = {"status": "working", "versions": [], "drafts": [], "pick": -1, "work": True}
    assert got["untouched"] == [working, [{"id": "jobB", "k": 1, "got": False}], working, working]
    assert got["other"] == [["r-acct:other", "jobB"], {"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": False}, working]
    assert got["pw"] == [["jobC"], True, True]


def test_a_request_whose_results_ran_out_before_it_was_picked_up_is_said_and_not_cancelled():
    """The answer to the POST never came, and the visit that asks about the request is hours later: the server has
    let the results go. Such a view has no ref to match a sound by. It is counted for the notice, and nothing is
    cancelled (a cancel would only use up the room's allowance)."""
    got = run(r"""
    const api = fakeApi(); let cut = true;
    const a = slot('sfx_a', { status: 'draft', versions: [oldVersion('v1')] }), b = slot('sfx_b');
    const p = page({ assets: [a, b], api, deps: { fetch: async (url, init) => { const r = await api.fetch(url, init); if (cut && url.endsWith('/jobs')) throw new TypeError('connection lost'); return r; } } });
    await p.token();
    out.sent = (await p.gen.generate([a, b], { mode: 'make', drafts: 1 })).pending;
    T.timers = []; T.wall += 2 * 3600000;
    api.set('job1', { status: 'gone', refund: 'done' }); api.set('job2', { status: 'gone', refund: 'none' });
    const q = reload(p), from = api.calls.length;
    await q.token(); await advance(0);
    out.calls = api.paths(from).filter((x) => x.startsWith('POST'));
    out.after = [q.assets.map(brief), q.toasts, [...q.store.board.keys()].filter((k) => k.startsWith('req:')), JSON.parse(q.store.board.get('board')).assets.map((x) => [x.status, 'work' in x])];
    await advance(6000);
    out.quiet = api.paths(from).filter((x) => x.startsWith('POST')).length;
    """)
    assert got["sent"] is True and got["calls"] == ["POST /jobs/status"] and got["quiet"] == 1
    assert got["after"] == [[{"status": "draft", "versions": ["v1"], "drafts": [], "pick": -1, "work": False}, {"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": False}],
                            ["genRefunded:1 genLost:1"], [], [["draft", False], ["pending", False]]]


def test_picking_work_up_rests_after_a_429_for_as_long_as_the_server_asks():
    got = run(r"""
    const posts = (p, from) => p.api.paths(from).filter((x) => x.startsWith('POST'));
    // Asking about a request that has no answer yet.
    const a = slot('sfx_a'), p = page({ assets: [a] });
    await p.token(); p.api.down = true;
    await p.gen.generate([a], { mode: 'make', drafts: 1 });
    T.timers = [];
    const q = reload(p); p.api.down = false;
    let limited = 1;
    p.api.hook = (call, h) => (call.path === '/jobs/status' && limited-- > 0 ? h.err(429, 'rate', { retry_after: 30 }, { 'Retry-After': '30' }) : null);
    const from = p.api.calls.length;
    await q.token(); await advance(0);
    out.first = posts(p, from);
    await advance(10000); out.fiveOn = posts(p, from).length;         // the usual five seconds do not apply
    await q.token('acct', 'acct:me', 'newer'); await advance(0);      // nor does a newer token ask sooner
    out.newer = posts(p, from).length;
    await advance(19999); out.resting = posts(p, from).length;
    await advance(1);
    out.back = [posts(p, from), work(q.assets[0]).jobs.length, q.toasts];
    // Cancelling a request that is too old to send again.
    const b = slot('sfx_b'), p2 = page({ assets: [b] });
    await p2.token(); p2.api.down = true;
    await p2.gen.generate([b], { mode: 'make', drafts: 1 });
    T.timers = []; T.wall += 11 * 60000;
    const q2 = reload(p2); p2.api.down = false;
    let limited2 = 1;
    p2.api.hook = (call, h) => (call.path === '/jobs/cancel' && limited2-- > 0 ? h.err(429, 'rate', { retry_after: 20 }, { 'Retry-After': '20' }) : null);
    const from2 = p2.api.calls.length;
    await q2.token(); await advance(0);
    out.cancel = [posts(p2, from2), q2.assets[0].status];
    await advance(19999); out.cancelResting = posts(p2, from2).length;
    await advance(1);
    out.cancelBack = [posts(p2, from2), brief(q2.assets[0])];
    """)
    assert got["first"] == ["POST /jobs/status"] and got["fiveOn"] == 1 and got["newer"] == 1 and got["resting"] == 1
    assert got["back"] == [["POST /jobs/status", "POST /jobs/status", "POST /jobs", "POST /jobs/status"], 1, []]
    assert got["cancel"] == [["POST /jobs/status", "POST /jobs/cancel"], "working"] and got["cancelResting"] == 2
    assert got["cancelBack"] == [["POST /jobs/status", "POST /jobs/cancel", "POST /jobs/status", "POST /jobs/cancel"], {"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": False}]


# ---------- cancelling ----------

def test_trashing_a_sound_being_made_cancels_its_jobs():
    got = run(r"""
    const a = slot('sfx_a', { status: 'draft', versions: [oldVersion('v1')] }), b = slot('sfx_b'), c = slot('sfx_c'), p = page({ assets: [a, b, c] });
    await p.token();
    await p.gen.generate([a], { mode: 'revise', text: 'x', drafts: 2 });
    p.api.finish('job1'); await advance(0);                         // one draft is in, the other still being made
    await p.gen.cancel([a]);
    out.withIds = [p.api.posted('/jobs/cancel'), brief(a), p.api.calls.at(-1).keepalive, p.api.jobs.get('job2').status];
    // No ids yet (the request has no answer): the whole request is cancelled, but only when none of its sounds is still wanted.
    p.api.down = true;
    await p.gen.generate([b, c], { mode: 'make', drafts: 1 });
    p.api.down = false;
    await p.gen.cancel([b]);
    out.partial = [p.api.posted('/jobs/cancel').length, brief(b), c.status];
    await p.gen.cancel([c]);
    out.whole = [p.api.posted('/jobs/cancel').at(-1), brief(c), [...p.api.marks], p.store.board.has('req:req-2')];
    // A job that comes back for a sound that was trashed meanwhile is cancelled when its id is learned.
    const d = slot('sfx_d'), e = slot('sfx_e'); p.assets.push(d, e);
    let trashed = false;
    p.api.hook = (call) => { if (call.path === '/jobs' && !trashed) { trashed = true; p.gen.cancel([d]); } };
    await p.gen.generate([d, e], { mode: 'make', drafts: 1 });
    await settle();
    out.stray = [p.api.posted('/jobs/cancel').at(-1), brief(d), work(e).jobs.length];
    """)
    assert got["withIds"] == [[{"ids": ["job2"]}], {"status": "draft", "versions": ["v1"], "drafts": [], "pick": -1, "work": False}, True, "cancelled"]
    assert got["partial"] == [1, {"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": False}, "working"]
    assert got["whole"] == [{"request_id": "req-2"}, {"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": False}, ["req-2"], False]
    assert got["stray"][0] == {"ids": ["job3"]} and got["stray"][1]["work"] is False and got["stray"][2] == 1


def test_a_cancel_the_server_did_not_take_is_told_again():
    got = run(r"""
    const a = slot('sfx_a'), b = slot('sfx_b'), p = page({ assets: [a, b] });
    await p.token();
    await p.gen.generate([a], { mode: 'make', drafts: 1 });        // job1
    await p.gen.generate([b], { mode: 'make', drafts: 1 });        // job2
    const cancels = () => p.api.posted('/jobs/cancel');
    // The page is paused (its token ran out and no other came) when the first sound goes to the trash.
    const old = tokenOf('acct', 'acct:me'); p.api.deny = (call) => call.token === old;
    await advance(0); await advance(10000);
    out.paused = p.gen.paused;
    await p.gen.cancel([a]);
    out.first = [cancels().length, p.api.jobs.get('job1').status, brief(a)];
    await advance(30000);
    out.whilePaused = cancels().length;                             // nothing more is sent while paused
    await p.token('acct', 'acct:me', 'fresh'); await advance(0);    // the next token: the cancel goes out again
    out.resent = [cancels(), p.api.jobs.get('job1').status, p.api.jobs.get('job2').status];
    // No connection when the second goes: it is told again five seconds on, once.
    p.api.down = true;
    await p.gen.cancel([b]);
    const n = cancels().length;
    p.api.down = false;
    await advance(4999); out.early = cancels().length - n;
    await advance(1); out.late = [cancels().at(-1), p.api.jobs.get('job2').status];
    await advance(20000); out.once = cancels().length - n;
    // Another person's token does not send what the one before still owed.
    const c = slot('sfx_c'), p2 = page({ assets: [c] });
    await p2.token('acct', 'acct:me');
    await p2.gen.generate([c], { mode: 'make', drafts: 1 });
    p2.api.down = true; await p2.gen.cancel([c]); p2.api.down = false;
    const m = p2.api.posted('/jobs/cancel').length;
    await p2.token('acct', 'acct:other'); await advance(6000);
    out.other = p2.api.posted('/jobs/cancel').length - m;
    """)
    back = {"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": False}
    assert got["paused"] is True and got["first"] == [1, "queued", back] and got["whilePaused"] == 1
    assert got["resent"] == [[{"ids": ["job1"]}, {"ids": ["job1"]}], "cancelled", "queued"]
    assert got["early"] == 0 and got["late"] == [{"ids": ["job2"]}, "cancelled"] and got["once"] == 1
    assert got["other"] == 0


def test_a_cancel_that_got_a_429_is_told_again_after_the_rest_the_server_asked_for():
    got = run(r"""
    const a = slot('sfx_a'), b = slot('sfx_b'), p = page({ assets: [a, b] });
    await p.token();
    await p.gen.generate([a], { mode: 'make', drafts: 1 });
    await advance(0);
    let limited = 1;
    p.api.hook = (call, h) => (call.path === '/jobs/cancel' && limited-- > 0 ? h.err(429, 'rate', { retry_after: 20 }, { 'Retry-After': '20' }) : null);
    const cancels = () => p.api.posted('/jobs/cancel').length;
    await p.gen.cancel([a]);
    out.first = [cancels(), p.api.jobs.get('job1').status, brief(a)];
    await advance(10000);
    await p.token('acct', 'acct:me', 'newer');                      // neither the usual five seconds nor a newer token asks sooner
    await advance(9999); out.resting = cancels();
    await advance(1); out.back = [cancels(), p.api.jobs.get('job1').status];
    await advance(60000); out.once = cancels();
    """)
    assert got["first"] == [1, "queued", {"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": False}]
    assert got["resting"] == 1 and got["back"] == [2, "cancelled"] and got["once"] == 2


def test_dropping_drafts_lets_their_record_go_without_a_word_to_the_server():
    """Drafts under review that were not kept. Their jobs have all ended, so there is nothing to cancel: a cancel
    would only count against the room's allowance of ten a minute."""
    got = run(r"""
    const a = slot('sfx_a', { status: 'draft', versions: [oldVersion('v1')] }), b = slot('sfx_b'), p = page({ assets: [a, b] });
    await p.token();
    await p.gen.generate([a], { mode: 'revise', text: 'x', drafts: 2 });
    p.api.finish('job1'); p.api.finish('job2');
    p.store.failBlob = (key) => key === 'ver:job2';                 // one draft's sound did not reach the disk: its record stays
    await advance(0);
    out.review = [brief(a), work(a).jobs.map((j) => j.got)];
    const n = p.api.calls.length;
    p.gen.drop([a]);
    out.dropped = [!!a.work, p.api.calls.length - n];
    // A sound that is still being made is not let go this way: that is what cancel() is for.
    await p.gen.generate([b], { mode: 'make', drafts: 1 });
    p.gen.drop([b]);
    out.working = [b.status, !!b.work];
    """)
    assert got["review"] == [{"status": "review", "versions": ["v1"], "drafts": ["job1", "job2"], "pick": 0, "work": True}, [True, False]]
    assert got["dropped"] == [False, 0] and got["working"] == ["working", True]


# ---------- with the real store ----------

# One visit with the real store: the board as app.js keeps it (snapshot, apply, keys), the store, the generator on top.
REAL_VISIT = r"""
    T.slow = 25;
    const disk = tinyIdb(), api = fakeApi();
    async function visit() {
      const v = { assets: [], toasts: [], info: null };
      v.store = S.create({ indexedDB: disk.indexedDB,
        snapshot: () => ({ v: S.SNAPSHOT, assets: v.assets.map((a) => ({ ...a, versions: a.versions.map(S.record), drafts: a.drafts.map(S.record) })), trash: [] }),
        apply: (data, buffers, info) => { v.assets = data.assets; v.info = info; },
        keys: () => { const want = new Map(); for (const a of v.assets) for (const x of [...a.versions, ...a.drafts]) for (const k of S.versionKeys(x)) want.set(k, null); return want; } });
      await v.store.lock(); v.restored = await v.store.restore();
      v.gen = G.create({ store: v.store, assets: () => v.assets, fetch: api.fetch, now: () => T.mono, wall: () => T.wall, setTimeout: setT, clearTimeout: clearT,
        uuid: () => 'req-' + (++T.uuid), measure: M, peaks: S.peaksOf, project: () => ({ game: 'g' }), item: (a) => ({ kind: 'sfx', id: a.id, name: a.name }),
        text: (k, n) => (n === undefined ? k : k + ':' + n), toast: (t) => v.toasts.push(t) });
      v.token = async () => { await v.gen.token({ token: tokenOf('acct', 'acct:me'), ttl: 900, api: BASE }); await settle(); };
      return v;
    }
"""


def test_with_the_real_store_a_draft_survives_a_reload_and_a_settled_sound_that_lost_a_blob_loses_only_that_version():
    got = run(REAL_VISIT + r"""
    const one = await visit();
    one.assets.push(slot('sfx_a'), slot('sfx_b'));
    await one.token();
    out.first = [one.restored, (await one.gen.generate(one.assets, { mode: 'make', drafts: 1 })).ok];
    await settle();
    out.words =disk.stores.get('board').has('req:req-1');           // deleted once the ids were kept
    out.diskWork = disk.stores.get('board').get('board').assets.map((a) => [a.status, a.work.jobs.map((j) => j.id)]);
    api.finish('job1', 1);
    await advance(0);
    out.made = [brief(one.assets[0]), [...disk.stores.get('audio').keys()].sort(), one.assets[0].versions[0].sha256 === sha(api.jobs.get('job1').wav)];
    // The sound plays from what was stored: real WAV bytes, decoded by the store.
    const sound = await one.store.ensureSound(one.assets[0].versions[0]);
    out.sound = [sound.rate, sound.chans.length, sound.stems.map((s) => s.name)];
    // Next visit, while the second sound is still being made; one stem of the first has gone missing from the disk.
    disk.stores.get('audio').delete('ver:job1:s1');
    const two = await visit();
    out.second = [two.restored, two.assets.map(brief), two.info.refetch, two.info.dropped];
    out.second.push(work(two.assets[0]));
    """)
    assert got["first"] == ["empty", True] and got["words"] is False and got["diskWork"] == [["working", ["job1"]], ["working", ["job2"]]]
    assert got["made"] == [{"status": "draft", "versions": ["job1"], "drafts": [], "pick": -1, "work": False}, ["ver:job1", "ver:job1:s1"], True]
    assert got["sound"] == [48000, 1, ["part 1"]]
    # The first sound had been settled and its record was gone, so the version whose stem is missing is dropped (store.mend);
    # the second is still being made and keeps its record.
    assert got["second"][0] == "restored"
    assert got["second"][1] == [{"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": False}, {"status": "working", "versions": [], "drafts": [], "pick": -1, "work": True}]
    assert got["second"][2] == [] and got["second"][3] == [{"asset": "sfx_a", "id": "job1"}] and got["second"][4] is None


def test_with_the_real_store_a_lost_sound_that_the_job_record_still_names_is_fetched_again():
    """Spec F, restore: a version whose Blob is missing is fetched again when a.work still has its id."""
    got = run(REAL_VISIT + r"""
    const one = await visit();
    one.assets.push(slot('sfx_a', { status: 'draft', versions: [oldVersion('v1')] }));
    await one.token();
    await one.gen.generate(one.assets, { mode: 'revise', text: 'softer', drafts: 2 });
    await settle();
    api.finish('job1', 1);
    await advance(0);
    await until(() => one.assets[0].work.jobs[0].got);          // the first draft is on disk and counted; the second is still being made
    out.first = [brief(one.assets[0]), work(one.assets[0]).jobs.map((j) => j.got), [...disk.stores.get('audio').keys()].sort()];
    // Before the next visit the draft's sound goes missing from the disk. Its job is still in the record.
    await until(() => disk.stores.get('board').get('board').assets[0].work.jobs[0].got);
    disk.stores.get('audio').delete('ver:job1');
    T.timers = [];
    const two = await visit();
    out.second = [two.restored, brief(two.assets[0]), two.info.refetch, two.info.dropped, work(two.assets[0]).jobs];
    const from = api.calls.length;
    await two.token(); await advance(0);
    await until(() => disk.stores.get('audio').has('ver:job1') && two.assets[0].work.jobs[0].got);
    out.fetched = [api.paths(from).filter((x) => x.startsWith('GET /jobs')), work(two.assets[0]).jobs.map((j) => j.got), brief(two.assets[0])];
    api.finish('job2');
    await advance(1500);
    await until(() => !two.assets[0].work);
    out.after = [brief(two.assets[0]), [...disk.stores.get('audio').keys()].sort(), two.toasts];
    """)
    working = {"status": "working", "versions": ["v1"], "drafts": ["job1"], "pick": -1, "work": True}
    assert got["first"] == [working, [True, False], ["ver:job1", "ver:job1:s1"]]
    assert got["second"] == ["restored", {**working, "drafts": []}, [{"asset": "sfx_a", "id": "job1"}], [], [{"id": "job1", "k": 1, "got": False}, {"id": "job2", "k": 2, "got": False}]]
    assert got["fetched"] == [["GET /jobs/job1/sound", "GET /jobs/job1/stems/1"], [True, False], working]
    assert got["after"] == [{"status": "review", "versions": ["v1"], "drafts": ["job1", "job2"], "pick": 0, "work": False}, ["ver:job1", "ver:job1:s1", "ver:job2"], []]


# ---------- the page itself ----------

PAGE_STORY = r"""
    T.slow = 10;
    await settle(); await advance(0);
    const $ = (id) => document.getElementById(id), tiles = () => document.querySelectorAll('.tile'), tileOf = (id) => document.querySelector('.tile[data-id="' + id + '"]');
    const said = () => ($('toast').hidden ? null : $('toast').textContent);
    const count = () => { const n = {}; for (const t of tiles()) n[t.dataset.status] = (n[t.dataset.status] || 0) + 1; return n; };
    // Typed the way a browser reports typing: the input event comes before the press, so the draft picker has followed the words.
    const ask = async (id, text) => { tileOf(id).focus(); $('ask').value = text; $('ask').fire('input'); $('askForm').fire('submit'); await advance(0); };
    const credits = () => { $('exportBtn').click(); const text = document.querySelector('.creditsText').textContent; return text; };
    const ONE = 'sfx_ui_confirm';

    // Without a token: the old sample board is there and checked, and asking for a sound says that AI is off.
    out.start = { tiles: tiles().length, count: count(), issues: [...new Set(tiles().filter((t) => t.dataset.issues !== undefined).map((t) => t.dataset.issues))].sort(), withIssues: tiles().filter((t) => t.dataset.issues !== undefined).length };
    $('approveAll').click();
    $('fillBtn').click();
    out.off = { said: said(), calls: api.calls.length, count: count(), button: !!$('fillBtn') };
    await ask(ONE, 'a soft bell');
    out.offAsk = { said: said(), count: count(), calls: api.calls.length };
    out.credits = credits(); $('dialog').close();

    // The host page hands in a token: the price of a draft is read.
    tellWindow('message', { data: { type: 'asset:token', token: tokenOf('acct', 'acct:me'), ttl: 900, api: BASE }, source: globalThis, origin: 'https://evil.test' });
    await settle();
    out.stranger = api.calls.length;                      // a message from another origin is no token
    tellWindow('message', { data: { type: 'asset:token', token: tokenOf('acct', 'acct:me'), ttl: 900, api: BASE }, source: globalThis, origin: location.origin });
    await until(() => api.calls.length > 0);
    out.quote = api.paths();

    // Two drafts of a sound that is not made yet, asked for in words.
    await ask(ONE, '2 drafts of a soft bell');
    await until(() => api.posted('/jobs').length === 1);
    const first = api.posted('/jobs')[0];
    out.make = { drafts: first.drafts, credits: first.expect_credits, lang: first.lang, project: first.project, item: first.items[0], status: tileOf(ONE).dataset.status, bar: !!tileOf(ONE).querySelector('.bar') };
    out.words = [...disk.stores.get('board').keys()].filter((k) => String(k).startsWith('req:')).length;
    api.finish('job1'); api.finish('job2');
    await advance(1500);                                  // the next look finds them done
    await until(() => tileOf(ONE).dataset.status === 'review');
    out.review = { picks: tileOf(ONE).querySelectorAll('[data-pick]').map((b) => b.textContent), canvas: !!tileOf(ONE).querySelector('canvas'), issues: tileOf(ONE).dataset.issues.split(' ') };
    tileOf(ONE).querySelector('.keep').click();
    out.kept = tileOf(ONE).dataset.status;

    // A change to it, two drafts again; this time they are dropped.
    await ask(ONE, 'brighter, 2 drafts');
    await until(() => api.posted('/jobs').length === 2);
    const second = api.posted('/jobs')[1];
    out.revise = { drafts: second.drafts, item: { mode: second.items[0].mode, change: second.items[0].change, base: second.items[0].base, style: second.items[0].style_ref } };
    api.finish('job3'); api.finish('job4');
    await advance(1500);
    await until(() => tileOf(ONE).dataset.status === 'review');
    out.review2 = tileOf(ONE).querySelectorAll('[data-pick]').map((b) => b.textContent);
    tileOf(ONE).querySelector('.drop').click();
    out.dropped = tileOf(ONE).dataset.status;

    // A sound that is still being made goes to the trash: its job is cancelled.
    const GONE = 'sfx_ui_cancel';
    await ask(GONE, 'a low thud');
    await until(() => api.posted('/jobs').length === 3);
    tileOf(GONE).fire('contextmenu', { clientX: 0, clientY: 0 });
    $('tileMenu').querySelectorAll('button').find((b) => b.textContent.startsWith('Move to trash')).click();
    await settle();
    out.trashed = { cancel: api.posted('/jobs/cancel'), job: api.jobs.get('job5').status, tile: !!tileOf(GONE), tiles: tiles().length };

    // The rest of the board, one draft a sound.
    $('fillBtn').click();
    await until(() => api.posted('/jobs').length === 4);
    const third = api.posted('/jobs')[3];
    out.expand = { items: third.items.length, drafts: third.drafts, credits: third.expect_credits, kinds: [...new Set(third.items.map((i) => i.kind))].sort(), working: count().working, said: said() };
    for (const [id, j] of api.jobs) if (j.status === 'queued') api.finish(id, id === 'job6' ? 2 : 0);
    await advance(1500);
    await until(() => !count().working);
    out.made = { count: count(), button: !!$('fillBtn'), lic: tiles().filter((t) => (t.dataset.issues || '').split(' ').includes('lic')).length };

    // Credits: the sources of what is approved, then the encoder of the chosen format.
    $('approveAll').click();
    out.credits2 = credits();
    const format = $('dialog').querySelector('select'); format.value = 'mp3'; format.fire('change');
    out.credits3 = document.querySelector('.creditsText').textContent;
    $('dialog').close();

    // What reached the disk.
    await advance(600);
    await until(() => { const b = disk.stores.get('board').get('board'); return !!b && b.assets.every((a) => a.status === 'approved' || a.id === ONE); });
    const saved = disk.stores.get('board').get('board'), made = saved.assets.flatMap((a) => a.versions.filter((v) => v.engine === 'nkido'));
    out.disk = { engines: [...new Set(saved.assets.flatMap((a) => a.versions.map((v) => v.engine)))].sort(), work: saved.assets.filter((a) => a.work).length,
      one: saved.assets.find((a) => a.id === ONE).versions.map((v) => v.id), words: [...disk.stores.get('board').keys()].filter((k) => String(k).startsWith('req:')).length,
      made: made.length, stems: made.flatMap((v) => v.stems).length, sounds: made.flatMap((v) => S.versionKeys(v)).every((k) => disk.stores.get('audio').has(k)) };
"""


def test_the_page_makes_changes_and_credits_sounds_through_the_generator():
    """app.js as the browser runs it, on the stand-in DOM, over a sample board an earlier page saved: no token, then a
    token, a first sound in two drafts, a change that is dropped, the rest of the board, and the credits. What a real
    browser adds (layout, sound, files) is not here."""
    got = run_page(PAGE_STORY, before=OLD_BOARD)
    off = 'AI is not connected here, so sounds cannot be made. Links and notes ("note: …") are still saved as references.'
    synth = "olmuse built-in synth\n  License: -\n  Holder: -\n"
    nkido = "nkido (Akkado, Cedar)\n  Use: Sound synthesis engine\n  License: MIT\n  Holder: Moritz Laass\n"
    head = "Starlight Garden sound asset license notice\n\n"

    # The old sample board: its eight samples are rendered by the room's own synth from their saved recipes and checked.
    assert got["start"] == {"tiles": 32, "count": {"draft": 8, "pending": 24}, "issues": ["", "dc", "peak clip", "peak clip loud"], "withIssues": 8}
    # Without a token nothing is asked for and nothing changes; the room says AI is off, and still credits what it has.
    assert got["off"] == {"said": off, "calls": 0, "count": {"approved": 8, "pending": 24}, "button": True}
    assert got["offAsk"] == {"said": off, "count": {"approved": 8, "pending": 24}, "calls": 0}
    assert got["credits"] == head + synth
    assert got["stranger"] == 0 and got["quote"] == ["GET /quote?items=1&drafts=1"]

    # A sound not made yet, two drafts: both wait for a pick, and there is no "previous" to go back to.
    make = got["make"]
    assert (make["drafts"], make["credits"], make["lang"], make["status"], make["bar"]) == (2, 2, "en", "working", True)
    assert make["project"] == {"game": "Starlight Garden", "style": "A calm fantasy collecting game. Cute and warm.", "platform": "mobile", "loud": [-20, -16]}
    assert {k: make["item"][k] for k in ("mode", "kind", "loop", "id", "name", "description", "base", "style_ref")} == {
        "mode": "make", "kind": "sfx", "loop": False, "id": "sfx_ui_confirm", "name": "Confirm", "description": "2 drafts of a soft bell", "base": None, "style_ref": None}
    assert got["words"] == 0
    assert got["review"]["picks"] == ["1", "2"] and got["review"]["canvas"] is True
    assert "lic" not in got["review"]["issues"] and "name" not in got["review"]["issues"]
    assert got["kept"] == "approved"

    # A change starts from the patch of the version in use; dropped drafts leave the sound as a draft.
    assert got["revise"] == {"drafts": 2, "item": {"mode": "revise", "change": "brighter, 2 drafts", "base": {"source": "SOURCE job1", "seconds": 0.01, "bpm": None}, "style": None}}
    assert got["review2"] == ["Previous", "1", "2"] and got["dropped"] == "draft"

    # Trashing a sound that is being made cancels its job at the server.
    assert got["trashed"] == {"cancel": [{"ids": ["job5"]}], "job": "cancelled", "tile": False, "tiles": 31}

    # The rest of the board is one request, one draft a sound.
    assert got["expand"] == {"items": 22, "drafts": 1, "credits": 22, "kinds": ["amb", "music", "sfx"], "working": 22, "said": "Making 22"}
    assert got["made"] == {"count": {"approved": 8, "draft": 23}, "button": False, "lic": 0}

    # Credits are the sources of what is approved, each once, and the encoders only when the format needs them.
    assert got["credits2"] == head + synth + "\n" + nkido
    assert got["credits3"] == head + synth + "\n" + nkido + "\nwasm-media-encoders\n  Use: OGG and MP3 export\n  License: MIT\n  Holder: arseneyr\n\nLAME\n  Use: MP3 encoder\n  License: LGPL-2.0\n  Holder: The LAME Project\n"
    assert got["disk"] == {"engines": ["legacy", "nkido"], "work": 0, "one": ["job2", "job1"], "words": 0, "made": 24, "stems": 2, "sounds": True}


PAGE_TOOLS = r"""
    T.slow = 10;
    await settle(); await advance(0);
    const $ = (id) => document.getElementById(id), tiles = () => document.querySelectorAll('.tile'), tileOf = (id) => document.querySelector('.tile[data-id="' + id + '"]');
    const said = () => ($('toast').hidden ? null : $('toast').textContent);
    const count = () => { const n = {}; for (const t of tiles()) n[t.dataset.status] = (n[t.dataset.status] || 0) + 1; return n; };
    const type = (id, text) => { tileOf(id).focus(); $('ask').value = text; $('ask').fire('input'); $('askForm').fire('submit'); };
    const hand = (kind = 'acct', sub = 'acct:me') => tellWindow('message', { data: { type: 'asset:token', token: tokenOf(kind, sub), ttl: 900, api: BASE }, source: parent, origin: location.origin });
    const MADE = tiles().find((t) => t.dataset.status === 'draft').dataset.id, EMPTY = tiles().find((t) => t.dataset.status === 'pending').dataset.id;
"""
AI_OFF = 'AI is not connected here, so sounds cannot be made. Links and notes ("note: …") are still saved as references.'


def test_a_request_typed_in_the_dock_that_the_room_cannot_take_says_why_and_not_that_sounds_are_being_made():
    """The saved board could not be read, so nothing is saved or made on this visit, and a token is there. A request for
    a picked sound is answered with that reason. It used to be answered "Remaking 1 sound." over a POST that never went."""
    got = run_page(PAGE_TOOLS.split("    const MADE")[0] + r"""
    out.start = [said(), tiles().length];
    hand();
    await until(() => api.calls.length > 0);
    // the page is on an empty board: a slot comes from a list
    $('importBtn').click(); $('listIn').value = 'Bell'; $('listIn').fire('input'); $('addSlots').click(); await settle();
    const EMPTY = tiles()[0].dataset.id;
    type(EMPTY, 'a soft bell'); await advance(0);
    out.empty = [said(), tileOf(EMPTY).dataset.status];
    // A link is still a reference: that needs no generation.
    type(EMPTY, 'https://example.com/ref'); await advance(0);
    out.link = said();
    out.calls = api.paths();
    """, before="disk.stores.set('board', new Map([['board', { v: 2, assets: 'not a list' }]])); disk.stores.set('audio', new Map());")
    failed = "The saved board could not be opened, so nothing is saved on this visit. Reloading the page may open it again."
    assert got["start"] == [failed, 0]
    assert got["empty"] == [failed, "pending"]
    assert got["link"].startswith("Saved it as a reference.") and got["calls"] == ["GET /quote?items=1&drafts=1"]


HOST_STORY = r"""
    const tell = (data) => tellWindow('message', { data, source: parent, origin: location.origin });
    const answer = async (reply, actions) => { const n = hostBox.filter((m) => m.type === 'asset:agent').at(-1).payload.n; tell({ type: 'asset:agent_reply', n, status: 'done', reply, actions }); await settle(); await advance(0); };
    out.ready = hostBox.some((m) => m.type === 'asset:ready');

    // The host's assistant answers that it is remaking a sound, but there is no token: the room's reason stays up,
    // with the undo of what the answer did change.
    tell({ type: 'asset:ai', on: true });
    type(MADE, 'make it brighter'); await settle();
    await answer('Remaking it brighter.', [{ op: 'revise', assets: [MADE], text: 'make it brighter' }]);
    out.turned = [said(), !!$('toast').querySelector('button'), api.calls.length];
    type(MADE, 'call it a bright one and remake it'); await settle();
    await answer('Noted, and remaking it.', [{ op: 'describe', assets: [MADE], text: 'bright' }, { op: 'revise', assets: [MADE], text: 'brighter' }]);
    out.turnedWithUndo = [$('toast').textContent.startsWith(AI_OFF), !!$('toast').querySelector('button')];
    // An answer that asks for no sound is said as it is.
    type(MADE, 'what is this'); await settle();
    await answer('It is the confirm sound.', []);
    out.plain = said();
    tell({ type: 'asset:ai', on: false });

    // With a token: a sound is being made while another sound's view is open and a request is being typed there.
    hand();
    await until(() => api.calls.length > 0);
    type(EMPTY, 'a soft bell'); await advance(0);
    await until(() => api.posted('/jobs').length === 1);
    tileOf(MADE).focus();
    tellWindow('keydown', { key: 'Enter', code: 'Enter', target: tileOf(MADE) });
    await settle();
    const box = document.querySelector('.detailDock textarea');
    box.value = 'warmer and'; box.focus();
    await advance(1500);                                  // a look that ends nothing
    out.looking = [document.querySelector('.detailDock textarea') === box, document.activeElement === box];
    api.finish('job1');
    await advance(1500);                                  // the other sound's job ends
    await until(() => !!disk.stores.get('board').get('board') && disk.stores.get('board').get('board').assets.some((a) => a.id === EMPTY && a.status === 'draft'));
    await advance(0);
    out.typing = [document.querySelector('.detailDock textarea') === box, document.activeElement === box, box.value, document.documentElement.contains(box)];
    tellWindow('keydown', { key: 'Escape', code: 'Escape', target: document.body });
    await settle();
    out.closed = [$('detailView').hidden, tileOf(EMPTY).dataset.status];

    // The rest of the board is being made when a bundle replaces the board: those jobs are cancelled.
    $('approveAll').click();
    $('fillBtn').click();
    await until(() => api.posted('/jobs').length === 2);
    const asked = api.posted('/jobs')[1].items.length, ids = [...api.jobs.values()].filter((j) => j.request === api.posted('/jobs')[1].request_id).map((j) => j.id);
    $('importBtn').click();
    $('importFiles').files = [new File([JSON.stringify({ game: 'Other game', assets: [{ id: 'sfx_jump', name: 'Jump land', category: 'char' }, { id: 'sfx_coin', name: 'Coin pickup', category: 'ui' }] })], 'game-audio.spec.json')];
    $('importFiles').fire('change');
    for (let i = 0; i < 50 && !tileOf('sfx_coin'); i++) { await settle(); await advance(0); } // a bundle of two takes a breath between its sounds
    const looks = api.posted('/jobs/status').length;
    await advance(30000);
    out.replaced = { asked, ids: ids.length, cancel: api.posted('/jobs/cancel').map((b) => b.ids.length), same: JSON.stringify(api.posted('/jobs/cancel').flatMap((b) => b.ids).sort()) === JSON.stringify(ids.slice().sort()),
      jobs: [...new Set(ids.map((id) => api.jobs.get(id).status))], tiles: tiles().length, count: count(), looksAfter: api.posted('/jobs/status').length - looks };

    // The sound the generator made for the old board was paid for: it is in the trash, not gone, and can be put back.
    const bin = () => $('side').querySelectorAll('button').find((b) => b.title === 'Trash');
    out.binned = [bin().getAttribute('aria-label'), tileOf(EMPTY) === null];
    await advance(600);
    await until(() => { const b = disk.stores.get('board').get('board'); return !!b && (b.trash || []).length === 1; });
    const kept = disk.stores.get('board').get('board').trash[0];
    out.binnedOnDisk = [kept.id === EMPTY, kept.versions.map((v) => v.engine), disk.stores.get('audio').has(kept.versions[0].key)];
    bin().click();
    $('dialog').querySelectorAll('.lineItem')[0].querySelectorAll('button').find((b) => b.textContent === 'Put back').click();
    out.putBack = [tiles().length, !!tileOf(EMPTY).querySelector('canvas'), !!bin()];
"""


def test_inside_the_host_page_a_turned_away_request_keeps_its_reason_a_typed_request_keeps_its_input_and_a_replaced_board_cancels_its_jobs():
    got = run_page("const AI_OFF = " + json.dumps(AI_OFF) + ";\n" + PAGE_TOOLS + HOST_STORY, before=OLD_BOARD + "const hostBox = []; own('parent', { postMessage: (m) => hostBox.push(m) });")
    assert got["ready"] is True
    # The answer said sounds were being remade; nothing was asked for, and the toast says why (with the undo when there is one).
    assert got["turned"] == [AI_OFF, False, 0] and got["turnedWithUndo"] == [True, True] and got["plain"] == "It is the confirm sound."
    # A job of another sound ending leaves the open sound's view alone: same input, still focused, text as typed.
    assert got["looking"] == [True, True] and got["typing"] == [True, True, "warmer and", True]
    assert got["closed"] == [True, "draft"]
    # Every job of the board that was replaced is cancelled at the server, and the poller has nothing left to ask.
    replaced = got["replaced"]
    assert replaced["asked"] == replaced["ids"] and replaced["ids"] > 0 and replaced["cancel"] == [replaced["ids"]] and replaced["same"] is True
    assert replaced["jobs"] == ["cancelled"] and replaced["tiles"] == 2 and replaced["count"] == {"pending": 2} and replaced["looksAfter"] == 0
    # The one sound the generator had made is in the trash with its sound (the synth's own samples are not), and comes back.
    assert got["binned"] == ["Trash 1", True] and got["binnedOnDisk"] == [True, ["nkido"], True] and got["putBack"] == [3, True, False]


BOARD_REPLACED = r"""
    hand();
    await until(() => api.calls.length > 0);
    const [ONE, TWO, THREE] = tiles().filter((t) => t.dataset.status === 'pending').map((t) => t.dataset.id);
    const nameOf = (id) => tileOf(id).querySelector('.name').textContent, NAMES = { [nameOf(ONE)]: 'one', [nameOf(TWO)]: 'two' };
    const onDisk = () => disk.stores.get('board').get('board');
    const inTrash = () => onDisk().trash.map((a) => [a.id === ONE ? 'one' : a.id === TWO ? 'two' : a.id, a.status, a.versions.map((v) => v.id), a.current, a.drafts.length, 'work' in a]).sort();
    const bin = () => $('side').querySelectorAll('button').find((b) => b.title === 'Trash');
    // ONE is made. TWO has two drafts under review and no version yet. THREE is still being made.
    type(ONE, 'a soft bell'); await advance(0);
    await until(() => api.posted('/jobs').length === 1);
    api.finish('job1'); await advance(1500);
    await until(() => tileOf(ONE).dataset.status === 'draft');
    type(TWO, '2 drafts of a low thud'); await advance(0);
    await until(() => api.posted('/jobs').length === 2);
    api.finish('job2'); api.finish('job3'); await advance(1500);
    await until(() => tileOf(TWO).dataset.status === 'review');
    type(THREE, 'a click'); await advance(0);
    await until(() => api.posted('/jobs').length === 3);

    // A bundle replaces the board.
    const open = async (spec, id) => { $('importBtn').click(); $('importFiles').files = [new File([JSON.stringify(spec)], 'game-audio.spec.json')]; $('importFiles').fire('change'); for (let i = 0; i < 50 && !tileOf(id); i++) { await settle(); await advance(0); } };
    await open({ game: 'Mine', assets: [{ id: 'sfx_jump', name: 'Jump land', category: 'char' }, { id: 'sfx_coin', name: 'Coin pickup', category: 'ui' }] }, 'sfx_coin');
    out.list = [tiles().length, count(), api.posted('/jobs/cancel'), api.jobs.get('job4').status, bin().getAttribute('aria-label')];
    await advance(600);
    await until(() => { const b = onDisk(); return !!b && b.assets.length === 2 && (b.trash || []).length === 2; });
    out.listTrash = inTrash();
    out.listSounds = onDisk().trash.flatMap((a) => a.versions).every((v) => disk.stores.get('audio').has(v.key));

    // ONE is put back on the user's own board. Then a bundle replaces that board too.
    bin().click();
    $('dialog').querySelectorAll('.lineItem').find((r) => NAMES[r.querySelector('.grow').textContent.split(' · ')[0]] === 'one').querySelectorAll('button').find((b) => b.textContent === 'Put back').click();
    $('dialog').close();
    out.back = [tiles().length, tileOf(ONE).dataset.status, bin().getAttribute('aria-label')];
    const spec = { game: 'Other game', assets: [{ id: 'sfx_x', name: 'X', category: 'ui' }] };
    $('importFiles').files = [new File([JSON.stringify(spec)], 'game-audio.spec.json')];
    $('importFiles').fire('change');
    await until(() => !!tileOf('sfx_x'));
    out.bundle = [tiles().map((t) => t.dataset.id), bin().getAttribute('aria-label')];
    await advance(600);
    await until(() => { const b = onDisk(); return !!b && b.assets.length === 1 && (b.trash || []).length === 2; });
    out.bundleTrash = inTrash();
"""


def test_sounds_the_generator_made_go_to_the_trash_when_the_board_is_replaced_and_drafts_under_review_go_as_versions():
    """Opening a bundle empties the board. What the generator made was paid for, so it is in the trash afterwards and can
    be put back; the trash keeps versions only, so drafts that were still under review are there as versions. What was
    still being made is cancelled, and everything else goes as before."""
    got = run_page(PAGE_TOOLS + BOARD_REPLACED, before=OLD_BOARD)
    assert got["list"] == [2, {"pending": 2}, [{"ids": ["job4"]}], "cancelled", "Trash 2"]
    made = [["one", "draft", ["job1"], 0, 0, False], ["two", "draft", ["job2", "job3"], 0, 0, False]]
    assert got["listTrash"] == made and got["listSounds"] is True
    assert got["back"] == [3, "draft", "Trash 1"]
    # the bundle's own sound is the board now; the two list slots, which cost nothing, are gone, and the made sound is back in the trash
    assert got["bundle"] == [["sfx_x"], "Trash 2"] and got["bundleTrash"] == made


def test_start_again_cancels_what_is_being_made_and_then_empties_what_was_saved():
    got = run_page(PAGE_TOOLS + r"""
    let asked = 0; own('confirm', () => { asked++; return true; });
    hand();
    await until(() => api.calls.length > 0);
    type(EMPTY, 'a soft bell'); await advance(0);
    await until(() => api.posted('/jobs').length === 1);
    await advance(600);
    await until(() => !!disk.stores.get('board').get('board'));
    out.before = [tileOf(EMPTY).dataset.status, api.jobs.get('job1').status, disk.stores.get('board').size > 0];
    let reloads = 0; location.reload = () => { reloads++; };
    $('menu').fire('click', { target: document.querySelector('#menu [data-act=game]') });
    out.buttons = $('dialog').querySelectorAll('button').map((b) => b.textContent).filter((x) => /board|sample/i.test(x));
    $('dialog').querySelectorAll('button').find((b) => b.textContent === 'Start with an empty board').click();
    await until(() => reloads === 1);
    const cancel = api.calls.find((c) => c.path === '/jobs/cancel');
    out.again = [api.posted('/jobs/cancel'), cancel.keepalive, api.jobs.get('job1').status, disk.stores.get('board').size, disk.stores.get('audio').size, asked];
    """, before=OLD_BOARD)
    assert got["before"] == ["working", "queued", True]
    # one way to start again, and it is to an empty board
    assert got["buttons"] == ["Start with an empty board"]
    # the cancel is sent so that it outlives the page (keepalive), and nothing of the old board is left on disk; none of
    # the old board's sounds is the user's own (made by the generator or brought in), so nothing is asked first
    assert got["again"] == [[{"ids": ["job1"]}], True, "cancelled", 0, 0, 0]


def test_what_only_the_page_can_do_with_drafts_and_boards_is_written_as_the_spec_asks():
    """Read from app.js, as Node has no way to press these: review with nothing picked, dropping drafts, a bundle opened."""
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    settle = app[app.index("function settle(a, keep) {"):app.index("/* ---------- dock ---------- */")]
    # "Keep" with no version and no draft picked throws nothing away; the guard comes before anything is dropped
    assert "if (keep && !a.versions.length && a.drafts.length && !a.drafts[a.pick]) { a.pick = 0; renderOpen(); return; }" in settle
    assert settle.index("a.pick = 0; renderOpen(); return;") < settle.index("a.drafts = [];")
    # dropping drafts cancels nothing at the server (spec F: cancelling belongs to the trash and to starting again)
    assert "gen.drop([a])" in settle and "gen.cancel(" not in settle
    # a board that is replaced (a bundle opened) is emptied in one place: what was being made for it is cancelled
    # first, and what the generator made goes to the trash before the rest goes
    clear = app[app.index("function clearBoard() {"):app.index("function nameBoard(name) {")]
    assert clear.index("gen.cancel([...assets]);") < clear.index("toTrash(made);") < clear.rindex("assets.length = 0;")
    bundle = app[app.index("async function openBundle(spec, files"):app.index("function addSlots(list) {")]
    assert "clearBoard();" in bundle and "assets.length = 0" not in bundle
    # a list or sound files are added to the board, never put in place of it
    for start, end in (("async function addSounds(files", "async function openBundle("), ("function addSlots(list) {", "/* ---------- filling empty slots")):
        assert "clearBoard()" not in app[app.index(start):app.index(end)]
    # the trash still cancels, and "start again" cancels in forget() itself, before the store is emptied
    assert "gen.cancel(list);" in app[app.index("function toTrash(list) {"):app.index("function removeAssets(list)")]
    forget = app[app.index("async function forget() {"):app.index("/* ---------- host page")]
    assert forget.index("gen.cancel([...assets, ...trash])") < forget.index("store.clear()")
    assert "await forget();\n    location.reload();" in app


# ---------- a board kept in step with the server (docs/ASSET_SYNC_SPEC.md H) ----------

def test_on_a_synced_board_only_this_computers_job_records_are_polled_cancelled_or_put_back():
    got = run(r"""
    const ME = 'a'.repeat(16), OTHER = 'b'.repeat(16), who = whoOf('acct:me');
    const record = (dev, id) => ({ request: 'r-' + id, kind: 'acct', who, ...(dev ? { dev } : {}), mode: 'make', text: '', n: 1, at: 1, before: 'pending', jobs: [{ id, k: 1, got: false }] });
    const make = (deps) => {
      const mine = slot('sfx_mine', { status: 'working', work: record(ME, 'jm') }), other = slot('sfx_other', { status: 'working', work: record(OTHER, 'jo') }), bare = slot('sfx_bare', { status: 'working', work: record(null, 'jb') });
      const p = page({ assets: [mine, other, bare], deps });
      for (const [id, ref] of [['jm', 'k-sfx_mine'], ['jo', 'k-sfx_other'], ['jb', 'k-sfx_bare']]) p.api.jobs.set(id, { id, ref, k: 1, n: 1, status: 'running', refund: 'none', stems: [] });
      return { p, mine, other, bare };
    };
    const look = async (deps) => {
      const { p, mine, other, bare } = make(deps);
      await p.token(); await advance(2000);
      const polled = [...new Set(p.api.posted('/jobs/status').flatMap((b) => b.ids || []))].sort();
      const free = [p.gen.free(mine), p.gen.free(other), p.gen.free(bare)];
      await p.gen.cancel([mine, other, bare]); await settle();
      const cancelled = p.api.posted('/jobs/cancel').flatMap((b) => b.ids || []).sort();
      return { polled, cancelled, left: [mine, other, bare].map((a) => [a.status, !!a.work]), free };
    };
    out.synced = await look({ dev: ME });
    out.plain = await look({});
    // a sound asked for here carries this computer's dev
    const s = slot('sfx_new'), q = page({ assets: [s], deps: { dev: () => ME } });
    await q.token(); await q.gen.generate([s], { mode: 'make', text: '', drafts: 1 });
    out.dev = s.work.dev;
    // the moment the board is tied to an account, the records without a dev are this computer's
    const { p, bare, other } = make({ dev: ME });
    out.stamped = [p.gen.stamp(), bare.work.dev, other.work.dev, p.gen.stamp()];
    """)
    assert got["synced"]["polled"] == ["jm"] and got["synced"]["cancelled"] == ["jm"]
    assert got["synced"]["left"] == [["pending", False], ["working", True], ["working", True]]
    assert got["plain"]["polled"] == ["jb", "jm", "jo"]  # no dev given: as before, every record of the account
    assert got["dev"] == "a" * 16
    assert got["stamped"] == [1, "a" * 16, "b" * 16, 0]


def test_a_claim_refused_or_not_reached_sends_nothing_and_without_claim_the_order_is_as_before():
    got = run(r"""
    const ME = 'a'.repeat(16);
    for (const answer of [false, 'throws', true]) {
      const a = slot('sfx_a'), claimed = [], p = page({ assets: [a], deps: { dev: ME, claim: async (list) => {
        claimed.push(list.map((x) => [x.id, x.status, x.work.dev])); p.log.push('claim'); if (answer === 'throws') throw new Error('offline'); return answer; } } });
      await p.token();
      const r = await p.gen.generate([a], { mode: 'make', text: '', drafts: 1 });
      out[String(answer)] = { r, claimed, order: p.log.filter((x) => /^(put|board|del|claim|POST \/jobs$)/.test(x)).map((x) => x.replace(/req-\d+/, 'req-1')), after: brief(a), posts: p.api.paths().filter((x) => x === 'POST /jobs').length };
    }
    """)
    for no in ("false", "throws"):
        o = got[no]
        assert o["r"] == {"ok": False, "reason": "claim"} and o["posts"] == 0, no
        assert o["claimed"] == [[["sfx_a", "working", "a" * 16]]], no
        assert o["order"] == ["put req:req-1", "board", "claim", "del req:req-1", "board"], no
        assert o["after"] == {"status": "pending", "versions": [], "drafts": [], "pick": -1, "work": False}, no
    assert got["true"]["r"] == {"ok": True} and got["true"]["posts"] == 1
    assert got["true"]["order"] == ["put req:req-1", "board", "claim", "POST /jobs", "board", "del req:req-1"]


def test_work_is_not_picked_up_or_polled_before_the_first_receiving_of_the_board():
    got = run(r"""
    const ME = 'a'.repeat(16), who = whoOf('acct:me');
    let open = null;
    const gate = new Promise((ok) => { open = ok; });
    const a = slot('sfx_a', { status: 'working', work: { request: 'r1', kind: 'acct', who, dev: ME, mode: 'make', text: '', n: 1, at: 1, before: 'pending', jobs: [{ id: 'j1', k: 1, got: false }] } });
    const b = slot('sfx_b', { status: 'working', work: { request: 'r2', kind: 'acct', who, dev: ME, mode: 'make', text: '', n: 1, at: T.wall, before: 'pending', jobs: [] } });
    let asked = 0;
    const p = page({ assets: [a, b], deps: { dev: ME, ready: () => { asked++; return gate; } } });
    p.api.jobs.set('j1', { id: 'j1', ref: 'k-sfx_a', k: 1, n: 1, status: 'running', refund: 'none', stems: [] });
    await p.token(); await advance(5000);
    out.before = [p.api.paths().filter((x) => x.startsWith('POST /jobs')), asked];
    open(); await advance(3000);
    out.after = [...new Set(p.api.paths().filter((x) => x.startsWith('POST /jobs')))].sort();
    """)
    assert got["before"] == [[], 1]
    assert got["after"] == ["POST /jobs/cancel", "POST /jobs/status"]  # the request without ids was never seen by the server


def test_work_left_by_another_computer_is_taken_over_only_when_it_is_away_the_api_knows_and_every_job_ended():
    got = run(r"""
    const ME = 'a'.repeat(16), GONE = 'c'.repeat(16), who = whoOf('acct:me');
    const setup = (status, info, won = true) => {
      const a = slot('sfx_a', { status: 'working', work: { request: 'r1', kind: 'acct', who, dev: GONE, mode: 'make', text: '', n: 1, at: 1, before: 'pending', jobs: [{ id: 'j1', k: 1, got: false }] } });
      const taken = [];
      const p = page({ assets: [a], deps: { dev: ME, handover: { info: () => info, take: async (list) => { taken.push(list.map((x) => x.work.dev)); return won ? list : []; } } } });
      p.api.jobs.set('j1', { id: 'j1', ref: 'k-sfx_a', k: 1, n: 1, status, refund: 'none', stems: [] });
      if (status === 'done') p.api.finish('j1');
      return { a, p, taken };
    };
    const away = { up: 500, now: 10000, peers: [], at: () => 0 };
    const tryOne = async (status, info, won) => {
      const { a, p, taken } = setup(status, info, won);
      await p.token();
      const r = await p.gen.handover();
      return { won: r.length, dev: a.work && a.work.dev, taken, cancels: p.api.posted('/jobs/cancel').length, p, a };
    };
    const strip = ({ p, a, ...rest }) => rest;
    out.here = strip(await tryOne('done', { ...away, peers: [{ dev: GONE, age: 10 }] }));
    out.justUp = strip(await tryOne('done', { ...away, up: 30 }));
    out.running = strip(await tryOne('running', away));
    out.lost = strip(await tryOne('done', away, false));
    const won = await tryOne('done', { ...away, peers: [{ dev: GONE, age: 120 }] });
    await advance(3000);
    out.won = { ...strip(won), status: won.a.status, versions: won.a.versions.length, saved: won.p.log.includes('board') };
    // a request that never got its job ids: only once it is ten minutes old on the server's clock
    const orphan = async (at) => {
      const a = slot('sfx_o', { status: 'working', work: { request: 'r9', kind: 'acct', who, dev: GONE, mode: 'make', text: '', n: 1, at: 1, before: 'pending', jobs: [] } });
      const p = page({ assets: [a], deps: { dev: ME, handover: { info: () => ({ up: 500, now: 10000, peers: [], at: () => at }), take: async (list) => list } } });
      await p.token();
      const r = await p.gen.handover();
      return [r.length, p.api.posted('/jobs/status').filter((b) => b.request_id).length];
    };
    out.orphan = [await orphan(9700), await orphan(9000)];
    """)
    assert got["here"] == {"won": 0, "dev": "c" * 16, "taken": [], "cancels": 0}  # its maker is still here
    assert got["justUp"] == {"won": 0, "dev": "c" * 16, "taken": [], "cancels": 0}  # the API has not been up long enough to know
    assert got["running"] == {"won": 0, "dev": "c" * 16, "taken": [], "cancels": 0}
    assert got["lost"] == {"won": 0, "dev": "c" * 16, "taken": [["a" * 16]], "cancels": 0}  # lost: back to its maker, nothing cancelled
    assert got["won"] == {"won": 1, "dev": "a" * 16, "taken": [["a" * 16]], "cancels": 0, "status": "draft", "versions": 1, "saved": True}
    assert got["orphan"] == [[0, 0], [1, 2]]  # asked once to take it over, once more as the winner picks it up


def test_call_sends_bytes_as_they_are():
    got = run(r"""
    const types = [];
    let p = null;
    p = page({ deps: { fetch: (url, init) => { types.push([init.headers['Content-Type'], init.body instanceof Uint8Array]); return p.api.fetch(url, init); } } });
    p.api.hook = (call, { res }) => (call.path.startsWith('/boards/') ? res(200, { at: 3 }) : null);
    await p.token();
    const r = await p.gen.call('POST', '/boards/' + 'a'.repeat(32) + '/blobs/' + 'b'.repeat(64) + '?at=0&size=3', new Uint8Array([1, 2, 3]), { raw: true });
    out.r = [r.status, r.data];
    out.types = types.filter(([t]) => t);
    """)
    assert got["r"] == [200, {"at": 3}]
    assert got["types"] == [["application/octet-stream", True]]


# ---------- the Unreal export on the page (docs/ASSET_UNREAL_SPEC.md B, I1) ----------

UNREAL_STORY = r"""
    T.slow = 10;
    await settle(); await advance(0);
    const $ = (id) => document.getElementById(id), tiles = () => document.querySelectorAll('.tile');
    const said = () => ($('toast').hidden ? null : $('toast').textContent);
    const until2 = async (done, steps = 400) => { for (let i = 0; i < steps && !done(); i++) await advance(50); };
    // A short WAV, 16-bit mono 48 kHz.
    const wav = (freq = 440, secs = 0.2) => {
      const n = Math.round(48000 * secs), b = new DataView(new ArrayBuffer(44 + n * 2)), s = (o, t) => [...t].forEach((c, i) => b.setUint8(o + i, c.charCodeAt(0)));
      s(0, 'RIFF'); b.setUint32(4, 36 + n * 2, true); s(8, 'WAVEfmt '); b.setUint32(16, 16, true); b.setUint16(20, 1, true); b.setUint16(22, 1, true);
      b.setUint32(24, 48000, true); b.setUint32(28, 96000, true); b.setUint16(32, 2, true); b.setUint16(34, 16, true); s(36, 'data'); b.setUint32(40, n * 2, true);
      for (let i = 0; i < n; i++) b.setInt16(44 + i * 2, Math.round(8000 * Math.sin(2 * Math.PI * freq * i / 48000) * Math.min(1, i / 200, (n - i) / 200)), true);
      return new Uint8Array(b.buffer);
    };
    // A folder handle of the File System Access API over a plain tree ({ name: bytes | {subtree} }). Reads and writes
    // are written down by path.
    const isDir = (v) => v && typeof v === 'object' && !(v instanceof Uint8Array);
    const missing = () => Object.assign(new Error('not found'), { name: 'NotFoundError' });
    function dirOf(tree, path, log) {
      const at = (n) => (path ? path + '/' + n : n);
      const file = (n) => ({ kind: 'file', name: n,
        getFile: async () => { log.push('read ' + at(n)); return new File([tree[n]], n); },
        createWritable: async () => ({ write: async (b) => { tree[n] = b; log.push('write ' + at(n)); }, close: async () => {} }) });
      return { kind: 'directory', name: path.split('/').pop() || 'Game',
        async *entries() { for (const [n, v] of Object.entries(tree)) yield [n, isDir(v) ? dirOf(v, at(n), log) : file(n)]; },
        async getDirectoryHandle(n, o = {}) { if (!(n in tree)) { if (!o.create) throw missing(); tree[n] = {}; } if (!isDir(tree[n])) throw missing(); return dirOf(tree[n], at(n), log); },
        async getFileHandle(n, o = {}) { if (!(n in tree)) { if (!o.create) throw missing(); tree[n] = new Uint8Array(0); } if (isDir(tree[n])) throw missing(); return file(n); },
        requestPermission: async () => 'granted' };
    }
    const log = [];
    const spec = { game: 'Linked', export: { engine: 'unreal' }, categories: [{ id: 'ui', name: 'UI', kind: 'sfx' }],
      assets: [{ id: 'ui_x', name: 'X', category: 'ui', file: 'audio/ui/ui_x.wav', status: 'approved', loop: false }] };
    const tree = {
      Content: { 'c.wav': wav(300) }, Saved: { 's.wav': wav(310) }, Config: { 'g.wav': wav(320) },
      Sub: { Content: { 'deep.wav': wav(330) } },
      OlmuseAudio: { 'game-audio.spec.json': new TextEncoder().encode(JSON.stringify(spec)), audio: { ui: { 'ui_x.wav': wav(600) } } },
      Plugins: { OlmuseAudio: { 'foreign.txt': new TextEncoder().encode('not ours') } },
    };
    own('showDirectoryPicker', async () => dirOf(tree, '', log));
    const blobs = [];
    URL.createObjectURL = (b) => { blobs.push(b); return 'blob:x'; }; URL.revokeObjectURL = () => {};

    // The engine choice offers Unreal Engine 5.
    $('exportBtn').click();
    const engine = $('dialog').querySelectorAll('select').find((s) => s.children.some((o) => o.value === 'godot'));
    out.options = engine.children.map((o) => [o.value, o.textContent]);

    // Linking an Unreal project's folder: the engine's own top folders are not read, the same names deeper are, and
    // the spec in OlmuseAudio/ opens with its sounds.
    $('folderLink').click();
    await until2(() => tiles().length === 1 && said() && !said().startsWith('Bringing'));
    out.read = log.filter((x) => x.startsWith('read ')).map((x) => x.slice(5)).sort();
    out.linked = [tiles().map((t) => t.dataset.id), tiles()[0] && tiles()[0].dataset.status];
    $('dialog').close();

    // A folder of the project that Olmuse did not write (Plugins/OlmuseAudio without its build file): nothing is written.
    $('exportBtn').click(); $('folderLink').click(); $('folderLink').click(); // unlink, link again: approved sounds are written
    await until2(() => (said() || '').includes('game folder'));
    out.refused = [said(), log.filter((x) => x.startsWith('write ')).length];
    $('dialog').close();

    // With the build file there, the files go under OlmuseAudio/ and the plugin folder; nothing at the project top.
    tree.Plugins.OlmuseAudio['olmuse_build.json'] = new TextEncoder().encode('{}');
    $('exportBtn').click(); $('folderLink').click(); $('folderLink').click();
    await until2(() => log.some((x) => x === 'write Plugins/OlmuseAudio/olmuse_build.json'));
    out.written = log.filter((x) => x.startsWith('write ')).map((x) => x.slice(6)).sort();
    $('dialog').close();

    // The bundle: the same layout, and opened again nothing in it counts as skipped.
    $('exportBtn').click(); $('exportGo').click();
    await until2(() => blobs.length > 0);
    const zipped = new Uint8Array(await blobs[0].arrayBuffer());
    out.zip = (await window.importer.unzip(zipped, 1e9)).map((z) => z.path).sort();
    $('importFiles').files = [new File([zipped], 'Linked-audio.zip')];
    $('importFiles').fire('change');
    await until2(() => (said() || '').includes('Linked'));
    out.reopened = said();

    // Without unreal.js the bundle says so and is not made without the engine's files.
    const kept = window.unrealExport; delete window.unrealExport;
    $('exportBtn').click(); $('exportGo').click();
    await until2(() => (said() || '').startsWith('Export failed'));
    out.noLib = [said(), blobs.length];
    window.unrealExport = kept;
"""


def test_the_unreal_export_is_chosen_written_under_its_folder_read_back_and_never_written_over_a_folder_not_its_own():
    """docs/ASSET_UNREAL_SPEC.md I1, the page's part (WP-D): the engine choice, the files of the bundle and of the linked
    game folder, the no-overwrite check, reading an Unreal project's folder, and the bundle opened again."""
    got = run_page("const importer = window.assetImporter;\n" + UNREAL_STORY)
    assert got["options"] == [["none", "None (files only)"], ["godot", "Godot 4"], ["unreal", "Unreal Engine 5"]]
    # Content/, Saved/, Config/ at the top are not read; Sub/Content/ is; the spec in OlmuseAudio/ is the board's spec
    assert got["read"] == ["OlmuseAudio/audio/ui/ui_x.wav", "OlmuseAudio/game-audio.spec.json", "Sub/Content/deep.wav"]
    assert got["linked"] == [["ui_x"], "approved"]
    assert got["refused"][0] == "Could not write to the game folder: Plugins/OlmuseAudio" and got["refused"][1] == 0
    w = got["written"]
    assert "OlmuseAudio/game-audio.spec.json" in w and "OlmuseAudio/audio/ui_x.wav" in w and "Plugins/OlmuseAudio/olmuse_build.json" in w
    assert not [p for p in w if not (p.startswith("OlmuseAudio/") or p.startswith("Plugins/OlmuseAudio/"))]
    z = got["zip"]
    assert "Plugins/OlmuseAudio/olmuse_build.json" in z and "OlmuseAudio/game-audio.spec.json" in z
    assert "game-audio.spec.json" not in z and not [p for p in z if p.startswith("audio/")]
    assert [p for p in z if p.endswith(".py")] and [p for p in z if p.endswith(".uplugin")]
    assert "Skipped" not in got["reopened"] and "Linked" in got["reopened"]
    assert got["noLib"] == ["Export failed: unreal.js", 1]


# ---------- the linked game folder: its engine is this computer's, and an Unreal project's top stays clean ----------

FOLDER_PRELUDE = UNREAL_STORY.split("    const log = [];")[0] + r"""
    const enc = (x) => new TextEncoder().encode(typeof x === 'string' ? x : JSON.stringify(x));
    const bundle = async (engine, status, id = 'ui_x') => {
      const spec = { game: `Linked ${engine} ${status}`, export: { engine }, categories: [{ id: 'ui', name: 'UI', kind: 'sfx' }],
        assets: [{ id, name: id, category: 'ui', file: `audio/ui/${id}.wav`, status, loop: false }] };
      const z = window.importer.zip([{ path: 'game-audio.spec.json', bytes: enc(spec) }, { path: `audio/ui/${id}.wav`, bytes: wav(500) }]);
      $('importFiles').files = [new File([z], 'Linked-audio.zip')];
      $('importFiles').fire('change');
      await until2(() => tiles().some((t) => t.dataset.id === id) && (said() || '').includes(`Linked ${engine} ${status}`));
    };
    const writes = (log) => log.filter((x) => x.startsWith('write ')).map((x) => x.slice(6)).sort();
    const link = async (tree, log, done) => {
      own('showDirectoryPicker', async () => dirOf(tree, '', log));
      $('exportBtn').click(); $('folderLink').click();
      await until2(done);
      $('dialog').close();
    };
"""

FOLDER_ENGINE_STORY = FOLDER_PRELUDE + r"""
    // An Unreal project linked while the board's engine is 'none': nothing lands at the project's top.
    await bundle('none', 'approved');
    const ulog = [], uproj = { 'Moon.uproject': enc('{}'), Content: {} };
    await link(uproj, ulog, () => ulog.some((x) => x.endsWith('olmuse_build.json')) || (said() || '').includes('game folder'));
    out.unreal = writes(ulog);
    $('exportBtn').click(); $('folderLink').click(); $('dialog').close(); // unlink

    // A plain folder linked with Godot chosen here. The board's engine then changes without this computer choosing it
    // (as a teammate's change comes in): the folder still gets what it was linked with.
    await bundle('godot', 'approved');
    const glog = [], plain = {};
    await link(plain, glog, () => glog.some((x) => x.endsWith('.gd')));
    await bundle('none', 'draft', 'ui_y');
    glog.length = 0;
    $('approveAll').click();
    await until2(() => glog.some((x) => x.endsWith('ui_y.wav')));
    await advance(500);
    out.godot = writes(glog);
"""


def test_the_linked_folder_keeps_this_computers_engine_and_an_unreal_projects_top_gets_nothing():
    got = run_page("const importer = window.assetImporter;\n" + FOLDER_ENGINE_STORY)
    u = got["unreal"]
    assert "Plugins/OlmuseAudio/olmuse_build.json" in u and "OlmuseAudio/game-audio.spec.json" in u
    assert not [p for p in u if not (p.startswith("OlmuseAudio/") or p.startswith("Plugins/OlmuseAudio/"))]
    g = got["godot"]
    assert "audio/ui_y.wav" in g and [p for p in g if p.endswith(".gd")]


FOLDER_CUT_STORY = FOLDER_PRELUDE + r"""
    // A first Unreal write cut short: the plugin descriptor and a script are there, the build file is not.
    await bundle('unreal', 'approved');
    const uplugin = enc({ FileVersion: 3, FriendlyName: 'Olmuse Audio', CreatedBy: 'Olmuse' });
    const log = [], tree = { 'Moon.uproject': enc('{}'), OlmuseAudio: { 'game-audio.spec.json': enc('{}') },
      Plugins: { OlmuseAudio: { 'OlmuseAudio.uplugin': uplugin, Content: { Python: { 'init_unreal.py': enc('#') } } } } };
    await link(tree, log, () => log.some((x) => x.endsWith('olmuse_build.json')) || (said() || '').includes('game folder'));
    out.resumed = [writes(log).includes('Plugins/OlmuseAudio/olmuse_build.json'), said()];
    $('exportBtn').click(); $('folderLink').click(); $('dialog').close(); // unlink

    // A plugin of that name somebody else made is still not written over.
    const flog = [], foreign = { 'Moon.uproject': enc('{}'), Plugins: { OlmuseAudio: { 'OlmuseAudio.uplugin': enc({ FileVersion: 3, CreatedBy: 'Someone' }) } } };
    await link(foreign, flog, () => (said() || '').includes('game folder'));
    out.foreign = [said(), writes(flog).length];
"""


def test_a_cut_short_first_unreal_write_is_resumed_by_the_plugin_descriptor_and_a_foreign_plugin_is_not():
    got = run_page("const importer = window.assetImporter;\n" + FOLDER_CUT_STORY)
    assert got["resumed"][0] is True, got["resumed"]
    assert got["foreign"] == ["Could not write to the game folder: Plugins/OlmuseAudio", 0]


def test_a_first_visit_opens_on_an_empty_board_and_the_guide_and_game_info_offer_no_stand_in_board():
    """Nothing saved: no sounds, the categories as they come, the game called a new one. How to use starts the guide
    (no dialog) at its first step, making an empty sound tile; the game info has the one way to start again, on an
    empty board."""
    got = run_page(PAGE_TOOLS.split("    const MADE")[0] + r"""
    out.board = [tiles().length, $('gameTitle').textContent, !!$('fillBtn'), !!$('approveAll'), $('side').querySelectorAll('button').map((b) => b.title).filter(Boolean)];
    $('menu').fire('click', { target: document.querySelector('#menu [data-act=help]') });
    const tour = $('tour');
    out.help = [!!$('dialog').open, tour.hidden, tour.querySelector('.tourStep').textContent, tour.querySelector('.tourText').textContent, !!tour.querySelector('#tourNext')];
    tour.querySelector('.tourClose').click();
    out.closed = tour.hidden;
    $('menu').fire('click', { target: document.querySelector('#menu [data-act=game]') });
    out.game = $('dialog').querySelectorAll('button').filter((b) => b.textContent).map((b) => [b.id, b.textContent]);
    """)
    assert got["board"] == [0, "New game", False, False, ["All", "UI", "Combat", "Character", "Ambience", "Music", "Add group"]]
    assert got["help"] == [False, False, "1 / 10", "Press + to put an empty sound tile in this group.", False]
    assert got["closed"] is True
    assert got["game"] == [["startBlank", "Start with an empty board"]]
