# -*- coding: utf-8 -*-
"""Passos 1–5 do teste de integração: SOMENTE LEITURA (nenhum POST de escrita).

Uso:  python tests/teste_leitura.py
Saída: tests/relatorio-leitura.md
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tisaude_client import TiSaude  # noqa: E402

CAL_LUCIANA, CAL_LUCAS = 1, 36
PROC_LUCIANA, PROC_LUCAS = 5, 264
USER_LUCIANA, USER_LUCAS = 29110, 79786

api = TiSaude(Path(__file__).resolve().parent / "relatorio-leitura.md")

print("1. login...")
u = api.login()
print(f"   ok — usuário {u.get('nome')} (id {u.get('id')}, adm={u.get('adm')})")

print("2. calendários e procedimentos...")
api.get("2a. Calendários", "/calendarios")
api.get("2b. Procedimento 5 (Consulta Dra. Luciana)", f"/procedimento/{PROC_LUCIANA}")
api.get("2c. Procedimento 264 (Consulta Equipe Médica)", f"/procedimento/{PROC_LUCAS}")
api.get("2d. Usuário Dr. Lucas", f"/usuario/{USER_LUCAS}")

hoje = date.today()
d1 = hoje + timedelta(days=1)
d30 = hoje + timedelta(days=30)
d45 = hoje + timedelta(days=45)

print("3. horasDisponiveis (API do Paciente)...")
if api.hash_pac:
    api.get_pac("3a. Profissionais (API Paciente)", "/rest/agenda/profissionais", cliente=12054)
    for label, pid in (("usuário", USER_LUCAS), ("calendário", CAL_LUCAS)):
        api.get_pac(f"3b. Detalhes profissional Dr. Lucas por id de {label} ({pid})", f"/rest/agenda/profissional/{pid}")
        for d in (d1, d30):
            api.get_pac(f"3c. horasDisponiveis Dr. Lucas id {label} {pid} em {d:%Y-%m-%d}",
                        f"/rest/agenda/horasDisponiveis/{pid}", data=d.isoformat())
    api.get_pac(f"3d. horasDisponiveis Dra. Luciana (usuário {USER_LUCIANA}) em {d30:%Y-%m-%d}",
                f"/rest/agenda/horasDisponiveis/{USER_LUCIANA}", data=d30.isoformat())
else:
    print("   TISAUDE_HASH_PACIENTE vazio — pulando")

print("4. ocupação real da agenda do Dr. Lucas (próximos 45 dias)...")
st, ag = api.get(f"4. Agenda cal. {CAL_LUCAS} {d1} → {d45}", f"/agenda/{CAL_LUCAS}",
                 dataInicio=d1.isoformat(), dataFim=d45.isoformat())
if isinstance(ag, list):
    ativos = [a for a in ag if a.get("status") != -2 and not a.get("deletado")]
    print(f"   {len(ag)} agendamentos, {len(ativos)} ativos")
    # resumo por dia/hora sem dados pessoais
    from collections import defaultdict
    por_dia = defaultdict(list)
    for a in ativos:
        por_dia[a["data"]].append(str(a.get("hora"))[:5])
    with api.log_path.open("a", encoding="utf-8") as f:
        f.write("\n### Ocupação (hora ocupada por dia, sem dados pessoais)\n")
        for d in sorted(por_dia):
            f.write(f"- {d}: {', '.join(sorted(por_dia[d]))}\n")

print("5. busca de paciente (dedup) com CPF inexistente...")
cpf_fake = "00000000191"  # CPF válido pelo algoritmo, improvável de existir
api.get("5a. GET /pacientes?busca=<cpf inexistente>", "/pacientes", busca=cpf_fake)
if api.hash_pac:
    api.get_pac("5b. GET /rest/paciente/cpf/<cpf inexistente>", f"/rest/paciente/cpf/{cpf_fake}")

print(f"\nRelatório: {api.log_path}")
