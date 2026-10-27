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
FRENTES_IA = {f for f, cfg in config.parametros()["frentes"].items() if cfg.get("ativa")}   # frentes que a Celeste trabalha hoje
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
    return f"{100 * a / b:.1f}%" if b else "0%"


def _oidc_post(url: str, caminho: str, corpo: dict, timeout=120):
    tok = id_token.fetch_id_token(GRequest(), url)
    return requests.post(f"{url}{caminho}", json=corpo, headers={"Authorization": f"Bearer {tok}"}, timeout=timeout)


tpl.env.filters["local"] = _local
tpl.env.globals["nome_ia"] = config.parametros()["ia"]["nome_atendente"]
tpl.env.globals["numero_ia"] = "+55 11 94231-5926"   # número oficial da clínica na Meta (phone_number_id 1219345307926640)
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

    # só os elegíveis (base atual): quem saiu da base não entra em nenhuma conta da Gestão
    leads = [l.to_dict() for l in db.collection("leads").where("elegivel", "==", True).select(["frente", "elegivel", "teste"]).stream()]
    leads = [l for l in leads if not l.get("teste")]   # 25/10/2026: lead de teste (simulação da esteira) não entra na Gestão
    conversas = [dict(c.to_dict(), id=c.id) for c in db.collection("conversas").stream() if not (c.to_dict() or {}).get("teste")]

    dias = [(d + timedelta(days=i)).isoformat() for i in range((a - d).days + 1)]
    n_dias = max(1, len(dias))
    hoje_d = datetime.now(FUSO).date().isoformat()

    # mensagens que a Celeste ENVIOU no período (template ou IA; orientação/botão da recepção e humano não contam)
    frente_de = {c["id"]: c.get("frente") for c in conversas}
    por_dia: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    conv_msg: dict[str, set] = defaultdict(set)      # frente → conversas com mensagem da Celeste no período
    n_msgs: dict[str, int] = defaultdict(int)        # frente → mensagens enviadas no período
    try:
        q = (db.collection_group("mensagens").where("direcao", "in", ["celeste", "template"])
             .where("recebido_em", ">=", ini).where("recebido_em", "<", fim))
        for m in q.stream():
            x = m.to_dict()
            if x.get("tipo") == "interactive" or (x.get("modelo") or "").startswith("automatico"):
                continue
            cid = m.reference.parent.parent.id
            fr = frente_de.get(cid) if frente_de.get(cid) in FRENTES_IA else "sem_frente"
            dia = _dt(x.get("recebido_em")).astimezone(FUSO).strftime("%Y-%m-%d")
            por_dia[dia][fr].add(cid); conv_msg[fr].add(cid); n_msgs[fr] += 1
    except Exception as e:  # índice ainda propagando
        aviso = aviso or f"Dados de mensagens indisponíveis no momento ({str(e)[:80]})"
    serie = {f: [len(por_dia[x][f]) for x in dias] for f in ["leads_perdidos", "sem_frente"]}

    funil = {}
    for f in FRENTES:
        ls = [l for l in leads if l.get("frente") == f]
        cs = [c for c in conversas if c.get("frente") == f]
        disponibilizados = len(ls)                                                   # 1. base elegível (query da clínica)
        conversados = len(conv_msg.get(f, set()))                                    # 2. distintos com msg da Celeste no período
        msgs = n_msgs.get(f, 0)                                                      # 4. mensagens enviadas
        primeira_vez = sum(1 for c in cs if _no_periodo(c.get("primeira_msg_celeste_em") or c.get("ultimo_template_em"), ini, fim))  # 6.
        marcados = [c for c in cs if c.get("agendado_em") and _no_periodo(c.get("agendado_em"), ini, fim)]                           # 8.
        decorridos = [c for c in marcados if (c.get("agendamento") or {}).get("data", "9999") < hoje_d]                              # 11.
        comparecidos = [c for c in cs if c.get("compareceu") and _no_periodo(c.get("compareceu_em") or c.get("agendado_em"), ini, fim)]  # 12.
        sair = sum(1 for c in cs if c.get("opt_out") and _no_periodo(c.get("opt_out_em") or c.get("ultima_msg_lead_em"), ini, fim))
        ef1 = (len(marcados) / disponibilizados) if disponibilizados else None
        ef2 = (len(comparecidos) / len(decorridos)) if decorridos else None
        funil[f] = {
            "disponibilizados": disponibilizados, "conversados": conversados, "conversados_dia": round(conversados / n_dias, 1),
            "msgs_dia": round(msgs / n_dias, 1), "pct_conversados": _pct(conversados, disponibilizados),
            "primeira_vez": primeira_vez, "primeira_vez_dia": round(primeira_vez / n_dias, 1),
            "marcados": len(marcados), "ef1": _pct(len(marcados), disponibilizados),
            "agendados_mes": None, "decorridos": len(decorridos), "comparecidos": len(comparecidos),
            "ef2": _pct(len(comparecidos), len(decorridos)), "vendas": None, "faturamento": None, "ef3": None,
            "ef_global": None, "sair": sair, "_msgs": msgs, "_ef1": ef1, "_ef2": ef2,
        }
    inteiros = ("disponibilizados", "conversados", "primeira_vez", "marcados", "decorridos", "comparecidos", "sair", "_msgs")
    total = {k: sum(funil[f][k] for f in FRENTES) for k in inteiros}
    total.update({"conversados_dia": round(total["conversados"] / n_dias, 1), "msgs_dia": round(total["_msgs"] / n_dias, 1),
                  "pct_conversados": _pct(total["conversados"], total["disponibilizados"]),
                  "primeira_vez_dia": round(total["primeira_vez"] / n_dias, 1), "ef1": _pct(total["marcados"], total["disponibilizados"]),
                  "agendados_mes": None, "ef2": _pct(total["comparecidos"], total["decorridos"]), "vendas": None, "faturamento": None,
                  "ef3": None, "ef_global": None})

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

    # 16/10/2026: o custo mostrado inclui a manutenção do cache (pings a cada 50 min e regravação após publicar), que antes ficava fora
    # e fazia o painel não bater com o painel da Anthropic. `custo_usd` = conversas; `aquecer_cache_usd` = cache.
    dh = db.collection("custos_diarios").document(hoje).get().to_dict() or {}
    conv_hoje, cache_hoje = dh.get("custo_usd", 0), dh.get("aquecer_cache_usd", 0)
    docs_mes = [(c.to_dict() or {}) for c in db.collection("custos_diarios").stream() if c.id.startswith(hoje[:7])]
    conv_mes, cache_mes = sum(x.get("custo_usd", 0) for x in docs_mes), sum(x.get("aquecer_cache_usd", 0) for x in docs_mes)
    custo_hoje, custo_mes = conv_hoje + cache_hoje, conv_mes + cache_mes
    sem_frente = sum(1 for c in conversas if c.get("frente") not in FRENTES_IA)          # tudo que não é frente da IA
    encaminhados = sum(1 for c in conversas if c.get("orientado_recepcao_em"))           # receberam a mensagem da recepção
    abertas_ia = sum(1 for c in conversas if c.get("frente") in FRENTES_IA and c.get("aberta")
                     and (c.get("primeira_msg_celeste_em") or c.get("ultimo_template_em")))
    return tpl.TemplateResponse(request, "gestao.html", {
        "de": d.isoformat(), "ate": a.isoformat(), "funil": funil, "total": total, "dias": dias, "serie": serie,
        "campanhas": dict(sorted(campanhas.items())), "custo_hoje": custo_hoje, "custo_mes": custo_mes,
        "conv_hoje": conv_hoje, "cache_hoje": cache_hoje, "conv_mes": conv_mes, "cache_mes": cache_mes,
        "cap": config.parametros()["modelos"]["cap_diario_usd"], "elegiveis": sum(1 for l in leads if l.get("elegivel")),
        "abertas": abertas_ia, "sem_frente": sem_frente, "encaminhados": encaminhados,
        "aviso": aviso, "atalhos": _atalhos(),
    })


