"""Bit-exact RX stream in the hardware's causal frame: the Phase C reference for the RTL.

    x      ADC samples as channel_top emits them: x[m] = model front_end(...)[m - cursor]
    FFE    z[m] = sat(round_shift(sum_{i<N} c[i] x[m - i], shift), 10)     causal: no n_pre
           = model/fixed.py ffe_out(...)[m - n_pre]; defined for m >= N - 1 (FIR history
           registers are data, not reset), so the RX stream starts at m = N - 1
    DFE    d[m] = slice(z[m] - b * level(d[m-1])), d[N-2] = d_init        (fixed.dfe1_int)
    demap  G[m] = (d[m] + d[m-1]) mod 4 with d[N-2] = p_init when precoded, else G = d

RX symbol m therefore decides TX symbol m - cursor - n_pre (the caller aligns; ADR 0008 frame).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from model import pam4
from model.fixed import FixedCfg, RxRegs, dfe1_int, round_shift, sat

IArr = npt.NDArray[np.int64]


@dataclass(frozen=True)
class RxOut:
    z: IArr  # FFE output, from m = N - 1
    idx: IArr  # DFE decisions (level index 0..3), same m
    gray: IArr  # Gray symbols after the optional precoder inverse, same m


def ffe_causal(x: IArr, regs: RxRegs, cfg: FixedCfg) -> IArr:
    """z[m] for every m, with zeros before x[0]; only m >= N - 1 is defined in hardware."""
    acc = np.convolve(np.asarray(x, dtype=np.int64), regs.coefs)[: len(x)]
    return sat(round_shift(acc, regs.out_shift), cfg.out_bits)


def rx(x: IArr, regs: RxRegs, cfg: FixedCfg, precoder: bool, d_init: int = 0,
       p_init: int = 0) -> RxOut:  # fmt: skip
    """The RX stream from m = N - 1 (the first symbol the RTL decides)."""
    z = ffe_causal(x, regs, cfg)[len(regs.coefs) - 1 :]
    idx = dfe1_int(z, regs.dfe_b, regs.t2, d_init)
    gray = pam4.precode_inverse(idx, p_init) if precoder else idx
    return RxOut(z, idx, gray)
