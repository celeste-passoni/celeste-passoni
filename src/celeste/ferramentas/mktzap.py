# -*- coding: utf-8 -*-
"""Cliente da API pública do MarketZap (https://apidoc.mktzap.com.br, v1.6.1).

25/11/2026: a Celeste fala com os Leads Perdidos pelo número oficial da clínica, dentro do setor exclusivo dela no MarketZap.
Aqui só a conversa com a API; as regras (qual setor, quando passar para a equipe) ficam em `canal.py`.
Nunca registre o token nem a clientKey em log.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import requests

from celeste.comum import config

log = logging.getLogger(__name__)

_TOKEN_VALIDADE_S = 50 * 60      # o token vale 1 h; renova 10 min antes
_cache_token: dict[str, Any] = {"valor": None, "ate": 0.0}
_trava = threading.Lock()


class MktZapErro(RuntimeError):
    pass


def iso(dt: datetime) -> str:
    """Data no formato que a API aceita nos filtros (ISO 8601, UTC, com milissegundos)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def separar_ddi(telefone: str) -> tuple[str, str]:
    """'5511999990000' → ('55', '11999990000'). O send-hsm v1.2.2 pede DDI e número separados."""
    t = "".join(c for c in str(telefone) if c.isdigit())
    if t.startswith("55") and len(t) >= 12:
        return "55", t[2:]
    return "", t


def telefone_do_atendimento(h: dict) -> Optional[str]:
    """O contact_id é interno (waent_934_<uuid>); o telefone vem em external_ids (key=phone)."""
    for e in h.get("external_ids") or []:
        if e.get("key") == "phone" and e.get("value"):
            return str(e["value"])
    return None


