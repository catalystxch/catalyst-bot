"""A misfit absorption's own output coin must never look like a new deposit."""

from __future__ import annotations

import json
from types import SimpleNamespace

import database
from coin_manager import CoinManager

PRE_A = "aa" * 32
PRE_B = "bb" * 32
OUTPUT = "cc" * 32


def _settings(monkeypatch, initial=""):
    store = {"deposit_advisory_advised_coins": initial}
    monkeypatch.setattr(
        database, "get_setting", lambda key, default=None: store.get(key, default)
    )
    monkeypatch.setattr(
        database, "set_setting", lambda key, value: store.__setitem__(key, value)
    )
    return store


def _receipt():
    return SimpleNamespace(
        operation={
            "prepared_evidence_json": json.dumps(
                {"pre_view_coin_ids": [PRE_A, "0x" + PRE_B]}
            )
        }
    )


def test_absorbed_output_coin_is_recorded_as_internal(monkeypatch):
    store = _settings(monkeypatch, initial="0x" + "dd" * 32)
    manager = CoinManager.__new__(CoinManager)

    manager._remember_absorbed_output_coins(
        _receipt(), {"0x" + PRE_A: 5, PRE_B.upper(): 6, OUTPUT: 11}
    )

    advised = set(store["deposit_advisory_advised_coins"].split(","))
    assert advised == {"0x" + "dd" * 32, "0x" + OUTPUT}


def test_nothing_is_recorded_when_no_new_coin_appeared(monkeypatch):
    store = _settings(monkeypatch)
    manager = CoinManager.__new__(CoinManager)

    manager._remember_absorbed_output_coins(_receipt(), {PRE_A: 5})

    assert store["deposit_advisory_advised_coins"] == ""


def test_bad_receipt_never_raises(monkeypatch):
    store = _settings(monkeypatch)
    manager = CoinManager.__new__(CoinManager)

    manager._remember_absorbed_output_coins(SimpleNamespace(operation={}), {OUTPUT: 1})

    assert store["deposit_advisory_advised_coins"] == ""
