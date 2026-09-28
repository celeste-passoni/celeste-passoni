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
    assert "'Não quer'" in sql and "'Número Inválido'" in sql and "2026-01-01" in sql and "ROW_NUMBER()" in sql


def _lead(**k):
    base = {"elegivel": True, "opt_out": False, "status_ia": "Não contatado", "passo": 0, "ultimo_template_em": None}
    base.update(k)
    return base


def test_esteira_ciclo_1():
    d0 = disparos.decidir(_lead(), AGORA)
    assert d0 and d0.template == "T1" and d0.novo_passo == 1
    # T2 só depois de 3 dias
    assert disparos.decidir(_lead(status_ia="Template enviado (1°)", passo=1, ultimo_template_em=AGORA - timedelta(days=2)), AGORA) is None
    d2 = disparos.decidir(_lead(status_ia="Template enviado (1°)", passo=1, ultimo_template_em=AGORA - timedelta(days=3)), AGORA)
    assert d2 and d2.template == "T2"
    d3 = disparos.decidir(_lead(status_ia="Template enviado (1°)", passo=2, ultimo_template_em=AGORA - timedelta(days=7)), AGORA)
    assert d3 and d3.template == "T3" and d3.novo_passo == 3


def test_ciclo_2_e_pausa_longa():
    # após T3 (passo 3) espera 40 dias para T4
    assert disparos.decidir(_lead(status_ia="Template enviado (2°)", passo=3, ultimo_template_em=AGORA - timedelta(days=39)), AGORA) is None
    d4 = disparos.decidir(_lead(status_ia="Template enviado (2°)", passo=3, ultimo_template_em=AGORA - timedelta(days=40)), AGORA)
    assert d4 and d4.template == "T4"
    # T5 exige tarde livre hoje
    l5 = _lead(status_ia="Template enviado (1°)", passo=4, ultimo_template_em=AGORA - timedelta(days=7))
    assert disparos.decidir(l5, AGORA, tarde_livre_hoje=False) is None
    assert disparos.decidir(l5, AGORA, tarde_livre_hoje=True).template == "T5"
    # fim da esteira: pausa de 90 dias e volta ao T4
    fim = _lead(status_ia="Template enviado (2°)", passo=5, ultimo_template_em=AGORA - timedelta(days=89))
    assert disparos.decidir(fim, AGORA) is None
    fim["ultimo_template_em"] = AGORA - timedelta(days=91)
    r = disparos.decidir(fim, AGORA)
    assert r and r.template == "T4" and r.novo_passo == 4


def test_quem_respondeu_sai_da_esteira():
    for st in ("Em conversa", "Agendado", "Receiteiro", "Mora em outro País", "Não quer (opt-out)", "Encaminhado à recepção"):
        assert disparos.decidir(_lead(status_ia=st, passo=1, ultimo_template_em=AGORA - timedelta(days=30)), AGORA) is None
    assert disparos.decidir(_lead(opt_out=True), AGORA) is None
    assert disparos.decidir(_lead(elegivel=False), AGORA) is None


def test_recontato_por_objecao():
    caro = _lead(status_ia="Achou caro", passo=1, ultimo_template_em=AGORA - timedelta(days=31), ultima_msg_lead_em=AGORA - timedelta(days=29))
    assert disparos.decidir(caro, AGORA) is None          # 30 dias após a última msg do lead
    caro["ultima_msg_lead_em"] = AGORA - timedelta(days=30)
    assert disparos.decidir(caro, AGORA).template == "T3"
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
