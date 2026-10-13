# -*- coding: utf-8 -*-
"""Texto dos templates de resgate — os MESMOS que a clínica usa hoje no MarketZap (Leads Perdidos), palavra por palavra.

Fonte: conversas da atendente de referência (ago–out/2026). Decisão da clínica em 09/10/2026: manter os mesmos templates.
Usado para gravar no histórico da conversa o que o lead de fato recebeu, para o modelo não repetir a apresentação
e para o painel/relatórios mostrarem a mensagem. {1} = primeiro nome (só nos templates que o usam).

Volumes e resposta em até 3 dias, medidos nos 2 meses (atendente de referência):
  T1 (antigo) revisando agenda          1.488 envios ·  5%   → substituído em 13/10/2026 por resgate_solicitacao_pendente (UTILITY)
  T2 (antigo) "me dá um oi"             4.576 envios ·  7%   → substituído em 13/10/2026 por resgate_solicitacao_segue_pendente (UTILITY)
  T3 duas modalidades (frio)            3.874 envios · 10%
  T4 demonstrou interesse               2.090 envios ·  5%
"""
from __future__ import annotations

RODAPE = "Se preferir não receber mais mensagens, responda SAIR."   # rodapé do template na Meta (opt-out); o corpo é o da clínica

TEMPLATES: dict[str, dict] = {
    "T1": {   # aprovado pela clínica em 13/10/2026; cadastrado na Meta como UTILITY (id 1443893117837530). {1} = primeiro nome, {2} = mês do contato anterior
        "nome": "resgate_solicitacao_pendente",
        "corpo": ("Olá, {1}! Aqui é a Celeste, da Passoni Clinic.\n\n"
                  "Identificamos que a sua solicitação de consulta, feita em {2}, ficou pendente e o agendamento não foi concluído.\n\n"
                  "Deseja dar continuidade? Responda esta mensagem que eu verifico os horários disponíveis para você."),
        "botoes": ["Quero continuar", "Agora não"],   # quick replies (payload = texto); fluxo em ia/t1_botoes do YAML
        "sem_rodape": True,
    },
    "T2": {   # aprovado pela clínica em 13/10/2026 (UTILITY). 1 dia após o T1, para quem não respondeu e para quem tocou "Agora não" e sumiu
        "nome": "resgate_solicitacao_segue_pendente",
        "corpo": ("Olá, {1}. Sua solicitação de consulta na Passoni Clinic segue pendente. "
                  "Caso ainda queira concluir o agendamento, responda esta mensagem."),
        "botoes": ["Quero continuar", "Agora não"],
        "sem_rodape": True,
    },
    "T3": {
        "nome": "resgate_duas_modalidades",
        "corpo": ("Olá 😀!\n\n"
                  "Na Passoni Clinic, você pode agendar sua consulta de duas formas:\n\n"
                  "🔹 Dra. Luciana Passoni - R$ 1.200,00.\n"
                  "A consulta é iniciada pelos tricologistas, que realizam a anamnese e a tricoscopia.\n"
                  "Em seguida, a Dra. Luciana faz a avaliação médica, define o diagnóstico e indica o tratamento personalizado.\n\n"
                  "🔹 Dr. Lucas Vieira - R$ 800,00.\n"
                  "Diretor Médico da Passoni Clinic e tricologista, ele realiza toda a consulta, desde a avaliação clínica até o "
                  "diagnóstico e a definição do tratamento.\n\n"
                  "Em ambas as modalidades, o objetivo é fechar o seu diagnóstico e indicar o tratamento mais adequado para o seu caso.\n\n"
                  "Ao finalizar todo o tratamento, você tem direito a um retorno como cortesia, que para a modalidade de cortesia, "
                  "deverá ser realizado em até 30 dias após a última sessão, sem desmarcações.\n\n"
                  "Esse retorno, ocorrerá com a equipe de tricologistas, para lhe apresentar o plano de manutenção preventiva. "
                  "E durante o seu tratamento, essa mesma equipe, realizará discussões clínicas sobre a sua evolução."),
        "botoes": [],
    },
    "T4": {
        "nome": "resgate_demonstrou_interesse",
        "corpo": ("Olá {1}😀 esperamos que estejas bem?\n\n"
                  "Vimos que você demonstrou interesse em vir na Passoni Clinic, cuidar da saúde capilar, mas infelizmente "
                  "acabou não acontecendo.\n\n"
                  "Podemos retomar o seu atendimento?\n"
                  "Me responda, que consigo te atender!"),
        "botoes": [],
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
    if t["botoes"]:
        saida += f"\n\n[botões: {' · '.join(t['botoes'])}]"
    return saida
