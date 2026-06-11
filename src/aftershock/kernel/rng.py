"""Deterministic seed derivation and RNG construction.

All randomness in the simulation flows through rng_for. No module-level random
functions, time.time(), datetime.now(), uuid4(), or os.urandom() anywhere.
"""

from __future__ import annotations

import hashlib
import random


def derive_seed(root_seed: int, *parts: str | int) -> int:
    """Blake2b over "root/part1/part2/..." joined string, masked to 63 bits.

    Stable across runs and platforms.
    """
    joined = "/".join([str(root_seed)] + [str(p) for p in parts])
    h = hashlib.blake2b(joined.encode(), digest_size=8)
    return int.from_bytes(h.digest(), "big") & ((1 << 63) - 1)


def rng_for(root_seed: int, *parts: str | int) -> random.Random:
    """Return a seeded random.Random instance derived from root_seed and parts."""
    return random.Random(derive_seed(root_seed, *parts))
