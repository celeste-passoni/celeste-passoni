# TI Saúde — Referência da API (v1.2.1) para a integração da IA

> Fonte: documentação oficial exportada em PDF (21/09/2026) — API Principal ("TI.Saúde v1.2.1") e API do Paciente ("v1.0.3").
> Base: `https://app.tisaude.com/api`. Todas as chamadas levam `?hash=HASH&token=TOKEN` na query string (POSTs aceitam os campos no body form/JSON).
> Segredos (`HASH`, login, senha, `HASH_PAC`) ficam em Secret Manager — nunca neste repositório.

## 0. Identificação

| Item | Valor |
|---|---|
| Identificador da clínica | `$PASSONI_12054_TISAUDE` → `HASH` = md5 do identificador (API Principal) |
| `cliente` (id numérico da clínica) | **12054** |
| Hash da API do Paciente | `HASH_PAC` (diferente do `HASH` principal; consta na doc "Agendamento Online - Pacientes") |
| Usuário de integração atual | `Apex.BI` (id 97049). Recomendado criar `IA.Atendimento` depois. |

## 1. Autenticação

```
POST /login?hash=HASH
body: { "login": "...", "senha": "...", "system": "web", "deviceToken": "..." }
200: { "access_token": "eyJ...", "token_type": "bearer", "expires_in": 30568235463, "usuario": {...} }
Erros: {"error":"Invalid credentials"} | {"error":"Missing data"} | {"error":"Invalid hash"}
```
- `expires_in` enorme (~970 anos) → na prática o token não expira; mesmo assim, renovar a cada 24 h e em qualquer 401.
- O `usuario.idCalendario` do retorno é o calendário do próprio usuário logado (irrelevante para o Apex.BI).

## 2. Pacientes

### 2.1 Buscar (evitar duplicidade)
```
GET /pacientes?hash=HASH&token=TOKEN&busca=<nome|CPF|RG|prontuário>&celular=<ddd+numero>&page=N
```
- Filtros opcionais: `busca`, `convenio`, `celular`, `sexo`, `mae`, `pai`, `bairro`, `cidade`, `estado`, `profissao`, `estadocivil`, `status`.
- Paginado: `{ total, per_page: 200, current_page, last_page, data: [...] }`.
- **Estratégia da IA:** buscar por `celular` (número do WhatsApp) e depois por `busca=<CPF>`; se encontrar, reutilizar o `id`.

### 2.2 Detalhes
```
GET /paciente/{id}?hash=HASH&token=TOKEN
```

### 2.3 Criar / atualizar  ← **usado pela IA**
```
POST /paciente/salvar?hash=HASH&token=TOKEN
```
"Adiciona pacientes ao sistema **ou edita se o CPF já for encontrado**."

> ⚠️ **Testado em 22/09/2026: a edição por CPF é uma SUBSTITUIÇÃO COMPLETA** — campos não enviados são apagados (um reenvio com só `nome+cpf+convenio` zerou nascimento, e-mail, celular e endereço). **Não existe endpoint de atualização parcial em nenhum módulo da documentação** (o `POST /rest/paciente/edita` da API do Paciente exige o token do próprio paciente). O campo opcional `id` do `salvar` não é documentado — não usar. **Regra da IA:** só chamar `salvar` para paciente **novo** (após `buscar_paciente` não encontrar). Se um dia precisar atualizar: `GET /paciente/{id}` → mesclar → reenviar o cadastro inteiro (a ferramenta faz a mescla; o modelo nunca envia payload parcial).

| Campo | Obrig. | Formato / valores aceitos |
|---|---|---|
| `nome` | **sim** | texto |
| `cpf` | não | `xxx.xxx.xxx-xx` ou só dígitos |
| `nascimento` | não | **`dd/mm/YYYY`** |
| `celular` | não | texto (a clínica grava 11 dígitos sem máscara) |
| `telefone`, `email` | não | |
| `endereco`, `n`, `apt`, `bairro`, `cidade`, `uf` (ex. `SP`), `cep` | não | `apt` = complemento |
| `sexo` | não | `Masculino` / `Feminino` |
| `genero` | não | lista fechada (Masculino, Feminino, Transhomem, …) |
| `estadocivil` | não | Solteiro, Casado, Divorciado, Viúvo, Separado, União estável |
| `convenio` | não | id do convênio — Passoni usa **1** = PARTICULAR. ⚠️ **Testado: `idConvenioCliente` é ignorado (convênio fica vazio); o nome correto é `convenio`.** |
| `medico` | não | idCalendario do profissional responsável — **não enviar** (a recepção não preenche; decisão da clínica 21/09/2026) |
| `indicado` | não | "como nos conheceu" — texto livre (valores usados: `INSTAGRAM DRA. LUCIANA`, `GOOGLE`, `INSTAGRAM PASSONI CLINIC`, `CAMPANHA DE MENSAGENS`) |
| `responsavel`, `parentesco_responsavel` (Mãe, Pai, Irmão, Irmã, Tio, Tia, Padrinho, Madrinha, Primo, Prima, Outro), `cpf_responsavel` | não | para menores |
| `aceitaCpfDuplicado`, `aceitaNomeDuplicado` | não | `1` para confirmar cadastro duplicado |
| outros | não | `identidade`, `cns`, `carteira`, `validade` (dd/mm/YYYY), `plano`, `nomemae`, `nomepai`, `nomeconjuge`, `profissao`, `grauInstrucao`, `formacao`, `religiao`, `senha`, `FL_TIPO_SANGUINEO`, `FL_FATOR_RH` (+/−) |

