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

## 2026-11-05 (cont.): sampling-phase sweep

- Commits: `31546f5` (model), `de166b6` (BER results re-run on clean tree, identical numbers).
- Phase sweep, 32 phases × 2 channels × 2 noise levels: max-cursor 0.18–0.25 dB below the best
  phase; MM phase 0.04–1.08 dB. User rule (≤ 0.5 dB) → **keep max-cursor**. ADR 0001 resolved.
- Noted: 0.14 dB ref-SNR offset on Ch2 between the sweep and `channels.csv`, traced to the crop
  window in the reflection tail (sidecar).

## 2026-11-06: KP4 RS(544,514) golden model

- Committed last session's work: buildplan split (`0bb6f21`), sweep script (`3dad5b8`), sweep
  results (`ffdddcb`, re-run on clean tree, byte-identical).
- `model/rs.py`: GF(2¹⁰) (x¹⁰+x³+1), systematic encoder, BM/Chien/Forney decoder that reports
  detected failures (−1), RS symbol ↔ 5 PAM4 symbols (MSB first). Golden reference for
  `fpga-rs-core`'s output only; no RTL decoder here (§12).
- Independent reference: `galois` 0.4.11 (parent RS(1023,993), c=0, shortened). Tests: generator,
  encoder, 0…15 errors, edge positions, 16/17/20/30/60 errors (success/fail and outputs agree
  with galois), miscorrection, c(α^j)=0 from the definition, alignment, bad input. 19 tests.
- Bug injection: Chien off-by-one, syndrome fcr=1, generator fcr=1, Forney missing X, encoder
  feedback tap, LSB-first bits, BM length rule: all caught (1–11 failures each). Removing any
  one failure check (deg Λ > t, Chien root count, final syndrome re-check) is not caught: they
  overlap. Removing root count + syndrome re-check together: 5 tests fail. All three kept on
  purpose: deg > t defines bounded-distance decoding (as in hardware); an undetected failure
  would silently understate CER.
- **Bug 3 (tooling).** Symptom: identical test runs took 16 s to 13 min 44 s (179 CPU-min) with
  load ~16 on 16 cores from other sessions. Root cause: galois' threaded numba kernels
  spin-wait when the CPU is oversubscribed. Fix: `NUMBA_NUM_THREADS=1` in `make model-test`;
  same load, `make ci` 16.6 s wall / 18.7 s CPU.

## 2026-11-06 (cont.): serdespy cross-check

- `make xcheck` (`scripts/serdespy_xcheck.py`, run at `0837fd4`, re-run reproduces exactly).
- **SDD21:** serdespy vs ours, IL @ 53.12 GHz 19.267 / 31.375 dB on both; max 0.05 dB residual
  traced to serdespy using S32 for S23 in its port reorder (substitution → 1.6e-16 match).
- **Statistical BER** (independent generators and equaliser engine, same pulse/taps): 8 points
  1.4e-3 … 4e-6, all |z| ≤ 1.63 with batch-means SE (DFE bursts make binomial CIs too narrow).
- **Paired BER** (identical bits + noise into serdespy's FFE/DFE/slicer/demap): identical error
  counts in 80/80 chunks. Settles the 0.67/0.82 ratios at the two lowest points as generator
  statistics, not model error.
- Not cross-checked by serdespy (it has none): CTLE, MMSE solver, SNR definition.
- Trap: serdespy `FFE_BR` uses `fftconvolve(mode="same")`, centring at tap (N−1)//2, so its
  output leads run_link's by 4 symbols (net lag −2 vs TX); an alignment search over 0…40 only
  found 25.7% matches until widened to ±40.
