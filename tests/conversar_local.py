# -*- coding: utf-8 -*-
"""Conversa com a Celeste no terminal, SEM WhatsApp, SEM Firestore e SEM escrever no TI Saúde.

Serve para validar persona, tom e fluxo antes de publicar. Precisa de ANTHROPIC_API_KEY no .env.
Modo padrão: TI Saúde simulado (horários de mentira, cadastro/agendamento só na tela).
   --tisaude-real : lê horários reais do TI Saúde (só leitura; cadastro e agendamento continuam simulados).

Uso:  python tests/conversar_local.py [--tisaude-real] [--template T1]
Comandos: /sair  /custo  /reset
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from celeste.orquestrador import ferramentas_ia, motor  # noqa: E402
from celeste.comum import config  # noqa: E402


class TiSaudeFake:
    def __init__(self, real=None):
        self.real, self._pacientes, self._agend = real, {}, {}

    def buscar_paciente(self, *, celular="", cpf=""):
        return self._pacientes.get("x")

    def criar_paciente(self, dados):
        print(f"\n   [SIMULADO] criar_paciente: {json.dumps({k: v for k, v in dados.items() if k in ('nome', 'nascimento', 'sexo', 'indicado', 'cidade')}, ensure_ascii=False)}")
        self._pacientes["x"] = {"id": 999001, "nome": dados["nome"]}
        return {"id": 999001}

    def buscar_horarios(self, profissional_id, *, dias=None, a_partir_de=None):
        if self.real:
            return self.real.buscar_horarios(profissional_id, dias=dias, a_partir_de=a_partir_de)
        ini = a_partir_de or date.today()
        out = []
        for i in range(dias or 14):
            d = ini + timedelta(days=i)
            if d.weekday() < 5:
                horas = ["12:00", "13:00", "15:00", "16:00"] if profissional_id == "dra_luciana" else ["09:00", "10:30", "14:00", "16:30", "18:00"]
                out += [{"data": d.isoformat(), "hora": h} for h in horas]
        return out

    def agendar_consulta(self, *, id_paciente, profissional_id, data, hora, observacoes):
        print(f"\n   [SIMULADO] agendar_consulta: paciente {id_paciente} · {profissional_id} · {data} {hora}")
        return {"id": 777001, "status": 0}

    def reagendar(self, id_agendamento, data, hora):
        print(f"\n   [SIMULADO] reagendar {id_agendamento} → {data} {hora}")
        return {"data": data.strftime("%d/%m/%Y"), "hora": hora}

    def cancelar(self, id_agendamento, motivo=""):
        print(f"\n   [SIMULADO] cancelar {id_agendamento} ({motivo})")
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tisaude-real", action="store_true")
    ap.add_argument("--template", default="T1", help="qual template abriu a conversa (T1..T5) ou 'nenhum'")
    ap.add_argument("--nome", default="Ana")
    args = ap.parse_args()

    real = None
    if args.tisaude_real:
        from celeste.ferramentas import tisaude
        real = tisaude.TiSaude()
    ts = TiSaudeFake(real)
    p = config.parametros()
    conv = {"id": "local", "contato": "5511999990000", "nome": args.nome, "frente": "leads_perdidos", "status": "Em conversa",
            "origem": "leads_perdidos", "ultimo_contato_anterior": "há 3 meses, não respondeu à recepção", "template_origem": args.template}
    ctx = ferramentas_ia.Contexto(
        conversa=conv, telefone=conv["contato"], tisaude=ts,
        viacep=lambda cep: {"endereco": "RUA EXEMPLO", "bairro": "CENTRO", "cidade": "SAO PAULO", "uf": "SP"} if len(cep.replace("-", "")) == 8 else {},
        enviar_video=lambda v: (print(f"\n   [SIMULADO] enviar_video: {v}"), "wamid-video")[1],
        avisar_recepcao=lambda m, r: print(f"\n   [SIMULADO] aviso à recepção: {m} — {r}"),
        atualizar=lambda campos: conv.update(campos))
    mot = motor.Motor()
    historico: list[dict] = []
    total = 0.0
    if args.template != "nenhum":
        historico.append({"role": "user", "content": "[início da conversa — a Celeste enviou a primeira mensagem]"})
        historico.append({"role": "assistant", "content": f"[template {args.template} de resgate enviado pela Celeste ao lead {args.nome}]"})
    print(f"\n{p['ia']['nome_atendente']} — modo local ({'TI Saúde real (leitura)' if real else 'tudo simulado'}). /sair para encerrar.\n")
    while True:
        try:
            txt = input(f"{args.nome}: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not txt:
            continue
        if txt == "/sair":
            break
        if txt == "/custo":
            print(f"   custo acumulado: US$ {total:.4f}"); continue
        if txt == "/reset":
            historico.clear(); total = 0.0; continue
        historico.append({"role": "user", "content": txt})
        res = mot.responder("leads_perdidos", conv, list(historico), ctx)
        total += res.custo_usd
        for b in res.baloes:
            print(f"\n{p['ia']['nome_atendente']}: {b}")
        historico.append({"role": "assistant", "content": "\n---\n".join(res.baloes) or "[sem resposta]"})
        usadas = ", ".join(f["nome"] for f in res.ferramentas) or "—"
        print(f"\n   [{res.modelo} · {res.chamadas} chamada(s) · ferramentas: {usadas} · US$ {res.custo_usd:.4f} · "
              f"cache {res.tokens.get('cache_read_input_tokens', 0)} lidos]\n")
        if ctx.encerrar:
            print("   (conversa encerrada pela Celeste)"); break


if __name__ == "__main__":
    main()
