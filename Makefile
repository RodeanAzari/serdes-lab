# Open SerDes Lab. All targets must work from a clean checkout.
PY      := .venv/bin/python
SV_SRCS := $(shell find rtl -name '*.sv' -not -path 'rtl/soc/*' -not -path 'rtl/eth/*' -not -path 'rtl/rs/*' 2>/dev/null)
# fpga-eth-core at its tag: RTL, the example clk_gen/reset_sync, and its Xilinx-primitive
# stand-ins (tb/models/, lint only). Read from the submodule, never copied.
ETH_SRCS := $(wildcard rtl/eth/rtl/*.sv rtl/eth/examples/rx_stats/reset_sync.sv rtl/eth/examples/rx_stats/xilinx/clk_gen.sv rtl/eth/tb/models/*.sv)

.PHONY: setup channels model-kp4 model-ber xcheck model-test lint sim synth-ooc sim-full formal fw synth impl prog ber plots reports ci clean

setup:
	python3 -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -r requirements.txt
	git submodule update --init

channels:
	$(PY) scripts/make_channels.py

model-kp4:  # KP4 statistics, float model (~30 min)
	NUMBA_NUM_THREADS=1 $(PY) scripts/kp4_model.py

model-ber:
	$(PY) scripts/ber_model.py

xcheck:  # serdespy cross-check (buildplan §8); needs data/raw from `make channels`
	$(PY) scripts/serdespy_xcheck.py

model-test:
	NUMBA_NUM_THREADS=1 $(PY) -m pytest -q  # threaded numba spin-waits under shared CPU load: 13 min vs 13 s
	.venv/bin/mypy model --exclude model/tests
	.venv/bin/ruff check model scripts analysis tb

lint:
	@if [ -z "$(SV_SRCS)" ]; then echo "lint: no RTL yet"; else \
	  for f in $(SV_SRCS); do t=$$(basename $$f .sv); \
	    verilator --lint-only -Wall --top-module $$t $(SV_SRCS) $(ETH_SRCS) || exit 1; echo "lint ok: $$t"; done; fi  # one top per file

plots:
	$(PY) analysis/plot_pulses.py
	$(PY) analysis/plot_ber.py
	$(PY) analysis/plot_xcheck.py
	$(PY) analysis/plot_kp4.py

sim:  # cocotb + Verilator, bit-exact vs model/ (tb/cocotb/run.py lists modules and parameters)
	$(PY) tb/cocotb/run.py

synth-ooc:  # make synth-ooc TOP=channel_fir [PERIOD=8] [GEN="P=4 L=16"]; reports in syn/build/$(TOP)/
	mkdir -p syn/build && cd syn/build && ../../scripts/vivado.sh -mode batch -nojournal -nolog \
	  -source ../synth_ooc.tcl -tclargs $(TOP) $(or $(PERIOD),8) $(GEN)

impl:  # make impl [TOP=noise_hist_top]: board build + bitstream in syn/build/$(TOP)/; refuses on negative slack
	@git diff --quiet HEAD -- rtl constr syn || echo "WARNING: uncommitted changes: BUILD_ID does not identify the source"
	mkdir -p syn/build && cd syn/build && ../../scripts/vivado.sh -mode batch -nojournal -nolog \
	  -source ../build_board.tcl -tclargs $(or $(TOP),noise_hist_top) $$(git rev-parse --short=8 HEAD)

prog:  # make prog [TOP=noise_hist_top]: JTAG load of syn/build/$(TOP)/$(TOP).bit; claim the board first
	mkdir -p syn/build && cd syn/build && ../../scripts/vivado.sh -mode batch -nojournal -nolog \
	  -source ../prog.tcl -tclargs $(CURDIR)/syn/build/$(or $(TOP),noise_hist_top)/$(or $(TOP),noise_hist_top).bit

sim-full formal fw synth ber reports:
	@echo "make $@: not implemented yet (see docs/buildplan.md §11)"; exit 1

ci: lint sim model-test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache sim_build
