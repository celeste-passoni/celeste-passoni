# -*- coding: utf-8 -*-
"""Texto dos templates de resgate — os MESMOS que a clínica usa hoje no MarketZap (Leads Perdidos), palavra por palavra.

Fonte: conversas da atendente de referência (ago–out/2026). Decisão da clínica em 09/10/2026: manter os mesmos templates.
Usado para gravar no histórico da conversa o que o lead de fato recebeu, para o modelo não repetir a apresentação
e para o painel/relatórios mostrarem a mensagem. {1} = primeiro nome (só nos templates que o usam).

Volumes e resposta em até 3 dias, medidos nos 2 meses (atendente de referência):
  T1 (antigo) revisando agenda          1.488 envios ·  5%   → substituído em 13/10/2026 por resgate_solicitacao_pendente (UTILITY)
                                                              → e em 28/10/2026 por resgate_queda_3cm_v2 (MARKETING, com imagem)
  T2 (antigo) "me dá um oi"             4.576 envios ·  7%   → substituído em 13/10/2026 por resgate_solicitacao_segue_pendente (UTILITY)
                                                              → e em 29/10/2026 por resgate_video_solicitacao_pendente (oferece o vídeo; a antiga virou T2r)
  T3 (antigo) duas modalidades (frio)   3.874 envios · 10%   → substituído em 14/10/2026 por resgate_solicitacao_ainda_pendente (UTILITY)
  T4 (antigo) demonstrou interesse      2.090 envios ·  5%   → substituído em 14/10/2026 por resgate_solicitacao_encerramento (UTILITY)
"""
from __future__ import annotations

RODAPE = "Se preferir não receber mais mensagens, responda SAIR."   # rodapé do template na Meta (opt-out); o corpo é o da clínica

TEMPLATES: dict[str, dict] = {
    "T1": {   # 28/10/2026 (decisão da clínica): pergunta sobre os cabelos, com imagem da Dra. Luciana. MARKETING (Meta id 1827070681628958). {1} = primeiro nome
        "nome": "resgate_queda_3cm_v2",   # 28/10: a pergunta final virou convite ("Quer que a gente avalie…?") para casar com os botões; v1 = 958115566957712
        "corpo": ("Oi, {1}! Você sabia que um fio saudável cresce cerca de 3 cm em 3 meses? 🌱\n"
                  "Já faz uns 3 meses desde que conversamos, e muita coisa pode ter mudado nos seus fios. Quer que a gente avalie como eles estão hoje?"),
        "botoes": ["Quero agendar uma consulta", "Não tenho interesse"],   # 28/10 (clínica editou na Meta); quick replies (payload = texto); fluxo em ia/t1_botoes do YAML
        "imagem": "https://storage.googleapis.com/celeste-videos-vertical-theory-489419-a7/templates/t1_queda_3cm_h.jpg",   # 04/11/2026: versão horizontal 1200x628 (o WhatsApp cortava a vertical: rosto e texto fora); cópia e gerador em midia/templates/
        "imagem_descricao": "foto da Dra. Luciana Passoni com o texto \"Você sabia? Um fio saudável cresce 3 cm em 3 meses.\", uma régua de hoje a 3 meses e \"Como estão seus cabelos hoje?\"",
        "sem_rodape": True,
    },
    "T2": {   # 29/10/2026 (decisão da clínica): 1 dia após o T1, SÓ para quem não respondeu nada. UTILITY.
              # 06/11/2026 (clínica): o "Agora não" (7% de cliques, 2,5x o vídeo, zero respostas depois) saiu; entra opt-out de verdade.
              # A v2 (3 botões, com "Prefiro agendar direto", Meta id 1214650231228426) foi recategorizada como MARKETING e NÃO é usada; a v3 (2 botões) é UTILITY
        "nome": "resgate_video_solicitacao_pendente_v3",
        "corpo": ("Olá, {1}. Sua solicitação de consulta na Passoni Clinic ainda está pendente. "
                  "Antes de seguir, a Dra. Luciana Passoni gravou um vídeo curto sobre queda de cabelo que pode te ajudar. Quer receber?"),
        "botoes": ["Quero ver o vídeo", "Não tenho interesse"],
        "video_botao": "dra_luciana",   # "Quero ver o vídeo" → este vídeo, sem passar pelo modelo (orquestrador/_responder_quero_video)
        "sem_rodape": True,
    },
    "T2r": {   # o T2 de 13/10/2026; desde 29/10 só no recontato de quem respondeu e parou ("Irá nos retornar", "Agora não")
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
        "nome": "resgate_solicitacao_encerramento_v2",   # 03/11/2026 (clínica): botões novos; a v1 (Quero continuar · Pode encerrar) continua aprovada na Meta
        "corpo": ("Olá, {1}. Como não tivemos o seu retorno, vamos encerrar a sua solicitação de consulta na Passoni Clinic. "
                  "Se ainda quiser agendar, responda esta mensagem."),
        "botoes": ["Sim, tenho interesse", "Encerrar solicitação"],   # "Sim, tenho interesse" vai para a Celeste (como qualquer texto); "Encerrar solicitação" = opt-out com despedida própria
        "sem_rodape": True,
    },
    "TL": {   # 09/11/2026 (clínica): conversa em aberto parada > 2 dias fora da janela de 24 h (job de lembretes, 1x por fio). UTILITY, Meta id 1693036058852742
        "nome": "retomada_conversa_em_aberto",
        "corpo": "Olá, {1}! Nossa conversa sobre a sua consulta na Passoni Clinic ficou em aberto. Posso continuar te ajudando por aqui?",
        "botoes": ["Sim, vamos continuar", "Não tenho interesse"],   # o 1º vai para a Celeste como texto; o 2º é opt-out (t1_botoes.sair_outros_rotulos)
        "sem_rodape": True,
    },
    "TR": {   # decisão da clínica em 25/10/2026: retorno na data que o lead pediu ("me chama na segunda"), no lugar do T2. UTILITY, sem botões
        "nome": "retorno_combinado",
        "corpo": "Olá, {1}! Como combinamos, estou retomando a nossa conversa sobre a sua consulta na Passoni Clinic. Podemos continuar?",
        "botoes": [],
        "sem_rodape": True,
    },
}

