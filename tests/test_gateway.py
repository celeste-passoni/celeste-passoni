# -*- coding: utf-8 -*-
"""Regras do gateway que não precisam de rede."""
from datetime import datetime
from zoneinfo import ZoneInfo


def test_corte_de_mensagens_antigas(monkeypatch):
    import sys
    import google.cloud.firestore as fs
    monkeypatch.setattr(fs, "Client", lambda **k: None)
    sys.modules.pop("celeste.gateway.app", None)
    from celeste.gateway import app as gw
    sp = ZoneInfo("America/Sao_Paulo")
    assert gw._antiga(int(datetime(2026, 9, 28, 23, 59, tzinfo=sp).timestamp()))
    assert not gw._antiga(int(datetime(2026, 9, 29, 0, 1, tzinfo=sp).timestamp()))
