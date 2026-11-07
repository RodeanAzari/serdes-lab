"""Fixed-point receiver blocks: the bit-exact reference for the RTL (docs/fixed-point.md).

All values are int64 arrays. Integer operations only, so RTL and model agree bit for bit:
- rounding is round-half-up via add-then-arithmetic-shift (one adder in RTL)
- saturation is symmetric, to +/-(2^(bits-1) - 1), so PAM4's symmetric levels clip evenly

Signal chain (Phases B, C):
    pre-ADC word y = sum_j h[j] * a[k + cursor - j] + noise   (units: ADC LSB / 2^frac)
    ADC:  x = sat(round_shift(y, frac), adc_bits)
    FFE:  acc = sum_i c[i] * x[k + n_pre - i]                 (full precision, no rounding)
          z = sat(round_shift(acc, out_shift), out_bits)
    DFE + slicer on z with integer tap b and threshold t2 = 2*h0 (shift/add: decisions are
    +/-1, +/-3).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

IArr = npt.NDArray[np.int64]
FArr = npt.NDArray[np.float64]

PAM4_ES = 5.0  # E[a^2] for equiprobable +/-1, +/-3


@dataclass(frozen=True)
class FixedCfg:
    """Datapath widths. Defaults are the ADR 0004 choice (docs/fixed-point.md)."""

    adc_bits: int = 7
    clip: float = 3.0  # ADC full scale / noiseless received-signal rms
    frac: int = 6  # pre-ADC fractional bits below the ADC LSB
    coef_bits: int = 10
    out_bits: int = 10


@dataclass(frozen=True)
class RxRegs:
    """Register values the host computes for one channel + MMSE solution."""

    coefs: IArr  # FFE taps, coef_bits signed
    out_shift: int  # FFE accumulator -> z
    dfe_b: int  # 1-tap DFE, z units
    t2: int  # outer slicer threshold (2*h0), z units


def round_shift(x: IArr, s: int) -> IArr:
    """x / 2^s rounded half up (toward +inf at ties): (x + 2^(s-1)) >> s. s = 0 is identity."""
    if s < 0:
        raise ValueError("shift must be >= 0")
    if s == 0:
        return np.asarray(x, dtype=np.int64)
    return np.asarray((np.asarray(x, dtype=np.int64) + (1 << (s - 1))) >> s, dtype=np.int64)


def sat(x: IArr, bits: int) -> IArr:
    """Symmetric saturation to [-(2^(bits-1) - 1), 2^(bits-1) - 1]."""
    m = (1 << (bits - 1)) - 1
    return np.asarray(np.clip(x, -m, m), dtype=np.int64)


def quantize_coefs(w: FArr, bits: int) -> tuple[IArr, float]:
    """Scale so max|w| maps to 2^(bits-1) - 1, round to nearest. Returns (ints, scale)."""
    scale = ((1 << (bits - 1)) - 1) / float(np.max(np.abs(w)))
    return np.asarray(np.round(w * scale), dtype=np.int64), scale


def adc(y: IArr, frac: int, bits: int) -> IArr:
    return sat(round_shift(y, frac), bits)


def ffe_acc(x: IArr, c: IArr, n_pre: int) -> IArr:
    """Full-precision FFE accumulator, acc[k] = sum_i c[i] x[k + n_pre - i] (same as float)."""
    n = len(x)
    return np.asarray(np.convolve(x, c)[n_pre : n_pre + n], dtype=np.int64)


def slice_int(v: IArr, t2: int) -> IArr:
    """Level index 0..3 (-3, -1, +1, +3) with thresholds -t2, 0, +t2; ties go up."""
    return np.asarray((v >= -t2).astype(np.int64) + (v >= 0) + (v >= t2), dtype=np.int64)


def dfe1_int(z: IArr, b: int, t2: int, d_init: int) -> IArr:
    """1-tap DFE: d[k] = slice(z[k] - b * level(d[k-1])). Sequential reference (slow)."""
    lv = (-3, -1, 1, 3)
    out = np.empty(len(z), dtype=np.int64)
    prev = d_init
    for k, zk in enumerate(z.tolist()):
        v = zk - b * lv[prev]
        prev = (v >= -t2) + (v >= 0) + (v >= t2)
        out[k] = prev
    return out


def channel_int(pulse: FArr, cfg: FixedCfg) -> IArr:
    """Channel FIR taps in pre-ADC units, gain set so full scale = cfg.clip * signal rms."""
    fs = (1 << (cfg.adc_bits - 1)) - 1
    gain = fs / (cfg.clip * math.sqrt(PAM4_ES * float(pulse @ pulse)))
    return np.asarray(np.round(pulse * gain * (1 << cfg.frac)), dtype=np.int64)


def rx_regs(hq: IArr, cursor: int, taps: FArr, n_pre: int, cfg: FixedCfg) -> RxRegs:
    """Quantize float FFE taps and derive shift, DFE tap and threshold from the exact
    combined integer response, so the slicer scale matches what the hardware computes.

    Output shift puts the outer level 3*h0 in (1/4, 1/2] of the z full scale.
    """
    cq, _ = quantize_coefs(taps, cfg.coef_bits)
    comb = np.convolve(hq, cq) / (1 << cfg.frac)  # accumulator units
    h0 = float(comb[n_pre + cursor])
    shift = max(0, math.ceil(math.log2(3 * h0 / (1 << (cfg.out_bits - 2)))))
    b = int(round(float(comb[n_pre + cursor + 1]) / (1 << shift)))
    return RxRegs(cq, shift, b, int(round(2 * h0 / (1 << shift))))


def ffe_out(x: IArr, regs: RxRegs, n_pre: int, cfg: FixedCfg) -> IArr:
    return sat(round_shift(ffe_acc(x, regs.coefs, n_pre), regs.out_shift), cfg.out_bits)
