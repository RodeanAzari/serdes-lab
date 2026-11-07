# ADR 0003: Gaussian noise generator

**Status:** accepted 2026-11-06 (user decision). **Phase:** A (design), B (implementation).
Formats and validation step 3: superseded by [ADR 0005](0005-noise-formats-and-validation.md).

## Requirements (buildplan §6.4, ADR 0002)

- 8 independent samples per clock (P = 4 × 2 instances) at 125 MHz = 10⁹ samples/s.
- Tails accurate to **≥ 8σ**: Gray PAM4 BER 10⁻¹² sits at 7.0σ from the slicer threshold,
  10⁻¹⁵ at 7.9σ. Target: |P_gen(X > t) / Q(t) − 1| ≤ 1% for every t ≤ 8σ, so tail error moves
  BER by ≤ 1%.
- Fixed latency, no rejection (no stalls in a streaming datapath); bit-exact Python mirror.
- Independent of the payload PRBS (different generator, polynomials and seeds: CLAUDE.md §5).

## Decision

| Item | Choice |
|---|---|
| Method | **Inverse CDF with hierarchical (octave) segmentation**, degree-2 polynomial per segment |
| Input | 64 uniform bits per sample: 1 sign bit + 63-bit magnitude u |
| Segment select | Leading-zero count of u (octave, finer toward the tail) + top bits after the leading one (sub-segment); coefficients c0, c1, c2 from BRAM |
| Evaluate | c0 + x·(c1 + x·c2), x = remaining bits after the sub-segment index |
| Reach | 9.08σ: smallest magnitude step 2⁻⁶³ ⇒ 2Q(x) = 2⁻⁶³ |
| Scaling | × σ from the SNR register (1 DSP) |
| Uniform source | One F₂-linear 64-bit generator per lane (L'Ecuyer `lfsr258`-type combined Tausworthe: XOR/shift only, LUTs, period ≈ 2²⁵⁸), distinct seeds per lane |
| Cost (estimate) | ~2 DSP (polynomial) + 1 (scaling) = **~3 DSP/sample, ~24 total** (ADR 0002 budget); a few BRAM36 per instance (ports shared by 2 lanes) |

Segment count, sub-segment bits, coefficient and datapath widths are chosen in Phase B by the
Python model against the 1% tail target, and recorded in `docs/fixed-point.md`.

## Validation

1. **Exact (model).** The generator is a monotonic map of one uniform input, so its output
   CDF follows exactly from the tables: count the inputs mapping below each threshold, per
   segment. `make model-test` checks the 1% tail target to 8σ with **no sampling**.
2. **Bit-exact RTL** vs. the model in cocotb (random seeds, every segment and the sign bit hit).
3. *(Superseded by ADR 0005: compared to the exact model pmf, Gaussian chi-square on |n| ≥ 4σ only.)*
   **Hardware histogram, ~4×10¹³ samples (~11 h overnight)**, compared to the Gaussian to ±7σ
   by chi-square (bins merged to ≥ 5 expected counts); log-scale plot committed. Exceeds the
   §6.4 minimum of 10¹² (user decision): 10¹² samples hold only ~2.6 values beyond 7σ
   (80 beyond 6.5σ), so they verify only to ~6.5σ; 4×10¹³ gives ~100 beyond 7σ. All 8 lanes
   must feed the histogram (one per lane, or tail-event capture): one lane alone would take
   ~89 h. Hardware confirms the RTL and the uniform source; the model check covers the tail.
4. Lag-1…16 autocorrelation and cross-lane correlation of the generated samples (FFE sums
   16 lags, so correlation there would bias BER).

## Rejected alternatives

- **Box–Muller + CORDIC** (2 uniforms → 2 samples, reach 8.2σ with 48 bits): viable, but the
  2-D construction has no exact tail check (only the radius part is 1-D), and the wide ln
  polynomial is estimated at ~3.5–4.5 DSP/sample.
- **Sum of uniforms (CLT):** no tails, fake-good BER (§6.4, CLAUDE.md §14).
- **Ziggurat:** rejection gives variable latency; needs FIFOs and stalls in a fixed-rate stream.
- **Wallace:** sample reuse makes outputs correlated; tails depend on pool mixing.
- **Piecewise-linear inverse CDF:** saves 1 DSP but needs many more segments for 1% tails; revisit
  only if the DSP budget is exceeded.

## Risk

F₂-linear uniform generators fail linear-complexity tests. Each 64-bit output feeds one sample
once, and checks 3 and 4 above would show any structure that matters here.
