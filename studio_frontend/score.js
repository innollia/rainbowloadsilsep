// Sheet music for a song: scored events -> sixteenth-note grid -> ABC (drawn by abcjs), MusicXML, MIDI.
// The file builders are pure so they can be checked without a browser; only mount touches the page.
(() => {
  const STEPS = 16; // sixteenth notes in a 4/4 bar, and one cycle is one bar
  const DURS = [16, 12, 8, 6, 4, 3, 2, 1];
  const TICKS = 120; // MIDI ticks per sixteenth at 480 per quarter
  const NOTE_TYPES = {
    16: ['whole', 0], 12: ['half', 1], 8: ['half', 0], 6: ['quarter', 1],
    4: ['quarter', 0], 3: ['eighth', 1], 2: ['eighth', 0], 1: ['16th', 0],
  };
  const SHARPS = [['C', 0], ['C', 1], ['D', 0], ['D', 1], ['E', 0], ['F', 0], ['F', 1], ['G', 0], ['G', 1], ['A', 0], ['A', 1], ['B', 0]];
  const FLATS = [['C', 0], ['D', -1], ['D', 0], ['E', -1], ['E', 0], ['F', 0], ['G', -1], ['G', 0], ['A', -1], ['A', 0], ['B', -1], ['B', 0]];
  const PROGRAMS = { bass: 33, pad: 89, melody: 80 };

  const ko = () => window.studioLang?.() === 'ko';
  const TEXT = {
    en: {
      perc_of: '{name} perc', untitled: 'Untitled', track: 'Track', bars: 'Bars', bars_n: '{n} bars', save: 'Save score', file_failed: "Couldn't make the file.",
      range: 'Bars {a}–{b}', all_tracks: 'All tracks', empty_all: 'No notes in this part.', empty_track: 'This track has no notes in this part.',
      moved: 'Notes off the sixteenth grid were moved to the nearest step.', legend: 'Percussion: {list}',
      draw_failed: "Couldn't draw the score. Saving files still works.", reading: 'Reading the score...', make_failed: "Couldn't make the score. Check that the song plays.",
    },
    ko: {
      perc_of: '{name} 타악', untitled: '제목 없음', track: '트랙', bars: '마디 수', bars_n: '{n}마디', save: '악보 저장', file_failed: '파일을 만들지 못했어.',
      range: '{a}~{b}마디', all_tracks: '전체 트랙', empty_all: '이 구간에는 음이 없어.', empty_track: '이 트랙은 이 구간에 음이 없어.',
      moved: '16분음표에 맞지 않는 음은 가장 가까운 칸으로 옮겨 적었어.', legend: '타악 표기: {list}',
      draw_failed: '악보를 그리지 못했어. 파일 저장은 그대로 쓸 수 있어.', reading: '악보를 읽는 중...', make_failed: '악보를 만들지 못했어. 곡이 소리 나는 상태인지 확인해 줘.',
    },
  };
  const txt = (key, vars = {}) => TEXT[ko() ? 'ko' : 'en'][key].replace(/\{(\w+)\}/g, (_, n) => vars[n] ?? '');
  // gm is the General MIDI drum key; step/oct place it on the five-line percussion staff.
  const drum = (key, names, gm, step, oct, head = 'normal') => ({ key, get label() { return names[ko() ? 1 : 0]; }, gm, step, oct, head });
  const DRUMS = [
    drum('bd', ['Kick', '킥'], 36, 'F', 4), drum('sd', ['Snare', '스네어'], 38, 'C', 5), drum('rim', ['Rimshot', '림샷'], 37, 'B', 4, 'x'),
    drum('cp', ['Clap', '클랩'], 39, 'D', 5, 'x'), drum('hh', ['Hi-hat', '하이햇'], 42, 'G', 5, 'x'), drum('oh', ['Open hi-hat', '오픈 하이햇'], 46, 'A', 5, 'x'),
    drum('cr', ['Crash', '크래시'], 49, 'B', 5, 'x'), drum('rd', ['Ride', '라이드'], 51, 'F', 5, 'x'), drum('ht', ['High tom', '하이 탐'], 50, 'E', 5),
    drum('mt', ['Mid tom', '미드 탐'], 47, 'B', 4), drum('lt', ['Low tom', '로우 탐'], 45, 'A', 4), drum('cb', ['Cowbell', '카우벨'], 56, 'E', 5, 'x'),
    drum('sh', ['Shaker', '셰이커'], 70, 'E', 4, 'x'), drum('tb', ['Tambourine', '탬버린'], 54, 'D', 4, 'x'), drum('perc', ['Percussion', '타악기'], 76, 'G', 4, 'x'),
  ];
  const DRUM_WORDS = [
    [/kick|bass ?drum/, 'bd'], [/snare/, 'sd'], [/clap/, 'cp'], [/open.*hat/, 'oh'], [/hat/, 'hh'],
    [/crash/, 'cr'], [/ride/, 'rd'], [/shak/, 'sh'], [/tamb/, 'tb'], [/cowbell/, 'cb'],
  ];
  const drumFor = (s) => {
    const name = String(s ?? '').toLowerCase();
    const short = name.split(/[_:]/).filter(Boolean).pop() ?? ''; // "RolandTR909_bd" -> "bd"
    const key = DRUMS.some((d) => d.key === short) ? short : DRUM_WORDS.find(([word]) => word.test(name))?.[1] ?? 'perc';
    return DRUMS.find((d) => d.key === key);
  };

  // Snap to the grid; same sound at one step becomes one note, and a repeat cuts the one still ringing.
  function quantize(events, cycles, identify) {
    const total = cycles * STEPS, byKey = new Map();
    let moved = 0;
    for (const e of [...events].sort((a, b) => a.b - b.b)) {
      const start = Math.round(e.b * STEPS);
      if (start >= total) continue;
      const end = Math.min(total, Math.max(start + 1, Math.round(e.e * STEPS)));
      if (Math.abs(e.b * STEPS - start) > 1e-6) moved++;
      const vel = Math.min(1, Math.max(0, Number(e.gain ?? 1) || 0));
      const id = identify(e), list = byKey.get(id.key) ?? [];
      byKey.set(id.key, list);
      const last = list[list.length - 1];
      if (last?.start === start) { last.end = Math.max(last.end, end); last.vel = Math.max(last.vel, vel); continue; }
      if (last && last.end > start) last.end = start;
      list.push({ ...id, start, end, vel });
    }
    return { notes: [...byKey.values()].flat().sort((a, b) => a.start - b.start || a.midi - b.midi), moved };
  }
  const pitchOf = (e) => {
    const midi = Math.min(127, Math.max(0, Math.round(e.note)));
    return { key: midi, midi };
  };
  const hitOf = (e) => {
    const d = drumFor(e.s);
    return { key: d.key, midi: d.gm, drum: d };
  };

  function allParts(song, reply, cycles) {
    const ids = [...song.tracks.map((t) => t.id), ...Object.keys(reply).filter((id) => !song.tracks.some((t) => t.id === id))];
    const parts = [];
    const add = (part, events, identify) => {
      const q = quantize(events, cycles, identify);
      if (!q.notes.length) return;
      parts.push({ ...part, notes: q.notes, moved: q.moved });
    };
    for (const id of ids) {
      const track = song.tracks.find((t) => t.id === id) ?? { id, name: id, role: 'other' };
      const events = reply[id] ?? [];
      const isDrums = track.role === 'drums';
      const tones = isDrums ? [] : events.filter((e) => e.note != null);
      const hits = isDrums ? events : events.filter((e) => e.note == null);
      add({ id, name: track.name, role: track.role, kind: 'pitched', clef: track.role === 'bass' ? 'bass' : 'treble' }, tones, pitchOf);
      add({ id, name: tones.length ? txt('perc_of', { name: track.name }) : track.name, role: track.role, kind: 'perc', clef: 'perc' }, hits, hitOf);
    }
    return parts;
  }

  function buildScore(song, reply, cycles, pick = 'all') {
    const parts = allParts(song, reply ?? {}, cycles);
    const chosen = pick === 'all' ? parts : parts.filter((p) => p.id === pick);
    const classes = chosen.filter((p) => p.kind === 'pitched').flatMap((p) => p.notes.map((n) => n.midi % 12));
    const count = (...pcs) => classes.filter((pc) => pcs.includes(pc)).length;
    const picked = pick === 'all' ? null : song.tracks.find((t) => t.id === pick);
    return {
      title: [song.name || txt('untitled'), picked?.name].filter(Boolean).join(' - '),
      bpm: song.bpm, cycles, parts: chosen,
      flats: count(3, 10) >= count(1, 6), // spell the whole score one way: Eb/Bb or C#/F#
      moved: chosen.reduce((sum, p) => sum + p.moved, 0),
    };
  }

  function spell(midi, flats) {
    const [step, alter] = (flats ? FLATS : SHARPS)[midi % 12];
    return { step, alter, oct: Math.floor(midi / 12) - 1 };
  }

  // Which single written note value may sit at a position in the bar, so beats and the middle stay visible.
  function fits(pos, d) {
    const inBeat = pos % 4 + d <= 4, inHalf = pos % 8 + d <= 8;
    switch (d) {
      case 16: return pos === 0;
      case 12: return pos % 4 === 0 && pos + 12 <= STEPS;
      case 8: return pos % 4 === 0;
      case 6: case 4: return pos % 2 === 0 && inHalf;
      case 3: case 2: return inBeat;
      default: return true;
    }
  }
  const firstFit = (pos, room) => DURS.find((d) => d <= room && fits(pos, d));

  // Drum parts are written by onset only: each hit lasts to the next hit and is never tied.
  function struck(notes) {
    const onsets = [...new Set(notes.map((n) => n.start))].sort((a, b) => a - b);
    return notes.map((n) => {
      const next = onsets.find((t) => t > n.start) ?? Infinity;
      const longest = Math.max(...notes.filter((o) => o.start === n.start).map((o) => o.end));
      const pos = n.start % STEPS;
      return { ...n, end: n.start + firstFit(pos, Math.min(next, longest, n.start - pos + STEPS) - n.start) };
    });
  }

  // Bars of {pos, dur, notes}: everything sounding between two changes, spelled as tied note values.
  function layout(part, cycles) {
    const notes = part.kind === 'perc' ? struck(part.notes) : part.notes;
    const bars = [];
    for (let m = 0; m < cycles; m++) {
      const from = m * STEPS, to = from + STEPS;
      const inside = notes.flatMap((n) => [n.start, n.end]).filter((t) => t > from && t < to);
      const cuts = [...new Set([from, to, ...inside])].sort((a, b) => a - b);
      const items = [];
      for (let i = 0; i + 1 < cuts.length; i++) {
        const [a, b] = [cuts[i], cuts[i + 1]];
        const sounding = notes.filter((n) => n.start < b && n.end > a);
        for (let at = a; at < b;) {
          const dur = firstFit(at - from, b - at);
          items.push({
            pos: at - from, dur,
            notes: sounding.map((n) => ({ ...n, tieIn: n.start < at, tieOut: n.end > at + dur })),
          });
          at += dur;
        }
      }
      bars.push(items);
    }
    return bars;
  }

  // --- ABC ---
  function abcLetter({ step, oct }) {
    return oct >= 5 ? step.toLowerCase() + "'".repeat(oct - 5) : step + ','.repeat(4 - oct);
  }
  const abcSize = (d) => (d === 1 ? '' : String(d));
  const abcText = (s) => String(s).replace(/["\r\n]/g, ' ');

  function abcBar(items, score) {
    const seen = new Map(); // an accidental holds to the end of the bar, so naturals must be written back
    return items.map((item) => {
      const gap = item.pos % 4 === 0 && item.pos ? ' ' : '';
      if (!item.notes.length) return `${gap}z${abcSize(item.dur)}`;
      const heads = item.notes.map((n) => {
        if (n.drum) return `${n.drum.head === 'x' ? '!style=x!' : ''}${abcLetter(n.drum)}`;
        const p = spell(n.midi, score.flats), id = p.step + p.oct;
        const mark = (seen.get(id) ?? 0) === p.alter ? '' : { 1: '^', 0: '=', '-1': '_' }[p.alter];
        seen.set(id, p.alter);
        return `${mark}${abcLetter(p)}`;
      });
      // A lone note takes its tie after the length; in a chord each head carries its own.
      const ties = item.notes.map((n) => (n.tieOut ? '-' : ''));
      if (heads.length === 1) return `${gap}${heads[0]}${abcSize(item.dur)}${ties[0]}`;
      return `${gap}[${heads.map((h, i) => h + ties[i]).join('')}]${abcSize(item.dur)}`;
    }).join('');
  }

  function toAbc(score) {
    const lines = ['X:1', `T:${abcText(score.title)}`, 'M:4/4', 'L:1/16', `Q:1/4=${Math.round(score.bpm)}`];
    score.parts.forEach((p, i) => lines.push(`V:${i + 1} clef=${p.clef}${p.kind === 'perc' ? ' stem=up' : ''} name="${abcText(p.name)}"`));
    lines.push('K:C');
    const bars = score.parts.map((p) => layout(p, score.cycles).map((items) => abcBar(items, score)));
    for (let m = 0; m < score.cycles; m += 4) {
      bars.forEach((partBars, i) => {
        const line = partBars.slice(m, m + 4).join(' | ');
        lines.push(`[V:${i + 1}] ${line} ${m + 4 >= score.cycles ? '|]' : '|'}`);
      });
    }
    return lines.join('\n') + '\n';
  }

  // --- MusicXML ---
  const xmlText = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  function xmlNote(n, item, chord, partNo) {
    const [type, dots] = NOTE_TYPES[item.dur];
    const out = ['<note>'];
    if (chord) out.push('<chord/>');
    if (!n) out.push(item.dur === STEPS ? '<rest measure="yes"/>' : '<rest/>');
    else if (n.drum) out.push(`<unpitched><display-step>${n.drum.step}</display-step><display-octave>${n.drum.oct}</display-octave></unpitched>`);
    else {
      const p = spell(n.midi, item.flats);
      out.push(`<pitch><step>${p.step}</step>${p.alter ? `<alter>${p.alter}</alter>` : ''}<octave>${p.oct}</octave></pitch>`);
    }
    out.push(`<duration>${item.dur}</duration>`);
    if (n?.tieIn) out.push('<tie type="stop"/>');
    if (n?.tieOut) out.push('<tie type="start"/>');
    if (n?.drum) out.push(`<instrument id="P${partNo}-I${n.drum.gm}"/>`);
    out.push('<voice>1</voice>', `<type>${type}</type>`, '<dot/>'.repeat(dots));
    if (n?.drum?.head === 'x') out.push('<notehead>x</notehead>');
    if (n?.tieIn || n?.tieOut) {
      out.push(`<notations>${n.tieIn ? '<tied type="stop"/>' : ''}${n.tieOut ? '<tied type="start"/>' : ''}</notations>`);
    }
    out.push('</note>');
    return out.join('');
  }

  function toMusicXml(score) {
    const instruments = (p) => [...new Map(p.notes.map((n) => [n.drum.key, n.drum])).values()];
    const list = score.parts.map((p, i) => {
      const no = i + 1;
      const name = `<part-name>${xmlText(p.name)}</part-name>`;
      if (p.kind !== 'perc') return `<score-part id="P${no}">${name}</score-part>`;
      const drums = instruments(p);
      return `<score-part id="P${no}">${name}`
        + drums.map((d) => `<score-instrument id="P${no}-I${d.gm}"><instrument-name>${xmlText(d.label)}</instrument-name></score-instrument>`).join('')
        + drums.map((d) => `<midi-instrument id="P${no}-I${d.gm}"><midi-channel>10</midi-channel><midi-unpitched>${d.gm + 1}</midi-unpitched></midi-instrument>`).join('')
        + '</score-part>';
    }).join('\n');
    const clefs = { treble: ['G', 2], bass: ['F', 4], perc: ['percussion', 2] };
    const body = score.parts.map((p, i) => {
      const no = i + 1;
      const measures = layout(p, score.cycles).map((items, m) => {
        const [sign, line] = clefs[p.clef];
        const head = m ? '' : `<attributes><divisions>4</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>${sign}</sign><line>${line}</line></clef></attributes>`
          + (i ? '' : `<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>${Math.round(score.bpm)}</per-minute></metronome></direction-type><sound tempo="${score.bpm}"/></direction>`);
        const notes = items.map((item) => {
          const each = { ...item, flats: score.flats };
          if (!item.notes.length) return xmlNote(null, each, false, no);
          return item.notes.map((n, k) => xmlNote(n, each, k > 0, no)).join('');
        }).join('\n');
        return `<measure number="${m + 1}">${head}\n${notes}\n</measure>`;
      }).join('\n');
      return `<part id="P${no}">\n${measures}\n</part>`;
    }).join('\n');
    return '<?xml version="1.0" encoding="UTF-8"?>\n'
      + '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">\n'
      + `<score-partwise version="4.0">\n<work><work-title>${xmlText(score.title)}</work-title></work>\n<part-list>\n${list}\n</part-list>\n${body}\n</score-partwise>\n`;
  }

  // --- Standard MIDI file, format 1: a tempo track, then one track per part ---
  const uint = (value, size) => Array.from({ length: size }, (_, i) => (value >>> (8 * (size - 1 - i))) & 255);
  function varLen(value) {
    const out = [value & 127];
    for (let v = value >>> 7; v; v >>>= 7) out.unshift((v & 127) | 128);
    return out;
  }
  const chunk = (tag, data) => [...tag].map((c) => c.charCodeAt(0)).concat(uint(data.length, 4), data);
  const midiTrack = (events) => {
    let now = 0;
    const data = [];
    for (const e of events) { data.push(...varLen(e.tick - now), ...e.bytes); now = e.tick; }
    data.push(0, 0xff, 0x2f, 0);
    return chunk('MTrk', data);
  };
  const nameEvent = (name) => {
    const text = [...new TextEncoder().encode(String(name))];
    return { tick: 0, bytes: [0xff, 0x03, ...varLen(text.length), ...text] };
  };

  function toMidi(score) {
    const tempo = Math.round(60000000 / (score.bpm || 120));
    const out = [chunk('MThd', [...uint(1, 2), ...uint(score.parts.length + 1, 2), ...uint(TICKS * 4, 2)])];
    out.push(midiTrack([
      nameEvent(score.title),
      { tick: 0, bytes: [0xff, 0x51, 0x03, ...uint(tempo, 3)] },
      { tick: 0, bytes: [0xff, 0x58, 0x04, 4, 2, 24, 8] },
    ]));
    let free = 0;
    for (const p of score.parts) {
      let channel = 9;
      if (p.kind !== 'perc') { channel = free % 15; if (channel >= 9) channel++; free++; }
      const timed = [];
      for (const n of p.notes) {
        const vel = Math.max(1, Math.round(n.vel * 127));
        timed.push({ tick: n.start * TICKS, order: 1, bytes: [0x90 | channel, n.midi, vel] });
        timed.push({ tick: n.end * TICKS, order: 0, bytes: [0x80 | channel, n.midi, 0] });
      }
      timed.sort((a, b) => a.tick - b.tick || a.order - b.order);
      const head = [nameEvent(p.name)];
      if (p.kind !== 'perc') head.push({ tick: 0, bytes: [0xc0 | channel, PROGRAMS[p.role] ?? 0] });
      out.push(midiTrack([...head, ...timed]));
    }
    return new Uint8Array(out.flat());
  }

  // --- Page ---
  const here = document.currentScript?.src ?? location.href;
  const asset = (path) => new URL(path, here).href;
  let abcjsLoad = null;
  function loadAbcjs() {
    if (window.ABCJS) return Promise.resolve();
    abcjsLoad ??= new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = asset('vendor/abcjs-basic-min.js');
      s.onload = resolve;
      s.onerror = () => { abcjsLoad = null; reject(new Error('abcjs')); };
      document.head.append(s);
    });
    return abcjsLoad;
  }
  function ensureCss() {
    if (document.querySelector('link[data-score-css]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = asset('score.css');
    link.dataset.scoreCss = '1';
    document.head.append(link);
  }

  function save(name, type, data) {
    const url = URL.createObjectURL(new Blob([data], { type }));
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const element = (tag, props = {}, ...kids) => {
    const el = Object.assign(document.createElement(tag), props);
    el.append(...kids);
    return el;
  };
  const fileName = (title) => title.replace(/[\\/:*?"<>|\s]+/g, '_').replace(/^_+|_+$/g, '') || 'score';

  const mounts = new WeakMap(); // host -> newest mount, so an older one's late answers are dropped

  const SAVE_ICON = '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11M7 11l5 5 5-5M5 20h14"/></svg>';
  const FORMATS = [
    ['MIDI', 'mid', 'audio/midi', toMidi],
    ['MusicXML', 'musicxml', 'application/vnd.recordare.musicxml+xml', toMusicXml],
    ['ABC', 'abc', 'text/vnd.abc', toAbc],
  ];

  function mount(host, { song, query, onError, position }) {
    ensureCss();
    const view = mounts.get(host)?.view ?? { track: 'all', cycles: 4 };
    const run = { view };
    mounts.set(host, run);
    const stale = () => mounts.get(host) !== run;
    let reply = null, score = null, asked = 0, from = 0, drawn = '', beats = [], cursor = null, lit = -1, lineTop = null, turning = false;

    const trackBox = element('select', { ariaLabel: txt('track') });
    const barBox = element('select', { ariaLabel: txt('bars') });
    for (const n of [4, 8, 16]) barBox.append(element('option', { value: String(n), textContent: txt('bars_n', { n }) }));
    barBox.value = String(view.cycles);
    const range = element('span', { className: 'score-range', role: 'status' });
    const note = element('p', { className: 'score-note', role: 'status' });
    const paper = element('div', { className: 'score-paper', hidden: true });
    const legend = element('p', { className: 'score-legend', hidden: true });
    const saveBtn = element('button', { type: 'button', className: 'iconBtn', innerHTML: SAVE_ICON, ariaLabel: txt('save'), title: txt('save'), disabled: true });
    saveBtn.setAttribute('aria-haspopup', 'menu');
    saveBtn.setAttribute('aria-expanded', 'false');
    const menu = element('div', { className: 'score-menu', role: 'menu', hidden: true });
    const closeMenu = () => { menu.hidden = true; saveBtn.setAttribute('aria-expanded', 'false'); };
    saveBtn.onclick = (e) => {
      e.stopPropagation();
      menu.hidden = !menu.hidden; saveBtn.setAttribute('aria-expanded', String(!menu.hidden));
      if (!menu.hidden) menu.firstChild.focus();
    };
    // A file always starts at bar 1, wherever playback has turned the page to.
    async function saveAs(ext, type, make) {
      closeMenu();
      if (!score) return;
      let made = score;
      if (from) {
        const r = await query(view.cycles, 0);
        if (!r?.ok) { note.textContent = txt('file_failed'); return; }
        made = buildScore(song, r.tracks ?? {}, view.cycles, view.track);
      }
      save(`${fileName(made.title)}.${ext}`, type, make(made));
    }
    for (const [label, ext, type, make] of FORMATS) {
      const item = element('button', { type: 'button', role: 'menuitem', onclick: () => saveAs(ext, type, make) },
        element('span', { textContent: label }), element('small', { textContent: `.${ext}` }));
      menu.append(item);
    }
    const dismiss = (e) => {
      if (stale()) { removeEventListener('pointerdown', dismiss); removeEventListener('keydown', escape); return; }
      if (!menu.hidden && !menu.contains(e.target) && !saveBtn.contains(e.target)) closeMenu();
    };
    const escape = (e) => { if (e.key === 'Escape' && !menu.hidden) { closeMenu(); saveBtn.focus(); } };
    addEventListener('pointerdown', dismiss); addEventListener('keydown', escape);

    host.replaceChildren(element('div', { className: 'score' },
      element('div', { className: 'score-bar' }, trackBox, barBox, range, element('span', { className: 'score-gap' }),
        element('div', { className: 'score-save' }, saveBtn, menu)),
      note, paper, legend));

    const say = (text) => { note.textContent = text; };
    const showRange = () => { range.textContent = from || position?.().playing ? txt('range', { a: from + 1, b: from + view.cycles }) : ''; };
    const clearLit = () => { if (lit >= 0) beats[lit]?.notes.forEach((n) => n.classList.remove('score-on')); lit = -1; };
    const blank = () => {
      score = null; drawn = ''; beats = []; cursor = null; lit = -1;
      paper.hidden = legend.hidden = true; paper.replaceChildren();
      saveBtn.disabled = true; closeMenu();
    };
    function fillTracks() {
      const extra = Object.keys(reply ?? {}).filter((id) => !song.tracks.some((t) => t.id === id));
      const rows = [['all', txt('all_tracks')], ...song.tracks.map((t) => [t.id, t.name]), ...extra.map((id) => [id, id])];
      if (!rows.some(([id]) => id === view.track)) view.track = 'all';
      trackBox.replaceChildren(...rows.map(([value, textContent]) => element('option', { value, textContent })));
      trackBox.value = view.track;
    }
    // Each drawing gets its own box: abcjs writes inline layout onto its target, and that must not stick to the paper.
    function draw(abc, made) {
      const sheet = element('div');
      paper.hidden = false;
      paper.append(sheet);
      const [tune] = window.ABCJS.renderAbc(sheet, abc, { responsive: 'resize', staffwidth: 860, paddingleft: 8, paddingright: 8, add_classes: true });
      while (paper.firstChild !== sheet) paper.firstChild.remove();
      drawn = abc; lit = -1; lineTop = null;
      tune.setTiming?.(made.bpm);
      const svg = sheet.querySelector('svg');
      beats = (tune.noteTimings ?? []).filter((t) => t.type === 'event' && t.left != null).map((t) => ({
        at: t.milliseconds, left: t.left, top: t.top, height: t.height, notes: (t.elements ?? []).flat(Infinity).filter(Boolean),
      }));
      cursor = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      cursor.setAttribute('class', 'score-cursor');
      cursor.style.display = 'none';
      svg?.append(cursor);
    }
    async function show() {
      const made = buildScore(song, reply, view.cycles, view.track);
      if (!made.parts.length) {
        blank();
        say(view.track === 'all' ? txt('empty_all') : txt('empty_track'));
        return;
      }
      score = made;
      saveBtn.disabled = false;
      say(made.moved ? txt('moved') : '');
      const used = [...new Map(made.parts.flatMap((p) => p.notes).filter((n) => n.drum).map((n) => [n.drum.key, n.drum])).values()];
      legend.textContent = used.length ? txt('legend', { list: used.map((d) => d.label).join(', ') }) : '';
      legend.hidden = !used.length;
      try {
        await loadAbcjs();
        if (stale() || score !== made) return;
        const abc = toAbc(made);
        if (abc !== drawn) draw(abc, made); // a repeating song keeps the same page, so nothing flickers
        showRange();
      } catch (e) {
        paper.hidden = true;
        say(txt('draw_failed'));
        onError?.(String(e.message || e));
      }
    }
    async function load(quiet = false) {
      const ticket = ++asked;
      if (!quiet) { blank(); say(txt('reading')); }
      let r;
      try { r = await query(view.cycles, from); } catch (e) { r = { ok: false, error: String(e.message || e) }; }
      if (stale() || ticket !== asked) return;
      if (!r?.ok) {
        if (quiet) return; // a failed page turn keeps the page on screen
        reply = null;
        say(txt('make_failed'));
        onError?.(r?.error ?? 'score failed');
        return;
      }
      reply = r.tracks ?? {};
      fillTracks();
      await show();
    }
    trackBox.onchange = () => { view.track = trackBox.value; if (reply) show(); };
    const pageOf = (cycle) => Math.floor(Math.max(0, cycle) / view.cycles) * view.cycles;
    barBox.onchange = () => {
      view.cycles = +barBox.value;
      const now = position?.();
      from = now?.playing ? pageOf(now.cycles) : 0;
      load();
    };

    // Follows the sound: the page turns with the bars, a line sweeps the system and the sounding notes light up.
    function place(cycle) {
      const ms = (cycle - from) * 240000 / (score?.bpm || 120);
      let i = beats.length - 1;
      while (i > 0 && beats[i].at > ms) i--;
      const now = beats[i], next = beats[i + 1];
      if (!now || !cursor) return;
      const span = next && next.top === now.top ? next.left - now.left : 0;
      const share = next ? Math.min(1, Math.max(0, (ms - now.at) / ((next.at - now.at) || 1))) : 0;
      const x = String(now.left + span * share);
      cursor.setAttribute('x1', x); cursor.setAttribute('x2', x);
      cursor.setAttribute('y1', String(now.top)); cursor.setAttribute('y2', String(now.top + now.height));
      cursor.style.display = '';
      if (i !== lit) { clearLit(); now.notes.forEach((n) => n.classList.add('score-on')); lit = i; }
      if (now.top !== lineTop) {
        lineTop = now.top;
        const box = host.closest('#stage'), q = cursor.getBoundingClientRect(), b = box?.getBoundingClientRect();
        if (b && (q.top < b.top || q.bottom > b.bottom)) box.scrollBy({ top: q.top - b.top - 24, behavior: 'smooth' });
      }
    }
    function follow() {
      if (stale()) return;
      requestAnimationFrame(follow);
      const now = position?.();
      if (!now?.playing || host.hidden) {
        if (cursor && cursor.style.display !== 'none') { cursor.style.display = 'none'; clearLit(); lineTop = null; showRange(); }
        return;
      }
      if (!range.textContent) showRange();
      const page = pageOf(now.cycles);
      if (page !== from && !turning) {
        from = page; turning = true;
        load(true).finally(() => { turning = false; });
        return;
      }
      if (!turning && score) place(now.cycles);
    }

    fillTracks();
    requestAnimationFrame(follow);
    return load();
  }

  window.studioScore = { mount, buildScore, toAbc, toMusicXml, toMidi };
})();
