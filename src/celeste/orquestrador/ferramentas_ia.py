# -*- coding: utf-8 -*-
"""Ferramentas que a Celeste pode chamar (schemas estritos) e sua execução.

Os guarda-corpos moram aqui e no cliente TI Saúde, não no prompt.
"""
from __future__ import annotations

import json
import re
import logging
from datetime import date, datetime, timezone
from typing import Any, Callable

from celeste.comum import config
from celeste.comum import consultas as cons
from celeste.ferramentas import tisaude as ts

log = logging.getLogger(__name__)

FERRAMENTAS: list[dict] = [
    {"name": "buscar_paciente", "description": "Procura o lead no TI Saúde pelo CPF (identificação exata) ou, sem CPF, pelo nome completo entre os cadastros deste telefone. Use sempre que o lead disser que já tem cadastro ou informar o CPF, inclusive quando o contexto disser que o número está no cadastro de outra pessoa: o CPF decide quem é. A busca só pelo telefone já foi feita pelo sistema.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "cpf": {"type": "string", "description": "CPF informado pelo lead (11 dígitos, com ou sem pontuação); vazio se não informou"},
         "nome_completo": {"type": "string", "description": "nome completo informado pelo lead, para desempatar quando o telefone tem vários cadastros; vazio se não tiver"}},
         "required": ["cpf", "nome_completo"], "additionalProperties": False}},
    {"name": "criar_paciente", "description": "Cria o cadastro de UM paciente no TI Saúde. Um cadastro por pessoa: se o lead agenda para ele e para outra pessoa (o filho, por exemplo), cada um tem o seu, com os dados dele; nunca reaproveite dados ou cadastro de uma pessoa para outra. Só chame com TODOS os campos coletados; nunca para quem já existe.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "nome": {"type": "string"}, "cpf": {"type": "string"}, "nascimento": {"type": "string", "description": "dd/mm/AAAA"},
         "sexo": {"type": "string", "enum": ["Masculino", "Feminino"]}, "email": {"type": "string"},
         "como_conheceu": {"type": "string", "description": "valor do sistema para 'Encaminhado por' (ex.: CAMPANHA DE MENSAGENS, INSTAGRAM DRA. LUCIANA, GOOGLE)"},
         "cep": {"type": "string"}, "numero": {"type": "string"}, "complemento": {"type": "string"},
         "responsavel": {"type": "string", "description": "nome do responsável se menor de idade; senão vazio"},
         "parentesco_responsavel": {"type": "string", "description": "Mãe, Pai, Irmão, Irmã, Tio, Tia, Padrinho, Madrinha, Primo, Prima, Outro ou vazio"},
         "cpf_responsavel": {"type": "string"},
         "dados_genericos": {"type": "boolean", "description": "true SÓ quando o lead, depois de você insistir UMA vez, manteve que não quer passar os dados. O sistema preenche nascimento, e-mail, encaminhado por e endereço com os genéricos da clínica e deixa o CPF vazio; você informa só nome completo e sexo (deduza pelo nome)."}},
         "required": ["nome", "cpf", "nascimento", "sexo", "email", "como_conheceu", "cep", "numero", "complemento", "responsavel", "parentesco_responsavel", "cpf_responsavel", "dados_genericos"],
         "additionalProperties": False}},
    {"name": "atualizar_cadastro", "description": "Atualiza dados cadastrais do paciente já identificado nesta conversa, a pedido dele: CPF, e-mail, celular, data de nascimento, sexo, endereço por CEP/número/complemento, como conheceu, responsável. Nome o TI Saúde não deixa alterar pela API: se o lead pedir, registre com sinalizar_revisao para a recepção corrigir e siga normalmente. Deixe vazios os campos que não mudam.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "cpf": {"type": "string", "description": "novo CPF (11 dígitos); vazio se não muda"},
         "email": {"type": "string"}, "celular": {"type": "string", "description": "novo celular com DDD; vazio se não muda"},
         "nascimento": {"type": "string", "description": "dd/mm/AAAA; vazio se não muda"},
         "sexo": {"type": "string", "enum": ["Masculino", "Feminino", ""]},
         "cep": {"type": "string", "description": "novo CEP (o endereço é preenchido pelo sistema); vazio se não muda"},
         "numero": {"type": "string", "description": "número da residência; obrigatório se o CEP mudou"},
         "complemento": {"type": "string"},
         "como_conheceu": {"type": "string", "description": "valor do sistema para 'Encaminhado por'; vazio se não muda"},
         "responsavel": {"type": "string"}, "parentesco_responsavel": {"type": "string"}, "cpf_responsavel": {"type": "string"},
         "id_paciente": {"type": "integer", "description": "id do paciente a alterar, um dos pacientes desta conversa (veja o contexto); 0 = o próprio lead"}},
         "required": ["cpf", "email", "celular", "nascimento", "sexo", "cep", "numero", "complemento", "como_conheceu", "responsavel", "parentesco_responsavel", "cpf_responsavel", "id_paciente"],
         "additionalProperties": False}},
    {"name": "buscar_horarios", "description": "Devolve ATÉ 2 horários LIVRES de consulta para UM profissional, do dia pedido (a_partir_de) ou, se esse dia não tiver vaga, do dia mais próximo com vaga (campo dia_pedido_sem_vaga). Só chame depois de saber com quem o lead quer (Dra. Luciana ou Dr. Lucas) e qual dia da semana fica melhor para ele; se não souber, pergunte antes. Uma chamada por resposta, nunca para os dois profissionais de uma vez. Ofereça só os horários devolvidos.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "profissional": {"type": "string", "enum": ["dra_luciana", "dr_lucas"]},
         "a_partir_de": {"type": "string", "description": "AAAA-MM-DD ou vazio para a partir de hoje"},
         "dias": {"type": "integer", "description": "quantos dias à frente (1 a 30)"}},
         "required": ["profissional", "a_partir_de", "dias"], "additionalProperties": False}},
    {"name": "agendar_consulta", "description": "Agenda UMA Consulta no TI Saúde em um horário que veio de buscar_horarios, para UM paciente desta conversa (id de buscar_paciente ou criar_paciente). Uma consulta por chamada; cada paciente tem no máximo uma consulta ativa (para mudar a data de quem já tem, use reagendar). Para outra pessoa, primeiro o cadastro dela.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "id_paciente": {"type": "integer"}, "profissional": {"type": "string", "enum": ["dra_luciana", "dr_lucas"]},
         "data": {"type": "string", "description": "AAAA-MM-DD"}, "hora": {"type": "string", "description": "HH:MM"}},
         "required": ["id_paciente", "profissional", "data", "hora"], "additionalProperties": False}},
    {"name": "consultar_agendamento", "description": "Lê no TI Saúde o estado REAL das consultas desta conversa (data, hora, profissional, paciente, status). Chame SEMPRE que o lead falar de consulta marcada (quando é, confirmar, trocar, desmarcar, 'está marcada?') ANTES de responder; nunca afirme nada sobre agendamento sem ela. Com mais de uma consulta na conversa e o lead sem dizer de qual fala, devolva todas (id_agendamento 0) e PERGUNTE qual (pelo nome do paciente e a data) antes de confirmar, remarcar ou cancelar.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "id_agendamento": {"type": "integer", "description": "id de uma consulta desta conversa (veja o contexto); 0 = todas"}},
         "required": ["id_agendamento"], "additionalProperties": False}},
    {"name": "reagendar", "description": "Muda data/hora de UMA consulta que a Celeste agendou nesta conversa (id_agendamento do contexto). Com mais de uma consulta e o lead sem dizer qual, pergunte antes. O novo horário deve vir de buscar_horarios, do mesmo profissional.",
     "strict": True, "input_schema": {"type": "object", "properties": {"id_agendamento": {"type": "integer"}, "data": {"type": "string"}, "hora": {"type": "string"}},
                                      "required": ["id_agendamento", "data", "hora"], "additionalProperties": False}},
    {"name": "confirmar_presenca", "description": "Confirma a presença em UMA consulta que a Celeste agendou nesta conversa (status Confirmado no TI Saúde). Use quando o lead escrever que confirma (o botão 'Confirmar presença' o sistema trata sozinho). Com mais de uma consulta e o lead sem dizer qual, pergunte antes.",
     "strict": True, "input_schema": {"type": "object", "properties": {"id_agendamento": {"type": "integer"}},
                                      "required": ["id_agendamento"], "additionalProperties": False}},
    {"name": "cancelar", "description": "Desmarca UMA consulta que a Celeste agendou nesta conversa (id_agendamento do contexto; com mais de uma e o lead sem dizer qual, pergunte antes). SÓ pode ser chamada depois de UMA tentativa: você ofereceu uma alternativa (remarcar, Dr. Lucas, esclarecer a dúvida) em uma mensagem e o lead respondeu que quer cancelar mesmo assim. Nunca uma segunda tentativa. Chamar antes da alternativa devolve erro.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "id_agendamento": {"type": "integer"},
         "motivo_do_lead": {"type": "string", "description": "o motivo que o LEAD disse, com as palavras dele (ex.: 'vai viajar na data', 'achou caro'); vazio se ele não disse"},
         "solucao_oferecida": {"type": "string", "description": "o que você ofereceu para resolver o motivo (ex.: 'remarcar para sexta 10h ou 15h')"},
         "lead_confirmou_apos_solucao": {"type": "boolean", "description": "true só se o lead, DEPOIS de ouvir a solução, repetiu que quer cancelar"}},
         "required": ["id_agendamento", "motivo_do_lead", "solucao_oferecida", "lead_confirmou_apos_solucao"], "additionalProperties": False}},
    {"name": "encaminhar_recepcao", "description": "Encerra a conversa encaminhando o lead à recepção humana (só nos 4 motivos permitidos). Avisa a equipe pelo WhatsApp com um resumo.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "motivo": {"type": "string", "enum": ["paciente_em_tratamento", "assunto_clinico", "reclamacao_reembolso", "pediu_pessoa"]},
         "resumo": {"type": "string", "description": "3 linhas para a recepção: quem é, o que quer, o que já foi dito"}},
         "required": ["motivo", "resumo"], "additionalProperties": False}},
    {"name": "registrar_opt_out", "description": "Marca que o lead não quer mais receber mensagens. Encerra a conversa.",
     "strict": True, "input_schema": {"type": "object", "properties": {"motivo": {"type": "string"}}, "required": ["motivo"], "additionalProperties": False}},
    {"name": "enviar_video", "description": "Envia um dos vídeos da clínica ao lead (uma vez por conversa cada). Quando o lead pede resultados/casos/antes e depois, o vídeo vem ANTES da foto: resultado_alopecia_androgenetica, depois resultado_androgenetica_masculina, depois caso_bruna_1_primeira_consulta + caso_bruna_2_resultado; transplante → resultado_transplante_capilar. Um por pedido; mais só se ele pedir.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "video": {"type": "string", "enum": list(config.parametros()["videos"].keys())},   # catálogo = bloco `videos` do YAML
         "reenviar": {"type": "boolean", "description": "true só quando o lead CONFIRMOU que quer receber de novo um vídeo já enviado"}},
         "required": ["video", "reenviar"], "additionalProperties": False}},
    {"name": "enviar_antes_e_depois", "description": "Envia ao lead UMA foto real de antes e depois de um caso daquela doença tratado na clínica (com legenda e aviso de que resultados variam). Resultado é VÍDEO primeiro (enviar_video): use esta foto só se o lead pediu FOTO explicitamente ou se a doença não tem vídeo de resultado (areata, seborreica, fibrosante, psoríase etc.). SÓ depois de o lead PEDIR para ver resultados/casos, ou DIZER SIM à sua oferta. Nunca por conta própria. Se ele pedir mais, chame de novo e sai a próxima foto. A foto sai logo depois do seu PRIMEIRO balão e o resto da sua resposta vem depois dela; não diga que já enviou.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "doenca": {"type": "string", "enum": ["dermatite_seborreica", "psoriase_couro_cabeludo", "alopecia_areata", "alopecia_fibrosante_frontal",
                                                "lupus_couro_cabeludo", "alopecia_por_tracao", "foliculite_decalvante", "foliculite_dissecante",
                                                "liquen_plano_pilar", "alopecia_androgenetica_masculina", "alopecia_androgenetica_feminina",
                                                "efluvio_anageno", "tricotilomania", "disturbios_da_haste", "efluvio_telogeno"]}},
         "required": ["doenca"], "additionalProperties": False}},
    {"name": "enviar_antes_e_depois_tratamento", "description": "Envia UMA foto real de antes e depois de um TRATAMENTO/tecnologia da clínica (com legenda dizendo que o tratamento é definido na consulta). Resultado é VÍDEO primeiro (enviar_video com resultado_alopecia_androgenetica etc.): use esta foto só se o lead pediu FOTO explicitamente ou citou um tratamento pelo nome. 'geral' só quando ele pediu FOTO sem dizer de quê. SÓ depois de o lead PEDIR para ver fotos/resultados, ou DIZER SIM à sua oferta. Perguntar 'que tratamentos vocês fazem' NÃO é pedido de foto: responda em texto e, no máximo, ofereça. Nunca para sugerir tratamento ao caso dele. Se ele pedir mais, chame de novo e sai a próxima. A foto sai logo depois do seu PRIMEIRO balão e o resto da resposta vem depois dela.",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "tratamento": {"type": "string", "enum": list(config.parametros()["antes_e_depois_tratamentos"]["tratamentos"].keys()) + ["geral"]}},
         "required": ["tratamento"], "additionalProperties": False}},
    {"name": "sinalizar_revisao", "description": "Marca a conversa para a equipe revisar quando o lead perguntou algo que NÃO está na base de conhecimento (você não inventa a resposta). Registre a dúvida exata.",
     "strict": True, "input_schema": {"type": "object", "properties": {"duvida": {"type": "string", "description": "a pergunta do lead que ficou sem resposta na base"}},
                                      "required": ["duvida"], "additionalProperties": False}},
    {"name": "atualizar_status", "description": "Registra o resultado da conversa quando ela chega a um desfecho sem agendamento (ex.: Irá nos retornar, Achou caro).",
     "strict": True, "input_schema": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["Irá nos retornar", "Vamos retornar na data solicitada", "Achou caro", "Quer pelo convênio",
                                                "Mora em outro Estado", "Mora em outro País", "Está em outra clínica", "Receiteiro"]},
         "data_retorno": {"type": "string", "description": "AAAA-MM-DD se o lead pediu uma data; AAAA-MM-DDTHH:MM (hora de São Paulo) se ele pediu uma hora ('me chama às 11h30'); senão vazio"}},
         "required": ["status", "data_retorno"], "additionalProperties": False}},
]


