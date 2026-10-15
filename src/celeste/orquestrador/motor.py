# -*- coding: utf-8 -*-
"""Motor de conversa: chama o Claude com as ferramentas, executa o ciclo, mede custo e faz fallback de modelo."""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import anthropic

from celeste.comum import config
from celeste.orquestrador import ferramentas_ia, prompt

log = logging.getLogger(__name__)


@dataclass
class Resultado:
    baloes: list[str]
    modelo: str
    custo_usd: float
    tokens: dict
    chamadas: int
    ferramentas: list[dict] = field(default_factory=list)
    refusal: bool = False


def _custo(modelo: str, uso: Any) -> float:
    precos = config.parametros()["modelos"]["precos_usd_por_milhao"].get(modelo, {})
    def m(k, v): return (v or 0) * precos.get(k, 0) / 1_000_000
    return (m("entrada", getattr(uso, "input_tokens", 0)) + m("saida", getattr(uso, "output_tokens", 0))
            + m("cache_leitura", getattr(uso, "cache_read_input_tokens", 0)) + m("cache_escrita", getattr(uso, "cache_creation_input_tokens", 0)))


def _somar(tot: dict, uso: Any) -> None:
    for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        tot[k] = tot.get(k, 0) + (getattr(uso, k, 0) or 0)


import re as _re
_TRAVESSAO = _re.compile(r"\s*[—–]\s+|\s+-\s+(?=[a-záéíóúâêôãõç])")
_DOIS_PONTOS = _re.compile(r"([a-záéíóúâêôãõç\)])\s*:\s+([a-záéíóúâêôãõç])")   # letra + ':' + minúscula; preserva horários (10:00), listas e "Endereço: Av."


def limpar_pontuacao(texto: str) -> str:
    """Travessão/hífen usado como pontuação no meio da frase vira vírgula (vício de escrita do modelo; soa artificial no WhatsApp)."""
    out = []
    for linha in texto.split("\n"):
        if linha.lstrip().startswith(("-", "—", "–", "•")):   # marcador de lista no início da linha: mantém
            out.append(linha); continue
        linha = _TRAVESSAO.sub(", ", linha)
        linha = _DOIS_PONTOS.sub(r"\1, \2", linha)   # "conferi no sistema: não tem" → "conferi no sistema, não tem" (pedido da clínica, 13/10)
        out.append(linha.replace(" ,", ",").replace(",,", ","))
    return "\n".join(out)


def separar_baloes(texto: str) -> list[str]:
    partes = [p.strip() for p in texto.replace("\r", "").split("\n---") if p.strip()]
    partes = [p[3:].strip() if p.startswith("---") else p for p in partes]
    partes = [limpar_pontuacao(p) for p in partes]
    partes = [p for p in partes if p and p.strip("-—– ")]       # descarta balão que seja só traço
    if len(partes) > MAX_BALOES:                                 # 14/10/2026: a clínica pediu no máximo 3 balões por resposta; o excedente vira parágrafos do 3º
        partes = partes[:MAX_BALOES - 1] + ["\n\n".join(partes[MAX_BALOES - 1:])]
    return partes or ([limpar_pontuacao(texto.strip())] if texto.strip() else [])


MAX_BALOES = 3


def delay_humano(fora_horario: bool = False) -> float:
    """Log-normal com mediana configurada; nunca abaixo do mínimo."""
    d = config.parametros()["ia"]["delay_resposta_segundos"]
    if fora_horario:
        d = d.get("fora_horario_comercial", d)
    mediana, minimo, maximo = float(d["mediana"]), float(d["minimo"]), float(d["maximo"])
    v = random.lognormvariate(0, 0.45) * mediana
    return max(minimo, min(maximo, v))


