import asset_classify as ac


def fake_jev(first_rule, second_rule, seen):
    """Answers like Jev: first_rule(path, options) -> group, second_rule(path) -> special group."""
    def ask(questions):
        seen.append(questions)
        out = {}
        for key, q in questions.items():
            path = q["instructions"].split("file path: ")[1].split(" (")[0]
            pick = first_rule(path, list(q["criteria"])) if key.startswith("f") else second_rule(path)
            out[key] = {"probabilities": {pick: 0.9, **{k: 0.1 / len(q["criteria"]) for k in q["criteria"] if k != pick}}}
        return out
    return ask


def test_usual_files_stay_in_the_five_groups():
    files = [{"path": p, "secs": 1} for p in ["ui/click.wav", "combat/sword.wav", "steps.wav", "rain_loop.ogg", "theme.ogg"]]
    rule = {"ui/click.wav": "ui", "combat/sword.wav": "combat", "steps.wav": "char", "rain_loop.ogg": "env", "theme.ogg": "bgm"}
    seen = []
    got = ac.classify(files, fake_jev(lambda p, o: rule[p], lambda p: "unsorted", seen))
    assert got == rule
    assert len(seen) == 1  # no second question when nothing is "other"
    assert ac.spread(got)["base_share"] == 1


def test_a_special_group_once_chosen_is_offered_first_from_then_on():
    files = [{"path": f"car_{i}.wav", "secs": 2} for i in range(12)]
    seen = []
    first = lambda p, options: "vehicle" if "vehicle" in options else "other"
    got = ac.classify(files, fake_jev(first, lambda p: "vehicle", seen), batch=4)
    assert set(got.values()) == {"vehicle"}
    later_firsts = [q for q in seen[2:] if any(k.startswith("f") for k in q)]
    assert later_firsts and all("vehicle" in q["criteria"] for batch in later_firsts for q in batch.values())
    assert not ac.spread(got)["scattered"]


def test_scattered_specials_are_judged_a_failure():
    result = {"a.wav": "voice", "b.wav": "machine", "c.wav": "magic", "d.wav": "ui"}
    assert ac.spread(result)["scattered"]
    dense = {"a.wav": "voice", "b.wav": "voice", "c.wav": "machine", "d.wav": "machine"}
    assert not ac.spread(dense)["scattered"]


def test_unknown_answers_fall_back_to_unsorted():
    got = ac.classify([{"path": "x.wav", "secs": 1}], lambda q: {})
    assert got == {"x.wav": "unsorted"}


def test_files_sorted_before_a_special_group_existed_are_asked_again():
    files = [{"path": "vo/a.ogg", "secs": 2}, {"path": "vo/b.ogg", "secs": 2}]
    calls = []
    # The first file is called "char" until "voice" is on offer; the second goes through "other" to "voice".
    first = lambda p, options: "voice" if "voice" in options else ("char" if p == "vo/a.ogg" else "other")
    got = ac.classify(files, fake_jev(first, lambda p: "voice", calls))
    assert got == {"vo/a.ogg": "voice", "vo/b.ogg": "voice"}
