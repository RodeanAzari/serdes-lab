`default_nettype none
// Arty A7-100T board top for the hardware noise histogram (ADR 0009; protocol docs/registers.md):
//   MII RX -> eth_rx -> udp_rx -> noise_hist_core -> udp_tx -> eth_tx -> MII TX
// fpga-eth-core at eth-core-v0.2 (submodule rtl/eth): MAC/UDP from its rtl/, clk_gen and
// reset_sync from its examples (consumer guide: "A minimal top level"). One core domain at
// 125 MHz; the PHY clocks only touch eth_rx/eth_tx internals.
//
// Replies go to the sender of the command (MAC/IP/port latched at the command's tlast; no ARP).
// Start-up as the eth-core examples: PHY reset released at 10 ms, the MAC at 200 ms after lock.
// The noise core leaves reset with the core clock (it needs no PHY clock).
//
// LEDs: led[0] 1 Hz heartbeat · led[1] run gate (generating) · led[2] configured-and-idle
//       (CONFIG received, not running) · led[3] MAC out of reset.
module noise_hist_top #(
    parameter int          CLK_HZ           = 125_000_000,
    parameter int          PHY_RST_CYCLES   = CLK_HZ / 100,  // 10 ms
    parameter int          MAC_START_CYCLES = CLK_HZ / 5,    // 200 ms
    parameter logic [47:0] OWN_MAC          = 48'h02_00_0A_0B_0C_0D,  // = the host's static neighbour for 192.168.10.2 (no ARP; one board)
    parameter logic [31:0] OWN_IP           = 32'hC0_A8_0A_02,  // 192.168.10.2
    parameter logic [15:0] UDP_PORT         = 16'd26400,
    parameter logic [31:0] BUILD_ID         = 32'h0,            // git commit (syn script)
    parameter string       INIT_FILE        = "noise_tables.mem"
) (
    input  wire logic       CLK100MHZ,
    input  wire logic       ck_rst,        // active low
    output logic [3:0]      led,
    output logic            uart_rxd_out,  // unused: idle high
    output logic            eth_ref_clk,
    output logic            eth_rstn,
    input  wire logic       eth_rx_clk,
    input  wire logic       eth_rx_dv,
    input  wire logic [3:0] eth_rxd,
    input  wire logic       eth_rxerr,
    input  wire logic       eth_tx_clk,
    output logic            eth_tx_en,
    output logic [3:0]      eth_txd,
    output logic            eth_mdc
);
  localparam int START_W = $clog2(MAC_START_CYCLES + 1);
  localparam int HB_W    = $clog2(CLK_HZ / 2);

  // ---- clocks and resets --------------------------------------------------------------------
  logic clk, clk_ref_unused, locked, rst;

  clk_gen u_clk (
      .clk100_i(CLK100MHZ), .clk_core_o(clk), .clk_ref_o(clk_ref_unused),
      .eth_ref_clk_o(eth_ref_clk), .locked_o(locked)
  );

  reset_sync u_rst_core (.clk_i(clk), .rst_req_i(!ck_rst || !locked), .rst_o(rst));

  logic [START_W-1:0] start_q;
  logic               mac_rst_q, mii_rx_rst, mii_tx_rst;

  always_ff @(posedge clk) begin
    if (rst) begin
      start_q   <= '0;
      eth_rstn  <= 1'b0;
      mac_rst_q <= 1'b1;
    end else begin
      if (start_q != START_W'(MAC_START_CYCLES)) start_q <= start_q + 1'b1;
      eth_rstn  <= start_q >= START_W'(PHY_RST_CYCLES);
      mac_rst_q <= start_q != START_W'(MAC_START_CYCLES);
    end
  end

  reset_sync u_rst_mii_rx (.clk_i(eth_rx_clk), .rst_req_i(mac_rst_q), .rst_o(mii_rx_rst));
  reset_sync u_rst_mii_tx (.clk_i(eth_tx_clk), .rst_req_i(mac_rst_q), .rst_o(mii_tx_rst));

  assign eth_mdc      = 1'b0;
  assign uart_rxd_out = 1'b1;

  // ---- receive ------------------------------------------------------------------------------
  logic [7:0]  f_tdata, c_tdata, r_tdata, t_tdata;
  logic        f_tvalid, f_tready, f_tlast;
  logic        c_tvalid, c_tready, c_tlast, c_tuser;
  logic        r_tvalid, r_tready, r_tlast;
  logic        t_tvalid, t_tready, t_tlast;
  logic [47:0] src_mac, peer_mac_q;
  logic [31:0] src_ip, peer_ip_q;
  logic [15:0] src_port, peer_port_q;

  /* verilator lint_off PINCONNECTEMPTY */
  eth_rx u_eth_rx (
      .mii_clk_i(eth_rx_clk), .mii_rst_i(mii_rx_rst), .mii_rxd_i(eth_rxd),
      .mii_rx_dv_i(eth_rx_dv), .mii_rx_er_i(eth_rxerr), .sfd_o(),
      .clk_i(clk), .rst_i(mac_rst_q),
      .m_tdata_o(f_tdata), .m_tvalid_o(f_tvalid), .m_tready_i(f_tready), .m_tlast_o(f_tlast),
      .frame_ok_o(), .crc_err_o(), .rx_err_o(), .runt_o(), .oversize_o(), .ovf_o(),
      .ovf_frames_o(), .fifo_level_o()
  );

  udp_rx u_udp_rx (
      .clk_i(clk), .rst_i(mac_rst_q),
      .cfg_mac_i(OWN_MAC), .cfg_ip_i(OWN_IP), .cfg_port_i(UDP_PORT),
      .s_tdata_i(f_tdata), .s_tvalid_i(f_tvalid), .s_tready_o(f_tready), .s_tlast_i(f_tlast),
      .m_tdata_o(c_tdata), .m_tvalid_o(c_tvalid), .m_tready_i(c_tready), .m_tlast_o(c_tlast),
      .m_tuser_o(c_tuser),
      .src_mac_o(src_mac), .src_ip_o(src_ip), .src_port_o(src_port), .dst_port_o(),
      .ok_o(), .filtered_o(), .ip_csum_err_o(), .malformed_o()
  );
  /* verilator lint_on PINCONNECTEMPTY */

  // reply address: the sender of the command just received
  always_ff @(posedge clk) begin
    if (c_tvalid && c_tready && c_tlast) begin
      peer_mac_q  <= src_mac;
      peer_ip_q   <= src_ip;
      peer_port_q <= src_port;
    end
  end

  // ---- noise histogram core -----------------------------------------------------------------
  logic run_led, cfg_led, configured;

  noise_hist_core #(.INIT_FILE(INIT_FILE), .BUILD_ID(BUILD_ID)) u_core (
      .clk_i(clk), .rst_i(rst),
      .s_tdata_i(c_tdata), .s_tvalid_i(c_tvalid), .s_tready_o(c_tready), .s_tlast_i(c_tlast),
      .s_tuser_i(c_tuser),
      .m_tdata_o(r_tdata), .m_tvalid_o(r_tvalid), .m_tready_i(r_tready), .m_tlast_o(r_tlast),
      .run_o(run_led), .configured_o(configured)
  );

  assign cfg_led = configured && !run_led;

  // ---- transmit -----------------------------------------------------------------------------
  /* verilator lint_off PINCONNECTEMPTY */
  udp_tx u_udp_tx (
      .clk_i(clk), .rst_i(mac_rst_q), .cfg_mac_i(OWN_MAC), .cfg_ip_i(OWN_IP),
      .s_tdata_i(r_tdata), .s_tvalid_i(r_tvalid), .s_tready_o(r_tready), .s_tlast_i(r_tlast),
      .s_tuser_i(1'b0),
      .dst_mac_i(peer_mac_q), .dst_ip_i(peer_ip_q), .dst_port_i(peer_port_q),
      .src_port_i(UDP_PORT),
      .m_tdata_o(t_tdata), .m_tvalid_o(t_tvalid), .m_tready_i(t_tready), .m_tlast_o(t_tlast),
      .sent_o(), .oversize_o()
  );

  eth_tx u_eth_tx (
      .clk_i(clk), .rst_i(mac_rst_q),
      .s_tdata_i(t_tdata), .s_tvalid_i(t_tvalid), .s_tready_o(t_tready), .s_tlast_i(t_tlast),
      .underrun_o(),
      .mii_clk_i(eth_tx_clk), .mii_rst_i(mii_tx_rst), .mii_txd_o(eth_txd), .mii_tx_en_o(eth_tx_en)
  );
  /* verilator lint_on PINCONNECTEMPTY */

  // ---- LEDs ---------------------------------------------------------------------------------
  logic [HB_W-1:0] hb_q;
  logic            hb_led_q;

  always_ff @(posedge clk) begin
    if (rst) begin
      hb_q     <= '0;
      hb_led_q <= 1'b0;
    end else if (hb_q == HB_W'(CLK_HZ / 2 - 1)) begin
      hb_q     <= '0;
      hb_led_q <= !hb_led_q;
    end else begin
      hb_q <= hb_q + 1'b1;
    end
  end

  assign led = {!mac_rst_q, cfg_led, run_led, hb_led_q};

endmodule
`default_nettype wire
