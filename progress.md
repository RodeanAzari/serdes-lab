# Progress

**Phase:** A (Python model + sizing). Started 2026-11-05.

Done:
- Repo, venv (Python 3.14.4), pinned requirements, Makefile (`make ci` green)
- Channels: TE KR Ch2 (19.3 dB) + Ch4 (31.4 dB) → pulse responses (ADR 0001)
- MMSE FFE+DFE reference; Gray PAM4; float link with real/ideal 1-tap DFE; BER stats with CIs
- Float BER waterfall (`data/results/model_ber_float.csv`): DFE error propagation 1.5× (Ch2) to 4.4× (Ch4)
- KP4 RS(544,514) model (`model/rs.py`), verified vs `galois` 0.4.11 (independent reference)
- serdespy cross-check (`make xcheck`): SDD21 + BER agree; paired runs bit-identical
- DSP sizing (ADR 0002): P = 4, FFE 16 taps, 2 instances, 125 MHz planning (~168/240 DSP est.)
- Noise generator (ADR 0003): segmented inverse-CDF, 64-bit uniform, exact tail check; HW histogram 4e13
- Fixed-point RX (ADR 0004, `docs/fixed-point.md`, `model/fixed.py`): 7-bit ADC FS 3.0×rms, coef 10 b, z 10 b; Ch4 0.60 dB at 1e-12
- Noise formats (ADR 0005, `model/noise.py`): S=4, XB=17, FG=20, 1024 segments; exact tail error 4.5e-5 to 8σ

Resolved: sampling phase stays max-cursor (phase sweep, ADR 0001).
Open: precoder definition must be verified against the 802.3 clause.

Trap: run tests with `NUMBA_NUM_THREADS=1` (Makefile does): threaded numba under shared load took 13 min.

Rule: hardware BER is compared to the bit-exact fixed-point model, never to float curves (ADR 0004).
Rule: the HW noise histogram is chi-squared vs the exact model pmf; vs the Gaussian only for |n| ≥ 4σ (ADR 0005).

Next (Phase A): precoder once the user supplies the 802.3 PDF (evidence so far: docs/log.md 2026-11-07); README draft awaits user review; then Phase A DoD (user confirms media).
Phase B noise RTL still needs: lfsr258 uniform source in the model (bit-exact), table export for BRAM init.
