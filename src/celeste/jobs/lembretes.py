# -*- coding: utf-8 -*-
"""Retomada no mesmo dia, no padrão das atendentes de referência: texto fixo por etapa, sem modelo.

Roda de hora em hora em `lembretes.horas` (Cloud Scheduler). Para cada conversa elegível, pede ao orquestrador
(POST /lembrete) o envio do texto da etapa. Só dentro da janela de 24 h do WhatsApp; fora dela, só template.
"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from google.auth.transport.requests import Request as GRequest
from google.cloud import firestore
from google.oauth2 import id_token

from celeste.comum import config
from celeste.ferramentas import meta
from celeste.jobs import disparos, templates_texto

log = logging.getLogger(__name__)
FUSO = ZoneInfo(config.FUSO)
STATUS_FINAIS = {"Agendado", "Encaminhado à recepção", "Não quer (opt-out)", "Orientado à recepção", "Encerrada (reiniciada)",
                 "Irá nos retornar", "Vamos retornar na data solicitada", "Agora não", "Não é lead", "Sem resposta (conversa)"}   # 07/11/2026: fornecedora recebeu "Aguardo seu retorno"   # quem disse que volta não leva cutucada no mesmo dia (padrão das atendentes)


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
    if int(conv.get("lembretes_enviados") or 0) >= int(c.get("max_por_conversa", 2)):
        return False, "máximo de lembretes atingido"
    ult_lemb = conv.get("ultimo_lembrete_em")
    if ult_lemb and (agora - ult_lemb) < timedelta(minutes=int(c.get("intervalo_entre_lembretes_min", 180))):
        return False, "ainda dentro do intervalo entre lembretes"
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
    teste = disparos.numeros_teste(db)
    docs = list(db.collection("conversas").where("aberta", "==", True).stream())   # retrato único para as duas passadas
    for doc in docs:
        conv = doc.to_dict()
        if disparos.e_teste(conv, teste):   # 27/10/2026: número de teste não recebe lembrete
            resumo["pulados"] += 1
            continue
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
    resumo["por_template"] = rodar_por_template(db, docs, agora, dry_run, teste)
    log.info("lembretes: %s", resumo)
    return resumo


# ---------------------------------------------------------------------------------------------------------------------
# Lembrete por template (09/11/2026, decisão da clínica): a conversa em que o lead já escreveu e parou de responder fora
# da janela de 24 h não entra na esteira nem no recontato; ficava parada para sempre (25 conversas em 09/11). Agora recebe
# UM template (TL) e, sem resposta, fecha com status próprio.
# ---------------------------------------------------------------------------------------------------------------------
def _cfg_template() -> dict:
    return _cfg().get("por_template") or {}


def elegivel_template(conv: dict, agora: datetime, cfg: dict | None = None) -> tuple[bool, str]:
    cfg = cfg or _cfg_template()
    frentes_ia = {f for f, c in config.parametros()["frentes"].items() if c.get("ativa")}
    if conv.get("frente") not in frentes_ia:
        return False, "fora das frentes da IA"
    if not conv.get("aberta") or conv.get("modo", "ia") != "ia" or conv.get("opt_out"):
        return False, "fechada/humano/opt-out"
    if conv.get("status") not in set(cfg.get("status_conversa") or ["Em conversa"]):
        return False, f"status {conv.get('status')}"
    if conv.get("lembrete_template_em"):
        return False, "já recebeu o lembrete por template"
    ultima = conv.get("ultima") or {}
    if ultima.get("direcao") != "celeste":   # se a última foi um template (ex.: T4 "vamos encerrar"), a esteira já cuidou; "ficou em aberto" contradiria
        return False, "última mensagem não é texto da Celeste"
    if not conv.get("ultima_msg_lead_em"):
        return False, "lead nunca respondeu (fica com a esteira de templates)"
    em = ultima.get("em")
    if not em or (agora - em) < timedelta(days=int(cfg.get("dias_sem_resposta", 2))):
        return False, "ainda dentro do prazo"
    janela = conv.get("janela_24h_ate")
    if janela and janela > agora:
        return False, "janela de 24 h aberta (lembrete por texto)"
    return True, "ok"


def deve_encerrar(conv: dict, agora: datetime, cfg: dict | None = None) -> bool:
    """Recebeu o template, não respondeu e passou o prazo: fecha a conversa."""
    cfg = cfg or _cfg_template()
    em = conv.get("lembrete_template_em")
    if not em or not conv.get("aberta") or conv.get("modo", "ia") != "ia":
        return False
    if conv.get("status") not in set(cfg.get("status_conversa") or ["Em conversa"]):
        return False
    ul = conv.get("ultima_msg_lead_em")
    if ul and ul >= em:
        return False
    return (agora - em) >= timedelta(days=int(cfg.get("encerrar_apos_dias", 5)))


def primeiro_nome(conv: dict) -> str:
    return ((conv.get("nome") or "").strip().split() or [""])[0].title()


def _registrar_template(db, conv_id: str, conv: dict, codigo: str, nome_tpl: str, wamid: str, nome_lead: str, agora: datetime) -> None:
    conv_ref = db.collection("conversas").document(conv_id)
    conv_ref.collection("mensagens").document(wamid).set({
        "direcao": "template", "tipo": "template", "template": nome_tpl, "codigo": codigo,
        "texto": templates_texto.renderizar(codigo, nome_lead), "recebido_em": agora, "gravado_em": firestore.SERVER_TIMESTAMP})
    conv_ref.set({"lembrete_template_em": agora, "ultimo_template_em": agora,
                  "ultima": {"texto": f"[template {codigo}] " + templates_texto.TEMPLATES[codigo]["corpo"][:120], "direcao": "template", "tipo": "template", "em": agora}}, merge=True)
    if conv.get("contato"):
        db.collection("leads").document(conv["contato"]).set({
            "ultimo_template_em": agora,
            "templates_enviados": firestore.ArrayUnion([{"codigo": codigo, "template": nome_tpl, "em": agora, "wamid": wamid, "motivo": "lembrete por template (conversa em aberto)"}])}, merge=True)
    hoje = datetime.now(FUSO).strftime("%Y-%m-%d")
    db.collection("disparos_diarios").document(hoje).set({f"por_template.{codigo}": firestore.Increment(1), "lembretes_template": firestore.Increment(1)}, merge=True)   # fora de "enviados": não consome a cota da esteira


def _encerrar(db, conv_id: str, conv: dict, agora: datetime, cfg: dict) -> None:
    st = cfg.get("status_encerrada") or "Sem resposta (conversa)"
    db.collection("conversas").document(conv_id).set({"status": st, "aberta": False, "encerrada_em": agora,
                                                      "encerrada_motivo": "sem resposta ao lembrete por template"}, merge=True)
    if conv.get("contato"):
        db.collection("leads").document(conv["contato"]).set({"status_ia": st}, merge=True)


def rodar_por_template(db, docs, agora: datetime, dry_run: bool, teste: set) -> dict:
    cfg = _cfg_template()
    r = {"enviados": 0, "elegiveis": 0, "encerrados": 0, "erros": 0, "detalhe": []}
    if not cfg.get("ativo"):
        r["ignorado"] = "lembretes.por_template.ativo = false"
        return r
    codigo = cfg.get("codigo") or "TL"
    nome_tpl = templates_texto.TEMPLATES[codigo]["nome"]
    mt = None if dry_run else meta.Meta()
    aprovados = None if dry_run else disparos.templates_aprovados(mt)
    if aprovados is not None and nome_tpl not in aprovados:
        r["ignorado"] = f"template {nome_tpl} não aprovado na Meta"
        return r
    for doc in docs:
        conv = doc.to_dict()
        if disparos.e_teste(conv, teste):
            continue
        if deve_encerrar(conv, agora, cfg):
            r["encerrados"] += 1
            if not dry_run:
                _encerrar(db, doc.id, conv, agora, cfg)
            continue
        ok, _ = elegivel_template(conv, agora, cfg)
        if not ok:
            continue
        r["elegiveis"] += 1
        nome_lead = primeiro_nome(conv)
        if dry_run:
            r["detalhe"].append({"conversa": doc.id, "nome": conv.get("nome"), "status": conv.get("status"),
                                 "parada_ha_dias": round((agora - conv["ultima"]["em"]).total_seconds() / 86400, 1)})
            continue
        try:
            wamid = mt.enviar_template(conv["contato"], nome_tpl, templates_texto.parametros(codigo, nome_lead))
        except Exception as e:
            r["erros"] += 1; log.warning("lembrete por template %s: %s", doc.id, e)
            continue
        _registrar_template(db, doc.id, conv, codigo, nome_tpl, wamid, nome_lead, agora)
        r["enviados"] += 1
        time.sleep(random.uniform(2, 6))
    return r
