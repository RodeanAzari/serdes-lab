# model_ber_float.csv

- **Command:** `make model-ber` (`scripts/ber_model.py`), then `make plots`
- **Commit:** `31546f5` (the `commit` column); run on a clean tree, 2026-11-05
- **Tools:** Python 3.14.4, numpy 2.5.4, scipy 1.18.1
- **Channel:** `data/channels/kr_ch{2,4}*.npz`, truncated to the 99.9%-energy window (ADR 0001)
- **SNR:** E[s²]/σ² at the ADC input ([design.md](../../docs/design.md))
- **Equalizer:** float MMSE FFE, 16 taps (3 pre), 1-tap DFE, re-solved at every SNR. Not the
  sized RTL configuration (sizing ADR pending). No ADC quantization, no precoder, no FEC.
- **Seeds:** data `20261105 + k`, noise `77 + k` (independent generators) for chunk k of 2M
  symbols; runs until ≥ 200 bit errors or 50M symbols.
- **Columns:** `ber` + 95% Clopper–Pearson CI only with ≥ 100 errors; otherwise
  `ber_upper_bound95`. `ber_ideal_dfe` uses the same seeds with the true previous symbol in the
  DFE. `ber_pred_gaussian` is from the MMSE slicer SNR.

**Interpretation.** With ideal decisions, measured BER matches the Gaussian prediction (e.g. Ch4
22 dB: 3.92e-4 vs 3.96e-4), which validates the model's alignment and noise scaling. With real
decisions, BER is ~1.5× higher on Ch2 (b/h0 = 0.47) and 3.5–4.4× higher on Ch4 (b/h0 = 0.72):
DFE error propagation, growing with the DFE tap. This is the burst mechanism Phase D measures
against KP4.
