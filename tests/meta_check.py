# -*- coding: utf-8 -*-
"""Checagem SOMENTE LEITURA da conta Meta / WhatsApp Cloud API.
Responde: permissões do token, dados do número, apps inscritos no webhook, templates, limites.
Uso: python tests/meta_check.py   (lê META_TOKEN, META_WABA_ID, META_PHONE_NUMBER_ID do .env)
"""
import os
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

TOKEN = os.environ["META_TOKEN"]
WABA = os.environ.get("META_WABA_ID", "2053539948590151")
PHONE = os.environ.get("META_PHONE_NUMBER_ID", "1219345307926640")
G = "https://graph.facebook.com/v23.0"
H = {"Authorization": f"Bearer {TOKEN}"}


def get(path, **params):
    r = requests.get(f"{G}/{path}", headers=H, params=params, timeout=60)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text[:500]}


def show(titulo, data):
    print(f"\n=== {titulo} ===")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])


# 1. permissões do token
st, d = get("debug_token", input_token=TOKEN, access_token=TOKEN)
info = d.get("data", {})
scopes = info.get("scopes", [])
show("1. Token", {"app_id": info.get("app_id"), "type": info.get("type"), "valido": info.get("is_valid"),
                  "expira": info.get("expires_at"), "scopes": scopes})
for p in ("whatsapp_business_messaging", "whatsapp_business_management"):
    print(f"   {'OK ' if p in scopes else 'FALTA'}  {p}")

# 2. WABA e número
st, d = get(WABA, fields="id,name,account_review_status,message_template_namespace,timezone_id")
show("2a. WABA", d)
st, d = get(PHONE, fields="display_phone_number,verified_name,quality_rating,messaging_limit_tier,status,name_status,platform_type,throughput")
show("2b. Número", d)

# 3. quem recebe o webhook (apps inscritos na WABA)
st, d = get(f"{WABA}/subscribed_apps")
show("3. Apps inscritos no webhook (quem recebe as mensagens hoje)", d)

# 4. templates aprovados
st, d = get(f"{WABA}/message_templates", fields="name,status,category,language,quality_score", limit=200)
tpl = d.get("data", [])
show("4. Templates", {"total": len(tpl)})
for t in sorted(tpl, key=lambda x: (x.get("status", ""), x.get("category", ""), x.get("name", ""))):
    print(f"   {t.get('status', ''):10} {t.get('category', ''):10} {t.get('language', ''):6} {t.get('name', '')}  q={t.get('quality_score', {}).get('score', '-')}")

# 5. números da WABA (há mais de um?)
st, d = get(f"{WABA}/phone_numbers", fields="display_phone_number,verified_name,quality_rating,messaging_limit_tier")
show("5. Números da WABA", d)
