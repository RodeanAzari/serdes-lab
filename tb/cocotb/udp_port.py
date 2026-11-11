"""Byte-stream driver for the UDP-payload ports (s_* commands in, m_* replies out) of the
board cores (noise_hist_core, ber_core): random tvalid gaps and tready stalls."""

from cocotb.triggers import FallingEdge


class Port:
    def __init__(self, dut, rng) -> None:  # type: ignore[no-untyped-def]
        self.dut, self.rng = dut, rng
        self.p_valid, self.p_ready = 0.8, 0.85  # 1.0: no handshake gaps

    async def send(self, data: bytes, truncated: bool = False, max_clocks: int = 20_000) -> None:
        """Drive at a falling edge; the beat transfers at the next rising edge if tready is
        high now (tready depends only on registered state). A stalled command input fails."""
        d, i = self.dut, 0
        for _ in range(max_clocks):
            if i == len(data):
                break
            v = self.rng.random() < self.p_valid
            d.s_tvalid_i.value = int(v)
            d.s_tdata_i.value = data[i]
            d.s_tlast_i.value = int(i == len(data) - 1)
            d.s_tuser_i.value = int(truncated and i == len(data) - 1)
            fire = v and int(d.s_tready_o.value)
            await FallingEdge(d.clk_i)
            i += int(fire)
        else:
            raise AssertionError(f"command stalled: {i} of {len(data)} bytes accepted")
        d.s_tvalid_i.value = 0

    async def recv(self, max_clocks: int = 400_000) -> bytes:
        """m_* are registered-state outputs: read them at the falling edge, then the beat
        transfers at the next rising edge if tready is driven high."""
        d, out = self.dut, bytearray()
        for _ in range(max_clocks):
            rdy = self.rng.random() < self.p_ready
            d.m_tready_i.value = int(rdy)
            valid = int(d.m_tvalid_o.value)
            data = int(d.m_tdata_o.value) if valid else 0
            last = int(d.m_tlast_o.value) if valid else 0
            await FallingEdge(d.clk_i)
            if rdy and valid:
                out.append(data)
                if last:
                    d.m_tready_i.value = 0
                    return bytes(out)
        raise AssertionError("no reply")
