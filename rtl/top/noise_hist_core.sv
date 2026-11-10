`default_nettype none
// Noise histogram datapath + control, no clocks/Ethernet (ADR 0009; protocol docs/registers.md):
//   noise_ctrl -> lfsr258 x 8 -> noise_gen x 2 (P = 4) -> hist_bram x 8 -> noise_ctrl readout
// Lane l = noise_gen l / 4, lane l % 4; its seed is CONFIG seed l. Byte streams are the UDP
// payloads of udp_rx / udp_tx.
module noise_hist_core #(
    parameter  string       INIT_FILE = "noise_tables.mem",
    parameter  logic [31:0] BUILD_ID  = 32'h0,
    localparam int          LANES     = 8,
    localparam int          P         = 4,
    localparam int          IDX_W     = 10,
    localparam int          COUNT_W   = 48
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
    output logic            run_o,         // status (LEDs): generator running
    output logic            configured_o   // CONFIG accepted
);
  logic [LANES-1:0][319:0]       seed;
  logic                          seed_load, en, clear;
  logic [16:0]                   sigma;
  logic [$clog2(LANES)-1:0]      rd_lane;
  logic                          rd_en;
  logic [IDX_W-1:0]              rd_addr;
  logic [LANES-1:0][COUNT_W-1:0] rd_data;
  logic [LANES-1:0]              rd_valid, busy;

  noise_ctrl #(.LANES(LANES), .IDX_W(IDX_W), .COUNT_W(COUNT_W), .BUILD_ID(BUILD_ID)) u_ctrl (
      .clk_i, .rst_i, .s_tdata_i, .s_tvalid_i, .s_tready_o, .s_tlast_i, .s_tuser_i,
      .m_tdata_o, .m_tvalid_o, .m_tready_i, .m_tlast_o,
      .seed_o(seed), .seed_load_o(seed_load), .sigma_o(sigma), .en_o(en), .configured_o,
      .clear_o(clear), .hist_busy_i(|busy),
      .rd_lane_o(rd_lane), .rd_en_o(rd_en), .rd_addr_o(rd_addr),
      .rd_data_i(rd_data[rd_lane]), .rd_valid_i(rd_valid[rd_lane])
  );

  assign run_o = en;

  // ---- uniform words: one lfsr258 per lane, stepped by the run gate -----------------------
  logic [LANES-1:0][63:0] word;
  logic                   word_valid_q;

  for (genvar l = 0; l < LANES; l++) begin : g_unif
    lfsr258 u_unif (
        .clk_i, .rst_i(rst_i || seed_load), .seed_i(seed[l]), .en_i(en), .word_o(word[l]),
        /* verilator lint_off PINCONNECTEMPTY */
        .valid_o()  // stays high after the first word; word_valid_q marks each new word
        /* verilator lint_on PINCONNECTEMPTY */
    );
  end

  always_ff @(posedge clk_i) begin
    if (rst_i) word_valid_q <= 1'b0;
    else       word_valid_q <= en;
  end

  // ---- noise and histograms ----------------------------------------------------------------
  for (genvar g = 0; g < LANES / P; g++) begin : g_noise
    logic [P-1:0][15:0] n;
    logic               n_valid;

    noise_gen #(.P(P), .INIT_FILE(INIT_FILE)) u_noise (
        .clk_i, .rst_i, .word_i(word[g*P +: P]), .valid_i(word_valid_q), .sigma_i(sigma),
        .n_o(n), .valid_o(n_valid)
    );

    for (genvar k = 0; k < P; k++) begin : g_hist
      hist_bram #(.DATA_W(16), .IDX_W(IDX_W), .COUNT_W(COUNT_W)) u_hist (
          .clk_i, .rst_i, .n_i(n[k]), .valid_i(n_valid), .clear_i(clear), .busy_o(busy[g*P+k]),
          .rd_en_i(rd_en), .rd_addr_i(rd_addr),
          .rd_data_o(rd_data[g*P+k]), .rd_valid_o(rd_valid[g*P+k])
      );
    end
  end

endmodule
`default_nettype wire
