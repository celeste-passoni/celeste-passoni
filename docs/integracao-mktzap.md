# Celeste no MarketZap: proposta de arquitetura (25/11/2026)

Status: **proposta, aguardando aprovação**. Nada foi implementado nem alterado em produção.

## 1. O que foi levantado

### Número e conta na Meta (consulta só leitura, 25/11)
| | Número da Celeste hoje | Número do MarketZap (recepção) |
|---|---|---|
| Telefone | +55 11 94231-5926 | +55 11 91606-9009 |
| WABA | 2053539948590151 | 1470345631783377 ("Passoni Clinic") |
| phone_number_id | 1219345307926640 | 658241090708883 |
| Dono da WABA | Passoni Clinic (BM 955343385821935) | **Passoni Clinic (mesmo BM)** |
| App inscrito no webhook | app da clínica 1219806986973585, que aponta para o gateway da Celeste | só o MarketZap (app 1113167412110083) |
| Qualidade | GREEN | GREEN |
| Templates | os da Celeste | 29 templates da equipe (nenhum da Celeste) |

O token de sistema da Celeste já lê essa WABA (números e templates). Como a WABA é da clínica, o app da Celeste
**pode ser inscrito nela também**. A Meta permite vários apps na mesma WABA e cada um recebe o seu webhook. O MarketZap
continua recebendo tudo normalmente.

### API pública do MarketZap (https://apidoc.mktzap.com.br, v1.6.1)
- Base `https://api.mktzap.com.br`. Token por `GET /company/:id/token?clientKey=` (vale 1 h, `Authorization: Bearer`).
- **Não existe webhook** de mensagem recebida, transferência ou mudança de setor. Para ler, só consulta:
  `GET /history` / `/historycontact` (filtros `updatedFrom`, `protocol`, `contact_id`; devolve `sector_id`,
  `operator_assigned_id`, `is_auto`, `protocol`) e `GET /history/:id/message` (`sent_by_operator`, `user_id`, `message` em JSON).
- Envio dentro da janela: `POST /history/:history_id/send-message-waent`, que manda **texto, imagem ou documento** com
  `operator_user_id`. A resposta é só `{success: true}`, **sem o id da mensagem (wamid)**.
- Template (HSM): `POST /history/send-hsm` (`hsm_id`, `params`, `operator_user_id`, `is_auto`, `contact_already_exists`).
  Lista de templates: `POST /history/post-hsm-template`.
- Mensagem interativa (lista ou botões), com a janela de 24 h aberta: `POST /history/send-interactive-message`.
- Gestão do atendimento: `sector-change`, `transfer-operator`, `transfer-no-operator` (sai do modo automático e entra na
  distribuição da equipe) e `finish-attendance`. Listas de setores, usuários, status e canais.
- Upload de mídia: só PNG, JPEG e PDF. **Não há envio de vídeo nem de áudio.** Há limite de requisições (HTTP 429),
  mas o valor não está documentado.

### O que a Celeste usa da Meta hoje (código)
- Entrada: `gateway/app.py`, que recebe o webhook, normaliza com `meta.normalizar_webhook`, grava em `conversas/{id}/mensagens/{wamid}`
  e agenda o debounce no Cloud Tasks. Nada disso diferencia o número de destino (`phone_number_id`).
- Saída (`ferramentas/meta.py`): `enviar_texto`, `enviar_imagem_link`, `enviar_video_link`, `enviar_botao_url` (encaminhamento),
  `enviar_template` (esteira, lembretes, retornos, rotinas de consulta, aviso à recepção), `marcar_lida` e `baixar_midia`
  (áudio para transcrição, imagem para o modelo).
- O encaminhamento atual manda o lead **para o próprio número do MarketZap** (botão "Falar com Recepção" → wa.me/5511916069009).
  Dentro do MarketZap, isso passa a ser uma transferência interna.

## 2. Arquitetura proposta

