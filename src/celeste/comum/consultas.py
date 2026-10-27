# -*- coding: utf-8 -*-
"""Pacientes e consultas de uma conversa (decisão da clínica, 27/10/2026).

Um lead pode agendar para mais de uma pessoa (ele e o filho, por exemplo). A conversa guarda:
  pacientes: [{id, nome}]                      um cadastro por paciente, nunca reaproveitado para outra pessoa
  consultas: [{id_agendamento, id_paciente, paciente_nome, profissional, data, hora, status, agendado_em, rotinas}]
Cada consulta tem os próprios lembretes (rotinas: C48_em, C24_em, CHOJ_em, confirmado_em). Os campos antigos
(id_agendamento_tisaude, agendamento) continuam gravados com a PRÓXIMA consulta ativa, para o painel e o funil.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
PROFISSIONAL = {"dra_luciana": "Dra. Luciana Passoni", "dr_lucas": "Dr. Lucas Vieira"}
INATIVOS = {"desmarcado", "cancelado", "atendido", "falta", "faltou", "não compareceu"}


def formatar_dia(d: date) -> str:
    return f"{DIAS[d.weekday()]}, {d.strftime('%d/%m')}"


def formatar_hora(h: str) -> str:
    """'14:00' → '14h'; '14:30' → '14h30'."""
    h = (h or "").strip()[:5]
    if ":" not in h:
        return h
    hh, mm = h.split(":", 1)
    return f"{int(hh)}h" if mm == "00" else f"{int(hh)}h{mm}"


def primeiro_nome(nome: Optional[str]) -> str:
    return ((nome or "").strip().split() or [""])[0].title()


# ----------------------------------------------------------------- pacientes
def pacientes(conv: dict) -> list[dict]:
    """Lista de pacientes da conversa; conversas antigas (só id_paciente_tisaude) viram uma lista de um."""
    ps = conv.get("pacientes")
    if isinstance(ps, list):
        return [dict(p) for p in ps]
    # conversa antiga: o paciente do número só conta como identificado se foi confirmado (CPF/cadastro) ou se o nome bate
    # com o de quem fala; um cadastro achado só pelo telefone pode ser de outra pessoa da família
    idp, nome_ts = conv.get("id_paciente_tisaude"), conv.get("paciente_tisaude_nome") or ""
    if idp and (conv.get("identidade_confirmada") or not nome_ts
                or (primeiro_nome(conv.get("nome")) and primeiro_nome(conv.get("nome")).lower() in nome_ts.lower())):
        return [{"id": int(idp), "nome": nome_ts or conv.get("nome") or ""}]
    return []


def com_paciente(ps: list[dict], id_paciente: int, nome: Optional[str]) -> list[dict]:
    """Inclui (ou atualiza o nome de) um paciente na lista, sem duplicar."""
    saida, achou = [], False
    for p in ps:
        if int(p.get("id") or 0) == int(id_paciente):
            achou = True
            p = dict(p, nome=nome or p.get("nome") or "")
        saida.append(p)
    if not achou:
        saida.append({"id": int(id_paciente), "nome": nome or ""})
    return saida


def nome_do_paciente(conv: dict, id_paciente: int) -> str:
    for p in pacientes(conv):
        if int(p.get("id") or 0) == int(id_paciente):
            return p.get("nome") or ""
    return ""


# ----------------------------------------------------------------- consultas
def lista(conv: dict) -> list[dict]:
    """Consultas da conversa; conversas antigas (só id_agendamento_tisaude) viram uma lista de uma."""
    cs = conv.get("consultas")
    if isinstance(cs, list):
        return [dict(c, rotinas=dict(c.get("rotinas") or {})) for c in cs]
    ida = conv.get("id_agendamento_tisaude")
    if not ida:
        return []
    ag = conv.get("agendamento") or {}
    return [{"id_agendamento": int(ida), "id_paciente": conv.get("id_paciente_tisaude"),
             "paciente_nome": conv.get("paciente_tisaude_nome") or conv.get("nome") or "",
             "profissional": ag.get("profissional"), "data": ag.get("data"), "hora": ag.get("hora"),
             "status": ag.get("status") or "Marcado", "agendado_em": conv.get("agendado_em"),
             "rotinas": dict(conv.get("rotinas_consulta") or {})}]


def ativa(c: dict) -> bool:
    return str(c.get("status") or "").strip().lower() not in INATIVOS


def ativas(conv_ou_lista) -> list[dict]:
    cs = conv_ou_lista if isinstance(conv_ou_lista, list) else lista(conv_ou_lista)
    return sorted([c for c in cs if ativa(c)], key=lambda c: (str(c.get("data") or ""), str(c.get("hora") or "")))


def achar(cs: list[dict], id_agendamento: int) -> Optional[dict]:
    for c in cs:
        if int(c.get("id_agendamento") or 0) == int(id_agendamento):
            return c
    return None


def substituir(cs: list[dict], nova: dict) -> list[dict]:
    return [nova if int(c.get("id_agendamento") or 0) == int(nova["id_agendamento"]) else c for c in cs]


def campos(cs: list[dict]) -> dict:
    """O que gravar na conversa: a lista inteira + os campos antigos com a próxima consulta ativa (painel e funil)."""
    at = ativas(cs)
    if at:
        p = at[0]
        return {"consultas": cs, "id_agendamento_tisaude": p["id_agendamento"],
                "agendamento": {"data": p.get("data"), "hora": p.get("hora"), "profissional": p.get("profissional"), "status": p.get("status")}}
    return {"consultas": cs, "id_agendamento_tisaude": None}


def rotulo(c: dict, com_paciente: bool = True) -> str:
    """'Pedro, quinta-feira, 29/10, às 14h, com o Dr. Lucas Vieira' (para o modelo e para o histórico)."""
    try:
        dia = formatar_dia(date.fromisoformat(str(c.get("data"))[:10]))
    except (TypeError, ValueError):
        dia = str(c.get("data") or "data não registrada")
    prof = PROFISSIONAL.get(c.get("profissional"), c.get("profissional") or "")
    artigo = "a" if c.get("profissional") == "dra_luciana" else "o"
    base = f"{dia}, às {formatar_hora(str(c.get('hora') or ''))}" + (f", com {artigo} {prof}" if prof else "")
    pac = primeiro_nome(c.get("paciente_nome")) if com_paciente else ""
    return f"{pac}, {base}" if pac else base


def de_outra_pessoa(conv: dict, c: dict) -> bool:
    """A consulta é de alguém que não é quem está no WhatsApp (o nome da conversa)?"""
    pac, contato = primeiro_nome(c.get("paciente_nome")), primeiro_nome(conv.get("nome"))
    return bool(pac and contato and pac.lower() != contato.lower())
