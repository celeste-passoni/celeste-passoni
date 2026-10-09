# -*- coding: utf-8 -*-
"""Texto dos templates de resgate — os MESMOS que a clínica usa hoje no MarketZap (Leads Perdidos), palavra por palavra.

Fonte: conversas da atendente de referência (ago–out/2026). Decisão da clínica em 09/10/2026: manter os mesmos templates.
Usado para gravar no histórico da conversa o que o lead de fato recebeu, para o modelo não repetir a apresentação
e para o painel/relatórios mostrarem a mensagem. {1} = primeiro nome (só nos templates que o usam).

Volumes e resposta em até 3 dias, medidos nos 2 meses (atendente de referência):
  T1 revisando agenda (tempo é cabelo)  1.488 envios ·  5%
  T2 "me dá um oi"                      4.576 envios ·  7%
  T3 duas modalidades (frio)            3.874 envios · 10%
  T4 demonstrou interesse               2.090 envios ·  5%
"""
from __future__ import annotations

RODAPE = "Se preferir não receber mais mensagens, responda SAIR."   # rodapé do template na Meta (opt-out); o corpo é o da clínica

TEMPLATES: dict[str, dict] = {
    "T1": {
        "nome": "resgate_revisando_agenda",
        "corpo": ("Olá {1}! 😀 tudo bem?\n\n"
                  "Estávamos revisando nossa agenda e lembramos de você!\n\n"
                  "Há algum tempo tivemos um contato sobre sua avaliação na Passoni Clinic, mas percebemos que esse cuidado "
                  "acabou não acontecendo.\n\n"
                  "Sabemos que a rotina muitas vezes faz com que algumas decisões fiquem para depois.\n"
                  "Mas, quando falamos em saúde capilar, o momento da avaliação pode fazer toda a diferença.\n\n"
                  "Porque tempo é cabelo. 🤍\n\n"
                  "Se ainda fizer sentido para você, me envie um “OI” por aqui.\n"
                  "Vou ter prazer em verificar um novo horário para sua avaliação.\n\n"
                  "Será um prazer receber você na Passoni Clinic!"),
        "botoes": [],
    },
    "T2": {
        "nome": "resgate_me_da_um_oi",
        "corpo": ("Olá, tudo bem? ☺️\n"
                  "Nosso sistema encerra as conversas automaticamente após 24h ⏳.\n\n"
                  "Por gentileza, me dá um oi por aqui 💬 que consigo te atender! 💖"),
        "botoes": [],
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
    """Lista de parâmetros do corpo, na ordem {{1}}, {{2}}… — o que vai à API da Meta. Só os templates com {1} levam o nome."""
    corpo = TEMPLATES[codigo]["corpo"]
    return [primeiro_nome or "tudo bem"] if "{1}" in corpo else []


def renderizar(codigo: str, primeiro_nome: str, **extras) -> str:
    """Texto completo como o lead vê: corpo + rodapé (para histórico e relatórios)."""
    t = TEMPLATES[codigo]
    corpo = t["corpo"]
    for i, v in enumerate(parametros(codigo, primeiro_nome, **extras), start=1):
        corpo = corpo.replace("{" + str(i) + "}", v)
    saida = f"{corpo}\n\n_{RODAPE}_"
    if t["botoes"]:
        saida += f"\n\n[botões: {' · '.join(t['botoes'])}]"
    return saida
