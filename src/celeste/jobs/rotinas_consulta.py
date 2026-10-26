# -*- coding: utf-8 -*-
"""Rotinas da consulta agendada pela Celeste (aprovado pela clínica em 26/10/2026).

Só conversas com status "Agendado" (consulta marcada pela própria Celeste no TI Saúde). Três toques, por template aprovado na Meta:
  C48  consulta_48_horas            2 dias antes, a partir de `hora_48h`; botões "Confirmar presença" / "Preciso remarcar"
  C24  consulta_confirmar_24_horas  véspera, a partir de `hora_vespera`, só para quem ainda não confirmou
  CHOJ consulta_hoje                manhã do dia, a partir de `hora_dia`, antes da hora da consulta
O botão "Confirmar presença" é tratado pelo orquestrador (status Confirmado no TI Saúde + agradecimento + vídeo do profissional);
"Preciso remarcar" vai para a Celeste reagendar pela conversa. Roda de hora em hora (Cloud Scheduler celeste-rotinas-consulta).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from google.cloud import firestore

from celeste.comum import config
from celeste.ferramentas import meta, tisaude

log = logging.getLogger(__name__)
FUSO = ZoneInfo(config.FUSO)
DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
STATUS_QUE_CANCELAM = {"cancelado", "desmarcado", "falta", "faltou", "atendido", "não compareceu"}

# corpo dos templates como estão na Meta (para o histórico da conversa e o painel); {1} nome, {2} dia, {3} hora
CORPOS = {
    "C48": "⏳ Olá, {1}!\n\nTemos uma consulta agendada para {2}, às {3}.\n\nComo este horário foi reservado exclusivamente para você, "
           "pedimos, por gentileza, que confirme a sua presença ou solicite o reagendamento pelos botões abaixo.\n\nAgradecemos pela compreensão. 💙"
           "\n\n[botões: Confirmar presença · Preciso remarcar]",
    "C24": "⏰ Olá, {1}!\n\nJá deixamos tudo preparado para te receber dia {2} e reservamos esse horário especialmente para a sua avaliação."
           "\n\nPassando para te lembrar que te esperamos às {3}, combinado?\n\n[botões: Confirmar presença · Preciso remarcar]",
    "CHOJ": "Olá, {1}!\n\nTudo preparado para te receber HOJE às {2}.\n\nPor gentileza, chegue com 15 minutos de antecedência! "
            "Estamos na Av. República do Líbano, 886, Moema, com valet cortesia.",
}


def _cfg() -> dict:
    return config.parametros().get("rotinas_consulta") or {}


def formatar_dia(d: date) -> str:
    return f"{DIAS[d.weekday()]}, {d.strftime('%d/%m')}"


def formatar_hora(h: str) -> str:
    """'14:00' → '14h'; '14:30' → '14h30'."""
    h = (h or "").strip()[:5]
    if ":" not in h:
        return h
    hh, mm = h.split(":", 1)
    return f"{int(hh)}h" if mm == "00" else f"{int(hh)}h{mm}"


def _data_consulta(conv: dict) -> Optional[date]:
    ag = conv.get("agendamento") or {}
    try:
        return date.fromisoformat(str(ag.get("data"))[:10])
    except (TypeError, ValueError):
        return None


def decidir(conv: dict, agora: datetime) -> Optional[str]:
    """Qual toque esta conversa recebe agora: 'C48' | 'C24' | 'CHOJ' | None."""
    c = _cfg()
    if conv.get("status") != "Agendado" or conv.get("opt_out") or conv.get("modo", "ia") != "ia":
        return None
    ag = conv.get("agendamento") or {}
    data = _data_consulta(conv)
    if not data or not ag.get("hora"):
        return None
    if str(ag.get("status") or "").strip().lower() in STATUS_QUE_CANCELAM:
        return None
    rot = conv.get("rotinas_consulta") or {}
    agora = agora.astimezone(FUSO)
    hoje = agora.date()
    agendado_em = conv.get("agendado_em")
    agendado_hoje = bool(agendado_em) and agendado_em.astimezone(FUSO).date() == hoje   # acabou de marcar: não leva lembrete no mesmo dia
    dias = (data - hoje).days
    if dias == 2 and agora.hour >= int(c.get("hora_48h", 10)) and not rot.get("C48_em") and not agendado_hoje:
        return "C48"
    if dias == 1 and agora.hour >= int(c.get("hora_vespera", 10)) and not rot.get("C24_em") and not rot.get("confirmado_em") and not agendado_hoje:
        return "C24"
    if dias == 0 and agora.hour >= int(c.get("hora_dia", 7)) and not rot.get("CHOJ_em") and not agendado_hoje:
        try:
            hh, mm = str(ag["hora"])[:5].split(":")
            if (agora.hour, agora.minute) >= (int(hh), int(mm)):
                return None   # consulta já passou
        except ValueError:
            pass
        return "CHOJ"
    return None


def parametros(codigo: str, conv: dict) -> list[str]:
    ag = conv.get("agendamento") or {}
    nome = ((conv.get("nome") or "").strip().split() or ["tudo bem"])[0].title()
    data = _data_consulta(conv)
    hora = formatar_hora(ag.get("hora", ""))
    if codigo == "CHOJ":
        return [nome, hora]
    return [nome, formatar_dia(data) if data else "", hora]


def renderizar(codigo: str, conv: dict) -> str:
    corpo = CORPOS[codigo]
    for i, v in enumerate(parametros(codigo, conv), start=1):
        corpo = corpo.replace("{" + str(i) + "}", v)
    return corpo


def _status_no_tisaude(ts, conv: dict) -> Optional[str]:
    """Estado real da consulta (só para conversas que gravam de verdade). None = não consultado."""
    ida = conv.get("id_agendamento_tisaude")
    if not ida or conv.get("tisaude_simulado"):
        return None
    try:
        d = ts.detalhe_agendamento(int(ida))
        return tisaude.STATUS.get(d.get("status"), str(d.get("status")))
    except Exception as e:   # noqa: BLE001
        log.warning("rotinas: não consegui ler a consulta %s no TI Saúde: %s", ida, e)
        return None


def rodar(dry_run: bool = False, forcar_horario: bool = False) -> dict:
    c = _cfg()
    p = config.parametros()
    nomes = {cod: v["nome"] for cod, v in (p.get("templates_consulta") or {}).items()}
    resumo = {"enviados": 0, "pulados": 0, "cancelados": 0, "erros": 0, "dry_run": dry_run, "detalhe": []}
    if not c.get("ativo", True):
        resumo["ignorado"] = "rotinas_consulta.ativo = false"
        return resumo
    db = firestore.Client(project=config.PROJETO_GCP)
    agora = datetime.now(timezone.utc)
    mt = None if dry_run else meta.Meta()
    ts = None
    for doc in db.collection("conversas").where("status", "==", "Agendado").stream():
        conv = doc.to_dict()
        cod = decidir(conv, agora)
        if not cod:
            resumo["pulados"] += 1
            continue
        # a consulta ainda existe no TI Saúde? (quem cancelou pela recepção não recebe lembrete)
        ts = ts or (None if dry_run else tisaude.TiSaude())
        st = _status_no_tisaude(ts, conv) if ts else None
        if st and st.strip().lower() in STATUS_QUE_CANCELAM:
            ag = dict(conv.get("agendamento") or {}); ag["status"] = st
            doc.reference.set({"agendamento": ag}, merge=True)
            resumo["cancelados"] += 1
            continue
        resumo["detalhe"].append({"conversa": doc.id, "nome": conv.get("nome"), "codigo": cod, "consulta": (conv.get("agendamento") or {}).get("data")})
        if dry_run:
            resumo["enviados"] += 1
            continue
        try:
            wamid = mt.enviar_template(conv["contato"], nomes[cod], parametros(cod, conv))
        except Exception as e:   # noqa: BLE001
            resumo["erros"] += 1
            log.warning("rotinas: falha ao enviar %s para a conversa %s: %s", cod, doc.id, e)
            continue
        texto = renderizar(cod, conv)
        doc.reference.collection("mensagens").document(wamid).set({
            "direcao": "template", "tipo": "template", "template": nomes[cod], "codigo": cod, "texto": texto,
            "recebido_em": agora, "gravado_em": firestore.SERVER_TIMESTAMP})
        rot = dict(conv.get("rotinas_consulta") or {}); rot[f"{cod}_em"] = agora
        doc.reference.set({"rotinas_consulta": rot, "ultimo_template_em": agora, "ultima_msg_celeste_em": agora,
                           "ultima": {"texto": f"[template {cod}] " + texto[:120], "direcao": "template", "tipo": "template", "em": agora}}, merge=True)
        resumo["enviados"] += 1
    log.info("rotinas de consulta: %s", resumo)
    return resumo