def _atalhos():
    hoje = datetime.now(FUSO).date()
    m1 = (hoje.replace(day=1) - timedelta(days=1))
    return [("Hoje", hoje, hoje), ("7 dias", hoje - timedelta(days=6), hoje), ("Mês atual", hoje.replace(day=1), hoje),
            ("Mês anterior", m1.replace(day=1), m1), ("30 dias", hoje - timedelta(days=29), hoje)]


# ================================================================= 2. ATENDIMENTOS (estilo WhatsApp Web)
from fastapi.responses import JSONResponse


def _json_dt(v):
    v = _dt(v)
    return v.astimezone(FUSO).isoformat() if v else None


def _resumo_conversa(c: dict) -> dict:
    u = c.get("ultima") or {}
    return {"id": c["id"], "nome": c.get("nome") or "(sem nome)", "contato": c.get("contato"), "frente": c.get("frente"),
            "campanha": c.get("campanha"), "rotulo": tpl.env.globals["rotulo_frente"](c.get("frente"), c.get("campanha")),
            "status": c.get("status"), "modo": c.get("modo", "ia"), "aberta": bool(c.get("aberta")),
            "ultima_texto": u.get("texto") or "", "ultima_direcao": u.get("direcao"), "ultima_em": _json_dt(u.get("em") or c.get("ultima_msg_lead_em") or c.get("criado_em")),
            "nao_lida": _nao_lida(c), "revisar": bool(c.get("revisar")), "teste": bool(c.get("teste"))}


