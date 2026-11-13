# -*- coding: utf-8 -*-
"""Nome do lead nas mensagens fixas: só nome de pessoa (clínica, 13/11/2026).

Caso real: o perfil do WhatsApp era "Deus É Fiel"; o T1 saiu "Oi, Deus!" e o lembrete "Aguardo seu retorno, Deus! 💛".
O nome do cadastro vem do perfil do WhatsApp e muitas vezes é frase, empresa, cargo, apelido de perfil, emoji ou o próprio
telefone. Regra da clínica: se não for nome de pessoa, a mensagem sai SEM nome; o nome só entra quando a Celeste pergunta
com quem fala e o lead responde (`registrar_nome` → `nome_tratamento`).

Critério: o primeiro nome precisa estar em `nomes_validos.txt` (primeiros nomes e apelidos da base da clínica, revisados
um a um, mais nomes comuns). Lista fechada de propósito: na dúvida, a mensagem sai sem nome, o que nunca soa errado.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

_LETRAS = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
# palavra logo depois do primeiro nome que denuncia frase ("Vitória Em Cristo", "Graça Para Todos"), não nome completo
_FRASE = {"eh", "em", "no", "na", "nos", "para", "pra", "com", "sem", "que", "te", "me", "meu", "minha", "so", "sou", "esta", "ta", "the", "and", "of"}
# em qualquer posição, salvo depois de "de"/"do" ("Maria de Deus" é nome; "Glória a Deus" não)
_SAGRADO = {"deus", "jeova", "cristo", "senhor"}


def _chave(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()


@lru_cache(maxsize=1)
def _validos() -> frozenset[str]:
    return frozenset(Path(__file__).with_name("nomes_validos.txt").read_text(encoding="utf-8").split())


def primeiro_nome_real(nome: str | None) -> str:
    """Primeiro nome do cadastro, capitalizado, se for nome de pessoa; senão "" (a mensagem sai sem nome)."""
    toks = _LETRAS.findall(unicodedata.normalize("NFKC", nome or ""))   # NFKC: fontes "enfeitadas" viram letras comuns
    while toks and (len(toks[0]) == 1 or _chave(toks[0]) in ("dr", "dra")):   # inicial ou título: "A. Carlos" → Carlos; "Dra Ana" → Ana
        toks = toks[1:]
    if not toks:
        return ""
    ch = [_chave(t) for t in toks]
    if ch[0] not in _validos():
        return ""
    if len(toks) > 1 and (ch[1] in _FRASE or toks[1].lower() == "é"):
        return ""
    if any(c in _SAGRADO and (i == 0 or ch[i - 1] not in ("de", "do")) for i, c in enumerate(ch)):
        return ""
    return toks[0].capitalize()


def nome_para_chamar(d: dict | None) -> str:
    """Como chamar o lead nas mensagens fixas (templates, lembretes, balões de script). `d` = conversa ou lead.
    1º o nome que o lead disse (`nome_tratamento`, gravado por registrar_nome); 2º o primeiro nome do cadastro, se for de pessoa."""
    d = d or {}
    dito = (d.get("nome_tratamento") or "").strip().split()
    if dito:
        return dito[0].title()
    return primeiro_nome_real(d.get("nome"))
