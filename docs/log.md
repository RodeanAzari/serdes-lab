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

## 2026-11-06 (cont.): DSP sizing (ADR 0002)

- `scripts/ffe_sizing.py` → `ffe_sizing.csv`: FFE saturates at ~12 taps; N = 16 ≤ 0.01 dB from
  N = 32 on both channels; N = 12 costs 0.12 dB on Ch4, N = 8 0.46 / 0.77 dB.
- User chose **P = 4, N = 16, 2 instances, 125 MHz planning clock**: ~168/240 DSP (estimate;
  noise ~3 DSP/sample and MLSE 2/symbol are guesses). P = 4 lets one `fpga-rs-core` decoder
  (1 RS symbol = 5 PAM4/clock) keep up per instance.

## 2026-11-06 (cont.): noise generator (ADR 0003)

- Tail depth needed: BER 1e-12 = 7.0σ, 1e-15 = 7.9σ at the slicer → target reach ≥ 8σ.
  Reach vs uniform bits: inverse-CDF 64-bit 9.08σ; Box–Muller 48-bit 8.16σ.
- Found: the §6.4 minimum (10¹² samples to ±7σ) can only verify to ~6.5σ (2.6 expected values
  beyond 7σ). 4×10¹³ samples (~11 h at 10⁹/s) gives ~100.
- User chose **segmented inverse-CDF** (exact tail check from the tables, no sampling needed)
  and the **overnight 4×10¹³** hardware histogram. All 8 lanes must feed it (one lane: ~89 h).

## 2026-11-06 (cont.): fixed-point formats (ADR 0004)

- `model/fixed.py`: bit-exact integer RX (ADC, FFE, DFE, slicer, register derivation);
  `scripts/fixed_point_sweep.py` → `fixed_point_sweep.csv`, `fixed_point_ber.csv` (at `72fd78d`).
- Metric: paired slicer-SNR penalty vs float on the same quantized channel and samples, at the
  2.4e-4 **and** 1e-12 points. Quantization noise is fixed, so the low-BER point sizes the datapath.
- User chose **7-bit ADC, FS = 3.0 × rms** (no ISI clipping: peaks 2.06 / 2.89 × rms). Ch4 0.17 dB
  at 2.4e-4, 0.60 dB at 1e-12; 6 bits ≥ 1.46 dB. Coef 10 b, z 10 b, pre-ADC frac 6: ≤ 0.04 dB each.
- Real-DFE paired BER: Ch4 fixed/float 1.22× → 1.81× from the operating point to +2 dB.
- Found: frac < 3 makes double round-half-up add a DC bias (frac = 1 worst). At 1e-12 Ch4 σ is
  0.77 ADC LSB, so 1e-12 penalties are MSE estimates until hardware (Phase C).
- Tests: 7 injected bugs (truncation, asymmetric clip, DFE tap index, FFE off-by-one, slicer ties,
  output shift, dropped DFE feedback) each caught; `make ci` green (43 tests).

## 2026-11-07: noise generator formats (ADR 0005)

- `model/noise.py`: bit-exact segmented inverse-CDF generator; `pmf_g` enumerates all 2⁶³ inputs
  by group, so every accuracy number is exact. `scripts/noise_tables.py` → `noise_sweep.csv`
  (S 2…5, XB 12/17, FG 18/20).
- User chose **S = 4, XB = 17, FG = 20**: 1024 segments, 8 BRAM36 total, 3 DSP/sample. Tail error
  4.5e-5 to 8σ (target 1%), max |g error| 2.4e-6σ, reach 9.155σ.
- Found: the tail error floor (~5e-5) is the 63-bit input itself (~10⁴ inputs beyond 8σ), the same for every table size.
- Found: a 4e13-sample histogram chi-square vs the ideal Gaussian would fail with bug-free RTL
  (λ ≈ 4e4 on 354 dof at σ = 49.4) for every config within the DSP budget. User chose: hardware
  histogram vs the exact model pmf, plus a Gaussian chi-square on |n| ≥ 4σ only (λ = 3.9 / 157 dof).
  Buildplan §6.4 and ADR 0003 step 3 updated.
