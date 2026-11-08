`default_nettype none
// Gray map + optional 1/(1+D) mod 4 precoder, P symbols per clock (ADR 0006; model:
// model/pam4.py bits_to_gray, precode). Symbol s of a word uses bits (A, B) = (d[2s], d[2s+1]),
// stream order; G = {A, A ^ B} (00->0, 01->1, 11->2, 10->3).
// Precoder: P(j) = (G(j) - P(j-1)) mod 4, P(-1) = 0 at reset; the state chains through the P
// symbols of a word and carries across words. Transmitted index = P if precode_i else G.
// Level a = 2 * index - 3 (-3, -1, +1, +3).
//
// precode_i must only change while rst_i is high (TX and RX precoders stay in lockstep).
// Latency: 1.
module pam4_map #(
    parameter int P = 4
) (
    input  wire logic               clk_i,
    input  wire logic               rst_i,
    input  wire logic               precode_i,
    input  wire logic [2*P-1:0]     data_i,
    input  wire logic               valid_i,
    output logic      [P-1:0][1:0]  idx_o,  // transmitted level index 0..3
    output logic      [P-1:0][2:0]  a_o,    // level, 3 b signed
    output logic                    valid_o
);
  logic [1:0]         prev_q;
  logic [P-1:0][1:0]  idx_d;
  logic [1:0]         last_d;

  always_comb begin
    logic [1:0] g, pr;
    pr = prev_q;
    for (int s = 0; s < P; s++) begin
      g = {data_i[2*s], data_i[2*s] ^ data_i[2*s+1]};
      idx_d[s] = precode_i ? (g - pr) : g;  // 2-bit wrap = mod 4 (specified, ADR 0006)
      pr = idx_d[s];
    end
    last_d = idx_d[P-1];
  end

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      prev_q  <= '0;
      valid_o <= 1'b0;
    end else begin
      valid_o <= valid_i;
      if (valid_i) prev_q <= last_d;
    end
    if (valid_i) begin
      idx_o <= idx_d;
      for (int s = 0; s < P; s++) a_o[s] <= {1'b0, idx_d[s]} + {1'b0, idx_d[s]} - 3'd3;
    end
  end

endmodule
`default_nettype wire
