# Registers and host commands

Single source for every host-visible field. RTL: `rtl/top/noise_ctrl.sv`. Host:
`scripts/noise_hist_run.py`. Decision: ADR 0009.

## Noise histogram board (`noise_hist_top`): UDP command protocol

Board address `192.168.10.2`, UDP port `26400`, MAC `02:00:0A:0B:0C:0E`. The board replies to
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
