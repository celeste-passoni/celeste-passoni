# Celeste — IA de Atendimento da Passoni Clinic

Atendente virtual no WhatsApp oficial que conversa com leads, quebra objeções e agenda Consultas no TI Saúde.

- `config/parametros.yaml` — fonte da verdade (preços, agendas, políticas, persona, resgate)
- `knowledge/` — base de conhecimento e guia de linguagem
- `prompts/` — prompt por frente e templates de resgate
- `src/celeste/` — código: `gateway` (webhook Meta), `orquestrador` (Claude + ferramentas), `ferramentas` (TI Saúde, Meta, Speech), `painel`, `jobs`, `comum`
- `infra/` — provisionamento no Google Cloud
- `tests/` — testes automáticos e scripts de validação

Documento de arquitetura: https://claude.ai/code/artifact/64654d72-0f0e-44b9-82fb-d6feec8d9c62
