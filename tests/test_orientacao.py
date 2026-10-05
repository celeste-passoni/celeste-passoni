# -*- coding: utf-8 -*-
"""Orientação automática para quem escreve ao número e não está na base de leads."""
from unittest.mock import MagicMock


def _orq(monkeypatch):
    import sys
    import google.cloud.firestore as fs
    monkeypatch.setattr(fs, "Client", lambda **k: MagicMock())
    sys.modules.pop("celeste.orquestrador.app", None)
    from celeste.orquestrador import app as orq
    orq.db.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {"orientar_automatico": True}
    return orq


def test_orienta_uma_vez_e_grava_no_painel(monkeypatch):
    orq = _orq(monkeypatch)
    mt = MagicMock(); mt.enviar_botao_url.return_value = "wamid.bot"
    monkeypatch.setattr(orq, "_svc", lambda: (None, mt, None))
    ref = MagicMock()
    r = orq._orientar_recepcao(ref, {"id": "c1", "contato": "5511777770000"})
    assert r["orientado_recepcao"] and mt.enviar_botao_url.call_args.args[2] == "Falar com Recepção"
    assert "recepção ou equipe médica" in mt.enviar_botao_url.call_args.args[1]
    gravado = ref.collection.return_value.document.return_value.set.call_args.args[0]
    assert gravado["direcao"] == "celeste" and "Falar com Recepção" in gravado["texto"]      # aparece no painel
    assert ref.set.call_args.args[0]["status"] == "Orientado à recepção"
    # segunda mensagem da mesma pessoa dentro de 24 h: não reenvia
    from datetime import datetime, timedelta, timezone
    mt.reset_mock()
    r2 = orq._orientar_recepcao(ref, {"id": "c1", "contato": "5511777770000", "orientado_recepcao_em": datetime.now(timezone.utc) - timedelta(hours=23)})
    assert "já orientado" in r2["ignorado"] and not mt.enviar_botao_url.called
    # botão do painel: força o envio mesmo dentro das 24 h
    rf = orq._orientar_recepcao(ref, {"id": "c1", "contato": "5511777770000", "orientado_recepcao_em": datetime.now(timezone.utc)}, forcar=True)
    assert rf["orientado_recepcao"] and mt.enviar_botao_url.called
    # depois de 24 h: reenvia
    r3 = orq._orientar_recepcao(ref, {"id": "c1", "contato": "5511777770000", "orientado_recepcao_em": datetime.now(timezone.utc) - timedelta(hours=25)})
    assert r3["orientado_recepcao"] and mt.enviar_botao_url.called


def test_orientacao_automatica_desligada_so_manual(monkeypatch):
    orq = _orq(monkeypatch)
    orq.db.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {"orientar_automatico": False}
    mt = MagicMock(); mt.enviar_botao_url.return_value = "wamid.bot"
    monkeypatch.setattr(orq, "_svc", lambda: (None, mt, None))
    ref = MagicMock()
    r = orq._orientar_recepcao(ref, {"id": "c1", "contato": "5511777770000"})
    assert "desligada" in r["ignorado"] and not mt.enviar_botao_url.called
    r2 = orq._orientar_recepcao(ref, {"id": "c1", "contato": "5511777770000"}, forcar=True)   # botão do painel
    assert r2["orientado_recepcao"] and mt.enviar_botao_url.called


def test_modo_humano_e_envio(monkeypatch):
    orq = _orq(monkeypatch)
    from fastapi import HTTPException
    import pytest
    # /modo grava o modo na conversa
    doc = orq.db.collection.return_value.document.return_value
    doc.get.return_value.exists = True
    assert orq.mudar_modo(orq.PedidoModo(conversa_id="c1", modo="humano"))["modo"] == "humano"
    assert doc.set.call_args.args[0]["modo"] == "humano"
    with pytest.raises(HTTPException):
        orq.mudar_modo(orq.PedidoModo(conversa_id="c1", modo="x"))
    # /enviar exige modo humano
    doc.get.return_value.to_dict.return_value = {"contato": "5511999990000", "modo": "ia"}
    with pytest.raises(HTTPException):
        orq.enviar_humano(orq.PedidoEnviar(conversa_id="c1", texto="oi"))
    doc.get.return_value.to_dict.return_value = {"contato": "5511999990000", "modo": "humano"}
    mt = MagicMock(); mt.enviar_texto.return_value = "wamid.h"
    monkeypatch.setattr(orq, "_svc", lambda: (None, mt, None))
    r = orq.enviar_humano(orq.PedidoEnviar(conversa_id="c1", texto="Olá, aqui é a equipe"))
    assert r["wamid"] == "wamid.h" and mt.enviar_texto.call_args.args == ("5511999990000", "Olá, aqui é a equipe")
    gravado = doc.collection.return_value.document.return_value.set.call_args.args[0]
    assert gravado["direcao"] == "humano"


def test_aviso_recebimento(monkeypatch):
    orq = _orq(monkeypatch)
    doc = orq.db.collection.return_value.document.return_value
    doc.get.return_value.to_dict.return_value = {"contato": "5511999990000"}
    mt = MagicMock(); mt.enviar_texto.return_value = "wamid.a"
    monkeypatch.setattr(orq, "_svc", lambda: (None, mt, None))
    r = orq.aviso_recebimento(orq.PedidoAviso(conversa_id="c1"))
    assert r["wamid"] == "wamid.a" and "encaminhada para a nossa equipe" in mt.enviar_texto.call_args.args[1]


def test_normalizacao_conversa_teste_no_codigo():
    import inspect
    from celeste.orquestrador import app as orq
    src = inspect.getsource(orq.responder)
    assert 'norm["frente"] = "leads_perdidos"' in src and 'norm["status"] = "Em conversa"' in src
