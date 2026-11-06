# ADR 0002: Parallelism P, FFE taps and instance count (DSP sizing)

**Status:** accepted 2026-11-06 (user decision). **Phase:** A. Revisit with real synthesis numbers.

## Decision

| Item | Choice | Why |
|---|---|---|
| Parallelism | **P = 4** PAM4 symbols per clock | One `fpga-rs-core` decoder takes 1 RS symbol/clock = 5 PAM4 symbols/clock; P = 4 needs 0.8, so one decoder per instance keeps up. 1-tap DFE / 4-state MLSE loop only 4 deep per clock |
| FFE | **N = 16** taps, main-tap position a parameter (default `N_PRE = 4`, best on both channels) | ≤ 0.01 dB from a 32-tap FFE on Ch2 and Ch4 ([`ffe_sizing.csv`](../../data/results/ffe_sizing.csv)); same length as the MMSE reference used in every model result so far |
| DFE | 1 tap (buildplan §7.1) | Shift/add on ±1/±3 decisions: no DSP |
| Instances | **2** independent emulators | Two SNR points (or DFE vs MLSE) in parallel |
| Clock | 125 MHz planning target | Buildplan §7.5 estimate. Real Fmax recorded after synthesis |
| Throughput | 0.5 Gsym/s = 1 Gb/s per instance, 2 Gb/s total | 10¹² bits ≈ 17 min per instance (planning) |

All of P, N, N_PRE and instance count stay RTL parameters (CLAUDE.md §5).

## DSP budget (planning estimates, not measurements)

| Block | Per symbol | ×P×instances | DSP48E1 |
|---|---|---|---|
| RX FFE | N = 16 multiplies | ×4×2 | 128 |
| Noise generator | ~3 (method open: separate ADR) | ×4×2 | ~24 |
| MLSE (Phase F) | 2: branch metric reduces to z·h0, z·α; levels are shifts | ×4×2 | ~16 |
| Channel FIR, DFE, correlators, slicer | 0 (inputs are ±1/±3 or signs) | | 0 |
| **Total** | | | **~168 / 240 (70%)** |

72 DSP headroom absorbs a costlier noise generator. Must be confirmed: FFE multipliers map
to DSP48E1 in the synthesis report (CLAUDE.md §14).

## FFE length vs. performance

Input SNR needed for Gaussian-predicted BER 2.4e-4, penalty vs. N = 32
([`ffe_sizing.csv`](../../data/results/ffe_sizing.csv)):

| N | 8 | 10 | 12 | 16 |
|---|---|---|---|---|
| Ch2 | 0.46 dB | 0.23 dB | 0.01 dB | 0.00 dB |
| Ch4 | 0.77 dB | 0.29 dB | 0.12 dB | 0.01 dB |

Against the truncated emulator channel (ADR 0001), so it says nothing about long reflection
tails a real channel would add.

## Rejected alternatives

- **P = 4, N = 12, 3 instances** (~204 DSP, 85%, 3 Gb/s): 0.12 dB on Ch4, little headroom for
  the noise generator, and LUT/BRAM for three RS decoders unknown until `rs-core-v1.0`.
- **P = 4, N = 12, 2 instances** (~136 DSP): most headroom, but departs from the 16-tap
  reference for 0.12 dB on Ch4 and no throughput gain.
- **P = 8, N = 16, 1 instance** (~168 DSP, 2 Gb/s in one stream): needs two RS decoders per
  instance and an 8-deep DFE/MLSE chain per clock; one SNR point at a time.
- **N = 24 or 32**: no measurable gain (0.00 dB) for 50–100% more FFE DSPs.
- **Packing two multiplies per DSP48E1**: possible for narrow operands, but complicates
  bit-exactness and DSP inference; revisit only if the budget is exceeded.
