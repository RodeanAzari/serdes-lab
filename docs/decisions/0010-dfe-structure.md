# ADR 0010: 1-tap DFE at P = 4: loop-unrolled (speculative) decisions

**Status:** accepted 2026-11-10 (buildplan §7.1: "unroll or speculate if it limits Fmax, and
record which"). Timing numbers are [TBD] until OOC synthesis. **Phase:** C.
Model: `model/fixed.py` `dfe1_int` (sequential reference). RTL: `rtl/rx/dfe_slicer.sv`.

## Context

The 1-tap DFE decides d[k] = slice(z[k] − b · level(d[k−1])), thresholds −t2, 0, +t2
(docs/fixed-point.md). At P = 4 symbols per clock (ADR 0002) the four decisions of one word
form a chain, and the last one feeds the next word's first: a 4-deep loop that must close in
one 8 ns clock (125 MHz).

Per link of a direct chain: a 4:1 mux of {−3b, −b, +b, +3b} on the previous decision, a 12 b
subtract, three 12 b compares, and the 2 b decision. On Artix-7 −1 that is roughly a LUT, two
carry chains and their routing, ~2.5–3 ns per link (estimate), so ~10–12 ns for four links:
it does not fit in 8 ns.

## Decision

**Speculate on the previous decision.** For every symbol, compute all four candidate decisions
in the feed-forward pipeline, one per possible previous level:

    cand[k][j] = slice(z[k] − b · level(j)),  j = 0..3   (4 × 3 compares per symbol, no DSP)

The loop then keeps only the selection: d[k] = cand[k][d[k−1]], a 4:1 mux of 2-bit values
with a 2-bit select. Each output bit is a 6-input function: one LUT6 per bit per link, so
the loop is 4 LUT levels per clock plus routing (estimate ~3 ns), independent of the data
width. Bit-exact with the sequential DFE by construction (same slice of the same integer).

The loop register is the word's last decision. It is control state for the loop, so it is
reset (to `D_INIT`) and loads only on `valid_i`. The model starts the sequential DFE from the
same `d_init` at the first symbol the RTL accepts.

## Consequences

- Cost per symbol: 4 subtracts and 12 compares (12 b) in LUTs, instead of 1 and 3. At P = 4,
  2 instances: ~100 adders/comparators in total, small against 63,400 LUTs.
- The pre-computation is pipelined freely; only the 4-LUT mux chain is in the loop.
- MLSE (Phase F) has its own add-compare-select loop and does not reuse this.
- Scales to larger P only linearly in loop depth (P LUT levels); beyond ~P = 8 a parallel-prefix
  composition of the 4 → 4 maps would be needed. Not needed at P = 4.

## Rejected alternatives

- **Direct feedback chain:** ~10–12 ns at P = 4 (estimate above); would force ~80 MHz or a
  two-clock loop, which is no longer a 1-tap DFE on consecutive symbols.
- **Lower the clock to close the direct loop:** CLAUDE.md §14 forbids silently lowering the
  clock; halves the emulation speed for nothing the speculative form cannot do.
- **Parallel-prefix (look-ahead) composition of the per-symbol 4 → 4 maps:** log₂P levels
  instead of P, but each level composes 4-entry tables (more LUTs and routing); at P = 4 it
  saves at most 2 LUT levels. Kept as the fallback if the chain fails timing.
- **Interleaved independent DFEs (each fed back over P symbols):** wrong algorithm: the
  feedback must use d[k−1], not d[k−P].
