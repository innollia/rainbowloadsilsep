"""Live check of Jev sorting on sample file sets (needs the Jev key; never prints it).

Pass: a usual game resolves in the five base groups (>= 90%), and when special groups appear
they gather several files each instead of scattering one file per group.
python tools/eval_classify.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import asset_classify as ac  # noqa: E402
from skill_router import ask_jev, read_key  # noqa: E402

SETS = {
    "usual": ["ui/click.wav", "ui/button_confirm.wav", "ui/menu_open.wav", "ui/popup_close.wav", "ui/notification.ogg",
              "combat/sword_swing_01.wav", "combat/sword_hit_02.wav", "combat/arrow_shot.wav", "combat/explosion_big.wav", "combat/shield_block.wav",
              "player/footstep_grass_01.wav", "player/footstep_stone_02.wav", "player/jump.wav", "player/land.wav", "player/hurt_grunt.wav",
              "amb/forest_birds_loop.ogg", "amb/wind_loop.ogg", "amb/rain_light.ogg", "amb/cave_drips.ogg", "amb/town_crowd.ogg",
              "music/title_theme.ogg", "music/battle_theme.ogg", "music/village_day.ogg", "music/victory_jingle.ogg", "music/game_over.ogg"],
    "racing": ["sfx/engine_idle.wav", "sfx/engine_rev_high.wav", "sfx/tire_screech.wav", "sfx/gear_shift.wav", "sfx/car_horn.wav",
               "sfx/turbo_blowoff.wav", "sfx/car_crash.wav", "sfx/nitro_boost.wav", "ui/menu_select.wav", "ui/countdown_beep.wav",
               "music/race_theme.ogg", "amb/stadium_crowd.ogg"],
    "story": ["vo/narrator_intro_001.ogg", "vo/hero_line_002.ogg", "vo/hero_line_003.ogg", "vo/villain_taunt_001.ogg", "vo/shopkeeper_greet.ogg",
              "ui/dialogue_next.wav", "ui/choice_select.wav", "music/sad_theme.ogg", "amb/castle_hall.ogg", "door_creak_open.wav",
              "door_slam.wav", "chest_open.wav", "coin_pickup.wav", "potion_drink.wav", "level_up.wav"],
}


def main():
    key = read_key()
    if not key:
        print("no Jev key")
        return 2
    failed = False
    for name, paths in SETS.items():
        files = [{"path": p, "secs": 60 if "music" in p else 8 if "amb" in p else 1} for p in paths]
        got = ac.classify(files, lambda q: ask_jev(key, {"task": "sort game sound files"}, q, timeout=20.0))
        s = ac.spread(got)
        ok = not s["scattered"] and (name != "usual" or s["base_share"] >= 0.9)
        failed |= not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: base {s['base_share']:.0%}, special {s['special']}, lonely {s['lonely']}")
        for p, g in got.items():
            print(f"    {g:10s} {p}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
