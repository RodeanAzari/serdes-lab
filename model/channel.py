"""802.3dj channel conversion: 4-port S-parameters -> symbol-spaced pulse response.

Chain (all in the frequency domain, then one IFFT):
    SDD21 * band-limit taper * RX filter * CTLE * 1-UI rectangle  ->  oversampled pulse
    -> pick the sampling phase that maximises the main cursor -> 1 sample/UI
    -> TX FIR applied at symbol spacing (exact, since its taps are UI-spaced)

Decisions behind every constant are in docs/decisions/0001-channel-model.md.
Deterministic, no I/O beyond reading the Touchstone file, no plotting.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FArr = npt.NDArray[np.float64]
CArr = npt.NDArray[np.complex128]

BAUD = 106.25e9  # 802.3dj 200G/lane PAM4 symbol rate
OVERSAMPLE = 32  # samples per UI before choosing the sampling phase


@dataclass(frozen=True)
class CtleParams:
    """802.3ck-form CTLE (Clause 162 / Annex 120F shape), poles/zeros scaled to BAUD."""

    g_dc: float  # dB, high-frequency peaking control
    g_dc2: float  # dB, low-frequency shelf
    f_z: float = BAUD / 2.5
    f_p1: float = BAUD / 2.5
    f_p2: float = BAUD
    f_lf: float = BAUD / 80


def sdd21_from_s4p_matrix(s: CArr) -> CArr:
    """Mixed-mode SDD21 for port map 1->2, 3->4 (diff in = (1,3), diff out = (2,4)).

    `s` has shape (n_freq, 4, 4), 0-indexed.
    """
    return 0.5 * (s[:, 1, 0] - s[:, 1, 2] - s[:, 3, 0] + s[:, 3, 2])


def load_sdd21(path: str) -> tuple[FArr, CArr]:
    import skrf as rf  # local import: keeps the rest of the model importable without skrf

    net = rf.Network(path)
    return np.asarray(net.f, dtype=np.float64), sdd21_from_s4p_matrix(net.s)


def ctle(f: FArr, p: CtleParams) -> CArr:
    jf = 1j * f
    g1 = 10 ** (p.g_dc / 20)
    g2 = 10 ** (p.g_dc2 / 20)
    hf = (g1 + jf / p.f_z) / ((1 + jf / p.f_p1) * (1 + jf / p.f_p2))
    lf = (g2 + jf / p.f_lf) / (1 + jf / p.f_lf)
    return np.asarray(hf * lf, dtype=np.complex128)


def rx_filter(f: FArr, f_r: float = 0.75 * BAUD) -> CArr:
    """4th-order Butterworth receiver noise filter (COM convention, f_r = 0.75 * baud)."""
    s = 1j * f / f_r
    # Normalised 4th-order Butterworth denominator.
    den = (s**2 + 0.7653668647 * s + 1) * (s**2 + 1.8477590650 * s + 1)
    return np.asarray(1.0 / den, dtype=np.complex128)


def band_taper(f: FArr, f_pass: float, f_stop: float) -> FArr:
    """Raised-cosine roll-off from 1 at f_pass to 0 at f_stop (avoids truncation ringing)."""
    t = np.clip((f - f_pass) / (f_stop - f_pass), 0.0, 1.0)
    return np.asarray(0.5 * (1 + np.cos(np.pi * t)), dtype=np.float64)


def oversampled_pulse(
    f: FArr, h: CArr, ctle_p: CtleParams | None, f_pass: float, f_stop: float
) -> FArr:
    """Pulse response (1-UI rectangle input) at OVERSAMPLE samples/UI.

    `h` is the channel transfer function on grid `f` (uniform, starting at 0 Hz).
    """
    df = f[1] - f[0]
    fs = OVERSAMPLE * BAUD
    n = int(round(fs / df))
    fg: FArr = np.arange(n // 2 + 1, dtype=np.float64) * (fs / n)  # one-sided irfft grid
    hr = np.interp(fg, f, h.real, right=0.0) + 1j * np.interp(fg, f, h.imag, right=0.0)
    tot = hr * band_taper(fg, f_pass, f_stop) * rx_filter(fg)
    if ctle_p is not None:
        tot = tot * ctle(fg, ctle_p)
    ui = 1.0 / BAUD
    rect = ui * np.sinc(fg * ui) * np.exp(-1j * np.pi * fg * ui)
    # irfft returns samples of the continuous response times fs (1/dt scaling).
    return np.asarray(np.fft.irfft(tot * rect, n) * fs, dtype=np.float64)


def sample_at_best_phase(pulse_os: FArr) -> tuple[FArr, int, int]:
    """Decimate to 1 sample/UI at the phase whose main cursor is largest.

    Returns (symbol-spaced pulse, cursor index in it, chosen phase in [0, OVERSAMPLE)).
    """
    peak = int(np.argmax(pulse_os))
    best_phase, best_val = 0, -np.inf
    for ph in range(OVERSAMPLE):
        # Candidate main cursors: samples within half a UI of the peak at this phase.
        idx = np.arange(ph, len(pulse_os), OVERSAMPLE)
        k = idx[np.argmin(np.abs(idx - peak))]
        if pulse_os[k] > best_val:
            best_val, best_phase = float(pulse_os[k]), ph
    sampled = pulse_os[best_phase::OVERSAMPLE]
    return np.asarray(sampled, dtype=np.float64), int(np.argmax(sampled)), best_phase


def apply_tx_fir(pulse: FArr, cursor: int, taps: FArr, tx_main: int) -> tuple[FArr, int]:
    """Convolve a UI-spaced pulse with UI-spaced TX FIR taps; returns (pulse, new cursor)."""
    out = np.convolve(pulse, taps)
    return np.asarray(out, dtype=np.float64), cursor + tx_main


def truncate_energy(pulse: FArr, cursor: int, frac: float = 0.999) -> tuple[int, int]:
    """Smallest (n_pre, n_post) window around `cursor` holding >= `frac` of pulse energy.

    Minimises n_pre + n_post; ties go to fewer pre-cursors.
    """
    e = pulse**2
    total = float(e.sum())
    csum = np.concatenate(([0.0], np.cumsum(e)))
    best: tuple[int, int] | None = None
    for n_pre in range(cursor + 1):
        lo = cursor - n_pre
        need = frac * total + csum[lo]
        hi = int(np.searchsorted(csum, need))  # window is [lo, hi)
        if hi > len(pulse):
            continue
        n_post = hi - 1 - cursor
        if n_post < 0:
            continue
        if best is None or n_pre + n_post < best[0] + best[1]:
            best = (n_pre, n_post)
    assert best is not None
    return best
