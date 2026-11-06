# Design notes

## SNR definition (buildplan §6.4)

**SNR = E[s²] / σ²**, at the ADC input, per symbol, where s is the noiseless channel output and
σ² the variance of the added white Gaussian noise. For i.i.d. equiprobable PAM4 levels ±1, ±3
(E[a²] = 5) through a symbol-spaced pulse response h: **E[s²] = 5 · Σ h²**.

This is the received-signal SNR, not the slicer SNR. The slicer SNR after equalization
(`mmse_slicer_snr_db` in result CSVs) is E[a²]·h0² / E[e²] with h0 the combined main cursor.

Implementation: `model/link.py:noise_sigma`. Tested against closed-form PAM4 BER on an ideal
channel (`model/tests/test_link.py`).

## Gaussian BER prediction

PAM4 with Gaussian error at the slicer: SER = 1.5 · Q(√(SNR_slicer / 5)), Gray BER ≈ SER / 2.
`model/stats.py`.