```
Lead ── WhatsApp (+55 11 91606-9009) ── Meta
                                          ├── webhook → MarketZap (como hoje; a equipe vê tudo)
                                          └── webhook → gateway da Celeste (NOVO: inscrição do app na WABA)
gateway: filtra por phone_number_id
   ├── 1219345307926640 (número atual)  → fluxo de hoje, sem mudança
   └── 658241090708883 (MarketZap)      → só segue se o atendimento estiver no SETOR CELESTE (consulta ao MktZap)
orquestrador: mesmo motor, prompt e ferramentas → saída por um "canal"
   ├── canal meta   (conversas do número atual)
   └── canal mktzap (send-message-waent / send-hsm com operator_user_id = usuário Celeste)
job "mktzap-sincronizar" (a cada 1 min): transferências para o setor, mensagens de pessoas da equipe, atendimentos fechados
```

### 2.1 Entrada em tempo real: webhook da Meta (recomendado)
1. **Antes de tudo**, publicar o gateway com o filtro por `phone_number_id`. Sem esse filtro, a inscrição faria o gateway
   abrir conversa (e a IA tentar responder) para **todo mundo** que escreve à recepção.
2. Inscrever o app da Celeste na WABA 1470345631783377 (`POST /{waba}/subscribed_apps`). É uma mudança de configuração na
   Meta que só será feita com OK explícito e pode ser desfeita com um `DELETE`.
3. Mensagem do número do MarketZap → o gateway confere se o contato tem conversa aberta da Celeste. Se não tiver, consulta o
   MarketZap (`/historycontact?contact_id=`, com cache de 1–2 min) para saber o setor do atendimento aberto:
   - **setor Celeste** → grava e agenda a resposta. O formato é o mesmo do webhook de hoje (texto, áudio, imagem, botão,
     reação), então transcrição e visão continuam iguais. A mídia é baixada pela Meta com o token atual;
   - outro setor → **descarta sem gravar** (privacidade: o gateway passa a ver tudo o que chega à recepção, mas não guarda).
4. Na hora de responder, o orquestrador confere o setor de novo. Se uma pessoa da equipe assumiu o atendimento nesse meio-tempo,
   a Celeste não responde.

Alternativa sem mexer na Meta: **só polling** do MarketZap (a cada 15–60 s). A resposta chega com até 1 min de atraso,
depende do limite de requisições (não informado) e do formato de áudio e botão do MarketZap (que não está documentado),
e um intervalo menor que 1 min exige uma instância sempre ligada (≈ US$ 10–25/mês). Fica como plano B.

### 2.2 Sincronização a cada minuto (o webhook da Meta não mostra isso)
Mensagens enviadas pelo MarketZap não voltam pelo webhook da Meta, e transferências de setor não geram evento. Um job novo,
`/jobs/mktzap-sincronizar`, roda a cada 1 min no Cloud Scheduler e faz três coisas:
- **Transferido para o setor Celeste** (pela distribuição ou por uma pessoa): cria a conversa (`canal: mktzap`, `protocolo`,
  `history_id`), importa o histórico do MarketZap para a Celeste ter o contexto e responde se a última mensagem for do lead;
- **Mensagem de pessoa da equipe** num atendimento da Celeste (`sent_by_operator=1` e `user_id` diferente do usuário Celeste):
  grava como "enviada por uma pessoa da equipe" e passa a conversa para `modo: humano` (a mesma regra do painel);
- **Atendimento saiu do setor ou foi finalizado** no MarketZap: fecha ou pausa a conversa na Celeste.

### 2.3 Saída pelo MarketZap
Uma camada de canal (`ferramentas/canal.py`) com a mesma interface de hoje. As conversas ganham o campo `canal` (`meta`|`mktzap`),
o que permite aos dois números conviverem durante a transição:

| Hoje (Meta) | Canal MarketZap |
|---|---|
| `enviar_texto` | `send-message-waent` type text. O MarketZap recusa mais de 255 caracteres (HTTP 422, teste de 25/11/2026); acima de `mktzap.limite_texto` (250), o texto sai em mensagens seguidas, quebrado em parágrafo, frase ou palavra |
| `enviar_imagem_link` (antes e depois) | `send-message-waent` media image (URL pública do bucket) |
| `enviar_video_link` | **lacuna**: ver decisão D3 |
| `enviar_botao_url` "Falar com Recepção" | deixa de existir: a passagem para a equipe vira transferência interna (2.4) |
| `enviar_template` | `send-hsm` (`hsm_id` do MarketZap, `contact_already_exists: true`, `operator_user_id` = Celeste) |
| `marcar_lida` | **desligado**: a Meta recusa o "lida" do app da Celeste no número oficial (code 10, subcode 2593181, 25/11/2026) |
| `baixar_midia` | pela Meta (o `media_id` vem no webhook); funcionou no teste de áudio de 25/11/2026 |

