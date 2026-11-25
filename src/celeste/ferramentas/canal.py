# -*- coding: utf-8 -*-
"""Canal de saída de uma conversa: Meta (número atual da Celeste) ou MarketZap (número oficial, setor da Celeste).

25/11/2026: `CanalMktZap` tem a mesma interface da classe `meta.Meta` (enviar_texto, enviar_template, baixar_midia…),
então o orquestrador e os jobs só escolhem o canal pela conversa (`conv["canal"]`) e seguem iguais.
Regras do MarketZap (decisões do usuário, 25/11/2026):
- todo template da Celeste leva o atendimento para o SETOR DELA (setor_celeste_id), mesmo que o lead já tenha atendimento aberto
  com uma pessoa da equipe: o atendimento é movido e fica sem operador (senão o MarketZap o devolve ao setor da atendente quando o
  lead responde; teste de 25/11/2026);
- a Celeste só responde se o atendimento continuar aberto e no setor dela;
- passar para a equipe = mudar para o setor de passagem (Comercial - resgate) e tirar do modo automático;
- a entrada continua pelo webhook da Meta; a mídia recebida é baixada pela Meta com o phone_number_id do número oficial
  (funciona: teste de áudio de 25/11/2026). "Lida" não: o app da Celeste não tem permissão de envio nesse número (code 10).
- texto: o send-message-waent recusa mais de 255 caracteres (HTTP 422, teste de 25/11/2026); textos maiores saem em
  mensagens seguidas, quebradas em parágrafo, frase ou palavra (`dividir_texto`).
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any, Callable, Optional

from celeste.comum import config, telefones
from celeste.ferramentas import meta
from celeste.ferramentas.mktzap import MktZap, MktZapErro, atendimento_aberto, desde_minutos

log = logging.getLogger(__name__)


def cfg() -> dict:
    return config.parametros()["mktzap"]


def _tamanho(texto: str) -> int:
    """Tamanho como o MarketZap (JavaScript) conta: unidades UTF-16, então emoji vale 2."""
    return len(texto.encode("utf-16-le")) // 2


def _cortar(texto: str, limite: int) -> list[str]:
    """Pedaço maior que o limite: quebra por frase, depois por palavra, e só em último caso no meio."""
    for padrao in (r"(?<=[.!?…])\s+", r"\s+"):
        partes: list[str] = []
        for x in (y for y in re.split(padrao, texto) if y):
            if partes and not re.search(r"\w", x) and _tamanho(partes[-1] + " " + x) <= limite:
                partes[-1] += " " + x   # emoji ou pontuação solta fica com a frase de antes, não vira mensagem sozinha
            else:
                partes.append(x)
        if len(partes) > 1:
            return _juntar(partes, " ", limite)
    pedacos, atual = [], ""
    for ch in texto:
        if atual and _tamanho(atual + ch) > limite:
            pedacos.append(atual)
            atual = ""
        atual += ch
    return pedacos + ([atual] if atual else [])


def _juntar(partes: list[str], sep: str, limite: int) -> list[str]:
    saida: list[str] = []
    for parte in partes:
        if _tamanho(parte) > limite:
            saida.extend(_cortar(parte, limite))
        elif saida and _tamanho(saida[-1] + sep + parte) <= limite:
            saida[-1] = saida[-1] + sep + parte
        else:
            saida.append(parte)
    return saida


def dividir_texto(texto: str, limite: Optional[int] = None) -> list[str]:
    """Quebra o texto em pedaços que caibam no limite do MarketZap, preferindo parágrafo, depois linha, frase e palavra."""
    limite = int(limite or cfg().get("limite_texto", 250))
    texto = (texto or "").strip()
    if _tamanho(texto) <= limite:
        return [texto] if texto else []
    pedacos: list[str] = []
    for par in [x.strip() for x in re.split(r"\n\s*\n", texto) if x.strip()]:
        if _tamanho(par) <= limite:
            pedacos.append(par)
        elif "\n" in par:
            pedacos.extend(_juntar([x for x in par.split("\n") if x.strip()], "\n", limite))
        else:
            pedacos.extend(_cortar(par, limite))
    return _juntar(pedacos, "\n\n", limite)


def canal_do_numero(phone_number_id: Optional[str]) -> Optional[str]:
    """'meta' (número atual, ou evento sem metadata), 'mktzap' (número oficial) ou None (número desconhecido: descartar)."""
    if not phone_number_id or str(phone_number_id) == meta.PHONE_ID:
        return "meta"
    if str(phone_number_id) == str(cfg()["phone_number_id"]):
        return "mktzap"
    return None


def para_conversa(conv: Optional[dict], padrao=None):
    """Canal de uma conversa já existente."""
    if (conv or {}).get("canal") == "mktzap":
        return CanalMktZap(conv)
    return padrao or meta.Meta()


def para_envio(nome_canal: Optional[str], conv: Optional[dict] = None):
    """Canal dos jobs de template (`disparos.canal`)."""
    return CanalMktZap(conv) if nome_canal == "mktzap" else meta.Meta()


def _contact_id_da_resposta(resp: Any) -> Optional[str]:
    """O send-hsm devolve {"history_id": {"success": true, "contact_id": "..."}}; só serve se for o id interno (não o telefone)."""
    if not isinstance(resp, dict):
        return None
    hid = resp.get("history_id")
    valor = (hid.get("contact_id") if isinstance(hid, dict) else None) or resp.get("contact_id")
    return str(valor) if valor and not str(valor).isdigit() else None


class CanalMktZap:
    nome = "mktzap"

    def __init__(self, conv: Optional[dict] = None, mz: Optional[MktZap] = None, leitor_meta: Optional[meta.Meta] = None,
                 dormir: Callable[[float], None] = time.sleep, mover_setor: bool = True):
        self.conv = conv or {}
        self.mover_setor = mover_setor               # False no envio de teste: o usuário quer ser avisado antes de mudar setor
        self.mz = mz or MktZap()
        self._meta = leitor_meta
        self.dormir = dormir
        self.atendimento: Optional[dict] = None
        self.setor_anterior: Optional[int] = None    # quando o template caiu em outro setor e foi movido
        self.operador_removido: Optional[int] = None  # atendente que estava no atendimento antes do template da Celeste
        self._hsm: Optional[dict[str, int]] = None

    # ----------------------------------------------------------- apoio
    def meta(self) -> meta.Meta:
        self._meta = self._meta or meta.Meta(phone_id=str(cfg()["phone_number_id"]))
        return self._meta

    def _telefones(self, para: str) -> set[str]:
        nums = set(telefones.variantes(para))
        for campo in ("contato", "wa_id"):
            if self.conv.get(campo):
                nums.update(telefones.variantes(self.conv[campo]))
        return nums

    @staticmethod
    def _novo_id() -> str:
        return f"mktzap-{uuid.uuid4().hex}"   # a API não devolve o wamid do que envia

    def localizar_atendimento(self, telefone: str, contact_id: Optional[str] = None, tentativas: int = 1) -> Optional[dict]:
        """Atendimento ABERTO do lead no canal oficial: pelo contact_id (rápido) ou pelos atualizados nos últimos minutos."""
        c = cfg()
        for i in range(tentativas):
            cid = contact_id or self.conv.get("mktzap_contact_id")
            h = atendimento_aberto(self.mz.atendimentos(contact_id=cid), c["canal_id"]) if cid else None
            if h is None:
                lista = self.mz.atendimentos(atualizados_desde=desde_minutos(float(c.get("procurar_atendimento_minutos") or 30)))
                h = atendimento_aberto(lista, c["canal_id"], self._telefones(telefone))
            if h is not None:
                self.atendimento = h
                return h
            if i < tentativas - 1:
                self.dormir(2.0 * (i + 1))   # o atendimento do template pode levar alguns segundos para aparecer
        return None

    def campos_conversa(self) -> dict:
        """Campos gravados na conversa da Celeste (canal + identificação do atendimento no MarketZap)."""
        h = self.atendimento or {}
        campos = {"canal": "mktzap", "mktzap_history_id": h.get("id"), "mktzap_protocolo": h.get("protocol"),
                  "mktzap_contact_id": h.get("contact_id"), "mktzap_setor_id": h.get("sector_id")}
        if self.setor_anterior is not None:
            campos["mktzap_setor_movido_de"] = self.setor_anterior
        if self.operador_removido is not None:
            campos["mktzap_operador_removido"] = self.operador_removido
        return {k: v for k, v in campos.items() if v is not None}

    def confirmar_atendimento(self, telefone: str) -> tuple[bool, str]:
        """Antes de responder: o atendimento precisa estar aberto e no setor da Celeste."""
        h = self.localizar_atendimento(telefone)
        if h is None:
            return False, "sem atendimento aberto no MarketZap"
        if int(h.get("sector_id") or 0) != int(cfg()["setor_celeste_id"]):
            return False, f"atendimento no setor {h.get('sector_id')}, fora do setor da Celeste"
        return True, ""

    def garantir_setor_celeste(self) -> None:
        h = self.atendimento
        alvo = int(cfg()["setor_celeste_id"])
        if h and int(h.get("sector_id") or 0) != alvo:
            if not self.mover_setor:
                log.warning("atendimento %s está no setor %s (não movido: mover_setor=False)", h.get("protocol"), h.get("sector_id"))
                return
            anterior = h.get("sector_id")
            self.mz.mudar_setor(h["protocol"], alvo)
            self.setor_anterior = anterior
            log.warning("atendimento %s estava no setor %s; movido para o setor da Celeste", h.get("protocol"), self.setor_anterior)
            h["sector_id"] = alvo

    def liberar_operador(self) -> None:
        """Atendimento no setor da Celeste ainda com uma atendente: tira a atendente (decisão do usuário, 25/11/2026). Sempre DEPOIS
        de mover para o setor da Celeste, que não tem pessoas: assim a distribuição do MarketZap não entrega o lead a ninguém."""
        h = self.atendimento
        if not h or not self.mover_setor or not h.get("operator_assigned_id"):
            return
        if int(h.get("sector_id") or 0) != int(cfg()["setor_celeste_id"]):
            return
        self.mz.tirar_do_automatico(h["protocol"])
        self.operador_removido = h.get("operator_assigned_id")
        log.warning("atendimento %s estava com o operador %s; liberado para a Celeste", h.get("protocol"), self.operador_removido)
        h["operator_assigned_id"] = None

    def passar_para_equipe(self, telefone: str) -> dict:
        """Lead encaminhado: vai para o setor de passagem e sai do modo automático (entra na distribuição da equipe)."""
        h = self.atendimento or self.localizar_atendimento(telefone)
        if h is None:
            raise MktZapErro("sem atendimento aberto para transferir")
        setor = int(cfg()["setor_passagem_id"])
        self.mz.mudar_setor(h["protocol"], setor)
        h["sector_id"] = setor
        try:
            self.mz.tirar_do_automatico(h["protocol"])
        except MktZapErro as e:   # atendimento que não estava em modo automático: o setor já mudou, segue
            log.warning("transfer-no-operator %s: %s", h.get("protocol"), e)
        return {"protocolo": h["protocol"], "setor": setor}

    def _history_id(self, para: str) -> int:
        if self.atendimento:
            return self.atendimento["id"]
        if self.conv.get("mktzap_history_id"):
            return self.conv["mktzap_history_id"]
        h = self.localizar_atendimento(para)
        if h is None:
            raise MktZapErro("sem atendimento aberto no MarketZap para responder")
        return h["id"]

    # ----------------------------------------------------------- mesma interface de meta.Meta
    def enviar_texto(self, para: str, texto: str) -> str:
        """Texto acima do limite do MarketZap sai em mensagens seguidas (o orquestrador grava o texto inteiro com um id só)."""
        history_id = self._history_id(para)
        for i, pedaco in enumerate(dividir_texto(texto)):
            if i:
                self.dormir(1.0)   # mantém a ordem e dá o ritmo de quem digita
            self.mz.enviar_texto(history_id, pedaco)
        return self._novo_id()

    def enviar_imagem_link(self, para: str, url: str, legenda: str = "") -> str:
        self.mz.enviar_midia(self._history_id(para), "image", url, legenda)
        return self._novo_id()

    def enviar_video_link(self, para: str, url: str, legenda: str = "") -> str:
        """A API do MarketZap não envia vídeo: 'link' manda o link em texto (fica no MarketZap); 'meta' manda o vídeo pela Meta."""
        if cfg().get("video") == "meta":
            return self.meta().enviar_video_link(para, url, legenda)
        return self.enviar_texto(para, f"{legenda}\n\n{url}" if legenda else url)

    def enviar_video(self, para: str, media_id: str, legenda: str = "") -> str:
        raise MktZapErro("vídeo por media_id não existe no MarketZap; use enviar_video_link")

    def enviar_botao_url(self, para: str, texto: str, rotulo: str, url: str) -> str:
        return self.enviar_texto(para, f"{texto}\n\n{url}")

    def enviar_botoes_resposta(self, para: str, texto: str, botoes: list[tuple[str, str]]) -> str:
        return self.enviar_texto(para, texto)

    def marcar_lida(self, wamid: str) -> None:
        """Desligado (25/11/2026): a Meta recusa "lida" do app da Celeste no número oficial (code 10, subcode 2593181)."""
        return None

    def baixar_midia(self, media_id: str) -> tuple[bytes, str]:
        return self.meta().baixar_midia(media_id)

    def _mapa_hsm(self) -> dict[str, int]:
        if self._hsm is None:
            self._hsm = {}
            for t in self.mz.templates_hsm():
                for chave in (t.get("element_name"), t.get("name")):
                    if chave:
                        self._hsm.setdefault(str(chave), int(t["id"]))
        return self._hsm

    def texto_do_template(self, nome: str, parametros: list[str]) -> Optional[str]:
        """Corpo do template como o MarketZap guarda ({{n}} preenchidos), com marca da imagem do cabeçalho quando houver."""
        alvo = self.nome_no_mktzap(nome)
        for t in self.mz.templates_hsm():
            if alvo in (t.get("element_name"), t.get("name")):
                corpo = str(t.get("template") or "")
                if corpo.startswith('"') and corpo.endswith('"'):
                    import json
                    try:
                        corpo = json.loads(corpo)
                    except ValueError:
                        pass
                for i, p in enumerate(parametros, 1):
                    corpo = corpo.replace("{{%d}}" % i, p)
                marca = f"[imagem do template {alvo}]\n" if t.get("header_type") == "image" else ""
                return marca + corpo
        return None

    def nome_no_mktzap(self, nome: str) -> str:
        return (cfg().get("templates") or {}).get(nome) or nome

    def templates(self) -> list[dict]:
        """No formato da Meta (name/status), para a checagem de aprovados dos jobs."""
        mapa = self._mapa_hsm()
        return [{"name": n, "status": "APPROVED", "hsm_id": i} for n, i in mapa.items()] + \
               [{"name": orig, "status": "APPROVED", "hsm_id": mapa[dest]} for orig, dest in (cfg().get("templates") or {}).items() if dest in mapa]

    def enviar_template(self, para: str, nome: str, parametros_corpo: list[str], idioma: str = "pt_BR",
                        imagem_cabecalho: Optional[str] = None) -> str:
        self.atendimento, self.setor_anterior, self.operador_removido = None, None, None   # os jobs usam a mesma instância para vários leads
        if imagem_cabecalho:
            log.warning("template %s com imagem no cabeçalho: a API do MarketZap não documenta como enviar a imagem (pergunta ao suporte)", nome)
        hsm_id = self._mapa_hsm().get(self.nome_no_mktzap(nome))
        if hsm_id is None:
            raise MktZapErro(f"template {self.nome_no_mktzap(nome)} não existe no MarketZap")
        resp = self.mz.enviar_hsm(para, hsm_id, parametros_corpo, nome=self.conv.get("nome"),
                                  setor_id=cfg()["setor_celeste_id"], automatico=bool(cfg().get("atendimento_automatico", True)))
        h = self.localizar_atendimento(para, contact_id=_contact_id_da_resposta(resp), tentativas=3)
        if h is None:
            log.error("template %s enviado pelo MarketZap, mas o atendimento não foi localizado (setor não conferido)", nome)
        else:
            self.garantir_setor_celeste()
            self.liberar_operador()
        return self._novo_id()
