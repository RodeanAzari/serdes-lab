"""Bit-exact TX -> channel -> noise -> ADC stream: the Phase B reference for the RTL.

    payload  PRBS31 bits (ADR 0007), continuous across codewords
    RS       10 payload bits per message symbol, MSB first; RS(544,514) systematic encode;
             codewords back to back from reset, 1 RS symbol = 5 PAM4 symbols, MSB first
    PAM4     Gray map, optional 1/(1+D) mod 4 precoder with P(-1) = 0 at reset (ADR 0006)
    channel  s[k] = sum_j hq[j] * a[k + cursor - j]                 (integer taps, LUT FIR)
    noise    n[j] from uniform word j = lane j mod P, step j div P   (ADR 0003/0005/0007)
    pre-ADC  y[k] = sat(s[k] + n[k + cursor], 16)                    (docs/fixed-point.md)

Noise word j pairs with hardware symbol j: the RTL FIR is causal, so its output m is s[m - cursor]
and its noise lanes step with that output (ADR 0008).
    ADC      x[k] = sat(round_shift(y[k], frac), adc_bits)

Data registers are not reset (CLAUDE.md §5), so y[k] is defined only where the FIR window holds
real symbols: k in valid(), i.e. len(hq) - 1 - cursor <= k < n_sym - cursor.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from model import noise, pam4, prng, rs
from model.fixed import FixedCfg, adc, sat

IArr = npt.NDArray[np.int64]
PRE_ADC_BITS = 16


@dataclass(frozen=True)
class TxOut:
    msg: IArr  # (n_cw, K) payload RS symbols
    cw: IArr  # (n_cw, N) codewords
    gray: IArr  # (n_sym,) Gray symbols G, 0..3
    idx: IArr  # (n_sym,) transmitted level index (P if precoded, else G), 0..3
    a: IArr  # (n_sym,) levels -3, -1, +1, +3


def tx(n_cw: int, prbs_seed: int, precoder: bool) -> TxOut:
    msg = rs.bits_to_symbols(prng.prbs31(n_cw * rs.K * rs.M, prbs_seed)).reshape(n_cw, rs.K)
    cw = rs.encode(msg)
    g = pam4.bits_to_gray(rs.symbols_to_bits(cw))
    idx = pam4.precode(g, 0) if precoder else g
    return TxOut(msg, cw, g, idx, np.asarray(pam4.LEVELS[idx], dtype=np.int64))


def valid(n_sym: int, n_taps: int, cursor: int) -> slice:
    return slice(n_taps - 1 - cursor, n_sym - cursor)


def pre_adc(
    a: IArr, hq: IArr, cursor: int, seeds: Sequence[Sequence[int]], tb: noise.Tables,
    sigma_reg: int,
) -> IArr:  # fmt: skip
    """y[k] for every k (only valid() is defined in hardware). P = len(seeds) noise lanes."""
    if not 0 <= cursor < len(hq):
        raise ValueError("cursor must index hq")
    n = len(a)
    s = np.convolve(a, hq)[cursor : cursor + n]
    nz = noise.noise(prng.noise_words(n + cursor, seeds)[cursor:], tb, sigma_reg)  # ADR 0008
    return sat(s + nz, PRE_ADC_BITS)


def front_end(y: IArr, cfg: FixedCfg) -> IArr:
    return adc(y, cfg.frac, cfg.adc_bits)
