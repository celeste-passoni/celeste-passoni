# -*- coding: utf-8 -*-
"""Celeste no MarketZap (25/11/2026): cliente da API, canal, gateway, orquestrador e jobs — tudo com mocks, sem rede."""
import importlib
import json
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from celeste.comum import config

SETOR_CELESTE, SETOR_PASSAGEM, CANAL = 40523, 38306, 934
NUM_OFICIAL = "658241090708883"


# ----------------------------------------------------------------- dublês
class Resp:
    def __init__(self, status=200, dados=None, headers=None):
        self.status_code, self._d, self.headers = status, dados, headers or {}
        self.content = b"x" if dados is not None else b""

    def json(self):
        return self._d


class HTTP:
    """Sessão falsa: `rotas` = lista de (método, trecho da URL, função(kw) -> Resp | Resp). Guarda as chamadas."""
    def __init__(self, rotas):
        self.rotas, self.chamadas = rotas, []

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def request(self, metodo, url, **kw):
        self.chamadas.append((metodo, url, kw))
        for m, trecho, r in self.rotas:
            if m == metodo and trecho in url:
                return r(kw) if callable(r) else r
        raise AssertionError(f"rota não prevista: {metodo} {url}")


@pytest.fixture(autouse=True)
def credenciais(monkeypatch):
    from celeste.ferramentas import mktzap
    monkeypatch.setenv("MKTZAP_COMPANY_ID", "1")
    monkeypatch.setenv("MKTZAP_CLIENT_KEY", "chave-teste")
    config.segredo.cache_clear()
    mktzap._cache_token.update(valor=None, ate=0.0)
    yield
    config.segredo.cache_clear()
    mktzap._cache_token.update(valor=None, ate=0.0)


def _token():
    return ("GET", "/company/1/token", Resp(200, {"accessToken": "tok"}))


def _atendimento(id_=10, setor=SETOR_CELESTE, tel="5511999990000", fechado=False, canal=CANAL, atualizado="2026-11-25T10:00:00.000Z"):
    return {"id": id_, "protocol": f"1-{id_}", "contact_id": f"waent_934_{id_}", "sector_id": setor, "channelable_id": canal,
            "closed_at": "2026-11-25T11:00:00.000Z" if fechado else None, "updated_at": atualizado,
            "external_ids": [{"key": "phone", "value": tel}]}


# ----------------------------------------------------------------- cliente
def test_token_em_cache_e_bearer():
    from celeste.ferramentas.mktzap import MktZap
    http = HTTP([_token(), ("GET", "/sector", Resp(200, [{"id": SETOR_CELESTE, "name": "Celeste Maria | IA"}]))])
    mz = MktZap(session=http)
    assert mz.setores()[0]["id"] == SETOR_CELESTE
    mz.setores()
    assert sum(1 for m, u, _ in http.chamadas if "/token" in u) == 1                     # token reaproveitado
    assert http.chamadas[1][2]["headers"]["Authorization"] == "Bearer tok"
    assert http.chamadas[0][2]["params"] == {"clientKey": "chave-teste"}


def test_429_espera_e_tenta_de_novo_mantendo_a_pagina():
    from celeste.ferramentas.mktzap import MktZap
    respostas = iter([Resp(429, {"code": "REQUEST_LIMIT_REACHED"}), Resp(200, [_atendimento()])])
    esperas = []
    http = HTTP([_token(), ("GET", "/historycontact", lambda kw: next(respostas))])
    mz = MktZap(session=http, dormir=esperas.append)
    assert mz.atendimentos(contact_id="waent_934_10")[0]["id"] == 10
    assert esperas == [1.0]
    chamadas = [kw for m, u, kw in http.chamadas if "/historycontact" in u]
    assert len(chamadas) == 2 and all(kw["headers"]["x-page"] == "1" for kw in chamadas)


def test_401_renova_o_token_uma_vez():
    from celeste.ferramentas.mktzap import MktZap
    respostas = iter([Resp(401, {}), Resp(200, [])])
    http = HTTP([_token(), ("GET", "/sector", lambda kw: next(respostas))])
    MktZap(session=http).setores()
    assert sum(1 for m, u, _ in http.chamadas if "/token" in u) == 2


