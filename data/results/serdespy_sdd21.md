# serdespy_sdd21.csv

- **Command:** `make xcheck` (`scripts/serdespy_xcheck.py`); deterministic
- **Commit:** `0837fd4`
- **Tools:** Python 3.14.4, numpy 2.5.4, scikit-rf 2.2.0, serdespy 1.0
- **Input:** raw THRU `.s4p` for Ch2/Ch4 (`data/MANIFEST.md`), not committed
- **Method:** serdespy `four_port_to_diff` (matched 50 Ω source/load, so H = SDD21/2; compared
  as 2H) vs `model.channel.load_sdd21`, over f ≤ 67 GHz (usable bandwidth, ADR 0001).

**Interpretation:** IL at 53.12 GHz identical to 3 decimals (19.267 / 31.375 dB). Max
residual 0.05 dB / 0.08° is fully explained: serdespy's port reorder (`four_port_to_diff.py`
lines 56–57) puts S32 where S23 belongs. Substituting S32 for S23 in our formula reproduces
serdespy to 1.6e-16; |S23 − S32| ≤ 1.0e-3 is the measured data's non-reciprocity. Our formula
is the textbook mixed-mode one; no change.
