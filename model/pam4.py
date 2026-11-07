"""PAM4 Gray mapping and 1/(1+D) mod 4 precoding, as IEEE Std 802.3-2022 (ADR 0006).

Gray symbol G (120.5.7.1): bits {A, B}, A first: {0,0} -> 0, {0,1} -> 1, {1,1} -> 2, {1,0} -> 3.
Level: symbol 0..3 -> -3, -1, +1, +3 (lowest to highest, 136.8.2). Without precoding the
transmitted symbol is G, so 00 -> -3, 01 -> -1, 11 -> +1, 10 -> +3 (buildplan §6.1).
Precoder (135.5.7.2): P(j) = (G(j) - P(j-1)) mod 4 (Eq. 135-1), transmitted as LEVELS[P];
inverse G(j) = (P(j) + P(j-1)) mod 4 (Eq. 135-3) on the RX decisions.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

IArr = npt.NDArray[np.int64]
U8Arr = npt.NDArray[np.uint8]

LEVELS = np.array([-3, -1, 1, 3], dtype=np.int64)
# Level index (0..3 = -3, -1, +1, +3) for the 2-bit value b1*2 + b0.
_BITS_TO_IDX = np.array([0, 1, 3, 2], dtype=np.int64)  # 00->0, 01->1, 10->3, 11->2
_IDX_TO_BITS = np.argsort(_BITS_TO_IDX)


def bits_to_gray(bits: U8Arr) -> IArr:
    """Gray symbols G (0..3) from an even-length bit array, first bit of each pair = A."""
    if len(bits) % 2:
        raise ValueError("need an even number of bits")
    pairs = bits.reshape(-1, 2).astype(np.int64)
    return np.asarray(_BITS_TO_IDX[pairs[:, 0] * 2 + pairs[:, 1]], dtype=np.int64)


def gray_to_bits(g: IArr) -> U8Arr:
    v = _IDX_TO_BITS[np.asarray(g)]
    return np.stack([(v >> 1) & 1, v & 1], axis=1).reshape(-1).astype(np.uint8)


def bits_to_symbols(bits: U8Arr) -> IArr:
    """Map an even-length bit array (MSB first per pair) to PAM4 levels (no precoding)."""
    return np.asarray(LEVELS[bits_to_gray(bits)], dtype=np.int64)


def symbols_to_bits(levels: IArr) -> U8Arr:
    return gray_to_bits((np.asarray(levels) + 3) // 2)


def precode(g: IArr, p_init: int = 0) -> IArr:
    """Eq. 135-1, P(j) = (G(j) - P(j-1)) mod 4, with P(-1) = p_init.

    Vectorised: Q(j) = (-1)^j P(j) obeys Q(j) = Q(j-1) + (-1)^j G(j), so Q is a cumulative sum.
    """
    alt = np.where(np.arange(len(g)) % 2 == 0, 1, -1)
    q = np.cumsum(alt * np.asarray(g, dtype=np.int64)) - p_init  # Q(-1) = -P(-1)
    return np.asarray((alt * q) % 4, dtype=np.int64)


def precode_inverse(p: IArr, p_init: int = 0) -> IArr:
    """Eq. 135-3, G(j) = (P(j) + P(j-1)) mod 4, with P(-1) = p_init."""
    p = np.asarray(p, dtype=np.int64)
    return np.asarray((p + np.concatenate(([p_init], p[:-1]))) % 4, dtype=np.int64)


def slice_idx(z: npt.NDArray[np.float64], h0: float) -> IArr:
    """Level index decided by thresholds at 0 and +/-2*h0."""
    return np.asarray(np.digitize(z, [-2 * h0, 0.0, 2 * h0]), dtype=np.int64)
