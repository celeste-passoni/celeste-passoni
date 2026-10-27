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
    # T1 (solicitação pendente) → +1 d T2 (segue pendente) → +3 d T3 (ainda pendente) → +7 d T4 (encerramento)
    d0 = disparos.decidir(_lead(), AGORA)
    assert d0 and d0.template == "T1" and d0.novo_passo == 1
    assert disparos.decidir(_lead(status_ia="Template enviado (1°)", passo=1, ultimo_template_em=AGORA - timedelta(hours=20)), AGORA) is None
    d2 = disparos.decidir(_lead(status_ia="Template enviado (1°)", passo=1, ultimo_template_em=AGORA - timedelta(days=1)), AGORA)
    assert d2 and d2.template == "T2" and d2.novo_passo == 2
    d3 = disparos.decidir(_lead(status_ia="Template enviado (2°)", passo=2, ultimo_template_em=AGORA - timedelta(days=3)), AGORA)
    assert d3 and d3.template == "T3" and d3.novo_passo == 3
    assert disparos.decidir(_lead(status_ia="Template enviado (2°)", passo=3, ultimo_template_em=AGORA - timedelta(days=6)), AGORA) is None
    d4 = disparos.decidir(_lead(status_ia="Template enviado (2°)", passo=3, ultimo_template_em=AGORA - timedelta(days=7)), AGORA)
    assert d4 and d4.template == "T4" and d4.novo_passo == 4 and d4.novo_ciclo == 1


def test_pausa_e_reinicio_da_esteira():
    # fim do 1º ciclo: pausa de 15 dias e recomeça no T1 (2º ciclo); fim do 2º ciclo: encerra
    fim = _lead(status_ia="Template enviado (1°)", passo=4, ciclos=1, ultimo_template_em=AGORA - timedelta(days=14))
    assert disparos.decidir(fim, AGORA) is None
    fim["ultimo_template_em"] = AGORA - timedelta(days=16)
    r = disparos.decidir(fim, AGORA)
    assert r and r.template == "T1" and r.novo_passo == 1 and r.novo_ciclo == 2
    fim2 = _lead(status_ia="Template enviado (1°)", passo=4, ciclos=2, ultimo_template_em=AGORA - timedelta(days=16))
    r2 = disparos.decidir(fim2, AGORA)
    assert r2 and r2.template is None and "encerrada" in r2.motivo


def test_templates_sao_os_da_clinica():
    from celeste.jobs import templates_texto as tt
    assert set(tt.TEMPLATES) == {"T1", "T2", "T3", "T4", "TR"}
    assert tt.TEMPLATES["TR"]["nome"] == "retorno_combinado" and tt.parametros("TR", "Ana") == ["Ana"] and "[botões" not in tt.renderizar("TR", "Ana")
    assert "solicitação de consulta, feita em {2}" in tt.TEMPLATES["T1"]["corpo"] and "segue pendente" in tt.TEMPLATES["T2"]["corpo"]
    assert tt.TEMPLATES["T2"]["botoes"] == ["Quero continuar", "Agora não"] and "SAIR" not in tt.renderizar("T2", "Ana")
    assert "ainda está pendente" in tt.TEMPLATES["T3"]["corpo"] and "vamos encerrar" in tt.TEMPLATES["T4"]["corpo"]
    assert tt.TEMPLATES["T4"]["botoes"] == ["Quero continuar", "Pode encerrar"] and tt.parametros("T4", "Ana") == ["Ana"]
    assert tt.parametros("T1", "Ana", mes="junho") == ["Ana", "junho"] and tt.parametros("T2", "Ana") == ["Ana"] and tt.parametros("T3", "Ana") == ["Ana"]
    assert "SAIR" not in tt.renderizar("T1", "Ana", mes="junho") and "feita em junho" in tt.renderizar("T1", "Ana", mes="junho")
    from celeste.jobs import disparos
    from datetime import datetime as _dt
    assert disparos._extras_template("T1", False, {"lead_created_at": _dt(2026, 6, 15)}) == {"mes": "junho"}
    assert tt.renderizar("T4", "Ana").startswith("Olá, Ana. Como não tivemos")


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
    assert disparos.decidir(data, AGORA) is None   # 27/10/2026: a esteira não trata mais esse status; é do job de retornos
    data["proximo_recontato_em"] = "2026-10-20"
    assert disparos.decidir(data, AGORA) is None


