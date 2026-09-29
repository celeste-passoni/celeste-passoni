# -*- coding: utf-8 -*-
"""Orientação automática para quem escreve ao número e não está na base de leads."""
from unittest.mock import MagicMock


def _orq(monkeypatch):
    import sys
    import google.cloud.firestore as fs
    monkeypatch.setattr(fs, "Client", lambda **k: MagicMock())
    sys.modules.pop("celeste.orquestrador.app", None)
    from celeste.orquestrador import app as orq
    orq.db.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {}
    return orq


def test_orienta_uma_vez_e_grava_no_painel(monkeypatch):
    orq = _orq(monkeypatch)
    mt = MagicMock(); mt.enviar_botao_url.return_value = "wamid.bot"
    monkeypatch.setattr(orq, "_svc", lambda: (None, mt, None))
    ref = MagicMock()
    r = orq._orientar_recepcao(ref, {"id": "c1", "contato": "5511777770000"})
    assert r["orientado_recepcao"] and mt.enviar_botao_url.call_args.args[2] == "Falar com Recepção"
    assert "avisos automáticos" in mt.enviar_botao_url.call_args.args[1]
    gravado = ref.collection.return_value.document.return_value.set.call_args.args[0]
    assert gravado["direcao"] == "celeste" and "Falar com Recepção" in gravado["texto"]      # aparece no painel
    assert ref.set.call_args.args[0]["status"] == "Orientado à recepção"
    # segunda mensagem da mesma pessoa: não reenvia
    mt.reset_mock()
    r2 = orq._orientar_recepcao(ref, {"id": "c1", "contato": "5511777770000", "orientado_recepcao_em": "x"})
    assert "já orientado" in r2["ignorado"] and not mt.enviar_botao_url.called
