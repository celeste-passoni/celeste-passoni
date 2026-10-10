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
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo
from typing import Any

import yaml

from celeste.comum import config

ARQUIVOS_CONHECIMENTO = ["01-base-conhecimento-clinica.md", "02-guia-de-linguagem.md", "03-exemplos-de-conversas.md"]
PROMPTS_FRENTE = {"leads_perdidos": "leads-perdidos-v0.md"}


def _lookup(dados: dict, caminho: str) -> Any:
    cur: Any = dados
    for parte in caminho.split("."):
        if isinstance(cur, dict) and parte in cur:
            cur = cur[parte]
        elif isinstance(cur, list):   # lista de itens com `id` (ex.: consultas.dra_luciana.valor_texto)
            achado = next((x for x in cur if isinstance(x, dict) and str(x.get("id")) == parte), None)
            if achado is None:
                return None
            cur = achado
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


_SKIP = re.compile(r"<!--\s*prompt:skip\s*-->.*?<!--\s*/prompt:skip\s*-->\s*", re.S)


def para_modelo(texto: str) -> str:
    """Remove dos documentos os blocos marcados para não ir ao modelo (histórico, operacional, repetições)."""
    texto = _SKIP.sub("", texto)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


@lru_cache(maxsize=8)
def camadas_estaveis(frente: str) -> str:
    p = config.parametros()
    partes = ["# PARÂMETROS DA CLÍNICA (fonte da verdade)\n\n```yaml\n" + yaml.safe_dump(
        {k: p[k] for k in ("clinica", "consultas", "consulta_inclui", "levar_no_dia", "politicas", "pre_cadastro_campos",
                           "pre_cadastro_observacao", "pre_cadastro_menor_de_idade", "encaminhado_por", "procedimentos_permitidos")
         if k in p}, allow_unicode=True, sort_keys=False) + "```"]
    partes[0] = renderizar(partes[0], p)
    for nome in ARQUIVOS_CONHECIMENTO:
        partes.append(para_modelo(renderizar((config.RAIZ / "knowledge" / nome).read_text(encoding="utf-8"), p)))
    prompt_frente = (config.RAIZ / "prompts" / PROMPTS_FRENTE[frente]).read_text(encoding="utf-8")
    prompt_frente = prompt_frente.split("---", 1)[1] if "\n---\n" in prompt_frente else prompt_frente  # tira o cabeçalho de notas
    partes.append("# INSTRUÇÃO DA FRENTE\n\n" + para_modelo(renderizar(prompt_frente, p)))
    return "\n\n---\n\n".join(partes)