def proxima_foto(bloco: dict, slug: str, enviadas: list, geral: list | None = None):
    """(slug, arquivo) da próxima foto ainda não enviada; 'geral' percorre os tratamentos da lista `geral`. None se acabou."""
    ordem = list(geral or []) if slug == "geral" else [slug]
    for s in ordem:
        for a in (bloco.get(s) or {}).get("arquivos", []):
            if a not in enviadas:
                return s, a
    return None


def selecionar_opcoes(livres: list, n: int = 2) -> list:
    """Até n horários para oferecer (22/10/2026, pedido da clínica): os n primeiros do primeiro dia com vaga; se esse dia
    tiver menos que n, completa em ordem com os dias seguintes. Antes era 2 do 1º dia + 1 do 2º."""
    return list(livres)[:n]


class Contexto:
    """Estado da conversa disponível às ferramentas (injetado pelo orquestrador)."""
    def __init__(self, conversa: dict, telefone: str, tisaude: ts.TiSaude, viacep: Callable[[str], dict],
                 enviar_video: Callable[[str], str], avisar_recepcao: Callable[[str, str], None], atualizar: Callable[[dict], None],
                 enviar_imagem: "Callable[[str], str] | None" = None):
        self.conversa, self.telefone, self.ts = conversa, telefone, tisaude
        self.viacep, self.enviar_video, self.avisar_recepcao, self.atualizar = viacep, enviar_video, avisar_recepcao, atualizar
        self.enviar_imagem = enviar_imagem or (lambda chave: "sem-envio-de-imagem")
        self.encerrar = False


