# -*- coding: utf-8 -*-
"""Cliente da Meta WhatsApp Cloud API: envio (texto, template, vídeo), mídia e validação do webhook."""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Optional

import requests

from celeste.comum import config

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v23.0"
PHONE_ID = "1219345307926640"
WABA_ID = "2053539948590151"


class MetaErro(RuntimeError):
    pass


def assinatura_valida(corpo: bytes, cabecalho: str) -> bool:
    """Confere X-Hub-Signature-256 (HMAC-SHA256 do corpo com o app secret)."""
    if not cabecalho or not cabecalho.startswith("sha256="):
        return False
    esperado = hmac.new(config.segredo("META_APP_SECRET").encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecalho[7:])


class Meta:
    def __init__(self, session: Optional[requests.Session] = None):
        self.http = session or requests.Session()

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {config.segredo('META_TOKEN')}"}

    def _post(self, caminho: str, corpo: dict) -> dict:
        r = self.http.post(f"{GRAPH}/{caminho}", headers=self._h(), json=corpo, timeout=60)
        dados = r.json() if r.content else {}
        if r.status_code >= 300:
            raise MetaErro(f"POST {caminho}: HTTP {r.status_code} {dados.get('error')}")
        return dados

    # ----------------------------------------------------------- envio
    def enviar_texto(self, para: str, texto: str) -> str:
        d = self._post(f"{PHONE_ID}/messages", {"messaging_product": "whatsapp", "to": para, "type": "text",
                                                "text": {"preview_url": False, "body": texto}})
        return d["messages"][0]["id"]

    def enviar_template(self, para: str, nome: str, parametros_corpo: list[str], idioma: str = "pt_BR") -> str:
        comp = []
        if parametros_corpo:
            comp.append({"type": "body", "parameters": [{"type": "text", "text": p} for p in parametros_corpo]})
        d = self._post(f"{PHONE_ID}/messages", {"messaging_product": "whatsapp", "to": para, "type": "template",
                                                "template": {"name": nome, "language": {"code": idioma}, "components": comp}})
        return d["messages"][0]["id"]

    def enviar_video(self, para: str, media_id: str, legenda: str = "") -> str:
        v: dict[str, Any] = {"id": media_id}
        if legenda:
            v["caption"] = legenda
        d = self._post(f"{PHONE_ID}/messages", {"messaging_product": "whatsapp", "to": para, "type": "video", "video": v})
        return d["messages"][0]["id"]

    def enviar_botao_url(self, para: str, texto: str, rotulo: str, url: str) -> str:
        """Mensagem com botão que abre um link (interactive cta_url). Só dentro da janela de 24 h."""
        d = self._post(f"{PHONE_ID}/messages", {"messaging_product": "whatsapp", "to": para, "type": "interactive",
                                                "interactive": {"type": "cta_url", "body": {"text": texto},
                                                                "action": {"name": "cta_url", "parameters": {"display_text": rotulo[:20], "url": url}}}})
        return d["messages"][0]["id"]

    def enviar_botoes_resposta(self, para: str, texto: str, botoes: list[tuple[str, str]]) -> str:
        """Mensagem com até 3 botões de resposta rápida (interactive/button). botoes = [(id, título ≤ 20 chars)]. Só na janela de 24 h."""
        acao = {"buttons": [{"type": "reply", "reply": {"id": i[:256], "title": t[:20]}} for i, t in botoes[:3]]}
        d = self._post(f"{PHONE_ID}/messages", {"messaging_product": "whatsapp", "to": para, "type": "interactive",
                                                "interactive": {"type": "button", "body": {"text": texto}, "action": acao}})
        return d["messages"][0]["id"]

    def enviar_video_link(self, para: str, url: str, legenda: str = "") -> str:
        """Envia vídeo por URL pública (a Meta baixa e entrega)."""
        v = {"link": url}
        if legenda:
            v["caption"] = legenda
        d = self._post(f"{PHONE_ID}/messages", {"messaging_product": "whatsapp", "to": para, "type": "video", "video": v})
        return d["messages"][0]["id"]

    def marcar_lida(self, wamid: str) -> None:
        try:
            self._post(f"{PHONE_ID}/messages", {"messaging_product": "whatsapp", "status": "read", "message_id": wamid})
        except MetaErro as e:  # não é crítico
            log.warning("marcar_lida falhou: %s", e)

    # ----------------------------------------------------------- mídia
    def baixar_midia(self, media_id: str) -> tuple[bytes, str]:
        """Retorna (bytes, mime_type) de uma mídia recebida."""
        r = self.http.get(f"{GRAPH}/{media_id}", headers=self._h(), timeout=60)
        if r.status_code != 200:
            raise MetaErro(f"mídia {media_id}: HTTP {r.status_code}")
        info = r.json()
        conteudo = self.http.get(info["url"], headers=self._h(), timeout=120)
        return conteudo.content, info.get("mime_type", "application/octet-stream")

    def subir_midia(self, conteudo: bytes, mime: str, nome: str) -> str:
        r = self.http.post(f"{GRAPH}/{PHONE_ID}/media", headers=self._h(),
                           data={"messaging_product": "whatsapp"}, files={"file": (nome, conteudo, mime)}, timeout=300)
        if r.status_code >= 300:
            raise MetaErro(f"upload mídia: HTTP {r.status_code} {r.text[:200]}")
        return r.json()["id"]

    # ----------------------------------------------------------- conta
    def numero(self) -> dict:
        r = self.http.get(f"{GRAPH}/{PHONE_ID}", headers=self._h(),
                          params={"fields": "display_phone_number,quality_rating,messaging_limit_tier,status"}, timeout=60)
        return r.json()

    def templates(self) -> list[dict]:
        r = self.http.get(f"{GRAPH}/{WABA_ID}/message_templates", headers=self._h(),
                          params={"fields": "name,status,category,language,quality_score,components", "limit": 200}, timeout=60)
        return r.json().get("data", [])


