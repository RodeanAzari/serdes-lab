Project ID: P4
@~/fpga-coord/PROTOCOL.md

# CLAUDE.md — Project 4: Open SerDes Lab

## What this is

The digital half of a **200 Gb/s-per-lane PAM4 SerDes receiver** in SystemVerilog on the Digilent Arty A7-100T. It runs against **real IEEE 802.3dj channel data**, fast enough to measure post-FEC error statistics that software simulation can't reach. The equalizer's adaptation loop runs as **firmware on the Project 1 RV32I core**, the way production SerDes IP runs adaptation on an embedded microcontroller.

```
payload ─▶ KP4 RS(544,514) encode ─▶ Gray PAM4 (+ optional 1/(1+D) precoder)
        ─▶ CHANNEL: pulse-response FIR (802.3dj S-params, TX FIR + CTLE folded in) + Gaussian noise + ADC quantization
        ─▶ RX FFE ─▶ DFE or 4-state MLSE ─▶ slicer ─▶ precoder inverse ─▶ Gray demap ─▶ KP4 RS decode
        ─▶ counters: pre-FEC BER · symbol errors per codeword · burst lengths · post-FEC CER
             ▲ error×data correlators (RTL) ─▶ RV32I firmware: sign-sign LMS ─▶ tap registers
```

**This is a portfolio project.** Working RTL is half the deliverable. The other half is evidence: measured numbers, plots, screenshots, video and a full, in-depth README. §13 is mandatory, not optional polish. **A phase without its numbers and media is not done.**

**Duration:** 12–16 weeks. **Languages:** SystemVerilog (RTL), Python/NumPy/scikit-rf (channel model, golden model, analysis), C (RV32I adaptation firmware).

**Novelty, stated precisely.** U of T built an FPGA platform for post-FEC BER analysis of 200G links (Barrie, Yang, Shakiba, Carusone, MWSCAS 2024). It counts symbol errors per KP4 codeword but doesn't run the RS decoder on the FPGA, and no open-source release was found. serdespy (U of T) is Python only. **New here:** a bit-true equalizer + MLSE + full KP4 decoder in the hardware loop, against public 802.3dj channels, with adaptation firmware on a custom RISC-V core, released openly. README wording: *"the first open-source … that I'm aware of"*, with prior work cited. Never claim "first" outright.

**The research question:** DFE error propagation produces **burst** errors, and bursts interact with RS decoding in ways statistical tools approximate. A bit-true emulator measures burst-length distributions and post-FEC CER directly, for DFE vs. MLSE, with and without precoding, and compares them to the independent-error prediction.

---

## Current status

<!-- Claude: update as phases complete. Never mark a phase done until its §11 checklist
     passes in full, INCLUDING the portfolio items. -->

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
- **Stay in scope (§12).** Say so first if a task drifts.

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
| SymbiYosys | Formal on small blocks (§9.3) |
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
make formal        # SymbiYosys (§9.3)
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
│   ├── design.md  decisions/  fixed-point.md  log.md  portfolio-todo.md
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

## 6. Signal and channel specification

