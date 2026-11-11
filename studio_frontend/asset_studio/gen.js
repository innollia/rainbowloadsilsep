// The asset room's side of the generation API (asset_api.py): the token the host page hands in, the price of a draft,
// asking for sounds, the one poller that brings them back, picking work up again after a reload, and what is said
// when drafts fail. fetch, the clocks and the timers are handed in, so Node runs this file in tests.
//
// assetGen.create(deps) -> one page's generator. deps (all optional but store and assets for a page that makes sounds):
//   store (assetStore.create(...)), assets() -> the live asset list,
//   fetch, now() (a clock that only runs forward, in ms: performance.now), wall() (Date.now), setTimeout, clearTimeout,
//   uuid(), sha256(bytes) -> hex, atob, measure (assetMeasure), peaks (assetStore.peaksOf),
//   project() -> { game, style, platform, loud }, item(asset, { mode, text }) -> what POST /jobs takes for one sound
//   (ref and mode are filled in here, and every field is cut to the length the API takes; a sound it throws for is
//   left out of the request and goes back to how it was, counted among the drafts that could not be made),
//   examples(list, opts) -> approved sounds to stay close to, lang(),
//   text(key, n) -> the wording of aiOff, genPaused, otherTab, loadFailed, saveFull, genFailed, genRefunded, genLost,
//   toast(text, ms), toastBusy() -> a toast with a button in it is up, post(type) -> a message to the host page,
//   hidden() -> the tab is in the background, render(list) -> the sounds in list changed and are drawn again,
//   progress(asset), done(asset, { made, mode, text, n }), onQuote() -> the price of a draft is known or has changed.
// The generator it returns:
//   token({ token, ttl, api }) -> true when it was taken, generate(list, { mode, text, drafts }) -> { ok, reason }
//   (text: the words for every sound of the list, or a function that gives each sound its own; the list goes out
//   together either way),
//   quoteOf(count, drafts) -> { items, drafts, unit, credits, free, known }, attach() (after a restore and with every
//   token), cancel(list) (sounds taken off the board: moved to the trash, the board replaced or started again),
//   drop(list) (drafts that were not kept: their records go, the server is told nothing), free(asset) -> it can be
//   asked for, check() (after a save: drafts whose sound reached the disk late), why() -> '' or the reason nothing
//   new is taken now, refuse() -> says that reason, and the flags ready, paused, identity, unit and unreached (the
//   price was asked for three times running and no answer of the API came back).
//
// A sound being made carries its job record, written before anything is sent:
//   a.work = { request, kind, who, mode, text, n, at, before, jobs: [{ id, k, got }] }
// kind and who say whose work it is (the token's kind, and the first 16 hex of the SHA-256 of its sub). Only records
// of the token in hand are touched: an account's by kind and who, a password session's by kind alone.
(function (factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  const root = typeof window !== 'undefined' ? window : typeof self !== 'undefined' ? self : null;
  if (root) root.assetGen = api;
})(function () {
  'use strict';

  const root = typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : {};
  const POLL_MS = 1500, HIDDEN_MS = 5000, FAR_MS = 3000, FAR_POSITION = 12; // how often the status is asked
  const RENEW_BEFORE = 60; // seconds before a token runs out that a newer one is asked for
  const TOKEN_WAIT_MS = 10000; // how long a 401 waits for another token
  const RESEND_MS = 600000; // a request the server never saw is sent again while it is younger than this
  const RETRY_MS = 5000, NOTICE_WAIT_MS = 500, NOTICE_MS = 7000;
  const QUOTE_RETRY_MS = 10000; // how often the price of a draft is read again while it is not known
  const QUOTE_MISSES = 3; // reads of the price in a row without an answer of the API, after which it counts as not reached
  const MAX_ITEMS = 64, MAX_DRAFTS = 4, MAX_IDS = 256, MAX_REFS = 8, MAX_EXAMPLES = 3, PEAKS = 200;
  // What the API takes (asset_generate.clean_request): a longer text is refused there, never cut, so it is cut here.
  const CAPS = { ref: 40, id: 64, name: 80, when: 300, description: 2000, change: 2000, game: 200, style: 1000, source: 20000, example: 4000 };
  const REF_CAPS = [['name', 120], ['url', 300], ['note', 600], ['summary', 400]];
  const KINDS = ['sfx', 'amb', 'music'], PLATFORMS = ['mobile', 'console', 'wide'], REF_KINDS = ['audio', 'midi', 'score', 'link', 'text'];
  const FACTS = ['peak', 'loud', 'seconds', 'clips', 'lead', 'tail', 'dc', 'seam', 'wrap', 'dip', 'low', 'mid', 'high', 'bright', 'rate', 'channels', 'bits', 'sample_peak', 'end'];
  // Half of a character pair on its own. JSON can carry one, the API cannot store it. A whole pair is matched first and
  // kept, so the pattern never looks behind: a browser that cannot read a look-behind would not load this file at all.
  const HALVES = /[\uD800-\uDBFF][\uDC00-\uDFFF]|[\uD800-\uDFFF]/g, REPLACED = String.fromCharCode(0xfffd);
  const paired = (s) => s.replace(HALVES, (m) => (m.length === 2 ? m : REPLACED));
  const halved = (s) => paired(s) !== s;

  /* ---------- what goes into a request ---------- */
  // Text the API can store: no half of a character pair on its own, and no longer than cap.
  function clip(text, cap) {
    const s = paired(typeof text === 'string' ? text : text == null ? '' : String(text)).slice(0, cap);
    const last = s.charCodeAt(s.length - 1);
    return last >= 0xd800 && last <= 0xdbff ? s.slice(0, -1) : s;
  }
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const positive = (v) => (num(v) != null && v > 0 ? v : null);
  // Measurements under measure.js names, numbers only.
  function factsOf(m) {
    const out = {};
    if (m && typeof m === 'object') for (const k of FACTS) if (num(m[k]) != null) out[k] = m[k];
    return out;
  }
  const refsOf = (list) => (Array.isArray(list) ? list : []).filter((r) => r && REF_KINDS.includes(r.kind)).slice(0, MAX_REFS).map((r) => {
    const out = { kind: r.kind };
    for (const [key, cap] of REF_CAPS) if (typeof r[key] === 'string' && r[key].trim()) out[key] = clip(r[key].trim(), cap);
    return out;
  });
  const styleOf = (s) => (s && typeof s === 'object' ? { name: clip(s.name, CAPS.name), seconds: positive(s.seconds), loop: !!s.loop, facts: factsOf(s.facts) } : null);
  // A sound whose patch is known is changed from the patch; any other is described by its measurements.
  function baseOf(b) {
    if (!b || typeof b !== 'object') return null;
    if (typeof b.source === 'string' && b.source.trim() && b.source.length <= CAPS.source && !halved(b.source)) return { source: b.source, seconds: positive(b.seconds), bpm: num(b.bpm) };
    return { facts: factsOf(b.facts) };
  }
  function shapeItem(ref, raw, mode) {
    const x = raw || {};
    const item = {
      ref, mode, kind: KINDS.includes(x.kind) ? x.kind : 'sfx', loop: !!x.loop,
      id: clip(x.id, CAPS.id), name: clip(x.name, CAPS.name), when: clip(x.when, CAPS.when), description: clip(x.description, CAPS.description),
      seconds: positive(x.seconds), bpm: num(x.bpm), references: refsOf(x.references),
      style_ref: styleOf(x.style_ref), base: baseOf(x.base), change: clip(x.change, CAPS.change),
    };
    // A change needs something to change. With nothing to go by, the sound is made from its description.
    if (mode === 'revise' && !item.base) item.base = { facts: {} };
    return item;
  }
  function shapeProject(p) {
    const x = p || {}, out = { game: clip(x.game, CAPS.game), style: clip(x.style, CAPS.style), platform: PLATFORMS.includes(x.platform) ? x.platform : 'mobile' };
    const l = x.loud;
    if (Array.isArray(l) && l.length === 2 && num(l[0]) != null && num(l[1]) != null && l[0] >= -70 && l[0] <= l[1] && l[1] <= 0) out.loud = [l[0], l[1]];
    return out;
  }
  // An example is the patch of an approved sound. One too long to send whole is left out: half a patch teaches nothing.
  const shapeExamples = (list) => (Array.isArray(list) ? list : []).filter((e) => e && KINDS.includes(e.kind) && typeof e.source === 'string' && e.source.length <= CAPS.example && !halved(e.source))
    .slice(0, MAX_EXAMPLES).map((e) => ({ name: clip(e.name, CAPS.name), kind: e.kind, loop: !!e.loop, source: e.source, facts: factsOf(e.facts) }));

  /* ---------- the token ---------- */
  // Only the host page's own message counts: from the parent window, and from this page's origin.
  const fromHost = (e, parent, origin) => !!e && e.source === parent && e.origin === origin;
  // kind and sub of a token's payload. Nothing else is read from it; whether it has run out is the server's to say.
  function readToken(token, decode) {
    try {
      const part = String(token).split('.')[0], p = JSON.parse((decode || root.atob)(part.replace(/-/g, '+').replace(/_/g, '/')));
      return p && (p.kind === 'acct' || p.kind === 'pw') && typeof p.sub === 'string' && p.sub ? { kind: p.kind, sub: p.sub } : null;
    } catch { return null; }
  }
  async function sha256(bytes) {
    const subtle = root.crypto && root.crypto.subtle;
    if (!subtle) return null;
    return [...new Uint8Array(await subtle.digest('SHA-256', bytes))].map((b) => b.toString(16).padStart(2, '0')).join('');
  }
  const versionKeys = (v) => [v.key, ...(v.stems || []).map((s) => s.key)];
  // A result as it is told once the sound went out: the engine, the source, the prompt and the stem names are in it.
  const told = (result) => typeof result.engine === 'string';

  function create(deps) {
    const d = deps || {}, store = d.store;
    const fetcher = d.fetch || ((url, init) => root.fetch(url, init));
    const mono = d.now || (() => root.performance.now()), wall = d.wall || (() => Date.now());
    const later = d.setTimeout || ((fn, ms) => setTimeout(fn, ms)), unlater = d.clearTimeout || ((t) => clearTimeout(t));
    const digest = d.sha256 || sha256;
    const uuid = d.uuid || (() => (root.crypto && root.crypto.randomUUID ? root.crypto.randomUUID() : `r${Math.floor(wall()).toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`));
    const measurer = () => d.measure || root.assetMeasure;
    const peaksOf = (chans) => (d.peaks || root.assetStore.peaksOf)(chans, PEAKS);
    const say = (key, n) => (d.text ? d.text(key, n) : key);
    const toast = (text, ms) => { if (d.toast && text) d.toast(text, ms); };
    const post = (type) => { if (d.post) d.post(type); };
    const render = (list) => { if (d.render && list.length) d.render(list); };
    const live = () => (d.assets ? d.assets() : []);

    // token: { token, api, kind, sub, who, at, ttl }. unit: { unit, free }, the price of one draft for that token.
    // paused: a 401 that another token did not cure. Nothing is asked or sent until a token with another string comes.
    const state = { token: null, unit: null, paused: false, pausedOn: '' };
    // flying: requests this page is sending right now. fetched: drafts in memory whose sound is not on disk yet.
    // skipped: jobs whose bytes came wrong twice, left for the next visit. barred: jobs the server will not show this
    // token; their sound stays as it is. seen: the last view of each job still being made.
    // answered: requests whose job ids this page has been given; a record of one that has no job left is settled, not
    // asked about again. unsent: cancels the server has not confirmed, told again when work is next picked up.
    // had: the bytes of a finished job, master and stems, that all came while what is told of it afterwards did not.
    // The next look makes the draft from them. They are let go with the job's record.
    const flying = new Set(), fetched = new Map(), skipped = new Set(), barred = new Set(), seen = new Map(), answered = new Set(), waiters = new Set(), had = new Map();
    const unsent = { ids: new Set(), requests: new Set() };
    const owed = { failed: 0, refunded: 0, lost: 0 };
    let tokenN = 0, renewTimer = 0, asking = null, pollTimer = 0, ticking = false, pollAgain = false;
    let attaching = null, attachAgain = false, attachTimer = 0, attachAt = 0, attachRest = 0, noteTimer = 0;
    // quoting: the read of the price that is under way, and whose it is. unitTimer: the next read while the price is
    // not known. unitRest: nothing asks for the price before this moment (a 429 said how long). unitMisses: reads in
    // a row that brought no answer the API wrote (nothing at all, or another server's page).
    let quoting = null, unitTimer = 0, unitRest = 0, unitMisses = 0;
    // What the downloads of one look were told: fetchWait, the wait (ms) a 503 or a 429 named, and fetchLimited, a 429.
    let fetchWait = 0, fetchLimited = false;

    // Whose a record is: an account's by kind and who, a password session's by kind alone.
    const owns = (tok, w) => !!w && !!tok && w.kind === tok.kind && (w.kind !== 'acct' || w.who === tok.who);
    const mine = (w) => owns(state.token, w);
    const usable = () => !!state.token && !state.paused && !!store && !!store.writable;
    const isOpen = (j) => !j.got && !fetched.has(j.id) && !skipped.has(j.id) && !barred.has(j.id);
    // Whether the sound's record still names the job: it does not once the sound was put back or taken off the board.
    const holds = (a, j) => !!a.work && a.work.jobs.includes(j);
    // A sound is settled once none of its jobs is still being waited for. One with a barred job is never settled here.
    const waiting = (w) => w.jobs.some((j) => isOpen(j) || barred.has(j.id));
    // Whether a sound can be asked for: it has no job record, or one with nothing left to wait for on this visit (what
    // is left of it are jobs whose bytes came wrong twice, which asking again lets go).
    const free = (a) => !!a && (!a.work || (mine(a.work) && a.status !== 'working' && a.work.jobs.length > 0 && a.work.jobs.every((j) => j.got || skipped.has(j.id))));
    const refOf = (a) => clip(a.key, CAPS.ref);
    const newKey = () => `k${Math.floor(wall()).toString(36)}${Math.random().toString(36).slice(2, 8)}`;

    /* ---------- token ---------- */
    async function takeToken(msg) {
      const at = mono(), text = msg && typeof msg.token === 'string' ? msg.token : '', read = text ? readToken(text, d.atob) : null;
      if (!read || typeof msg.api !== 'string') return false;
      const n = ++tokenN;
      let who = null;
      try { const h = await digest(new TextEncoder().encode(read.sub)); who = h ? String(h).slice(0, 16) : null; } catch { who = null; }
      if (!who || n !== tokenN) return false;
      const was = state.token, ttl = num(Number(msg.ttl)) ?? 0;
      const next = { token: text, api: msg.api.replace(/\/+$/, ''), kind: read.kind, sub: read.sub, who, at, ttl };
      state.token = next;
      // Counted from the moment it came, on a clock that does not jump. The browser's date is never compared with exp.
      unlater(renewTimer);
      renewTimer = later(() => { renewTimer = 0; post('asset:token?'); }, Math.max(0, (ttl - RENEW_BEFORE) * 1000 - (mono() - at)));
      if (!was || was.token !== text) for (const w of [...waiters]) { waiters.delete(w); w(next); }
      if (state.paused && text !== state.pausedOn) state.paused = false;
      if (!was || was.kind !== next.kind || was.sub !== next.sub) { state.unit = null; unitRest = 0; unitMisses = 0; seen.clear(); skipped.clear(); barred.clear(); had.clear(); loadUnit(); }
      // The price did not come with the token before this one: it is read again with every token until it has.
      else if (!state.unit && !state.paused && mono() >= unitRest) loadUnit();
      // A cancel is the canceller's to send: one still owed is let go when the token is someone else's.
      if (was && !owns(next, was)) { unsent.ids.clear(); unsent.requests.clear(); }
      attach(); kick();
      return true;
    }
    // A token whose string is not `held`: the one in hand if it already differs, else the host is asked and waited for.
    function newerToken(held) {
      if (state.token && state.token.token !== held) return Promise.resolve(state.token);
      if (!asking) {
        post('asset:token?');
        asking = new Promise((ok) => {
          const done = (tok) => { unlater(timer); ok(tok); };
          const timer = later(() => { waiters.delete(done); ok(null); }, TOKEN_WAIT_MS);
          waiters.add(done);
        });
        asking.then(() => { asking = null; });
      }
      return asking;
    }
    function pause(on) {
      if (state.paused) return;
      state.paused = true; state.pausedOn = on;
      unlater(pollTimer); pollTimer = 0;
      toast(say('genPaused'), 8000);
    }

    /* ---------- one call ---------- */
    // { status, data, bytes, code, message, retry }. status 0: no answer came. A 401 asks the host for another token,
    // waits up to ten seconds for one and tries once more; a second 401, or no token, stops everything (pause).
    // opts.as (a job record): the call is that person's. With a token that is someone else's nothing is sent and the
    // answer is { status: 0, other: true }.
    async function call(method, path, body, opts) {
      const o = opts || {};
      const once = async (tok) => {
        const headers = { Authorization: 'Bearer ' + tok.token }, init = { method, headers, cache: 'no-store' };
        if (body !== undefined) { headers['Content-Type'] = 'application/json'; init.body = body; }
        if (o.keepalive) init.keepalive = true;
        let res;
        try { res = await fetcher(tok.api + path, init); } catch { return { status: 0 }; }
        const out = { status: res.status, data: null, code: '', message: '', retry: 0 };
        try {
          if (o.bytes && res.status === 200) out.bytes = new Uint8Array(await res.arrayBuffer());
          else out.data = await res.json();
        } catch { if (o.bytes && res.status === 200) return { status: 0 }; }
        const err = out.data && typeof out.data === 'object' ? out.data.error : null;
        if (err && typeof err === 'object') {
          if (typeof err.code === 'string') out.code = err.code;
          if (typeof err.message === 'string') out.message = err.message;
        }
        const head = res.headers && typeof res.headers.get === 'function' ? Number(res.headers.get('Retry-After')) : 0;
        const wait = err && num(Number(err.retry_after)) != null ? Number(err.retry_after) : head;
        if (num(wait) != null && wait > 0) out.retry = wait;
        return out;
      };
      const tok = state.token;
      if (!tok) return { status: 0 };
      if (o.as && !owns(tok, o.as)) return { status: 0, other: true };
      let r = await once(tok);
      if (r.status !== 401 || state.paused) return r;
      const next = await newerToken(tok.token);
      if (next && o.as && !owns(next, o.as)) return { status: 0, other: true };
      if (next) r = await once(next);
      if (!next || r.status === 401) pause(next ? next.token : tok.token);
      return r;
    }

    /* ---------- the price of a draft ---------- */
    // Reads the price for the person the token names. One read at a time for one person: a second asker gets the
    // answer of the read under way. A read that brings no price while none is known is tried again by itself: ten
    // seconds on, or after the rest a 429 asked for. A paused page waits for its next token instead.
    function loadUnit() {
      const tok = state.token;
      if (!tok) return Promise.resolve({ status: 0 });
      if (quoting && quoting.kind === tok.kind && quoting.sub === tok.sub) return quoting.read;
      const mine = { kind: tok.kind, sub: tok.sub, read: null };
      mine.read = (async () => {
        let r = { status: 0 };
        try { r = await call('GET', '/quote?items=1&drafts=1'); } finally { if (quoting === mine) quoting = null; }
        const now = state.token;
        if (!now || now.kind !== tok.kind || now.sub !== tok.sub) return r; // someone else's token came meanwhile: their price is being read
        if (r.status === 200 && r.data && num(r.data.unit) != null) setUnit(r.data.unit, r.data.free);
        else {
          // An error with a code is the API's own answer: it is there. Anything else is one more read it did not answer.
          unitMisses = r.code || r.status === 401 ? 0 : unitMisses + 1;
          if (!state.unit && !state.paused) retryUnit(r.status === 429 ? r.retry * 1000 : 0);
        }
        return r;
      })();
      quoting = mine;
      return mine.read;
    }
    function retryUnit(rest) {
      const wait = Math.max(QUOTE_RETRY_MS, rest || 0);
      unitRest = rest ? mono() + wait : 0;
      unlater(unitTimer);
      unitTimer = later(() => { unitTimer = 0; if (!state.unit && state.token && !state.paused) loadUnit(); }, wait);
    }
    // onQuote tells the page: the price has come (a first read, or one that failed before) or is another now. Its
    // labels say the number, and it takes requests it had to turn away while no label could.
    function setUnit(unit, free) {
      const was = state.unit;
      state.unit = { unit, free: !!free };
      unlater(unitTimer); unitTimer = 0; unitRest = 0; unitMisses = 0;
      if ((!was || was.unit !== unit || was.free !== !!free) && d.onQuote) d.onQuote();
    }
    // The one sum the labels and generate() both use. credits is null until the price is known.
    function quoteOf(count, drafts) {
      const u = state.unit;
      return { items: count, drafts, unit: u ? u.unit : null, credits: u ? count * drafts * u.unit : null, free: !!u && u.free, known: !!u };
    }

    /* ---------- asking for sounds ---------- */
    // Why nothing new is taken right now, or ''. 'wait' has no words: the board is still being read.
    function why() {
      if (!state.token) return 'aiOff';
      if (state.paused) return 'genPaused';
      if (!store || !store.locked || store.readOnly) return 'otherTab';
      if (store.paused) return 'loadFailed';
      if (!store.writable) return 'wait';
      if (store.blobFull) return 'saveFull';
      return '';
    }
    function refuse() {
      const key = why();
      if (key && key !== 'wait') toast(say(key), key === 'aiOff' ? 4000 : 8000);
      return !!key;
    }
    // A job record is let go: bytes that were kept for its jobs' next look go with it, now and not at a later look
    // (with nothing left to wait for there is none).
    const unhold = (w) => { for (const j of w.jobs) had.delete(j.id); };
    // The sound goes back to how it was before it was asked for; drafts of that request are dropped.
    function undo(a) {
      const w = a.work;
      if (!w) return;
      if (a.status === 'working') {
        const ids = new Set(w.jobs.map((j) => j.id));
        a.drafts = a.drafts.filter((v) => !ids.has(v.id));
        a.status = w.before;
      }
      unhold(w);
      a.progress = 0; delete a.work;
    }
    const asked = (request) => live().filter((a) => a.work && a.work.request === request);

    async function generate(assets, opts) {
      const o = opts || {}, mode = o.mode === 'revise' ? 'revise' : 'make', text = typeof o.text === 'string' ? o.text : '';
      // The words of a sound: the one text for all of them, or what the function gives for that sound.
      const wordsOf = typeof o.text === 'function' ? (a) => { const s = o.text(a); return typeof s === 'string' ? s : ''; } : () => text;
      const n = Math.min(MAX_DRAFTS, Math.max(1, Math.floor(Number(o.drafts)) || 1));
      const todo = [...new Set(assets || [])].filter(free);
      if (!todo.length) return { ok: false, reason: 'none' };
      const key = why();
      if (refuse()) return { ok: false, reason: key };
      // Marked before anything is waited for, so a second press finds nothing left to ask for.
      const tok = state.token, at = wall(), batches = [];
      for (let i = 0; i < todo.length; i += MAX_ITEMS) {
        const request = clip(uuid(), 64);
        for (const a of todo.slice(i, i + MAX_ITEMS)) {
          if (!a.key) a.key = newKey();
          a.work = { request, kind: tok.kind, who: tok.who, mode, text: wordsOf(a), n, at, before: a.status, jobs: [] };
          a.status = 'working'; a.progress = 0;
        }
        flying.add(request); batches.push(request);
      }
      render(todo);
      let out = { ok: true };
      try {
        for (const [i, request] of batches.entries()) {
          const r = await ask(request, { mode, text, n });
          if (r.ok) continue;
          out = r;
          // The server said no: the rest of what was asked would hear the same. A request of which nothing could be
          // put together ('body') was not the server's answer: the next one is still sent.
          if (!r.pending && r.reason !== 'body') { const rest = batches.slice(i + 1).flatMap(asked); rest.forEach(undo); render(rest); break; }
        }
      } finally { for (const request of batches) flying.delete(request); }
      return out;
    }
    // One request: the words that will be sent are kept, then the board that says which sounds are being made, and
    // only then is anything sent. A board that could not be written sends nothing.
    // What is told of each sound is put together one sound at a time. A sound for which that fails (the page's item()
    // threw) goes back to how it was, alone: the others are sent and paid for without it. What could not be asked for
    // is said as drafts that could not be made, and only after this has waited once: the page says its own words
    // right after it asks ("Making 4", the assistant's reply), and those must not be what is left standing.
    async function ask(request, o) {
      const back = (text, ms) => { const list = asked(request); list.forEach(undo); render(list); toast(text, ms); };
      const priced = state.unit ? null : await loadUnit();
      let group = asked(request);
      if (!group.length) return { ok: false, reason: 'none' };
      // The token became someone else's while this waited: nothing is made in another person's name.
      if (!mine(group[0].work)) { back(''); return { ok: false, reason: 'other' }; }
      if (!state.unit) { back(priced.status === 401 ? '' : priced.message || say('aiOff'), 6000); return { ok: false, reason: priced.code || 'aiOff' }; }
      const items = new Map();
      for (const a of group) {
        try { items.set(a, shapeItem(refOf(a), d.item ? d.item(a, { mode: o.mode, text: a.work.text }) : null, o.mode)); } catch { /* goes back below */ }
      }
      const dropped = group.filter((a) => !items.has(a));
      dropped.forEach(undo); render(dropped);
      group = group.filter((a) => items.has(a));
      let body = null;
      try {
        if (group.length) body = JSON.stringify({
          request_id: request, expect_credits: quoteOf(group.length, o.n).credits, drafts: o.n, lang: d.lang ? d.lang() : undefined,
          project: shapeProject(d.project ? d.project() : null),
          examples: shapeExamples(d.examples ? d.examples(group, { mode: o.mode, text: o.text, drafts: o.n }) : []),
          items: group.map((a) => items.get(a)),
        });
      } catch { body = null; }
      if (body == null) {
        // Nothing of the request can be sent. As with a request the server turned away, that is said at once.
        back('');
        await null;
        toast(say('genFailed', (dropped.length + group.length) * o.n), 6000);
        return { ok: false, reason: 'body' };
      }
      const kept = (await store.put('req:' + request, body)) && (await store.saveBoard());
      if (dropped.length) tell({ failed: dropped.length * o.n, refunded: 0, lost: 0 });
      if (!kept) { back(say('saveFull'), 8000); store.del('req:' + request); return { ok: false, reason: 'saveFull' }; }
      return send(request, body);
    }
    // POSTs the stored words as they are, as the person the records name. Only an answer the API wrote says what became
    // of the request: its jobs, or an error with a code. Anything else (no answer, a proxy's 502 or 504, a 200 cut
    // short) may have reached the server all the same, so the records and the words stay and attach() asks what the
    // server knows of the request. again: this is attach() sending a request once more.
    async function send(request, body, again) {
      const group = asked(request);
      if (!group.length) { store.del('req:' + request); return { ok: false, reason: 'none' }; } // every sound of it was taken off the board meanwhile
      const r = await call('POST', '/jobs', body, { as: group[0].work });
      if (r.other) {
        // The token in hand is someone else's now and nothing was sent. What was just asked for goes back. A request
        // being picked up again is its owner's: it waits for them.
        if (again) return { ok: false, pending: true, reason: 'other' };
        asked(request).forEach(undo); store.del('req:' + request);
        render(group); await store.saveBoard();
        return { ok: false, reason: 'other' };
      }
      const taken = r.status === 200 && !!r.data && Array.isArray(r.data.jobs);
      if (!taken && !r.code && r.status !== 401) { retryLater(); return { ok: false, pending: true, reason: 'offline' }; }
      if (taken) {
        const note = { failed: 0, refunded: 0, lost: 0 };
        adopt(request, r.data.jobs, note);
        await store.saveBoard(); store.del('req:' + request);
        render(group); tell(note); kick();
        return { ok: true };
      }
      asked(request).forEach(undo);
      store.del('req:' + request);
      if (r.status === 409 && r.code === 'quote_changed') {
        // The price is not what the label showed. The new one is read and shown; nothing is sent again by itself.
        const q = r.data.error.quote;
        if (q && num(q.unit) != null) setUnit(q.unit, q.free);
        await loadUnit();
      }
      render(group);
      if (r.status !== 401) toast(r.message || say('aiOff'), 6000);
      await store.saveBoard();
      return { ok: false, reason: r.code || String(r.status) };
    }
    // The job ids of a request go to the sounds they were made for, and only to a sound that has none yet: what a
    // sound already holds (a draft that has arrived) is not asked for twice. A job whose sound is gone (trashed
    // meanwhile) is cancelled while it is still being made. A view without a ref is a result the server no longer
    // has: it is counted in note, as refunded when the server says so and as lost when it does not.
    function adopt(request, jobs, note) {
      const group = asked(request), byRef = new Map(group.map((a) => [refOf(a), a])), empty = new Set(group.filter((a) => !a.work.jobs.length)), stray = [];
      answered.add(request);
      for (const j of jobs) {
        if (!j || typeof j.id !== 'string') continue;
        const a = byRef.get(j.ref);
        if (a) { if (empty.has(a)) a.work.jobs.push({ id: j.id, k: j.k, got: false }); }
        else if (j.status === 'gone' || j.status === 'unknown') { if (j.refund === 'done' || j.refund === 'pending') note.refunded++; else note.lost++; }
        else if (j.status === 'queued' || j.status === 'running') stray.push(j.id);
      }
      for (const a of empty) if (!a.work.jobs.length) undo(a);
      if (stray.length) stop(stray, []);
    }

    /* ---------- the poller: one for the page ---------- */
    function kick() {
      if (ticking) { pollAgain = true; return; }
      if (pollTimer || !usable()) return;
      pollTimer = later(tick, 0);
    }
    async function tick() {
      pollTimer = 0;
      if (ticking || !usable()) return;
      ticking = true; pollAgain = false;
      let wait = null;
      try { wait = await round(); } catch { wait = POLL_MS; } finally { ticking = false; }
      if (wait == null && pollAgain) wait = 0;
      if (wait != null && usable() && !pollTimer) pollTimer = later(tick, wait);
    }
    // How long until the next look: 5 s in a hidden tab, 3 s while every job waits far back in the queue, else 1.5 s.
    // null when no job is left to wait for: the poller stops until the next one is asked for.
    function pace() {
      let open = 0, far = 0;
      for (const a of live()) {
        if (!mine(a.work)) continue;
        for (const j of a.work.jobs) {
          if (!isOpen(j)) continue;
          open++;
          const v = seen.get(j.id);
          if (v && v.status === 'queued' && v.position > FAR_POSITION) far++;
        }
      }
      if (!open) return null;
      if (d.hidden && d.hidden()) return HIDDEN_MS;
      return far === open ? FAR_MS : POLL_MS;
    }
    const progressOf = (w) => (w.jobs.length ? w.jobs.reduce((sum, j) => sum + (isOpen(j) ? num((seen.get(j.id) || {}).progress) || 0 : 1), 0) / w.jobs.length : 0);
    // One look at every job still open. Returns the wait before the next one, or null when nothing is left to wait for.
    async function round() {
      const open = [];
      for (const a of live()) if (mine(a.work)) for (const j of a.work.jobs) if (isOpen(j)) open.push({ a, j });
      for (const id of [...had.keys()]) if (!open.some((x) => x.j.id === id)) had.delete(id); // its job is no longer waited for
      if (!open.length) return null;
      const views = new Map();
      for (let i = 0; i < open.length; i += MAX_IDS) {
        const r = await call('POST', '/jobs/status', JSON.stringify({ ids: open.slice(i, i + MAX_IDS).map((x) => x.j.id) }));
        if (r.status === 401) return null;
        if (r.status === 429) return Math.max(1, r.retry) * 1000;
        if (r.status !== 200 || !r.data || !Array.isArray(r.data.jobs)) return pace();
        for (const v of r.data.jobs) if (v && typeof v.id === 'string') views.set(v.id, v);
      }
      const note = { failed: 0, refunded: 0, lost: 0 }, touched = new Set();
      let changed = false;
      fetchWait = 0; fetchLimited = false;
      for (const { a, j } of open) {
        const v = views.get(j.id), w = a.work;
        if (!v || !w || !w.jobs.includes(j)) continue; // taken back while the answer was on its way
        touched.add(a);
        if (v.status === 'queued' || v.status === 'running') { seen.set(j.id, v); continue; }
        seen.delete(j.id);
        if (v.status !== 'done') had.delete(j.id); // no result after all: its bytes are let go
        if (v.status === 'done') { if (!fetchLimited && (await receive(a, j, v, note))) changed = true; } // after a 429 this look fetches nothing more
        else if (v.status === 'forbidden') barred.add(j.id); // not this token's to see: left as it is
        else {
          // It ended without a sound, and the record lets it go. A refund is only spoken of when the server says so.
          w.jobs.splice(w.jobs.indexOf(j), 1); changed = true;
          const back = v.refund === 'done' || v.refund === 'pending';
          if (v.status === 'failed') { note.failed++; if (back) note.refunded++; }
          else if (v.status === 'gone') { if (back) note.refunded++; else note.lost++; }
          else if (v.status === 'unknown') note.lost++;
        }
        if (state.paused) break;
      }
      const ended = [];
      for (const a of touched) {
        const w = a.work;
        if (!w) continue;
        if (waiting(w)) {
          if (a.status === 'working') { a.progress = progressOf(w); if (d.progress) d.progress(a); }
          continue;
        }
        finish(a); ended.push(a);
      }
      if (changed || ended.length) await store.saveBoard();
      // Only the sounds that ended are drawn again: a view of another sound (a request being typed there) is left alone.
      if (ended.length) { render(ended); post('asset:account'); }
      tell(note);
      const next = pace();
      return next == null ? null : Math.max(next, fetchWait);
    }
    // An answer that was no sound. One that names a wait (a 503 for a file that is there and could not be read just
    // then, a 429) puts the next look off by that long: the draft stays in its record and is fetched then.
    function putOff(r) {
      if (r.retry) fetchWait = Math.max(fetchWait, r.retry * 1000);
      if (r.status === 429) fetchLimited = true;
    }
    // The bytes of a result, checked against the sha the status named. Wrong bytes are fetched once more.
    // 'later': no answer or not there yet, so the next round tries again. null: wrong twice.
    async function download(path, sha) {
      for (let i = 0; i < 2; i++) {
        const r = await call('GET', path, undefined, { bytes: true });
        if (r.status !== 200 || !r.bytes) { putOff(r); return 'later'; }
        let got = null;
        try { got = await digest(r.bytes); } catch { got = null; }
        if (!sha || got == null || got === sha) return r.bytes;
      }
      return null;
    }
    // A finished job becomes a draft: master and stems are fetched and checked, the status is read once more for what
    // is only told after the sound went out (source, prompt, stem names, measurements), and every Blob is written.
    // got is set only when all of them are on disk. A draft that is not plays from memory and keeps its id in the
    // record, so the next visit fetches it again. Returns whether the board changed.
    // When every file came and that second read of the status did not (a 429, no answer, a proxy's page), the bytes
    // stay in hand: the next look was asked after the sound went out, so its view says all of it, and the draft is
    // made from that and the bytes with no file fetched twice.
    async function receive(a, j, view, note) {
      const res = view.result || {}, id = j.id;
      const wrong = () => { skipped.add(id); note.failed++; return true; };
      let got = had.get(id), full = got && told(res) ? view : null;
      if (!got) {
        const main = await download(`/jobs/${id}/sound`, res.sha256), parts = [];
        if (main === 'later') return false;
        if (!main) return wrong();
        for (const s of Array.isArray(res.stems) ? res.stems : []) {
          const bytes = await download(`/jobs/${id}/stems/${s.n}`, s.sha256);
          if (bytes === 'later') return false;
          if (!bytes) return wrong();
          parts.push({ n: s.n, bytes });
        }
        got = { main, parts };
      }
      if (!full) {
        const r = await call('POST', '/jobs/status', JSON.stringify({ ids: [id] }));
        const views = r.status === 200 && r.data && Array.isArray(r.data.jobs) ? r.data.jobs : null;
        full = views ? views.find((x) => x && x.id === id) : null;
        // Kept for the look that follows, and only for a job its sound still waits for: a sound taken off the board
        // while this read was on its way has no look to follow, and the poller may stop here.
        if (!views) { if (holds(a, j)) had.set(id, got); else had.delete(id); putOff(r); return false; }
        if (!full || full.status !== 'done' || !full.result) { had.delete(id); return false; } // it is no longer a result: the next look says what became of it
      }
      had.delete(id);
      const w = a.work, { main, parts } = got;
      if (!holds(a, j)) return false;
      const v = versionOf(a, j, full.result, main, parts), blobs = [[v.key, new Blob([main], { type: 'audio/wav' })]];
      v.stems.forEach((s, i) => blobs.push([s.key, new Blob([parts[i].bytes], { type: 'audio/wav' })]));
      for (const [key, blob] of blobs) store.hold(key, blob);
      a.drafts = [...a.drafts.filter((x) => x.id !== v.id), v];
      fetched.set(id, v);
      let ok = true;
      for (const [key, blob] of blobs) ok = (await store.saveBlob(key, blob)) && ok;
      if (ok) { j.got = true; fetched.delete(id); await store.saveBoard(); }
      return true;
    }
    // The version record of a generated sound. Its id is the job's, so fetching it twice still makes one version.
    function versionOf(a, j, r, main, parts) {
      const w = a.work, id = j.id, now = a.versions[a.current], named = Array.isArray(r.stems) ? r.stems : [];
      let wav = null, peaks = new Array(PEAKS).fill(0), m = r.measure && typeof r.measure === 'object' ? r.measure : null;
      try { wav = measurer().readWav(main); peaks = peaksOf(wav.chans); if (!m) m = measurer().measure(wav); } catch { /* drawn flat */ }
      if (!m) m = { seconds: num(r.seconds) ?? 0 };
      return {
        id, at: wall(), note: w.n > 1 ? { key: 'draft', text: w.text || '', k: j.k } : w.mode === 'revise' && w.text ? w.text : { key: 'fromPrompt' },
        engine: 'nkido', job: id, parent: w.mode === 'revise' && now ? now.id : null, draft: { k: j.k, n: w.n },
        source: typeof r.source === 'string' ? r.source : null, seconds: num(r.seconds) ?? num(m.seconds) ?? 0, bpm: num(r.bpm),
        prompt: typeof r.prompt === 'string' ? r.prompt : null, model: typeof r.model === 'string' ? r.model : null,
        sources: Array.isArray(r.sources) ? r.sources : [],
        measure: m, issues: Array.isArray(r.issues) ? r.issues : [], peaks,
        key: `ver:${id}`,
        stems: parts.map((p) => { const s = named.find((x) => x && x.n === p.n) || {}; return { label: typeof s.label === 'string' ? s.label : '', key: `ver:${id}:s${p.n}`, bytes: p.bytes.length, sha256: s.sha256 || null }; }),
        rate: num(r.rate) ?? (wav ? wav.rate : null), channels: num(r.channels) ?? (wav ? wav.chans.length : null), bits: num(r.bits) ?? (wav ? wav.bits : null),
        bytes: main.length, sha256: r.sha256 || null,
      };
    }
    // Every job of a sound has ended. A sound that had no version and got one draft has its first version. Otherwise
    // the drafts wait for the user to pick one. With no draft at all the sound is as it was before.
    function finish(a) {
      const w = a.work, ids = new Set(w.jobs.map((j) => j.id)), order = (x, y) => ((x.draft && x.draft.k) || 0) - ((y.draft && y.draft.k) || 0);
      const first = (v) => { a.versions = [v]; a.current = 0; a.drafts = []; a.pick = -1; a.status = 'draft'; };
      if (a.status === 'working') {
        const fresh = a.drafts.filter((v) => ids.has(v.id)).sort(order);
        if (!fresh.length) {
          a.status = w.before;
          // Back under review with the drafts it had and no version: one of them is the one heard, as before.
          if (a.status === 'review' && !a.versions.length && a.drafts.length && !a.drafts[a.pick]) a.pick = 0;
        } else if (!a.versions.length && fresh.length === 1) first(fresh[0]);
        else { a.drafts = fresh; a.pick = 0; a.status = 'review'; }
        a.progress = 0;
        if (d.done) d.done(a, { made: fresh.length, mode: w.mode, text: w.text, n: w.n });
      } else {
        // A draft fetched again on a later visit joins a sound that has moved on since.
        const late = a.drafts.filter((v) => ids.has(v.id));
        if (late.length && a.status !== 'review') {
          if (!a.versions.length && a.drafts.length === 1) first(late[0]);
          else { a.pick = Math.max(0, a.drafts.indexOf(late[0])); a.status = 'review'; }
        } else if (late.length && !(a.pick >= 0) && !a.versions.length) a.pick = 0;
      }
      if (w.jobs.every((j) => j.got)) delete a.work;
    }
    // Records a reload left half done: every job ended but the sound was not settled, or settled with its record still
    // there. A record with no job at all is a request without an answer, which reattach() asks about, unless its
    // answer came on this visit: then its jobs all ended without a sound in a look that never got to settle it.
    // Returns the sounds it settled.
    function sweep() {
      const done = [];
      for (const a of live()) {
        const w = a.work;
        if (!mine(w) || waiting(w)) continue;
        if (w.jobs.length ? a.status === 'working' || w.jobs.every((j) => j.got) : !ticking && answered.has(w.request) && !flying.has(w.request)) { finish(a); done.push(a); }
      }
      return done;
    }
    // After a save: a draft whose sound did not fit earlier and is on disk now counts as received.
    function check() {
      const shown = [];
      let changed = false;
      for (const a of live()) {
        const w = a.work;
        if (!w) continue;
        let moved = false;
        for (const j of w.jobs) {
          const v = fetched.get(j.id);
          if (!j.got && v && versionKeys(v).every((k) => store.saved.has(k))) { j.got = true; fetched.delete(j.id); moved = true; }
        }
        // Settled the way a look settles it: a draft fetched again on a later visit is put up for a pick, not left behind.
        if (moved && a.status !== 'working' && w.jobs.every((j) => j.got)) { const was = a.status; finish(a); if (a.status !== was) shown.push(a); }
        changed = changed || moved;
      }
      if (changed) store.saveBoard();
      render(shown);
      return changed;
    }

    /* ---------- what is said: the failures and refunds of one look are one sentence ---------- */
    function tell(note) {
      owed.failed += note.failed; owed.refunded += note.refunded; owed.lost += note.lost;
      flush();
    }
    function flush() {
      if (!owed.failed && !owed.refunded && !owed.lost) return;
      // A toast with a button in it (an answer that can be undone) is left up; this waits until it is gone.
      if (d.toastBusy && d.toastBusy()) { if (!noteTimer) noteTimer = later(() => { noteTimer = 0; flush(); }, NOTICE_WAIT_MS); return; }
      const parts = [];
      if (owed.failed) parts.push(say('genFailed', owed.failed));
      if (owed.refunded) parts.push(say('genRefunded', owed.refunded));
      if (owed.lost) parts.push(say('genLost', owed.lost));
      owed.failed = owed.refunded = owed.lost = 0;
      toast(parts.join(' '), NOTICE_MS);
    }

    /* ---------- picking work up again ---------- */
    // attach() once more: five seconds on, or after the rest a 429 asked for (which also puts off a sooner try).
    function retryLater(rest) {
      const wait = Math.max(RETRY_MS, rest || 0), at = mono() + wait;
      if (attachTimer && (!rest || attachAt >= at)) return;
      unlater(attachTimer); attachAt = at;
      attachTimer = later(() => { attachTimer = 0; attach(); }, wait);
    }
    function attach() {
      if (attaching) { attachAgain = true; return attaching; }
      attaching = (async () => {
        try { do { attachAgain = false; await reattach(); } while (attachAgain); } catch { retryLater(); } finally { attaching = null; }
      })();
      return attaching;
    }
    // Records with job ids go to the poller. A record without ids is a request whose answer never arrived: the server
    // is asked what it knows of it, whatever its age.
    //   known: the ids are kept and polled.   cancelled: the sounds go back to how they were.
    //   not known, younger than ten minutes, its words still stored: those very words are sent again.
    //   not known otherwise: the request is cancelled on the server (a late arrival gets 410), then the sounds go back.
    // A request answered on this visit is not asked about again: a look that is under way settles its sounds.
    async function reattach() {
      if (!usable()) return;
      const requests = new Set(), resting = mono() < attachRest;
      if (!resting) for (const a of live()) { const w = a.work; if (mine(w) && !w.jobs.length && !flying.has(w.request) && !answered.has(w.request)) requests.add(w.request); }
      const touched = new Set(sweep()), note = { failed: 0, refunded: 0, lost: 0 };
      // wait: how long until this is tried again. No answer: five seconds. A 429: as long as the server asks, and
      // nothing more is asked until then.
      let wait = resting ? attachRest - mono() : 0;
      const rest = (r) => { wait = Math.max(RETRY_MS, r.retry * 1000); attachRest = mono() + wait; };
      for (const request of requests) {
        const still = () => asked(request).filter((a) => !a.work.jobs.length);
        const back = () => { for (const a of still()) { undo(a); touched.add(a); } store.del('req:' + request); };
        const r = await call('POST', '/jobs/status', JSON.stringify({ request_id: request }));
        if (r.status === 401) break;
        if (r.status === 429) { rest(r); break; }
        if (r.status !== 200 || !r.data) { wait = Math.max(wait, RETRY_MS); continue; }
        if (r.data.cancelled) { back(); continue; }
        if (r.data.known) { for (const a of asked(request)) touched.add(a); adopt(request, Array.isArray(r.data.jobs) ? r.data.jobs : [], note); store.del('req:' + request); continue; }
        const list = still();
        if (!list.length) continue;
        const body = await store.get('req:' + request), age = wall() - Math.min(...list.map((a) => a.work.at));
        if (typeof body === 'string' && age <= RESEND_MS) {
          flying.add(request);
          try { if ((await send(request, body, true)).pending) wait = Math.max(wait, RETRY_MS); } finally { flying.delete(request); }
          continue;
        }
        const c = await call('POST', '/jobs/cancel', JSON.stringify({ request_id: request }));
        if (c.status === 401) break;
        if (c.status === 429) { rest(c); break; }
        if (c.status !== 200) { wait = Math.max(wait, RETRY_MS); continue; }
        back();
      }
      if (touched.size) { await store.saveBoard(); render([...touched]); }
      tell(note); kick();
      if (!resting && !wait && usable()) await resend();
      if (wait) retryLater(wait > RETRY_MS ? wait : 0);
    }

    /* ---------- cancelling: sounds taken off the board (the trash, a board replaced or started again) ---------- */
    // Tells the server to stop making jobs (by id) and whole requests (that have no ids yet). A cancel that gets no
    // answer, a 401, a 429 or a 5xx is kept in unsent and told again when work is next picked up: five seconds on,
    // after the rest a 429 asked for, and with the next token when the page is paused.
    function stop(ids, requests) {
      const sent = [];
      let rest = 0;
      const one = (body, keep) => sent.push(call('POST', '/jobs/cancel', JSON.stringify(body), { keepalive: true }).then((r) => {
        if (r.status === 0 || r.status === 401 || r.status === 429 || r.status >= 500) { keep(); if (r.status === 429) rest = Math.max(rest, r.retry * 1000); return false; }
        return true;
      }, () => { keep(); return false; }));
      for (const request of requests) one({ request_id: request }, () => unsent.requests.add(request));
      for (let i = 0; i < ids.length; i += MAX_IDS) { const part = ids.slice(i, i + MAX_IDS); one({ ids: part }, () => part.forEach((id) => unsent.ids.add(id))); }
      return Promise.all(sent).then((all) => {
        if (all.every(Boolean)) return;
        if (rest > RETRY_MS) attachRest = Math.max(attachRest, mono() + rest);
        retryLater(rest > RETRY_MS ? rest : 0);
      });
    }
    function resend() {
      const ids = [...unsent.ids], requests = [...unsent.requests];
      unsent.ids.clear(); unsent.requests.clear();
      return stop(ids, requests);
    }
    function cancel(assets) {
      const ids = [], requests = new Set(), whole = [];
      for (const a of assets || []) {
        const w = a && a.work;
        // Work that is not this token's is its owner's to cancel: the record stays, and they pick it up when they are back.
        if (!mine(w)) continue;
        const open = w.jobs.filter((j) => !j.got).map((j) => j.id);
        if (open.length) ids.push(...open); else if (!w.jobs.length) requests.add(w.request);
        undo(a);
      }
      // A request that has no ids yet is cancelled whole, and only when none of its sounds is still wanted.
      for (const request of requests) {
        if (asked(request).length) continue;
        if (store) store.del('req:' + request);
        whole.push(request);
      }
      return stop(ids, whole).then(() => undefined, () => undefined);
    }
    // Drafts that were not kept. Their records go, so a later visit does not fetch them again. The server is told
    // nothing: every job of a sound that is not being made has ended, and a result nobody takes runs out there by itself.
    function drop(assets) {
      for (const a of assets || []) if (a && mine(a.work) && a.status !== 'working') { unhold(a.work); delete a.work; }
    }

    return {
      token: takeToken, generate, quoteOf, attach, cancel, drop, free, check, why, refuse,
      get ready() { return !!state.token && !state.paused; }, get paused() { return state.paused; },
      get identity() { return state.token ? { kind: state.token.kind, who: state.token.who } : null; },
      get unit() { return state.unit ? { ...state.unit } : null; },
      get unreached() { return !state.unit && unitMisses >= QUOTE_MISSES; },
    };
  }

  return { create, fromHost, readToken, clip, factsOf, shapeItem, shapeProject, shapeExamples, MAX_DRAFTS, POLL_MS, HIDDEN_MS, FAR_MS, RESEND_MS, TOKEN_WAIT_MS };
});
