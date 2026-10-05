# -*- coding: utf-8 -*-
"""Lembretes de retomada: a Celeste chama de volta quem ela escreveu e não respondeu.

Roda nos horários de `lembretes.horas` (Cloud Scheduler). Para cada conversa elegível, pede ao orquestrador
(POST /lembrete) uma mensagem curta e nova. Só dentro da janela de 24 h do WhatsApp (texto livre); fora dela,
a retomada depende de template aprovado (futuro).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from google.auth.transport.requests import Request as GRequest
from google.cloud import firestore
from google.oauth2 import id_token

from celeste.comum import config

log = logging.getLogger(__name__)
FUSO = ZoneInfo(config.FUSO)
STATUS_FINAIS = {"Agendado", "Encaminhado à recepção", "Não quer (opt-out)", "Orientado à recepção", "Encerrada (reiniciada)"}


def _cfg() -> dict:
    return config.parametros().get("lembretes") or {}


def dentro_do_horario(agora: datetime | None = None) -> bool:
    c = _cfg()
    agora = agora or datetime.now(FUSO)
    if c.get("dias_uteis", True) and agora.weekday() >= 5:
        return False
    return agora.hour in set(c.get("horas") or [])


def elegivel(conv: dict, agora: datetime) -> tuple[bool, str]:
    """Decide se a conversa recebe lembrete agora. Retorna (ok, motivo)."""
    c = _cfg()
    frentes_ia = {f for f, cfg in config.parametros()["frentes"].items() if cfg.get("ativa")}
    if conv.get("frente") not in frentes_ia:
        return False, "fora das frentes da IA"
    if not conv.get("aberta") or conv.get("modo", "ia") != "ia" or conv.get("opt_out"):
        return False, "fechada/humano/opt-out"
    if conv.get("status") in STATUS_FINAIS:
        return False, f"status {conv.get('status')}"
    ultima = conv.get("ultima") or {}
    if ultima.get("direcao") not in ("celeste", "template"):
        return False, "última mensagem não é da Celeste"
    if ultima.get("tipo") == "interactive":
        return False, "última foi orientação"
    em = ultima.get("em")
    if not em or (agora - em) < timedelta(minutes=int(c.get("minimo_sem_resposta_min", 60))):
        return False, "ainda dentro do tempo mínimo"
    if int(conv.get("lembretes_enviados") or 0) >= int(c.get("max_por_conversa", 3)):
        return False, "máximo de lembretes atingido"
    if c.get("so_dentro_janela_24h", True):
        janela = conv.get("janela_24h_ate")
        if not janela or janela <= agora:
            return False, "fora da janela de 24 h (precisa de template)"
    if not conv.get("ultima_msg_lead_em"):
        return False, "lead nunca respondeu (fica com a esteira de templates)"
    if not (conv.get("primeira_msg_celeste_em") or conv.get("ultimo_template_em")):
        return False, "a Celeste ainda não conversou aqui (só mensagens manuais/automáticas da equipe)"
    return True, "ok"


def rodar(url_orquestrador: str, forcar_horario: bool = False, dry_run: bool = False) -> dict:
    c = _cfg()
    resumo = {"enviados": 0, "elegiveis": 0, "pulados": 0, "erros": 0, "dry_run": dry_run, "detalhe": []}
    if not c.get("ativo", True):
        resumo["ignorado"] = "lembretes.ativo = false"
        return resumo
    if not dentro_do_horario() and not forcar_horario:
        resumo["ignorado"] = "fora dos horários de lembrete"
        return resumo
    db = firestore.Client(project=config.PROJETO_GCP)
    agora = datetime.now(timezone.utc)
    tok = None if dry_run else id_token.fetch_id_token(GRequest(), url_orquestrador)
    for doc in db.collection("conversas").where("aberta", "==", True).stream():
        conv = doc.to_dict()
        ok, motivo = elegivel(conv, agora)
        if not ok:
            resumo["pulados"] += 1
            continue
        resumo["elegiveis"] += 1
        if dry_run:
            resumo["detalhe"].append({"conversa": doc.id, "nome": conv.get("nome"), "sem_resposta_ha_min": int((agora - conv["ultima"]["em"]).total_seconds() // 60)})
            continue
        try:
            r = requests.post(f"{url_orquestrador}/lembrete", json={"conversa_id": doc.id}, headers={"Authorization": f"Bearer {tok}"}, timeout=300)
            if r.ok:
                resumo["enviados"] += 1
            else:
                resumo["erros"] += 1; log.warning("lembrete %s: HTTP %s %s", doc.id, r.status_code, r.text[:160])
        except Exception as e:
            resumo["erros"] += 1; log.warning("lembrete %s: %s", doc.id, e)
    log.info("lembretes: %s", resumo)
    return resumo
