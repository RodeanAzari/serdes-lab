# ADR 0008: Noise-to-symbol alignment in the channel

**Status:** accepted 2026-11-09. **Phase:** B. Model: `model/tx.py` `pre_adc`. RTL: `rtl/channel/channel_top.sv`.

## Context

The RTL channel FIR is causal: its output symbol m (counted from the first valid input) is the
model's s[m − cursor] (`channel_fir.sv` header). The noise lanes are one lfsr258 per lane, word j
from lane j mod P at step j div P (ADR 0007). Until now the model added noise word k to model
symbol k, i.e. to hardware symbol k + cursor.

## Decision

**Noise word j is added to hardware symbol j.** In the model's frame:
y[k] = sat(s[k] + n[k + cursor], 16). The noise lanes step with the FIR's input words, and their
output is delayed to meet the FIR output; no lane rotation, no cursor register in hardware.

The noise is an i.i.d. stream independent of the data, so which word meets which symbol has
no statistical effect: only the bit-exact reference changes.

## Rejected alternatives

- **Keep word k ↔ model symbol k in RTL:** needs a P-lane rotation of the noise samples by
  cursor mod P plus a word delay, both set by a runtime cursor register (P × 16 b muxes): hardware
  and a register for an arbitrary index convention.
- **Make the RTL FIR non-causal (output s[m]):** the FIR would have to wait `cursor` symbols
  for future inputs anyway; same as a delay, with a cursor-dependent latency.
