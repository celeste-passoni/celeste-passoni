# -*- coding: utf-8 -*-
"""Grafias equivalentes de um celular brasileiro (decisão da clínica, 03/11/2026: casos Adryano/DDD 49 e Steffany/DDD 62).

A base da clínica guarda o celular com o 9º dígito (55 + DDD + 9 + 8 dígitos). Em alguns DDDs a Meta identifica o mesmo
aparelho SEM o 9 (55 + DDD + 8 dígitos): o template sai para o número com 9, chega, e a resposta volta "de outro número".
Sem este tratamento o gateway abria uma 2ª conversa, sem frente, e a Celeste não respondia.
"""
from __future__ import annotations


def so_digitos(numero: str) -> str:
    return "".join(ch for ch in str(numero or "") if ch.isdigit())


def variantes(numero: str) -> list[str]:
    """O próprio número primeiro, depois a outra grafia (com ou sem o 9), quando for celular brasileiro. Não repete."""
    n = so_digitos(numero)
    saida = [n] if n else []
    if n.startswith("55"):
        resto = n[2:]                       # DDD + assinante
        if len(resto) == 11 and resto[2] == "9":       # com o 9: 55 + DD + 9 + 8 dígitos
            saida.append("55" + resto[:2] + resto[3:])
        elif len(resto) == 10 and resto[2] in "6789":  # sem o 9: 55 + DD + 8 dígitos (celular começa por 6-9)
            saida.append("55" + resto[:2] + "9" + resto[2:])
    return saida


def mesmo_celular(a: str, b: str) -> bool:
    return bool(a and b) and so_digitos(b) in variantes(a)
