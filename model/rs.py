"""KP4 RS(544,514) over GF(2^10) (docs/buildplan.md §6.2).

Field polynomial x^10 + x^3 + 1, generator g(x) = prod_{j=0}^{29} (x - alpha^j), t = 15.
Codeword arrays are highest-degree coefficient first (index 0 = c_543, sent first): the 514
message symbols, then the 30 parity symbols (systematic).

One RS symbol = 10 bits = 5 PAM4 symbols. Bits within a symbol are MSB first; the bit order
does not change symbol-error counts, which is all the statistics depend on.

The decoder (Berlekamp-Massey, Chien, Forney) is the golden reference for `fpga-rs-core`'s
output, not RTL to be built here (§12).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

IArr = npt.NDArray[np.int64]
U8Arr = npt.NDArray[np.uint8]

M = 10
N = 544
K = 514
T = 15
NPAR = N - K  # 30
POLY = 0x409  # x^10 + x^3 + 1
Q1 = (1 << M) - 1  # 1023, multiplicative group order


def _tables() -> tuple[IArr, IArr]:
    exp = np.zeros(2 * Q1, dtype=np.int64)
    log = np.zeros(Q1 + 1, dtype=np.int64)
    x = 1
    for i in range(Q1):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & (1 << M):
            x ^= POLY
    if x != 1 or len(set(exp[:Q1].tolist())) != Q1:
        raise RuntimeError("field polynomial is not primitive")
    exp[Q1:] = exp[:Q1]
    return exp, log


EXP, LOG = _tables()


def gf_mul(a: IArr | int, b: IArr | int) -> IArr:
    """Element-wise product in GF(2^10) (broadcasts)."""
    a_ = np.asarray(a, dtype=np.int64)
    b_ = np.asarray(b, dtype=np.int64)
    p = EXP[LOG[a_] + LOG[b_]]
    return np.asarray(np.where((a_ == 0) | (b_ == 0), 0, p), dtype=np.int64)


def _mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else int(EXP[LOG[a] + LOG[b]])


def _inv(a: int) -> int:
    if a == 0:
        raise ZeroDivisionError("GF inverse of 0")
    return int(EXP[Q1 - LOG[a]])


def _generator() -> IArr:
    g = [1]  # lowest degree first
    for j in range(NPAR):
        r = int(EXP[j])
        g = [_mul(c, r) ^ (g[i - 1] if i else 0) for i, c in enumerate(g)] + [g[-1]]
    return np.array(g[::-1], dtype=np.int64)  # highest first, monic


GEN = _generator()  # 31 coefficients, GEN[0] = 1


def _check_symbols(x: IArr, n: int) -> IArr:
    a = np.asarray(x, dtype=np.int64)
    if a.shape[-1] != n:
        raise ValueError(f"last axis must be {n} symbols, got {a.shape[-1]}")
    if np.any((a < 0) | (a > Q1)):
        raise ValueError("symbols must be 10-bit (0..1023)")
    return a


def encode(msg: IArr) -> IArr:
    """Systematic encode, shape (..., 514) -> (..., 544)."""
    m = _check_symbols(msg, K)
    flat = m.reshape(-1, K)
    p = np.zeros((flat.shape[0], NPAR), dtype=np.int64)
    for i in range(K):
        fb = flat[:, i] ^ p[:, 0]
        p = np.concatenate([p[:, 1:], np.zeros((len(p), 1), np.int64)], axis=1)
        p ^= gf_mul(fb[:, None], GEN[None, 1:])
    return np.concatenate([flat, p], axis=1).reshape(*m.shape[:-1], N)


def syndromes(r: IArr) -> IArr:
    """S_j = r(alpha^j), j = 0..29, shape (..., 544) -> (..., 30)."""
    a = _check_symbols(r, N)
    flat = a.reshape(-1, N)
    roots = EXP[:NPAR]
    s = np.zeros((flat.shape[0], NPAR), dtype=np.int64)
    for i in range(N):
        s = gf_mul(s, roots[None, :]) ^ flat[:, i : i + 1]
    return s.reshape(*a.shape[:-1], NPAR)


def _poly_eval(p: list[int], x: int) -> int:
    """p lowest degree first."""
    acc = 0
    for c in reversed(p):
        acc = _mul(acc, x) ^ c
    return acc


def _berlekamp_massey(s: list[int]) -> list[int]:
    lam, b = [1], [1]
    ell, m, bd = 0, 1, 1
    for k in range(NPAR):
        d = s[k]
        for i in range(1, ell + 1):
            if i < len(lam):
                d ^= _mul(lam[i], s[k - i])
        if d == 0:
            m += 1
            continue
        coef = _mul(d, _inv(bd))
        new = lam + [0] * max(0, len(b) + m - len(lam))
        for i, c in enumerate(b):
            new[i + m] ^= _mul(coef, c)
        if 2 * ell <= k:
            b, bd, ell, m = lam, d, k + 1 - ell, 1
        else:
            m += 1
        lam = new
    while len(lam) > 1 and lam[-1] == 0:
        lam.pop()
    return lam


def _decode_one(r: IArr, s: list[int]) -> tuple[IArr, int]:
    lam = _berlekamp_massey(s)
    nerr = len(lam) - 1
    if nerr > T:
        return r, -1
    # Chien search over the 544 transmitted positions only (shortened code).
    locs = [i for i in range(N) if _poly_eval(lam, int(EXP[(Q1 - (N - 1 - i)) % Q1])) == 0]
    if len(locs) != nerr:
        return r, -1
    omega = [0] * NPAR  # S(x) * Lambda(x) mod x^30
    for i, li in enumerate(lam):
        for j in range(NPAR - i):
            omega[i + j] ^= _mul(li, s[j])
    dlam = [c if k % 2 else 0 for k, c in enumerate(lam)][1:]  # formal derivative
    out = r.copy()
    for i in locs:
        x = int(EXP[N - 1 - i])
        xinv = _inv(x)
        den = _poly_eval(dlam, xinv)
        e = _mul(x, _mul(_poly_eval(omega, xinv), _inv(den))) if den else 0
        if e == 0:
            return r, -1
        out[i] ^= e
    if syndromes(out).any():
        return r, -1
    return out, nerr


def decode(r: IArr) -> tuple[IArr, IArr]:
    """Decode received words, shape (..., 544).

    Returns (codewords, n_corrected). n_corrected is 0..15, or -1 for a detected uncorrectable
    word, which is returned unchanged. More than 15 errors can also miscorrect to another
    codeword (counted as corrected): that is real decoder behaviour, not a model bug.
    """
    a = _check_symbols(r, N)
    flat = a.reshape(-1, N)
    s = syndromes(flat)
    out = flat.copy()
    n = np.zeros(len(flat), dtype=np.int64)
    for w in np.flatnonzero(s.any(axis=1)):
        out[w], n[w] = _decode_one(flat[w], s[w].tolist())
    return out.reshape(a.shape), n.reshape(a.shape[:-1])


def symbols_to_bits(sym: IArr) -> U8Arr:
    """RS symbols -> bits, MSB first, 10 bits per symbol (= 5 PAM4 symbols)."""
    a = np.asarray(sym, dtype=np.int64)
    if np.any((a < 0) | (a > Q1)):
        raise ValueError("symbols must be 10-bit (0..1023)")
    shifts = np.arange(M - 1, -1, -1, dtype=np.int64)
    return ((a[..., None] >> shifts) & 1).reshape(-1).astype(np.uint8)


def bits_to_symbols(bits: U8Arr) -> IArr:
    """Inverse of symbols_to_bits. Length must be a multiple of 10 (RS-symbol aligned)."""
    b = np.asarray(bits, dtype=np.int64)
    if len(b) % M:
        raise ValueError("bit count must be a multiple of 10 (RS symbol alignment)")
    return np.asarray(b.reshape(-1, M) @ (1 << np.arange(M - 1, -1, -1)), dtype=np.int64)
