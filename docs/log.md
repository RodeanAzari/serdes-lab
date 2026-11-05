# Lab notebook

## 2026-11-05: Phase A start: repo, channel data, pulse responses

- Repo initialised; venv on Python 3.14.4 (3.11 not installed; 3.14 meets "3.11+").
- fpga-coord: tb-common-v0.1 MET; eth-core-v0.2, rs-core-v1.0, soc-v1.0 not released (hard gates
  for streaming, Phase D, Phase E). Phases A–C ungated.
- Downloaded 3 KR archives (MANIFEST). Chose TE/Shanbhag set: same 1 m cabled backplane at
  19.3/27.4/28.0/31.4 dB IL. No COM published for it → user chose Ch2 + Ch4 by IL, no package.
- SDD21 port map verified: computed IL 19.26 / 31.38 dB vs published 19.3 / 31.4 dB.
- CTLE/TX FIR by grid search (ADR 0001): Ch2 g_DC −11, g_DC2 −2; Ch4 −10 / −3. TX FIR ~flat.
- 99.9% energy: Ch2 2 pre + 7 post, Ch4 2 pre + 9 post UI.
- Plot: `docs/media/2026-11-05_phase-a_pulse-responses.png`.

**Bug 1.** Symptom: `test_taps_are_mse_optimal` found a perturbation with lower MSE than the
"MMSE" solution. Root cause: the symbol-offset range in `mmse_ffe_dfe`'s convolution matrix
ended at −(cursor + n_taps), but the combined response reaches −(n_taps − 1) − (L − 1); the
far ISI tail was missing from the cost. Fix: derive the range from the index bounds.

**Open:** sampling-phase rule (max main cursor vs. COM's MM phase), see ADR 0001.

## 2026-11-05 (cont.): float BER waterfall

- Added `model/pam4.py` (Gray map; precoder **withheld** until the 802.3 clause definition is
  verified, §6.1), `model/link.py`, `model/stats.py`. 14 model tests, mypy strict clean.
- 1-tap DFE with real decisions vectorised exactly: 4 speculative decisions per symbol, chain
  resolved by log-depth prefix composition (tested equal to the sequential loop).
- `make model-ber` (3 min): Ch2 BER 2.5e-2 @ 14 dB → 4.15e-6 @ 21 dB (216 errors);
  Ch4 1.2e-1 @ 14 dB → 7.57e-6 @ 25 dB (212 errors). 22/26 dB points: upper bounds only.
- Real-decision BER exceeds the Gaussian prediction. Hypothesis checked, not assumed: with the
  true previous symbol in the DFE, BER matches the prediction within ~4%, so the whole gap is
  error propagation: ~1.5× on Ch2 (b/h0 0.47), 3.5–4.4× on Ch4 (b/h0 0.72).

**Bug 2 (caught before running).** `pam4_ser_awgn` used 1.5·erfc instead of 1.5·Q =
0.75·erfc(x/√2), a factor-2 error in every prediction. Found on review; the ideal-channel test
would also have failed on it.
