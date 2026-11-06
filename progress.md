# Progress

**Phase:** A (Python model + sizing). Started 2026-11-05.

Done:
- Repo, venv (Python 3.14.4), pinned requirements, Makefile (`make ci` green)
- Channels: TE KR Ch2 (19.3 dB) + Ch4 (31.4 dB) → pulse responses (ADR 0001)
- MMSE FFE+DFE reference; Gray PAM4; float link with real/ideal 1-tap DFE; BER stats with CIs
- Float BER waterfall (`data/results/model_ber_float.csv`): DFE error propagation 1.5× (Ch2) to 4.4× (Ch4)
- KP4 RS(544,514) model (`model/rs.py`), verified vs `galois` 0.4.11 (independent reference)

Resolved: sampling phase stays max-cursor (phase sweep, ADR 0001).
Open: precoder definition must be verified against the 802.3 clause.

Trap: run tests with `NUMBA_NUM_THREADS=1` (Makefile does): threaded numba under shared load took 13 min.

Next (Phase A): serdespy cross-check;
DSP sizing ADR (P, FFE taps, instances); fixed-point formats + ADC; precoder once verified.
