# -*- coding: utf-8 -*-
"""Orquestrador — a Celeste em si.

Recebe do Cloud Tasks "responda a conversa X (versão V)", e:
  1. descarta tarefas obsoletas (chegou mensagem nova depois → outra tarefa virá);
  2. monta o histórico (texto, transcrição de áudio, imagens) a partir do Firestore;
  3. chama o Claude com as ferramentas (TI Saúde, vídeos, encaminhar, opt-out);
  4. respeita o ritmo humano e envia os balões pela Meta;
  5. registra tudo (mensagens, chamadas, custo) para o painel e o espelho no BigQuery.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from google.cloud import firestore, storage
from pydantic import BaseModel

from celeste.comum import config
from celeste.ferramentas import meta, tisaude, transcricao
from celeste.orquestrador import ferramentas_ia, motor

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("orquestrador")
app = FastAPI(title="Celeste · Orquestrador")

db = firestore.Client(project=config.PROJETO_GCP)
BUCKET = os.environ.get("BUCKET_MIDIA", f"celeste-midia-{config.PROJETO_GCP}")
SIMULAR_DELAY = os.environ.get("SIMULAR_DELAY", "1") == "1"   # desligar em testes locais
FUSO = ZoneInfo(config.FUSO)

_motor: motor.Motor | None = None
_meta: meta.Meta | None = None
_ts: tisaude.TiSaude | None = None


def _svc():
    global _motor, _meta, _ts
    _motor = _motor or motor.Motor()
    _meta = _meta or meta.Meta()
    _ts = _ts or tisaude.TiSaude()
    return _motor, _meta, _ts


class Pedido(BaseModel):
    conversa_id: str
    versao: str


@app.get("/status")  # /healthz é interceptado pelo front-end do Google no Cloud Run
def healthz():
    return {"ok": True, "servico": "orquestrador"}


@app.post("/responder")
def responder(p: Pedido):
    ref = db.collection("conversas").document(p.conversa_id)
    conv = ref.get().to_dict()
    if not conv:
        raise HTTPException(404, "conversa não existe")
    if conv.get("debounce_versao") != p.versao:
        return {"ok": True, "ignorado": "tarefa obsoleta"}
    if not conv.get("aberta", True) or conv.get("modo", "ia") != "ia" or conv.get("opt_out"):
        return {"ok": True, "ignorado": "conversa fechada/pausada"}
    if _custo_hoje() >= float(config.parametros()["modelos"]["cap_diario_usd"]):
        ref.set({"pausada_por_custo": True}, merge=True)
        log.error("cap diário de custo atingido; conversa %s pausada", p.conversa_id)
        return {"ok": False, "ignorado": "cap diário de custo"}
    conv["id"] = p.conversa_id
    inicio = time.time()
    mot, mt, ts = _svc()

    historico, ultimo_wamid = _historico(ref, mt)
    if not historico or historico[-1]["role"] != "user":
        return {"ok": True, "ignorado": "nada novo do lead"}
    if ultimo_wamid:
        try:
            mt.marcar_lida(ultimo_wamid)
        except Exception:
            pass

    ctx = ferramentas_ia.Contexto(
        conversa=conv, telefone=conv["contato"], tisaude=ts, viacep=transcricao.viacep,
        enviar_video=lambda v: _enviar_video(mt, ref, conv, v),
        avisar_recepcao=lambda motivo, resumo: _avisar_recepcao(mt, conv, motivo, resumo),
        atualizar=lambda campos: (conv.update(campos), ref.set(campos, merge=True)),
    )
    frente = conv.get("frente") or "leads_perdidos"
    if frente not in ("leads_perdidos",):
        frente = "leads_perdidos"  # única frente ativa no piloto
    res = mot.responder(frente, conv, historico, ctx)
    _registrar_chamada(p.conversa_id, res, time.time() - inicio)
    if res.refusal:
        ref.set({"revisar": True, "revisar_motivo": "modelo recusou responder"}, merge=True)
        return {"ok": True, "enviado": 0, "refusal": True}

    # ritmo humano: espera antes do 1º balão; se chegou msg nova nesse meio tempo, descarta e deixa a nova tarefa responder
    if SIMULAR_DELAY:
        time.sleep(motor.delay_humano(fora_horario=not _horario_comercial()))
    if ref.get().to_dict().get("debounce_versao") != p.versao:
        log.info("mensagem nova chegou durante a geração; resposta descartada (conversa %s)", p.conversa_id)
        return {"ok": True, "ignorado": "regerar"}

    enviados = 0
    for i, texto in enumerate(res.baloes):
        if i and SIMULAR_DELAY:
            time.sleep(min(12.0, 1.5 + len(texto) / 25))  # "digitando" proporcional ao tamanho
        wamid = mt.enviar_texto(conv["contato"], texto)
        ref.collection("mensagens").document(wamid).set({
            "direcao": "celeste", "tipo": "text", "texto": texto, "modelo": res.modelo,
            "recebido_em": datetime.now(timezone.utc), "gravado_em": firestore.SERVER_TIMESTAMP})
        enviados += 1
    if conv.get("status") == "Encaminhado à recepção" and ctx.encerrar:
        rec = config.parametros()["ia"]["recepcao"]
        try:
            wamid = mt.enviar_botao_url(conv["contato"], rec["botao_texto"], rec["botao_rotulo"], rec["link_wa"])
            ref.collection("mensagens").document(wamid).set({
                "direcao": "celeste", "tipo": "interactive", "texto": f"{rec['botao_texto']}
[botão: {rec['botao_rotulo']} → {rec['link_wa']}]",
                "recebido_em": datetime.now(timezone.utc), "gravado_em": firestore.SERVER_TIMESTAMP})
            enviados += 1
        except Exception as e:
            log.warning("botão da recepção não enviado: %s", e)
    ref.set({"pendente_resposta": False, "ultima_msg_celeste_em": firestore.SERVER_TIMESTAMP,
             "total_msgs_celeste": firestore.Increment(enviados), "custo_usd": firestore.Increment(res.custo_usd),
             "aberta": conv.get("aberta", True) and not ctx.encerrar}, merge=True)
    _espelhar_lead(conv)
    return {"ok": True, "enviado": enviados, "modelo": res.modelo, "custo_usd": round(res.custo_usd, 5)}


# ----------------------------------------------------------------- histórico
def _historico(ref, mt: meta.Meta) -> tuple[list[dict], str | None]:
    """Converte as mensagens do Firestore em turnos user/assistant, agrupando balões consecutivos."""
    turnos: list[dict] = []
    ultimo_wamid = None
    for doc in ref.collection("mensagens").order_by("recebido_em").stream():
        m = doc.to_dict()
        if m.get("direcao") == "lead":
            ultimo_wamid = doc.id
            blocos = _blocos_lead(doc, m, mt)
            if turnos and turnos[-1]["role"] == "user":
                turnos[-1]["content"].extend(blocos)
            else:
                turnos.append({"role": "user", "content": blocos})
        elif m.get("direcao") in ("celeste", "template"):
            texto = m.get("texto") or f"[template {m.get('template')}]"
            if turnos and turnos[-1]["role"] == "assistant":
                turnos[-1]["content"] += "\n---\n" + texto
            else:
                turnos.append({"role": "assistant", "content": texto})
    # a API exige que o 1º turno seja user; se a conversa começou com template, o modelo vê como assistant → prefixamos
    if turnos and turnos[0]["role"] == "assistant":
        turnos.insert(0, {"role": "user", "content": "[início da conversa — a Celeste enviou a primeira mensagem]"})
    # o motor injeta o contexto do lead no 1º turno se ele for string: compactamos blocos só-texto em string
    for t in turnos:
        if t["role"] == "user" and all(b.get("type") == "text" for b in t["content"]):
            t["content"] = "\n".join(b["text"] for b in t["content"])
    return turnos, ultimo_wamid


def _blocos_lead(doc, m: dict, mt: meta.Meta) -> list[dict]:
    tipo = m.get("tipo")
    if tipo == "text":
        return [{"type": "text", "text": m.get("texto") or ""}]
    if tipo in ("button", "interactive"):
        return [{"type": "text", "text": f"[clicou no botão: {m.get('botao') or m.get('texto')}]"}]
    if tipo in ("audio", "voice"):
        if m.get("transcricao") is None:
            transcr = ""
            try:
                conteudo, mime = mt.baixar_midia(m["media_id"])
                _guardar_midia(doc, conteudo, mime)
                transcr = transcricao.transcrever(conteudo, mime)
            except Exception as e:
                log.warning("áudio %s: %s", doc.id, e)
            doc.reference.set({"transcricao": transcr}, merge=True)
            m["transcricao"] = transcr
        return [{"type": "text", "text": f"[áudio do lead, transcrição: {m['transcricao']}]" if m["transcricao"]
                 else "[o lead mandou um áudio que não foi possível ouvir — peça com jeitinho para escrever]"}]
    if tipo == "image":
        try:
            conteudo, mime = mt.baixar_midia(m["media_id"])
            _guardar_midia(doc, conteudo, mime)
            legenda = f" Legenda: {m['texto']}" if m.get("texto") else ""
            return [{"type": "text", "text": f"[o lead enviou uma imagem.{legenda}]"},
                    {"type": "image", "source": {"type": "base64", "media_type": mime.split(";")[0] or "image/jpeg",
                                                 "data": base64.b64encode(conteudo).decode()}}]
        except Exception as e:
            log.warning("imagem %s: %s", doc.id, e)
            return [{"type": "text", "text": "[o lead enviou uma imagem que não pôde ser aberta]"}]
    return [{"type": "text", "text": f"[o lead enviou {tipo}{': ' + m['texto'] if m.get('texto') else ''}]"}]


def _guardar_midia(doc, conteudo: bytes, mime: str) -> None:
    if doc.to_dict().get("midia_gcs"):
        return
    try:
        ext = {"audio/ogg": "ogg", "image/jpeg": "jpg", "image/png": "png"}.get(mime.split(";")[0], "bin")
        caminho = f"{doc.reference.parent.parent.id}/{doc.id}.{ext}"
        storage.Client(project=config.PROJETO_GCP).bucket(BUCKET).blob(caminho).upload_from_string(conteudo, content_type=mime)
        doc.reference.set({"midia_gcs": f"gs://{BUCKET}/{caminho}"}, merge=True)
    except Exception as e:
        log.warning("não guardou mídia: %s", e)


# ----------------------------------------------------------------- ações laterais
def _enviar_video(mt: meta.Meta, ref, conv: dict, chave: str) -> str:
    v = config.parametros()["videos"][chave]
    wamid = mt.enviar_video_link(conv["contato"], v["url"])
    ref.collection("mensagens").document(wamid).set({
        "direcao": "celeste", "tipo": "video", "texto": f"[vídeo: {chave} — {v['descricao']}]", "video": chave,
        "recebido_em": datetime.now(timezone.utc), "gravado_em": firestore.SERVER_TIMESTAMP})
    return wamid


def _avisar_recepcao(mt: meta.Meta, conv: dict, motivo: str, resumo: str) -> None:
    rec = config.parametros()["ia"]["recepcao"]
    nome = conv.get("nome") or "lead sem nome"
    db.collection("encaminhamentos").document().set({
        "conversa_id": conv["id"], "contato": conv["contato"], "nome": nome, "frente": conv.get("frente"),
        "motivo": motivo, "resumo": resumo, "em": firestore.SERVER_TIMESTAMP, "atendido": False})
    try:
        mt.enviar_template(rec["whatsapp"], rec["template_aviso"],
                           [nome, f"https://wa.me/{conv['contato']}", motivo.replace("_", " "), resumo[:300], conv.get("frente") or ""])
    except Exception as e:  # template ainda não aprovado → fica só no painel; tenta texto livre (só funciona com janela aberta)
        log.warning("aviso à recepção por template falhou (%s); tentando texto", e)
        try:
            mt.enviar_texto(rec["whatsapp"], f"Lead encaminhado pela Celeste\nNome: {nome}\nWhatsApp: https://wa.me/{conv['contato']}\n"
                                             f"Motivo: {motivo.replace('_', ' ')}\nResumo: {resumo}")
        except Exception as e2:
            log.error("aviso à recepção não entregue: %s", e2)


def _espelhar_lead(conv: dict) -> None:
    """Mantém `leads/{celular}` (fila de disparos) coerente com a conversa: status, opt-out, datas de recontato."""
    campos = {"status_ia": conv.get("status"), "ultima_msg_lead_em": datetime.now(timezone.utc), "conversa_id": conv["id"]}
    if conv.get("opt_out"):
        campos["opt_out"] = True
    if "proximo_recontato_em" in conv:
        campos["proximo_recontato_em"] = conv["proximo_recontato_em"]
    if conv.get("status") == "Agendado":
        campos["elegivel"] = False
    ref = db.collection("leads").document(conv["contato"])
    if ref.get().exists:
        ref.set(campos, merge=True)


# ----------------------------------------------------------------- custo e métricas
def _registrar_chamada(conversa_id: str, res: motor.Resultado, segundos: float) -> None:
    hoje = datetime.now(FUSO).strftime("%Y-%m-%d")
    db.collection("chamadas_ia").document().set({
        "conversa_id": conversa_id, "modelo": res.modelo, "custo_usd": res.custo_usd, "tokens": res.tokens,
        "chamadas": res.chamadas, "ferramentas": res.ferramentas, "baloes": len(res.baloes), "refusal": res.refusal,
        "latencia_s": round(segundos, 2), "dia": hoje, "em": firestore.SERVER_TIMESTAMP})
    db.collection("custos_diarios").document(hoje).set(
        {"custo_usd": firestore.Increment(res.custo_usd), "chamadas": firestore.Increment(res.chamadas)}, merge=True)


def _custo_hoje() -> float:
    d = db.collection("custos_diarios").document(datetime.now(FUSO).strftime("%Y-%m-%d")).get().to_dict() or {}
    return float(d.get("custo_usd", 0))


def _horario_comercial() -> bool:
    agora = datetime.now(FUSO)
    return agora.weekday() < 5 and 9 <= agora.hour < 19
