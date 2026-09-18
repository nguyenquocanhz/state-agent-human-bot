"""PRNG co seed + cac phan phoi dung de mo phong do tre cua nguoi that."""
from __future__ import annotations

import random


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


class Rng:
    """Bao mong quanh random.Random de seed co dinh -> test tai lap duoc."""

    def __init__(self, seed: int | str | None = None):
        self._r = random.Random(seed)

    def next(self) -> float:
        return self._r.random()

    def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        return self._r.gauss(mu, sigma)

    def log_normal(self, median: float, sigma: float = 0.5) -> float:
        """Lech phai: phan lon quanh `median`, thinh thoang co duoi dai (bi phan tam)."""
        return median * self._r.lognormvariate(0.0, sigma)

    def between(self, a: float, b: float) -> float:
        return self._r.uniform(a, b)

    def int(self, a: int, b: int) -> int:
        return self._r.randint(a, b)

    def chance(self, p: float) -> bool:
        return self._r.random() < p

    def pick(self, seq):
        return self._r.choice(seq)
