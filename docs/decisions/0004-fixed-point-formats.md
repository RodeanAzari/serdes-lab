# ADR 0004: Fixed-point formats (channel, ADC, FFE, DFE/slicer)

**Status:** accepted 2026-11-06 (ADC: user decision; widths: measured). **Phase:** A (design),
B/C (implementation). Format table: [`docs/fixed-point.md`](../fixed-point.md).
Noise-generator formats are a separate step (ADR 0003 tables).

## Decision

| Item | Choice |
|---|---|
| ADC | **7 bits**, symmetric ±63, **full scale = 3.0 × noiseless received-signal rms** |
| Gain | Per channel, folded into the integer channel taps (`model/fixed.py:channel_int`) |
| Pre-ADC fraction | 6 bits below the ADC LSB |
| FFE coefficients | **10 bits** signed, max \|tap\| scaled to 511 per channel |
| FFE output z | **10 bits** signed, symmetric; outer level 3·h0 in (¼, ½] of full scale |
| Arithmetic | Round half up (add + arithmetic shift), symmetric saturation, full-precision accumulator |
| DFE tap, threshold | Integers in z units, from the exact integer combined response (`rx_regs`) |

## Evidence

Paired slicer-SNR penalty vs. a float receiver, same symbols, noise and quantized channel,
ideal-decision DFE, 10⁶ symbols ([`fixed_point_sweep.csv`](../../data/results/fixed_point_sweep.csv)).
Operating points: input SNR where float Gaussian-predicted BER = 2.4e-4 and 1e-12.

| Config | Ch2 @ 2.4e-4 | Ch2 @ 1e-12 | Ch4 @ 2.4e-4 | Ch4 @ 1e-12 |
|---|---|---|---|---|
| **Chosen (7b, 3.0, coef 10, out 10)** | **0.07 dB** | **0.25 dB** | **0.17 dB** | **0.60 dB** |
| 6-bit ADC, best full scale | 0.18 dB | 0.43 dB | 0.38 dB | 1.46 dB |
| 8-bit ADC, 3.0 × rms | 0.02 dB | 0.06 dB | 0.03 dB | 0.15 dB |

- Noiseless ISI peaks: 2.06 × rms (Ch2), 2.89 × rms (Ch4). Full scale 3.0 clips neither
  channel's signal; 2.5 clips Ch4's on 0.16% of samples.
- Coefficients: 10 bits ≤ 0.011 dB; 8 bits up to 0.11 dB. FFE output: 10 bits ≤ 0.04 dB;
  8 bits up to 1.66 dB. Metric resolution ≈ ±0.02 dB (small negative values occur).
- Pre-ADC fraction < 3 bits: double rounding (half up twice) adds a DC bias; frac = 1 is
  worst (Ch4 1e-12: 0.64 vs 0.56 dB at frac = 6).
- **Real-decision DFE BER**, chosen config vs. float on identical samples, 10⁷ bits per point
  ([`fixed_point_ber.csv`](../../data/results/fixed_point_ber.csv)): Ch4 fixed/float 1.22×
  (10,707 vs 8,810 errors) at the 2.4e-4 point, 1.38× at +1 dB, 1.81× at +2 dB; Ch2 1.10×,
  1.24×, 1.14×. Consistent with the MSE penalty and its growth with SNR.

## Consequences

- The 7-bit ADC is a **real, reported impairment** (≈ 0.6 dB on Ch4 at 1e-12), as in a real
  ADC-based receiver. Hardware BER is compared to the bit-exact fixed-point model, never to
  the float curves.
- DSP: 7 × 10-bit products fit one DSP48E1 each (25 × 18); accumulator 20 bits signed
  (63 · 511 · 16 = 515,088 < 2¹⁹).
- **Caveat:** at the 1e-12 point the Ch4 noise is σ = 0.77 ADC LSB, so ADC quantization error
  is not well dithered there; the 1e-12 penalties come from MSE (Gaussian assumption) and are
  estimates until measured on hardware (Phase C).

## Rejected alternatives

- **6-bit ADC:** ≥ 1.46 dB on Ch4 at 1e-12 at every full scale tested.
- **7-bit, full scale 2.5 × rms:** 0.14 dB better on Ch4, but clips the noiseless signal;
  data-dependent distortion whose low-BER effect MSE cannot vouch for.
- **7-bit, per-channel full scale = ISI peak:** small gain on Ch2 only; one more per-channel
  rule to document and justify.
- **8-bit ADC:** 0.15 dB, but outside buildplan §6.4 (6–7 bits) and less representative of
  a 200G ADC.
- **Asymmetric (two's-complement) saturation:** biases the ±3 levels differently.