def test_send_hsm_no_formato_da_api():
    from celeste.ferramentas.mktzap import MktZap
    http = HTTP([_token(), ("POST", "/history/send-hsm", Resp(201, {"history_id": {"success": True, "contact_id": "waent_934_x"}}))])
    MktZap(session=http).enviar_hsm("5511999990000", 77, ["Ana"], nome="Ana", setor_id=SETOR_CELESTE)
    corpo = http.chamadas[-1][2]["json"]
    assert corpo["type"] == "whatsapp-enterprise" and corpo["broker_phone"] == "5511916069009"
    assert corpo["phone_ddi"] == "55" and corpo["phone_number"] == "11999990000"
    assert corpo["sector_id"] == SETOR_CELESTE and corpo["contact_already_exists"] is True and corpo["is_auto"] is True
    assert corpo["messages"] == {"type": "hsm", "content": {"hsm_id": 77, "params": ["Ana"]}}


def test_atendimento_aberto_filtra_canal_fechado_e_telefone():
    from celeste.ferramentas.mktzap import atendimento_aberto
    lista = [_atendimento(1, fechado=True), _atendimento(2, canal=10681), _atendimento(3, tel="5511888880000"),
             _atendimento(4, atualizado="2026-11-25T09:00:00.000Z"), _atendimento(5, atualizado="2026-11-25T12:00:00.000Z")]
    assert atendimento_aberto(lista, CANAL, {"5511999990000"})["id"] == 5
    assert atendimento_aberto(lista, CANAL, {"5511777770000"}) is None


# ----------------------------------------------------------------- canal
class MZ:
    """MktZap falso para o canal."""
    def __init__(self, atendimentos=None, hsm=None):
        self.lista = list(atendimentos or [])
        self.hsm = hsm if hsm is not None else [{"id": 77, "element_name": "resgate_queda_3cm_v2"}]
        self.chamadas = []

    def atendimentos(self, contact_id=None, atualizados_desde=None, protocolo=None, paginas=5):
        self.chamadas.append(("atendimentos", contact_id))
        return [h for h in self.lista if not contact_id or h["contact_id"] == contact_id]

    def templates_hsm(self):
        return self.hsm

    def enviar_hsm(self, telefone, hsm_id, parametros, nome=None, setor_id=None, automatico=True):
        self.chamadas.append(("hsm", telefone, hsm_id, tuple(parametros), setor_id))
        return {"history_id": {"success": True, "contact_id": "waent_934_10"}}

    def enviar_texto(self, history_id, texto):
        self.chamadas.append(("texto", history_id, texto)); return {"success": True}

    def enviar_midia(self, history_id, tipo, url, legenda="", nome=None):
        self.chamadas.append(("midia", history_id, tipo, url)); return {"success": True}

    def mudar_setor(self, protocolo, setor_id):
        self.chamadas.append(("setor", protocolo, setor_id))
        for h in self.lista:
            if h["protocol"] == protocolo:
                h["sector_id"] = setor_id
        return {"success": True}

    def tirar_do_automatico(self, protocolo):
        self.chamadas.append(("sem_operador", protocolo)); return {"success": True}


def _canal(mz, conv=None, leitor=None):
    from celeste.ferramentas.canal import CanalMktZap
    return CanalMktZap(conv if conv is not None else {"contato": "5511999990000"}, mz=mz, leitor_meta=leitor or MagicMock(), dormir=lambda s: None)


def test_template_abre_no_setor_da_celeste_e_grava_o_atendimento():
    mz = MZ([_atendimento(10, setor=SETOR_CELESTE)])
    cz = _canal(mz)
    wid = cz.enviar_template("5511999990000", "resgate_queda_3cm_v2", ["Ana"], imagem_cabecalho="https://x/img.jpg")
    assert wid.startswith("mktzap-")
    assert ("hsm", "5511999990000", 77, ("Ana",), SETOR_CELESTE) in mz.chamadas
    assert not any(c[0] == "setor" for c in mz.chamadas)
    assert cz.campos_conversa() == {"canal": "mktzap", "mktzap_history_id": 10, "mktzap_protocolo": "1-10",
                                    "mktzap_contact_id": "waent_934_10", "mktzap_setor_id": SETOR_CELESTE}


