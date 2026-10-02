# -*- coding: utf-8 -*-
"""CRM Celeste — painel da clínica.

Abas: Gestão e Performance · Atendimentos · Listas · Frentes de Trabalho · Templates.
Só lê o Firestore (exceto configurações em `config/*`), chama o orquestrador/jobs por OIDC para ações.
Protegido por senha simples (segredo PAINEL_SENHA).
"""
from __future__ import annotations

import os
import secrets
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import markdown
import requests
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from google.auth.transport.requests import Request as GRequest
from google.cloud import firestore
from google.oauth2 import id_token

from celeste.comum import config
from celeste.orquestrador.prompt import renderizar

app = FastAPI(title="CRM Celeste")
tpl = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
db = firestore.Client(project=config.PROJETO_GCP)
FUSO = ZoneInfo(config.FUSO)
seguranca = HTTPBasic()
config.SEGREDOS.setdefault("PAINEL_SENHA", "painel-senha")
URL_ORQUESTRADOR = os.environ.get("URL_ORQUESTRADOR", "")
URL_JOBS = os.environ.get("URL_JOBS", "")
FRENTES = {"leads_perdidos": "Leads Perdidos", "novos_leads": "Novos Leads"}
POR_PAGINA = 200


# ----------------------------------------------------------------- autenticação e utilidades
def autenticar(cred: HTTPBasicCredentials = Depends(seguranca)):
    senha = os.environ.get("PAINEL_SENHA") or _senha()
    if not (secrets.compare_digest(cred.username, "passoni") and secrets.compare_digest(cred.password, senha)):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})
    return cred.username


def _senha() -> str:
    try:
        return config.segredo("PAINEL_SENHA")
    except Exception:
        return "celeste"


def _local(dt, fmt="%d/%m %H:%M") -> str:
    if not dt:
        return ""
    if isinstance(dt, str):
        return dt
    return dt.astimezone(FUSO).strftime(fmt)


def _dt(v):
    """Normaliza valores de data vindos do Firestore para datetime UTC (ou None)."""
    if v is None or isinstance(v, str):
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def _periodo(de: str, ate: str):
    hoje = datetime.now(FUSO).date()
    d = date.fromisoformat(de) if de else hoje.replace(day=1)
    a = date.fromisoformat(ate) if ate else hoje
    ini = datetime.combine(d, time.min, tzinfo=FUSO).astimezone(timezone.utc)
    fim = datetime.combine(a + timedelta(days=1), time.min, tzinfo=FUSO).astimezone(timezone.utc)
    return d, a, ini, fim


def _no_periodo(v, ini, fim) -> bool:
    v = _dt(v)
    return bool(v and ini <= v < fim)


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "—"


def _oidc_post(url: str, caminho: str, corpo: dict, timeout=120):
    tok = id_token.fetch_id_token(GRequest(), url)
    return requests.post(f"{url}{caminho}", json=corpo, headers={"Authorization": f"Bearer {tok}"}, timeout=timeout)


tpl.env.filters["local"] = _local
tpl.env.globals["nome_ia"] = config.parametros()["ia"]["nome_atendente"]
tpl.env.globals["FRENTES"] = FRENTES
tpl.env.globals["rotulo_frente"] = lambda f, camp=None: (camp or "Campanha") if f == "campanha" else (FRENTES.get(f) or "Sem frente")


@app.get("/status")
def status():
    return {"ok": True, "servico": "painel"}


