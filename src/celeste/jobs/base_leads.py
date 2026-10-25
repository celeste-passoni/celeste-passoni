# -*- coding: utf-8 -*-
"""Carga da base de Leads Perdidos: query oficial da clínica (BigQuery) → Firestore `leads`.

Regras:
  • a query é a da clínica (gold.leads + gold.sistemaweb_perdidos; janela de 3 a 4 meses; exclui 'Não quer'; 1 por celular);
  • a IA só LÊ as tabelas da clínica; o estado dela vive em `leads/{celular}` no Firestore;
  • a janela de data vale na ENTRADA: quem já recebeu template (passo > 0) fica elegível até o fim do ciclo,
    a menos que tenha agendado / 'Não quer' / participado de outra ação (query sem janela);
  • `disponibilizado_em` = primeira vez que o lead apareceu na base (métrica "Leads disponibilizados" do painel);
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


def sql_base(p: dict, com_janela: bool = True) -> str:
    """Query oficial da clínica (recebida em 02/10/2026). `com_janela=False` = mesmos filtros sem o recorte de data
    (usada para saber se quem já está na esteira continua válido)."""
    f = p["filtros"]
    excluidos = ", ".join(f"'{s}'" for s in p["status_da_clinica_excluidos"])
    janela = (f"  AND DATE(t.created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL {int(f['janela_meses_max'])} MONTH)\n"
              f"  AND DATE(t.created_at) <  DATE_SUB(CURRENT_DATE(), INTERVAL {int(f['janela_meses_min'])} MONTH)\n") if com_janela else ""
    return f"""
SELECT
  CURRENT_DATE() AS data_execucao,
  'Perdidos' AS frente,
  CAST(t.created_at AS DATETIME) AS data,
  t.nome AS nome,
  CONCAT('55', REGEXP_REPLACE(CAST(t.celular_sem_ddd AS STRING), r'[^0-9]', '')) AS contato,
  t.primeira_origem AS info_extra,
  s.status AS status,
  s.data_atualizacao AS data_atualizacao,
  t.cpf AS cpf
FROM `{p['fonte']['tabela_leads']}` t
LEFT JOIN `{p['fonte']['tabela_status']}` s
  ON COALESCE(t.nome, '') = COALESCE(s.nome, '') AND COALESCE(CAST(t.celular_sem_ddd AS STRING), '') = COALESCE(s.contato, '')
WHERE LOWER(CAST(t.agendou AS STRING)) IN ('não', 'nao')
{janela}  AND LOWER(CAST(t.dentro_2_dias_uteis AS STRING)) IN ('não', 'nao')
  AND LOWER(CAST(t.participou_acao_lead_perdidos AS STRING)) = 'não'
  AND (s.status IS NULL OR s.status NOT IN ({excluidos}))
QUALIFY ROW_NUMBER() OVER (PARTITION BY t.celular_sem_ddd ORDER BY t.created_at DESC) = 1
"""


def sql_base_funil(p: dict) -> str:
    """Base do dia lida da tabela do funil de resgate da clínica (frente 'Perdidos IA', execução mais recente),
    com o CPF buscado em gold.leads pelo celular. Decisão da clínica em 22/10/2026."""
    tabela = p["fonte"].get("tabela_funil", "vertical-theory-489419-a7.automacoes.resgate_leads_diario")
    frente = p["fonte"].get("frente_funil", "Perdidos IA")
    return f"""
