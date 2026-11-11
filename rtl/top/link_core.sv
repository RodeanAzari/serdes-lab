`default_nettype none
// Phase C emulated link with fixed-tap RX and pre-FEC BER counters, P symbols per clock:
//   channel_top (TX + channel + noise + ADC) -> rx_top -> bits --------------+-> ber_check
//   channel_top TX index -> demap (TX bits, same precoder setting) -----------+
//
// Frames (ADR 0011): m counts from the first TX symbol. x is defined from m = L - 1, the RX
// stream starts at M0 = P * ceil((L + N - 2) / P), and RX symbol m decides TX symbol m - K,
// K = cursor + n_pre (lag_i), so ber_check compares from TX symbol first = M0 - K.
// cfg_err_o: lag_i > M0 (no such TX symbol); the counts are then meaningless.
//
// All configuration is static: set it while rst_i is high (channel_top, rx_top, ber_check).
// Counters reflect an RX word 2 clocks after rx_top emits it (ber_check).
module link_core #(
    parameter  int    P         = 4,
    parameter  int    L         = 16,  // channel FIR taps
    parameter  int    N         = 16,  // FFE taps
    parameter  int    TAP_W     = 11,
    parameter  int    C_W       = 10,
    parameter  int    SH_W      = 4,
    parameter  int    B_W       = 10,
    parameter  int    T_W       = 10,
    parameter  int    CNT_W     = 64,
    parameter  int    H_W       = 16,
    parameter  string INIT_FILE = "noise_tables.mem",
    localparam int    M0        = P * ((L + N - 2 + P - 1) / P),
    localparam int    F_W       = $clog2(M0 + 1)
) (
    input  wire logic                     clk_i,
    input  wire logic                     rst_i,
    // channel
    input  wire logic [30:0]              prbs_seed_i,
    input  wire logic                     precode_i,  // TX precoder and RX inverse (lockstep)
    input  wire logic [L-1:0][TAP_W-1:0]  taps_i,
    input  wire logic [P-1:0][319:0]      noise_seed_i,
    input  wire logic [16:0]              sigma_i,
    // RX
    input  wire logic [N-1:0][C_W-1:0]    coef_i,
    input  wire logic [SH_W-1:0]          shift_i,
    input  wire logic [B_W-1:0]           b_i,
    input  wire logic [T_W-1:0]           t2_i,
    // checker
    input  wire logic [F_W-1:0]           lag_i,      // K = cursor + n_pre
    input  wire logic [H_W-1:0]           holdoff_i,  // RX words not counted
    output logic      [CNT_W-1:0]         bits_o,
    output logic      [CNT_W-1:0]         bit_err_o,
    output logic      [CNT_W-1:0]         sym_err_o,
    output logic                          err_o,      // FIFO over/underflow (ber_check)
    output logic                          cfg_err_o
);
  logic [P-1:0][6:0] x;
  logic              x_valid;
  logic [P-1:0][1:0] tx_idx;
  logic              tx_valid;

  channel_top #(.P(P), .L(L), .TAP_W(TAP_W), .INIT_FILE(INIT_FILE)) u_chan (
      .clk_i, .rst_i, .prbs_seed_i, .precode_i, .taps_i, .noise_seed_i, .sigma_i,
      .x_o(x), .valid_o(x_valid), .idx_o(tx_idx), .idx_valid_o(tx_valid)
  );

  logic [2*P-1:0] rx_bits, tx_bits;
  logic           rx_valid, tx_bits_valid;

  rx_top #(.P(P), .N(N), .X0(L - 1), .C_W(C_W), .SH_W(SH_W), .B_W(B_W), .T_W(T_W)) u_rx (
      .clk_i, .rst_i, .coef_i, .shift_i, .b_i, .t2_i, .precode_i, .x_i(x), .valid_i(x_valid),
      /* verilator lint_off PINCONNECTEMPTY */
      .z_o(), .z_valid_o(), .d_o(),
      /* verilator lint_on PINCONNECTEMPTY */
      .data_o(rx_bits), .valid_o(rx_valid)
  );

  demap #(.P(P)) u_ref (
      .clk_i, .rst_i, .precode_i, .d_i(tx_idx), .valid_i(tx_valid),
      /* verilator lint_off PINCONNECTEMPTY */
      .g_o(),
      /* verilator lint_on PINCONNECTEMPTY */
      .data_o(tx_bits), .valid_o(tx_bits_valid)
  );

  assign cfg_err_o = lag_i > F_W'(M0);

  ber_check #(.P(P), .CNT_W(CNT_W), .F_W(F_W), .H_W(H_W)) u_ber (
      .clk_i, .rst_i, .first_i(F_W'(M0) - lag_i), .holdoff_i,
      .tx_bits_i(tx_bits), .tx_valid_i(tx_bits_valid),
      .rx_bits_i(rx_bits), .rx_valid_i(rx_valid),
      .bits_o, .bit_err_o, .sym_err_o, .err_o
  );

endmodule
`default_nettype wire
