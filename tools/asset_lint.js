// Lint one WAV from the command line with the asset room's own code: readWav -> measure -> lint.
// Exit code: 0 when nothing is at error level, 1 when something is, 2 when the arguments or the file cannot be used.
'use strict';
const fs = require('fs'), path = require('path');
const M = require('../studio_frontend/asset_studio/measure.js');

const USAGE = 'usage: node tools/asset_lint.js <file.wav> [--kind sfx|amb|music] [--loop] [--profile p | --loud lo,hi] [--spec game-audio.spec.json] [--id x] [--sources json] [--json]\n'
  + '       a file whose name starts with -- goes last, after a bare --';
const KINDS = ['sfx', 'amb', 'music'];
const VALUED = ['kind', 'profile', 'loud', 'spec', 'id', 'sources'], SWITCHES = ['loop', 'json'];
const usage = (message) => Object.assign(new Error(message), { usage: true });
const keyOf = (a) => (a.startsWith('--') ? a.slice(2).split('=')[0] : null);

function parse(argv) {
  const o = { files: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i], eq = a.indexOf('='), key = keyOf(a);
    if (a === '--') { o.files.push(...argv.slice(i + 1)); break; } // what follows is a file even when it looks like an option
    if (key === null) { o.files.push(a); continue; }
    if (SWITCHES.includes(key) && eq < 0) o[key] = true;
    else if (!VALUED.includes(key)) throw usage(`unknown option ${a}`);
    else if (eq >= 0) o[key] = a.slice(eq + 1);
    // `--id --json` is a forgotten value, not an id called --json. `--id=--json` says the second on purpose.
    else if (i + 1 < argv.length && ![...VALUED, ...SWITCHES, ''].includes(keyOf(argv[i + 1]))) o[key] = argv[++i];
    else throw usage(`${a} needs a value`);
  }
  if (o.files.length !== 1) throw usage(o.files.length ? 'one file at a time' : 'no file given');
  if (o.kind !== undefined && !KINDS.includes(o.kind)) throw usage(`--kind is one of ${KINDS.join(', ')}`);
  if (o.profile !== undefined && !M.PROFILES.some((p) => p.id === o.profile)) throw usage(`--profile is one of ${M.PROFILES.map((p) => p.id).join(', ')}`);
  if (o.loud !== undefined) {
    o.loud = o.loud.split(',').map((s) => (s.trim() ? Number(s) : NaN));
    if (o.loud.length !== 2 || !o.loud.every(Number.isFinite) || o.loud[0] > o.loud[1]) throw usage('--loud is two numbers, low then high, like --loud -20,-16');
  }
  if (o.sources !== undefined) {
    try { o.sources = JSON.parse(o.sources); } catch { throw usage('--sources is JSON, like --sources "[]"'); }
  }
  return o;
}

// Without a spec entry the kind is read off the id's prefix: bgm_title is music under the default rule.
function kindFromPrefix(id, idRule) {
  const sep = idRule && typeof idRule.sep === 'string' ? idRule.sep : M.ID_RULE.sep, prefix = { ...M.ID_RULE.prefix, ...(idRule && idRule.prefix) };
  return KINDS.find((k) => prefix[k] && (id === prefix[k] || id.startsWith(prefix[k] + sep)));
}

function main(argv) {
  const options = argv.includes('--') ? argv.slice(0, argv.indexOf('--')) : argv;
  if (options.includes('--help') || options.includes('-h')) { console.log(USAGE); return 0; }
  const o = parse(argv), file = o.files[0];
  let spec = null;
  if (o.spec !== undefined) {
    const text = fs.readFileSync(o.spec, 'utf8');
    spec = JSON.parse(text.charCodeAt(0) === 0xfeff ? text.slice(1) : text); // Windows editors put a byte order mark first
    if (!spec || typeof spec !== 'object' || Array.isArray(spec)) throw new Error(`${o.spec} is not a spec`);
  }
  // With a spec, its id rule, groups and platform judge the file, and the file's own entry says what kind of sound it is.
  // Read the way the asset room opens a spec: an id rule without a pattern is no rule, and a group of an unknown kind holds effects.
  const id = o.id !== undefined ? o.id : path.basename(file, path.extname(file));
  const idRule = spec && spec.id_rule && typeof spec.id_rule.pattern === 'string' && spec.id_rule.pattern ? spec.id_rule : undefined;
  const cats = spec && Array.isArray(spec.categories) ? spec.categories.filter((c) => c && c.id) : [];
  const entry = spec && Array.isArray(spec.assets) ? spec.assets.find((a) => a && a.id === id) : null;
  const cat = entry ? cats.find((c) => c.id === entry.category) : null;
  const kind = o.kind || (cat ? (KINDS.includes(cat.kind) ? cat.kind : 'sfx') : null) || kindFromPrefix(id, idRule) || 'sfx';
  const loop = !!o.loop || !!(entry && entry.loop);

  // lint always judges the name and the license. Here a bare file says nothing about either, so the name issue is only kept
  // when an id or a spec was given, and the license issue only when sources were.
  const named = o.id !== undefined || !!spec, sourced = o.sources !== undefined;
  const opts = { idRule, catIds: cats.map((c) => c.id) };
  if (o.loud) opts.loud = o.loud; else opts.profile = o.profile !== undefined ? o.profile : spec ? spec.platform : undefined;

  const m = M.measure(M.readWav(fs.readFileSync(file)));
  const issues = M.lint({ kind, loop, id, sources: o.sources }, m, opts).filter((x) => (x.id !== 'name' || named) && (x.id !== 'lic' || sourced));
  if (o.json) console.log(JSON.stringify({ file, kind, loop, ...(named ? { id } : {}), measure: m, issues }));
  else {
    const show = (v) => (typeof v === 'number' ? String(Math.round(v * 1000) / 1000) : Array.isArray(v) ? v.join(' to ') : JSON.stringify(v));
    console.log(`${file}: ${kind}${loop ? ', loop' : ''}, ${show(m.seconds)} s, ${m.rate} Hz, ${m.channels} ch, ${m.bits} bit, peak ${show(m.peak)} dBTP, ${show(m.loud)} LUFS`);
    for (const x of issues) console.log(`${x.level.padEnd(5)} ${x.id.padEnd(6)} ${show(x.value)} (limit ${show(x.limit)})`);
    if (!issues.length) console.log('no issues');
  }
  return issues.some((x) => x.level === 'error') ? 1 : 0;
}

// exitCode instead of exit(): output still in the pipe is written out before the process ends.
try { process.exitCode = main(process.argv.slice(2)); } catch (e) {
  console.error(`asset_lint: ${e.message}`);
  if (e.usage) console.error(USAGE);
  process.exitCode = 2;
}