Retorno 200: objeto do paciente com **`id`** (usar no agendamento).

**Testado em 21–22/09/2026 (paciente id 6436):** a API normaliza `sexo` e `email` para MAIÚSCULAS e devolve `nascimento` em ISO. `idConvenioCliente=1` **não grava** o convênio (ficou vazio na tela) — usar `convenio=1`.

**Restrição do agente:** `agendar_consulta` só aceita `idProcedimentos` **264** (PC - CONSULTA EQUIPE MÉDICA → `idCalendario` 36, Dr. Lucas, R$ 800) ou **5** (PC - CONSULTA DRA. LUCIANA → `idCalendario` 1, R$ 1.200). Qualquer outro procedimento é recusado pela ferramenta, independentemente do que o modelo peça.

Erros relevantes: `Invalid cpf` · `Duplicate patient cpf` · `Duplicate patient name` (reenviar com `aceitaNomeDuplicado=1` após checar que é outra pessoa) · `invalidate date of birth` · `invalidate e-mail` · `incorrect value of sex` · `Missing agreement` · `Missing doctor`.

### 2.4 Agendamentos de um paciente
```
GET /paciente/{id}/agenda/{idCalendario?}?hash=HASH&token=TOKEN&data=&status=
```
Paginado. Útil para detectar "já tem consulta marcada" e para a frente de consultas canceladas.

## 3. Agenda

### 3.1 Calendários
```
GET /calendarios?hash=HASH&token=TOKEN   → [{ id, nome, idUsuario }]
```
Passoni: **1 = Dra. Luciana**, **36 = Dr. Lucas Vieira** (ver `04-tisaude-modelo-dados.md`).

### 3.2 Listar agendamentos (ocupação)
```
GET /agenda/{idCalendario?}?hash=HASH&token=TOKEN&dataInicio=YYYY-MM-DD&dataFim=YYYY-MM-DD
GET /agenda/{idCalendario?}?...&data=YYYY-MM-DD
```
Retorna lista com `id, idPcte, data, hora, idConvenio, idProcedimento, idCalendario, marcacao, status, marcadopor, deletado, local, infoLocal{...}`.

### 3.3 Criar agendamento  ← **usado pela IA**
```
POST /agendamento/adicionar?hash=HASH&token=TOKEN
```
| Campo | Obrig. | Valor para a Passoni |
|---|---|---|
| `idpcte` | **sim** | id do paciente (2.3) |
| `idCalendario` | **sim** | 1 (Dra. Luciana) ou 36 (Dr. Lucas) |
| `idProcedimentos` | **sim** | `5` (PC - CONSULTA DRA. LUCIANA) ou `264` (PC - CONSULTA EQUIPE MÉDICA); vários → `"1,2,3"` |
| `local` | sim* | `1` (PASSONI CLINIC - SP) — *obrigatório só se houver >1 local; enviar sempre |
| `data` | não** | **`dd/mm/YYYY`** — **se omitido grava a data de hoje; enviar sempre** |
| `hora` | não** | `HH:ii:ss` (ex. `14:00:00`) — enviar sempre |
| `observacoes` | não | texto — usar para rastrear: `"Agendado pela IA (Celeste) via WhatsApp — frente leads_perdidos — conversa #123"` |

Retorno 200: `{ id, idPcte, data, idConvenio, procedimento, idProcedimento, hora, idCalendario, local, status: 0, marcacao, duracao, horafinal, observacoes }`.
Erros: `Missing data` · `Invalid hash` · `Patient not found` · `Missing Local`.

⚠️ **A API não valida conflito de horário** (nada na doc indica isso). A IA deve checar ocupação (3.2 ou 3.5) imediatamente antes de criar e re-checar depois (ler de volta com 3.2) para detectar corrida com a recepção.

