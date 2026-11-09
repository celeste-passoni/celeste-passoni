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
    ex = base_leads.sql_excluidos_pela_clinica(config.parametros()["leads_perdidos"])
    assert "sistemaweb_perdidos" in ex and "'Não quer'" in ex


def _lead(**k):
    base = {"elegivel": True, "opt_out": False, "status_ia": "Não contatado", "passo": 0, "ultimo_template_em": None}
    base.update(k)
    return base


def test_esteira_segue_cadencia_da_atendente_de_referencia():
    # 06/11/2026 (clínica): T1 → +1 d T2 (vídeo) → +3 d T4 (encerramento); o T3 saiu da esteira
    d0 = disparos.decidir(_lead(), AGORA)
    assert d0 and d0.template == "T1" and d0.novo_passo == 1
    assert disparos.decidir(_lead(status_ia="Template enviado (1°)", passo=1, ultimo_template_em=AGORA - timedelta(hours=20)), AGORA) is None
    d2 = disparos.decidir(_lead(status_ia="Template enviado (1°)", passo=1, ultimo_template_em=AGORA - timedelta(days=1)), AGORA)
    assert d2 and d2.template == "T2" and d2.novo_passo == 2
    assert disparos.decidir(_lead(status_ia="Template enviado (2°)", passo=2, ultimo_template_em=AGORA - timedelta(days=2)), AGORA) is None
    d4 = disparos.decidir(_lead(status_ia="Template enviado (2°)", passo=2, ultimo_template_em=AGORA - timedelta(days=3)), AGORA)
    assert d4 and d4.template == "T4" and d4.novo_passo == 3 and d4.novo_ciclo == 1
    # quem já recebeu o T3 no modelo antigo (passo 3) está no fim da esteira: pausa, não recebe T4 de novo pela esteira
    assert disparos.decidir(_lead(status_ia="Template enviado (2°)", passo=3, ciclos=1, ultimo_template_em=AGORA - timedelta(days=7)), AGORA) is None


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
    assert set(tt.TEMPLATES) == {"T1", "T2", "T2r", "T3", "T4", "TR", "TL"}   # 09/11/2026: TL = retomada de conversa em aberto
    assert tt.TEMPLATES["TR"]["nome"] == "retorno_combinado" and tt.parametros("TR", "Ana") == ["Ana"] and "[botões" not in tt.renderizar("TR", "Ana")
    assert "cresce cerca de 3 cm em 3 meses" in tt.TEMPLATES["T1"]["corpo"] and "segue pendente" in tt.TEMPLATES["T2r"]["corpo"]
    assert tt.TEMPLATES["T2r"]["botoes"] == ["Quero continuar", "Agora não"] and "SAIR" not in tt.renderizar("T2", "Ana")
    assert "ainda está pendente" in tt.TEMPLATES["T3"]["corpo"] and "vamos encerrar" in tt.TEMPLATES["T4"]["corpo"]
    assert tt.TEMPLATES["T4"]["botoes"] == ["Sim, tenho interesse", "Encerrar solicitação"] and tt.parametros("T4", "Ana") == ["Ana"]
    assert tt.parametros("T1", "Ana") == ["Ana"] and tt.parametros("T2", "Ana") == ["Ana"] and tt.parametros("T3", "Ana") == ["Ana"]
    t1 = tt.renderizar("T1", "Ana")   # 28/10/2026: o histórico mostra a imagem e o texto como o lead viu
    assert t1.startswith("[imagem: foto da Dra. Luciana") and "Oi, Ana! Você sabia" in t1 and "SAIR" not in t1
    assert tt.TEMPLATES["T1"]["imagem"].startswith("https://storage.googleapis.com/") and "imagem" not in tt.TEMPLATES["T2"]
    assert tt.renderizar("T4", "Ana").startswith("Olá, Ana. Como não tivemos")


def test_template_com_imagem_no_cabecalho():
    from celeste.ferramentas import meta as m
    cli = m.Meta.__new__(m.Meta); enviados = {}
    cli._post = lambda caminho, corpo: (enviados.update(corpo) or {"messages": [{"id": "wamid-t"}]})
    assert cli.enviar_template("5511", "resgate_queda_3cm", ["Ana"], imagem_cabecalho="https://x/t1.jpg") == "wamid-t"
    comp = enviados["template"]["components"]
    assert comp[0] == {"type": "header", "parameters": [{"type": "image", "image": {"link": "https://x/t1.jpg"}}]}
    assert comp[1]["parameters"] == [{"type": "text", "text": "Ana"}]
    cli.enviar_template("5511", "resgate_solicitacao_segue_pendente", ["Ana"])
    assert [c["type"] for c in enviados["template"]["components"]] == ["body"]


