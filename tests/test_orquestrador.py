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
    assert "5511916069009" not in s  # a Celeste nunca escreve o número da recepção (vai por botão)
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
        assert 2 <= motor.delay_humano() <= 9
        assert 2 <= motor.delay_humano(fora_horario=True) <= 9


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
    e = {"nome": "Joana Silva", "cpf": "1", "nascimento": "01/01/2015", "sexo": "Feminino", "email": "a@b", "como_conheceu": "GOOGLE",
         "cep": "01001000", "numero": "1", "complemento": "", "responsavel": "", "parentesco_responsavel": "", "cpf_responsavel": ""}
    saida, erro = ferramentas_ia.executar("criar_paciente", e, _ctx())
    assert erro and "responsável" in saida


def test_criar_paciente_cep_invalido():
    e = {"nome": "Joana Silva", "cpf": "1", "nascimento": "01/01/1990", "sexo": "Feminino", "email": "a@b", "como_conheceu": "GOOGLE",
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


def _resp(stop, content, modelo="claude-opus-5-5", uso=None):
    return SimpleNamespace(stop_reason=stop, content=content, model=modelo, usage=uso or _uso())


def test_motor_ciclo_de_ferramenta_e_custo(monkeypatch):
    monkeypatch.setattr(motor.portao, "ativo", lambda: False)   # custo medido sem o revisor
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
    # custo pelo preço do modelo da resposta (opus 5.5 no mock): 2×(1000 in + 100 out) + 20000 de cache lido
    pr = config.parametros()["modelos"]["precos_usd_por_milhao"]["claude-opus-5-5"]
    assert abs(res.custo_usd - (2 * (1000 * pr["entrada"] + 100 * pr["saida"]) / 1e6 + 20000 * pr["cache_leitura"] / 1e6)) < 1e-9
    # contexto do lead foi injetado na 1ª mensagem; system tem cache_control
    kwargs = cliente.beta.messages.create.call_args_list[0].kwargs
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "Nome: Ana" in kwargs["messages"][0]["content"]
    assert kwargs["model"] == config.parametros()["modelos"]["conversa"]


def test_motor_fallback_para_sonnet():
    cliente = MagicMock()
    req = MagicMock()
    cliente.beta.messages.create.side_effect = [
        anthropic.InternalServerError("boom", response=MagicMock(status_code=500, headers={}), body=None),
        _resp("end_turn", [SimpleNamespace(type="text", text="Oi!")], modelo="claude-sonnet-5-5"),
    ]
    res = motor.Motor(cliente=cliente).responder("leads_perdidos", {"id": "c1"}, [{"role": "user", "content": "oi"}], _ctx())
    assert res.modelo == config.parametros()["modelos"]["conversa_fallback"] and res.baloes == ["Oi!"]
    assert cliente.beta.messages.create.call_args_list[1].kwargs["model"] == config.parametros()["modelos"]["conversa_fallback"]


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
        def __init__(self, cfg, leads, nunca_disparados=()): self.cfg, self.leads, self.nunca_disparados = cfg, leads, set(nunca_disparados)
        def collection(self, nome):
            db = self
            class Col:
                def document(self, id_):
                    if nome == "config": return Ref(db.cfg)
                    return Ref({"passo": 1 if id_ in db.leads else 0}, exists=id_ in db.leads or id_ in db.nunca_disparados)
            return Col()
    monkeypatch.setattr(orq, "db", DB({"modo": "teste", "numeros_teste": ["5511999990000"]}, {"5511555550000"}))
    assert orq._pode_responder("5511999990000") and not orq._pode_responder("5511555550000") and not orq._pode_responder("5511777770000")
    monkeypatch.setattr(orq, "db", DB({"modo": "producao", "numeros_teste": ["5511999990000"]}, {"5511555550000"}, nunca_disparados={"5511666660000"}))
    assert orq._pode_responder("5511555550000") and orq._pode_responder("5511999990000") and not orq._pode_responder("5511777770000")
    assert not orq._pode_responder("5511666660000")   # 25/10/2026: lead da base que ainda não recebeu template não é atendido
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


@pytest.mark.parametrize("entrada,esperado", [
    ("posso te enviar um vídeo — assim você conhece", "posso te enviar um vídeo, assim você conhece"),
    ("não trabalhamos com descontos – os valores são tabelados", "não trabalhamos com descontos, os valores são tabelados"),
    ("*Dra. Luciana – R$ 1.200,00*", "*Dra. Luciana, R$ 1.200,00*"),
    ("- primeiro item\n- segundo item", "- primeiro item\n- segundo item"),
    ("Oi! 😊 Tudo bem?", "Oi! 😊 Tudo bem?"),
])
def test_limpar_pontuacao(entrada, esperado):
    assert motor.limpar_pontuacao(entrada) == esperado


def test_separar_baloes_descarta_so_traco():
    assert motor.separar_baloes("Oi!\n---\n—\n---\nTudo bem?") == ["Oi!", "Tudo bem?"]


def test_motor_modelo_forcado_haiku_sem_thinking():
    cliente = MagicMock()
    cliente.beta.messages.create.return_value = _resp("end_turn", [SimpleNamespace(type="text", text="Oi, ainda por aí?")], modelo="claude-haiku-4-5")
    res = motor.Motor(cliente=cliente).responder("leads_perdidos", {"id": "c1"}, [{"role": "user", "content": "oi"}], _ctx(), modelo="claude-haiku-4-5")
    kwargs = cliente.beta.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5" and "thinking" not in kwargs and res.modelo == "claude-haiku-4-5"


def test_contexto_paciente_pre_verificado():
    c = prompt.contexto_lead({"nome": "Ana", "contato": "5511", "id_paciente_tisaude": 6436, "paciente_tisaude_nome": "ANA"})
    assert "JÁ É PACIENTE" in c and "6436" in c
    c2 = prompt.contexto_lead({"nome": "Ana", "contato": "5511", "paciente_tisaude_ausente": True})
    assert "NÃO cadastrado" in c2


def test_sinalizar_revisao():
    conv = {"id": "c1"}
    ctx = _ctx(conv); ctx.atualizar = lambda campos: conv.update(campos)
    saida, erro = ferramentas_ia.executar("sinalizar_revisao", {"duvida": "tem algum preparo?"}, ctx)
    assert not erro and conv["revisar"] and conv["duvidas_pendentes"] == ["tem algum preparo?"]


def test_base_tem_preparo_e_prompt_tem_regra():
    from celeste.comum import config
    kb = (config.RAIZ / "knowledge" / "01-base-conhecimento-clinica.md").read_text(encoding="utf-8")
    pr = (config.RAIZ / "prompts" / "leads-perdidos-v0.md").read_text(encoding="utf-8")
    assert "cabelos limpos e secos" in kb and "Não inventa informação" in pr and "sinalizar_revisao" in pr


def test_contexto_numero_de_outra_pessoa():
    c = prompt.contexto_lead({"nome": "Tati", "contato": "5511", "id_paciente_tisaude": 4942, "paciente_tisaude_nome": "ARTHUR SPERRY CEZAR FILHO"})
    assert "outra pessoa" in c and "Arthur" in c and "confirme" in c
    c2 = prompt.contexto_lead({"nome": "Arthur Cezar", "contato": "5511", "id_paciente_tisaude": 4942, "paciente_tisaude_nome": "ARTHUR SPERRY CEZAR FILHO"})
    assert "JÁ É PACIENTE" in c2


def test_cancelar_exige_motivo_solucao_e_confirmacao():
    ts = MagicMock(); conv = {"id": "c1"}
    ctx = _ctx(conv, ts); ctx.atualizar = lambda campos: conv.update(campos)
    base = {"id_agendamento": 1, "motivo_do_lead": "", "solucao_oferecida": "", "lead_confirmou_apos_solucao": False}
    s, erro = ferramentas_ia.executar("cancelar", dict(base), ctx); assert erro and "solução" in s and not ts.cancelar.called   # 26/10: motivo opcional
    s, erro = ferramentas_ia.executar("cancelar", dict(base, motivo_do_lead="vai viajar"), ctx); assert erro and "solução" in s
    s, erro = ferramentas_ia.executar("cancelar", dict(base, motivo_do_lead="vai viajar", solucao_oferecida="remarcar sexta 10h"), ctx); assert erro and "confirmou" in s
    s, erro = ferramentas_ia.executar("cancelar", dict(base, motivo_do_lead="vai viajar", solucao_oferecida="remarcar sexta 10h", lead_confirmou_apos_solucao=True), ctx)
    assert not erro and ts.cancelar.called and conv["motivo_cancelamento"] == "vai viajar"


# ------------------------------------------------------------------ identificação do paciente (CPF manda)
def _ts_fake(por_celular, por_cpf):
    from celeste.ferramentas import tisaude
    ts = tisaude.TiSaude.__new__(tisaude.TiSaude)
    def req(metodo, caminho, *, params=None, **kw):
        if "celular" in (params or {}):
            return {"data": por_celular}
        return {"data": [p for p in por_cpf if params.get("busca") in (p["cpf"], p["nome"])]}
    ts._req = req
    return ts


def test_buscar_paciente_cpf_decide_mesmo_com_telefone_de_outra_pessoa():
    pai = {"id": 4942, "nome": "ARTHUR SPERRY CEZAR FILHO", "cpf": "11111111111"}
    tati = {"id": 2301, "nome": "TATIANA FREITAS", "cpf": "22222222222"}
    ts = _ts_fake([pai, tati], [pai, tati])
    assert ts.buscar_paciente(celular="5511980567117", cpf="222.222.222-22")["id"] == 2301
    assert ts.buscar_paciente(celular="5511980567117") is None                      # ambíguo sem nome
    assert ts.buscar_paciente(celular="5511980567117", nome="Tatiana Freitas")["id"] == 2301   # desempate pelo nome
    assert ts.buscar_paciente(cpf="33333333333") is None                            # CPF não cadastrado não cai para o telefone
    assert len(ts.listar_por_celular("5511980567117")) == 2


def test_ferramenta_buscar_paciente_por_cpf_confirma_identidade():
    ts = MagicMock(); ts.buscar_paciente.return_value = {"id": 2301, "nome": "TATIANA FREITAS"}
    conv = {"id": "c1", "id_paciente_tisaude": 4942, "paciente_tisaude_nome": "ARTHUR SPERRY CEZAR FILHO"}
    ctx = _ctx(conv, ts); ctx.atualizar = lambda campos: conv.update(campos)
    saida, erro = ferramentas_ia.executar("buscar_paciente", {"cpf": "698.005.450-34", "nome_completo": ""}, ctx)
    assert not erro and '"id": 2301' in saida
    assert ts.buscar_paciente.call_args.kwargs == {"cpf": "69800545034"}            # só CPF, nunca o telefone junto
    assert conv["id_paciente_tisaude"] == 2301 and conv["identidade_confirmada"] and conv["paciente_tisaude_nome"] == "TATIANA FREITAS"
    ts.buscar_paciente.return_value = None
    saida, erro = ferramentas_ia.executar("buscar_paciente", {"cpf": "69800545034", "nome_completo": ""}, ctx)
    assert not erro and '"encontrado": false' in saida and "criar_paciente" in saida
    saida, erro = ferramentas_ia.executar("buscar_paciente", {"cpf": "123", "nome_completo": ""}, ctx)
    assert erro and "11 dígitos" in saida


def test_criar_paciente_nao_reaproveita_id_de_outra_pessoa():
    ts = MagicMock(); ts.buscar_paciente.return_value = None; ts.criar_paciente.return_value = {"id": 777}
    conv = {"id": "c1", "id_paciente_tisaude": 4942, "paciente_tisaude_nome": "ARTHUR SPERRY CEZAR FILHO"}
    ctx = _ctx(conv, ts); ctx.atualizar = lambda campos: conv.update(campos)
    e = {"nome": "Tatiana Freitas", "cpf": "69800545034", "nascimento": "01/01/1990", "sexo": "Feminino", "email": "a@b", "como_conheceu": "GOOGLE",
         "cep": "01001000", "numero": "1", "complemento": "", "responsavel": "", "parentesco_responsavel": "", "cpf_responsavel": ""}
    saida, erro = ferramentas_ia.executar("criar_paciente", e, ctx)
    assert not erro and '"id": 777' in saida and conv["id_paciente_tisaude"] == 777
    # mesmo nome do cadastro do número → reaproveita
    conv2 = {"id": "c2", "id_paciente_tisaude": 4942, "paciente_tisaude_nome": "ARTHUR SPERRY CEZAR FILHO"}
    saida, erro = ferramentas_ia.executar("criar_paciente", {**e, "nome": "Arthur Cezar"}, _ctx(conv2, ts))
    assert '"id": 4942' in saida
    # CPF já existe em outro cadastro → adota em vez de duplicar
    ts.buscar_paciente.return_value = {"id": 2301, "nome": "TATIANA FREITAS"}
    conv3 = {"id": "c3"}; ctx3 = _ctx(conv3, ts); ctx3.atualizar = lambda campos: conv3.update(campos)
    saida, erro = ferramentas_ia.executar("criar_paciente", e, ctx3)
    assert not erro and '"id": 2301' in saida and conv3["identidade_confirmada"]


def test_contexto_numero_compartilhado_pede_cpf():
    c = prompt.contexto_lead({"nome": "Tati", "contato": "5511", "pacientes_mesmo_numero": [{"id": 1, "nome": "ARTHUR X"}, {"id": 2, "nome": "CAIO TESTE"}]})
    assert "2 pessoas" in c and "CPF" in c and "buscar_paciente" in c and "Arthur X" in c


def test_numero_teste_com_escrita_real(monkeypatch):
    from celeste.orquestrador import app as oapp
    monkeypatch.setattr(oapp, "_cfg_atendimento", lambda: {"modo": "teste", "numeros_teste": ["5511980567117", "5511900000001"],
                                                            "numeros_teste_escrita_real": ["5511980567117"]})
    assert oapp._e_numero_teste("5511980567117") and oapp._escreve_no_tisaude("5511980567117")
    assert oapp._e_numero_teste("5511900000001") and not oapp._escreve_no_tisaude("5511900000001")
    assert not oapp._escreve_no_tisaude("5511999999999")


# ------------------------------------------------------------------ cadastro: alteração (exceto nome/CPF) e nome completo
def test_nome_completo_sem_abreviacoes():
    from celeste.ferramentas.tisaude import nome_completo_valido
    assert nome_completo_valido("Maria Aparecida da Silva")[0]
    assert nome_completo_valido("João e Silva")[0]
    for ruim in ("Tati", "Maria A. Silva", "J Carlos Souza", "MARIA A SILVA"):
        ok, motivo = nome_completo_valido(ruim)
        assert not ok and motivo, ruim


def test_criar_paciente_recusa_nome_abreviado():
    e = {"nome": "Maria A. Silva", "cpf": "69800545034", "nascimento": "01/01/1990", "sexo": "Feminino", "email": "a@b", "como_conheceu": "GOOGLE",
         "cep": "01001000", "numero": "1", "complemento": "", "responsavel": "", "parentesco_responsavel": "", "cpf_responsavel": ""}
    saida, erro = ferramentas_ia.executar("criar_paciente", e, _ctx())
    assert erro and "abreviação" in saida


def test_atualizar_paciente_reenvia_registro_inteiro_e_bloqueia_nome_cpf():
    from celeste.ferramentas import tisaude
    ts = tisaude.TiSaude.__new__(tisaude.TiSaude)
    atual = {"cliente": 12054, "id": 6436, "nome": "TESTE IA BIA - APAGAR", "cpf": "27313332785", "nascimento": "1990-01-01", "sexo": "FEMININO",
             "email": "A@B.C", "celular": "11999990000", "idConvenio": 1, "endereco": "RUA X", "n": "886", "complemento": "TESTE IA",
             "bairro": "VILA", "cidade": "SÃO PAULO", "uf": "SP", "cep": "04131000", "indicado": "GOOGLE", "status": 1, "rg": "", "nomemae": "MAE"}
    enviados = {}
    def req(metodo, caminho, *, params=None, data=None, **kw):
        if metodo == "GET" and caminho == "/pacientes":
            return {"data": [dict(atual)]}            # busca por CPF: cadastro ativo
        if metodo == "GET":
            return dict(atual)
        enviados.update(data); return {"id": 6436}
    ts._req = req
    r = ts.atualizar_paciente(6436, {"email": "novo@x.com", "celular": "(11) 98888-7777"})
    assert r["id"] == 6436 and enviados["id"] == 6436                                             # id vai no payload
    assert enviados["email"] == "novo@x.com" and enviados["celular"] == "11988887777"
    assert enviados["nome"] == "TESTE IA BIA - APAGAR" and enviados["cpf"] == "27313332785"       # preservados
    assert enviados["nascimento"] == "01/01/1990" and enviados["sexo"] == "Feminino"             # formatos de entrada
    assert enviados["apt"] == "TESTE IA" and enviados["convenio"] == 1 and enviados["nomemae"] == "MAE"
    assert "status" not in enviados and "cliente" not in enviados
    with pytest.raises(ValueError):
        ts.atualizar_paciente(6436, {"nome": "OUTRO"})
    with pytest.raises(ValueError):
        ts.atualizar_paciente(6436, {"cpf": "1"})          # CPF inválido
    with pytest.raises(ValueError):
        ts.atualizar_paciente(6436, {"nascimento": "1990-01-01"})
    # TI Saúde devolve outro id (criou duplicado) → erro, nunca silencioso
    ts._req = lambda m, c, *, params=None, data=None, **kw: ({"data": [dict(atual)]} if c == "/pacientes" else dict(atual)) if m == "GET" else {"id": 9999}
    with pytest.raises(tisaude.TiSaudeErro):
        ts.atualizar_paciente(6436, {"email": "x@y.z"})
    # cadastro excluído (não aparece na busca) → erro antes de salvar
    ts._req = lambda m, c, *, params=None, data=None, **kw: ({"data": []} if c == "/pacientes" else dict(atual)) if m == "GET" else {"id": 6436}
    with pytest.raises(tisaude.TiSaudeErro):
        ts.atualizar_paciente(6436, {"email": "x@y.z"})


def test_ferramenta_atualizar_cadastro():
    ts = MagicMock(); ts.atualizar_paciente.return_value = {"id": 2301}
    vazio = {"cpf": "", "email": "", "celular": "", "nascimento": "", "sexo": "", "cep": "", "numero": "", "complemento": "", "como_conheceu": "",
             "responsavel": "", "parentesco_responsavel": "", "cpf_responsavel": ""}
    # sem paciente identificado
    saida, erro = ferramentas_ia.executar("atualizar_cadastro", {**vazio, "email": "n@x.com"}, _ctx({"id": "c1"}, ts))
    assert erro and "CPF" in saida
    # número compartilhado sem identidade confirmada
    saida, erro = ferramentas_ia.executar("atualizar_cadastro", {**vazio, "email": "n@x.com"},
                                          _ctx({"id": "c1", "id_paciente_tisaude": 4942, "pacientes_mesmo_numero": [{"id": 1, "nome": "A B"}]}, ts))
    assert erro and "vários cadastros" in saida
    # ok: e-mail + endereço por CEP
    conv = {"id": "c1", "id_paciente_tisaude": 2301, "identidade_confirmada": True}
    ctx = _ctx(conv, ts); ctx.atualizar = lambda campos: conv.update(campos)
    saida, erro = ferramentas_ia.executar("atualizar_cadastro", {**vazio, "email": "n@x.com", "cep": "01001000", "numero": "10"}, ctx)
    assert not erro and '"ok": true' in saida
    mud = ts.atualizar_paciente.call_args.args[1]
    assert mud["email"] == "n@x.com" and mud["cep"] == "01001000" and mud["n"] == "10" and mud["endereco"] == "R"
    assert conv["cadastro_campos_atualizados"]
    # nada para atualizar
    saida, erro = ferramentas_ia.executar("atualizar_cadastro", vazio, ctx)
    assert erro and "nenhum campo" in saida
    # CPF pode ser atualizado a pedido do lead
    saida, erro = ferramentas_ia.executar("atualizar_cadastro", {**vazio, "cpf": "390.533.447-05"}, ctx)
    assert not erro and ts.atualizar_paciente.call_args.args[1]["cpf"] == "390.533.447-05"


# ------------------------------------------------------------------ modelo e cache
def test_modelo_principal_tem_preco_cadastrado():
    cfg = config.parametros()["modelos"]
    for m in (cfg["conversa"], cfg["conversa_fallback"], cfg["lembretes"], cfg["auxiliar"]):
        assert m in cfg["precos_usd_por_milhao"], m
    assert cfg["conversa"] in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")


def test_aquecer_cache_envia_max_tokens_zero_com_mesmo_prefixo():
    cliente = MagicMock()
    cliente.beta.messages.create.return_value = SimpleNamespace(model="claude-opus-5-5", content=[], stop_reason="max_tokens",
        usage=SimpleNamespace(input_tokens=1, output_tokens=0, cache_read_input_tokens=21000, cache_creation_input_tokens=0))
    m = motor.Motor(cliente=cliente)
    r = m.aquecer("leads_perdidos")
    kw = cliente.beta.messages.create.call_args.kwargs
    assert kw["max_tokens"] == 0 and kw["model"] == config.parametros()["modelos"]["conversa"]
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert kw["system"][0]["text"] == m._system("leads_perdidos")[0]["text"]   # mesmo prefixo da conversa real
    assert kw["tools"] == ferramentas_ia.FERRAMENTAS and ("thinking" in kw) == ("haiku" not in kw["model"])
    assert r["cache_lido"] == 21000 and r["custo_usd"] == round(21000 * 0.2 / 1e6 + 1 * 4 / 1e6, 5)


def test_renderizar_lista_por_id_e_prompt_sem_placeholders():
    import re
    assert prompt.renderizar("{{consultas.dr_lucas.valor_texto}}", config.parametros()) == "R$ 800,00"
    assert prompt.renderizar("{{consultas.dra_luciana.agenda_texto}}", config.parametros()).startswith("de segunda a sexta")
    prompt.camadas_estaveis.cache_clear()
    t = prompt.camadas_estaveis("leads_perdidos")
    assert not re.findall(r"\{\{[^}]+\}\}", t), re.findall(r"\{\{[^}]+\}\}", t)


def test_lembrete_texto_por_etapa():
    from celeste.orquestrador import lembretes_texto as lt
    hor = {"nome": "ana paula", "ultima": {"direcao": "celeste", "texto": "Terei às 15h00 e 16h00. Qual horário melhor lhe atende?"}, "horarios_oferecidos": ["2026-10-13 15:00"]}
    assert lt.texto_lembrete(hor, 1) == "Ana, algum desses horários lhe atende?"
    assert lt.texto_lembrete(hor, 2).startswith("Os agendamentos são realizados por todos os setores")
    cad = {"nome": "ana", "ultima": {"direcao": "celeste", "texto": "Para atualizar seu endereço, me manda o CEP, o número e o complemento"}}
    assert lt.texto_lembrete(cad, 1) == "Olá, gostaria de dar continuidade ao agendamento?"
    # lista antiga de horários na conversa, mas a última mensagem não fala de horário → NÃO é etapa de horários
    velho = {"nome": "tati", "ultima": {"direcao": "celeste", "texto": "Pode desconsiderar minha última mensagem, foi um engano meu, desculpa"}, "horarios_oferecidos": ["2026-10-07 11:00"]}
    assert lt.etapa(velho) == "geral" and lt.texto_lembrete(velho, 1) == "Aguardo seu retorno, Tati! 💛"
    assert lt.texto_lembrete({"nome": "", "ultima": {"direcao": "celeste", "texto": "ok"}}, 1) == "Aguardo seu retorno! 💛"
    assert lt.etapa({"ultima": {"direcao": "lead", "texto": "tenho às 15h"}}) == "geral"


def test_lembrete_nao_vai_para_quem_disse_que_volta():
    from celeste.jobs import lembretes
    from datetime import datetime, timedelta, timezone
    agora = datetime.now(timezone.utc)
    base = {"frente": "leads_perdidos", "aberta": True, "modo": "ia", "lembretes_enviados": 0, "ultima_msg_lead_em": agora - timedelta(hours=5),
            "primeira_msg_celeste_em": agora - timedelta(hours=5), "janela_24h_ate": agora + timedelta(hours=19),
            "ultima": {"direcao": "celeste", "tipo": "text", "em": agora - timedelta(hours=3)}}
    assert lembretes.elegivel(dict(base, status="Em conversa"), agora)[0]
    for st in ("Irá nos retornar", "Vamos retornar na data solicitada", "Agora não"):
        assert not lembretes.elegivel(dict(base, status=st), agora)[0]


def test_fechar_assunto_limpa_horarios_oferecidos():
    conv = {"id": "c1", "horarios_oferecidos": ["2026-10-13 15:00"]}
    ctx = _ctx(conv); ctx.atualizar = lambda campos: conv.update(campos)
    saida, erro = ferramentas_ia.executar("atualizar_status", {"status": "Irá nos retornar", "data_retorno": ""}, ctx)
    assert not erro and conv["horarios_oferecidos"] == []
def test_prompt_v2_exemplos_e_regras():
    pr = (config.RAIZ / "prompts" / "leads-perdidos-v0.md").read_text(encoding="utf-8")
    ex = (config.RAIZ / "knowledge" / "03-exemplos-de-conversas.md").read_text(encoding="utf-8")
    assert "Exemplos de conversas reais" in pr and "Como você conversa: igual às atendentes dos exemplos" in pr
    assert ex.count("### Exemplo") >= 50 and "- **Celeste:**" in ex and "- **Lead:**" in ex
    import re
    assert not re.search(r"(?i)maria fernanda|raiane|@[\w.]+\.|\d{3}\.\d{3}\.\d{3}-\d{2}", ex)   # anonimizado
    for trecho in ("Pedido de cancelamento — UMA tentativa só", "Quando encaminhar à recepção", "Nome completo, sem abreviações",
                   "Alteração de cadastro, a pedido do lead", "só os retornados por `buscar_horarios`", "Qual seria a melhor opção para você?",
                   "Os agendamentos são realizados por todos os setores da clínica", "Não inventa informação", "sinalizar_revisao"):
        assert trecho in pr, trecho
    prompt.camadas_estaveis.cache_clear()
    t = prompt.camadas_estaveis("leads_perdidos")
    assert "### Exemplo 1 —" in t and t.index("### Exemplo 1 —") < t.index("# INSTRUÇÃO DA FRENTE")
    assert not re.findall(r"\{\{[^}]+\}\}", t)


def test_video_e_adiado_para_depois_dos_baloes():
    from celeste.orquestrador import app as oapp
    import inspect
    src = inspect.getsource(oapp.responder)
    # 15/10/2026: 1º balão → mídia → resto do texto; no máximo 3 envios contando a mídia
    assert "videos_pendentes" in src and src.index("_balao(baloes[0], False)") < src.index("\n    _midia()\n") < src.index("for texto in baloes[1:]")
    assert "max_texto = max(1, 3 - n_midia)" in src
    assert "ArrayRemove(videos_pendentes)" in src


def test_contexto_mostra_consulta_agendada_e_simulada():
    c = prompt.contexto_lead({"nome": "Tati", "contato": "5511", "id_agendamento_tisaude": 47187558,
                              "agendamento": {"data": "2026-10-12", "hora": "11:00", "profissional": "dr_lucas", "status": "Marcado"}})
    assert "CONSULTA AGENDADA (TI Saúde id 47187558), último registro conhecido: segunda-feira, 12/10/2026 às 11:00 com Dr. Lucas Vieira" in c
    assert "NUNCA deduza" in c and "consultar_agendamento" in c
    s = prompt.contexto_lead({"nome": "Tati", "contato": "5511", "id_agendamento_tisaude": 951836, "agendamento": {"data": "2026-10-13", "hora": "10:00", "profissional": "dr_lucas"}})
    assert "SIMULAÇÃO DE TESTE" in s and "NÃO existe no TI Saúde real" in s


def test_consultar_agendamento_le_o_tisaude():
    ts = MagicMock(); ts.detalhe_agendamento.return_value = {"id": 47187558, "data": "2026-10-12", "hora": "11:00:00", "status": 0, "idCalendario": 36}
    conv = {"id": "c1", "id_agendamento_tisaude": 47187558, "agendamento": {"data": "2026-10-13", "hora": "10:00", "profissional": "dr_lucas"}}
    ctx = _ctx(conv, ts); ctx.atualizar = lambda campos: conv.update(campos)
    saida, erro = ferramentas_ia.executar("consultar_agendamento", {}, ctx)
    assert not erro and '"data": "2026-10-12"' in saida and '"hora": "11:00"' in saida and '"status": "Marcado"' in saida and "Dr. Lucas Vieira" in saida
    assert conv["agendamento"]["data"] == "2026-10-12"
    ts.detalhe_agendamento.return_value = {"id": 47187558, "data": "2026-10-12", "hora": "11:00:00", "status": -2, "idCalendario": 36}
    saida, erro = ferramentas_ia.executar("consultar_agendamento", {}, ctx)
    assert '"agendada": false' in saida and "Desmarcado" in saida
    saida, erro = ferramentas_ia.executar("consultar_agendamento", {}, _ctx({"id": "c2"}, ts))
    assert '"agendada": false' in saida


def test_buscar_horarios_so_depende_da_agenda():
    from celeste.ferramentas import tisaude
    from datetime import date
    ts = tisaude.TiSaude.__new__(tisaude.TiSaude)
    ts._ocupados = lambda prof, de, ate: set()
    ts._grade_livre = lambda prof, dia: ["11:00:00"]       # a grade devolve horário até em sábado e feriado: a agenda manda
    livres = ts.buscar_horarios("dr_lucas", dias=3, a_partir_de=date(2026, 10, 31))   # sábado, domingo, feriado (2/11) no futuro
    assert {l["data"] for l in livres} >= {"2026-10-31", "2026-11-01", "2026-11-02"}
    assert "feriados" not in config.parametros()


def test_criar_paciente_dados_genericos_sem_cpf():
    ts = MagicMock(); ts.buscar_paciente.return_value = None; ts.criar_paciente.return_value = {"id": 6519}
    conv = {"id": "c1"}; ctx = _ctx(conv, ts); ctx.atualizar = lambda campos: conv.update(campos)
    e = {"nome": "Maria Aparecida Souza", "cpf": "", "nascimento": "", "sexo": "Feminino", "email": "", "como_conheceu": "", "cep": "", "numero": "",
         "complemento": "", "responsavel": "", "parentesco_responsavel": "", "cpf_responsavel": "", "dados_genericos": True}
    ctx.viacep = lambda cep: {"endereco": "AV REP DO LIBANO", "bairro": "VILA NOVA CONCEICAO", "cidade": "SAO PAULO", "uf": "SP"} if cep == "04502001" else {}
    saida, erro = ferramentas_ia.executar("criar_paciente", e, ctx)
    assert not erro and '"id": 6519' in saida and "dados genéricos" in saida and "No dia da consulta" in saida
    d = ts.criar_paciente.call_args.args[0]
    assert d["cpf"] == "" and d["nascimento"] == "01/01/2001" and d["email"] == "ATUALIZAR111@GMAIL.COM" and d["indicado"] == "DRA. LUCIANA PASSONI" and d["n"] == "886"
    assert conv["cadastro_generico"] is True and not ts.buscar_paciente.called
    # sem a flag, CPF vazio é recusado
    saida, erro = ferramentas_ia.executar("criar_paciente", {**e, "dados_genericos": False}, _ctx({"id": "c2"}, ts))
    assert erro and "CPF não informado" in saida


def test_tisaude_criar_paciente_sem_cpf_omite_campo():
    from celeste.ferramentas import tisaude
    ts = tisaude.TiSaude.__new__(tisaude.TiSaude)
    enviados = {}
    ts._req = lambda m, c, *, params=None, data=None, **kw: (enviados.update(data) or {"id": 6519})
    ts.buscar_paciente = lambda **kw: (_ for _ in ()).throw(AssertionError("não deve buscar CPF vazio"))
    r = ts.criar_paciente({"nome": "Maria Souza", "cpf": "", "nascimento": "01/01/2001", "sexo": "Feminino", "celular": "5511999990000", "email": "a@b",
                           "indicado": "DRA. LUCIANA PASSONI", "cep": "04502001", "n": "886", "endereco": "AV", "bairro": "B", "cidade": "C", "uf": "SP"})
    assert r["id"] == 6519 and "cpf" not in enviados and enviados["nome"] == "MARIA SOUZA"


def test_atualizar_paciente_cpf_novo_checa_duplicidade():
    from celeste.ferramentas import tisaude
    ts = tisaude.TiSaude.__new__(tisaude.TiSaude)
    atual = {"id": 6519, "nome": "TESTE", "cpf": "", "nascimento": "2001-01-01", "sexo": "FEMININO", "email": "A@B.C", "celular": "11999990002",
             "idConvenio": 1, "endereco": "AV", "n": "886", "complemento": "", "bairro": "B", "cidade": "C", "uf": "SP", "cep": "04502001", "indicado": "X", "status": 1}
    enviados = {}
    def req(m, c, *, params=None, data=None, **kw):
        if m == "GET" and c == "/pacientes":
            return {"data": [{"id": 999, "nome": "OUTRA PESSOA", "cpf": "12345678909"}] if params.get("busca") == "12345678909" else []}
        if m == "GET":
            return dict(atual)
        enviados.update(data); return {"id": 6519}
    ts._req = req
    r = ts.atualizar_paciente(6519, {"cpf": "390.533.447-05"})      # preenche CPF vazio
    assert r["id"] == 6519 and enviados["cpf"] == "39053344705" and enviados["id"] == 6519
    with pytest.raises(tisaude.TiSaudeErro):
        ts.atualizar_paciente(6519, {"cpf": "12345678909"})           # pertence a outro cadastro


@pytest.mark.parametrize("entrada,esperado", [
    ("Conferi agora no sistema: não tem nenhuma consulta marcada.", "Conferi agora no sistema, não tem nenhuma consulta marcada."),
    ("Terei às 15:00 ou às 16:00.", "Terei às 15:00 ou às 16:00."),
    ("📍 Endereço: Avenida República do Líbano, 886", "📍 Endereço: Avenida República do Líbano, 886"),
    ("Me passa, por gentileza:\n\n🔹 CEP", "Me passa, por gentileza:\n\n🔹 CEP"),
])
def test_limpar_pontuacao_dois_pontos(entrada, esperado):
    assert motor.limpar_pontuacao(entrada) == esperado


def test_classificar_botao_t1():
    from celeste.orquestrador import app as oapp
    assert oapp.classificar_botao_consulta("Confirmar presença", "Confirmar presença") == "confirmar_presenca"
    assert oapp.classificar_botao_consulta(None, "confirmar presença") == "confirmar_presenca"
    assert oapp.classificar_botao_consulta("Preciso remarcar", "Preciso remarcar") is None
    assert oapp.classificar_botao_t1("Agora não", "Agora não") == "agora_nao"
    assert oapp.classificar_botao_t1("agora não", None) == "agora_nao"
    assert oapp.classificar_botao_t1("nao_quero_continuar", "Não quero continuar") == "sair"
    assert oapp.classificar_botao_t1(None, "Não quero continuar") == "sair"
    assert oapp.classificar_botao_t1("Pode encerrar", "Pode encerrar") == "encerrar"
    assert oapp.classificar_botao_t1("Quero continuar", "Quero continuar") is None
    assert oapp.classificar_botao_t1(None, "oi") is None


def test_botoes_resposta_payload():
    from celeste.ferramentas import meta as m
    cli = m.Meta.__new__(m.Meta); enviados = {}
    cli._post = lambda caminho, corpo: (enviados.update(corpo) or {"messages": [{"id": "wamid-b"}]})
    assert cli.enviar_botoes_resposta("5511", "texto", [("nao_quero_continuar", "Não quero continuar")]) == "wamid-b"
    btn = enviados["interactive"]["action"]["buttons"][0]["reply"]
    assert enviados["interactive"]["type"] == "button" and btn["id"] == "nao_quero_continuar" and btn["title"] == "Não quero continuar" and len(btn["title"]) <= 20


def test_t1_tem_botoes_e_textos_do_fluxo():
    from celeste.jobs import templates_texto as tt
    assert tt.TEMPLATES["T1"]["botoes"] == ["Quero continuar", "Agora não"]
    b = config.parametros()["t1_botoes"]
    assert len(b["sair_rotulo"]) <= 20 and "{nome}" in b["agora_nao_texto"] and "{nome}" in b["sair_texto"]


def test_haiku_sem_thinking_nem_fallback_do_servidor():
    cliente = MagicMock()
    cliente.beta.messages.create.return_value = SimpleNamespace(model="x", content=[], stop_reason="max_tokens",
        usage=SimpleNamespace(input_tokens=1, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0))
    m = motor.Motor(cliente=cliente)
    m._criar("claude-haiku-5-5", [], [{"role": "user", "content": "."}], max_tokens=0)
    kw = cliente.beta.messages.create.call_args.kwargs
    assert "thinking" not in kw and "betas" not in kw and "fallbacks" not in kw
    m._criar("claude-opus-5-5", [], [{"role": "user", "content": "."}], max_tokens=0)
    kw = cliente.beta.messages.create.call_args.kwargs
    assert kw["thinking"] == {"type": "adaptive"} and kw["fallbacks"] == "default"


def test_buscar_horarios_oferece_2_do_dia_pedido_e_acumula_oferecidos():
    livres = [{"data": "2026-10-15", "hora": h} for h in ("13:00", "14:00", "15:00", "16:00")]
    livres += [{"data": "2026-10-16", "hora": "13:00"}, {"data": "2026-10-19", "hora": "13:00"}]
    assert ferramentas_ia.selecionar_opcoes(livres, 2) == livres[:2]   # 22/10/2026: 2 do dia pedido
    assert ferramentas_ia.selecionar_opcoes(livres[3:], 2) == [livres[3], livres[4]]   # dia com 1 vaga completa com o seguinte
    assert ferramentas_ia.selecionar_opcoes(livres[:1], 2) == livres[:1]
    ts = MagicMock(); ts.buscar_horarios.return_value = livres
    conv = {"id": "c1", "frente": "leads_perdidos", "horarios_oferecidos": ["2026-10-14 10:00"]}
    ctx = _ctx(conv, ts=ts); ctx.atualizar = lambda campos: conv.update(campos)
    saida, erro = ferramentas_ia.executar("buscar_horarios", {"profissional": "dra_luciana", "a_partir_de": "", "dias": 14}, ctx)
    d = __import__("json").loads(saida)
    assert not erro and len(d["livres"]) == 2 and d["ha_mais_no_periodo"] and not d["dia_pedido_sem_vaga"]
    assert conv["horarios_oferecidos"] == ["2026-10-14 10:00", "2026-10-15 13:00", "2026-10-15 14:00"]
    # dia pedido sem vaga: devolve o dia mais próximo e sinaliza
    saida, erro = ferramentas_ia.executar("buscar_horarios", {"profissional": "dra_luciana", "a_partir_de": "2026-10-14", "dias": 14}, ctx)
    d = __import__("json").loads(saida)
    assert not erro and d["dia_pedido_sem_vaga"] and "não tem vaga" in d["aviso"]


def test_separar_baloes_limita_a_tres():
    sep = chr(10) + "---" + chr(10)
    partes = motor.separar_baloes(sep.join(["Um.", "Dois.", "Três.", "Quatro.", "Cinco."]))
    assert len(partes) == 3 and partes[:2] == ["Um.", "Dois."]
    assert partes[2] == "Três." + chr(10) * 2 + "Quatro." + chr(10) * 2 + "Cinco."


def test_referencias_codigo_vira_link_e_link_digitado_errado_e_corrigido():
    from celeste.orquestrador import referencias
    cat = referencias.catalogo()
    assert len(cat) >= 40 and cat["artigo-fapd"].endswith("microgra-1102219.html") and cat["instagram-dra"].endswith("/dralupassoni/")
    assert referencias.resolver("Olha: [[ref:metropoles-queda-por-dia]] 😊") == "Olha: " + cat["metropoles-queda-por-dia"] + " 😊"
    assert referencias.resolver("Veja [[ref:nao-existe]] aqui") == "Veja aqui"          # código desconhecido nunca vira link inventado
    errado = cat["artigo-fapd"].replace("single-injection", "single-installation")       # incidente de 14/10: slug redigitado
    assert referencias.resolver("o certo é este, " + errado + ".") == "o certo é este, " + cat["artigo-fapd"] + "."
    assert referencias.resolver("https://www.google.com/x") == "https://www.google.com/x"   # domínio desconhecido fica como está


def test_enviar_texto_liga_previa_so_quando_ha_link():
    from celeste.ferramentas import meta
    m = meta.Meta.__new__(meta.Meta); chamadas = []
    m._post = lambda caminho, corpo: (chamadas.append(corpo), {"messages": [{"id": "w1"}]})[1]
    m.enviar_texto("55", "Oi, tudo bem?"); m.enviar_texto("55", "Olha: https://vogue.globo.com/x")
    assert chamadas[0]["text"]["preview_url"] is False and chamadas[1]["text"]["preview_url"] is True


def test_catalogo_de_videos_bate_com_a_ferramenta():
    cfg = config.parametros()
    enum = next(t for t in ferramentas_ia.FERRAMENTAS if t["name"] == "enviar_video")["input_schema"]["properties"]["video"]["enum"]
    assert set(enum) == set(cfg["videos"]) and len(enum) >= 18
    for chave, v in cfg["videos"].items():
        assert v["url"].endswith(f"/{chave}.mp4") and v["descricao"] and v["quando"], chave
    assert not set(cfg["videos_rotinas"]) & set(cfg["videos"])


def test_limitar_emojis_deixa_so_um_por_resposta():
    b = motor.limitar_emojis(["Sem problemas, Tadeu! 😊 Ficou mais alguma dúvida? 😊", "Combinado! 💛 Até lá 😊"])
    assert b == ["Sem problemas, Tadeu! 😊 Ficou mais alguma dúvida?", "Combinado! Até lá"]
    assert motor.limitar_emojis(["Oi, tudo bem?"]) == ["Oi, tudo bem?"]
    assert motor.limitar_emojis(["💛"]) == ["💛"] and motor.limitar_emojis(["Oi 💛", "💛"]) == ["Oi 💛"]


def test_abertura_extrai_texto_do_turno_em_string_ou_blocos():
    from celeste.orquestrador import app as oapp
    import inspect
    src = inspect.getsource(oapp.responder)
    assert "isinstance(conteudo, str)" in src   # 15/10: o histórico compacta turnos só-texto em string; a extração precisa aceitar os dois


def test_abertura_sem_modelo_reconhece_so_cumprimento():
    from celeste.orquestrador import abertura
    for t in ("Oi", "oi!", "Olá", "olá, tudo bem?", "Bom dia", "Boa tarde!!", "oi celeste", "Oi 😊", "boa noite, Celeste"):
        assert abertura.e_saudacao_solta(t), t
    for t in ("Oi, gostaria de mais informações", "bom dia, quanto custa a consulta?", "", "quero agendar", "oi meu cabelo está caindo"):
        assert not abertura.e_saudacao_solta(t), t
    # a apresentação não muda com o cumprimento do lead (decisão da clínica, 15/10/2026)
    for t in ("Bom dia", "oi", "olá celeste", "boa noite"):
        b = abertura.baloes_abertura("tadeu lopes", t)
        assert b == ["Olá, Tadeu, tudo bem?", "É um prazer falar com você, aqui é a Celeste, concierge da Passoni Clinic, e estou aqui para te ajudar! 💛"]
    assert abertura.baloes_abertura("", "oi")[0] == "Olá, tudo bem?"


def test_enviar_antes_e_depois_tratamento_config_e_uma_vez():
    conv = {"id": "c1", "frente": "leads_perdidos"}; pend = []
    ctx = _ctx(conv); ctx.atualizar = lambda campos: conv.update(campos); ctx.enviar_imagem = lambda d: (pend.append(d), "adiado")[1]
    # uma foto por pedido; a 2ª chamada manda a próxima; quando acabam, avisa (Fotona tem 2 fotos)
    s1, e1 = ferramentas_ia.executar("enviar_antes_e_depois_tratamento", {"tratamento": "fotona_capilar"}, ctx)
    s2, e2 = ferramentas_ia.executar("enviar_antes_e_depois_tratamento", {"tratamento": "fotona_capilar"}, ctx)
    s3, e3 = ferramentas_ia.executar("enviar_antes_e_depois_tratamento", {"tratamento": "fotona_capilar"}, ctx)
    assert not e1 and not e2 and pend == ["tratamento:fotona_capilar:04-fotona-capilar.jpg", "tratamento:fotona_capilar:12-fotona-capilar.jpg"]
    assert conv["fotos_enviadas"] == ["04-fotona-capilar.jpg", "12-fotona-capilar.jpg"] and "não há mais fotos" in s3
    # 'geral' percorre os tratamentos da lista geral, uma foto por vez
    conv2 = {"id": "c2", "frente": "leads_perdidos"}; pend2 = []
    ctx2 = _ctx(conv2); ctx2.atualizar = lambda campos: conv2.update(campos); ctx2.enviar_imagem = lambda d: (pend2.append(d), "adiado")[1]
    ferramentas_ia.executar("enviar_antes_e_depois_tratamento", {"tratamento": "geral"}, ctx2)
    assert len(pend2) == 1 and pend2[0].startswith("tratamento:microinfusao_de_medicamentos:")
    cfg = config.parametros()["antes_e_depois_tratamentos"]
    enum = next(t for t in ferramentas_ia.FERRAMENTAS if t["name"] == "enviar_antes_e_depois_tratamento")["input_schema"]["properties"]["tratamento"]["enum"]
    assert set(enum) == set(cfg["tratamentos"]) | {"geral"} and all(t in cfg["tratamentos"] for t in cfg["geral"])
    assert "{tratamento}" in cfg["legenda"] and all(d["arquivos"] for d in cfg["tratamentos"].values())


def test_enviar_antes_e_depois_uma_vez_por_doenca_e_config_consistente():
    conv = {"id": "c1", "frente": "leads_perdidos"}
    pend = []
    ctx = _ctx(conv); ctx.atualizar = lambda campos: conv.update(campos); ctx.enviar_imagem = lambda d: (pend.append(d), "adiado")[1]
    s1, e1 = ferramentas_ia.executar("enviar_antes_e_depois", {"doenca": "efluvio_telogeno"}, ctx)
    s2, e2 = ferramentas_ia.executar("enviar_antes_e_depois", {"doenca": "efluvio_telogeno"}, ctx)
    s3, e3 = ferramentas_ia.executar("enviar_antes_e_depois", {"doenca": "efluvio_telogeno"}, ctx)
    assert not e1 and not e2 and pend == ["doenca:efluvio_telogeno:16-efluvio-telogeno-a.jpg", "doenca:efluvio_telogeno:16-efluvio-telogeno-b.jpg"]
    assert conv["fotos_enviadas"] == ["16-efluvio-telogeno-a.jpg", "16-efluvio-telogeno-b.jpg"] and "não há mais fotos" in s3
    cfg = config.parametros()["antes_e_depois"]
    enum = next(t for t in ferramentas_ia.FERRAMENTAS if t["name"] == "enviar_antes_e_depois")["input_schema"]["properties"]["doenca"]["enum"]
    assert set(enum) == set(cfg["doencas"]) and all(d["arquivos"] for d in cfg["doencas"].values())
    assert "{doenca}" in cfg["legenda"]


# ------------------------------------------------------------------ saneamento: marcação de ferramenta vazada no texto (caso Curti, 24/10/2026)
_VAZADO = ('E se conseguir ver antes, é só me mandar uma mensagem que já verifico as opções para você. 💛\n\n'
           '<invoke name="atualizar_status">\n<parameter name="status">Vamos retornar na data solicitada</parameter>\n'
           '<parameter name="data_retorno">2026-10-26</parameter>\n</invoke>\n'
           '<invoke name="sinalizar_revisao">\n<parameter name="duvida">Perguntou qual médico fala no vídeo.</parameter>\n</invoke>\n'
           '</function_calls>')


def test_saneamento_extrai_chamadas_e_limpa_texto():
    from celeste.orquestrador import saneamento
    limpo, chamadas = saneamento.extrair_chamadas(_VAZADO, ferramentas_ia.FERRAMENTAS)
    assert limpo == "E se conseguir ver antes, é só me mandar uma mensagem que já verifico as opções para você. 💛"
    assert chamadas == [("atualizar_status", {"status": "Vamos retornar na data solicitada", "data_retorno": "2026-10-26"}),
                        ("sinalizar_revisao", {"duvida": "Perguntou qual médico fala no vídeo."})]
    assert not saneamento.tem_marcacao(limpo) and saneamento.tem_marcacao("ok <function_calls>")
    # texto normal passa intacto; ferramenta inexistente é descartada mas a marcação some; inteiro vira int
    assert saneamento.extrair_chamadas("Oi, tudo bem?\n---\nPosso ajudar?", ferramentas_ia.FERRAMENTAS) == ("Oi, tudo bem?\n---\nPosso ajudar?", [])
    limpo, chamadas = saneamento.extrair_chamadas('Oi <invoke name="nao_existe"><parameter name="x">1</parameter></invoke>', ferramentas_ia.FERRAMENTAS)
    assert (limpo, chamadas) == ("Oi", [])
    _, ch = saneamento.extrair_chamadas('<invoke name="agendar_consulta"><parameter name="id_paciente">6504</parameter></invoke>', ferramentas_ia.FERRAMENTAS)
    assert ch[0][1]["id_paciente"] == 6504 and ch[0][1]["profissional"] == ""


def test_motor_filtra_marcacao_vazada_executa_e_sinaliza():
    cliente = MagicMock()
    cliente.beta.messages.create.return_value = _resp("end_turn", [SimpleNamespace(type="text", text="Imagina, Curti!\n---\n" + _VAZADO)])
    conv = {"id": "c1", "contato": "55", "nome": "Curti"}
    ctx = _ctx(conv); ctx.atualizar = lambda campos: conv.update(campos)
    res = motor.Motor(cliente=cliente).responder("leads_perdidos", conv, [{"role": "user", "content": "oi"}], ctx)
    assert res.baloes == ["Imagina, Curti!", "E se conseguir ver antes, é só me mandar uma mensagem que já verifico as opções para você. 💛"]
    assert res.chamadas == 1   # nenhuma chamada extra ao modelo
    assert [f["nome"] for f in res.ferramentas] == ["atualizar_status", "sinalizar_revisao"] and all(f["vazada"] for f in res.ferramentas)
    assert conv["status"] == "Vamos retornar na data solicitada" and conv["proximo_recontato_em"] == "2026-10-26" and conv["revisar"]


def test_motor_regera_uma_vez_se_sobrou_so_marcacao():
    cliente = MagicMock()
    so_marcacao = '<invoke name="atualizar_status"><parameter name="status">Achou caro</parameter><parameter name="data_retorno"></parameter></invoke>'
    cliente.beta.messages.create.side_effect = [
        _resp("end_turn", [SimpleNamespace(type="text", text=so_marcacao)]),
        _resp("end_turn", [SimpleNamespace(type="text", text="Entendo! Qualquer coisa, me chama.")]),
    ]
    conv = {"id": "c1", "contato": "55", "nome": "Ana"}
    ctx = _ctx(conv); ctx.atualizar = lambda campos: conv.update(campos)
    res = motor.Motor(cliente=cliente).responder("leads_perdidos", conv, [{"role": "user", "content": "caro demais"}], ctx)
    assert res.baloes == ["Entendo! Qualquer coisa, me chama."] and res.chamadas == 2
    assert conv["status"] == "Achou caro" and conv["revisar"]
    assert "[sistema]" in cliente.beta.messages.create.call_args.kwargs["messages"][-1]["content"]


def test_confirmar_presenca_simulado_envia_texto_e_video(monkeypatch):
    from celeste.orquestrador import app as oapp
    monkeypatch.setattr(oapp, "_cfg_atendimento", lambda: {"modo": "teste", "numeros_teste": ["5511900000001"], "numeros_teste_escrita_real": []})
    ref, mt = MagicMock(), MagicMock()
    mt.enviar_texto.return_value = "wamid.txt"; mt.enviar_video_link.return_value = "wamid.vid"
    conv = {"id": "c1", "contato": "5511900000001", "nome": "Ana Souza", "teste": True, "id_agendamento_tisaude": 123,
            "agendamento": {"data": "2026-10-29", "hora": "14:00", "profissional": "dra_luciana"}}
    r = oapp._responder_confirmar_presenca(ref, conv, mt)
    assert r["fluxo"] == "consulta_confirmar" and r["tisaude"] == "simulado" and r["enviado"] == 2
    texto = mt.enviar_texto.call_args.args[1]
    assert "Presença confirmada" in texto and "quinta-feira, 29/10" in texto and "14h" in texto and texto.startswith("Perfeito, Ana!")
    assert "confirmou_dra_luciana" in mt.enviar_video_link.call_args.args[1]
    campos = ref.set.call_args.args[0]
    assert campos["agendamento"]["status"] == "Confirmado" and campos["rotinas_consulta"]["confirmado_no_tisaude"] and not campos.get("revisar")



# ------------------------------------------------------------------ portão antes do envio (26/10/2026)
def _juiz(aprovado, motivo=""):
    txt = '{"aprovado": true}' if aprovado else '{"aprovado": false, "motivo": "%s"}' % motivo
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=txt)], usage=_uso(input_tokens=4000, output_tokens=20))


