`default_nettype none
// Phase B emulated link front end, P symbols per clock (buildplan §7.1; model: model/tx.py):
//   tx_top -> channel_fir -------------(delay)--+
//          -> lfsr258 x P -> noise_gen ---------+-> y = sat(s + n, 16) -> x = sat(rs(y, 6), 7)
//
// Alignment (ADR 0008): output symbol m (counted from the first TX symbol) is model symbol
// k = m - cursor: x_o = model front_end(pre_adc(...))[k], noise word m on symbol m. Defined for
// m >= L - 1 (FIR history is data, not reset). The cursor exists only in the model.
//
// Noise lane i (seed noise_seed_i[i]) steps once per TX word, as the FIR's input does.
//
// Pipeline, latency 16 (TX word -> x_o, valid_o follows tx valid):
//   FIR 3 + delay 11  ==  lfsr258 1 + noise_gen 13;   +1 sum and saturate (y);   +1 ADC (x)
// Configuration (taps, sigma, seeds, precoder) is static: seeds and precoder load in reset.
module channel_top #(
    parameter  int    P         = 4,
    parameter  int    L         = 16,
    parameter  int    TAP_W     = 11,
    parameter  string INIT_FILE = "noise_tables.mem",
    localparam int    S_W       = TAP_W + 2 + $clog2(L)  // channel_fir output
) (
    input  wire logic                     clk_i,
    input  wire logic                     rst_i,
    input  wire logic [30:0]              prbs_seed_i,   // payload PRBS31, nonzero
    input  wire logic                     precode_i,
    input  wire logic [L-1:0][TAP_W-1:0]  taps_i,        // signed hq, zero-padded to L
    input  wire logic [P-1:0][319:0]      noise_seed_i,  // lfsr258 seed per lane
    input  wire logic [16:0]              sigma_i,       // docs/fixed-point.md
    output logic      [P-1:0][6:0]        x_o,           // ADC samples, signed, +-63
    output logic                          valid_o
);
  localparam int D     = 11;  // (1 + 13) - 3
  localparam int YS_W  = (S_W > 16 ? S_W : 16) + 1;  // s + n, no overflow
  localparam int YMAX  = (1 << 15) - 1;
  localparam int XMAX  = 63;

  // ---- TX ----------------------------------------------------------------------------------
  logic [P-1:0][1:0] idx;
  logic              tx_valid;

  tx_top #(.P(P)) u_tx (
      .clk_i, .rst_i, .prbs_seed_i, .precode_i,
      /* verilator lint_off PINCONNECTEMPTY */
      .a_o(),
      /* verilator lint_on PINCONNECTEMPTY */
      .idx_o(idx), .valid_o(tx_valid)
  );

  // ---- channel FIR + alignment delay -------------------------------------------------------
  logic [P-1:0][S_W-1:0] s;
  logic                  s_valid;
  logic [P-1:0][S_W-1:0] s_dly_q[D];

  channel_fir #(.P(P), .L(L), .TAP_W(TAP_W)) u_fir (
      .clk_i, .rst_i, .taps_i, .idx_i(idx), .valid_i(tx_valid), .s_o(s), .valid_o(s_valid)
  );

  always_ff @(posedge clk_i) begin
    s_dly_q[0] <= s;
    for (int i = 1; i < D; i++) s_dly_q[i] <= s_dly_q[i-1];
  end

  // ---- noise -------------------------------------------------------------------------------
  logic [P-1:0][63:0] word;
  logic               word_valid_q;
  logic [P-1:0][15:0] n;
  logic               n_valid;

  for (genvar i = 0; i < P; i++) begin : g_unif
    lfsr258 u_unif (
        .clk_i, .rst_i, .seed_i(noise_seed_i[i]), .en_i(tx_valid), .word_o(word[i]),
        /* verilator lint_off PINCONNECTEMPTY */
        .valid_o()  // stays high after the first word; word_valid_q marks each new word
        /* verilator lint_on PINCONNECTEMPTY */
    );
  end

  always_ff @(posedge clk_i) begin
    if (rst_i) word_valid_q <= 1'b0;
    else       word_valid_q <= tx_valid;
  end

  noise_gen #(.P(P), .INIT_FILE(INIT_FILE)) u_noise (
      .clk_i, .rst_i, .word_i(word), .valid_i(word_valid_q), .sigma_i, .n_o(n), .valid_o(n_valid)
  );

  // ---- y = sat(s + n, 16); x = sat(rs(y, 6), 7) ---------------------------------------------
  logic [P-1:0][15:0] y_q;
  logic               y_valid_q;

  always_ff @(posedge clk_i) begin
    for (int i = 0; i < P; i++) begin
      logic signed [YS_W-1:0] sum;
      logic signed [10:0]     r;  // (y + 32) >>> 6: |y| <= 32767 -> [-512, 512]
      sum = YS_W'($signed(s_dly_q[D-1][i])) + YS_W'($signed(n[i]));
      y_q[i] <= (sum > YS_W'(YMAX)) ? 16'(YMAX) : (sum < -YS_W'(YMAX)) ? 16'(-YMAX) : 16'(sum);
      r = 11'((32'($signed(y_q[i])) + 32) >>> 6);
      x_o[i] <= (r > 11'(XMAX)) ? 7'(XMAX) : (r < -11'(XMAX)) ? 7'(-XMAX) : 7'(r);
    end
    if (rst_i) {valid_o, y_valid_q} <= '0;
    else       {valid_o, y_valid_q} <= {y_valid_q, n_valid};
  end

`ifndef SYNTHESIS
  // FIR valid delayed by D must coincide with the noise valid (sim only: s_valid is otherwise
  // unused, the alignment is by construction).
  logic [D-1:0] sv_dly_q;
  always_ff @(posedge clk_i) begin
    if (rst_i) sv_dly_q <= '0;
    else       sv_dly_q <= {sv_dly_q[D-2:0], s_valid};
  end
  a_aligned : assert property (@(posedge clk_i) disable iff (rst_i) sv_dly_q[D-1] == n_valid);
`endif

endmodule
`default_nettype wire
