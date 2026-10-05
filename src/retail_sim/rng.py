from __future__ import annotations

import random


def make_rng(seed: int, *keys: object) -> random.Random:
    material = ":".join(str(key) for key in keys)
    if material:
        return random.Random(f"{seed}:{material}")
    return random.Random(str(seed))