def test_template_que_cai_em_outro_setor_e_movido_para_o_da_celeste():
    mz = MZ([_atendimento(10, setor=32139)])          # lead já tinha atendimento aberto na recepção
    cz = _canal(mz)
    cz.enviar_template("5511999990000", "resgate_queda_3cm_v2", ["Ana"])
    assert ("setor", "1-10", SETOR_CELESTE) in mz.chamadas
    assert cz.campos_conversa()["mktzap_setor_id"] == SETOR_CELESTE and cz.campos_conversa()["mktzap_setor_movido_de"] == 32139


def test_template_inexistente_no_mktzap_falha_antes_de_enviar():
    from celeste.ferramentas.mktzap import MktZapErro
    mz = MZ([], hsm=[])
    with pytest.raises(MktZapErro):
        _canal(mz).enviar_template("5511999990000", "resgate_queda_3cm_v2", ["Ana"])
    assert not any(c[0] == "hsm" for c in mz.chamadas)


def test_mesma_instancia_nao_carrega_atendimento_de_um_lead_para_outro():
    mz = MZ([_atendimento(10, tel="5511999990000"), _atendimento(20, tel="5511888880000")])
    mz.enviar_hsm = lambda telefone, *a, **k: {"history_id": {"success": True, "contact_id": None}}
    cz = _canal(mz, conv={})
    cz.enviar_template("5511999990000", "resgate_queda_3cm_v2", ["Ana"])
    assert cz.campos_conversa()["mktzap_history_id"] == 10
    cz.enviar_template("5511888880000", "resgate_queda_3cm_v2", ["Bia"])
    assert cz.campos_conversa()["mktzap_history_id"] == 20


def test_confirmar_atendimento_so_no_setor_da_celeste():
    assert _canal(MZ([_atendimento(10)]), {"contato": "5511999990000", "mktzap_contact_id": "waent_934_10"}).confirmar_atendimento("5511999990000") == (True, "")
    ok, motivo = _canal(MZ([_atendimento(10, setor=SETOR_PASSAGEM)])).confirmar_atendimento("5511999990000")
    assert not ok and "fora do setor" in motivo
    ok, motivo = _canal(MZ([_atendimento(10, fechado=True)])).confirmar_atendimento("5511999990000")
    assert not ok and "sem atendimento" in motivo


def test_texto_e_imagem_vao_para_o_atendimento():
    mz = MZ([_atendimento(10)])
    cz = _canal(mz, {"contato": "5511999990000", "mktzap_history_id": 10})
    assert cz.enviar_texto("5511999990000", "Oi").startswith("mktzap-")
    cz.enviar_imagem_link("5511999990000", "https://x/foto.jpg", "antes e depois")
    assert ("texto", 10, "Oi") in mz.chamadas and ("midia", 10, "image", "https://x/foto.jpg") in mz.chamadas


def test_video_vai_como_link_ou_pela_meta(monkeypatch):
    mz = MZ([_atendimento(10)])
    leitor = MagicMock(); leitor.enviar_video_link.return_value = "wamid.V"
    cz = _canal(mz, {"contato": "5511999990000", "mktzap_history_id": 10}, leitor)
    cz.enviar_video_link("5511999990000", "https://x/v.mp4")
    assert ("texto", 10, "https://x/v.mp4") in mz.chamadas and not leitor.enviar_video_link.called
    monkeypatch.setitem(config.parametros()["mktzap"], "video", "meta")
    assert cz.enviar_video_link("5511999990000", "https://x/v.mp4") == "wamid.V"


def test_passagem_para_comercial_resgate():
    mz = MZ([_atendimento(10)])
    r = _canal(mz).passar_para_equipe("5511999990000")
    assert r == {"protocolo": "1-10", "setor": SETOR_PASSAGEM}
    assert mz.chamadas[-2:] == [("setor", "1-10", SETOR_PASSAGEM), ("sem_operador", "1-10")]


