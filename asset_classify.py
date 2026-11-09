"""Sorts imported sound files into the asset studio's groups with Jev, for users who have no agent to ask.

Each file is asked once among the five base groups, the special groups already in use, and "other".
A file that answers "other" is asked again among all special groups or "unsorted". A special group
chosen once is offered in the first question from then on, so related files gather in it instead of
spreading one file per group. Files go in small batches so the special groups grow between batches.
"""
from __future__ import annotations

import re

BASE = {
    "ui": "Interface sounds: clicks, buttons, menus, popups, notifications, confirm and cancel.",
    "combat": "Fighting: weapon swings and hits, shots, explosions, damage, skills and spells used in battle.",
    "char": "A character's own body: footsteps, jumps, landing, voice effort grunts, breathing, pickups by the player.",
    "env": "Ambience and the world around: wind, rain, water, birds, crowds, room tone, looping backgrounds.",
    "bgm": "Music: background tracks, themes, battle music, menu music, jingles and stingers.",
}
OTHER, UNSORTED = "other", "unsorted"
SPECIALS = {
    "voice": "Spoken lines and dialogue, narration, announcer calls.",
    "vehicle": "Cars, engines, ships, aircraft, riding mounts.",
    "machine": "Machines and devices: doors, levers, elevators, traps, robots, gears.",
    "magic": "Magic and fantasy effects outside battle: portals, enchanting, teleport, sparkles.",
    "item": "Items and rewards: coins, chests, crafting, potions, level up, achievement.",
    "creature": "Animals and monsters: roars, growls, barks, wings, monster cries.",
    "weather": "Weather events: thunder, storms, hail.",
    "cinematic": "Cutscene and trailer sounds: whooshes, risers, impacts, transitions.",
    "horror": "Horror stingers, creepy textures, jump scares.",
    "sport": "Sports and games: balls, whistles, crowds cheering a match, scoreboards.",
}
BATCH = 8


def describe(path: str, secs) -> str:
    words = re.sub(r"[_\-./\\]+", " ", path).strip()
    return f"file path: {path} (words: {words}); length: {float(secs or 0):.1f} s"


def first_question(path: str, secs, specials: list) -> dict:
    options = {**BASE, **{s: SPECIALS[s] for s in specials},
               OTHER: "None of the groups above fits this sound well."}
    return {"type": "choice",
            "instructions": "A game's sound file is being sorted into folders by what it is used for in the game. "
                            f"Which group fits it best? {describe(path, secs)}. "
                            "Judge from the file name, its folders and its length. Most sounds belong to one of the first five groups.",
            "criteria": options}


def second_question(path: str, secs) -> dict:
    return {"type": "choice",
            "instructions": "This game sound fit none of the five usual groups (UI, combat, character, ambience, music). "
                            f"Which special group fits it? {describe(path, secs)}",
            "criteria": {**SPECIALS, UNSORTED: "No group here fits, or the name says too little to tell."}}


def top(answer: dict, allowed) -> str:
    probabilities = (answer or {}).get("probabilities") or {}
    ranked = sorted(((k, v) for k, v in probabilities.items() if k in allowed), key=lambda kv: kv[1], reverse=True)
    return ranked[0][0] if ranked else ""


def classify(files: list, ask, batch: int = BATCH) -> dict:
    """files: [{"path", "secs"}]; ask(questions) -> {key: {"probabilities": {...}}}. Returns {path: group}."""
    out, specials, asked_with = {}, [], {}
    for start in range(0, len(files), batch):
        chunk = files[start:start + batch]
        firsts = ask({f"f{i}": first_question(f["path"], f.get("secs"), specials) for i, f in enumerate(chunk)})
        again = []
        for f in chunk:
            asked_with[f["path"]] = len(specials)
        for i, f in enumerate(chunk):
            pick = top(firsts.get(f"f{i}"), [*BASE, *specials, OTHER])
            if pick in (OTHER, ""):
                again.append(i)
            else:
                out[f["path"]] = pick
        if again:
            seconds = ask({f"s{i}": second_question(chunk[i]["path"], chunk[i].get("secs")) for i in again})
            for i in again:
                pick = top(seconds.get(f"s{i}"), [*SPECIALS, UNSORTED]) or UNSORTED
                out[chunk[i]["path"]] = pick
                if pick in SPECIALS and pick not in specials:
                    specials.append(pick)
    # Files sorted before a special group existed are asked once more with it on offer, so related files end up together.
    late = [f for f in files if out.get(f["path"]) in BASE and asked_with[f["path"]] < len(specials)]
    for start in range(0, len(late), batch):
        chunk = late[start:start + batch]
        again = ask({f"f{i}": first_question(f["path"], f.get("secs"), specials) for i, f in enumerate(chunk)})
        for i, f in enumerate(chunk):
            pick = top(again.get(f"f{i}"), [*BASE, *specials])
            if pick in specials:
                out[f["path"]] = pick
    return out


def spread(result: dict) -> dict:
    """How the answer is judged: base share, and whether special groups gather files or scatter them one by one."""
    groups = {}
    for g in result.values():
        groups[g] = groups.get(g, 0) + 1
    special = {g: n for g, n in groups.items() if g in SPECIALS}
    lonely = [g for g, n in special.items() if n == 1]
    total = len(result) or 1
    return {"base_share": sum(n for g, n in groups.items() if g in BASE) / total, "special": special,
            "lonely": lonely, "scattered": len(special) > 1 and len(lonely) * 2 > len(special), "groups": groups}
