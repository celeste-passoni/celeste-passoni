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
    # 11/11/2026 (texto da clínica): o 2º lembrete geral é só o nome com interrogação ("Elaine?"); sem nome, "Olá?".
    # Antes: "{nome}, aqui a Celeste da Passoni Clinic e estou passando para dar continuidade ao seu atendimento" (10/11) e "Oi {nome}, conseguiu verificar?"
    "geral":    ["Aguardo seu retorno, {nome}! 💛", "{nome}?"],
    # 05/11/2026 (clínica): retomada de quem tocou "Quero ver o vídeo" (T2) e não escreveu mais. "Conseguiu assistir?" e não
    # "O que achou?", porque o WhatsApp não avisa se o vídeo foi aberto; a pergunta de diagnóstico já vai junto.
    "video":    ["Oi, {nome}! Conseguiu assistir ao vídeo da Dra. Luciana? 💛 Me conta o que achou. E, se você já tem algum diagnóstico "
                 "para a queda, me fala também, assim eu já te indico a consulta certa para o seu caso.",
                 "{nome}, me conta um pouquinho do seu caso? Há quanto tempo você percebe a queda e se já fez algum tratamento. Assim eu consigo te orientar melhor 💛"],   # 10/11/2026 (clínica): antes "Aguardo seu retorno"
}


import re as _re
_HORA = _re.compile(r"\b\d{1,2}h(\d{2})?\b|\b\d{1,2}:\d{2}\b")


def etapa(conv: dict) -> str:
    """Em que ponto a conversa parou, lendo a ÚLTIMA mensagem da Celeste (não listas antigas): horários oferecidos nela,
    dados de cadastro pedidos nela, ou outro. Incidente de 13/10: uma lista de horários de uma semana antes gerou lembrete errado."""
    # 10/11/2026: o 2º lembrete herda a etapa do 1º (gravada em `lembrete_etapa`). Antes, a última mensagem passava a ser o
    # próprio lembrete 1 e a etapa caía em "geral" (caso Claudia, 07/11: "conseguiu verificar?" depois do vídeo).
    if int(conv.get("lembretes_enviados") or 0) > 0 and conv.get("lembrete_etapa") in TEXTOS:
        return conv["lembrete_etapa"]
    u = conv.get("ultima") or {}
    if u.get("direcao") not in ("celeste", "template"):
        return "geral"
    texto = (u.get("texto") or "").lower()
    if "assista com calma" in texto or conv.get("ultimo_fluxo") == "t2_quero_video":   # 05/11/2026: logo depois do vídeo do T2
        return "video"
    if any(k in texto for k in ("dados abaixo", "pré-cadastro", "pre-cadastro", "cep", "nome completo", "cadastro")):
        return "cadastro"
    if _HORA.search(texto) and any(k in texto for k in ("horário", "horario", "reserv", "atende", "tenho às", "terei")) and conv.get("status") != "Agendado":
        return "horarios"
    return "geral"


def texto_lembrete(conv: dict, n: int) -> str:
    """n = número do lembrete neste fio (1 ou 2). Nome = primeiro nome do lead; sem nome, frase sem vocativo."""
    nome = ((conv.get("nome") or "").strip().split() or [""])[0].title()
    lista = TEXTOS[etapa(conv)]
    t = lista[min(max(n, 1), len(lista)) - 1]
    if not nome:
        t = t.replace("{nome}?", "Olá?").replace("Oi, {nome}! ", "Oi! ").replace("{nome}, ", "").replace(", {nome}", "").replace("Oi {nome}, ", "Oi, ").replace("{nome}", "")
        t = t[0].upper() + t[1:]
    return t.replace("{nome}", nome)