def _numeros_teste() -> set:
    cfg = db.collection("config").document("atendimento").get().to_dict() or {}
    return {str(n) for n in (cfg.get("numeros_teste") or [])}


def _e_teste(c: dict, numeros: set) -> bool:
    return bool(c.get("teste")) or (c.get("contato") in numeros)


def _nao_lida(c: dict) -> bool:
    """Pendente = última mensagem é do lead e ninguém marcou como lida depois dela."""
    u = c.get("ultima") or {}
    if u.get("direcao") != "lead":
        return False
    lida, em = _dt(c.get("lida_em")), _dt(u.get("em"))
    return not (lida and em and lida >= em)


@app.get("/atendimentos", response_class=HTMLResponse)
def atendimentos(request: Request, c: str = "", _=Depends(autenticar)):
    statuses = sorted({x.get("status") for x in (d.to_dict() for d in db.collection("conversas").select(["status"]).stream()) if x.get("status")})
    campanhas_lista = sorted({x.get("campanha") for x in (d.to_dict() for d in db.collection("conversas").select(["campanha"]).stream()) if x.get("campanha")})
    return tpl.TemplateResponse(request, "atendimentos.html", {"inicial": c, "statuses": statuses, "campanhas_lista": campanhas_lista})


@app.get("/api/conversas")
def api_conversas(frente: str = "", status: str = "", busca: str = "", abertas: str = "", _=Depends(autenticar)):
    docs = [dict(c.to_dict(), id=c.id) for c in db.collection("conversas").stream()]
    numeros = _numeros_teste()
    for c in docs:
        c["teste"] = _e_teste(c, numeros)
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
    def chave(c):
        u = c.get("ultima") or {}
        return _dt(u.get("em")) or _dt(c.get("ultima_msg_lead_em")) or _dt(c.get("criado_em")) or datetime.min.replace(tzinfo=timezone.utc)
    docs.sort(key=chave, reverse=True)
    return JSONResponse({"total": len(docs), "itens": [_resumo_conversa(c) for c in docs[:400]]})


