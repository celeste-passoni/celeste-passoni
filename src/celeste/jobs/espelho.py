# -*- coding: utf-8 -*-
"""Espelho diário Firestore → BigQuery (dataset `ia_atendimento`), para BI e auditoria.

Substitui as tabelas inteiras a cada rodada (idempotente, simples); os volumes são pequenos.
Campos aninhados viram JSON em string para o esquema ficar estável.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from google.cloud import bigquery, firestore

from celeste.comum import config

log = logging.getLogger(__name__)
DATASET = "ia_atendimento"

COLECOES = {  # nome da tabela → coleção (None = collection group)
    "leads": ("leads", False), "conversas": ("conversas", False), "mensagens": ("mensagens", True),
    "chamadas_ia": ("chamadas_ia", False), "status_entrega": ("status_entrega", False),
    "encaminhamentos": ("encaminhamentos", False), "custos_diarios": ("custos_diarios", False),
    "disparos_diarios": ("disparos_diarios", False), "campanha_contatos": ("campanha_contatos", False),
}


def _plano(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return v


def _linha(doc) -> dict:
    d = {k: _plano(v) for k, v in (doc.to_dict() or {}).items()}
    d["_id"] = doc.id
    if doc.reference.parent.parent is not None:
        d["_pai_id"] = doc.reference.parent.parent.id
    return d


def rodar(tabelas: list[str] | None = None) -> dict:
    db = firestore.Client(project=config.PROJETO_GCP)
    bq = bigquery.Client(project=config.PROJETO_GCP)
    bq.create_dataset(bigquery.Dataset(f"{config.PROJETO_GCP}.{DATASET}"), exists_ok=True)
    resumo = {}
    for tabela, (colecao, grupo) in COLECOES.items():
        if tabelas and tabela not in tabelas:
            continue
        fonte = db.collection_group(colecao) if grupo else db.collection(colecao)
        linhas = [_linha(doc) for doc in fonte.stream()]
        if not linhas:
            resumo[tabela] = 0
            continue
        # campo 'texto' das mensagens sai do espelho: conteúdo do lead fica só no Firestore (mín. necessário no BI)
        if tabela == "mensagens":
            for l in linhas:
                l["tamanho_texto"] = len(l.get("texto") or "")
                l.pop("texto", None)
        job = bq.load_table_from_json(
            linhas, f"{config.PROJETO_GCP}.{DATASET}.{tabela}",
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", autodetect=True,
                                              schema_update_options=["ALLOW_FIELD_ADDITION"]))
        job.result()
        resumo[tabela] = len(linhas)
    log.info("espelho BigQuery: %s", resumo)
    return resumo
