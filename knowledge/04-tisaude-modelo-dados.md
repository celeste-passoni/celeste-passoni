# TI Saúde — Modelo de Dados e API (o que já sabemos)

> Fonte: pipeline diário `Codigo Pipeline Diario TI SAUDE (TI CLINIC).txt` + tabelas `bronze.*` no BigQuery (21/09/2026).
> Os endpoints oficiais (incluindo **criar paciente** `POST /paciente/salvar` e **criar agendamento** `POST /agendamento/adicionar`) foram confirmados na documentação e estão detalhados em [`05-tisaude-api-referencia.md`](05-tisaude-api-referencia.md). Este arquivo cobre o **modelo de dados real** da Passoni (ids, calendários, formatos, status).

## 1. Autenticação (confirmada pelo pipeline)

Existem **duas APIs** com o mesmo login:

| API | Base URL | Uso conhecido |
|---|---|---|
| Legada | `https://app.tisaude.com/api` | cliente, usuarios, pacientes, agenda, procedimentos, guias, orcamentos, financeiro/receitas |
| Nova | `https://api.tisaude.com/api` | priceTable (POST) |

```
POST {base}/login?hash={HASH}
body: { "login": "...", "senha": "...", "system": "web", "deviceToken": "123" }
→ { "access_token": "..." }

Demais chamadas: {base}/{recurso}?hash={HASH}&token={access_token}
```

- `HASH` identifica a clínica (fixo). Login/senha do usuário de integração `Apex.BI` (id 97049, adm=1, não profissional de saúde).
- ⚠️ As credenciais estão em texto puro no código do pipeline. Para a IA, mover para **Secret Manager** e criar um usuário de integração dedicado (ex.: `IA.Atendimento`) para que `marcadopor` mostre que foi a IA que agendou.

## 2. Endpoints GET conhecidos

| Endpoint | Paginação | Observações |
|---|---|---|
| `GET /cliente` | — | dados da clínica |
| `GET /usuarios` | — | 26 usuários; `idCalendario` liga usuário → agenda |
| `GET /pacientes?page=N` | `data`, `last_page` | 6.316 pacientes |
| `GET /agenda?dataInicio=&dataFim=` | — | lista de agendamentos (janela ≤ 1 ano por chamada) |
| `GET /procedimentos` | — | 252 procedimentos |
| `GET /guias?inicio=&fim=&page=` | `data`, `last_page` | |
| `GET /orcamentos?inicio=&fim=&page=` | `data`, `last_page` | |
| `GET /financeiro/receitas?inicio=&fim=&page=` | `data`, `last_page` | |
| `POST /priceTable` (api nova) | — | `{idLocal, idProcedures[], idHealthInsurances[]}` |

**Confirmado na documentação (ver 05):** `POST /paciente/salvar` (cria ou atualiza por CPF), `POST /agendamento/adicionar`, `POST /agendamento/editar/{id}` (remarcar/cancelar/confirmar via `status`), `GET /pacientes?busca=|celular=` (dedup), `GET /calendarios`, `GET /agenda/{idCalendario}?dataInicio&dataFim`, e um endpoint de grade `GET /rest/agenda/horasDisponiveis/{idProfissional}` na API do Paciente (a validar). **Não há webhooks** — status sincronizado por polling.

## 3. Entidades relevantes para o agendamento

### `usuarios` → calendários dos profissionais ofertados
| Profissional | id usuário | idCalendario | Procedimento de consulta |
|---|---|---|---|
| **Dra. Luciana Passoni** | 29110 | **1** | **5 – PC - CONSULTA DRA. LUCIANA** |
| **Dr. Lucas Vieira** | 79786 | **36** | **264 – PC - CONSULTA EQUIPE MÉDICA** |
| Dra. Érica Mello (retornos) | 82046 | 41 | 264 (raro) / 73 – RETORNO |
| Dra. Fernanda Faco | 100465 | 66 | 264 (raro) |

Outros calendários (24, 49, 51, 52 = tricologistas/salas de procedimento; 7 Beatriz; 69 Thais; 62 Giovana; 70 Larissa) não são usados para primeira consulta.

Quem marca hoje (`marcadopor`, últimos 90 dias): atendentes de Novos Leads ~3.100 · comercial/recepção ~1.900 · resgate ~290. A IA marcará como usuário "Tecnologia - IA".

### `agenda` (campos)
```
id, idPcte, cd_bsuid, cliente, data (AAAA-MM-DD), hora (HH:MM:SS), idConvenio (=1 particular),
idProcedimento, idCalendario, marcacao (data em que foi marcado), status, marcadopor (nome),
deletado, local (=1 "PASSONI CLINIC - SP"), infoLocal_*
```
`agenda_detalhes` (versão antiga do pipeline, mar/2026) tem campos extras úteis: `obs`, `dataatendido`, `datachegou`, `datadesmarcado`, `dataconfirmado`, `motivoFalta`, `periodo`, `valor`, `link_agendamento`, `flagVideo`, `prioridade`.

