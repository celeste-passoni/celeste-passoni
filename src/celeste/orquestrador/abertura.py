# -*- coding: utf-8 -*-
"""Abertura sem modelo (15/10/2026): um "oi" solto numa conversa nova recebe os dois balões fixos de apresentação.

A resposta a um cumprimento solto é sempre a mesma (regra do roteiro), então não há por que chamar o modelo: a resposta
sai em segundos e sem custo. Só vale para conversa que NÃO veio de template (quem veio do T1 já foi apresentado) e cuja
primeira mensagem é só um cumprimento. Qualquer outro conteúdo vai para o modelo como sempre.
"""
from __future__ import annotations

import re
import unicodedata

_SAUDACOES = {"oi", "oie", "oii", "oiii", "ola", "olaa", "opa", "eai", "e ai", "hello", "hi", "hey", "bom dia", "boa tarde", "boa noite",
              "tudo bem", "tudo bom", "td bem", "td bom", "oi tudo bem", "ola tudo bem", "oi tudo bom", "ola tudo bom", "bom dia tudo bem",
              "boa tarde tudo bem", "boa noite tudo bem", "boa"}
_NOMES_IA = {"celeste"}


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z ]+", " ", t)          # tira pontuação, emojis e números
    return re.sub(r"\s+", " ", t).strip()


def e_saudacao_solta(texto: str) -> bool:
    """True se a mensagem é só um cumprimento (com ou sem o nome da Celeste), sem assunto."""
    t = _normalizar(texto)
    if not t:
        return False
    palavras = [w for w in t.split() if w not in _NOMES_IA]
    t = " ".join(palavras)
    return t in _SAUDACOES


def baloes_abertura(nome_lead: str, texto_lead: str, nome_atendente: str = "Celeste") -> list[str]:
    """Os dois balões fixos do roteiro, com o cumprimento no mesmo tom do lead (bom dia / boa tarde / boa noite / olá)."""
    t = _normalizar(texto_lead)
    primeiro = ((nome_lead or "").strip().split() or [""])[0].title()
    voc = f", {primeiro}" if primeiro else ""
    if t.startswith("bom dia"):
        b1 = f"Bom dia{voc}! Tudo bem?"
    elif t.startswith("boa tarde"):
        b1 = f"Boa tarde{voc}! Tudo bem?"
    elif t.startswith("boa noite"):
        b1 = f"Boa noite{voc}! Tudo bem?"
    else:
        b1 = f"Olá{voc}, tudo bem?"
    b2 = f"É um prazer falar com você, aqui é a {nome_atendente}, concierge da Passoni Clinic, e estou aqui para te ajudar! 💛"
    return [b1, b2]
