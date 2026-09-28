# -*- coding: utf-8 -*-
"""Carga da base de Leads Perdidos: BigQuery (query da clínica + filtros do YAML) → Firestore `leads`.

Regras:
  • a IA só LÊ as tabelas da clínica; o estado dela vive em `leads/{celular}` no Firestore;
  • um lead que já existe no Firestore mantém status_ia, ciclo e histórico — só atualizamos os dados vindos da clínica;
  • quem saiu da base (agendou, 'Não quer', fora da janela) fica `elegivel=false` e sai da fila de disparo;
  • telefone normalizado para o formato da Meta (55 + DDD + 9 dígitos); formato irreconhecível → inelegível.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from google.cloud import bigquery, firestore

from celeste.comum import config

log = logging.getLogger(__name__)


def normalizar_celular(bruto: str | None) -> str | None:
    d = re.sub(r"\D", "", bruto or "").lstrip("0")
    if d.startswith("55") and len(d) == 13:
        return d
    if d.startswith("55") and len(d) == 12:          # 55 + DDD + 8 dígitos (sem o 9)
        return d[:4] + "9" + d[4:]
    if len(d) == 11:
        return "55" + d
    if len(d) == 10:
        return "55" + d[:2] + "9" + d[2:]
    return None


def sql_base(p: dict) -> str:
    f = p["filtros"]
    condicao_data = (f"DATE(t.created_at) >= DATE_SUB(CURRENT_DATE('America/Sao_Paulo'), INTERVAL {int(f['janela_meses'])} MONTH)"
                     if f.get("janela_meses") else f"DATE(t.created_at) >= '{f['created_at_a_partir_de']}'")
    excluidos = ", ".join(f"'{s}'" for s in p["status_da_clinica_excluidos"])
    return f"""
WITH base AS (
  SELECT t.celular, t.nome, t.created_at, t.primeira_origem, t.cpf,
         s.status AS status_clinica, s.contatado AS contatado_clinica, s.data_atualizacao AS status_clinica_em,
         ROW_NUMBER() OVER (PARTITION BY t.celular ORDER BY t.created_at DESC) AS rn
  FROM `{p['fonte']['tabela_leads']}` t
  LEFT JOIN `{p['fonte']['tabela_status']}` s
    ON s.nome = t.nome AND REGEXP_REPLACE(s.contato, '[^0-9]', '') = REGEXP_REPLACE(t.celular_sem_ddd, '[^0-9]', '')
  WHERE LOWER(t.agendou) IN ('não', 'nao')
    AND LOWER(t.participou_acao_lead_perdidos) IN ('não', 'nao')
    AND LOWER(t.dentro_2_dias_uteis) IN ('não', 'nao')
    AND {condicao_data}
    AND t.created_at < CURRENT_TIMESTAMP()
)
SELECT * EXCEPT(rn) FROM base
WHERE rn = 1 AND (status_clinica IS NULL OR status_clinica NOT IN ({excluidos}))
"""


def carregar(dry_run: bool = False) -> dict:
    p = config.parametros()["leads_perdidos"]
    bq = bigquery.Client(project=config.PROJETO_GCP)
    db = firestore.Client(project=config.PROJETO_GCP)
    linhas = list(bq.query(sql_base(p)).result())
    agora = datetime.now(timezone.utc)
    vistos: set[str] = set()
    novos = atualizados = invalidos = 0
    lote, n_lote = db.batch(), 0

    existentes = {d.id: d.to_dict() for d in db.collection("leads").select(["status_ia", "elegivel"]).stream()}

    for r in linhas:
        cel = normalizar_celular(r["celular"])
        if not cel or cel in vistos:
            invalidos += 1
            continue
        vistos.add(cel)
        nome = (r["nome"] or "").strip()
        dados = {
            "celular": cel, "nome": nome, "primeiro_nome": _primeiro_nome(nome), "frente": "leads_perdidos",
            "lead_created_at": r["created_at"], "origem": r["primeira_origem"], "tem_cpf": bool(r["cpf"]),
            "status_clinica": r["status_clinica"], "contatado_clinica": r["contatado_clinica"],
            "elegivel": True, "atualizado_em": agora,
        }
        if cel not in existentes:
            dados.update({"status_ia": "Não contatado", "passo": 0, "ciclo": 0, "templates_enviados": [],
                          "proximo_contato_em": None, "opt_out": False, "conversa_id": None, "carregado_em": agora})
            novos += 1
        else:
            atualizados += 1
        if not dry_run:
            lote.set(db.collection("leads").document(cel), dados, merge=True)
            n_lote += 1
            if n_lote >= 400:
                lote.commit(); lote, n_lote = db.batch(), 0

    sairam = [cid for cid, d in existentes.items() if d.get("elegivel") and cid not in vistos]
    if not dry_run:
        for cid in sairam:
            lote.set(db.collection("leads").document(cid), {"elegivel": False, "saiu_da_base_em": agora}, merge=True)
            n_lote += 1
            if n_lote >= 400:
                lote.commit(); lote, n_lote = db.batch(), 0
        if n_lote:
            lote.commit()
    resumo = {"lidos_bigquery": len(linhas), "elegiveis": len(vistos), "novos": novos, "atualizados": atualizados,
              "invalidos_ou_duplicados": invalidos, "sairam_da_base": len(sairam), "dry_run": dry_run}
    log.info("carga da base: %s", resumo)
    return resumo


def _primeiro_nome(nome: str) -> str:
    partes = [x for x in re.split(r"\s+", nome.strip()) if x]
    if not partes:
        return ""
    return partes[0].capitalize()
