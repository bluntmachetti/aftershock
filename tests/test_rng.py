"""Tests for rng.py: seed derivation stability and distinctness."""

from aftershock.kernel.rng import derive_seed, rng_for

# These literals pin cross-platform stability — computed once on CPython 3.11+
# with blake2b(digest_size=8) and masked to 63 bits.  If these change the
# derivation algorithm has changed (a breaking determinism violation).
PINNED = [
    ((42, "tick", 0), 7676572737141894775),
    ((42, "timeline"), 2815057425107500455),
    ((0, "a", "b", 1), 3794951035743593189),
]


def test_derive_seed_stability():
    for (root, *parts), expected in PINNED:
        assert derive_seed(root, *parts) == expected, (
            f"derive_seed({root!r}, {parts!r}) changed — cross-platform stability broken"
        )


def test_derive_seed_distinctness():
    seeds = [
        derive_seed(42, "tick", 0),
        derive_seed(42, "tick", 1),
        derive_seed(42, "tick", 2),
        derive_seed(99, "tick", 0),
        derive_seed(42, "timeline"),
        derive_seed(0, "a", "b", 1),
    ]
    assert len(seeds) == len(set(seeds)), "derive_seed produced collisions"


def test_derive_seed_63_bit():
    for root, *parts in [(42, "tick", 0), (0,), (2**62, "x")]:
        s = derive_seed(root, *parts)
        assert 0 <= s < (1 << 63), f"derive_seed out of 63-bit range: {s}"


def test_rng_for_returns_seeded_random():
    r1 = rng_for(42, "tick", 0)
    r2 = rng_for(42, "tick", 0)
    # Same seed → same sequence
    assert r1.random() == r2.random()


def test_rng_for_different_parts_differ():
    r1 = rng_for(42, "tick", 0)
    r2 = rng_for(42, "tick", 1)
    assert r1.random() != r2.random()
