# -*- coding: utf-8 -*-
"""Configuração da Celeste: parâmetros da clínica (YAML) e segredos.

Ordem de resolução de um segredo: variável de ambiente → arquivo .env (local) → Secret Manager (produção).
Nunca registre valores de segredos em log.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

RAIZ = Path(__file__).resolve().parents[3]
PROJETO_GCP = os.environ.get("GCP_PROJECT", "vertical-theory-489419-a7")
REGIAO = os.environ.get("GCP_REGION", "southamerica-east1")
FUSO = "America/Sao_Paulo"

# nome da variável de ambiente → nome do segredo no Secret Manager
SEGREDOS = {
    "TISAUDE_HASH": "tisaude-hash",
    "TISAUDE_LOGIN": "tisaude-login",
    "TISAUDE_SENHA": "tisaude-senha",
    "TISAUDE_HASH_PACIENTE": "tisaude-hash-paciente",
    "META_TOKEN": "meta-token",
    "META_VERIFY_TOKEN": "meta-verify-token",
    "META_APP_SECRET": "meta-app-secret",
    "ANTHROPIC_API_KEY": "anthropic-api-key",
}


def _carregar_dotenv() -> None:
    env = RAIZ / ".env"
    if not env.exists():
        return
    for linha in env.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip())


_carregar_dotenv()


@lru_cache(maxsize=None)
def segredo(nome_env: str) -> str:
    """Retorna o valor de um segredo (env/.env primeiro; Secret Manager em produção)."""
    valor = os.environ.get(nome_env)
    if valor:
        return valor
    nome_secreto = SEGREDOS.get(nome_env)
    if not nome_secreto:
        raise KeyError(f"Segredo desconhecido: {nome_env}")
    from google.cloud import secretmanager  # import tardio: só em produção

    cliente = secretmanager.SecretManagerServiceClient()
    caminho = f"projects/{PROJETO_GCP}/secrets/{nome_secreto}/versions/latest"
    return cliente.access_secret_version(request={"name": caminho}).payload.data.decode("utf-8")


@lru_cache(maxsize=1)
def parametros() -> dict[str, Any]:
    """Carrega config/parametros.yaml (fonte da verdade da clínica)."""
    with open(RAIZ / "config" / "parametros.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def profissional(id_: str) -> dict[str, Any]:
    """Dados de um profissional ofertado ('dra_luciana' | 'dr_lucas')."""
    for c in parametros()["consultas"]:
        if c["id"] == id_:
            return c
    raise KeyError(id_)


def procedimento_permitido(id_procedimento: int) -> dict[str, Any]:
    """Garante que a IA só agenda os procedimentos autorizados (264 e 5)."""
    for p in parametros()["procedimentos_permitidos"]:
        if int(p["id"]) == int(id_procedimento):
            return p
    raise ValueError(f"Procedimento {id_procedimento} não autorizado para a IA")
