# ber_exact_kr_ch2_19p3db_pre.csv

- Written: 2026-11-11T11:39:34
- Command: `scripts/ber_run.py exact --channel kr_ch2_19p3db --snr 17 --precoder`
- Host commit: 5ed0b033
- seed: 1592590354
- codewords (model): 200
- R (bits): 1087424
- verdict: PASS
- SNR: PAM4 Es * sum(hq^2) / sigma^2 on the quantized channel (model.link.noise_sigma)
- Equalizer: MMSE FFE 16 taps (4 pre) + 1-tap DFE designed at the point's SNR, fixed point per ADR 0004; holdoff and lag per ADR 0011; interleaving: none (pre-FEC)
- CI: 95% Clopper-Pearson; kind = upper_bound when fewer than 100 bit errors

Interpretation: ADR 0012 exactness check: the board's counts over exactly R bits vs the bit-exact model for the same seeds and registers. PASS means bits, bit errors and symbol errors are all equal, so long board runs sample the model's error process.
