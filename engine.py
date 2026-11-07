"""BLACK BOX 09: deterministic, pure-Python rule engine and inference helpers."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import log2
from random import Random
from typing import Callable, Iterable

N = 3
ALL = (1 << (N * N)) - 1


def lit(mask: int, r: int, c: int) -> bool:
    return bool(mask & (1 << (r * N + c)))


def put(mask: int, r: int, c: int) -> int:
    return mask | (1 << (r * N + c))


def transform(mask: int, point: Callable[[int, int], tuple[int, int]]) -> int:
    out = 0
    for r in range(N):
        for c in range(N):
            if lit(mask, r, c):
                rr, cc = point(r, c)
                out = put(out, rr, cc)
    return out


def mirror_lr(mask: int) -> int:
    return transform(mask, lambda r, c: (r, 2 - c))


def mirror_ud(mask: int) -> int:
    return transform(mask, lambda r, c: (2 - r, c))


def spin_cw(mask: int) -> int:
    return transform(mask, lambda r, c: (c, 2 - r))


def transpose(mask: int) -> int:
    return transform(mask, lambda r, c: (c, r))


def drift_right(mask: int) -> int:
    return transform(mask, lambda r, c: (r, (c + 1) % 3))


def drift_down(mask: int) -> int:
    return transform(mask, lambda r, c: ((r + 1) % 3, c))


def adjacent(mask: int, r: int, c: int, *, diagonals: bool = False) -> int:
    total = 0
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == dc == 0:
                continue
            if not diagonals and abs(dr) + abs(dc) != 1:
                continue
            rr, cc = r + dr, c + dc
            if 0 <= rr < N and 0 <= cc < N and lit(mask, rr, cc):
                total += 1
    return total


def spread(mask: int) -> int:
    return sum(1 << (r * N + c) for r in range(N) for c in range(N)
               if lit(mask, r, c) or adjacent(mask, r, c) > 0)


def xor_cross(mask: int) -> int:
    return sum(1 << (r * N + c) for r in range(N) for c in range(N)
               if adjacent(mask, r, c) % 2 == 1)


def lonely_filter(mask: int) -> int:
    return sum(1 << (r * N + c) for r in range(N) for c in range(N)
               if lit(mask, r, c) and adjacent(mask, r, c) >= 1)


def gravity(mask: int) -> int:
    out = 0
    for c in range(N):
        count = sum(lit(mask, r, c) for r in range(N))
        for r in range(N - count, N):
            out = put(out, r, c)
    return out


def parity_switch(mask: int) -> int:
    return mask ^ ALL if mask.bit_count() % 2 == 0 else mask


def life(mask: int) -> int:
    return sum(1 << (r * N + c) for r in range(N) for c in range(N)
               if adjacent(mask, r, c, diagonals=True) == 3
               or (lit(mask, r, c) and adjacent(mask, r, c, diagonals=True) == 2))


def diagonal_pair(mask: int) -> int:
    out = 0
    for r in range(N):
        for c in range(N):
            n = sum(lit(mask, r + dr, c + dc)
                    for dr in (-1, 1) for dc in (-1, 1)
                    if 0 <= r + dr < N and 0 <= c + dc < N)
            if n == 2:
                out = put(out, r, c)
    return out


def row_vote(mask: int) -> int:
    return sum(1 << (r * N + c) for r in range(N) for c in range(N)
               if sum(lit(mask, r, i) for i in range(N)) >= 2)


@dataclass(frozen=True)
class Rule:
    name: str
    short: str
    explanation: str
    func: Callable[[int], int]


RULES: dict[str, Rule] = {
    "identity": Rule("그대로", "입력 모양 보존", "모든 칸의 상태를 그대로 내보낸다.", lambda m: m),
    "mirror_lr": Rule("좌우 거울", "왼쪽과 오른쪽 교환", "각 행의 첫째 칸과 셋째 칸을 교환한다.", mirror_lr),
    "mirror_ud": Rule("상하 거울", "위쪽과 아래쪽 교환", "윗줄과 아랫줄을 교환한다.", mirror_ud),
    "spin_cw": Rule("시계 회전", "시계 방향 90°", "전체 모양을 시계 방향으로 90도 회전한다.", spin_cw),
    "transpose": Rule("대각선 접기", "왼쪽 위↘오른쪽 아래 대칭", "주대각선을 축으로 행과 열을 바꾼다.", transpose),
    "invert": Rule("부정", "전부 반전", "켜진 칸은 끄고 꺼진 칸은 켠다.", lambda m: m ^ ALL),
    "drift_right": Rule("오른쪽 순환", "모든 신호가 한 칸 이동", "칸이 오른쪽으로 한 칸 이동하고 맨 오른쪽은 왼쪽에 나타난다.", drift_right),
    "drift_down": Rule("아래쪽 순환", "모든 신호가 한 칸 이동", "칸이 아래쪽으로 한 칸 이동하고 맨 아래는 위쪽에 나타난다.", drift_down),
    "spread": Rule("십자 전염", "상하좌우로 확장", "기존 켜진 칸과 거기에 직교로 맞닿은 칸을 모두 켠다.", spread),
    "xor_cross": Rule("홀수 이웃", "상하좌우 이웃의 홀짝", "상하좌우에 켜진 이웃이 홀수 개이면 해당 칸을 켠다. 자기 자신은 세지 않는다.", xor_cross),
    "lonely_filter": Rule("고독의 제거", "혼자 켜진 칸 제거", "스스로 켜져 있으면서 상하좌우에 켜진 이웃이 하나 이상 있을 때만 살아남는다.", lonely_filter),
    "gravity": Rule("낙하", "열마다 아래로 압축", "각 세로줄에서 켜진 칸의 개수는 보존하고 모두 맨 아래로 쌓는다.", gravity),
    "parity_switch": Rule("짝수의 반란", "전체 개수에 반응", "켜진 칸의 총수가 짝수이면 전체를 반전하고, 홀수이면 그대로 둔다.", parity_switch),
    "life": Rule("미니 생명", "8방향 이웃 규칙", "8방향 이웃이 정확히 3개면 켜지고, 원래 켜졌다면 이웃 2개일 때도 유지된다.", life),
    "diagonal_pair": Rule("대각선 쌍", "대각선 이웃이 정확히 둘", "대각선 방향의 켜진 이웃이 정확히 2개면 해당 칸을 켠다.", diagonal_pair),
    "row_vote": Rule("다수결 줄", "한 행에서 둘 이상이면 승리", "각 가로줄의 켜진 칸이 2개 이상이면 그 줄 전체를 켠다.", row_vote),
}

LEVELS: tuple[dict, ...] = (
    {
        "title": "01 / 공간 감각",
        "subtitle": "세상은 정직하다. 다만 방향이 모호하다.",
        "brief": "관측실이 사진을 받아 사진을 돌려준다. 뭘 어떻게 바꾸는지만 찾아내면 된다.",
        "keys": ("identity", "mirror_lr", "mirror_ud", "spin_cw", "transpose", "invert"),
    },
    {
        "title": "02 / 인접성",
        "subtitle": "일부 전구들은 자기 옆 사람의 일에 지나치게 관심이 많다.",
        "brief": "이제 출력은 한 칸의 이동만으로 설명되지 않는다. 두 칸을 동시에 켜보는 게 유용할 수 있다.",
        "keys": ("drift_right", "drift_down", "spread", "xor_cross", "lonely_filter", "gravity"),
    },
    {
        "title": "03 / 상태의 논리",
        "subtitle": "국장은 전체를 볼 뿐, 사정을 봐주지는 않는다.",
        "brief": "작은 입력과 큰 입력이 서로 다른 효과를 낼 수 있다. 전구 하나만 고집하지 않는 편이 좋다.",
        "keys": ("parity_switch", "life", "diagonal_pair", "row_vote", "xor_cross", "gravity"),
    },
    {
        "title": "04 / 전면 재시험",
        "subtitle": "검증된 모든 법칙이 같은 공간에서 경쟁한다.",
        "brief": "16개의 가설 중 하나만 살아남아야 한다. 한 번의 실험으로 반을 지우면 훌륭하다.",
        "keys": tuple(RULES),
    },
)


def candidates(level: int) -> tuple[str, ...]:
    return LEVELS[level]["keys"]


def secret_for(level: int, seed: int) -> str:
    return Random((seed + 9127) * 109 + level * 9983).choice(candidates(level))


def apply(rule: str, mask: int) -> int:
    if rule not in RULES:
        raise KeyError(f"Unknown rule: {rule}")
    if not 0 <= mask <= ALL:
        raise ValueError("mask must contain 9 binary bits")
    return RULES[rule].func(mask)


def consistent(rules: Iterable[str], observations: Iterable[dict]) -> list[str]:
    rows = tuple(observations)
    return [key for key in rules if all(apply(key, x["input"]) == x["output"] for x in rows)]


def info_gain(rules: Iterable[str], mask: int) -> float:
    keys = tuple(rules)
    if len(keys) <= 1:
        return 0.0
    groups = Counter(apply(key, mask) for key in keys)
    n = len(keys)
    return log2(n) - sum((count / n) * log2(count) for count in groups.values())


def best_experiment(rules: Iterable[str], used: Iterable[int] = ()) -> tuple[int, float] | None:
    """Find a reproducible max-information probe (uniform prior; ties prefer 3 lit cells)."""
    keys = tuple(rules)
    if len(keys) <= 1:
        return None
    used_set = set(used)
    best: tuple[tuple[float, int, int], int, float] | None = None
    for mask in range(1, ALL):
        if mask in used_set:
            continue
        gain = info_gain(keys, mask)
        rank = (round(gain, 11), -abs(mask.bit_count() - 3), -mask)
        if best is None or rank > best[0]:
            best = (rank, mask, gain)
    if best is None or best[2] < 1e-12:
        return None
    return best[1], best[2]


def distinguishing_input(a: str, b: str, used: Iterable[int] = ()) -> int | None:
    used_set = set(used)
    choices = [m for m in range(1, ALL) if m not in used_set and apply(a, m) != apply(b, m)]
    if not choices:
        return None
    return min(choices, key=lambda m: (abs(m.bit_count() - 3), m))


def mini(mask: int) -> str:
    return " / ".join("".join("■" if lit(mask, r, c) else "·" for c in range(N)) for r in range(N))


def grade(probes: int, hints: int, mistakes: int) -> int:
    return max(0, 100 - max(0, probes - 1) * 12 - hints * 16 - mistakes * 18)