- Verified: pre-ADC 16 b headroom holds to SNR −7.41 dB (Ch4) with 9.155σ noise.
- Tests: 12 injected bugs each caught (one more injection exposed a dead line, removed; one exposed an
  upper-bound-only chi-square test, fixed with a known-perturbation test). `make ci` green.

## 2026-11-07 (cont.): precoder sources, serdespy overlay plot

- Precoder: normative 802.3 text not available publicly (IEEE GET needs the user's account; user
  will fetch it). Evidence found: 1/(1+D) ⇒ P(j) = (G(j) − P(j−1)) mod 4, RX (P(j) + P(j−1)) mod 4;
  the Broadcom worked example (parthasarathy_01_0911, a proposal) matches the minus sign at every
  step and breaks for plus at symbol 7; 802.3cd D1.1 comment responses cite "Equation (135-1)",
  Gray-coded {A,B} input, state initialized to 0 per training pattern. Not implemented until the
  clause is read (CLAUDE.md rule).
- `analysis/plot_xcheck.py` (in `make plots`) → `docs/media/2026-11-07_phase-a_serdespy-overlay.png`
  from `serdespy_ber.csv`. The palette validator could not run (no node); identity is also carried
  by marker shape and the legend.
- Open for Phase A DoD: precoder, README (none exists yet), user confirmation of media.
- README.md drafted (Phase A scope, §13.4 order; every number linked to its CSV, unmeasured = [TBD]); awaits user review.

## 2026-11-07 (cont.): precoder (ADR 0006), GitHub repo

- User supplied IEEE Std 802.3-2022 (`data/raw/`, gitignored). Read 120.5.7.1–2 (pp. 4886–7) and
  135.5.7.1–2 (p. 5283): P(j) = (G(j) – P(j-1)) mod 4 (135–1), G(j) = (P(j) + P(j-1)) mod 4 (135–3),
  on Gray symbols. Levels 0..3 lowest→highest (136.8.2), initial state 0 for training patterns
  only (136.8.11.1.3). Matches the earlier non-normative evidence.
- `model/pam4.py`: `bits_to_gray`, `gray_to_bits`, `precode` (cumulative-sum form),
  `precode_inverse`; `run_link(precoder=True)`. 5 tests; 6 injected bugs caught.
- **Test bug.** Symptom: precoded ideal-channel BER test failed (2× theory just above the CI).
  Root cause: the test applied a binomial CI to errors that come in adjacent pairs (√2 too narrow).
  Fix: CI on pair count vs the Gray BER. Precoder itself correct: 14,092 bit errors from 7,055 slicer errors.
- Injection exposed a gap: ignoring the RX initial state passed with one seed (1/4 chance). Fixed: 8 seeds.
- GitHub: created private `RodeanAzari/serdes-lab`, pushed main (history checked: no blob > 500 kB,
  no credentials; IEEE PDF and raw archives gitignored). No CI workflow exists yet.
- User: keep CLAUDE.md and progress.md local → untracked + gitignored (they remain in commits before
  this change; the repo is private). Makefile stub message now points to docs/buildplan.md.
- CI: `.github/workflows/ci.yml` (Python 3.14, `make setup` + `make ci`). Verified first from a fresh
  local clone (63 passed), then on GitHub: run 42408134930, all steps success.
- README: shared-blocks table linking tb-common, fpga-eth-core, riscv-rv32i-tmr-core with tags
  (user request; PROTOCOL §3). Filed request 0003 to P2 for tb-common's "Used by" list.

## 2026-11-07 (cont.): end-to-end KP4 model + statistics (Phase A DoD)

- User decision: Phase A closes with the KP4 link + statistics modelled; MLSE model → Phase F,
  bit-exact PRBS/lfsr258 → Phase B (buildplan amended).
