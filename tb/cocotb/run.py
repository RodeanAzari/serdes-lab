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
                build_args=["--assert", "-Wall", "-Wno-fatal", "--timing"],
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
