# Open SerDes Lab. All targets must work from a clean checkout.
PY      := .venv/bin/python
SV_SRCS := $(shell find rtl -name '*.sv' -not -path 'rtl/soc/*' -not -path 'rtl/eth/*' -not -path 'rtl/rs/*' 2>/dev/null)

.PHONY: setup channels model-ber xcheck model-test lint sim sim-full formal fw synth impl prog ber plots reports ci clean

setup:
	python3 -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -r requirements.txt
	git submodule update --init

channels:
	$(PY) scripts/make_channels.py

model-ber:
	$(PY) scripts/ber_model.py

xcheck:  # serdespy cross-check (buildplan §8); needs data/raw from `make channels`
	$(PY) scripts/serdespy_xcheck.py

model-test:
	NUMBA_NUM_THREADS=1 $(PY) -m pytest -q  # threaded numba spin-waits under shared CPU load: 13 min vs 13 s
	.venv/bin/mypy model --exclude model/tests
	.venv/bin/ruff check model scripts analysis

lint:
	@if [ -z "$(SV_SRCS)" ]; then echo "lint: no RTL yet"; else verilator --lint-only -Wall $(SV_SRCS); fi

plots:
	$(PY) analysis/plot_pulses.py
	$(PY) analysis/plot_ber.py

sim sim-full formal fw synth impl prog ber reports:
	@echo "make $@: not implemented yet (see progress.md)"; exit 1

ci: lint model-test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache sim_build