class Motor:
    def __init__(self, cliente: Optional[anthropic.Anthropic] = None):
        self.cliente = cliente or anthropic.Anthropic(api_key=config.segredo("ANTHROPIC_API_KEY"), max_retries=1, timeout=90.0)
        self.cfg = config.parametros()["modelos"]

    def _system(self, frente: str) -> list:
        """O 1º bloco (estável, com cache de 1 h) é idêntico entre a conversa real e o keep-alive; o 2º é volátil (data/hora)."""
        return [
            {"type": "text", "text": prompt.camadas_estaveis(frente), "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"type": "text", "text": prompt.formato_saida()},
        ]

    def aquecer(self, frente: str) -> dict:
        """Keep-alive do cache: reenvia tools + prompt fixo com max_tokens=0. A API só faz o prefill (grava ou renova o cache)
        e devolve content vazio; custo = leitura de cache (ou uma gravação, se tinha expirado). Nada é gerado."""
        resp = self._criar(self.cfg["conversa"], self._system(frente), [{"role": "user", "content": "."}], max_tokens=0)
        uso = resp.usage
        return {"frente": frente, "modelo": resp.model or self.cfg["conversa"], "custo_usd": round(_custo(resp.model or self.cfg["conversa"], uso), 5),
                "cache_lido": getattr(uso, "cache_read_input_tokens", 0) or 0, "cache_gravado": getattr(uso, "cache_creation_input_tokens", 0) or 0}

    def _criar(self, modelo: str, system: list, messages: list, max_tokens: Optional[int] = None) -> Any:
        extras = {}
        if "haiku" not in modelo:   # raciocínio adaptativo e fallback automático do servidor só nos modelos grandes
            extras = {"thinking": {"type": "adaptive"}, "output_config": {"effort": self.cfg.get("esforco", "medium")},
                      "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        return self.cliente.beta.messages.create(
            model=modelo, max_tokens=int(self.cfg["max_tokens_resposta"]) if max_tokens is None else max_tokens,
            system=system, messages=messages, tools=ferramentas_ia.FERRAMENTAS, **extras,
        )

    def _chamar(self, system: list, messages: list, modelo: Optional[str] = None) -> tuple[Any, str]:
        """Principal com 1 retentativa; depois fallback para o modelo secundário. `modelo` força outro modelo (ex.: Haiku para lembretes)."""
        principal, secundario = modelo or self.cfg["conversa"], self.cfg["conversa_fallback"]
        try:
            return self._criar(principal, system, messages), principal
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APITimeoutError) as e:
            log.warning("modelo principal falhou (%s); usando fallback %s", type(e).__name__, secundario)
            return self._criar(secundario, system, messages), secundario

    def responder(self, frente: str, conversa: dict, historico: list[dict], ctx: ferramentas_ia.Contexto,
                  modelo: Optional[str] = None) -> Resultado:
        """historico: mensagens no formato da API (user/assistant), a última sendo do lead. `modelo` opcional força outro modelo."""
        system = self._system(frente)
        messages = list(historico)
        # contexto volátil do lead entra junto da primeira mensagem do usuário (não invalida o cache do system)
        if messages and isinstance(messages[0].get("content"), str):
            messages[0] = {"role": "user", "content": prompt.contexto_lead(conversa) + "\n\n" + messages[0]["content"]}
        tokens: dict = {}
        custo, chamadas, usadas, forcado = 0.0, 0, [], modelo
        modelo = forcado or self.cfg["conversa"]
        texto_acumulado = ""   # o modelo pode escrever balões ANTES de chamar uma ferramenta; nada se perde
        while True:
            resp, modelo = self._chamar(system, messages, forcado)
            chamadas += 1
            _somar(tokens, resp.usage)
            custo += _custo(resp.model or modelo, resp.usage)
            if resp.stop_reason == "refusal":
                return Resultado([], modelo, custo, tokens, chamadas, usadas, refusal=True)
            trecho = "".join(b.text for b in resp.content if b.type == "text").strip()
            if trecho:
                texto_acumulado = (texto_acumulado + "\n---\n" + trecho) if texto_acumulado else trecho
            if resp.stop_reason != "tool_use" or chamadas >= int(self.cfg["max_chamadas_por_resposta"]):
                return Resultado(separar_baloes(texto_acumulado), modelo, custo, tokens, chamadas, usadas)
            messages.append({"role": "assistant", "content": resp.content})
            resultados = []
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                t0 = time.time()
                saida, erro = ferramentas_ia.executar(b.name, dict(b.input), ctx)
                usadas.append({"nome": b.name, "entrada": dict(b.input), "saida": saida[:2000], "erro": erro, "ms": int((time.time() - t0) * 1000)})
                resultados.append({"type": "tool_result", "tool_use_id": b.id, "content": saida, "is_error": erro})
            messages.append({"role": "user", "content": resultados})
