# -*- coding: utf-8 -*-
"""Disparo de templates para Leads Perdidos, seguindo os ciclos de `disparos.passos` no YAML.

Quem responde a um template sai da esteira (o orquestrador assume e muda o status da conversa).
Quem respondeu e parou (objeção, 'vou pensar') volta pela tabela `template_por_status`
após os dias de `leads_perdidos.recontato_por_status_ia`.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from google.cloud import firestore

from celeste.comum import config
from celeste.ferramentas import meta, tisaude
from celeste.jobs import templates_texto

log = logging.getLogger(__name__)
FUSO = ZoneInfo(config.FUSO)


@dataclass
class Decisao:
    template: Optional[str]  # T1..T4; None = encerrar a esteira para este lead (sem envio)
    motivo: str              # 'passo 2 do ciclo 1' | 'recontato após Achou caro' | 'esteira encerrada'
    novo_passo: int
    novo_ciclo: int = 1      # nº do ciclo em que este envio acontece


def dentro_do_horario(agora: Optional[datetime] = None) -> bool:
    h = config.parametros()["disparos"]["horario"]
    agora = agora or datetime.now(FUSO)
    if h.get("dias_uteis") and agora.weekday() >= 5:
        return False
    return int(h["inicio"]) <= agora.hour < int(h["fim"])


def decidir(lead: dict, agora: datetime, tarde_livre_hoje: Optional[bool] = None) -> Optional[Decisao]:
    """Qual template este lead recebe agora? None = nada hoje."""
    p = config.parametros()
    d = p["disparos"]
    if not lead.get("elegivel") or lead.get("opt_out"):
        return None
    status = lead.get("status_ia") or "Não contatado"
    ultimo_lead = lead.get("ultima_msg_lead_em")
    ultimo_tpl = lead.get("ultimo_template_em")

    # 1) recontato de quem respondeu e parou
    if status == "Vamos retornar na data solicitada":
        return None   # 27/10/2026: hora exata pedida pelo lead é do job de retornos (celeste-retornos, a cada minuto), não da esteira
    if status in d["template_por_status"]:
        dias = p["leads_perdidos"]["recontato_por_status_ia"].get(status)
        quando = lead.get("proximo_recontato_em")
        if dias == "na data":
            if not quando:
                return None
        elif dias is None:
            return None
        else:
            base = ultimo_lead or ultimo_tpl
            if not base:
                return None
            quando = base + timedelta(days=int(dias))
        if _dt(quando) <= agora and _dt(ultimo_tpl) < agora - timedelta(hours=20):
            return Decisao(d["template_por_status"][status], f"recontato após '{status}'", int(lead.get("passo") or 0))
        return None

    # 2) esteira de templates (só quem nunca respondeu)
    if status not in ("Não contatado", "Template enviado (1°)", "Template enviado (2°)", "Template enviado (3°)"):
        return None
    passos = d["passos"]
    passo = int(lead.get("passo") or 0)
    ciclo = int(lead.get("ciclos") or 1)
    # 29/10/2026 (decisão da clínica): qualquer resposta (normal, automática, "não quero") tira da esteira, mesmo com o status
    # ainda em "Template enviado"; falha de entrega definitiva do último template também (`respondeu_em`/`falha_entrega`: rodar)
    if passo > 0 and (ultimo_lead or lead.get("respondeu_em")):
        return None
    if lead.get("falha_entrega") in set(d.get("falhas_que_param_esteira") or []):
        return None
    if passo >= len(passos):
        # fim da esteira: pausa e recomeça; depois de `max_ciclos` ciclos completos sem resposta, encerra para este lead
        if ultimo_tpl and _dt(ultimo_tpl) + timedelta(days=int(d["pausa_apos_ultimo_passo_dias"])) > agora:
            return None
        if ciclo >= int(d.get("max_ciclos") or 99):
            return Decisao(None, "esteira encerrada (sem resposta após os ciclos previstos)", passo, ciclo)
        passo = int(d["reiniciar_no_passo"]); ciclo += 1
    prox = passos[passo]
    if passo > 0 or ultimo_tpl:
        if not ultimo_tpl or _dt(ultimo_tpl) + timedelta(days=int(prox["apos_dias"])) > agora:
            return None
    if prox.get("so_se_horario_livre_hoje_a_tarde") and not tarde_livre_hoje:
        return None
    return Decisao(prox["template"], f"passo {passo + 1} (ciclo {ciclo})", passo + 1, ciclo)


def _dt(v) -> datetime:
    if v is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):                       # data sem hora = "a partir do início daquele dia" (hora local)
        return datetime(v.year, v.month, v.day, 0, tzinfo=FUSO)
    s = str(v)
    if "T" in s or " " in s:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=FUSO)   # 27/10/2026: "2026-10-27T11:30" gravado pela Celeste é hora de São Paulo
    return datetime.fromisoformat(s).replace(tzinfo=FUSO)


def _dt_retorno(v) -> datetime:
    """Hora do retorno combinado. Só data ("me chama na terça") = às `disparos.retorno_hora_padrao` (10h) daquele dia, hora local;
    antes (até 02/11/2026) caía à meia-noite. Data com hora segue como está."""
    dt = _dt(v)
    so_data = isinstance(v, date) and not isinstance(v, datetime) or (isinstance(v, str) and "T" not in v and " " not in v)
    if so_data:
        hora = int(config.parametros()["disparos"].get("retorno_hora_padrao", 10))
        dt = dt.replace(hour=hora, minute=0)
    return dt


def numeros_teste(db) -> set:
    """Números internos de teste (lista do painel, config/atendimento)."""
    cfg = db.collection("config").document("atendimento").get().to_dict() or {}
    return {str(n) for n in (cfg.get("numeros_teste") or [])}


def e_teste(doc: dict, numeros: set) -> bool:
    """27/10/2026 (decisão da clínica): números de teste não participam de nenhuma fila nem esteira, não recebem nenhum disparo.
    Vale para lead (`celular`) e conversa (`contato`), marcados como teste ou com número da lista do painel."""
    return bool(doc.get("teste")) or str(doc.get("celular") or doc.get("contato") or "") in numeros


def _completar_resposta_e_entrega(db, lead: dict) -> None:
    """Lead já abordado e ainda na esteira: traz da conversa se ele escreveu algo (o gateway grava `primeira_msg_lead_em` em
    qualquer mensagem, inclusive resposta automática) e o código de erro da entrega do último template (`status_entrega`)."""
    if int(lead.get("passo") or 0) <= 0 or lead.get("status_ia") not in ("Template enviado (1°)", "Template enviado (2°)", "Template enviado (3°)"):
        return
    if lead.get("conversa_id"):
        conv = db.collection("conversas").document(lead["conversa_id"]).get().to_dict() or {}
        lead["respondeu_em"] = conv.get("primeira_msg_lead_em") or conv.get("ultima_msg_lead_em")
    wamid = ((lead.get("templates_enviados") or [{}])[-1] or {}).get("wamid")
    if wamid:
        st = db.collection("status_entrega").document(wamid).get().to_dict() or {}
        if st.get("status") == "failed":
            lead["falha_entrega"] = next((e.get("code") for e in (st.get("erros") or []) if isinstance(e, dict)), None)


TRAVA_MINUTOS = 35   # uma rodada de 100 envios leva ~17 min; a trava expira sozinha se o processo morrer


def trava_livre(doc: Optional[dict], agora: datetime) -> bool:
    """A trava está livre se não existe ou se já expirou."""
    ate = (doc or {}).get("ate")
    return not ate or _dt(ate) <= agora


def _travar(db, agora: datetime) -> bool:
    """08/11/2026: o Cloud Scheduler disparou a rodada das 9h duas vezes (9h00 e 9h01) e, com 3 instâncias no jobs, as duas
    rodaram em paralelo: 191 envios num dia de limite 100. Só uma rodada por vez (transação no Firestore)."""
    ref = db.collection("config").document("disparos_trava")

    @firestore.transactional
    def _tentar(tx):
        atual = ref.get(transaction=tx).to_dict()
        if not trava_livre(atual, agora):
            return False
        tx.set(ref, {"ate": agora + timedelta(minutes=TRAVA_MINUTOS), "desde": agora})
        return True

    return bool(_tentar(db.transaction()))


def _destravar(db) -> None:
    db.collection("config").document("disparos_trava").set({"ate": None, "liberada_em": datetime.now(timezone.utc)}, merge=True)


def ja_recebeu_depois(fresco: Optional[dict], retrato: dict) -> bool:
    """O lead recebeu algum template depois do retrato tirado no início da rodada? (53 leads receberam o T1 em dobro em 08/11/2026)"""
    a, b = (fresco or {}).get("ultimo_template_em"), retrato.get("ultimo_template_em")
    if not a:
        return False
    return not b or _dt(a) > _dt(b)


def _enviados_hoje(db) -> int:
    hoje = datetime.now(FUSO).strftime("%Y-%m-%d")
    doc = db.collection("disparos_diarios").document(hoje).get().to_dict() or {}
    return int(doc.get("enviados", 0))


_TARDE: dict = {}


def _tarde_livre_hoje(ts: tisaude.TiSaude) -> bool:
    """Confere se há horário livre hoje à tarde; guarda o primeiro (hora + profissional) para o T5."""
    _TARDE.clear()
    try:
        hoje = date.today()
        for prof in ("dr_lucas", "dra_luciana"):
            for h in ts.buscar_horarios(prof, dias=1, a_partir_de=hoje):
                if h["data"] == hoje.isoformat() and int(h["hora"][:2]) >= 12:
                    _TARDE.update({"horario": h["hora"][:5].replace(":00", "h").replace(":", "h"),
                                   "profissional": config.profissional(prof)["profissional"]})
                    return True
    except Exception as e:
        log.warning("não conferiu tarde livre: %s", e)
    return False


def _extras_template(codigo: str, tarde: bool, lead: Optional[dict] = None) -> dict:
    if codigo == "T4":
        return {"mes": templates_texto.MESES[datetime.now(FUSO).month - 1]}
    if codigo == "T5":
        return dict(_TARDE)
    return {}


def templates_aprovados(mt) -> Optional[set]:
    """Nomes dos templates APPROVED na Meta; None se a consulta falhar (aí ninguém é bloqueado por isso)."""
    try:
        return {t["name"] for t in mt.templates() if str(t.get("status", "")).upper() == "APPROVED"}
    except Exception as e:  # noqa: BLE001
        log.warning("não consegui listar os templates na Meta (%s); seguindo sem a checagem", e)
        return None


def escolher_template(codigo: str, d: dict, aprovados: Optional[set]) -> Optional[str]:
    """Nome do template a enviar: o principal se aprovado (ou sem checagem), senão a reserva de `templates_reserva`; None se nenhum serve."""
    principal = d["templates"][codigo]
    if aprovados is None or principal in aprovados:
        return principal
    reserva = (d.get("templates_reserva") or {}).get(codigo)
    if reserva and reserva in aprovados:
        log.warning("template %s (%s) não está aprovado na Meta; usando a reserva %s", codigo, principal, reserva)
        return reserva
    log.warning("template %s (%s) não está aprovado na Meta e não há reserva aprovada; lead pulado", codigo, principal)
    return None


def rodar(dry_run: bool = False, forcar_horario: bool = False, limite: Optional[int] = None) -> dict:
    p = config.parametros()
    d = dict(p["disparos"])
    db = firestore.Client(project=config.PROJETO_GCP)
    d.update(db.collection("config").document("disparos").get().to_dict() or {})   # o painel sobrescreve ativo/limites
    resumo = {"dry_run": dry_run, "enviados": 0, "candidatos": 0, "pulados": 0, "erros": 0, "detalhe": []}
    if not d.get("ativo") and not dry_run:
        resumo["ignorado"] = "disparos.ativo = false"
        return resumo
    if not dentro_do_horario() and not forcar_horario:
        resumo["ignorado"] = "fora do horário de disparo"
        return resumo
    agora = datetime.now(timezone.utc)
    if not dry_run and not _travar(db, agora):
        resumo["ignorado"] = "outra rodada de disparos em andamento"
        return resumo
    try:
        return _rodar_travado(db, d, resumo, agora, dry_run, limite)
    finally:
        if not dry_run:
            _destravar(db)


def _rodar_travado(db, d: dict, resumo: dict, agora: datetime, dry_run: bool, limite: Optional[int]) -> dict:
    ja_hoje = _enviados_hoje(db)
    cota = min(int(d["limite_por_execucao"]), int(d["limite_diario"]) - ja_hoje)
    if limite is not None:
        cota = min(cota, limite)
    if cota <= 0:
        resumo["ignorado"] = f"limite diário atingido ({ja_hoje})"
        return resumo

    precisa_tarde = any(x.get("so_se_horario_livre_hoje_a_tarde") for x in d["passos"])
    tarde = _tarde_livre_hoje(tisaude.TiSaude()) if precisa_tarde and not dry_run else False
    mt = None if dry_run else meta.Meta()
    aprovados = None if dry_run else templates_aprovados(mt)   # 06/11/2026: T2 v3 em análise; se não estiver aprovado, sai a reserva (v2)
    ordem = firestore.Query.DESCENDING if d.get("priorizar", "mais_recentes") == "mais_recentes" else firestore.Query.ASCENDING
    consulta = db.collection("leads").where("elegivel", "==", True).where("opt_out", "==", False).order_by("lead_created_at", direction=ordem)
    teste = numeros_teste(db)

    # 07/11/2026: materializa a consulta ANTES do laço. Com o stream aberto durante os envios (4-12 s cada), o gRPC do Firestore
    # estourava o prazo (~5 min, '504 Deadline Exceeded') e a rodada morria no 34º envio com HTTP 500.
    docs = list(consulta.stream())
    for doc in docs:
        if resumo["enviados"] >= cota:
            break
        lead = doc.to_dict()
        if e_teste(lead, teste):   # 27/10/2026: número de teste não entra na esteira
            resumo["pulados"] += 1
            continue
        _completar_resposta_e_entrega(db, lead)
        dec = decidir(lead, agora, tarde)
        if not dec:
            resumo["pulados"] += 1
            continue
        resumo["candidatos"] += 1
        if dec.template is None:   # esteira encerrada para este lead: só muda o status, nada é enviado
            if not dry_run:
                db.collection("leads").document(doc.id).set({"status_ia": "Sem resposta (esteira encerrada)", "esteira_encerrada_em": agora}, merge=True)
            resumo["encerrados"] = resumo.get("encerrados", 0) + 1
            continue
        nome_tpl = escolher_template(dec.template, d, aprovados)
        if not nome_tpl:
            resumo["pulados"] += 1
            resumo["sem_template_aprovado"] = resumo.get("sem_template_aprovado", 0) + 1
            continue
        if dry_run:
            resumo["enviados"] += 1
            resumo["detalhe"].append({"lead": doc.id[-4:].rjust(len(doc.id), "*"), "template": dec.template, "motivo": dec.motivo})
            continue
        if ja_recebeu_depois(db.collection("leads").document(doc.id).get().to_dict(), lead):
            resumo["pulados"] += 1   # 08/11/2026: a lista é um retrato do início da rodada; outra rodada/pessoa pode ter enviado nesse meio-tempo
            resumo["ja_recebido"] = resumo.get("ja_recebido", 0) + 1
            continue
        extras = _extras_template(dec.template, tarde, lead)
        try:
            wamid = mt.enviar_template(lead["celular"], nome_tpl, templates_texto.parametros(dec.template, lead.get("primeiro_nome") or "", **extras),
                                       imagem_cabecalho=templates_texto.TEMPLATES[dec.template].get("imagem"))
        except Exception as e:
            resumo["erros"] += 1
            log.warning("falha ao enviar %s para lead: %s", dec.template, e)
            db.collection("leads").document(doc.id).set({"ultimo_erro_envio": str(e)[:300], "ultimo_erro_em": agora}, merge=True)
            continue
        _registrar_envio(db, doc.id, lead, dec, nome_tpl, wamid, datetime.now(timezone.utc), extras)   # 09/11/2026: hora real do envio, não a do início da rodada
        resumo["enviados"] += 1
        time.sleep(random.uniform(*d["intervalo_entre_envios_segundos"]))
    log.info("disparos: %s", resumo)
    return resumo


def _registrar_envio(db, lead_id: str, lead: dict, dec: Decisao, nome_tpl: str, wamid: str, agora: datetime, extras: dict) -> None:
    d = config.parametros()["disparos"]
    status = d["status_apos_template"][dec.template]
    conv_id = lead.get("conversa_id")
    conv_ref = db.collection("conversas").document(conv_id) if conv_id else None
    if not conv_ref or not (conv_ref.get().to_dict() or {}).get("aberta"):
        conv_ref = db.collection("conversas").document()
        conv_ref.set({"contato": lead["celular"], "nome": lead.get("nome"), "frente": "leads_perdidos", "modo": "ia",
                      "status": status, "aberta": True, "criado_em": agora, "origem": "disparo", "template_origem": dec.template,
                      "primeira_msg_celeste_em": agora,
                      "ciclo": next((x["ciclo"] for x in d["passos"] if x["template"] == dec.template), None)})
        conv_id = conv_ref.id
    db.collection("contatos").document(lead["celular"]).set(
        {"telefone": lead["celular"], "nome": lead.get("nome"), "origem": "leads_perdidos", "opt_out": False, "criado_em": agora}, merge=True)
    conv_ref.collection("mensagens").document(wamid).set({
        "direcao": "template", "tipo": "template", "template": nome_tpl, "codigo": dec.template,
        "texto": templates_texto.renderizar(dec.template, lead.get("primeiro_nome") or "", **extras),
        "recebido_em": agora, "gravado_em": firestore.SERVER_TIMESTAMP})
    conv_ref.set({"status": status, "ultimo_template_em": agora, "template_origem": dec.template,
                  "ultima": {"texto": f"[template {dec.template}] " + templates_texto.TEMPLATES[dec.template]["corpo"][:120], "direcao": "template", "tipo": "template", "em": agora}}, merge=True)
    db.collection("leads").document(lead_id).set({
        "status_ia": status, "passo": dec.novo_passo, "ciclos": dec.novo_ciclo, "ultimo_template_em": agora, "conversa_id": conv_id,
        "templates_enviados": firestore.ArrayUnion([{"codigo": dec.template, "template": nome_tpl, "em": agora, "wamid": wamid, "motivo": dec.motivo}]),
        "proximo_recontato_em": None}, merge=True)
    hoje = datetime.now(FUSO).strftime("%Y-%m-%d")
    db.collection("disparos_diarios").document(hoje).set(
        {"enviados": firestore.Increment(1), f"por_template.{dec.template}": firestore.Increment(1)}, merge=True)