def test_horario_de_disparo():
    from zoneinfo import ZoneInfo
    sp = ZoneInfo("America/Sao_Paulo")
    assert disparos.dentro_do_horario(datetime(2026, 10, 13, 10, 0, tzinfo=sp))
    assert not disparos.dentro_do_horario(datetime(2026, 10, 13, 18, 30, tzinfo=sp))
    assert not disparos.dentro_do_horario(datetime(2026, 10, 17, 10, 0, tzinfo=sp))  # sábado


def test_rotinas_consulta_decidir_e_parametros():
    from zoneinfo import ZoneInfo
    from celeste.jobs import rotinas_consulta as rc
    F = ZoneInfo("America/Sao_Paulo")
    c = {"id_agendamento": 10, "id_paciente": 1, "paciente_nome": "Ana Souza", "profissional": "dra_luciana", "data": "2026-10-29", "hora": "14:00",
         "status": "Marcado", "agendado_em": datetime(2026, 10, 20, 15, 0, tzinfo=F), "rotinas": {}}
    assert rc.decidir(dict(c), datetime(2026, 10, 27, 10, 5, tzinfo=F)) == "C48"
    assert rc.decidir(dict(c), datetime(2026, 10, 27, 9, 0, tzinfo=F)) is None                      # antes das 10h
    assert rc.decidir(dict(c, rotinas={"C48_em": 1}), datetime(2026, 10, 27, 11, 0, tzinfo=F)) is None
    assert rc.decidir(dict(c), datetime(2026, 10, 28, 10, 0, tzinfo=F)) == "C24"
    assert rc.decidir(dict(c, rotinas={"confirmado_em": 1}), datetime(2026, 10, 28, 10, 0, tzinfo=F)) is None   # já confirmou
    assert rc.decidir(dict(c), datetime(2026, 10, 29, 7, 30, tzinfo=F)) == "CHOJ"
    assert rc.decidir(dict(c), datetime(2026, 10, 29, 14, 10, tzinfo=F)) is None                    # consulta já passou
    assert rc.decidir(dict(c, status="Desmarcado"), datetime(2026, 10, 27, 10, 5, tzinfo=F)) is None
    assert rc.decidir(dict(c, agendado_em=datetime(2026, 10, 27, 9, 0, tzinfo=F)), datetime(2026, 10, 27, 10, 5, tzinfo=F)) is None  # marcou hoje
    conv = {"status": "Agendado", "modo": "ia", "nome": "Ana Souza", "consultas": [c]}
    assert [cod for _, cod in rc.pendentes(conv, datetime(2026, 10, 27, 10, 5, tzinfo=F))] == ["C48"]
    assert rc.pendentes(dict(conv, status="Em conversa"), datetime(2026, 10, 27, 10, 5, tzinfo=F)) == []
    assert rc.parametros("C48", conv, c) == ["Ana", "quinta-feira, 29/10", "14h"]
    assert rc.parametros("CHOJ", conv, dict(c, hora="09:30")) == ["Ana", "9h30"]
    assert "quinta-feira, 29/10, às 14h" in rc.renderizar("C48", conv, c) and "[botões: Confirmar presença · Preciso remarcar]" in rc.renderizar("C48", conv, c)
    assert "HOJE às 14h" in rc.renderizar("CHOJ", conv, c)
    # conversa antiga (uma consulta só nos campos antigos) continua funcionando
    antiga = {"status": "Agendado", "modo": "ia", "nome": "Ana Souza", "id_agendamento_tisaude": 10, "agendado_em": c["agendado_em"],
              "agendamento": {"data": "2026-10-29", "hora": "14:00", "profissional": "dra_luciana"}}
    assert [cod for _, cod in rc.pendentes(antiga, datetime(2026, 10, 27, 10, 5, tzinfo=F))] == ["C48"]