def test_t2_so_para_quem_nao_respondeu_o_t1():
    from celeste.jobs import templates_texto as tt
    # 29/10/2026 (decisão da clínica): T2 = vídeo, só para quem não escreveu nada; status pode continuar "Template enviado (1°)"
    base = dict(status_ia="Template enviado (1°)", passo=1, ultimo_template_em=AGORA - timedelta(days=1))
    assert disparos.decidir(_lead(**base), AGORA).template == "T2"
    assert disparos.config.parametros()["disparos"]["templates"]["T2"] == "resgate_video_solicitacao_pendente_v3"   # 06/11/2026: opt-out no lugar do "Agora não" (a v2, 3 botões, virou MARKETING)
    assert disparos.decidir(_lead(**base, respondeu_em=AGORA - timedelta(hours=5)), AGORA) is None        # resposta automática conta
    assert disparos.decidir(_lead(**base, ultima_msg_lead_em=AGORA - timedelta(hours=5)), AGORA) is None
    assert disparos.decidir(_lead(**base, falha_entrega=131050), AGORA) is None    # parou de receber marketing
    assert disparos.decidir(_lead(**base, falha_entrega=131026), AGORA) is None    # número não recebe
    assert disparos.decidir(_lead(**base, falha_entrega=130472), AGORA).template == "T2"   # experimento da Meta: nunca viu o T1
    # quem respondeu e parou volta pelo T2 antigo (T2r), não pelo vídeo
    agora_nao = _lead(status_ia="Agora não", passo=1, ultimo_template_em=AGORA - timedelta(days=2), ultima_msg_lead_em=AGORA - timedelta(days=2))
    assert disparos.decidir(agora_nao, AGORA).template == "T2r"
    assert tt.renderizar("T2", "Ana").startswith("Olá, Ana. Sua solicitação de consulta na Passoni Clinic ainda está pendente.")
    assert "[botões: Quero ver o vídeo · Não tenho interesse]" in tt.renderizar("T2", "Ana")
    assert tt.METADADOS["T2"] ["sem_interesse"] == ["Não tenho interesse"] and tt.METADADOS["T2"]["com_interesse"] == ["Quero ver o vídeo"]
    assert any(h["nome"] == "resgate_video_solicitacao_pendente" and h["em_uso_ate"] == "2026-11-06" for h in tt.HISTORICO)   # a v1 fica no de-para do funil
    assert tt.TEMPLATES["T2"]["video_botao"] == "dra_luciana" and tt.parametros("T2", "Ana") == ["Ana"]


def test_completar_resposta_e_entrega():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    db = MagicMock()
    docs = {"conversas/c1": {"primeira_msg_lead_em": AGORA}, "status_entrega/w1": {"status": "failed", "erros": [{"code": 131050}]}}
    db.collection.side_effect = lambda col: SimpleNamespace(document=lambda i: SimpleNamespace(
        get=lambda: SimpleNamespace(to_dict=lambda: docs.get(f"{col}/{i}"))))
    lead = {"passo": 1, "status_ia": "Template enviado (1°)", "conversa_id": "c1", "templates_enviados": [{"wamid": "w1"}]}
    disparos._completar_resposta_e_entrega(db, lead)
    assert lead["respondeu_em"] == AGORA and lead["falha_entrega"] == 131050
    novo = {"passo": 0, "status_ia": "Não contatado"}
    disparos._completar_resposta_e_entrega(db, novo)
    assert "respondeu_em" not in novo


def test_quem_respondeu_sai_da_esteira():
    for st in ("Em conversa", "Agendado", "Receiteiro", "Mora em outro País", "Não quer (opt-out)", "Encaminhado à recepção", "Não é lead"):
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
    assert disparos.dentro_do_horario(datetime(2026, 10, 17, 10, 0, tzinfo=sp))      # sábado: desde 06/11/2026 a esteira roda todos os dias


