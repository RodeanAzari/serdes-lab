# ADR 0013: KP4 decoding on the board (Phase D): clocking, alignment, interleaving, statistics

**Status:** accepted 2026-11-11 (clocking: user decision; the rest proposed with it, open to
revision before the RTL). **Phase:** D. Decoder: `fpga-rs-core` at `rs-core-v1.0` (submodule
`rtl/rs`, owner P3). Model: `model/kp4link.py`, `model/fec_stats.py`. Builds on ADR 0011
(BER frame) and ADR 0012 (board control).

## Context

- `rs_decoder` sustains one RS symbol per clock and meets **100 MHz** on the Artix-7 (KP4 set:
  WNS +1.168 ns at 10 ns, i.e. ~8.8 ns critical path). It does **not** meet our 125 MHz, and
  we may not change it (shared block).
- At P = 4 the link produces 4 PAM4 symbols = 0.8 RS symbols per clock. At 125 MHz that is
  100 M RS symbols/s: exactly one decoder at 100 MHz, with zero margin.
- fpga-eth-core accepts any core clock above its 12.5 MB/s byte rate (timed at 125 MHz).
- The TX sends codewords back to back, non-interleaved, from TX symbol 0 (`tx_top`, model
  `tx.tx`); one RS symbol = 10 bits = 5 PAM4 symbols, MSB first.

## Decision

1. **One 100 MHz clock domain** for a new board top `kp4_top`: link, decoder, statistics and
   Ethernet. Own MMCM clock generator (100 MHz core, 25 MHz PHY reference). The decoder sees
   0.8 symbol per clock (20% margin), no CDC. KP4 emulation rate: **0.8 Gb/s**. `ber_top`
   stays at 125 MHz / 1 Gb/s for pre-FEC campaigns.
2. **RS-symbol alignment from the BER frame (ADR 0011).** RX symbol j decides TX symbol
   first + j, first = m0 − K. Codeword c occupies TX symbols 2720c … 2720c + 2719. The first
   codeword decoded is the first one that starts after the holdoff:
   c0 = ⌈(first + 4·holdoff) / 2720⌉. The RX stream is realigned in symbols (as `ber_check`
   does, a window rotated by (2720·c0 − first) mod P), then packed 5 PAM4 symbols → one 10-bit
   RS symbol, MSB first. The TX reference goes through the same packing, so every RS symbol
   has its reference.
3. **Interleaving assumption** (required ADR item): **real decoding is non-interleaved**, which
   is what the TX sends. The **2-way interleaved** view is computed exactly as the model does
   (`fec_stats.errors_per_codeword(…, interleave=2)`): the same lane error mask regrouped into
   virtual codewords A/B on even/odd symbols of each 1088-symbol block. It is a statistic
   from the reference compare, not a second decode.
4. **Statistics per codeword** (from the reference compare, independent of the decoder):
   RS-symbol errors per codeword, histogram 0…15 and 16+, non-interleaved and 2-way;
   burst-length histogram of consecutive PAM4 symbol errors. **From the decoder:** fail count,
   and a cross-check counter of codewords where the decoder's corrected count ≠ the true error
   count (must stay 0 for ≤ 15 errors); a codeword with > 15 true errors that the decoder does
   not flag is a **miscorrection**, counted separately. **Post-FEC CER** = (fail +
   miscorrections) / codewords. The measured CER is compared with the independent-error
   prediction from the measured per-symbol error rate (buildplan §7.2).
5. **Model first:** the model computes the same counters over the same frame (codewords from
   c0, same holdoff) so a short board run matches count for count, as in ADR 0012.

## Consequences

- One clock: no CDC verification; timing slack for the rest of the design (it met 125 MHz).
- 20% slower KP4 runs than pre-FEC runs: CER 10⁻⁷ with 100 failures needs ~5.4 × 10¹² bits,
  ~1.9 h at 0.8 Gb/s.
- The decoder's output data is not compared with the reference in the first version: fail flag
  plus true error count identify every post-FEC error a bounded-distance decoder can make
  (fail, or miscorrection when > t errors). A data compare can be added if the counters
  disagree.

## Rejected alternatives

- **Two decoders in a 100 MHz domain with the link at 125 MHz:** keeps 1 Gb/s, but async
  FIFOs, CDC and codeword re-ordering for a 20% speed gain.
- **Request a pipelined 125 MHz decoder from P3:** waits on another project; can still be
  filed later if speed matters.
- **Interleave the TX for real 2-way decoding:** a second encoder path and deinterleaver for a
  statistic the error mask already gives exactly.
