# ffe_capture_kr_ch4_31p4db_24db.csv

- Written: 2026-11-11T15:07:02
- Command: `scripts/ber_run.py capture --channel kr_ch4_31p4db --snr 24`
- Host commit: bbd5b143
- SNR (dB): 24.0
- sigma_reg: 2714
- seed: 1592590354
- prbs_seed: 263825222
- noise_seed: 1838343771109760852
- b (dfe): 45
- t2: 124
- build id: 70fb7cb6
- samples differing (hw vs model): 0
- verdict: PASS
- SNR: PAM4 Es * sum(hq^2) / sigma^2 on the quantized channel (model.link.noise_sigma)
- Equalizer: MMSE FFE 16 taps (4 pre) + 1-tap DFE designed at the point's SNR, fixed point per ADR 0004; holdoff and lag per ADR 0011; interleaving: none (pre-FEC)
- CI: 95% Clopper-Pearson; kind = upper_bound when fewer than 100 bit errors

Interpretation: ILA capture of the FFE output z (rx_top z_o), 4096 words x P = 16384 symbols from RX symbol m0 (k = 0). z_model: bit-exact model, same seeds. d_model: the model's DFE decision (level index); v = z - b * level(d[k-1]) is the slicer input; the slicer thresholds are -t2, 0, +t2 (dfe_slicer.sv).
