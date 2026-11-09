"""Export the noise generator coefficient tables (model/noise.py, ADR 0005) as the BRAM init file.

    rtl/channel/noise_tables.mem: 1024 lines, one per segment (seg = octave * 16 + sub),
    17 hex digits = 65 bits {c2[16:0], c1[22:0], c0[24:0]}, two's complement fields.

The file is committed; model/tests/test_noise.py fails if it differs from build_tables().
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import noise as nz  # noqa: E402

OUT = ROOT / "rtl/channel/noise_tables.mem"
W_C0, W_C1, W_C2 = 25, 23, 17  # docs/fixed-point.md


def field(v: int, bits: int) -> int:
    if not -(1 << (bits - 1)) <= v < (1 << (bits - 1)):
        raise ValueError(f"{v} does not fit {bits} b signed")
    return v & ((1 << bits) - 1)


def mem_lines(tb: nz.Tables) -> list[str]:
    lines = []
    for c0, c1, c2 in zip(tb.c0, tb.c1, tb.c2, strict=True):
        word = (field(int(c2), W_C2) << (W_C1 + W_C0)) | (field(int(c1), W_C1) << W_C0)
        lines.append(f"{word | field(int(c0), W_C0):017x}")
    return lines


def main() -> None:
    OUT.write_text("\n".join(mem_lines(nz.build_tables(nz.NoiseCfg()))) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
