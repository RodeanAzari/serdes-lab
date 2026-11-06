"""KP4 RS(544,514) tests (§6.2), checked against the spec and the independent `galois` library.

galois builds the parent RS(1023,993) code with the same field polynomial and first root
alpha^0, and shortens it to 544/514. It shares no code with model/rs.py.
"""

import galois
import numpy as np
import pytest

from model import pam4, rs

GF = galois.GF(2**10, irreducible_poly="x^10+x^3+1")
REF = galois.ReedSolomon(1023, 993, field=GF, c=0, alpha=GF.primitive_element)


def _corrupt(rng: np.random.Generator, c: np.ndarray, nerr: int, pos: np.ndarray | None = None):
    r = c.copy()
    if pos is None:
        pos = rng.choice(rs.N, nerr, replace=False)
    r[pos] ^= rng.integers(1, 1024, len(pos))
    return r


def test_field_is_spec_field() -> None:
    # x^10 + x^3 + 1: alpha^10 = alpha^3 + 1, and alpha generates all 1023 nonzero elements.
    assert rs.EXP[10] == 0b1001
    assert len(set(rs.EXP[: rs.Q1].tolist())) == 1023
    a, b = 0x2A5, 0x1F3
    assert rs.gf_mul(a, b) == int(GF(a) * GF(b))


def test_generator_matches_reference() -> None:
    assert len(rs.GEN) == 31
    assert np.array_equal(rs.GEN, np.array(REF.generator_poly.coeffs))


def test_codewords_vanish_at_generator_roots() -> None:
    # Spec definition, independent of any library: c(alpha^j) = 0 for j = 0..29.
    rng = np.random.default_rng(1)
    c = rs.encode(rng.integers(0, 1024, (4, rs.K)))
    for j in (0, 1, 29):
        x = GF.primitive_element**j
        powers = x ** np.arange(rs.N - 1, -1, -1)
        assert not np.any(np.sum(GF(c) * powers, axis=1))
    assert not rs.syndromes(c).any()


def test_encode_matches_reference_and_is_systematic() -> None:
    rng = np.random.default_rng(2)
    m = rng.integers(0, 1024, (50, rs.K))
    m[0] = 0
    m[1] = 1023
    c = rs.encode(m)
    assert c.shape == (50, rs.N)
    assert np.array_equal(c[:, : rs.K], m)
    assert np.array_equal(c, np.array(REF.encode(GF(m))))


@pytest.mark.parametrize("nerr", [0, 1, 2, 7, 14, 15])
def test_corrects_up_to_t(nerr: int) -> None:
    rng = np.random.default_rng(100 + nerr)
    c = rs.encode(rng.integers(0, 1024, (40, rs.K)))
    r = np.stack([_corrupt(rng, w, nerr) for w in c])
    d, n = rs.decode(r)
    assert np.array_equal(d, c)
    assert np.all(n == nerr)


def test_corrects_errors_at_codeword_edges() -> None:
    # First and last transmitted symbols, parity boundary, and a burst at the end.
    rng = np.random.default_rng(5)
    c = rs.encode(rng.integers(0, 1024, rs.K))
    for pos in ([0], [543], [513, 514], list(range(529, 544)), list(range(15))):
        r = _corrupt(rng, c, 0, np.array(pos))
        d, n = rs.decode(r)
        assert np.array_equal(d, c) and n == len(pos), pos


@pytest.mark.parametrize("nerr", [16, 17, 20, 30, 60])
def test_beyond_t_agrees_with_reference(nerr: int) -> None:
    rng = np.random.default_rng(200 + nerr)
    c = rs.encode(rng.integers(0, 1024, (40, rs.K)))
    r = np.stack([_corrupt(rng, w, nerr) for w in c])
    d, n = rs.decode(r)
    ref_d, ref_n = REF.decode(GF(r), output="codeword", errors=True)
    assert np.array_equal(n, np.array(ref_n))
    ok = n >= 0
    assert np.array_equal(d[ok], np.array(ref_d)[ok])
    # Failures leave the word unchanged; any "success" must be a codeword within distance t.
    assert np.array_equal(d[~ok], r[~ok])
    assert not rs.syndromes(d[ok]).any() if ok.any() else True
    assert np.all((d[ok] != r[ok]).sum(axis=1) <= rs.T)
    assert np.all(n == -1)  # at these weights a miscorrection is ~1e-5 likely per word


def test_miscorrection_is_reported_as_success() -> None:
    # A received word at distance 15 from a *different* codeword decodes to that codeword.
    rng = np.random.default_rng(7)
    c = rs.encode(rng.integers(0, 1024, (2, rs.K)))
    r = c[1].copy()
    diff = np.flatnonzero(c[0] != c[1])
    r[diff[:15]] = c[0][diff[:15]]  # now 15 from c[1], far from c[0]
    assert (r != c[0]).sum() >= 16  # sent c[0]: beyond t
    d, n = rs.decode(r)
    assert n == 15 and np.array_equal(d, c[1])


def test_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        rs.encode(np.zeros(513, dtype=np.int64))
    with pytest.raises(ValueError):
        rs.decode(np.zeros(545, dtype=np.int64))
    with pytest.raises(ValueError):
        rs.encode(np.full(rs.K, 1024))
    with pytest.raises(ValueError):
        rs.bits_to_symbols(np.zeros(15, dtype=np.uint8))


def test_rs_symbol_is_five_pam4_symbols() -> None:
    # Alignment: one RS symbol error must hit exactly one 5-PAM4-symbol group, and vice versa.
    rng = np.random.default_rng(8)
    s = rng.integers(0, 1024, 2 * rs.N)
    bits = rs.symbols_to_bits(s)
    lv = pam4.bits_to_symbols(bits)
    assert len(lv) == 5 * len(s)
    assert np.array_equal(rs.bits_to_symbols(pam4.symbols_to_bits(lv)), s)
    assert list(rs.symbols_to_bits(np.array([0b1000000001]))) == [1, 0, 0, 0, 0, 0, 0, 0, 0, 1]
    lv2 = lv.copy()
    lv2[5 * 37 + 4] = -lv2[5 * 37 + 4]  # last PAM4 symbol of RS symbol 37
    s2 = rs.bits_to_symbols(pam4.symbols_to_bits(lv2))
    assert list(np.flatnonzero(s2 != s)) == [37]
