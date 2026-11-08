import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skill_router as sr  # noqa: E402
import studio_backend as sb  # noqa: E402

DIR = sb.SKILLS_DIR


def all_skills():
    return [s for g in sr.load_skill_catalog(DIR) for s in g["skills"]]


def test_fragments_are_music_skill_md_split_verbatim():
    original = sb.load_skill()
    bodies = "\n".join(sr.skill_body(s) for s in all_skills())
    for line in original.splitlines():
        if line.strip() and not line.startswith("#"):
            assert line in bodies, line
    names = [s["name"] for s in all_skills()]
    for heading in re.findall(r"^## (.+)$", original, re.M):
        assert heading in names or heading == "Genre recipes"


def test_flag_off_keeps_the_whole_skill_in_system_and_prompts_untouched(monkeypatch):
    assert sb.SKILL_ROUTER is False  # tests run without OLMUSE_SKILL_ROUTER
    assert sb.SYSTEM == sb.with_skill(sb.BASE_SYSTEM, sb.load_skill()) == sb.system_prompt(False)
    assert sb.with_skills("prompt", "make a house track", "new_song") == "prompt"


def test_routed_system_keeps_only_the_core_fragments():
    system = sb.system_prompt(True)
    assert system.startswith(sb.BASE_SYSTEM)
    assert "## Engine limits" in system and "## Sounds" in system and "There is no oh, rd, or rim." in system
    assert "## Mixing" not in system and "House, 120-128 bpm" not in system


def test_keyword_fallback_injects_matched_skill_bodies():
    route = sr.SkillRouter(DIR, api_key="")
    block = route("하우스 느낌으로 바꿔줘", kind="edit")
    assert route.last_route == "keyword"
    assert "## House" in block and "four-on-floor" in block  # the body, not a file index
    assert "## Trap" not in block and "## Mixing" not in block
    assert route("음", kind="edit") == ""


def test_keyword_fallback_without_skill_hit_takes_the_group_within_budget():
    block = sr.SkillRouter(DIR, api_key="", budget_chars=3000)("소리가 작아", kind="edit")
    assert "## Mixing" in block and len(block) <= 3000 + 200


def test_key_falls_back_to_the_pool_jev_name(tmp_path, monkeypatch):
    for name in sr.KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    pool = tmp_path / "key-pool.env"
    pool.write_text("OTHER=x\nJEV__BELLASIL2085=pool-key\n", encoding="utf-8")
    assert sr.read_key(str(pool)) == "pool-key"
    monkeypatch.setenv("TYPESAFE_API_KEY", "env-key")
    assert sr.read_key(str(pool)) == "env-key"
    assert sr.read_key(str(tmp_path / "missing.env")) == "env-key"


def test_listen_kind_always_brings_the_mixing_table_even_without_a_key():
    block = sr.SkillRouter(DIR, api_key="")("잘 됐는지 들어봐", kind="listen")
    assert "| Measurement | Code change |" in block and "## Common failures" in block


def test_budget_cuts_long_bodies_and_stops_under_500():
    skills = {s["name"]: s for s in all_skills()}
    picked = [{"skill": skills["Mixing"]}, {"skill": skills["House"]}]
    block = sr.render_bodies(picked, 900)
    assert "(Cut for length." in block and "## House" not in block
    assert sr.render_bodies(picked, 400) == ""
    budget = sr.allocate_context_budget(total_chars=30000, agent_document_chars=5000, history_chars=4000,
                                        reply_reserve_chars=2000)
    assert budget["remaining_chars"] == 19000
    assert sr.allocate_context_budget(total_chars=30000, agent_document_chars=40000)["remaining_chars"] == 0
    assert sr.SkillRouter(DIR, api_key="")("하우스", kind="edit", max_chars=499) == ""


class FakeJev:
    def __init__(self, replies):
        self.replies, self.bodies = list(replies), []

    def __call__(self, req, timeout=0):
        body = json.loads(req.data)
        self.bodies.append(body)
        assert req.full_url == sr.JEV_URL and body["model"] == "jev-latest"
        answers = self.replies.pop(0)(body["questions"])
        return io.BytesIO(json.dumps({"answers": answers}).encode())


def test_fake_jev_answers_pick_group_and_skill():
    groups = [g for g in sr.load_skill_catalog(DIR) if not g["always"]]
    genre = next(i for i, g in enumerate(groups) if g["name"] == "genre")

    def group_answers(questions):
        return {k: {"noul": 0.9 if k == f"group_{genre}" else 0.1} for k in questions}

    def skill_answers(questions):
        assert list(questions) == [f"skill_{genre}"]
        return {f"skill_{genre}": {"probabilities": {"Game music": 0.6, "Orchestra and symphony": 0.3, "House": 0.1}}}

    fake = FakeJev([group_answers, skill_answers])
    route = sr.SkillRouter(DIR, api_key="test", opener=fake)
    block = route("던전 보스전 음악 만들어줘", kind="new_song")
    assert route.last_route == "jev" and len(fake.bodies) == 2
    assert "## Game music" in block and "## Orchestra and symphony" in block and "## House" not in block
    assert fake.bodies[0]["state"]["current_message"] == "던전 보스전 음악 만들어줘"


def test_jev_failure_falls_back_to_keywords():
    def broken(questions):
        raise OSError("down")

    route = sr.SkillRouter(DIR, api_key="test", opener=FakeJev([broken]))
    assert "## Jazz" in route("재즈로 바꿔줘", kind="edit") and route.last_route == "keyword"


def test_decide_skills_thresholds():
    groups = [{"skills": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}]
    answers = {"group_0": {"noul": 0.7}}
    picked = sr.decide_skills(groups, answers, {"skill_0": {"probabilities": {"a": 0.7, "b": 0.2, "c": 0.1}}})
    assert [p["skill"]["name"] for p in picked] == ["a"]
    assert sr.decide_skills(groups, {"group_0": {"noul": 0.69}}, {}) == []


def test_routed_with_skills_prepends_block(monkeypatch):
    monkeypatch.setattr(sb, "SKILL_ROUTER", True)
    monkeypatch.setattr(sb, "_router", sr.SkillRouter(DIR, api_key=""))
    out = sb.with_skills("Current song: {}", "들어봐", "listen")
    assert out.startswith("# Craft notes for this request") and out.endswith("\n\nCurrent song: {}")
