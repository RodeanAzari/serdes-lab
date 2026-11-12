# Build plan — Project 4: Open SerDes Lab

Detailed build spec moved out of CLAUDE.md to keep always-loaded context lean. **Not imported**: read the section you need.
Section numbers match the original CLAUDE.md, so `§N` references still resolve here (§1–§5, §10, §14, §15 stayed in CLAUDE.md).

## Research question

DFE error propagation produces **burst** errors, and bursts interact with RS decoding in ways statistical tools approximate. A bit-true emulator measures burst-length distributions and post-FEC CER directly, for DFE vs. MLSE, with and without precoding, and compares them to the independent-error prediction.

Prior work: U of T FPGA platform for post-FEC BER analysis of 200G links (Barrie, Yang, Shakiba, Carusone, MWSCAS 2024) counts symbol errors per KP4 codeword but doesn't run the RS decoder on the FPGA; no open-source release found. serdespy (U of T) is Python only.

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
  - **Validate before trusting any BER:** a hardware histogram in BRAM over ≥ 10¹² samples, plotted bin by bin against the Gaussian out to ±7σ. Commit the plot and the chi-square results: against the model's exact pmf (all bins) and against the Gaussian (tail bins, ADR 0005; a full-range Gaussian chi-square at 4×10¹³ samples would reject any generator within the DSP budget).

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

## 11. Phases and definitions of done

Every phase's DoD includes **README updated, `docs/log.md` entry, that phase's media captured (§13.1), and the user confirming physical captures**.

### Phase A — Python model + sizing
- [x] Two 802.3dj channels converted to pulse responses; truncation and energy capture recorded (ADR 0001, `channels.csv`)
- [x] Full chain modelled (end-to-end KP4 link + §7.2 statistics, `kp4_model.csv`, 2026-11-07); KP4 encode/decode verified against an independent Python reference (`galois`). *Amended 2026-11-07 (user decision): the MLSE model moves to Phase F and the bit-exact payload PRBS / noise uniform source to Phase B; each is still modelled before its RTL.*
- [x] BER curves cross-checked with serdespy (`data/results/serdespy_*.csv`, 2026-11-06)
- [x] DSP sizing: P, taps, instances; ADR written (ADR 0002, 2026-11-06; real numbers after synthesis)
- [x] Media: pulse-response plots per channel; model BER waterfall; serdespy overlay; model errors-per-codeword histogram (all user confirmed 2026-11-07). **Phase A done 2026-11-07, tag `v0.1-model`.**

### Phase B — TX + channel + noise
- [x] Model first: bit-exact payload PRBS and noise uniform source (`lfsr258`-type, ADR 0003), independent generators
- [x] RS encoder, Gray map, precoder, multiplierless channel FIR, noise generator, ADC; bit-exact vs. model
- [x] **Noise-tail validation on hardware** to ±7σ; plot and statistic committed
- [x] Media: noise histogram (log scale) vs. Gaussian (user confirmed captures 2026-11-11). **Phase B done 2026-11-11, tag `v0.2-channel`.**

### Phase C — RX equalization (fixed taps)
- [x] FFE + DFE + slicer with Python-computed taps
- [x] Hardware BER matches the model at 10⁻³–10⁻⁶ within confidence intervals
- [x] Media: BER vs. SNR, hardware over model; ILA capture of FFE output (user confirmed captures 2026-11-11). **Phase C done 2026-11-11, tag `v0.3-rx`.**

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
- [ ] Model first: 4-state MLSE (float and bit-exact)
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
