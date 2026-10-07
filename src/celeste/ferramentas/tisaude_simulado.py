# -*- coding: utf-8 -*-
"""TI Saúde em modo simulado: LÊ de verdade (pacientes, horários) e SIMULA as escritas (cadastro, agendamento, remarcação, cancelamento).

Usado para os números de teste da clínica: a Celeste segue o roteiro inteiro e oferece a agenda real, mas nada é gravado no TI Saúde.
"""
from __future__ import annotations

import logging
import random
from datetime import date

from celeste.ferramentas.tisaude import TiSaude

log = logging.getLogger(__name__)


class TiSaudeSimulado(TiSaude):
    """Mesma interface do cliente real; escritas devolvem ids fictícios (≥ 900000) e registram o que teria sido enviado."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.simulados: list[dict] = []

    def criar_paciente(self, dados: dict) -> dict:
        fake = {"id": random.randint(900000, 999999), "simulado": True}
        self.simulados.append({"acao": "criar_paciente", "dados": {k: v for k, v in dados.items() if k not in ("cpf", "cpf_responsavel")}, "retorno": fake})
        log.info("TI Saúde SIMULADO criar_paciente: %s", dados.get("nome"))
        return fake

    def atualizar_paciente(self, id_paciente: int, mudancas: dict) -> dict:
        proibidos = [k for k in mudancas if k in self.CAMPOS_IMUTAVEIS]
        if proibidos:
            raise ValueError(f"nome e CPF não podem ser alterados pela IA ({proibidos}); só a recepção faz isso")
        fake = {"id": id_paciente, "simulado": True}
        self.simulados.append({"acao": "atualizar_paciente", "dados": {"id": id_paciente, "campos": sorted(mudancas)}, "retorno": fake})
        log.info("TI Saúde SIMULADO atualizar_paciente %s: %s", id_paciente, sorted(mudancas))
        return fake

    def agendar_consulta(self, *, id_paciente: int, profissional_id: str, data: date, hora: str, observacoes: str) -> dict:
        fake = {"id": random.randint(900000, 999999), "status": 0, "data": data.strftime("%d/%m/%Y"), "hora": hora, "simulado": True}
        self.simulados.append({"acao": "agendar_consulta", "dados": {"id_paciente": id_paciente, "profissional": profissional_id,
                                                                      "data": data.isoformat(), "hora": hora}, "retorno": fake})
        log.info("TI Saúde SIMULADO agendar_consulta: %s %s %s", profissional_id, data, hora)
        return fake

    def reagendar(self, id_agendamento: int, data: date, hora: str) -> dict:
        fake = {"id": id_agendamento, "data": data.strftime("%d/%m/%Y"), "hora": hora, "simulado": True}
        self.simulados.append({"acao": "reagendar", "dados": {"id_agendamento": id_agendamento, "data": data.isoformat(), "hora": hora}, "retorno": fake})
        return fake

    def cancelar(self, id_agendamento: int, motivo: str = "") -> dict:
        self.simulados.append({"acao": "cancelar", "dados": {"id_agendamento": id_agendamento, "motivo": motivo}, "retorno": {"simulado": True}})
        return {"simulado": True}

    def confirmar_presenca(self, id_agendamento: int) -> dict:
        return {"simulado": True}
