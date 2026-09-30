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

from celeste.jobs import base_leads, campanhas, disparos, espelho

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


@app.post("/jobs/espelho")
def job_espelho():
    return espelho.rodar()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("job", choices=["carregar-base", "disparos", "espelho", "campanhas"])
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
    else:
        r = espelho.rodar()
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
