`default_nettype none
// RX with fixed taps, P symbols per clock (buildplan §7.1; model: model/rx.py rx()):
//   x -> ffe -> (drop warm-up words) -> dfe_slicer -> demap -> bits
//
// Input symbol m counts from the first valid x word; x is defined for m >= X0 (X0 = L - 1 after
// channel_top). z is then defined for m >= X0 + N - 1, so the first SKIP = ceil((X0 + N - 1) / P)
// FFE words are dropped and the DFE starts at m0 = P * SKIP with d[m0 - 1] = 0 (D_INIT, and the
// demap's reset state): model rx(x[X0:], ..., d_init = 0, p_init = 0, start = m0 - X0).
// RX symbol m decides TX symbol m - cursor - n_pre (ADR 0011; the BER checker aligns).
//
// Latency: 11 (ffe 7 + dfe_slicer 3 + demap 1) for every word after the dropped ones.
// Configuration is static: change it only while rst_i is high (dfe_slicer, demap headers).
module rx_top #(
    parameter  int P    = 4,
    parameter  int N    = 16,  // FFE taps
    parameter  int X0   = 15,  // first defined input symbol
    parameter  int X_W  = 7,
    parameter  int C_W  = 10,
    parameter  int Z_W  = 10,
    parameter  int SH_W = 4,
    parameter  int B_W  = 10,
    parameter  int T_W  = 10,
    localparam int SKIP = (X0 + N - 1 + P - 1) / P
) (
    input  wire logic                    clk_i,
    input  wire logic                    rst_i,
    input  wire logic [N-1:0][C_W-1:0]   coef_i,
    input  wire logic [SH_W-1:0]         shift_i,
    input  wire logic [B_W-1:0]          b_i,
    input  wire logic [T_W-1:0]          t2_i,
    input  wire logic                    precode_i,
    input  wire logic [P-1:0][X_W-1:0]   x_i,
    input  wire logic                    valid_i,
    output logic      [P-1:0][Z_W-1:0]   z_o,      // FFE output fed to the DFE (capture)
    output logic                         z_valid_o,
    output logic      [P-1:0][1:0]       d_o,      // DFE decisions
    output logic      [2*P-1:0]          data_o,   // bits, stream order (demap)
    output logic                         valid_o
);
  localparam int K_W = $clog2(SKIP + 2);  // >= 1 bit, holds SKIP

  logic [P-1:0][Z_W-1:0] z;
  logic                  z_valid;
  logic [K_W-1:0]        skip_q;  // FFE words dropped so far, saturates at SKIP
  logic                  d_valid;

  ffe #(.P(P), .N(N), .X_W(X_W), .C_W(C_W), .Z_W(Z_W), .SH_W(SH_W)) u_ffe (
      .clk_i, .rst_i, .coef_i, .shift_i, .x_i, .valid_i, .z_o(z), .valid_o(z_valid)
  );

  always_ff @(posedge clk_i) begin
    if (rst_i)                                     skip_q <= '0;
    else if (z_valid && skip_q != K_W'(SKIP))      skip_q <= skip_q + 1'b1;
  end

  assign z_o       = z;
  assign z_valid_o = z_valid && skip_q == K_W'(SKIP);

  dfe_slicer #(.P(P), .Z_W(Z_W), .B_W(B_W), .T_W(T_W)) u_dfe (
      .clk_i, .rst_i, .b_i, .t2_i, .z_i(z), .valid_i(z_valid_o), .d_o, .valid_o(d_valid)
  );

  demap #(.P(P)) u_demap (
      .clk_i, .rst_i, .precode_i, .d_i(d_o), .valid_i(d_valid),
      /* verilator lint_off PINCONNECTEMPTY */
      .g_o(),
      /* verilator lint_on PINCONNECTEMPTY */
      .data_o, .valid_o
  );

endmodule
`default_nettype wire
