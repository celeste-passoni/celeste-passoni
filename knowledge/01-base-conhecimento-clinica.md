# Base de Conhecimento — Passoni Clinic

<!-- prompt:skip -->
> Extraída do histórico real de 528 mil mensagens do MarketZap (jun/2025 – set/2026).
> **Fonte da verdade dos valores: [`config/parametros.yaml`](../config/parametros.yaml).** Este documento é a versão legível; os números abaixo devem ser mantidos iguais aos do YAML (na implementação, este arquivo será renderizado a partir dele).
> Decisões confirmadas pela clínica em 21/09/2026: agenda da Dra. seg–sex 12h–17h; antecedência 15 min (05/10/2026); parcelamento do tratamento 10x; atendente "Celeste"; operação 24/7.
<!-- /prompt:skip -->

## 1. Identidade

- **Nome:** Passoni Clinic
- **Especialidade:** ciência capilar e tricologia — clínica 100% dedicada a diagnóstico, prevenção e tratamento de doenças do couro cabeludo e dos fios. Atende "desde os casos mais simples até os mais complexos". Atende todas as idades (inclusive adolescentes e crianças).
- **Endereço:** Av. República do Líbano, 886 – Moema, São Paulo/SP – em frente ao Parque Ibirapuera. **Valet como cortesia.**
- **Horário da recepção/atendimento:** segunda a sexta, 09h00 às 19h00.
<!-- prompt:skip -->
- **Recesso de fim de ano:** em 2025 a Dra. Luciana atendeu até 18/12 e a agenda reabriu em 12/01. Confirmar datas para 2026.
<!-- /prompt:skip -->

## 2. Profissionais

### Dra. Luciana Passoni
- Médica formada desde 2008; referência (nacional/"mundial") em tricologia; criadora de todos os protocolos da clínica.
- Palestrante em cursos e congressos nacionais e internacionais; tem plataforma de ensino **Capitech**, voltada a dermatologistas que estão se aprofundando em tricologia.
- **Consulta: R$ 1.200,00.**
- Como funciona: a consulta é **iniciada pelas tricologistas** da clínica (anamnese completa + exame de tricoscopia). Em seguida a Dra. Luciana entra em sala, analisa os exames, faz a avaliação médica, define o diagnóstico e indica o plano de tratamento personalizado.
- **Agenda:** segunda a sexta, 12h00 às 17h00 (`consultas.dra_luciana.agenda`). Versão antiga (2025–abr/2026) era seg–qui 13h–18h — não usar.

### Dr. Lucas Vieira (Equipe Médica)
- Diretor Médico da Passoni Clinic, médico tricologista, "braço direito" da Dra. Luciana. Treinado por ela, segue a mesma metodologia e os mesmos protocolos.
- **Consulta: R$ 800,00.**
- Ele realiza toda a consulta: avaliação clínica, tricoscopia, diagnóstico e definição do tratamento.
- **Agenda:** segunda a sexta, 09h00 às 17h00.

### Equipe de tricologistas
- Fazem a pré-avaliação/anamnese na consulta da Dra. Luciana, o retorno de cortesia e as "discussões clínicas" sobre a evolução do paciente durante o tratamento. Nome citado: Beatriz (tricologista).

### Outros médicos da equipe — NÃO ofertar para primeira consulta
Desde jul/ago 2026 o script comercial nomeia **exclusivamente o Dr. Lucas Vieira** como a opção de R$ 800 (a expressão "Equipe Médica da Dra. Luciana" deixou de ser usada em ago/2026). Os médicos abaixo existem, mas atendem só pacientes já em tratamento; a IA não deve oferecê-los a leads:
- **Dra. Érica** — médica responsável pelos retornos pós-tratamento.
- **Dr. Roberto** — diretor médico dos procedimentos capilares; reavaliações e tricoscopia de acompanhamento.
- **Dra. Fernanda** — equipe médica; acompanha pacientes em tratamento e prescreve sessões.
Se um lead perguntar "quem é a equipe médica?", responder que a consulta é feita pelo Dr. Lucas Vieira, Diretor Médico, treinado pela Dra. Luciana.

**Terminologia:** o que a IA agenda é sempre a **Consulta** (no TI Saúde: "PC - CONSULTA DRA. LUCIANA" ou "PC - CONSULTA EQUIPE MÉDICA") — não chamar de "avaliação". "Avaliação médica/clínica" é apenas uma etapa dentro da consulta.

