# -*- coding: utf-8 -*-
"""Retornos combinados na hora exata (decisão da clínica, 27/10/2026).

Quando o lead pede "me chama às 11h30", a Celeste grava status "Vamos retornar na data solicitada" e `proximo_recontato_em`
(data, ou data e hora de São Paulo). Este job roda TODO MINUTO (Cloud Scheduler celeste-retornos), em qualquer dia e hora:
a clínica decidiu que o horário pedido pelo lead vale sempre, inclusive fora do horário comercial, fim de semana e feriado.
Lê só os leads nesse status e envia o template de retorno (TR) a quem já passou da hora. O envio muda o status do lead,
então nunca repete. Não tem limite diário: é uma promessa feita ao lead. O job de disparos (esteira) não trata mais esse status.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore

from celeste.comum import config
from celeste.ferramentas import meta
from celeste.jobs import disparos, templates_texto

log = logging.getLogger(__name__)
STATUS = "Vamos retornar na data solicitada"


def vencidos(leads: list[tuple[str, dict]], agora: datetime) -> list[tuple[str, dict]]:
    """Leads cujo horário combinado já chegou (ordem: o mais antigo primeiro)."""
    saida = []
    for lead_id, lead in leads:
        quando = lead.get("proximo_recontato_em")
        if not quando or not lead.get("elegivel") or lead.get("opt_out") or lead.get("status_ia") != STATUS:
            continue
        try:
            if disparos._dt(quando) <= agora:
                saida.append((lead_id, lead))
        except (TypeError, ValueError):
            log.warning("retornos: data inválida no lead %s: %r", lead_id[-4:], quando)
    return sorted(saida, key=lambda x: disparos._dt(x[1]["proximo_recontato_em"]))


def rodar(dry_run: bool = False, limite: Optional[int] = None) -> dict:
    p = config.parametros()
    d = dict(p["disparos"])
    resumo = {"enviados": 0, "candidatos": 0, "erros": 0, "dry_run": dry_run, "detalhe": []}
    db = firestore.Client(project=config.PROJETO_GCP)
    d.update(db.collection("config").document("disparos").get().to_dict() or {})
    agora = datetime.now(timezone.utc)
    consulta = db.collection("leads").where("status_ia", "==", STATUS).where("elegivel", "==", True)
    leads = [(doc.id, doc.to_dict()) for doc in consulta.stream()]
    fila = vencidos(leads, agora)
    if limite:
        fila = fila[:limite]
    resumo["candidatos"] = len(fila)
    if not fila:
        return resumo
    nome_tpl = d["templates"]["TR"]
    mt = None if dry_run else meta.Meta()
    for lead_id, lead in fila:
        dec = disparos.Decisao("TR", "retorno combinado na hora pedida", int(lead.get("passo") or 0), int(lead.get("ciclos") or 1))
        resumo["detalhe"].append({"lead": lead_id[-4:].rjust(len(lead_id), "*"), "combinado": str(lead.get("proximo_recontato_em"))})
        if dry_run:
            resumo["enviados"] += 1
            continue
        try:
            wamid = mt.enviar_template(lead["celular"], nome_tpl, templates_texto.parametros("TR", lead.get("primeiro_nome") or ""))
        except Exception as e:   # noqa: BLE001
            resumo["erros"] += 1
            log.warning("retornos: falha ao enviar TR para o lead %s: %s", lead_id[-4:], e)
            continue
        disparos._registrar_envio(db, lead_id, lead, dec, nome_tpl, wamid, agora, {})
        resumo["enviados"] += 1
    log.info("retornos: %s", resumo)
    return resumo