### 6.1 Line format
- **802.3dj, 200 Gb/s per lane:** PAM4 at **106.25 GBd** (emulated at a lower clock rate; the *math* is bit-true, the *speed* isn't).
- **Gray mapping:** 00 → −3, 01 → −1, 11 → +1, 10 → +3.
- **Precoding:** 1/(1+D) mod 4, optional. **Verify the exact definition in the 802.3 clause before implementing**, and keep TX and RX in lockstep.

### 6.2 KP4 FEC
- **RS(544,514) over GF(2¹⁰)**, t = 15, field polynomial x¹⁰ + x³ + 1, generator roots α^j for j = 0…29. Shortened code (544 < 1023).
- One 10-bit RS symbol = 5 PAM4 symbols. **Track symbol alignment explicitly.**
- **Interleaving:** real PMAs interleave codewords across lanes and symbols. For single-lane emulation, report both non-interleaved and 2-way interleaved results and record the assumption in an ADR.
- Encoder: systematic, implemented here. Decoder: `fpga-rs-core` at `rs-core-v1.0`.

### 6.3 Channels
- **Source:** IEEE P802.3dj tools and channel data area (`ieee802.org/3/dj/public/tools/`). Raw `.s4p` files are **not committed**; record name, URL and SHA-256 in `data/MANIFEST.md`.
- **Conversion (Python, scikit-rf):** single-ended 4-port → mixed-mode SDD21 → impulse → **pulse response at one sample per UI**, at the sampling phase that maximizes the main cursor.
- **Fold the TX FIR and the RX CTLE into the pulse response in Python.** The FPGA channel FIR then takes PAM4 symbols as input.
- Truncate to N_pre pre-cursors and N_post post-cursors that capture ≥ 99.9% of pulse energy (record the numbers per channel).
- Start with **two channels**, a moderate one and a hard one, chosen from the COM results the task force published for them.

### 6.4 Noise and quantization
- Additive Gaussian noise set by SNR (per-symbol, documented definition), then an **ADC quantizer at 6–7 bits** with a documented full-scale.
- **Noise-tail accuracy is the critical risk.** BER around 10⁻¹² sits ~7σ out.
  - Sum-of-uniforms (CLT) generators have no tails, so they produce **fake-good BER**.
  - Use Box–Muller (fixed-point log/sqrt + CORDIC) or an inverse-CDF approximation with tail segments.
  - **Validate before trusting any BER:** a hardware histogram in BRAM over ≥ 10¹² samples, compared bin by bin to the Gaussian out to ±7σ. Commit the plot and the chi-square result.

---

## 7. Architecture

### 7.1 Datapath
Process **P symbols per clock** in parallel.

| Block | Implementation |
|---|---|
| TX | PRBS payload → RS encoder → Gray map → precoder |
| **Channel FIR** | **Multiplierless**: input is ±1/±3, so each tap is shift/add. Uses LUTs, not DSPs |
| Noise | Gaussian generator (§6.4), one sample per symbol per lane, scaled by an SNR register |
| ADC | Saturating quantizer |
| **RX FFE** | N taps × P parallel = the DSP budget. Coefficients from registers |
| DFE | 1 tap, decision fed back within the cycle budget (the classic DFE timing loop; unroll or speculate if it limits Fmax, and record which in an ADR) |
| MLSE | Reduced-state Viterbi on 1 + αD: 4 states, 4 branches per state, squared-Euclidean branch metrics. Reuse Project 3's path-metric normalization and traceback modules |
| Slicer, demap | Thresholds at 0 and ±2 (scaled) |

### 7.2 Statistics (the scientific output)
- Pre-FEC bit and symbol error counts
- **Histogram of RS-symbol errors per codeword (0…16+)**
- Post-FEC codeword errors (from the real decoder)
- **Burst-length histogram** of consecutive PAM4 symbol errors
- Error-position samples for offline analysis
- **Prediction comparison:** from the per-symbol error rate, compute the CER expected if errors were independent, and compare it with the measured CER. That gap is the result.

### 7.3 Adaptation (Phase E)
- RTL correlators accumulate **sign(e) · sign(x_k)** for every FFE tap k over a block of N symbols.
- Firmware on the RV32I core reads the accumulators over AXI4-Lite, updates each tap by ±μ, and writes it back. **Sign-sign LMS needs only add/subtract**, which suits a core without the M extension.
- Measure convergence from a deliberately bad initial setting, and steady-state error vs. the MMSE-optimal taps from Python.

### 7.4 Host link
- Stats packets and subsampled equalized samples via `fpga-eth-core` (UDP) to `analysis/dashboard.py`: live eye/histogram, BER and adaptation state.
- UART fallback for counters.

### 7.5 Sizing (Phase A deliverable)
Size P, FFE taps and instance count against **240 DSP48E1**. Estimated emulation speed at P = 4 and 125 MHz: 500 M symbols/s = 1 Gb/s, so ~10¹² bits in ~17 minutes per instance. **Record the real numbers after synthesis**; this estimate is only for planning.

---

## 8. Python golden model

- Channel conversion, TX, channel, noise, ADC, FFE (MMSE-optimal taps computed directly), DFE, MLSE, Gray/precoder, KP4 encode/decode, all statistics.
- **Fixed-point mirror** of every RTL block, bit-exact.
- **Cross-check against serdespy** at BER 10⁻³–10⁻⁵ on the same channel. Differences must be explained (different CTLE or sampling choices are fine if documented).
- Produces the reference BER curves the hardware is compared to.

---

## 9. Verification

### 9.1 cocotb
- Per block, bit-exact against the model with random stimulus (seeded, logged).
- Full chain: identical error counts to the model on fixed seeds over long runs.
- **Scenarios:** every Gray symbol, precoder on/off, all-same and alternating patterns, saturation at the ADC and FFE, RS codewords with 0…15 errors and with 16, symbol-alignment edge cases, counter rollover, tap updates mid-stream.

### 9.2 Coverage
Symbol values × precoder mode, FFE saturation events, errors-per-codeword bins 0…16+, burst lengths, adaptation step directions.

### 9.3 Formal (SymbiYosys)
Counter saturation and rollover, MLSE path-metric normalization (no overflow), the register bank (no partial updates seen mid-block), noise-generator scaling (no overflow).

### 9.4 Hardware
Hardware error counts must match the model's statistics (not bit-for-bit, since seeds differ, but within confidence intervals) at every SNR point both can reach.

---

## 10. Measurement discipline

- Every BER/CER point: **bits tested, errors counted, 95% confidence interval**.
- Fewer than 100 errors at a point → report as an upper bound.
- Every result file records: channel, SNR definition, equalizer config, precoder, interleaving assumption, seed, bitstream tag, firmware hash.

---

## 11. Phases and definitions of done

Every phase's DoD includes **README updated, `docs/log.md` entry, that phase's media captured (§13.1), and the user confirming physical captures**.

### Phase A — Python model + sizing
- [ ] Two 802.3dj channels converted to pulse responses; truncation and energy capture recorded
- [ ] Full chain modelled; KP4 encode/decode verified against an independent Python reference
- [ ] BER curves cross-checked with serdespy
- [ ] DSP sizing: P, taps, instances; ADR written
- [ ] Media: pulse-response plots per channel; model BER waterfall

### Phase B — TX + channel + noise
- [ ] RS encoder, Gray map, precoder, multiplierless channel FIR, noise generator, ADC; bit-exact vs. model
- [ ] **Noise-tail validation on hardware** to ±7σ; plot and statistic committed
- [ ] Media: noise histogram (log scale) vs. Gaussian

### Phase C — RX equalization (fixed taps)
- [ ] FFE + DFE + slicer with Python-computed taps
- [ ] Hardware BER matches the model at 10⁻³–10⁻⁶ within confidence intervals
- [ ] Media: BER vs. SNR, hardware over model; ILA capture of FFE output

### Phase D — KP4 decode + statistics *(gate: `rs-core-v1.0`)*
- [ ] Real RS(544,514) decoding in the loop; codeword-error histograms; burst histograms; post-FEC CER
- [ ] Measured CER vs. the independent-error prediction
- [ ] Long hardware campaigns; every point with errors/bits/CI
- [ ] Media: errors-per-codeword histogram; CER vs. SNR; measured vs. predicted CER

### Phase E — Adaptation firmware *(gate: `soc-v1.0`)*
- [ ] Correlators + register bank; sign-sign LMS firmware on the RV32I core
- [ ] Convergence from a bad start; steady-state error vs. MMSE taps
- [ ] Media: tap trajectories and BER vs. adaptation time

### Phase F — MLSE + portfolio
- [ ] 4-state MLSE; DFE vs. MLSE burst and CER comparison, with and without precoding
- [ ] Live dashboard; timing closed; README complete per §13.4; demo video
- [ ] Media: burst-length histograms DFE vs. MLSE; hero GIF; video

**Fallback that's still impressive:** Phases A–D with fixed taps on two channels.

---

## 12. Out of scope — do not build

- Analog circuits: CTLE, CDR, DAC/ADC hardware. Symbol timing is ideal (jitter injection is a possible extension).
- Real 106 GBd signals or any transceivers.
- Optical PMDs and their inner Hamming FEC (a possible extension only).
- Multi-lane distribution, alignment markers, 256b/257b transcoding, the PCS.
- Re-implementing the RS decoder here: it comes from `fpga-rs-core`.

---

## 13. Portfolio deliverables — mandatory

### 13.1 Captures

Claude generates plots and terminal recordings. For photos, video and anything on the board, **Claude lists exactly what to capture, adds it to `docs/portfolio-todo.md`, and waits for the user**.

| Capture | Type | Phase |
|---|---|---|
| **Hero GIF:** dashboard during adaptation: eye/histogram opening, BER falling live | Screen recording → GIF | E/F |
| **Demo video (60–120 s):** board, channel selection, adaptation converging, CER result | OBS + phone, unlisted YouTube | F |
| Pulse responses for each channel | Plot | A |
| Noise histogram vs. Gaussian to ±7σ (log) | Plot | B |
| BER vs. SNR: hardware over model and serdespy | Plot | C |
| Errors-per-codeword histogram; measured vs. predicted CER | Plot | D |
| Burst-length histograms: DFE vs. MLSE, precoder on/off | Plot | F |
| Adaptation: tap trajectories and BER vs. time | Plot | E |
| Emulation speed vs. the Python model | Table/plot | D |
| Vivado device view + per-block utilization (DSP budget) | Screenshot + table | F |

### 13.2 Media rules
- `docs/media/`, named `YYYY-MM-DD_phase-x_description.ext`; plots generated by `make plots` only.
- Every result CSV has a sidecar `.md`: commit, command, tool versions, channel/seed, interpretation.
- GIFs ≤ 8 MB in the repo; videos on unlisted YouTube, linked.

### 13.3 Lab notebook — `docs/log.md`
Dated entries; numbers; bugs as **symptom → root cause → fix**. Appended every session.

### 13.4 README standard

The README is a technical project report. Use the RISC-V core's README (github.com/RodeanAzari/riscv-rv32i-tmr-core) as the template for structure, depth and tone. Every number comes from a committed report or CSV and links to it; unmeasured = `[TBD]`.

**At a glance table** (two columns, 10–15 rows, directly under the intro): Target standard (802.3dj, PAM4 106.25 GBd, KP4) · Channels emulated · Equalizer (FFE taps, DFE/MLSE) · Emulation speed (symbols/s, speedup vs. Python) · Lowest BER/CER measured (bits tested) · Measured vs. predicted CER gap · Adaptation convergence · DSP / LUT / BRAM · Fmax · Tests and coverage · Formal properties · Bugs caught · CI.

**Sections, in order:** title stating the claim + intro + status + sourcing note + hero · at a glance · status · architecture (Mermaid) · verification by layer with numbered bugs · deep sections (channel model, noise generator, FFE/DFE/MLSE, KP4 + statistics, adaptation firmware) with alternatives tables · on the board · demos · in Vivado (screenshot grid) · results (every row linked) · **limitations** (#1: emulation, not a real 106 GBd link; ideal timing) · prior work and novelty · build and reproduce · repository layout · roadmap.

Tone: precise, numbers with conditions, no marketing language, limits stated openly.

**Outreach once Phase D works:** Tony Chan Carusone's group at U of T built the closest prior work. A short email with results and the repo is a realistic way in.

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
