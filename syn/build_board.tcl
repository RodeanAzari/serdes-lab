# Board build (non-project): synth -> place -> route -> reports -> bitstream, Arty A7-100T.
#
#   vivado -mode batch -source syn/build_board.tcl -tclargs <top> <build_id_hex>
#
# Sources: rtl/{channel,stats,top,tx}/*.sv, fpga-eth-core (submodule rtl/eth at its release tag):
# rtl/*.sv plus its example clk_gen/reset_sync (consumer guide). Constraints per top below.
# Outputs in syn/build/<top>/ (gitignored); `make reports` copies reports to docs/reports/<tag>/.
# The bitstream is written only if setup and hold are met (CLAUDE.md §3: no negative slack).

set expected_vivado 2025.2
if {[version -short] ne $expected_vivado} {
    puts "WARNING: Vivado [version -short], pinned version is $expected_vivado"
}
set part     xc7a100tcsg324-1
set top      [lindex $argv 0]
set build_id [lindex $argv 1]
if {$top eq "" || $build_id eq ""} { error "usage: -tclargs <top> <build_id_hex>" }

set root [file normalize [file join [file dirname [info script]] ..]]
set eth  [file join $root rtl eth]
set out  [file join $root syn build $top]
file mkdir $out
cd $out

switch -- $top {
    noise_hist_top {
        set xdcs [list [file join $eth constr arty_a7_100_pins.xdc] \
                       [file join $eth constr arty_a7_100_pins_tx.xdc] \
                       [file join $root constr noise_hist_timing.xdc]]
    }
    default { error "unknown board top '$top'" }
}

set sv {}
foreach d {channel stats top tx} { lappend sv {*}[lsort [glob -nocomplain [file join $root rtl $d *.sv]]] }
lappend sv {*}[lsort [glob [file join $eth rtl *.sv]]]
lappend sv [file join $eth examples rx_stats xilinx clk_gen.sv] [file join $eth examples rx_stats reset_sync.sv]
read_verilog -sv $sv
foreach m [glob -nocomplain [file join $root rtl * *.mem]] { read_mem $m }
foreach x $xdcs { read_xdc $x }
read_xdc -ref async_fifo [file join $eth constr async_fifo.xdc]

synth_design -top $top -part $part -generic BUILD_ID=32'h$build_id
set bb [get_cells -hier -quiet -filter {IS_BLACKBOX == 1}]
if {[llength $bb] > 0} { error "black boxes in the netlist: $bb" }
# hist_bram's RAMs must write only on its write enable (port A ENARDEN driven, not tied high):
# a constant enable maps to a write-back every idle clock, and readout reads of the last
# written bin then collide on hardware (seen 2026-11-10; Verilator cannot show it).
foreach r [get_cells -quiet -hier -filter {REF_NAME =~ RAMB* && NAME =~ *u_hist*}] {
    if {[get_nets -of [get_pins $r/ENARDEN]] eq "<const1>"} { error "hist RAM $r: ENARDEN tied high" }
}

opt_design
place_design
phys_opt_design
route_design

report_timing_summary -max_paths 20 -report_unconstrained -file [file join $out timing_summary.rpt]
report_utilization                    -file [file join $out utilization.rpt]
report_utilization -hierarchical      -file [file join $out utilization_hier.rpt]
report_clock_interaction -delay_type min_max -file [file join $out clock_interaction.rpt]
report_cdc -details                   -file [file join $out cdc.rpt]
report_methodology                    -file [file join $out methodology.rpt]
report_drc                            -file [file join $out drc.rpt]
report_power                          -file [file join $out power.rpt]

set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1 -nworst 1]]
set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1 -nworst 1]]
set fh [open [file join $out summary.txt] w]
puts $fh "vivado [version -short]  part $part  top $top  build_id $build_id"
puts $fh "WNS $wns ns  WHS $whs ns"
close $fh
puts "BOARD_RESULT top=$top build_id=$build_id WNS=$wns WHS=$whs"
if {$wns < 0 || $whs < 0} { error "timing not met: no bitstream (WNS $wns, WHS $whs)" }
write_bitstream -force [file join $out $top.bit]