def test_rotinas_consulta_decidir_e_parametros():
    from datetime import date
    from zoneinfo import ZoneInfo
    from celeste.jobs import rotinas_consulta as rc
    F = ZoneInfo("America/Sao_Paulo")
    base = {"status": "Agendado", "modo": "ia", "nome": "Ana Souza", "agendado_em": datetime(2026, 10, 20, 15, 0, tzinfo=F),
            "agendamento": {"data": "2026-10-29", "hora": "14:00", "profissional": "dra_luciana"}}
    assert rc.decidir(dict(base), datetime(2026, 10, 27, 10, 5, tzinfo=F)) == "C48"
    assert rc.decidir(dict(base), datetime(2026, 10, 27, 9, 0, tzinfo=F)) is None                      # antes das 10h
    assert rc.decidir(dict(base, rotinas_consulta={"C48_em": 1}), datetime(2026, 10, 27, 11, 0, tzinfo=F)) is None
    assert rc.decidir(dict(base, rotinas_consulta={"desligadas": True}), datetime(2026, 10, 27, 11, 0, tzinfo=F)) is None   # 06/11/2026: recepção já confirmou por fora
    assert rc.decidir(dict(base), datetime(2026, 10, 28, 10, 0, tzinfo=F)) == "C24"
    assert rc.decidir(dict(base, rotinas_consulta={"confirmado_em": 1}), datetime(2026, 10, 28, 10, 0, tzinfo=F)) is None   # já confirmou
    assert rc.decidir(dict(base), datetime(2026, 10, 29, 7, 30, tzinfo=F)) == "CHOJ"
    assert rc.decidir(dict(base), datetime(2026, 10, 29, 14, 10, tzinfo=F)) is None                    # consulta já passou
    assert rc.decidir(dict(base, status="Em conversa"), datetime(2026, 10, 27, 10, 5, tzinfo=F)) is None
    assert rc.decidir(dict(base, agendamento=dict(base["agendamento"], status="Cancelado")), datetime(2026, 10, 27, 10, 5, tzinfo=F)) is None
    assert rc.decidir(dict(base, agendado_em=datetime(2026, 10, 27, 9, 0, tzinfo=F)), datetime(2026, 10, 27, 10, 5, tzinfo=F)) is None  # marcou hoje
    assert rc.parametros("C48", base) == ["Ana", "quinta-feira, 29/10", "14h"]
    assert rc.parametros("CHOJ", dict(base, agendamento={"data": "2026-10-29", "hora": "09:30"})) == ["Ana", "9h30"]
    assert "quinta-feira, 29/10, às 14h" in rc.renderizar("C48", base) and "[botões: Confirmar presença · Preciso remarcar]" in rc.renderizar("C48", base)
    assert "HOJE às 14h" in rc.renderizar("CHOJ", base)


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
    assert lembretes.dentro_do_horario(datetime(2026, 10, 10, 10, 0, tzinfo=sp))       # sábado: desde 06/11/2026 os lembretes rodam todos os dias


def test_escolher_template_usa_reserva_quando_principal_nao_aprovado():
    """06/11/2026: T2 v3 (UTILITY) em análise; enquanto não aprovar, sai a v2 (MARKETING); sem checagem (None) sai o principal."""
    d = dict(disparos.config.parametros()["disparos"], templates_reserva={"T2": "resgate_video_solicitacao_pendente_v2"})
    assert disparos.escolher_template("T2", d, None) == d["templates"]["T2"]
    assert disparos.escolher_template("T2", d, {d["templates"]["T2"], "x"}) == d["templates"]["T2"]
    assert disparos.escolher_template("T2", d, {"resgate_video_solicitacao_pendente_v2"}) == "resgate_video_solicitacao_pendente_v2"
    assert disparos.escolher_template("T2", d, set()) is None
    assert disparos.escolher_template("T1", d, set()) is None and disparos.escolher_template("T1", d, {d["templates"]["T1"]}) == d["templates"]["T1"]
    from unittest.mock import MagicMock
    mt = MagicMock(); mt.templates.return_value = [{"name": "a", "status": "APPROVED"}, {"name": "b", "status": "PENDING"}]
    assert disparos.templates_aprovados(mt) == {"a"}
    mt.templates.side_effect = RuntimeError("x")
    assert disparos.templates_aprovados(mt) is None
    import celeste.jobs.templates_texto as tt
    assert any(h["nome"] == "resgate_video_solicitacao_pendente_v2" for h in tt.HISTORICO)   # a reserva também está no de-para do funil