- `model/kp4link.py` + `model/fec_stats.py`; `link.run_link` split (bit-identical outputs on 5
  configs). CER = P(> 15 errors): exact for bounded-distance decoding, so the slow Python decoder
  (~170 ms/codeword) only spot-checks it (≥ 80 per row, 0 contradictions).
- `make model-kp4` → `kp4_model.csv` (at `4fa99da`): null case holds (ideal DFE: variance/binomial
  0.98–1.03, CER = prediction). Real DFE, Ch4 21 dB: CER 9.72% vs 4.63% predicted (2.1×, 972
  errors); 2-way interleave 1.22×. Precoder: BER and bursts down (mean 3.4 → 1.08), CER up
  (9.7% → 12.9%): RS-symbol error rate rises. Counter-intuitive; check on hardware at low BER.
- Plot `docs/media/2026-11-07_phase-a_kp4-errors-per-codeword.png` (`make plots`), inspected.
- Tests: 8 new; 9 injected bugs caught. A decode check at "< t" survived until a direct
  t = 15/16 boundary test was added.
- User confirmed the KP4 errors-per-codeword plot. **Phase A done**; tagged `v0.1-model`.

## 2026-11-08: Phase B model first (PRBS31, lfsr258, TX stream)

- `model/prng.py` (ADR 0007, accepted: PRBS31 payload, user took the recommendation): PRBS31
  x³¹+x²⁸+1; L'Ecuyer lfsr258 per noise lane, word k from lane k mod P; host-side lane seeds.
- lfsr258 bit-exact vs the reference C (`scripts/lfsr258_ref.sh`, source SHA-256 pinned,
  vectors in `model/tests/data/`). Also checked: Tausworthe sequence model, galois primitivity
  and Berlekamp–Massey (linear complexity 258), lag/lane/payload correlation.
- **Lesson:** a wrong constant in the shared lfsr258 table passed every test except the
  reference vectors (the "independent" model read the same table). Reference vectors catch 3/3.
- `model/tx.py`: the stream the Phase B RTL must match (PRBS → RS → Gray/precoder → integer
  FIR → noise → sat 16 → ADC). Precoder state from reset only; outputs defined once the FIR
  window is full (data registers not reset). 10/10 injected bugs caught.
- Test bug: a precoder-reset test passed by chance when the boundary state was 0 (1 in 4);
  now requires a nonzero-state boundary.
- `make ci`: 102 passed. Commits efb26d7, b3696d3, 7294be5.

## 2026-11-08 (cont.): Phase B RTL: PRNGs and TX path

- RTL, all bit-exact vs `model/` in cocotb (Verilator): `prbs31_par`, `lfsr258` (050ee3d);
  `rs_enc`, `gearbox`, `pam4_map`, `tx_top` at P = 4 and 2, precoder on/off (77dfb62).
- `make sim` added to `make ci`; lint runs each file as its own top. Hosted CI now installs
  OSS CAD Suite 2026-10-24 (Verilator 5.053-devel; cocotb needs ≥ 5.036, apt has 5.020).
  Runs 42513121720 and 42516056274: success, 14 cocotb runs on GitHub.
- Injected bugs: PRNG RTL 9/9; rs_enc 9/9 (+1 equivalent: `M'(PRIM_POLY)` already truncates);
  TX 11/11 after a fix to the gearbox test.
- **Lesson (gearbox):** a buffer 1 bit too small passed every even width pair (bit counts stay
  even, so the deadlock state is unreachable) and, at odd widths, *hung* the test instead of
  failing it. Added 10→7 and 9→8, a no-underrun check at full input rate, and a cycle bound.
- Test bug: SVA fired at t = 0 because the TB applied reset after the first edge (RTL fine).
- Trap: `pkill -f <pattern>` matched the invoking shell and killed it mid-command.

## 2026-11-08 (cont.): Phase B RTL: channel FIR

