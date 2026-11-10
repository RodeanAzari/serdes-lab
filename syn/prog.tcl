# Load a bitstream into the Arty A7-100T over JTAG (volatile: lost at power-off).
#
#   vivado -mode batch -source syn/prog.tcl -tclargs <bitfile>
#
# Under WSL the board's FTDI JTAG/UART (0403:6010) must be attached with usbipd-win.
# Claim the board first (fpga-coord: coord.py board claim P4 "<reason>").
# Fails unless the FPGA reports DONE high afterwards.

set bit [lindex $argv 0]
if {$bit eq "" || ![file exists $bit]} { error "usage: -tclargs <bitfile> (got '$bit')" }

open_hw_manager
connect_hw_server -allow_non_jtag
open_hw_target
set dev [lindex [get_hw_devices xc7a100t*] 0]
if {$dev eq ""} { error "no xc7a100t on the JTAG chain" }
current_hw_device $dev
set_property PROGRAM.FILE [file normalize $bit] $dev
program_hw_devices $dev
refresh_hw_device $dev
set done [get_property REGISTER.CONFIG_STATUS.BIT14_DONE_PIN $dev]
puts "PROG_RESULT bit=$bit DONE=$done"
close_hw_manager
if {$done ne 1} { error "DONE is low after programming" }
