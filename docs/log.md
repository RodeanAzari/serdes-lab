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