def test_rotinas_consulta_pai_e_filho():
    from zoneinfo import ZoneInfo
    from celeste.jobs import rotinas_consulta as rc
    F = ZoneInfo("America/Sao_Paulo")
    antes = datetime(2026, 10, 20, 15, 0, tzinfo=F)
    pai = {"id_agendamento": 10, "id_paciente": 1, "paciente_nome": "Curti Lopes", "profissional": "dr_lucas", "data": "2026-10-29", "hora": "14:00",
           "status": "Marcado", "agendado_em": antes, "rotinas": {}}
    filho = {"id_agendamento": 11, "id_paciente": 2, "paciente_nome": "Pedro Lopes", "profissional": "dr_lucas", "data": "2026-10-30", "hora": "10:00",
             "status": "Marcado", "agendado_em": antes, "rotinas": {}}
    conv = {"status": "Agendado", "modo": "ia", "nome": "Curti", "consultas": [pai, filho]}
    # 28/10 às 10h: véspera do pai (C24) e 48 h do filho (C48), cada um com o seu lembrete
    pend = rc.pendentes(conv, datetime(2026, 10, 28, 10, 0, tzinfo=F))
    assert sorted((c["id_agendamento"], cod) for c, cod in pend) == [(10, "C24"), (11, "C48")]
    assert rc.parametros("C48", conv, filho) == ["Curti", "sexta-feira, 30/10 (Pedro)", "10h"]       # nome do filho junto da data
    assert rc.parametros("C24", conv, pai) == ["Curti", "quinta-feira, 29/10", "14h"]                # consulta do próprio lead: sem nome
    assert rc.parametros("CHOJ", conv, filho) == ["Curti", "10h (Pedro)"]


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


def test_agora_nao_recebe_t2_no_dia_seguinte():
    # tocou "Agora não" no T1 (status "Agora não") e não escreveu nada → T2 1 dia depois
    l = _lead(status_ia="Agora não", passo=1, ultimo_template_em=AGORA - timedelta(days=1, hours=1), ultima_msg_lead_em=AGORA - timedelta(hours=20))
    assert disparos.decidir(l, AGORA) is None                                  # ainda não passou 1 dia da última msg do lead
    l["ultima_msg_lead_em"] = AGORA - timedelta(days=1, minutes=5)
    r = disparos.decidir(l, AGORA)
    assert r and r.template == "T2"



def test_dt_hora_sem_fuso_e_sao_paulo():
    from zoneinfo import ZoneInfo
    d = disparos._dt("2026-10-27T11:30")
    assert d.hour == 11 and d.tzinfo == ZoneInfo("America/Sao_Paulo")
    lead = {"elegivel": True, "opt_out": False, "status_ia": "Vamos retornar na data solicitada", "proximo_recontato_em": "2026-10-27T11:30", "passo": 1}
    from celeste.jobs import retornos
    assert retornos.vencidos([("l1", lead)], datetime(2026, 10, 27, 11, 29, tzinfo=ZoneInfo("America/Sao_Paulo"))) == []
    assert retornos.vencidos([("l1", lead)], datetime(2026, 10, 27, 11, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))) == [("l1", lead)]
    # domingo 22h também vale (decisão da clínica: sempre na hora pedida)
    dom = dict(lead, proximo_recontato_em="2026-11-01T22:00")
    assert retornos.vencidos([("l2", dom)], datetime(2026, 11, 1, 22, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))) == [("l2", dom)]
    # só data = a partir da meia-noite local; opt-out e outro status ficam de fora; ordem = mais antigo primeiro
    so_data = dict(lead, proximo_recontato_em="2026-10-27")
    fora = [("x", dict(lead, opt_out=True)), ("y", dict(lead, status_ia="Em conversa"))]
    assert [i for i, _ in retornos.vencidos([("l3", so_data), ("l1", lead)] + fora, datetime(2026, 10, 27, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo")))] == ["l3", "l1"]