def test_agora_nao_recebe_t2_no_dia_seguinte():
    # tocou "Agora não" no T1 (status "Agora não") e não escreveu nada → T2r 1 dia depois
    l = _lead(status_ia="Agora não", passo=1, ultimo_template_em=AGORA - timedelta(days=1, hours=1), ultima_msg_lead_em=AGORA - timedelta(hours=20))
    assert disparos.decidir(l, AGORA) is None                                  # ainda não passou 1 dia da última msg do lead
    l["ultima_msg_lead_em"] = AGORA - timedelta(days=1, minutes=5)
    r = disparos.decidir(l, AGORA)
    assert r and r.template == "T2r"   # 29/10/2026: o T2 da esteira (vídeo) é só para quem não respondeu



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
    # só data = às 10h local (02/11/2026; antes meia-noite); opt-out e outro status ficam de fora; ordem = mais antigo primeiro
    so_data = dict(lead, proximo_recontato_em="2026-10-27")
    assert disparos._dt_retorno("2026-10-27").hour == 10 and disparos._dt_retorno("2026-10-27T11:30").hour == 11
    assert retornos.vencidos([("l3", so_data)], datetime(2026, 10, 27, 9, 59, tzinfo=ZoneInfo("America/Sao_Paulo"))) == []
    fora = [("x", dict(lead, opt_out=True)), ("y", dict(lead, status_ia="Em conversa"))]
    assert [i for i, _ in retornos.vencidos([("l3", so_data), ("l1", lead)] + fora, datetime(2026, 10, 27, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo")))] == ["l3", "l1"]
    # número de teste recebe retorno combinado (02/11/2026): `vencidos` não filtra teste e `rodar` não usa mais e_teste
    import inspect
    assert retornos.vencidos([("t", dict(lead, teste=True))], datetime(2026, 10, 27, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo")))
    assert "e_teste" not in inspect.getsource(retornos.rodar)


def test_numero_de_teste_fora_de_todas_as_filas():
    # 27/10/2026: números de teste não participam de nenhuma fila nem esteira
    numeros = {"5511954884444"}
    assert disparos.e_teste({"celular": "5511954884444"}, numeros)            # lead pelo número
    assert disparos.e_teste({"contato": "5511954884444"}, numeros)            # conversa pelo número
    assert disparos.e_teste({"celular": "5511900000000", "teste": True}, numeros)
    assert not disparos.e_teste({"celular": "5511900000000"}, numeros)
    assert not disparos.e_teste({"contato": "5511900000000", "teste": False}, numeros)


def test_de_para_cobre_todos_os_templates():
    """05/11/2026: todo template em uso (e todo aposentado) tem etapa, versão e botões de interesse coerentes; chaves únicas."""
    from celeste.jobs import templates_texto as t
    linhas = t.de_para()
    chaves = [(l["codigo"], l["template"]) for l in linhas]
    assert len(chaves) == len(set(chaves))
    em_uso = {(l["codigo"], l["template"]) for l in linhas if l["em_uso"]}
    reservas = {(c, n) for c, n in (disparos.config.parametros()["disparos"].get("templates_reserva") or {}).items()}   # 06/11/2026: a reserva também conta como em uso
    assert em_uso == {(c, x["nome"]) for c, x in t.TEMPLATES.items() if not t.METADADOS[c].get("em_uso_ate")} | reservas   # cada template que a esteira usa está no de-para
    assert ("T3", "resgate_solicitacao_ainda_pendente") not in em_uso      # 06/11/2026: T3 fora da esteira
    assert set(t.METADADOS) == set(t.TEMPLATES)
    for l in linhas:
        botoes = set(l["botoes"].split(" | ")) if l["botoes"] else set()
        for campo in ("botoes_com_interesse", "botoes_sem_interesse"):
            assert set(filter(None, l[campo].split(" | "))) <= botoes, (l["template"], campo)
        assert l["etapa"] and l["versao"] >= 1 and l["em_uso_desde"]
        assert l["em_uso"] == (l["em_uso_ate"] is None)
    # uma versão por etapa em uso
    from collections import Counter
    assert max(Counter(l["codigo"] for l in linhas if l["em_uso"]).values()) == 1
    # a mesma etapa não repete número de versão
    assert len({(l["codigo"], l["versao"]) for l in linhas}) == len(linhas)


def test_publicar_funil_templates_grava_de_para_testes_e_view():
    from celeste.jobs import espelho

    class Job:
        def result(self): return self

    class BQ:
        def __init__(self): self.cargas, self.queries = {}, []
        def load_table_from_json(self, linhas, destino, job_config=None):
            self.cargas[destino.split(".")[-1]] = linhas; return Job()
        def query(self, sql): self.queries.append(sql); return Job()

    class Doc:
        def get(self): return self
        def to_dict(self): return {"numeros_teste": ["5511999405671", 5511980567117], "numeros_teste_escrita_real": ["5511999405671"]}

    class DB:
        def collection(self, nome): return self
        def document(self, nome): return Doc()

    bq = BQ()
    r = espelho.publicar_funil_templates(DB(), bq)
    assert r["templates_de_para"] == len(bq.cargas["templates_de_para"]) >= 6
    assert bq.cargas["numeros_teste"] == [{"contato": "5511980567117"}, {"contato": "5511999405671"}]
    assert len(bq.queries) == 2 and bq.queries[0].startswith("CREATE OR REPLACE VIEW `") and "vw_funil_templates" in bq.queries[0]
    assert bq.queries[1].startswith("CREATE OR REPLACE TABLE `") and ".funil_templates` AS SELECT * FROM `" in bq.queries[1]
    assert "automacoes.leads_disponibilizados_diario" in bq.queries[0] and "CELESTE MARIA" in bq.queries[0]


def test_espelho_limpa_nome_de_coluna_com_ponto():
    """05/11/2026: 'por_template.T4' (disparos_diarios) derrubava a carga do espelho no BigQuery."""
    from celeste.jobs import espelho

    class Ref:
        class parent:
            parent = None

    class Doc:
        id = "2026-11-05"; reference = Ref()
        def to_dict(self): return {"enviados": 3, "por_template.T4": 1, "por_template.T1": 2}

    assert espelho._linha(Doc()) == {"enviados": 3, "por_template_T4": 1, "por_template_T1": 2, "_id": "2026-11-05"}


def test_disparos_trava_uma_rodada_por_vez(monkeypatch):
    """08/11/2026: duas rodadas das 9h em paralelo (Scheduler repetiu o disparo) passaram do limite diário: 191 envios. Trava no Firestore."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from unittest.mock import MagicMock
    from celeste.jobs import disparos
    agora = _dt(2026, 11, 9, 12, 0, tzinfo=_tz.utc)
    assert disparos.trava_livre(None, agora) and disparos.trava_livre({"ate": None}, agora)
    assert not disparos.trava_livre({"ate": agora + _td(minutes=10)}, agora)
    assert disparos.trava_livre({"ate": agora - _td(minutes=1)}, agora)   # trava velha (processo morreu) expira sozinha
    # rodar(): com a trava ocupada, nada é enviado e nada é destravado por esta rodada
    db = MagicMock()
    db.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {"ativo": True, "limite_por_execucao": 100, "limite_diario": 100}
    monkeypatch.setattr(disparos.firestore, "Client", lambda project=None: db)
    monkeypatch.setattr(disparos, "dentro_do_horario", lambda agora=None: True)
    monkeypatch.setattr(disparos, "_travar", lambda db_, agora_: False)
    destravou = []
    monkeypatch.setattr(disparos, "_destravar", lambda db_: destravou.append(1))
    r = disparos.rodar()
    assert r["ignorado"] == "outra rodada de disparos em andamento" and r["enviados"] == 0 and not destravou
    # com a trava livre, a rodada destrava ao terminar (mesmo se falhar no meio)
    monkeypatch.setattr(disparos, "_travar", lambda db_, agora_: True)
    monkeypatch.setattr(disparos, "_rodar_travado", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        disparos.rodar()
    except RuntimeError:
        pass
    assert destravou == [1]


def test_disparos_relê_o_lead_antes_de_enviar():
    """08/11/2026: 53 leads receberam o T1 duas vezes porque a 2ª rodada usava um retrato velho da fila. Antes de enviar, relê o lead."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from celeste.jobs import disparos
    t0 = _dt(2026, 11, 8, 12, 0, tzinfo=_tz.utc)
    assert not disparos.ja_recebeu_depois({}, {})                                   # nunca recebeu nada
    assert not disparos.ja_recebeu_depois({"ultimo_template_em": t0}, {"ultimo_template_em": t0})   # nada mudou
    assert disparos.ja_recebeu_depois({"ultimo_template_em": t0}, {})               # recebeu o 1º template depois do retrato
    assert disparos.ja_recebeu_depois({"ultimo_template_em": t0 + _td(minutes=1)}, {"ultimo_template_em": t0})
    assert not disparos.ja_recebeu_depois(None, {"ultimo_template_em": t0})


def test_lembrete_por_template_para_conversa_em_aberto():
    """09/11/2026 (clínica): conversa parada > 2 dias fora da janela recebe o TL uma vez; sem resposta em 5 dias, fecha."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from celeste.jobs import lembretes, templates_texto as tt
    cfg = {"ativo": True, "codigo": "TL", "status_conversa": ["Em conversa"], "dias_sem_resposta": 2, "encerrar_apos_dias": 5, "status_encerrada": "Sem resposta (conversa)"}
    agora = _dt(2026, 11, 9, 15, 0, tzinfo=_tz.utc)
    base = {"frente": "leads_perdidos", "aberta": True, "modo": "ia", "status": "Em conversa",
            "ultima_msg_lead_em": agora - _td(days=4), "janela_24h_ate": agora - _td(days=3),
            "ultima": {"direcao": "celeste", "tipo": "text", "em": agora - _td(days=3)}}
    assert lembretes.elegivel_template(dict(base), agora, cfg) == (True, "ok")
    assert not lembretes.elegivel_template(dict(base, ultima={"direcao": "celeste", "tipo": "text", "em": agora - _td(days=1)}), agora, cfg)[0]   # ainda dentro do prazo
    assert not lembretes.elegivel_template(dict(base, janela_24h_ate=agora + _td(hours=2)), agora, cfg)[0]                                   # janela aberta: lembrete por texto
    assert not lembretes.elegivel_template(dict(base, status="Agora não"), agora, cfg)[0]
    assert not lembretes.elegivel_template(dict(base, lembrete_template_em=agora - _td(days=1)), agora, cfg)[0]                               # só um por fio
    assert not lembretes.elegivel_template(dict(base, ultima_msg_lead_em=None), agora, cfg)[0]                                               # nunca respondeu: esteira
    assert not lembretes.elegivel_template(dict(base, modo="humano"), agora, cfg)[0]
    assert not lembretes.elegivel_template(dict(base, ultima={"direcao": "template", "tipo": "template", "em": agora - _td(days=3)}), agora, cfg)[0]   # última foi template (T4): esteira já cuidou
    # encerramento
    enviado = dict(base, ultima_msg_lead_em=agora - _td(days=8), lembrete_template_em=agora - _td(days=6), ultima={"direcao": "template", "tipo": "template", "em": agora - _td(days=6)})
    assert lembretes.deve_encerrar(enviado, agora, cfg)
    assert not lembretes.deve_encerrar(dict(enviado, lembrete_template_em=agora - _td(days=2)), agora, cfg)
    assert not lembretes.deve_encerrar(dict(enviado, ultima_msg_lead_em=agora - _td(days=1)), agora, cfg)   # respondeu depois do template
    assert not lembretes.deve_encerrar(dict(base), agora, cfg)
    assert "Sem resposta (conversa)" in lembretes.STATUS_FINAIS
    # template e de-para
    assert tt.TEMPLATES["TL"]["nome"] == "retomada_conversa_em_aberto" and tt.TEMPLATES["TL"]["botoes"] == ["Sim, vamos continuar", "Não tenho interesse"]
    assert tt.METADADOS["TL"]["categoria"] == "UTILITY" and tt.ETAPAS["TL"][0] == "Retomada de conversa"
    assert tt.parametros("TL", "Ana") == ["Ana"] and "Ana" in tt.renderizar("TL", "Ana")
    assert "Não tenho interesse" in disparos.config.parametros()["t1_botoes"]["sair_outros_rotulos"]   # botão de saída já é opt-out
    assert lembretes.primeiro_nome({"nome": "maria da silva"}) == "Maria" and lembretes.primeiro_nome({}) == ""
    assert disparos.config.parametros()["lembretes"]["por_template"]["ativo"] is False   # 09/11/2026: liga depois da aprovação da Meta e do OK da clínica
