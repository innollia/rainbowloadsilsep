// Song <-> Strudel text. Pure functions, shared by the player and the code editor.
(() => {
  const ID = /^[a-z][a-z0-9_]{0,23}$/;

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
    return [`setcpm(${song.bpm}/4)`, ...song.tracks.map((t) => `$${t.id}: ${t.code}`)].join('\n\n') + '\n';
  }

  const rawSong = (text, prev) => ({
    bpm: prev.bpm,
    tracks: [{ id: 'song', name: '전체 곡', role: 'other', code: text, raw: true }],
  });

  // Anything that is not "tempo plus named tracks" stays one whole-song track rather than being guessed at.
  function parseSong(text, prev) {
    const marks = [...text.matchAll(/^\$([^\s:]*):/gm)];
    if (!marks.length) return rawSong(text, prev);
    const head = text.slice(0, marks[0].index).replace(/\/\/.*$/gm, '');
    const tempo = head.match(/setcpm\(\s*([\d.]+)\s*\/\s*4\s*\)/);
    if (head.replace(tempo ? tempo[0] : '', '').replace(/;/g, '').trim()) return rawSong(text, prev);
    const old = Object.fromEntries(prev.tracks.map((t) => [t.id, t]));
    const tracks = marks.map((m, i) => {
      const code = text.slice(m.index + m[0].length, marks[i + 1]?.index ?? text.length).trim();
      const had = old[m[1]];
      return { id: m[1], name: had?.name || m[1], role: had?.role || 'other', code };
    });
    const ids = tracks.map((t) => t.id);
    if (ids.some((id) => !ID.test(id)) || new Set(ids).size !== ids.length || tracks.some((t) => !t.code) || tracks.length > 8) {
      return rawSong(text, prev);
    }
    const bpm = tempo ? Math.min(400, Math.max(20, +tempo[1])) : prev.bpm;
    return { bpm, tracks };
  }

  window.songCode = { compose, songText, parseSong };
})();
