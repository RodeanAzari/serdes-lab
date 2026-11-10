`default_nettype none
// Histogram of a signed sample stream in block RAM, one update per clock (ADR 0009).
//
//   bin = clamp(n, -2^(IDX_W-1), 2^(IDX_W-1) - 1) + 2^(IDX_W-1);   count[bin] += 1, saturating
//
// Update pipeline (latency 3 from n_i to the write):
//   1  bin computed and registered
//   2  BRAM read                      (read latency 2: array read + output register)
//   3  output register; new = old + 1 (held at all-ones), written at the end of stage 3
// A sample's read happens 2 clocks before the previous sample's write lands and in the same
// clock as the one before that, so the value is forwarded from the last two writes (most
// recent first). The BRAM's read/write collision behaviour is never relied on. The forward
// selects depend only on the address pipeline, so they are compared 1 and 2 clocks early and
// registered; saturation uses the increment's carry out. Stage 3 is mux + 48 b increment.
//
// clear_i: writes 0 to every bin, one per clock (busy_o high for 2^IDX_W clocks). Samples must
// not arrive while busy. Readout: rd_en_i/rd_addr_i -> rd_data_o, rd_valid_o 2 clocks later;
// only when idle: no sample in flight and not clearing (shared read port; asserted).
module hist_bram #(
    parameter int DATA_W  = 16,
    parameter int IDX_W   = 10,
    parameter int COUNT_W = 48
) (
    input  wire logic               clk_i,
    input  wire logic               rst_i,      // resets valid/control only
    input  wire logic [DATA_W-1:0]  n_i,        // signed
    input  wire logic               valid_i,
    input  wire logic               clear_i,
    output logic                    busy_o,
    input  wire logic               rd_en_i,
    input  wire logic [IDX_W-1:0]   rd_addr_i,
    output logic      [COUNT_W-1:0] rd_data_o,
    output logic                    rd_valid_o
);
  localparam int NB = 1 << IDX_W;
  localparam logic signed [DATA_W-1:0] NMIN = DATA_W'(-(NB / 2));
  localparam logic signed [DATA_W-1:0] NMAX = DATA_W'(NB / 2 - 1);

  (* ram_style = "block" *) logic [COUNT_W-1:0] mem[NB];

  // ---- stage 1: bin -----------------------------------------------------------------------
  logic signed [DATA_W-1:0] n_s, n_c;
  logic [IDX_W-1:0] a1_q, a2_q, a3_q;
  logic             v1_q, v2_q, v3_q;

  assign n_s = $signed(n_i);
  assign n_c = (n_s < NMIN) ? NMIN : (n_s > NMAX) ? NMAX : n_s;

  // ---- stages 2-3: read (latency 2), forward, increment -------------------------------------
  logic [IDX_W-1:0]   raddr;
  logic [COUNT_W-1:0] rd_q, dout_q, old, new_cnt;
  logic [COUNT_W-1:0] w1_d_q, w2_d_q;  // last two values written
  logic               sel1_q, sel2_q, sel2_d_q;
  logic [COUNT_W:0]   inc;
  logic [1:0]         rdv_q;

  assign raddr = v1_q ? a1_q : rd_addr_i;

  always_comb begin
    if      (sel1_q) old = w1_d_q;  // previous sample, same bin, written last clock
    else if (sel2_q) old = w2_d_q;  // the one before: its write collided with this read
    else             old = dout_q;
    inc     = {1'b0, old} + 1'b1;
    new_cnt = inc[COUNT_W] ? old : inc[COUNT_W-1:0];  // saturate at all-ones
  end

  // ---- clear sweep --------------------------------------------------------------------------
  logic [IDX_W-1:0] clr_a_q;
  logic             clr_q;

  assign busy_o     = clr_q;
  assign rd_data_o  = dout_q;
  assign rd_valid_o = rdv_q[1];

  always_ff @(posedge clk_i) begin
    a1_q   <= IDX_W'(n_c - NMIN);
    a2_q   <= a1_q;
    a3_q   <= a2_q;
    rd_q   <= mem[raddr];
    dout_q <= rd_q;
    if (clr_q)      mem[clr_a_q] <= '0;
    else if (v3_q)  mem[a3_q]    <= new_cnt;
    w1_d_q <= new_cnt;
    w2_d_q <= w1_d_q;
    if (rst_i) begin
      {v1_q, v2_q, v3_q, sel1_q, sel2_q, sel2_d_q} <= '0;
      rdv_q      <= '0;
      clr_q      <= 1'b0;
      clr_a_q    <= '0;
    end else begin
      v1_q   <= valid_i;
      v2_q   <= v1_q;
      v3_q   <= v2_q;
      // next clock's stage-3 sample is a2 (1 behind the one writing now), the one after is a1
      sel1_q   <= v3_q && a2_q == a3_q;
      sel2_d_q <= v3_q && a1_q == a3_q;
      sel2_q   <= sel2_d_q;
      rdv_q  <= {rdv_q[0], rd_en_i && !v1_q};
      if (clear_i && !clr_q) begin
        clr_q   <= 1'b1;
        clr_a_q <= '0;
      end else if (clr_q) begin
        clr_a_q <= clr_a_q + 1'b1;
        if (clr_a_q == IDX_W'(NB - 1)) clr_q <= 1'b0;
      end
    end
  end

`ifndef SYNTHESIS
  a_no_sample_while_clearing : assert property (@(posedge clk_i) disable iff (rst_i)
                                                !(clr_q && (valid_i || v1_q || v2_q || v3_q)));
  a_no_read_while_counting   : assert property (@(posedge clk_i) disable iff (rst_i)
                                                !(rd_en_i && (v1_q || v2_q || v3_q || clr_q)));
`endif

endmodule
`default_nettype wire
