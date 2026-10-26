# -*- coding: utf-8 -*-
"""Portão antes do envio (aprovado pela clínica em 26/10/2026).

Um modelo pequeno (Haiku) revisa a resposta da Celeste ANTES de ela ir ao WhatsApp, só quando a resposta é de risco:
cita valor, data, hora, dia da semana, doença, tratamento, medicação, desconto, política. Ele recebe a base de conhecimento
da clínica (única fonte de fatos permitida), a conversa recente, o que as ferramentas devolveram nesta vez e os balões.
Devolve JSON {"aprovado": bool, "motivo": str}. Reprovou: o motor regera uma vez com o motivo; reprovou de novo: não envia,
manda a frase de fallback e sinaliza revisão. Erro no revisor = aprova (nunca trava o atendimento por causa do revisor).
Custo: ~4 mil tokens de entrada no Haiku por revisão, com a base em cache; centavos por conversa.
"""
from __future__ import annotations

import json
import logging
import re
from types import SimpleNamespace
from typing import Any

from celeste.comum import config
from celeste.orquestrador import prompt

log = logging.getLogger(__name__)

_GATILHOS = re.compile(
    r"(r\$|\d+[.,]\d{2}\b|\b\d{1,2}\s?h(\d{2})?\b|\b\d{1,2}:\d{2}\b|\b\d{1,2}/\d{1,2}\b|%|"
    r"\b(segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo|feriado)\b|"
    r"\b(desconto|promo[çc][ãa]o|encaixe|online|on-line|parcel\w*|conv[êe]nio|reembolso|garant\w*|cura\b|curar|"
    r"diagn[óo]stico|receita|medica[çc][ãa]o|rem[ée]dio|minoxidil|finasterida|dose|mg\b|alopecia|efl[úu]vio|areata|"
    r"transplante|bi[óo]psia|exame|laser|mmp|prp|intradermo|fotona|cancel\w*|desmarc\w*|remarc\w*|confirmad\w*|"
    r"agendad\w*|marcad\w*|unidade|filial)\b)", re.I)

CHECKLIST = """Você é o revisor interno da Celeste, concierge virtual da Passoni Clinic (clínica de tricologia em São Paulo).
Sua única tarefa: decidir se a resposta abaixo pode ser enviada ao lead pelo WhatsApp. Seja rigoroso com fatos e permissivo com estilo.

REPROVE (aprovado=false) se a resposta tiver QUALQUER um destes problemas:
1. Fato que não está na base de conhecimento nem veio de ferramenta: valor, prazo, duração, cidade ou unidade, procedimento, nome, promessa.
2. Horário, data ou profissional de consulta que não apareceu nos resultados das ferramentas desta vez (a Celeste só pode oferecer o que a agenda devolveu).
3. Diagnóstico, orientação de tratamento, de medicação ou de dose para o lead.
4. Promessa fora da política: desconto, encaixe fora da grade, consulta online, tratamento sem consulta, parcelamento da consulta, atendimento em fim de semana ou feriado.
5. Afirmação de que uma consulta foi marcada, remarcada, cancelada ou confirmada sem a ferramenta correspondente ter devolvido sucesso nesta vez ou antes na conversa.
6. Marcação técnica, código, JSON, texto em outra língua ou conteúdo que claramente não é mensagem para um lead.

NÃO reprove por: tom, emoji, tamanho, repetição leve, ordem das frases, uso de "você", preferência de palavras. Não reprove por informação que ESTÁ na base de conhecimento.
Valor da consulta e grade de atendimento estão na base; se a resposta repete o que está lá, está certo.

Responda SOMENTE com JSON em uma linha: {"aprovado": true} ou {"aprovado": false, "motivo": "frase curta dizendo o que está errado e o que seria o certo"}."""


def _cfg() -> dict:
    return config.parametros().get("portao") or {}


def ativo() -> bool:
    return bool(_cfg().get("ativo"))


def arriscada(baloes: list[str]) -> bool:
    """A resposta cita algo que vale a pena conferir? Só essas passam pelo revisor (custo e latência)."""
    return bool(_GATILHOS.search(" ".join(baloes or [])))


