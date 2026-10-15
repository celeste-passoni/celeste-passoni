# -*- coding: utf-8 -*-
"""Links de referência (imprensa, artigos, site) com entrega determinística.

Incidente de 14/10/2026: o modelo redigitou um link longo da Longdom trocando uma palavra do slug e depois "se corrigiu"
na conversa. Links não podem ser digitados pelo modelo. Dois mecanismos:
1) no texto o modelo escreve o código [[ref:ID]] (os IDs estão no documento de referências); aqui ele vira o link exato;
2) se mesmo assim vier um link escrito à mão, ele é comparado com os links conhecidos do mesmo domínio e, se for quase igual
   (erro de digitação), é substituído pelo link certo.
"""
from __future__ import annotations

import difflib
import re
from functools import lru_cache

from celeste.comum import config

ARQUIVO = "04-referencias-imprensa-e-resultados.md"
_REF = re.compile(r"\[\[ref:([a-z0-9\-]+)\]\]")
_LINHA = re.compile(r"\[\[ref:([a-z0-9\-]+)\]\][^\n]*?(https?://[^\s\)\]]+)")
_URL = re.compile(r"https?://[^\s\)\]>,]+")


@lru_cache(maxsize=1)
def catalogo() -> dict[str, str]:
    """ID → URL, lido do documento de referências (cada link anotado com [[ref:ID]])."""
    texto = (config.RAIZ / "knowledge" / ARQUIVO).read_text(encoding="utf-8")
    return {m.group(1): m.group(2).rstrip(".,;") for m in _LINHA.finditer(texto)}


def _dominio(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower()


def corrigir_url(url: str, conhecidas: dict[str, str] | None = None) -> str:
    """Devolve o link conhecido mais parecido (mesmo domínio, semelhança ≥ 0,9); senão o próprio."""
    conhecidas = conhecidas if conhecidas is not None else catalogo()
    limpo = url.rstrip(".,;)")
    if limpo in conhecidas.values():
        return limpo
    candidatas = [u for u in conhecidas.values() if _dominio(u) == _dominio(limpo)]
    melhor = difflib.get_close_matches(limpo, candidatas, n=1, cutoff=0.9)
    return melhor[0] if melhor else limpo


def resolver(texto: str, conhecidas: dict[str, str] | None = None) -> str:
    """Troca [[ref:ID]] pelo link exato e conserta links digitados à mão. Código desconhecido vira texto vazio (nunca link inventado)."""
    conhecidas = conhecidas if conhecidas is not None else catalogo()
    texto = _REF.sub(lambda m: conhecidas.get(m.group(1), ""), texto)
    texto = _URL.sub(lambda m: corrigir_url(m.group(0), conhecidas) + m.group(0)[len(m.group(0).rstrip(".,;)")):], texto)
    return re.sub(r"[ \t]{2,}", " ", texto).strip()
