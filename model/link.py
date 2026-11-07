"""Floating-point link: PAM4 -> pulse-response channel -> AWGN -> FFE -> 1-tap DFE -> slicer.

SNR definition (docs/design.md): received signal power at the ADC input divided by noise
variance, SNR = E[s^2] / sigma^2 with E[s^2] = PAM4_ES * sum(h^2) for i.i.d. equiprobable PAM4.

Payload and noise use independent generators (§5: correlated PRNGs bias BER).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from model.equalizer import PAM4_ES
from model.pam4 import LEVELS, bits_to_gray, gray_to_bits, precode, precode_inverse, slice_idx

FArr = npt.NDArray[np.float64]
IArr = npt.NDArray[np.int64]
U8Arr = npt.NDArray[np.uint8]


def noise_sigma(pulse: FArr, snr_db: float) -> float:
    return float(np.sqrt(PAM4_ES * float(pulse @ pulse) / 10 ** (snr_db / 10)))


def dfe1_decide(z: FArr, b: float, h0: float, d_init: int) -> IArr:
    """Exact 1-tap DFE decisions: d[k] = slice(z[k] - b * LEVELS[d[k-1]]).

    Builds the 4 speculative decisions per symbol, then resolves the dependency chain with a
    log-depth prefix composition of the per-symbol maps {prev index -> index}. Same result as
    the sequential loop (tested), at numpy speed.
    """
    m = np.stack([slice_idx(z - b * lv, h0) for lv in LEVELS], axis=1)  # (N, 4)
    step = 1
    while step < len(m):
        m[step:] = np.take_along_axis(m[step:], m[:-step], axis=1)
        step *= 2
    return np.asarray(m[:, d_init], dtype=np.int64)


@dataclass(frozen=True)
class LinkRun:
    bits: int
    bit_errors: int
    symbols: int
    symbol_errors: int


def link_guard(pulse: FArr, ffe: FArr) -> int:
    """Symbols dropped at each end of a block: edge transients of the channel and FFE."""
    return len(pulse) + len(ffe)


def link_bits(
    tx_bits: U8Arr, pulse: FArr, cursor: int, ffe: FArr, n_pre: int, dfe_b: float, h0: float,
    sigma: float, rng_n: np.random.Generator, ideal_dfe: bool = False, precoder: bool = False,
) -> tuple[U8Arr, U8Arr, IArr, IArr]:  # fmt: skip
    """Send tx_bits (2 per PAM4 symbol) through channel, noise, FFE and 1-tap DFE.

    Returns (tx bits, rx bits, decided transmitted-level indices, true indices), all over the
    window that drops link_guard() symbols at each end. Noise: n_sym draws from rng_n.
    precoder=True applies 1/(1+D) mod 4 at TX and its inverse after the slicer (ADR 0006); the
    DFE always works on transmitted levels. Precoder state starts at 0 (Eq. 135-1, P(-1) = 0).
    """
    n_sym = len(tx_bits) // 2
    g = bits_to_gray(tx_bits)
    sym = precode(g) if precoder else g
    a = LEVELS[sym].astype(np.float64)
    # y[k] = sum_j pulse[j] a[k + cursor - j]
    y = np.convolve(a, pulse)[cursor : cursor + n_sym]
    y = y + rng_n.normal(0.0, sigma, size=n_sym)
    # z[k] = sum_i ffe[i] y[k + n_pre - i]
    z = np.convolve(y, ffe)[n_pre : n_pre + n_sym]
    guard = link_guard(pulse, ffe)
    sl = slice(guard, n_sym - guard)
    true_idx = (a.astype(np.int64) + 3) // 2
    if ideal_dfe:
        d = slice_idx(z[sl] - dfe_b * a[guard - 1 : n_sym - guard - 1], h0)
    else:
        d = dfe1_decide(z[sl], dfe_b, h0, int(true_idx[guard - 1]))
    # RX inverse starts from the true symbol before the window, as the DFE does.
    g_rx = precode_inverse(d, int(true_idx[guard - 1])) if precoder else d
    return tx_bits[2 * guard : 2 * (n_sym - guard)], gray_to_bits(g_rx), d, true_idx[sl]


def run_link(
    pulse: FArr, cursor: int, ffe: FArr, n_pre: int, dfe_b: float, h0: float,
    snr_db: float, n_sym: int, seed_data: int, seed_noise: int, ideal_dfe: bool = False,
    precoder: bool = False,
) -> LinkRun:  # fmt: skip
    """Simulate n_sym random symbols. `ffe`/`dfe_b`/`h0` come from mmse_ffe_dfe (n_dfe <= 1).

    ideal_dfe=True feeds the DFE the true previous symbol (no error propagation): the gap
    between the two modes is the DFE error-propagation penalty. precoder: see link_bits.
    """
    rng_d = np.random.default_rng(seed_data)
    rng_n = np.random.default_rng(np.random.SeedSequence(seed_noise, spawn_key=(1,)))
    tx_bits = rng_d.integers(0, 2, size=2 * n_sym, dtype=np.uint8)
    tb, rb, d, t = link_bits(tx_bits, pulse, cursor, ffe, n_pre, dfe_b, h0,
                             noise_sigma(pulse, snr_db), rng_n, ideal_dfe, precoder)  # fmt: skip
    return LinkRun(
        bits=len(tb), bit_errors=int(np.count_nonzero(rb != tb)),
        symbols=len(d), symbol_errors=int(np.count_nonzero(d != t)),
    )  # fmt: skip