def _mesma_pessoa(nome_cadastro: str, nome_informado: str) -> bool:
    from celeste.ferramentas.tisaude import mesma_pessoa
    return mesma_pessoa(nome_cadastro, nome_informado)


def _nome_completo_valido(nome: str) -> tuple[bool, str]:
    from celeste.ferramentas.tisaude import nome_completo_valido
    return nome_completo_valido(nome)


def _gravar(ctx: "Contexto", campos: dict) -> None:
    ctx.conversa.update(campos)
    ctx.atualizar(campos)


def _registrar_paciente(ctx: "Contexto", id_paciente: int, nome: str | None, confirmado: bool = True) -> None:
    """Põe o paciente na lista da conversa (27/10/2026). O paciente principal (quem fala no WhatsApp) só muda se ainda não
    houver um confirmado; senão é uma segunda pessoa (o filho, por exemplo) e entra só na lista."""
    conv = ctx.conversa
    campos: dict = {"pacientes": cons.com_paciente(cons.pacientes(conv), id_paciente, nome)}
    atual = conv.get("id_paciente_tisaude")
    if not atual or not conv.get("identidade_confirmada") or int(atual) == int(id_paciente):
        campos.update({"id_paciente_tisaude": id_paciente, "paciente_tisaude_nome": nome, "identidade_confirmada": bool(confirmado or conv.get("identidade_confirmada"))})
    _gravar(ctx, campos)


