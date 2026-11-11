# Fixed-point formats

Single source for every RTL signal's width. The Python mirror is `model/fixed.py`
(`FixedCfg` defaults = this table). Decision and evidence: ADR 0004.

Conventions: two's complement; **round half up** = `(x + 2^(s-1)) >>> s`; **saturation is
symmetric** to ±(2^(n-1) − 1); no silent wrap anywhere.

| Signal | Width | Range / units | Notes |
|---|---|---|---|
| PAM4 symbol a | 3 b signed | ±1, ±3 | Gray map per buildplan §6.1 |
| Gray / precoded symbol G, P | 2 b unsigned | 0…3 | P(j) = (G(j) − P(j−1)) mod 4: the specified mod-4 wrap (ADR 0006), not an overflow |
| Channel tap hq[j] | 11 b signed | units 2⁻⁶ ADC LSB | Gain per channel: ADC FS = 3.0 × signal rms. Rms normalization bounds \|hq\| ≤ 601 |
| Channel FIR sum s = Σ hq·a | 11 + 2 + ⌈log₂ L⌉ b signed (17 b at L = 16) | units 2⁻⁶ ADC LSB | Full precision, cannot overflow (3·1024·L < 2^(S_W−1)). `rtl/channel/channel_fir.sv`, L = 16 taps (Ch2 uses 10, Ch4 12) |
| Pre-ADC word y = Σ hq·a + noise | 16 b signed | units 2⁻⁶ ADC LSB | y = sat(s + n, 16) (`model/tx.py`); saturation never engages on Ch2/Ch4 for SNR ≥ −7.41 dB (worst data pattern + 9.155σ noise, ADR 0005) |
| Uniform word | 64 b | bit 63 sign, bits 62:0 magnitude input u | One per sample per lane (ADR 0003) |
| Noise segment index | 10 b | octave (leading zeros of u, 0…63) ‖ 4 sub bits | 1024 segments (ADR 0005) |
| Noise poly input x | 17 b unsigned | next 17 bits after the sub index | Zero-padded in octaves with < 21 bits left |
| Noise c0 / c1 / c2 | 25 / 23 / 17 b signed | c0 units 2⁻²⁰; c1, c2 units 2⁻²⁶ | 65 b BRAM word |
| Noise Horner t | 23 b signed | units 2⁻²⁶ | t = c1 + rs(x·c2, 17) |
| Noise magnitude g | 24 b unsigned | units 2⁻²⁰ σ, max 9.155 | g = max(0, c0 + rs(x·t, 23)) |
| σ register | 17 b unsigned | units 2⁻⁵ pre-ADC unit | σ_reg = round(32 σ) |
| Noise sample n | 16 b signed | units 2⁻⁶ ADC LSB | ±sat(rs(g·σ_reg, 25), 16); sign applied after rounding |
| ADC output x | 7 b signed | ±63 LSB | `sat(round_shift(y, 6), 7)` |
| FFE coefficient c[i] | 10 b signed | ±511, scale per channel | `quantize_coefs`: max \|tap\| → 511 |
| FFE product | 17 b signed | | One DSP48E1 per tap |
| FFE accumulator | 21 b signed | full precision | Sized for any port value: 16 · (−64)(−512) = 2¹⁹ needs 21 b (ADC ±63, coefs ±511 would fit 20 b) |
| FFE output shift | register, 0…10 | | 6 on Ch2 and Ch4 |
| FFE output z | 10 b signed | ±511 | `sat(round_shift(acc, shift), 10)` |
| DFE tap b | 10 b signed | z units | Ch2 37, Ch4 45 (at the 2.4e-4 and 1e-12 points) |
| DFE/slicer input v = z − b·d | 12 b signed | \|v\| ≤ 511 + 3·511 | b·d is shift/add (d ∈ ±1, ±3) |
| Slicer threshold t2 (= 2·h0) | 10 b unsigned | z units | Ch2 158, Ch4 124; thresholds −t2, 0, +t2, ties go up |
