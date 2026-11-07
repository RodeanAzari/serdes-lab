# ADR 0005: Noise generator formats and validation

**Status:** accepted 2026-11-07 (format and validation: user decisions; widths: measured).
**Phase:** A (design), B (implementation). Method: ADR 0003. Formats: [`docs/fixed-point.md`](../fixed-point.md).
Model: `model/noise.py`. Evidence: [`noise_sweep.csv`](../../data/results/noise_sweep.csv).
Supersedes ADR 0003 validation step 3 (hardware histogram compared to the ideal Gaussian).

## Decision

| Item | Choice |
|---|---|
| Sub-segments per octave | **S = 4** → 64 octaves × 16 = **1024 segments** (6 b octave + 4 b sub index) |
| Polynomial input x | **XB = 17 b** unsigned (DSP 18 b port); input resolution T = 21 b per octave |
| Output \|g\| | **FG = 20** fraction bits, 24 b unsigned (DSP 25 b port), reach **9.155σ** |
| Coefficients | c0 25 b, c1 23 b, c2 17 b signed (c1, c2, t at 2⁻²⁶): 65 b/entry, **2 BRAM36 per lane pair, 8 total** |
| σ register | 17 b unsigned, 5 fraction bits (pre-ADC units); n = sat(rs(g·σ, 25), 16) |
| Sign | Applied **after** rounding: the pmf is exactly symmetric, mean exactly 0 |
| DSP | 3 per sample (x·c2, x·t, g·σ), 24 total, as budgeted in ADR 0002 |

## Evidence (exact: all 2⁶³ inputs enumerated, no sampling)

- **Tail target met with 220× margin:** worst |P_gen(\|g\| ≥ t)/P_ideal − 1| to 8σ is 4.5 × 10⁻⁵
  (target 1%); ≤ 3.6 × 10⁻⁵ after scaling to pre-ADC units at the four operating-point σ values.
  The ideal is an exact Gaussian rounded the same way (the output is discrete; comparing to a
  continuous Q(t) would mostly measure the output grid). Every config swept meets the target,
  even S = 2 (2.2 × 10⁻⁴).
- **Tail floor is the 63-bit input, not the tables:** beyond 8σ only ~10⁴ distinct inputs remain,
  so the tail CDF moves in steps of ~10⁻⁴. Error is flat at 4.4–5.8 × 10⁻⁵ for S ≥ 3.
- Max |g − g_ideal| = 2.4 × 10⁻⁶σ. Its BER effect (< 10⁻⁴ relative) is negligible next to the
  statistical CIs.
- Pre-ADC headroom: worst-case data pattern + a 9.155σ noise sample fits the 16 b word down to
  SNR −7.41 dB (Ch4) / −7.74 dB (Ch2). The noise sample saturates symmetrically above that.

## Validation change (user decision)

A 4 × 10¹³-sample histogram resolves body-region probability differences of ~10⁻⁹. The generator's
fit error, output LSB and input granularity are each ~10⁻⁶σ, so a chi-square against the ideal
Gaussian with one bin per pre-ADC unit has expected excess **λ ≈ 4 × 10⁴ on 354 dof** at σ = 49.4
(Ch4 1e-12 point): **bug-free RTL would fail it.** Every swept config fails it (λ ≥ 4 × 10⁴). Passing
needs a ~31 b datapath (FG ≥ 27, T ≥ 28): ~6–8 DSP/sample, and exhaustive model checks would no longer be feasible.

Hardware noise check (replaces ADR 0003 step 3):
1. **Histogram vs. the exact model pmf** (`pmf_n`), chi-square, all bins (merged to ≥ 5 expected).
   Expected excess 0: any RTL or uniform-source defect shows up.
2. **Histogram vs. the Gaussian on the tail only,** |n| ≥ 4σ with the body merged into one bin, at
   σ_reg for 49.4: predicted λ = 3.9 on 157 dof (the statistic's spread is √(2·157) ≈ 18), so a
   correct generator passes. Covers ~2.5 × 10⁹ samples beyond 4σ. From 3σ: λ = 128, which would
   fail. Tested in `test_hw_tail_chi2_cannot_reject_bug_free_generator`.
3. Log-scale plot of the hardware histogram vs. Gaussian to ±7σ (buildplan §6.4), with the model pmf.

The Gaussian accuracy that BER depends on (cumulative tails) is proven exactly in the model, not
by hardware sampling.

## Rejected alternatives

- **Wide datapath to pass a full Gaussian chi-square at 4 × 10¹³:** +24–40 DSP and more BRAM to fix
  differences that move BER by < 10⁻⁴ relative.
- **Gaussian chi-square on ~10⁹ samples** (where it passes): insensitive to small RTL defects, and
  it drops the 7σ statistics from the test.
- **S = 3** (512 segments, 4 BRAM36 total): 5× larger body error (1.3 × 10⁻⁵σ) to save 4 BRAM36.
- **S = 5** (16 BRAM36): halves the body error with no tail gain.
- **FG = 18:** tail error rises to 5.7 × 10⁻⁵ and the full-σ λ grows 7×. FG = 20 is the widest the
  25 b DSP port allows.