def normalizar_webhook(payload: dict) -> list[dict]:
    """Achata o webhook da Meta em eventos simples: mensagens e status de entrega."""
    eventos = []
    for entrada in payload.get("entry", []):
        for mud in entrada.get("changes", []):
            v = mud.get("value", {})
            nomes = {c["wa_id"]: c.get("profile", {}).get("name") for c in v.get("contacts", [])}
            for m in v.get("messages", []):
                tipo = m.get("type")
                ev = {"kind": "mensagem", "wamid": m["id"], "de": m["from"], "nome": nomes.get(m["from"]),
                      "timestamp": int(m.get("timestamp", 0)), "tipo": tipo, "texto": None, "media_id": None, "mime": None,
                      "botao": None, "contexto": (m.get("context") or {}).get("id")}
                if tipo == "text":
                    ev["texto"] = m["text"]["body"]
                elif tipo in ("audio", "image", "video", "document"):
                    ev["media_id"] = m[tipo]["id"]; ev["mime"] = m[tipo].get("mime_type"); ev["texto"] = m[tipo].get("caption")
                elif tipo == "button":
                    ev["botao"] = m["button"].get("payload") or m["button"].get("text"); ev["texto"] = m["button"].get("text")
                elif tipo == "interactive":
                    i = m["interactive"]; br = i.get("button_reply") or i.get("list_reply") or {}
                    ev["botao"] = br.get("id"); ev["texto"] = br.get("title")
                eventos.append(ev)
            for s in v.get("statuses", []):
                eventos.append({"kind": "status", "wamid": s["id"], "para": s.get("recipient_id"), "status": s.get("status"),
                                "timestamp": int(s.get("timestamp", 0)), "erros": s.get("errors"),
                                "conversa": (s.get("conversation") or {}).get("origin", {}).get("type"),
                                "cobravel": (s.get("pricing") or {}).get("billable"), "categoria": (s.get("pricing") or {}).get("category")})
    return eventos
