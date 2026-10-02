# -*- coding: utf-8 -*-
"""Ferramentas que a Celeste pode chamar (schemas estritos) e sua execução.

Os guarda-corpos moram aqui e no cliente TI Saúde, não no prompt.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Callable

from celeste.comum import config
from celeste.ferramentas import tisaude as ts

log = logging.getLogger(__name__)

FERRAMENTAS: list[dict] = [
    {"name": "buscar_paciente", "description": "Procura o lead no TI Saúde pelo telefone do WhatsApp e/ou CPF, para não duplicar cadastro. Use antes de criar_paciente.",
     "strict": True, "input_schema": {"type": "object", "properties": {"cpf": {"type": "string", "description": "CPF do lead, se já informado; senão string vazia"}},
                                      "required": ["cpf"], "additionalProperties": False}},
    {"name": "criar_paciente", "description": "Cria o cadastro do lead no TI Saúde. Só chame com TODOS os campos coletados; nunca para quem já existe.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "nome": {"type": "string"}, "cpf": {"type": "string"}, "nascimento": {"type": "string", "description": "dd/mm/AAAA"},
         "sexo": {"type": "string", "enum": ["Masculino", "Feminino"]}, "email": {"type": "string"},
         "como_conheceu": {"type": "string", "description": "valor do sistema para 'Encaminhado por' (ex.: CAMPANHA DE MENSAGENS, INSTAGRAM DRA. LUCIANA, GOOGLE)"},
         "cep": {"type": "string"}, "numero": {"type": "string"}, "complemento": {"type": "string"},
         "responsavel": {"type": "string", "description": "nome do responsável se menor de idade; senão vazio"},
         "parentesco_responsavel": {"type": "string", "description": "Mãe, Pai, Irmão, Irmã, Tio, Tia, Padrinho, Madrinha, Primo, Prima, Outro ou vazio"},
         "cpf_responsavel": {"type": "string"}},
         "required": ["nome", "cpf", "nascimento", "sexo", "email", "como_conheceu", "cep", "numero", "complemento", "responsavel", "parentesco_responsavel", "cpf_responsavel"],
         "additionalProperties": False}},
    {"name": "buscar_horarios", "description": "Lista horários LIVRES de consulta para um profissional nos próximos dias. Só ofereça horários vindos daqui.",
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
    {"name": "reagendar", "description": "Muda data/hora de uma consulta que a Celeste agendou. O novo horário deve vir de buscar_horarios.",
     "strict": True, "input_schema": {"type": "object", "properties": {"id_agendamento": {"type": "integer"}, "data": {"type": "string"}, "hora": {"type": "string"}},
                                      "required": ["id_agendamento", "data", "hora"], "additionalProperties": False}},
    {"name": "cancelar", "description": "Desmarca uma consulta que a Celeste agendou, a pedido do lead.",
     "strict": True, "input_schema": {"type": "object", "properties": {"id_agendamento": {"type": "integer"}, "motivo": {"type": "string"}},
                                      "required": ["id_agendamento", "motivo"], "additionalProperties": False}},
    {"name": "encaminhar_recepcao", "description": "Encerra a conversa encaminhando o lead à recepção humana (só nos 4 motivos permitidos). Avisa a equipe pelo WhatsApp com um resumo.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "motivo": {"type": "string", "enum": ["paciente_em_tratamento", "assunto_clinico", "reclamacao_reembolso", "pediu_pessoa"]},
         "resumo": {"type": "string", "description": "3 linhas para a recepção: quem é, o que quer, o que já foi dito"}},
         "required": ["motivo", "resumo"], "additionalProperties": False}},
    {"name": "registrar_opt_out", "description": "Marca que o lead não quer mais receber mensagens. Encerra a conversa.",
     "strict": True, "input_schema": {"type": "object", "properties": {"motivo": {"type": "string"}}, "required": ["motivo"], "additionalProperties": False}},
    {"name": "enviar_video", "description": "Envia um dos vídeos da clínica ao lead (uma vez por conversa cada).",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "video": {"type": "string", "enum": ["institucional", "dra_luciana", "dr_lucas", "boas_vindas_consulta", "como_funciona_consulta", "casos_sucesso", "tecnologias", "sobre_clinica"]},
         "reenviar": {"type": "boolean", "description": "true só quando o lead CONFIRMOU que quer receber de novo um vídeo já enviado"}},
         "required": ["video", "reenviar"], "additionalProperties": False}},
    {"name": "atualizar_status", "description": "Registra o resultado da conversa quando ela chega a um desfecho sem agendamento (ex.: Irá nos retornar, Achou caro).",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["Irá nos retornar", "Vamos retornar na data solicitada", "Achou caro", "Quer pelo convênio",
                                                "Mora em outro Estado", "Mora em outro País", "Está em outra clínica", "Receiteiro"]},
         "data_retorno": {"type": "string", "description": "AAAA-MM-DD se o lead pediu uma data; senão vazio"}},
         "required": ["status", "data_retorno"], "additionalProperties": False}},
]


class Contexto:
    """Estado da conversa disponível às ferramentas (injetado pelo orquestrador)."""
    def __init__(self, conversa: dict, telefone: str, tisaude: ts.TiSaude, viacep: Callable[[str], dict],
                 enviar_video: Callable[[str], str], avisar_recepcao: Callable[[str, str], None], atualizar: Callable[[dict], None]):
        self.conversa, self.telefone, self.ts = conversa, telefone, tisaude
        self.viacep, self.enviar_video, self.avisar_recepcao, self.atualizar = viacep, enviar_video, avisar_recepcao, atualizar
        self.encerrar = False


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
        p = ctx.ts.buscar_paciente(celular=ctx.telefone, cpf=e.get("cpf", ""))
        if p:
            ctx.atualizar({"id_paciente_tisaude": p["id"]})
            return {"encontrado": True, "id": p["id"], "nome": p.get("nome")}
        return {"encontrado": False}

    if nome == "criar_paciente":
        if ctx.conversa.get("id_paciente_tisaude"):
            return {"id": ctx.conversa["id_paciente_tisaude"], "aviso": "paciente já existia; use este id"}
        end = ctx.viacep(e["cep"])
        if not end:
            raise ValueError("CEP inválido: peça ao lead para conferir o CEP")
        if _menor(e["nascimento"]) and not (e.get("responsavel") and e.get("cpf_responsavel")):
            raise ValueError("menor de idade: colete nome, parentesco e CPF do responsável antes de cadastrar")
        p = ctx.ts.criar_paciente({"nome": e["nome"], "cpf": e["cpf"], "nascimento": e["nascimento"], "sexo": e["sexo"],
                                   "celular": ctx.telefone, "email": e["email"], "indicado": e["como_conheceu"], "cep": e["cep"],
                                   "n": e["numero"], "apt": e.get("complemento", ""), **end,
                                   "responsavel": e.get("responsavel", ""), "parentesco_responsavel": e.get("parentesco_responsavel", ""),
                                   "cpf_responsavel": e.get("cpf_responsavel", "")})
        ctx.atualizar({"id_paciente_tisaude": p["id"], "nome": e["nome"]})
        return {"id": p["id"]}

    if nome == "buscar_horarios":
        inicio = date.fromisoformat(e["a_partir_de"]) if e.get("a_partir_de") else None
        dias = max(1, min(int(e.get("dias") or 14), 30))
        livres = ctx.ts.buscar_horarios(e["profissional"], dias=dias, a_partir_de=inicio)
        ctx.atualizar({"horarios_oferecidos": [f"{l['data']} {l['hora']}" for l in livres[:60]]})
        return {"profissional": e["profissional"], "livres": livres[:40], "total": len(livres)}

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

    if nome == "reagendar":
        chave = f"{e['data']} {e['hora']}"
        if chave not in (ctx.conversa.get("horarios_oferecidos") or []):
            raise ValueError("horário não veio de buscar_horarios")
        a = ctx.ts.reagendar(int(e["id_agendamento"]), date.fromisoformat(e["data"]), e["hora"])
        ctx.atualizar({"agendamento": {"data": e["data"], "hora": e["hora"]}, "status": "Agendado"})
        return {"ok": True, "data": a.get("data"), "hora": a.get("hora")}

    if nome == "cancelar":
        ctx.ts.cancelar(int(e["id_agendamento"]), e.get("motivo", ""))
        ctx.atualizar({"status": "Irá nos retornar", "id_agendamento_tisaude": None})
        return {"ok": True}

    if nome == "encaminhar_recepcao":
        ctx.avisar_recepcao(e["motivo"], e["resumo"])
        ctx.atualizar({"status": "Encaminhado à recepção", "motivo_encaminhamento": e["motivo"], "aberta": False})
        ctx.encerrar = True
        return {"ok": True, "aviso": "botão 'Falar com Recepção' será enviado automaticamente após suas mensagens; não escreva link nem número"}

    if nome == "registrar_opt_out":
        ctx.atualizar({"status": "Não quer (opt-out)", "aberta": False, "opt_out": True, "opt_out_em": datetime.now(timezone.utc)})
        ctx.encerrar = True
        return {"ok": True}

    if nome == "enviar_video":
        enviados = ctx.conversa.get("videos_enviados") or []
        if e["video"] in enviados and not e.get("reenviar"):
            return {"ok": False, "aviso": "vídeo já enviado nesta conversa; confirme com o lead se ele quer de novo e, se sim, chame com reenviar=true"}
        wamid = ctx.enviar_video(e["video"])
        ctx.atualizar({"videos_enviados": enviados + [e["video"]]})
        return {"ok": True, "wamid": wamid}

    if nome == "atualizar_status":
        status = e["status"]
        if status == "Vamos retornar na data solicitada" and not e.get("data_retorno"):
            status = "Irá nos retornar"   # sem data concreta, cai na cadência padrão
        campos: dict = {"status": status}
        if e.get("data_retorno"):
            campos["proximo_recontato_em"] = e["data_retorno"]
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
