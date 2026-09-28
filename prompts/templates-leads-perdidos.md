# Templates de resgate — Leads Perdidos (proposta v0 para aprovação na Meta)

> Idioma `pt_BR`. `{{1}}` = primeiro nome do lead. Botões = *quick reply* (a resposta do lead abre a janela de 24 h e a IA assume).
> Categoria: submeter os templates 1 e 3 como **UTILITY** (referem-se a um contato anterior do próprio lead); se a Meta reclassificar como MARKETING, aceitar — o custo é maior (US$ 0,062 × US$ 0,007) mas o texto não muda.
> Rodapé de opt-out em todos: "Se preferir não receber mais mensagens, responda SAIR."

## Ciclo de abordagem

```
Ciclo 1 (lead nunca contatado pela IA)
  D0    T1  resgate_lembramos_de_voce      → responde? IA assume
  D+3   T2  resgate_poucos_horarios        → responde? IA assume
  D+10  T3  resgate_o_que_dificultou       → responde? IA assume (o botão já traz a objeção)
  D+10  sem resposta → status "Template enviado (2°)" · pausa

Ciclo 2 (40 dias após o fim do ciclo 1, se ainda elegível)
  D0    T4  resgate_agenda_do_mes          → responde? IA assume
  D+7   T5  resgate_hoje_a_tarde (só em dia com horário livre à tarde)
  sem resposta → pausa de 90 dias; depois volta ao Ciclo 2 com o template de melhor taxa

Regras
  • máximo 3 templates por ciclo, nunca dois no mesmo dia, só seg–sex 9h–18h
  • lead que respondeu a qualquer template sai do ciclo e passa à cadência de follow-up da conversa (D+1, D+3, D+7…)
  • lead com status "Achou caro" / "Quer pelo convênio" volta em 30 / 60 dias direto no T3 (objeção)
  • "Vamos retornar na data solicitada" → T2 na data
  • qualquer "SAIR", "pare", "não quero" → opt-out permanente
  • a IA nunca reenvia um template que o lead já recebeu no mesmo ciclo
```

## T1 — `resgate_lembramos_de_voce` (UTILITY tentativa; D0)

**Corpo**
> Olá, {{1}}, tudo bem? 😊 Aqui é a Celeste, da Passoni Clinic.
>
> Estávamos revisando nossa agenda e lembramos de você: há um tempo conversamos sobre sua consulta com a Dra. Luciana Passoni e esse cuidado acabou não acontecendo.
>
> Sabemos que a rotina faz algumas decisões ficarem para depois. Mas, quando falamos em saúde capilar, o momento da avaliação faz toda a diferença. Porque tempo é cabelo. 🤍
>
> Se ainda fizer sentido para você, é só me responder por aqui que eu vejo um horário.

**Botões:** `Quero ver horários` · `Tenho uma dúvida` · `Agora não`
**Rodapé:** Se preferir não receber mais mensagens, responda SAIR.

## T2 — `resgate_poucos_horarios` (MARKETING; D+3)

**Corpo**
> Oi, {{1}}! 😊 Celeste, da Passoni Clinic.
>
> Passando para avisar que a agenda desta e da próxima semana está com poucos horários para consulta — com a Dra. Luciana e com o Dr. Lucas Vieira, nosso Diretor Médico.
>
> Quer que eu reserve um para você? Me diz o melhor dia e período que eu confiro na hora.

**Botões:** `Sim, quero reservar` · `Prefiro outra semana` · `Agora não`
**Rodapé:** Se preferir não receber mais mensagens, responda SAIR.

## T3 — `resgate_o_que_dificultou` (UTILITY tentativa; D+10 e retorno de objeções)

**Corpo**
> {{1}}, tudo bem? Aqui é a Celeste, da Passoni Clinic. 🤍
>
> Vi que você chegou a se interessar pela consulta, mas não seguimos com o agendamento. Existe algo que esteja dificultando marcar agora?
>
> Podemos ver outras opções de data e horário, ou esclarecer qualquer dúvida — sobre a consulta, os valores ou como funciona o tratamento.

**Botões:** `Dúvida sobre valor` · `Dúvida sobre horário` · `Outra dúvida`
**Rodapé:** Se preferir não receber mais mensagens, responda SAIR.

## T4 — `resgate_agenda_do_mes` (MARKETING; ciclo 2, D0)

**Corpo**
> Olá, {{1}}! 😊 Celeste, da Passoni Clinic.
>
> Abrimos a agenda de consultas de {{2}} com a Dra. Luciana Passoni e com o Dr. Lucas Vieira. Como você já tinha conversado com a gente, quis te avisar antes de os horários preencherem.
>
> A consulta inclui a avaliação médica completa e o exame de tricoscopia, que analisa em detalhes o couro cabeludo e os fios.
>
> Quer que eu veja um horário para você?

**Variáveis:** `{{2}}` = mês ("outubro")
**Botões:** `Quero agendar` · `Me conta mais` · `Agora não`
**Rodapé:** Se preferir não receber mais mensagens, responda SAIR.

## T5 — `resgate_hoje_a_tarde` (MARKETING; só quando há horário livre hoje à tarde)

**Corpo**
> {{1}}, boa tarde! Celeste, da Passoni Clinic. 😊
>
> Surgiu um horário hoje às {{2}} para consulta com o {{3}}, aqui na clínica (Moema, em frente ao Parque Ibirapuera, com valet).
>
> Se conseguir vir, eu reservo para você agora mesmo. Me responde por aqui?

**Variáveis:** `{{2}}` = horário ("16h"), `{{3}}` = profissional ("Dr. Lucas Vieira" / "Dra. Luciana Passoni")
**Botões:** `Consigo hoje` · `Outro dia` · `Agora não`
**Rodapé:** Se preferir não receber mais mensagens, responda SAIR.

## O que a IA faz com cada botão

| Botão | Ação da IA |
|---|---|
| Quero ver horários / Sim, quero reservar / Quero agendar / Consigo hoje | apresenta as 2 modalidades (se ainda não conhece) e oferece 2–3 horários de `buscar_horarios` |
| Tenho uma dúvida / Outra dúvida / Me conta mais | pergunta qual é e responde com a base de conhecimento |
| Dúvida sobre valor | script de valores (R$ 1.200 / R$ 800 + o que inclui) e, se insistir, política de tratamento |
| Dúvida sobre horário | pergunta preferência de dia/período e oferece horários |
| Prefiro outra semana / Outro dia | pergunta a semana e agenda o follow-up para ela |
| Agora não | "Sem problemas, no seu tempo marcamos 😊" + pergunta se há algo dificultando; status "Irá nos retornar", recontato em 30 dias |
| SAIR / pare / não quero | opt-out permanente, mensagem cordial de encerramento |

## Métricas por template (painel)
enviados · entregues · lidos · respondidos (%) · por botão · agendados originados · falhas · qualidade Meta. O ciclo 2 usa, no lugar de T4, o template de maior taxa de resposta do ciclo 1 quando esta for maior.
