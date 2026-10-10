# -*- coding: utf-8 -*-
"""Testes unitários do cliente TI Saúde (HTTP simulado — não toca a produção)."""
import json
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from celeste.ferramentas import tisaude


class Resp:
    def __init__(self, dados, status=200):
        self._d, self.status_code = dados, status
        self.content = json.dumps(dados).encode()

    def json(self):
        return self._d


@pytest.fixture
def cli(monkeypatch):
    for k in ("TISAUDE_HASH", "TISAUDE_HASH_PACIENTE", "TISAUDE_LOGIN", "TISAUDE_SENHA"):
        monkeypatch.setenv(k, "x")
    tisaude.config.segredo.cache_clear()
    sess = MagicMock()
    c = tisaude.TiSaude(session=sess)
    c.token = "tok"
    return c, sess


def test_profissionais_mapeiam_calendario_e_procedimento():
    p = tisaude.profissionais()
    assert p["dra_luciana"].id_calendario == 1 and p["dra_luciana"].id_procedimento == 5
    assert p["dr_lucas"].id_calendario == 36 and p["dr_lucas"].id_procedimento == 264
    assert p["dr_lucas"].id_usuario == 79786


def test_criar_paciente_normaliza_e_usa_convenio(cli):
    c, sess = cli
    sess.request.side_effect = [Resp({"data": []}), Resp({"id": 1, "nome": "X"})]  # busca cpf, salvar
    c.criar_paciente({"nome": "ana silva", "cpf": "273.133.327-85", "nascimento": "01/01/1990", "sexo": "feminino",
                      "celular": "+55 (11) 99999-0000", "email": "a@b.com", "indicado": "google", "cep": "04131-000",
                      "n": "886", "apt": "ap 1", "endereco": "rua x", "bairro": "b", "cidade": "são paulo", "uf": "sp"})
    body = sess.request.call_args.kwargs["data"]
    assert body["nome"] == "ANA SILVA" and body["cpf"] == "27313332785" and body["celular"] == "11999990000"
    assert body["sexo"] == "Feminino" and body["convenio"] == 1 and "idConvenioCliente" not in body
    assert body["cidade"] == "SÃO PAULO" and body["uf"] == "SP"


def test_criar_paciente_recusa_campos_faltando(cli):
    c, _ = cli
    with pytest.raises(ValueError):
        c.criar_paciente({"nome": "x"})


def test_criar_paciente_nao_atualiza_existente(cli):
    c, sess = cli
    sess.request.return_value = Resp({"data": [{"id": 9, "cpf": "27313332785"}]})
    with pytest.raises(tisaude.TiSaudeErro):
        c.criar_paciente({"nome": "x", "cpf": "27313332785", "nascimento": "01/01/1990", "sexo": "Feminino", "celular": "11999990000",
                          "email": "a@b.com", "indicado": "GOOGLE", "cep": "04131000", "n": "1", "endereco": "r", "bairro": "b",
                          "cidade": "c", "uf": "SP"})


def test_buscar_horarios_desconta_ocupados_e_antecedencia(cli, monkeypatch):
    c, sess = cli
    hoje = datetime.now(tisaude.TZ).date()
    dia = hoje + timedelta(days=(7 - hoje.weekday()) % 7 or 7)  # próxima segunda
    monkeypatch.setitem(tisaude.config.parametros(), "feriados", [])   # o teste não depende do calendário de feriados
    sess.request.return_value = Resp([{"data": dia.isoformat(), "hora": "10:00:00", "status": 0, "deletado": 0}])
    sess.get.return_value = Resp([{"horario": "10:00:00"}, {"horario": "11:00:00"}, {"horario": "15:00:00"}])
    livres = c.buscar_horarios("dr_lucas", dias=(dia - hoje).days, a_partir_de=dia)
    horas = {(l["data"], l["hora"]) for l in livres}
    assert (dia.isoformat(), "11:00") in horas and (dia.isoformat(), "15:00") in horas
    assert (dia.isoformat(), "10:00") not in horas  # ocupado


def test_agendar_so_procedimentos_permitidos(cli):
    c, _ = cli
    with pytest.raises(ValueError):
        tisaude.config.procedimento_permitido(129)


def test_agendar_le_de_volta_e_valida(cli):
    c, sess = cli
    d = date(2026, 10, 27)
    sess.request.side_effect = [
        Resp([]),                                                   # ocupados no dia
        Resp({"id": 47186713}),                                     # adicionar
        Resp({"id": 47186713, "data": "2026-10-27", "hora": "17:00:00", "status": 0}),  # detalhe
    ]
    volta = c.agendar_consulta(id_paciente=6436, profissional_id="dr_lucas", data=d, hora="17:00", observacoes="teste")
    body = sess.request.call_args_list[1].kwargs["data"]
    assert body["idProcedimentos"] == 264 and body["idCalendario"] == 36 and body["data"] == "27/10/2026" and body["hora"] == "17:00:00"
    assert volta["status"] == 0


def test_editar_envia_payload_completo_com_convenio(cli):
    c, sess = cli
    atual = {"id": 1, "data": "2026-10-27", "hora": "17:00:00", "idPcte": 6436, "idCalendario": 36, "idProcedimento": 264,
             "local": 1, "obs": "x", "status": 0}
    sess.request.side_effect = [Resp(atual), Resp({"ok": 1}), Resp({**atual, "status": 3})]
    volta = c.confirmar_presenca(1)
    body = sess.request.call_args_list[1].kwargs["data"]
    assert body == {"data": "27/10/2026", "hora": "17:00:00", "idpcte": 6436, "idCalendario": 36, "idProcedimento": 264,
                    "local": 1, "observacoes": "x", "idConvenio": 1, "status": 3}
    assert volta["status"] == 3
