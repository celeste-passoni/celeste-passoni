# -*- coding: utf-8 -*-
"""Montagem do prompt da Celeste em camadas estáveis (para o prompt caching funcionar).

Camadas, nesta ordem:
  1. parâmetros da clínica (YAML renderizado)        ← estável
  2. base de conhecimento + guia de linguagem         ← estável
  3. prompt da frente                                 ← estável (por frente)
  --- cache_control aqui ---
  4. contexto do lead (varia por conversa)            ← volátil, vai na 1ª mensagem do usuário
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import yaml

from celeste.comum import config

ARQUIVOS_CONHECIMENTO = ["01-base-conhecimento-clinica.md", "02-guia-de-linguagem.md"]
PROMPTS_FRENTE = {"leads_perdidos": "leads-perdidos-v0.md"}


def _lookup(dados: dict, caminho: str) -> Any:
    cur: Any = dados
    for parte in caminho.split("."):
        if isinstance(cur, dict) and parte in cur:
            cur = cur[parte]
        else:
            return None
    return cur


def renderizar(texto: str, dados: dict) -> str:
    """Substitui {{a.b.c}} pelos valores do YAML; listas/dicts viram YAML inline; desconhecidos ficam."""
    def sub(m):
        v = _lookup(dados, m.group(1).strip())
        if v is None:
            return m.group(0)
        if isinstance(v, (dict, list)):
            return yaml.safe_dump(v, allow_unicode=True, sort_keys=False).strip()
        return str(v)
    return re.sub(r"\{\{([^{}]+)\}\}", sub, texto)


@lru_cache(maxsize=8)
def camadas_estaveis(frente: str) -> str:
    p = config.parametros()
    partes = ["# PARÂMETROS DA CLÍNICA (fonte da verdade)\n\n```yaml\n" + yaml.safe_dump(
        {k: p[k] for k in ("clinica", "consultas", "consulta_inclui", "levar_no_dia", "politicas", "pre_cadastro_campos",
                           "pre_cadastro_observacao", "pre_cadastro_menor_de_idade", "encaminhado_por", "procedimentos_permitidos")
         if k in p}, allow_unicode=True, sort_keys=False) + "```"]
    for nome in ARQUIVOS_CONHECIMENTO:
        partes.append(renderizar((config.RAIZ / "knowledge" / nome).read_text(encoding="utf-8"), p))
    prompt_frente = (config.RAIZ / "prompts" / PROMPTS_FRENTE[frente]).read_text(encoding="utf-8")
    prompt_frente = prompt_frente.split("---", 1)[1] if "\n---\n" in prompt_frente else prompt_frente  # tira o cabeçalho de notas
    partes.append("# INSTRUÇÃO DA FRENTE\n\n" + renderizar(prompt_frente, p))
    return "\n\n---\n\n".join(partes)


def contexto_lead(conversa: dict) -> str:
    """Bloco volátil com o que se sabe do lead (vai na primeira mensagem do usuário)."""
    linhas = ["[CONTEXTO DO LEAD — não repita isto para o lead]"]
    for rotulo, chave in (("Nome", "nome"), ("Telefone", "contato"), ("Frente", "frente"), ("Origem", "origem"),
                          ("Último contato anterior", "ultimo_contato_anterior"), ("Resumo da conversa anterior", "resumo_contexto"),
                          ("Objeção anterior", "objecao_anterior"), ("Modalidade de interesse", "modalidade_interesse"),
                          ("Template que originou", "template_origem"), ("Status atual", "status"), ("Paciente TI Saúde id", "id_paciente_tisaude"),
                          ("Agendamento TI Saúde id", "id_agendamento_tisaude")):
        v = conversa.get(chave)
        if v:
            linhas.append(f"- {rotulo}: {v}")
    return "\n".join(linhas)


def formato_saida() -> str:
    p = config.parametros()["ia"]
    return (f"FORMATO: responda só com as mensagens para o lead, separando cada balão por uma linha contendo apenas ---. "
            f"Entre {p['baloes_por_resposta']['min']} e {p['baloes_por_resposta']['max']} balões, no máximo {p['emojis_max_por_mensagem']} emojis por balão. "
            "Nunca escreva nada além das mensagens (sem títulos, sem explicações).")
