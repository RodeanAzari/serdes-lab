`default_nettype none
// Noise generator coefficient ROM (ADR 0005): 1024 x 65 b {c2, c1, c0}, two read ports so one
// ROM (2 x BRAM36) serves a lane pair. Contents: INIT_FILE, from scripts/export_noise_tables.py.
//
// Latency 2 per port: address registered by the BRAM read, data by its output register (DOREG).
// Reads every clock; no enable, no reset (ROM data, CLAUDE.md §5).
module noise_rom #(
    parameter string INIT_FILE = "noise_tables.mem"
) (
    input  wire logic        clk_i,
    input  wire logic [9:0]  addr_a_i,
    input  wire logic [9:0]  addr_b_i,
    output logic      [64:0] data_a_o,
    output logic      [64:0] data_b_o
);
  (* rom_style = "block" *) logic [64:0] rom[1024];
  logic [64:0] rd_a_q, rd_b_q;

  initial $readmemh(INIT_FILE, rom);

  always_ff @(posedge clk_i) begin
    rd_a_q   <= rom[addr_a_i];
    rd_b_q   <= rom[addr_b_i];
    data_a_o <= rd_a_q;
    data_b_o <= rd_b_q;
  end

endmodule
`default_nettype wire
