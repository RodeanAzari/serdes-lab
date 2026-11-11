`default_nettype none
// RX demap, P symbols per clock: inverse of rtl/tx/pam4_map.sv (ADR 0006; model: model/pam4.py
// precode_inverse, gray_to_bits). For decided level index d (0..3):
//     G(j) = precode_i ? (d(j) + d(j-1)) mod 4 : d(j),   d(-1) = 0 at reset   (Eq. 135-3)
//     bits (A, B) = (G[1], G[1] ^ G[0])                    (G = {A, A ^ B} in pam4_map)
// Symbol s of a word gives data_o[2s] = A, data_o[2s+1] = B: the TX stream order.
// The state chains through the P symbols of a word and carries across words, on valid only.
// precode_i must only change while rst_i is high (TX and RX in lockstep, ADR 0006).
// Latency: 1.
module demap #(
    parameter int P = 4
) (
    input  wire logic               clk_i,
    input  wire logic               rst_i,
    input  wire logic               precode_i,
    input  wire logic [P-1:0][1:0]  d_i,     // decided level index
    input  wire logic               valid_i,
    output logic      [P-1:0][1:0]  g_o,     // Gray symbol
    output logic      [2*P-1:0]     data_o,  // bits, stream order
    output logic                    valid_o
);
  logic [1:0]        prev_q;
  logic [P-1:0][1:0] g_d;

  always_comb begin
    logic [1:0] pr;
    pr = prev_q;
    for (int s = 0; s < P; s++) begin
      g_d[s] = precode_i ? (d_i[s] + pr) : d_i[s];  // 2-bit wrap = mod 4 (specified)
      pr = d_i[s];
    end
  end

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      prev_q  <= '0;
      valid_o <= 1'b0;
    end else begin
      valid_o <= valid_i;
      if (valid_i) prev_q <= d_i[P-1];
    end
    if (valid_i) begin
      g_o <= g_d;
      for (int s = 0; s < P; s++) begin
        data_o[2*s]   <= g_d[s][1];
        data_o[2*s+1] <= g_d[s][1] ^ g_d[s][0];
      end
    end
  end

endmodule
`default_nettype wire
