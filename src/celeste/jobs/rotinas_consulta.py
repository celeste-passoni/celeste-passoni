# -*- coding: utf-8 -*-
"""Rotinas da consulta agendada pela Celeste (aprovado pela clínica em 26/10/2026; por consulta desde 27/10/2026).

Só conversas com status "Agendado". Cada consulta ativa da conversa (lista `consultas`, ver comum/consultas.py) recebe
os próprios toques, por template aprovado na Meta:
  C48  consulta_48_horas            2 dias antes, a partir de `hora_48h`; botões "Confirmar presença" / "Preciso remarcar"
  C24  consulta_confirmar_24_horas  véspera, a partir de `hora_vespera`, só se esta consulta ainda não foi confirmada
  CHOJ consulta_hoje                manhã do dia, a partir de `hora_dia`, antes da hora da consulta
Quando a consulta é de outra pessoa (o filho de quem está no WhatsApp), o nome do paciente entra junto da data.
A mensagem gravada guarda o id_agendamento: o botão tocado em resposta a ela vale para aquela consulta.
Roda de hora em hora (Cloud Scheduler celeste-rotinas-consulta).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from google.cloud import firestore

from celeste.comum import config
from celeste.comum import consultas as cons
from celeste.comum.consultas import formatar_dia, formatar_hora   # noqa: F401  (reexportadas: o orquestrador importa daqui)
from celeste.ferramentas import meta, tisaude

log = logging.getLogger(__name__)
FUSO = ZoneInfo(config.FUSO)
STATUS_QUE_CANCELAM = cons.INATIVOS

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


def _data(c: dict) -> Optional[date]:
    try:
        return date.fromisoformat(str(c.get("data"))[:10])
    except (TypeError, ValueError):
        return None


def decidir(c: dict, agora: datetime) -> Optional[str]:
    """Qual toque ESTA consulta recebe agora: 'C48' | 'C24' | 'CHOJ' | None."""
    cfg = _cfg()
    data = _data(c)
    if not data or not c.get("hora") or not cons.ativa(c):
        return None
    rot = c.get("rotinas") or {}
    agora = agora.astimezone(FUSO)
    hoje = agora.date()
    agendado_em = c.get("agendado_em")
    agendado_hoje = bool(agendado_em) and agendado_em.astimezone(FUSO).date() == hoje   # acabou de marcar: não leva lembrete no mesmo dia
    dias = (data - hoje).days
    if dias == 2 and agora.hour >= int(cfg.get("hora_48h", 10)) and not rot.get("C48_em") and not agendado_hoje:
        return "C48"
    if dias == 1 and agora.hour >= int(cfg.get("hora_vespera", 10)) and not rot.get("C24_em") and not rot.get("confirmado_em") and not agendado_hoje:
        return "C24"
    if dias == 0 and agora.hour >= int(cfg.get("hora_dia", 7)) and not rot.get("CHOJ_em") and not agendado_hoje:
        try:
            hh, mm = str(c["hora"])[:5].split(":")
            if (agora.hour, agora.minute) >= (int(hh), int(mm)):
                return None   # consulta já passou
        except ValueError:
            pass
        return "CHOJ"
    return None


def pendentes(conv: dict, agora: datetime) -> list[tuple[dict, str]]:
    """(consulta, toque) que esta conversa deve receber agora."""
    if conv.get("status") != "Agendado" or conv.get("opt_out") or conv.get("modo", "ia") != "ia":
        return []
    saida = []
    for c in cons.ativas(conv):
        cod = decidir(c, agora)
        if cod:
            saida.append((c, cod))
    return saida


def parametros(codigo: str, conv: dict, c: dict) -> list[str]:
    nome = cons.primeiro_nome(conv.get("nome")) or "tudo bem"
    data = _data(c)
    hora = formatar_hora(c.get("hora", ""))
    dia = formatar_dia(data) if data else ""
    if cons.de_outra_pessoa(conv, c):   # 27/10/2026: consulta do filho etc.: o nome do paciente vai junto, para o lead saber de qual se trata
        pac = cons.primeiro_nome(c.get("paciente_nome"))
        dia, hora = f"{dia} ({pac})", (f"{hora} ({pac})" if codigo == "CHOJ" else hora)
    if codigo == "CHOJ":
        return [nome, hora]
    return [nome, dia, hora]


def renderizar(codigo: str, conv: dict, c: dict) -> str:
    corpo = CORPOS[codigo]
    for i, v in enumerate(parametros(codigo, conv, c), start=1):
        corpo = corpo.replace("{" + str(i) + "}", v)
    return corpo


def _status_no_tisaude(ts, conv: dict, c: dict) -> Optional[str]:
    """Estado real da consulta (só para conversas que gravam de verdade). None = não consultado."""
    if conv.get("tisaude_simulado") or not c.get("id_agendamento"):
        return None
    try:
        d = ts.detalhe_agendamento(int(c["id_agendamento"]))
        if d.get("deletado") or d.get("status") == -2:
            return "Desmarcado"
        return tisaude.STATUS.get(d.get("status"), str(d.get("status")))
    except Exception as e:   # noqa: BLE001
        log.warning("rotinas: não consegui ler a consulta %s no TI Saúde: %s", c.get("id_agendamento"), e)
        return None


def rodar(dry_run: bool = False, forcar_horario: bool = False) -> dict:
    cfg = _cfg()
    p = config.parametros()
    nomes = {cod: v["nome"] for cod, v in (p.get("templates_consulta") or {}).items()}
    resumo = {"enviados": 0, "pulados": 0, "cancelados": 0, "erros": 0, "dry_run": dry_run, "detalhe": []}
    if not cfg.get("ativo", True):
        resumo["ignorado"] = "rotinas_consulta.ativo = false"
        return resumo
    db = firestore.Client(project=config.PROJETO_GCP)
    agora = datetime.now(timezone.utc)
    mt = None if dry_run else meta.Meta()
    ts = None
    for doc in db.collection("conversas").where("status", "==", "Agendado").stream():
        conv = doc.to_dict()
        fila = pendentes(conv, agora)
        if not fila:
            resumo["pulados"] += 1
            continue
        cs = cons.lista(conv)
        mudou, ultima = False, None
        for c, cod in fila:
            ts = ts or (None if dry_run else tisaude.TiSaude())
            st = _status_no_tisaude(ts, conv, c) if ts else None
            if st and st.strip().lower() in STATUS_QUE_CANCELAM:   # a recepção cancelou ou já atendeu: sem lembrete
                cs = cons.substituir(cs, dict(c, status=st)); mudou = True
                resumo["cancelados"] += 1
                continue
            resumo["detalhe"].append({"conversa": doc.id, "consulta": c.get("id_agendamento"), "paciente": cons.primeiro_nome(c.get("paciente_nome")),
                                      "codigo": cod, "data": c.get("data")})
            if dry_run:
                resumo["enviados"] += 1
                continue
            try:
                wamid = mt.enviar_template(conv["contato"], nomes[cod], parametros(cod, conv, c))
            except Exception as e:   # noqa: BLE001
                resumo["erros"] += 1
                log.warning("rotinas: falha ao enviar %s (conversa %s, consulta %s): %s", cod, doc.id, c.get("id_agendamento"), e)
                continue
            texto = renderizar(cod, conv, c)
            doc.reference.collection("mensagens").document(wamid).set({
                "direcao": "template", "tipo": "template", "template": nomes[cod], "codigo": cod, "texto": texto,
                "id_agendamento": c.get("id_agendamento"), "consulta_rotulo": cons.rotulo(c),
                "recebido_em": agora, "gravado_em": firestore.SERVER_TIMESTAMP})
            rot = dict(c.get("rotinas") or {}); rot[f"{cod}_em"] = agora
            cs = cons.substituir(cs, dict(c, rotinas=rot)); mudou = True
            ultima = {"texto": f"[template {cod}] " + texto[:120], "direcao": "template", "tipo": "template", "em": agora}
            resumo["enviados"] += 1
        if mudou and not dry_run:
            campos = cons.campos(cs)
            if ultima:
                campos.update({"ultimo_template_em": agora, "ultima_msg_celeste_em": agora, "ultima": ultima})
            doc.reference.set(campos, merge=True)
    log.info("rotinas de consulta: %s", resumo)
    return resumo
