# ADR 0009: Hardware noise histogram (Phase B noise validation on the board)

**Status:** accepted 2026-11-09 (Ethernet readout and the overall plan: user decision; details below
proposed with it). **Phase:** B. Implements ADR 0003 step 3 as revised by ADR 0005.
RTL: `rtl/stats/hist_bram.sv`, `rtl/top/noise_ctrl.sv`, `rtl/top/noise_hist_top.sv`.

## Requirements (ADR 0003, ADR 0005, buildplan §6.4)

- ~4 × 10¹³ samples from **all 8 lanes** (P = 4 × 2 instances) at σ_reg = 1581 (σ = 49.406, the
  Ch4 1e-12 point): 10⁹ samples/s, ~11.1 h.
- Statistics: chi-square vs the exact model pmf (`pmf_n`, all bins merged to ≥ 5 expected) and vs
  the Gaussian on |n| ≥ 4σ only; log plot to ±7σ with the model pmf.
- The hardware must be shown to run the **same** generator as the model, not just a similar one.

## Decision

| Item | Choice |
|---|---|
| Board design | Dedicated `noise_hist_top`: 8 × lfsr258 → 2 × `noise_gen` (P = 4) → 8 histograms. No TX/FIR: the noise path is what is under test, and `channel_top` adds it to s bit-exactly (cocotb) |
| What is binned | The signed noise sample n per lane (not \|n\|): the pmf test folds to \|n\|; keeping the sign adds a symmetry check (n vs −n) for free |
| Bins | 1024 per lane, index = clamp(n, −512, 511) + 512. At σ_reg 1581, \|n\| ≤ 452 (9.155σ), so the clamp never engages; it exists so other σ cannot wrap |
| Counters | 48 b per bin, **saturating** (never wrap). Peak bin (n = 0) ≈ 0.81% of 5 × 10¹² per lane = 4 × 10¹⁰ < 2⁴⁸ = 2.8 × 10¹⁴. 2 BRAM36 per lane, 16 total |
| Update | One read-modify-write per lane per clock: BRAM read latency 1, write next clock, **forwarding** for a repeat of the bin 1 or 2 samples later (the BRAM collision behaviour is never relied on) |
| Sample counter | 64 b words-per-lane counter; Σ bins must equal it (checked on the host) |
| Run control | Run gate on the lfsr258 enables + histogram valid. **Pause/resume keeps the generator state**, so a paused-and-resumed run is the same sample stream as an unbroken one. Optional run length N (words per lane): stops exactly at N |
| Readout | UDP via `fpga-eth-core` at `eth-core-v0.2` (git submodule `rtl/eth/`). Stateless request/reply: host sends `READ(lane, chunk)`, board replies with that chunk (128 bins × 6 B + header). Lost packets are re-requested; no board-side retransmit logic. Reads are refused while running (no torn snapshots) |
| Commands | `CONFIG` (σ_reg, run length, 8 × 320 b seeds; loads seeds, clears histograms), `START`, `STOP` (pause), `READ(lane, chunk)`, `STATUS` (running, words done, flags, build id). One opcode byte + fields; format in `docs/registers.md` |
| Checkpoints | Host pauses, reads all 64 chunks, resumes, about once per hour: a crash or power loss costs ≤ 1 h, and the partial histograms show tail convergence |
| Clock | MMCM 100 → 125 MHz core (noise, histograms, eth core: built and timed at 125 MHz by its owner) + 25 MHz PHY reference via ODDR, one core domain |
| UART | Not built. Fallback only if the Ethernet path fails on this board |

## End-to-end exactness check (before the overnight run)

Run exactly N = 2²² words per lane from host-chosen seeds and compare each lane's histogram
**bin for bin** with `np.bincount` of `model.noise.noise(lfsr258_words(...))` (~3.5 min of model
time; 2²⁴ would be ~14 min). A match proves the board runs the RTL that simulation showed
bit-exact on every segment (BRAM tables, DSP rounding, lane seeds, readout), so the model's
exact tail proof (ADR 0005) applies to the hardware. 3.4 × 10⁷ samples reach only ~5.5σ, which is
why the deep segments rest on the simulation, not on this run. Any mismatch blocks the overnight run.

ADR 0003 step 4 (lag 1…16 and cross-lane correlation) is then computed on model samples
(≥ 10⁹), which the exactness check makes equivalent to hardware samples; no sample capture
block is built.

## Verification

- `hist_bram` (cocotb vs `np.bincount`): random streams; adversarial same-bin runs (every bin
  repeated at distance 1, 2, 3, alternating pairs); gated valid; clamp at both ends; counter
  saturation via a parameter-reduced counter width (COUNT_W = 4). Bug injection: no forwarding,
  forwarding at one distance only, wrap instead of saturate, off-by-one index.
- `noise_ctrl` (cocotb at the UDP-payload AXI-Stream level, between `udp_rx` and `udp_tx`):
  every command, malformed and short packets, READ while running refused, pause/resume
  producing the same histogram as an unbroken run of the same length.
- Full `noise_hist_top` timing closure at 125 MHz (no negative slack: CLAUDE.md §3).
- Formal (buildplan §9.3, counter saturation) once `make formal` exists; until then the
  COUNT_W = 4 cocotb case.

## Rejected alternatives

- **Histogram of \|n\| only:** loses the symmetry check; signed bins cost nothing extra.
- **36 b counters, 1 BRAM36 per lane:** peak bin 4 × 10¹⁰ vs 6.9 × 10¹⁰ capacity, 1.7× margin
  for one 11 h run; a longer run would saturate. 8 more BRAM36 (of 135) buys a 7000× margin.
- **One shared histogram for all lanes:** 8 updates per clock into one table needs banking
  plus a merge; per-lane tables are simpler and also give per-lane evidence.
- **Free-running readout (snapshot while counting):** torn reads; pausing is free because the
  generator state is held.
- **Board-side streaming of all chunks per request:** needs pacing and retransmit logic in RTL;
  the stateless per-chunk request moves that to a few lines of host Python.
- **UART readout:** 48 KB per checkpoint is ~4 s at 115200 Bd (acceptable), but the dashboard
  (buildplan §7.4) needs Ethernet anyway; one readout path is less to build.
- **Sample-capture block for the autocorrelation test:** redundant once the exactness check
  ties the hardware to the model bit for bit.
