# -*- coding: utf-8 -*-
"""Retornos combinados (16/10/2026): o lead pediu "me chama em 2 horas" e a Celeste agendou (`retorno_em` na conversa).

Este job roda a cada 5 minutos (Cloud Scheduler `celeste-retornos`, 24 h por dia: a clínica decidiu que o horário pedido
pelo lead é respeitado, qualquer dia e hora) e pede ao orquestrador (POST /retomar) o envio da mensagem de retomada.
Se o lead escreveu antes da hora, o gateway já apagou `retorno_em` e nada é enviado.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests
from google.auth.transport.requests import Request as GRequest
from google.cloud import firestore
from google.oauth2 import id_token

from celeste.comum import config

log = logging.getLogger("jobs.retornos")


def devidos(db, agora: datetime) -> list:
    """Conversas com retorno combinado cujo horário já chegou (documentos sem `retorno_em` não entram na consulta)."""
    return list(db.collection("conversas").where("retorno_em", "<=", agora).limit(50).stream())


def rodar(url_orquestrador: str, dry_run: bool = False) -> dict:
    db = firestore.Client(project=config.PROJETO_GCP)
    agora = datetime.now(timezone.utc)
    docs = devidos(db, agora)
    tok = None if dry_run or not docs else id_token.fetch_id_token(GRequest(), url_orquestrador)
    enviados, falhas = 0, []
    for doc in docs:
        if dry_run:
            enviados += 1
            continue
        try:
            r = requests.post(f"{url_orquestrador}/retomar", json={"conversa_id": doc.id}, headers={"Authorization": f"Bearer {tok}"}, timeout=300)
            if r.ok:
                enviados += 1
            else:
                falhas.append({"conversa": doc.id, "erro": r.text[:200]})
                doc.reference.set({"retorno_em": None, "retorno_falha": r.text[:200]}, merge=True)   # não insiste a cada 5 min
        except Exception as e:   # noqa: BLE001
            falhas.append({"conversa": doc.id, "erro": str(e)[:200]})
    log.info("retornos: %d devidos, %d enviados, %d falhas", len(docs), enviados, len(falhas))
    return {"ok": True, "devidos": len(docs), "enviados": enviados, "falhas": falhas, "dry_run": dry_run}
