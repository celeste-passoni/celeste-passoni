# Templates de resgate — Leads Perdidos (estado em 13/10/2026)

> Idioma `pt_BR`. Os textos oficiais usados pelo sistema estão em `src/celeste/jobs/templates_texto.py`; a esteira (ordem, intervalos, pausa) está em `config/parametros.yaml` → `disparos`. A esteira está **pausada** (scheduler `celeste-disparos`) até a clínica liberar.
> Decisão da clínica (13/10/2026): os templates serão redefinidos pela clínica. Tentar todos como **UTILITY**; critério que funcionou: texto escrito como continuação de um pedido do próprio lead (solicitação pendente, dar continuidade), sem valor, sem benefício, sem emoji, sem "esperamos que estejas bem". Se a Meta reclassificar para MARKETING, aceitar sem mudar o texto.

## T1 — `resgate_solicitacao_pendente` — APROVADO como UTILITY (Meta id 1443893117837530, 13/10/2026)

```
Olá, {{1}}! Aqui é a Celeste, da Passoni Clinic.

Identificamos que a sua solicitação de consulta, feita em {{2}}, ficou pendente e o agendamento não foi concluído.

Deseja dar continuidade? Responda esta mensagem que eu verifico os horários disponíveis para você.
```

- `{{1}}` = primeiro nome; `{{2}}` = mês do contato anterior do lead (campo `lead_created_at` da base), ex.: "junho".
- Sem rodapé e sem botões (decisão para maximizar a categoria utilidade). Botões de resposta rápida podem ser acrescentados depois, sem perder a categoria, mas a edição volta para revisão da Meta.
- Quando o lead responde, a Celeste **não se apresenta de novo** (o template já se apresentou) e vai direto para modalidade e agenda (regra em `prompts/leads-perdidos-v0.md`).

## T2, T3, T4 — provisórios (copiados do MarketZap em 09/10/2026; serão substituídos pela clínica)

| Código | Nome na Meta | Conteúdo | Categoria esperada |
|---|---|---|---|
| T2 | `resgate_me_da_um_oi` | "Nosso sistema encerra as conversas automaticamente após 24h… me dá um oi" | marketing (reengajamento) |
| T3 | `resgate_duas_modalidades` | script das duas modalidades com valores | marketing (oferta) |
| T4 | `resgate_demonstrou_interesse` | "Vimos que você demonstrou interesse… podemos retomar?" | tentar utilidade; provável marketing |

Nenhum destes foi cadastrado na Meta ainda.

## Cadência atual da esteira (`disparos.passos`)

```
D0    T1   → responde? a Celeste assume
D+3   T2
D+3   T3
D+8   T4
D+3   T2
pausa de 30 dias → recomeça no T3
```

Recontato por status de quem respondeu e parou: "Irá nos retornar" e "Vamos retornar na data solicitada" → T2; "Achou caro" e "Quer pelo convênio" → T1; "Mora em outro Estado" e "Está em outra clínica" → T4.

## Sugestões de utilidade para os próximos (a validar pela clínica)

- Segundo toque, sem resposta ao T1: "Olá, {{1}}. Sua solicitação de consulta segue pendente. Caso ainda queira concluir o agendamento, responda esta mensagem."
- Escolheu horário e não mandou os dados: "Olá, {{1}}. A reserva da sua consulta ficou pendente por falta dos dados de cadastro. Responda esta mensagem para concluir."
- Pediu para remarcar e sumiu: "Olá, {{1}}. A remarcação da sua consulta ficou pendente. Responda esta mensagem para escolhermos um novo horário."

## Templates de consulta (pós-agendamento) — cadastrados em 14/10/2026 na conta da Celeste, todos como UTILITY; **os 6 APROVADOS** (conferido na Meta em 15/10/2026)

Cópias dos templates da conta "Passoni Clinic" (1470345631783377) do outro número, com "Digite 1/2" trocado por botões; os dois que só existiam em texto foram criados a partir das versões da clínica.

| Nome | Meta id | Variáveis | Botões | Rotina de envio (a definir) |
|---|---|---|---|---|
| `consulta_48_horas` | 1814879276183701 | {{1}} nome · {{2}} data · {{3}} hora | Confirmar presença · Preciso remarcar | 48 h antes |
| `consulta_confirmar_24_horas` | 1772542997334489 | {{1}} nome · {{2}} data · {{3}} hora | Confirmar presença · Preciso remarcar | véspera |
| `consulta_hoje` | 1619438986499382 | {{1}} nome · {{2}} hora | — | manhã do dia |
| `faltou_a_consulta` | 1015024554724255 | {{1}} nome · {{2}} data | Quero remarcar · Não quero remarcar | fim do dia, status Falta no TI Saúde |
| `consulta_cancelada_clinica` | 1424836069802950 | {{1}} nome · {{2}} data | Remarcar agora | manual, pela recepção no painel |
| `atrasos` | 1625466219306925 | {{1}} nome | — | recepção, pacientes em tratamento (fora da Celeste) |

Decisões pendentes da clínica: (1) alcance dos envios automáticos — toda a agenda do TI Saúde ou só consultas agendadas pela Celeste; (2) efeito do botão "Não quero remarcar" — encerra só o agendamento ou retira o paciente dos contatos da IA. As rotinas de envio só serão implementadas depois dessas respostas e da aprovação do desenho.

## Alternativas com gancho de vídeo — cadastradas em 15/10/2026 (textos aprovados pela clínica), aguardando a Meta

Ideia da clínica: em vez do "textão", oferecer um vídeo. Mantidas como alternativas ao T3 e ao T4 (os atuais continuam); a esteira passa a usá-las só depois da aprovação e do fluxo dos botões. Cadastradas como UTILITY com `allow_category_change`; a Meta pode reclassificar como MARKETING (custo ~8× maior por envio e cota de marketing por usuário).

| Código | Nome | Meta id | Texto | Botões | Ao tocar "Quero ver o vídeo" |
|---|---|---|---|---|---|
| T3v | `resgate_video_dra_luciana` | 1440529418173583 | Olá, {{1}}! A Dra. Luciana Passoni gravou um vídeo curto sobre queda de cabelo e o que costuma estar por trás dela. Quer receber? | Quero ver o vídeo · Agora não | vídeo `dra_luciana` + "Assista com calma e depois me conta o que achou! 😊" |
| T4v | `resgate_video_encerramento` | 1783985846158088 | Olá, {{1}}. Antes de encerrar a sua solicitação de consulta na Passoni Clinic, a Dra. Luciana deixou um vídeo com uma mensagem para você. Quer receber? | Quero ver o vídeo · Pode encerrar | vídeo `casos_sucesso` + Celeste pergunta se quer ver um horário; "Pode encerrar" = opt-out |

Plano de teste: metade da base com T3/T4 atuais, metade com T3v/T4v; medir taxa de resposta.
