# ADR 0011: BER reference: symbol-counted FIFO of the TX bits

**Status:** accepted 2026-11-11. **Phase:** C. Model: `model/rx.py` (frame), counts from the
bit-exact model stream. RTL: `rtl/stats/ber_check.sv` (planned).

## Context

Hardware BER must match the bit-exact model's error counts on fixed seeds (buildplan §9, §10).
The checker compares each RX bit with the TX bit it decides. In the hardware frame
(`model/rx.py`), RX symbol m decides TX symbol m − K, K = cursor + n_pre (6 on both TE KR
channels: cursor 2, n_pre 4); m counts from the first TX symbol. The channel output is defined
from m = L − 1 (FIR history is data, not reset) and the FFE needs N − 1 more, so the RX stream
starts at m0 = P · ⌈(L + N − 2) / P⌉ (32 at P = 4, L = N = 16): the first word boundary with
both windows full. K depends on the channel and the equalizer solution, so it is a runtime
register.

`tx_top` exposes the precoded level index, not the Gray bits. A second `demap` on that index
(state 0 at reset, as the TX precoder's P(−1) = 0) returns the TX bits exactly.

## Decision

**Count symbols, not clocks.** The reference is a FIFO of TX bit words (`demap` of the TX index),
written on TX valid. At start the checker drops the first m0 − K TX symbols, then for each RX
word reads the next P symbols: a word FIFO read through a two-word window rotated by
(m0 − K) mod P, plus (m0 − K) div P dropped words. Requires K ≤ m0 (checked; a larger K
raises a config error flag).

Counters (64 b, saturating): bits compared, bit errors, symbol errors (Gray symbol ≠). The
first `holdoff` RX words are not counted: the DFE and precoder-inverse reset states
(d_init, p_init) are guesses, and a wrong guess costs a short burst even without noise
(`test_rx.py`, ≤ 4 symbols on Ch4). The model counts the same window, so counts stay bit-exact.

FIFO overflow or underflow sets a sticky error flag; the host rejects a run that sets it.

## Consequences

- Independent of every block's latency and of valid gaps: changing a pipeline depth needs no
  re-tuned delay. The FIFO only has to cover the TX → RX latency (~27 words at P = 4: channel
  16, FFE 7, DFE 3, demap 1); 64 words × 2P bits fit in distributed RAM.
- The model's error count over the same symbols is a direct comparison: same seeds → same
  count; different seeds → within the confidence interval (buildplan §10).

## Rejected alternatives

- **Fixed clock delay line + lane rotation by K mod P:** the delay must be retuned whenever a
  block latency changes, and valid gaps break it.
- **Second `tx_top` with the same seed, started late:** a second RS encoder (LUTs) to save a
  64-word FIFO.
- **PRBS checker on the decoded payload:** needs RS alignment and decoding, which is Phase D;
  pre-FEC BER must not depend on it.

## Note 2026-11-11: start-up burst longer than stated

"≤ 4 symbols on Ch4" above is wrong in general. With no noise, a wrong d_init guess gave a
**10-symbol** DFE burst (P = 2, Ch4, precoded; the precoder inverse turned it into one Gray
error at its end, symbol 10). The model shows the same burst, so counts stayed bit-exact; only
`test_link_core`'s zero-error claim with holdoff 2 words failed. Holdoff is now 16 words in that
test and 64 words (256 symbols) on the board (`scripts/ber_run.py`), negligible run time.
