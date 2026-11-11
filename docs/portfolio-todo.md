# Portfolio captures

| Capture | Phase | Type | Status |
|---|---|---|---|
| Pulse responses per channel | A | Plot | Done: `docs/media/2026-11-05_phase-a_pulse-responses.png` |
| Model BER waterfall (float, DFE real vs ideal decisions) | A | Plot | Done: `docs/media/2026-11-05_phase-a_model-ber-waterfall.png` |
| Model BER waterfall with serdespy overlay | A | Plot | Done: `docs/media/2026-11-07_phase-a_serdespy-overlay.png` |
| Model errors per KP4 codeword vs independent prediction | A | Plot | Done: `docs/media/2026-11-07_phase-a_kp4-errors-per-codeword.png` |
| Hardware noise histogram vs Gaussian ±7σ, 7.2 × 10¹² samples (log scale, residuals) | B | Plot | Done: `docs/media/2026-11-11_phase-b_noise-histogram.png` |
| Photo: Arty running the noise histogram (LD4 heartbeat, LD6 run LED, Ethernet link LEDs) | B | Photo | Pending: user |
| Terminal capture: `noise_hist_run.py exact` printing PASS, 0 of 8192 bins differ | B | Screenshot | Pending: user |
| Hardware BER vs bit-exact model, Ch4 and Ch2 precoded, 10¹⁰ bits per point down to 2.5 × 10⁻⁸ | C | Plot | Done: `docs/media/2026-11-11_phase-c_ber-hw-vs-model.png` |
| Terminal capture: `ber_run.py exact` printing PASS (board counts = model counts) | C | Screenshot | Pending: user |
| Terminal capture: `ber_run.py sweep` printing the 7-point waterfall, 10 s per point | C | Screenshot | Pending: user |
| Photo: Arty running `ber_top` (LD4 heartbeat, LD5 run LED during a sweep, Ethernet LEDs) | C | Photo | Pending: user |
| ILA capture of the FFE output: 16384 samples, slicer input v and z histograms (equal to the model) | C | Plot | Done: `docs/media/2026-11-11_phase-c_ila-ffe-eye.png` |
| Optional: Vivado Hardware Manager waveform of the same ILA (ber_top.ltx) | C | Screenshot | Pending: user |
