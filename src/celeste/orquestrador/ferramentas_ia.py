# -*- coding: utf-8 -*-
"""Ferramentas que a Celeste pode chamar (schemas estritos) e sua execução.

Os guarda-corpos moram aqui e no cliente TI Saúde, não no prompt.
"""
from __future__ import annotations

import json
import re
import logging
from datetime import date, datetime, timezone
from typing import Any, Callable

from celeste.comum import config
from celeste.ferramentas import tisaude as ts

log = logging.getLogger(__name__)

FERRAMENTAS: list[dict] = [
    {"name": "buscar_paciente", "description": "Procura o lead no TI Saúde pelo CPF (identificação exata) ou, sem CPF, pelo nome completo entre os cadastros deste telefone. Use sempre que o lead disser que já tem cadastro ou informar o CPF, inclusive quando o contexto disser que o número está no cadastro de outra pessoa: o CPF decide quem é. A busca só pelo telefone já foi feita pelo sistema.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "cpf": {"type": "string", "description": "CPF informado pelo lead (11 dígitos, com ou sem pontuação); vazio se não informou"},
         "nome_completo": {"type": "string", "description": "nome completo informado pelo lead, para desempatar quando o telefone tem vários cadastros; vazio se não tiver"}},
         "required": ["cpf", "nome_completo"], "additionalProperties": False}},
    {"name": "criar_paciente", "description": "Cria o cadastro do lead no TI Saúde. Só chame com TODOS os campos coletados; nunca para quem já existe.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "nome": {"type": "string"}, "cpf": {"type": "string"}, "nascimento": {"type": "string", "description": "dd/mm/AAAA"},
         "sexo": {"type": "string", "enum": ["Masculino", "Feminino"]}, "email": {"type": "string"},
         "como_conheceu": {"type": "string", "description": "valor do sistema para 'Encaminhado por' (ex.: CAMPANHA DE MENSAGENS, INSTAGRAM DRA. LUCIANA, GOOGLE)"},
         "cep": {"type": "string"}, "numero": {"type": "string"}, "complemento": {"type": "string"},
         "responsavel": {"type": "string", "description": "nome do responsável se menor de idade; senão vazio"},
         "parentesco_responsavel": {"type": "string", "description": "Mãe, Pai, Irmão, Irmã, Tio, Tia, Padrinho, Madrinha, Primo, Prima, Outro ou vazio"},
         "cpf_responsavel": {"type": "string"},
         "dados_genericos": {"type": "boolean", "description": "true SÓ quando o lead, depois de você insistir UMA vez, manteve que não quer passar os dados. O sistema preenche nascimento, e-mail, encaminhado por e endereço com os genéricos da clínica e deixa o CPF vazio; você informa só nome completo e sexo (deduza pelo nome)."}},
         "required": ["nome", "cpf", "nascimento", "sexo", "email", "como_conheceu", "cep", "numero", "complemento", "responsavel", "parentesco_responsavel", "cpf_responsavel", "dados_genericos"],
         "additionalProperties": False}},
    {"name": "atualizar_cadastro", "description": "Atualiza dados cadastrais do paciente já identificado nesta conversa, a pedido dele: CPF, e-mail, celular, data de nascimento, sexo, endereço por CEP/número/complemento, como conheceu, responsável. Nome o TI Saúde não deixa alterar pela API: se o lead pedir, registre com sinalizar_revisao para a recepção corrigir e siga normalmente. Deixe vazios os campos que não mudam.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "cpf": {"type": "string", "description": "novo CPF (11 dígitos); vazio se não muda"},
         "email": {"type": "string"}, "celular": {"type": "string", "description": "novo celular com DDD; vazio se não muda"},
         "nascimento": {"type": "string", "description": "dd/mm/AAAA; vazio se não muda"},
         "sexo": {"type": "string", "enum": ["Masculino", "Feminino", ""]},
         "cep": {"type": "string", "description": "novo CEP (o endereço é preenchido pelo sistema); vazio se não muda"},
         "numero": {"type": "string", "description": "número da residência; obrigatório se o CEP mudou"},
         "complemento": {"type": "string"},
         "como_conheceu": {"type": "string", "description": "valor do sistema para 'Encaminhado por'; vazio se não muda"},
         "responsavel": {"type": "string"}, "parentesco_responsavel": {"type": "string"}, "cpf_responsavel": {"type": "string"}},
         "required": ["cpf", "email", "celular", "nascimento", "sexo", "cep", "numero", "complemento", "como_conheceu", "responsavel", "parentesco_responsavel", "cpf_responsavel"],
         "additionalProperties": False}},
    {"name": "buscar_horarios", "description": "Devolve ATÉ 3 horários LIVRES de consulta para um profissional (os primeiros do período). Ofereça só esses. Se o lead pedir outro dia ou outro horário, chame de novo com a_partir_de nesse dia.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "profissional": {"type": "string", "enum": ["dra_luciana", "dr_lucas"]},
         "a_partir_de": {"type": "string", "description": "AAAA-MM-DD ou vazio para a partir de hoje"},
         "dias": {"type": "integer", "description": "quantos dias à frente (1 a 30)"}},
         "required": ["profissional", "a_partir_de", "dias"], "additionalProperties": False}},
    {"name": "agendar_consulta", "description": "Agenda a Consulta no TI Saúde em um horário que veio de buscar_horarios. Exige o id do paciente (de buscar_paciente ou criar_paciente).",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "id_paciente": {"type": "integer"}, "profissional": {"type": "string", "enum": ["dra_luciana", "dr_lucas"]},
         "data": {"type": "string", "description": "AAAA-MM-DD"}, "hora": {"type": "string", "description": "HH:MM"}},
         "required": ["id_paciente", "profissional", "data", "hora"], "additionalProperties": False}},
    {"name": "consultar_agendamento", "description": "Lê no TI Saúde o estado REAL da consulta agendada nesta conversa (data, hora, profissional, status). Chame SEMPRE que o lead falar da consulta marcada (quando é, confirmar, trocar, desmarcar, 'está marcada?') ANTES de responder. Nunca afirme nada sobre o agendamento sem esta consulta.",
     "strict": True, "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
    {"name": "reagendar", "description": "Muda data/hora de uma consulta que a Celeste agendou. O novo horário deve vir de buscar_horarios.",
     "strict": True, "input_schema": {"type": "object", "properties": {"id_agendamento": {"type": "integer"}, "data": {"type": "string"}, "hora": {"type": "string"}},
                                      "required": ["id_agendamento", "data", "hora"], "additionalProperties": False}},
    {"name": "cancelar", "description": "Desmarca uma consulta que a Celeste agendou. SÓ pode ser chamada depois de: (1) perguntar ao lead o motivo, (2) oferecer uma solução para o motivo (remarcar, valor, dúvida) com escassez, e (3) o lead confirmar que mesmo assim quer cancelar. Chamar antes disso devolve erro.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "id_agendamento": {"type": "integer"},
         "motivo_do_lead": {"type": "string", "description": "o motivo que o LEAD disse, com as palavras dele (ex.: 'vai viajar na data', 'achou caro'); vazio se ele não disse"},
         "solucao_oferecida": {"type": "string", "description": "o que você ofereceu para resolver o motivo (ex.: 'remarcar para sexta 10h ou 15h')"},
         "lead_confirmou_apos_solucao": {"type": "boolean", "description": "true só se o lead, DEPOIS de ouvir a solução, repetiu que quer cancelar"}},
         "required": ["id_agendamento", "motivo_do_lead", "solucao_oferecida", "lead_confirmou_apos_solucao"], "additionalProperties": False}},
    {"name": "encaminhar_recepcao", "description": "Encerra a conversa encaminhando o lead à recepção humana (só nos 4 motivos permitidos). Avisa a equipe pelo WhatsApp com um resumo.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "motivo": {"type": "string", "enum": ["paciente_em_tratamento", "assunto_clinico", "reclamacao_reembolso", "pediu_pessoa"]},
         "resumo": {"type": "string", "description": "3 linhas para a recepção: quem é, o que quer, o que já foi dito"}},
         "required": ["motivo", "resumo"], "additionalProperties": False}},
    {"name": "registrar_opt_out", "description": "Marca que o lead não quer mais receber mensagens. Encerra a conversa.",
     "strict": True, "input_schema": {"type": "object", "properties": {"motivo": {"type": "string"}}, "required": ["motivo"], "additionalProperties": False}},
    {"name": "enviar_video", "description": "Envia um dos vídeos da clínica ao lead (uma vez por conversa cada).",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "video": {"type": "string", "enum": list(config.parametros()["videos"].keys())},   # catálogo = bloco `videos` do YAML
         "reenviar": {"type": "boolean", "description": "true só quando o lead CONFIRMOU que quer receber de novo um vídeo já enviado"}},
         "required": ["video", "reenviar"], "additionalProperties": False}},
    {"name": "enviar_antes_e_depois", "description": "Envia ao lead até 2 fotos reais de antes e depois de um caso daquela doença tratado na clínica (com legenda e aviso de que resultados variam). Só quando o lead pede resultados/casos dessa doença ou aceita a sua oferta. Uma vez por doença por conversa. As fotos saem DEPOIS dos seus balões; não diga que já enviou.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "doenca": {"type": "string", "enum": ["dermatite_seborreica", "psoriase_couro_cabeludo", "alopecia_areata", "alopecia_fibrosante_frontal",
                                                "lupus_couro_cabeludo", "alopecia_por_tracao", "foliculite_decalvante", "foliculite_dissecante",
                                                "liquen_plano_pilar", "alopecia_androgenetica_masculina", "alopecia_androgenetica_feminina",
                                                "efluvio_anageno", "tricotilomania", "disturbios_da_haste", "efluvio_telogeno"]}},
         "required": ["doenca"], "additionalProperties": False}},
    {"name": "enviar_antes_e_depois_tratamento", "description": "Envia até 2 fotos reais de antes e depois de um TRATAMENTO/tecnologia da clínica (com legenda dizendo que o tratamento é definido na consulta). SÓ quando o lead perguntou explicitamente por esse tratamento pelo nome ou perguntou 'quais tratamentos vocês fazem' (use 'geral'). Nunca para sugerir tratamento ao caso dele. Uma vez por tratamento por conversa. As fotos saem DEPOIS dos seus balões.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "tratamento": {"type": "string", "enum": list(config.parametros()["antes_e_depois_tratamentos"]["tratamentos"].keys()) + ["geral"]}},
         "required": ["tratamento"], "additionalProperties": False}},
    {"name": "sinalizar_revisao", "description": "Marca a conversa para a equipe revisar quando o lead perguntou algo que NÃO está na base de conhecimento (você não inventa a resposta). Registre a dúvida exata.",
     "strict": True, "input_schema": {"type": "object", "properties": {"duvida": {"type": "string", "description": "a pergunta do lead que ficou sem resposta na base"}},
                                      "required": ["duvida"], "additionalProperties": False}},
    {"name": "atualizar_status", "description": "Registra o resultado da conversa quando ela chega a um desfecho sem agendamento (ex.: Irá nos retornar, Achou caro).",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["Irá nos retornar", "Vamos retornar na data solicitada", "Achou caro", "Quer pelo convênio",
                                                "Mora em outro Estado", "Mora em outro País", "Está em outra clínica", "Receiteiro"]},
         "data_retorno": {"type": "string", "description": "AAAA-MM-DD se o lead pediu uma data; senão vazio"}},
         "required": ["status", "data_retorno"], "additionalProperties": False}},
]


