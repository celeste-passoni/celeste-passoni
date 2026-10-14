# Fluxograma — Leads Perdidos (Celeste) · estado em 14/10/2026

Documento vivo. Fonte da verdade do que está no ar: `config/parametros.yaml` (esteira, textos fixos), `src/celeste/jobs/templates_texto.py` (templates), `prompts/leads-perdidos-v0.md` (roteiro) e `knowledge/03-exemplos-de-conversas.md` (exemplos reais que a Celeste imita).

## 1. Visão geral

```mermaid
flowchart TD
    A[Base Leads Perdidos<br/>query da clínica · 445 elegíveis<br/>job carregar-base 06:00 · pausado] --> B[Esteira de templates<br/>job disparos · pausado]
    B --> T1[T1 · resgate_solicitacao_pendente<br/>UTILITY · botões Quero continuar / Agora não]
    T1 -->|toca Quero continuar<br/>ou escreve| C[Celeste assume a conversa]
    T1 -->|toca Agora não| AN[Mensagem fixa: pergunta o motivo<br/>+ botão Não quero continuar<br/>status Agora não]
    T1 -->|sem resposta · 1 dia| T2[T2 · resgate_solicitacao_segue_pendente<br/>UTILITY · mesmos botões]
    AN -->|escreve o motivo| C
    AN -->|toca Não quero continuar| OUT[Despedida · opt-out · sai da esteira]
    AN -->|silêncio · 1 dia| T2
    T2 -->|toca Quero continuar<br/>ou escreve| C
    T2 -->|toca Agora não| AN
    T2 -->|sem resposta · 3 dias| T3[T3 · provisório<br/>a definir pela clínica]
    T3 -->|sem resposta · 8 dias| T4[T4 · provisório<br/>a definir pela clínica]
    T4 -->|sem resposta| P[Pausa 30 dias → recomeça no T3]
    C --> F[Fluxo de atendimento · seção 2]
```

## 2. Atendimento pela Celeste (dentro da janela de 24 h)

```mermaid
flowchart TD
    S([Lead responde]) --> AP[Apresentação · 1–2 balões<br/>não se apresenta de novo se veio do T1/T2]
    AP --> M{Já sabe a modalidade?}
    M -->|não| MOD[Script das duas modalidades<br/>Qual seria a melhor opção para você?]
    M -->|sim| AG
    MOD --> AG[Agenda: Quando você poderia vir? /<br/>Como está a sua agenda na próxima semana?]
    AG --> H[buscar_horarios · 2–3 opções reais<br/>Lhe atende? / Posso reservar para você?]
    H --> OBJ{Objeção?}
    OBJ -->|valor, convênio, parcela, online,<br/>mora longe, Dr. Lucas, já fiz de tudo| SC[Texto fixo da casa · uma vez<br/>e volta para a agenda]
    SC --> H
    OBJ -->|vou pensar| INC[Incentivo único · tempo é cabelo<br/>+ o que está dificultando?]
    INC -->|mantém| RET[Combinado! Aguardo o seu retorno<br/>status Irá nos retornar · esteira recontata]
    INC -->|segue| H
    OBJ -->|não| PC[Pré-cadastro · lista de dados]
    PC -->|passa os dados| CAD[criar_paciente · nome completo sem abreviação]
    PC -->|recusa| INS[Insiste UMA vez]
    INS -->|recusa de novo| GEN[Cadastro genérico · nome + sexo<br/>CPF vazio · demais genéricos]
    INS -->|passa| CAD
    CAD --> AGD[agendar_consulta no TI Saúde]
    GEN --> AGD
    AGD --> CONF[Confirmação · 2–3 balões<br/>endereço · antecedência · cabelos limpos e secos]
    CONF -->|cadastro genérico| AV[Aviso: no dia a recepção pede os dados completos]
    CONF --> FIM([Agendado · missão cumprida])
```

### Regras transversais (sempre)

- **Consulta já marcada:** se o lead falar dela, `consultar_agendamento` antes de responder; nunca deduzir por horários livres.
- **Cancelamento:** 1) pergunta o motivo → 2) oferece solução → 3) só cancela se o lead insistir depois da solução (a ferramenta recusa sem os três).
- **Alteração cadastral a pedido:** qualquer dado, inclusive CPF; nome a API não altera → registra para a recepção.
- **Recepção só em 4 casos:** já é paciente em tratamento; assunto clínico; reclamação/reembolso; pediu pessoa. Botão "Falar com Recepção".
- **Horários:** sempre da agenda do TI Saúde; sem lista de feriados; orientação de que a clínica não atende fim de semana nem feriado.
- **Nunca:** diagnosticar, valor de tratamento, desconto, parcelar consulta, online, convênio, inventar informação (→ `sinalizar_revisao`), dizer que é IA.

## 3. O que ainda não existe (pendente)

| Item | Estado |
|---|---|
| T3 e T4 definitivos | a definir pela clínica (hoje: textos antigos do MarketZap, não cadastrados na Meta) |
| Lembrete de retomada no mesmo dia | implementado (texto fixo por etapa), scheduler pausado |
| Confirmação de presença (D-1), lembrete do dia, pós-consulta | dependem de templates de utilidade ainda não criados |
| Ligar a esteira e a base | decisão da clínica para o piloto |

## 4. Custos por lead (ordem de grandeza)

- Template de utilidade: centavos de dólar por envio. Conversa típica com a Celeste (8–10 respostas): ~US$ 0,35–0,45. Renovação de cache: ~US$ 0,60/dia.
