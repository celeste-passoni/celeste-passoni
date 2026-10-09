# -*- coding: utf-8 -*-
"""Retomada no mesmo dia, como as atendentes de referência fazem: texto fixo (sem modelo, custo zero), escolhido pela etapa.

Medido nas duas atendentes (244 retomadas): mediana de ~5 h depois da última mensagem delas sem resposta, 25% em até 2 h.
Textos reais delas: "Aguardo seu retorno, Ana! 💛", "Ana, algum desses horários lhe atende?", "Olá, gostaria de dar continuidade
ao agendamento?", "Ana, aguardo o seu retorno para darmos continuidade no seu agendamento." e o script de escassez da casa.
"""
from __future__ import annotations

ESCASSEZ = ("Os agendamentos são realizados por todos os setores da clínica e as datas são preenchidas conforme a disponibilidade. "
            "Por isso, pedimos a gentileza de nos dar um retorno o mais breve possível, para que possamos verificar a disponibilidade "
            "e reservar sua data.\n\nFicamos no aguardo da sua confirmação, ok?")

TEXTOS = {
    "horarios": ["{nome}, algum desses horários lhe atende?", ESCASSEZ],
    "cadastro": ["Olá, gostaria de dar continuidade ao agendamento?", "{nome}, aguardo o seu retorno para darmos continuidade no seu agendamento."],
    "geral":    ["Aguardo seu retorno, {nome}! 💛", "Oi {nome}, conseguiu verificar?"],
}


def etapa(conv: dict) -> str:
    """Em que ponto a conversa parou: horários oferecidos, pré-cadastro pedido, ou outro."""
    ultima = ((conv.get("ultima") or {}).get("texto") or "").lower()
    if (conv.get("ultima") or {}).get("direcao") in ("celeste", "template") and ("dados abaixo" in ultima or "pré-cadastro" in ultima or "pre-cadastro" in ultima):
        return "cadastro"
    if conv.get("horarios_oferecidos") and conv.get("status") not in ("Agendado",):
        return "horarios"
    return "geral"


def texto_lembrete(conv: dict, n: int) -> str:
    """n = número do lembrete neste fio (1 ou 2). Nome = primeiro nome do lead; sem nome, frase sem vocativo."""
    nome = ((conv.get("nome") or "").strip().split() or [""])[0].title()
    lista = TEXTOS[etapa(conv)]
    t = lista[min(max(n, 1), len(lista)) - 1]
    if not nome:
        t = t.replace("{nome}, ", "").replace(", {nome}", "").replace("Oi {nome}, ", "Oi, ").replace("{nome}", "")
        t = t[0].upper() + t[1:]
    return t.replace("{nome}", nome)
