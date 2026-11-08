`default_nettype none
// Multiplierless channel FIR, P symbols per clock (buildplan §7.1; model: model/tx.py pre_adc,
// s = conv(a, hq)). Causal: output symbol m (counted from the first valid input symbol) is
//     s[m] = sum_{j=0}^{L-1} taps[j] * a[m - j],   a = 2 * idx - 3 in {-3, -1, +1, +3},
// i.e. the model's s[m - cursor]; the cursor only sets alignment, which the caller handles.
// s[m] is defined for m >= L - 1 (history registers are data, not reset: CLAUDE.md §5).
//
// Each term is a 4:1 mux of {-3h, -h, +h, +3h}; 3h = (h << 1) + h is precomputed per tap, so
// no DSPs. Sums are full precision (S_W bits never overflow, even at taps = -2^(TAP_W-1)).
//
// Pipeline, latency 3 (input word -> output word, valid_o = valid_i delayed by 3):
//   1  products (mux) registered
//   2  partial sums of groups of 4 terms (2 adder levels)
//   3  pairwise sum of the groups (<= 2 adder levels for L <= 16; more above)
// History shifts only on valid_i. A tap change applies to input words from one clock later.
module channel_fir #(
    parameter  int P     = 4,   // symbols per clock
    parameter  int L     = 16,  // taps (Ch2 needs 10, Ch4 12: ADR 0001 99.9% window)
    parameter  int TAP_W = 11,  // docs/fixed-point.md: channel tap hq
    localparam int S_W   = TAP_W + 2 + $clog2(L)
) (
    input  wire logic                        clk_i,
    input  wire logic                        rst_i,   // resets valid only
    input  wire logic [L-1:0][TAP_W-1:0]     taps_i,  // signed, taps_i[0] = hq[0]
    input  wire logic [P-1:0][1:0]           idx_i,   // level index, symbol 0 first
    input  wire logic                        valid_i,
    output logic      [P-1:0][S_W-1:0]       s_o,     // signed
    output logic                             valid_o
);
  localparam int PROD_W = TAP_W + 2;  // |3h| <= 3 * 2^(TAP_W-1) < 2^(TAP_W+1)
  localparam int GRP    = 4;
  localparam int NG     = (L + GRP - 1) / GRP;
  localparam int PART_W = PROD_W + 2;  // sum of 4 terms

  // ---- taps: h and 3h, registered ----------------------------------------------------------
  logic [L-1:0][PROD_W-1:0] h_q, h3_q;

  always_ff @(posedge clk_i) begin
    for (int j = 0; j < L; j++) begin
      logic signed [PROD_W-1:0] h;
      h = PROD_W'($signed(taps_i[j]));
      h_q[j]  <= h;
      h3_q[j] <= (h <<< 1) + h;
    end
  end

  // ---- window: win[i] = symbol (word base) - (L - 1) + i ----------------------------------
  logic [L+P-2:0][1:0] win;

  if (L > 1) begin : g_hist
    logic [L-2:0][1:0] hist_q;  // previous L - 1 symbols, oldest at 0
    assign win = {idx_i, hist_q};
    always_ff @(posedge clk_i) if (valid_i) hist_q <= win[P +: L-1];
  end else begin : g_nohist
    assign win = idx_i;
  end

  // ---- stage 1: products ------------------------------------------------------------------
  logic [P-1:0][L-1:0][PROD_W-1:0] prod_q;
  logic [2:0] v_q;

  always_ff @(posedge clk_i) begin
    for (int p = 0; p < P; p++) begin
      for (int j = 0; j < L; j++) begin
        unique case (win[L-1+p-j])
          2'd0: prod_q[p][j] <= -h3_q[j];
          2'd1: prod_q[p][j] <= -h_q[j];
          2'd2: prod_q[p][j] <= h_q[j];
          2'd3: prod_q[p][j] <= h3_q[j];
        endcase
      end
    end
  end

  // ---- stage 2: groups of 4, (t0 + t1) + (t2 + t3) ---------------------------------------
  logic [P-1:0][NG-1:0][PART_W-1:0] part_q;

  always_ff @(posedge clk_i) begin
    for (int p = 0; p < P; p++) begin
      for (int g = 0; g < NG; g++) begin
        logic signed [PART_W-1:0] t[GRP];
        for (int i = 0; i < GRP; i++)
          t[i] = (g * GRP + i < L) ? PART_W'($signed(prod_q[p][g*GRP+i])) : '0;
        part_q[p][g] <= (t[0] + t[1]) + (t[2] + t[3]);
      end
    end
  end

  // ---- stage 3: sum of groups, pairwise tree (2 levels for NG <= 4, i.e. L <= 16) -------
  localparam int NG2 = 1 << $clog2(NG);

  always_ff @(posedge clk_i) begin
    for (int p = 0; p < P; p++) begin
      logic signed [S_W-1:0] t[NG2];
      for (int g = 0; g < NG2; g++) t[g] = (g < NG) ? S_W'($signed(part_q[p][g])) : '0;
      for (int n = NG2 / 2; n >= 1; n /= 2)
        for (int i = 0; i < n; i++) t[i] = t[2*i] + t[2*i+1];  // in place: i <= 2i
      s_o[p] <= t[0];
    end
  end

  always_ff @(posedge clk_i) begin
    if (rst_i) v_q <= '0;
    else       v_q <= {v_q[1:0], valid_i};
  end
  assign valid_o = v_q[2];

`ifndef SYNTHESIS
  a_idx_known : assert property (@(posedge clk_i) disable iff (rst_i) valid_i |-> !$isunknown(idx_i));
`endif

endmodule
`default_nettype wire
