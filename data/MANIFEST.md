# Channel data manifest

Raw Touchstone files are not committed (`data/raw/` is gitignored). `make channels` re-downloads
them and checks these hashes.

| Archive | Source URL | SHA-256 | Downloaded |
|---|---|---|---|
| `shanbhag_3dj_02_2305.zip` | https://www.ieee802.org/3/dj/public/tools/KR/shanbhag_3dj_02_2305.zip | `4688e7832cf3b7d5abe41f60a80b023f62c9a2fda235f83cbcd07e09166598df` | 2026-11-05 |
| `weaver_3dj_02_2303.zip` | https://www.ieee802.org/3/dj/public/tools/KR/weaver_3dj_02_2303.zip | `cf830c79b2da9ec7cb3bf58c9cc8181350d182c47c949fb25398ec2524cdb7a1` | 2026-11-05 |
| `tracy_3dj_02_2303.zip` | https://www.ieee802.org/3/dj/public/tools/KR/tracy_3dj_02_2303.zip | `e074731534526e50af12c45071b39bde3725f65ba4e9c5632dc10e733939dfbc` | 2026-11-05 |

## Shanbhag/Tracy (TE Connectivity), "Updated KR Channels in Support of a 200G Backplane Objective", May 2023

Contribution: https://www.ieee802.org/3/dj/public/23_05/shanbhag_3dj_02a_2305.pdf

1 m 26AWG cabled backplane, TP0–TP5, **no package model**. Authors state the usable channel
bandwidth is 67 GHz (data provided to 80 GHz, 10 MHz step).

Port map (from file header): 1→2 and 3→4 are the through paths. Differential input = (1,3),
output = (2,4), so SDD21 = ½(S21 − S23 − S41 + S43) (1-indexed).

Check that port mapping is correct: |SDD21| at 53.125 GHz computed here vs. the value in the
contribution's table.

| Ch (deck) | THRU file | IL in deck (dB) | IL computed (dB) |
|---|---|---|---|
| Ch2 | `KR_1mCabledBP_TP0TP5_19p3dB_PCBHost_3p8dB_THRU.s4p` | 19.3 | 19.4 |
| Ch1 | `KR_1mCabledBP_TP0TP5_27p4dB_CabledHost_7p85dB_THRU.s4p` | 27.4 | 27.8 |
| Ch3 | `KR_1mCabledBP_TP0TP5_28dB_PCBHost_8dB_THRU.s4p` | 28.0 | 27.9 |
| Ch4 | `KR_1mCabledBP_TP0TP5_31p4dB_PCBHost_9p8dB_THRU.s4p` | 31.4 | 31.6 |

The deck publishes **no COM values** for these channels.
