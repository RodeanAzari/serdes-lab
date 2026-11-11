# ber_model_kr_ch2_19p3db_pre.csv

- Written: 2026-11-11T12:31:44
- Command: `scripts/ber_run.py model --channel kr_ch2_19p3db --precoder`
- Host commit: 5ed0b033
- seed: 1592590354
- target errors: 3000
- bit cap per point: 120000000
- not run (need > cap bits for 100 errors): none
- board sweep: ber_hw_kr_ch2_19p3db_pre.csv
- SNR: PAM4 Es * sum(hq^2) / sigma^2 on the quantized channel (model.link.noise_sigma)
- Equalizer: MMSE FFE 16 taps (4 pre) + 1-tap DFE designed at the point's SNR, fixed point per ADR 0004; holdoff and lag per ADR 0011; interleaving: none (pre-FEC)
- CI: 95% Clopper-Pearson; kind = upper_bound when fewer than 100 bit errors

Interpretation: bit-exact fixed-point model (model.tx/rx, same registers as the board run, independent seeds per chunk; prbs/noise seed columns = the last chunk's). build_id 00000000 = model, not hardware. ci95_*_batch: batch means over the chunks (ratio estimator, Student t), valid with DFE error bursts; ci95_lo/hi: Clopper-Pearson, which assumes independent errors and is too narrow here. Compare the board with the batch CI (ADR 0004).
