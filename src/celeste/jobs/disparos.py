# -*- coding: utf-8 -*-
"""Disparo de templates para Leads Perdidos, seguindo os ciclos de `disparos.passos` no YAML.

Quem responde a um template sai da esteira (o orquestrador assume e muda o status da conversa).
Quem respondeu e parou (objeção, 'vou pensar') volta pela tabela `template_por_status`
após os dias de `leads_perdidos.recontato_por_status_ia`.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from google.cloud import firestore

from celeste.comum import config
from celeste.ferramentas import meta, tisaude
from celeste.jobs import templates_texto

log = logging.getLogger(__name__)
FUSO = ZoneInfo(config.FUSO)


@dataclass
class Decisao:
    template: str           # T1..T5
    motivo: str             # 'passo 2 do ciclo 1' | 'recontato após Achou caro'
    novo_passo: int


def dentro_do_horario(agora: Optional[datetime] = None) -> bool:
    h = config.parametros()["disparos"]["horario"]
    agora = agora or datetime.now(FUSO)
    if h.get("dias_uteis") and agora.weekday() >= 5:
        return False
    return int(h["inicio"]) <= agora.hour < int(h["fim"])


def decidir(lead: dict, agora: datetime, tarde_livre_hoje: Optional[bool] = None) -> Optional[Decisao]:
    """Qual template este lead recebe agora? None = nada hoje."""
    p = config.parametros()
    d = p["disparos"]
    if not lead.get("elegivel") or lead.get("opt_out"):
        return None
    status = lead.get("status_ia") or "Não contatado"
    ultimo_lead = lead.get("ultima_msg_lead_em")
    ultimo_tpl = lead.get("ultimo_template_em")

    # 1) recontato de quem respondeu e parou
    if status in d["template_por_status"]:
        dias = p["leads_perdidos"]["recontato_por_status_ia"].get(status)
        quando = lead.get("proximo_recontato_em")
        if dias == "na data":
            if not quando:
                return None
        elif dias is None:
            return None
        else:
            base = ultimo_lead or ultimo_tpl
            if not base:
                return None
            quando = base + timedelta(days=int(dias))
        if _dt(quando) <= agora and _dt(ultimo_tpl) < agora - timedelta(hours=20):
            return Decisao(d["template_por_status"][status], f"recontato após '{status}'", int(lead.get("passo") or 0))
        return None

    # 2) esteira de templates (só quem nunca respondeu)
    if status not in ("Não contatado", "Template enviado (1°)", "Template enviado (2°)"):
        return None
    passos = d["passos"]
    passo = int(lead.get("passo") or 0)
    if passo >= len(passos):
        # fim da esteira: pausa longa e volta ao passo de reinício
        if ultimo_tpl and _dt(ultimo_tpl) + timedelta(days=int(d["pausa_apos_ultimo_passo_dias"])) > agora:
            return None
        passo = int(d["reiniciar_no_passo"])
    prox = passos[passo]
    if passo > 0 or ultimo_tpl:
        if not ultimo_tpl or _dt(ultimo_tpl) + timedelta(days=int(prox["apos_dias"])) > agora:
            return None
    if prox.get("so_se_horario_livre_hoje_a_tarde") and not tarde_livre_hoje:
        return None
    return Decisao(prox["template"], f"passo {passo + 1} (ciclo {prox['ciclo']})", passo + 1)


def _dt(v) -> datetime:
    if v is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):                       # data sem hora = "a partir do início daquele dia" (hora local)
        return datetime(v.year, v.month, v.day, 0, tzinfo=FUSO)
    s = str(v)
    if "T" in s or " " in s:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(s).replace(tzinfo=FUSO)


def _enviados_hoje(db) -> int:
    hoje = datetime.now(FUSO).strftime("%Y-%m-%d")
    doc = db.collection("disparos_diarios").document(hoje).get().to_dict() or {}
    return int(doc.get("enviados", 0))


_TARDE: dict = {}


def _tarde_livre_hoje(ts: tisaude.TiSaude) -> bool:
    """Confere se há horário livre hoje à tarde; guarda o primeiro (hora + profissional) para o T5."""
    _TARDE.clear()
    try:
        hoje = date.today()
        for prof in ("dr_lucas", "dra_luciana"):
            for h in ts.buscar_horarios(prof, dias=1, a_partir_de=hoje):
                if h["data"] == hoje.isoformat() and int(h["hora"][:2]) >= 12:
                    _TARDE.update({"horario": h["hora"][:5].replace(":00", "h").replace(":", "h"),
                                   "profissional": config.profissional(prof)["profissional"]})
                    return True
    except Exception as e:
        log.warning("não conferiu tarde livre: %s", e)
    return False


def _extras_template(codigo: str, tarde: bool) -> dict:
    if codigo == "T4":
        return {"mes": templates_texto.MESES[datetime.now(FUSO).month - 1]}
    if codigo == "T5":
        return dict(_TARDE)
    return {}


def rodar(dry_run: bool = False, forcar_horario: bool = False, limite: Optional[int] = None) -> dict:
    p = config.parametros()
    d = dict(p["disparos"])
    db = firestore.Client(project=config.PROJETO_GCP)
    d.update(db.collection("config").document("disparos").get().to_dict() or {})   # o painel sobrescreve ativo/limites
    resumo = {"dry_run": dry_run, "enviados": 0, "candidatos": 0, "pulados": 0, "erros": 0, "detalhe": []}
    if not d.get("ativo") and not dry_run:
        resumo["ignorado"] = "disparos.ativo = false"
        return resumo
    if not dentro_do_horario() and not forcar_horario:
        resumo["ignorado"] = "fora do horário de disparo"
        return resumo
    agora = datetime.now(timezone.utc)
    ja_hoje = _enviados_hoje(db)
    cota = min(int(d["limite_por_execucao"]), int(d["limite_diario"]) - ja_hoje)
    if limite is not None:
        cota = min(cota, limite)
    if cota <= 0:
        resumo["ignorado"] = f"limite diário atingido ({ja_hoje})"
        return resumo

    precisa_tarde = any(x.get("so_se_horario_livre_hoje_a_tarde") for x in d["passos"])
    tarde = _tarde_livre_hoje(tisaude.TiSaude()) if precisa_tarde and not dry_run else False
    mt = None if dry_run else meta.Meta()
    ordem = firestore.Query.DESCENDING if d.get("priorizar", "mais_recentes") == "mais_recentes" else firestore.Query.ASCENDING
    consulta = db.collection("leads").where("elegivel", "==", True).where("opt_out", "==", False).order_by("lead_created_at", direction=ordem)

    for doc in consulta.stream():
        if resumo["enviados"] >= cota:
            break
        lead = doc.to_dict()
        dec = decidir(lead, agora, tarde)
        if not dec:
            resumo["pulados"] += 1
            continue
        resumo["candidatos"] += 1
        nome_tpl = d["templates"][dec.template]
        if dry_run:
            resumo["enviados"] += 1
            resumo["detalhe"].append({"lead": doc.id[-4:].rjust(len(doc.id), "*"), "template": dec.template, "motivo": dec.motivo})
            continue
        extras = _extras_template(dec.template, tarde)
        try:
            wamid = mt.enviar_template(lead["celular"], nome_tpl, templates_texto.parametros(dec.template, lead.get("primeiro_nome") or "", **extras))
        except Exception as e:
            resumo["erros"] += 1
            log.warning("falha ao enviar %s para lead: %s", dec.template, e)
            db.collection("leads").document(doc.id).set({"ultimo_erro_envio": str(e)[:300], "ultimo_erro_em": agora}, merge=True)
            continue
        _registrar_envio(db, doc.id, lead, dec, nome_tpl, wamid, agora, extras)
        resumo["enviados"] += 1
        time.sleep(random.uniform(*d["intervalo_entre_envios_segundos"]))
    log.info("disparos: %s", resumo)
    return resumo


def _registrar_envio(db, lead_id: str, lead: dict, dec: Decisao, nome_tpl: str, wamid: str, agora: datetime, extras: dict) -> None:
    d = config.parametros()["disparos"]
    status = d["status_apos_template"][dec.template]
    conv_id = lead.get("conversa_id")
    conv_ref = db.collection("conversas").document(conv_id) if conv_id else None
    if not conv_ref or not (conv_ref.get().to_dict() or {}).get("aberta"):
        conv_ref = db.collection("conversas").document()
        conv_ref.set({"contato": lead["celular"], "nome": lead.get("nome"), "frente": "leads_perdidos", "modo": "ia",
                      "status": status, "aberta": True, "criado_em": agora, "origem": "disparo", "template_origem": dec.template,
                      "primeira_msg_celeste_em": agora,
                      "ciclo": next((x["ciclo"] for x in d["passos"] if x["template"] == dec.template), None)})
        conv_id = conv_ref.id
    db.collection("contatos").document(lead["celular"]).set(
        {"telefone": lead["celular"], "nome": lead.get("nome"), "origem": "leads_perdidos", "opt_out": False, "criado_em": agora}, merge=True)
    conv_ref.collection("mensagens").document(wamid).set({
        "direcao": "template", "tipo": "template", "template": nome_tpl, "codigo": dec.template,
        "texto": templates_texto.renderizar(dec.template, lead.get("primeiro_nome") or "", **extras),
        "recebido_em": agora, "gravado_em": firestore.SERVER_TIMESTAMP})
    conv_ref.set({"status": status, "ultimo_template_em": agora, "template_origem": dec.template,
                  "ultima": {"texto": f"[template {dec.template}] " + templates_texto.TEMPLATES[dec.template]["corpo"][:120], "direcao": "template", "tipo": "template", "em": agora}}, merge=True)
    db.collection("leads").document(lead_id).set({
        "status_ia": status, "passo": dec.novo_passo, "ultimo_template_em": agora, "conversa_id": conv_id,
        "templates_enviados": firestore.ArrayUnion([{"codigo": dec.template, "template": nome_tpl, "em": agora, "wamid": wamid, "motivo": dec.motivo}]),
        "proximo_recontato_em": None}, merge=True)
    hoje = datetime.now(FUSO).strftime("%Y-%m-%d")
    db.collection("disparos_diarios").document(hoje).set(
        {"enviados": firestore.Increment(1), f"por_template.{dec.template}": firestore.Increment(1)}, merge=True)
