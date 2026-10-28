# -*- coding: utf-8 -*-
"""Texto dos templates de resgate — os MESMOS que a clínica usa hoje no MarketZap (Leads Perdidos), palavra por palavra.

Fonte: conversas da atendente de referência (ago–out/2026). Decisão da clínica em 09/10/2026: manter os mesmos templates.
Usado para gravar no histórico da conversa o que o lead de fato recebeu, para o modelo não repetir a apresentação
e para o painel/relatórios mostrarem a mensagem. {1} = primeiro nome (só nos templates que o usam).

Volumes e resposta em até 3 dias, medidos nos 2 meses (atendente de referência):
  T1 (antigo) revisando agenda          1.488 envios ·  5%   → substituído em 13/10/2026 por resgate_solicitacao_pendente (UTILITY)
                                                              → e em 28/10/2026 por resgate_queda_3cm (MARKETING, com imagem)
  T2 (antigo) "me dá um oi"             4.576 envios ·  7%   → substituído em 13/10/2026 por resgate_solicitacao_segue_pendente (UTILITY)
  T3 (antigo) duas modalidades (frio)   3.874 envios · 10%   → substituído em 14/10/2026 por resgate_solicitacao_ainda_pendente (UTILITY)
  T4 (antigo) demonstrou interesse      2.090 envios ·  5%   → substituído em 14/10/2026 por resgate_solicitacao_encerramento (UTILITY)
"""
from __future__ import annotations

RODAPE = "Se preferir não receber mais mensagens, responda SAIR."   # rodapé do template na Meta (opt-out); o corpo é o da clínica

TEMPLATES: dict[str, dict] = {
    "T1": {   # 28/10/2026 (decisão da clínica): pergunta sobre os cabelos, com imagem da Dra. Luciana. MARKETING (Meta id 958115566957712). {1} = primeiro nome
        "nome": "resgate_queda_3cm",   # antes: resgate_solicitacao_pendente(_v2), "sua solicitação de consulta, feita em {2}, ficou pendente"
        "corpo": ("Oi, {1}! Você sabia que um fio saudável cresce cerca de 3 cm em 3 meses? 🌱\n"
                  "Já faz uns 3 meses desde que conversamos. Como estão seus cabelos hoje?"),
        "botoes": ["Quero uma avaliação", "Tenho uma dúvida", "Não quero receber"],   # quick replies (payload = texto); fluxo em ia/t1_botoes do YAML
        "imagem": "https://storage.googleapis.com/celeste-videos-vertical-theory-489419-a7/templates/t1_queda_3cm.jpg",   # cópia em midia/templates/
        "imagem_descricao": "foto da Dra. Luciana Passoni com o texto \"Você sabia? Um fio saudável cresce 3 cm em 3 meses.\", uma régua de hoje a 3 meses e \"Como estão seus cabelos hoje?\"",
        "sem_rodape": True,
    },
    "T2": {   # aprovado pela clínica em 13/10/2026 (UTILITY). 1 dia após o T1, para quem não respondeu e para quem tocou "Agora não" e sumiu
        "nome": "resgate_solicitacao_segue_pendente",
        "corpo": ("Olá, {1}. Sua solicitação de consulta na Passoni Clinic segue pendente. "
                  "Caso ainda queira concluir o agendamento, responda esta mensagem."),
        "botoes": ["Quero continuar", "Agora não"],
        "sem_rodape": True,
    },
    "T3": {   # aprovado pela clínica em 14/10/2026 (UTILITY). 3 dias após o T2
        "nome": "resgate_solicitacao_ainda_pendente",
        "corpo": ("Olá, {1}. Sua solicitação de consulta na Passoni Clinic ainda está pendente. "
                  "Se quiser concluir o agendamento, responda esta mensagem."),
        "botoes": ["Quero continuar", "Agora não"],
        "sem_rodape": True,
    },
    "T4": {   # aprovado pela clínica em 14/10/2026 (UTILITY). 7 dias após o T3: aviso de encerramento da solicitação
        "nome": "resgate_solicitacao_encerramento",
        "corpo": ("Olá, {1}. Como não tivemos o seu retorno, vamos encerrar a sua solicitação de consulta na Passoni Clinic. "
                  "Se ainda quiser agendar, responda esta mensagem."),
        "botoes": ["Quero continuar", "Pode encerrar"],
        "sem_rodape": True,
    },
    "TR": {   # decisão da clínica em 25/10/2026: retorno na data que o lead pediu ("me chama na segunda"), no lugar do T2. UTILITY, sem botões
        "nome": "retorno_combinado",
        "corpo": "Olá, {1}! Como combinamos, estou retomando a nossa conversa sobre a sua consulta na Passoni Clinic. Podemos continuar?",
        "botoes": [],
        "sem_rodape": True,
    },
}

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def parametros(codigo: str, primeiro_nome: str, **extras) -> list[str]:
    """Lista de parâmetros do corpo, na ordem {{1}}, {{2}}… — o que vai à API da Meta. {1} = nome (se o corpo tiver), {2} = mês (T1)."""
    corpo = TEMPLATES[codigo]["corpo"]
    p = [primeiro_nome or "tudo bem"] if "{1}" in corpo else []
    if "{2}" in corpo:
        p.append(extras.get("mes") or "")
    return p


def renderizar(codigo: str, primeiro_nome: str, **extras) -> str:
    """Texto completo como o lead vê: corpo + rodapé (para histórico e relatórios)."""
    t = TEMPLATES[codigo]
    corpo = t["corpo"]
    for i, v in enumerate(parametros(codigo, primeiro_nome, **extras), start=1):
        corpo = corpo.replace("{" + str(i) + "}", v)
    saida = corpo if t.get("sem_rodape") else f"{corpo}\n\n_{RODAPE}_"
    if t.get("imagem_descricao"):   # o modelo não vê a imagem: o histórico descreve o que o lead recebeu
        saida = f"[imagem: {t['imagem_descricao']}]\n{saida}"
    if t["botoes"]:
        saida += f"\n\n[botões: {' · '.join(t['botoes'])}]"
    return saida