def contexto_lead(conversa: dict) -> str:
    """Bloco volátil com o que se sabe do lead (vai na primeira mensagem do usuário)."""
    linhas = ["[CONTEXTO DO LEAD — não repita isto para o lead]"]
    if conversa.get("id_paciente_tisaude"):
        nome_ts = (conversa.get("paciente_tisaude_nome") or "").strip()
        nome_lead = (conversa.get("nome") or "").strip()
        bate = bool(nome_ts and nome_lead) and nome_lead.split()[0].lower() in nome_ts.lower()
        if bate or not nome_ts or conversa.get("identidade_confirmada"):
            linhas.append(f"- TI Saúde: JÁ É PACIENTE cadastrado (id {conversa['id_paciente_tisaude']}" + (f", nome {nome_ts}" if nome_ts else "") + "). Não chame buscar_paciente nem criar_paciente; use este id para agendar.")
        else:
            linhas.append(f"- TI Saúde: este NÚMERO está no cadastro de outra pessoa: {nome_ts} (id {conversa['id_paciente_tisaude']}). "
                          f"ANTES de agendar, confirme com naturalidade se a consulta é para {nome_ts.split()[0].title()} ou para quem está falando "
                          f"(ex.: 'Vi aqui que esse número está no cadastro de {nome_ts.split()[0].title()}. A consulta é para ele(a) ou para você?'). "
                          f"Se for para {nome_ts.split()[0].title()}, agende com o id {conversa['id_paciente_tisaude']}. Se for para outra pessoa: pergunte se ela já tem cadastro na clínica "
                          f"e peça o CPF; chame buscar_paciente com o CPF (é o CPF que identifica a pessoa, não o telefone). Só se o CPF não existir, faça o pré-cadastro completo e use criar_paciente.")
    elif conversa.get("pacientes_mesmo_numero"):
        nomes = ", ".join((p.get("nome") or "?").title() for p in conversa["pacientes_mesmo_numero"])
        linhas.append(f"- TI Saúde: este NÚMERO está no cadastro de {len(conversa['pacientes_mesmo_numero'])} pessoas ({nomes}). Quem está falando pode ser uma delas ou outra pessoa. "
                      "Antes de agendar, pergunte com naturalidade se já é paciente da clínica e peça o CPF; chame buscar_paciente com o CPF (é o CPF que identifica a pessoa, não o telefone). "
                      "Nunca diga que o CPF 'está vinculado a outra pessoa' sem o resultado de buscar_paciente. Só se o CPF não existir, faça o pré-cadastro e use criar_paciente.")
    elif conversa.get("paciente_tisaude_ausente"):
        linhas.append("- TI Saúde: número NÃO cadastrado (já verificado pelo sistema). Não chame buscar_paciente; faça o pré-cadastro antes de agendar.")
    ag = conversa.get("agendamento") or {}
    if conversa.get("id_agendamento_tisaude"):
        ida = conversa["id_agendamento_tisaude"]
        prof = {"dra_luciana": "Dra. Luciana Passoni", "dr_lucas": "Dr. Lucas Vieira"}.get(ag.get("profissional"), ag.get("profissional") or "")
        quando = f"{_br(ag.get('data'))} às {str(ag.get('hora') or '')[:5]}" if ag.get("data") else "data não registrada"
        if 900000 <= int(ida) <= 999999:   # ids simulados (TiSaudeSimulado); os reais têm 8 dígitos
            linhas.append(f"- CONSULTA (SIMULAÇÃO DE TESTE, id {ida}): {quando} com {prof}. Este agendamento NÃO existe no TI Saúde real; foi só simulado.")
        else:
            linhas.append(f"- CONSULTA AGENDADA (TI Saúde id {ida}), último registro conhecido: {quando} com {prof}. "
                          "Se o lead falar da consulta (quando é, confirmar, trocar, desmarcar), chame consultar_agendamento ANTES de responder e use o que o sistema devolver. "
                          "NUNCA deduza que um agendamento falhou ou mudou a partir de buscar_horarios: o horário do lead nunca aparece como livre justamente porque está reservado para ele.")
    if conversa.get("origem") == "espontaneo":
        linhas.append("- Origem: espontâneo (o lead escreveu primeiro; nenhum template foi enviado a ele)")
    for rotulo, chave in (("Nome", "nome"), ("Telefone", "contato"), ("Frente", "frente"), ("Origem", "origem") if conversa.get("origem") != "espontaneo" else ("", ""),
                          ("Último contato anterior", "ultimo_contato_anterior"), ("Resumo da conversa anterior", "resumo_contexto"),
                          ("Objeção anterior", "objecao_anterior"), ("Modalidade de interesse", "modalidade_interesse"),
                          ("Template que originou", "template_origem"), ("Status atual", "status"), ("Paciente TI Saúde id", "id_paciente_tisaude")):
        v = conversa.get(chave) if chave else None
        if v:
            linhas.append(f"- {rotulo}: {v}")
    return "\n".join(linhas)


DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


def _br(iso: str | None) -> str:
    """'2026-10-12' → 'segunda-feira, 12/10/2026'."""
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(str(iso)[:10])
        return f"{DIAS[d.weekday()]}, {d.strftime('%d/%m/%Y')}"
    except ValueError:
        return str(iso)


def formato_saida(agora: datetime | None = None) -> str:
    """Bloco volátil do system (depois do cache): data/hora atual e regras operacionais."""
    p = config.parametros()["ia"]
    agora = agora or datetime.now(ZoneInfo(config.FUSO))
    return (f"AGORA: {DIAS[agora.weekday()]}, {agora.strftime('%d/%m/%Y %H:%M')} (horário de São Paulo). "
            "Use esta data para interpretar 'hoje', 'amanhã', 'semana que vem', 'mês que vem' e para preencher datas nas ferramentas.\n"
            f"FORMATO: responda só com as mensagens para o lead, separando cada balão por uma linha contendo apenas ---. "
            f"Entre {p['baloes_por_resposta']['min']} e {p['baloes_por_resposta']['max']} balões, no máximo {p['emojis_max_por_mensagem']} emojis por balão. "
            "Nunca escreva nada além das mensagens (sem títulos, sem explicações). "
            "PONTUAÇÃO: nunca use travessão ou hífen como pontuação no meio da frase (nada de ' — ' ou ' - '); use vírgula, ponto ou dois-pontos, como numa conversa de WhatsApp. "
            "FORMATAÇÃO: horários, datas e dias da semana sempre em texto normal, sem negrito (*...*), itálico (_..._) ou sublinhado; escreva 'terça, 14/10, às 14h'.\n"
            "REGRAS OPERACIONAIS: se disser que vai enviar um vídeo, chame enviar_video na MESMA resposta. "
            "Se o lead pedir para ser chamado em uma data ou período ('mês que vem', 'depois do dia 15'), converta para uma data concreta "
            "(AAAA-MM-DD) em atualizar_status; se não houver data, use o status 'Irá nos retornar'. "
            "Só ofereça horários que vieram de buscar_horarios nesta conversa. "
            "Ao encaminhar à recepção, NÃO escreva o link nem o número: um botão 'Falar com Recepção' é enviado automaticamente "
            "logo depois das suas mensagens; apenas diga que é só tocar no botão.")
