Project ID: P4
@~/fpga-coord/PROTOCOL.md

# CLAUDE.md — Project 4: Open SerDes Lab

## What this is

The digital half of a **200 Gb/s-per-lane PAM4 SerDes receiver** in SystemVerilog on the Digilent Arty A7-100T. It runs against **real IEEE 802.3dj channel data**, fast enough to measure post-FEC error statistics that software simulation can't reach. The equalizer's adaptation loop runs as **firmware on the Project 1 RV32I core**.

```
payload ─▶ KP4 RS(544,514) encode ─▶ Gray PAM4 (+ optional 1/(1+D) precoder)
        ─▶ CHANNEL: pulse-response FIR (802.3dj S-params, TX FIR + CTLE folded in) + Gaussian noise + ADC quantization
        ─▶ RX FFE ─▶ DFE or 4-state MLSE ─▶ slicer ─▶ precoder inverse ─▶ Gray demap ─▶ KP4 RS decode
        ─▶ counters: pre-FEC BER · symbol errors per codeword · burst lengths · post-FEC CER
             ▲ error×data correlators (RTL) ─▶ RV32I firmware: sign-sign LMS ─▶ tap registers
```

**Portfolio project:** evidence (measured numbers, plots, media, an in-depth README) is half the deliverable. **A phase without its numbers and media is not done** (buildplan §13).

**Novelty wording:** README says *"the first open-source … that I'm aware of"*, with prior work cited (buildplan, "Research question"). Never claim "first" outright.

**Full build spec:** [`docs/buildplan.md`](docs/buildplan.md) — signal/channel spec (§6), architecture (§7), golden model (§8), verification (§9), phases and DoD (§11), out of scope (§12), portfolio deliverables (§13). Not imported; read the relevant section before starting a block or phase.

---

## Current status

<!-- Claude: update as phases complete. Never mark a phase done until its buildplan §11
     checklist passes in full, INCLUDING the portfolio items. -->

| Phase | Status | Key result |
|---|---|---|
| A — Python model + sizing | IN PROGRESS | Ch2/Ch4 pulse responses ([csv](data/results/channels.csv)) |
| B — TX + channel + noise | NOT STARTED | — |
| C — RX equalization (fixed taps) | NOT STARTED | — |
| D — KP4 decode + statistics | NOT STARTED | — |
| E — Adaptation firmware | NOT STARTED | — |
| F — MLSE + portfolio | NOT STARTED | — |

---

## Rules for Claude

- **Follow the imported fpga-coord protocol** at the start and end of every session.
- **Never invent a number.** Unmeasured values are `[TBD]`. Every reported number links to its CSV in `data/results/`.
- **Golden model before RTL.** No RTL block is written until the Python model produces its expected output, in the same fixed-point formats.
- **BER claims need errors.** Report every BER/CER with the number of errors and bits observed and a confidence interval. Fewer than 100 errors: report an upper bound, not a value.
- **"Done" means verified.** A block is done when its tests pass, `make lint` is clean and `make ci` passes locally.
- **Record decisions.** Every architectural choice gets an ADR in `docs/decisions/`, including rejected alternatives.
- **Portfolio moments.** At the end of every phase and whenever something striking works (first BER curve matching the model, first KP4 decode, first adaptation convergence): generate the plots yourself, list the physical captures for the user, add them to `docs/portfolio-todo.md`, and wait for the user before marking the phase done.
- **Lab notebook:** append a `docs/log.md` entry at the end of every session.
- **Progress file:** read `progress.md` at session start; keep it short and current.
- **Stay in scope (buildplan §12).** Say so first if a task drifts.
- **Keep always-loaded docs lean.** CLAUDE.md ≤ 250 lines and `progress.md` ≤ 150 lines. Trim them at the end of every session that edits them, and at once if either is over. Keep only what a future session would get wrong without being told (current state, open work, rules, traps that cost real time). Cut finished-work narratives, dated history, reasons the code, tests, commits or reports already record, and duplicates of other docs. Move what must be kept but isn't needed every turn (the spec, append-only measurement tables, long verification detail) to files that aren't imported, such as `docs/buildplan.md` and `docs/measurements.md`, and leave a one-line pointer. Never edit the shared `~/fpga-coord/PROTOCOL.md`; propose trims to the user instead.

---

## 1. Dependencies (fpga-coord)

| Needs | Tag | Gate | Until then |
|---|---|---|---|
| `tb-common` | `tb-common-v0.1` | Soft | Import Project 2's `tb/common/` by path; never copy |
| `fpga-eth-core` TX | `eth-core-v0.2` | **Hard** for streaming stats/eye samples | UART counters |
| `fpga-rs-core` | `rs-core-v1.0` | **Hard** for Phase D | Count symbol errors per codeword without decoding |
| SoC register bus | `soc-v1.0` | **Hard** for Phase E | Python model of the adaptation loop |
| SoC M extension | `soc-v2.0` | Soft | Sign-sign LMS needs no multiply |

