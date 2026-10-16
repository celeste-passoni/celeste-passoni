# -*- coding: utf-8 -*-
"""Jobs da Celeste — chamados pelo Cloud Scheduler (HTTP, OIDC) ou pela linha de comando.

  POST /jobs/carregar-base      diário 06:00   BigQuery → Firestore leads
  POST /jobs/disparos           a cada 30 min  templates conforme os ciclos (só no horário permitido)
  POST /jobs/espelho            diário 23:30   Firestore → BigQuery ia_atendimento

CLI:  python -m celeste.jobs.app carregar-base|disparos|espelho [--dry-run] [--forcar-horario] [--limite N]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from fastapi import FastAPI

import os

from celeste.jobs import base_leads, campanhas, disparos, espelho, lembretes

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Celeste · Jobs")


@app.get("/status")  # /healthz é interceptado pelo front-end do Google no Cloud Run
def healthz():
    return {"ok": True, "servico": "jobs"}


@app.post("/jobs/carregar-base")
def job_carregar_base(dry_run: bool = False):
    return base_leads.carregar(dry_run=dry_run)


@app.post("/jobs/disparos")
def job_disparos(dry_run: bool = False, limite: int | None = None):
    return disparos.rodar(dry_run=dry_run, limite=limite)


@app.post("/jobs/campanhas")
def job_campanhas():
    return campanhas.sincronizar()


@app.post("/jobs/lembretes")
def job_lembretes(dry_run: bool = False):
    return lembretes.rodar(os.environ.get("URL_ORQUESTRADOR", ""), dry_run=dry_run)


@app.post("/jobs/aquecer-cache")
def job_aquecer_cache():
    """Keep-alive do cache do prompt da Celeste: repassa ao orquestrador (privado) com token de identidade."""
    import requests
    from google.auth.transport.requests import Request as GRequest
    from google.oauth2 import id_token
    url = os.environ.get("URL_ORQUESTRADOR", "")
    tok = id_token.fetch_id_token(GRequest(), url)
    r = requests.post(f"{url}/aquecer-cache", headers={"Authorization": f"Bearer {tok}"}, timeout=300)
    r.raise_for_status()
    return r.json()


@app.post("/jobs/espelho")
def job_espelho():
    return espelho.rodar()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("job", choices=["carregar-base", "disparos", "espelho", "campanhas", "lembretes"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--forcar-horario", action="store_true")
    ap.add_argument("--limite", type=int)
    a = ap.parse_args(argv)
    if a.job == "carregar-base":
        r = base_leads.carregar(dry_run=a.dry_run)
    elif a.job == "disparos":
        r = disparos.rodar(dry_run=a.dry_run, forcar_horario=a.forcar_horario, limite=a.limite)
    elif a.job == "campanhas":
        r = campanhas.sincronizar()
    elif a.job == "lembretes":
        r = lembretes.rodar(os.environ.get("URL_ORQUESTRADOR", ""), forcar_horario=a.forcar_horario, dry_run=a.dry_run)
    else:
        r = espelho.rodar()
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