def test_portao_gatilhos_e_parse():
    from celeste.orquestrador import portao
    assert portao.arriscada(["Com a Dra. Luciana, na sexta, 16/10, tenho às 13h."]) and portao.arriscada(["A consulta é R$ 1.200,00."])
    assert portao.arriscada(["Tem desconto para indicação?"]) and not portao.arriscada(["Oi, Ana! Tudo bem? Posso te ajudar com mais alguma coisa?"])
    assert portao._parse('{"aprovado": false, "motivo": "valor errado"}') == (False, "valor errado")
    assert portao._parse("blá {\"aprovado\": true} blá") == (True, "") and portao._parse("sem json") is None
    cliente = MagicMock(); cliente.messages.create.side_effect = RuntimeError("api fora")
    ok, motivo, uso = portao.avaliar(cliente, [{"role": "user", "content": "oi"}], ["R$ 10"], [])
    assert ok and uso is None and "indispon" in motivo


def test_motor_portao_reprova_regera_e_aprova():
    cliente = MagicMock()
    cliente.beta.messages.create.side_effect = [
        _resp("end_turn", [SimpleNamespace(type="text", text="A consulta com a Dra. custa R$ 500,00.")]),
        _resp("end_turn", [SimpleNamespace(type="text", text="A consulta com a Dra. Luciana Passoni é R$ 1.200,00.")]),
    ]
    cliente.messages.create.side_effect = [_juiz(False, "valor da consulta errado; na base é R$ 1.200,00"), _juiz(True)]
    conv = {"id": "c1", "contato": "55", "nome": "Ana"}
    ctx = _ctx(conv); ctx.atualizar = lambda campos: conv.update(campos)
    res = motor.Motor(cliente=cliente).responder("leads_perdidos", conv, [{"role": "user", "content": "quanto custa?"}], ctx)
    assert res.baloes == ["A consulta com a Dra. Luciana Passoni é R$ 1.200,00."] and res.chamadas == 2
    portoes = [f for f in res.ferramentas if f["nome"] == "portao"]
    assert len(portoes) == 2 and portoes[0]["erro"] and not portoes[1]["erro"]
    assert "[sistema] O revisor interno reprovou" in cliente.beta.messages.create.call_args.kwargs["messages"][-1]["content"]
    assert res.tokens["input_tokens"] == 2 * 1000 + 2 * 4000 and not conv.get("revisar")


