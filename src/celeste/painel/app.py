# -*- coding: utf-8 -*-
"""Painel da Celeste — CRM mínimo do piloto: métricas por frente, conversas, fila de disparos, encaminhamentos, custo.

Só lê o Firestore (exceto o controle de disparo, gravado em `config/disparos`). Protegido por senha simples
(segredo PAINEL_SENHA) até o IAP entrar.
"""
from __future__ import annotations

import os
import secrets
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from google.cloud import firestore

from celeste.comum import config

app = FastAPI(title="Celeste · Painel")
tpl = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
db = firestore.Client(project=config.PROJETO_GCP)
FUSO = ZoneInfo(config.FUSO)
seguranca = HTTPBasic()
config.SEGREDOS.setdefault("PAINEL_SENHA", "painel-senha")


def autenticar(cred: HTTPBasicCredentials = Depends(seguranca)):
    senha = os.environ.get("PAINEL_SENHA") or _senha()
    if not (secrets.compare_digest(cred.username, "passoni") and secrets.compare_digest(cred.password, senha)):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})
    return cred.username


def _senha() -> str:
    try:
        return config.segredo("PAINEL_SENHA")
    except Exception:
        return "celeste"  # só em desenvolvimento local


def _local(dt) -> str:
    if not dt:
        return ""
    if isinstance(dt, str):
        return dt
    return dt.astimezone(FUSO).strftime("%d/%m %H:%M")


tpl.env.filters["local"] = _local
tpl.env.globals["nome_ia"] = config.parametros()["ia"]["nome_atendente"]
FRENTES = {"leads_perdidos": "Leads Perdidos", "novos_leads": "Novos Leads"}
tpl.env.globals["FRENTES"] = FRENTES


@app.get("/status")  # /healthz é interceptado pelo front-end do Google no Cloud Run
def healthz():
    return {"ok": True, "servico": "painel"}


# ----------------------------------------------------------------- dashboard
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, _=Depends(autenticar)):
    hoje = datetime.now(FUSO).strftime("%Y-%m-%d")
    mes = hoje[:7]
    conversas = [dict(c.to_dict(), id=c.id) for c in db.collection("conversas").stream()]
    por_frente = {}
    for f in FRENTES:
        cs = [c for c in conversas if c.get("frente") == f]
        respondidas = [c for c in cs if c.get("ultima_msg_lead_em")]
        por_frente[f] = {
            "conversas": len(cs), "abertas": sum(1 for c in cs if c.get("aberta")),
            "respondidas": len(respondidas), "agendados": sum(1 for c in cs if c.get("status") == "Agendado"),
            "encaminhados": sum(1 for c in cs if c.get("status") == "Encaminhado à recepção"),
            "opt_out": sum(1 for c in cs if c.get("opt_out")),
            "status": Counter(c.get("status") or "—" for c in cs).most_common(),
        }
    leads = Counter()
    elegiveis = 0
    for l in db.collection("leads").select(["status_ia", "elegivel"]).stream():
        d = l.to_dict()
        if d.get("elegivel"):
            elegiveis += 1
            leads[d.get("status_ia") or "Não contatado"] += 1
    custo_hoje = (db.collection("custos_diarios").document(hoje).get().to_dict() or {})
    custo_mes = sum((c.to_dict() or {}).get("custo_usd", 0) for c in db.collection("custos_diarios").stream() if c.id.startswith(mes))
    disp_hoje = db.collection("disparos_diarios").document(hoje).get().to_dict() or {}
    disp_cfg = dict(config.parametros()["disparos"])
    disp_cfg.update(db.collection("config").document("disparos").get().to_dict() or {})
    templates = _metricas_templates(conversas)
    atend = dict(config.parametros()["ia"])
    atend.update(db.collection("config").document("atendimento").get().to_dict() or {})
    return tpl.TemplateResponse(request, "dashboard.html", {
        "atend": {"modo": atend.get("modo", "teste"), "numeros_teste": atend.get("numeros_teste") or []},
        "por_frente": por_frente, "leads": leads.most_common(), "elegiveis": elegiveis, "custo_hoje": custo_hoje,
        "custo_mes": custo_mes, "disp_hoje": disp_hoje, "disp_cfg": disp_cfg, "templates": templates,
        "cap": config.parametros()["modelos"]["cap_diario_usd"], "hoje": hoje})


def _metricas_templates(conversas: list[dict]) -> list[dict]:
    """enviados / respondidos / agendados por código de template (T1..T5), a partir das conversas abertas por disparo."""
    m = defaultdict(lambda: {"enviados": 0, "respondidos": 0, "agendados": 0})
    for c in conversas:
        t = c.get("template_origem")
        if not t:
            continue
        m[t]["enviados"] += 1
        if c.get("ultima_msg_lead_em"):
            m[t]["respondidos"] += 1
        if c.get("status") == "Agendado":
            m[t]["agendados"] += 1
    nomes = config.parametros()["disparos"]["templates"]
    out = []
    for t in sorted(m):
        e = m[t]
        out.append({"codigo": t, "nome": nomes.get(t, t), **e, "taxa": f"{100 * e['respondidos'] / e['enviados']:.0f}%" if e["enviados"] else "—"})
    return out