# ---------------------------------------------------------------------------------------------------------------------
# DE-PARA DE TEMPLATES (05/11/2026, pedido da clínica): todo template que a esteira já usou, com a etapa a que pertence e
# quais botões contam como "com interesse" e "sem interesse". O espelho noturno grava isto em BigQuery
# (`ia_atendimento.templates_de_para`) e a view `vw_funil_templates` mede a eficiência por etapa e por versão.
# AO TROCAR UM TEMPLATE: atualize TEMPLATES acima (o que é enviado), ponha a nova versão em METADADOS e mova a antiga
# para HISTORICO com a data em que saiu de uso. O teste test_de_para_cobre_todos_os_templates falha se faltar algo.
# ---------------------------------------------------------------------------------------------------------------------
ETAPAS = {   # código → (rótulo da etapa no funil, ordem). TR e T2r ficam fora da esteira T1→T4 (recontato/retorno combinado)
    "T1": ("T1", 1), "T2": ("T2", 2), "T3": ("T3", 3), "T4": ("T4", 4),
    "T2r": ("Recontato", 5), "TR": ("Retorno combinado", 6), "TL": ("Retomada de conversa", 7),
}

METADADOS: dict[str, dict] = {   # templates EM USO (mesmas chaves de TEMPLATES)
    "T1": {"versao": 3, "categoria": "MARKETING", "em_uso_desde": "2026-10-28",
           "com_interesse": ["Quero agendar uma consulta"], "sem_interesse": ["Não tenho interesse"]},
    "T2": {"versao": 4, "categoria": "MARKETING", "em_uso_desde": "2026-11-06",   # v3 na Meta (a v2 de 3 botões é a versão 3 do de-para); cadastrada como UTILITY, aprovada como MARKETING (06/11/2026)
           "com_interesse": ["Quero ver o vídeo"], "sem_interesse": ["Não tenho interesse"]},
    "T2r": {"versao": 1, "categoria": "UTILITY", "em_uso_desde": "2026-10-29",
            "com_interesse": ["Quero continuar"], "sem_interesse": ["Agora não"]},
    "T3": {"versao": 1, "categoria": "UTILITY", "em_uso_desde": "2026-10-14", "em_uso_ate": "2026-11-05",   # 06/11/2026: saiu da esteira (encerramento vai 3 dias após o T2); o texto continua aqui para o histórico e envios manuais
           "com_interesse": ["Quero continuar"], "sem_interesse": ["Agora não"]},
    "T4": {"versao": 2, "categoria": "UTILITY", "em_uso_desde": "2026-11-03", "etapa_funil": "T3",   # 05/11/2026 (clínica): encerramento conta como T3 no funil até a revisão dos templates (em 03/11 o T3 foi pulado e 81 leads foram do T2 direto para ele)
           "com_interesse": ["Sim, tenho interesse"], "sem_interesse": ["Encerrar solicitação"]},
    "TR": {"versao": 1, "categoria": "UTILITY", "em_uso_desde": "2026-10-25", "com_interesse": [], "sem_interesse": []},
    "TL": {"versao": 1, "categoria": "UTILITY", "em_uso_desde": "2026-11-09",
           "com_interesse": ["Sim, vamos continuar"], "sem_interesse": ["Não tenho interesse"]},
}

