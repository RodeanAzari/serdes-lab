"""`make xcheck`: independent cross-check of the float model against serdespy 1.0 (buildplan §8).

1. Channel conversion: serdespy `four_port_to_diff` vs `model.channel.load_sdd21` on the same
   raw Touchstone files (matched 50-ohm source/load, so serdespy's H = SDD21 / 2).
2. Link BER: same truncated pulse and the same MMSE FFE16(pre3)+DFE1 taps, but serdespy does
   the TX symbol mapping (its own Gray coder), noise, FFE, the sequential PAM4 DFE with real
   decisions, slicing and demapping, with its own payload/noise generators. Not bit-exact by
   design: BERs must agree statistically. DFE error propagation clusters errors, so both
   sides are compared with batch-means standard errors over equal chunks, not binomial CIs.

serdespy has no CTLE, so its own pulse response can't be compared; the pulse is ours (§8).
Output: data/results/serdespy_sdd21.csv, data/results/serdespy_ber.csv (sidecars: .md).
"""

from __future__ import annotations

import csv
import subprocess
import sys
import warnings
from pathlib import Path

import numpy as np
import skrf as rf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model.channel import BAUD, load_sdd21  # noqa: E402
from model.equalizer import mmse_ffe_dfe  # noqa: E402
from model.link import noise_sigma, run_link  # noqa: E402

warnings.filterwarnings("ignore", category=UserWarning)
import serdespy as sdp  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "shanbhag"
FILES = {
    "kr_ch2_19p3db": "KR_1mCabledBP_TP0TP5_19p3dB_PCBHost_3p8dB_THRU.s4p",
    "kr_ch4_31p4db": "KR_1mCabledBP_TP0TP5_31p4dB_PCBHost_9p8dB_THRU.s4p",
}
POINTS = {"kr_ch2_19p3db": [18.0, 19.0, 20.0, 21.0], "kr_ch4_31p4db": [22.0, 23.0, 24.0, 25.0]}
REF_TAPS, REF_PRE = 16, 3
LEVELS = np.array([-3.0, -1.0, 1.0, 3.0])
CHUNK = 500_000  # symbols per batch
MIN_CHUNKS, TARGET_ERRORS, MAX_CHUNKS = 10, 200, 60
SEED_SDP, SEED_MODEL = 4242, 9100  # different from model_ber_float.csv's seeds
F_MAX = 67e9  # usable bandwidth of the data (ADR 0001)
GUARD = 64  # symbols skipped at each chunk edge (filter/DFE start-up)


def sdd21_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for cid, name in FILES.items():
        f, ours = load_sdd21(str(RAW / name))
        net = rf.Network(str(RAW / name))
        h_sdp = sdp.four_port_to_diff(net, np.array([[0, 1], [2, 3]]), 50.0, 50.0)[0]
        theirs = 2.0 * np.asarray(h_sdp)  # matched terminations: H = SDD21 / 2
        band = f <= F_MAX
        db = lambda h: 20 * np.log10(np.abs(h))  # noqa: E731
        diff_db = np.abs(db(ours[band]) - db(theirs[band]))
        ny = int(np.argmin(np.abs(f - BAUD / 2)))
        rows.append({
            "channel": cid, "f_nyquist_ghz": round(f[ny] / 1e9, 4),
            "il_nyquist_db_model": round(-float(db(ours[ny])), 3),
            "il_nyquist_db_serdespy": round(-float(db(theirs[ny])), 3),
            "max_abs_diff_db_to_67ghz": float(diff_db.max()),
            "max_abs_phase_diff_deg_to_67ghz": float(np.degrees(np.abs(
                np.angle(ours[band] / theirs[band]))).max()),
        })  # fmt: skip
    return rows


