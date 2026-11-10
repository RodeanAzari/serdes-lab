# Out-of-context synthesis + implementation of one RTL block, to route_design.
#
#   vivado -mode batch -source syn/synth_ooc.tcl -tclargs <top> <period_ns> [GEN=VAL ...]
#
# Reads every rtl/**/*.sv (only the top's hierarchy is elaborated). Clock: clk_i at
# <period_ns>. OOC: no I/O buffers, ports unconstrained, so only reg-to-reg paths are timed.
# Post-route timing is measured; post-synth timing would be an estimate. Reports land in
# syn/build/<top>/ (gitignored); `make reports` copies them to docs/reports/<tag>/.

set part   xc7a100tcsg324-1
set top    [lindex $argv 0]
set period [lindex $argv 1]
set gens   [lrange $argv 2 end]
if {$top eq "" || $period eq ""} { error "usage: -tclargs <top> <period_ns> \[GEN=VAL ...\]" }

set root [file normalize [file join [file dirname [info script]] ..]]
set out  [file join $root syn build $top]
file mkdir $out

proc sv_files {dir} {
    set fs [glob -nocomplain -directory $dir *.sv]
    foreach d [glob -nocomplain -type d -directory $dir *] {
        if {[file tail $d] in {eth rs soc}} continue  ;# submodules: only their rtl/, below
        lappend fs {*}[sv_files $d]
    }
    return $fs
}
read_verilog -sv [sv_files [file join $root rtl]]
# Shared blocks (git submodules at release tags): their rtl/ only, never tb/ formal/ examples/
foreach sub {eth rs soc} {
    set fs [glob -nocomplain -directory [file join $root rtl $sub rtl] *.sv]
    if {[llength $fs]} { read_verilog -sv $fs }
}
# ROM init files ($readmemh by file name, e.g. rtl/channel/noise_tables.mem)
foreach m [glob -nocomplain -directory [file join $root rtl] */*.mem] { read_mem $m }

set gargs {}
foreach g $gens { lappend gargs -generic $g }
synth_design -top $top -part $part -mode out_of_context {*}$gargs
create_clock -name clk -period $period [get_ports clk_i]

opt_design
place_design
route_design

report_timing_summary -max_paths 5 -file [file join $out timing.rpt]
report_utilization -file [file join $out utilization.rpt]
report_methodology -file [file join $out methodology.rpt]
report_drc -file [file join $out drc.rpt]

set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
puts "OOC_RESULT top=$top gens=\[$gens\] period=$period WNS=$wns WHS=$whs"
