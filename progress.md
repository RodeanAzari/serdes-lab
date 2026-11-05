# Progress

**Phase:** A (Python model + sizing). Started 2026-11-05.

Done:
- Repo skeleton, venv (Python 3.14.4), pinned `requirements.txt`, Makefile (`make ci` green)
- Channels: TE/Shanbhag KR Ch2 (19.3 dB) + Ch4 (31.4 dB) → pulse responses (`make channels`)
- MMSE FFE+DFE reference (`model/equalizer.py`); 8 model tests
- ADR 0001 (channel model); pulse-response plot

Open: sampling-phase rule (ADR 0001 open question). Nothing committed yet.

Next (Phase A): PAM4/Gray/precoder + noise + ADC model → float BER waterfall;
KP4 RS(544,514) encoder/decoder vs an independent reference; serdespy cross-check; DSP sizing ADR.
