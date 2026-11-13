# -*- coding: utf-8 -*-
"""Quando a Celeste NÃO responde (clínica, 13/11/2026).

Caso real: com a consulta marcada e depois de a Celeste escrever "Até breve", a paciente mandou "Boa tarde 🙏😊" (despedida)
e recebeu "Boa tarde, Andrea! Tudo bem? 😊", como se a conversa estivesse começando. Na mesma conversa, duas reações com
emoji viraram balões ("Fico no aguardo dos seus dados", "Imagina, Andrea! Até breve").

Aqui ficam os casos que dá para decidir sem o modelo (resposta nenhuma, custo nenhum):
  1. o lead só reagiu com emoji a uma mensagem da Celeste que não era pergunta;
  2. a Celeste já se despediu e o lead só devolveu a cortesia ("boa tarde", "obrigada", "imagina", "até", 🙏).
O resto vai para o modelo, que também pode decidir não responder escrevendo `[sem resposta]` (regra no prompt da frente).
"""
from __future__ import annotations

import re
from datetime import timedelta

from celeste.orquestrador import abertura

# o modelo escreve isto quando decide não responder; o orquestrador não envia
MARCA_SEM_RESPOSTA = re.compile(r"^\W*sem[ _]resposta\W*$", re.I)

# despedida da Celeste (texto já normalizado: minúsculas, sem acento, sem pontuação)
_DESPEDIDA = re.compile(
    r"\bate (breve|logo|mais|la|amanha|segunda|terca|quarta|quinta|sexta|sabado|domingo|a consulta|a proxima)\b"
    r"|\bbom descanso\b|\btenha um[a]? (otim[oa]|bo[am]|excelente|lind[oa])\b|\bte esper(o|amos)\b|\bnos vemos\b"
    r"|\ba disposicao\b|\bso me chamar\b")

# cortesias de fechamento do lead; a mensagem inteira precisa ser feita só delas ("mas ok tudo bem obrigada", "magina sem problemas até")
_CORTESIAS = {
    "obrigado", "obrigada", "obg", "obgd", "obgda", "brigada", "brigado", "muito obrigado", "muito obrigada", "valeu", "vlw", "agradeco",
    "agradecida", "agradecido", "gratidao", "grata", "grato", "ok", "okay", "okk", "blz", "beleza", "ta", "ta bom", "tabom", "ta bem", "ta ok",
    "tudo bem", "tudo certo", "certo", "entendi", "entendido", "combinado", "fechado", "perfeito", "otimo", "maravilha", "show", "joia",
    "tchau", "ate", "ate mais", "ate logo", "ate breve", "ate la", "ate segunda", "ate terca", "ate quarta", "ate quinta", "ate sexta",
    "ate sabado", "ate amanha", "abraco", "abracos", "bjs", "beijo", "beijos", "de nada", "por nada", "imagina", "magina", "sem problema",
    "sem problemas", "igualmente", "amem", "para voce tambem", "pra voce tambem", "voce tambem", "bom dia", "boa tarde", "boa noite",
    "bom fim de semana", "bom final de semana", "bom descanso", "fica com deus", "fique com deus", "deus abencoe", "deus te abencoe",
    "viu", "mas", "e", "entao", "celeste",
}
_SAUDACAO_HORARIO = ("bom dia", "boa tarde", "boa noite")
_MAIOR_FRASE = max(len(c.split()) for c in _CORTESIAS)
# "boa tarde" só é despedida logo depois da despedida da Celeste; horas depois é o lead voltando, e o modelo responde
JANELA_SAUDACAO = timedelta(minutes=15)


def e_cortesia_de_fechamento(texto: str) -> bool:
    """True se a mensagem é feita só de cortesias de fechamento (ou só de emoji)."""
    t = abertura._normalizar(texto)
    if not t:
        return bool((texto or "").strip())   # só emoji ou pontuação
    palavras = t.split()
    i = 0
    while i < len(palavras):
        for n in range(min(_MAIOR_FRASE, len(palavras) - i), 0, -1):
            if " ".join(palavras[i:i + n]) in _CORTESIAS:
                i += n
                break
        else:
            return False
    return True


def e_despedida_da_celeste(texto: str) -> bool:
    return bool(_DESPEDIDA.search(abertura._normalizar(texto)))


def motivo(msgs: list[dict]) -> str | None:
    """`msgs` = últimas mensagens da conversa em ordem cronológica (dicts do Firestore, com `id` = wamid).
    Devolve o motivo para não responder, ou None se a conversa segue para o modelo."""
    i = len(msgs)
    while i > 0 and msgs[i - 1].get("direcao") == "lead":
        i -= 1
    novas, antes = msgs[i:], msgs[:i]
    if not novas or not antes or antes[-1].get("direcao") not in ("celeste", "humano"):
        return None   # nada novo, ou a última antes do lead foi um template: quem responde é o modelo
    turno = []      # balões de texto do último turno da Celeste
    for m in reversed(antes):
        if m.get("direcao") not in ("celeste", "humano"):
            break
        if m.get("tipo") == "text" and (m.get("texto") or "").strip():
            turno.insert(0, m)
    if not turno:
        return None
    ultimo = turno[-1]
    if any(m.get("tipo") not in ("text", "reaction") for m in novas):
        return None   # botão, áudio, imagem, documento: sempre têm assunto

    if all(m.get("tipo") == "reaction" for m in novas):
        if not any((m.get("texto") or "").strip() for m in novas):
            return "reação removida"
        por_id = {m.get("id"): m for m in msgs}
        for m in novas:
            alvo = por_id.get(m.get("contexto_wamid")) or ultimo
            if alvo.get("direcao") == "template" or "?" in (alvo.get("texto") or ""):
                return None   # reação a uma pergunta ou oferta pode ser a resposta: o modelo decide
        return "reação a mensagem que não era pergunta"

    if "?" in (ultimo.get("texto") or "") or not any(e_despedida_da_celeste(m.get("texto") or "") for m in turno):
        return None
    textos = [m.get("texto") or "" for m in novas if m.get("tipo") == "text"]
    if not all(e_cortesia_de_fechamento(t) for t in textos):
        return None
    if any(s in abertura._normalizar(t) for t in textos for s in _SAUDACAO_HORARIO):
        em_c, em_l = ultimo.get("recebido_em"), novas[0].get("recebido_em")
        if not em_c or not em_l or (em_l - em_c) > JANELA_SAUDACAO:
            return None
    return "despedida do lead depois da despedida da Celeste"
