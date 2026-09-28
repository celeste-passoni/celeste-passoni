# -*- coding: utf-8 -*-
"""Cliente do TI Saúde — as 7 operações validadas em produção (21–22/09/2026).

Regras aprendidas nos testes e garantidas aqui, não no prompt:
- `POST /paciente/salvar` e `POST /agendamento/editar` SUBSTITUEM o registro inteiro:
  nunca enviar payload parcial; `editar` sempre parte de um GET e reenvia tudo (+ idConvenio=1).
- Só os procedimentos autorizados (264 → calendário 36; 5 → calendário 1) podem ser agendados.
- `horasDisponiveis` (API do Paciente, id do USUÁRIO do profissional) já desconta os ocupados;
  ainda assim cruzamos com `GET /agenda` por proteção contra corrida e aplicamos antecedência mínima.
- Toda escrita é lida de volta.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests

from celeste.comum import config

log = logging.getLogger(__name__)
BASE = "https://app.tisaude.com/api"
TZ = ZoneInfo(config.FUSO)
STATUS_OCUPA = {0, 1, 2, 3, 4, 5}  # -1 falta e -2 desmarcado liberam o slot

STATUS = {0: "Marcado", 1: "Em espera", 2: "Atendido", 3: "Confirmado", 4: "Solicitado",
          5: "Em atendimento", -1: "Falta", -2: "Desmarcado"}


class TiSaudeErro(RuntimeError):
    pass


@dataclass
class Profissional:
    id: str              # 'dra_luciana' | 'dr_lucas'
    nome: str
    id_usuario: int      # para horasDisponiveis
    id_calendario: int   # para agenda/agendamento
    id_procedimento: int # 5 | 264
    valor_texto: str


def profissionais() -> dict[str, Profissional]:
    p = config.parametros()
    ids_usuario = p["ia"]["horarios"]["id_usuario_profissional"]
    out = {}
    for proc in p["procedimentos_permitidos"]:
        pid = "dra_luciana" if proc["idCalendario"] == 1 else "dr_lucas"
        c = config.profissional(pid)
        out[pid] = Profissional(pid, c["profissional"], int(ids_usuario[pid]), int(proc["idCalendario"]),
                                int(proc["id"]), c["valor_texto"])
    return out


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


class TiSaude:
    def __init__(self, session: Optional[requests.Session] = None):
        self.http = session or requests.Session()
        self.hash = config.segredo("TISAUDE_HASH")
        self.hash_pac = config.segredo("TISAUDE_HASH_PACIENTE")
        self.token: Optional[str] = None

    # ------------------------------------------------------------------ http
    def _login(self) -> None:
        r = self.http.post(f"{BASE}/login", params={"hash": self.hash},
                           json={"login": config.segredo("TISAUDE_LOGIN"), "senha": config.segredo("TISAUDE_SENHA"),
                                 "system": "web", "deviceToken": "celeste"}, timeout=60)
        dados = r.json() if r.content else {}
        if r.status_code != 200 or "access_token" not in dados:
            raise TiSaudeErro(f"login falhou: HTTP {r.status_code} {dados.get('error')}")
        self.token = dados["access_token"]

    def _q(self) -> dict:
        if not self.token:
            self._login()
        return {"hash": self.hash, "token": self.token}

    def _req(self, metodo: str, caminho: str, *, params=None, data=None, tentar_relogin=True) -> Any:
        q = {**self._q(), **(params or {})}
        r = self.http.request(metodo, f"{BASE}{caminho}", params=q, data=data, timeout=60)
        if r.status_code in (401, 403) and tentar_relogin:
            self.token = None
            return self._req(metodo, caminho, params=params, data=data, tentar_relogin=False)
        try:
            dados = r.json()
        except ValueError:
            raise TiSaudeErro(f"{metodo} {caminho}: resposta não-JSON HTTP {r.status_code}")
        if r.status_code != 200 or (isinstance(dados, dict) and "error" in dados):
            raise TiSaudeErro(f"{metodo} {caminho}: HTTP {r.status_code} {dados if isinstance(dados, dict) else ''}")
        return dados

    # ------------------------------------------------------------- pacientes
    def buscar_paciente(self, *, celular: str = "", cpf: str = "") -> Optional[dict]:
        """Busca por celular (só dígitos) e depois por CPF; devolve o primeiro encontrado ou None."""
        if celular:
            dados = self._req("GET", "/pacientes", params={"celular": _so_digitos(celular)[-11:]})
            for p in dados.get("data", []):
                return p
        if cpf:
            dados = self._req("GET", "/pacientes", params={"busca": _so_digitos(cpf)})
            for p in dados.get("data", []):
                if _so_digitos(p.get("cpf", "")) == _so_digitos(cpf):
                    return p
        return None

    def criar_paciente(self, dados: dict) -> dict:
        """Cria um paciente NOVO com todos os campos obrigatórios. Nunca use para atualizar.

        dados: nome, cpf, nascimento (dd/mm/AAAA), sexo (Masculino|Feminino), celular (só dígitos, com DDD),
        email, indicado, cep, n, apt, endereco, bairro, cidade, uf; opcionais para menor de idade:
        responsavel, parentesco_responsavel, cpf_responsavel.
        """
        obrig = ["nome", "cpf", "nascimento", "sexo", "celular", "email", "indicado", "cep", "n", "endereco",
                 "bairro", "cidade", "uf"]
        faltando = [k for k in obrig if not str(dados.get(k, "")).strip()]
        if faltando:
            raise ValueError(f"campos obrigatórios ausentes: {faltando}")
        if self.buscar_paciente(cpf=dados["cpf"]):
            raise TiSaudeErro("já existe paciente com este CPF; não atualizar via IA")
        payload = {
            "nome": dados["nome"].strip().upper(),
            "cpf": _so_digitos(dados["cpf"]),
            "nascimento": dados["nascimento"],
            "sexo": dados["sexo"].strip().capitalize(),
            "celular": _so_digitos(dados["celular"])[-11:],
            "email": dados["email"].strip(),
            "indicado": dados["indicado"].strip().upper(),
            "cep": _so_digitos(dados["cep"]),
            "n": str(dados["n"]).strip(),
            "apt": str(dados.get("apt", "")).strip(),
            "endereco": dados["endereco"].strip().upper(),
            "bairro": dados["bairro"].strip().upper(),
            "cidade": dados["cidade"].strip().upper(),
            "uf": dados["uf"].strip().upper(),
            "convenio": 1,  # PARTICULAR (campo correto; idConvenioCliente é ignorado)
        }
        for k in ("responsavel", "parentesco_responsavel", "cpf_responsavel"):
            if dados.get(k):
                payload[k] = dados[k]
        criado = self._req("POST", "/paciente/salvar", data=payload)
        if not criado.get("id"):
            raise TiSaudeErro(f"criar_paciente sem id: {criado}")
        return criado

    # --------------------------------------------------------------- horários
    def _grade_livre(self, prof: Profissional, dia: date) -> list[str]:
        r = self.http.get(f"{BASE}/rest/agenda/horasDisponiveis/{prof.id_usuario}",
                          params={"hash": self.hash_pac, "data": dia.isoformat()}, timeout=60)
        if r.status_code != 200:
            return []
        return sorted(x["horario"] for x in r.json())

    def _ocupados(self, prof: Profissional, de: date, ate: date) -> set[tuple[str, str]]:
        ag = self._req("GET", f"/agenda/{prof.id_calendario}", params={"dataInicio": de.isoformat(), "dataFim": ate.isoformat()})
        return {(a["data"], str(a["hora"])) for a in ag if a.get("status") in STATUS_OCUPA and not a.get("deletado")}

    def buscar_horarios(self, profissional_id: str, *, dias: Optional[int] = None, a_partir_de: Optional[date] = None) -> list[dict]:
        """Horários livres [{data, hora, profissional}] — grade real − ocupados − passado/antecedência."""
        cfg = config.parametros()["ia"]["horarios"]
        prof = profissionais()[profissional_id]
        agora = datetime.now(TZ)
        inicio = a_partir_de or (agora.date() if cfg.get("oferecer_hoje", True) else agora.date() + timedelta(days=1))
        fim = inicio + timedelta(days=dias or int(cfg.get("dias_a_frente", 14)))
        limite = agora + timedelta(hours=float(cfg.get("antecedencia_minima_horas", 2)))
        ocupados = self._ocupados(prof, inicio, fim)
        livres = []
        d = inicio
        while d <= fim:
            if d.weekday() < 5:
                for h in self._grade_livre(prof, d):
                    if (d.isoformat(), h) in ocupados:
                        continue
                    inicio_slot = datetime.combine(d, datetime.strptime(h, "%H:%M:%S").time(), TZ)
                    if inicio_slot < limite:
                        continue
                    livres.append({"data": d.isoformat(), "hora": h[:5], "profissional": profissional_id})
            d += timedelta(days=1)
        return livres

    # ------------------------------------------------------------ agendamento
    def agendar_consulta(self, *, id_paciente: int, profissional_id: str, data: date, hora: str, observacoes: str) -> dict:
        prof = profissionais()[profissional_id]
        config.procedimento_permitido(prof.id_procedimento)  # guarda-corpo: só 264 e 5
        hora_full = hora if len(hora) == 8 else f"{hora}:00"
        if (data.isoformat(), hora_full) in self._ocupados(prof, data, data):
            raise TiSaudeErro("horário acabou de ser ocupado")
        criado = self._req("POST", "/agendamento/adicionar", data={
            "idpcte": id_paciente, "idCalendario": prof.id_calendario, "idProcedimentos": prof.id_procedimento,
            "local": 1, "data": _br(data), "hora": hora_full, "observacoes": observacoes})
        if not criado.get("id"):
            raise TiSaudeErro(f"agendar sem id: {criado}")
        volta = self.detalhe_agendamento(criado["id"])
        if volta.get("data") != data.isoformat() or str(volta.get("hora")) != hora_full:
            raise TiSaudeErro(f"leitura de volta divergente: {volta}")
        return volta

    def detalhe_agendamento(self, id_agendamento: int) -> dict:
        return self._req("GET", f"/agendamento/{id_agendamento}")

    def _editar_completo(self, id_agendamento: int, **mudancas) -> dict:
        a = self.detalhe_agendamento(id_agendamento)
        d = a["data"]
        body = {"data": f"{d[8:]}/{d[5:7]}/{d[:4]}", "hora": a["hora"], "idpcte": a["idPcte"], "idCalendario": a["idCalendario"],
                "idProcedimento": a["idProcedimento"], "local": a.get("local") or 1, "observacoes": a.get("obs") or "",
                "idConvenio": 1, "status": a["status"]}
        body.update(mudancas)
        self._req("POST", f"/agendamento/editar/{id_agendamento}", data=body)
        return self.detalhe_agendamento(id_agendamento)

    def confirmar_presenca(self, id_agendamento: int) -> dict:
        return self._editar_completo(id_agendamento, status=3)

    def reagendar(self, id_agendamento: int, data: date, hora: str) -> dict:
        hora_full = hora if len(hora) == 8 else f"{hora}:00"
        return self._editar_completo(id_agendamento, data=_br(data), hora=hora_full, status=0)

    def cancelar(self, id_agendamento: int, motivo: str = "") -> dict:
        a = self.detalhe_agendamento(id_agendamento)
        obs = (a.get("obs") or "") + (f" | cancelado pela IA: {motivo}" if motivo else "")
        return self._editar_completo(id_agendamento, status=-2, observacoes=obs)

    def agenda(self, profissional_id: str, de: date, ate: date) -> list[dict]:
        prof = profissionais()[profissional_id]
        return self._req("GET", f"/agenda/{prof.id_calendario}", params={"dataInicio": de.isoformat(), "dataFim": ate.isoformat()})
