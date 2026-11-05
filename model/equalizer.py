"""Floating-point reference equalizers (MMSE FFE + ideal DFE).

These give the optimal taps the fixed-point RTL and the adaptation firmware are compared to.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FArr = npt.NDArray[np.float64]

PAM4_LEVELS = np.array([-3.0, -1.0, 1.0, 3.0])
PAM4_ES = float(np.mean(PAM4_LEVELS**2))  # = 5, symbol energy for equiprobable ±1, ±3


@dataclass(frozen=True)
class MmseResult:
    taps: FArr  # FFE taps, taps[n_pre] is the main tap
    dfe: FArr  # DFE taps on decisions d[k-1], d[k-2], ...
    snr_db: float  # signal-to-(ISI + noise) at the slicer, symbol-energy based
    h0: float  # combined main cursor after FFE


def mmse_ffe_dfe(
    pulse: FArr, cursor: int, n_taps: int, n_pre: int, n_dfe: int, noise_var: float
) -> MmseResult:
    """MMSE FFE with an ideal (correct-decision) DFE, for symbol-spaced `pulse`.

    Model: y[k] = sum_j pulse[j] a[k + cursor - j] + n[k], a i.i.d. PAM4 (variance PAM4_ES),
    n white with variance `noise_var`. The FFE output at delay 0 targets a[k]; the DFE
    subtracts the first `n_dfe` post-cursors of the combined response exactly, so those
    cursors are excluded from the MMSE cost.
    """
    if not 0 <= n_pre < n_taps:
        raise ValueError("need 0 <= n_pre < n_taps")
    L = len(pulse)
    # Convolution matrix: rows = FFE taps, cols = symbol offsets m, combined c[m] = H[:, m] . w
    # with FFE input y[k + n_pre - i] for tap i. Symbol offset m = 0 is the cursor.
    # Tap i sees y at time k + n_pre - i, which contains a[k + n_pre - i + cursor - j].
    # Symbol offset m (relative to a[k]) = n_pre - i + cursor - j, so
    # j = n_pre - i + cursor - m. m spans every (i, j) pair:
    ms = np.arange(n_pre + cursor - (n_taps - 1) - (L - 1), n_pre + cursor + 1)
    H = np.zeros((n_taps, len(ms)))
    for i in range(n_taps):
        j = n_pre - i + cursor - ms
        ok = (j >= 0) & (j < L)
        H[i, ok] = pulse[j[ok]]
    m0 = int(np.where(ms == 0)[0][0])
    dfe_cols = [m0 - d for d in range(1, n_dfe + 1)]  # post-cursors at offsets -1, -2, ...
    keep = np.ones(len(ms), dtype=bool)
    keep[dfe_cols] = False
    Hk = H[:, keep]
    # MSE(w) = Es * ||Hk^T w - e0||^2 + noise_var * ||w||^2
    R = PAM4_ES * Hk @ Hk.T + noise_var * np.eye(n_taps)
    p = PAM4_ES * H[:, m0]
    w = np.linalg.solve(R, p)
    c = H.T @ w
    h0 = float(c[m0])
    dfe = np.asarray([c[col] for col in dfe_cols], dtype=np.float64)
    isi = c.copy()
    isi[m0] = 0.0
    isi[dfe_cols] = 0.0
    err = PAM4_ES * float(isi @ isi) + noise_var * float(w @ w)
    snr = PAM4_ES * h0**2 / err
    return MmseResult(np.asarray(w, dtype=np.float64), dfe, 10 * np.log10(snr), h0)