@app.get("/api/conversas/{cid}")
def api_conversa(cid: str, _=Depends(autenticar)):
    ref = db.collection("conversas").document(cid)
    c = ref.get().to_dict()
    if not c:
        raise HTTPException(404)
    c["id"] = cid
    msgs = []
    for m in ref.collection("mensagens").order_by("recebido_em").stream():
        x = m.to_dict()
        if x.get("direcao") == "lead" and x.get("tipo") in ("audio", "voice"):
            texto = "🎤 " + (x.get("transcricao") or "(áudio sem transcrição)")
        elif x.get("direcao") == "lead" and x.get("tipo") == "image":
            texto = "🖼️ imagem " + (x.get("texto") or "")
        elif x.get("botao"):
            texto = "🔘 " + str(x.get("botao"))
        else:
            texto = x.get("texto") or f"[{x.get('tipo')}]"
        msgs.append({"id": m.id, "direcao": x.get("direcao"), "texto": texto, "em": _json_dt(x.get("recebido_em")),
                     "modelo": (f"lembrete {x['lembrete']} · " if x.get("lembrete") else "") + (x.get("modelo") or ""), "autor": x.get("autor")})
    chamadas = [x.to_dict() for x in db.collection("chamadas_ia").where("conversa_id", "==", cid).stream()]
    lead = db.collection("leads").document(c.get("contato", "")).get().to_dict() or {}
    ficha = {"contato": c.get("contato"), "nome": c.get("nome"), "frente": c.get("frente"), "campanha": c.get("campanha"),
             "rotulo": tpl.env.globals["rotulo_frente"](c.get("frente"), c.get("campanha")), "status": c.get("status"), "modo": c.get("modo", "ia"),
             "aberta": bool(c.get("aberta")), "origem": c.get("origem") or lead.get("origem"), "template_origem": c.get("template_origem"), "ciclo": c.get("ciclo"),
             "lead_created_at": _json_dt(lead.get("lead_created_at")), "status_clinica": lead.get("status_clinica"),
             "id_paciente_tisaude": c.get("id_paciente_tisaude"), "id_agendamento_tisaude": c.get("id_agendamento_tisaude"), "agendamento": c.get("agendamento"),
             "motivo_encaminhamento": c.get("motivo_encaminhamento"), "proximo_recontato_em": c.get("proximo_recontato_em"),
             "videos_enviados": c.get("videos_enviados") or [], "orientacoes_enviadas": c.get("orientacoes_enviadas") or 0,
             "orientado_recepcao_em": _json_dt(c.get("orientado_recepcao_em")), "janela_24h_ate": _json_dt(c.get("janela_24h_ate")),
             "custo": round(sum(x.get("custo_usd", 0) for x in chamadas), 4), "respostas_ia": len(chamadas), "revisar": bool(c.get("revisar")),
             "teste": _e_teste(c, _numeros_teste()), "tisaude_real": c.get("tisaude_simulado") is False, "simulacoes": c.get("simulacoes_tisaude") or []}
    return JSONResponse({"ficha": ficha, "mensagens": msgs})


def _acao_orq(caminho: str, corpo: dict):
    if not URL_ORQUESTRADOR:
        return JSONResponse({"ok": False, "erro": "URL do orquestrador não configurada"}, status_code=500)
    try:
        r = _oidc_post(URL_ORQUESTRADOR, caminho, corpo, timeout=90)
        if r.ok:
            return JSONResponse({"ok": True, **(r.json() if r.headers.get("content-type", "").startswith("application/json") else {})})
        det = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
        return JSONResponse({"ok": False, "erro": det}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "erro": str(e)[:200]}, status_code=500)


@app.post("/api/conversas/{cid}/orientar")
def api_orientar(cid: str, _=Depends(autenticar)):
    return _acao_orq("/orientar", {"conversa_id": cid})


@app.post("/api/conversas/{cid}/lida")
def api_lida(cid: str, _=Depends(autenticar)):
    """Tira a marcação de pendente sem responder (marca como lida até a próxima mensagem do lead)."""
    db.collection("conversas").document(cid).set({"lida_em": datetime.now(timezone.utc) + timedelta(seconds=1)}, merge=True)
    return JSONResponse({"ok": True})


@app.post("/api/conversas/{cid}/reiniciar")
def api_reiniciar(cid: str, _=Depends(autenticar)):
    """Encerra a conversa (de teste) para que a próxima mensagem do número abra uma conversa nova, sem memória da anterior."""
    db.collection("conversas").document(cid).set({"aberta": False, "status": "Encerrada (reiniciada)", "encerrada_em": datetime.now(timezone.utc)}, merge=True)
    return JSONResponse({"ok": True})


@app.post("/api/conversas/{cid}/aviso")
def api_aviso(cid: str, _=Depends(autenticar)):
    return _acao_orq("/aviso", {"conversa_id": cid})


