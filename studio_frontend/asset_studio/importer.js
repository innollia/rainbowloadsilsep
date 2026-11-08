// Bringing existing work in and taking the board out: name guessing, list parsing, WAV and ZIP. No DOM here.
(() => {
  const AUDIO = /\.(wav|mp3|ogg|oga|flac|m4a|aac|webm)$/i;
  const SPEC = 'game-audio.spec.json';

  /* ---------- names ---------- */
  // Words that point at a category, in English and Korean. Folder names count too ("UI/click.wav").
  const HINTS = [
    ['bgm', /^(bgm|music|musics|song|songs|theme|track|ost|loop_music|menu_music|음악|배경음|브금|노래|테마)$/],
    ['env', /^(amb|ambience|ambient|ambiance|atmo|atmosphere|env|environment|wind|rain|fire|campfire|cave|forest|ocean|sea|river|waves|birds|crowd|room|storm|thunder|night|환경|환경음|바람|비|빗소리|불|모닥불|동굴|숲|바다|강|새소리)$/],
    ['combat', /^(combat|battle|hit|hits|attack|sword|swing|slash|stab|explosion|explode|boom|shoot|shot|gun|gunshot|arrow|bow|block|parry|hurt|damage|spell|cast|magic|punch|kick|impact|death|die|enemy|weapon|전투|타격|공격|폭발|칼|검|화살|피격|마법|방패)$/],
    ['char', /^(char|character|player|step|steps|footstep|footsteps|foot|walk|run|jump|land|landing|dash|pickup|pick|collect|voice|grunt|breath|eat|swim|climb|캐릭터|발소리|걸음|점프|착지|대시|줍기|목소리)$/],
    ['ui', /^(ui|gui|hud|menu|click|button|btn|tap|confirm|ok|cancel|back|select|hover|open|close|coin|coins|levelup|level|notify|notification|popup|alert|error|success|fail|reward|achievement|인터페이스|클릭|버튼|메뉴|확인|취소|코인|알림|보상)$/],
  ];
  const PREFIX = { sfx: null, amb: 'env', bgm: 'bgm' };
  const words = (text) => String(text)
    .replace(/\.[a-z0-9]{2,5}$/i, '')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .toLowerCase()
    .split(/[^a-z0-9가-힣]+/)
    .filter(Boolean);
  function guessCategory(path, seconds) {
    const parts = String(path).split(/[\\/]/), file = parts.pop(), mine = words(file);
    const prefix = PREFIX[mine[0]];
    if (prefix) return { cat: prefix, sure: true };
    for (const list of [mine, words(parts.join(' '))]) {
      for (const [cat, re] of HINTS) if (list.some((w) => re.test(w))) return { cat, sure: true };
    }
    if (mine.includes('loop') || mine.includes('loops')) return { cat: seconds > 30 ? 'bgm' : 'env', sure: false };
    if (seconds >= 20) return { cat: 'bgm', sure: false };
    if (seconds >= 5) return { cat: 'env', sure: false };
    return { cat: 'ui', sure: false };
  }
  // "sword_swing_01.wav" -> "Sword swing 01". A leading sfx_/amb_/bgm_ is not part of the name.
  function guessName(path) {
    const file = String(path).split(/[\\/]/).pop(), list = words(file);
    if (PREFIX[list[0]] !== undefined && list.length > 1) list.shift();
    const text = list.join(' ');
    return text ? text[0].toUpperCase() + text.slice(1) : file;
  }
  const PRE = { bgm: 'bgm', env: 'amb' };
  // A rule-abiding id. Korean-only names fall back to the category and a number.
  function makeId(name, cat, taken) {
    const head = PRE[cat] || 'sfx';
    let slug = words(name).filter((w) => /^[a-z0-9]+$/.test(w)).join('_');
    if (slug.startsWith(head + '_')) slug = slug.slice(head.length + 1);
    if (!slug) slug = cat;
    let id = `${head}_${slug}`.slice(0, 48), k = 2;
    while (taken.has(id)) id = `${head}_${slug}_${k++}`;
    taken.add(id);
    return id;
  }

  /* ---------- a pasted list of sounds ---------- */
  const COLS = {
    id: /^(id|key|file|파일|아이디)$/i, name: /^(name|title|sound|이름|소리|제목)$/i, category: /^(category|cat|type|kind|group|분류|종류|카테고리)$/i,
    when: /^(when|trigger|event|moment|언제|상황|때)$/i, description: /^(description|desc|notes?|feel|설명|느낌|메모)$/i, length: /^(length|duration|seconds|sec|길이|초)$/i, loop: /^(loop|반복|루프)$/i,
  };
  const CAT_WORDS = { ui: /^(ui|인터페이스)$/i, combat: /^(combat|battle|전투)$/i, char: /^(char|character|캐릭터)$/i, env: /^(env|amb|ambience|environment|환경|환경음)$/i, bgm: /^(bgm|music|음악|배경음)$/i };
  const catOf = (text) => Object.keys(CAT_WORDS).find((c) => CAT_WORDS[c].test(String(text).trim())) || null;
  function splitLine(line) {
    const sep = line.includes('\t') ? '\t' : line.includes('|') ? '|' : line.includes(',') ? ',' : null;
    if (!sep) return [line];
    const out = []; let cell = '', quoted = false;
    for (const ch of line) {
      if (ch === '"') quoted = !quoted;
      else if (ch === sep && !quoted) { out.push(cell); cell = ''; } else cell += ch;
    }
    out.push(cell);
    return out.map((c) => c.trim());
  }
  // One sound per line. A header row names the columns; without one, the first cell is the name or id and the rest is description.
  function parseList(text) {
    const lines = String(text).split(/\r?\n/).map((l) => l.replace(/^\s*(?:[-*•]|\d+[.)])\s+/, '').trim()).filter((l) => l && !/^[-|:\s]+$/.test(l));
    if (!lines.length) return [];
    let head = null;
    const first = splitLine(lines[0]).map((c) => c.toLowerCase());
    const named = first.map((c) => Object.keys(COLS).find((k) => COLS[k].test(c)) || null);
    if (named.filter(Boolean).length >= 1 && (named.includes('name') || named.includes('id')) && first.length > 1) { head = named; lines.shift(); }
    return lines.map((line) => {
      const cells = splitLine(line), row = {};
      if (head) head.forEach((k, i) => { if (k && cells[i]) row[k] = cells[i]; });
      else {
        const [lead, ...rest] = cells;
        if (/^(sfx|amb|bgm)_[a-z0-9_]+$/.test(lead)) row.id = lead; else row.name = lead;
        const cat = rest.find((c) => catOf(c));
        if (cat) { row.category = cat; rest.splice(rest.indexOf(cat), 1); }
        if (rest.length) row.description = rest.join(' · ');
      }
      const name = row.name || guessName(row.id || ''), cat = catOf(row.category || '') || (row.id && PREFIX[row.id.split('_')[0]]) || guessCategory(`${row.id || ''} ${name}`.trim(), 0).cat;
      const length = parseFloat(row.length);
      return {
        id: row.id && /^(sfx|amb|bgm)_[a-z0-9_]+$/.test(row.id) ? row.id : null, name, cat,
        when: row.when || '', description: row.description || '', length: Number.isFinite(length) ? length : null,
        loop: row.loop ? /^(1|true|yes|y|o|네|예|반복)$/i.test(row.loop) : cat === 'env' || cat === 'bgm',
      };
    }).filter((x) => x.name);
  }

  /* ---------- WAV ---------- */
  function encodeWav(data, rate) {
    const out = new DataView(new ArrayBuffer(44 + data.length * 2)), text = (at, s) => [...s].forEach((c, i) => out.setUint8(at + i, c.charCodeAt(0)));
    text(0, 'RIFF'); out.setUint32(4, 36 + data.length * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
    out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true); out.setUint32(24, rate, true);
    out.setUint32(28, rate * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true); text(36, 'data'); out.setUint32(40, data.length * 2, true);
    for (let i = 0; i < data.length; i++) out.setInt16(44 + i * 2, Math.max(-1, Math.min(1, data[i])) * 0x7fff, true);
    return new Uint8Array(out.buffer);
  }

  /* ---------- ZIP (stored on the way out; stored or deflated on the way in) ---------- */
  const CRC = new Uint32Array(256).map((_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c; });
  const crc32 = (bytes) => { let c = -1; for (let i = 0; i < bytes.length; i++) c = CRC[(c ^ bytes[i]) & 255] ^ (c >>> 8); return (c ^ -1) >>> 0; };
  const utf8 = (s) => new TextEncoder().encode(s);
  function zip(files) {
    const parts = [], dir = [];
    let at = 0;
    for (const { path, bytes } of files) {
      const name = utf8(path), crc = crc32(bytes), head = new DataView(new ArrayBuffer(30));
      head.setUint32(0, 0x04034b50, true); head.setUint16(4, 20, true); head.setUint16(6, 0x0800, true);
      head.setUint32(14, crc, true); head.setUint32(18, bytes.length, true); head.setUint32(22, bytes.length, true); head.setUint16(26, name.length, true);
      const entry = new DataView(new ArrayBuffer(46));
      entry.setUint32(0, 0x02014b50, true); entry.setUint16(4, 20, true); entry.setUint16(6, 20, true); entry.setUint16(8, 0x0800, true);
      entry.setUint32(16, crc, true); entry.setUint32(20, bytes.length, true); entry.setUint32(24, bytes.length, true); entry.setUint16(28, name.length, true); entry.setUint32(42, at, true);
      parts.push(new Uint8Array(head.buffer), name, bytes); dir.push(new Uint8Array(entry.buffer), name);
      at += 30 + name.length + bytes.length;
    }
    const size = dir.reduce((s, p) => s + p.length, 0), end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true); end.setUint32(12, size, true); end.setUint32(16, at, true);
    return new Blob([...parts, ...dir, new Uint8Array(end.buffer)], { type: 'application/zip' });
  }
  async function unzip(buffer) {
    const bytes = new Uint8Array(buffer), view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let end = -1;
    for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) if (view.getUint32(i, true) === 0x06054b50) { end = i; break; }
    if (end < 0) throw new Error('not a zip');
    const count = view.getUint16(end + 10, true), out = [];
    let p = view.getUint32(end + 16, true);
    for (let k = 0; k < count; k++) {
      const method = view.getUint16(p + 10, true), packed = view.getUint32(p + 20, true), nameLen = view.getUint16(p + 28, true), extra = view.getUint16(p + 30, true), note = view.getUint16(p + 32, true), local = view.getUint32(p + 42, true);
      const path = new TextDecoder().decode(bytes.subarray(p + 46, p + 46 + nameLen));
      p += 46 + nameLen + extra + note;
      if (path.endsWith('/')) continue;
      const start = local + 30 + view.getUint16(local + 26, true) + view.getUint16(local + 28, true), raw = bytes.slice(start, start + packed);
      if (method === 0) out.push({ path, bytes: raw });
      else if (method === 8) out.push({ path, bytes: new Uint8Array(await new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).arrayBuffer()) });
    }
    return out;
  }

  window.importer = { AUDIO, SPEC, guessCategory, guessName, makeId, parseList, encodeWav, zip, unzip, crc32 };
})();