All consumed as git submodules pinned to tags (`rtl/eth/`, `rtl/rs/`, `rtl/soc/`). **This project owns no shared block.** If it needs a change in one, file a request.

**Phases A–C need no gate**, so they can run alongside Project 3.

---

## 2. Hardware

**Board:** Digilent Arty A7-100T, `xc7a100tcsg324-1` (free Vivado).

| Resource | Available | Use here |
|---|---|---|
| **DSP48E1** | **240** | **The binding constraint**: RX FFE multipliers, MLSE metrics |
| LUTs / FFs | 63,400 / 126,800 | Channel FIR (multiplierless), slicers, counters, RS decoder |
| Block RAM | 135 × BRAM36 | Histograms, pulse-response taps, sample capture |
| Ethernet | 10/100 via `fpga-eth-core` | Stats and subsampled samples to the host |
| UART | USB-UART | Fallback counters, control |

**No analog front end is used.** Everything after the transmitter is emulated digitally. That's the design, not a limitation to hide: say so plainly in the README.

---

## 3. Toolchain and build process

| Tool | Use |
|---|---|
| Vivado ML Standard (batch Tcl) | Synthesis, implementation, ILA |
| Verilator | Lint, simulation |
| cocotb + cocotb-coverage + `tb-common` | Testbenches, coverage |
| SymbiYosys | Formal on small blocks (buildplan §9.3) |
| Python 3.11+ (NumPy, SciPy, scikit-rf, matplotlib, pytest) | Channel model, golden model, analysis |
| serdespy | **Independent** cross-check at high BER, not ground truth |
| RISC-V GNU toolchain (`riscv32-unknown-elf-gcc`) | Adaptation firmware |

### Makefile targets — all must work from a clean checkout

```
make setup         # .venv + pinned requirements.txt; git submodule update --init
make channels      # download/convert 802.3dj channels → data/channels/*.npz (pulse responses)
make model-test    # pytest: golden model, fixed-point equivalence, noise tails
make lint          # verilator --lint-only -Wall, zero warnings
make sim           # fast cocotb regression (< 5 min)
make sim-full      # long bit-exact runs vs. the model
make formal        # SymbiYosys (buildplan §9.3)
make fw            # build adaptation firmware
make synth impl prog
make ber CH=<channel> SNR=<range> CFG=<eq config>   # hardware BER campaign → data/results/
make plots         # regenerate every plot from data/results/
make reports       # copy timing + utilization into docs/reports/<tag>/
make ci            # everything CI runs, locally
make clean
```

- **Vivado runs in batch mode** from `syn/` Tcl. Never commit project directories. No GUI-only steps.
- **Vivado isn't in hosted CI.** Run it locally and commit reports for every tagged milestone.
- **Timing closure is required.** No milestone is tagged with negative slack.
- **CI on every push:** `make lint sim formal model-test fw`, plus ruff. A broken CI gets fixed first.

---

## 4. Repository layout

```
├── CLAUDE.md  README.md  progress.md
├── rtl/
│   ├── soc/        # submodule: SoC at soc-v1.0 (core + register bus)
│   ├── eth/        # submodule: fpga-eth-core at eth-core-v0.2
│   ├── rs/         # submodule: fpga-rs-core at rs-core-v1.0
│   ├── tx/         # payload PRBS, RS encode wrapper, Gray map, precoder
│   ├── channel/    # multiplierless pulse-response FIR, noise generator, ADC quantizer
│   ├── rx/         # FFE, DFE, MLSE, slicer, demap
│   ├── adapt/      # error×data correlators, tap register bank
│   ├── stats/      # BER/CER counters, histograms, burst detector, sample capture
│   └── top/
├── fw/             # C adaptation firmware for the RV32I core
├── tb/cocotb/  tb/formal/
├── model/          # Python channel + transceiver golden model (fixed-point mirror)
├── analysis/       # BER/CER stats, confidence intervals, plots, dashboard
├── syn/  constr/  scripts/
├── data/
│   ├── channels/   # converted pulse responses (small .npz); raw .s4p NOT committed
│   ├── results/    # CSVs behind every number, each with a sidecar .md
│   └── MANIFEST.md # channel files: source URL, contribution name, SHA-256
├── docs/
│   ├── buildplan.md  design.md  decisions/  fixed-point.md  log.md  portfolio-todo.md
│   ├── reports/  media/
├── Makefile
└── .github/workflows/
```

---

## 5. Coding standards

