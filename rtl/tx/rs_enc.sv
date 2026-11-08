`default_nettype none
// Systematic Reed-Solomon encoder, one symbol per clock (KP4: RS(544,514), GF(2^10), x^10+x^3+1,
// generator roots alpha^0..alpha^(NPAR-1); buildplan §6.2). Model: model/rs.py encode().
//
//   message phase (K symbols): m_axis = s_axis (combinational pass-through, ready = m ready);
//                              on each handshake fb = sym ^ p[0]; p <= (p << 1) ^ fb * GEN[1..NPAR]
//   parity phase (NPAR symbols): m_axis = p[0], s_axis_tready_o low; p shifts out on handshake
//   m_axis_tlast_o on symbol N-1. Codewords are counted from reset (no input framing).
//
// Latency: 0 (message symbols pass through; parity follows the last message symbol directly).
// GEN is computed at elaboration; each fb * GEN[i] is a constant multiply (an XOR network).
module rs_enc #(
    parameter int M         = 10,
    parameter int PRIM_POLY = 'h409,  // x^10 + x^3 + 1
    parameter int N         = 544,
    parameter int K         = 514
) (
    input  wire logic         clk_i,
    input  wire logic         rst_i,
    input  wire logic [M-1:0] s_axis_tdata_i,
    input  wire logic         s_axis_tvalid_i,
    output logic              s_axis_tready_o,
    output logic      [M-1:0] m_axis_tdata_o,
    output logic              m_axis_tvalid_o,
    input  wire logic         m_axis_tready_i,
    output logic              m_axis_tlast_o
);
  localparam int NPAR = N - K;
  localparam int CW = $clog2(N);

  function automatic logic [M-1:0] gf_mul(input logic [M-1:0] a, input logic [M-1:0] b);
    logic [M-1:0] r, x;
    r = '0;
    x = a;
    for (int i = 0; i < M; i++) begin
      if (b[i]) r ^= x;
      x = x[M-1] ? ((x << 1) ^ M'(PRIM_POLY)) : (x << 1);
    end
    return r;
  endfunction

  // Coefficient of x^(NPAR - i) in prod_{j<NPAR} (x - alpha^j); i = 0 is the monic 1.
  function automatic logic [M-1:0] gen_coef(input int i);
    logic [M-1:0] g[NPAR+1];  // g[d] = coefficient of x^d
    logic [M-1:0] r;
    for (int d = 0; d <= NPAR; d++) g[d] = '0;
    g[0] = 1;
    r = 1;  // alpha^j
    for (int j = 0; j < NPAR; j++) begin
      for (int d = j + 1; d > 0; d--) g[d] = g[d-1] ^ gf_mul(g[d], r);
      g[0] = gf_mul(g[0], r);
      r = gf_mul(r, M'(2));
    end
    return g[NPAR-i];
  endfunction

  logic [M-1:0]  p_q[NPAR];
  logic [CW-1:0] idx_q;  // symbol index within the codeword
  logic          par;    // parity phase
  logic          hs;     // output handshake
  logic [M-1:0]  fb;

  assign par             = idx_q >= CW'(K);
  assign s_axis_tready_o = !par && m_axis_tready_i;
  assign m_axis_tvalid_o = par || s_axis_tvalid_i;
  assign m_axis_tdata_o  = par ? p_q[0] : s_axis_tdata_i;
  assign m_axis_tlast_o  = idx_q == CW'(N - 1);
  assign hs              = m_axis_tvalid_o && m_axis_tready_i;
  assign fb              = s_axis_tdata_i ^ p_q[0];

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      idx_q <= '0;
      for (int i = 0; i < NPAR; i++) p_q[i] <= '0;
    end else if (hs) begin
      idx_q <= m_axis_tlast_o ? '0 : idx_q + 1'b1;
      for (int i = 0; i < NPAR; i++) begin
        if (par) p_q[i] <= (i < NPAR - 1) ? p_q[(i+1)%NPAR] : '0;
        else     p_q[i] <= ((i < NPAR - 1) ? p_q[(i+1)%NPAR] : '0) ^ gf_mul(fb, gen_coef(i + 1));
      end
    end
  end

`ifndef SYNTHESIS
  // After the last parity symbol the register must be empty for the next codeword.
  a_par_clear : assert property (@(posedge clk_i) disable iff (rst_i)
                                 (hs && m_axis_tlast_o) |=> (p_q[0] == '0));
  a_idx_range : assert property (@(posedge clk_i) disable iff (rst_i) idx_q < CW'(N));
`endif

endmodule
`default_nettype wire
