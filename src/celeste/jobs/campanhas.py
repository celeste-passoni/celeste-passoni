# -*- coding: utf-8 -*-
"""Campanhas da recepção: quem recebeu disparo pelos fluxos da clínica (n8n) e por isso NÃO é atendido pela IA.

Fonte: tabelas `automacoes.controle_envio_*` do BigQuery, filtradas pela coluna `acao` — só as ações listadas em
`campanhas.fontes` (config/parametros.yaml) contam. Destino: Firestore `campanha_contatos/{celular}`.
O gateway rotula a conversa com a campanha; contatos que deixarem de estar nas fontes são removidos e as conversas voltam a "sem frente".
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from google.cloud import bigquery, firestore

from celeste.comum import config
from celeste.jobs.base_leads import normalizar_celular

log = logging.getLogger(__name__)


def _sql(tabela: str, acao: str) -> str:
    return f"""
    SELECT celular, nome, acao, status,
           COALESCE(enviado_em, enviado_em_repescagem, enviado_em_repescagem_2, criado_em) AS ultimo_envio
    FROM `{config.PROJETO_GCP}.automacoes.{tabela}`
    WHERE acao = @acao
      AND COALESCE(enviado_em, enviado_em_repescagem, enviado_em_repescagem_2) IS NOT NULL
    """


def sincronizar() -> dict:
    fontes = config.parametros().get("campanhas", {}).get("fontes") or []
    bq = bigquery.Client(project=config.PROJETO_GCP)
    db = firestore.Client(project=config.PROJETO_GCP)
    agora = datetime.now(timezone.utc)
    resumo: dict = {"importados": 0, "por_campanha": {}, "removidos": 0, "conversas_rotuladas": 0, "conversas_desrotuladas": 0, "invalidos": 0}
    validos: dict[str, str] = {}
    lote, n = db.batch(), 0
    for f in fontes:
        tabela, acao, rot = f["tabela"], f["acao"], f["rotulo"]
        try:
            job = bq.query(_sql(tabela, acao), job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("acao", "STRING", acao)]))
            linhas = list(job.result())
        except Exception as e:
            log.warning("campanhas: falha lendo %s/%s: %s", tabela, acao, e)
            resumo[f"erro_{tabela}_{acao}"] = str(e)[:160]
            continue
        for r in linhas:
            cel = normalizar_celular(r["celular"])
            if not cel:
                resumo["invalidos"] += 1
                continue
            validos[cel] = rot
            lote.set(db.collection("campanha_contatos").document(cel), {
                "celular": cel, "nome": (r["nome"] or "").strip(), "campanha": rot, "fonte": tabela, "acao": acao,
                "status_fluxo": r["status"], "ultimo_envio_em": r["ultimo_envio"], "sincronizado_em": agora}, merge=True)
            n += 1; resumo["importados"] += 1
            resumo["por_campanha"][rot] = resumo["por_campanha"].get(rot, 0) + 1
            if n >= 400:
                lote.commit(); lote, n = db.batch(), 0
    if n:
        lote.commit()

    # remove contatos que não pertencem mais a nenhuma fonte configurada
    for doc in db.collection("campanha_contatos").select([]).stream():
        if doc.id not in validos:
            doc.reference.delete(); resumo["removidos"] += 1

    # conversas: rotula as sem frente cujo número é de campanha; desrotula as de campanha cujo número saiu
    for c in db.collection("conversas").stream():
        d = c.to_dict(); tel = d.get("contato", "")
        if d.get("frente") is None and tel in validos:
            c.reference.set({"frente": "campanha", "campanha": validos[tel]}, merge=True); resumo["conversas_rotuladas"] += 1
        elif d.get("frente") == "campanha" and tel not in validos:
            c.reference.set({"frente": None, "campanha": None}, merge=True); resumo["conversas_desrotuladas"] += 1
    log.info("campanhas: %s", resumo)
    return resumo
