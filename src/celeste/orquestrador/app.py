# -*- coding: utf-8 -*-
"""Orquestrador — a Celeste em si.

Recebe do Cloud Tasks "responda a conversa X (versão V)", e:
  1. descarta tarefas obsoletas (chegou mensagem nova depois → outra tarefa virá);
  2. monta o histórico (texto, transcrição de áudio, imagens) a partir do Firestore;
  3. chama o Claude com as ferramentas (TI Saúde, vídeos, encaminhar, opt-out);
  4. respeita o ritmo humano e envia os balões pela Meta;
  5. registra tudo (mensagens, chamadas, custo) para o painel e o espelho no BigQuery.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from google.cloud import firestore, storage
from pydantic import BaseModel

from celeste.comum import config
from celeste.ferramentas import meta, tisaude, transcricao
from celeste.ferramentas.tisaude_simulado import TiSaudeSimulado
from celeste.orquestrador import abertura, ferramentas_ia, lembretes_texto, motor, referencias

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("orquestrador")
app = FastAPI(title="Celeste · Orquestrador")

db = firestore.Client(project=config.PROJETO_GCP)
BUCKET = os.environ.get("BUCKET_MIDIA", f"celeste-midia-{config.PROJETO_GCP}")
SIMULAR_DELAY = os.environ.get("SIMULAR_DELAY", "1") == "1"   # desligar em testes locais
FUSO = ZoneInfo(config.FUSO)
FRENTES_IA = {f for f, cfg in config.parametros()["frentes"].items() if cfg.get("ativa")}   # hoje: leads_perdidos

_motor: motor.Motor | None = None
_meta: meta.Meta | None = None
_ts: tisaude.TiSaude | None = None


def _svc():
    global _motor, _meta, _ts
    _motor = _motor or motor.Motor()
    _meta = _meta or meta.Meta()
    _ts = _ts or tisaude.TiSaude()
    return _motor, _meta, _ts


class Pedido(BaseModel):
    conversa_id: str
    versao: str


@app.get("/status")  # /healthz é interceptado pelo front-end do Google no Cloud Run
def healthz():
    return {"ok": True, "servico": "orquestrador"}


@app.post("/responder")
def responder(p: Pedido):
    ref = db.collection("conversas").document(p.conversa_id)
    conv = ref.get().to_dict()
    if not conv:
        raise HTTPException(404, "conversa não existe")
    if conv.get("debounce_versao") != p.versao:
        return {"ok": True, "ignorado": "tarefa obsoleta"}
    if not conv.get("aberta", True) or conv.get("modo", "ia") != "ia" or conv.get("opt_out"):
        return {"ok": True, "ignorado": "conversa fechada/pausada"}
    if conv.get("frente") not in FRENTES_IA and not _e_numero_teste(conv.get("contato", "")):
        return _orientar_recepcao(ref, conv)   # sem frente ou campanha da recepção: a IA não atende
    if not _pode_responder(conv.get("contato", "")):
        if _cfg_atendimento().get("modo", "teste") == "producao":   # 25/10/2026: lead da base ainda não disparado → mesmo caminho de quem não tem frente
            return _orientar_recepcao(ref, conv)
        ref.set({"pendente_resposta": False, "modo_teste_ignorado": True}, merge=True)
        log.info("modo teste: número fora da lista; mensagem gravada sem resposta (conversa %s)", p.conversa_id)
        return {"ok": True, "ignorado": "modo teste: número não autorizado"}
    if _custo_hoje() >= float(config.parametros()["modelos"]["cap_diario_usd"]):
        ref.set({"pausada_por_custo": True}, merge=True)
        log.error("cap diário de custo atingido; conversa %s pausada", p.conversa_id)
        return {"ok": False, "ignorado": "cap diário de custo"}
    conv["id"] = p.conversa_id
    inicio = time.time()
    mot, mt, ts = _svc()

    historico, ultimo_wamid = _historico(ref, mt)
    if not historico or historico[-1]["role"] != "user":
        return {"ok": True, "ignorado": "nada novo do lead"}
    if ultimo_wamid:
        try:
            mt.marcar_lida(ultimo_wamid)
        except Exception:
            pass
    conv["id"] = p.conversa_id
    acao = _acao_botao_t1(ref, ultimo_wamid)
    if acao == "agora_nao":
        return _responder_agora_nao(ref, conv, mt)
    if acao in ("sair", "encerrar"):
        return _responder_sair(ref, conv, mt, acao)

    if _acao_botao_consulta(ref, ultimo_wamid) == "confirmar_presenca":   # 26/10/2026: botão do lembrete da consulta, sem modelo
        return _responder_confirmar_presenca(ref, conv, mt)

    # abertura sem modelo (15/10/2026): conversa nova, não vinda de template, cuja 1ª mensagem é só um cumprimento
    conteudo = historico[-1]["content"]   # string (só texto) ou lista de blocos (com mídia)
    texto_lead = conteudo if isinstance(conteudo, str) else " ".join(b.get("text", "") for b in conteudo if isinstance(b, dict) and b.get("type") == "text")
    if len(historico) == 1 and not conv.get("template_origem") and conv.get("origem") != "disparo" and abertura.e_saudacao_solta(texto_lead):
        return _responder_abertura(ref, conv, mt, texto_lead)
    log.info("abertura fixa não aplicada: turnos=%d origem=%r template_origem=%r saudacao=%s texto=%r", len(historico), conv.get("origem"),
             conv.get("template_origem"), abertura.e_saudacao_solta(texto_lead), texto_lead[:60])

    if conv.get("teste") or _e_numero_teste(conv.get("contato", "")):
        escrita_real = _escreve_no_tisaude(conv.get("contato", ""))
        if not escrita_real:
            ts = TiSaudeSimulado()                  # lê a agenda real, não grava nada
        # normaliza a conversa de teste (pode ter nascido antes do cadastro do número): frente da IA e status conversável
        norm = {"teste": True, "tisaude_simulado": not escrita_real}
        if conv.get("frente") not in FRENTES_IA:
            norm["frente"] = "leads_perdidos"
        if conv.get("status") in ("Orientado à recepção", "Encaminhado à recepção", None):
            norm["status"] = "Em conversa"
        conv.update(norm)
        ref.set(norm, merge=True)
    videos_pendentes: list[str] = []   # o vídeo vai DEPOIS dos balões de texto (ordem das atendentes); a ferramenta só agenda
    imagens_pendentes: list[str] = []  # idem para as fotos de antes e depois (chave = doença)
    ctx = ferramentas_ia.Contexto(
        conversa=conv, telefone=conv["contato"], tisaude=ts, viacep=transcricao.viacep,
        enviar_video=lambda v: (videos_pendentes.append(v), "adiado-para-depois-dos-baloes")[1],
        enviar_imagem=lambda d: (imagens_pendentes.append(d), "adiado-para-depois-dos-baloes")[1],
        avisar_recepcao=lambda motivo, resumo: _avisar_recepcao(mt, conv, motivo, resumo),
        atualizar=lambda campos: (conv.update(campos), ref.set(campos, merge=True)),
    )
    frente = conv.get("frente") or "leads_perdidos"
    if frente not in ("leads_perdidos",):
        frente = "leads_perdidos"  # única frente ativa no piloto
    _pre_verificar_paciente(ref, conv, ts)   # consulta o TI Saúde pelo código, poupando uma chamada do modelo
    res = mot.responder(frente, conv, historico, ctx)
    _registrar_chamada(p.conversa_id, res, time.time() - inicio)
    if isinstance(ts, TiSaudeSimulado) and ts.simulados:
        ref.set({"simulacoes_tisaude": firestore.ArrayUnion(ts.simulados)}, merge=True)
    if res.refusal:
        ref.set({"revisar": True, "revisar_motivo": "modelo recusou responder"}, merge=True)
        return {"ok": True, "enviado": 0, "refusal": True}

    # ritmo humano: espera antes do 1º balão, DESCONTANDO o que a geração já levou (14/10: a clínica achou lento;
    # a geração sozinha leva 5–30 s, então na prática a espera extra só existe quando o modelo respondeu muito rápido)
    if SIMULAR_DELAY:
        time.sleep(max(0.0, motor.delay_humano(fora_horario=not _horario_comercial()) - (time.time() - inicio)))
    if ref.get().to_dict().get("debounce_versao") != p.versao:
        log.info("mensagem nova chegou durante a geração; resposta descartada (conversa %s)", p.conversa_id)
        if videos_pendentes:   # o vídeo não foi enviado: desfaz a marcação para a próxima resposta poder mandá-lo
            ref.set({"videos_enviados": firestore.ArrayRemove(videos_pendentes)}, merge=True)
        if imagens_pendentes:
            ref.set({"fotos_enviadas": firestore.ArrayRemove([d.split(":", 2)[2] for d in imagens_pendentes])}, merge=True)
        return {"ok": True, "ignorado": "regerar"}

    # Regra da clínica (15/10/2026): no máximo 3 envios seguidos, contando fotos e vídeos. Com mídia, a ordem é
    # 1º balão (anuncia) → mídia → resto do texto. Sem mídia: até 3 balões.
    baloes = [b for b in (referencias.resolver(b) for b in res.baloes) if b]
    n_midia = len(videos_pendentes) + len(imagens_pendentes)
    max_texto = max(1, 3 - n_midia)
    if len(baloes) > max_texto:
        baloes = baloes[:max_texto - 1] + ["\n\n".join(baloes[max_texto - 1:])]
    baloes = motor.limitar_emojis(baloes)                              # 15/10/2026: no máximo 1 emoji por resposta
    enviados = 0

    def _balao(texto: str, pausa: bool) -> None:
        nonlocal enviados
        if pausa and SIMULAR_DELAY:
            time.sleep(min(2.0, 0.5 + len(texto) / 100))  # "digitando" proporcional ao tamanho (teto 2 s)
        wamid = mt.enviar_texto(conv["contato"], texto)
        ref.collection("mensagens").document(wamid).set({
            "direcao": "celeste", "tipo": "text", "texto": texto, "modelo": res.modelo,
            "recebido_em": datetime.now(timezone.utc), "gravado_em": firestore.SERVER_TIMESTAMP})
        enviados += 1

    def _midia() -> None:
        nonlocal enviados
        for v in videos_pendentes:
            if SIMULAR_DELAY:
                time.sleep(2.0)
            try:
                _enviar_video(mt, ref, conv, v); enviados += 1
            except Exception as e:
                log.warning("vídeo %s não enviado: %s", v, e)
        for d in imagens_pendentes:
            if SIMULAR_DELAY:
                time.sleep(1.5)
            try:
                grupo, slug, arquivo = d.split(":", 2)
                enviados += _enviar_foto(mt, ref, conv, grupo, slug, arquivo)
            except Exception as e:
                log.warning("antes e depois %s não enviado: %s", d, e)

    if baloes:
        _balao(baloes[0], False)
    _midia()
    for texto in baloes[1:]:
        _balao(texto, True)
    if conv.get("status") == "Encaminhado à recepção" and ctx.encerrar:
        rec = config.parametros()["ia"]["recepcao"]
        try:
            wamid = mt.enviar_botao_url(conv["contato"], rec["botao_texto"], rec["botao_rotulo"], rec["link_wa"])
            ref.collection("mensagens").document(wamid).set({
                "direcao": "celeste", "tipo": "interactive", "texto": f"{rec['botao_texto']}\n[botão: {rec['botao_rotulo']} → {rec['link_wa']}]",
                "recebido_em": datetime.now(timezone.utc), "gravado_em": firestore.SERVER_TIMESTAMP})
            enviados += 1
        except Exception as e:
            log.warning("botão da recepção não enviado: %s", e)
    if enviados and not conv.get("primeira_msg_celeste_em"):
        ref.set({"primeira_msg_celeste_em": firestore.SERVER_TIMESTAMP}, merge=True)
    if res.baloes:
        ref.set({"ultima": {"texto": res.baloes[-1][:160], "direcao": "celeste", "tipo": "text", "em": datetime.now(timezone.utc)}}, merge=True)
    ref.set({"pendente_resposta": False, "ultima_msg_celeste_em": firestore.SERVER_TIMESTAMP,
             "total_msgs_celeste": firestore.Increment(enviados), "custo_usd": firestore.Increment(res.custo_usd),
             "aberta": conv.get("aberta", True) and not ctx.encerrar}, merge=True)
    _espelhar_lead(conv)
    return {"ok": True, "enviado": enviados, "modelo": res.modelo, "custo_usd": round(res.custo_usd, 5)}


def _cfg_atendimento() -> dict:
    cfg = dict(config.parametros()["ia"])
    cfg.update(db.collection("config").document("atendimento").get().to_dict() or {})
    return cfg


def _e_numero_teste(contato: str) -> bool:
    return contato in {str(n) for n in (_cfg_atendimento().get("numeros_teste") or [])}


def _escreve_no_tisaude(contato: str) -> bool:
    """Número de teste autorizado a agendar DE VERDADE no TI Saúde (lista `numeros_teste_escrita_real`); os demais testes só simulam."""
    return contato in {str(n) for n in (_cfg_atendimento().get("numeros_teste_escrita_real") or [])}


class PedidoModo(BaseModel):
    conversa_id: str
    modo: str          # "humano" | "ia"


@app.post("/aquecer-cache")
def aquecer_cache():
    """Keep-alive do cache do prompt fixo (chamado pelo job celeste-aquecer-cache a cada 50 min)."""
    if not config.parametros()["modelos"].get("aquecer_cache", True):
        return {"ok": True, "ignorado": "modelos.aquecer_cache = false"}
    mot, _, _ = _svc()
    saida = []
    for frente in FRENTES_IA:
        try:
            r = mot.aquecer(frente)
            saida.append(r)
            db.collection("custos_diarios").document(datetime.now(ZoneInfo(config.FUSO)).strftime("%Y-%m-%d")).set(
                {"aquecer_cache_usd": firestore.Increment(r["custo_usd"]), "aquecer_cache_vezes": firestore.Increment(1)}, merge=True)
        except Exception as e:
            log.warning("aquecer cache (%s) falhou: %s", frente, e)
            saida.append({"frente": frente, "erro": str(e)[:200]})
    log.info("aquecer cache: %s", saida)
    return {"ok": True, "resultado": saida}


@app.post("/modo")
def mudar_modo(p: PedidoModo):
    """'humano' pausa a Celeste nesta conversa (a equipe responde pelo painel); 'ia' devolve para ela."""
    if p.modo not in ("humano", "ia"):
        raise HTTPException(400, "modo inválido")
    ref = db.collection("conversas").document(p.conversa_id)
    if not ref.get().exists:
        raise HTTPException(404, "conversa não existe")
    ref.set({"modo": p.modo, "modo_alterado_em": firestore.SERVER_TIMESTAMP, "aberta": True}, merge=True)
    return {"ok": True, "modo": p.modo}


class PedidoEnviar(BaseModel):
    conversa_id: str
    texto: str
    autor: str = "equipe"


@app.post("/enviar")
def enviar_humano(p: PedidoEnviar):
    """Texto livre enviado por uma pessoa da equipe (conversa em modo humano; só dentro da janela de 24 h do WhatsApp)."""
    texto = (p.texto or "").strip()
    if not texto:
        raise HTTPException(400, "texto vazio")
    ref = db.collection("conversas").document(p.conversa_id)
    conv = ref.get().to_dict()
    if not conv:
        raise HTTPException(404, "conversa não existe")
    if conv.get("modo") != "humano":
        raise HTTPException(400, "libere a conversa para humano antes de enviar")
    _, mt, _ = _svc()
    try:
        wamid = mt.enviar_texto(conv["contato"], texto)
    except Exception as e:
        fora = "131047" in str(e)
        raise HTTPException(400, "fora da janela de 24 h: a pessoa precisa escrever de novo antes" if fora else f"falha ao enviar: {str(e)[:160]}")
    ref.collection("mensagens").document(wamid).set({
        "direcao": "humano", "tipo": "text", "texto": texto, "autor": p.autor,
        "recebido_em": datetime.now(timezone.utc), "gravado_em": firestore.SERVER_TIMESTAMP})
    ref.set({"ultima": {"texto": texto[:160], "direcao": "humano", "tipo": "text", "em": datetime.now(timezone.utc)},
             "ultima_msg_humano_em": firestore.SERVER_TIMESTAMP, "pendente_resposta": False}, merge=True)
    return {"ok": True, "wamid": wamid}


class PedidoLembrete(BaseModel):
    conversa_id: str


@app.post("/lembrete")
def lembrete(p: PedidoLembrete):
    """Retomada no mesmo dia (chamada pelo job de lembretes): texto fixo por etapa, como as atendentes fazem. Sem modelo."""
    ref = db.collection("conversas").document(p.conversa_id)
    conv = ref.get().to_dict()
    if not conv:
        raise HTTPException(404, "conversa não existe")
    if not conv.get("aberta") or conv.get("modo", "ia") != "ia" or conv.get("opt_out"):
        raise HTTPException(400, "conversa fechada, em modo humano ou opt-out")
    if conv.get("frente") not in FRENTES_IA or not _pode_responder(conv.get("contato", "")):
        raise HTTPException(400, "fora do modo de atendimento atual (lembrete só para quem a Celeste pode responder)")
    if not (conv.get("primeira_msg_celeste_em") or conv.get("ultimo_template_em")):
        raise HTTPException(400, "a Celeste ainda não conversou nesta conversa")
    if (conv.get("ultima") or {}).get("direcao") not in ("celeste", "template"):
        raise HTTPException(400, "a última mensagem não é da Celeste")
    n = int(conv.get("lembretes_enviados") or 0) + 1
    texto = lembretes_texto.texto_lembrete(conv, n)
    _, mt, _ = _svc()
    wamid = mt.enviar_texto(conv["contato"], texto)
    agora = datetime.now(timezone.utc)
    ref.collection("mensagens").document(wamid).set({
        "direcao": "celeste", "tipo": "text", "texto": texto, "modelo": "script", "lembrete": n,
        "recebido_em": agora, "gravado_em": firestore.SERVER_TIMESTAMP})
    ref.set({"lembretes_enviados": n, "ultimo_lembrete_em": agora,
             "ultima": {"texto": texto[:160], "direcao": "celeste", "tipo": "text", "em": agora},
             "ultima_msg_celeste_em": firestore.SERVER_TIMESTAMP}, merge=True)
    log.info("lembrete %s (%s) enviado à conversa %s", n, lembretes_texto.etapa(conv), p.conversa_id)
    return {"ok": True, "enviado": 1, "lembrete": n, "etapa": lembretes_texto.etapa(conv), "custo_usd": 0.0}


class PedidoAviso(BaseModel):
    conversa_id: str


@app.post("/aviso")
def aviso_recebimento(p: PedidoAviso):
    """Acionado pelo painel: envia o aviso de recebimento (texto puro) à conversa, dentro da janela de 24 h."""
    ref = db.collection("conversas").document(p.conversa_id)
    conv = ref.get().to_dict()
    if not conv:
        raise HTTPException(404, "conversa não existe")
    texto = config.parametros()["ia"]["recepcao"]["aviso_recebimento_texto"]
    _, mt, _ = _svc()
    try:
        wamid = mt.enviar_texto(conv["contato"], texto)
    except Exception as e:
        fora = "131047" in str(e)
        raise HTTPException(400, "fora da janela de 24 h: a pessoa precisa escrever de novo antes" if fora else f"falha ao enviar: {str(e)[:160]}")
    ref.collection("mensagens").document(wamid).set({
        "direcao": "celeste", "tipo": "text", "modelo": "automatico (aviso de recebimento)", "texto": texto,
        "recebido_em": datetime.now(timezone.utc), "gravado_em": firestore.SERVER_TIMESTAMP})
    ref.set({"ultima": {"texto": texto[:160], "direcao": "celeste", "tipo": "text", "em": datetime.now(timezone.utc)},
             "pendente_resposta": False, "aviso_recebimento_em": datetime.now(timezone.utc),
             "avisos_recebimento": firestore.Increment(1)}, merge=True)
    return {"ok": True, "wamid": wamid}


class PedidoOrientar(BaseModel):
    conversa_id: str


@app.post("/orientar")
def orientar_manual(p: PedidoOrientar):
    """Acionado pelo painel: envia a orientação + botão da recepção agora, ignorando o intervalo de 24 h entre repetições."""
    ref = db.collection("conversas").document(p.conversa_id)
    conv = ref.get().to_dict()
    if not conv:
        raise HTTPException(404, "conversa não existe")
    conv["id"] = p.conversa_id
    r = _orientar_recepcao(ref, conv, forcar=True)
    if not r.get("ok"):
        raise HTTPException(400, r.get("erro", "não foi possível enviar"))
    return r


def _orientar_recepcao(ref, conv: dict, forcar: bool = False) -> dict:
    """Quem não está na base de leads recebe, uma vez por conversa, a orientação + botão 'Falar com Recepção'. Sem IA, sem custo."""
    rec = config.parametros()["ia"]["recepcao"]
    cfg = _cfg_atendimento()
    automatico = cfg.get("orientar_automatico", rec.get("orientar_nao_leads", False))
    if not forcar and not automatico:
        ref.set({"pendente_resposta": False, "sem_frente_ignorado": True}, merge=True)
        return {"ok": True, "ignorado": "sem frente; orientação automática desligada (use o botão no painel)"}
    ultimo = conv.get("orientado_recepcao_em")
    intervalo = timedelta(hours=float(rec.get("orientacao_intervalo_horas") or 24))
    if not forcar and ultimo and datetime.now(timezone.utc) - ultimo < intervalo:
        ref.set({"pendente_resposta": False}, merge=True)
        return {"ok": True, "ignorado": "sem frente; já orientado nas últimas horas"}
    _, mt, _ = _svc()
    try:
        wamid = mt.enviar_botao_url(conv["contato"], rec["orientacao_texto"], rec["botao_rotulo"], rec["link_wa"])
    except Exception as e:
        log.warning("orientação à recepção não enviada (%s): %s", conv.get("id"), e)
        ref.set({"pendente_resposta": False}, merge=True)
        fora = "131047" in str(e) or "janela" in str(e).lower()
        return {"ok": False, "erro": "fora da janela de 24 h: a pessoa precisa escrever de novo antes" if fora else f"falha ao enviar: {str(e)[:160]}"}
    ref.collection("mensagens").document(wamid).set({
        "direcao": "celeste", "tipo": "interactive", "modelo": "manual (painel)" if forcar else "automatico",
        "texto": f"{rec['orientacao_texto']}\n[botão: {rec['botao_rotulo']} → {rec['link_wa']}]",
        "recebido_em": datetime.now(timezone.utc), "gravado_em": firestore.SERVER_TIMESTAMP})
    ref.set({"ultima": {"texto": rec["orientacao_texto"][:160], "direcao": "celeste", "tipo": "interactive", "em": datetime.now(timezone.utc)},
             "pendente_resposta": False, "status": "Orientado à recepção", "orientado_recepcao_em": datetime.now(timezone.utc),
             "orientacoes_enviadas": firestore.Increment(1),
             "ultima_msg_celeste_em": firestore.SERVER_TIMESTAMP, "total_msgs_celeste": firestore.Increment(1)}, merge=True)
    return {"ok": True, "enviado": 1, "orientado_recepcao": True}


def _acao_botao_t1(ref, ultimo_wamid: str | None) -> str | None:
    """Se a última mensagem do lead foi um botão do fluxo do T1, devolve a ação determinística ('agora_nao' | 'sair'); senão None."""
    if not ultimo_wamid:
        return None
    m = ref.collection("mensagens").document(ultimo_wamid).get().to_dict() or {}
    return classificar_botao_t1(m.get("botao"), m.get("texto"))


def classificar_botao_t1(botao: str | None, texto: str | None) -> str | None:
    b = config.parametros().get("t1_botoes") or {}
    cand = {str(x or "").strip().casefold() for x in (botao, texto)}
    if b.get("sair_id", "").casefold() in cand or b.get("sair_rotulo", "").casefold() in cand:
        return "sair"
    if b.get("encerrar_rotulo", "").casefold() in cand:
        return "encerrar"
    if b.get("agora_nao", "").casefold() in cand:
        return "agora_nao"
    return None


def _responder_agora_nao(ref, conv: dict, mt: meta.Meta) -> dict:
    """Lead tocou 'Agora não': pergunta o motivo com um botão de saída; status 'Irá nos retornar'. Sem modelo."""
    b = config.parametros()["t1_botoes"]
    nome = ((conv.get("nome") or "").strip().split() or [""])[0].title()
    texto = b["agora_nao_texto"].replace("{nome}", nome).replace("Entendo, !", "Entendo!")
    wamid = mt.enviar_botoes_resposta(conv["contato"], texto, [(b["sair_id"], b["sair_rotulo"])])
    agora = datetime.now(timezone.utc)
    ref.collection("mensagens").document(wamid).set({
        "direcao": "celeste", "tipo": "interactive", "texto": f"{texto}\n[botão: {b['sair_rotulo']}]", "modelo": "fluxo T1",
        "recebido_em": agora, "gravado_em": firestore.SERVER_TIMESTAMP})
    campos = {"status": "Agora não", "agora_nao_em": agora, "pendente_resposta": False,
              "ultima": {"texto": texto[:160], "direcao": "celeste", "tipo": "interactive", "em": agora}, "ultima_msg_celeste_em": firestore.SERVER_TIMESTAMP}
    conv.update(campos); ref.set(campos, merge=True)
    _espelhar_lead(conv)
    return {"ok": True, "enviado": 1, "fluxo": "t1_agora_nao"}


def _acao_botao_consulta(ref, ultimo_wamid: str | None) -> str | None:
    """Se a última mensagem do lead foi o botão 'Confirmar presença' dos lembretes da consulta, devolve 'confirmar_presenca'."""
    if not ultimo_wamid:
        return None
    m = ref.collection("mensagens").document(ultimo_wamid).get().to_dict() or {}
    return classificar_botao_consulta(m.get("botao"), m.get("texto"))


def classificar_botao_consulta(botao: str | None, texto: str | None) -> str | None:
    b = config.parametros().get("consulta_botoes") or {}
    cand = {str(x or "").strip().casefold() for x in (botao, texto)}
    if b.get("confirmar", "").casefold() in cand:
        return "confirmar_presenca"
    return None   # "Preciso remarcar" vai para o modelo: a Celeste consulta o agendamento e reagenda pela conversa


def _responder_confirmar_presenca(ref, conv: dict, mt: meta.Meta) -> dict:
    """Lead tocou 'Confirmar presença' (C48/C24): status Confirmado no TI Saúde, agradecimento fixo e vídeo do profissional. Sem modelo.
    Aprovado pela clínica em 26/10/2026."""
    from celeste.jobs.rotinas_consulta import formatar_dia, formatar_hora
    p = config.parametros()
    b = p["consulta_botoes"]
    ag = dict(conv.get("agendamento") or {})
    ida = conv.get("id_agendamento_tisaude")
    simulado = bool(conv.get("teste") or _e_numero_teste(conv.get("contato", ""))) and not _escreve_no_tisaude(conv.get("contato", ""))
    ts = TiSaudeSimulado() if simulado else _svc()[2]
    gravou = False
    if ida:
        try:
            ts.confirmar_presenca(int(ida))
            gravou = True
        except Exception as e:   # noqa: BLE001
            log.warning("confirmar presença no TI Saúde falhou (conversa %s, agendamento %s): %s", conv.get("id"), ida, e)
    nome = ((conv.get("nome") or "").strip().split() or [""])[0].title()
    try:
        dia = formatar_dia(date.fromisoformat(str(ag.get("data"))[:10]))
    except (TypeError, ValueError):
        dia = "o dia marcado"
    texto = b["confirmado_texto"].replace("{nome}", nome or "tudo bem").replace("{dia}", dia).replace("{hora}", formatar_hora(ag.get("hora", "")))
    agora = datetime.now(timezone.utc)
    wamid = mt.enviar_texto(conv["contato"], texto)
    ref.collection("mensagens").document(wamid).set({
        "direcao": "celeste", "tipo": "text", "texto": texto, "modelo": "fluxo consulta",
        "recebido_em": agora, "gravado_em": firestore.SERVER_TIMESTAMP})
    enviados = 1
    chave = "confirmou_dra_luciana" if ag.get("profissional") == "dra_luciana" else "confirmou_dr_lucas"
    v = (p.get("videos_rotinas") or {}).get(chave)
    if v:
        try:
            wv = mt.enviar_video_link(conv["contato"], v["url"])
            ref.collection("mensagens").document(wv).set({
                "direcao": "celeste", "tipo": "video", "texto": f"[vídeo: {chave} — {v['descricao']}]", "video": chave, "modelo": "fluxo consulta",
                "recebido_em": agora, "gravado_em": firestore.SERVER_TIMESTAMP})
            enviados += 1
        except Exception as e:   # noqa: BLE001
            log.warning("vídeo de confirmação não enviado (conversa %s): %s", conv.get("id"), e)
    rot = dict(conv.get("rotinas_consulta") or {}); rot.update({"confirmado_em": agora, "confirmado_no_tisaude": gravou})
    ag["status"] = "Confirmado" if gravou else ag.get("status")
    campos = {"rotinas_consulta": rot, "agendamento": ag, "pendente_resposta": False,
              "ultima": {"texto": texto[:160], "direcao": "celeste", "tipo": "text", "em": agora}, "ultima_msg_celeste_em": firestore.SERVER_TIMESTAMP}
    if ida and not gravou:
        campos.update({"revisar": True, "revisar_motivo": "confirmação de presença não gravou no TI Saúde"})
    conv.update(campos); ref.set(campos, merge=True)
    return {"ok": True, "enviado": enviados, "fluxo": "consulta_confirmar", "tisaude": "simulado" if simulado else ("confirmado" if gravou else "falhou")}


def _responder_sair(ref, conv: dict, mt: meta.Meta, acao: str = "sair") -> dict:
    """Lead tocou 'Não quero continuar' (T1–T3) ou 'Pode encerrar' (T4): despedida, opt-out, sai da esteira. Sem modelo."""
    b = config.parametros()["t1_botoes"]
    nome = ((conv.get("nome") or "").strip().split() or [""])[0].title()
    texto = (b["encerrar_texto"] if acao == "encerrar" else b["sair_texto"]).replace("{nome}", nome).replace("Tudo bem, .", "Tudo bem.")
    wamid = mt.enviar_texto(conv["contato"], texto)
    agora = datetime.now(timezone.utc)
    ref.collection("mensagens").document(wamid).set({
        "direcao": "celeste", "tipo": "text", "texto": texto, "modelo": "fluxo T1",
        "recebido_em": agora, "gravado_em": firestore.SERVER_TIMESTAMP})
    campos = {"status": "Não quer (opt-out)", "opt_out": True, "opt_out_em": agora, "aberta": False, "pendente_resposta": False,
              "ultima": {"texto": texto[:160], "direcao": "celeste", "tipo": "text", "em": agora}, "ultima_msg_celeste_em": firestore.SERVER_TIMESTAMP}
    conv.update(campos); ref.set(campos, merge=True)
    _espelhar_lead(conv)
    return {"ok": True, "enviado": 1, "fluxo": "t1_sair"}


def _pre_verificar_paciente(ref, conv: dict, ts) -> None:
    """Antes da 1ª resposta, verifica pelo código se o número já é paciente no TI Saúde (evita uma chamada do modelo só para isso)."""
    if conv.get("paciente_verificado_em") or conv.get("id_paciente_tisaude"):
        return
    campos: dict = {"paciente_verificado_em": datetime.now(timezone.utc)}
    try:
        lista = ts.listar_por_celular(conv.get("contato", ""))
        if not lista:
            campos["paciente_tisaude_ausente"] = True
        elif len(lista) == 1:
            campos.update({"id_paciente_tisaude": lista[0]["id"], "paciente_tisaude_nome": lista[0].get("nome")})
        else:   # número compartilhado (família): só assume se o nome do lead bater com um único cadastro; senão a Celeste pergunta o CPF
            campos["pacientes_mesmo_numero"] = [{"id": p["id"], "nome": p.get("nome")} for p in lista[:10]]
            escolhido = tisaude.escolher_por_nome(lista, conv.get("nome") or "")
            if escolhido:
                campos.update({"id_paciente_tisaude": escolhido["id"], "paciente_tisaude_nome": escolhido.get("nome")})
    except Exception as e:
        log.warning("pré-verificação de paciente falhou: %s", e)
        return
    conv.update(campos)
    ref.set(campos, merge=True)


def _lead_contatado(contato: str) -> bool:
    """Lead da base que já recebeu ao menos um template da Celeste (passo > 0). 25/10/2026: em produção, só esses são atendidos;
    um lead da base que escreve antes de ser disparado é tratado como sem frente (orientação à recepção)."""
    doc = db.collection("leads").document(contato).get()
    return bool(doc.exists and int((doc.to_dict() or {}).get("passo") or 0) > 0)


def _pode_responder(contato: str) -> bool:
    """teste: só numeros_teste · producao: numeros_teste + leads que já receberam template da Celeste · aberto: todos.
    Override: Firestore config/atendimento {modo, numeros_teste}."""
    cfg = _cfg_atendimento()
    modo = cfg.get("modo", "teste")
    if modo == "aberto":
        return True
    if contato in {str(n) for n in (cfg.get("numeros_teste") or [])}:
        return True
    if modo == "producao":
        return _lead_contatado(contato)
    return False


# ----------------------------------------------------------------- histórico
def _historico(ref, mt: meta.Meta) -> tuple[list[dict], str | None]:
    """Converte as mensagens do Firestore em turnos user/assistant, agrupando balões consecutivos."""
    turnos: list[dict] = []
    ultimo_wamid = None
    for doc in ref.collection("mensagens").order_by("recebido_em").stream():
        m = doc.to_dict()
        if m.get("direcao") == "lead":
            ultimo_wamid = doc.id
            blocos = _blocos_lead(doc, m, mt)
            if turnos and turnos[-1]["role"] == "user":
                turnos[-1]["content"].extend(blocos)
            else:
                turnos.append({"role": "user", "content": blocos})
        elif m.get("direcao") in ("celeste", "template", "humano"):
            texto = m.get("texto") or f"[template {m.get('template')}]"
            if m.get("direcao") == "humano":
                texto = f"[mensagem enviada por uma pessoa da equipe, não por você]: {texto}"
            if turnos and turnos[-1]["role"] == "assistant":
                turnos[-1]["content"] += "\n---\n" + texto
            else:
                turnos.append({"role": "assistant", "content": texto})
    # a API exige que o 1º turno seja user; se a conversa começou com template, o modelo vê como assistant → prefixamos
    if turnos and turnos[0]["role"] == "assistant":
        turnos.insert(0, {"role": "user", "content": "[início da conversa — a Celeste enviou a primeira mensagem]"})
    # o motor injeta o contexto do lead no 1º turno se ele for string: compactamos blocos só-texto em string
    for t in turnos:
        if t["role"] == "user" and all(b.get("type") == "text" for b in t["content"]):
            t["content"] = "\n".join(b["text"] for b in t["content"])
    return turnos, ultimo_wamid


def _blocos_lead(doc, m: dict, mt: meta.Meta) -> list[dict]:
    tipo = m.get("tipo")
    if tipo == "text":
        return [{"type": "text", "text": m.get("texto") or ""}]
    if tipo in ("button", "interactive"):
        return [{"type": "text", "text": f"[clicou no botão: {m.get('botao') or m.get('texto')}]"}]
    if tipo in ("audio", "voice"):
        if m.get("transcricao") is None:
            transcr = ""
            try:
                conteudo, mime = mt.baixar_midia(m["media_id"])
                _guardar_midia(doc, conteudo, mime)
                transcr = transcricao.transcrever(conteudo, mime)
            except Exception as e:
                log.warning("áudio %s: %s", doc.id, e)
            doc.reference.set({"transcricao": transcr}, merge=True)
            m["transcricao"] = transcr
        return [{"type": "text", "text": f"[áudio do lead, transcrição: {m['transcricao']}]" if m["transcricao"]
                 else "[o lead mandou um áudio que não foi possível ouvir — peça com jeitinho para escrever]"}]
    if tipo == "image":
        try:
            conteudo, mime = mt.baixar_midia(m["media_id"])
            _guardar_midia(doc, conteudo, mime)
            legenda = f" Legenda: {m['texto']}" if m.get("texto") else ""
            return [{"type": "text", "text": f"[o lead enviou uma imagem.{legenda}]"},
                    {"type": "image", "source": {"type": "base64", "media_type": mime.split(";")[0] or "image/jpeg",
                                                 "data": base64.b64encode(conteudo).decode()}}]
        except Exception as e:
            log.warning("imagem %s: %s", doc.id, e)
            return [{"type": "text", "text": "[o lead enviou uma imagem que não pôde ser aberta]"}]
    return [{"type": "text", "text": f"[o lead enviou {tipo}{': ' + m['texto'] if m.get('texto') else ''}]"}]


def _guardar_midia(doc, conteudo: bytes, mime: str) -> None:
    if doc.to_dict().get("midia_gcs"):
        return
    try:
        ext = {"audio/ogg": "ogg", "image/jpeg": "jpg", "image/png": "png"}.get(mime.split(";")[0], "bin")
        caminho = f"{doc.reference.parent.parent.id}/{doc.id}.{ext}"
        storage.Client(project=config.PROJETO_GCP).bucket(BUCKET).blob(caminho).upload_from_string(conteudo, content_type=mime)
        doc.reference.set({"midia_gcs": f"gs://{BUCKET}/{caminho}"}, merge=True)
    except Exception as e:
        log.warning("não guardou mídia: %s", e)


# ----------------------------------------------------------------- ações laterais
def _enviar_video(mt: meta.Meta, ref, conv: dict, chave: str) -> str:
    v = config.parametros()["videos"][chave]
    wamid = mt.enviar_video_link(conv["contato"], v["url"])
    ref.collection("mensagens").document(wamid).set({
        "direcao": "celeste", "tipo": "video", "texto": f"[vídeo: {chave} — {v['descricao']}; quem aparece: {v.get('quem_aparece', 'a confirmar pela clínica')}]", "video": chave,
        "recebido_em": datetime.now(timezone.utc), "gravado_em": firestore.SERVER_TIMESTAMP})
    return wamid


def _enviar_foto(mt: meta.Meta, ref, conv: dict, grupo: str, slug: str, arquivo: str) -> int:
    """Uma foto de antes e depois (por doença ou por tratamento), com legenda. Devolve 1."""
    p = config.parametros()
    if grupo == "doenca":
        cfg, item = p["antes_e_depois"], p["antes_e_depois"]["doencas"][slug]
        legenda, rotulo, caminho = cfg["legenda"].format(doenca=item["nome"]), f"antes e depois: {item['nome']}", arquivo
    else:
        cfg, item = p["antes_e_depois_tratamentos"], p["antes_e_depois_tratamentos"]["tratamentos"][slug]
        legenda, rotulo, caminho = cfg["legenda"].format(tratamento=item["nome"]), f"antes e depois do tratamento: {item['nome']}", "tratamentos/" + arquivo
    wamid = mt.enviar_imagem_link(conv["contato"], cfg["base_url"] + arquivo, legenda)
    ref.collection("mensagens").document(wamid).set({
        "direcao": "celeste", "tipo": "image", "texto": f"[{rotulo} — {arquivo}] {legenda}", "imagem": caminho,
        "recebido_em": datetime.now(timezone.utc), "gravado_em": firestore.SERVER_TIMESTAMP})
    return 1


def _responder_abertura(ref, conv: dict, mt: meta.Meta, texto_lead: str) -> dict:
    """Dois balões fixos de apresentação, sem chamar o modelo (custo zero, resposta em segundos)."""
    nome_ia = config.parametros()["ia"].get("nome_atendente", "Celeste")
    baloes = abertura.baloes_abertura(conv.get("nome") or "", texto_lead, nome_ia)
    enviados = 0
    for i, texto in enumerate(baloes):
        if i and SIMULAR_DELAY:
            time.sleep(1.2)
        wamid = mt.enviar_texto(conv["contato"], texto)
        ref.collection("mensagens").document(wamid).set({
            "direcao": "celeste", "tipo": "text", "texto": texto, "modelo": "fixo-abertura",
            "recebido_em": datetime.now(timezone.utc), "gravado_em": firestore.SERVER_TIMESTAMP})
        enviados += 1
    campos = {"pendente_resposta": False, "ultima_msg_celeste_em": firestore.SERVER_TIMESTAMP, "total_msgs_celeste": firestore.Increment(enviados),
              "ultima": {"texto": baloes[-1][:160], "direcao": "celeste", "tipo": "text", "em": datetime.now(timezone.utc)}}
    if not conv.get("primeira_msg_celeste_em"):
        campos["primeira_msg_celeste_em"] = firestore.SERVER_TIMESTAMP
    ref.set(campos, merge=True)
    _espelhar_lead(conv)
    log.info("abertura fixa enviada sem modelo (conversa %s)", conv.get("id"))
    return {"ok": True, "enviado": enviados, "modelo": "fixo-abertura", "custo_usd": 0.0}


def _avisar_recepcao(mt: meta.Meta, conv: dict, motivo: str, resumo: str) -> None:
    rec = config.parametros()["ia"]["recepcao"]
    nome = conv.get("nome") or "lead sem nome"
    db.collection("encaminhamentos").document().set({
        "conversa_id": conv["id"], "contato": conv["contato"], "nome": nome, "frente": conv.get("frente"),
        "motivo": motivo, "resumo": resumo, "em": firestore.SERVER_TIMESTAMP, "atendido": False})
    try:
        mt.enviar_template(rec["whatsapp"], rec["template_aviso"],
                           [nome, f"https://wa.me/{conv['contato']}", motivo.replace("_", " "), resumo[:300], conv.get("frente") or ""])
    except Exception as e:  # template ainda não aprovado → fica só no painel; tenta texto livre (só funciona com janela aberta)
        log.warning("aviso à recepção por template falhou (%s); tentando texto", e)
        try:
            mt.enviar_texto(rec["whatsapp"], f"Lead encaminhado pela Celeste\nNome: {nome}\nWhatsApp: https://wa.me/{conv['contato']}\n"
                                             f"Motivo: {motivo.replace('_', ' ')}\nResumo: {resumo}")
        except Exception as e2:
            log.error("aviso à recepção não entregue: %s", e2)


def _espelhar_lead(conv: dict) -> None:
    """Mantém `leads/{celular}` (fila de disparos) coerente com a conversa: status, opt-out, datas de recontato."""
    campos = {"status_ia": conv.get("status"), "ultima_msg_lead_em": datetime.now(timezone.utc), "conversa_id": conv["id"]}
    if conv.get("opt_out"):
        campos["opt_out"] = True
    if "proximo_recontato_em" in conv:
        campos["proximo_recontato_em"] = conv["proximo_recontato_em"]
    if conv.get("status") == "Agendado":
        campos["elegivel"] = False
    ref = db.collection("leads").document(conv["contato"])
    if ref.get().exists:
        ref.set(campos, merge=True)
    elif conv.get("teste") or _e_numero_teste(conv.get("contato", "")):
        # 27/10/2026: número de teste da clínica entra na fila como lead já contatado (passo 1), para o retorno combinado
        # e os demais recontatos poderem ser testados de verdade. `teste: true` o mantém fora da Gestão/Funil e da carga das 6h.
        nome = (conv.get("nome") or "").strip()
        agora = datetime.now(timezone.utc)
        ref.set({"celular": conv["contato"], "nome": nome, "primeiro_nome": (nome.split() or [""])[0].title(), "frente": "leads_perdidos",
                 "origem": "teste", "teste": True, "elegivel": True, "opt_out": False, "na_janela": False, "passo": 1, "ciclos": 1, "ciclo": 1,
                 "lead_created_at": agora, "carregado_em": agora, "disponibilizado_em": agora, **campos}, merge=True)


# ----------------------------------------------------------------- custo e métricas
def _registrar_chamada(conversa_id: str, res: motor.Resultado, segundos: float) -> None:
    hoje = datetime.now(FUSO).strftime("%Y-%m-%d")
    db.collection("chamadas_ia").document().set({
        "conversa_id": conversa_id, "modelo": res.modelo, "custo_usd": res.custo_usd, "tokens": res.tokens,
        "chamadas": res.chamadas, "ferramentas": res.ferramentas, "baloes": len(res.baloes), "refusal": res.refusal,
        "latencia_s": round(segundos, 2), "dia": hoje, "em": firestore.SERVER_TIMESTAMP})
    db.collection("custos_diarios").document(hoje).set(
        {"custo_usd": firestore.Increment(res.custo_usd), "chamadas": firestore.Increment(res.chamadas)}, merge=True)


def _custo_hoje() -> float:
    d = db.collection("custos_diarios").document(datetime.now(FUSO).strftime("%Y-%m-%d")).get().to_dict() or {}
    return float(d.get("custo_usd", 0))


def _horario_comercial() -> bool:
    agora = datetime.now(FUSO)
    return agora.weekday() < 5 and 9 <= agora.hour < 19
