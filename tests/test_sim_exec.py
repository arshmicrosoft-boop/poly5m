import pytest

from poly5m.sim_exec import calculate_crypto_fee


def test_fee_at_half():
    assert calculate_crypto_fee(0.50, 1.0) == 0.0175


def test_fee_at_058():
    assert abs(calculate_crypto_fee(0.58, 1.0) - 0.017052) < 1e-4


def test_min_fee_floor():
    assert calculate_crypto_fee(0.50, 0.0001) == 0.00001


def test_breakeven_allin():
    p = 0.58
    fee = calculate_crypto_fee(p, 1.0)
    all_in = p + fee  # per share
    assert abs(all_in - 0.6011) < 5e-3
    # 5 shares
    total = 5 * all_in
    assert abs(total - 5 * 0.6011) < 5e-2
