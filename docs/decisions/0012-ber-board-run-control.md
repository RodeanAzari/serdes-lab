# ADR 0012: BER board run control and counter readout

**Status:** accepted 2026-11-11 (proposed by Claude, run-length rule open for the user to
revisit). **Phase:** C. RTL: `rtl/top/link_ctrl.sv`, `rtl/top/ber_core.sv`, `rtl/top/ber_top.sv`.
Protocol: `docs/registers.md`. Builds on ADR 0009 (UDP control) and ADR 0011 (BER checker).

## Context

`link_core` takes all its configuration statically while in reset and, once out of reset, runs
every clock with free-running 64 b saturating counters (bits compared, bit errors, symbol
errors). The board campaign needs: the host loads a configuration (channel taps, seeds, σ,
equalizer registers, K, holdoff), starts a run, reads consistent counters while it runs, and
gets a run of a known exact length so that a short hardware run can be compared **count for
count** with the bit-exact model (the same exactness check as the noise histogram, ADR 0009).

## Decision

- **No change to `link_core` or `ber_check`.** A new controller `link_ctrl` (UDP payload in and
  out, like `noise_ctrl`) holds the link in reset whenever it is not running, so all
  configuration registers only change while the link is in reset.
- **Run length R in bits compared** (64 b, 0 = unbounded), a multiple of 2P (refused
  otherwise), so the bits counter hits R exactly.
- **Snapshot counters.** While running, the controller copies bits, bit errors, symbol errors
  and the FIFO error flag into snapshot registers every clock, all on the same edge. When the
  live bits counter equals R, the run stops on that edge: the snapshot then holds exactly R
  bits and the error counts of exactly those bits. STOP ends a run the same way at an arbitrary
  point. Every reply carries the snapshot, so STATUS while running is a consistent mid-run
  reading.
- **START always starts a new run from reset.** With the same CONFIG it repeats the identical
  run (same seeds): a free repeatability check on hardware. New seeds need a new CONFIG.
  There is no pause/resume.
- **CONFIG is validated before anything is applied** (code 3 otherwise): σ < 2¹⁷, PRBS seed
  nonzero and < 2³¹, every lfsr258 seed word valid, R mod 2P = 0, K ≤ m0 (so `link_core`'s
  config-error flag can never be set from the host), shift < 2^SH_W, and every signed field
  (taps, coefficients, b) and unsigned field (t2) fits its RTL width. Fields are whole bytes,
  signed ones sign-extended: a host packing bug is refused instead of silently truncated.
- **Own UDP port 26401** (noise histogram: 26400), so a host script talking to the wrong
  bitstream gets no reply instead of a misread one. Board IP and MAC unchanged.

## Consequences

- Short runs are exactly comparable with the model (`test_ber_core`, and the host `exact`
  check on the board). Long runs give (bits, errors) for the CI; R sets the run length, or the
  host stops an unbounded run once it has enough errors.
- Throughput 2P bits per clock = 1 Gb/s at P = 4 and 125 MHz: 1e-6 with 100 errors needs 10⁸
  bits (0.1 s); 1e-9 needs 10¹¹ (100 s); 1e-12 needs ~28 h with one link instance.
- A run of R bits takes R / 2P clocks after the link's ~27-word warm-up and the holdoff.

## Rejected alternatives

- **Run length in clocks or TX words:** the counted bits then depend on the pipeline latency
  and holdoff; the model comparison would need that latency.
- **Gate the counters in `ber_check` (count enable):** changes a verified block for no gain;
  the snapshot gives the same exact stop.
- **Pause/resume as in the noise board:** the link has a TX → RX pipeline and a DFE state; a
  clean pause needs a valid gate through every block. Not needed for BER.
- **Reuse port 26400:** the noise host script would misparse BER replies.
