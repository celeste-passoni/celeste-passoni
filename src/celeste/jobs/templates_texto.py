# -*- coding: utf-8 -*-
"""Texto dos templates de resgate (espelho do que está aprovado na Meta; fonte: prompts/templates-leads-perdidos.md).

Usado para gravar no histórico da conversa o que o lead de fato recebeu, para o modelo não repetir a apresentação
e para o painel/relatórios mostrarem a mensagem. {1} = primeiro nome; T4 {2} = mês; T5 {2} = horário, {3} = profissional.
"""
from __future__ import annotations

RODAPE = "Se preferir não receber mais mensagens, responda SAIR."

TEMPLATES: dict[str, dict] = {
    "T1": {
        "nome": "resgate_lembramos_de_voce",
        "corpo": ("Olá, {1}, tudo bem? 😊 Aqui é a Celeste, da Passoni Clinic.\n\n"
                  "Estávamos revisando nossa agenda e lembramos de você: há um tempo conversamos sobre sua consulta com a "
                  "Dra. Luciana Passoni e esse cuidado acabou não acontecendo.\n\n"
                  "Sabemos que a rotina faz algumas decisões ficarem para depois. Mas, quando falamos em saúde capilar, "
                  "o momento da avaliação faz toda a diferença. Porque tempo é cabelo. 🤍\n\n"
                  "Se ainda fizer sentido para você, é só me responder por aqui que eu vejo um horário."),
        "botoes": ["Quero ver horários", "Tenho uma dúvida", "Agora não"],
    },
    "T2": {
        "nome": "resgate_poucos_horarios",
        "corpo": ("Oi, {1}! 😊 Celeste, da Passoni Clinic.\n\n"
                  "Passando para avisar que a agenda desta e da próxima semana está com poucos horários para consulta — "
                  "com a Dra. Luciana e com o Dr. Lucas Vieira, nosso Diretor Médico.\n\n"
                  "Quer que eu reserve um para você? Me diz o melhor dia e período que eu confiro na hora."),
        "botoes": ["Sim, quero reservar", "Prefiro outra semana", "Agora não"],
    },
    "T3": {
        "nome": "resgate_o_que_dificultou",
        "corpo": ("{1}, tudo bem? Aqui é a Celeste, da Passoni Clinic. 🤍\n\n"
                  "Vi que você chegou a se interessar pela consulta, mas não seguimos com o agendamento. "
                  "Existe algo que esteja dificultando marcar agora?\n\n"
                  "Podemos ver outras opções de data e horário, ou esclarecer qualquer dúvida — sobre a consulta, "
                  "os valores ou como funciona o tratamento."),
        "botoes": ["Dúvida sobre valor", "Dúvida sobre horário", "Outra dúvida"],
    },
    "T4": {
        "nome": "resgate_agenda_do_mes",
        "corpo": ("Olá, {1}! 😊 Celeste, da Passoni Clinic.\n\n"
                  "Abrimos a agenda de consultas de {2} com a Dra. Luciana Passoni e com o Dr. Lucas Vieira. "
                  "Como você já tinha conversado com a gente, quis te avisar antes de os horários preencherem.\n\n"
                  "A consulta inclui a avaliação médica completa e o exame de tricoscopia, que analisa em detalhes "
                  "o couro cabeludo e os fios.\n\n"
                  "Quer que eu veja um horário para você?"),
        "botoes": ["Quero agendar", "Me conta mais", "Agora não"],
    },
    "T5": {
        "nome": "resgate_hoje_a_tarde",
        "corpo": ("{1}, boa tarde! Celeste, da Passoni Clinic. 😊\n\n"
                  "Surgiu um horário hoje às {2} para consulta com o {3}, aqui na clínica "
                  "(Moema, em frente ao Parque Ibirapuera, com valet).\n\n"
                  "Se conseguir vir, eu reservo para você agora mesmo. Me responde por aqui?"),
        "botoes": ["Consigo hoje", "Outro dia", "Agora não"],
    },
}

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def parametros(codigo: str, primeiro_nome: str, **extras) -> list[str]:
    """Lista de parâmetros do corpo, na ordem {{1}}, {{2}}, {{3}} — o que vai à API da Meta."""
    p = [primeiro_nome or "tudo bem"]
    if codigo == "T4":
        p.append(extras.get("mes", ""))
    if codigo == "T5":
        p += [extras.get("horario", ""), extras.get("profissional", "")]
    return p


def renderizar(codigo: str, primeiro_nome: str, **extras) -> str:
    """Texto completo como o lead vê: corpo + rodapé + botões (para histórico e relatórios)."""
    t = TEMPLATES[codigo]
    valores = {str(i + 1): v for i, v in enumerate(parametros(codigo, primeiro_nome, **extras))}
    corpo = t["corpo"]
    for k, v in valores.items():
        corpo = corpo.replace("{" + k + "}", v)
    return f"{corpo}\n\n_{RODAPE}_\n\n[botões: {' · '.join(t['botoes'])}]"