def serdespy_chunk(pulse, cursor, taps, b, h0, sigma, seed):  # type: ignore[no-untyped-def]
    """One chunk through serdespy; returns (bits, bit_errors, latency in symbols)."""
    rs = np.random.RandomState(seed)
    bits = rs.randint(0, 2, 2 * CHUNK).astype(np.uint8)
    syms = np.array([sdp.grey_encode(bits[2 * i : 2 * i + 2]) for i in range(CHUNK)])
    tx = sdp.Transmitter(syms, LEVELS, 2 * BAUD)
    y = np.convolve(tx.signal_BR, pulse)[: CHUNK + 64]
    rx = sdp.Receiver(y, 1, BAUD / 2, LEVELS, shift=False, main_cursor=h0)
    np.random.seed(seed + 1)  # serdespy draws noise from numpy's global generator
    rx.noise(sigma)
    rx.slice_signal()
    rx.FFE_BR(taps, REF_PRE)
    rx.pam4_DFE_BR(np.array([b]))
    out = rx.symbols_out
    # Latency (channel cursor + FFE 'same' centring) found by search, then checked.
    n = 20_000
    lags = range(-40, 41)
    match = [np.mean(out[GUARD + lag : GUARD + lag + n] == syms[GUARD : GUARD + n]) for lag in lags]
    lag = lags[int(np.argmax(match))]
    if max(match) < 0.95:
        raise RuntimeError(f"serdespy alignment failed: best match {max(match):.3f}")
    k = np.arange(GUARD, CHUNK - GUARD - 40)
    rx_bits = np.concatenate([sdp.grey_decode(int(s)) for s in out[k + lag]])
    tx_bits = bits.reshape(-1, 2)[k].reshape(-1)
    return len(tx_bits), int(np.count_nonzero(rx_bits != tx_bits)), lag


def paired_chunk(pulse, cursor, taps, b, h0, snr, seed_data, seed_noise):  # type: ignore[no-untyped-def]
    """Same bits and noise as run_link, equalised by serdespy. Returns (serdespy, model) errors.

    Rebuilds run_link's exact draws, hands serdespy the noisy ADC samples, and counts bit
    errors over run_link's own guard window. Identical engines -> identical counts.
    """
    rng_d = np.random.default_rng(seed_data)
    rng_n = np.random.default_rng(np.random.SeedSequence(seed_noise, spawn_key=(1,)))
    bits = rng_d.integers(0, 2, size=2 * CHUNK, dtype=np.uint8)
    syms = np.array([sdp.grey_encode(bits[2 * i : 2 * i + 2]) for i in range(CHUNK)])
    a = sdp.Transmitter(syms, LEVELS, 2 * BAUD).signal_BR
    y = np.convolve(a, pulse)[cursor : cursor + CHUNK]
    y = y + rng_n.normal(0.0, noise_sigma(pulse, snr), size=CHUNK)
    rx = sdp.Receiver(y, 1, BAUD / 2, LEVELS, shift=False, main_cursor=h0)
    rx.slice_signal()
    rx.FFE_BR(taps, REF_PRE)
    rx.pam4_DFE_BR(np.array([b]))
    shift = (len(taps) - 1) // 2 - REF_PRE  # 'same' centring vs run_link's n_pre alignment
    guard = len(pulse) + len(taps)
    k = np.arange(guard, CHUNK - guard)
    rx_bits = np.concatenate([sdp.grey_decode(int(v)) for v in rx.symbols_out[k - shift]])
    s_err = int(np.count_nonzero(rx_bits != bits.reshape(-1, 2)[k].reshape(-1)))
    r = run_link(pulse, cursor, taps, REF_PRE, b, h0, snr, CHUNK, seed_data, seed_noise)
    return s_err, r.bit_errors


def paired_rows(commit: str, n_chunks: int = 10) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for cid, snrs in POINTS.items():
        d = np.load(ROOT / "data" / "channels" / f"{cid}.npz")
        cur, n_pre, n_post = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
        pulse = d["pulse"][cur - n_pre : cur + n_post + 1]
        for snr in snrs:
            sigma = noise_sigma(pulse, snr)
            eq = mmse_ffe_dfe(pulse, n_pre, REF_TAPS, REF_PRE, 1, sigma**2)
            pairs = [paired_chunk(pulse, n_pre, eq.taps, float(eq.dfe[0]), eq.h0, snr,
                                  SEED_MODEL + k, SEED_MODEL + 500 + k)
                     for k in range(n_chunks)]  # fmt: skip
            s_tot, m_tot = sum(p[0] for p in pairs), sum(p[1] for p in pairs)
            mism = sum(p[0] != p[1] for p in pairs)
            rows.append({"channel": cid, "snr_db": snr, "chunks": n_chunks,
                         "chunk_symbols": CHUNK, "serdespy_bit_errors": s_tot,
                         "model_bit_errors": m_tot, "chunks_with_different_count": mism,
                         "seed_model": SEED_MODEL, "commit": commit})  # fmt: skip
            print(f"paired {cid} {snr:4.1f} dB: serdespy {s_tot} model {m_tot} "
                  f"mismatched chunks {mism}/{n_chunks}", flush=True)
    return rows


