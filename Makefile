# Open SerDes Lab. All targets must work from a clean checkout.
PY      := .venv/bin/python
SV_SRCS := $(shell find rtl -name '*.sv' -not -path 'rtl/soc/*' -not -path 'rtl/eth/*' -not -path 'rtl/rs/*' 2>/dev/null)

.PHONY: setup channels model-kp4 model-ber xcheck model-test lint sim sim-full formal fw synth impl prog ber plots reports ci clean

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
	    verilator --lint-only -Wall --top-module $$t $(SV_SRCS) || exit 1; echo "lint ok: $$t"; done; fi  # one top per file

plots:
	$(PY) analysis/plot_pulses.py
	$(PY) analysis/plot_ber.py
	$(PY) analysis/plot_xcheck.py
	$(PY) analysis/plot_kp4.py

sim:  # cocotb + Verilator, bit-exact vs model/ (tb/cocotb/run.py lists modules and parameters)
	$(PY) tb/cocotb/run.py

sim-full formal fw synth impl prog ber reports:
	@echo "make $@: not implemented yet (see docs/buildplan.md §11)"; exit 1

ci: lint sim model-test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache sim_build