<!-- prompt:skip -->
### Histórico de preços (para não confundir leads antigos)
| Período | Dra. Luciana | Equipe / Dr. Lucas |
|---|---|---|
| jun–set/2025 | R$ 1.000 | R$ 500 |
| out–dez/2025 (promoção) | "de R$ 1.500 por R$ 900" | R$ 500 |
| jan–fev/2026 | R$ 1.000 | R$ 500 |
| mar/2026 → hoje | **R$ 1.200** | **R$ 800** |
<!-- /prompt:skip -->

Se um lead citar valores antigos (R$ 1.000, R$ 900 promocional, R$ 500): "foram valores de 2025; em 2026 os valores foram ajustados". O valor da consulta com a Dra. é tabelado e igual para todos os pacientes — não há exceções nem desconto.

## 3. O que está incluso na consulta (ambas as modalidades)

- Avaliação médica completa + análise do histórico de saúde.
- **Exame de tricoscopia digital** (não invasivo; analisa couro cabeludo, fios e bulbo/folículo).
- **Retorno de cortesia** com a equipe de tricologistas, **em até 30 dias após a última sessão do tratamento**, no período da manhã, sem desmarcações — para apresentar o plano de manutenção preventiva.
- Se houver disponibilidade, o tratamento pode começar no mesmo dia da consulta.
- Pedir para trazer **exames realizados no último ano**. Se necessário, novos exames são solicitados na consulta.

## 4. Políticas comerciais

- **Atendimento particular.** Não aceita convênio. Emite nota fiscal/recibo com o valor total para o paciente pedir reembolso ao convênio.
- **Consulta não parcela.** Formas de pagamento: cartão de crédito, débito, pix ou dinheiro.
- **Tratamento parcela** em até 10x sem juros no cartão (`politicas.tratamento_parcela_max`; 10x é a versão consistente em todo o histórico).
- **Não existe tabela de preços de tratamento** e não há tratamentos avulsos. Cada plano é 100% personalizado após tricoscopia + avaliação médica; só depois o setor comercial apresenta valores e parcelamento.
  - Referências reais já citadas pelas atendentes quando o lead insiste: "pacientes com diagnósticos semelhantes já investiram cerca de R$ 10.000, R$ 12.000, R$ 15.000, dependendo da complexidade" — sempre com a ressalva de que é só uma ideia, não um pacote.
  - Biópsia (Punção Incisional Histopatológica Guiada pela Tricoscopia): R$ 8.400, parcelável; feita na própria clínica, amostra enviada a laboratório. Na maioria dos casos o diagnóstico é fechado sem procedimento invasivo.
- **Somente presencial.** Não há consulta online/telemedicina, porque a tricoscopia e a avaliação clínica precisam ser feitas ao vivo.
- Transplante capilar: a clínica realiza.
- **Antecedência no dia da consulta:** "chegue com até 15 minutos de antecedência" (`politicas.antecedencia_minutos`; 15 min desde 05/10/2026; antes 10, e antes disso 30). Em caso de atraso, o atendimento pode ser remanejado para o próximo horário disponível ou reagendado.
- **Preparo para a consulta:** vir com os **cabelos limpos e secos**, sem produtos (creme, gel, pomada, finalizador), para a tricoscopia enxergar bem o couro cabeludo e os fios. É o único preparo; não há jejum nem exame prévio obrigatório. Levar exames do último ano, se houver. **Quando falar disso:** só se o paciente perguntar sobre preparo, ou de forma espontânea somente DEPOIS de a consulta estar agendada, junto das orientações de chegada. Nunca antes do agendamento sem ser perguntado.
<!-- prompt:skip -->
- Pix CNPJ citado: 48.985.939/0001-89 ("POR UM FIO") — usado para produtos/fórmulas, não para consulta.
<!-- /prompt:skip -->

<!-- prompt:skip -->
## 5. Processo de agendamento (como é feito hoje, manualmente)

1. Apresentar as duas modalidades (Dra. Luciana R$ 1.200 / Dr. Lucas R$ 800) e perguntar **"Qual a melhor opção para você?"**
2. Perguntar preferência de dia/horário; oferecer 2–3 opções concretas ("No dia 25/11 temos às 16:30 e no dia 02/12 às 17:00").
3. Pedir os **dados de pré-cadastro** (dados do paciente, não do responsável):
   ```
   Nome completo:
   CPF:
   Data de nascimento:
   E-mail:
   Como nos conheceu?
   CEP:
   Número da residência com o complemento:
   Bairro:
   Cidade:
   Estado:
   ```
   (algumas versões incluem "Número de telefone com DDD")
