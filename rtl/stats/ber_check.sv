`default_nettype none
// Pre-FEC BER checker, P symbols per clock (ADR 0011; model: model/rx.py count_errors).
// RX symbol j (counted from the first RX word) is compared with TX symbol first_i + j (counted
// from the first TX word): bit errors, Gray-symbol errors and bits compared. The first
// holdoff_i RX words are not counted. Bits in stream order: symbol s = bits [2s +: 2] (demap).
//
// Reference path, counted in symbols (no clock delays): TX words before c0 are dropped; from
// word c0 on, each TX word c writes P symbols taken at offset o of the window {word c, word
// c - 1} into a FIFO, i.e. TX symbols (c - 1) P + o ... (c - 1) P + o + P - 1, with
//     o = first mod P, c0 = first div P + 1     (first mod P != 0)
//     o = P,           c0 = first div P         (first mod P == 0: the window's upper word)
// so FIFO word w holds TX symbols first + P w .... Each RX word reads one FIFO word.
//
// Counters are CNT_W bits and saturate (never wrap). err_o is sticky: FIFO overflow (TX more
// than DEPTH words ahead) or underflow (RX word with no reference); either voids the run.
// first_i / holdoff_i are static configuration: change them only while rst_i is high.
//
// Latency: an RX word is reflected in the counters 2 clocks after it is accepted.
module ber_check #(
    parameter int P     = 4,
    parameter int DEPTH = 64,  // FIFO words, power of 2: covers the TX -> RX latency
    parameter int CNT_W = 64,
    parameter int F_W   = 8,   // first_i width (symbols)
    parameter int H_W   = 16   // holdoff_i width (words)
) (
    input  wire logic                clk_i,
    input  wire logic                rst_i,      // clears FIFO, counters, err_o
    input  wire logic [F_W-1:0]      first_i,    // TX symbol of RX symbol 0 (m0 - K)
    input  wire logic [H_W-1:0]      holdoff_i,  // RX words not counted
    input  wire logic [2*P-1:0]      tx_bits_i,  // reference (demap of the TX index)
    input  wire logic                tx_valid_i,
    input  wire logic [2*P-1:0]      rx_bits_i,
    input  wire logic                rx_valid_i,
    output logic      [CNT_W-1:0]    bits_o,     // bits compared
    output logic      [CNT_W-1:0]    bit_err_o,
    output logic      [CNT_W-1:0]    sym_err_o,
    output logic                     err_o
);
  localparam int LP   = $clog2(P);
  localparam int AW   = $clog2(DEPTH);
  localparam int PC_W = $clog2(2 * P + 1);  // popcount of 2P bits
  localparam logic [CNT_W-1:0] CMAX = '1;

  if ((1 << LP) != P || (1 << AW) != DEPTH) begin : g_check
    $error("ber_check: P and DEPTH must be powers of 2");
  end

  // ---- write side: drop to c0, realign by o ------------------------------------------------
  logic [F_W-1:0] c0;
  logic [LP:0]    o;  // 1..P
  logic [F_W-1:0] cnt_q;  // TX words seen, saturates at c0
  logic [2*P-1:0] prev_q;
  logic [4*P-1:0] window;
  logic           wr;

  if (P > 1) begin : g_split
    logic [LP-1:0] lo;
    assign lo = first_i[LP-1:0];
    assign c0 = F_W'(first_i >> LP) + F_W'(lo != '0);
    assign o  = (lo == '0) ? (LP+1)'(P) : (LP+1)'(lo);
  end else begin : g_one
    assign c0 = first_i;
    assign o  = 1'b1;
  end

  assign window = {tx_bits_i, prev_q};
  assign wr     = tx_valid_i && cnt_q == c0;

  always_ff @(posedge clk_i) begin
    if (rst_i)                          cnt_q <= '0;
    else if (tx_valid_i && cnt_q != c0) cnt_q <= cnt_q + 1'b1;
    if (tx_valid_i) prev_q <= tx_bits_i;
  end

  // ---- FIFO ----------------------------------------------------------------------------------
  logic [2*P-1:0] mem_q[DEPTH];
  logic [AW:0]    wp_q, rp_q;
  logic           full, empty, rd;

  assign full  = (wp_q[AW] != rp_q[AW]) && (wp_q[AW-1:0] == rp_q[AW-1:0]);
  assign empty = wp_q == rp_q;
  assign rd    = rx_valid_i && !empty;

  always_ff @(posedge clk_i) begin
    if (wr && !full) mem_q[wp_q[AW-1:0]] <= window[2*o +: 2*P];
    if (rst_i) begin
      wp_q  <= '0;
      rp_q  <= '0;
      err_o <= 1'b0;
    end else begin
      if (wr && !full) wp_q <= wp_q + 1'b1;
      if (rd)          rp_q <= rp_q + 1'b1;
      if ((wr && full) || (rx_valid_i && empty)) err_o <= 1'b1;
    end
  end

  // ---- compare (stage 1) and count (stage 2) ------------------------------------------------
  logic [H_W-1:0] rxw_q;  // RX words compared, saturates at holdoff
  logic [2*P-1:0] diff_q;
  logic           cmp_q;

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      rxw_q <= '0;
      cmp_q <= 1'b0;
    end else begin
      cmp_q <= rd && rxw_q == holdoff_i;
      if (rd && rxw_q != holdoff_i) rxw_q <= rxw_q + 1'b1;
    end
    diff_q <= rx_bits_i ^ mem_q[rp_q[AW-1:0]];
  end

  logic [PC_W-1:0] nbit, nsym;

  always_comb begin
    nbit = '0;
    nsym = '0;
    for (int s = 0; s < P; s++) begin
      nbit = nbit + PC_W'(diff_q[2*s]) + PC_W'(diff_q[2*s+1]);
      nsym = nsym + PC_W'(diff_q[2*s +: 2] != 2'b00);
    end
  end

  function automatic logic [CNT_W-1:0] sat_add(input logic [CNT_W-1:0] a,
                                               input logic [PC_W-1:0]  b);
    logic [CNT_W:0] s;
    s = {1'b0, a} + (CNT_W+1)'(b);
    return s[CNT_W] ? CMAX : s[CNT_W-1:0];
  endfunction

  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      bits_o    <= '0;
      bit_err_o <= '0;
      sym_err_o <= '0;
    end else if (cmp_q) begin
      bits_o    <= sat_add(bits_o, PC_W'(2 * P));
      bit_err_o <= sat_add(bit_err_o, nbit);
      sym_err_o <= sat_add(sym_err_o, nsym);
    end
  end

endmodule
`default_nettype wire