def test_lida_e_midia_pela_meta_do_numero_oficial():
    leitor = MagicMock()
    cz = _canal(MZ(), leitor=leitor)
    cz.marcar_lida("mktzap-abc"); cz.marcar_lida("wamid.X"); cz.baixar_midia("m1")
    leitor.marcar_lida.assert_called_once_with("wamid.X")
    leitor.baixar_midia.assert_called_once_with("m1")
    from celeste.ferramentas.canal import CanalMktZap
    assert CanalMktZap({}, mz=MZ()).meta().phone_id == NUM_OFICIAL


def test_canal_do_numero_e_escolha_pela_conversa():
    from celeste.ferramentas import canal, meta
    assert canal.canal_do_numero(None) == "meta" and canal.canal_do_numero(meta.PHONE_ID) == "meta"
    assert canal.canal_do_numero(NUM_OFICIAL) == "mktzap" and canal.canal_do_numero("123") is None
    padrao = object()
    assert canal.para_conversa({"canal": "meta"}, padrao) is padrao and canal.para_conversa({}, padrao) is padrao


def test_webhook_traz_o_numero_de_destino():
    from celeste.ferramentas import meta
    payload = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": NUM_OFICIAL}, "contacts": [{"wa_id": "5511999990000"}],
                                                 "messages": [{"id": "wamid.1", "from": "5511999990000", "timestamp": "1795600000", "type": "text", "text": {"body": "oi"}}],
                                                 "statuses": [{"id": "wamid.2", "status": "read", "timestamp": "1795600000"}]}}]}]}
    evs = meta.normalizar_webhook(payload)
    assert [e["phone_number_id"] for e in evs] == [NUM_OFICIAL, NUM_OFICIAL]


# ----------------------------------------------------------------- Firestore falso
class Doc:
    def __init__(self, store, col, id_): self.s, self.col, self.id = store, col, id_
    def get(self): return self
    @property
    def exists(self): return self.id in self.s.setdefault(self.col, {})
    def to_dict(self): return dict(self.s[self.col].get(self.id) or {}) if self.exists else None
    def set(self, d, merge=False): self.s.setdefault(self.col, {}).setdefault(self.id, {}).update(d)
    def collection(self, nome): return Col(self.s, f"{self.col}/{self.id}/{nome}")
    @property
    def reference(self): return self


class Query:
    def __init__(self, store, col, filtros): self.s, self.col, self.f = store, col, filtros
    def where(self, campo, op, valor): return Query(self.s, self.col, self.f + [(campo, valor)])
    def limit(self, n): return self
    def stream(self):
        for id_, d in list(self.s.setdefault(self.col, {}).items()):
            if all(d.get(c) == v for c, v in self.f):
                yield Doc(self.s, self.col, id_)


class Col(Query):
    def __init__(self, store, col): super().__init__(store, col, [])
    def document(self, id_=None): return Doc(self.s, self.col, id_ or f"novo{len(self.s.setdefault(self.col, {})) + 1}")


class DB:
    def __init__(self): self.store = {}
    def collection(self, nome): return Col(self.store, nome)


@pytest.fixture
def gw(monkeypatch):
    import google.cloud.firestore as fs
    monkeypatch.setattr(fs, "Client", lambda **k: DB())
    sys.modules.pop("celeste.gateway.app", None)
    g = importlib.import_module("celeste.gateway.app")
    monkeypatch.setattr(g, "db", DB())
    agendados = []
    monkeypatch.setattr(g, "_agendar_debounce", lambda cid, tipo: agendados.append(cid))
    g.db.store["config"] = {"atendimento": {"numeros_teste": []}}
    g.agendados = agendados
    return g


def _ev(phone_number_id, de="5511999990000", wamid="wamid.1", kind="mensagem"):
    if kind == "status":
        return {"kind": "status", "wamid": wamid, "para": de, "status": "read", "timestamp": 1795600000, "phone_number_id": phone_number_id}
    return {"kind": "mensagem", "wamid": wamid, "de": de, "nome": "Ana", "timestamp": int(datetime.now(timezone.utc).timestamp()),
            "tipo": "text", "texto": "oi", "media_id": None, "mime": None, "botao": None, "contexto": None, "phone_number_id": phone_number_id}