def selecionar_opcoes(livres: list, n: int = 3) -> list:
    """Até n horários para oferecer, como as atendentes fazem: até 2 do primeiro dia e 1 do dia seguinte, completando em ordem."""
    livres = list(livres)
    if len(livres) <= n:
        return livres
    por_dia: dict = {}
    for l in livres:
        por_dia.setdefault(l["data"], []).append(l)
    dias = list(por_dia)
    escolha = por_dia[dias[0]][:2]
    if len(dias) > 1:
        escolha += por_dia[dias[1]][:1]
    for l in livres:
        if len(escolha) >= n:
            break
        if l not in escolha:
            escolha.append(l)
    return escolha[:n]


class Contexto:
    """Estado da conversa disponível às ferramentas (injetado pelo orquestrador)."""
    def __init__(self, conversa: dict, telefone: str, tisaude: ts.TiSaude, viacep: Callable[[str], dict],
                 enviar_video: Callable[[str], str], avisar_recepcao: Callable[[str, str], None], atualizar: Callable[[dict], None],
                 enviar_imagem: "Callable[[str], str] | None" = None):
        self.conversa, self.telefone, self.ts = conversa, telefone, tisaude
        self.viacep, self.enviar_video, self.avisar_recepcao, self.atualizar = viacep, enviar_video, avisar_recepcao, atualizar
        self.enviar_imagem = enviar_imagem or (lambda chave: "sem-envio-de-imagem")
        self.encerrar = False


