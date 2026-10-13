# -*- coding: utf-8 -*-
"""Regras de carga e de disparo, sem rede."""
from datetime import datetime, timedelta, timezone

import pytest

from celeste.jobs import base_leads, disparos

AGORA = datetime(2026, 10, 13, 14, 0, tzinfo=timezone.utc)  # terça 11h em SP


@pytest.mark.parametrize("bruto,esperado", [
    ("+55 (11) 99999-0000", "5511999990000"),
    ("11999990000", "5511999990000"),
    ("551199990000", "5511999990000"),      # 55 + DDD + 8 dígitos → insere o 9
    ("1199990000", "5511999990000"),
    ("0011999990000", "5511999990000"),
    ("999990000", None), ("", None), (None, None),
])
def test_normalizar_celular(bruto, esperado):
    assert base_leads.normalizar_celular(bruto) == esperado


def test_primeiro_nome():
    assert base_leads._primeiro_nome("MARIA DA SILVA") == "Maria"
    assert base_leads._primeiro_nome("  ") == ""
    assert base_leads._primeiro_nome("Laís✨ 22") == "Laís"
    assert base_leads._primeiro_nome("A. Carlos") == "Carlos"


def test_sql_usa_filtros_do_yaml():
    from celeste.comum import config
    sql = base_leads.sql_base(config.parametros()["leads_perdidos"])
    assert "'Não quer'" in sql and "INTERVAL 4 MONTH" in sql and "INTERVAL 3 MONTH" in sql and "QUALIFY ROW_NUMBER()" in sql
    assert "INTERVAL" not in base_leads.sql_base(config.parametros()["leads_perdidos"], com_janela=False)


def _lead(**k):
    base = {"elegivel": True, "opt_out": False, "status_ia": "Não contatado", "passo": 0, "ultimo_template_em": None}
    base.update(k)
    return base


def test_esteira_segue_cadencia_da_atendente_de_referencia():
    # T1 (revisando agenda) → +3 d T2 (me dá um oi) → +3 d T3 (duas modalidades) → +8 d T4 (demonstrou interesse) → +3 d T2
    d0 = disparos.decidir(_lead(), AGORA)
    assert d0 and d0.template == "T1" and d0.novo_passo == 1
    assert disparos.decidir(_lead(status_ia="Template enviado (1°)", passo=1, ultimo_template_em=AGORA - timedelta(days=2)), AGORA) is None
    d2 = disparos.decidir(_lead(status_ia="Template enviado (1°)", passo=1, ultimo_template_em=AGORA - timedelta(days=3)), AGORA)
    assert d2 and d2.template == "T2" and d2.novo_passo == 2
    d3 = disparos.decidir(_lead(status_ia="Template enviado (2°)", passo=2, ultimo_template_em=AGORA - timedelta(days=3)), AGORA)
    assert d3 and d3.template == "T3" and d3.novo_passo == 3
    assert disparos.decidir(_lead(status_ia="Template enviado (2°)", passo=3, ultimo_template_em=AGORA - timedelta(days=7)), AGORA) is None
    d4 = disparos.decidir(_lead(status_ia="Template enviado (2°)", passo=3, ultimo_template_em=AGORA - timedelta(days=8)), AGORA)
    assert d4 and d4.template == "T4" and d4.novo_passo == 4
    d5 = disparos.decidir(_lead(status_ia="Template enviado (1°)", passo=4, ultimo_template_em=AGORA - timedelta(days=3)), AGORA)
    assert d5 and d5.template == "T2" and d5.novo_passo == 5


def test_pausa_e_reinicio_da_esteira():
    # fim da esteira: pausa de 30 dias e volta ao índice 2 (T3)
    fim = _lead(status_ia="Template enviado (2°)", passo=5, ultimo_template_em=AGORA - timedelta(days=29))
    assert disparos.decidir(fim, AGORA) is None
    fim["ultimo_template_em"] = AGORA - timedelta(days=31)
    r = disparos.decidir(fim, AGORA)
    assert r and r.template == "T3" and r.novo_passo == 3


def test_templates_sao_os_da_clinica():
    from celeste.jobs import templates_texto as tt
    assert set(tt.TEMPLATES) == {"T1", "T2", "T3", "T4"}
    assert "solicitação de consulta, feita em {2}" in tt.TEMPLATES["T1"]["corpo"] and "me dá um oi" in tt.TEMPLATES["T2"]["corpo"]
    assert "duas formas" in tt.TEMPLATES["T3"]["corpo"] and "demonstrou interesse" in tt.TEMPLATES["T4"]["corpo"]
    assert tt.parametros("T1", "Ana", mes="junho") == ["Ana", "junho"] and tt.parametros("T2", "Ana") == [] and tt.parametros("T3", "Ana") == []
    assert "SAIR" not in tt.renderizar("T1", "Ana", mes="junho") and "feita em junho" in tt.renderizar("T1", "Ana", mes="junho")
    from celeste.jobs import disparos
    from datetime import datetime as _dt
    assert disparos._extras_template("T1", False, {"lead_created_at": _dt(2026, 6, 15)}) == {"mes": "junho"}
    assert tt.renderizar("T4", "Ana").startswith("Olá Ana😀")


