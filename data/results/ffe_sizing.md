# ffe_sizing.csv

- **Command:** `.venv/bin/python scripts/ffe_sizing.py`; deterministic, no seed, ~2 s
- **Commit:** `85ecf02`
- **Tools:** Python 3.14.4, numpy 2.5.4, scipy 1.18.1
- **Input:** `data/channels/kr_ch{2,4}*.npz`, 99.9%-energy truncation (the pulse the emulator's
  channel FIR will use: Ch2 2pre+7post, Ch4 2pre+9post)
- **Method:** for each FFE length N, every pre-cursor split 0…min(N−1, 10); MMSE taps with a
  1-tap ideal DFE; input SNR at which the Gaussian-predicted slicer BER = 2.4e-4 (KP4 pre-FEC
  target as used in 802.3ck/dj budgets, **[verify against 802.3dj]**). Penalty vs N = 32.

**Interpretation:** the FFE saturates at ~12 taps on both channels: N = 12 costs 0.01 dB (Ch2)
and 0.12 dB (Ch4); N = 16 ≤ 0.01 dB; N = 8 costs 0.46 / 0.77 dB; N ≤ 6 collapses on Ch4.
Caveats: relative numbers only (no DFE error propagation, float taps); against the
**truncated** channel, so a real channel's long reflection tail is not represented, and that
is by construction of the emulator (ADR 0001).