def _ids_pacientes(conv: dict) -> set[int]:
    ids = {int(p["id"]) for p in cons.pacientes(conv) if p.get("id")}
    if conv.get("id_paciente_tisaude"):
        ids.add(int(conv["id_paciente_tisaude"]))
    return ids


def _consulta_da_conversa(ctx: "Contexto", id_agendamento: int) -> tuple[list[dict], dict]:
    cs = cons.lista(ctx.conversa)
    c = cons.achar(cs, id_agendamento)
    if not c:
        ativas = cons.ativas(cs)
        lista = "; ".join(f"id {x['id_agendamento']}: {cons.rotulo(x)}" for x in ativas) or "nenhuma"
        raise ValueError(f"o id_agendamento {id_agendamento} não é de uma consulta desta conversa. Consultas ativas: {lista}")
    return cs, c


def executar(nome: str, entrada: dict, ctx: Contexto) -> tuple[str, bool]:
    """Executa a ferramenta; retorna (resultado_json, is_error)."""
    try:
        r = _executar(nome, entrada, ctx)
        return json.dumps(r, ensure_ascii=False, default=str), False
    except Exception as e:  # o modelo recebe o erro e explica ao lead com naturalidade
        log.warning("ferramenta %s falhou: %s", nome, e)
        return json.dumps({"erro": str(e)}, ensure_ascii=False), True


