# -*- coding: utf-8 -*-
"""Campanhas da recepção (Inativos, Retorno, Geral): quem recebeu disparo pelos fluxos da clínica.

Fonte: tabelas `automacoes.controle_envio_*` do BigQuery (o fluxo do n8n grava celular, nome, enviado_em, acao).
Destino: Firestore `campanha_contatos/{celular}` → o gateway rotula a conversa com a campanha e a IA NÃO atende.
Também corrige conversas já abertas sem frente cujo número pertença a uma campanha.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from google.cloud import bigquery, firestore

from celeste.comum import config
from celeste.jobs.base_leads import normalizar_celular

log = logging.getLogger(__name__)

TABELAS = {  # tabela → rótulo da campanha
    "controle_envio_inativos": "Inativos",
    "controle_envio_retorno": "Retorno",
    "controle_envio_geral": "Geral",
}
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _sql(tabela: str, dias: int) -> str:
    return f"""
    SELECT celular, nome, acao, status,
           GREATEST(IFNULL(enviado_em, TIMESTAMP('2000-01-01')), IFNULL(enviado_em_repescagem, TIMESTAMP('2000-01-01')),
                    IFNULL(enviado_em_repescagem_2, TIMESTAMP('2000-01-01'))) AS ultimo_envio
    FROM `{config.PROJETO_GCP}.automacoes.{tabela}`
    WHERE COALESCE(enviado_em, enviado_em_repescagem, enviado_em_repescagem_2) IS NOT NULL
      AND GREATEST(IFNULL(enviado_em, TIMESTAMP('2000-01-01')), IFNULL(enviado_em_repescagem, TIMESTAMP('2000-01-01')),
                   IFNULL(enviado_em_repescagem_2, TIMESTAMP('2000-01-01'))) >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {int(dias)} DAY)
    """


def rotulo(tabela: str, quando: datetime) -> str:
    return f"{TABELAS[tabela]} · {MESES[quando.month - 1]}/{quando.year}"


def sincronizar(dias: int = 60) -> dict:
    p = config.parametros().get("campanhas", {})
    dias = int(p.get("janela_dias", dias))
    bq = bigquery.Client(project=config.PROJETO_GCP)
    db = firestore.Client(project=config.PROJETO_GCP)
    agora = datetime.now(timezone.utc)
    resumo: dict = {"importados": 0, "por_campanha": {}, "conversas_rotuladas": 0, "invalidos": 0}
    lote, n = db.batch(), 0
    vistos: set[str] = set()
    for tabela in TABELAS:
        try:
            linhas = list(bq.query(_sql(tabela, dias)).result())
        except Exception as e:
            log.warning("campanhas: falha lendo %s: %s", tabela, e)
            resumo[f"erro_{tabela}"] = str(e)[:160]
            continue
        for r in linhas:
            cel = normalizar_celular(r["celular"])
            if not cel:
                resumo["invalidos"] += 1
                continue
            quando = r["ultimo_envio"]
            camp = rotulo(tabela, quando.astimezone(timezone.utc) if quando.tzinfo else quando)
            # um número em mais de uma tabela: fica com o envio mais recente
            if cel in vistos:
                atual = db.collection("campanha_contatos").document(cel).get().to_dict() or {}
                if atual.get("ultimo_envio_em") and atual["ultimo_envio_em"] >= quando:
                    continue
            vistos.add(cel)
            lote.set(db.collection("campanha_contatos").document(cel), {
                "celular": cel, "nome": (r["nome"] or "").strip(), "campanha": camp, "fonte": tabela,
                "acao": r["acao"], "status_fluxo": r["status"], "ultimo_envio_em": quando, "sincronizado_em": agora}, merge=True)
            n += 1; resumo["importados"] += 1
            resumo["por_campanha"][camp] = resumo["por_campanha"].get(camp, 0) + 1
            if n >= 400:
                lote.commit(); lote, n = db.batch(), 0
    if n:
        lote.commit()

    # conversas abertas sem frente cujo número é de campanha → rotula (a resposta pode ter chegado antes da sincronização)
    for c in db.collection("conversas").where("frente", "==", None).stream():
        d = c.to_dict()
        cc = db.collection("campanha_contatos").document(d.get("contato", "")).get()
        if cc.exists:
            info = cc.to_dict()
            c.reference.set({"frente": "campanha", "campanha": info["campanha"], "nome": d.get("nome") or info.get("nome")}, merge=True)
            resumo["conversas_rotuladas"] += 1
    log.info("campanhas: %s", resumo)
    return resumo
