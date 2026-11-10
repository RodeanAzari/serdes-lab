`default_nettype none
// Noise histogram run control and readout (ADR 0009; protocol: docs/registers.md).
//
// Sits between udp_rx (UDP payload bytes in) and udp_tx (reply payload bytes out). One command
// at a time: s_tready_o is low from a command's tlast until its reply has been sent.
// A truncated datagram (s_tuser_i on tlast) is dropped without a reply.
//
// CONFIG bytes 1..331 shift through cfg_sh_q (big-endian fields, fixed slices); they are
// applied two clocks after tlast (S_CHK registers the seed/sigma checks, then S_EXEC) only if
// the length is 332, the run is stopped, no clear is in progress, sigma < 2^17 and
// every seed word is valid. Nothing changes otherwise.
//
// Run gate en_o (registered): high while running and the word count is below N (N = 0:
// unbounded). words_q counts clocks with en_o high = words per lane; the run stops by itself
// with words_q == N exactly. drained: en_o has been low for DRAIN clocks (longer than the
// lfsr258 + noise_gen + hist_bram pipeline), so every word's sample has been counted.
// Today the gate is redundant for READ: the first rd_en follows the HDR + 2 reply bytes
// (>= 28 clocks) and the pipeline drains in 17, so removing it is an equivalent mutant
// (test_read_waits_for_drain checks the end-to-end property). Kept so READ stays correct if the
// header shrinks or the pipeline grows, and for STATUS.drained.
//
// READ reply: header, lane, chunk, then 128 bins, each read from the histogram (latency
// RD_LAT, rd_valid_i) and sent as 6 bytes big-endian.
module noise_ctrl #(
    parameter int          LANES    = 8,
    parameter int          IDX_W    = 10,
    parameter int          COUNT_W  = 48,
    parameter int          DRAIN    = 31,  // clocks; pipeline is 1 + 13 + 3 = 17
    parameter logic [31:0] BUILD_ID = 32'h0
) (
    input  wire logic                     clk_i,
    input  wire logic                     rst_i,
    // commands (udp_rx payload)
    input  wire logic [7:0]               s_tdata_i,
    input  wire logic                     s_tvalid_i,
    output logic                          s_tready_o,
    input  wire logic                     s_tlast_i,
    input  wire logic                     s_tuser_i,
    // replies (udp_tx payload)
    output logic      [7:0]               m_tdata_o,
    output logic                          m_tvalid_o,
    input  wire logic                     m_tready_i,
    output logic                          m_tlast_o,
    // generator
    output logic      [LANES-1:0][319:0]  seed_o,       // lfsr258 seed_i format per lane
    output logic                          seed_load_o,  // pulse: reset the lfsr258 lanes
    output logic      [16:0]              sigma_o,
    output logic                          en_o,         // run gate: step every lane
    output logic                          configured_o, // status (LED): CONFIG accepted
    // histograms
    output logic                          clear_o,      // pulse
    input  wire logic                     hist_busy_i,
    output logic      [$clog2(LANES)-1:0] rd_lane_o,
    output logic                          rd_en_o,
    output logic      [IDX_W-1:0]         rd_addr_o,
    input  wire logic [COUNT_W-1:0]       rd_data_i,    // from lane rd_lane_o
    input  wire logic                     rd_valid_i
);
  localparam int CFG_LEN  = 332;
  localparam int SH_W     = 8 * (CFG_LEN - 1);
  localparam int HDR      = 26;
  localparam int CHUNK    = 128;
  localparam int N_CHUNKS = (1 << IDX_W) / CHUNK;
  localparam int K[5]     = '{63, 55, 52, 47, 41};  // lfsr258 recurrence bits (model/prng.py)
  // Reset seed: model/prng.py SEED_MIN {y5..y1}, valid, so a lane is never in lock-up
  // (lfsr258 a_alive) before the first CONFIG. Never run: START needs CONFIG.
  localparam logic [319:0] SEED_RST = {64'd8388608, 64'd131072, 64'd4096, 64'd512, 64'd2};

  typedef enum logic [2:0] {S_RX, S_CHK, S_EXEC, S_HDR, S_FETCH, S_WAIT, S_BIN} state_t;
  state_t state_q;

  // ---- receive ---------------------------------------------------------------------------
  logic [SH_W-1:0] cfg_sh_q;
  logic [8:0]      idx_q;      // bytes seen in this datagram (saturates)
  logic [7:0]      op_q, arg1_q, arg2_q;
  logic [8:0]      len_q;
  logic            rx_fire;

  assign s_tready_o = (state_q == S_RX);
  assign rx_fire    = s_tvalid_i && s_tready_o;

  // CONFIG fields from the shift register (byte 1 at the top)
  logic [23:0]            c_sigma;
  logic [63:0]            c_len;
  logic [LANES-1:0][319:0] c_seed;
  logic                   c_seed_ok;
  logic                   cfg_ok_q;  // seed + sigma checks, registered in S_CHK (timing: 8 ns)

  always_comb begin
    c_sigma   = cfg_sh_q[SH_W-1 -: 24];
    c_len     = cfg_sh_q[SH_W-25 -: 64];
    c_seed_ok = 1'b1;
    for (int l = 0; l < LANES; l++) begin
      for (int w = 0; w < 5; w++) begin
        logic [63:0] y;
        y = cfg_sh_q[8 * 320 - 1 - 320 * l - 64 * w -: 64];  // lane l word y(w+1)
        c_seed[l][64*w +: 64] = y;
        if ((y >> (64 - K[w])) == '0) c_seed_ok = 1'b0;
      end
    end
  end

  // ---- run state --------------------------------------------------------------------------
  logic [63:0] words_q, runlen_q;
  logic [63:0] left_q;     // runlen_q - words_q when runlen_q != 0: the stop test needs no
                           // 64 b add + compare (timing: 8 ns, see the run-gate block)
  logic [16:0] sigma_q;
  logic        running_q, configured_q;
  logic [4:0]  idle_q;
  logic        drained, reached, clearing;

  assign reached  = (runlen_q != 0) && (left_q == 0);
  assign drained  = (idle_q == 5'(DRAIN));
  assign configured_o = configured_q;
  assign clearing = hist_busy_i || clear_o;
  assign sigma_o  = sigma_q;

  // ---- reply -----------------------------------------------------------------------------
  logic [8*(HDR+2)-1:0] hdr_q;
  logic [5:0]           hcnt_q;     // header byte
  logic                 rd_ok_q;    // READ accepted: bins follow the header
  logic [7:0]           bin_q;      // bin within chunk
  logic [2:0]           bcnt_q;     // byte within bin
  logic [COUNT_W-1:0]   cnt_q;
  logic [7:0]           code;
  logic                 apply_cfg, do_start, do_stop, do_read;

  always_comb begin
    code      = 8'd0;
    apply_cfg = 1'b0;
    do_start  = 1'b0;
    do_stop   = 1'b0;
    do_read   = 1'b0;
    unique case (op_q)
      8'h01: if (len_q != 9'(CFG_LEN))            code = 8'd2;
             else if (running_q || clearing)      code = 8'd1;
             else if (!cfg_ok_q)                  code = 8'd3;
             else                                 apply_cfg = 1'b1;
      8'h02: if (len_q != 9'd1)                   code = 8'd2;
             else if (!configured_q || clearing || reached) code = 8'd1;
             else                                 do_start = 1'b1;
      8'h03: if (len_q != 9'd1)                   code = 8'd2;
             else                                 do_stop = 1'b1;
      8'h04: if (len_q != 9'd3)                   code = 8'd2;
             else if (running_q || !drained || clearing) code = 8'd1;
             else if (arg1_q >= 8'(LANES) || arg2_q >= 8'(N_CHUNKS)) code = 8'd3;
             else                                 do_read = 1'b1;
      8'h05: if (len_q != 9'd1)                   code = 8'd2;
      default:                                    code = 8'd4;
    endcase
  end

  // run gate next state: stop with words == N exactly (N = runlen in force after this clock).
  // hit = (N != 0 && w_next >= N), without the 64 b add + compare: on a CONFIG clock w_next = 0
  // and N != 0, so it is false; otherwise words_q <= N (a_stops_at_n), so it is
  // w_next == N, i.e. left_q - en == 0.
  logic [63:0] w_next, n_next;
  logic        run_next, hit;

  always_comb begin
    w_next   = (state_q == S_EXEC && apply_cfg) ? 64'd0 : words_q + 64'(en_o);
    n_next   = (state_q == S_EXEC && apply_cfg) ? c_len : runlen_q;
    hit      = !(state_q == S_EXEC && apply_cfg) && runlen_q != 0
               && (en_o ? left_q == 64'd1 : left_q == 64'd0);
    run_next = running_q;
    if (state_q == S_EXEC && do_start) run_next = 1'b1;
    if (state_q == S_EXEC && do_stop)  run_next = 1'b0;
    if (hit) run_next = 1'b0;
  end

  always_comb begin
    m_tvalid_o = 1'b0;
    m_tlast_o  = 1'b0;
    m_tdata_o  = '0;
    if (state_q == S_HDR) begin
      m_tvalid_o = 1'b1;
      m_tdata_o  = hdr_q[8*(HDR+2)-1 - 8*hcnt_q -: 8];
      m_tlast_o  = !rd_ok_q && hcnt_q == 6'(HDR - 1);
    end else if (state_q == S_BIN) begin
      m_tvalid_o = 1'b1;
      m_tdata_o  = cnt_q[COUNT_W-1 - 8*bcnt_q -: 8];
      m_tlast_o  = bin_q == 8'(CHUNK - 1) && bcnt_q == 3'(COUNT_W / 8 - 1);
    end
  end

  assign rd_en_o   = (state_q == S_FETCH);
  assign rd_addr_o = IDX_W'(arg2_q * CHUNK + bin_q);

  always_ff @(posedge clk_i) begin
    seed_load_o <= 1'b0;
    clear_o     <= 1'b0;
    if (rx_fire) begin
      cfg_sh_q <= {cfg_sh_q[SH_W-9:0], s_tdata_i};
      if (idx_q == 9'd0) op_q   <= s_tdata_i;
      if (idx_q == 9'd1) arg1_q <= s_tdata_i;
      if (idx_q == 9'd2) arg2_q <= s_tdata_i;
    end

    cfg_ok_q  <= c_seed_ok && c_sigma[23:17] == '0;
    words_q   <= w_next;
    left_q    <= (state_q == S_EXEC && apply_cfg) ? c_len : left_q - 64'(en_o);
    running_q <= run_next;
    en_o      <= run_next;
    if (en_o) idle_q <= '0;
    else if (!drained) idle_q <= idle_q + 1'b1;

    unique case (state_q)
      S_RX: if (rx_fire) begin
        idx_q <= (idx_q == '1) ? idx_q : idx_q + 1'b1;
        if (s_tlast_i) begin
          len_q   <= (idx_q == '1) ? idx_q : idx_q + 1'b1;
          idx_q   <= '0;
          state_q <= s_tuser_i ? S_RX : S_CHK;  // truncated: drop silently
        end
      end
      S_CHK: state_q <= S_EXEC;  // cfg_sh_q is complete: cfg_ok_q settles
      S_EXEC: begin
        if (apply_cfg) begin
          seed_o       <= c_seed;
          sigma_q      <= c_sigma[16:0];
          runlen_q     <= c_len;
          configured_q <= 1'b1;
          seed_load_o  <= 1'b1;
          clear_o      <= 1'b1;
        end
        rd_lane_o <= $bits(rd_lane_o)'(arg1_q);
        rd_ok_q   <= do_read;
        // reply header: the state this command leaves (after this clock)
        hdr_q <= {(code == 8'd4) ? 8'hFF : (op_q | 8'h80), code,
                  3'b0, drained && !run_next, hit,
                  configured_q || apply_cfg, clearing || apply_cfg, run_next,
                  w_next, n_next, 7'd0, apply_cfg ? c_sigma[16:0] : sigma_q, BUILD_ID,
                  arg1_q, arg2_q};
        hcnt_q  <= '0;
        state_q <= S_HDR;
      end
      S_HDR: if (m_tready_i) begin
        hcnt_q <= hcnt_q + 1'b1;
        if (rd_ok_q ? hcnt_q == 6'(HDR + 1) : hcnt_q == 6'(HDR - 1)) begin
          bin_q   <= '0;
          state_q <= rd_ok_q ? S_FETCH : S_RX;
        end
      end
      S_FETCH: state_q <= S_WAIT;
      S_WAIT: if (rd_valid_i) begin
        cnt_q   <= rd_data_i;
        bcnt_q  <= '0;
        state_q <= S_BIN;
      end
      S_BIN: if (m_tready_i) begin
        bcnt_q <= bcnt_q + 1'b1;
        if (bcnt_q == 3'(COUNT_W / 8 - 1)) begin
          bin_q   <= bin_q + 1'b1;
          state_q <= (bin_q == 8'(CHUNK - 1)) ? S_RX : S_FETCH;
        end
      end
      default: state_q <= S_RX;
    endcase

    if (rst_i) begin
      state_q      <= S_RX;
      idx_q        <= '0;
      running_q    <= 1'b0;
      en_o         <= 1'b0;
      configured_q <= 1'b0;
      words_q      <= '0;
      runlen_q     <= '0;
      left_q       <= '0;
      sigma_q      <= '0;
      idle_q       <= '0;
      seed_load_o  <= 1'b0;
      clear_o      <= 1'b0;
      seed_o       <= {LANES{SEED_RST}};
    end
  end

`ifndef SYNTHESIS
  if (COUNT_W % 8 != 0) begin : g_bad_w
    $error("noise_ctrl: COUNT_W must be a whole number of bytes");
  end
  a_stops_at_n : assert property (@(posedge clk_i) disable iff (rst_i)
                                  !(runlen_q != 0 && words_q > runlen_q));
  a_left : assert property (@(posedge clk_i) disable iff (rst_i)
                            runlen_q == 0 || left_q == runlen_q - words_q);
`endif

endmodule
`default_nettype wire
