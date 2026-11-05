# channels.csv

- **Command:** `make channels` (`scripts/make_channels.py`)
- **Commit:** [TBD: first commit not made yet]
- **Tools:** Python 3.14.4, numpy 2.5.4, scikit-rf 2.2.0 (see `requirements.txt`)
- **Input:** `shanbhag_3dj_02_2305.zip`, SHA-256 in `data/MANIFEST.md`
- **Seed:** none (deterministic)
- **Columns:** published vs computed IL @ 53.125 GHz; chosen CTLE and TX FIR; sampling phase
  (of 32/UI); main cursor per unit PAM4 symbol (A_v/3 = 137.7 mV); 99.9%-energy truncation;
  reference RX and its SNR.

**Interpretation.** IL agrees with the contribution to ≤ 0.05 dB, so the port mapping is right.
`ref_snr_db` is the SNR of a reference receiver against **thermal noise only** (no crosstalk,
jitter, TX SNDR or package). It was used to choose the CTLE and must **not** be quoted as a
channel SNR or link margin. Method: [ADR 0001](../../docs/decisions/0001-channel-model.md).
