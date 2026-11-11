"""Build and run the cocotb tests with Verilator: python tb/cocotb/run.py [test_module ...]"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from cocotb_tools.runner import get_results, get_runner

ROOT = Path(__file__).resolve().parents[2]

# test module -> (toplevel, sources, parameter sets)
TESTS: dict[str, tuple[str, list[str], list[dict[str, int]]]] = {
    "test_prbs31_par": ("prbs31_par", ["rtl/tx/prbs31_par.sv"],
                        [{"W": 1}, {"W": 10}, {"W": 31}, {"W": 40}]),  # fmt: skip
    "test_lfsr258": ("lfsr258", ["rtl/channel/lfsr258.sv"], [{}]),
    "test_channel_fir": ("channel_fir", ["rtl/channel/channel_fir.sv"],
                         [{"P": 4, "L": 16}, {"P": 4, "L": 12}, {"P": 2, "L": 16},
                          {"P": 2, "L": 5}, {"P": 4, "L": 3}, {"P": 4, "L": 1}]),  # fmt: skip
    "test_rs_enc": ("rs_enc", ["rtl/tx/rs_enc.sv"], [{}]),
    "test_gearbox": ("gearbox", ["rtl/tx/gearbox.sv"],
                     [{"IN_W": 10, "OUT_W": 8}, {"IN_W": 10, "OUT_W": 4}, {"IN_W": 10, "OUT_W": 10},
                      {"IN_W": 4, "OUT_W": 10},
                      {"IN_W": 10, "OUT_W": 7}, {"IN_W": 9, "OUT_W": 8}]),  # fmt: skip
    "test_noise_gen": ("noise_gen", ["rtl/channel/noise_rom.sv", "rtl/channel/noise_lane.sv",
                                     "rtl/channel/noise_gen.sv"], [{"P": 4}, {"P": 3}, {"P": 1}]),
    "test_channel_top": ("channel_top", ["rtl/tx/prbs31_par.sv", "rtl/tx/rs_enc.sv",
                                         "rtl/tx/gearbox.sv", "rtl/tx/pam4_map.sv",
                                         "rtl/tx/tx_top.sv", "rtl/channel/channel_fir.sv",
                                         "rtl/channel/lfsr258.sv", "rtl/channel/noise_rom.sv",
                                         "rtl/channel/noise_lane.sv", "rtl/channel/noise_gen.sv",
                                         "rtl/channel/channel_top.sv"],
                         [{"P": 4}, {"P": 2}]),
    "test_hist_bram": ("hist_bram", ["rtl/stats/hist_bram.sv"],
                       [{}, {"DATA_W": 8, "IDX_W": 4, "COUNT_W": 4}]),
    "test_noise_hist_core": ("noise_hist_core",
                             ["rtl/channel/lfsr258.sv", "rtl/channel/noise_rom.sv",
                              "rtl/channel/noise_lane.sv", "rtl/channel/noise_gen.sv",
                              "rtl/stats/hist_bram.sv", "rtl/top/noise_ctrl.sv",
                              "rtl/top/noise_hist_core.sv"], [{"BUILD_ID": 0xC0FFEE01}]),
    "test_tx_top": ("tx_top", ["rtl/tx/prbs31_par.sv", "rtl/tx/rs_enc.sv", "rtl/tx/gearbox.sv",
                               "rtl/tx/pam4_map.sv", "rtl/tx/tx_top.sv"],
                    [{"P": 4}, {"P": 2}]),  # fmt: skip
    "test_ffe": ("ffe", ["rtl/rx/ffe.sv"],
                 [{"P": 4, "N": 16}, {"P": 2, "N": 16}, {"P": 4, "N": 5}, {"P": 3, "N": 1}]),
    "test_dfe_slicer": ("dfe_slicer", ["rtl/rx/dfe_slicer.sv"],
                        [{"P": 4}, {"P": 4, "D_INIT": 3}, {"P": 3, "D_INIT": 1}, {"P": 1}]),
    "test_demap": ("demap", ["rtl/rx/demap.sv"], [{"P": 4}, {"P": 1}]),
    "test_ber_check": ("ber_check", ["rtl/stats/ber_check.sv"],
                       [{"P": 4}, {"P": 2}, {"P": 1}, {"P": 4, "CNT_W": 6},
                        {"P": 4, "DEPTH": 8}]),  # fmt: skip
    "test_link_core": ("link_core", ["rtl/tx/prbs31_par.sv", "rtl/tx/rs_enc.sv",
                                     "rtl/tx/gearbox.sv", "rtl/tx/pam4_map.sv",
                                     "rtl/tx/tx_top.sv", "rtl/channel/channel_fir.sv",
                                     "rtl/channel/lfsr258.sv", "rtl/channel/noise_rom.sv",
                                     "rtl/channel/noise_lane.sv", "rtl/channel/noise_gen.sv",
                                     "rtl/channel/channel_top.sv", "rtl/rx/ffe.sv",
                                     "rtl/rx/dfe_slicer.sv", "rtl/rx/demap.sv",
                                     "rtl/rx/rx_top.sv", "rtl/stats/ber_check.sv",
                                     "rtl/top/link_core.sv"],
                       [{"P": 4}, {"P": 2}]),
}

# extra Verilator build arguments per test module (string parameters stay out of the run tag)
BUILD_ARGS: dict[str, list[str]] = {
    "test_noise_gen": [f'-GINIT_FILE="{ROOT}/rtl/channel/noise_tables.mem"'],
    "test_channel_top": [f'-GINIT_FILE="{ROOT}/rtl/channel/noise_tables.mem"', "--public-flat-rw"],
    "test_noise_hist_core": [f'-GINIT_FILE="{ROOT}/rtl/channel/noise_tables.mem"'],
    "test_link_core": [f'-GINIT_FILE="{ROOT}/rtl/channel/noise_tables.mem"', "--public-flat-rw"],
}


def main(names: list[str]) -> int:
    failed = 0
    for name in names or list(TESTS):
        top, srcs, param_sets = TESTS[name]
        for params in param_sets:
            tag = "_".join(f"{k}{v}" for k, v in params.items()) or "default"
            build_dir = ROOT / "sim_build" / f"{name}_{tag}"
            runner = get_runner("verilator")
            runner.build(
                sources=[ROOT / s for s in srcs],
                hdl_toplevel=top,
                parameters=params,
                build_args=["--assert", "-Wall", "-Wno-fatal", "--timing",
                            *BUILD_ARGS.get(name, [])],  # fmt: skip
                build_dir=build_dir,
                always=True,
            )
            env = {k: str(v) for k, v in params.items()}
            env["PYTHONPATH"] = os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")])
            results = runner.test(
                hdl_toplevel=top,
                test_module=name,
                test_dir=ROOT / "tb" / "cocotb",
                build_dir=build_dir,
                extra_env=env,
            )
            _, fails = get_results(results)
            failed += fails
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
