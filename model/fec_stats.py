"""KP4 error statistics (docs/buildplan.md §7.2): the project's scientific output.

All inputs are error masks over the lane, so the same pattern can be grouped into codewords
in several ways (non-interleaved, 2-way interleaved) and compared on identical errors.

Post-FEC codeword error: a codeword with more than T = 15 RS-symbol errors. This is exact for
any bounded-distance decoder, including KP4's: <= T errors always decode to the sent codeword,
and with > T errors the output (a codeword within distance T of the received word, or a failure
flag) cannot be the sent one. model/kp4link.py spot-checks this with the real decoder.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from scipy.stats import binom  # type: ignore[import-untyped]

from model import rs

IArr = npt.NDArray[np.int64]
BArr = npt.NDArray[np.bool_]
FArr = npt.NDArray[np.float64]

HIST_BINS = rs.T + 2  # 0 .. 15 errors, then one "16+" bin


def errors_per_codeword(rs_err: BArr, interleave: int) -> IArr:
    """RS-symbol errors per codeword from a lane mask (one entry per RS symbol, in lane order).

    interleave = 1: consecutive blocks of 544 symbols. interleave = 2: each block of 1088 lane
    symbols carries two codewords alternating symbol by symbol (A0 B0 A1 B1 ...), so codeword
    A takes the even positions and B the odd ones (buildplan §6.2).
    """
    if interleave not in (1, 2):
        raise ValueError("interleave must be 1 or 2")
    block = rs.N * interleave
    if len(rs_err) % block:
        raise ValueError(f"lane length must be a multiple of {block} RS symbols")
    m = np.asarray(rs_err, dtype=np.int64).reshape(-1, rs.N, interleave)
    return np.asarray(m.sum(axis=1).reshape(-1), dtype=np.int64)  # (block, A/B) order


def error_histogram(counts: IArr) -> IArr:
    """Codewords with 0, 1, ..., 15 errors, and a last bin for 16 or more."""
    return np.asarray(np.bincount(np.minimum(counts, HIST_BINS - 1), minlength=HIST_BINS),
                      dtype=np.int64)  # fmt: skip


def burst_lengths(err: BArr) -> IArr:
    """Lengths of runs of consecutive True values (bursts of consecutive symbol errors)."""
    e = np.concatenate(([False], np.asarray(err, dtype=bool), [False])).astype(np.int8)
    edges = np.diff(e)
    return np.asarray(np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1), dtype=np.int64)


def independent_histogram(p_sym: float, n_cw: int) -> FArr:
    """Expected histogram if RS-symbol errors were independent with probability p_sym."""
    k = np.arange(HIST_BINS - 1)
    pmf = binom.pmf(k, rs.N, p_sym)
    return np.asarray(np.append(pmf, binom.sf(rs.T, rs.N, p_sym)) * n_cw, dtype=np.float64)


def independent_cer(p_sym: float) -> float:
    """CER if RS-symbol errors were independent: P(Binomial(544, p_sym) > 15)."""
    return float(binom.sf(rs.T, rs.N, p_sym))