### 3.4 Editar / remarcar / cancelar  ← **usado pela IA (cancelar/reagendar)**
```
POST /agendamento/editar/{idAgendamento}?hash=HASH&token=TOKEN
campos opcionais: data (dd/mm/YYYY), hora (HH:ii:ss), idpcte, idCalendario, idProcedimento, local, observacoes, status
```
**Status:** `0` Marcado · `1` Em espera · `2` Atendido · `3` Confirmado · `4` Solicitado · `5` Em atendimento · `-1` Falta · `-2` Desmarcado.
- Cancelar = `status=-2`. Confirmar presença (após o lembrete "1") = `status=3`. Remarcar = novo `data`/`hora`.

> ⚠️ **Testado em 22/09/2026: `editar` é SUBSTITUIÇÃO COMPLETA.** Enviando só `{status: 3}`, a API trocou `hora` pela hora da chamada e apagou o convênio do agendamento. **Sempre reenviar o agendamento inteiro** (`data` dd/mm/YYYY, `hora`, `idpcte`, `idCalendario`, `idProcedimento` — singular aqui, plural no `adicionar` —, `local`, `observacoes`) junto com o `status`. A ferramenta da IA faz `GET /agendamento/{id}` → mescla → `editar` completo; o modelo nunca envia payload parcial.
>
> **Teste 2 (22/09/2026, id 47186713):** com payload completo, `hora` e demais campos se mantêm em 0 → 3 → −2, e o horário volta ao `horasDisponiveis` após −2. Porém `idConvenio` foi para `null` mesmo assim — o `editar` não herda o convênio. **Teste 3 (mesmo id): enviando `idConvenio=1` no `editar`, o convênio é aceito e preservado.**
>
> **Payload final e validado do `editar`:** `data` (dd/mm/YYYY), `hora` (HH:MM:SS), `idpcte`, `idCalendario`, `idProcedimento`, `local=1`, `observacoes`, **`idConvenio=1`**, `status`. Outros fatos do retorno: `duracao: 60` e `horafinal` (consulta = 60 min); `link_agendamento` (`https://tisau.de/...`, link curto para o paciente); `observacoes` vem `null` no POST — o texto está em `obs` no `GET /agendamento/{id}`; `marcacao` é atualizada a cada edição (= última modificação; guardar a data de criação no nosso banco).

### 3.5 Horários disponíveis (API do Paciente) — **VALIDADO em 22/09/2026**
```
GET /rest/agenda/horasDisponiveis/{idUsuarioProfissional}?hash=HASH_PAC&data=YYYY-MM-DD
→ [{ cliente, id, medico: <idCalendario>, dia (1=dom…7=sáb), horario: "15:00:00", numatendimentos: 1,
     numatendimentos_home_service: 0, origem: "clinic", local: {...} }]
GET /rest/agenda/profissional/{idUsuarioProfissional}?hash=HASH_PAC   → dias[] com horários por período e local
```
- **Devolve os horários LIVRES do dia** (já desconta os agendamentos com status que ocupam; dia cheio → `[]`). Validado contra a tela da agenda em vários dias.
- Usa o **id do usuário** (79786 Dr. Lucas, 29110 Dra. Luciana); com idCalendario retorna 404 `User not found`. Só `hash` da API do Paciente, sem token.
- Grade real varia por dia da semana (Dr. Lucas: 10, 11, 15, 16, 17). A recepção faz encaixes fora da grade, que aparecem em `GET /agenda` mas não aqui.
- **`buscar_horarios`** = horasDisponiveis(data) − ocupados de `GET /agenda/{cal}` (redundante; proteção contra corrida) − horários passados/antecedência mínima (YAML) − feriados/recesso (YAML). Uma chamada por dia da janela (14 dias = 14 GETs, rápidos).

### 3.6 Outros
- `GET /agendamento/{id}` — detalhes (inclui `obs`, `dataconfirmado`, `datadesmarcado`, `motivoFalta`, `valor`).
- Sub-procedimentos: `GET /agendamento/subprocedimentos/{id}`, `POST /agendamento/adicionar/subprocedimentos/{id}` — não usados para consulta.

## 4. Procedimentos e convênios (leitura)
- `GET /procedimentos` → `[{ id, tipo, descricao, codigo, tuss, dias_retorno, local, idConvenioCliente, flag_financeiro, usadoemagendamento }]`.
- `GET /procedimento/{id}`, `POST /procedimento/adicionar`, `POST /procedimento/editar/{id}` (campo `duracao` em minutos — verificar se 5 e 264 têm 60).
- `GET /convenios`, `GET /convenio/{id}` — Passoni: id 1 = particular.

## 5. Clínica e usuários (leitura)
- `GET /cliente` — dados da clínica.
- `GET /usuarios?busca=` — lista; `idCalendario` liga usuário → agenda.
- `GET /usuario/{id}`.

