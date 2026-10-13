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


def _normalizar_nome(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def mesma_pessoa(nome_cadastro: str, nome_informado: str) -> bool:
    """Nome completo igual, ou primeiro nome igual (o lead costuma dar só o primeiro nome)."""
    a, b = _normalizar_nome(nome_cadastro), _normalizar_nome(nome_informado)
    if not a or not b:
        return False
    return a == b or a.split()[0] == b.split()[0]


def escolher_por_nome(lista: list[dict], nome: str) -> Optional[dict]:
    """Entre vários cadastros, o único cujo nome bate com o informado; None se nenhum ou mais de um."""
    if not nome:
        return None
    exatos = [p for p in lista if _normalizar_nome(p.get("nome") or "") == _normalizar_nome(nome)]
    if len(exatos) == 1:
        return exatos[0]
    parecidos = [p for p in lista if mesma_pessoa(p.get("nome") or "", nome)]
    return parecidos[0] if len(parecidos) == 1 else None


CONECTIVOS = {"de", "da", "do", "das", "dos", "e", "d"}


def nome_completo_valido(nome: str) -> tuple[bool, str]:
    """Nome completo sem abreviações: 2+ palavras, nenhuma com ponto, nenhuma de 1 letra (exceto conectivos)."""
    partes = [p for p in (nome or "").replace("  ", " ").strip().split(" ") if p]
    if len(partes) < 2:
        return False, "nome incompleto: peça nome e sobrenome completos"
    for p in partes:
        if "." in p or (len(p.strip("'")) == 1 and p.lower() not in CONECTIVOS):
            return False, f"'{p}' parece abreviação: a clínica exige o nome completo, sem abreviações (ex.: 'Maria A. Silva' não serve; precisa 'Maria Aparecida Silva')"
    return True, ""


def _iso_para_br(d: str) -> str:
    """'1990-01-01' (como o TI Saúde devolve) → '01/01/1990' (como ele exige na entrada)."""
    d = (d or "").strip()[:10]
    if len(d) == 10 and d[4] == "-" and d[7] == "-":
        return f"{d[8:10]}/{d[5:7]}/{d[0:4]}"
    return d


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
    def listar_por_celular(self, celular: str) -> list[dict]:
        """Todos os cadastros com este celular (um número da família pode estar em vários pacientes)."""
        dados = self._req("GET", "/pacientes", params={"celular": _so_digitos(celular)[-11:]})
        return [p for p in dados.get("data", []) if str(p.get("deletado") or "0") not in ("1", "True")]

    def buscar_por_cpf(self, cpf: str) -> Optional[dict]:
        """Busca exata por CPF (o parâmetro `busca` da API aceita CPF; conferimos dígito a dígito)."""
        cpf = _so_digitos(cpf)
        if len(cpf) != 11:
            return None
        dados = self._req("GET", "/pacientes", params={"busca": cpf})
        for p in dados.get("data", []):
            if _so_digitos(p.get("cpf") or "") == cpf:
                return p
        return None

    def buscar_paciente(self, *, celular: str = "", cpf: str = "", nome: str = "") -> Optional[dict]:
        """O CPF identifica a pessoa: se informado, decide sozinho (não cai para o celular, que pode ser de outra pessoa).
        Sem CPF: pelo celular; se o número tiver vários cadastros, escolhe pelo nome; se continuar ambíguo, None."""
        if cpf:
            return self.buscar_por_cpf(cpf)
        if celular:
            lista = self.listar_por_celular(celular)
            if len(lista) == 1:
                return lista[0]
            if len(lista) > 1:
                return escolher_por_nome(lista, nome)
        return None

    def criar_paciente(self, dados: dict) -> dict:
        """Cria um paciente NOVO com todos os campos obrigatórios. Nunca use para atualizar.

        dados: nome, cpf, nascimento (dd/mm/AAAA), sexo (Masculino|Feminino), celular (só dígitos, com DDD),
        email, indicado, cep, n, apt, endereco, bairro, cidade, uf; opcionais para menor de idade:
        responsavel, parentesco_responsavel, cpf_responsavel.
        """
        obrig = ["nome", "nascimento", "sexo", "celular", "email", "indicado", "cep", "n", "endereco",
                 "bairro", "cidade", "uf"]
        faltando = [k for k in obrig if not str(dados.get(k, "")).strip()]
        if faltando:
            raise ValueError(f"campos obrigatórios ausentes: {faltando}")
        cpf = _so_digitos(dados.get("cpf") or "")
        if cpf and self.buscar_paciente(cpf=cpf):
            raise TiSaudeErro("já existe paciente com este CPF; não atualizar via IA")
        payload = {
            "nome": dados["nome"].strip().upper(),
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
        if cpf:
            payload["cpf"] = cpf          # sem CPF (cadastro genérico) o campo é omitido: o TI Saúde cria pacientes distintos (testado 13/10/2026)
        for k in ("responsavel", "parentesco_responsavel", "cpf_responsavel"):
            if dados.get(k):
                payload[k] = dados[k]
        criado = self._req("POST", "/paciente/salvar", data=payload)
        if not criado.get("id"):
            raise TiSaudeErro(f"criar_paciente sem id: {criado}")
        return criado

    CAMPOS_IMUTAVEIS = ("nome",)   # testado 13/10/2026: CPF altera com id; nome NÃO altera pela API
    CAMPOS_EDITAVEIS = ("cpf", "nascimento", "sexo", "celular", "email", "indicado", "cep", "n", "apt", "endereco", "bairro", "cidade", "uf",
                        "responsavel", "parentesco_responsavel", "cpf_responsavel")
    _NAO_REENVIAR = {"id", "cliente", "status", "timestamp", "deletado", "idConvenio", "idConvenioCliente", "complemento", "data",
                     "profilepicture", "alteradoPor_idPacienteEmpresa", "idPacienteEmpresa", "idUsuario", "preenchidoPor", "medico",
                     "nascimento", "sexo", "apt", "convenio", "celular_whatsapp"}

    def dados_paciente(self, id_paciente: int) -> dict:
        return self._req("GET", f"/paciente/{int(id_paciente)}")

    def atualizar_paciente(self, id_paciente: int, mudancas: dict) -> dict:
        """Atualiza dados cadastrais de um paciente existente. NUNCA nome ou CPF.

        `POST /paciente/salvar` substitui o registro inteiro (campos ausentes são apagados), então lemos o cadastro
        atual, reenviamos tudo o que ele tem e aplicamos só as mudanças pedidas.
        """
        proibidos = [k for k in mudancas if k in self.CAMPOS_IMUTAVEIS]
        if proibidos:
            raise ValueError(f"o TI Saúde não permite alterar {proibidos} pela API; registre com sinalizar_revisao para a recepção corrigir")
        desconhecidos = [k for k in mudancas if k not in self.CAMPOS_EDITAVEIS]
        if desconhecidos:
            raise ValueError(f"campos não editáveis: {desconhecidos}")
        atual = self.dados_paciente(id_paciente)
        if not atual.get("id"):
            raise TiSaudeErro(f"paciente {id_paciente} não encontrado para atualizar")
        if _so_digitos(atual.get("cpf") or ""):           # cadastro excluído não aparece na busca; salvar nele criaria um duplicado
            ativo = self.buscar_por_cpf(atual["cpf"])
            if not ativo or int(ativo.get("id") or 0) != int(id_paciente):
                raise TiSaudeErro(f"cadastro {id_paciente} está inativo ou o CPF pertence a outro cadastro ativo; a recepção precisa resolver")
        if "cpf" in mudancas:                               # CPF novo: válido e não pode pertencer a outro paciente
            novo = _so_digitos(str(mudancas["cpf"]))
            if len(novo) != 11:
                raise ValueError("CPF deve ter 11 dígitos; peça ao lead para conferir")
            outro = self.buscar_por_cpf(novo)
            if outro and int(outro.get("id") or 0) != int(id_paciente):
                raise TiSaudeErro(f"este CPF já pertence a outro cadastro ({outro.get('nome')}); não alterar; registre com sinalizar_revisao")
            mudancas = {**mudancas, "cpf": novo}
        payload = {k: v for k, v in atual.items() if k not in self._NAO_REENVIAR and isinstance(v, (str, int)) and str(v).strip() != ""}
        if _so_digitos(atual.get("cpf") or ""):
            payload["cpf"] = _so_digitos(atual["cpf"])
        payload.update({
            "id": int(id_paciente),                   # com o id, o TI Saúde atualiza ESTE registro (sem id ele casa pelo CPF e pode criar outro)
            "nome": atual["nome"],
            "nascimento": _iso_para_br(atual.get("nascimento") or ""),
            "sexo": (atual.get("sexo") or "").strip().capitalize(),
            "apt": str(atual.get("complemento") or atual.get("apt") or "").strip(),
            "convenio": int(atual.get("idConvenio") or atual.get("idConvenioCliente") or 1),
        })
        for k, v in mudancas.items():
            v = str(v).strip()
            if k == "nascimento":
                if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", v):
                    raise ValueError("nascimento deve estar em dd/mm/AAAA")
            elif k == "sexo":
                v = v.capitalize()
                if v not in ("Masculino", "Feminino"):
                    raise ValueError("sexo deve ser Masculino ou Feminino")
            elif k == "nome":
                ok, motivo = nome_completo_valido(v)
                if not ok:
                    raise ValueError(motivo)
                v = v.strip().upper()
            elif k in ("celular", "cep", "cpf_responsavel"):
                v = _so_digitos(v)[-11:] if k == "celular" else _so_digitos(v)
            elif k in ("indicado", "endereco", "bairro", "cidade", "uf"):
                v = v.upper()
            payload[k] = v
        salvo = self._req("POST", "/paciente/salvar", data=payload)
        if not salvo.get("id"):
            raise TiSaudeErro(f"atualizar_paciente sem id: {salvo}")
        if int(salvo["id"]) != int(id_paciente):
            raise TiSaudeErro(f"o TI Saúde devolveu o id {salvo['id']} em vez de {id_paciente}: pode ter criado um cadastro duplicado; avisar a recepção")
        return salvo

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
        """Horários livres [{data, hora, profissional}] — grade real do TI Saúde − ocupados − passado/antecedência. Só a agenda decide os dias."""
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
            if True:   # a agenda do TI Saúde manda: sem filtro de fim de semana nem lista de feriados no código (decisão da clínica, 10/10/2026)
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