def _executar(nome: str, e: dict, ctx: Contexto) -> Any:
    if nome == "buscar_paciente":
        cpf = re.sub(r"\D", "", e.get("cpf") or "")
        nome_c = (e.get("nome_completo") or "").strip()
        if cpf:
            if len(cpf) != 11:
                raise ValueError("CPF deve ter 11 dígitos; peça ao lead para conferir")
            p = ctx.ts.buscar_paciente(cpf=cpf)
            if not p:
                return {"encontrado": False, "aviso": "nenhum paciente com este CPF; confira os dígitos com o lead e, se estiverem certos, faça o pré-cadastro e chame criar_paciente"}
        elif nome_c:
            p = ctx.ts.buscar_paciente(celular=ctx.telefone, nome=nome_c)
            if not p:
                return {"encontrado": False, "aviso": "não localizei com segurança pelo nome; peça o CPF ao lead e chame buscar_paciente de novo"}
        else:
            raise ValueError("informe o CPF (ou o nome completo) do lead")
        _registrar_paciente(ctx, p["id"], p.get("nome"))
        _gravar(ctx, {"pacientes_mesmo_numero": []})
        return {"encontrado": True, "id": p["id"], "nome": p.get("nome"), "aviso": "é este o paciente; use este id para agendar"}

    if nome == "atualizar_cadastro":
        idp = int(e.get("id_paciente") or 0) or ctx.conversa.get("id_paciente_tisaude")
        if idp and int(idp) not in _ids_pacientes(ctx.conversa):
            raise ValueError("este id_paciente não é de um paciente desta conversa; use o id do contexto")
        if not idp:
            raise ValueError("paciente ainda não identificado: localize pelo CPF (buscar_paciente) antes de alterar o cadastro")
        if ctx.conversa.get("pacientes_mesmo_numero") and not ctx.conversa.get("identidade_confirmada"):
            raise ValueError("este número tem vários cadastros: confirme a identidade pelo CPF (buscar_paciente) antes de alterar")
        mapa = {"cpf": "cpf", "email": "email", "celular": "celular", "nascimento": "nascimento", "sexo": "sexo", "como_conheceu": "indicado",
                "complemento": "apt", "numero": "n", "responsavel": "responsavel", "parentesco_responsavel": "parentesco_responsavel",
                "cpf_responsavel": "cpf_responsavel"}
        mud = {mapa[k]: str(v).strip() for k, v in e.items() if k in mapa and k != "id_paciente" and str(v or "").strip()}
        if str(e.get("cep") or "").strip():
            end = ctx.viacep(e["cep"])
            if not end:
                raise ValueError("CEP inválido: peça ao lead para conferir o CEP")
            if not str(e.get("numero") or "").strip():
                raise ValueError("CEP novo exige o número da residência")
            mud.update({"cep": e["cep"], **end})
        if not mud:
            raise ValueError("nenhum campo para atualizar")
        r = ctx.ts.atualizar_paciente(int(idp), mud)
        campos_conv = {"cadastro_atualizado_em": datetime.now(timezone.utc), "cadastro_campos_atualizados": sorted(mud)}
        if "nome" in mud and int(idp) == int(ctx.conversa.get("id_paciente_tisaude") or 0):
            campos_conv["nome"] = mud["nome"]
        if "cpf" in mud and ctx.conversa.get("cadastro_generico"):
            campos_conv["cadastro_generico"] = False
        ctx.atualizar(campos_conv)
        return {"ok": True, "atualizado": sorted(mud), "id": r.get("id", idp), "aviso": "cadastro atualizado; confirme ao lead o que foi alterado"}

    if nome == "criar_paciente":
        ok, motivo = _nome_completo_valido(e["nome"])
        if not ok:
            raise ValueError(motivo)
        if e.get("dados_genericos"):
            g = config.parametros().get("cadastro_generico") or {}
            e = {**e, "cpf": g.get("cpf", "") or "", "nascimento": e.get("nascimento") or g.get("nascimento", ""), "email": g.get("email", ""),
                 "como_conheceu": g.get("indicado", ""), "cep": g.get("cep", ""), "numero": g.get("numero", ""), "complemento": g.get("complemento", "")}
        elif not re.sub(r"\D", "", e.get("cpf") or ""):
            raise ValueError("CPF não informado: peça o CPF; só cadastre sem CPF com dados_genericos=true, depois de o lead recusar os dados após UMA insistência")
        # 27/10/2026: só reaproveita um cadastro se for da MESMA pessoa (pelo nome). Antes, "identidade confirmada" bastava,
        # e o cadastro do filho podia cair no do pai que estava falando.
        for p in cons.pacientes(ctx.conversa):
            if p.get("nome") and _mesma_pessoa(p["nome"], e["nome"]):
                return {"id": p["id"], "aviso": f"{p['nome']} já tem cadastro nesta conversa; use este id"}
        if ctx.conversa.get("id_paciente_tisaude") and _mesma_pessoa(ctx.conversa.get("paciente_tisaude_nome") or "", e["nome"]):
            return {"id": ctx.conversa["id_paciente_tisaude"], "aviso": "paciente já existia; use este id"}
        end = ctx.viacep(e["cep"])
        if not end:
            raise ValueError("CEP inválido: peça ao lead para conferir o CEP")
        if _menor(e["nascimento"]) and not (e.get("responsavel") and e.get("cpf_responsavel")):
            raise ValueError("menor de idade: colete nome, parentesco e CPF do responsável antes de cadastrar")
        existente = ctx.ts.buscar_paciente(cpf=e["cpf"]) if re.sub(r"\D", "", e.get("cpf") or "") else None   # CPF já cadastrado: adota em vez de duplicar
        if isinstance(existente, dict) and existente.get("id"):
            _registrar_paciente(ctx, existente["id"], existente.get("nome"))
            return {"id": existente["id"], "aviso": f"este CPF já está cadastrado como {existente.get('nome')}; use este id para agendar (não criei cadastro novo)"}
        p = ctx.ts.criar_paciente({"nome": e["nome"], "cpf": e["cpf"], "nascimento": e["nascimento"], "sexo": e["sexo"],
                                   "celular": ctx.telefone, "email": e["email"], "indicado": e["como_conheceu"], "cep": e["cep"],
                                   "n": e["numero"], "apt": e.get("complemento", ""), **end,
                                   "responsavel": e.get("responsavel", ""), "parentesco_responsavel": e.get("parentesco_responsavel", ""),
                                   "cpf_responsavel": e.get("cpf_responsavel", "")})
        era_o_primeiro = not cons.pacientes(ctx.conversa)
        _registrar_paciente(ctx, p["id"], e["nome"])
        extra: dict = {"cadastro_generico": bool(e.get("dados_genericos"))}
        contato = cons.primeiro_nome(ctx.conversa.get("nome"))
        if era_o_primeiro and (not contato or contato.lower() == cons.primeiro_nome(e["nome"]).lower()):
            extra["nome"] = e["nome"]   # nome completo de quem fala; o cadastro de outra pessoa não troca o nome da conversa
        _gravar(ctx, extra)
        if e.get("dados_genericos"):
            return {"id": p["id"], "aviso": "cadastro feito com dados genéricos e sem CPF; depois de agendar, avise o lead: " + str((config.parametros().get("cadastro_generico") or {}).get("aviso_ao_lead", ""))}
        return {"id": p["id"]}

    if nome == "buscar_horarios":
        inicio = date.fromisoformat(e["a_partir_de"]) if e.get("a_partir_de") else None
        dias = max(1, min(int(e.get("dias") or 14), 30))
        livres = ctx.ts.buscar_horarios(e["profissional"], dias=dias, a_partir_de=inicio)
        from celeste.comum import config as _cfg
        n = int(((_cfg.parametros().get("ia") or {}).get("horarios") or {}).get("opcoes_por_vez", 3))
        oferecer = selecionar_opcoes(livres, n)   # 22/10/2026: 2 horários do dia pedido (antes 3; em 14/10 a Celeste listava 12)
        sem_vaga_no_dia = bool(inicio) and bool(oferecer) and oferecer[0]["data"] != inicio.isoformat()
        ja = list(ctx.conversa.get("horarios_oferecidos") or [])
        novos = [f"{l['data']} {l['hora']}" for l in oferecer if f"{l['data']} {l['hora']}" not in ja]
        ctx.conversa["horarios_oferecidos"] = (ja + novos)[-60:]
        ctx.atualizar({"horarios_oferecidos": ctx.conversa["horarios_oferecidos"]})
        return {"profissional": e["profissional"], "livres": oferecer, "ha_mais_no_periodo": len(livres) > len(oferecer),
                "dia_pedido_sem_vaga": sem_vaga_no_dia,
                "aviso": "ofereça só estes; se o lead quiser outro dia ou horário, chame de novo com a_partir_de"
                         + ("; o dia pedido não tem vaga: avise em uma frase e ofereça estes, do dia mais próximo" if sem_vaga_no_dia else "")}

    if nome == "agendar_consulta":
        chave = f"{e['data']} {e['hora']}"
        if chave not in (ctx.conversa.get("horarios_oferecidos") or []):
            raise ValueError("horário não veio de buscar_horarios; chame buscar_horarios e ofereça só o que está livre")
        idp = int(e["id_paciente"])
        if idp not in _ids_pacientes(ctx.conversa):
            raise ValueError("este id_paciente não é de um paciente desta conversa: identifique (buscar_paciente) ou cadastre (criar_paciente) a pessoa antes")
        cs = cons.lista(ctx.conversa)
        ja = [c for c in cons.ativas(cs) if int(c.get("id_paciente") or 0) == idp]
        if ja:
            raise ValueError(f"este paciente já tem consulta ativa ({cons.rotulo(ja[0])}, id_agendamento {ja[0]['id_agendamento']}); "
                             "uma consulta por paciente: para mudar a data, use reagendar")
        obs = f"Agendado pela Celeste (IA) via WhatsApp | frente {ctx.conversa.get('frente')} | conversa {ctx.conversa.get('id')}"
        a = ctx.ts.agendar_consulta(id_paciente=idp, profissional_id=e["profissional"],
                                    data=date.fromisoformat(e["data"]), hora=e["hora"], observacoes=obs)
        agora = datetime.now(timezone.utc)
        nova = {"id_agendamento": int(a["id"]), "id_paciente": idp,
                "paciente_nome": cons.nome_do_paciente(ctx.conversa, idp) or ctx.conversa.get("paciente_tisaude_nome") or ctx.conversa.get("nome") or "",
                "profissional": e["profissional"], "data": e["data"], "hora": e["hora"], "status": "Marcado", "agendado_em": agora, "rotinas": {}}
        cs.append(nova)
        restantes = [h for h in (ctx.conversa.get("horarios_oferecidos") or []) if h != chave]   # o mesmo horário não serve para a próxima pessoa
        _gravar(ctx, {**cons.campos(cs), "status": "Agendado", "agendado_em": agora, "horarios_oferecidos": restantes})
        return {"id_agendamento": a["id"], "paciente": nova["paciente_nome"], "data": e["data"], "hora": e["hora"], "status": ts.STATUS.get(a.get("status")),
                "consultas_ativas_na_conversa": len(cons.ativas(cs))}

    if nome == "consultar_agendamento":
        cs = cons.lista(ctx.conversa)
        alvo = int(e.get("id_agendamento") or 0)
        if not cs:
            return {"agendada": False, "aviso": "não há consulta agendada nesta conversa"}
        if alvo:
            cs_alvo = [_consulta_da_conversa(ctx, alvo)[1]]
        else:   # todas as que ainda podem estar ativas (as já desmarcadas não precisam de nova leitura)
            cs_alvo = cons.ativas(cs) or cs[-1:]
        cal = {36: "dr_lucas", 1: "dra_luciana"}
        saida = []
        for c in cs_alvo:
            d = ctx.ts.detalhe_agendamento(int(c["id_agendamento"]))
            prof = cal.get(d.get("idCalendario"), c.get("profissional"))
            status = "Desmarcado" if (d.get("deletado") or d.get("status") == -2) else ts.STATUS.get(d.get("status"), str(d.get("status")))
            c = dict(c, data=str(d.get("data") or c.get("data") or "")[:10], hora=str(d.get("hora") or c.get("hora") or "")[:5], profissional=prof, status=status)
            cs = cons.substituir(cs, c)
            saida.append({"id_agendamento": int(c["id_agendamento"]), "paciente": c.get("paciente_nome") or "", "data": c["data"], "hora": c["hora"],
                          "profissional": cons.PROFISSIONAL.get(prof, prof), "status": status, "agendada": status != "Desmarcado"})
        _gravar(ctx, cons.campos(cs))
        if len(saida) == 1:
            return {**saida[0], "aviso": "responda ao lead com exatamente estes dados"}
        return {"agendada": any(x["agendada"] for x in saida), "consultas": saida,
                "aviso": f"há {len(saida)} consultas nesta conversa. Se o lead não disse de qual está falando, pergunte qual (pelo nome do paciente e a data) "
                         "antes de confirmar, remarcar ou cancelar. Responda com exatamente estes dados."}

    if nome == "reagendar":
        chave = f"{e['data']} {e['hora']}"
        if chave not in (ctx.conversa.get("horarios_oferecidos") or []):
            raise ValueError("horário não veio de buscar_horarios")
        cs, c = _consulta_da_conversa(ctx, int(e["id_agendamento"]))
        if not cons.ativa(c):
            raise ValueError("esta consulta já foi desmarcada; para uma nova data, use agendar_consulta")
        a = ctx.ts.reagendar(int(e["id_agendamento"]), date.fromisoformat(e["data"]), e["hora"])
        # mantém paciente e profissional; a nova data zera os lembretes (C48/C24/CHOJ) e a confirmação desta consulta
        c = dict(c, data=e["data"], hora=e["hora"], status="Marcado", rotinas={}, reagendado_em=datetime.now(timezone.utc))
        cs = cons.substituir(cs, c)
        restantes = [h for h in (ctx.conversa.get("horarios_oferecidos") or []) if h != chave]
        _gravar(ctx, {**cons.campos(cs), "status": "Agendado", "reagendado_em": datetime.now(timezone.utc), "horarios_oferecidos": restantes})
        return {"ok": True, "paciente": c.get("paciente_nome") or "", "data": a.get("data") or e["data"], "hora": a.get("hora") or e["hora"]}

    if nome == "confirmar_presenca":
        cs, c = _consulta_da_conversa(ctx, int(e["id_agendamento"]))
        if not cons.ativa(c):
            raise ValueError("esta consulta foi desmarcada; não há o que confirmar")
        ctx.ts.confirmar_presenca(int(e["id_agendamento"]))
        rot = dict(c.get("rotinas") or {}); rot.update({"confirmado_em": datetime.now(timezone.utc), "confirmado_no_tisaude": True})
        cs = cons.substituir(cs, dict(c, status="Confirmado", rotinas=rot))
        _gravar(ctx, cons.campos(cs))
        return {"ok": True, "paciente": c.get("paciente_nome") or "", "consulta": cons.rotulo(c), "aviso": "presença confirmada no sistema; agradeça e confirme ao lead em uma frase"}

    if nome == "cancelar":
        motivo = (e.get("motivo_do_lead") or "").strip() or "não informado"   # 26/10/2026: motivo é opcional; a alternativa e a confirmação não
        solucao = (e.get("solucao_oferecida") or "").strip()
        if len(solucao) < 4:
            raise ValueError("ainda não houve tentativa de solução: ofereça uma saída para o motivo (remarcar com horários de buscar_horarios, valor, dúvida) com escassez, e só cancele se o lead insistir")
        if not e.get("lead_confirmou_apos_solucao"):
            raise ValueError("o lead ainda não confirmou o cancelamento depois da solução oferecida; aguarde a resposta dele")
        cs, c = _consulta_da_conversa(ctx, int(e["id_agendamento"]))
        if not cons.ativa(c):
            return {"ok": True, "aviso": "esta consulta já estava desmarcada"}
        ctx.ts.cancelar(int(e["id_agendamento"]), f"{motivo} | oferecido: {solucao}")
        cs = cons.substituir(cs, dict(c, status="Desmarcado", cancelado_em=datetime.now(timezone.utc), motivo_cancelamento=motivo))
        restam = cons.ativas(cs)
        _gravar(ctx, {**cons.campos(cs), "status": "Agendado" if restam else "Irá nos retornar", "motivo_cancelamento": motivo,
                      "solucao_oferecida": solucao, "horarios_oferecidos": []})
        return {"ok": True, "paciente": c.get("paciente_nome") or "", "consulta_cancelada": cons.rotulo(c), "consultas_ativas_restantes": len(restam)}

    if nome == "encaminhar_recepcao":
        ctx.avisar_recepcao(e["motivo"], e["resumo"])
        ctx.atualizar({"status": "Encaminhado à recepção", "motivo_encaminhamento": e["motivo"], "aberta": False})
        ctx.encerrar = True
        return {"ok": True, "aviso": "botão 'Falar com Recepção' será enviado automaticamente após suas mensagens; não escreva link nem número"}

    if nome == "registrar_opt_out":
        ctx.atualizar({"status": "Não quer (opt-out)", "aberta": False, "opt_out": True, "opt_out_em": datetime.now(timezone.utc), "horarios_oferecidos": []})
        ctx.encerrar = True
        return {"ok": True}

    if nome == "enviar_video":
        enviados = ctx.conversa.get("videos_enviados") or []
        if e["video"] in enviados and not e.get("reenviar"):
            return {"ok": False, "aviso": "vídeo já enviado nesta conversa; confirme com o lead se ele quer de novo e, se sim, chame com reenviar=true"}
        wamid = ctx.enviar_video(e["video"])
        ctx.atualizar({"videos_enviados": enviados + [e["video"]]})
        return {"ok": True, "wamid": wamid}

    if nome in ("enviar_antes_e_depois", "enviar_antes_e_depois_tratamento"):
        # 15/10/2026 (clínica): UMA foto por pedido; se o lead pedir mais, a chamada seguinte manda a próxima ainda não enviada
        from celeste.comum import config as _cfg
        p = _cfg.parametros()
        if nome == "enviar_antes_e_depois":
            grupo, bloco, slug, geral = "doenca", p["antes_e_depois"]["doencas"], e["doenca"], None
        else:
            grupo, bloco, slug, geral = "tratamento", p["antes_e_depois_tratamentos"]["tratamentos"], e["tratamento"], p["antes_e_depois_tratamentos"].get("geral") or []
        enviadas = list(ctx.conversa.get("fotos_enviadas") or [])
        prox = proxima_foto(bloco, slug, enviadas, geral)
        if not prox:
            return {"ok": False, "aviso": "não há mais fotos disponíveis para isso nesta conversa; indique a seção de resultados do site"}
        s, arquivo = prox
        wamid = ctx.enviar_imagem(f"{grupo}:{s}:{arquivo}")
        ctx.atualizar({"fotos_enviadas": enviadas + [arquivo]})
        return {"ok": True, "wamid": wamid, "aviso": "UMA foto sai logo depois do seu primeiro balão, com legenda; o resto da sua resposta vem depois dela. Se o lead pedir mais, chame de novo."}

    if nome == "sinalizar_revisao":
        pend = list(ctx.conversa.get("duvidas_pendentes") or []) + [e["duvida"][:300]]
        ctx.atualizar({"revisar": True, "revisar_motivo": "dúvida fora da base de conhecimento", "duvidas_pendentes": pend})
        return {"ok": True, "aviso": "equipe avisada; diga ao lead que vai confirmar e retornar"}

    if nome == "atualizar_status":
        status = e["status"]
        if status == "Vamos retornar na data solicitada" and not e.get("data_retorno"):
            status = "Irá nos retornar"   # sem data concreta, cai na cadência padrão
        campos: dict = {"status": status}
        if e.get("data_retorno"):
            campos["proximo_recontato_em"] = e["data_retorno"]
        campos["horarios_oferecidos"] = []   # assunto fechado sem agendamento: lista antiga não gera lembrete errado (incidente 13/10)
        ctx.atualizar(campos)
        return {"ok": True}

    raise ValueError(f"ferramenta desconhecida: {nome}")


def _menor(nascimento_br: str) -> bool:
    try:
        d = datetime.strptime(nascimento_br, "%d/%m/%Y").date()
    except ValueError:
        return False
    hoje = date.today()
    return (hoje.year - d.year - ((hoje.month, hoje.day) < (d.month, d.day))) < 18
