// The records of a board opened from a folder, the way the asset room opens a bundle (app.js openBundle), for
// tools/board_import.py to write into the board store. Prints JSON: { game, records: [[kind, uid, data]],
// blobs: [{ sha, path, size }] }.
//
//   node tools/board_import.js FOLDER
//
// FOLDER holds a spec (game-audio.spec.json, else any .json with an `assets` list) and the sounds, found by the
// spec's `file` or by an id-named audio file anywhere under FOLDER. An Akkado patch named <id>.akkado beside or under
// it makes that version an nkido one with the patch as its source (header lines `// seconds: N` and `// bpm: N`
// are read), so the room can revise it; without one the version is an import.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const HERE = path.join(__dirname, '..', 'studio_frontend', 'asset_studio');
const assetMeasure = require(path.join(HERE, 'measure.js'));
const assetStore = require(path.join(HERE, 'store.js'));
const assetBoard = require(path.join(HERE, 'board.js'));

const SPEC = 'game-audio.spec.json';
const AUDIO = /\.(wav)$/i; // the server measures what readWav reads; other formats go in through the page
const HUES = ['#E8AE72', '#87B9E8', '#8CCDB2', '#C7A0E8', '#F3C978', '#F29BB2', '#9FD36B', '#7FD1D9', '#E89A7F', '#B7B3F2'];
const KINDS = ['sfx', 'amb', 'music'];
const NKIDO = { name: 'nkido (Akkado, Cedar)', license: 'MIT', holder: 'Moritz Laass', use: 'Sound synthesis engine' };
const EXPORT = { format: 'wav', rate: 48000, bits: 16, quality: 'high', folders: 'flat', root: 'audio', engine: 'none' };

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name.startsWith('.') || e.name === 'node_modules') continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out); else out.push(p);
  }
  return out;
}
const stem = (p) => path.basename(p).replace(/\.[^.]+$/, '');
const header = (src, key) => { const m = src.match(new RegExp(`//\\s*${key}\\s*:\\s*([0-9.]+)`)); return m ? +m[1] : null; };
const sha256 = (u8) => crypto.createHash('sha256').update(u8).digest('hex');

// The spec: the named file first, then the first .json (shallowest path first) whose `assets` is a list.
function findSpec(files) {
  const jsons = files.filter((f) => /\.json$/i.test(f)).sort((a, b) => a.split(path.sep).length - b.split(path.sep).length || a.localeCompare(b));
  for (const f of [...jsons.filter((f) => path.basename(f) === SPEC), ...jsons]) {
    try { const x = JSON.parse(fs.readFileSync(f, 'utf8')); if (x && Array.isArray(x.assets)) return x; } catch { /* not a spec */ }
  }
  return null;
}

function main(folder) {
  const files = walk(folder), spec = findSpec(files);
  if (!spec) throw new Error('no spec here: a .json with an assets list');
  const audio = files.filter((f) => AUDIO.test(f)), patches = files.filter((f) => /\.akkado$/i.test(f));
  const profile = assetMeasure.PROFILES.find((p) => p.id === spec.platform) || assetMeasure.PROFILES[0];
  const cats = (spec.categories || []).filter((c) => c && c.id).map((c, i) => ({
    id: c.id, name: c.name || c.id, kind: KINDS.includes(c.kind) ? c.kind : 'sfx', hue: c.color || HUES[i % HUES.length], ...(c.parent ? { parent: c.parent } : {}), refs: [],
  }));
  const catOf = (id) => cats.find((c) => c.id === id);
  const refsOf = (list) => (Array.isArray(list) ? list : []).filter((r) => r && (r.kind === 'text' || r.kind === 'link' || (!r.kind && (r.note || r.url))))
    .map((r, i) => ({ id: `r${crypto.createHash('sha1').update(JSON.stringify(r) + i).digest('hex').slice(0, 10)}`, kind: r.kind || (r.url ? 'link' : 'text'), name: String(r.name || ''), note: String(r.note || ''), url: String(r.url || ''), at: Date.now() }));
  const blobs = new Map(), assets = [], now = Date.now();
  for (const [i, x] of spec.assets.entries()) {
    if (!x || !x.id) continue;
    const file = audio.find((f) => (x.file && f.replace(/\\/g, '/').endsWith(x.file)) || stem(f) === x.id);
    const patch = patches.find((f) => stem(f) === x.id);
    const cat = catOf(x.category) ? x.category : (cats[0] || { id: 'sfx' }).id, kind = (catOf(cat) || { kind: 'sfx' }).kind;
    const a = {
      key: `k${(now + i).toString(36)}${crypto.createHash('sha1').update(x.id).digest('hex').slice(0, 6)}`,
      id: x.id, name: x.name || x.id, cat, music: kind === 'music', loop: !!x.loop, when: x.when || '', description: x.description || '',
      length: x.length ?? null, imported: x.origin === 'imported', file: x.source_file || '', license: x.license || '', holder: x.holder || '', prompt: x.prompt || '',
      status: 'pending', versions: [], current: 0, drafts: [], chat: [], layers: [], refs: refsOf(x.references).map((r) => ({ ...r, from: 'asset' })),
    };
    if (file) {
      const u8 = new Uint8Array(fs.readFileSync(file)), sound = assetMeasure.readWav(u8), m = assetMeasure.measure(sound);
      const sha = sha256(u8), id = assetStore.newId(now + i, 0.5);
      const source = patch ? fs.readFileSync(patch, 'utf8').replace(/\r\n/g, '\n') : null;
      a.versions = [{
        id, at: now + i, note: { key: 'fromBundle' }, engine: source ? 'nkido' : 'import', job: null, parent: null, draft: null,
        source, seconds: m.seconds, bpm: source ? header(source, 'bpm') : null, prompt: null, model: null,
        sources: source ? [NKIDO] : assetStore.sourcesFor(a), measure: m, issues: [], peaks: assetStore.peaksOf(sound.chans),
        key: `ver:${id}`, stems: [], rate: sound.rate, channels: sound.chans.length, bits: sound.bits ?? null, bytes: u8.length, sha256: sha,
      }];
      a.status = x.status === 'approved' || !x.status ? 'approved' : 'draft';
      blobs.set(sha, { sha, path: file, size: u8.length });
    }
    assets.push(a);
  }
  const snapshot = {
    game: spec.game || path.basename(folder), brief: spec.style || '', platform: profile.id, loud: [...profile.loud], demo: false, stage: 'expand',
    idRule: spec.id_rule?.pattern ? { ...assetMeasure.ID_RULE, ...spec.id_rule, prefix: { ...assetMeasure.ID_RULE.prefix, ...spec.id_rule.prefix } } : { ...assetMeasure.ID_RULE, prefix: { ...assetMeasure.ID_RULE.prefix } },
    exportOpts: { ...EXPORT, ...(spec.export || {}) }, cats, projectRefs: refsOf(spec.references), dynamics: [], assets, trash: [],
  };
  const records = [...assetBoard.toRecords(snapshot)].map(([k, d]) => { const at = k.indexOf('/'); return [k.slice(0, at), k.slice(at + 1), d]; });
  return { game: snapshot.game, records, blobs: [...blobs.values()] };
}

if (require.main === module) {
  try { process.stdout.write(JSON.stringify(main(process.argv[2] || '.'))); } catch (e) { process.stderr.write(String(e && e.message || e) + '\n'); process.exit(1); }
}
module.exports = { main, findSpec };
