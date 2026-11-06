# serdespy_ber.csv

- **Command:** `make xcheck` (`scripts/serdespy_xcheck.py`); seeded, re-run reproduces exactly
- **Commit:** `0837fd4`
- **Tools:** Python 3.14.4, numpy 2.5.4, scipy 1.18.1, serdespy 1.0
- **Channel/EQ:** `data/channels/kr_ch{2,4}*.npz`, 99.9%-energy truncation; MMSE FFE16(pre3) +
  DFE1 with real decisions, solved per SNR; precoder off; no FEC
- **Seeds:** serdespy payload `RandomState(4242 + 1000k)`, noise `np.random.seed(… + 1)`;
  model `run_link` seeds 9100 + k / 9600 + k (k = chunk)
- **What differs between the two columns:** payload and noise generators, TX Gray map, FFE,
  DFE recursion, slicer, Gray demap (all serdespy's). **Shared:** pulse, taps, SNR → σ.
- **Statistics:** chunks of 5e5 symbols; ≥ 10 chunks and ≥ 200 errors per side. DFE bursts
  make errors non-independent, so `*_ber_se` is a batch-means standard error, and
  z = (BER_serdespy − BER_model) / √(se² + se²).

**Interpretation:** all 8 points agree (|z| ≤ 1.63), BER 1.4e-3 down to 4e-6. Ratios
0.95–1.04 at ≥ 400 errors; 0.82 and 0.67 at the two lowest points (201–322 errors), both
within noise, and the paired run (`serdespy_paired.csv`) shows the engines give identical
counts on identical inputs, so that scatter is generator statistics. For scale, the model's
own earlier run at Ch4 25 dB gave 7.57e-6 (`model_ber_float.csv`) vs 8.95e-6 here.
