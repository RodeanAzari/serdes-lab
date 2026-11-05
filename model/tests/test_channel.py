"""Channel-conversion tests. Each guards a known way the channel can silently go wrong (§14)."""

import numpy as np

from model.channel import (
    BAUD,
    OVERSAMPLE,
    CtleParams,
    ctle,
    oversampled_pulse,
    sample_at_best_phase,
    sdd21_from_s4p_matrix,
    truncate_energy,
)


def _s4p(through: complex, cm_through: complex) -> np.ndarray:
    """4-port with port map 1->2, 3->4, built from pure differential/common-mode gains."""
    s = np.zeros((1, 4, 4), dtype=complex)
    # Single-ended from mixed-mode: S21 = S43 = (dd + cc)/2, S23 = S41 = (cc - dd)/2
    s[0, 1, 0] = s[0, 3, 2] = (through + cm_through) / 2
    s[0, 1, 2] = s[0, 3, 0] = (cm_through - through) / 2
    return s


def test_sdd21_extracts_differential_and_rejects_common_mode() -> None:
    # A wrong port map would mix common-mode into the channel and change its loss.
    assert np.isclose(sdd21_from_s4p_matrix(_s4p(0.7, 0.0))[0], 0.7)
    assert np.isclose(sdd21_from_s4p_matrix(_s4p(0.0, 0.9))[0], 0.0)


def _flat_channel() -> tuple[np.ndarray, np.ndarray]:
    f = np.arange(0, 80e9 + 1, 10e6)
    return f, np.full(f.shape, 0.5 + 0j)


def test_pulse_scaling_preserves_dc_gain() -> None:
    # Sum of UI-spaced pulse samples equals the DC gain (Poisson summation). Catches a
    # wrong IFFT scale, which would make every SNR in the project off by a constant.
    f, h = _flat_channel()
    p = oversampled_pulse(f, h, None, 67e9, 80e9)
    for ph in (0, OVERSAMPLE // 3):
        assert np.isclose(p[ph::OVERSAMPLE].sum(), 0.5, rtol=1e-3)


def test_sampling_phase_maximises_main_cursor() -> None:
    # §14: the wrong sampling phase makes the channel look easier or harder than it is.
    f, h = _flat_channel()
    h = h * np.exp(-2j * np.pi * f * 37.3e-12)  # non-integer-UI delay
    p = oversampled_pulse(f, h, None, 67e9, 80e9)
    sampled, cur, _ = sample_at_best_phase(p)
    for ph in range(OVERSAMPLE):
        assert p[ph::OVERSAMPLE].max() <= sampled[cur] + 1e-12


def test_ctle_dc_and_peaking() -> None:
    f = np.array([0.0, BAUD / 2])
    h = ctle(f, CtleParams(g_dc=-10, g_dc2=-3))
    assert np.isclose(20 * np.log10(abs(h[0])), -13.0, atol=1e-9)  # both shelves at DC
    assert abs(h[1]) > abs(h[0])  # peaking toward Nyquist


def test_truncate_energy_is_minimal_window() -> None:
    rng = np.random.default_rng(1)
    for _ in range(20):
        p = rng.normal(size=40) * np.exp(-np.abs(np.arange(40) - 10) / 4)
        p[10] = 5.0
        n_pre, n_post = truncate_energy(p, 10, 0.99)
        e = p**2
        assert e[10 - n_pre : 11 + n_post].sum() >= 0.99 * e.sum()
        # No strictly shorter window around the cursor reaches the target.
        for a in range(11):
            for b in range(30):
                if a + b < n_pre + n_post:
                    assert e[10 - a : 11 + b].sum() < 0.99 * e.sum()
