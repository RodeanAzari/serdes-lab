`default_nettype none
// 1-tap DFE + PAM4 slicer, P symbols per clock, loop-unrolled (ADR 0010; model: model/fixed.py
// dfe1_int). For symbol m (counted from the first valid input symbol):
//     d[m] = slice(z[m] - b * level(d[m-1])),  d[-1] = D_INIT,  level = -3, -1, +1, +3
//     slice(v) = (v >= -t2) + (v >= 0) + (v >= t2)                (ties go up)
// All four candidates cand[m][j] = slice(z[m] - b * level(j)) are computed feed-forward; the
// loop is only d[m] = cand[m][d[m-1]]: P cascaded 4:1 muxes of 2 bits (one LUT6 per bit).
//
// Widths (docs/fixed-point.md): with ZB = max(Z_W, B_W), any port values give
// -2^(ZB+1) <= z - b * level <= 2^(ZB+1) - 1 (extremes at z, b = -2^(ZB-1) / 2^(ZB-1) - 1, level
// = +-3), and t2 < 2^T_W, so V_W = max(ZB + 2, T_W + 1) is exact (12 b at the defaults).
// No rounding or saturation is needed.
//
// Pipeline, latency 3 (input word -> output word, valid_o = valid_i delayed by 3):
//   1  v[j] = z - b * level(j), 4 per symbol (b, 3b registered from b_i)
//   2  cand[j] = slice(v[j])
//   3  decision chain through the word; the word's last decision is the loop register
// The loop register is reset to D_INIT and advances only on valid words. b_i / t2_i are static
// configuration: change them only with no valid word in flight.
module dfe_slicer #(
    parameter  int         P      = 4,
    parameter  int         Z_W    = 10,  // FFE output
    parameter  int         B_W    = 10,  // DFE tap, z units
    parameter  int         T_W    = 10,  // outer threshold t2 = 2 h0, unsigned
    parameter  logic [1:0] D_INIT = 2'd0
) (
    input  wire logic                   clk_i,
    input  wire logic                   rst_i,  // resets valid and the loop register
    input  wire logic [B_W-1:0]         b_i,    // signed
    input  wire logic [T_W-1:0]         t2_i,   // unsigned
    input  wire logic [P-1:0][Z_W-1:0]  z_i,    // signed, symbol 0 first
    input  wire logic                   valid_i,
    output logic      [P-1:0][1:0]      d_o,    // level index 0..3
    output logic                        valid_o
);
  localparam int ZB_W = Z_W > B_W ? Z_W : B_W;
  localparam int V_W  = ZB_W + 2 > T_W + 1 ? ZB_W + 2 : T_W + 1;

  // ---- configuration: b, 3b, thresholds at V_W bits ---------------------------------------
  logic signed [V_W-1:0] b1_q, b3_q, tp_q, tn_q;

  always_ff @(posedge clk_i) begin
    b1_q <= V_W'($signed(b_i));
    b3_q <= (V_W'($signed(b_i)) <<< 1) + V_W'($signed(b_i));
    tp_q <= V_W'(t2_i);
    tn_q <= -V_W'(t2_i);
  end

  // ---- stage 1: v[j] = z - b * level(j); level(j) = -3, -1, +1, +3 ------------------------
  logic [P-1:0][3:0][V_W-1:0] v_q;

  always_ff @(posedge clk_i) begin
    for (int p = 0; p < P; p++) begin
      logic signed [V_W-1:0] z;
      z = V_W'($signed(z_i[p]));
      v_q[p][0] <= z + b3_q;
      v_q[p][1] <= z + b1_q;
      v_q[p][2] <= z - b1_q;
      v_q[p][3] <= z - b3_q;
    end
  end

  // ---- stage 2: candidates ----------------------------------------------------------------
  logic [P-1:0][3:0][1:0] cand_q;

  always_ff @(posedge clk_i) begin
    for (int p = 0; p < P; p++) begin
      for (int j = 0; j < 4; j++) begin
        logic signed [V_W-1:0] v;
        v = $signed(v_q[p][j]);
        cand_q[p][j] <= 2'(v >= tn_q) + 2'(v >= 0) + 2'(v >= tp_q);
      end
    end
  end

  // ---- stage 3: the loop ------------------------------------------------------------------
  logic [1:0]        last_q;
  logic [P-1:0][1:0] d_d;
  logic [2:0]        v_vq;

  always_comb begin
    logic [1:0] prev;
    prev = last_q;
    for (int p = 0; p < P; p++) begin
      d_d[p] = cand_q[p][prev];
      prev   = d_d[p];
    end
  end

  always_ff @(posedge clk_i) begin
    if (rst_i)          last_q <= D_INIT;
    else if (v_vq[1])   last_q <= d_d[P-1];
    if (v_vq[1]) d_o <= d_d;
  end

  always_ff @(posedge clk_i) begin
    if (rst_i) v_vq <= '0;
    else       v_vq <= {v_vq[1:0], valid_i};
  end
  assign valid_o = v_vq[2];

`ifndef SYNTHESIS
  a_z_known : assert property (@(posedge clk_i) disable iff (rst_i) valid_i |-> !$isunknown(z_i));
`endif

endmodule
`default_nettype wire