# ================================================================= 1. GESTÃO E PERFORMANCE
@app.get("/", response_class=HTMLResponse)
def gestao(request: Request, de: str = "", ate: str = "", aviso: str = "", _=Depends(autenticar)):
    d, a, ini, fim = _periodo(de, ate)
    hoje = datetime.now(FUSO).strftime("%Y-%m-%d")

    leads = [l.to_dict() for l in db.collection("leads").select(["frente", "disponibilizado_em", "carregado_em", "elegivel"]).stream()]
    conversas = [dict(c.to_dict(), id=c.id) for c in db.collection("conversas").stream()]

    funil = {}
    for f in FRENTES:
        ls = [l for l in leads if l.get("frente") == f]
        cs = [c for c in conversas if c.get("frente") == f]
        disponibilizados = sum(1 for l in ls if _no_periodo(l.get("disponibilizado_em") or l.get("carregado_em"), ini, fim))
        conversados = [c for c in cs if _no_periodo(c.get("primeira_msg_celeste_em") or c.get("ultimo_template_em") or c.get("ultima_msg_celeste_em"), ini, fim)]
        com_resposta = [c for c in cs if _no_periodo(c.get("primeira_msg_lead_em") or c.get("ultima_msg_lead_em"), ini, fim)]
        marcados = [c for c in cs if c.get("status") == "Agendado" and _no_periodo(c.get("agendado_em") or c.get("criado_em"), ini, fim)]
        sair = [c for c in cs if c.get("opt_out") and _no_periodo(c.get("opt_out_em") or c.get("ultima_msg_lead_em"), ini, fim)]
        comparecidos = [c for c in cs if c.get("compareceu") and _no_periodo(c.get("compareceu_em"), ini, fim)]
        funil[f] = {
            "disponibilizados": disponibilizados, "conversados": len(conversados), "com_resposta": len(com_resposta),
            "marcados": len(marcados), "sair": len(sair), "comparecidos": len(comparecidos), "vendas": None, "faturamento": None,
            "ef_resposta": _pct(len(com_resposta), len(conversados)), "ef_marcacao": _pct(len(marcados), len(conversados)),
            "ef_comparecimento": _pct(len(comparecidos), len(marcados)), "ef_global": _pct(len(marcados), disponibilizados),
            "custo": sum(float(c.get("custo_usd") or 0) for c in conversados),
        }
    total = {k: (sum(funil[f][k] for f in FRENTES) if isinstance(funil["leads_perdidos"][k], int) else None)
             for k in ("disponibilizados", "conversados", "com_resposta", "marcados", "sair", "comparecidos", "vendas", "faturamento")}
    total["ef_resposta"] = _pct(total["com_resposta"], total["conversados"])
    total["ef_marcacao"] = _pct(total["marcados"], total["conversados"])
    total["ef_comparecimento"] = _pct(total["comparecidos"], total["marcados"])
    total["ef_global"] = _pct(total["marcados"], total["disponibilizados"])
    total["custo"] = sum(funil[f]["custo"] for f in FRENTES)

    # gráfico diário: conversas distintas em que a Celeste mandou ≥ 1 mensagem (template ou IA), por dia e frente
    frente_de = {c["id"]: c.get("frente") for c in conversas}
    por_dia: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    try:
        q = (db.collection_group("mensagens").where("direcao", "in", ["celeste", "template"])
             .where("recebido_em", ">=", ini).where("recebido_em", "<", fim))
        for m in q.stream():
            cid = m.reference.parent.parent.id
            dia = _dt(m.to_dict().get("recebido_em")).astimezone(FUSO).strftime("%Y-%m-%d")
            por_dia[dia][frente_de.get(cid) or "outros"].add(cid)
    except Exception as e:  # índice ainda propagando
        por_dia = defaultdict(lambda: defaultdict(set)); aviso = aviso or f"Gráfico diário indisponível no momento ({str(e)[:80]})"
    dias = [(d + timedelta(days=i)).isoformat() for i in range((a - d).days + 1)]
    serie = {f: [len(por_dia[x][f]) for x in dias] for f in list(FRENTES) + ["outros"]}

    # campanhas da recepção
    campanhas: dict[str, dict] = {}
    for cc in db.collection("campanha_contatos").select(["campanha"]).stream():
        k = cc.to_dict().get("campanha") or "Campanha"
        campanhas.setdefault(k, {"enviados": 0, "responderam": 0, "orientados": 0})["enviados"] += 1
    for c in conversas:
        if c.get("frente") == "campanha":
            k = c.get("campanha") or "Campanha"
            campanhas.setdefault(k, {"enviados": 0, "responderam": 0, "orientados": 0})["responderam"] += 1
            if c.get("orientado_recepcao_em"):
                campanhas[k]["orientados"] += 1

    custo_hoje = (db.collection("custos_diarios").document(hoje).get().to_dict() or {}).get("custo_usd", 0)
    custo_mes = sum((c.to_dict() or {}).get("custo_usd", 0) for c in db.collection("custos_diarios").stream() if c.id.startswith(hoje[:7]))
    sem_frente = sum(1 for c in conversas if not c.get("frente"))
    encaminhados_abertos = sum(1 for e in db.collection("encaminhamentos").where("atendido", "==", False).stream())
    return tpl.TemplateResponse(request, "gestao.html", {
        "de": d.isoformat(), "ate": a.isoformat(), "funil": funil, "total": total, "dias": dias, "serie": serie,
        "campanhas": dict(sorted(campanhas.items())), "custo_hoje": custo_hoje, "custo_mes": custo_mes,
        "cap": config.parametros()["modelos"]["cap_diario_usd"], "elegiveis": sum(1 for l in leads if l.get("elegivel")),
        "abertas": sum(1 for c in conversas if c.get("aberta")), "sem_frente": sem_frente, "encaminhados_abertos": encaminhados_abertos,
        "aviso": aviso, "atalhos": _atalhos(),
    })