## 6. Módulos secundários (endpoints mapeados)

| Módulo | Endpoints | Uso futuro |
|---|---|---|
| Guias / Orçamentos | `GET /guias/{idDoPaciente?}?inicio&fim&status&page`, `GET /orcamentos/{idDoPaciente?}?inicio&fim&page` | frente **orçamento não fechado** (orçamentos emitidos e não convertidos em solicitação) |
| Prontuário | `GET /prontuarios`, `GET /paciente/{id}/prontuarios`, `GET /prontuario/{id}`, `POST /prontuario/adicionar/{idPcte}` | não usar (dados clínicos; `Permission denied` para usuários sem perfil) |
| Cirurgias | `GET /cirurgias`, `GET /paciente/{id}/cirurgias`, `GET /cirurgia/{id}` | não usar |
| Financeiro | `GET /financeiro/receitas`, `/despesas`, `/boletos` (`inicio`, `fim`, `status`) | painel financeiro (já no pipeline) |
| API do Paciente — auth | `POST /rest/login`, `POST /rest/cadastro?v=2`, `/rest/cadastrosms`, `/rest/novasenha`, `/rest/senha/sms`, `/rest/senha/reset`, `GET|POST /rest/paciente/termodeuso` (todos com `hash=HASH_PAC`) | não usar (fluxo de app do paciente) |
| API do Paciente — util | **`GET /rest/paciente/cpf/{cpf}?hash=HASH_PAC`** — "verifica se o paciente existe na clínica" | **dedup rápido antes de `criar_paciente`** (validar em teste) |
| API do Paciente — perfil | `GET /rest/paciente/dadospessoais`, `POST /rest/paciente/edita`, `GET /rest/paciente/agendamentos`, `POST /rest/paciente/agendamento/status` (`estado` 3 ou −2, `cliente=12054`) | alternativa para confirmar/desmarcar como paciente |

## 7. Fluxo final das ferramentas da IA

```
buscar_paciente(celular, cpf)
   GET /pacientes?celular=…  → se vazio, GET /pacientes?busca=<cpf>
criar_paciente(dados)
   POST /paciente/salvar  (nome MAIÚSCULAS, cpf, nascimento dd/mm/YYYY, sexo Masculino/Feminino, email,
                           celular=<whatsapp com DDD>, indicado=<encaminhado por>, convenio=1,
                           cep + n + apt + endereco/bairro/cidade/uf via ViaCEP; sem `medico`)
buscar_horarios(profissional, de, ate)
   grade (YAML ou 3.5) − GET /agenda/{idCalendario}?dataInicio&dataFim (status ≠ −2, deletado=0)
   − feriados − recesso − passado − antecedência mínima (ex.: ≥ 2 h)
agendar_consulta(idpcte, profissional, data, hora)
   re-checar slot → POST /agendamento/adicionar (data dd/mm/YYYY, hora HH:MM:00, local=1,
   idProcedimentos=5|264, observacoes="IA Celeste | frente | conversa")  → ler de volta
confirmar_presenca(idAgendamento)      POST /agendamento/editar/{id}  status=3
reagendar(idAgendamento, data, hora)   POST /agendamento/editar/{id}  data, hora
cancelar(idAgendamento, motivo)        POST /agendamento/editar/{id}  status=-2, observacoes+=motivo
sync_status (job a cada 15 min)        GET /agenda?dataInicio&dataFim → métricas do painel
```

## 8. Validação em produção (21–22/09/2026) — resultado

| # | Item | Resultado |
|---|---|---|
| 1 | `POST /paciente/salvar` | ✅ paciente 6436 criado; `nascimento` dd/mm/YYYY, `celular` 11 dígitos, `convenio=1`; sexo/e-mail normalizados para maiúsculas. ⚠️ edição por CPF substitui tudo. |
| 2 | `POST /agendamento/adicionar` + `editar` | ✅ id 47186713 (27/10 17:00, Dr. Lucas): 0 → 3 → −2; `editar` exige payload completo + `idConvenio=1`. |
| 3 | Conflito de horário | ⏳ não testado ainda (a API provavelmente aceita; a ferramenta checa antes e depois). |
| 4 | `horasDisponiveis` | ✅ funciona com `HASH_PAC` e **id do usuário**; **já desconta ocupados**; encaixes fora da grade aparecem só no `GET /agenda`. |
| 5 | Duração | ✅ `duracao: 60` no retorno do agendamento (consulta = 60 min). |
| 6 | `marcadopor` | ✅ "Tecnologia - IA" (usuário de integração próprio). |

Pendências: teste de conflito (opcional); apagar paciente 6436 e agendamento 47186713 pela interface ao fim dos testes.
