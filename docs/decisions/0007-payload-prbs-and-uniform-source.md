# ADR 0007: Payload PRBS and noise uniform source (bit-exact definitions)

**Status:** accepted 2026-11-08 (PRBS31: user accepted the recommendation). **Phase:** B. Model: `model/prng.py`,
tests: `model/tests/test_prng.py`. Noise generator method: ADR 0003.

## Decision

| Item | Choice |
|---|---|
| Payload generator | **PRBS31**, a[n] = a[n−28] ⊕ a[n−31] (x³¹ + x²⁸ + 1, primitive), the 802.3 test-pattern polynomial |
| Payload seed | 31-bit nonzero; a[0..30] = seed bits 0..30; stream order a[0], a[1], … |
| Noise uniform source | L'Ecuyer **lfsr258** exactly as the reference code: per step, update all 5 components, output y1 ⊕ … ⊕ y5 (64 b) |
| Lanes | One lfsr258 per noise lane; symbol k of an instance uses lane k mod P, step k div P |
| Seeds | 5 × 64 b per lane, computed on the host (`lane_seeds`, SplitMix64, bit 63 forced so every word is legal); the RTL loads them, it does not derive them |

Independence (CLAUDE.md §5): different generators, polynomials (PRBS31 vs. degrees 63/55/52/47/41)
and seeds. Distinct primitive minimal polynomials make the payload and noise sequences linearly
independent over F₂. Lanes are offsets in one 2²⁵⁸ − 1 period: for 16 lanes and 2⁵⁰ steps each
(~10¹⁵), the chance that any two lanes overlap is ≲ 16² · 2⁵⁰ / 2²⁵⁸ = 2⁻²⁰⁰.

Not decided here: the bit order from the payload stream into 10-bit RS symbols (decided with the
RS encoder model, which is the next step).

## Evidence

- PRBS31: matches a naive recurrence across chunk boundaries; Berlekamp–Massey (`galois`)
  recovers exactly x³¹ + x³ + 1 (connection form); polynomial primitive.
- lfsr258: constants match the reference source text (all 25, one-off check 2026-11-08);
  each component word equals the Tausworthe sequence a[i+k] = a[i] ⊕ a[i+q] advanced by s per
  step (independent bit-serial model); all 5 trinomials primitive, gcd(s, 2ᵏ−1) = 1; output
  linear complexity exactly 258; vectorized and pure-int forms agree.
- Correlation (model, 2¹⁶ samples, |r| < 5/√N): lags 1–16, all 28 lane pairs, noise sign vs. payload.
- **Bit-exact vs. the reference C code** (`scripts/lfsr258_ref.sh` → `model/tests/data/lfsr258_ref.txt`,
  source SHA-256 pinned): 4 seed sets (reference default, minimum legal seed, 2 lane seeds),
  words 0–63 and 19,999.
- Injected bugs: 9 in the first round, 7 caught, 1 equivalent mutant (`|` vs `^` on
  non-overlapping bits). A wrong constant in the shared table (s or q) passes every other test,
  because the independent model reads the same table; the reference vectors catch all 3 tried.

## Rejected alternatives

- **PRBS23 / PRBS15 payload:** shorter periods; PRBS31 costs the same LUTs.
- **Same generator type for payload and noise (e.g. two lfsr258):** allowed with distinct seeds,
  but different generator families remove any doubt about correlated sequences.
- **Seeds derived in RTL from one 32 b register:** SplitMix64 needs 64 b multiplies (≈ 16 DSP);
  loading 320 b per lane over the register bus is free.
- **xoshiro/PCG uniform source:** PCG needs multiplies; ADR 0003 already chose lfsr258 (XOR/shift only).
