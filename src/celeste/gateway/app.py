# -*- coding: utf-8 -*-
"""Gateway — a porta de entrada: recebe o webhook da Meta, valida, grava e enfileira com debounce.

Não pensa: só prepara. A resposta é responsabilidade do Orquestrador.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request, Response
from google.cloud import firestore, tasks_v2
from google.protobuf import timestamp_pb2

from celeste.comum import config
from celeste.ferramentas import meta

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gateway")
app = FastAPI(title="Celeste · Gateway")

db = firestore.Client(project=config.PROJETO_GCP)
FILA = os.environ.get("FILA_TASKS", "celeste-debounce")
URL_ORQUESTRADOR = os.environ.get("URL_ORQUESTRADOR", "")
SA_TASKS = os.environ.get("SA_TASKS", f"celeste-gateway@{config.PROJETO_GCP}.iam.gserviceaccount.com")


@app.get("/status")  # /healthz é interceptado pelo front-end do Google no Cloud Run
def healthz():
    return {"ok": True, "servico": "gateway"}


@app.get("/webhook")
def verificar(request: Request):
    """Verificação do webhook pela Meta (hub.challenge)."""
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == config.segredo("META_VERIFY_TOKEN"):
        return Response(content=q.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(403, "verify token inválido")


@app.post("/webhook")
async def receber(request: Request):
    corpo = await request.body()
    if not meta.assinatura_valida(corpo, request.headers.get("X-Hub-Signature-256", "")):
        raise HTTPException(403, "assinatura inválida")
    payload = json.loads(corpo)
    for ev in meta.normalizar_webhook(payload):
        try:
            _processar(ev)
        except Exception:  # nunca devolver erro à Meta por um evento; ela reenviaria tudo
            log.exception("falha ao processar evento %s", ev.get("wamid"))
    return {"ok": True}


def _processar(ev: dict) -> None:
    if ev["kind"] == "status":
        _gravar_status(ev)
        return
    if _antiga(ev["timestamp"]):
        log.info("mensagem %s descartada: anterior ao corte", ev.get("wamid"))
        return
    telefone = ev["de"]
    conv_ref = _conversa_aberta(telefone, ev.get("nome"))
    msg_ref = conv_ref.collection("mensagens").document(ev["wamid"])
    if msg_ref.get().exists:  # idempotência: a Meta reenvia webhooks
        return
    msg_ref.set({
        "direcao": "lead", "tipo": ev["tipo"], "texto": ev.get("texto"), "botao": ev.get("botao"),
        "media_id": ev.get("media_id"), "mime": ev.get("mime"), "contexto_wamid": ev.get("contexto"),
        "recebido_em": datetime.fromtimestamp(ev["timestamp"], tz=timezone.utc), "gravado_em": firestore.SERVER_TIMESTAMP,
        "transcricao": None, "midia_gcs": None,
    })
    if not (conv_ref.get().to_dict() or {}).get("primeira_msg_lead_em"):
        conv_ref.set({"primeira_msg_lead_em": firestore.SERVER_TIMESTAMP}, merge=True)
    previa = ev.get("texto") or ev.get("botao") or {"audio": "🎤 áudio", "voice": "🎤 áudio", "image": "🖼️ imagem", "document": "📎 documento",
                                                      "video": "🎬 vídeo", "sticker": "sticker"}.get(ev["tipo"], f"[{ev['tipo']}]")
    conv_ref.set({"ultima": {"texto": str(previa)[:160], "direcao": "lead", "tipo": ev["tipo"],
                             "em": datetime.fromtimestamp(ev["timestamp"], tz=timezone.utc)},
                  "ultima_msg_lead_em": firestore.SERVER_TIMESTAMP,
                  "janela_24h_ate": datetime.now(timezone.utc) + timedelta(hours=24),
                  "pendente_resposta": True}, merge=True)
    _agendar_debounce(conv_ref.id, ev["tipo"])


def _antiga(timestamp: int) -> bool:
    """Mensagens represadas pela Meta com data anterior ao corte configurado não entram no painel."""
    corte = config.parametros()["ia"].get("ignorar_mensagens_antes_de")
    if not corte:
        return False
    limite = datetime.combine(date.fromisoformat(str(corte)), datetime.min.time(), tzinfo=ZoneInfo(config.FUSO))
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc) < limite


def _conversa_aberta(telefone: str, nome: str | None):
    abertas = db.collection("conversas").where("contato", "==", telefone).where("aberta", "==", True).limit(1).stream()
    for c in abertas:
        return c.reference
    # frente: quem está na base de leads (coleção `leads`) é Leads Perdidos; quem não está fica SEM frente
    frente, campanha, teste = None, None, False
    cfg = db.collection("config").document("atendimento").get().to_dict() or {}
    if telefone in {str(n) for n in (cfg.get("numeros_teste") or [])}:
        frente, teste = "leads_perdidos", True            # número de teste da clínica: Celeste atende como lead novo, TI Saúde simulado
    elif db.collection("leads").document(telefone).get().exists:
        frente = "leads_perdidos"
    else:
        cc = db.collection("campanha_contatos").document(telefone).get()
        if cc.exists:  # recebeu disparo dos fluxos da clínica (Inativos/Retorno/Geral): a IA não atende
            frente, campanha = "campanha", cc.to_dict().get("campanha")
            nome = nome or cc.to_dict().get("nome")
    contato = db.collection("contatos").document(telefone)
    if not contato.get().exists:
        contato.set({"telefone": telefone, "nome": nome, "criado_em": firestore.SERVER_TIMESTAMP, "opt_out": False,
                     "origem": frente or "espontaneo"}, merge=True)
    ref = db.collection("conversas").document()
    ref.set({"contato": telefone, "nome": nome, "frente": frente, "campanha": campanha, "modo": "ia", "status": "Em conversa",
             "aberta": True, "criado_em": firestore.SERVER_TIMESTAMP, "origem": "espontaneo", "teste": teste})
    return ref


def _gravar_status(ev: dict) -> None:
    db.collection("status_entrega").document(ev["wamid"]).set({
        "para": ev.get("para"), "status": ev.get("status"), "erros": ev.get("erros"), "categoria": ev.get("categoria"),
        "cobravel": ev.get("cobravel"), "em": datetime.fromtimestamp(ev["timestamp"], tz=timezone.utc)}, merge=True)


def _agendar_debounce(conversa_id: str, tipo: str) -> None:
    """Enfileira 'responder conversa X' com atraso; o orquestrador ignora tarefas obsoletas."""
    if not URL_ORQUESTRADOR:
        log.warning("URL_ORQUESTRADOR não definida; debounce não agendado")
        return
    cfg = config.parametros()["ia"]["agrupamento_mensagens"]
    espera = cfg["espera_apos_audio_segundos"] if tipo in ("audio", "voice") else cfg["espera_padrao_segundos"]
    cliente = tasks_v2.CloudTasksClient()
    fila = cliente.queue_path(config.PROJETO_GCP, config.REGIAO, FILA)
    quando = timestamp_pb2.Timestamp(); quando.FromDatetime(datetime.now(timezone.utc) + timedelta(seconds=espera))
    versao = datetime.now(timezone.utc).isoformat()
    db.collection("conversas").document(conversa_id).set({"debounce_versao": versao}, merge=True)
    cliente.create_task(parent=fila, task=tasks_v2.Task(
        schedule_time=quando,
        http_request=tasks_v2.HttpRequest(
            http_method=tasks_v2.HttpMethod.POST, url=f"{URL_ORQUESTRADOR}/responder",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"conversa_id": conversa_id, "versao": versao}).encode(),
            oidc_token=tasks_v2.OidcToken(service_account_email=SA_TASKS))))