def _mesma_pessoa(nome_cadastro: str, nome_informado: str) -> bool:
    from celeste.ferramentas.tisaude import mesma_pessoa
    return mesma_pessoa(nome_cadastro, nome_informado)


def _nome_completo_valido(nome: str) -> tuple[bool, str]:
    from celeste.ferramentas.tisaude import nome_completo_valido
    return nome_completo_valido(nome)


def executar(nome: str, entrada: dict, ctx: Contexto) -> tuple[str, bool]:
    """Executa a ferramenta; retorna (resultado_json, is_error)."""
    try:
        r = _executar(nome, entrada, ctx)
        return json.dumps(r, ensure_ascii=False, default=str), False
    except Exception as e:  # o modelo recebe o erro e explica ao lead com naturalidade
        log.warning("ferramenta %s falhou: %s", nome, e)
        return json.dumps({"erro": str(e)}, ensure_ascii=False), True


def _executar(nome: str, e: dict, ctx: Contexto) -> Any:
    if nome == "buscar_paciente":
        cpf = re.sub(r"\D", "", e.get("cpf") or "")
        nome_c = (e.get("nome_completo") or "").strip()
        if cpf:
            if len(cpf) != 11:
                raise ValueError("CPF deve ter 11 dígitos; peça ao lead para conferir")
            p = ctx.ts.buscar_paciente(cpf=cpf)
            if not p:
                return {"encontrado": False, "aviso": "nenhum paciente com este CPF; confira os dígitos com o lead e, se estiverem certos, faça o pré-cadastro e chame criar_paciente"}
        elif nome_c:
            p = ctx.ts.buscar_paciente(celular=ctx.telefone, nome=nome_c)
            if not p:
                return {"encontrado": False, "aviso": "não localizei com segurança pelo nome; peça o CPF ao lead e chame buscar_paciente de novo"}
        else:
            raise ValueError("informe o CPF (ou o nome completo) do lead")
        ctx.atualizar({"id_paciente_tisaude": p["id"], "paciente_tisaude_nome": p.get("nome"), "identidade_confirmada": True, "pacientes_mesmo_numero": []})
        return {"encontrado": True, "id": p["id"], "nome": p.get("nome"), "aviso": "é este o paciente; use este id para agendar"}

    if nome == "atualizar_cadastro":
        idp = ctx.conversa.get("id_paciente_tisaude")
        if not idp:
            raise ValueError("paciente ainda não identificado: localize pelo CPF (buscar_paciente) antes de alterar o cadastro")
        if ctx.conversa.get("pacientes_mesmo_numero") and not ctx.conversa.get("identidade_confirmada"):
            raise ValueError("este número tem vários cadastros: confirme a identidade pelo CPF (buscar_paciente) antes de alterar")
        mapa = {"cpf": "cpf", "email": "email", "celular": "celular", "nascimento": "nascimento", "sexo": "sexo", "como_conheceu": "indicado",
                "complemento": "apt", "numero": "n", "responsavel": "responsavel", "parentesco_responsavel": "parentesco_responsavel",
                "cpf_responsavel": "cpf_responsavel"}
        mud = {mapa[k]: str(v).strip() for k, v in e.items() if k in mapa and str(v or "").strip()}
        if str(e.get("cep") or "").strip():
            end = ctx.viacep(e["cep"])
            if not end:
                raise ValueError("CEP inválido: peça ao lead para conferir o CEP")
            if not str(e.get("numero") or "").strip():
                raise ValueError("CEP novo exige o número da residência")
            mud.update({"cep": e["cep"], **end})
        if not mud:
            raise ValueError("nenhum campo para atualizar")
        r = ctx.ts.atualizar_paciente(int(idp), mud)
        campos_conv = {"cadastro_atualizado_em": datetime.now(timezone.utc), "cadastro_campos_atualizados": sorted(mud)}
        if "nome" in mud:
            campos_conv["nome"] = mud["nome"]
        if "cpf" in mud and ctx.conversa.get("cadastro_generico"):
            campos_conv["cadastro_generico"] = False
        ctx.atualizar(campos_conv)
        return {"ok": True, "atualizado": sorted(mud), "id": r.get("id", idp), "aviso": "cadastro atualizado; confirme ao lead o que foi alterado"}

    if nome == "criar_paciente":
        ok, motivo = _nome_completo_valido(e["nome"])
        if not ok:
            raise ValueError(motivo)
        if e.get("dados_genericos"):
            g = config.parametros().get("cadastro_generico") or {}
            e = {**e, "cpf": g.get("cpf", "") or "", "nascimento": e.get("nascimento") or g.get("nascimento", ""), "email": g.get("email", ""),
                 "como_conheceu": g.get("indicado", ""), "cep": g.get("cep", ""), "numero": g.get("numero", ""), "complemento": g.get("complemento", "")}
        elif not re.sub(r"\D", "", e.get("cpf") or ""):
            raise ValueError("CPF não informado: peça o CPF; só cadastre sem CPF com dados_genericos=true, depois de o lead recusar os dados após UMA insistência")
        if ctx.conversa.get("id_paciente_tisaude") and (ctx.conversa.get("identidade_confirmada")
                                                        or _mesma_pessoa(ctx.conversa.get("paciente_tisaude_nome") or "", e["nome"])):
            return {"id": ctx.conversa["id_paciente_tisaude"], "aviso": "paciente já existia; use este id"}
        end = ctx.viacep(e["cep"])
        if not end:
            raise ValueError("CEP inválido: peça ao lead para conferir o CEP")
        if _menor(e["nascimento"]) and not (e.get("responsavel") and e.get("cpf_responsavel")):
            raise ValueError("menor de idade: colete nome, parentesco e CPF do responsável antes de cadastrar")
        existente = ctx.ts.buscar_paciente(cpf=e["cpf"]) if re.sub(r"\D", "", e.get("cpf") or "") else None   # CPF já cadastrado: adota em vez de duplicar
        if isinstance(existente, dict) and existente.get("id"):
            ctx.atualizar({"id_paciente_tisaude": existente["id"], "paciente_tisaude_nome": existente.get("nome"), "identidade_confirmada": True})
            return {"id": existente["id"], "aviso": f"este CPF já está cadastrado como {existente.get('nome')}; use este id para agendar (não criei cadastro novo)"}
        p = ctx.ts.criar_paciente({"nome": e["nome"], "cpf": e["cpf"], "nascimento": e["nascimento"], "sexo": e["sexo"],
                                   "celular": ctx.telefone, "email": e["email"], "indicado": e["como_conheceu"], "cep": e["cep"],
                                   "n": e["numero"], "apt": e.get("complemento", ""), **end,
                                   "responsavel": e.get("responsavel", ""), "parentesco_responsavel": e.get("parentesco_responsavel", ""),
                                   "cpf_responsavel": e.get("cpf_responsavel", "")})
        ctx.atualizar({"id_paciente_tisaude": p["id"], "nome": e["nome"], "cadastro_generico": bool(e.get("dados_genericos"))})
        if e.get("dados_genericos"):
            return {"id": p["id"], "aviso": "cadastro feito com dados genéricos e sem CPF; depois de agendar, avise o lead: " + str((config.parametros().get("cadastro_generico") or {}).get("aviso_ao_lead", ""))}
        return {"id": p["id"]}

    if nome == "buscar_horarios":
        inicio = date.fromisoformat(e["a_partir_de"]) if e.get("a_partir_de") else None
        dias = max(1, min(int(e.get("dias") or 14), 30))
        livres = ctx.ts.buscar_horarios(e["profissional"], dias=dias, a_partir_de=inicio)
        from celeste.comum import config as _cfg
        n = int(((_cfg.parametros().get("ia") or {}).get("horarios") or {}).get("opcoes_por_vez", 3))
        oferecer = selecionar_opcoes(livres, n)   # 14/10/2026: a clínica pediu no máximo 3 por vez (a Celeste listava 12)
        ja = list(ctx.conversa.get("horarios_oferecidos") or [])
        novos = [f"{l['data']} {l['hora']}" for l in oferecer if f"{l['data']} {l['hora']}" not in ja]
        ctx.conversa["horarios_oferecidos"] = (ja + novos)[-60:]
        ctx.atualizar({"horarios_oferecidos": ctx.conversa["horarios_oferecidos"]})
        return {"profissional": e["profissional"], "livres": oferecer, "ha_mais_no_periodo": len(livres) > len(oferecer),
                "aviso": "ofereça só estes; se o lead quiser outro dia ou horário, chame de novo com a_partir_de"}

    if nome == "agendar_consulta":
        chave = f"{e['data']} {e['hora']}"
        if chave not in (ctx.conversa.get("horarios_oferecidos") or []):
            raise ValueError("horário não veio de buscar_horarios; chame buscar_horarios e ofereça só o que está livre")
        obs = f"Agendado pela Celeste (IA) via WhatsApp | frente {ctx.conversa.get('frente')} | conversa {ctx.conversa.get('id')}"
        a = ctx.ts.agendar_consulta(id_paciente=int(e["id_paciente"]), profissional_id=e["profissional"],
                                    data=date.fromisoformat(e["data"]), hora=e["hora"], observacoes=obs)
        ctx.atualizar({"id_agendamento_tisaude": a["id"], "status": "Agendado", "agendado_em": datetime.now(timezone.utc),
                       "agendamento": {"data": e["data"], "hora": e["hora"], "profissional": e["profissional"]}})
        return {"id_agendamento": a["id"], "data": e["data"], "hora": e["hora"], "status": ts.STATUS.get(a.get("status"))}

    if nome == "consultar_agendamento":
        ida = ctx.conversa.get("id_agendamento_tisaude")
        if not ida:
            return {"agendada": False, "aviso": "não há consulta agendada nesta conversa"}
        d = ctx.ts.detalhe_agendamento(int(ida))
        cal = {36: "dr_lucas", 1: "dra_luciana"}
        prof_nome = {"dr_lucas": "Dr. Lucas Vieira", "dra_luciana": "Dra. Luciana Passoni"}
        ag = dict(ctx.conversa.get("agendamento") or {})
        prof = cal.get(d.get("idCalendario"), ag.get("profissional"))
        status = "Desmarcado" if (d.get("deletado") or d.get("status") == -2) else ts.STATUS.get(d.get("status"), str(d.get("status")))
        ag.update({"data": str(d.get("data") or ag.get("data") or "")[:10], "hora": str(d.get("hora") or ag.get("hora") or "")[:5], "profissional": prof, "status": status})
        ctx.atualizar({"agendamento": ag})
        return {"agendada": status not in ("Desmarcado",), "id_agendamento": int(ida), "data": ag["data"], "hora": ag["hora"],
                "profissional": prof_nome.get(prof, prof), "status": status, "aviso": "responda ao lead com exatamente estes dados"}

    if nome == "reagendar":
        chave = f"{e['data']} {e['hora']}"
        if chave not in (ctx.conversa.get("horarios_oferecidos") or []):
            raise ValueError("horário não veio de buscar_horarios")
        a = ctx.ts.reagendar(int(e["id_agendamento"]), date.fromisoformat(e["data"]), e["hora"])
        ctx.atualizar({"agendamento": {"data": e["data"], "hora": e["hora"]}, "status": "Agendado"})
        return {"ok": True, "data": a.get("data"), "hora": a.get("hora")}

    if nome == "cancelar":
        motivo = (e.get("motivo_do_lead") or "").strip()
        solucao = (e.get("solucao_oferecida") or "").strip()
        if len(motivo) < 4:
            raise ValueError("ainda não há motivo: pergunte ao lead com empatia o que aconteceu antes de cancelar")
        if len(solucao) < 4:
            raise ValueError("ainda não houve tentativa de solução: ofereça uma saída para o motivo (remarcar com horários de buscar_horarios, valor, dúvida) com escassez, e só cancele se o lead insistir")
        if not e.get("lead_confirmou_apos_solucao"):
            raise ValueError("o lead ainda não confirmou o cancelamento depois da solução oferecida; aguarde a resposta dele")
        ctx.ts.cancelar(int(e["id_agendamento"]), f"{motivo} | oferecido: {solucao}")
        ctx.atualizar({"status": "Irá nos retornar", "id_agendamento_tisaude": None, "motivo_cancelamento": motivo, "solucao_oferecida": solucao,
                       "horarios_oferecidos": []})
        return {"ok": True}

    if nome == "encaminhar_recepcao":
        ctx.avisar_recepcao(e["motivo"], e["resumo"])
        ctx.atualizar({"status": "Encaminhado à recepção", "motivo_encaminhamento": e["motivo"], "aberta": False})
        ctx.encerrar = True
        return {"ok": True, "aviso": "botão 'Falar com Recepção' será enviado automaticamente após suas mensagens; não escreva link nem número"}

    if nome == "registrar_opt_out":
        ctx.atualizar({"status": "Não quer (opt-out)", "aberta": False, "opt_out": True, "opt_out_em": datetime.now(timezone.utc), "horarios_oferecidos": []})
        ctx.encerrar = True
        return {"ok": True}

    if nome == "enviar_video":
        enviados = ctx.conversa.get("videos_enviados") or []
        if e["video"] in enviados and not e.get("reenviar"):
            return {"ok": False, "aviso": "vídeo já enviado nesta conversa; confirme com o lead se ele quer de novo e, se sim, chame com reenviar=true"}
        wamid = ctx.enviar_video(e["video"])
        ctx.atualizar({"videos_enviados": enviados + [e["video"]]})
        return {"ok": True, "wamid": wamid}

    if nome == "enviar_antes_e_depois":
        enviadas = ctx.conversa.get("imagens_enviadas") or []
        if e["doenca"] in enviadas:
            return {"ok": False, "aviso": "fotos dessa doença já enviadas nesta conversa; não reenvie, indique a seção de resultados do site"}
        wamid = ctx.enviar_imagem(e["doenca"])
        ctx.atualizar({"imagens_enviadas": enviadas + [e["doenca"]]})
        return {"ok": True, "wamid": wamid, "aviso": "as fotos saem depois dos seus balões, com legenda; não diga que já enviou"}

    if nome == "enviar_antes_e_depois_tratamento":
        enviadas = ctx.conversa.get("imagens_tratamento_enviadas") or []
        if e["tratamento"] in enviadas:
            return {"ok": False, "aviso": "fotos desse tratamento já enviadas nesta conversa; não reenvie"}
        wamid = ctx.enviar_imagem("tratamento:" + e["tratamento"])
        ctx.atualizar({"imagens_tratamento_enviadas": enviadas + [e["tratamento"]]})
        return {"ok": True, "wamid": wamid, "aviso": "as fotos saem depois dos seus balões, com legenda; não diga que já enviou"}

    if nome == "sinalizar_revisao":
        pend = list(ctx.conversa.get("duvidas_pendentes") or []) + [e["duvida"][:300]]
        ctx.atualizar({"revisar": True, "revisar_motivo": "dúvida fora da base de conhecimento", "duvidas_pendentes": pend})
        return {"ok": True, "aviso": "equipe avisada; diga ao lead que vai confirmar e retornar"}

    if nome == "atualizar_status":
        status = e["status"]
        if status == "Vamos retornar na data solicitada" and not e.get("data_retorno"):
            status = "Irá nos retornar"   # sem data concreta, cai na cadência padrão
        campos: dict = {"status": status}
        if e.get("data_retorno"):
            campos["proximo_recontato_em"] = e["data_retorno"]
        campos["horarios_oferecidos"] = []   # assunto fechado sem agendamento: lista antiga não gera lembrete errado (incidente 13/10)
        ctx.atualizar(campos)
        return {"ok": True}

    raise ValueError(f"ferramenta desconhecida: {nome}")


def _menor(nascimento_br: str) -> bool:
    try:
        d = datetime.strptime(nascimento_br, "%d/%m/%Y").date()
    except ValueError:
        return False
    hoje = date.today()
    return (hoje.year - d.year - ((hoje.month, hoje.day) < (d.month, d.day))) < 18
