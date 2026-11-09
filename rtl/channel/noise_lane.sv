`default_nettype none
// One Gaussian noise lane: segmented inverse CDF, one sample per clock (ADR 0003/0005;
// model: model/noise.py noise(), formats: docs/fixed-point.md).
//
//   word_i = {s, u}: s = bit 63 sign, u = bits 62:0 magnitude input
//   normalize: lz = leading zeros of u (63 for u = 0), v = u << lz (63 b)
//   seg = {lz, v[61:58]} (ROM address), x = v[57:41] (17 b unsigned)
//   t = c1 + rs(x*c2, 17)       = (x*c2 + {c1, 1, 0^16}) >>> 17      exact: c1 rides in C
//   g = max(0, c0 + rs(x*t, 23)) = max(0, (x*t + {c0, 1, 0^22}) >>> 23)
//   n = sat(rs(g*sigma, 25), 16): (g*sigma + 2^24) >> 25, clipped to 2^15 - 1
//   out = s ? -n : n            (sign after rounding: symmetric pmf)
// rs = round half up; adding the half-LSB constant before the shift folds each rounding and
// coefficient add into one DSP48E1 post-add (P = A*B + C). 3 DSP48E1 per lane.
//
// Pipeline, latency 13 (word_i -> n_o, valid_o = valid_i delayed by 13), free running:
//   1-3   normalize, 2 shift steps per stage (32,16 | 8,4 | 2,1)       rom_addr_o after 3
//   4-5   ROM read (external noise_rom, latency 2)                     rom_data_i at 5
//   6-7   DSP1 x*c2 (M), + c1 (P)        8-9  DSP2 x*t (M), + c0 (P)
//   10    g = max(0, .)                  11-12 DSP3 g*sigma (M), + 2^24 (P)
//         (the clamp mirrors the model; with the committed tables the pre-clamp minimum over all
//         2^63 inputs is exactly 0, so it never engages: an equivalent mutant in bug injection)
//   13    saturate, apply sign
// sigma_i is sampled at stage 11: a change applies to samples from that stage on.
module noise_lane (
    input  wire logic        clk_i,
    input  wire logic        rst_i,       // resets valid only
    input  wire logic [63:0] word_i,
    input  wire logic        valid_i,
    input  wire logic [16:0] sigma_i,     // unsigned, units 2^-5 pre-ADC unit
    output logic      [9:0]  rom_addr_o,  // to noise_rom, registered
    input  wire logic [64:0] rom_data_i,  // {c2[16:0], c1[22:0], c0[24:0]}, 2 clocks later
    output logic      [15:0] n_o,         // signed, pre-ADC units
    output logic             valid_o
);
  localparam int LAT = 13;
  localparam int SH[6] = '{32, 16, 8, 4, 2, 1};

  // ---- 1-3: normalize ----------------------------------------------------------------------
  logic [62:0] nv_q[3];
  logic [5:0]  nlz_q[3];
  logic [62:0] nv_d[3];
  logic [5:0]  nlz_d[3];

  always_comb begin
    for (int s = 0; s < 3; s++) begin
      nv_d[s]  = (s == 0) ? word_i[62:0] : nv_q[s-1];
      nlz_d[s] = (s == 0) ? 6'd0 : nlz_q[s-1];
      for (int k = 2 * s; k < 2 * s + 2; k++) begin
        if ((nv_d[s] >> (63 - SH[k])) == '0) begin  // top SH[k] bits all zero
          nv_d[s]  = nv_d[s] << SH[k];
          nlz_d[s] = nlz_d[s] + 6'(SH[k]);
        end
      end
    end
  end

  always_ff @(posedge clk_i) begin
    for (int s = 0; s < 3; s++) begin
      nv_q[s]  <= nv_d[s];
      nlz_q[s] <= nlz_d[s];
    end
  end

  assign rom_addr_o = {nlz_q[2], nv_q[2][61:58]};

  // ---- 4-7: x alongside the ROM; DSP1 -----------------------------------------------------
  logic        [16:0] x_q4, x_q5, x_q6, x_q7;
  logic signed [22:0] c1_q6;
  logic signed [24:0] c0_q6, c0_q7, c0_q8;
  logic signed [47:0] m1_q, m2_q;
  // Low bits are the rounding remainders (>>> 17, >>> 23), discarded by design.
  /* verilator lint_off UNUSEDSIGNAL */
  logic signed [47:0] p1_q, p2_q;
  /* verilator lint_on UNUSEDSIGNAL */
  logic signed [22:0] t;

  assign t = p1_q[39:17];

  always_ff @(posedge clk_i) begin
    x_q4  <= nv_q[2][57:41];
    x_q5  <= x_q4;
    x_q6  <= x_q5;
    x_q7  <= x_q6;
    m1_q  <= 48'($signed({1'b0, x_q5})) * 48'($signed(rom_data_i[64:48]));
    c1_q6 <= rom_data_i[47:25];
    c0_q6 <= rom_data_i[24:0];
    p1_q  <= m1_q + 48'($signed({c1_q6, 1'b1, 16'd0}));  // sign-extend c1
    c0_q7 <= c0_q6;
    // ---- 8-9: DSP2
    m2_q  <= 48'($signed({1'b0, x_q7})) * 48'(t);
    c0_q8 <= c0_q7;
    p2_q  <= m2_q + {c0_q8, 1'b1, 22'd0};
  end

  // ---- 10-13: g, DSP3, saturate, sign -----------------------------------------------------
  logic        [23:0] g_q;
  logic        [47:0] m3_q;
  // [24:0]: rounding remainder (>> 25); [47:42]: always 0 (g*sigma + 2^24 < 2^42).
  /* verilator lint_off UNUSEDSIGNAL */
  logic        [47:0] p3_q;
  /* verilator lint_on UNUSEDSIGNAL */
  logic        [16:0] mag;
  logic signed [15:0] n_sat;

  assign mag   = p3_q[41:25];  // <= 2^16: g < 2^24, sigma < 2^17
  assign n_sat = (mag > 17'd32767) ? 16'sd32767 : 16'(mag);

  logic [LAT-1:0] sgn_q, vld_q;

  always_ff @(posedge clk_i) begin
    g_q  <= p2_q[47] ? '0 : p2_q[46:23];
    m3_q <= 48'(g_q) * 48'(sigma_i);
    p3_q <= m3_q + 48'h100_0000;
    n_o  <= sgn_q[LAT-2] ? -n_sat : n_sat;
    sgn_q <= {sgn_q[LAT-2:0], word_i[63]};
    if (rst_i) vld_q <= '0;
    else       vld_q <= {vld_q[LAT-2:0], valid_i};
  end

  assign valid_o = vld_q[LAT-1];

`ifndef SYNTHESIS
  // t is truncated from 40 to 23 b; model fit_stats proves 23 b over every reachable
  // (segment, x). Firing means a table or datapath defect. (g needs no check: p2_q[46:23]
  // holds every non-negative value.)
  a_t_fits : assert property (@(posedge clk_i) disable iff (rst_i)
                              vld_q[6] |-> (p1_q[47:39] == '0 || p1_q[47:39] == '1));
`endif

endmodule
`default_nettype wire
