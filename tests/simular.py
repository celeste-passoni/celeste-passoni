# -*- coding: utf-8 -*-
"""Roda cenários roteirizados com a Celeste (TI Saúde e WhatsApp simulados) e grava relatórios em tests/relatorio-<cenario>.md.

Uso:  python tests/simular.py [nome_do_cenario ...]     (sem argumentos = todos)
Precisa de ANTHROPIC_API_KEY no .env. Não grava nada no TI Saúde nem no Firestore.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conversar_local import TiSaudeFake  # noqa: E402
from celeste.comum import config  # noqa: E402
from celeste.jobs import templates_texto  # noqa: E402
from celeste.orquestrador import ferramentas_ia, motor  # noqa: E402

CENARIOS = {
    "1-agenda-dr-lucas": {"nome": "Ana", "template": "T1", "falas": [
        "[clicou no botão: Quero ver horários]",
        "quanto custa a consulta?",
        "nossa, 1200 é caro demais... vcs aceitam convênio?",
        "hmm entendi. e o dr lucas, ele é bom? nunca ouvi falar",
        "ta bom, pode ser com ele então. que horários tem na semana que vem?",
        "terça 10h30 pode ser",
        "Ana Paula Ribeiro, 111.444.777-35, 15/03/1988, feminino, anapaula@email.com, cep 04077-020, número 800 apto 12, conheci pelo instagram da dra",
    ]},
    "2-agora-nao": {"nome": "Carlos", "template": "T1", "falas": [
        "[clicou no botão: Agora não]",
        "é que to sem tempo agora, mês que vem talvez",
    ]},
    "3-receita": {"nome": "Marcia", "template": "T2", "falas": [
        "oi, na verdade eu já sou paciente da dra, só queria renovar minha receita do minoxidil",
    ]},
    "4-sair": {"nome": "Roberto", "template": "T1", "falas": [
        "SAIR",
    ]},
    "5-menor-de-idade": {"nome": "Fernanda", "template": "T3", "falas": [
        "[clicou no botão: Dúvida sobre horário]",
        "é pra minha filha de 15 anos, ela tá com muita queda. tem horário sábado?",
        "então pode ser sexta depois das 15h com a dra luciana",
        "sexta 16h. Júlia Mendes Costa, 12/08/2011, feminino, nascimento dela. cpf dela 222.333.444-05. email julia.mc@email.com, cep 05407-002 n 1500. eu sou a mãe, Fernanda Mendes, cpf 333.444.555-06",
    ]},
    "6-tratamento-sem-consulta": {"nome": "Paulo", "template": "T1", "falas": [
        "[clicou no botão: Tenho uma dúvida]",
        "eu já fiz consulta em outra clínica e tenho diagnóstico de alopecia androgenética. posso fazer só o tratamento direto com vcs? qual o valor do tratamento?",
        "ah então tem que pagar consulta de novo? que chato. dá pra fazer online pelo menos?",
    ]},
}


def rodar(chave: str, cen: dict) -> str:
    nome, tpl = cen["nome"], cen["template"]
    conv = {"id": f"sim-{chave}", "contato": "5511999990000", "nome": nome, "frente": "leads_perdidos",
            "status": config.parametros()["disparos"]["status_apos_template"][tpl], "origem": "leads_perdidos",
            "ultimo_contato_anterior": "há 3 meses, conversou com a recepção e não agendou", "template_origem": tpl}
    ts = TiSaudeFake()
    linhas: list[str] = []
    ctx = ferramentas_ia.Contexto(
        conversa=conv, telefone=conv["contato"], tisaude=ts,
        viacep=lambda cep: {"endereco": "RUA EXEMPLO", "bairro": "MOEMA", "cidade": "SAO PAULO", "uf": "SP"} if len(cep.replace("-", "")) == 8 else {},
        enviar_video=lambda v: (linhas.append(f"   *[SIMULADO] vídeo enviado: {v}*\n"), "wamid-video")[1],
        avisar_recepcao=lambda m, r: linhas.append(f"   *[SIMULADO] aviso à recepção — motivo: {m} — resumo: {r}*\n"),
        atualizar=lambda campos: conv.update(campos))
    # o TI Saúde simulado imprime no stdout; redirecionamos para o relatório
    import builtins, io, contextlib
    mot = motor.Motor()
    texto_tpl = templates_texto.renderizar(tpl, nome, mes="outubro", horario="16h", profissional="Dr. Lucas Vieira")
    hist = [{"role": "user", "content": "[início da conversa — a Celeste enviou a primeira mensagem]"},
            {"role": "assistant", "content": texto_tpl}]
    linhas.append(f"# Cenário {chave} — {config.parametros()['ia']['nome_atendente']} × {nome}\n")
    linhas.append("_TI Saúde e WhatsApp simulados; nada é gravado._\n")
    linhas.append(f"> **Celeste (template {tpl}):** " + texto_tpl.replace("\n", "\n> ") + "\n")
    total = 0.0
    for f in cen["falas"]:
        linhas.append(f"**{nome}:** {f}\n")
        hist.append({"role": "user", "content": f})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r = mot.responder("leads_perdidos", conv, list(hist), ctx)
        for l in buf.getvalue().splitlines():
            if l.strip():
                linhas.append(f"   *{l.strip()}*\n")
        total += r.custo_usd
        for b in r.baloes:
            linhas.append("> **Celeste:** " + b.replace("\n", "\n> ") + "\n")
        hist.append({"role": "assistant", "content": "\n---\n".join(r.baloes) or "[sem resposta]"})
        usadas = ", ".join(x["nome"] + (" (erro)" if x["erro"] else "") for x in r.ferramentas) or "—"
        linhas.append(f"`{r.modelo} · {r.chamadas} chamada(s) · ferramentas: {usadas} · US$ {r.custo_usd:.4f}`\n")
        if ctx.encerrar:
            linhas.append("_(conversa encerrada pela Celeste)_\n")
            break
    linhas.append(f"\n**Custo: US$ {total:.4f}** · status final: **{conv.get('status')}**" +
                  (f" · recontato: {conv.get('proximo_recontato_em')}" if conv.get("proximo_recontato_em") else ""))
    return "\n".join(linhas)


if __name__ == "__main__":
    escolhidos = sys.argv[1:] or list(CENARIOS)
    for k in escolhidos:
        rel = rodar(k, CENARIOS[k])
        out = Path(__file__).parent / f"relatorio-{k}.md"
        out.write_text(rel, encoding="utf-8")
        print(f"{k}: {rel.splitlines()[-1]}")
