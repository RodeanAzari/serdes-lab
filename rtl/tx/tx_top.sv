`default_nettype none
// TX: PRBS31 payload -> RS(544,514) encoder -> gearbox (10 -> 2P bits) -> Gray map / precoder.
// Model: model/tx.py tx(): output symbol k (counted from the first valid word) is lane k mod P
// of word k div P and equals tx(...).a[k].
//
// One payload symbol = 10 PRBS bits, first bit = MSB. Codewords are back to back from reset.
// The encoder supplies up to one RS symbol (10 bits) per clock and the map consumes 2P <= 10,
// so after the pipeline fills valid_o stays high every clock (asserted below).
//
// Latency from reset release to the first valid word: 2 clocks (gearbox fill + map register).
module tx_top #(
    parameter int P = 4
) (
    input  wire logic              clk_i,
    input  wire logic              rst_i,
    input  wire logic [30:0]       prbs_seed_i,  // nonzero; loaded during reset
    input  wire logic              precode_i,    // change only during reset
    output logic      [P-1:0][2:0] a_o,          // PAM4 levels, symbol 0 first
    output logic      [P-1:0][1:0] idx_o,        // level index 0..3
    output logic                   valid_o
);
  localparam int M = 10;

  if (2 * P > M) begin : g_bad_p
    $error("tx_top: 2P = %0d bits/clock exceeds one RS symbol per clock (M = %0d)", 2 * P, M);
  end

  logic [M-1:0]   prbs_bits, pay_sym, cw_sym;
  logic           pay_ready, cw_valid, cw_ready;
  logic [2*P-1:0] gb_data;
  logic           gb_valid;

  prbs31_par #(.W(M)) u_prbs (
      .clk_i, .rst_i, .seed_i(prbs_seed_i), .en_i(pay_ready), .data_o(prbs_bits)
  );

  // PRBS bit 0 is first in the stream and becomes the payload symbol's MSB.
  always_comb for (int i = 0; i < M; i++) pay_sym[M-1-i] = prbs_bits[i];

  rs_enc u_enc (
      .clk_i, .rst_i,
      .s_axis_tdata_i(pay_sym), .s_axis_tvalid_i(1'b1), .s_axis_tready_o(pay_ready),
      .m_axis_tdata_o(cw_sym), .m_axis_tvalid_o(cw_valid), .m_axis_tready_i(cw_ready),
      // Framing is counted from reset (symbol k belongs to codeword k div 2720), so the TX
      // has no use for the encoder's tlast.
      /* verilator lint_off PINCONNECTEMPTY */
      .m_axis_tlast_o()
      /* verilator lint_on PINCONNECTEMPTY */
  );

  gearbox #(.IN_W(M), .OUT_W(2 * P)) u_gb (
      .clk_i, .rst_i, .s_data_i(cw_sym), .s_valid_i(cw_valid), .s_ready_o(cw_ready),
      .data_o(gb_data), .valid_o(gb_valid)
  );

  pam4_map #(.P(P)) u_map (
      .clk_i, .rst_i, .precode_i, .data_i(gb_data), .valid_i(gb_valid),
      .idx_o, .a_o, .valid_o
  );

`ifndef SYNTHESIS
  // The channel consumes a symbol every clock: once started, the TX must never underrun.
  a_no_underrun : assert property (@(posedge clk_i) disable iff (rst_i) valid_o |=> valid_o);
`endif

endmodule
`default_nettype wire
