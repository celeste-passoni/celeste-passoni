# -*- coding: utf-8 -*-
"""Transcrição de áudio (Google Speech-to-Text v2, pt-BR) e consulta de CEP (ViaCEP)."""
from __future__ import annotations

import logging

import requests

from celeste.comum import config

log = logging.getLogger(__name__)


def transcrever(audio: bytes, mime: str = "audio/ogg") -> str:
    """Transcreve um áudio curto (WhatsApp: OGG/Opus). Retorna '' se falhar — a IA pede por texto."""
    try:
        from google.cloud import speech_v2 as speech
        cliente = speech.SpeechClient()
        cfg = speech.RecognitionConfig(auto_decoding_config=speech.AutoDetectDecodingConfig(),
                                       language_codes=["pt-BR"], model="latest_long")
        req = speech.RecognizeRequest(recognizer=f"projects/{config.PROJETO_GCP}/locations/global/recognizers/_",
                                      config=cfg, content=audio)
        resp = cliente.recognize(request=req)
        return " ".join(r.alternatives[0].transcript for r in resp.results if r.alternatives).strip()
    except Exception as e:  # nunca derruba a conversa
        log.warning("transcrição falhou: %s", e)
        return ""


def viacep(cep: str) -> dict:
    """Faz o que a tela do TI Saúde faz ao digitar o CEP: preenche rua, bairro, cidade e UF. {} se inválido."""
    digitos = "".join(ch for ch in cep if ch.isdigit())
    if len(digitos) != 8:
        return {}
    try:
        d = requests.get(f"https://viacep.com.br/ws/{digitos}/json/", timeout=15).json()
    except Exception:
        return {}
    if d.get("erro"):
        return {}
    return {"endereco": (d.get("logradouro") or "").upper(), "bairro": (d.get("bairro") or "").upper(),
            "cidade": (d.get("localidade") or "").upper(), "uf": d.get("uf", "")}
