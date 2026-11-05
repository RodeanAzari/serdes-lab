"""MMSE reference equalizer tests: these taps are the yardstick for RTL and adaptation."""

import numpy as np

from model.equalizer import PAM4_ES, mmse_ffe_dfe


def test_ideal_channel_snr_equals_input_snr() -> None:
    r = mmse_ffe_dfe(np.array([1.0]), 0, n_taps=5, n_pre=2, n_dfe=0, noise_var=0.05)
    assert np.isclose(r.snr_db, 10 * np.log10(PAM4_ES / 0.05), atol=1e-6)


def test_dfe_cancels_first_postcursor_exactly() -> None:
    # 1 + 0.5D: a 1-tap DFE alone removes all ISI, so the FFE should stay a pure gain.
    r = mmse_ffe_dfe(np.array([1.0, 0.5]), 0, n_taps=4, n_pre=1, n_dfe=1, noise_var=1e-6)
    assert np.allclose(r.taps / r.taps[1], [0, 1, 0, 0], atol=1e-4)
    assert np.isclose(r.dfe[0] / r.h0, 0.5, atol=1e-4)
    assert r.snr_db > 60


def _mse(pulse: np.ndarray, w: np.ndarray, n_pre: int, n_dfe: int, nv: float) -> float:
    c = np.convolve(w, pulse)  # combined response; cursor at n_pre (pulse cursor 0)
    target = np.zeros_like(c)
    target[n_pre] = 1.0
    d = c - target
    d[n_pre + 1 : n_pre + 1 + n_dfe] = 0.0
    return PAM4_ES * float(d @ d) + nv * float(w @ w)


def test_taps_are_mse_optimal() -> None:
    # Any perturbation of the solved taps must not lower the MSE.
    rng = np.random.default_rng(7)
    pulse = np.array([1.0, 0.6, 0.3, -0.1, 0.05])
    r = mmse_ffe_dfe(pulse, 0, n_taps=8, n_pre=0, n_dfe=1, noise_var=0.02)
    base = _mse(pulse, r.taps, 0, 1, 0.02)
    for _ in range(200):
        assert _mse(pulse, r.taps + 1e-3 * rng.normal(size=8), 0, 1, 0.02) >= base - 1e-12
