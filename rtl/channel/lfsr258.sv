`default_nettype none
// L'Ecuyer lfsr258 uniform source, one 64-bit word per enabled clock (ADR 0003, ADR 0007;
// model: model/prng.py lfsr258_words, bit-exact vs the reference C code).
//
// Per component (k, q, s, mask):  b = ((y << q) ^ y) >> (k - s);  y' = ((y & mask) << s) ^ b
// Output word = y1' ^ y2' ^ y3' ^ y4' ^ y5' (state after the update, as the reference code).
//
// Latency: 1. Reset loads seed_i (5 x 64 b, y1 in the low word). Each clock with en_i high
// steps the state and registers the next word into word_o; valid_o rises with the first word
// and stays high until the next reset. Word m after reset = model step m.
module lfsr258 (
    input  wire logic         clk_i,
    input  wire logic         rst_i,   // synchronous, active high: loads seed_i
    input  wire logic [319:0] seed_i,  // y5 y4 y3 y2 y1; each above SEED_MIN (model/prng.py)
    input  wire logic         en_i,
    output logic      [63:0]  word_o,
    output logic              valid_o
);
  localparam int NC = 5;
  localparam int K[NC] = '{63, 55, 52, 47, 41};
  localparam int Q[NC] = '{1, 24, 3, 5, 3};
  localparam int S[NC] = '{10, 5, 29, 23, 8};

  logic [63:0] y_q[NC];
  logic [63:0] y_d[NC];
  logic [63:0] word_d;

  always_comb begin
    word_d = '0;
    for (int c = 0; c < NC; c++) begin
      // mask clears the low 64 - K bits; b holds the S new bits below the kept ones
      y_d[c] = ((y_q[c] & ({64{1'b1}} << (64 - K[c]))) << S[c])
             ^ (((y_q[c] << Q[c]) ^ y_q[c]) >> (K[c] - S[c]));
      word_d ^= y_d[c];
    end
  end

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      for (int c = 0; c < NC; c++) y_q[c] <= seed_i[64*c +: 64];
      valid_o <= 1'b0;
    end else if (en_i) begin
      for (int c = 0; c < NC; c++) y_q[c] <= y_d[c];
      word_o  <= word_d;
      valid_o <= 1'b1;
    end
  end

`ifndef SYNTHESIS
  // Each component's recurrence lives in its top K bits; all-zero there is lock-up
  // (seed below SEED_MIN or a broken update).
  for (genvar c = 0; c < NC; c++) begin : g_chk
    a_alive : assert property (@(posedge clk_i) disable iff (rst_i)
                               (y_q[c] >> (64 - K[c])) != '0);
  end
`endif

endmodule
`default_nettype wire
