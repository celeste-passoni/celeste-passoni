# -*- coding: utf-8 -*-
"""Teste de integração — ciclo completo de agendamento no TI Saúde (PRODUÇÃO).

Passos:
  6. cria paciente fictício            POST /paciente/salvar
  7. cria agendamento                   POST /agendamento/adicionar  → lê de volta
  8. confirma (status 3) e desmarca (status -2)   POST /agendamento/editar/{id}
  9. tenta 2º agendamento no MESMO slot (teste de conflito) → desmarca também

Uso:
  python tests/teste_agendamento.py              # SIMULAÇÃO: só leitura, mostra o plano, não escreve nada
  python tests/teste_agendamento.py --executar   # escreve de verdade (passos 6–9)

Saída: tests/relatorio-agendamento.md (request/response de cada passo, sem segredos)
"""
import sys
import random
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tisaude_client import TiSaude  # noqa: E402

# ----------------------------------------------------------------------------
# PARÂMETROS DO TESTE (edite aqui se quiser mudar algo antes de rodar)
# ----------------------------------------------------------------------------
CAL_LUCAS = 36                 # calendário do Dr. Lucas Vieira
PROC_EQUIPE = 264              # "PC - CONSULTA EQUIPE MÉDICA"
LOCAL = 1                      # PASSONI CLINIC - SP
DIAS_MIN, DIAS_MAX = 25, 40    # janela para procurar um slot livre (daqui a 25–40 dias)
HORAS_CANDIDATAS = ["10:00:00", "11:00:00", "16:00:00"]  # horários com uso comprovado na agenda dele
# Todos os campos obrigatórios do formulário "Novo Paciente" do TI Saúde (nome em MAIÚSCULAS,
# convênio particular, celular com DDD, e-mail, encaminhado por, sexo, endereço completo, CEP válido).
# Endereço/CEP = os da própria clínica, para o CEP ser válido sem usar dado de ninguém.
PACIENTE = {
    "nome": "TESTE IA BIA - APAGAR",     # sempre MAIÚSCULAS
    "nascimento": "01/01/1990",          # dd/mm/YYYY (formato exigido pela API); maior de idade
    "celular": "11999990000",            # DDD + número, só dígitos; fictício
    "email": "teste.ia.bia@passoniclinic.com.br",
    "indicado": "CAMPANHA DE MENSAGENS", # "Encaminhado por" — valor já existente na lista do sistema
    "sexo": "Feminino",                  # Masculino | Feminino (exato)
    "endereco": "AVENIDA REPÚBLICA DO LÍBANO",
    "n": "886",
    "apt": "TESTE IA",                   # complemento
    "bairro": "IBIRAPUERA",
    "cidade": "SÃO PAULO",
    "uf": "SP",
    "cep": "04502001",                   # CEP válido (o da clínica)
    "convenio": 1,                       # PARTICULAR (campo correto; "idConvenioCliente" é ignorado pela API — testado)
    # "medico" NÃO é enviado — a recepção não preenche esse campo (decisão da clínica, 21/09/2026)
}
OBS = "TESTE INTEGRACAO IA (Bia) - CANCELAR - nao e paciente real"
EXECUTAR = "--executar" in sys.argv


def gerar_cpf_valido() -> str:
    """Gera um CPF sintaticamente válido (dígitos verificadores corretos) para o teste."""
    n = [random.randint(0, 9) for _ in range(9)]
    for _ in range(2):
        s = sum(d * w for d, w in zip(n, range(len(n) + 1, 1, -1)))
        n.append((11 - s % 11) % 10 if (11 - s % 11) < 10 else 0)
    return "".join(map(str, n))


def escolher_slot(ocupados):
    """Primeiro dia útil na janela com um horário candidato livre no calendário do Dr. Lucas."""
    hoje = date.today()
    for delta in range(DIAS_MIN, DIAS_MAX + 1):
        d = hoje + timedelta(days=delta)
        if d.weekday() >= 5:            # sáb/dom
            continue
        for h in HORAS_CANDIDATAS:
            if (d.isoformat(), h) not in ocupados:
                return d, h
    return None, None


def falhou(status, data, passo):
    return status != 200 or (isinstance(data, dict) and "error" in data)


def consultar_cep(cep: str) -> dict:
    """Preenche rua/bairro/cidade/UF a partir do CEP (ViaCEP, público) — faz o que a tela do
    TI Saúde faz ao digitar o CEP, já que a API não preenche sozinha. Retorna {} se inválido."""
    import requests
    r = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=15)
    d = r.json() if r.status_code == 200 else {}
    if d.get("erro"):
        return {}
    return {"endereco": d.get("logradouro", "").upper(), "bairro": d.get("bairro", "").upper(),
            "cidade": d.get("localidade", "").upper(), "uf": d.get("uf", "")}


api = TiSaude(Path(__file__).resolve().parent / "relatorio-agendamento.md")
api.login()
print(f"modo: {'EXECUTAR (escreve em produção)' if EXECUTAR else 'SIMULAÇÃO (só leitura)'}")

# --- ocupação real → escolha do slot ---------------------------------------
hoje = date.today()
st, ag = api.get("Ocupação Dr. Lucas (janela do teste)", f"/agenda/{CAL_LUCAS}",
                 dataInicio=(hoje + timedelta(days=DIAS_MIN)).isoformat(),
                 dataFim=(hoje + timedelta(days=DIAS_MAX)).isoformat())