def _atalhos():
    hoje = datetime.now(FUSO).date()
    m1 = (hoje.replace(day=1) - timedelta(days=1))
    return [("Hoje", hoje, hoje), ("7 dias", hoje - timedelta(days=6), hoje), ("Mês atual", hoje.replace(day=1), hoje),
            ("Mês anterior", m1.replace(day=1), m1), ("30 dias", hoje - timedelta(days=29), hoje)]


# ================================================================= 2. ATENDIMENTOS (lista + conversa; versão WhatsApp na próxima entrega)
@app.get("/conversas", response_class=HTMLResponse)
def conversas(request: Request, frente: str = "", status: str = "", abertas: str = "", busca: str = "", _=Depends(autenticar)):
    docs = [dict(c.to_dict(), id=c.id) for c in db.collection("conversas").stream()]
    if frente == "sem_frente":
        docs = [c for c in docs if not c.get("frente")]
    elif frente.startswith("campanha:"):
        docs = [c for c in docs if c.get("frente") == "campanha" and c.get("campanha") == frente[9:]]
    elif frente:
        docs = [c for c in docs if c.get("frente") == frente]
    if status:
        docs = [c for c in docs if c.get("status") == status]
    if abertas:
        docs = [c for c in docs if c.get("aberta")]
    if busca:
        b = busca.lower()
        docs = [c for c in docs if b in (c.get("nome") or "").lower() or b in (c.get("contato") or "")]
    docs.sort(key=lambda c: (_dt(c.get("ultima_msg_lead_em")) or _dt(c.get("criado_em")) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    statuses = sorted({c.get("status") for c in db.collection("conversas").select(["status"]).stream() for c in [c.to_dict()] if c.get("status")})
    campanhas_lista = sorted({x.get("campanha") for x in (c.to_dict() for c in db.collection("conversas").select(["campanha"]).stream()) if x.get("campanha")})
    return tpl.TemplateResponse(request, "conversas.html", {"conversas": docs[:300], "total": len(docs), "frente": frente, "status": status,
                                                            "abertas": abertas, "busca": busca, "statuses": statuses, "campanhas_lista": campanhas_lista})


@app.get("/conversas/{cid}", response_class=HTMLResponse)
def conversa(request: Request, cid: str, aviso: str = "", _=Depends(autenticar)):
    ref = db.collection("conversas").document(cid)
    c = ref.get().to_dict()
    if not c:
        raise HTTPException(404)
    msgs = [dict(m.to_dict(), id=m.id) for m in ref.collection("mensagens").order_by("recebido_em").stream()]
    chamadas = [x.to_dict() for x in db.collection("chamadas_ia").where("conversa_id", "==", cid).stream()]
    chamadas.sort(key=lambda x: _dt(x.get("em")) or datetime.min.replace(tzinfo=timezone.utc))
    lead = db.collection("leads").document(c.get("contato", "")).get().to_dict() or {}
    return tpl.TemplateResponse(request, "conversa.html", {"c": dict(c, id=cid), "msgs": msgs, "chamadas": chamadas, "lead": lead, "aviso": aviso,
                                                           "custo": sum(x.get("custo_usd", 0) for x in chamadas)})


@app.post("/conversas/{cid}/orientar")
def orientar(cid: str, _=Depends(autenticar)):
    if not URL_ORQUESTRADOR:
        return RedirectResponse(f"/conversas/{cid}?aviso=URL do orquestrador não configurada", status_code=303)
    try:
        r = _oidc_post(URL_ORQUESTRADOR, "/orientar", {"conversa_id": cid}, timeout=60)
        aviso = "Orientação enviada." if r.ok else (r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text[:160])
    except Exception as e:
        aviso = f"Falha: {str(e)[:160]}"
    return RedirectResponse(f"/conversas/{cid}?aviso={aviso}", status_code=303)


@app.get("/encaminhamentos", response_class=HTMLResponse)
def encaminhamentos(request: Request, _=Depends(autenticar)):
    docs = [dict(e.to_dict(), id=e.id) for e in db.collection("encaminhamentos").order_by("em", direction=firestore.Query.DESCENDING).limit(200).stream()]
    return tpl.TemplateResponse(request, "encaminhamentos.html", {"itens": docs})


@app.post("/encaminhamentos/{eid}/atendido")
def marcar_atendido(eid: str, _=Depends(autenticar)):
    db.collection("encaminhamentos").document(eid).set({"atendido": True, "atendido_em": firestore.SERVER_TIMESTAMP}, merge=True)
    return RedirectResponse("/encaminhamentos", status_code=303)


# ================================================================= 3. LISTAS
@app.get("/listas", response_class=HTMLResponse)
def listas(request: Request, frente: str = "leads_perdidos", status: str = "", pagina: int = 1, _=Depends(autenticar)):
    pagina = max(1, pagina)
    campanhas_lista = sorted({x.get("campanha") for x in (c.to_dict() for c in db.collection("campanha_contatos").select(["campanha"]).stream()) if x.get("campanha")})
    conv_por_contato = {x.get("contato"): cid for cid, x in ((c.id, c.to_dict()) for c in db.collection("conversas").select(["contato", "aberta"]).stream())}
    if frente.startswith("campanha:"):
        q = db.collection("campanha_contatos").where("campanha", "==", frente[9:])
        total = q.count().get()[0][0].value
        itens = []
        for d in q.order_by("ultimo_envio_em", direction=firestore.Query.DESCENDING).offset((pagina - 1) * POR_PAGINA).limit(POR_PAGINA).stream():
            x = d.to_dict()
            itens.append({"nome": x.get("nome"), "celular": x.get("celular"), "origem": x.get("acao"), "lead_created_at": x.get("ultimo_envio_em"),
                          "status_clinica": x.get("status_fluxo"), "status_ia": "Campanha (recepção)", "passo": "—", "ultimo_template_em": x.get("ultimo_envio_em"),
                          "conversa_id": conv_por_contato.get(x.get("celular"))})
        statuses = []
    else:
        q = db.collection("leads").where("frente", "==", frente)
        if status:
            q = q.where("status_ia", "==", status)
        total = q.count().get()[0][0].value
        itens = [d.to_dict() for d in q.order_by("lead_created_at", direction=firestore.Query.DESCENDING).offset((pagina - 1) * POR_PAGINA).limit(POR_PAGINA).stream()]
        statuses = config.parametros()["leads_perdidos"]["status_ia"]
    paginas = max(1, -(-total // POR_PAGINA))
    por_status = Counter()
    if not frente.startswith("campanha:"):
        for d in db.collection("leads").where("frente", "==", frente).select(["status_ia", "elegivel"]).stream():
            x = d.to_dict(); por_status[("elegível" if x.get("elegivel") else "fora da base")] += 1
    return tpl.TemplateResponse(request, "listas.html", {"itens": itens, "total": total, "pagina": pagina, "paginas": paginas, "frente": frente,
                                                         "status": status, "statuses": statuses, "campanhas_lista": campanhas_lista,
                                                         "por_status": dict(por_status), "por_pagina": POR_PAGINA})


# ================================================================= 4. FRENTES DE TRABALHO
DOCS = {"prompt": ("Prompt da frente", None), "conhecimento": ("Base de conhecimento da clínica", "knowledge/01-base-conhecimento-clinica.md"),
        "linguagem": ("Guia de linguagem", "knowledge/02-guia-de-linguagem.md")}


def _resumo_prompt(caminho: str) -> str:
    try:
        txt = (config.RAIZ / caminho).read_text(encoding="utf-8")
    except Exception:
        return "(prompt ainda não escrito)"
    txt = renderizar(txt, config.parametros())
    corpo = txt.split("\n---\n", 1)[1] if "\n---\n" in txt else txt
    paras = [p.strip() for p in corpo.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    return "\n\n".join(paras[:2])[:900]


@app.get("/frentes", response_class=HTMLResponse)
def frentes(request: Request, aviso: str = "", _=Depends(autenticar)):
    p = config.parametros()
    itens = []
    for chave, cfg in p["frentes"].items():
        itens.append({"chave": chave, "nome": FRENTES.get(chave, chave.replace("_", " ").title()), "ativa": cfg.get("ativa"),
                      "prompt": cfg.get("prompt"), "resumo": _resumo_prompt(cfg.get("prompt", "")) if cfg.get("ativa") else "Em breve."})
    atend = dict(p["ia"]); atend.update(db.collection("config").document("atendimento").get().to_dict() or {})
    disp = dict(p["disparos"]); disp.update(db.collection("config").document("disparos").get().to_dict() or {})
    return tpl.TemplateResponse(request, "frentes.html", {
        "itens": itens, "aviso": aviso, "docs": DOCS,
        "atend": {"modo": atend.get("modo", "teste"), "numeros_teste": atend.get("numeros_teste") or [],
                  "orientar_automatico": atend.get("orientar_automatico", p["ia"]["recepcao"].get("orientar_nao_leads", False))},
        "disp": disp, "consultas": p["consultas"], "recepcao": p["ia"]["recepcao"], "lp": p["leads_perdidos"]})


@app.get("/frentes/{frente}/doc/{qual}", response_class=HTMLResponse)
def doc(request: Request, frente: str, qual: str, _=Depends(autenticar)):
    if qual not in DOCS or frente not in config.parametros()["frentes"]:
        raise HTTPException(404)
    titulo, caminho = DOCS[qual]
    if qual == "prompt":
        caminho = config.parametros()["frentes"][frente].get("prompt")
    try:
        txt = (config.RAIZ / caminho).read_text(encoding="utf-8")
    except Exception:
        raise HTTPException(404, "arquivo não encontrado")
    html = markdown.markdown(renderizar(txt, config.parametros()), extensions=["tables", "fenced_code", "toc"])
    return tpl.TemplateResponse(request, "doc.html", {"titulo": f"{titulo} · {FRENTES.get(frente, frente)}", "html": html, "caminho": caminho})


@app.post("/config/atendimento")
def salvar_atendimento(modo: str = Form("teste"), numeros_teste: str = Form(""), orientar_automatico: str = Form("off"), _=Depends(autenticar)):
    numeros = ["".join(ch for ch in n if ch.isdigit()) for n in numeros_teste.replace(";", ",").replace("\n", ",").split(",")]
    db.collection("config").document("atendimento").set({
        "modo": modo if modo in ("teste", "producao", "aberto") else "teste", "numeros_teste": [n for n in numeros if len(n) >= 12],
        "orientar_automatico": orientar_automatico == "on", "alterado_em": firestore.SERVER_TIMESTAMP}, merge=True)
    return RedirectResponse("/frentes?aviso=Modo de atendimento salvo.", status_code=303)


@app.post("/config/disparos")
def salvar_disparos(ativo: str = Form("off"), limite_diario: int = Form(100), limite_por_execucao: int = Form(25), _=Depends(autenticar)):
    db.collection("config").document("disparos").set({
        "ativo": ativo == "on", "limite_diario": max(0, limite_diario), "limite_por_execucao": max(0, limite_por_execucao),
        "alterado_em": firestore.SERVER_TIMESTAMP}, merge=True)
    return RedirectResponse("/frentes?aviso=Controle de disparo salvo.", status_code=303)


@app.post("/campanhas/sincronizar")
def sincronizar_campanhas(_=Depends(autenticar)):
    if not URL_JOBS:
        return RedirectResponse("/?aviso=URL do serviço de jobs não configurada", status_code=303)
    try:
        r = _oidc_post(URL_JOBS, "/jobs/campanhas", {}, timeout=300)
        j = r.json() if r.ok else {}
        aviso = f"Campanhas sincronizadas: {j.get('importados', 0)} contatos, {j.get('conversas_rotuladas', 0)} conversas rotuladas." if r.ok else f"Falha: {r.text[:160]}"
    except Exception as e:
        aviso = f"Falha: {str(e)[:160]}"
    return RedirectResponse(f"/?aviso={aviso}", status_code=303)


# ================================================================= 5. TEMPLATES
@app.get("/templates", response_class=HTMLResponse)
def templates(request: Request, _=Depends(autenticar)):
    p = config.parametros()
    usados = set(p["disparos"]["templates"].values()) | {p["ia"]["recepcao"].get("template_aviso")}
    itens, erro = [], ""
    try:
        from celeste.ferramentas import meta
        for t in meta.Meta().templates():
            comps = {c.get("type"): c for c in t.get("components", [])}
            botoes = [b.get("text") for b in (comps.get("BUTTONS") or {}).get("buttons", [])]
            itens.append({"nome": t.get("name"), "status": t.get("status"), "categoria": t.get("category"), "idioma": t.get("language"),
                          "cabecalho": (comps.get("HEADER") or {}).get("text"), "corpo": (comps.get("BODY") or {}).get("text"),
                          "rodape": (comps.get("FOOTER") or {}).get("text"), "botoes": botoes, "celeste": t.get("name") in usados})
    except Exception as e:
        erro = str(e)[:200]
    ordem = {"APPROVED": 0, "PENDING": 1, "IN_APPEAL": 2, "REJECTED": 3}
    itens.sort(key=lambda x: (not x["celeste"], ordem.get(x["status"], 9), x["nome"] or ""))
    return tpl.TemplateResponse(request, "templates.html", {"itens": itens, "erro": erro, "usados": sorted(u for u in usados if u)})
