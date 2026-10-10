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
        assert 5 <= motor.delay_humano() <= 20
        assert 5 <= motor.delay_humano(fora_horario=True) <= 20


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
    # custo (opus 5.5): 2×(1000 in ×4 + 100 out ×20)/1M + 20000 cache ×0.2/1M
    assert abs(res.custo_usd - (2 * (1000 * 4 + 100 * 20) / 1e6 + 20000 * 0.2 / 1e6)) < 1e-9
    # contexto do lead foi injetado na 1ª mensagem; system tem cache_control
    kwargs = cliente.beta.messages.create.call_args_list[0].kwargs
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "Nome: Ana" in kwargs["messages"][0]["content"]
    assert kwargs["model"] == "claude-opus-5-5"


def test_motor_fallback_para_sonnet():
    cliente = MagicMock()
    req = MagicMock()
    cliente.beta.messages.create.side_effect = [
        anthropic.InternalServerError("boom", response=MagicMock(status_code=500, headers={}), body=None),
        _resp("end_turn", [SimpleNamespace(type="text", text="Oi!")], modelo="claude-sonnet-5-5"),
    ]
    res = motor.Motor(cliente=cliente).responder("leads_perdidos", {"id": "c1"}, [{"role": "user", "content": "oi"}], _ctx())
    assert res.modelo == "claude-sonnet-5-5" and res.baloes == ["Oi!"]
    assert cliente.beta.messages.create.call_args_list[1].kwargs["model"] == "claude-sonnet-5-5"


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
    s, erro = ferramentas_ia.executar("cancelar", dict(base), ctx); assert erro and "motivo" in s and not ts.cancelar.called
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
        ts.atualizar_paciente(6436, {"cpf": "1"})
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
    vazio = {"email": "", "celular": "", "nascimento": "", "sexo": "", "cep": "", "numero": "", "complemento": "", "como_conheceu": "",
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
    assert erro and "nome e CPF" in saida


# ------------------------------------------------------------------ modelo e cache
def test_modelo_principal_tem_preco_cadastrado():
    cfg = config.parametros()["modelos"]
    for m in (cfg["conversa"], cfg["conversa_fallback"], cfg["lembretes"], cfg["auxiliar"]):
        assert m in cfg["precos_usd_por_milhao"], m
    assert cfg["conversa"] == "claude-opus-5-5"


def test_aquecer_cache_envia_max_tokens_zero_com_mesmo_prefixo():
    cliente = MagicMock()
    cliente.beta.messages.create.return_value = SimpleNamespace(model="claude-opus-5-5", content=[], stop_reason="max_tokens",
        usage=SimpleNamespace(input_tokens=1, output_tokens=0, cache_read_input_tokens=21000, cache_creation_input_tokens=0))
    m = motor.Motor(cliente=cliente)
    r = m.aquecer("leads_perdidos")
    kw = cliente.beta.messages.create.call_args.kwargs
    assert kw["max_tokens"] == 0 and kw["model"] == "claude-opus-5-5"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert kw["system"][0]["text"] == m._system("leads_perdidos")[0]["text"]   # mesmo prefixo da conversa real
    assert kw["tools"] == ferramentas_ia.FERRAMENTAS and "thinking" in kw
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
    base = {"nome": "ana paula", "ultima": {"direcao": "celeste", "texto": "Terei às 15h00 e 16h00. Qual horário melhor lhe atende?"}}
    assert lt.texto_lembrete(dict(base, horarios_oferecidos=["2026-10-13 15:00"]), 1) == "Ana, algum desses horários lhe atende?"
    assert lt.texto_lembrete(dict(base, horarios_oferecidos=["2026-10-13 15:00"]), 2).startswith("Os agendamentos são realizados por todos os setores")
    cad = dict(base, ultima={"direcao": "celeste", "texto": "Por gentileza, poderia me informar os dados abaixo para realizarmos o seu pré-cadastro"})
    assert lt.texto_lembrete(cad, 1) == "Olá, gostaria de dar continuidade ao agendamento?"
    assert lt.texto_lembrete(base, 1) == "Aguardo seu retorno, Ana! 💛"
    assert lt.texto_lembrete(base, 2) == "Oi Ana, conseguiu verificar?"
    assert lt.texto_lembrete(dict(base, nome=""), 1) == "Aguardo seu retorno! 💛"
    assert lt.texto_lembrete(dict(base, horarios_oferecidos=["x"], status="Agendado"), 1) == "Aguardo seu retorno, Ana! 💛"


def test_prompt_v2_exemplos_e_regras():
    pr = (config.RAIZ / "prompts" / "leads-perdidos-v0.md").read_text(encoding="utf-8")
    ex = (config.RAIZ / "knowledge" / "03-exemplos-de-conversas.md").read_text(encoding="utf-8")
    assert "Exemplos de conversas reais" in pr and "Como você conversa: igual às atendentes dos exemplos" in pr
    assert ex.count("### Exemplo") >= 50 and "- **Celeste:**" in ex and "- **Lead:**" in ex
    import re
    assert not re.search(r"(?i)maria fernanda|raiane|@[\w.]+\.|\d{3}\.\d{3}\.\d{3}-\d{2}", ex)   # anonimizado
    for trecho in ("Pedido de cancelamento — ordem obrigatória", "Quando encaminhar à recepção", "Nome completo, sem abreviações",
                   "nome e CPF nunca mudam por você", "só os retornados por `buscar_horarios`", "Qual seria a melhor opção para você?",
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
    assert "videos_pendentes" in src and src.index("for v in videos_pendentes") > src.index("for i, texto in enumerate(res.baloes)")
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