class MktZap:
    def __init__(self, session: Optional[requests.Session] = None, dormir: Callable[[float], None] = time.sleep):
        self.http = session or requests.Session()
        self.dormir = dormir
        self.base = config.parametros()["mktzap"]["api"].rstrip("/")
        self.empresa = str(config.segredo("MKTZAP_COMPANY_ID")).strip()

    # ----------------------------------------------------------- autenticação
    def _token(self, renovar: bool = False) -> str:
        with _trava:
            if not renovar and _cache_token["valor"] and time.time() < _cache_token["ate"]:
                return _cache_token["valor"]
            r = self.http.get(f"{self.base}/company/{self.empresa}/token",
                              params={"clientKey": str(config.segredo("MKTZAP_CLIENT_KEY")).strip()}, timeout=30)
            if r.status_code != 200 or not (r.json() if r.content else {}).get("accessToken"):
                raise MktZapErro(f"token: HTTP {r.status_code}")
            _cache_token.update(valor=r.json()["accessToken"], ate=time.time() + _TOKEN_VALIDADE_S)
            return _cache_token["valor"]

    def _req(self, metodo: str, caminho: str, tentativas: int = 4, **kw) -> Any:
        """Chamada com Bearer; renova o token uma vez em 401 e espera em 429 (limite de requisições não documentado)."""
        renovou = False
        extras = kw.pop("headers", None) or {}
        for i in range(tentativas):
            h = {"Authorization": f"Bearer {self._token()}", **extras}
            r = self.http.request(metodo, f"{self.base}{caminho}", headers=h, timeout=60, **kw)
            if r.status_code == 401 and not renovou:
                self._token(renovar=True); renovou = True
                continue
            if r.status_code == 429 and i < tentativas - 1:
                espera = float(r.headers.get("Retry-After") or 2 ** i)
                log.warning("MarketZap 429 em %s; aguardando %.0f s", caminho, espera)
                self.dormir(espera)
                continue
            dados = r.json() if r.content else {}
            if r.status_code >= 300:
                raise MktZapErro(f"{metodo} {caminho}: HTTP {r.status_code} {str(dados)[:200]}")
            return dados
        raise MktZapErro(f"{metodo} {caminho}: limite de requisições (429) persistente")

    @staticmethod
    def _lista(dados: Any) -> list[dict]:
        if isinstance(dados, list):
            return dados
        if isinstance(dados, dict) and isinstance(dados.get("data"), list):
            return dados["data"]
        return []

    # ----------------------------------------------------------- leitura
    def setores(self) -> list[dict]:
        return self._lista(self._req("GET", f"/company/{self.empresa}/sector"))

    def templates_hsm(self) -> list[dict]:
        """Templates HSM do MarketZap (espelho da WABA do número oficial), sem os excluídos."""
        return [t for t in self._lista(self._req("POST", f"/company/{self.empresa}/history/post-hsm-template")) if not t.get("deleted_at")]

    def atendimentos(self, contact_id: Optional[str] = None, atualizados_desde: Optional[datetime] = None,
                     protocolo: Optional[str] = None, paginas: int = 5) -> list[dict]:
        params: dict[str, Any] = {}
        if contact_id:
            params["contact_id"] = contact_id
        if atualizados_desde:
            params["updatedFrom"] = iso(atualizados_desde)
        if protocolo:
            params["protocol"] = protocolo
        saida: list[dict] = []
        for pagina in range(1, paginas + 1):
            lote = self._lista(self._req("GET", f"/company/{self.empresa}/historycontact", params=params, headers={"x-page": str(pagina)}))
            saida.extend(lote)
            if not lote or contact_id or protocolo:
                break
        return saida

    def mensagens(self, history_id: int, desde: Optional[datetime] = None) -> list[dict]:
        params: dict[str, Any] = {"showMessageStatus": "true"}
        if desde:
            params["createdFrom"] = iso(desde)
        return self._lista(self._req("GET", f"/company/{self.empresa}/history/{history_id}/message", params=params))

    # ----------------------------------------------------------- envio (dentro da janela de 24 h)
    def enviar_texto(self, history_id: int, texto: str) -> dict:
        return self._req("POST", f"/company/{self.empresa}/history/{history_id}/send-message-waent", json={"type": "text", "message": texto})

    def enviar_midia(self, history_id: int, tipo: str, url: str, legenda: str = "", nome: Optional[str] = None) -> dict:
        """tipo = 'image' | 'document' (a API não envia vídeo nem áudio)."""
        media: dict[str, Any] = {"type": tipo, "url": url}
        if legenda:
            media["caption"] = legenda
        if nome and tipo == "document":
            media["name"] = nome
        return self._req("POST", f"/company/{self.empresa}/history/{history_id}/send-message-waent", json={"type": "media", "media": media})

    # ----------------------------------------------------------- template (abre ou reaproveita o atendimento)
    def enviar_hsm(self, telefone: str, hsm_id: int, parametros: list[str], nome: Optional[str] = None,
                   setor_id: Optional[int] = None, automatico: bool = True) -> dict:
        ddi, numero = separar_ddi(telefone)
        corpo: dict[str, Any] = {
            "type": "whatsapp-enterprise", "broker_phone": config.parametros()["mktzap"]["broker_phone"],
            "phone_ddi": ddi or "55", "phone_number": numero, "only_active": False,
            "contact_already_exists": True,   # lead com atendimento aberto: o template entra nele, sem duplicar
            "is_auto": bool(automatico),
            "messages": {"type": "hsm", "content": {"hsm_id": hsm_id, "params": list(parametros)}},
        }
        if nome:
            corpo["name"] = nome
        if setor_id:
            corpo["sector_id"] = int(setor_id)   # aceito na v0.10.1; se a v1.2.2 ignorar, o canal move o atendimento depois
        return self._req("POST", f"/company/{self.empresa}/history/send-hsm", json=corpo)

    # ----------------------------------------------------------- gestão do atendimento
    def mudar_setor(self, protocolo: str, setor_id: int) -> dict:
        return self._req("PUT", f"/company/{self.empresa}/history/sector-change", json={"protocol": str(protocolo), "sector_id": int(setor_id)})

    def tirar_do_automatico(self, protocolo: str) -> dict:
        """Sem operador: o atendimento segue a distribuição da empresa no setor em que estiver."""
        return self._req("POST", f"/company/{self.empresa}/history/transfer-no-operator", json={"protocol": str(protocolo)})


def atendimento_aberto(lista: list[dict], canal_id: int, telefones: Optional[set[str]] = None) -> Optional[dict]:
    """O atendimento aberto mais recente deste canal (e destes telefones, quando informados)."""
    candidatos = []
    for h in lista:
        if h.get("closed_at") or int(h.get("channelable_id") or 0) != int(canal_id):
            continue
        if telefones is not None and telefone_do_atendimento(h) not in telefones:
            continue
        candidatos.append(h)
    candidatos.sort(key=lambda h: str(h.get("updated_at") or h.get("created_at") or ""), reverse=True)
    return candidatos[0] if candidatos else None


def desde_minutos(minutos: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutos)