### Semântica de `status` (confirmada pela documentação)
| status | Significado | Volume na Passoni |
|---|---|---|
| **0** | Marcado | só datas futuras |
| 1 | Em espera | 1 registro |
| **2** | Atendido | 31k |
| **3** | Confirmado | poucos, datas próximas |
| 4 | Solicitado (agendamento online pelo paciente) | 0 |
| 5 | Em atendimento | raro |
| 6, 7 | não documentados (estados internos) | raríssimos |
| **-1** | Falta | |
| **-2** | Desmarcado | |

**Para o dashboard "total agendados":** contar `agenda` com `idProcedimento IN (5, 264)`, `deletado = 0`, `status IN (0, 3, 2)`, `marcadopor = <usuário da IA>`. No-show = `-1`; cancelado = `-2`.

### Grade de horários real (últimos 60 dias, seg–sex)
- **Dra. Luciana (cal. 1):** slots de **1 h** às 12:00, 13:00, 14:00, 15:00, 16:00, 17:00 (raro 17:30). ~1 consulta por slot/dia. Agenda dela vai até **18/12/2026** (recesso).
- **Dr. Lucas (cal. 36):** slots de 1 h de 09:00 a 17:00; picos às 10:00, 16:00 e 17:00; 12:00–15:00 pouco usados (provavelmente procedimentos/almoço) — confirmar se são bloqueados.
- Volume: Dra. ~760 consultas / 180 d (≈ 6/dia); Dr. Lucas ~540 / 180 d (≈ 4/dia).
- Taxas (180 d): Dra. — 424 atendidas, 265 desmarcadas (**38%**), 30 faltas (4%); Dr. Lucas — 329 atendidas, 171 desmarcadas (**34%**), 44 faltas (8%).

### `pacientes` (campos e formatos observados em 2026)
| Campo | Formato | Obs |
|---|---|---|
| `nome` | texto | obrigatório |
| `cpf` | **11 dígitos sem pontuação** | 99,5% preenchido |
| `nascimento` | data | 100% |
| `celular` | **11 dígitos DDD+número, sem máscara** | 100%; `celular_whatsapp` = 0/1 |
| `email` | texto | 100% |
| `cep` | 8 dígitos sem hífen | |
| `endereco`, `n`, `apt`, `bairro`, `cidade`, `uf`, `pais` | texto | cidade em MAIÚSCULAS |
| `sexo` | `FEMININO` / `MASCULINO` | |
| `indicado` | texto livre = "como nos conheceu" | valores usados: `INSTAGRAM DRA. LUCIANA`, `GOOGLE`, `INSTAGRAM PASSONI CLINIC`, `CAMPANHA DE MENSAGENS`, nome de quem indicou |
| `idConvenioCliente` | 1 (particular) | `convenio` null |
| `status` | 1 (ativo) | `deletado` 0 |
| `idUsuario` | id do usuário que cadastrou | vira o "criado pela IA" |
| `medico` | vazio ou idCalendario | |

Campos do pré-cadastro pedidos no WhatsApp → mapeamento direto: nome → `nome`; CPF → `cpf` (só dígitos); nascimento → `nascimento`; e-mail → `email`; "como nos conheceu" → `indicado`; CEP → `cep`; número+complemento → `n` + `apt`; bairro/cidade/estado → `bairro`/`cidade`/`uf`; telefone do WhatsApp → `celular` + `celular_whatsapp=1`; sexo → inferir do nome ou perguntar (⚠️ definir).

## 4. Fluxo de integração proposto para a IA

```
1. buscar_paciente(cpf | celular)      → GET /pacientes (filtro) — evita duplicar
2. criar_paciente(dados)                → POST /pacientes (a confirmar)
3. buscar_horarios(idCalendario, de, até) → GET /agenda no período + grade fixa do YAML
                                          (ou endpoint nativo de disponibilidade, se existir)
4. agendar_consulta(idPcte, idCalendario, idProcedimento, data, hora) → POST /agenda (a confirmar)
5. reagendar / cancelar                 → PUT/DELETE /agenda/{id} (a confirmar)
6. sync de status (atendido/faltou/cancelou) → GET /agenda diário → métricas do painel
```

Regras de negócio já conhecidas para `buscar_horarios`:
- Dra. Luciana: cal. 1, proc. 5, seg–sex, 12:00–17:00, slots de 60 min, 1 paciente por slot.
- Dr. Lucas: cal. 36, proc. 264, seg–sex, 09:00–17:00, slots de 60 min.
- Não agendar em `feriados` (tabela `bronze.feriados` existe mas está vazia — popular) nem após `clinica.recesso_fim_de_ano.ultimo_dia_atendimento`.
- Slot ocupado = existe registro em `agenda` com mesma `data`+`hora`+`idCalendario`, `deletado=0` e `status NOT IN (-2)`.
