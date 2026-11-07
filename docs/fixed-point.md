# Fixed-point formats

Single source for every RTL signal's width. The Python mirror is `model/fixed.py`
(`FixedCfg` defaults = this table). Decision and evidence: ADR 0004.

Conventions: two's complement; **round half up** = `(x + 2^(s-1)) >>> s`; **saturation is
symmetric** to ±(2^(n-1) − 1); no silent wrap anywhere.

| Signal | Width | Range / units | Notes |
|---|---|---|---|
| PAM4 symbol a | 3 b signed | ±1, ±3 | Gray map per buildplan §6.1 |
| Channel tap hq[j] | 11 b signed | units 2⁻⁶ ADC LSB | Gain per channel: ADC FS = 3.0 × signal rms. Rms normalization bounds \|hq\| ≤ 601 |
| Pre-ADC word y = Σ hq·a + noise | 16 b signed | units 2⁻⁶ ADC LSB | No wrap for ≤ 16 channel taps and SNR ≥ −7 dB (noise to 9.08σ) |
| Noise sample | [TBD] | units 2⁻⁶ ADC LSB | With the ADR 0003 segment tables (next step) |
| ADC output x | 7 b signed | ±63 LSB | `sat(round_shift(y, 6), 7)` |
| FFE coefficient c[i] | 10 b signed | ±511, scale per channel | `quantize_coefs`: max \|tap\| → 511 |
| FFE product | 17 b signed | | One DSP48E1 per tap |
| FFE accumulator | 20 b signed | full precision | 63 · 511 · 16 = 515,088 < 2¹⁹ |
| FFE output shift | register, 0…10 | | 6 on Ch2 and Ch4 |
| FFE output z | 10 b signed | ±511 | `sat(round_shift(acc, shift), 10)` |
| DFE tap b | 10 b signed | z units | Ch2 37, Ch4 45 (at the 2.4e-4 and 1e-12 points) |
| DFE/slicer input v = z − b·d | 12 b signed | \|v\| ≤ 511 + 3·511 | b·d is shift/add (d ∈ ±1, ±3) |
| Slicer threshold t2 (= 2·h0) | 10 b unsigned | z units | Ch2 158, Ch4 124; thresholds −t2, 0, +t2, ties go up |
