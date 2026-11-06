# ADR 0001: Channel-model construction

**Status:** accepted 2026-11-05. **Phase:** A.

## Decision

| Item | Choice | Why |
|---|---|---|
| Source | TE/Shanbhag KR set, `shanbhag_3dj_02_2305.zip` ([MANIFEST](../../data/MANIFEST.md)) | One topology (1 m 26AWG cabled backplane) at four losses: only host loss changes between channels |
| Channels | Ch2 19.3 dB (moderate), Ch4 31.4 dB (hard) IL @ 53.125 GHz | Chosen by **insertion loss**, not COM: the contribution publishes no COM values (user decision, 2026-11-05) |
| Package | **None** | Data is TP0–TP5 without package. 802.3dj COM adds one. Stated as a README limitation (user decision) |
| SDD21 | ½(S21 − S23 − S41 + S43), port map 1→2, 3→4 | From file header; checked against published IL (≤ 0.05 dB) on every `make channels` run |
| Band limit | Raised-cosine taper 67 → 80 GHz | Authors: usable bandwidth 67 GHz; a hard cut at 80 GHz rings |
| RX filter | 4th-order Butterworth, f_r = 0.75 × 106.25 GHz | COM convention |
| CTLE | 802.3ck form: f_z = f_p1 = f_b/2.5, f_p2 = f_b, f_LF = f_b/80; g_DC ∈ [−20, 0], g_DC2 ∈ [−6, 0], 1 dB steps | **[verify against the 802.3dj Clause 178 CTLE table]**: form taken from 802.3ck, scaled to f_b |
| TX FIR | 3 taps, c(−1), c(+1) ∈ [−0.30, 0] step 0.05, c(0) = 1 − \|c(−1)\| − \|c(+1)\| | Small, conventional. Optimiser chose ~flat taps on both channels: the RX FFE does the work |
| Selection | Grid search maximising MMSE SNR of a reference RX (16-tap FFE, 3 pre, 1-tap DFE) | COM-style. Reference RX is **not** the sized RTL equalizer (separate ADR) |
| Selection noise | One-sided η₀ = 8.2e-9 V²/GHz input-referred, shaped by CTLE × RX filter; A_v = 0.413 V | 802.3ck COM reference values, **[verify against 802.3dj]**. Used only to pick CTLE/TX FIR |
| Sampling | 32 samples/UI, phase maximising main cursor | docs/buildplan.md §6.3 |
| Truncation | Smallest window holding ≥ 99.9% of pulse energy | docs/buildplan.md §6.3 |

Results (from [`channels.csv`](../../data/results/channels.csv)):

| Channel | CTLE g_DC / g_DC2 | TX (c−1, c0, c+1) | h−1/h0 | h+1/h0 | N_pre / N_post (99.9%) |
|---|---|---|---|---|---|
| Ch2 19.3 dB | −11 / −2 dB | (−0.05, 0.95, 0) | 0.39 | 0.08 | 2 / 7 |
| Ch4 31.4 dB | −10 / −3 dB | (0, 1, 0) | 0.52 | 0.42 | 2 / 9 |

## Why selection noise is shaped but emulation noise is white

The FPGA adds white Gaussian noise after the pulse-response FIR. If the CTLE were chosen by ISI
alone, maximum peaking would always win, since its noise enhancement would be invisible. So
selection includes CTLE-shaped noise. The emulator then adds white noise at a set SNR. The
noise **colour** after the CTLE is neglected in emulation; this is a stated approximation.

## Rejected alternatives

- **Choose channels by COM**: no published COM for this set; computing our own COM is out of scope.
- **Add a COM package model**: more realistic loss but more unverified parameters; deferred.
- **Coloured noise in the FPGA** (white noise through a CTLE-shaped FIR): more fidelity, more
  LUTs and a harder tail-validation problem. Revisit only if serdespy cross-check disagrees.
- **Fix CTLE/TX FIR by hand**: not reproducible.

## Sampling phase: resolved 2026-11-05

Question: max-main-cursor sampling gives large first pre-cursors (h−1/h0 = 0.39, 0.52). Is it
far from the phase a real receiver would want? Decided by measurement: post-EQ SNR of the
reference RX at all 32 phases ([`phase_sweep.csv`](../../data/results/phase_sweep.csv),
`scripts/phase_sweep.py`), at the thermal reference noise and at an operating point near
BER 1e-4. **Rule (user): keep max-cursor if within 0.5 dB of the best phase everywhere.**

| Channel | Noise | Best SNR | Max-cursor gap | COM/MM (h−1 = h+1) gap |
|---|---|---|---|---|
| Ch2 | thermal ref | 31.08 dB | 0.24 dB | 0.23 dB |
| Ch2 | 19 dB input | 18.16 dB | 0.20 dB | 1.08 dB |
| Ch4 | thermal ref | 27.86 dB | 0.25 dB | 0.04 dB |
| Ch4 | 23 dB input | 18.35 dB | 0.18 dB | 0.38 dB |

**Decision: keep max-main-cursor (docs/buildplan.md §6.3).** Within 0.25 dB of the best phase in all
four cases; the MM phase is not consistently closer and is 1.08 dB off on Ch2 at the operating
point. Caveat: CTLE/TX FIR were held at their max-cursor values; re-optimising them per phase
could favour another phase slightly. Rejected: MM phase (more CDR-like, not better here);
per-run best-phase search (noise-dependent channel, breaks comparability across SNR).
