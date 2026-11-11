# Registers and host commands

Single source for every host-visible field. Noise histogram board: RTL `rtl/top/noise_ctrl.sv`,
host `scripts/noise_hist_run.py`, ADR 0009. BER board: RTL `rtl/top/link_ctrl.sv`, host
`scripts/ber_run.py`, ADR 0012.

## Noise histogram board (`noise_hist_top`): UDP command protocol

Board address `192.168.10.2`, UDP port `26400`, MAC `02:00:0A:0B:0C:0D` (no ARP: the host needs a static neighbour entry, already present for the shared board). The board replies to
the sender of each command (address learned from the datagram, no ARP). One command at a
time: the host waits for the reply (or times out and retries). All multi-byte fields are
**big-endian**.

### Commands (host → board)

| Op | Name | Length (B) | Fields after the op byte | Accepted when |
|---|---|---|---|---|
| `0x01` | CONFIG | 332 | σ_reg (3 B, 17 b used) · run length N (8 B, words per lane; 0 = unbounded) · seeds: lane 0…7, each y1…y5 (8 B each) | stopped, not clearing |
| `0x02` | START | 1 | — | stopped, configured, not clearing, N not reached |
| `0x03` | STOP | 1 | — | always (pause; generator state held) |
| `0x04` | READ | 3 | lane (1 B, 0…7) · chunk (1 B, 0…7) | stopped and pipeline drained, not clearing |
| `0x05` | STATUS | 1 | — | always |

CONFIG loads the seeds into the 8 lfsr258 lanes, sets σ_reg and N, zeroes the word counter
and clears all 8 histograms (1024 clocks). A seed word whose recurrence bits are all zero
(below `SEED_MIN`, `model/prng.py`) or a σ_reg ≥ 2¹⁷ is rejected (code 3) and nothing is applied.

### Reply (board → host)

| Byte | Field |
|---|---|
| 0 | op \| `0x80` (unknown op: `0xFF`) |
| 1 | code: 0 ok · 1 refused in this state · 2 bad length · 3 bad argument · 4 unknown op |
| 2 | flags: bit 0 running · bit 1 clearing · bit 2 configured · bit 3 N reached · bit 4 drained |
| 3…10 | words done per lane (64 b) |
| 11…18 | run length N (64 b) |
| 19…21 | σ_reg (24 b field, 17 b used) |
| 22…25 | build id (32 b: git commit of the bitstream source) |
| 26… | READ with code 0 only: lane (1 B) · chunk (1 B) · 128 bins × 6 B (48 b counts) |

Every command gets a reply, including refused and malformed ones (26 B). A READ reply is
26 + 2 + 768 = 796 B. Chunk c of lane l holds bins 128c … 128c + 127; bin b counts samples
with clamp(n, −512, 511) = b − 512 (`rtl/stats/hist_bram.sv`).

## BER board (`ber_top`): UDP command protocol

Same board address, MAC, transport rules and reply addressing as the noise board above, but
**UDP port `26401`**. All multi-byte fields big-endian; signed fields are two's complement,
sign-extended to the field. P = 4, L = 16 channel taps, N = 16 FFE taps on the board.

### Commands (host → board)

| Op | Name | Length (B) | Accepted when |
|---|---|---|---|
| `0x01` | CONFIG | 25 + 2L + 2N + 40P = 249 | stopped |
| `0x02` | START | 1 | stopped, configured: a **new run from reset** (same CONFIG = identical run) |
| `0x03` | STOP | 1 | always (ends the run; the snapshot keeps its counts) |
| `0x05` | STATUS | 1 | always |

CONFIG fields after the op byte (byte offset in the datagram):

| Offset | Bytes | Field | Valid (else code 3, nothing applied) |
|---|---|---|---|
| 1 | 8 | run length R, bits compared (0 = unbounded) | R mod 2P = 0 |
| 9 | 4 | payload PRBS31 seed | 1 … 2³¹ − 1 |
| 13 | 1 | flags: bit 0 precoder (TX and RX) | bits 7:1 zero |
| 14 | 3 | σ_reg (`docs/fixed-point.md`) | < 2¹⁷ |
| 17 | 1 | K = cursor + n_pre (BER lag, ADR 0011) | ≤ m0 = P·⌈(L + N − 2)/P⌉ (32) |
| 18 | 2 | holdoff, RX words not counted | any |
| 20 | 1 | FFE output shift | < 16 |
| 21 | 2 | DFE tap b, signed | fits 10 b |
| 23 | 2 | slicer t2, unsigned | < 2¹⁰ |
| 25 | 2L | channel taps hq, signed, tap 0 first (zero-padded to L) | each fits 11 b |
| 25 + 2L | 2N | FFE coefficients, signed, coefficient 0 first | each fits 10 b |
| 25 + 2L + 2N | 40P | noise seeds: lane 0…P−1, each y1…y5 (8 B) | lfsr258 `SEED_MIN` rule |

CONFIG zeroes the snapshot. While no run is in progress the link is held in reset. A run stops
by itself on the clock its bits counter reaches R; the snapshot then holds exactly R bits.

### Reply (board → host), 39 B for every command

| Byte | Field |
|---|---|
| 0 | op \| `0x80` (unknown op: `0xFF`) |
| 1 | code: 0 ok · 1 refused in this state · 2 bad length · 3 bad argument · 4 unknown op |
| 2 | flags: bit 0 running · bit 1 configured · bit 2 R reached · bit 3 BER FIFO error (run void) |
| 3…10 | bits compared (snapshot, 64 b) |
| 11…18 | bit errors (snapshot) |
| 19…26 | symbol errors (snapshot, Gray symbols that differ) |
| 27…34 | run length R |
| 35…38 | build id (git commit of the bitstream source) |

All three counters and the FIFO flag come from the same clock (a consistent reading, also
mid-run). Counters saturate at 2⁶⁴ − 1.