def test_gateway_descarta_mensagem_do_numero_oficial_sem_conversa_da_celeste(gw):
    gw._processar(_ev(NUM_OFICIAL))
    assert not gw.db.store.get("conversas") and gw.agendados == []      # paciente da recepção: nada gravado


def test_gateway_aceita_resposta_de_lead_da_celeste_no_numero_oficial(gw):
    gw.db.store["conversas"] = {"c1": {"contato": "5511999990000", "aberta": True, "canal": "mktzap", "frente": "leads_perdidos"}}
    gw._processar(_ev(NUM_OFICIAL))
    assert gw.agendados == ["c1"] and "wamid.1" in gw.db.store["conversas/c1/mensagens"]


def test_gateway_numero_atual_nao_usa_a_conversa_do_mktzap(gw):
    gw.db.store["conversas"] = {"c1": {"contato": "5511999990000", "aberta": True, "canal": "mktzap", "frente": "leads_perdidos"}}
    gw._processar(_ev(None))                                              # mesmo lead escrevendo ao número atual da Celeste
    assert gw.agendados and gw.agendados[0] != "c1"
    assert "conversas/c1/mensagens" not in gw.db.store


def test_gateway_ignora_status_do_oficial_e_numero_desconhecido(gw):
    gw._processar(_ev(NUM_OFICIAL, kind="status"))
    gw._processar(_ev("999", wamid="wamid.9"))
    assert "status_entrega" not in gw.db.store and not gw.db.store.get("conversas")
    gw._processar(_ev(None, kind="status"))
    assert "wamid.1" in gw.db.store["status_entrega"]


def test_gateway_nao_reabre_conversa_ja_passada_para_a_equipe(gw):
    agora = datetime.now(timezone.utc)
    gw.db.store["conversas"] = {"c1": {"contato": "5511999990000", "aberta": False, "canal": "mktzap", "status": "Encaminhado à recepção",
                                       "ultima_msg_celeste_em": agora}}
    gw._processar(_ev(NUM_OFICIAL))
    assert gw.agendados == [] and gw.db.store["conversas"]["c1"]["aberta"] is False


# ----------------------------------------------------------------- orquestrador
@pytest.fixture
def orq(monkeypatch):
    import google.cloud.firestore as fs
    monkeypatch.setattr(fs, "Client", lambda **k: MagicMock())
    from celeste.orquestrador import app as o
    monkeypatch.setattr(o, "db", MagicMock())
    return o


class CanalFalso:
    nome = "mktzap"

    def __init__(self, ok=True, motivo=""):
        self.ok, self.motivo, self.enviados, self.passou = ok, motivo, [], False

    def confirmar_atendimento(self, tel): return self.ok, self.motivo
    def campos_conversa(self): return {"canal": "mktzap", "mktzap_history_id": 10, "mktzap_setor_id": SETOR_CELESTE}
    def passar_para_equipe(self, tel): self.passou = True; return {"protocolo": "1-10", "setor": SETOR_PASSAGEM}
    def enviar_template(self, *a, **k): self.enviados.append(("template", a)); return "mktzap-t"
    def enviar_texto(self, *a): self.enviados.append(("texto", a)); return "mktzap-x"


def test_orquestrador_nao_responde_fora_do_setor(orq):
    ref, conv = MagicMock(), {"contato": "5511999990000", "canal": "mktzap", "id": "c1"}
    r = orq._bloqueio_mktzap(ref, conv, CanalFalso(False, "atendimento no setor 38306, fora do setor da Celeste"))
    assert "fora do setor" in r["ignorado"]
    assert ref.set.call_args[0][0]["pendente_resposta"] is False


def test_orquestrador_responde_no_setor_e_grava_o_atendimento(orq):
    ref, conv = MagicMock(), {"contato": "5511999990000", "canal": "mktzap", "id": "c1"}
    assert orq._bloqueio_mktzap(ref, conv, CanalFalso()) is None
    assert conv["mktzap_history_id"] == 10
    assert orq._bloqueio_mktzap(ref, {"contato": "x"}, orq.meta.Meta.__new__(orq.meta.Meta)) is None   # número atual: sem checagem