WITH ultima AS (
  SELECT MAX(data_execucao) AS data_execucao FROM `{tabela}` WHERE frente = '{frente}'
),
base AS (
  SELECT r.data_execucao, r.frente, r.data, r.nome, r.contato, r.info_extra, r.status, r.data_atualizacao
  FROM `{tabela}` r
  JOIN ultima u ON r.data_execucao = u.data_execucao
  WHERE r.frente = '{frente}'
),
cpfs AS (
  SELECT CONCAT('55', REGEXP_REPLACE(CAST(t.celular_sem_ddd AS STRING), r'[^0-9]', '')) AS contato, MAX(CAST(t.cpf AS STRING)) AS cpf
  FROM `{p['fonte']['tabela_leads']}` t
  GROUP BY 1
)
SELECT b.*, c.cpf
FROM base b
LEFT JOIN cpfs c ON c.contato = b.contato
"""


def carregar(dry_run: bool = False) -> dict:
    p = config.parametros()["leads_perdidos"]
    bq = bigquery.Client(project=config.PROJETO_GCP)
    db = firestore.Client(project=config.PROJETO_GCP)
    agora = datetime.now(timezone.utc)
    existentes = {d.id: d.to_dict() for d in db.collection("leads").select(["status_ia", "elegivel", "passo", "disponibilizado_em", "carregado_em", "teste"]).stream()}

    # (A) base do dia = frente 'Perdidos IA' da tabela do funil da clínica (decisão de 22/10/2026: uma fonte só,
    #     painel = Power BI por construção). Usa a execução mais recente da frente; se a frente ainda não existe
    #     na tabela (query do funil ainda sem a frente), NÃO mexe na base e avisa.
    na_janela: dict[str, dict] = {}
    invalidos = 0
    linhas = list(bq.query(sql_base_funil(p)).result())
    if not linhas:
        resumo = {"erro": "frente 'Perdidos IA' sem linhas em resgate_leads_diario; base mantida", "dry_run": dry_run}
        log.error("carga da base: %s", resumo)
        return resumo
    for r in linhas:
        cel = normalizar_celular(r["contato"])
        if not cel or cel in na_janela:
            invalidos += 1
            continue
        na_janela[cel] = dict(r)
    log.info("carga da base: frente 'Perdidos IA' da execução %s, %d linhas", linhas[0]["data_execucao"], len(linhas))
    # (B) quem já está na esteira continua válido se ainda passa nos filtros sem a janela
    em_esteira = {cid for cid, d in existentes.items() if int(d.get("passo") or 0) > 0 and d.get("elegivel")}
    ainda_validos: dict[str, dict] = {}
    if em_esteira:
        for r in bq.query(sql_base(p, com_janela=False)).result():
            cel = normalizar_celular(r["contato"])
            if cel in em_esteira and cel not in na_janela:
                ainda_validos[cel] = dict(r)

    novos = atualizados = 0
    lote, n = db.batch(), 0
    for cel, r in list(na_janela.items()) + list(ainda_validos.items()):
        nome = (r["nome"] or "").strip()
        dados = {
            "celular": cel, "nome": nome, "primeiro_nome": _primeiro_nome(nome), "frente": "leads_perdidos",
            "lead_created_at": r["data"].replace(tzinfo=timezone.utc) if r["data"].tzinfo is None else r["data"],
            "origem": r["info_extra"], "tem_cpf": bool(r["cpf"]), "status_clinica": r["status"],
            "status_clinica_em": r["data_atualizacao"], "elegivel": True, "atualizado_em": agora,
            "na_janela": cel in na_janela,
        }
        if cel not in existentes:
            dados.update({"status_ia": "Não contatado", "passo": 0, "ciclo": 0, "templates_enviados": [],
                          "proximo_contato_em": None, "opt_out": False, "conversa_id": None,
                          "carregado_em": agora, "disponibilizado_em": agora})
            novos += 1
        else:
            if not existentes[cel].get("disponibilizado_em"):
                dados["disponibilizado_em"] = existentes[cel].get("carregado_em") or agora
            atualizados += 1
        if not dry_run:
            lote.set(db.collection("leads").document(cel), dados, merge=True)
            n += 1
            if n >= 400:
                lote.commit(); lote, n = db.batch(), 0

    validos = set(na_janela) | set(ainda_validos)
    # 25/10/2026: lead de teste (número da clínica, criado à mão para simular a esteira) fica na base até ser removido no Firestore
    sairam = [cid for cid, d in existentes.items() if d.get("elegivel") and cid not in validos and not d.get("teste")]
    if not dry_run:
        for cid in sairam:
            lote.set(db.collection("leads").document(cid), {"elegivel": False, "saiu_da_base_em": agora}, merge=True)
            n += 1
            if n >= 400:
                lote.commit(); lote, n = db.batch(), 0
        if n:
            lote.commit()
    resumo = {"na_janela": len(na_janela), "mantidos_em_esteira": len(ainda_validos), "elegiveis": len(validos),
              "novos": novos, "atualizados": atualizados, "invalidos_ou_duplicados": invalidos,
              "sairam_da_base": len(sairam), "dry_run": dry_run}
    log.info("carga da base: %s", resumo)
    return resumo


def _primeiro_nome(nome: str) -> str:
    limpo = re.sub(r"[^A-Za-zÀ-ÿ' -]", " ", nome)          # tira emojis, números e símbolos
    partes = [x for x in re.split(r"\s+", limpo.strip()) if len(x) > 1]
    if not partes:
        return ""
    return partes[0].capitalize()
