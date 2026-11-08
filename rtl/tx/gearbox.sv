`default_nettype none
// Width converter IN_W -> OUT_W bits, stream order preserved. Input symbols are MSB first
// (the RS symbol bit order, model/rs.py symbols_to_bits); output data_o[i] is the i-th bit in
// stream order (data_o[0] first), the convention pam4_map consumes.
//
// Holds up to CAP = IN_W + OUT_W - 1 bits. valid_o is high whenever >= OUT_W bits are held; the
// consumer takes every valid word (no ready). s_ready_o is high when an input symbol fits after
// this cycle's output. With IN_W >= OUT_W and an input that is never starved, valid_o never
// drops after the first word (checked in tx_top).
//
// Latency: 1 (an accepted bit can leave on the next clock at the earliest).
module gearbox #(
    parameter int IN_W  = 10,
    parameter int OUT_W = 8
) (
    input  wire logic             clk_i,
    input  wire logic             rst_i,
    input  wire logic [IN_W-1:0]  s_data_i,
    input  wire logic             s_valid_i,
    output logic                  s_ready_o,
    output logic      [OUT_W-1:0] data_o,
    output logic                  valid_o
);
  localparam int CAP = IN_W + OUT_W - 1;
  localparam int CB  = $clog2(CAP + 1);

  logic [CAP-1:0] buf_q;  // buf_q[i] = i-th oldest held bit
  logic [CB-1:0]  cnt_q;  // bits held
  logic [CAP-1:0] rest;   // held bits after this cycle's output
  logic [CB-1:0]  rest_n;
  logic [CAP-1:0] buf_d;

  assign valid_o   = cnt_q >= CB'(OUT_W);
  assign data_o    = buf_q[OUT_W-1:0];
  assign rest      = valid_o ? (buf_q >> OUT_W) : buf_q;
  assign rest_n    = valid_o ? cnt_q - CB'(OUT_W) : cnt_q;
  assign s_ready_o = rest_n <= CB'(CAP - IN_W);

  always_comb begin
    buf_d = rest;
    if (s_valid_i && s_ready_o) begin
      for (int j = 0; j < IN_W; j++) begin
        // bit j in stream order is the symbol's bit IN_W-1-j (MSB first)
        if (int'(rest_n) + j < CAP) buf_d[int'(rest_n) + j] = s_data_i[IN_W-1-j];
      end
    end
  end

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      cnt_q <= '0;
    end else begin
      cnt_q <= rest_n + ((s_valid_i && s_ready_o) ? CB'(IN_W) : '0);
    end
    buf_q <= buf_d;  // data: not reset (cnt_q says which bits are real)
  end

`ifndef SYNTHESIS
  a_cap : assert property (@(posedge clk_i) disable iff (rst_i) cnt_q <= CB'(CAP));
`endif

endmodule
`default_nettype wire
