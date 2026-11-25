# -*- coding: utf-8 -*-
"""Envio de UM template da Celeste pelo MarketZap para um número de TESTE (25/11/2026).

Só roda à mão e com OK do usuário (custo: um template na conta do número oficial; marketing ≈ US$ 0,06).
O número precisa estar em config/atendimento.numeros_teste: a conversa nasce como teste (TI Saúde simulado, fora da esteira).

    python -m celeste.jobs.mktzap_teste 5511999990000 --codigo T1 --nome Fulano            # só mostra o que faria
    python -m celeste.jobs.mktzap_teste 5511999990000 --codigo T1 --nome Fulano --enviar   # envia
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore

from celeste.comum import config
from celeste.ferramentas import canal
from celeste.jobs import disparos, templates_texto

log = logging.getLogger(__name__)


def enviar(numero: str, codigo: str = "T1", nome: Optional[str] = None, dry_run: bool = True, db=None, canal_mz=None,
           template: Optional[str] = None, parametros: Optional[list[str]] = None, mover_setor: bool = False) -> dict:
    """template/parametros: outro template já aprovado no número oficial (teste de 25/11/2026: os da Celeste ainda não existem lá).
    mover_setor=False: se o atendimento cair fora do setor da Celeste, NÃO move (o usuário quer ser avisado antes)."""
    d = config.parametros()["disparos"]
    nome_tpl = template or d["templates"][codigo]
    extras = disparos._extras_template(codigo, False)
    params = list(parametros) if parametros is not None else templates_texto.parametros(codigo, nome or "", **extras)
    plano = {"numero": numero, "codigo": codigo, "template": nome_tpl, "parametros": params, "setor": config.parametros()["mktzap"]["setor_celeste_id"]}
    db = db or firestore.Client(project=config.PROJETO_GCP)
    if numero not in disparos.numeros_teste(db):
        raise ValueError(f"{numero} não está em config/atendimento.numeros_teste; o envio de teste é só para números de teste")
    if dry_run:
        return {"dry_run": True, **plano}
    cz = canal_mz or canal.CanalMktZap({"contato": numero, "nome": nome}, mover_setor=mover_setor)
    texto = (cz.texto_do_template(nome_tpl, params) if template else None) or templates_texto.renderizar(codigo, nome or "", **extras)
    wamid = cz.enviar_template(numero, nome_tpl, params, imagem_cabecalho=None if template else templates_texto.TEMPLATES[codigo].get("imagem"))
    agora = datetime.now(timezone.utc)
    ref = None
    for c in db.collection("conversas").where("contato", "==", numero).where("aberta", "==", True).stream():
        if (c.to_dict() or {}).get("canal") == "mktzap":
            ref = c.reference
            break
    if ref is None:
        ref = db.collection("conversas").document()
        ref.set({"contato": numero, "nome": nome, "frente": "leads_perdidos", "modo": "ia", "aberta": True, "criado_em": agora,
                 "origem": "disparo", "teste": True, "primeira_msg_celeste_em": agora})
    ref.collection("mensagens").document(wamid).set({
        "direcao": "template", "tipo": "template", "template": nome_tpl, "codigo": codigo, "texto": texto,
        "recebido_em": agora, "gravado_em": firestore.SERVER_TIMESTAMP})
    campos = cz.campos_conversa()
    ref.set({"status": d["status_apos_template"][codigo], "template_origem": codigo, "ultimo_template_em": agora,
             "ultima": {"texto": f"[template {codigo}] " + texto[:120], "direcao": "template", "tipo": "template", "em": agora},
             **campos}, merge=True)
    return {"dry_run": False, "conversa_id": ref.id, **plano, **campos}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("numero")
    ap.add_argument("--codigo", default="T1")
    ap.add_argument("--nome")
    ap.add_argument("--template", help="nome de outro template do número oficial (no lugar do template da Celeste)")
    ap.add_argument("--parametro", action="append", dest="parametros", help="parâmetro {{n}} do --template, na ordem (repetir)")
    ap.add_argument("--mover-setor", action="store_true", help="se cair em outro setor, mover para o da Celeste (sem isso, só avisa)")
    ap.add_argument("--enviar", action="store_true")
    a = ap.parse_args()
    print(json.dumps(enviar(a.numero, a.codigo, a.nome, dry_run=not a.enviar, template=a.template,
                            parametros=a.parametros if a.template else None, mover_setor=a.mover_setor),
                     ensure_ascii=False, indent=2, default=str))
