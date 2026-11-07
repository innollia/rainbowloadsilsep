// Song <-> Strudel text. Pure functions, shared by the player and the code editor.
(() => {
  const isNote = (line) => !line.trim() || line.trim().startsWith('//');

  function compose(song, wired) {
    const lines = [`setcpm(${song.bpm}/4)`];
    for (const t of song.tracks) {
      if (t.raw) { lines.push(t.code); continue; }
      const live = wired ? `.set({trk:'${t.id}'}).postgain(ref(()=>globalThis.__mix['${t.id}']??1))` : '';
      lines.push(`$${t.id}: (${t.code}\n)${live}`);
    }
    return lines.join('\n');
  }

  function songText(song) {
    if (song.tracks.every((t) => t.raw)) return song.tracks.map((t) => t.code).join('\n');
    const blocks = song.tracks.map((t) => `${t.lead ? t.lead + '\n' : ''}$${t.id}: ${t.code}`);
    return [song.head, `setcpm(${song.bpm}/4)`].filter(Boolean).join('\n') + '\n\n' + blocks.join('\n\n') + '\n';
  }

  const rawSong = (text, prev) => ({
    bpm: prev.bpm, head: '',
    tracks: [{ id: 'song', name: window.studioLang?.() === 'ko' ? '전체 곡' : 'Whole song', role: 'other', code: text, raw: true, at: 0 }],
  });

  function guessRole(id, code) {
    const text = `${id} ${code}`.toLowerCase();
    if (/drum|kick|snare|perc|\bbd\b|\bsd\b|\bhh\b/.test(text)) return 'drums';
    if (/bass/.test(text)) return 'bass';
    if (/pad|chord|string/.test(text)) return 'pad';
    if (/lead|melod|arp|note\(/.test(text)) return 'melody';
    return 'other';
  }
  function tempoOf(head, prev) {
    const m = head.match(/set(cpm|cps)\(\s*([\d.]+)(?:\s*\/\s*([\d.]+))?\s*\)/);
    if (!m) return { bpm: prev, found: '' };
    const value = +m[2] / +(m[3] || 1);
    const bpm = m[1] === 'cpm' ? value * 4 : value * 240;
    return { bpm: Math.min(400, Math.max(20, Math.round(bpm * 100) / 100)), found: m[0] };
  }
  function trackId(raw, used) {
    let id = raw.toLowerCase().replace(/[^a-z0-9_]/g, '_').slice(0, 20);
    if (!/^[a-z]/.test(id)) id = `t${id}`;
    if (id === 't') id = 't1';
    let unique = id;
    for (let i = 2; used.has(unique); i++) unique = `${id.replace(/\d+$/, '')}${i}`;
    used.add(unique);
    return unique;
  }

  // "Tempo plus $tracks" becomes tracks. Anything else stays one whole-song track rather than being guessed at.
  function parseSong(text, prev) {
    const marks = [...text.matchAll(/^\$([^\s:]*):/gm)];
    if (!marks.length || marks.length > 8) return rawSong(text, prev);
    const headText = text.slice(0, marks[0].index);
    const headLines = headText.split('\n');
    const head = headLines.filter((l) => l.trim().startsWith('//')).join('\n');
    const code = headLines.filter((l) => !isNote(l)).join('\n');
    const tempo = tempoOf(code, prev.bpm);
    if (code.replace(tempo.found, '').replace(/;/g, '').trim()) return rawSong(text, prev);

    const old = Object.fromEntries(prev.tracks.map((t) => [t.id, t]));
    const used = new Set(marks.map((m) => m[1]).filter((id) => /^[a-z][a-z0-9_]{0,23}$/.test(id)));
    const seen = new Set();
    let lead = '';
    const tracks = [];
    for (let i = 0; i < marks.length; i++) {
      const m = marks[i], start = m.index + m[0].length, end = marks[i + 1]?.index ?? text.length;
      const body = text.slice(start, end);
      const lines = body.split('\n');
      let next = [];
      if (i + 1 < marks.length) while (lines.length > 1 && isNote(lines[lines.length - 1])) { const l = lines.pop(); if (l.trim()) next.unshift(l.trim()); }
      const joined = lines.join('\n');
      const value = joined.trim();
      if (!value) return rawSong(text, prev);
      let id = m[1];
      if (seen.has(id) || !/^[a-z][a-z0-9_]{0,23}$/.test(id)) id = trackId(id || 't', used);
      seen.add(id);
      const had = old[id];
      tracks.push({ id, name: had?.name || id, role: had?.role || guessRole(id, value), code: value, lead,
                    at: start + joined.indexOf(value) });
      lead = next.join('\n');
    }
    return { bpm: tempo.bpm, head, tracks };
  }

  // Maps an error from probing one track back to an offset in the editor text.
  function locate(song, track, error) {
    const at = track.at || 0, lines = track.code.split('\n');
    const m = String(error).match(/\((\d+):(\d+)\)/);
    if (m) {
      const line = Math.min(lines.length - 1, Math.max(0, +m[1] - 2));
      const shift = !track.raw && line === 0 ? `$${track.id}: (`.length : 0;
      const col = Math.min(lines[line].length, Math.max(0, +m[2] - shift));
      return at + lines.slice(0, line).reduce((a, l) => a + l.length + 1, 0) + col;
    }
    const name = String(error).match(/([A-Za-z_$][\w$]*)\s+is not/);
    const found = name ? track.code.indexOf(name[1]) : -1;
    return at + Math.max(0, found);
  }

  const clean = ({ at, ...track }) => track;
  window.songCode = { compose, songText, parseSong, locate, clean };
})();
