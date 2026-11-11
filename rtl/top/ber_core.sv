`default_nettype none
// BER board datapath + control, no clocks/Ethernet (ADR 0012; protocol docs/registers.md):
//   link_ctrl (UDP payload in/out) -> configuration + reset -> link_core -> counters -> link_ctrl
// Byte streams are the UDP payloads of udp_rx / udp_tx.
module ber_core #(
    parameter  int          P         = 4,
    parameter  string       INIT_FILE = "noise_tables.mem",
    parameter  logic [31:0] BUILD_ID  = 32'h0,
    localparam int          L         = 16,  // channel taps
    localparam int          N         = 16,  // FFE taps
    localparam int          TAP_W     = 11,
    localparam int          C_W       = 10,
    localparam int          SH_W      = 4,
    localparam int          B_W       = 10,
    localparam int          T_W       = 10,
    localparam int          H_W       = 16,
    localparam int          M0        = P * ((L + N - 2 + P - 1) / P),  // = link_core
    localparam int          F_W       = $clog2(M0 + 1)
) (
    input  wire logic       clk_i,
    input  wire logic       rst_i,
    input  wire logic [7:0] s_tdata_i,
    input  wire logic       s_tvalid_i,
    output logic            s_tready_o,
    input  wire logic       s_tlast_i,
    input  wire logic       s_tuser_i,
    output logic      [7:0] m_tdata_o,
    output logic            m_tvalid_o,
    input  wire logic       m_tready_i,
    output logic            m_tlast_o,
    output logic            running_o,     // status (LEDs)
    output logic            configured_o
);
  logic                    link_rst, precode, err;
  logic                    link_rst_any;  // link_ctrl's register is not reset until rst_i's first edge
  logic [30:0]             prbs_seed;
  logic [L-1:0][TAP_W-1:0] taps;
  logic [P-1:0][319:0]     noise_seed;
  logic [16:0]             sigma;
  logic [N-1:0][C_W-1:0]   coef;
  logic [SH_W-1:0]         shift;
  logic [B_W-1:0]          b;
  logic [T_W-1:0]          t2;
  logic [F_W-1:0]          lag;
  logic [H_W-1:0]          holdoff;
  logic [63:0]             bits, bit_err, sym_err;

  link_ctrl #(.P(P), .L(L), .N(N), .TAP_W(TAP_W), .C_W(C_W), .SH_W(SH_W), .B_W(B_W),
              .T_W(T_W), .H_W(H_W), .F_W(F_W), .M0(M0), .BUILD_ID(BUILD_ID)) u_ctrl (
      .clk_i, .rst_i, .s_tdata_i, .s_tvalid_i, .s_tready_o, .s_tlast_i, .s_tuser_i,
      .m_tdata_o, .m_tvalid_o, .m_tready_i, .m_tlast_o,
      .link_rst_o(link_rst), .prbs_seed_o(prbs_seed), .precode_o(precode), .taps_o(taps),
      .noise_seed_o(noise_seed), .sigma_o(sigma), .coef_o(coef), .shift_o(shift), .b_o(b),
      .t2_o(t2), .lag_o(lag), .holdoff_o(holdoff),
      .bits_i(bits), .bit_err_i(bit_err), .sym_err_i(sym_err), .err_i(err),
      .running_o, .configured_o
  );

  assign link_rst_any = rst_i || link_rst;

  link_core #(.P(P), .L(L), .N(N), .TAP_W(TAP_W), .C_W(C_W), .SH_W(SH_W), .B_W(B_W),
              .T_W(T_W), .H_W(H_W), .INIT_FILE(INIT_FILE)) u_link (
      .clk_i, .rst_i(link_rst_any), .prbs_seed_i(prbs_seed), .precode_i(precode), .taps_i(taps),
      .noise_seed_i(noise_seed), .sigma_i(sigma), .coef_i(coef), .shift_i(shift), .b_i(b),
      .t2_i(t2), .lag_i(lag), .holdoff_i(holdoff),
      .bits_o(bits), .bit_err_o(bit_err), .sym_err_o(sym_err), .err_o(err),
      /* verilator lint_off PINCONNECTEMPTY */
      .cfg_err_o()  // lag <= M0 is checked by link_ctrl before it is applied
      /* verilator lint_on PINCONNECTEMPTY */
  );

endmodule
`default_nettype wire
