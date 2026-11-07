# kp4_model.csv

- **Command:** `make model-kp4` (`scripts/kp4_model.py`), then `make plots`; seeded, ~30 min
- **Commit:** `4fa99da`
- **Tools:** Python 3.14.4, numpy 2.5.4, scipy 1.18.1
- **Chain:** `model/kp4link.py`: random payload → KP4 RS(544,514) encode → Gray PAM4 (1/(1+D)
  mod 4 precoder off/on, ADR 0006) → channel (99.9%-energy pulse, ADR 0001) → white Gaussian
  noise → float MMSE FFE 16 taps (3 pre) + 1-tap DFE, re-solved per SNR (same reference
  equalizer as `model_ber_float.csv`) → slicer → precoder inverse → Gray demap → RS symbols.
  Float model: no ADC quantization.
- **SNR:** E[s²]/σ² at the ADC input ([design.md](../../docs/design.md))
- **Seeds:** payload `20261107 + k`, noise `SeedSequence(707 + k, spawn_key=(1,))`, chunk k of
  1,000 codewords, 10 chunks per row. **Paired:** real/ideal DFE and precoder off/on rows at one
  SNR share payload and noise draws; `interleave` 1 and 2 rows group the **same** lane errors.
- **Interleaving:** 1 = consecutive codewords; 2 = two codewords alternating RS symbol by RS
  symbol (A0 B0 A1 B1 …) (buildplan §6.2; assumption, not a real PMA).
- **CER:** codewords with > 15 RS-symbol errors. Exact for any bounded-distance decoder; the real
  decoder (`model/rs.py`, checked against `galois`) was run on ≥ 80 codewords per row, both
  sides of t, with **0** contradictions. `cer` and its Clopper–Pearson CI only with ≥ 100
  codeword errors, otherwise `cer_upper_bound95`. Codewords are 2,720 PAM4 symbols and the
  longest burst is 32, so codeword errors are close to independent and the CI is appropriate.
- **Prediction:** `cer_pred_independent` = P(Binomial(544, p) > 15) with p = the row's measured
  RS-symbol error rate; `h*_pred` the binomial histogram. `var_binomial` = 544·p·(1−p).
- **Bursts:** runs of consecutive PAM4 symbol errors after the precoder inverse (chunk edges cut
  bursts; negligible).

**Interpretation.**
- **Null case holds:** ideal DFE decisions with no precoder give independent errors
  (variance / binomial 0.98–1.03), and the measured CER matches the prediction: Ch4 20.5 dB
  9.68% vs 9.42% (968 errors), Ch2 16.5 dB 46.5% vs 46.4%.
- **DFE bursts raise CER above the independent prediction** when errors per codeword sit below
  the threshold: Ch4 21 dB, real DFE, non-interleaved, **9.72% (CI 9.15–10.32%) vs 4.63%**,
  2.1×; Ch2 17 dB 8.27% vs 6.76%, 1.22×. Ch4's larger DFE tap gives longer bursts (mean 3.4
  PAM4 symbols, max 32, vs 1.5 and 10 on Ch2) and variance 1.7–1.8× binomial. Near CER ≈ 50%
  (16.5 / 20.5 dB) the excess vanishes: the distribution is wider, not shifted.
- **2-way interleaving recovers most of it** on identical errors: Ch4 21 dB 5.65% (1.22× the
  prediction).
- **Precoding lowers BER and bursts but not CER here:** Ch4 21 dB BER 4.25e-3 → 2.48e-3, mean
  burst 3.4 → 1.08 (max 32 → 4), yet the RS-symbol error rate rises 1.83% → 1.97% and CER
  9.72% → 12.9%. A short burst often lies within one or two RS symbols (5 PAM4 symbols each);
  precoding turns it into entry and exit errors that can fall in two RS symbols. With ideal
  decisions precoding doubles BER, as expected (each error becomes two).
- **Limits:** high pre-FEC BER only (10⁻³ range). At the 18 / 22 dB points the predicted CER is
  10⁻⁷–10⁻⁹, beyond 10⁴ codewords; those rows are upper bounds. The low-BER regime is what the
  FPGA measures (Phase D).