def _texto(conteudo: Any) -> str:
    if isinstance(conteudo, str):
        return conteudo
    partes = []
    for b in conteudo or []:
        t = b.get("type") if isinstance(b, dict) else getattr(b, "type", None)
        if t == "text":
            partes.append(b.get("text") if isinstance(b, dict) else getattr(b, "text", ""))
        elif t == "image":
            partes.append("[imagem]")
        elif t == "tool_use":
            nome = b.get("name") if isinstance(b, dict) else getattr(b, "name", "")
            partes.append(f"[chamou a ferramenta {nome}]")
        elif t == "tool_result":
            c = b.get("content") if isinstance(b, dict) else getattr(b, "content", "")
            partes.append(f"[resultado de ferramenta: {str(c)[:600]}]")
    return " ".join(p for p in partes if p)


def contexto_recente(messages: list[dict], n: int = 8) -> str:
    linhas = []
    for m in messages[-n:]:
        quem = "LEAD" if m.get("role") == "user" else "CELESTE"
        t = _texto(m.get("content")).strip()
        if t:
            linhas.append(f"{quem}: {t[:700]}")
    return "\n".join(linhas) or "(sem histórico)"


def _base_conhecimento() -> str:
    p = config.parametros()
    txt = (config.RAIZ / "knowledge/01-base-conhecimento-clinica.md").read_text(encoding="utf-8")
    return prompt.renderizar(txt, p)


def _parse(texto: str) -> tuple[bool, str] | None:
    m = re.search(r"\{.*\}", texto or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if "aprovado" not in d:
        return None
    return bool(d["aprovado"]), str(d.get("motivo") or "").strip()


def avaliar(cliente, messages: list[dict], baloes: list[str], ferramentas_usadas: list[dict]) -> tuple[bool, str, Any]:
    """(aprovado, motivo, uso). Erro ou resposta inválida do revisor → aprovado=True (fail-open), com motivo informativo."""
    cfg = _cfg()
    ferr = "\n".join(f"- {f.get('nome')}: {str(f.get('saida'))[:500]}" for f in (ferramentas_usadas or []) if f.get("nome") != "portao") or "(nenhuma)"
    user = (f"CONVERSA RECENTE:\n{contexto_recente(messages)}\n\nFERRAMENTAS CHAMADAS NESTA VEZ (resultados reais do sistema):\n{ferr}\n\n"
            f"RESPOSTA A REVISAR (cada linha é um balão que iria ao lead):\n" + "\n".join(f"- {b}" for b in baloes) + "\n\nJSON:")
    system = [{"type": "text", "text": CHECKLIST + "\n\nBASE DE CONHECIMENTO DA CLÍNICA (única fonte de fatos permitida):\n" + _base_conhecimento(),
               "cache_control": {"type": "ephemeral"}}]
    try:
        resp = cliente.messages.create(model=cfg.get("modelo", "claude-haiku-5-5"), max_tokens=int(cfg.get("max_tokens", 250)),
                                       system=system, messages=[{"role": "user", "content": user}])
    except Exception as e:   # noqa: BLE001
        log.warning("portão: revisor falhou (%s); resposta liberada", e)
        return True, f"revisor indisponível: {type(e).__name__}", None
    texto = "".join(getattr(b, "text", "") for b in getattr(resp, "content", []) or [])
    u = getattr(resp, "usage", None)
    uso = SimpleNamespace(input_tokens=int(getattr(u, "input_tokens", 0) or 0), output_tokens=int(getattr(u, "output_tokens", 0) or 0),
                          cache_read_input_tokens=int(getattr(u, "cache_read_input_tokens", 0) or 0),
                          cache_creation_input_tokens=int(getattr(u, "cache_creation_input_tokens", 0) or 0))
    r = _parse(texto)
    if r is None:
        log.warning("portão: resposta do revisor sem JSON válido (%r); resposta liberada", (texto or "")[:160])
        return True, "revisor sem resposta válida", uso
    return r[0], r[1] or ("ok" if r[0] else "reprovado sem motivo"), uso