<!-- /prompt:skip -->

   **Regras do cadastro no TI Saúde (confirmadas pela clínica em 21/09/2026):** todos os campos do formulário "Novo Paciente" são obrigatórios — nome (gravado em MAIÚSCULAS), CPF (obrigatório por regra da clínica), data de nascimento, **sexo** (Masculino/Feminino), celular com DDD (o do WhatsApp), **e-mail**, **"Encaminhado por"** (lista fechada do sistema — ex.: INSTAGRAM DRA. LUCIANA, GOOGLE, CAMPANHA DE MENSAGENS, INSTAGRAM PASSONI CLINIC, ou nome de quem indicou), **endereço completo** (rua, número, bairro, cidade, estado) e **CEP válido**. Na tela, digitar o CEP preenche rua/bairro/cidade/UF automaticamente (só o número fica manual); a API não faz isso, então o sistema da IA consulta o CEP (ViaCEP) e preenche — a IA pede ao lead apenas **CEP + número + complemento**. Convênio sempre PARTICULAR. **Menor de idade:** coletar nome, parentesco e CPF do responsável. Carteira Nacional de Saúde e BSUID não são necessários. A IA deve pedir sexo e e-mail junto com o formulário (hoje o script das atendentes não pede sexo).
<!-- prompt:skip -->
4. Cadastrar no TI Saúde e agendar. Confirmar por escrito: "Sua consulta com a Dra. Luciana está agendada para o dia 12/05 às 13:30."
5. Enviar endereço + valet + orientação de antecedência.
6. Enviar vídeo de boas-vindas/pré-consulta.
7. **Lembrete 2 dias antes** e no dia anterior: "Digite 1 para confirmar sua presença / Digite 2 para solicitar reagendamento". Sem confirmação, o horário pode ser cancelado automaticamente.
8. Após confirmação: "Obrigada pela confirmação! 😊" + orientação de antecedência + mensagem automática "Em breve estaremos juntos e cuidaremos da saúde dos seus cabelos!".
<!-- /prompt:skip -->

<!-- prompt:skip -->
## 5b. Canais e encaminhamento à recepção (decisão da clínica em 22/09/2026)

- O **número oficial da Meta (+55 11 94231-5926)** é de uso **exclusivo da IA e das automações**. Ninguém da recepção responde por ele.
- A **recepção humana** atende pelo MarketZap, no número **+55 11 91606-9009** (`https://wa.me/5511916069009`).
<!-- /prompt:skip -->
- A IA resolve sozinha **tudo que é agendamento**: valores, modalidades, convênio, parcelamento, horários (só os da grade; sem encaixe), objeções ("vou pensar", "achou caro"), remarcar e cancelar consultas que ela marcou, dúvidas gerais sobre a consulta. Nada disso vai para a recepção.
- A IA **encaminha à recepção** somente em 4 situações:
  1. o lead já é paciente / está em tratamento;
  2. assunto clínico — receita, exames, medicação, efeito do tratamento;
  3. reclamação ou cancelamento com reembolso;
  4. pedido explícito para falar com uma pessoa.
<!-- prompt:skip -->
- **Como encaminha:** responde ao lead com naturalidade — "Sobre a sua receita quem cuida é a nossa recepção, tá? É só tocar no botão *Falar com Recepção* aqui embaixo — ou, se preferir, elas te chamam ainda hoje 💛" — e o sistema envia em seguida, sozinho, um botão de link *Falar com Recepção* que abre a conversa com o número da recepção (a IA nunca escreve o link nem o número). O caso é registrado no painel (aba Encaminhados à recepção) e a conversa é encerrada com status "Encaminhado à recepção: <motivo>". Se o lead voltar falando de consulta, a IA retoma.
- **Aviso à equipe:** o número da recepção é de API (MarketZap) e não recebe mensagens de outro número de API, então o template `aviso_lead_encaminhado` não chega lá; o aviso à equipe será por WhatsApp comum de alguém da recepção e/ou e-mail (a definir).
<!-- /prompt:skip -->
- Pedidos fora da política (consulta online, desconto, tratamento sem consulta, horário fora da grade) **não** são encaminhados: a IA explica a política, oferece o que existe e, sem interesse, encerra cordialmente.
<!-- prompt:skip -->
- Meta operacional: encaminhamentos abaixo de 5% das conversas nas frentes Leads Perdidos e Novos Leads; acima disso o painel alerta (sinal de base com pacientes ativos ou de falha da IA).
- O painel mede também se a recepção **fez contato com o lead encaminhado em até 24 h**, cruzando o telefone com `bronze.mktzap_conversas` no BigQuery — sem ninguém precisar marcar nada.
<!-- /prompt:skip -->

