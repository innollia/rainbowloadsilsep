// What asking for sounds costs, as the asset room shows it and keeps to it: the number in a label, the request that
// waits when an answer would cost more than the number that was showing, and the approved sounds a new one is told to
// stay close to. Nothing here touches the page or the network, so Node runs this file in tests.
//
// A quote is what assetGen's quoteOf(count, drafts) returns: { items, drafts, unit, credits, free, known }.
//
// assetQuote.number(quote) -> the credits a label shows, or null when it shows none: a session that pays nothing,
//   a price that is not known yet, nothing to make.
// assetQuote.label(base, quote, withNumber) -> the text of a label: base, or withNumber(base, credits).
// assetQuote.fits(need, shown) -> whether sounds that cost `need` may start when `shown` was on the label.
// assetQuote.create() -> the request that waits:
//   send(text, ids, quote, need) -> { via: 'agent' }, { via: 'direct', ids, text, plan } or { via: 'hold' }. Send was
//     pressed with these words, these sounds picked and this quote on the label. 'direct': it is the request that was
//     waiting, sent again as it was, so its sounds are made without asking the assistant. need is the quote of what
//     is left of it to make; 'hold': that is more than the label showed at this press, so it goes on waiting and
//     nothing starts.
//   answer(ids, text, need, plan) -> 'start' or 'hold'. The assistant's answer wants these sounds made. 'hold': that
//     costs more than the label showed when send was pressed, so nothing starts and { ids, text } waits. plan is
//     whatever the page needs to make them later as the answer asked (which sounds, in which words); it is kept
//     beside the request and handed back untouched.
//   changed(text, ids) -> whether a request still waits. Other words, or other sounds picked, let it go.
//   drop(), held -> { ids, text } or null (it stays whatever the toast does), plan -> what was kept beside it,
//   shown -> the quote of the last send.
// assetQuote.examples(kinds, pool, max) -> up to three of pool ([{ name, kind, loop, source, facts }]: the approved
//   sounds, each with the patch of the version in use) for a request for sounds of these kinds, one kind for each
//   sound asked for. Only a sound whose patch is known and short enough to send is taken; the kinds asked for come first.
(function (factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  const root = typeof window !== 'undefined' ? window : typeof self !== 'undefined' ? self : null;
  if (root) root.assetQuote = api;
})(function () {
  'use strict';

  const MAX_EXAMPLES = 3;
  const SOURCE_CAP = 4000; // the longest patch the API takes as an example (asset_generate.clean_request)
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

  /* ---------- the number in a label ---------- */
  function number(quote) {
    return quote && quote.known && !quote.free && isNum(quote.credits) && quote.credits > 0 ? quote.credits : null;
  }
  function label(base, quote, withNumber) {
    const n = number(quote);
    return n == null || !withNumber ? base : withNumber(base, n);
  }

  /* ---------- the request that waits ---------- */
  // Sounds may start when they cost no more than the number that was on the label when send was pressed. A session
  // that pays nothing always may. What has no known price may not, and neither may anything that costs credits when
  // the label carried no number (no price yet, nothing picked, a session that paid nothing then): nobody was shown
  // what it takes.
  function fits(need, shown) {
    if (!need || need.free) return true;
    if (!need.known || !isNum(need.credits)) return false;
    if (need.credits <= 0) return true;
    const had = number(shown);
    return had != null && need.credits <= had;
  }
  const listOf = (ids) => [...new Set(Array.isArray(ids) ? ids : [])];

  function create() {
    let held = null, shown = null;
    const same = (text, ids) => {
      if (!held || held.text !== text) return false;
      const now = listOf(ids);
      return now.length === held.ids.length && held.ids.every((id) => now.includes(id));
    };
    return {
      get held() { return held ? { ids: held.ids.slice(), text: held.text } : null; },
      get plan() { return held ? held.plan : null; },
      get shown() { return shown; },
      send(text, ids, quote, need) {
        const waiting = same(text, ids);
        shown = quote || null;
        if (!waiting) { held = null; return { via: 'agent' }; }
        // Sent again as it was. It is held to the number on the label at this press like any other: when that is less
        // than it costs (the label changed under it), it goes on waiting.
        if (!fits(need, shown)) return { via: 'hold' };
        const out = held; held = null;
        return { via: 'direct', ids: out.ids.slice(), text: out.text, plan: out.plan };
      },
      answer(ids, text, need, plan) {
        if (fits(need, shown)) return 'start';
        held = { ids: listOf(ids), text, plan: plan === undefined ? null : plan };
        return 'hold';
      },
      changed(text, ids) {
        if (held && !same(text, ids)) held = null;
        return !!held;
      },
      drop() { held = null; },
    };
  }

  /* ---------- the sounds a new one stays close to ---------- */
  function examples(kinds, pool, max) {
    const most = isNum(max) ? max : MAX_EXAMPLES, out = [];
    const usable = (Array.isArray(pool) ? pool : []).filter((e) => e && typeof e.source === 'string' && e.source.trim() && e.source.length <= SOURCE_CAP);
    const asked = new Map();
    for (const k of Array.isArray(kinds) ? kinds : []) asked.set(k, (asked.get(k) || 0) + 1);
    // One of each kind asked for in turn, the kind most asked for first, so that each kind has a sound to go by.
    const lines = [...asked.keys()].sort((a, b) => asked.get(b) - asked.get(a)).map((k) => usable.filter((e) => e.kind === k));
    for (let i = 0; out.length < most && lines.some((l) => i < l.length); i++) for (const l of lines) if (i < l.length && out.length < most) out.push(l[i]);
    for (const e of usable) if (out.length < most && !asked.has(e.kind)) out.push(e);
    return out.map((e) => ({ name: e.name, kind: e.kind, loop: !!e.loop, source: e.source, facts: e.facts }));
  }

  return { number, label, fits, create, examples, MAX_EXAMPLES, SOURCE_CAP };
});
