# -*- coding: utf-8 -*-
"""Cliente mínimo da API TI Saúde para os testes de integração.

Lê credenciais de variáveis de ambiente / arquivo .env e NUNCA as imprime.
"""
import os
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]


def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    missing = [k for k in ("TISAUDE_HASH", "TISAUDE_LOGIN", "TISAUDE_SENHA") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Faltam variáveis no .env: {missing}")


def redact(s: str) -> str:
    """Mascara hash/token/senha em qualquer string antes de logar."""
    for k in ("TISAUDE_HASH", "TISAUDE_HASH_PACIENTE", "TISAUDE_SENHA", "_TOKEN"):
        v = os.environ.get(k)
        if v and v in s:
            s = s.replace(v, f"<{k}>")
    return s


class TiSaude:
    BASE = "https://app.tisaude.com/api"

    def __init__(self, log_path: Path):
        load_env()
        self.hash = os.environ["TISAUDE_HASH"]
        self.hash_pac = os.environ.get("TISAUDE_HASH_PACIENTE", "")
        self.token = None
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("", encoding="utf-8")

    # ---------- logging ----------
    def _log(self, title, method, url, params=None, body=None, resp=None, elapsed=None):
        params = {k: v for k, v in (params or {}).items() if k not in ("hash", "token")}
        entry = [f"\n## {title}", f"`{method} {url.replace(self.BASE, '')}`"]
        if params:
            entry.append(f"params: `{json.dumps(params, ensure_ascii=False)}`")
        if body:
            entry.append(f"body: `{json.dumps(body, ensure_ascii=False)}`")
        if resp is not None:
            try:
                data = resp.json()
                txt = json.dumps(data, ensure_ascii=False, indent=2)
            except Exception:
                txt = resp.text[:2000]
            if len(txt) > 4000:
                txt = txt[:4000] + "\n... (truncado)"
            entry.append(f"HTTP {resp.status_code} ({elapsed:.2f}s)\n```json\n{txt}\n```")
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(redact("\n".join(entry)) + "\n")

    # ---------- http ----------
    def _call(self, title, method, path, params=None, body=None, use_pac_hash=False):
        url = f"{self.BASE}{path}"
        q = {"hash": self.hash_pac if use_pac_hash else self.hash}
        if self.token and not use_pac_hash:
            q["token"] = self.token
        q.update(params or {})
        t0 = time.time()
        if method == "GET":
            resp = requests.get(url, params=q, timeout=60)
        else:
            resp = requests.post(url, params=q, data=body, timeout=60)
        self._log(title, method, url, params, body, resp, time.time() - t0)
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, {"_raw": resp.text[:500]}

    def get(self, title, path, **params):
        return self._call(title, "GET", path, params)

    def post(self, title, path, body, **params):
        return self._call(title, "POST", path, params, body)

    def get_pac(self, title, path, **params):
        return self._call(title, "GET", path, params, use_pac_hash=True)

    # ---------- auth ----------
    def login(self):
        body = {"login": os.environ["TISAUDE_LOGIN"], "senha": os.environ["TISAUDE_SENHA"],
                "system": "web", "deviceToken": "ia-atendimento-teste"}
        url = f"{self.BASE}/login"
        t0 = time.time()
        resp = requests.post(url, params={"hash": self.hash}, json=body, timeout=60)
        data = resp.json()
        self.token = data.get("access_token")
        if self.token:
            os.environ["_TOKEN"] = self.token
        safe = {k: v for k, v in data.items() if k != "access_token"}
        safe["access_token"] = "<token>" if self.token else None
        # loga sem token e sem senha
        entry = f"\n## 1. Login\n`POST /login`\nHTTP {resp.status_code} ({time.time()-t0:.2f}s)\n```json\n{json.dumps(safe, ensure_ascii=False, indent=2)[:3000]}\n```\n"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(redact(entry))
        if not self.token:
            raise SystemExit(f"Login falhou: {data}")
        return data.get("usuario", {})
