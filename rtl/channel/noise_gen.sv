`default_nettype none
// P Gaussian noise lanes (noise_lane), one coefficient ROM per lane pair (ADR 0005: 2 BRAM36 per
// pair, 3 DSP48E1 per lane). Uniform words come from the caller (one lfsr258 per lane, ADR 0007),
// so lane k's sample is model noise.noise(word k, tables, sigma).
//
// Latency 13 (word_i -> n_o, valid_o = valid_i delayed by 13), free running. Lane 0 first.
module noise_gen #(
    parameter int    P         = 4,
    parameter string INIT_FILE = "noise_tables.mem"
) (
    input  wire logic                  clk_i,
    input  wire logic                  rst_i,    // resets valid only
    input  wire logic [P-1:0][63:0]    word_i,   // bit 63 sign, 62:0 magnitude input
    input  wire logic                  valid_i,
    input  wire logic [16:0]           sigma_i,  // docs/fixed-point.md: sigma register
    output logic      [P-1:0][15:0]    n_o,      // signed, pre-ADC units
    output logic                       valid_o
);
  localparam int NR = (P + 1) / 2;  // ROMs

  logic [2*NR-1:0][9:0]  addr;
  /* verilator lint_off UNUSEDSIGNAL */  // odd P: the last ROM's port b output is unused
  logic [2*NR-1:0][64:0] data;
  /* verilator lint_on UNUSEDSIGNAL */
  logic [P-1:0]          vld;

  for (genvar k = 0; k < P; k++) begin : g_lane
    noise_lane u_lane (
      .clk_i      (clk_i),
      .rst_i      (rst_i),
      .word_i     (word_i[k]),
      .valid_i    (valid_i),
      .sigma_i    (sigma_i),
      .rom_addr_o (addr[k]),
      .rom_data_i (data[k]),
      .n_o        (n_o[k]),
      .valid_o    (vld[k])
    );
  end

  if (P % 2 == 1) begin : g_odd  // last ROM's second port unused
    assign addr[P] = '0;
  end

  for (genvar r = 0; r < NR; r++) begin : g_rom
    noise_rom #(.INIT_FILE(INIT_FILE)) u_rom (
      .clk_i    (clk_i),
      .addr_a_i (addr[2*r]),
      .addr_b_i (addr[2*r+1]),
      .data_a_o (data[2*r]),
      .data_b_o (data[2*r+1])
    );
  end

  assign valid_o = vld[0];  // identical in every lane

`ifndef SYNTHESIS
  a_lanes_in_step : assert property (@(posedge clk_i) vld == '0 || vld == '1);
`endif

endmodule
`default_nettype wire
