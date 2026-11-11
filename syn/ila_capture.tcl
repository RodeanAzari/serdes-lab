# Arm the ber_top ILA on the first valid FFE word and save the capture as CSV (Phase C eye).
#
#   vivado -mode batch -source syn/ila_capture.tcl -tclargs <ltx> <csv>
#
# Driven by scripts/ber_run.py capture: the board must already hold a CONFIG (link in reset,
# z_valid_dbg low). This script prints ILA_ARMED once armed; the host then sends START, so the
# trigger (z_valid_dbg rising, position 0) is RX word 0.

set ltx [lindex $argv 0]
set csv [lindex $argv 1]
if {$ltx eq "" || ![file exists $ltx] || $csv eq ""} { error "usage: -tclargs <ltx> <csv>" }

open_hw_manager
connect_hw_server -allow_non_jtag
open_hw_target
set dev [lindex [get_hw_devices xc7a100t*] 0]
if {$dev eq ""} { error "no xc7a100t on the JTAG chain" }
current_hw_device $dev
set_property PROBES.FILE [file normalize $ltx] $dev
set_property FULL_PROBES.FILE [file normalize $ltx] $dev
refresh_hw_device $dev
set ila [lindex [get_hw_ilas -of_objects $dev] 0]
if {$ila eq ""} { error "no ILA in the programmed design (wrong bitstream?)" }

set trig [get_hw_probes -of_objects $ila -filter {NAME =~ *z_valid_dbg*}]
if {[llength $trig] != 1} { error "trigger probe z_valid_dbg not found" }
set_property CONTROL.DATA_DEPTH 4096 $ila
set_property CONTROL.TRIGGER_POSITION 0 $ila
set_property TRIGGER_COMPARE_VALUE eq1'bR $trig
run_hw_ila $ila
puts "ILA_ARMED"
flush stdout
wait_on_hw_ila -timeout 1 $ila  ;# the host checks the CSV: 4096 rows, trigger at row 0
upload_hw_ila_data $ila
write_hw_ila_data -force -csv_file [file normalize $csv] [current_hw_ila_data]
puts "ILA_DONE $csv"
close_hw_manager
