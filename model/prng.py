"""Bit-exact payload PRBS and noise uniform source (ADR 0003, ADR 0007): references for the RTL.

Two independent F2-linear generators (CLAUDE.md §5: correlated PRNGs bias BER):

* Payload: PRBS31, a[n] = a[n-28] ^ a[n-31] (x^31 + x^28 + 1). Seed s (31 bits, nonzero) sets
  a[0..30] = bits 0..30 of s; the stream is a[0], a[1], ... in that order.
* Noise uniform words: L'Ecuyer's lfsr258 (combined Tausworthe, 5 components of degree
  63, 55, 52, 47, 41), one generator per lane. Like the reference C code, each step updates the
  state and then returns y1 ^ y2 ^ y3 ^ y4 ^ y5 as a 64-bit word.

Lane mapping: noise word for symbol k of an instance comes from lane k mod P at step k // P
(step 0 is the first word after reset).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

UArr = npt.NDArray[np.uint64]
BArr = npt.NDArray[np.uint8]

M64 = (1 << 64) - 1
PRBS_LEN, PRBS_TAP = 31, 28

# (k, q, s, mask) per component; mask clears the low 64 - k bits, as in the reference code.
LFSR258 = (
    (63, 1, 10, 0xFFFFFFFFFFFFFFFE),
    (55, 24, 5, 0xFFFFFFFFFFFFFE00),
    (52, 3, 29, 0xFFFFFFFFFFFFF000),
    (47, 5, 23, 0xFFFFFFFFFFFE0000),
    (41, 3, 8, 0xFFFFFFFFFF800000),
)
# Reference: seed y_i must exceed 1, 511, 4095, 131071, 8388607 (its masked bits must be nonzero).
SEED_MIN = (2, 512, 4096, 131072, 8388608)

Seed258 = tuple[int, int, int, int, int]


def prbs31(n_bits: int, seed: int) -> BArr:
    """First n_bits payload bits (0/1) from a 31-bit nonzero seed."""
    if not 0 < seed < (1 << PRBS_LEN):
        raise ValueError("PRBS31 seed must be a nonzero 31-bit value")
    if n_bits < 0:
        raise ValueError("n_bits must be >= 0")
    a = np.zeros(max(n_bits, PRBS_LEN), dtype=np.uint8)
    a[:PRBS_LEN] = (seed >> np.arange(PRBS_LEN)) & 1
    n = PRBS_LEN
    while n < len(a):  # each chunk only reads bits at least PRBS_TAP back
        m = min(PRBS_TAP, len(a) - n)
        a[n : n + m] = a[n - PRBS_TAP : n - PRBS_TAP + m] ^ a[n - PRBS_LEN : n - PRBS_LEN + m]
        n += m
    return a[:n_bits]


def check_seed258(seed: Sequence[int]) -> Seed258:
    if len(seed) != 5:
        raise ValueError("lfsr258 seed needs 5 words")
    for y, lo in zip(seed, SEED_MIN, strict=True):
        if not lo <= y <= M64:
            raise ValueError(f"lfsr258 seed word {y:#x} out of range [{lo}, 2^64)")
    return (seed[0], seed[1], seed[2], seed[3], seed[4])


def lfsr258_step(y: Seed258) -> tuple[Seed258, int]:
    """One step: (new state, output word). Pure-int form of the reference code."""
    out = []
    for yi, (k, q, s, mask) in zip(y, LFSR258, strict=True):
        b = (((yi << q) & M64) ^ yi) >> (k - s)
        out.append((((yi & mask) << s) & M64) ^ b)
    st: Seed258 = (out[0], out[1], out[2], out[3], out[4])
    return st, out[0] ^ out[1] ^ out[2] ^ out[3] ^ out[4]


def lfsr258_words(n_steps: int, seeds: Sequence[Sequence[int]]) -> UArr:
    """Output words, shape (n_steps, n_lanes): one lfsr258 per lane, all stepped together."""
    st = np.array([check_seed258(s) for s in seeds], dtype=np.uint64).T  # (5, lanes)
    out = np.empty((n_steps, st.shape[1]), dtype=np.uint64)
    par = [tuple(np.uint64(v) for v in (q, k - s, s, mask)) for k, q, s, mask in LFSR258]
    for i in range(n_steps):
        acc = np.zeros(st.shape[1], dtype=np.uint64)
        for c, (q, ks, s, mask) in enumerate(par):
            b = ((st[c] << q) ^ st[c]) >> ks
            st[c] = ((st[c] & mask) << s) ^ b
            acc ^= st[c]
        out[i] = acc
    return out


def noise_words(n_sym: int, seeds: Sequence[Sequence[int]]) -> UArr:
    """Uniform word per symbol, symbol k from lane k mod P at step k // P (P = len(seeds))."""
    p = len(seeds)
    return lfsr258_words(-(-n_sym // p), seeds).reshape(-1)[:n_sym]


def _splitmix64(x: int) -> tuple[int, int]:
    x = (x + 0x9E3779B97F4A7C15) & M64
    z = x
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M64
    return x, z ^ (z >> 31)


def lane_seeds(seed: int, n_lanes: int) -> list[Seed258]:
    """Distinct valid lfsr258 seeds per lane from one integer (SplitMix64; host-side only, the
    RTL receives the 5 words per lane). Bit 63 is forced so every word meets SEED_MIN."""
    x, out = seed & M64, []
    for _ in range(n_lanes):
        words = []
        for _ in range(5):
            x, z = _splitmix64(x)
            words.append(z | (1 << 63))
        out.append(check_seed258(words))
    if len(set(out)) != n_lanes:
        raise ValueError("lane seeds collide")
    return out
