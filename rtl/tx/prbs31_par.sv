`default_nettype none
// PRBS31 payload generator, W bits per enabled clock (ADR 0007, model: model/prng.py prbs31).
//
//   a[n] = a[n-28] ^ a[n-31]  (x^31 + x^28 + 1)
//   reset: a[0..30] = seed_i[0..30]; each enabled clock emits data_o[i] = a[n+i], i = 0..W-1,
//   in stream order (data_o[0] first), then n += W.
//
// Latency: 0. data_o is a combinational function of the state register: the current W bits are
// valid whenever rst_i is low, and en_i advances to the next W.
module prbs31_par #(
    parameter int W = 10
) (
    input  wire logic         clk_i,
    input  wire logic         rst_i,   // synchronous, active high: loads seed_i
    input  wire logic [30:0]  seed_i,  // must be nonzero
    input  wire logic         en_i,
    output logic      [W-1:0] data_o
);
  localparam int LEN = 31;
  localparam int TAP = 28;

  logic [LEN-1:0]   win_q;  // win_q[i] = a[n+i]
  logic [W+LEN-1:0] ext;    // ext[j] = a[n+j]

  always_comb begin
    ext = '0;
    ext[LEN-1:0] = win_q;
    for (int j = LEN; j < W + LEN; j++) begin
      ext[j] = ext[j-TAP] ^ ext[j-LEN];
    end
  end

  assign data_o = ext[W-1:0];

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      win_q <= seed_i;
    end else if (en_i) begin
      win_q <= ext[W+LEN-1:W];
    end
  end

`ifndef SYNTHESIS
  // An all-zero window is the LFSR's lock-up state: a zero seed or a broken update.
  a_nonzero : assert property (@(posedge clk_i) disable iff (rst_i) win_q != '0);
`endif

endmodule
`default_nettype wire