def test_passagem_no_fim_da_resposta_vira_modo_humano(orq):
    ref, cz = MagicMock(), CanalFalso()
    orq._passar_para_equipe_mktzap(ref, {"contato": "5511999990000", "id": "c1"}, cz)
    assert cz.passou
    campos = ref.set.call_args_list[0][0][0]
    assert campos["modo"] == "humano" and campos["mktzap_setor_id"] == SETOR_PASSAGEM


def test_aviso_a_recepcao_no_mktzap_nao_manda_template(orq):
    cz = CanalFalso()
    orq._avisar_recepcao(cz, {"id": "c1", "contato": "5511999990000", "nome": "Ana"}, "quer_humano", "pediu atendente")
    assert cz.enviados == []
    assert orq.db.collection.return_value.document.return_value.set.call_args[0][0]["canal"] == "mktzap"


def test_sem_orientacao_a_recepcao_em_conversa_do_mktzap(orq):
    ref = MagicMock()
    r = orq._orientar_recepcao(ref, {"id": "c1", "contato": "5511999990000", "canal": "mktzap"}, forcar=True)
    assert "MarketZap" in r["ignorado"]


# ----------------------------------------------------------------- jobs
def test_registrar_envio_mktzap_abre_conversa_nova_se_a_aberta_e_do_numero_atual(monkeypatch):
    from celeste.jobs import disparos
    db = DB()
    db.store["conversas"] = {"antiga": {"contato": "5511999990000", "aberta": True, "frente": "leads_perdidos"}}
    lead = {"celular": "5511999990000", "nome": "Ana", "conversa_id": "antiga"}
    dec = disparos.Decisao("T1", "teste", 1, 1)
    campos = {"canal": "mktzap", "mktzap_history_id": 10, "mktzap_setor_id": SETOR_CELESTE}
    disparos._registrar_envio(db, "5511999990000", lead, dec, "resgate_queda_3cm_v2", "mktzap-1", datetime.now(timezone.utc), {}, campos)
    nova_id = db.store["leads"]["5511999990000"]["conversa_id"]
    assert nova_id != "antiga" and db.store["conversas"][nova_id]["canal"] == "mktzap"
    assert db.store["conversas"][nova_id]["mktzap_setor_id"] == SETOR_CELESTE
    assert "canal" not in db.store["conversas"]["antiga"]
    assert disparos.campos_canal(object()) == {} and disparos.campos_canal(CanalFalso())["canal"] == "mktzap"


def test_envio_de_teste_so_para_numero_de_teste():
    from celeste.jobs import mktzap_teste
    db = DB()
    db.store["config"] = {"atendimento": {"numeros_teste": ["5511999990000"]}}
    with pytest.raises(ValueError):
        mktzap_teste.enviar("5511888880000", "T1", "Ana", dry_run=True, db=db)
    plano = mktzap_teste.enviar("5511999990000", "T1", "Ana", dry_run=True, db=db)
    assert plano["dry_run"] and plano["setor"] == SETOR_CELESTE and not db.store.get("conversas")
    cz = CanalFalso()
    r = mktzap_teste.enviar("5511999990000", "T1", "Ana", dry_run=False, db=db, canal_mz=cz)
    conv = db.store["conversas"][r["conversa_id"]]
    assert conv["teste"] is True and conv["canal"] == "mktzap" and conv["frente"] == "leads_perdidos" and cz.enviados


def test_envio_de_teste_nao_move_setor_sem_aviso_e_le_o_texto_do_template():
    mz = MZ([_atendimento(10, setor=32139)], hsm=[{"id": 5, "element_name": "resgate_lead_perdido", "template": json.dumps("Oi {{1}} 🗓️"),
                                                  "header_type": "image"}])
    cz = _canal(mz)
    cz.mover_setor = False
    assert cz.texto_do_template("resgate_lead_perdido", ["Ana"]) == "[imagem do template resgate_lead_perdido]\nOi Ana 🗓️"
    cz.enviar_template("5511999990000", "resgate_lead_perdido", ["Ana"])
    assert not any(c[0] == "setor" for c in mz.chamadas) and cz.campos_conversa()["mktzap_setor_id"] == 32139
