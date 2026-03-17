import random
from typing import List, Optional, Sequence, Tuple, TypeVar


T = TypeVar("T")


def hit_by_denominator(chance: int) -> bool:
    c = max(1, int(chance))
    return random.randint(1, c) == 1


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def choose_weighted(items: Sequence[T], weights: Sequence[float]) -> Optional[T]:
    if not items:
        return None
    if len(items) != len(weights):
        return random.choice(list(items))
    usable = [max(0.0, float(w)) for w in weights]
    if not any(usable):
        return random.choice(list(items))
    return random.choices(list(items), weights=usable, k=1)[0]


def choose_weighted_candidate(candidates: Sequence[Tuple[T, int]]) -> Optional[T]:
    if not candidates:
        return None
    valid = [(item, int(w)) for item, w in candidates if int(w) > 0]
    if not valid:
        return None
    items = [x[0] for x in valid]
    weights = [x[1] for x in valid]
    return random.choices(items, weights=weights, k=1)[0]