Como o MarketZap não devolve o wamid, a Celeste grava os próprios envios com id `mktzap-<uuid>`. Os status de entrega dessas
mensagens chegam pela Meta, mas não dá para ligá-los a elas (perde-se só a estatística de entregue/lido no painel).

### 2.4 Passagem para a equipe
Quando a Celeste encaminha (o `avisar_recepcao` de hoje, o pedido do lead por humano, assunto fora do escopo ou o botão do painel):
1. ela manda a frase de passagem normalmente;
2. `sector-change` para o setor da equipe (a definir) e então `transfer-operator` para a atendente que divide os Leads Perdidos
   ou `transfer-no-operator` para a distribuição padrão;
3. a conversa fica `modo: humano` na Celeste, com o motivo e o resumo gravados no painel. **Isso resolve a pendência antiga do
   "aviso à equipe"**: a atendente recebe o atendimento já com a conversa inteira na tela.

"Devolver para a Celeste" = a equipe transfere de volta para o setor Celeste no MarketZap, e o job de sincronização religa o `modo: ia`.

### 2.5 Janela de 24 h e templates
- A janela continua contada pela última mensagem do lead (vinda do webhook). As regras de lembretes, esteira e opt-out não mudam.
- Os templates da Celeste precisam **existir na WABA do número do MarketZap** (hoje estão só na WABA 2053539948590151).
  Recriar e mandar para aprovação da Meta; o MarketZap enxerga os templates da WABA e dá o `hsm_id` de cada um
  (pelo `post-hsm-template`). O custo por envio é o mesmo de hoje (marketing ≈ US$ 0,06; utility ≈ US$ 0,007).
- Lacuna: o T1 tem imagem no cabeçalho. A documentação do `send-hsm` não diz como passar a imagem; confirmar com o suporte.
- Lembrete: disparar em massa pelo número oficial afeta a nota de qualidade dele (risco já informado e aceito em 17/11).

### 2.6 Configuração nova
`.env` e Secret Manager: `MKTZAP_COMPANY_ID`, `MKTZAP_CLIENT_KEY`. YAML: `mktzap.usuario_celeste_id`, `mktzap.setor_celeste_id`,
`mktzap.setor_equipe_id`, `mktzap.operador_passagem_id`, `mktzap.broker_phone: "5511916069009"`, `mktzap.phone_number_id: "658241090708883"`.
Os ids são lidos pela API (`/user`, `/sector`) depois que as credenciais estiverem no `.env`.

## 3. Custos
- Meta: receber webhook é grátis. As respostas dentro da janela continuam sem custo. Templates: ver 2.5.
- GCP: um job novo no Cloud Scheduler (≈ US$ 0,10/mês) e um segredo novo (≈ US$ 0,06/mês). As chamadas extras ao Cloud Run e ao
  Firestore são desprezíveis (a recepção recebe ~600 mensagens por mês no número atual; no oficial, estimar pelo BigQuery).
- MarketZap: confirmar se o uso da API pública tem custo no plano da clínica.
- Anthropic: igual ao de hoje, por conversa atendida.

## 4. Decisões para o usuário
- **D1. Entrada**: webhook da Meta, com inscrição do app na WABA do MarketZap e sincronização de 1 min (recomendado), ou só polling.
- **D2. Como os atendimentos chegam ao setor Celeste**: regra de distribuição do MarketZap (qual?), transferência manual,
  disparos da própria Celeste? Existe chatbot ou mensagem automática do MarketZap nesse setor? Se existir, precisa ser desligado
  para não responder junto com a Celeste.
- **D3. Vídeo** (o MarketZap não envia vídeo): (a) mandar o vídeo direto pela Meta no mesmo número; o lead recebe normal, mas
  **a equipe não vê o vídeo na tela do MarketZap** (recomendado, com uma linha no painel da Celeste); (b) mandar o link do vídeo
  em texto; (c) esperar o suporte do MarketZap.
- **D4. Passagem**: para qual setor e para quem (atendente fixa da divisão ou distribuição automática).
- **D5. Divisão dos Leads Perdidos e % dos novos leads**: feita pela distribuição do MarketZap ou pela Celeste (ex.: par/ímpar)?
- **D6. Número atual (94231-5926)**: continua para a esteira atual durante a transição ou é desligado quando o MarketZap estiver no ar?

