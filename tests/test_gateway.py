# -*- coding: utf-8 -*-
"""Regras do gateway que não precisam de rede."""
from datetime import datetime
from zoneinfo import ZoneInfo


def test_corte_de_mensagens_antigas(monkeypatch):
    import sys
    import google.cloud.firestore as fs
    monkeypatch.setattr(fs, "Client", lambda **k: None)
    sys.modules.pop("celeste.gateway.app", None)
    from celeste.gateway import app as gw
    sp = ZoneInfo("America/Sao_Paulo")
    assert gw._antiga(int(datetime(2026, 9, 28, 23, 59, tzinfo=sp).timestamp()))
    assert not gw._antiga(int(datetime(2026, 9, 29, 0, 1, tzinfo=sp).timestamp()))


def test_variantes_do_celular_com_e_sem_o_nono_digito():
    from celeste.comum import telefones as tf
    assert tf.variantes("5562985767814") == ["5562985767814", "556285767814"]     # Steffany (DDD 62): a Meta devolveu sem o 9
    assert tf.variantes("556285767814") == ["556285767814", "5562985767814"]
    assert tf.variantes("5549991429768") == ["5549991429768", "554991429768"]     # Adryano (DDD 49)
    assert tf.variantes("551130001234") == ["551130001234"]                       # fixo (começa por 3): não inventa o 9
    assert tf.variantes("+55 (62) 98576-7814") == ["5562985767814", "556285767814"]
    assert tf.variantes("14155550123") == ["14155550123"]                         # fora do Brasil: só ele mesmo
    assert tf.mesmo_celular("5562985767814", "556285767814") and not tf.mesmo_celular("5562985767814", "556285767815")


def test_gateway_junta_a_resposta_sem_o_9_na_conversa_do_lead_com_o_9(monkeypatch):
    """Caso Steffany (03/11/2026): template foi para 5562985767814, a Meta entregou a resposta como 556285767814."""
    import sys
    import google.cloud.firestore as fs

    class Doc:
        def __init__(self, store, col, id_): self.s, self.col, self.id = store, col, id_
        def get(self): return self
        @property
        def exists(self): return self.id in self.s.setdefault(self.col, {})
        def to_dict(self): return dict(self.s[self.col].get(self.id) or {}) if self.exists else None
        def set(self, d, merge=False): self.s.setdefault(self.col, {}).setdefault(self.id, {}).update(d)
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

    monkeypatch.setattr(fs, "Client", lambda **k: DB())
    sys.modules.pop("celeste.gateway.app", None)
    import importlib
    gw = importlib.import_module("celeste.gateway.app")   # import fresh (o pacote ainda guarda o módulo antigo em `app`)
    monkeypatch.setattr(gw, "db", DB())
    gw.db.store["conversas"] = {"c1": {"contato": "5562985767814", "aberta": True, "frente": "leads_perdidos"}}
    gw.db.store["leads"] = {"5562985767814": {"passo": 2}}
    gw.db.store["config"] = {"atendimento": {"numeros_teste": []}}
    ref = gw._conversa_aberta("556285767814", "Steffany")
    assert ref.id == "c1" and gw.db.store["conversas"]["c1"]["wa_id"] == "556285767814"   # mesma conversa, e a resposta vai para o wa_id
    # sem conversa aberta: a nova nasce com o contato da BASE (chave do lead) e frente Leads Perdidos
    gw.db.store["conversas"]["c1"]["aberta"] = False
    ref2 = gw._conversa_aberta("556285767814", "Steffany")
    nova = gw.db.store["conversas"][ref2.id]
    assert nova["contato"] == "5562985767814" and nova["wa_id"] == "556285767814" and nova["frente"] == "leads_perdidos"
    # número desconhecido, sem lead: fica como veio, sem frente, sem wa_id
    ref3 = gw._conversa_aberta("5511999990000", None)
    assert gw.db.store["conversas"][ref3.id]["contato"] == "5511999990000" and gw.db.store["conversas"][ref3.id]["wa_id"] is None
