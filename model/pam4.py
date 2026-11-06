"""PAM4 Gray mapping (docs/buildplan.md §6.1): 00 -> -3, 01 -> -1, 11 -> +1, 10 -> +3.

The 1/(1+D) precoder is deliberately absent until its 802.3 definition is verified (§6.1).
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


def bits_to_symbols(bits: U8Arr) -> IArr:
    """Map an even-length bit array (MSB first per pair) to PAM4 levels."""
    if len(bits) % 2:
        raise ValueError("need an even number of bits")
    pairs = bits.reshape(-1, 2).astype(np.int64)
    return np.asarray(LEVELS[_BITS_TO_IDX[pairs[:, 0] * 2 + pairs[:, 1]]], dtype=np.int64)


def symbols_to_bits(levels: IArr) -> U8Arr:
    idx = (np.asarray(levels) + 3) // 2
    v = _IDX_TO_BITS[idx]
    return np.stack([(v >> 1) & 1, v & 1], axis=1).reshape(-1).astype(np.uint8)


def slice_idx(z: npt.NDArray[np.float64], h0: float) -> IArr:
    """Level index decided by thresholds at 0 and +/-2*h0."""
    return np.asarray(np.digitize(z, [-2 * h0, 0.0, 2 * h0]), dtype=np.int64)
