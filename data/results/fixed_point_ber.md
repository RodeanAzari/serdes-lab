# fixed_point_ber.csv

- **Command:** `.venv/bin/python scripts/fixed_point_sweep.py`; seeded
- **Commit:** `72fd78d`
- **Tools:** Python 3.14.4, numpy 2.5.4, scipy 1.18.1
- **Channel/EQ:** as `fixed_point_sweep.md`; **real-decision** 1-tap DFE (error propagation
  included); fixed = ADR 0004 config (7-bit ADC, FS 3.0 × rms, frac 6, coef 10, out 10)
- **SNR:** the 2.4e-4 float operating point + 0, 1, 2 dB; precoder off; no FEC
- **Seeds:** payload 101, noise SeedSequence(202, spawn_key=(1,)); 5 × 10⁶ symbols per point,
  same samples into both receivers
- **Statistics:** `*_lo95/_hi95` are Clopper–Pearson assuming independent errors; DFE bursts
  make them too narrow (see `serdespy_ber.md`). The paired ratio is the quantity of interest.
  All points have ≥ 100 errors.

**Interpretation:** fixed/float BER ratio 1.10–1.24 (Ch2) and 1.22 → 1.38 → 1.81 (Ch4) as SNR
rises 0 → 2 dB above the operating point: consistent with the MSE penalties in
`fixed_point_sweep.csv` (0.17 dB on Ch4 at the operating point predicts ≈ 1.28×) and with the
penalty growing at low BER.
