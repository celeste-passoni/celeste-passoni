-- vw_funil_templates (05/11/2026, pedido da clínica): eficiência da esteira da Celeste POR ETAPA (T1→T4) E POR VERSÃO DE TEMPLATE.
-- Grão: 1 linha por lead × envio de template, mais 1 linha por lead disponibilizado/aguardando uma etapa que ainda não recebeu.
-- No Power BI, toda métrica é CONTAGEM DISTINTA de `contato` com o filtro da coluna (ex.: chamado = TRUE). A coluna "Total"
-- é a mesma contagem sem filtrar etapa (lead distinto, não soma das etapas).
-- Regras iguais às do funil de resgate (frente 'Perdidos IA'): disponibilizados de automacoes.leads_disponibilizados_diario;
-- marcação/consulta/comparecimento de gold.atendimentos com marcadopor = Celeste Maria a partir de 28/10/2026 (sem 'PC - AVALIAÇÃO');
-- venda de silver.vendas tipo RESGATE com marcadopor = Celeste Maria; números de teste fora (ia_atendimento.numeros_teste + conversas de teste).
-- Atribuição: resposta vai para o template que o lead respondeu (contexto do WhatsApp) ou, sem contexto, ao último template
-- recebido antes dela; marcação (e o que vem dela: consulta, comparecimento, venda) vai para o último template recebido antes
-- da marcação. Cada lead marcado conta em UMA etapa só.
-- D-1 (06/11/2026, pedido da clínica): só entra o que aconteceu ATÉ ONTEM (envios, respostas, marcações, vendas, disponibilizações);
-- o espelho roda às 00:30 para a tabela da manhã ter o dia anterior completo. status_lead e status de entrega são os atuais.
-- status_lead (06/11/2026): o mesmo status do painel da Celeste (leads.status_ia; opt-out → 'Não quer (opt-out)'), com
-- 'Em conversa' dividido em 'Em conversa - Interagiu' quando o lead escreveu texto livre (não só clicou em botão).
-- Gerada pelo espelho noturno (celeste.jobs.espelho); a fonte é este arquivo no repositório.
WITH
etapas AS (
  SELECT * FROM UNNEST([
    STRUCT('T1' AS codigo, 1 AS ordem, CAST(NULL AS STRING) AS anterior, 0 AS prazo_dias),
    STRUCT('T2', 2, 'T1', 1), STRUCT('T3', 3, 'T2', 3), STRUCT('T4', 4, 'T3', 7)])
),
teste AS (
  SELECT contato FROM `vertical-theory-489419-a7.ia_atendimento.numeros_teste`
  UNION DISTINCT
  SELECT CAST(contato AS STRING) FROM `vertical-theory-489419-a7.ia_atendimento.conversas` WHERE teste
  UNION DISTINCT
  SELECT CAST(celular AS STRING) FROM `vertical-theory-489419-a7.ia_atendimento.leads` WHERE teste
),
disp AS (   -- base da Celeste no funil da clínica
  SELECT contato, MIN(data_disponibilizacao) AS data_disponibilizacao
  FROM `vertical-theory-489419-a7.automacoes.leads_disponibilizados_diario`
  WHERE frente = 'Perdidos IA' AND data_disponibilizacao < CURRENT_DATE('America/Sao_Paulo')   -- D-1
  GROUP BY contato
),
optout AS (
  SELECT CAST(celular AS STRING) AS contato FROM `vertical-theory-489419-a7.ia_atendimento.leads` WHERE opt_out
  UNION DISTINCT
  SELECT CAST(contato AS STRING) FROM `vertical-theory-489419-a7.ia_atendimento.conversas` WHERE opt_out AND (opt_out_em IS NULL OR opt_out_em < TIMESTAMP(CURRENT_DATE('America/Sao_Paulo'), 'America/Sao_Paulo'))
),
envios AS (
  SELECT
    CAST(l.celular AS STRING) AS contato,
    JSON_VALUE(x, '$.codigo') AS codigo,
    JSON_VALUE(x, '$.template') AS template,
    TIMESTAMP(JSON_VALUE(x, '$.em')) AS enviado_em,
    JSON_VALUE(x, '$.wamid') AS wamid,
    JSON_VALUE(x, '$.motivo') AS motivo_envio
  FROM `vertical-theory-489419-a7.ia_atendimento.leads` l, UNNEST(JSON_QUERY_ARRAY(l.templates_enviados)) x
  WHERE JSON_VALUE(x, '$.codigo') IS NOT NULL
    AND CAST(l.celular AS STRING) NOT IN (SELECT contato FROM teste)
    AND TIMESTAMP(JSON_VALUE(x, '$.em')) < TIMESTAMP(CURRENT_DATE('America/Sao_Paulo'), 'America/Sao_Paulo')   -- D-1
),
envios_ord AS (
  SELECT e.*,
    LEAD(e.enviado_em) OVER (PARTITION BY e.contato ORDER BY e.enviado_em) AS proximo_envio_em,
    ROW_NUMBER() OVER (PARTITION BY e.contato, e.codigo ORDER BY e.enviado_em) AS envio_na_etapa
  FROM envios e
),
msgs_lead AS (
  SELECT m._id AS msg_id, CAST(c.contato AS STRING) AS contato, m.recebido_em, m.botao, m.contexto_wamid, m.tipo
  FROM `vertical-theory-489419-a7.ia_atendimento.mensagens` m
  JOIN `vertical-theory-489419-a7.ia_atendimento.conversas` c ON c._id = m._pai_id
  WHERE m.direcao = 'lead' AND m.recebido_em IS NOT NULL AND m.recebido_em < TIMESTAMP(CURRENT_DATE('America/Sao_Paulo'), 'America/Sao_Paulo')   -- D-1
),
resp_janela AS (   -- sem contexto: último template recebido antes da mensagem
  SELECT ml.msg_id, e.wamid
  FROM msgs_lead ml
  JOIN envios_ord e ON e.contato = ml.contato AND ml.recebido_em >= e.enviado_em
  QUALIFY ROW_NUMBER() OVER (PARTITION BY ml.msg_id ORDER BY e.enviado_em DESC) = 1
),
resp AS (
  SELECT ml.msg_id, ml.recebido_em, ml.botao, COALESCE(ctx.wamid, rj.wamid) AS wamid
  FROM msgs_lead ml
  LEFT JOIN envios_ord ctx ON ctx.wamid = ml.contexto_wamid
  LEFT JOIN resp_janela rj ON rj.msg_id = ml.msg_id
),
primeira_resp AS (
  SELECT wamid,
    MIN(recebido_em) AS primeira_resposta_em,
    ARRAY_AGG(STRUCT(botao) ORDER BY recebido_em LIMIT 1)[OFFSET(0)].botao AS primeiro_botao,
    COUNT(*) AS mensagens_do_lead
  FROM resp WHERE wamid IS NOT NULL
  GROUP BY wamid
),
marc AS (
  SELECT
    CONCAT('55', REGEXP_REPLACE(CAST(a.celular_sem_ddd AS STRING), r'[^0-9]', '')) AS contato,
    COALESCE(a.marcacao_hora, TIMESTAMP(DATETIME(DATE(a.marcacao), TIME '23:59:59'), 'America/Sao_Paulo')) AS marcado_em,
    DATE(a.marcacao) AS data_marcacao, DATE(a.data) AS data_consulta, a.status
  FROM `vertical-theory-489419-a7.gold.atendimentos` a
  WHERE UPPER(a.marcadopor) = 'CELESTE MARIA'
    AND DATE(a.marcacao) >= DATE '2026-10-28'
    AND a.tipo_procedimento IS DISTINCT FROM 'PC - AVALIAÇÃO'
    AND DATE(a.marcacao) < CURRENT_DATE('America/Sao_Paulo')   -- D-1
),
marc_lead AS (
  SELECT contato,
    MIN(marcado_em) AS marcado_em,
    MIN(data_marcacao) AS data_marcacao,
    MAX(data_consulta) AS data_consulta,                         -- a mais recente (segue reagendamentos)
    LOGICAL_OR(status IN (2, 5)) AS compareceu,
    MAX(IF(status IN (2, 5), data_consulta, NULL)) AS data_comparecimento
  FROM marc
  WHERE contato NOT IN (SELECT contato FROM teste)
  GROUP BY contato
),
marc_atrib AS (
  SELECT ml.*, e.wamid
  FROM marc_lead ml
  JOIN envios_ord e ON e.contato = ml.contato AND e.enviado_em <= ml.marcado_em
  QUALIFY ROW_NUMBER() OVER (PARTITION BY ml.contato ORDER BY e.enviado_em DESC) = 1
),
vendas AS (
  SELECT CONCAT('55', REGEXP_REPLACE(CAST(v.celular AS STRING), r'[^0-9]', '')) AS contato,
    DATE(v.data_venda) AS data_venda, v.valor_total, v.macro_produto
  FROM `vertical-theory-489419-a7.silver.vendas` v
  WHERE v.tipo_consulta = 'RESGATE' AND UPPER(v.marcadopor) = 'CELESTE MARIA' AND DATE(v.data_venda) >= DATE '2026-10-28'
    AND DATE(v.data_venda) < CURRENT_DATE('America/Sao_Paulo')   -- D-1
),
venda_lead AS (
  SELECT ma.contato,
    LOGICAL_OR(v.macro_produto != 'CONSULTA') AS teve_venda,       -- mesma regra do funil: venda = algo além da consulta
    MIN(IF(v.macro_produto != 'CONSULTA', v.data_venda, NULL)) AS data_venda,
    SUM(v.valor_total) AS faturamento
  FROM marc_atrib ma
  JOIN vendas v ON v.contato = ma.contato AND v.data_venda >= ma.data_marcacao
  GROUP BY ma.contato
),
entrega AS (
  SELECT _id AS wamid, status AS status_entrega FROM `vertical-theory-489419-a7.ia_atendimento.status_entrega`
),
-- linhas de envio
linhas_envio AS (
  SELECT e.contato, e.codigo, e.template, e.enviado_em, e.wamid, e.motivo_envio, e.envio_na_etapa, TRUE AS chamado,
    pr.primeira_resposta_em, pr.primeiro_botao, pr.mensagens_do_lead, ent.status_entrega
  FROM envios_ord e
  LEFT JOIN primeira_resp pr ON pr.wamid = e.wamid
  LEFT JOIN entrega ent ON ent.wamid = e.wamid
),
-- leads da base que nunca receberam T1
t1_sem_envio AS (
  SELECT d.contato, 'T1' AS codigo
  FROM disp d
  WHERE d.contato NOT IN (SELECT contato FROM teste)
    AND d.contato NOT IN (SELECT contato FROM envios WHERE codigo = 'T1')
),
-- leads parados numa etapa da esteira, já no prazo da seguinte, que ainda não a receberam (disponibilizados para ela)
ultima_esteira AS (
  SELECT le.contato, le.codigo, le.enviado_em, le.primeira_resposta_em
  FROM linhas_envio le JOIN etapas et ON et.codigo = le.codigo
  QUALIFY ROW_NUMBER() OVER (PARTITION BY le.contato ORDER BY le.enviado_em DESC) = 1
),
aguardando AS (
  SELECT u.contato, prox.codigo
  FROM ultima_esteira u
  JOIN etapas prox ON prox.anterior = u.codigo
  WHERE u.primeira_resposta_em IS NULL
    AND u.contato NOT IN (SELECT contato FROM optout)
    AND u.contato NOT IN (SELECT contato FROM marc_lead)
    AND DATE_DIFF(DATE_SUB(CURRENT_DATE('America/Sao_Paulo'), INTERVAL 1 DAY), DATE(u.enviado_em, 'America/Sao_Paulo'), DAY) >= prox.prazo_dias   -- no fim de D-1
),
interagiu AS (   -- escreveu (texto, áudio, foto ou documento), não só clicou em botão
  SELECT DISTINCT contato FROM msgs_lead WHERE botao IS NULL AND tipo IN ('text', 'audio', 'image', 'document')
),
-- 06/11/2026 (clínica, só na tabela): lead em 'Irá nos retornar' ou 'Agora não' que voltou a mandar mensagem depois desse status
-- conta como em conversa. Momento do status: 'Agora não' → conversas.agora_nao_em; 'Irá nos retornar' → última chamada da Celeste
-- com atualizar_status (chamadas_ia). Sem o momento gravado, o status fica como está.
conv_atual AS (
  SELECT _id AS conversa_id, CAST(contato AS STRING) AS contato, agora_nao_em, status_em
  FROM `vertical-theory-489419-a7.ia_atendimento.conversas`
  WHERE NOT COALESCE(teste, FALSE)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY contato ORDER BY criado_em DESC) = 1
),
status_ia_celeste AS (
  SELECT ch.conversa_id, MAX(ch.em) AS em
  FROM `vertical-theory-489419-a7.ia_atendimento.chamadas_ia` ch, UNNEST(JSON_QUERY_ARRAY(ch.ferramentas)) f
  WHERE JSON_VALUE(f, '$.nome') = 'atualizar_status' AND ch.em < TIMESTAMP(CURRENT_DATE('America/Sao_Paulo'), 'America/Sao_Paulo')
  GROUP BY ch.conversa_id
),
ultima_msg_lead AS (
  SELECT contato, MAX(recebido_em) AS em FROM msgs_lead GROUP BY contato
),
status_lead AS (   -- status do painel (leads.status_ia), com 'Em conversa - Interagiu' para quem escreveu texto livre até D-1
  SELECT contato,
    CASE WHEN status_base = 'Em conversa' AND interagiu THEN 'Em conversa - Interagiu' ELSE status_base END AS status_lead
  FROM (
    SELECT CAST(l.celular AS STRING) AS contato, it.contato IS NOT NULL AS interagiu,
      CASE
        WHEN l.opt_out THEN 'Não quer (opt-out)'
        WHEN l.status_ia IN ('Irá nos retornar', 'Agora não')
         AND uml.em > COALESCE(IF(l.status_ia = 'Agora não', ca.agora_nao_em, sic.em), ca.status_em) THEN 'Em conversa'   -- voltou a escrever
        ELSE COALESCE(l.status_ia, 'Não contatado')
      END AS status_base
    FROM `vertical-theory-489419-a7.ia_atendimento.leads` l
    LEFT JOIN interagiu it ON it.contato = CAST(l.celular AS STRING)
    LEFT JOIN conv_atual ca ON ca.contato = CAST(l.celular AS STRING)
    LEFT JOIN status_ia_celeste sic ON sic.conversa_id = ca.conversa_id
    LEFT JOIN ultima_msg_lead uml ON uml.contato = CAST(l.celular AS STRING)
  )
),
em_uso AS (   -- versão em uso de cada etapa (para as linhas sem envio)
  SELECT codigo, template FROM `vertical-theory-489419-a7.ia_atendimento.templates_de_para` WHERE em_uso
),
linhas AS (
  SELECT * FROM linhas_envio
  UNION ALL
  SELECT contato, codigo, NULL, NULL, NULL, NULL, NULL, FALSE, NULL, NULL, NULL, NULL FROM t1_sem_envio
  UNION ALL
  SELECT contato, codigo, NULL, NULL, NULL, NULL, NULL, FALSE, NULL, NULL, NULL, NULL FROM aguardando
)
SELECT
  l.contato,
  COALESCE(sl.status_lead, 'Não contatado') AS status_lead,
  d.data_disponibilizacao,
  DATE_TRUNC(d.data_disponibilizacao, MONTH) AS mes_disponibilizacao,
  COALESCE(dp.etapa, l.codigo) AS etapa,
  COALESCE(dp.etapa_ordem, et.ordem) AS etapa_ordem,
  l.codigo AS codigo_fluxo,
  l.template,
  dp.versao,
  COALESCE(dp.rotulo_versao, IF(l.template IS NULL, NULL, CONCAT(l.codigo, ' · ', l.template, ' (fora do de-para)'))) AS rotulo_versao,
  dp.categoria,
  l.motivo_envio,
  l.envio_na_etapa,
  -- funil
  TRUE AS disponibilizado,
  l.chamado,
  l.enviado_em,
  DATE(l.enviado_em, 'America/Sao_Paulo') AS data_envio,
  DATE_TRUNC(DATE(l.enviado_em, 'America/Sao_Paulo'), MONTH) AS mes_envio,
  l.status_entrega,
  l.status_entrega IN ('delivered', 'read') AS entregue,
  l.status_entrega = 'read' AS lido,
  l.status_entrega = 'failed' AS falhou,
  l.primeira_resposta_em IS NOT NULL AS respondeu,
  l.primeira_resposta_em,
  ROUND(TIMESTAMP_DIFF(l.primeira_resposta_em, l.enviado_em, MINUTE) / 60, 1) AS horas_ate_resposta,
  l.primeiro_botao AS botao_clicado,
  CASE
    WHEN l.primeira_resposta_em IS NULL THEN NULL
    WHEN l.primeiro_botao IS NULL THEN 'Texto livre'
    WHEN STRPOS(CONCAT(' | ', dp.botoes_com_interesse, ' | '), CONCAT(' | ', l.primeiro_botao, ' | ')) > 0 THEN 'Com interesse (botão)'
    WHEN STRPOS(CONCAT(' | ', dp.botoes_sem_interesse, ' | '), CONCAT(' | ', l.primeiro_botao, ' | ')) > 0 THEN 'Sem interesse (botão)'
    ELSE 'Outro botão'
  END AS tipo_resposta,
  COALESCE(STRPOS(CONCAT(' | ', dp.botoes_com_interesse, ' | '), CONCAT(' | ', l.primeiro_botao, ' | ')) > 0, FALSE) AS com_interesse,
  COALESCE(STRPOS(CONCAT(' | ', dp.botoes_sem_interesse, ' | '), CONCAT(' | ', l.primeiro_botao, ' | ')) > 0, FALSE) AS sem_interesse,
  l.primeira_resposta_em IS NOT NULL AND l.primeiro_botao IS NULL AS texto_livre,
  l.mensagens_do_lead,
  -- resultado (só na etapa a que a marcação foi atribuída)
  ma.contato IS NOT NULL AS marcou,
  ma.data_marcacao,
  ma.data_consulta,
  ma.contato IS NOT NULL AND DATE_TRUNC(ma.data_consulta, MONTH) = DATE_TRUNC(ma.data_marcacao, MONTH) AS consulta_no_mes_da_marcacao,
  ma.contato IS NOT NULL AND ma.data_consulta < CURRENT_DATE('America/Sao_Paulo') AS consulta_decorrida,
  COALESCE(ma.compareceu, FALSE) AS compareceu,
  ma.data_comparecimento,
  COALESCE(vl.teve_venda, FALSE) AS teve_venda,
  vl.data_venda,
  COALESCE(vl.faturamento, 0) AS faturamento,
  DATE_SUB(CURRENT_DATE('America/Sao_Paulo'), INTERVAL 1 DAY) AS dados_ate,
  CURRENT_TIMESTAMP() AS calculado_em
FROM linhas l
LEFT JOIN disp d ON d.contato = l.contato
LEFT JOIN etapas et ON et.codigo = l.codigo
LEFT JOIN em_uso eu ON eu.codigo = l.codigo
LEFT JOIN `vertical-theory-489419-a7.ia_atendimento.templates_de_para` dp
  ON dp.codigo = l.codigo AND dp.template = COALESCE(l.template, eu.template)   -- sem envio: versão em uso
LEFT JOIN marc_atrib ma ON ma.wamid = l.wamid
LEFT JOIN venda_lead vl ON vl.contato = ma.contato
LEFT JOIN status_lead sl ON sl.contato = l.contato
