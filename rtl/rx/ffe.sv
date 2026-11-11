`default_nettype none
// RX feed-forward equalizer, P symbols per clock (buildplan §7.1; model: model/rx.py ffe_causal).
// Causal: output symbol m (counted from the first valid input symbol) is
//     z[m] = sat(round_half_up(sum_{i=0}^{N-1} c[i] * x[m - i], shift), Z_W)
// = the model's ffe_out[m - n_pre]; the main-tap position only sets alignment (caller's job).
// z[m] is defined for m >= N - 1 (history registers are data, not reset: CLAUDE.md §5).
//
// One DSP48E1 per product (N * P), docs/fixed-point.md: x 7 b, c 10 b, product 17 b, full-
// precision accumulator ACC_W: no overflow for any port values, x = -64 and c = -512 included
// (the ADC never emits -64; sized for the port, not the source). |acc| <= 2^(ACC_W-2) and the
// rounding constant is <= 2^(2^SH_W - 2), so acc + 2^(shift-1) fits ACC_W while 2^SH_W < ACC_W
// (checked at elaboration). Saturation is symmetric to +-(2^(Z_W-1) - 1).
//
// Pipeline, latency 7 (input word -> output word, valid_o = valid_i delayed by 7):
//   1  operands registered (DSP A/B registers)
//   2  product (DSP M register)
//   3  product (DSP P register)
//   4  partial sums of groups of 4 products (2 adder levels)
//   5  sum of the groups (2 adder levels for N <= 16, more above)
//   6  + rounding constant 2^(shift-1)
//   7  arithmetic shift and saturation
// History shifts only on valid_i. coef_i / shift_i are static configuration: change them only
// with no valid word in flight (they are registered at different stages).
module ffe #(
    parameter  int P     = 4,   // symbols per clock
    parameter  int N     = 16,  // taps (ADR 0002)
    parameter  int X_W   = 7,   // ADC sample
    parameter  int C_W   = 10,  // coefficient
    parameter  int Z_W   = 10,  // output
    parameter  int SH_W  = 4,   // shift register width
    localparam int ACC_W = X_W + C_W + $clog2(N)
) (
    input  wire logic                    clk_i,
    input  wire logic                    rst_i,    // resets valid only
    input  wire logic [N-1:0][C_W-1:0]   coef_i,   // signed, coef_i[0] = c[0] (newest sample)
    input  wire logic [SH_W-1:0]         shift_i,  // accumulator -> z, unsigned
    input  wire logic [P-1:0][X_W-1:0]   x_i,      // signed, symbol 0 first
    input  wire logic                    valid_i,
    output logic      [P-1:0][Z_W-1:0]   z_o,      // signed
    output logic                         valid_o
);
  localparam int LAT    = 7;
  localparam int PROD_W = X_W + C_W;  // (-2^(X_W-1)) * (-2^(C_W-1)) = +2^(X_W+C_W-2)
  localparam int GRP    = 4;
  localparam int NG     = (N + GRP - 1) / GRP;
  localparam int PART_W = PROD_W + 2;
  localparam int NG2    = 1 << $clog2(NG);
  localparam int R_W    = ACC_W;  // acc + rounding constant: no wrap (header)
  localparam int ZMAX   = (1 << (Z_W - 1)) - 1;
  localparam logic signed [R_W-1:0] RMAX = R_W'(ZMAX);  // ZMAX at the rounding width

  // ---- window: win[i] = sample (word base) - (N - 1) + i ----------------------------------
  logic [N+P-2:0][X_W-1:0] win;

  if (N > 1) begin : g_hist
    logic [N-2:0][X_W-1:0] hist_q;  // previous N - 1 samples, oldest at 0
    assign win = {x_i, hist_q};
    always_ff @(posedge clk_i) if (valid_i) hist_q <= win[P +: N-1];
  end else begin : g_nohist
    assign win = x_i;
  end

  // ---- stages 1-3: DSP operand, M and P registers --------------------------------------------
  logic [P-1:0][N-1:0][X_W-1:0]    a_q;
  logic [N-1:0][C_W-1:0]           c_q;
  (* use_dsp = "yes" *)  // multipliers only: on the module it also moved the adders into DSPs
  logic [P-1:0][N-1:0][PROD_W-1:0] m_q;
  logic [P-1:0][N-1:0][PROD_W-1:0] p_q;

  always_ff @(posedge clk_i) begin
    c_q <= coef_i;
    for (int p = 0; p < P; p++) begin
      for (int i = 0; i < N; i++) begin
        a_q[p][i] <= win[N-1+p-i];
        m_q[p][i] <= PROD_W'($signed(a_q[p][i]) * $signed(c_q[i]));
        p_q[p][i] <= m_q[p][i];
      end
    end
  end

  // ---- stage 4: groups of 4, (t0 + t1) + (t2 + t3) ---------------------------------------
  logic [P-1:0][NG-1:0][PART_W-1:0] part_q;

  always_ff @(posedge clk_i) begin
    for (int p = 0; p < P; p++) begin
      for (int g = 0; g < NG; g++) begin
        logic signed [PART_W-1:0] t[GRP];
        for (int i = 0; i < GRP; i++)
          t[i] = (g * GRP + i < N) ? PART_W'($signed(p_q[p][g*GRP+i])) : '0;
        part_q[p][g] <= (t[0] + t[1]) + (t[2] + t[3]);
      end
    end
  end

  // ---- stage 5: sum of groups, pairwise tree ----------------------------------------------
  logic [P-1:0][ACC_W-1:0] acc_q;

  always_ff @(posedge clk_i) begin
    for (int p = 0; p < P; p++) begin
      logic signed [ACC_W-1:0] t[NG2];
      for (int g = 0; g < NG2; g++) t[g] = (g < NG) ? ACC_W'($signed(part_q[p][g])) : '0;
      for (int n = NG2 / 2; n >= 1; n /= 2)
        for (int i = 0; i < n; i++) t[i] = t[2*i] + t[2*i+1];  // in place: i <= 2i
      acc_q[p] <= t[0];
    end
  end

  // ---- stage 6: rounding constant; stage 7: shift and symmetric saturation ----------------
  logic [SH_W-1:0]       sh_q;
  logic [R_W-1:0]        rc_q;
  logic [P-1:0][R_W-1:0] r_q;

  always_ff @(posedge clk_i) begin
    sh_q <= shift_i;
    rc_q <= (shift_i == '0) ? '0 : R_W'(1) << (shift_i - 1'b1);
    for (int p = 0; p < P; p++) r_q[p] <= R_W'($signed(acc_q[p])) + rc_q;
    for (int p = 0; p < P; p++) begin
      logic signed [R_W-1:0] s;
      s = $signed(r_q[p]) >>> sh_q;
      if (s > RMAX)       z_o[p] <= Z_W'(ZMAX);
      else if (s < -RMAX) z_o[p] <= Z_W'(-ZMAX);
      else                z_o[p] <= Z_W'(s);
    end
  end

  if ((1 << SH_W) >= ACC_W) begin : g_bad_shift
    $error("ffe: shift_i range 0..2^SH_W-1 can overflow the rounding add (need 2^SH_W < ACC_W)");
  end

  // ---- valid ------------------------------------------------------------------------------
  logic [LAT-1:0] v_q;

  always_ff @(posedge clk_i) begin
    if (rst_i) v_q <= '0;
    else       v_q <= {v_q[LAT-2:0], valid_i};
  end
  assign valid_o = v_q[LAT-1];

`ifndef SYNTHESIS
  a_x_known : assert property (@(posedge clk_i) disable iff (rst_i) valid_i |-> !$isunknown(x_i));
`endif

endmodule
`default_nettype wire