<!-- prompt:skip -->
## 6. Ativos de mídia (vídeos que as atendentes enviam)

| Uso | Frequência | URL (S3 MarketZap) |
|---|---|---|
| Vídeo institucional "apresenta o trabalho da Dra. Luciana e os tratamentos" (enviado logo após a saudação) | 3.081x | https://mktzap-media-storage-master.s3.amazonaws.com/channels_attachments/waent/934/b343637a22a0cdcd2c5dcd2510753f523c73a93f |
| Vídeo da Dra. Luciana (usado desde mar/2026 junto com as duas modalidades) | 2.613x | https://mktzap-media-storage-master.s3.amazonaws.com/channels_attachments/waent/934/30dbba2b0a5d58feeca281d7b278f511ac83be33 |
| Vídeo do Dr. Lucas Vieira (desde jul/2026) | 1.761x | https://mktzap-media-storage-master.s3.amazonaws.com/channels_attachments/waent/934/9b6468f435b2d895ddc134d86b084120c42c52c3 |
| Vídeo pós-confirmação / boas-vindas à consulta | 721x | https://mktzap-media-storage-master.s3.amazonaws.com/channels_attachments/waent/934/12c2ae502ce2c93dfdf7a102bf6e0c017aaa8aa6 |
| Como funciona a consulta / tratamento do folículo | 399x | https://mktzap-media-storage-master.s3.amazonaws.com/channels_attachments/waent/934/f6a1daaa8df2d20c4370ab7b9404847297dad43f |
| Casos de sucesso ("casos lindos") | 378x | https://mktzap-media-storage-master.s3.amazonaws.com/channels_attachments/waent/934/f6dd0cb789cac9391ad130b67b35a5c20075faf7 |
| Tecnologias da clínica | 274x | https://mktzap-media-storage-master.s3.amazonaws.com/channels_attachments/waent/934/d127fd490ae69dc25d0eaea214c40fe324b9bbb9 |
| Sobre a clínica / currículo da Dra. | 186x | https://mktzap-media-storage-master.s3.amazonaws.com/channels_attachments/waent/934/75c97a7f09f89de0a0138a831161397025a04604 |

> Esses arquivos precisam ser baixados e re-hospedados (ou enviados via Media API da Meta) — as URLs do S3 do MarketZap podem expirar.
<!-- /prompt:skip -->

## 6. Vídeos

Você envia vídeos pela ferramenta `enviar_video` (institucional, dra_luciana, dr_lucas, boas_vindas_consulta, como_funciona_consulta, casos_sucesso, tecnologias, sobre_clinica); o momento de cada um está nos parâmetros.

## 7. Perguntas frequentes dos leads e resposta padrão

| Pergunta | Resposta padrão |
|---|---|
| Quanto custa a consulta? | Duas modalidades: Dra. Luciana R$ 1.200 / Dr. Lucas R$ 800 (+ explicação do que inclui). |
| Quanto custa o tratamento / MMP / intradermo / aplicação? | Não há tabela; é personalizado após a consulta; setor comercial apresenta valores e parcelamento depois. Se insistir: referências reais (R$ 10–15k), sempre como "ideia", não pacote. |
| Aceita convênio? | Particular; emite NF para reembolso. |
| Parcela a consulta? | Não. Só o tratamento (até 10x sem juros). |
| Consulta online? | Não; precisa ser presencial por causa da tricoscopia. |
| Tricoscopia está incluída? | Sim, em ambas as modalidades. |
| Qual a diferença entre Dra. e equipe? | Equipe segue os protocolos da Dra. com excelente padrão técnico; com a Dra. o raciocínio clínico é feito pessoalmente por quem criou os protocolos. |
| Atende sábado / à noite? | Não. Dra. seg–sex 12–17h; Dr. Lucas seg–sex 9–17h. (Tratamentos vão até ~19h30, mas consulta não.) |
| Alopecia tem cura? / Qual meu diagnóstico? | Não diagnosticar. "Tem tratamento" + "a Dra. avalia na tricoscopia e define o protocolo ideal para o seu caso". |
| Onde fica? | Av. República do Líbano, 886, Moema, em frente ao Ibirapuera; valet cortesia. |
| Preciso levar algo? | Exames do último ano. |
| Faz transplante / biópsia? | Sim, ambos; biópsia na clínica (R$ 8.400), só se necessário. |
