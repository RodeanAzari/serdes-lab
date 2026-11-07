"""End-to-end KP4 link: payload -> RS(544,514) encode -> PAM4 (optional precoder) -> channel ->
noise -> FFE -> 1-tap DFE -> slicer -> precoder inverse -> Gray demap -> RS symbols.

Codewords are sent back to back, non-interleaved: one RS symbol = 10 bits = 5 PAM4 symbols, MSB
first, aligned to the start of the block (buildplan §6.2). Random guard symbols pad both ends so
the equalizer's edge transients fall outside the codewords.

The result is the lane error mask; statistics (model/fec_stats.py) group it into codewords. The
real decoder is run on a sample of codewords with errors as a consistency check of the whole
chain against the bounded-distance rule: <= 15 errors must decode to the sent codeword, more
must not.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from model import rs
from model.link import link_bits, link_guard

FArr = npt.NDArray[np.float64]
BArr = npt.NDArray[np.bool_]

BITS_PER_CW = rs.N * rs.M  # 5440 bits = 2720 PAM4 symbols


@dataclass(frozen=True)
class KP4Run:
    rs_err: BArr  # per lane RS symbol: received != sent
    pam4_err: BArr  # per lane PAM4 symbol (after the precoder inverse): any bit wrong
    bits: int
    bit_errors: int
    decode_checked: int  # codewords run through the real decoder
    decode_mismatches: int  # outcomes contradicting the bounded-distance rule (must be 0)


def decode_mismatches(sent: npt.NDArray[np.int64], received: npt.NDArray[np.int64]) -> int:
    """Decode received words; count outcomes that break the bounded-distance rule (<= T errors
    must decode to the sent codeword, > T must not)."""
    if len(sent) == 0:
        return 0
    dec, _ = rs.decode(received)
    ok = (dec == sent).all(axis=1)
    return int(np.count_nonzero(ok != ((received != sent).sum(axis=1) <= rs.T)))


def run_kp4(
    pulse: FArr, cursor: int, ffe: FArr, n_pre: int, dfe_b: float, h0: float, sigma: float,
    n_cw: int, seed_data: int, seed_noise: int, ideal_dfe: bool = False, precoder: bool = False,
    n_decode_check: int = 8,
) -> KP4Run:  # fmt: skip
    """n_cw codewords through the link. Payload and noise use independent generators."""
    rng_d = np.random.default_rng(seed_data)
    rng_n = np.random.default_rng(np.random.SeedSequence(seed_noise, spawn_key=(1,)))
    cw = rs.encode(rng_d.integers(0, 1 << rs.M, size=(n_cw, rs.K)))
    guard_bits = 2 * link_guard(pulse, ffe)
    pad = rng_d.integers(0, 2, size=(2, guard_bits), dtype=np.uint8)
    tx_bits = np.concatenate([pad[0], rs.symbols_to_bits(cw), pad[1]])
    tb, rb, _, _ = link_bits(tx_bits, pulse, cursor, ffe, n_pre, dfe_b, h0, sigma, rng_n,
                             ideal_dfe, precoder)  # fmt: skip
    if len(rb) != n_cw * BITS_PER_CW:  # window must be exactly the codewords (alignment)
        raise RuntimeError(f"RS alignment lost: {len(rb)} bits for {n_cw} codewords")
    rx = rs.bits_to_symbols(rb).reshape(n_cw, rs.N)
    rs_err = rx != cw
    bit_err = rb != tb

    # Real decoder on a sample: every codeword with > T errors (up to the budget) first, then
    # codewords with 1..T errors.
    n_err = rs_err.sum(axis=1)
    over, under = np.flatnonzero(n_err > rs.T), np.flatnonzero((n_err > 0) & (n_err <= rs.T))
    pick = np.concatenate([over, under])[:n_decode_check]
    mismatches = decode_mismatches(cw[pick], rx[pick])
    return KP4Run(
        rs_err=rs_err.reshape(-1), pam4_err=bit_err.reshape(-1, 2).any(axis=1),
        bits=len(tb), bit_errors=int(np.count_nonzero(bit_err)),
        decode_checked=len(pick), decode_mismatches=mismatches,
    )  # fmt: skip