def test_motor_portao_reprova_duas_vezes_manda_fallback():
    cliente = MagicMock()
    cliente.beta.messages.create.side_effect = [
        _resp("end_turn", [SimpleNamespace(type="text", text="Atendemos aos sábados às 9h.")]),
        _resp("end_turn", [SimpleNamespace(type="text", text="Aos sábados temos vaga às 10h.")]),
    ]
    cliente.messages.create.side_effect = [_juiz(False, "não atende sábado"), _juiz(False, "não atende sábado")]
    conv = {"id": "c1", "contato": "55", "nome": "Ana"}
    ctx = _ctx(conv); ctx.atualizar = lambda campos: conv.update(campos)
    res = motor.Motor(cliente=cliente).responder("leads_perdidos", conv, [{"role": "user", "content": "atende sábado?"}], ctx)
    assert res.baloes == [config.parametros()["portao"]["fallback"]] and conv.get("revisar")
    assert [f["nome"] for f in res.ferramentas] == ["portao", "portao", "sinalizar_revisao"]


def test_motor_portao_nao_revisa_resposta_sem_risco():
    cliente = MagicMock()
    cliente.beta.messages.create.return_value = _resp("end_turn", [SimpleNamespace(type="text", text="Oi, Ana! Tudo bem? Posso te ajudar com mais alguma coisa?")])
    conv = {"id": "c1", "contato": "55", "nome": "Ana"}
    res = motor.Motor(cliente=cliente).responder("leads_perdidos", conv, [{"role": "user", "content": "oi"}], _ctx(conv))
    assert res.baloes and not cliente.messages.create.called


def test_portao_contexto_ignora_reprovacao_anterior():
    from celeste.orquestrador import portao
    msgs = [{"role": "user", "content": "tem desconto?"},
            {"role": "assistant", "content": [{"type": "text", "text": "Temos condições especiais!"}]},
            {"role": "user", "content": "[sistema] O revisor interno reprovou a sua resposta: promete condições especiais. Reescreva."}]
    ctx = portao.contexto_recente(msgs)
    assert ctx == "LEAD: tem desconto?" and "[sistema]" not in ctx and "condições especiais" not in ctx
