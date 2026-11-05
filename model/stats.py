"""Error-rate statistics (§10): exact binomial confidence intervals and AWGN PAM4 theory."""

from __future__ import annotations

import math

from scipy.stats import beta  # type: ignore[import-untyped]

MIN_ERRORS_FOR_VALUE = 100  # CLAUDE.md: fewer errors -> report an upper bound only


def clopper_pearson(errors: int, trials: int, conf: float = 0.95) -> tuple[float, float]:
    a = 1 - conf
    lo = 0.0 if errors == 0 else float(beta.ppf(a / 2, errors, trials - errors + 1))
    hi = 1.0 if errors == trials else float(beta.ppf(1 - a / 2, errors + 1, trials - errors))
    return lo, hi


def upper_bound(errors: int, trials: int, conf: float = 0.95) -> float:
    """One-sided upper bound (for points with < MIN_ERRORS_FOR_VALUE errors)."""
    return 1.0 if errors == trials else float(beta.ppf(conf, errors + 1, trials - errors))


def pam4_ser_awgn(snr_slicer_db: float) -> float:
    """SER of PAM4 (+-1, +-3) with Gaussian error at the slicer; SNR = Es*h0^2 / var(e), Es=5."""
    x = math.sqrt(10 ** (snr_slicer_db / 10) / 5)  # half-eye / sigma
    return 1.5 * 0.5 * math.erfc(x / math.sqrt(2))  # SER = 2(M-1)/M * Q(x), M = 4


def pam4_ber_awgn(snr_slicer_db: float) -> float:
    """Gray-coded PAM4: one bit error per (adjacent-level) symbol error."""
    return pam4_ser_awgn(snr_slicer_db) / 2
