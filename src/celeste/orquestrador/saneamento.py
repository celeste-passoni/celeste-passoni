# -*- coding: utf-8 -*-
"""Validação sem custo do texto gerado antes de ir para o lead (25/10/2026).

Caso real (Curti, 24/10): o modelo escreveu a chamada de ferramenta no próprio texto, no formato interno de marcação
(<invoke name="atualizar_status">...<parameter ...>...</invoke></function_calls>), em vez de usar o mecanismo
estruturado da API. O texto foi para o WhatsApp e as ferramentas não rodaram.

Aqui: (1) detecta a marcação, (2) extrai as chamadas escritas para o motor executá-las de verdade, (3) devolve o texto limpo.
Tudo em Python puro, sem chamada ao modelo.
"""
from __future__ import annotations

import html
import re

_INVOKE = re.compile(r"<invoke\s+name=\"([^\"]+)\"\s*>(.*?)</invoke>", re.S | re.I)
_PARAM = re.compile(r"<parameter\s+name=\"([^\"]+)\"\s*>(.*?)</parameter>", re.S | re.I)
# qualquer tag do formato interno de ferramentas, com ou sem o prefixo, aberta ou fechada, inclusive truncada no fim do texto
_TAGS = re.compile(r"</?\s*(?:antml:)?(?:function_calls|function_results|invoke|parameter)\b[^>]*>?", re.I)
_SUSPEITO = re.compile(r"<\s*/?\s*(?:antml:)?(?:function_calls|invoke|parameter)\b", re.I)


def tem_marcacao(texto: str) -> bool:
    """True se o texto contém marcação de chamada de ferramenta (nunca deve ir para o lead)."""
    return bool(_SUSPEITO.search(texto or ""))


def _valor(nome_ferramenta: str, campo: str, bruto: str, ferramentas: list[dict]):
    """Converte o valor escrito (sempre string) para o tipo do schema da ferramenta."""
    v = html.unescape(bruto.strip())
    for f in ferramentas:
        if f["name"] != nome_ferramenta:
            continue
        tipo = (f["input_schema"]["properties"].get(campo) or {}).get("type")
        if tipo == "integer":
            d = re.sub(r"\D", "", v)
            return int(d) if d else 0
        if tipo == "boolean":
            return v.lower() in ("true", "1", "sim", "yes")
        if tipo == "number":
            try:
                return float(v)
            except ValueError:
                return 0.0
    return v


def extrair_chamadas(texto: str, ferramentas: list[dict]) -> tuple[str, list[tuple[str, dict]]]:
    """Separa o texto para o lead das chamadas de ferramenta escritas nele.

    Retorna (texto_limpo, [(nome, entrada), ...]). Só devolve chamadas de ferramentas que existem no catálogo;
    campos obrigatórios que faltarem entram vazios ("" / 0 / False), para o schema estrito do executor.
    """
    if not texto or not tem_marcacao(texto):
        return (texto or "").strip(), []
    nomes = {f["name"]: f for f in ferramentas}
    chamadas: list[tuple[str, dict]] = []
    for m in _INVOKE.finditer(texto):
        nome = m.group(1).strip()
        if nome not in nomes:
            continue
        entrada = {k.strip(): _valor(nome, k.strip(), v, ferramentas) for k, v in _PARAM.findall(m.group(2))}
        for campo, spec in nomes[nome]["input_schema"]["properties"].items():
            if campo not in entrada:
                entrada[campo] = {"integer": 0, "boolean": False, "number": 0.0}.get(spec.get("type"), "")
        chamadas.append((nome, entrada))
    limpo = _INVOKE.sub("", texto)
    limpo = _PARAM.sub("", limpo)
    limpo = _TAGS.sub("", limpo)
    limpo = re.sub(r"\n{3,}", "\n\n", limpo)
    return limpo.strip(), chamadas