## 5. Perguntas para o suporte do MarketZap
1. Existe webhook (mensagem recebida, transferência, mudança de setor) fora da documentação pública?
2. O `send-message-waent` aceita vídeo ou áudio (mesmo sem estar documentado)? E botões de resposta rápida com a janela aberta?
3. Qual é o limite de requisições da API?
4. `send-hsm` com template que tem imagem no cabeçalho: como passar a imagem? Dá para informar o setor (`sector_id`) na v1.2.2?
5. É possível obter o id da mensagem (wamid) enviada pela API?

## 6. Plano de implementação (depois da aprovação)
1. `ferramentas/mktzap.py`: cliente com token em cache, retry em 429 e os endpoints acima, testado com mocks.
2. `ferramentas/canal.py`: interface única; o orquestrador e os jobs escolhem pelo `conv["canal"]`.
3. Gateway: roteamento por `phone_number_id` e filtro de setor. Testes com payloads dos dois números.
4. Job `mktzap-sincronizar` e passagem para a equipe (`sector-change`/`transfer`).
5. ~~Painel~~: fora do escopo (decisão do usuário, 25/11). As métricas vêm da extração do MarketZap que já existe para o Power BI,
   filtrando o setor Celeste. Por isso a falta do wamid nos envios pelo MarketZap não atrapalha.
6. Testes com mocks (pytest) cobrindo entrada, filtro, envio, passagem, sincronização e templates.
7. Só com OK: credenciais no `.env`, deploy, inscrição do app na WABA e teste com os números de teste da clínica, usando um
   atendimento colocado no setor Celeste.

## 7. Implementado em 25/11/2026 (testes simulados; nada publicado)
Decisões do usuário: a Celeste atende só Leads Perdidos, sempre abrindo a conversa com template; o setor "Celeste Maria | IA"
(40523) é exclusivo dela; a Celeste não tem usuário no MarketZap; a passagem para a equipe vai para "Comercial - resgate"
(38306); as métricas saem do Power BI que já existe (sem painel); entrada pelo webhook da Meta até o suporte responder.
- `ferramentas/mktzap.py`: cliente da API, com token em cache, nova tentativa em 429 e renovação do token em 401.
- `ferramentas/canal.py`: `CanalMktZap`, com a mesma interface da Meta. O template sai com `sector_id` e, se o atendimento cair
  em outro setor, é movido; a resposta só sai se o atendimento estiver aberto e no setor 40523; a passagem usa `sector-change`
  e depois `transfer-no-operator`; vídeo vai como link (`mktzap.video: link`).
- Gateway: separa por `phone_number_id`. No número oficial, só entra a resposta de um lead com conversa `canal: mktzap`; o resto
  é descartado sem gravar. Os status de entrega do número oficial também são descartados.
- Orquestrador: escolhe o canal pela conversa (`canal`), confere o setor antes de responder e passa para a equipe no fim da
  resposta, em vez de mandar o botão. Não manda aviso à recepção nem orientação nas conversas do MarketZap.
- Jobs: `disparos.canal` ("meta" por padrão) vale para a esteira e os retornos; lembretes e rotinas usam o canal da conversa.
- `jobs/mktzap_teste.py`: envio manual de 1 template a um número de teste (sem `--enviar` só mostra o que faria).
- `tests/test_mktzap.py`: 28 testes; a suíte inteira passa (196).

**Falta antes do teste real, cada item com OK:**
1. Template da Celeste na WABA do número oficial. Hoje o T1 (`resgate_queda_3cm_v2`) tem imagem no cabeçalho, e a API do
   MarketZap não diz como mandar a imagem. Para o teste: criar uma versão sem imagem ou esperar o suporte.
2. Segredos `mktzap-company-id` e `mktzap-client-key` no Secret Manager, com acesso para o orquestrador e os jobs.
3. Número de teste em `config/atendimento.numeros_teste`.
4. Deploy (gateway e orquestrador) e conferência pelos logs de que o número atual segue igual.
5. Inscrição do app da Celeste na WABA 1470345631783377.
6. Envio do template de teste: `python -m celeste.jobs.mktzap_teste <número> --codigo T1 --nome <nome> --enviar`.