ocupados = {(a["data"], str(a.get("hora"))) for a in (ag if isinstance(ag, list) else [])
            if a.get("status") != -2 and not a.get("deletado")}
dia, hora = escolher_slot(ocupados)
if not dia:
    raise SystemExit("Nenhum slot livre na janela — ajuste DIAS_MIN/DIAS_MAX ou HORAS_CANDIDATAS")
cpf = gerar_cpf_valido()
print(f"slot escolhido: {dia:%d/%m/%Y} às {hora} (cal {CAL_LUCAS}, proc {PROC_EQUIPE})")
print(f"paciente: {PACIENTE['nome']} | CPF de teste {cpf}")

# --- CEP → endereço (como a tela faz) ---------------------------------------
via = consultar_cep(PACIENTE["cep"])
if not via:
    raise SystemExit(f"CEP {PACIENTE['cep']} inválido no ViaCEP")
PACIENTE.update(via)   # sobrescreve endereco/bairro/cidade/uf com o que o CEP retorna
print(f"ViaCEP {PACIENTE['cep']}: {via}")
with api.log_path.open("a", encoding="utf-8") as f:
    f.write(f"\n## ViaCEP {PACIENTE['cep']}\n`{via}`\n")

# --- dedup (leitura) --------------------------------------------------------
api.get("Dedup: GET /pacientes?busca=<cpf de teste>", "/pacientes", busca=cpf)
api.get("Dedup: GET /pacientes?celular=", "/pacientes", celular=PACIENTE["celular"])

if not EXECUTAR:
    print("\nSIMULAÇÃO concluída — nada foi escrito. Rode com --executar para os passos 6–9.")
    print(f"Relatório: {api.log_path}")
    sys.exit(0)

# ============================================================================
# A PARTIR DAQUI ESCREVE EM PRODUÇÃO
# ============================================================================

# --- 6. criar paciente ------------------------------------------------------
st, pac = api.post("6. POST /paciente/salvar (paciente de teste)", "/paciente/salvar",
                   {**PACIENTE, "cpf": cpf})
if falhou(st, pac, 6) or not pac.get("id"):
    raise SystemExit(f"Passo 6 falhou: {pac}")
id_pcte = pac["id"]
print(f"6. paciente criado: id {id_pcte}")

# --- 7. criar agendamento ---------------------------------------------------
body = {"idpcte": id_pcte, "idCalendario": CAL_LUCAS, "idProcedimentos": PROC_EQUIPE, "local": LOCAL,
        "data": dia.strftime("%d/%m/%Y"), "hora": hora, "observacoes": OBS}
st, agd = api.post("7. POST /agendamento/adicionar", "/agendamento/adicionar", body)
if falhou(st, agd, 7) or not agd.get("id"):
    raise SystemExit(f"Passo 7 falhou: {agd}")
id_agd = agd["id"]
print(f"7. agendamento criado: id {id_agd} | data {agd.get('data')} hora {agd.get('hora')} status {agd.get('status')}")

api.get(f"7b. GET /agendamento/{id_agd} (leitura de volta)", f"/agendamento/{id_agd}")
st, lst = api.get("7c. GET /agenda no dia (aparece na agenda?)", f"/agenda/{CAL_LUCAS}", data=dia.isoformat())
achou = any(a.get("id") == id_agd for a in (lst if isinstance(lst, list) else []))
print(f"7c. aparece na agenda do dia: {achou}")

# --- 8. confirmar e desmarcar -----------------------------------------------
st, r = api.post("8a. POST /agendamento/editar (status=3 confirmado)", f"/agendamento/editar/{id_agd}", {"status": 3})
print(f"8a. confirmar → status {r.get('status') if isinstance(r, dict) else r}")

# --- 9. conflito: 2º agendamento no mesmo slot ------------------------------
st, agd2 = api.post("9. POST /agendamento/adicionar no MESMO slot (teste de conflito)",
                    "/agendamento/adicionar", {**body, "observacoes": OBS + " - CONFLITO"})
id_agd2 = agd2.get("id") if isinstance(agd2, dict) else None
print(f"9. conflito: {'API ACEITOU (id ' + str(id_agd2) + ') — não bloqueia horário duplicado' if id_agd2 else 'API RECUSOU: ' + str(agd2)}")

# --- limpeza: desmarcar tudo ------------------------------------------------
st, r = api.post("8b. POST /agendamento/editar (status=-2 desmarcado)", f"/agendamento/editar/{id_agd}", {"status": -2})
print(f"8b. desmarcar → status {r.get('status') if isinstance(r, dict) else r}")
if id_agd2:
    api.post("9b. desmarca o agendamento de conflito", f"/agendamento/editar/{id_agd2}", {"status": -2})

api.get(f"final. GET /agendamento/{id_agd} (estado final)", f"/agendamento/{id_agd}")

with api.log_path.open("a", encoding="utf-8") as f:
    f.write(f"\n---\n## Resumo\n- paciente de teste id **{id_pcte}** (CPF {cpf}) — apagar pela interface do TI Saúde\n"
            f"- agendamento **{id_agd}** em {dia:%d/%m/%Y} {hora} → desmarcado\n"
            f"- conflito: {'aceito, id ' + str(id_agd2) + ' → desmarcado' if id_agd2 else 'recusado pela API'}\n")
print(f"\nRelatório: {api.log_path}")