def batch_stats(per_chunk: list[tuple[int, int]]) -> tuple[int, int, float, float]:
    bits = np.array([c[0] for c in per_chunk], dtype=np.float64)
    errs = np.array([c[1] for c in per_chunk], dtype=np.float64)
    rates = errs / bits
    se = float(rates.std(ddof=1) / np.sqrt(len(rates)))
    return int(bits.sum()), int(errs.sum()), float(errs.sum() / bits.sum()), se


def ber_rows(commit: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for cid, snrs in POINTS.items():
        d = np.load(ROOT / "data" / "channels" / f"{cid}.npz")
        cur, n_pre, n_post = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
        pulse = d["pulse"][cur - n_pre : cur + n_post + 1]
        for snr in snrs:
            sigma = noise_sigma(pulse, snr)
            eq = mmse_ffe_dfe(pulse, n_pre, REF_TAPS, REF_PRE, 1, sigma**2)
            b = float(eq.dfe[0])
            sd: list[tuple[int, int]] = []
            md: list[tuple[int, int]] = []
            lags = set()
            while len(sd) < MAX_CHUNKS and (
                len(sd) < MIN_CHUNKS or min(sum(c[1] for c in x) for x in (sd, md)) < TARGET_ERRORS
            ):
                k = len(sd)
                nb, ne, lag = serdespy_chunk(pulse, n_pre, eq.taps, b, eq.h0, sigma,
                                             SEED_SDP + 1000 * k)  # fmt: skip
                sd.append((nb, ne))
                lags.add(lag)
                r = run_link(pulse, n_pre, eq.taps, REF_PRE, b, eq.h0, snr, CHUNK,
                             SEED_MODEL + k, SEED_MODEL + 500 + k)  # fmt: skip
                md.append((r.bits, r.bit_errors))
            s_bits, s_err, s_ber, s_se = batch_stats(sd)
            m_bits, m_err, m_ber, m_se = batch_stats(md)
            z = (s_ber - m_ber) / np.hypot(s_se, m_se)
            rows.append({
                "channel": cid, "snr_db": snr, "snr_definition": "E[s^2]/sigma^2 at ADC input",
                "equalizer": f"MMSE FFE{REF_TAPS}(pre{REF_PRE})+DFE1 real decisions, float",
                "precoder": "off", "chunks": len(sd), "chunk_symbols": CHUNK,
                "serdespy_bits": s_bits, "serdespy_bit_errors": s_err, "serdespy_ber": s_ber,
                "serdespy_ber_se": s_se, "model_bits": m_bits, "model_bit_errors": m_err,
                "model_ber": m_ber, "model_ber_se": m_se, "ratio": s_ber / m_ber,
                "z": float(z), "serdespy_lag": ",".join(map(str, sorted(lags))),
                "seed_serdespy": SEED_SDP, "seed_model": SEED_MODEL, "commit": commit,
            })  # fmt: skip
            print(f"{cid} {snr:4.1f} dB: serdespy {s_ber:.3e} ({s_err}) model {m_ber:.3e} "
                  f"({m_err}) ratio {s_ber / m_ber:.3f} z {z:+.2f}", flush=True)  # fmt: skip
    return rows


def write(rows: list[dict[str, object]], name: str) -> None:
    with (ROOT / "data" / "results" / name).open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    s = sdd21_rows()
    for r in s:
        print(r)
    write(s, "serdespy_sdd21.csv")
    write(ber_rows(commit), "serdespy_ber.csv")
    write(paired_rows(commit), "serdespy_paired.csv")


if __name__ == "__main__":
    main()