def test_quem_respondeu_sai_da_esteira():
    for st in ("Em conversa", "Agendado", "Receiteiro", "Mora em outro País", "Não quer (opt-out)", "Encaminhado à recepção"):
        assert disparos.decidir(_lead(status_ia=st, passo=1, ultimo_template_em=AGORA - timedelta(days=30)), AGORA) is None
    assert disparos.decidir(_lead(opt_out=True), AGORA) is None
    assert disparos.decidir(_lead(elegivel=False), AGORA) is None


def test_recontato_por_objecao():
    caro = _lead(status_ia="Achou caro", passo=1, ultimo_template_em=AGORA - timedelta(days=31), ultima_msg_lead_em=AGORA - timedelta(days=29))
    assert disparos.decidir(caro, AGORA) is None          # 30 dias após a última msg do lead
    caro["ultima_msg_lead_em"] = AGORA - timedelta(days=30)
    assert disparos.decidir(caro, AGORA).template == "T1"   # "Achou caro" → tempo é cabelo
    data = _lead(status_ia="Vamos retornar na data solicitada", passo=1, ultimo_template_em=AGORA - timedelta(days=10), proximo_recontato_em="2026-10-13")
    assert disparos.decidir(data, AGORA).template == "T2"
    data["proximo_recontato_em"] = "2026-10-20"
    assert disparos.decidir(data, AGORA) is None


def test_horario_de_disparo():
    from zoneinfo import ZoneInfo
    sp = ZoneInfo("America/Sao_Paulo")
    assert disparos.dentro_do_horario(datetime(2026, 10, 13, 10, 0, tzinfo=sp))
    assert not disparos.dentro_do_horario(datetime(2026, 10, 13, 18, 30, tzinfo=sp))
    assert not disparos.dentro_do_horario(datetime(2026, 10, 17, 10, 0, tzinfo=sp))  # sábado


def test_lembretes_elegibilidade():
    from datetime import datetime, timedelta, timezone
    from celeste.jobs import lembretes
    agora = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)
    base = {"frente": "leads_perdidos", "aberta": True, "modo": "ia", "status": "Em conversa", "lembretes_enviados": 0,
            "ultima": {"direcao": "celeste", "tipo": "text", "em": agora - timedelta(hours=2)},
            "janela_24h_ate": agora + timedelta(hours=10), "ultima_msg_lead_em": agora - timedelta(hours=3),
            "primeira_msg_celeste_em": agora - timedelta(hours=4)}
    assert lembretes.elegivel(dict(base), agora)[0]
    assert not lembretes.elegivel(dict(base, ultima={"direcao": "lead", "em": agora - timedelta(hours=2)}), agora)[0]     # lead respondeu
    assert not lembretes.elegivel(dict(base, ultima={"direcao": "celeste", "tipo": "text", "em": agora - timedelta(minutes=90)}), agora)[0]  # < 2 h
    assert not lembretes.elegivel(dict(base, status="Agendado"), agora)[0]
    assert not lembretes.elegivel(dict(base, modo="humano"), agora)[0]
    assert not lembretes.elegivel(dict(base, lembretes_enviados=2), agora)[0]                          # máx. 2 por fio
    assert not lembretes.elegivel(dict(base, lembretes_enviados=1, ultimo_lembrete_em=agora - timedelta(hours=2)), agora)[0]   # < 3 h desde o 1º
    assert lembretes.elegivel(dict(base, lembretes_enviados=1, ultimo_lembrete_em=agora - timedelta(hours=4)), agora)[0]
    assert not lembretes.elegivel(dict(base, janela_24h_ate=agora - timedelta(hours=1)), agora)[0]     # fora da janela
    assert not lembretes.elegivel(dict(base, frente=None), agora)[0]
    assert not lembretes.elegivel(dict(base, ultima_msg_lead_em=None), agora)[0]                       # nunca respondeu
    assert not lembretes.elegivel(dict(base, primeira_msg_celeste_em=None), agora)[0]                  # Celeste nunca falou (só equipe)
    from zoneinfo import ZoneInfo
    sp = ZoneInfo("America/Sao_Paulo")
    assert lembretes.dentro_do_horario(datetime(2026, 10, 6, 14, 0, tzinfo=sp))
    assert not lembretes.dentro_do_horario(datetime(2026, 10, 6, 20, 0, tzinfo=sp))
    assert not lembretes.dentro_do_horario(datetime(2026, 10, 10, 10, 0, tzinfo=sp))   # sábado