@app.post("/api/conversas/{cid}/modo")
def api_modo(cid: str, modo: str = Form(...), _=Depends(autenticar)):
    return _acao_orq("/modo", {"conversa_id": cid, "modo": modo})


@app.post("/api/conversas/{cid}/enviar")
def api_enviar(cid: str, texto: str = Form(...), _=Depends(autenticar)):
    return _acao_orq("/enviar", {"conversa_id": cid, "texto": texto, "autor": "equipe"})


@app.get("/conversas")
def conversas_redirect(frente: str = "", _=Depends(autenticar)):
    return RedirectResponse(f"/atendimentos?frente={frente}", status_code=302)


@app.get("/conversas-tabela", response_class=HTMLResponse)
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


@app.get("/conversas/{cid}")
def conversa_redirect(cid: str, _=Depends(autenticar)):
    return RedirectResponse(f"/atendimentos?c={cid}", status_code=302)


@app.get("/conversas-tabela/{cid}", response_class=HTMLResponse)
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
def listas(request: Request, frente: str = "leads_perdidos", status: str = "", pagina: int = 1, base: str = "elegiveis", _=Depends(autenticar)):
    pagina = max(1, pagina)
    if frente not in FRENTES:
        frente = "leads_perdidos"
    if True:
        q = db.collection("leads").where("frente", "==", frente)
        if base == "elegiveis":
            q = q.where("elegivel", "==", True)
        if status:
            q = q.where("status_ia", "==", status)
        total = q.count().get()[0][0].value
        itens = [d.to_dict() for d in q.order_by("lead_created_at", direction=firestore.Query.DESCENDING).offset((pagina - 1) * POR_PAGINA).limit(POR_PAGINA).stream()]
        statuses = config.parametros()["leads_perdidos"]["status_ia"]
    paginas = max(1, -(-total // POR_PAGINA))
    por_status = Counter()
    for d in db.collection("leads").where("frente", "==", frente).where("elegivel", "==", True).select(["status_ia"]).stream():
        por_status[d.to_dict().get("status_ia") or "Não contatado"] += 1
    return tpl.TemplateResponse(request, "listas.html", {"itens": itens, "total": total, "pagina": pagina, "paginas": paginas, "frente": frente,
                                                         "status": status, "statuses": statuses, "base": base,
                                                         "por_status": dict(por_status.most_common()), "por_pagina": POR_PAGINA})


# ================================================================= 3b. FUNIL (25/10/2026)
ETAPAS_FUNIL = [("Não contatado", "Não contatado", "na base, ainda sem template"),
                ("Template enviado (1°)", "1º template enviado", "T1 saiu, sem resposta ainda"),
                ("Template enviado (2°)", "2º/3º template enviado", "T2 ou T3 saíram, sem resposta"),
                ("Em conversa", "Em conversa", "respondeu e a Celeste está atendendo"),
                ("Agendado", "Agendado", "consulta marcada no TI Saúde")]
GRUPOS_FUNIL = [("Retornos combinados", ["Vamos retornar na data solicitada", "Irá nos retornar", "Agora não"]),
                ("Objeções", ["Achou caro", "Quer pelo convênio"]),
                ("Fora do perfil", ["Mora em outro Estado", "Mora em outro País", "Está em outra clínica", "Receiteiro"]),
                ("Equipe", ["Transferido para humano", "Encaminhado à recepção", "Orientado à recepção"])]


@app.get("/funil", response_class=HTMLResponse)
def funil(request: Request, _=Depends(autenticar)):
    """Funil visual da base elegível: etapas, situações laterais, passo da esteira e próximos retornos combinados."""
    p = config.parametros()
    d = dict(p["disparos"]); d.update(db.collection("config").document("disparos").get().to_dict() or {})
    recontato = p["leads_perdidos"]["recontato_por_status_ia"]
    tpl_status = d.get("template_por_status") or {}
    passos_cfg = d["passos"]
    agora = datetime.now(FUSO); hoje = agora.date()
    campos = ["nome", "celular", "status_ia", "passo", "ciclos", "ultimo_template_em", "ultima_msg_lead_em", "proximo_recontato_em",
              "conversa_id", "opt_out", "teste"]
    todos = [l.to_dict() for l in db.collection("leads").where("elegivel", "==", True).select(campos).stream()]
    leads = [l for l in todos if not l.get("teste")]   # contagens só com leads reais; os de teste aparecem apenas nos retornos, marcados
    total = len(leads)
    por_status = Counter(("Não quer (opt-out)" if l.get("opt_out") else (l.get("status_ia") or "Não contatado")) for l in leads)
    pct = lambda n: f"{(100 * n / total):.0f}%" if total else "0%"
    maior = max([por_status.get(k, 0) for k, _, _ in ETAPAS_FUNIL] + [1])
    etapas = [{"chave": k, "rotulo": r, "sub": s, "n": por_status.get(k, 0), "largura": round(100 * por_status.get(k, 0) / maior, 1)} for k, r, s in ETAPAS_FUNIL]
    usados = {k for k, _, _ in ETAPAS_FUNIL}
    grupos = []
    for titulo, chaves in GRUPOS_FUNIL:
        itens = [(c, por_status.get(c, 0)) for c in chaves if por_status.get(c, 0)]
        usados.update(chaves)
        grupos.append({"titulo": titulo, "itens": itens, "total": sum(n for _, n in itens)})
    outros = [(k, n) for k, n in por_status.most_common() if k not in usados]
    grupos.append({"titulo": "Outros", "itens": outros, "total": sum(n for _, n in outros)})
    contatados = sum(1 for l in leads if int(l.get("passo") or 0) > 0 or (l.get("status_ia") or "Não contatado") != "Não contatado")
    conversaram = sum(1 for l in leads if l.get("ultima_msg_lead_em"))
    agendados = por_status.get("Agendado", 0)

    por_passo = Counter(int(l.get("passo") or 0) for l in leads if (l.get("status_ia") or "Não contatado") in ("Não contatado", "Template enviado (1°)", "Template enviado (2°)"))
    passos = []
    for i in range(len(passos_cfg) + 1):
        if i == 0:
            desc, prox = "nenhum template ainda", f"{passos_cfg[0]['template']} na próxima rodada, dentro do limite diário"
        elif i < len(passos_cfg):
            desc = f"recebeu até o {passos_cfg[i - 1]['template']}"
            prox = f"{passos_cfg[i]['template']} {passos_cfg[i]['apos_dias']} dia(s) depois do último template, se não responder"
        else:
            desc, prox = f"recebeu o {passos_cfg[-1]['template']} (fim da esteira)", f"pausa de {d['pausa_apos_ultimo_passo_dias']} dias e recomeça uma vez"
        passos.append({"passo": i, "desc": desc, "n": por_passo.get(i, 0), "proximo": prox})

    retornos = []
    for l in todos:
        st = l.get("status_ia") or ""
        if st not in tpl_status or l.get("opt_out"):
            continue
        dias = recontato.get(st)
        hora = ""
        if dias == "na data":
            q = l.get("proximo_recontato_em")
            if not q:
                continue
            qdt = q if isinstance(q, datetime) else datetime.fromisoformat(str(q)[:16] if "T" in str(q) else str(q)[:10]).replace(tzinfo=FUSO)
            quando = qdt.astimezone(FUSO).date(); hora = qdt.astimezone(FUSO).strftime(" %H:%M") if "T" in str(q) or isinstance(q, datetime) else ""
        elif isinstance(dias, (int, float)):
            base = l.get("ultima_msg_lead_em") or l.get("ultimo_template_em")
            if not base:
                continue
            quando = (base.astimezone(FUSO) + timedelta(days=int(dias))).date()
        else:
            continue
        retornos.append({"nome": l.get("nome") or "(sem nome)", "celular": l.get("celular"), "status": st, "conversa_id": l.get("conversa_id"), "teste": bool(l.get("teste")),
                         "quando": quando.strftime("%d/%m/%Y") + hora, "ordem": quando, "atrasado": quando < hoje, "hoje": quando == hoje,
                         "template": f"{tpl_status[st]} · {templates_texto_nome(tpl_status[st])}"})
    retornos.sort(key=lambda r: r["ordem"])
    hoje_doc = db.collection("disparos_diarios").document(hoje.isoformat()).get().to_dict() or {}
    return tpl.TemplateResponse(request, "funil.html", {"total": total, "contatados": contatados, "conversaram": conversaram, "agendados": agendados,
                                                        "etapas": etapas, "grupos": grupos, "passos": passos, "retornos": retornos, "pct": pct,
                                                        "hoje_enviados": int(hoje_doc.get("enviados") or 0), "limite_diario": d.get("limite_diario"),
                                                        "disparos_ativo": bool(d.get("ativo"))})


def templates_texto_nome(codigo: str) -> str:
    from celeste.jobs import templates_texto
    return (templates_texto.TEMPLATES.get(codigo) or {}).get("nome", "")


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
    return RedirectResponse(f"/listas?frente=campanha:Inativos · outubro/2026&aviso={aviso}", status_code=303)


# ================================================================= 5. TEMPLATES
@app.get("/templates", response_class=HTMLResponse)
def templates(request: Request, _=Depends(autenticar)):
    """Só os templates da Celeste, em três grupos: esteira de resgate (T1–T4), rotinas de consulta (6) e aviso à recepção.
    Status, categoria, texto e botões vêm da Meta; o 'quando' vem dos parâmetros. Os das ações da clínica não aparecem."""
    from celeste.jobs import templates_texto
    p = config.parametros()
    grupos = [("Esteira de resgate · Leads Perdidos", [(cod, nome, (p["disparos"].get("quando") or {}).get(cod, "")) for cod, nome in p["disparos"]["templates"].items()]),
              ("Em teste · alternativas com vídeo (entram na esteira após aprovação)", [(cod, a["nome"], a.get("quando", "")) for cod, a in (p["disparos"].get("templates_alternativos") or {}).items()]),
              ("Consulta marcada · só consultas agendadas pela Celeste", [(cod, c["nome"], c.get("quando", "")) for cod, c in (p.get("templates_consulta") or {}).items()]),
              ("Recepção", [("Aviso", p["ia"]["recepcao"].get("template_aviso"), "Aviso à recepção quando a Celeste encaminha um lead.")])]
    na_meta, erro = {}, ""
    try:
        from celeste.ferramentas import meta
        for t in meta.Meta().templates():
            na_meta[t.get("name")] = t
    except Exception as e:
        erro = str(e)[:200]
    exemplo = {"{{1}}": "Ana", "{{2}}": "junho", "{{3}}": "11h"}
    saida = []
    for titulo, lista in grupos:
        itens = []
        for cod, nome, quando in lista:
            t = na_meta.get(nome)
            if t:
                comps = {c.get("type"): c for c in t.get("components", [])}
                corpo = (comps.get("BODY") or {}).get("text") or ""
                item = {"codigo": cod, "nome": nome, "quando": quando, "status": t.get("status"), "categoria": t.get("category"), "idioma": t.get("language"),
                        "corpo": corpo, "rodape": (comps.get("FOOTER") or {}).get("text"), "cabecalho": (comps.get("HEADER") or {}).get("text"),
                        "botoes": [b.get("text") for b in (comps.get("BUTTONS") or {}).get("buttons", [])], "meta_id": t.get("id")}
            else:
                prev = templates_texto.TEMPLATES.get(cod)
                corpo = prev["corpo"].replace("{1}", "{{1}}").replace("{2}", "{{2}}").replace("{3}", "{{3}}") if prev else "(não encontrado na Meta)"
                item = {"codigo": cod, "nome": nome, "quando": quando, "status": "NÃO ENCONTRADO NA META", "categoria": "—", "idioma": "pt_BR", "corpo": corpo,
                        "rodape": templates_texto.RODAPE if prev else None, "cabecalho": None, "botoes": prev["botoes"] if prev else [], "meta_id": None}
            previa = item["corpo"]
            for k, v in exemplo.items():
                previa = previa.replace(k, v)
            item["previa"] = previa
            itens.append(item)
        saida.append({"titulo": titulo, "itens": itens})
    return tpl.TemplateResponse(request, "templates.html", {"grupos": saida, "erro": erro})
