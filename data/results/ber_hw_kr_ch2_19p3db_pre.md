# ber_hw_kr_ch2_19p3db_pre.csv

- Written: 2026-11-11T11:46:38
- Command: `scripts/ber_run.py sweep --channel kr_ch2_19p3db --precoder --snr 17,18,19,20,21,22,23 --bits 1e10`
- Host commit: 5ed0b033
- seed (point i uses seed + i): 1592590354
- R per point (bits): 10000000000
- SNR: PAM4 Es * sum(hq^2) / sigma^2 on the quantized channel (model.link.noise_sigma)
- Equalizer: MMSE FFE 16 taps (4 pre) + 1-tap DFE designed at the point's SNR, fixed point per ADR 0004; holdoff and lag per ADR 0011; interleaving: none (pre-FEC)
- CI: 95% Clopper-Pearson; kind = upper_bound when fewer than 100 bit errors

Interpretation: pre-FEC BER measured on the board (ber_top), one fixed-length run per SNR. Compare with the bit-exact fixed-point model, never the float curve (ADR 0004).
