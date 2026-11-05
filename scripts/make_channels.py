"""`make channels`: download 802.3dj KR channels, verify, convert to symbol-spaced pulse responses.

Outputs
    data/channels/<id>.npz        pulse response + every parameter used to make it
    data/results/channels.csv     one row per channel (sidecar: channels.md)

Selection of TX FIR + CTLE: grid search maximising MMSE FFE+DFE SNR against a reference
receiver, with input-referred noise shaped by CTLE and RX filter. See
docs/decisions/0001-channel-model.md for why each constant is what it is.
"""

from __future__ import annotations

import csv
import hashlib
import itertools
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model.channel import (  # noqa: E402
    BAUD,
    OVERSAMPLE,
    CtleParams,
    apply_tx_fir,
    ctle,
    load_sdd21,
    oversampled_pulse,
    rx_filter,
    sample_at_best_phase,
    truncate_energy,
)
from model.equalizer import mmse_ffe_dfe  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
ARCHIVE = "shanbhag_3dj_02_2305.zip"
URL = "https://www.ieee802.org/3/dj/public/tools/KR/" + ARCHIVE
SHA256 = "4688e7832cf3b7d5abe41f60a80b023f62c9a2fda235f83cbcd07e09166598df"

# id -> (THRU file in archive, IL @ 53.125 GHz published in shanbhag_3dj_02a_2305 slide 7)
CHANNELS = {
    "kr_ch2_19p3db": ("KR_1mCabledBP_TP0TP5_19p3dB_PCBHost_3p8dB_THRU.s4p", 19.3),
    "kr_ch4_31p4db": ("KR_1mCabledBP_TP0TP5_31p4dB_PCBHost_9p8dB_THRU.s4p", 31.4),
}

F_PASS, F_STOP = 67e9, 80e9  # authors: usable bandwidth 67 GHz; data ends at 80 GHz
# Reference values for TX FIR / CTLE *selection only* (802.3ck COM style; ADR 0001).
A_V = 0.413  # V, TX peak amplitude: PAM4 symbol 3 -> A_V
ETA0 = 8.2e-9  # V^2/GHz, one-sided input-referred noise PSD
REF_TAPS, REF_PRE, REF_DFE = 16, 3, 1
G_DC = np.arange(-20.0, 0.5, 1.0)
G_DC2 = np.arange(-6.0, 0.5, 1.0)
C_PRE = np.round(np.arange(-0.30, 0.001, 0.05), 3)  # c(-1)
C_POST = np.round(np.arange(-0.30, 0.001, 0.05), 3)  # c(+1)
CROP_PRE, CROP_POST = 40, 400  # UI kept around the cursor for optimisation and storage
ENERGY_FRAC = 0.999


def fetch() -> Path:
    RAW.mkdir(parents=True, exist_ok=True)
    zp = RAW / ARCHIVE
    if not zp.exists():
        print(f"downloading {URL}")
        urllib.request.urlretrieve(URL, zp)
    digest = hashlib.sha256(zp.read_bytes()).hexdigest()
    if digest != SHA256:
        sys.exit(f"SHA-256 mismatch for {zp}: {digest} (expected {SHA256}, see data/MANIFEST.md)")
    out = RAW / "shanbhag"
    with zipfile.ZipFile(zp) as z:
        for name, _ in CHANNELS.values():
            if not (out / name).exists():
                z.extract(name, out)
    return out


def noise_var(f: np.ndarray, cp: CtleParams) -> float:
    """Variance of input-referred white noise (one-sided PSD ETA0) after CTLE x RX filter."""
    fg = np.linspace(0, OVERSAMPLE * BAUD / 2, 200001)
    g = np.abs(ctle(fg, cp) * rx_filter(fg)) ** 2
    return float(ETA0 * np.trapezoid(g, fg / 1e9))


def convert(cid: str, path: Path, il_pub: float) -> dict[str, float | int | str]:
    f, h = load_sdd21(str(path))
    h_ny = np.interp(BAUD / 2, f, np.abs(h))
    il = -20 * np.log10(h_ny)
    if abs(il - il_pub) > 0.5:
        sys.exit(f"{cid}: IL {il:.2f} dB vs published {il_pub} dB; port map or file is wrong")

    best: tuple[float, ...] | None = None
    for gdc, gdc2 in itertools.product(G_DC, G_DC2):
        cp = CtleParams(float(gdc), float(gdc2))
        sampled, cur, _ = sample_at_best_phase(oversampled_pulse(f, h, cp, F_PASS, F_STOP))
        seg = sampled[cur - CROP_PRE : cur + CROP_POST] * (A_V / 3)
        nv = noise_var(f, cp)
        for cm1, cp1 in itertools.product(C_PRE, C_POST):
            taps = np.array([cm1, 1 - abs(cm1) - abs(cp1), cp1])
            p, c = apply_tx_fir(seg, CROP_PRE, taps, 1)
            r = mmse_ffe_dfe(p, c, REF_TAPS, REF_PRE, REF_DFE, nv)
            if best is None or r.snr_db > best[0]:
                best = (r.snr_db, gdc, gdc2, cm1, cp1, nv)
    assert best is not None
    snr, gdc, gdc2, cm1, cp1, nv = best

    cp = CtleParams(gdc, gdc2)
    pos = oversampled_pulse(f, h, cp, F_PASS, F_STOP)
    sampled, cur, phase = sample_at_best_phase(pos)
    taps = np.array([cm1, 1 - abs(cm1) - abs(cp1), cp1])
    full, fcur = apply_tx_fir(sampled * (A_V / 3), cur, taps, 1)
    pulse = full[fcur - CROP_PRE : fcur + CROP_POST]
    n_pre, n_post = truncate_energy(pulse, CROP_PRE, ENERGY_FRAC)
    np.savez(
        ROOT / "data" / "channels" / f"{cid}.npz",
        pulse=pulse, cursor=CROP_PRE, n_pre=n_pre, n_post=n_post, phase=phase,
        ctle_gdc=gdc, ctle_gdc2=gdc2, tx_taps=taps, noise_var_ref=nv, baud=BAUD,
        a_v=A_V, source=str(path.name),
        pulse_os=pos[max(0, int(np.argmax(pos)) - CROP_PRE * OVERSAMPLE):
                     int(np.argmax(pos)) + CROP_POST * OVERSAMPLE] * (A_V / 3),
    )  # fmt: skip
    return {
        "channel": cid, "source_file": path.name, "il_published_db": il_pub,
        "il_computed_db": round(il, 2), "ctle_gdc_db": gdc, "ctle_gdc2_db": gdc2,
        "tx_c_m1": cm1, "tx_c0": round(taps[1], 3), "tx_c_p1": cp1,
        "sampling_phase": f"{phase}/{OVERSAMPLE}",
        "main_cursor_mv": round(pulse[CROP_PRE] * 1e3, 3),
        "n_pre_999": n_pre, "n_post_999": n_post,
        "ref_rx": f"FFE{REF_TAPS}(pre{REF_PRE})+DFE{REF_DFE}", "ref_snr_db": round(snr, 2),
    }  # fmt: skip


def main() -> None:
    raw = fetch()
    (ROOT / "data" / "channels").mkdir(parents=True, exist_ok=True)
    rows = [convert(cid, raw / name, il) for cid, (name, il) in CHANNELS.items()]
    out = ROOT / "data" / "results" / "channels.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