- `rtl/channel/channel_fir.sv` (58fce61): causal s[m] = Σ hq[j]·a[m−j], P symbols/clock, L = 16
  taps default (Ch2 needs 10, Ch4 12). Each term is a 4:1 mux of {−3h, −h, h, 3h}, 3h = (h<<1)+h;
  full-precision 17 b sums; latency 3 (products | groups of 4 | group tree). No cursor in RTL:
  hardware output m = model s[m − cursor]; alignment is the channel top's job.
- Bit-exact vs np.convolve (the model's channel) at 6 (P, L) sets incl. L < P and L = 1; real
  Ch2/Ch4 taps run where L ≥ 12. 10/10 injected bugs caught (incl. lane order, missing sign
  extension, valid-ignoring history, a dropped tap).
- Yosys `synth_xilinx` estimate (P=4, L=16): ~1.8k LUT, 1.5k FF, 0 DSP. **Vivado is not
  installed on this machine**: no timing yet. The explicit 2-levels-per-stage trees are the
  conservative guess; check in Vivado before tagging.
- `make ci` green (lint 7 modules, 20 cocotb runs, 102 pytest).
- **Correction:** Vivado *is* installed (2025.2 at `~/Xilinx/2025.2`, loaded by the opt-in
  `vivado-env`; I had only searched /opt and /mnt/c). The FIR commit message (58fce61) wrongly says
  "not installed". New: `scripts/vivado.sh` (Vivado env confined to one process, mirrors
  `vivado-env`), `syn/synth_ooc.tcl`, `make synth-ooc TOP=… [PERIOD=8] [GEN="P=4 L=16"]`.
- channel_fir P=4 L=16, OOC post-route at 8 ns on xc7a100tcsg324-1: **WNS +2.851 ns, WHS
  +0.132 ns**; 1,984 LUT, 1,557 FF, 0 DSP, 0 BRAM, 0 latches, 0 critical warnings (only the
  OOC partition-pin warnings). Pipeline kept as is.

## 2026-11-09: Phase B RTL: Gaussian noise generator

- `noise_lane` / `noise_rom` / `noise_gen` (9519432): ADR 0005 formats exactly. Normalize in 3
  stages (2 shift steps each), ROM latency 2, 3 DSP48E1 per lane, latency 13. Each rounding
  (`rs`) and coefficient add is one DSP post-add: c1 + rs(x·c2, 17) = (x·c2 + {c1, 1, 0¹⁶}) >>> 17
  exactly, so the C port carries both.
- Tables: `rtl/channel/noise_tables.mem` (`scripts/export_noise_tables.py`, committed); a pytest
  decodes it independently and requires equality with `build_tables()`.
- cocotb, P = 4, 3, 1: bit-exact vs `noise.noise()` on every reachable segment on every lane
  (random, zero and all-one x), u = 0, σ_reg ∈ {1581, 0, 1, 2¹⁶, 2¹⁷−1}; ≥ 200 directed
  rounding ties per lane at σ = 2¹⁶ (random words give only ~1/512 ties), saturation at max σ,
  valid gaps, mid-stream reset.
- Bug injection 13/14. The miss (`max(0)` clamp removed) is an equivalent mutant: the pre-clamp
  minimum over all 2⁶³ inputs is exactly 0. Clamp kept to mirror the model.
- **Test bug:** my first SVA claimed g < 2²³ (it checked bit 46 = g's bit 23 = 8σ); g reaches
  9.155σ legitimately. Removed; the t-truncation assertion (40 → 23 b) stays.
- Vivado OOC, P = 4 @ 8 ns post-route: **WNS +3.668 ns, WHS +0.058 ns**; 600 LUT, 837 FF,
  **12 DSP, 4 BRAM36** (= ADR 0002/0005 budget), 0 latches, 0 critical warnings. All three
  multiplies in DSP with MREG/PREG and the C-port add.
- Trap: background bug-injection scripts edit RTL in place; don't edit those files meanwhile.
- `make ci` green (lint 10 modules, 23 cocotb runs, 103 pytest).

## 2026-11-09 (cont.): Phase B RTL: channel top

- **ADR 0008** (6122345): noise word j is added to hardware symbol j, i.e. model
  y[k] = sat(s[k] + n[k + cursor], 16). The causal RTL FIR outputs s[m − cursor]; keeping the
  old pairing would need a runtime P-lane rotation by cursor mod P. Statistics unchanged.
  Two `test_tx` pairing tests updated deliberately (spec change, not a loosened check).
- `channel_top` (83d4161): tx_top → channel_fir (+11-clock delay) ‖ lfsr258 × P → noise_gen →
  y = sat(s + n, 16) → x = sat(rs(y, 6), 7); latency 16.
- cocotb P = 4, 2: x_o and internal y bit-exact vs `tx → pre_adc → front_end` on Ch4/Ch2 at the
  1e-12 σ, precoder off/on, σ = 0, and full-scale taps at max σ. y must be checked directly:
  the 7 b ADC clip hides a missing 16 b saturation. |s + n| > 2¹⁵ is a ~3.3σ event even at
  full-scale taps, so that case runs 40 codewords (25–46 saturations per rail seen).
- Bug injection 12/12 caught.
- Vivado OOC P = 4 @ 8 ns post-route: **WNS +1.533 ns**, WHS +0.097 ns; 4243 LUT, 4194 FF,
  12 DSP, 4 BRAM36, 0 latches, 0 critical warnings. Critical path: channel_fir history fanout
  (1 LUT, 5.8 ns route); standalone the FIR had +2.85 ns. First fix if slack runs out:
  duplicate the history registers / max_fanout.
- `make ci` green (lint 11 modules, 25 cocotb runs, 103 pytest).

## 2026-11-10: Phase B: hardware noise histogram RTL (ADR 0009)

- `hist_bram` (5eba067): clamp ±512 → 1024 × 48 b saturating counters, BRAM RMW with
  distance-1/2 same-bin forwarding. Registered forward selects + carry-out saturation took OOC
  WNS from −1.636 to **+0.921 ns** @ 8 ns; 214 LUT, 3 BRAM tiles per lane.
- `noise_hist_core` (802d275): noise_ctrl (UDP protocol, docs/registers.md) + 8 lfsr258 +
  2 noise_gen P = 4 + 8 hist_bram. cocotb: histograms bin-for-bin equal to the model (unbroken,
  pause/resume ×3, max σ with clamping), every error code, truncated datagram dropped.
- Bug injection: hist_bram 9/9; ctrl + core 20/22. Both misses are equivalent mutants:
  READ-while-running (implied by !drained) and the drain gate (the first READ `rd_en` follows
  28 reply header bytes, the pipeline drains in 17). Gate kept as a guard and for
  STATUS.drained; documented in the RTL. Added `test_read_waits_for_drain` anyway (σ_reg = 1,
  no handshake gaps, READ polled from START) to check the end-to-end property.
- **Test bug:** the "truncated not dropped" mutant hung `Port.send()` (no clock bound) for
  2 h 22 min of CPU instead of failing. `send()` now fails on a stalled command; mutant caught.
- `noise_hist_top` (2b74228, 0aee872) on fpga-eth-core `eth-core-v0.2` (submodule `rtl/eth`).
  `make lint` now includes the eth-core RTL and its Xilinx stand-in models (15 tops clean).
  MAC set to 02:00:0A:0B:0C:0D = the host's existing static neighbour for 192.168.10.2
  (eth-core has no ARP).
- Model: chi-square GOF / sign symmetry for the hardware histogram (8cfe245). Host script
  `scripts/noise_hist_run.py` (status / exact / run). `make prog` (JTAG via Vivado).
- Request 0011 to P2 (eth-core "Used by"): done by P2 the same day.
- `make ci` green (lint 15 tops, 28 cocotb runs, 110 pytest).
- First board build failed timing (WNS −1.533 ns): CONFIG's 331-byte seed check → apply_cfg →
  64 b add/compare → run gate, all in one clock. Fixed (3a1f17e) with S_CHK (registered CONFIG
  check) and a down-counter for the stop test. Mutants on the new logic 4/4.
- `make impl` (build_id 3a1f17ee): **WNS +0.241 ns, WHS +0.012 ns** @ 125 MHz; 7705 LUT,
  11682 FF, 35 BRAM tiles, 24 DSP; 0 critical warnings, 0 latches. Methodology SYNTH-16 (16
  address collisions) = hist_bram's same-address read/write, overridden by the distance-2
  forward; CDC-6 = eth-core Gray pointers (constrained). Reports: syn/build/noise_hist_top/.
- **Board, first exactness check (3a1f17ee): FAIL**, 4 of 8192 bins
  ([csv](../data/results/noise_hist_exact_3a1f17ee_fail.csv)). Each lane could lose only its
  run's last sample, in about half the runs. Repeated READs of one finished histogram flipped
  that bin between old and new, so the memory was right and the readback was not. Netlist:
  Vivado mapped `if (clr) mem[..] <= 0; else if (v3) mem[a3] <= new` to port A with
  WEA = ENA = 1 and an idle write-back of port A's read data. After a run a1..a3 hold the last
  bin (noise_gen holds its output), so port A rewrote it every clock, colliding with readout
  reads. Verilator's ideal RAM cannot show this. Fix 82d89d0: a single explicit write enable
  (now on ENARDEN), plus a build_board.tcl check that fails if a hist RAM's enable is tied
  high. Side effect: 1 RAMB36 + 1 RAMB18 per lane (was 2 + 2).
- Rebuild 82d89d09: **WNS +0.069 ns, WHS +0.015 ns**; 7696 LUT, 11643 FF, 23 BRAM tiles,
  24 DSP; 0 critical warnings; SYNTH-16 gone. On the board: 4 back-to-back reads identical,
  8 same-seed runs exact, and **`exact` PASS for 2 seeds: 0 of 8192 bins differ**
  ([csv](../data/results/noise_hist_exact.csv),
  [csv](../data/results/noise_hist_exact_seed7340033.csv)). Slack is thin (+0.069 ns); if a
  later change breaks it, first look at the hist clr → CONFIG accept → σ register path.
- Host network: the USB NIC had no carrier; a replug made Windows take it (mirrored as eth2,
  link-local). Re-attached with usbipd and the static IP/neighbour restored by the user.
- Long run started 13:29 (5 × 10¹² words/lane = 4 × 10¹³ samples, ~11.1 h, hourly
  checkpoints to `data/results/noise_hist_hw.csv`). Board claimed by P4 until it ends.

## 2026-11-11: Phase B noise result (partial run accepted); Phase C RX + BER checker

- Long noise run: the host process died at 19:57 on 2026-11-10 when WSL lost the board's USB
  NIC (likely host sleep); last checkpoint 7.2 × 10¹² samples (18%). User accepted it as final.
  27/27 tests pass; 19 samples beyond 7σ vs 19.4 expected (95% CI 11.4–29.7). ADR 0003 outcome
  note; plot `docs/media/2026-11-11_phase-b_noise-histogram.png`. Lesson: disable host sleep for
  overnight runs. A `.gitignore` trailing comment had silently disabled a pattern (git has no
  inline comments).
- `dfe_slicer` (ADR 0010): OOC WNS +2.834 ns @ 8 ns, critical path = the 4-LUT speculative loop
  as predicted. An equivalent mutant showed the 13 b DFE width was 1 bit over: exact is 12 b.
- `ber_check` (ADR 0011): reference = FIFO of TX bits counted in symbols, not a clock delay.
- `link_core`: TX → channel → noise → ADC → FFE → DFE → demap → BER counters. Error counts equal
  the bit-exact model exactly (hundreds of errors per run, Ch4 and Ch2, precoder off/on, P 4/2).
  RX starts at m0 = 32 at P = 4 (both the FIR and FFE windows full, word-aligned).
- Mutation: 16/16 (dfe_slicer, demap), 13/13 (ber_check), 4/4 (link wiring).
- Next: board top for the BER campaign (run control, counter readout over UDP), full-design
  synthesis (DSP count, timing), then hardware BER vs model at 1e-3…1e-6.

## 2026-11-11 (afternoon): BER board, first hardware BER curves = model

- **ADR 0012 / `link_ctrl`, `ber_core`, `ber_top`** (5ed0b03): UDP control of `link_core` on
  port 26401 (docs/registers.md). Link held in reset when idle; run length R in bits with an
  exact stop (snapshot counters copied on one edge, frozen when live bits == R). CONFIG
  (249 B) validates every field before applying it. `link_core`/`ber_check` unchanged.
- Sim (`test_ber_core`, P 4 and 2): counts == model over exactly R bits; every mid-run STATUS ==
  model over its own bit count (40–84 per run); STOP/repeat; every CONFIG check at its limit;
  the host script's CONFIG packing + model reference vs RTL. Bug injection 15/15 (the first
  pass missed "PRBS seed bit 31 unchecked": the test's 1 << 31 case was also caught by the
  nonzero check; added (1 << 31) | 1).
- ber_core first sim: PRBS a_nonzero fired at t = 0 because link_ctrl's reset register is 0
  until rst_i's first edge (same at power-up on hardware). Link reset = rst_i || link_rst.
- **Test bug found by a random seed:** `test_link_core` noiseless, P = 2, Ch4 precoded,
  SEED=3946702219: 1 error after a 2-word holdoff. The model gives the same count: a wrong
  d_init makes a 10-symbol DFE burst with no noise; the precoder inverse leaves one Gray error
  at its end. Holdoff 16 words in the test, 64 on the board; ADR 0011 note (was "≤ 4 symbols").
- `make impl TOP=ber_top` (5ed0b033): **WNS +0.360 ns, WHS +0.028 ns** @ 125 MHz; 8155 LUT,
  10575 FF, 7 BRAM tiles, 76 DSP (FFE 64, checked by build_board.tcl; noise 12); 0 critical
  warnings, 0 latches. link_ctrl 2129 LUT / 3772 FF (mostly the CONFIG shift register).
  Reports: docs/reports/ber_top-5ed0b033/.
- Board: static neighbour for 192.168.10.2 was gone (INCOMPLETE); user restored it with sudo.
- **`exact` PASS on both channels**: Ch4 21 dB 5149 = 5149 bit errors over 1,087,424 bits;
  Ch2 precoded 17 dB 4002 = 4002.
- **Sweeps, 10¹⁰ bits per point, 10 s each**: Ch4 21–27 dB 4.8e-3 … 5.9e-8 (587 errors);
  Ch2 precoded 17–23 dB 3.6e-3 … 2.5e-8 (252 errors).
- Model at the same points, independent seeds: first pass (~300 errors, Clopper-Pearson) put 3
  of 11 board points outside the model CI (highest BER on each channel −12…−16%, Ch4 24 dB
  +42%). Not a hardware difference (same-seed counts are exact): too few errors, and errors
  are bursty (DFE propagation, precoder pairs) so the binomial CI is too narrow. Rerun with
  ~3000 errors in ≥ 20 independent chunks and a batch-means CI (checked: equals CP for
  independent errors, wider for pairs, 93.5% coverage in 400 trials): **11/11 inside**.
  Points below ~1e-7 are board-only (the model needs ~8 h per point at 7e4 b/s).
- Open: `make sim` now 7 min 9 s (budget 5): move the P = 2 link/ber_core runs to sim-full.
  Board CIs are still Clopper-Pearson (optimistic at the low-count points by the burst factor).
