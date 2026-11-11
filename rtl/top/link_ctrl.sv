`default_nettype none
// BER board run control and counter readout (ADR 0012; protocol: docs/registers.md).
//
// Sits between udp_rx (UDP payload bytes in) and udp_tx (reply payload bytes out), and drives
// link_core's static configuration and reset. One command at a time: s_tready_o is low from a
// command's tlast until its reply has been sent. A truncated datagram (s_tuser_i on tlast) is
// dropped without a reply.
//
// CONFIG bytes 1..CFG_LEN-1 shift through cfg_sh_q (big-endian fields, fixed slices); the
// checks are registered in S_CHK and the fields applied in S_EXEC, only if the length is right,
// the link is stopped and every field is valid. Nothing changes otherwise.
//
// link_rst_o is high whenever no run is in progress, so the configuration registers change
// only while link_core is in reset. START releases it (a new run from reset). While running,
// the live counters are copied into the snapshot every clock; the run stops on the edge where
// the live bits counter equals R (R != 0): the snapshot then holds exactly R bits. STOP ends a
// run at that clock. Every reply reports the snapshot as it is after the command's clock.
module link_ctrl #(
    parameter  int          P        = 4,
    parameter  int          L        = 16,  // channel taps
    parameter  int          N        = 16,  // FFE taps
    parameter  int          TAP_W    = 11,
    parameter  int          C_W      = 10,
    parameter  int          SH_W     = 4,
    parameter  int          B_W      = 10,
    parameter  int          T_W      = 10,
    parameter  int          H_W      = 16,
    parameter  int          F_W      = 6,   // lag width (link_core)
    parameter  int          M0       = 32,  // link_core RX start: lag must be <= M0
    parameter  logic [31:0] BUILD_ID = 32'h0,
    parameter  int          CNT_W    = 64
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
    // link_core configuration (static while link_rst_o is high)
    output logic                          link_rst_o,
    output logic      [30:0]              prbs_seed_o,
    output logic                          precode_o,
    output logic      [L-1:0][TAP_W-1:0]  taps_o,
    output logic      [P-1:0][319:0]      noise_seed_o,
    output logic      [16:0]              sigma_o,
    output logic      [N-1:0][C_W-1:0]    coef_o,
    output logic      [SH_W-1:0]          shift_o,
    output logic      [B_W-1:0]           b_o,
    output logic      [T_W-1:0]           t2_o,
    output logic      [F_W-1:0]           lag_o,
    output logic      [H_W-1:0]           holdoff_o,
    // link_core counters
    input  wire logic [CNT_W-1:0]         bits_i,
    input  wire logic [CNT_W-1:0]         bit_err_i,
    input  wire logic [CNT_W-1:0]         sym_err_i,
    input  wire logic                     err_i,
    // status (LEDs)
    output logic                          running_o,
    output logic                          configured_o
);
  // CONFIG byte offsets (byte 0 = op) and lengths
  localparam int O_R     = 1;   // 8 B run length R, bits
  localparam int O_PRBS  = 9;   // 4 B
  localparam int O_FLAGS = 13;  // 1 B: bit 0 precoder
  localparam int O_SIGMA = 14;  // 3 B
  localparam int O_LAG   = 17;  // 1 B
  localparam int O_HOLD  = 18;  // 2 B
  localparam int O_SHIFT = 20;  // 1 B
  localparam int O_B     = 21;  // 2 B, signed
  localparam int O_T2    = 23;  // 2 B, unsigned
  localparam int O_TAPS  = 25;  // L x 2 B, signed, tap 0 first
  localparam int O_COEF  = O_TAPS + 2 * L;  // N x 2 B, signed, coefficient 0 first
  localparam int O_SEED  = O_COEF + 2 * N;  // P lanes x y1..y5 x 8 B
  localparam int CFG_LEN = O_SEED + 40 * P;
  localparam int SR_W    = 8 * (CFG_LEN - 1);
  localparam int LEN_W   = $clog2(CFG_LEN + 2);  // saturating byte count, all-ones > CFG_LEN
  localparam int HDR     = 39;
  localparam int LP2     = $clog2(2 * P);
  localparam int K[5]    = '{63, 55, 52, 47, 41};  // lfsr258 recurrence bits (model/prng.py)
  // Reset seed: model/prng.py SEED_MIN {y5..y1}, valid (never lock-up before the first CONFIG).
  localparam logic [319:0] SEED_RST = {64'd8388608, 64'd131072, 64'd4096, 64'd512, 64'd2};

  // top bit of the field at byte offset o in cfg_sh_q (byte 1 at the top)
  function automatic int top(input int o);
    return SR_W - 1 - 8 * (o - 1);
  endfunction

  typedef enum logic [1:0] {S_RX, S_CHK, S_EXEC, S_HDR} state_t;
  state_t state_q;

  // ---- receive -----------------------------------------------------------------------------
  logic [SR_W-1:0]  cfg_sh_q;
  logic [LEN_W-1:0] idx_q, len_q;
  logic [7:0]       op_q;
  logic             rx_fire;

  assign s_tready_o = (state_q == S_RX);
  assign rx_fire    = s_tvalid_i && s_tready_o;

  // CONFIG fields and checks
  logic [63:0]               c_r;
  logic [31:0]               c_prbs;
  logic [7:0]                c_flags, c_lag, c_shift;
  logic [23:0]               c_sigma;
  logic [15:0]               c_hold, c_b, c_t2;
  logic [L-1:0][15:0]        c_tap;
  logic [N-1:0][15:0]        c_coef;
  logic [P-1:0][319:0]       c_seed;
  logic                      c_ok;
  logic                      cfg_ok_q;  // registered in S_CHK

  // value v (16 b field) is a sign extension of its low w bits
  function automatic logic fits_s(input logic [15:0] v, input int w);
    logic [15:0] hi;
    hi = 16'($signed(v) >>> (w - 1));
    return $signed(hi) == 0 || $signed(hi) == -1;
  endfunction

  always_comb begin
    c_r     = cfg_sh_q[top(O_R) -: 64];
    c_prbs  = cfg_sh_q[top(O_PRBS) -: 32];
    c_flags = cfg_sh_q[top(O_FLAGS) -: 8];
    c_sigma = cfg_sh_q[top(O_SIGMA) -: 24];
    c_lag   = cfg_sh_q[top(O_LAG) -: 8];
    c_hold  = cfg_sh_q[top(O_HOLD) -: 16];
    c_shift = cfg_sh_q[top(O_SHIFT) -: 8];
    c_b     = cfg_sh_q[top(O_B) -: 16];
    c_t2    = cfg_sh_q[top(O_T2) -: 16];
    c_ok    = c_prbs[31] == 1'b0 && c_prbs[30:0] != '0
              && c_flags[7:1] == '0
              && c_sigma[23:17] == '0
              && c_lag <= 8'(M0)
              && (c_hold >> H_W) == '0
              && (c_shift >> SH_W) == '0
              && fits_s(c_b, B_W)
              && (c_t2 >> T_W) == '0
              && c_r[LP2-1:0] == '0;
    for (int i = 0; i < L; i++) begin
      c_tap[i] = cfg_sh_q[top(O_TAPS) - 16 * i -: 16];
      if (!fits_s(c_tap[i], TAP_W)) c_ok = 1'b0;
    end
    for (int i = 0; i < N; i++) begin
      c_coef[i] = cfg_sh_q[top(O_COEF) - 16 * i -: 16];
      if (!fits_s(c_coef[i], C_W)) c_ok = 1'b0;
    end
    for (int l = 0; l < P; l++) begin
      for (int w = 0; w < 5; w++) begin
        logic [63:0] y;
        y = cfg_sh_q[top(O_SEED) - 320 * l - 64 * w -: 64];  // lane l word y(w+1)
        c_seed[l][64*w +: 64] = y;
        if ((y >> (64 - K[w])) == '0) c_ok = 1'b0;
      end
    end
  end

  // ---- run state -----------------------------------------------------------------------------
  logic [63:0]      runlen_q;
  logic             bounded_q;  // runlen_q != 0
  logic             running_q, configured_q, reached_q;
  logic [CNT_W-1:0] s_bits_q, s_berr_q, s_serr_q;
  logic             s_err_q;

  assign running_o    = running_q;
  assign configured_o = configured_q;

  // ---- command decode ------------------------------------------------------------------------
  logic [7:0] code;
  logic       apply_cfg, do_start, do_stop;

  always_comb begin
    code      = 8'd0;
    apply_cfg = 1'b0;
    do_start  = 1'b0;
    do_stop   = 1'b0;
    unique case (op_q)
      8'h01: if (len_q != LEN_W'(CFG_LEN))          code = 8'd2;
             else if (running_q)                    code = 8'd1;
             else if (!cfg_ok_q)                    code = 8'd3;
             else                                   apply_cfg = 1'b1;
      8'h02: if (len_q != LEN_W'(1))                code = 8'd2;
             else if (running_q || !configured_q)   code = 8'd1;
             else                                   do_start = 1'b1;
      8'h03: if (len_q != LEN_W'(1))                code = 8'd2;
             else                                   do_stop = 1'b1;
      8'h05: if (len_q != LEN_W'(1))                code = 8'd2;
      default:                                      code = 8'd4;
    endcase
  end

  // next run state; exec = a command takes effect on this clock
  logic             exec, hit, run_next, reached_next;
  logic [CNT_W-1:0] n_bits, n_berr, n_serr;
  logic             n_err;

  always_comb begin
    exec         = state_q == S_EXEC;
    hit          = running_q && bounded_q && 64'(bits_i) == runlen_q;
    run_next     = running_q;
    reached_next = reached_q;
    if (exec && do_start) begin
      run_next     = 1'b1;
      reached_next = 1'b0;
    end
    if (exec && apply_cfg) reached_next = 1'b0;
    if (exec && do_stop) run_next = 1'b0;
    if (hit) begin
      run_next     = 1'b0;
      reached_next = 1'b1;
    end
    {n_bits, n_berr, n_serr, n_err} = {s_bits_q, s_berr_q, s_serr_q, s_err_q};
    if (running_q) {n_bits, n_berr, n_serr, n_err} = {bits_i, bit_err_i, sym_err_i, err_i};
    if (exec && apply_cfg) {n_bits, n_berr, n_serr, n_err} = '0;
  end

  // ---- reply -----------------------------------------------------------------------------
  logic [8*HDR-1:0] hdr_q;
  logic [5:0]       hcnt_q;

  assign m_tvalid_o = (state_q == S_HDR);
  assign m_tdata_o  = hdr_q[8*HDR-1 - 8*hcnt_q -: 8];
  assign m_tlast_o  = (state_q == S_HDR) && hcnt_q == 6'(HDR - 1);

  always_ff @(posedge clk_i) begin
    if (rx_fire) begin
      cfg_sh_q <= {cfg_sh_q[SR_W-9:0], s_tdata_i};
      if (idx_q == '0) op_q <= s_tdata_i;
    end

    cfg_ok_q   <= c_ok;
    running_q  <= run_next;
    reached_q  <= reached_next;
    link_rst_o <= !run_next;
    {s_bits_q, s_berr_q, s_serr_q, s_err_q} <= {n_bits, n_berr, n_serr, n_err};

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
          runlen_q     <= c_r;
          bounded_q    <= c_r != '0;
          prbs_seed_o  <= c_prbs[30:0];
          precode_o    <= c_flags[0];
          sigma_o      <= c_sigma[16:0];
          lag_o        <= F_W'(c_lag);
          holdoff_o    <= H_W'(c_hold);
          shift_o      <= SH_W'(c_shift);
          b_o          <= B_W'(c_b);
          t2_o         <= T_W'(c_t2);
          for (int i = 0; i < L; i++) taps_o[i] <= TAP_W'(c_tap[i]);
          for (int i = 0; i < N; i++) coef_o[i] <= C_W'(c_coef[i]);
          noise_seed_o <= c_seed;
          configured_q <= 1'b1;
        end
        // reply header: the state this command leaves (after this clock)
        hdr_q <= {(code == 8'd4) ? 8'hFF : (op_q | 8'h80), code,
                  4'b0, n_err, reached_next, configured_q || apply_cfg, run_next,
                  64'(n_bits), 64'(n_berr), 64'(n_serr),
                  apply_cfg ? c_r : runlen_q, BUILD_ID};
        hcnt_q  <= '0;
        state_q <= S_HDR;
      end
      S_HDR: if (m_tready_i) begin
        hcnt_q <= hcnt_q + 1'b1;
        if (hcnt_q == 6'(HDR - 1)) state_q <= S_RX;
      end
      default: state_q <= S_RX;
    endcase

    if (rst_i) begin
      state_q      <= S_RX;
      idx_q        <= '0;
      running_q    <= 1'b0;
      reached_q    <= 1'b0;
      configured_q <= 1'b0;
      link_rst_o   <= 1'b1;
      runlen_q     <= '0;
      bounded_q    <= 1'b0;
      {s_bits_q, s_berr_q, s_serr_q, s_err_q} <= '0;
      prbs_seed_o  <= 31'd1;
      noise_seed_o <= {P{SEED_RST}};
    end
  end

`ifndef SYNTHESIS
  if (F_W > 8 || H_W > 16 || TAP_W > 16 || C_W > 16 || B_W > 16 || T_W > 16 || SH_W > 8
      || CNT_W > 64 || M0 > 255) begin : g_bad_w
    $error("link_ctrl: a field is wider than its CONFIG bytes");
  end
  a_stops_at_r : assert property (@(posedge clk_i) disable iff (rst_i)
                                  !(bounded_q && 64'(s_bits_q) > runlen_q));
  a_rst_when_idle : assert property (@(posedge clk_i) disable iff (rst_i)
                                     link_rst_o == !running_q);
`endif

endmodule
`default_nettype wire