### SystemVerilog
- `logic` only; `always_ff` / `always_comb`; `<=` in sequential, `=` in combinational. Every file starts with `` `default_nettype none `` and restores it at the end.
- Synchronous active-high reset, synchronized per domain. Reset control state only.
- No latches, no magic numbers. **Parameterize:** parallelism `P` (symbols per clock), FFE taps, channel length, bit widths, DFE taps, MLSE states.
- One module per file; named ports; suffixes `_i`/`_o`/`_n`/`_q`/`_d`; parameters `UPPER_CASE`.
- AXI4-Stream style between blocks; AXI4-Lite for registers (the SoC's template).
- **Fixed point:** every signal's Q-format lives in `docs/fixed-point.md`. Explicit rounding and saturation, never silent wrap. The Python model uses identical widths, so RTL and model are **bit-exact**.
- **Two independent PRNGs:** payload and noise come from different generators with different polynomials and seeds. Correlated generators bias BER.
- DSP inference checked in the synthesis report: FFE multipliers must map to DSP48E1.
- Every pipeline stage documents its latency in cycles in its header.
- Zero Verilator `-Wall` warnings; waivers inline and justified.

### Python
- 3.11+, type hints, `mypy --strict` on `model/`, `ruff`, `pytest`. The model is deterministic and seeded, with no plotting or I/O side effects.

### C firmware
- C11, `-Wall -Wextra -Werror`, no dynamic allocation, fixed-width integer types. Register access through one generated header from the register map (single source of truth: `docs/registers.md` or an RDL file).

### Commits and tags
- Small, phase-tagged commits, e.g. `channel: multiplierless FIR, bit-exact vs model for P=4`.
- Tags: `v0.1-model`, `v0.2-channel`, `v0.3-rx`, `v0.4-kp4`, `v0.5-adapt`, `v1.0`.

### Required ADRs
Parallelism `P` and tap counts (from the DSP budget) · noise generator method · fixed-point formats · DFE vs. MLSE structure · precoding · adaptation split (hardware correlators vs. firmware loop) · channel-model construction (sampling phase, truncation length) · codeword interleaving assumption.

---

## 6–9, 11–13. Build spec → [`docs/buildplan.md`](docs/buildplan.md)

Same section numbers there. Rules from it that every session needs:
- **Gray mapping:** 00 → −3, 01 → −1, 11 → +1, 10 → +3. **Precoder 1/(1+D) mod 4:** verified against 802.3-2022 135.5.7.2 (ADR 0006); one enable drives TX and RX (lockstep).
- **KP4:** RS(544,514) over GF(2¹⁰), t = 15. One RS symbol = 5 PAM4 symbols: track alignment explicitly. Report non-interleaved and 2-way interleaved (§6.2).
- **Channels:** raw `.s4p` never committed; name/URL/SHA-256 in `data/MANIFEST.md` (§6.3).
- **Noise:** no sum-of-uniforms (CLT) generator. Validate tails to ±7σ on hardware before trusting any BER (§6.4).
- **Phase DoD** always includes README updated, `docs/log.md` entry, the phase's media, and the user confirming physical captures (§11).
- **Out of scope:** analog (CTLE/CDR/ADC hardware), real 106 GBd signals, optical PMDs, multi-lane/PCS, re-implementing the RS decoder (§12).
- **Media:** `docs/media/YYYY-MM-DD_phase-x_description.ext`, plots only via `make plots`; every result CSV has a sidecar `.md` (commit, command, tool versions, channel/seed, interpretation); GIFs ≤ 8 MB (§13.2).

---

## 10. Measurement discipline

- Every BER/CER point: **bits tested, errors counted, 95% confidence interval**.
- Fewer than 100 errors at a point → report as an upper bound.
- Every result file records: channel, SNR definition, equalizer config, precoder, interleaving assumption, seed, bitstream tag, firmware hash.

---

## 14. Known failure modes

- **CLT noise generator:** no tails → fake-good BER
- **Wrong pulse-response sampling phase:** the whole channel looks easier or harder than reality
- **Correlated payload and noise PRNGs:** biased BER
- **Gray mapping or precoder mismatch** between TX and RX: errors that look like a bad channel
- **RS symbol misalignment** (5 PAM4 symbols per RS symbol): every codeword fails
- **FFE saturation:** errors that look like noise
- **DFE feedback loop limiting Fmax:** unroll or speculate; don't silently lower the clock
- **MLSE metric overflow** after long runs
- **BER from too few errors:** report bounds
- **DSP inference failure:** multipliers in LUTs, timing fails
- **Editing a submodule in place:** request changes from the owner instead

---

## 15. Working principles

- **Model first, bit-exact always.**
- **Validate the noise before trusting any BER.**
- **Distributions and confidence intervals, never single numbers.**
- **State limitations plainly**: this is an emulator, and that's its strength.
- **Evidence is part of done.**
