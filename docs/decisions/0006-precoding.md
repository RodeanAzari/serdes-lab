# ADR 0006: 1/(1+D) mod 4 precoding

**Status:** accepted 2026-11-07. **Phase:** A (model), B (TX RTL), C (RX RTL).
Model: `model/pam4.py` (`precode`, `precode_inverse`), `model/link.py` (`precoder=`).

## Source: verified against IEEE Std 802.3-2022

The text was read from the standard itself (user's copy in `data/raw/`, not committed; PDF page
numbers below). 120.5.7.2 (200GBASE-R PMA) says "Precoding is implemented as specified in
135.5.7.2", which says:

> On each output lane, for each Gray-coded symbol G(j), a precoded symbol P(j) shall be
> determined by the following algorithm, where j is an index indicating the symbol number:
> P(j) = (G(j) – P(j-1)) mod 4, when precoding is enabled (135–1)
> P(j) = G(j), when precoding is disabled (135–2)
> On each input lane, for each precoded symbol P(j), a Gray-code symbol G(j) shall be
> determined by the following algorithm:
> G(j) = (P(j) + P(j-1)) mod 4, when precoding is enabled (135–3)
> G(j) = P(j), when precoding is disabled (135–4)
> (135.5.7.2, p. 5283)

| Item | Source | Text |
|---|---|---|
| Gray symbol G | 120.5.7.1, p. 4886 | Bits {A, B}, "A is the bit arriving first": {0,0}→0, {0,1}→1, {1,1}→2, {1,0}→3 |
| Symbol → level | 136.8.2, p. 5308 | "the PAM4 symbol values 0, 1, 2, and 3 correspond to the tx_symbol values zero, one, two, and three … highest differential output voltage corresponding to tx_symbol = three and the lowest … zero" |
| Levels | 136.9.3.1.1, p. 5328 | Normalized amplitudes "−1, −ES, ES, and 1 to represent the PAM4 symbol values 0, 1, 2, and 3" |
| Initial state | 136.8.11.1.3, p. 5312 | "The precoder state is initialized to 0 at the beginning of each training pattern, so that P(j–1)=0 in Equation (135–1)". **Training patterns only**; nothing is specified for data |

Combined, without precoding: 00 → −3, 01 → −1, 11 → +1, 10 → +3, the buildplan §6.1 mapping
(unchanged). Note: 802.3dj (Clause 176) was not checked. The 802.3-2022 text is the definition
this project implements.

## Decision

| Item | Choice |
|---|---|
| Definition | Eqs. 135-1 to 135-4 exactly, on the Gray symbol G (0..3); `mod 4` is the specified arithmetic (2-bit wrap in RTL, not an overflow) |
| TX placement | Gray map → **precoder** → level map (LEVELS[P]) → channel |
| RX placement | FFE → DFE or MLSE → slicer decisions (= P, transmitted levels) → **inverse** → Gray demap → RS symbols. The DFE feedback uses the decided transmitted level, so the DFE is unchanged |
| Initial state | P(−1) = 0 at reset on TX and on the RX inverse (Eq. 135-1's training convention, applied to data). A mismatch costs at most one Gray symbol after reset, outside every measurement window. Precoding is continuous across RS-symbol and codeword boundaries (the standard defines no per-codeword reset) |
| Control | **One** enable register drives TX and RX together: lockstep by construction (buildplan §6.1, CLAUDE.md §14) |
| Parallel RTL (P = 4) | Serial 2-bit chain within a clock (4 subtract-mod-4 steps), or closed form P(j) = (Σ(−1)^(j−i) G(i) ± P(−1)) mod 4. Choice and latency are recorded in the Phase B RTL header |

## Evidence (`make model-test`)

- Vectorised model equals a loop written directly from Eqs. 135-1 and 135-3, all four initial states.
- Matches the independent worked example in the Broadcom 802.3bj precoding proposal
  (parthasarathy_01_0911, Sep 2011), whose first output implies P(−1) = 2 there.
- The reason precoding exists, as a test: an alternating-sign DFE burst of any length in the
  received symbols becomes **exactly two** Gray symbol errors (entry and exit) after the inverse.
- Ideal channel: precoded errors come in adjacent pairs; pair rate = Gray BER (2 × 10⁶ symbols).
- Noise-free round trip, 8 seeds: zero errors through `run_link`.
- 6 injected bugs (TX sign +, RX sign −, A/B order, RX initial state, RX delay direction, TX
  precoder skipped) each caught. The initial-state bug survived the first version of the tests
  (one seed hid it with probability 1/4); fixed with 8 seeds.

## Rejected alternatives

- **1/(1−D) (P(j) = G(j) + P(j−1))**: a different code; the inverse would not match Eq. 135-3.
- **Precoding bits instead of Gray symbols**: not what 135.5.7.2 specifies; breaks the burst property.
- **Separate TX and RX enables** (as in the standard's MDIO registers): faithful, but allows a
  TX/RX mismatch that looks like a bad channel, with no research value here.
- **Inverse inside the DFE loop**: wrong. The DFE cancels ISI from transmitted levels (P), not
  from Gray symbols.