@app.post("/config/atendimento")
def salvar_atendimento(modo: str = Form("teste"), numeros_teste: str = Form(""), _=Depends(autenticar)):
    numeros = ["".join(ch for ch in n if ch.isdigit()) for n in numeros_teste.replace(";", ",").replace("\n", ",").split(",")]
    db.collection("config").document("atendimento").set({
        "modo": modo if modo in ("teste", "producao", "aberto") else "teste", "numeros_teste": [n for n in numeros if len(n) >= 12],
        "alterado_em": firestore.SERVER_TIMESTAMP}, merge=True)
    return RedirectResponse("/", status_code=303)


@app.post("/config/disparos")
def salvar_disparos(ativo: str = Form("off"), limite_diario: int = Form(100), limite_por_execucao: int = Form(25), _=Depends(autenticar)):
    db.collection("config").document("disparos").set({
        "ativo": ativo == "on", "limite_diario": max(0, limite_diario), "limite_por_execucao": max(0, limite_por_execucao),
        "alterado_em": firestore.SERVER_TIMESTAMP}, merge=True)
    return RedirectResponse("/", status_code=303)


# ----------------------------------------------------------------- conversas
@app.get("/conversas", response_class=HTMLResponse)
def conversas(request: Request, frente: str = "", status: str = "", abertas: str = "", _=Depends(autenticar)):
    q = db.collection("conversas")
    if frente:
        q = q.where("frente", "==", frente)
    docs = [dict(c.to_dict(), id=c.id) for c in q.stream()]
    if status:
        docs = [c for c in docs if c.get("status") == status]
    if abertas:
        docs = [c for c in docs if c.get("aberta")]
    docs.sort(key=lambda c: (c.get("ultima_msg_lead_em") or c.get("criado_em") or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    statuses = sorted({c.get("status") for c in docs if c.get("status")})
    return tpl.TemplateResponse(request, "conversas.html", {"conversas": docs[:300], "total": len(docs), "frente": frente,
                                                            "status": status, "abertas": abertas, "statuses": statuses})


@app.get("/conversas/{cid}", response_class=HTMLResponse)
def conversa(request: Request, cid: str, _=Depends(autenticar)):
    ref = db.collection("conversas").document(cid)
    c = ref.get().to_dict()
    if not c:
        raise HTTPException(404)
    msgs = [dict(m.to_dict(), id=m.id) for m in ref.collection("mensagens").order_by("recebido_em").stream()]
    chamadas = [x.to_dict() for x in db.collection("chamadas_ia").where("conversa_id", "==", cid).stream()]
    chamadas.sort(key=lambda x: x.get("em") or datetime.min.replace(tzinfo=timezone.utc))
    lead = db.collection("leads").document(c.get("contato", "")).get().to_dict() or {}
    return tpl.TemplateResponse(request, "conversa.html", {"c": dict(c, id=cid), "msgs": msgs, "chamadas": chamadas, "lead": lead,
                                                           "custo": sum(x.get("custo_usd", 0) for x in chamadas)})


# ----------------------------------------------------------------- fila e encaminhamentos
@app.get("/fila", response_class=HTMLResponse)
def fila(request: Request, status: str = "", _=Depends(autenticar)):
    q = db.collection("leads").where("elegivel", "==", True)
    if status:
        q = q.where("status_ia", "==", status)
    docs = [dict(l.to_dict(), id=l.id) for l in q.limit(500).stream()]
    docs.sort(key=lambda l: l.get("lead_created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return tpl.TemplateResponse(request, "fila.html", {"leads": docs, "status": status,
                                                       "statuses": config.parametros()["leads_perdidos"]["status_ia"]})


@app.get("/encaminhamentos", response_class=HTMLResponse)
def encaminhamentos(request: Request, _=Depends(autenticar)):
    docs = [dict(e.to_dict(), id=e.id) for e in db.collection("encaminhamentos").order_by("em", direction=firestore.Query.DESCENDING).limit(200).stream()]
    return tpl.TemplateResponse(request, "encaminhamentos.html", {"itens": docs})


@app.post("/encaminhamentos/{eid}/atendido")
def marcar_atendido(eid: str, _=Depends(autenticar)):
    db.collection("encaminhamentos").document(eid).set({"atendido": True, "atendido_em": firestore.SERVER_TIMESTAMP}, merge=True)
    return RedirectResponse("/encaminhamentos", status_code=303)
