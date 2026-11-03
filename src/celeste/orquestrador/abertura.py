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
# 03/11/2026 (caso Rute): depois do opt-out, "Obrigada"/"ok"/emoji não é assunto novo — resposta fixa de cortesia, sem modelo
_AGRADECIMENTOS = {"obrigado", "obrigada", "obg", "obrigadoo", "obrigadaa", "muito obrigado", "muito obrigada", "ok obrigado", "ok obrigada",
                   "obrigado viu", "obrigada viu", "valeu", "vlw", "agradeco", "agradecida", "agradecido", "gratidao", "grata", "grato",
                   "ta bom obrigado", "ta bom obrigada", "tudo bem obrigado", "tudo bem obrigada", "certo obrigado", "certo obrigada"}
_FECHAMENTOS = {"ok", "okay", "okk", "oks", "blz", "beleza", "ta", "ta bom", "tabom", "ta bem", "tudo bem", "certo", "entendi", "entendido",
                "combinado", "fechado", "tchau", "tchau tchau", "ate mais", "ate logo", "ate", "abraco", "abracos", "bjs", "beijos", "boa tarde",
                "bom dia", "boa noite", "de nada", "por nada", "imagina", "ok tchau", "ta bom tchau", "tudo bem tchau", "sim", "nao", "ta ok"}


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


def e_agradecimento_solto(texto: str) -> bool:
    """True se a mensagem é só um agradecimento ("Obrigada", "valeu", "obg 🙏")."""
    t = " ".join(w for w in _normalizar(texto).split() if w not in _NOMES_IA)
    return t in _AGRADECIMENTOS


def e_cortesia_solta(texto: str) -> bool:
    """True se a mensagem é só cortesia ou fechamento, sem assunto: agradecimento, "ok", "tchau", um emoji sozinho."""
    if e_agradecimento_solto(texto):
        return True
    t = " ".join(w for w in _normalizar(texto).split() if w not in _NOMES_IA)
    if not t:
        return bool((texto or "").strip())    # só emoji/pontuação ("👍", "🙏", "❤️")
    return t in _FECHAMENTOS


def baloes_abertura(nome_lead: str, texto_lead: str = "", nome_atendente: str = "Celeste") -> list[str]:
    """Os dois balões fixos do roteiro, exatamente como a Celeste já respondia (decisão da clínica: a apresentação não muda)."""
    primeiro = ((nome_lead or "").strip().split() or [""])[0].title()
    voc = f", {primeiro}" if primeiro else ""
    b1 = f"Olá{voc}, tudo bem?"
    b2 = f"É um prazer falar com você, aqui é a {nome_atendente}, concierge da Passoni Clinic, e estou aqui para te ajudar! 💛"
    return [b1, b2]
