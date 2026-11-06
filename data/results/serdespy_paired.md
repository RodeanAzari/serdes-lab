# serdespy_paired.csv

- **Command:** `make xcheck` (`scripts/serdespy_xcheck.py`); deterministic
- **Commit:** `0837fd4`
- **Tools:** Python 3.14.4, numpy 2.5.4, scipy 1.18.1, serdespy 1.0
- **Method:** per chunk (5e5 symbols, 10 chunks per point), rebuild `run_link`'s exact payload
  bits and noise samples, give the noisy ADC samples to serdespy (TX via its Gray coder and
  `Transmitter`; `FFE_BR`, `pam4_DFE_BR`, `grey_decode`), count bit errors over `run_link`'s
  guard window. serdespy's `same`-mode FFE is offset by (16−1)//2 − 3 = 4 symbols; corrected.

**Interpretation:** identical bit-error counts in all 80 chunks (8 points, 42–13,772 errors
per point). The model's FFE alignment, vectorised 1-tap DFE (prefix composition) with error
propagation, slicer thresholds and Gray demap match an independent sequential implementation
exactly. Not covered here: the pulse, MMSE taps and SNR → σ (shared inputs); the noise
generator is exercised only by the statistical run.
