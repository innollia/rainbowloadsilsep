from itertools import combinations
import pytest

from engine import (ALL, LEVELS, RULES, apply, best_experiment, candidates,
                    consistent, distinguishing_input, grade, info_gain, lit,
                    secret_for)


def m(*cells):
    return sum(1 << (r * 3 + c) for r, c in cells)


def test_displayed_rules_are_distinct_on_some_input():
    for a, b in combinations(RULES, 2):
        assert any(apply(a, v) != apply(b, v) for v in range(ALL + 1)), f"equivalent rules: {a}, {b}"


def test_output_mask_limits():
    for key in RULES:
        for x in range(ALL + 1):
            assert 0 <= apply(key, x) <= ALL


def test_known_spatial_transformations():
    single = m((0, 0))
    assert apply("mirror_lr", single) == m((0, 2))
    assert apply("mirror_ud", single) == m((2, 0))
    assert apply("spin_cw", single) == m((0, 2))
    assert apply("transpose", m((0, 2))) == m((2, 0))
    assert apply("drift_right", m((0, 2))) == single
    assert apply("drift_down", m((2, 0))) == single


def test_local_rules():
    assert apply("spread", m((1, 1))) == m((1, 1), (0, 1), (1, 0), (1, 2), (2, 1))
    assert apply("xor_cross", m((1, 1))) == m((0, 1), (1, 0), (1, 2), (2, 1))
    assert apply("lonely_filter", m((0, 0))) == 0
    assert apply("lonely_filter", m((0, 0), (0, 1))) == m((0, 0), (0, 1))
    assert apply("gravity", m((0, 0), (1, 0), (0, 2))) == m((1, 0), (2, 0), (2, 2))
    assert apply("parity_switch", 0) == ALL
    assert apply("parity_switch", m((1, 1))) == m((1, 1))
    assert apply("row_vote", m((0, 0), (0, 2))) == m((0, 0), (0, 1), (0, 2))


def test_life_blinker():
    vertical = m((0, 1), (1, 1), (2, 1))
    horizontal = m((1, 0), (1, 1), (1, 2))
    assert apply("life", vertical) == horizontal
    assert apply("life", horizontal) == vertical


def test_real_rule_survives_all_observations():
    for level in range(len(LEVELS)):
        for seed in (0, 1, 42, 20261107):
            truth = secret_for(level, seed)
            assert truth in candidates(level)
            history = []
            for mask in (1, 24, 37, 128, ALL):
                history.append({"input": mask, "output": apply(truth, mask)})
                assert truth in consistent(candidates(level), history)


def test_best_experiment_can_separate_every_level_and_is_optimal():
    for level in range(len(LEVELS)):
        keys = candidates(level)
        suggestion = best_experiment(keys)
        assert suggestion is not None
        mask, gain = suggestion
        assert gain > 0
        assert abs(info_gain(keys, mask) - gain) < 1e-10
        assert gain >= max(info_gain(keys, i) for i in range(1, ALL)) - 1e-10


def test_active_learning_never_leaves_unsplittable_distinct_hypotheses():
    for level in range(len(LEVELS)):
        for truth in candidates(level):
            records = []
            for _ in range(len(candidates(level)) + 1):
                left = consistent(candidates(level), records)
                if len(left) == 1:
                    break
                probe = best_experiment(left, [x["input"] for x in records])
                assert probe is not None
                mask, _ = probe
                records.append({"input": mask, "output": apply(truth, mask)})
            assert consistent(candidates(level), records) == [truth]


def test_distinguishing_example():
    for a, b in combinations(RULES, 2):
        inp = distinguishing_input(a, b)
        assert inp is not None
        assert apply(a, inp) != apply(b, inp)


def test_grade_and_invalid_inputs():
    assert grade(1, 0, 0) == 100
    assert grade(2, 1, 1) == 54
    assert grade(100, 0, 0) == 0
    with pytest.raises(ValueError):
        apply("identity", ALL + 1)
    with pytest.raises(KeyError):
        apply("nonexistent", 0)