HISTORICO: list[dict] = [   # templates que já saíram de uso (continuam no de-para para o histórico do funil)
    {"codigo": "T1", "nome": "resgate_solicitacao_pendente", "versao": 1, "categoria": "UTILITY",
     "em_uso_desde": "2026-10-13", "em_uso_ate": "2026-10-27", "botoes": ["Quero continuar", "Agora não"],
     "com_interesse": ["Quero continuar"], "sem_interesse": ["Agora não"],
     "corpo": "Olá, {1}. Sua solicitação de consulta na Passoni Clinic, feita em {2}, ficou pendente. Caso ainda queira concluir o agendamento, responda esta mensagem."},
    {"codigo": "T1", "nome": "resgate_queda_3cm", "versao": 2, "categoria": "MARKETING",
     "em_uso_desde": "2026-10-27", "em_uso_ate": "2026-10-28", "imagem": True, "botoes": ["Quero uma avaliação", "Tenho uma dúvida", "Não quero receber"],
     "com_interesse": ["Quero uma avaliação", "Tenho uma dúvida"], "sem_interesse": ["Não quero receber"],
     "corpo": "Oi, {1}! Você sabia que um fio saudável cresce cerca de 3 cm em 3 meses? (versão 1, com imagem vertical)"},
    {"codigo": "T2", "nome": "resgate_solicitacao_segue_pendente", "versao": 1, "categoria": "UTILITY",
     "em_uso_desde": "2026-10-13", "em_uso_ate": "2026-10-28", "botoes": ["Quero continuar", "Agora não"],
     "com_interesse": ["Quero continuar"], "sem_interesse": ["Agora não"],
     "corpo": TEMPLATES["T2r"]["corpo"]},
    {"codigo": "T2", "nome": "resgate_video_solicitacao_pendente", "versao": 2, "categoria": "UTILITY",
     "em_uso_desde": "2026-10-29", "em_uso_ate": "2026-11-06", "botoes": ["Quero ver o vídeo", "Agora não"],
     "com_interesse": ["Quero ver o vídeo"], "sem_interesse": ["Agora não"],
     "corpo": TEMPLATES["T2"]["corpo"]},
    {"codigo": "T2", "nome": "resgate_video_solicitacao_pendente_v2", "versao": 3, "categoria": "MARKETING",   # 3 botões; aprovada como MARKETING e nunca enviada (06/11/2026)
     "em_uso_desde": "2026-11-06", "em_uso_ate": "2026-11-06", "botoes": ["Quero ver o vídeo", "Prefiro agendar direto", "Não tenho interesse"],
     "com_interesse": ["Quero ver o vídeo", "Prefiro agendar direto"], "sem_interesse": ["Não tenho interesse"],
     "corpo": TEMPLATES["T2"]["corpo"]},
    {"codigo": "T4", "nome": "resgate_solicitacao_encerramento", "versao": 1, "categoria": "UTILITY", "etapa_funil": "T3",
     "em_uso_desde": "2026-10-14", "em_uso_ate": "2026-11-02", "botoes": ["Quero continuar", "Pode encerrar"],
     "com_interesse": ["Quero continuar"], "sem_interesse": ["Pode encerrar"],
     "corpo": TEMPLATES["T4"]["corpo"]},
]


def de_para() -> list[dict]:
    """Linhas da tabela `templates_de_para` (BigQuery): uma por (etapa, template). Listas de botões em texto ' | ' (Power BI)."""
    def linha(codigo, nome, meta, botoes, corpo, em_uso, ate, imagem):
        rotulo, ordem = ETAPAS[meta.get("etapa_funil") or codigo]   # etapa_funil: coluna do funil diferente do código do fluxo
        return {"codigo": codigo, "etapa": rotulo, "etapa_ordem": ordem, "template": nome, "versao": int(meta["versao"]),
                "rotulo_versao": f"{rotulo} v{meta['versao']} · {nome}", "categoria": meta["categoria"],
                "botoes": " | ".join(botoes), "botoes_com_interesse": " | ".join(meta["com_interesse"]),
                "botoes_sem_interesse": " | ".join(meta["sem_interesse"]), "tem_imagem": bool(imagem),
                "em_uso": em_uso, "em_uso_desde": meta["em_uso_desde"], "em_uso_ate": ate, "corpo": corpo}
    linhas = []
    for codigo, t in TEMPLATES.items():
        m = METADADOS[codigo]   # em_uso_ate: continua em TEMPLATES (histórico, envio manual), mas a esteira não usa mais
        linhas.append(linha(codigo, t["nome"], m, t["botoes"], t["corpo"], not m.get("em_uso_ate"), m.get("em_uso_ate"), t.get("imagem")))
    for h in HISTORICO:
        linhas.append(linha(h["codigo"], h["nome"], h, h["botoes"], h["corpo"], not h.get("em_uso_ate"), h.get("em_uso_ate"), h.get("imagem")))   # sem em_uso_ate = reserva em uso (06/11/2026)
    return linhas


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
