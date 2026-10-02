# -*- coding: utf-8 -*-
"""Testes do orquestrador sem rede: prompt em camadas, separação de balões, ciclo de ferramentas com Claude simulado."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import pytest

from celeste.comum import config
from celeste.orquestrador import ferramentas_ia, motor, prompt


# ------------------------------------------------------------------ prompt
def test_camadas_estaveis_renderiza_sem_placeholders_criticos():
    s = prompt.camadas_estaveis("leads_perdidos")
    assert "Celeste" in s
    assert "5511916069009" in s  # link da recepção renderizado
    assert "{{ia.nome_atendente}}" not in s
    assert "PARÂMETROS DA CLÍNICA" in s and "INSTRUÇÃO DA FRENTE" in s


def test_renderizar_lista_vira_yaml():
    out = prompt.renderizar("x {{ia.encaminhar_recepcao_quando}} y {{nao.existe}}", config.parametros())
    assert "lead já é paciente" in out and "{{nao.existe}}" in out


def test_contexto_lead_so_campos_presentes():
    c = prompt.contexto_lead({"nome": "Ana", "contato": "5511", "frente": "leads_perdidos"})
    assert "Nome: Ana" in c and "Objeção" not in c


# ------------------------------------------------------------------ balões
@pytest.mark.parametrize("texto,esperado", [
    ("Oi!\n---\nTudo bem?", ["Oi!", "Tudo bem?"]),
    ("---\nSó um", ["Só um"]),
    ("Sem separador", ["Sem separador"]),
    ("", []),
])
def test_separar_baloes(texto, esperado):
    assert motor.separar_baloes(texto) == esperado


def test_delay_humano_dentro_dos_limites():
    for _ in range(200):
        assert 30 <= motor.delay_humano() <= 180
        assert 120 <= motor.delay_humano(fora_horario=True) <= 900


# ------------------------------------------------------------------ ferramentas
def _ctx(conv=None, ts=None):
    return ferramentas_ia.Contexto(conversa=conv or {"id": "c1", "frente": "leads_perdidos"}, telefone="5511999990000", tisaude=ts or MagicMock(),
                                   viacep=lambda cep: {"endereco": "R", "bairro": "B", "cidade": "C", "uf": "SP"} if cep == "01001000" else {},
                                   enviar_video=lambda v: "wamid-v", avisar_recepcao=MagicMock(),
                                   atualizar=lambda campos: None)


def test_agendar_recusa_horario_nao_oferecido():
    saida, erro = ferramentas_ia.executar("agendar_consulta", {"id_paciente": 1, "profissional": "dr_lucas", "data": "2026-10-13", "hora": "10:00"}, _ctx())
    assert erro and "buscar_horarios" in saida


def test_buscar_horarios_e_agendar_ok():
    ts = MagicMock()
    ts.buscar_horarios.return_value = [{"data": "2026-10-13", "hora": "10:00"}]
    ts.agendar_consulta.return_value = {"id": 42, "status": 0}
    conv = {"id": "c1", "frente": "leads_perdidos"}
    ctx = _ctx(conv, ts)
    ctx.atualizar = lambda campos: conv.update(campos)
    ferramentas_ia.executar("buscar_horarios", {"profissional": "dr_lucas", "a_partir_de": "", "dias": 14}, ctx)
    saida, erro = ferramentas_ia.executar("agendar_consulta", {"id_paciente": 1, "profissional": "dr_lucas", "data": "2026-10-13", "hora": "10:00"}, ctx)
    assert not erro and '"id_agendamento": 42' in saida and conv["status"] == "Agendado"
    assert "Celeste" in ts.agendar_consulta.call_args.kwargs["observacoes"]


def test_criar_paciente_exige_responsavel_para_menor():
    e = {"nome": "Jo", "cpf": "1", "nascimento": "01/01/2015", "sexo": "Feminino", "email": "a@b", "como_conheceu": "GOOGLE",
         "cep": "01001000", "numero": "1", "complemento": "", "responsavel": "", "parentesco_responsavel": "", "cpf_responsavel": ""}
    saida, erro = ferramentas_ia.executar("criar_paciente", e, _ctx())
    assert erro and "responsável" in saida


def test_criar_paciente_cep_invalido():
    e = {"nome": "Jo", "cpf": "1", "nascimento": "01/01/1990", "sexo": "Feminino", "email": "a@b", "como_conheceu": "GOOGLE",
         "cep": "00000", "numero": "1", "complemento": "", "responsavel": "", "parentesco_responsavel": "", "cpf_responsavel": ""}
    saida, erro = ferramentas_ia.executar("criar_paciente", e, _ctx())
    assert erro and "CEP" in saida


def test_video_nao_repete():
    conv = {"id": "c1"}
    ctx = _ctx(conv)
    ctx.atualizar = lambda campos: conv.update(campos)
    s1, _ = ferramentas_ia.executar("enviar_video", {"video": "institucional", "reenviar": False}, ctx)
    s2, _ = ferramentas_ia.executar("enviar_video", {"video": "institucional", "reenviar": False}, ctx)
    s3, _ = ferramentas_ia.executar("enviar_video", {"video": "institucional", "reenviar": True}, ctx)
    assert '"ok": true' in s1 and "já enviado" in s2 and '"ok": true' in s3


def test_encaminhar_encerra_e_avisa():
    ctx = _ctx()
    ferramentas_ia.executar("encaminhar_recepcao", {"motivo": "assunto_clinico", "resumo": "quer receita"}, ctx)
    assert ctx.encerrar and ctx.avisar_recepcao.called


def test_schemas_estritos():
    for f in ferramentas_ia.FERRAMENTAS:
        assert f["strict"] is True
        assert f["input_schema"]["additionalProperties"] is False
        assert set(f["input_schema"]["required"]) == set(f["input_schema"]["properties"])


# ------------------------------------------------------------------ motor com Claude simulado
def _uso(**k):
    base = {"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    base.update(k)
    return SimpleNamespace(**base)


def _resp(stop, content, modelo="claude-opus-5", uso=None):
    return SimpleNamespace(stop_reason=stop, content=content, model=modelo, usage=uso or _uso())


def test_motor_ciclo_de_ferramenta_e_custo():
    cliente = MagicMock()
    tool_use = SimpleNamespace(type="tool_use", id="tu1", name="buscar_horarios", input={"profissional": "dr_lucas", "a_partir_de": "", "dias": 7})
    cliente.beta.messages.create.side_effect = [
        _resp("tool_use", [tool_use]),
        _resp("end_turn", [SimpleNamespace(type="text", text="Tenho terça 10h\n---\nTe serve?")], uso=_uso(cache_read_input_tokens=20000)),
    ]
    ts = MagicMock(); ts.buscar_horarios.return_value = [{"data": "2026-10-13", "hora": "10:00"}]
    m = motor.Motor(cliente=cliente)
    res = m.responder("leads_perdidos", {"id": "c1", "contato": "55", "nome": "Ana"}, [{"role": "user", "content": "oi"}], _ctx(ts=ts))
    assert res.baloes == ["Tenho terça 10h", "Te serve?"]
    assert res.chamadas == 2 and res.ferramentas[0]["nome"] == "buscar_horarios"
    # custo: 2×(1000 in ×5 + 100 out ×25)/1M + 20000 cache ×0.5/1M
    assert abs(res.custo_usd - (2 * (1000 * 5 + 100 * 25) / 1e6 + 20000 * 0.5 / 1e6)) < 1e-9
    # contexto do lead foi injetado na 1ª mensagem; system tem cache_control
    kwargs = cliente.beta.messages.create.call_args_list[0].kwargs
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "Nome: Ana" in kwargs["messages"][0]["content"]
    assert kwargs["model"] == "claude-opus-5"


def test_motor_fallback_para_sonnet():
    cliente = MagicMock()
    req = MagicMock()
    cliente.beta.messages.create.side_effect = [
        anthropic.InternalServerError("boom", response=MagicMock(status_code=500, headers={}), body=None),
        _resp("end_turn", [SimpleNamespace(type="text", text="Oi!")], modelo="claude-sonnet-5"),
    ]
    res = motor.Motor(cliente=cliente).responder("leads_perdidos", {"id": "c1"}, [{"role": "user", "content": "oi"}], _ctx())
    assert res.modelo == "claude-sonnet-5" and res.baloes == ["Oi!"]
    assert cliente.beta.messages.create.call_args_list[1].kwargs["model"] == "claude-sonnet-5"


def test_motor_refusal():
    cliente = MagicMock()
    cliente.beta.messages.create.return_value = _resp("refusal", [])
    res = motor.Motor(cliente=cliente).responder("leads_perdidos", {"id": "c1"}, [{"role": "user", "content": "oi"}], _ctx())
    assert res.refusal and res.baloes == []


def test_motor_preserva_texto_antes_da_ferramenta():
    cliente = MagicMock()
    tool_use = SimpleNamespace(type="tool_use", id="tu1", name="registrar_opt_out", input={"motivo": "pediu"})
    cliente.beta.messages.create.side_effect = [
        _resp("tool_use", [SimpleNamespace(type="text", text="Tudo certo, não mando mais."), tool_use]),
        _resp("end_turn", [SimpleNamespace(type="text", text="Obrigada!")]),
    ]
    res = motor.Motor(cliente=cliente).responder("leads_perdidos", {"id": "c1"}, [{"role": "user", "content": "SAIR"}], _ctx())
    assert res.baloes == ["Tudo certo, não mando mais.", "Obrigada!"]


def test_formato_saida_tem_data_atual():
    from datetime import datetime
    s = prompt.formato_saida(datetime(2026, 10, 13, 9, 5))
    assert "terça-feira, 13/10/2026 09:05" in s


def test_status_sem_data_vira_ira_retornar():
    conv = {"id": "c1"}
    ctx = _ctx(conv); ctx.atualizar = lambda campos: conv.update(campos)
    ferramentas_ia.executar("atualizar_status", {"status": "Vamos retornar na data solicitada", "data_retorno": ""}, ctx)
    assert conv["status"] == "Irá nos retornar"
    ferramentas_ia.executar("atualizar_status", {"status": "Vamos retornar na data solicitada", "data_retorno": "2026-11-03"}, ctx)
    assert conv["status"] == "Vamos retornar na data solicitada" and conv["proximo_recontato_em"] == "2026-11-03"


def test_botao_url_payload():
    from celeste.ferramentas import meta as m
    cliente = m.Meta(session=MagicMock())
    cliente._post = MagicMock(return_value={"messages": [{"id": "wamid.x"}]})
    wamid = cliente.enviar_botao_url("5511", "Toque abaixo", "Falar com Recepção", "https://wa.me/5511916069009")
    corpo = cliente._post.call_args.args[1]
    assert wamid == "wamid.x" and corpo["type"] == "interactive" and corpo["interactive"]["type"] == "cta_url"
    assert corpo["interactive"]["action"]["parameters"] == {"display_text": "Falar com Recepção", "url": "https://wa.me/5511916069009"}


def test_encaminhar_nao_devolve_link():
    ctx = _ctx()
    saida, erro = ferramentas_ia.executar("encaminhar_recepcao", {"motivo": "pediu_pessoa", "resumo": "x"}, ctx)
    assert not erro and "wa.me" not in saida and "Falar com Recepção" in prompt.formato_saida()


def test_modo_teste_gate(monkeypatch):
    import sys
    import google.cloud.firestore as fs
    monkeypatch.setattr(fs, "Client", lambda **k: None)   # o módulo cria um cliente Firestore ao importar
    sys.modules.pop("celeste.orquestrador.app", None)
    from celeste.orquestrador import app as orq
    class Doc:
        def __init__(self, d): self._d = d
        def to_dict(self): return self._d
    class Ref:
        def __init__(self, d, exists=True): self._d, self.exists = d, exists
        def get(self): return self
        def to_dict(self): return self._d
    class DB:
        def __init__(self, cfg, leads): self.cfg, self.leads = cfg, leads
        def collection(self, nome):
            db = self
            class Col:
                def document(self, id_):
                    if nome == "config": return Ref(db.cfg)
                    return Ref({}, exists=id_ in db.leads)
            return Col()
    monkeypatch.setattr(orq, "db", DB({"modo": "teste", "numeros_teste": ["5511999990000"]}, {"5511555550000"}))
    assert orq._pode_responder("5511999990000") and not orq._pode_responder("5511555550000") and not orq._pode_responder("5511777770000")
    monkeypatch.setattr(orq, "db", DB({"modo": "producao", "numeros_teste": ["5511999990000"]}, {"5511555550000"}))
    assert orq._pode_responder("5511555550000") and orq._pode_responder("5511999990000") and not orq._pode_responder("5511777770000")
    monkeypatch.setattr(orq, "db", DB({"modo": "aberto"}, set()))
    assert orq._pode_responder("5511777770000")


def test_tisaude_simulado_nao_grava():
    from datetime import date
    from celeste.ferramentas.tisaude_simulado import TiSaudeSimulado
    ts = TiSaudeSimulado(session=MagicMock())
    ts._req = MagicMock(side_effect=AssertionError("escrita real não pode acontecer"))
    p = ts.criar_paciente({"nome": "TESTE", "cpf": "1"})
    a = ts.agendar_consulta(id_paciente=p["id"], profissional_id="dr_lucas", data=date(2026, 10, 13), hora="10:00", observacoes="x")
    assert p["simulado"] and a["simulado"] and a["id"] >= 900000 and len(ts.simulados) == 2
    assert "cpf" not in ts.simulados[0]["dados"]


def test_contexto_espontaneo():
    c = prompt.contexto_lead({"nome": "Ana", "contato": "5511", "frente": "leads_perdidos", "origem": "espontaneo"})
    assert "espontâneo" in c and "nenhum template" in c and "Origem: espontaneo" not in c
