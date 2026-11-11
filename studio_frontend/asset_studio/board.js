// The board as records, for keeping one board in step between computers (docs/ASSET_SYNC_SPEC.md, E and G). Pure
// functions only: no storage, no network, no clock. Node runs this file in tests.
//
// A record is (kind, uid, data): meta/game, meta/rules, cat/<id>, ref/<id>, dyn/<id>, asset/<a.key>. Its text form is
// canon(data), the bytes the server stores and compares.
//   canon(x)                 JSON with sorted keys (the server's json.dumps(sort_keys=True) of the same value)
//   toRecords(snapshot)      Map("<kind>/<uid>" -> data) of what the page's snapshot() holds, cleaned and fitted
//   fit(data)                an asset record cut below RECORD_MAX - 4096 bytes (old prompts, then old sources)
//   merge3(kind, base, mine, theirs, mineWins) -> { data, lost, gone }   (null data: the record is deleted)
//   sane(asset data)         status and cur made to agree with the versions and drafts (in place, returned)
//   patch(model, kind, uid, data|null)   the live objects of the page changed in place to hold data
//   fixIds(model, shadow)    sounds that share a shown id get new ones, the same way on every computer
//   pristine(snapshot)       the untouched sample board, which never goes to the server
//   shasOf(kind, data)       the bytes a record points at, in upload order: [{ sha, key, size, rank, job, stem }]
//   remoteKeys(sync)         audio keys the records already on the server use (mend keeps them without local bytes)
//   revertFields(before, after, now) -> { field: value before } for the fields still holding what after wrote
// model (handed in by the page): { assets, trash, cats, refs, dynamics } (live arrays), get(name) and set(name, value)
// for game, brief, platform, loud, demo, stage, idRule, exportOpts, and makeId(name, cat, taken) for fixIds.
(function (factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  const root = typeof window !== 'undefined' ? window : typeof self !== 'undefined' ? self : null;
  if (root) root.assetBoard = api;
})(function () {
  'use strict';

  const RECORD_MAX = 1200000, FIT_MAX = RECORD_MAX - 4096;
  // The fields of each record. An asset field that is in neither ASSET nor DEVICE is a test failure (strays()).
  const GAME = ['game', 'brief', 'platform', 'loud', 'demo', 'stage'], RULES = ['idRule', 'exportOpts'];
  const CAT = ['id', 'name', 'kind', 'hue', 'parent', 'refs'], DYN = ['id', 'name', 'type', 'bpm', 'beats', 'params', 'layers'];
  const ASSET = ['id', 'name', 'cat', 'music', 'loop', 'loud', 'when', 'description', 'length', 'prompt', 'tempo', 'sample', 'layers', 'imported', 'file', 'license',
    'holder', 'guessed', 'autoCat', 'ref', 'trashedAt', 'status', 'cur', 'work', 'versions', 'drafts', 'chat', 'refs'];
  const DEVICE = ['key', 'progress', 'source', 'hasSource', 'current', 'pick', 'agentLog'];
  const SPECIAL = new Set(['versions', 'drafts', 'cur', 'work', 'refs', 'trashedAt', 'chat']);
  const HALVES = /[\uD800-\uDBFF][\uDC00-\uDFFF]|[\uD800-\uDFFF]/g, REPLACED = String.fromCharCode(0xfffd);
  const paired = (s) => s.replace(HALVES, (m) => (m.length === 2 ? m : REPLACED));
  const isLegacy = (v) => !v || !v.engine || v.engine === 'legacy';
  const plain = (x) => !!x && typeof x === 'object' && !Array.isArray(x);

  /* ---------- the text form ---------- */
  // A JSON-able copy: strings with every lone half of a pair replaced, Dates as their JSON, undefined dropped from
  // objects (null in arrays), numbers that JSON cannot hold as null, keys sorted.
  function clean(x) {
    if (typeof x === 'string') return paired(x);
    if (typeof x === 'number') return Number.isFinite(x) ? x : null;
    if (x === null || typeof x !== 'object') return typeof x === 'boolean' ? x : x === undefined ? undefined : null;
    if (typeof x.toJSON === 'function') return clean(x.toJSON());
    if (Array.isArray(x)) return x.map((v) => { const c = clean(v); return c === undefined ? null : c; });
    if (ArrayBuffer.isView(x) || x instanceof ArrayBuffer) return null;
    const out = {};
    for (const k of Object.keys(x).sort()) { if (typeof x[k] === 'function') continue; const c = clean(x[k]); if (c !== undefined) out[paired(k)] = c; }
    return out;
  }
  const canon = (x) => { const c = clean(x); return c === undefined ? 'null' : JSON.stringify(c); };
  const same = (a, b) => canon(a) === canon(b);
  const copy = (x) => (x === undefined ? undefined : JSON.parse(canon(x)));
  function utf8(s) {
    let n = 0;
    for (let i = 0; i < s.length; i++) {
      const c = s.charCodeAt(i);
      if (c < 0x80) n += 1; else if (c < 0x800) n += 2; else if (c >= 0xd800 && c <= 0xdbff) { n += 4; i++; } else n += 3;
    }
    return n;
  }
  const sizeOf = (data) => utf8(canon(data));

  /* ---------- the page's snapshot as records ---------- */
  const pickOf = (x, keys) => { const out = {}; for (const k of keys) if (x && x[k] !== undefined) out[k] = x[k]; return out; };
  // A version as it travels: its record with at as a number.
  const travel = (v) => { const { sound, ...rest } = v || {}; return { ...rest, at: +rest.at }; };
  function assetData(a, binned) {
    const d = {};
    for (const k of ASSET) if (!SPECIAL.has(k) && a[k] !== undefined) d[k] = a[k];
    const versions = Array.isArray(a.versions) ? a.versions : [], drafts = Array.isArray(a.drafts) ? a.drafts : [];
    d.versions = versions.map(travel); d.drafts = drafts.map(travel);
    const now = versions[a.current];
    d.cur = now ? now.id : versions.length ? versions[0].id : null;
    d.work = a.work ? { ...a.work, jobs: (a.work.jobs || []).map(({ got, ...j }) => j) } : null;
    d.trashedAt = binned ? a.trashedAt || 1 : null;
    d.chat = Array.isArray(a.chat) ? a.chat : [];
    d.refs = (Array.isArray(a.refs) ? a.refs : []).filter((r) => r && r.from === 'asset');
    return d;
  }
  // Every record of the board. An asset without a key cannot be a record: the page gives every sound one first.
  function toRecords(s) {
    const out = new Map(), put = (kind, uid, data) => out.set(kind + '/' + uid, clean(data));
    const x = s || {};
    put('meta', 'game', pickOf(x, GAME));
    put('meta', 'rules', pickOf(x, RULES));
    for (const c of x.cats || []) if (c && c.id) put('cat', c.id, pickOf(c, CAT));
    for (const r of x.projectRefs || []) if (r && r.id) { const { from, ...rest } = r; put('ref', r.id, rest); }
    for (const d of x.dynamics || []) if (d && d.id) put('dyn', d.id, { ...pickOf(d, DYN), params: (d.params || []).map(({ value, ...p }) => p) });
    for (const [list, binned] of [[x.assets, false], [x.trash, true]]) for (const a of list || []) if (a && a.key) put('asset', a.key, fit(clean(assetData(a, binned))));
    return out;
  }
  // Fields of the snapshot's assets that are neither shared nor known to stay on the device.
  function strays(s) {
    const known = new Set([...ASSET, ...DEVICE]), out = new Set();
    for (const a of [...((s && s.assets) || []), ...((s && s.trash) || [])]) for (const k of Object.keys(a || {})) if (!known.has(k)) out.add(k);
    return [...out].sort();
  }

  // Too big a sound record loses, oldest first, the prompts and then the patches of versions that are not the one in
  // use, until it fits. The same input gives the same output on every computer.
  function fit(data, max = FIT_MAX) {
    if (!data || !Array.isArray(data.versions)) return data;
    let size = sizeOf(data);
    if (size <= max) return data;
    const out = { ...data, versions: data.versions.map((v) => ({ ...v })) };
    const old = out.versions.map((v, i) => ({ v, i })).filter((x) => x.v.id !== out.cur).sort((p, q) => (+p.v.at || 0) - (+q.v.at || 0) || p.i - q.i);
    for (const field of ['prompt', 'source']) for (const { v } of old) {
      if (size <= max) return out;
      if (v[field] === undefined) continue;
      size -= utf8(JSON.stringify(field) + ':' + canon(v[field])) + 1; // the field and its comma
      delete v[field];
    }
    return out;
  }

  /* ---------- three-way merge ---------- */
  // One field. Changed on one side: that side. Changed on both to different values: the server's (first to arrive),
  // or mine when the server's value is my own earlier write. lost: my change was not applied.
  function field(b, m, t, mineWins, out) {
    if (same(m, b)) return t;
    if (same(t, b) || same(m, t)) return m;
    if (mineWins) return m;
    out.lost = true;
    return t;
  }
  // Lists of objects with ids, merged as id sets: an id both had at base stays only while both still have it, one only
  // one side added stays. Order: the server's, then mine only. Same id changed on both sides: as field() says.
  function idSet(b, m, t, mineWins, out) {
    const ids = (l) => new Map((Array.isArray(l) ? l : []).filter((x) => x && x.id != null).map((x) => [x.id, x]));
    const B = ids(b), M = ids(m), T = ids(t), res = [];
    for (const [id, tv] of T) {
      if (M.has(id)) res.push(field(B.get(id), M.get(id), tv, mineWins, out));
      else if (!B.has(id)) res.push(tv);
      else if (!same(tv, B.get(id)) && !mineWins) { out.lost = true; res.push(tv); } // deleted here, changed there: it stays
    }
    for (const [id, mv] of M) if (!T.has(id) && !(B.has(id) && same(mv, B.get(id)))) { if (!B.has(id)) res.push(mv); else if (mineWins) res.push(mv); }
    return res;
  }
  function chatOf(b, m, t) {
    const B = b || [], M = m || [], T = t || [];
    if (same(M, B)) return T;
    if (same(T, B)) return M;
    let p = 0;
    while (p < M.length && p < T.length && same(M[p], T[p])) p++;
    return [...T, ...M.slice(p)];
  }
  function mergeAsset(b, m, t, mineWins, out) {
    const res = {};
    for (const k of new Set([...Object.keys(b), ...Object.keys(m), ...Object.keys(t)])) {
      if (['versions', 'drafts', 'status', 'cur', 'work', 'chat', 'refs'].includes(k)) continue;
      const v = field(b[k], m[k], t[k], mineWins, out);
      if (v !== undefined) res[k] = v;
    }
    // Versions: the union, never fewer. The server's order, then mine only.
    const tv = Array.isArray(t.versions) ? t.versions : [], mv = Array.isArray(m.versions) ? m.versions : [], seen = new Set(tv.map((v) => v.id));
    res.versions = [...tv, ...mv.filter((v) => !seen.has(v.id))];
    const made = new Set(res.versions.map((v) => v.id));
    // Drafts: an id set; one that became a version on either side stays a version only.
    const quiet = { lost: false };
    res.drafts = idSet(b.drafts, m.drafts, t.drafts, true, quiet).filter((v) => !made.has(v.id)).map((v) => (t.drafts || []).find((x) => x.id === v.id) || v);
    // The current version, the approval and the job record move as one.
    const bundle = (x) => ({ status: x.status, cur: x.cur === undefined ? null : x.cur, work: x.work === undefined ? null : x.work });
    const one = field(bundle(b), bundle(m), bundle(t), mineWins, out);
    res.status = one.status; res.cur = one.cur; res.work = one.work;
    res.chat = chatOf(b.chat, m.chat, t.chat);
    res.refs = idSet(b.refs, m.refs, t.refs, mineWins, out);
    return sane(res);
  }
  // base, mine, theirs: data or null (deleted, or not there). mineWins: the server's value is my own earlier write
  // (or the server was restored from a backup), so mine wins every same-field clash.
  function merge3(kind, base, mine, theirs, mineWins) {
    const out = { data: null, lost: false, gone: false };
    if (!theirs) {
      if (!mine) return out;
      // The one who makes the record (no base) beats the server's delete; so does my own delete coming back.
      if (!base || mineWins) { out.data = mine; return out; }
      if (!same(mine, base)) out.gone = true; // deleted there first: my edit goes with it
      return out;
    }
    if (!mine) {
      if (!base) { out.data = theirs; return out; }
      if (mineWins || same(theirs, base)) return out; // my delete stands
      out.data = theirs; out.lost = true; // changed there first: it comes back here
      return out;
    }
    const b = plain(base) ? base : {}, m = plain(mine) ? mine : {}, t = plain(theirs) ? theirs : {};
    if (kind === 'asset') { out.data = mergeAsset(b, m, t, mineWins, out); return out; }
    const res = {};
    for (const k of new Set([...Object.keys(b), ...Object.keys(m), ...Object.keys(t)])) {
      const v = k === 'demo' && kind === 'meta' && (m.demo === false || t.demo === false) ? false : field(b[k], m[k], t[k], mineWins, out);
      if (v !== undefined) res[k] = v;
    }
    out.data = res;
    return out;
  }

  // After a merge: the version in use is one of the versions, and the status says what the lists hold.
  function sane(d) {
    if (!d) return d;
    const vs = Array.isArray(d.versions) ? d.versions : [], ds = Array.isArray(d.drafts) ? d.drafts : [];
    if (!vs.some((v) => v.id === d.cur)) d.cur = vs.length ? vs.reduce((best, v) => ((+v.at || 0) >= (+best.at || 0) ? v : best)).id : null;
    if (!ds.length && d.status === 'review') d.status = vs.length ? 'draft' : 'pending';
    if (ds.length && d.status !== 'review' && d.status !== 'working') d.status = 'review';
    if (vs.length && d.status === 'pending') d.status = 'draft';
    return d;
  }

  /* ---------- the live objects ---------- */
  // Each key of keys: deleted where data has none, set where it differs. Nothing is replaced that already matches.
  function assign(o, d, keys) {
    let changed = false;
    for (const k of keys) {
      if (d[k] === undefined) { if (k in o) { delete o[k]; changed = true; } } else if (!same(o[k], d[k])) { o[k] = copy(d[k]); changed = true; }
    }
    return changed;
  }
  function inList(list, uid, data, fill, make) {
    const i = list.findIndex((x) => x && x.id === uid);
    if (!data) { if (i < 0) return null; const [gone] = list.splice(i, 1); return gone; }
    if (i < 0) { const o = make(); fill(o, data); list.push(o); return o; }
    return fill(list[i], data) ? list[i] : null;
  }
  // Rewrites the list in place so the array the page holds stays the same array.
  const refill = (arr, items) => { arr.splice(0, arr.length, ...items); };
  function patchWork(a, w) {
    if (!w) { if (!a.work) return false; delete a.work; return true; }
    const gotOf = new Map(a.work && Array.isArray(a.work.jobs) ? a.work.jobs.map((j) => [j.id, j]) : []);
    const now = a.work ? { ...a.work, jobs: a.work.jobs.map(({ got, ...j }) => j) } : null;
    if (now && same(now, w)) return false;
    if (!a.work) a.work = {};
    assign(a.work, w, [...new Set([...Object.keys(a.work), ...Object.keys(w)])].filter((k) => k !== 'jobs'));
    a.work.jobs = (w.jobs || []).map((j) => { const had = gotOf.get(j.id); if (had) { had.k = j.k; return had; } return { ...copy(j), got: false }; });
    return true;
  }
  function patchAsset(m, uid, d) {
    let list = m.assets, i = list.findIndex((a) => a && a.key === uid);
    if (i < 0) { list = m.trash; i = list.findIndex((a) => a && a.key === uid); }
    if (!d) { if (i < 0) return null; const [gone] = list.splice(i, 1); return gone; }
    const binned = !!d.trashedAt, into = binned ? m.trash : m.assets;
    let a = i >= 0 ? list[i] : null, changed = false;
    if (!a) { a = { key: uid, progress: 0, current: 0, pick: -1, versions: [], drafts: [], chat: [] }; into.push(a); changed = true; }
    else if (list !== into) { list.splice(i, 1); into.push(a); changed = true; }
    changed = assign(a, d, ASSET.filter((k) => !SPECIAL.has(k))) || changed;
    if (binned) { if (a.trashedAt !== d.trashedAt) { a.trashedAt = d.trashedAt; changed = true; } } else if ('trashedAt' in a) { delete a.trashedAt; changed = true; }
    // A version object this page already holds is kept (its sound, and a prompt fit() may have cut on the way).
    const had = new Map([...(a.versions || []), ...(a.drafts || [])].map((v) => [v.id, v]));
    const versions = (d.versions || []).map((r) => had.get(r.id) || copy(r)), drafts = (d.drafts || []).map((r) => had.get(r.id) || copy(r));
    const ids = (l) => l.map((v) => v.id).join('\n');
    if (!Array.isArray(a.versions)) a.versions = [];
    if (!Array.isArray(a.drafts)) a.drafts = [];
    const now = a.versions[a.current], picked = a.drafts[a.pick];
    if (ids(a.versions) !== ids(versions) || a.versions.some((v, k) => v !== versions[k])) { refill(a.versions, versions); changed = true; }
    if (ids(a.drafts) !== ids(drafts) || a.drafts.some((v, k) => v !== drafts[k])) { refill(a.drafts, drafts); changed = true; }
    const cur = a.versions.findIndex((v) => v.id === d.cur), current = cur >= 0 ? cur : a.versions.indexOf(now) >= 0 ? a.versions.indexOf(now) : 0;
    if (a.current !== current) { a.current = current; changed = true; }
    const pick = a.drafts.includes(picked) ? a.drafts.indexOf(picked) : a.drafts.length && (a.pick >= 0 || d.status === 'review') ? 0 : -1;
    if (a.pick !== pick) { a.pick = pick; changed = true; }
    changed = patchWork(a, d.work) || changed;
    if (!Array.isArray(a.chat)) a.chat = [];
    if (!same(a.chat, d.chat || [])) { refill(a.chat, copy(d.chat || [])); changed = true; }
    const own = (Array.isArray(a.refs) ? a.refs : []).filter((r) => r && r.from === 'asset');
    if (!same(own, d.refs || [])) { a.refs = [...(a.refs || []).filter((r) => !r || r.from !== 'asset'), ...copy(d.refs || [])]; changed = true; }
    return changed ? a : null;
  }
  // Changes the page's live objects to hold data (null: the record is gone). Returns the object that changed, or null.
  function patch(m, kind, uid, data) {
    if (kind === 'meta') {
      if (!data) return null;
      let changed = false;
      for (const k of uid === 'game' ? GAME : RULES) if (data[k] !== undefined && !same(m.get(k), data[k])) { m.set(k, copy(data[k])); changed = true; }
      return changed ? m : null;
    }
    if (kind === 'cat') return inList(m.cats, uid, data, (o, d) => assign(o, d, CAT), () => ({}));
    if (kind === 'ref') return inList(m.refs, uid, data, (o, d) => assign(o, d, [...new Set([...Object.keys(o), ...Object.keys(d)])].filter((k) => k !== 'from')), () => ({}));
    if (kind === 'dyn') {
      return inList(m.dynamics, uid, data, (o, d) => {
        // A slider's position is this computer's: kept for a parameter that is still there.
        const at = new Map((o.params || []).map((p) => [p.id, p.value]));
        const params = (d.params || []).map((p) => ({ ...copy(p), value: at.has(p.id) ? at.get(p.id) : p.default ?? 0 }));
        const was = (o.params || []).map(({ value, ...p }) => p);
        let changed = assign(o, d, DYN.filter((k) => k !== 'params'));
        if (!same(was, d.params || [])) { o.params = params; changed = true; }
        return changed;
      }, () => ({ params: [] }));
    }
    if (kind === 'asset') return patchAsset(m, uid, data);
    return null;
  }

  /* ---------- repairs ---------- */
  // Sounds on the board (not the trash) that share a shown id: the one the server has had longest keeps it (not yet
  // on the server counts as last, then the key decides), the others are named again by the page's makeId.
  function fixIds(m, shadow) {
    const bornOf = (a) => { const s = shadow && shadow['asset/' + a.key]; return s && !s.gone && s.born ? s.born : Infinity; };
    const order = (x, y) => { const p = bornOf(x), q = bornOf(y); return p === q ? (x.key < y.key ? -1 : x.key > y.key ? 1 : 0) : p < q ? -1 : 1; };
    const groups = new Map();
    for (const a of m.assets) { if (!groups.has(a.id)) groups.set(a.id, []); groups.get(a.id).push(a); }
    const taken = new Set(m.assets.map((a) => a.id)), changed = [];
    for (const id of [...groups.keys()].sort()) {
      const g = groups.get(id);
      if (g.length < 2) continue;
      g.sort(order);
      for (const a of g.slice(1)) {
        let next;
        if (m.makeId) next = m.makeId(a.name, a.cat, taken);
        else { let k = 2; while (taken.has(`${id}_${k}`)) k++; next = `${id}_${k}`; taken.add(next); }
        a.id = next; changed.push(a);
      }
    }
    return changed;
  }
  // The sample board nobody has worked on: a demo with nothing in the trash, no references, no dynamic sounds, and
  // only the page's own stand-in sounds (samples, and the empty slots that come with them: key s_<id>) with their
  // first rendered versions and no job.
  function pristine(s) {
    const x = s || {};
    return !!x.demo && !(x.trash || []).length && !(x.projectRefs || []).length && !(x.dynamics || []).length
      && (x.assets || []).every((a) => a && (a.sample || String(a.key || '').startsWith('s_')) && (a.versions || []).every(isLegacy) && !(a.drafts || []).length && !a.work);
  }

  /* ---------- bytes ---------- */
  // What a record points at, in the order it is sent: the version in use, drafts, other versions, stems, a reference
  // file. sha is null where the record does not say yet (the sending computer works it out). Legacy versions have none.
  function shasOf(kind, data) {
    const out = [];
    if (kind === 'asset' && data) {
      const one = (v, rank) => {
        if (isLegacy(v) || !v.key) return;
        const job = v.engine === 'nkido' && v.job ? v.job : null;
        out.push({ sha: v.sha256 || null, key: v.key, size: +v.bytes || 0, rank, job, stem: null });
        for (const s of v.stems || []) {
          if (!s || !s.key) continue;
          const n = /:s(\d+)$/.exec(s.key);
          out.push({ sha: s.sha256 || null, key: s.key, size: +s.bytes || 0, rank: 3, job, stem: n ? +n[1] : null });
        }
      };
      for (const v of data.versions || []) one(v, v.id === data.cur ? 0 : 2);
      for (const v of data.drafts || []) one(v, 1);
    } else if (kind === 'ref' && data && typeof data.key === 'string' && data.key) out.push({ sha: data.sha256 || null, key: data.key, size: +data.bytes || 0, rank: 4, job: null, stem: null });
    return out.sort((p, q) => p.rank - q.rank);
  }
  // Audio keys of the records the server holds (from the stored shadow): mend keeps these without local bytes.
  function remoteKeys(sync) {
    const out = new Set();
    const shadow = sync && sync.shadow && typeof sync.shadow === 'object' ? sync.shadow : {};
    for (const [key, s] of Object.entries(shadow)) {
      if (!s || s.gone || typeof s.json !== 'string') continue;
      const kind = key.slice(0, key.indexOf('/'));
      if (kind !== 'asset' && kind !== 'ref') continue;
      let data = null;
      try { data = JSON.parse(s.json); } catch { continue; }
      for (const x of shasOf(kind, data)) out.add(x.key);
    }
    return out;
  }
  // An agent's answer taken back on a board others edit too: only the fields that still hold what the answer wrote.
  function revertFields(before, after, now) {
    const out = {};
    for (const k of Object.keys(after || {})) if (same((now || {})[k], after[k])) out[k] = (before || {})[k];
    return out;
  }

  return {
    canon, clean, copy, same, utf8, sizeOf, paired, toRecords, strays, fit, merge3, sane, patch, fixIds, pristine, shasOf, remoteKeys, revertFields, isLegacy,
    RECORD_MAX, FIT_MAX, ASSET, DEVICE, GAME, RULES, CAT, DYN,
  };
});
