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
LOCALIZACAO = "us-central1"   # 22/10/2026: a 1ª rodada criou o dataset em "US" e o funil (us-central1) não enxergava
COLUNAS_GARANTIDAS = {   # colunas que a query do funil de resgate (frente 'Perdidos IA') lê; criadas vazias se faltarem
    "conversas": {"contato": "STRING", "status": "STRING", "opt_out": "BOOL", "opt_out_em": "TIMESTAMP", "teste": "BOOL",
                  "criado_em": "TIMESTAMP", "agendado_em": "TIMESTAMP", "ultima_msg_celeste_em": "TIMESTAMP", "frente": "STRING"},
    "mensagens": {"_id": "STRING", "_pai_id": "STRING", "direcao": "STRING", "tipo": "STRING", "recebido_em": "TIMESTAMP"},
}

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
    nome_ds = f"{config.PROJETO_GCP}.{DATASET}"
    try:   # dataset criado na região errada (1ª rodada, 22/10/2026) é refeito: é só espelho, recarregado inteiro a cada rodada
        existente = bq.get_dataset(nome_ds)
        if (existente.location or "").lower() != LOCALIZACAO:
            log.warning("dataset %s está em %s; recriando em %s", DATASET, existente.location, LOCALIZACAO)
            bq.delete_dataset(nome_ds, delete_contents=True)
    except Exception:   # noqa: BLE001  (não existe ainda)
        pass
    ds = bigquery.Dataset(nome_ds)
    ds.location = LOCALIZACAO   # mesma região dos datasets da clínica (gold/silver/automacoes), senão a query do funil não consegue cruzar
    bq.create_dataset(ds, exists_ok=True)
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
            # WRITE_TRUNCATE + autodetect já recria o esquema inteiro; schema_update_options é inválido com TRUNCATE
            # em tabela sem partição (erro 400 na 1ª rodada, 22/10/2026)
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", autodetect=True))
        job.result()
        # 22/10/2026: o esquema é autodetectado dos dados; colunas que o funil da clínica lê precisam existir mesmo
        # quando nenhum documento as tem ainda (ex.: opt_out antes do 1º opt-out). ADD COLUMN IF NOT EXISTS garante.
        for col, tipo in COLUNAS_GARANTIDAS.get(tabela, {}).items():
            bq.query(f"ALTER TABLE `{config.PROJETO_GCP}.{DATASET}.{tabela}` ADD COLUMN IF NOT EXISTS `{col}` {tipo}").result()
        resumo[tabela] = len(linhas)
    try:   # 05/11/2026: de-para de templates + view do funil por template (falha aqui não derruba o espelho)
        resumo.update(publicar_funil_templates(db, bq))
    except Exception as e:   # noqa: BLE001
        log.exception("funil por template: %s", e)
        resumo["funil_templates_erro"] = str(e)[:300]
    log.info("espelho BigQuery: %s", resumo)
    return resumo


ESQUEMA_DE_PARA = [bigquery.SchemaField(n, t) for n, t in (
    ("codigo", "STRING"), ("etapa", "STRING"), ("etapa_ordem", "INT64"), ("template", "STRING"), ("versao", "INT64"),
    ("rotulo_versao", "STRING"), ("categoria", "STRING"), ("botoes", "STRING"), ("botoes_com_interesse", "STRING"),
    ("botoes_sem_interesse", "STRING"), ("tem_imagem", "BOOL"), ("em_uso", "BOOL"), ("em_uso_desde", "DATE"),
    ("em_uso_ate", "DATE"), ("corpo", "STRING"))]


def publicar_funil_templates(db, bq) -> dict:
    """05/11/2026 (pedido da clínica): grava `templates_de_para` (do código, templates_texto.de_para) e `numeros_teste`
    (config/atendimento) e recria a view `vw_funil_templates` a partir de sql/vw_funil_templates.sql."""
    from pathlib import Path
    from celeste.jobs import templates_texto
    base = f"{config.PROJETO_GCP}.{DATASET}"
    trunc = lambda esquema: bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", schema=esquema)   # noqa: E731
    de_para = templates_texto.de_para()
    bq.load_table_from_json(de_para, f"{base}.templates_de_para", job_config=trunc(ESQUEMA_DE_PARA)).result()
    cfg = db.collection("config").document("atendimento").get().to_dict() or {}
    numeros = sorted({str(n) for n in (cfg.get("numeros_teste") or []) + (cfg.get("numeros_teste_escrita_real") or [])})
    bq.load_table_from_json([{"contato": n} for n in numeros], f"{base}.numeros_teste",
                            job_config=trunc([bigquery.SchemaField("contato", "STRING")])).result()
    sql = (Path(__file__).parent / "sql" / "vw_funil_templates.sql").read_text(encoding="utf-8")
    ddl = "CREATE OR REPLACE VIEW `" + base + ".vw_funil_templates` AS" + chr(10) + sql
    bq.query(ddl).result()
    return {"templates_de_para": len(de_para), "numeros_teste": len(numeros), "vw_funil_templates": "ok"}
