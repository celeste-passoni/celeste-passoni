# Baseline e Insights para o Design da IA

> Números de referência extraídos do histórico do MarketZap (jun/2025 – set/2026). Servem para (a) calibrar o comportamento da IA e (b) comparar depois no dashboard.

## 1. Volume

| Métrica | Valor |
|---|---|
| Mensagens totais | 528.398 |
| Conversas (history_id) | 57.834 |
| Mensagens das atendentes | 326.477 (62%) |
| Mensagens dos leads/pacientes | 201.921 (38%) |
| Mensagens automáticas (MarketZap) | 52.781 |
| Conversas/mês (média 2026) | ~4.900 |
| Conversas no setor Novos Leads (32139) | 35.009 |
| Conversas no setor Leads Perdidos/Resgate (38306) | 14.527 |

## 2. Tipos de mensagem recebidas (o que a IA precisa interpretar)

| Tipo | Qtde | Observação |
|---|---|---|
| texto | 483.802 | |
| pdf | 13.393 | exames, receitas — maioria enviada pela clínica |
| vídeo | 12.134 | quase todo enviado pela clínica |
| imagem | 9.072 | fotos do couro cabeludo enviadas por leads, prints |
| documento | 4.110 | |
| **áudio/voice** | **5.683** | ~2,8% das msgs dos leads são áudio → transcrição obrigatória |
| contatos / localização | 73 | |

## 3. Tempo de resposta das atendentes (após msg do lead, em horário comercial)

| Atendente | P25 | Mediana | P75 | P90 |
|---|---|---|---|---|
| Novos Leads · atendente 1 | 2 min | 7,4 min | 25 min | 59 min |
| Novos Leads · atendente 2 | 2 min | 7,5 min | 24 min | 59 min |
| Resgate · atendente 1 | 1 min | 3,7 min | 18 min | 74 min |
| Resgate · atendente 2 | 3 min | 8,5 min | 27 min | 72 min |

**Recomendação para a IA:** delay de resposta aleatório entre **45 s e 3 min** (log-normal, mediana ~90 s), sem nunca responder em menos de 30 s. Isso é mais rápido que as humanas (bom para conversão) mas ainda humano.

## 4. Rajadas de mensagens dos leads (calibração do agrupamento)

| Msgs consecutivas do lead | Ocorrências |
|---|---|
| 1 | 64.922 (63%) |
| 2 | 22.944 (22%) |
| 3 | 8.580 (8%) |
| 4+ | 6.162 (6%) |

Intervalo entre balões dentro de uma rajada: mediana **12 s**, P75 **28 s**, P90 **65 s**, P95 **118 s**.

**Recomendação:** debounce de **25–30 s** após a última mensagem (cobre ~75% das rajadas), estendido para até 90 s se a última mensagem terminar sem pontuação/parecer incompleta ou se for áudio (lead costuma mandar 2 áudios seguidos). Se chegar mensagem nova durante a geração da resposta, descartar e regenerar.

## 5. Horário de atividade das atendentes (America/Sao_Paulo)

- 09h–19h, seg–sex. Pico 11h–12h (12% cada). Fim de semana: 0,4%.
- **Decisão (21/09/2026): a IA responde 24/7** (`ia.operacao_24_7`), com delay maior fora do horário comercial (`ia.delay_resposta_segundos.fora_horario_comercial`), e só **inicia** resgates/follow-ups em 9h–19h seg–sex (`ia.iniciar_resgates_apenas_em_horario_comercial`). 8% das msgs dos leads chegam fora do horário — ganho direto de conversão.

## 6. Funil — setor Leads Perdidos/Resgate (38306) — baseline a superar

| Etapa | Qtde | % |
|---|---|---|
| Conversas de resgate | 14.527 | 100% |
| Lead respondeu | 2.858 | **19,7%** |
| Lead enviou dados de cadastro (CPF) | 615 | **4,2%** |
| Sinal explícito de agendamento | 574 | 4,0% |
| Entre os que responderam → cadastro | | **20,5%** |

Cadência de follow-up praticada hoje (dias após a última msg do lead): mesmo dia (18k) · D+1 (1,7k) · D+2–4 (2,7k) · D+4–8 (4,8k) · D+8–15 (2,8k) · D+15–30 (2,1k) · D+30–90 (2,9k) · D+90+ (2,9k).

## 7. Objeções (mensagens de leads contendo o tema)

| Tema | Msgs | Como as atendentes lidam |
|---|---|---|
| Horário / disponibilidade | 8.926 | oferecem 2–3 opções concretas; "poucos horários"; encaixe em desistência |
| Preço / valor / parcelamento | 8.823 | duas modalidades; sem tabela de tratamento; investimento; 10x s/ juros |
| "Depois / vou pensar / semana que vem" | 4.398 | "no seu tempo marcamos" + "existe algo que esteja dificultando?" + follow-ups |
| Dúvida clínica (alopecia, minoxidil, queda…) | 3.760 | "tem tratamento"; explica tricoscopia; vídeo; nunca diagnostica |
| "Só com a Dra. Luciana" | 1.383 | valoriza equipe (mesmos protocolos, Dr. Lucas braço direito) |
| Convênio | 1.327 | particular + NF para reembolso |
| Longe / online / outra cidade | 803 | só presencial; valet; em frente ao Ibirapuera |
| Sem interesse / parar de enviar | 292 | encerrar cordialmente (e a IA deve registrar opt-out) |

## 8. Perfil dos leads (origem, pelo texto de entrada)

- "Olá! Conheci a Dra. Luciana no instagram pessoal dela e gostaria de agendar uma consulta." → anúncio/Instagram (click-to-WhatsApp)
- "Olá! Vi o anúncio da Dra. Luciana e gostaria de mais informações." → anúncio Meta
- "Peguei a indicação da Dra…" → indicação
- Pergunta nº 1 na primeira mensagem: **"Qual o valor da consulta?"**

## 9. Dados sensíveis presentes no histórico

O histórico contém CPF, endereço, e-mail e fotos clínicas de pacientes. Ao usar conversas como exemplos few-shot para a IA, **anonimizar** (substituir nomes/CPF/e-mail/endereço). A base de conhecimento acima já está anonimizada.
