#!/usr/bin/env bash
# Run Vivado (batch) with its environment confined to this process: settings64.sh must never
# be sourced globally (it breaks git/curl/python). Mirrors vivado-env in ~/.bashrc.
#   scripts/vivado.sh <vivado args...>
set -euo pipefail
s=$(ls -d "$HOME"/[Xx]ilinx/*/Vivado/settings64.sh "$HOME"/[Xx]ilinx/Vivado/*/settings64.sh \
      2>/dev/null | sort -V | tail -1 || true)
[ -n "$s" ] || { echo "vivado.sh: no Vivado install under ~/Xilinx" >&2; exit 1; }
export LOCPATH="$HOME/.locale"
set +u; source "$s"; set -u
export LD_LIBRARY_PATH="$HOME/.local/lib/vivado-compat:${LD_LIBRARY_PATH:-}"
exec vivado "$@"
