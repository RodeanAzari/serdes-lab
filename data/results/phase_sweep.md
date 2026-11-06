# phase_sweep.csv

- **Command:** `.venv/bin/python scripts/phase_sweep.py`; deterministic, no seed
- **Commit:** `3dad5b8` (re-run on clean tree; byte-identical to the first run)
- **Input:** `data/channels/kr_ch{2,4}*.npz` (`pulse_os`, `tx_taps`, `noise_var_ref`)
- **Method:** for each of 32 phases, decimate the oversampled CTLE pulse, apply the TX FIR, solve
  the reference MMSE FFE16(pre3)+DFE1; slicer SNR at the thermal reference noise and at an
  operating input SNR (Ch2 19 dB, Ch4 23 dB; ~1e-4 BER in `model_ber_float.csv`).
- **Known offset:** at max-cursor, Ch2 ref SNR is 30.84 dB here vs 30.98 dB in `channels.csv`
  (identical cursors; the 400-UI crop windows differ by a sample in the reflection tail). All
  phases here share one window, so between-phase gaps are unaffected. Ch4 matches exactly.

**Interpretation:** max-cursor is 0.18–0.25 dB below the best phase in all four cases → kept
(ADR 0001).
