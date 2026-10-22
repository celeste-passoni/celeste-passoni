-- NOVO (22/10/2026): frente 'Perdidos IA' = Celeste (IA). Nome do usuário no TI Saúde e data do lançamento.
DECLARE NOME_CELESTE STRING DEFAULT 'Celeste';
DECLARE INICIO_CELESTE DATE DEFAULT DATE '2026-10-26';

-- ============================================================
-- PASSO 1: atualiza resgate_leads_diario com quem é elegível hoje.
-- ============================================================
MERGE `vertical-theory-489419-a7.automacoes.resgate_leads_diario` T
USING (
  WITH orcamento AS (
    SELECT
      CURRENT_DATE() AS data_execucao,
      'Orcamento' AS frente,
      CAST(t.data AS DATETIME) AS data,
      t.nome AS nome,
      CONCAT('55', REGEXP_REPLACE(CAST(t.celular_sem_ddd AS STRING), r'[^0-9]', '')) AS contato,
      CAST(t.cpf AS STRING) AS chave,
      t.tipo_agendamento_novo AS info_extra,
      s.status AS status,
      s.data_atualizacao AS data_atualizacao
    FROM `vertical-theory-489419-a7.gold.atendimentos` t
    LEFT JOIN `vertical-theory-489419-a7.gold.sistemaweb_orcamento` s
      ON COALESCE(t.nome, '') = COALESCE(s.nome, '') AND COALESCE(CAST(t.celular_sem_ddd AS STRING), '') = COALESCE(s.contato, '')
    WHERE t.tipo_agendamento_novo IN ('Consulta', 'Retorno')
      AND t.status IN (2, 5)
      AND t.flag_procedimento_lista IS DISTINCT FROM 'Procedimento Vendido'
      AND (
        (t.tipo_agendamento_novo = 'Consulta' AND DATE(t.data) >= DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH))
        OR
        (t.tipo_agendamento_novo = 'Retorno' AND DATE(t.data) >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 MONTH))
      )
      AND DATE(t.data) < CURRENT_DATE()
      AND t.flag_ultimos_3_dias_uteis = false   -- ALTERADO (10/10/2026): era flag_ultimos_2_dias_uteis
      AND t.restricao = 'NADA CONSTA'
      AND t.guias_abertas IS NULL
      AND t.tipo_procedimento IS DISTINCT FROM 'PC - CORTESIA'
      AND t.cortesia != 'sim'
      AND t.considerar_retorno_lista = 'Sim'
      AND t.agendamento_futuro = 'Nao'
      AND (t.nome IS NULL OR UPPER(TRIM(t.nome)) != 'KEVIN WILLIAN BARBOSA MENDES')
      AND (s.status IS NULL OR s.status != 'Não quer')
    QUALIFY ROW_NUMBER() OVER (PARTITION BY t.cpf ORDER BY t.data DESC) = 1
  ),

  -- DESATIVADO (07/10/2026): a frente Inativos não recebe mais atualizações nem novos leads.
  -- O histórico já gravado em resgate_leads_diario / leads_disponibilizados_diario fica intacto.
  -- inativos AS (
  --   SELECT
  --     CURRENT_DATE() AS data_execucao,
  --     'Inativos' AS frente,
  --     CAST(t.data_inativacao AS DATETIME) AS data,
  --     t.nome_paciente AS nome,
  --     CONCAT('55', REGEXP_REPLACE(CAST(t.celular AS STRING), r'[^0-9]', '')) AS contato,
  --     CAST(t.cpf AS STRING) AS chave,
  --     CAST(t.faturamento_total AS STRING) AS info_extra,
  --     s.status AS status,
  --     s.data_atualizacao AS data_atualizacao
  --   FROM `vertical-theory-489419-a7.gold.pacientes` t
  --   LEFT JOIN `vertical-theory-489419-a7.gold.sistemaweb_inativos` s
  --     ON COALESCE(t.nome_paciente, '') = COALESCE(s.nome, '') AND COALESCE(CAST(t.celular AS STRING), '') = COALESCE(s.contato, '')
  --   WHERE LOWER(CAST(t.status_atividade AS STRING)) = 'inativo'
  --     AND (LOWER(CAST(t.guias_abertas AS STRING)) != 'sim' OR t.guias_abertas IS NULL)
  --     AND t.dias_desde_ultimo_atendimento <= 420
  --     AND DATE(t.data_inativacao) >= '2026-10-02'   -- ALTERADO (02/10/2026)
  --     AND t.faturamento_total > 10000
  --     AND (t.restricao IS NULL OR TRIM(UPPER(CAST(t.restricao AS STRING))) != 'IMPEDIDO DE OPERAR')
  --     AND t.agendamento_futuro = 'Nao'
  --     AND (t.nome_paciente IS NULL OR UPPER(TRIM(t.nome_paciente)) != 'KEVIN WILLIAN BARBOSA MENDES')
  --     AND (s.status IS NULL OR s.status != 'Não quer')
  --   QUALIFY ROW_NUMBER() OVER (PARTITION BY t.cpf ORDER BY t.data_inativacao DESC) = 1
  -- ),

  canceladas AS (
    SELECT
      CURRENT_DATE() AS data_execucao,
      'Canceladas' AS frente,
      CAST(t.data AS DATETIME) AS data,
      t.nome AS nome,
      CONCAT('55', REGEXP_REPLACE(CAST(t.celular_sem_ddd AS STRING), r'[^0-9]', '')) AS contato,
      CAST(t.cpf AS STRING) AS chave,
      t.tipo_agendamento AS info_extra,
      s.status AS status,
      s.data_atualizacao AS data_atualizacao
    FROM `vertical-theory-489419-a7.gold.atendimentos` t
    LEFT JOIN `vertical-theory-489419-a7.gold.sistemaweb_canceladas` s
      ON COALESCE(t.nome, '') = COALESCE(s.nome, '') AND COALESCE(CAST(t.celular_sem_ddd AS STRING), '') = COALESCE(s.contato, '')
    WHERE t.tipo_agendamento = 'Consulta'
      AND LOWER(CAST(t.status_agendamento AS STRING)) = 'cancelado'
      AND DATE(t.data) >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 MONTH)   -- ALTERADO (02/10/2026): janela móvel de 4 meses
      AND DATE(t.data) < CURRENT_DATE()
      AND t.flag_ultimos_2_dias_uteis = false
      AND t.restricao = 'NADA CONSTA'
      AND t.guias_abertas IS NULL
      AND t.tipo_procedimento IS DISTINCT FROM 'PC - CORTESIA'
      AND t.cortesia != 'sim'
      AND t.considerar_retorno_lista = 'Sim'
      AND t.agendamento_futuro = 'Nao'
      AND (t.nome IS NULL OR UPPER(TRIM(t.nome)) != 'KEVIN WILLIAN BARBOSA MENDES')
      AND (s.status IS NULL OR s.status != 'Não quer')
    QUALIFY ROW_NUMBER() OVER (PARTITION BY t.cpf ORDER BY t.data DESC) = 1
  ),

  perdidos AS (
    SELECT
      CURRENT_DATE() AS data_execucao,
      'Perdidos' AS frente,
      CAST(t.created_at AS DATETIME) AS data,
      t.nome AS nome,
      CONCAT('55', REGEXP_REPLACE(CAST(t.celular_sem_ddd AS STRING), r'[^0-9]', '')) AS contato,
      CONCAT('55', REGEXP_REPLACE(CAST(t.celular_sem_ddd AS STRING), r'[^0-9]', '')) AS chave,
      t.primeira_origem AS info_extra,
      s.status AS status,
      s.data_atualizacao AS data_atualizacao
    FROM `vertical-theory-489419-a7.gold.leads` t
    LEFT JOIN `vertical-theory-489419-a7.gold.sistemaweb_perdidos` s
      ON COALESCE(t.nome, '') = COALESCE(s.nome, '') AND COALESCE(CAST(t.celular_sem_ddd AS STRING), '') = COALESCE(s.contato, '')
    WHERE LOWER(CAST(t.agendou AS STRING)) IN ('não', 'nao')
      AND DATE(t.created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 MONTH)   -- ALTERADO (02/10/2026): janela móvel de 3 meses
      AND DATE(t.created_at) < CURRENT_DATE()
      AND LOWER(CAST(t.dentro_2_dias_uteis AS STRING)) IN ('não', 'nao')
      AND LOWER(CAST(t.participou_acao_lead_perdidos AS STRING)) = 'não'
      AND (s.status IS NULL OR s.status != 'Não quer')
    QUALIFY ROW_NUMBER() OVER (PARTITION BY t.celular_sem_ddd ORDER BY t.created_at DESC) = 1
  ),

  -- NOVO (22/10/2026): frente da Celeste (IA): leads criados entre 4 e 3 meses atrás, mesmos filtros de Perdidos.
  -- Status e 'Não quer' vêm do espelho da Celeste (opt-out), não do sistemaweb. Conversas de teste ficam fora.
  perdidos_ia AS (
    SELECT
      CURRENT_DATE() AS data_execucao,
      'Perdidos IA' AS frente,
      CAST(t.created_at AS DATETIME) AS data,
      t.nome AS nome,
      CONCAT('55', REGEXP_REPLACE(CAST(t.celular_sem_ddd AS STRING), r'[^0-9]', '')) AS contato,
      CONCAT('55', REGEXP_REPLACE(CAST(t.celular_sem_ddd AS STRING), r'[^0-9]', '')) AS chave,
      t.primeira_origem AS info_extra,
      CASE WHEN c.opt_out THEN 'Não quer' ELSE c.status END AS status,
      DATETIME(COALESCE(c.opt_out_em, c.agendado_em, c.ultima_msg_celeste_em)) AS data_atualizacao
    FROM `vertical-theory-489419-a7.gold.leads` t
    LEFT JOIN (
      SELECT CAST(contato AS STRING) AS contato, status, opt_out, opt_out_em, agendado_em, ultima_msg_celeste_em
      FROM `vertical-theory-489419-a7.ia_atendimento.conversas`
      WHERE (teste IS NULL OR teste = FALSE)
      QUALIFY ROW_NUMBER() OVER (PARTITION BY contato ORDER BY criado_em DESC) = 1
    ) c
      ON c.contato = CONCAT('55', REGEXP_REPLACE(CAST(t.celular_sem_ddd AS STRING), r'[^0-9]', ''))
    WHERE LOWER(CAST(t.agendou AS STRING)) IN ('não', 'nao')
      AND DATE(t.created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 MONTH)
      AND DATE(t.created_at) <  DATE_SUB(CURRENT_DATE(), INTERVAL 3 MONTH)
      AND LOWER(CAST(t.dentro_2_dias_uteis AS STRING)) IN ('não', 'nao')
      AND LOWER(CAST(t.participou_acao_lead_perdidos AS STRING)) = 'não'
      AND (c.opt_out IS NULL OR c.opt_out = FALSE)
    QUALIFY ROW_NUMBER() OVER (PARTITION BY t.celular_sem_ddd ORDER BY t.created_at DESC) = 1
  )

  SELECT * FROM orcamento
  -- UNION ALL SELECT * FROM inativos   -- DESATIVADO (07/10/2026)
  UNION ALL SELECT * FROM canceladas
  UNION ALL SELECT * FROM perdidos
  UNION ALL SELECT * FROM perdidos_ia   -- NOVO (22/10/2026)
) S
ON T.frente = S.frente
  AND T.chave = S.chave
  AND T.data_execucao = S.data_execucao
WHEN MATCHED THEN
  UPDATE SET
    nome = S.nome,
    contato = S.contato,
    data = S.data,
    info_extra = S.info_extra,
    status = S.status,
    data_atualizacao = S.data_atualizacao
WHEN NOT MATCHED THEN
  INSERT (data_execucao, frente, data, nome, contato, chave, info_extra, status, data_atualizacao)
  VALUES (S.data_execucao, S.frente, S.data, S.nome, S.contato, S.chave, S.info_extra, S.status, S.data_atualizacao);


-- ============================================================
-- Recria gold.mensagens_resgate AGORA (depois do Passo 1), pra já
-- enxergar resgate_leads_diario atualizado com os leads de hoje.
-- Precisa existir antes dos Passos 3 e 8, que dependem dela.
-- ============================================================
CREATE OR REPLACE TABLE gold.mensagens_resgate AS
WITH base AS (
  SELECT
    a.id AS mensagem_id,
    a.history_id,
    a.user_id,
    CASE
      WHEN a.user_id = 91826 THEN 'Raiane Santana Souza Santos'
      WHEN a.user_id = 97804 THEN 'Maria Fernanda Oliveira Martins'
      WHEN a.user_id = 85574 THEN 'Gisela Madeira Pinto'   -- NOVO (18/09/2026)
    END AS colaborador,
    a.sent_by_operator,
    a.sent_by_auto,
    a.received_at,
    a.message,
    a.created_at,
    a.sector_id,
    b.protocol,
    b.contact_id,
    b.messages_count,
    b.closed_by_user_id,
    REGEXP_EXTRACT(b.contact_id, r'(55\d+)$') AS celular,
    f.frente AS frente_original,
    CASE
      WHEN EXTRACT(DAYOFWEEK FROM DATE(a.created_at)) NOT IN (1, 7)
        AND DATE(a.created_at) NOT IN (SELECT DATE(fer.data) FROM `vertical-theory-489419-a7.silver.feriados` fer)
      THEN 'Sim'
      ELSE 'Não'
    END AS dia_util,
    CASE
      WHEN DATE(a.created_at) >= CURRENT_DATE() THEN 'Sim'
      ELSE 'Não'
    END AS data_futura
  FROM `bronze.mktzap_mensagens` AS a
  LEFT JOIN bronze.mktzap_conversas AS b
    ON a.history_id = b.id
  LEFT JOIN (
    SELECT DISTINCT contato, frente, DATE_TRUNC(data_execucao, MONTH) AS mes
    FROM `vertical-theory-489419-a7.automacoes.resgate_leads_diario`
  ) AS f
    ON f.contato = REGEXP_EXTRACT(b.contact_id, r'(55\d+)$')
    AND f.mes = DATE_TRUNC(DATE(a.created_at), MONTH)
  WHERE a.sent_by_operator = 1
    AND a.user_id IN (97804, 91826, 85574)   -- NOVO: 85574 = Gisela Madeira Pinto
    AND a.created_at >= '2026-01-01'
    -- ALTERADO (10/10/2026): a Gisela sai do resgate; mensagens dela só até 09/10.
    AND NOT (a.user_id = 85574 AND DATE(a.created_at) >= DATE '2026-10-10')
),

  celeste AS (   -- NOVO (22/10/2026): mensagens da Celeste (IA), vindas do espelho Firestore→BigQuery
    SELECT
      FARM_FINGERPRINT(m._id)      AS mensagem_id,
      FARM_FINGERPRINT(m._pai_id)  AS history_id,
      0.0                          AS user_id,
      'Celeste'                    AS colaborador,
      1                            AS sent_by_operator,
      0                            AS sent_by_auto,
      FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E3SZ', m.recebido_em) AS received_at,   -- mesmo formato (STRING, UTC) do MarketZap
      CAST(NULL AS STRING)         AS message,
      FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E3SZ', m.recebido_em) AS created_at,
      CAST(NULL AS INT64)          AS sector_id,
      CAST(NULL AS STRING)         AS protocol,
      CAST(c.contato AS STRING)    AS contact_id,
      CAST(NULL AS INT64)          AS messages_count,
      CAST(NULL AS FLOAT64)        AS closed_by_user_id,
      CAST(c.contato AS STRING)    AS celular,
      'Perdidos IA'                AS frente_original,
      CASE
        WHEN EXTRACT(DAYOFWEEK FROM DATE(m.recebido_em)) NOT IN (1, 7)
          AND DATE(m.recebido_em) NOT IN (SELECT DATE(fer.data) FROM `vertical-theory-489419-a7.silver.feriados` fer)
        THEN 'Sim' ELSE 'Não'
      END AS dia_util,
      CASE WHEN DATE(m.recebido_em) >= CURRENT_DATE() THEN 'Sim' ELSE 'Não' END AS data_futura
    FROM `vertical-theory-489419-a7.ia_atendimento.mensagens` m
    JOIN `vertical-theory-489419-a7.ia_atendimento.conversas` c ON c._id = m._pai_id
    WHERE m.direcao IN ('celeste', 'template')
      AND (c.teste IS NULL OR c.teste = FALSE)
      AND DATE(m.recebido_em) >= INICIO_CELESTE
  ),

base_mais_celeste AS (   -- NOVO (22/10/2026)
  SELECT * FROM base
  UNION ALL
  SELECT * FROM celeste
),

com_frente AS (
  SELECT
    mensagem_id,
    history_id,
    user_id,
    colaborador,
    sent_by_operator,
    sent_by_auto,
    received_at,
    message,
    created_at,
    sector_id,
    protocol,
    contact_id,
    messages_count,
    closed_by_user_id,
    celular,
    CASE
      -- NOVO (18/09/2026): a Gisela só trabalha Orcamento; tudo dela vira Orcamento
      WHEN colaborador = 'Gisela Madeira Pinto' THEN 'Orcamento'
      WHEN frente_original = 'Inativos' THEN 'Inativo'
      WHEN DATE(created_at) >= '2026-09-01' AND frente_original IS NULL THEN 'Perdidos'
      WHEN DATE(created_at) < '2026-09-01' AND frente_original IS NULL AND colaborador = 'Raiane Santana Souza Santos' THEN 'Perdidos'
      ELSE frente_original
    END AS frente,
    dia_util,
    data_futura
  FROM base_mais_celeste   -- ALTERADO (22/10/2026): inclui a Celeste
),

final AS (
  SELECT *
  FROM com_frente
  WHERE NOT (
    colaborador = 'Maria Fernanda Oliveira Martins'
    AND (
      (DATE(created_at) < '2026-09-01' AND frente IN ('Orcamento', 'Perdidos'))
      OR
      -- ALTERADO (10/10/2026): Orcamento passa para a Maria Fernanda; o descarte
      -- das mensagens dela em Orcamento só vale de 01/09 a 09/10.
      (DATE(created_at) >= '2026-09-01' AND DATE(created_at) < '2026-10-10' AND frente = 'Orcamento')
    )
  )
)

SELECT * FROM final
UNION ALL
SELECT
  mensagem_id,
  history_id,
  user_id,
  'Total' AS colaborador,
  sent_by_operator,
  sent_by_auto,
  received_at,
  message,
  created_at,
  sector_id,
  protocol,
  contact_id,
  messages_count,
  closed_by_user_id,
  celular,
  frente,
  dia_util,
  data_futura
FROM final;
-- ============================================================
-- PASSO ATRIBUICAO: define atribuicao (Raiane/Maria Fernanda) por celular,
-- usando a última mensagem enviada a partir de 24/08/2026; fallback por
-- paridade do último dígito. Só para frente = 'Perdidos', e só a partir
-- de 2026-09-01.
-- ============================================================
MERGE `vertical-theory-489419-a7.automacoes.resgate_leads_diario` T
USING (
  WITH ultima_mensagem AS (
    SELECT
      celular,
      colaborador,
      ROW_NUMBER() OVER (PARTITION BY celular ORDER BY created_at DESC) AS rn
    FROM `vertical-theory-489419-a7.gold.mensagens_resgate`
    -- NOVO (18/09/2026): a divisão de Perdidos é só entre Raiane e Maria Fernanda.
    -- A Gisela entrou em mensagens_resgate, mas não pode virar atribuicao de Perdidos.
    WHERE colaborador IN (
      'Raiane Santana Souza Santos',
      'Maria Fernanda Oliveira Martins'
    )
    AND DATE(created_at) >= '2026-08-24'
    AND DATE(created_at) < '2026-08-31'
  )
  SELECT
    r.data_execucao,
    r.frente,
    r.chave,
    -- NOVO (18/09/2026): a Raiane saiu da empresa; todo lead perdido passa a ser
    -- da Maria Fernanda. A divisão por última mensagem / paridade só vale até 17/09.
    CASE
      WHEN r.data_execucao >= DATE '2026-09-18' THEN 'Maria Fernanda Oliveira Martins'
      ELSE COALESCE(
        um.colaborador,
        CASE
          WHEN MOD(CAST(RIGHT(r.contato, 1) AS INT64), 2) = 0 THEN 'Raiane Santana Souza Santos'
          ELSE 'Maria Fernanda Oliveira Martins'
        END
      )
    END AS atribuicao
  FROM `vertical-theory-489419-a7.automacoes.resgate_leads_diario` r
  LEFT JOIN ultima_mensagem um
    ON um.celular = r.contato AND um.rn = 1
  WHERE r.data_execucao >= '2026-09-01'
    AND r.frente = 'Perdidos'
) S
ON T.frente = S.frente AND T.chave = S.chave AND T.data_execucao = S.data_execucao
WHEN MATCHED THEN
  UPDATE SET atribuicao = S.atribuicao;

-- ============================================================
-- PASSO COLABORADOR: define colaborador — prioriza atribuicao
-- (Leads Perdidos); senão, aplica a regra padrão por frente.
-- ============================================================
UPDATE `vertical-theory-489419-a7.automacoes.resgate_leads_diario`
SET colaborador =
  CASE
    -- NOVO (22/10/2026): a frente da IA é sempre da Celeste
    WHEN frente = 'Perdidos IA' THEN 'Celeste'
    -- ALTERADO (10/10/2026): Orcamento passa para a Maria Fernanda; a Gisela sai.
    -- A partir de 10/10 todas as frentes são da Maria Fernanda.
    WHEN data_execucao >= DATE '2026-10-10' THEN 'Maria Fernanda Oliveira Martins'
    -- NOVO (18/09/2026): Orcamento passa para a Gisela; todo o resto (Perdidos,
    -- Inativos e Canceladas) fica com a Maria Fernanda. A Raiane saiu da empresa.
    WHEN data_execucao >= DATE '2026-09-18' THEN
      CASE
        WHEN frente = 'Orcamento' THEN 'Gisela Madeira Pinto'
        ELSE 'Maria Fernanda Oliveira Martins'
      END
    ELSE COALESCE(
      atribuicao,
      CASE
        WHEN frente IN ('Inativos', 'Canceladas') THEN 'Maria Fernanda Oliveira Martins'
        ELSE 'Raiane Santana Souza Santos'
      END
    )
  END
WHERE TRUE;


-- ============================================================
-- PASSO 2: insere em leads_disponibilizados_diario quem é novo hoje
-- (não estava na execução anterior mais recente).
-- ============================================================
MERGE `vertical-theory-489419-a7.automacoes.leads_disponibilizados_diario` T
USING (
  WITH ultima_execucao_anterior AS (
    SELECT MAX(data_execucao) AS data_anterior
    FROM `vertical-theory-489419-a7.automacoes.resgate_leads_diario`
    WHERE data_execucao < CURRENT_DATE()
  ),

  hoje AS (
    SELECT DISTINCT chave, frente, contato, nome
    FROM `vertical-theory-489419-a7.automacoes.resgate_leads_diario`
    WHERE data_execucao = CURRENT_DATE()
      AND chave IS NOT NULL
  ),

  presentes_execucao_anterior AS (
    SELECT DISTINCT r.chave, r.frente
    FROM `vertical-theory-489419-a7.automacoes.resgate_leads_diario` r
    CROSS JOIN ultima_execucao_anterior u
    WHERE r.data_execucao = u.data_anterior
  )

  SELECT
    h.chave,
    h.frente,
    h.contato,
    h.nome,
    CURRENT_DATE() AS data_disponibilizacao,
    DATE_TRUNC(CURRENT_DATE(), MONTH) AS mes_ref
  FROM hoje h
  LEFT JOIN presentes_execucao_anterior p
    ON h.chave = p.chave AND h.frente = p.frente
  CROSS JOIN ultima_execucao_anterior u
  WHERE p.chave IS NULL
    AND u.data_anterior IS NOT NULL
) S
ON T.chave = S.chave
  AND T.frente = S.frente
  AND T.data_disponibilizacao = S.data_disponibilizacao
WHEN NOT MATCHED THEN
  INSERT (chave, frente, contato, nome, data_disponibilizacao, mes_ref)
  VALUES (S.chave, S.frente, S.contato, S.nome, S.data_disponibilizacao, S.mes_ref);


-- ============================================================
-- PASSO 3: recalcula mensagem_no_mes só para o mês corrente.
-- ============================================================
UPDATE `vertical-theory-489419-a7.automacoes.leads_disponibilizados_diario` T
SET
  mensagem_no_mes = CASE
    WHEN EXISTS (
      SELECT 1
      FROM `vertical-theory-489419-a7.gold.mensagens_resgate` m
      WHERE m.celular = T.contato
        AND DATE_TRUNC(DATE(m.created_at), MONTH) = T.mes_ref
    ) THEN 'Sim'
    ELSE 'Não'
  END,
  data_mensagem_no_mes = (
    SELECT MAX(DATE(m.created_at))
    FROM `vertical-theory-489419-a7.gold.mensagens_resgate` m
    WHERE m.celular = T.contato
      AND DATE_TRUNC(DATE(m.created_at), MONTH) = T.mes_ref
  )
WHERE T.mes_ref = DATE_TRUNC(CURRENT_DATE(), MONTH);


-- ============================================================
-- PASSO 4: recalcula marcado_no_mes, data_marcado_no_mes e atendimento_agendado_no_mes
-- só para o mês corrente.
-- ============================================================
UPDATE `vertical-theory-489419-a7.automacoes.leads_disponibilizados_diario` T
SET
  marcado_no_mes = CASE
    WHEN EXISTS (
      SELECT 1
      FROM `vertical-theory-489419-a7.gold.atendimentos` a
      WHERE (
        (T.frente IN ('Perdidos', 'Perdidos IA') AND a.celular_sem_ddd = SUBSTR(T.contato, 3))
        OR
        (T.frente NOT IN ('Perdidos', 'Perdidos IA') AND CAST(a.cpf AS STRING) = T.chave)
      )
      AND (
        UPPER(a.marcadopor) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
        OR UPPER(a.marcadopor) LIKE '%RAIANE SANTANA SOUZA SANTOS%'
        OR UPPER(a.marcadopor) = UPPER(NOME_CELESTE)   -- NOVO (22/10/2026)
      )
      AND DATE_TRUNC(DATE(a.marcacao), MONTH) = T.mes_ref
      AND DATE(a.marcacao) >= DATE('2026-08-18')
    ) THEN 'Sim'
    ELSE 'Não'
  END,
  data_marcado_no_mes = (
    SELECT MAX(DATE(a.marcacao))
    FROM `vertical-theory-489419-a7.gold.atendimentos` a
    WHERE (
      (T.frente IN ('Perdidos', 'Perdidos IA') AND a.celular_sem_ddd = SUBSTR(T.contato, 3))
      OR
      (T.frente NOT IN ('Perdidos', 'Perdidos IA') AND CAST(a.cpf AS STRING) = T.chave)
    )
    AND (
      UPPER(a.marcadopor) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
      OR UPPER(a.marcadopor) LIKE '%RAIANE SANTANA SOUZA SANTOS%'
        OR UPPER(a.marcadopor) = UPPER(NOME_CELESTE)   -- NOVO (22/10/2026)
    )
    AND DATE_TRUNC(DATE(a.marcacao), MONTH) = T.mes_ref
    AND DATE(a.marcacao) >= DATE('2026-08-18')
  ),
  atendimento_agendado_no_mes = (
    SELECT CASE WHEN COUNT(*) > 0 THEN 'Sim' ELSE 'Não' END
    FROM `vertical-theory-489419-a7.gold.atendimentos` a
    WHERE (
      (T.frente IN ('Perdidos', 'Perdidos IA') AND a.celular_sem_ddd = SUBSTR(T.contato, 3))
      OR
      (T.frente NOT IN ('Perdidos', 'Perdidos IA') AND CAST(a.cpf AS STRING) = T.chave)
    )
    AND (
      UPPER(a.marcadopor) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
      OR UPPER(a.marcadopor) LIKE '%RAIANE SANTANA SOUZA SANTOS%'
        OR UPPER(a.marcadopor) = UPPER(NOME_CELESTE)   -- NOVO (22/10/2026)
    )
    AND DATE_TRUNC(DATE(a.data), MONTH) = T.mes_ref
    AND DATE(a.data) >= DATE('2026-08-18')
  ),
  data_atendimento_agendado_no_mes = (
    SELECT MAX(DATE(a.data))
    FROM `vertical-theory-489419-a7.gold.atendimentos` a
    WHERE (
      (T.frente IN ('Perdidos', 'Perdidos IA') AND a.celular_sem_ddd = SUBSTR(T.contato, 3))
      OR
      (T.frente NOT IN ('Perdidos', 'Perdidos IA') AND CAST(a.cpf AS STRING) = T.chave)
    )
    AND (
      UPPER(a.marcadopor) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
      OR UPPER(a.marcadopor) LIKE '%RAIANE SANTANA SOUZA SANTOS%'
        OR UPPER(a.marcadopor) = UPPER(NOME_CELESTE)   -- NOVO (22/10/2026)
    )
    AND DATE_TRUNC(DATE(a.data), MONTH) = T.mes_ref
    AND DATE(a.data) >= DATE('2026-08-18')
  )
WHERE T.mes_ref = DATE_TRUNC(CURRENT_DATE(), MONTH);


-- ============================================================
-- PASSO 5: recalcula compra_no_mes, valor_total_no_mes e fechou_mais_que_consulta
-- só para o mês corrente (vendas em silver.vendas, marcadas por Maria Fernanda ou Raiane).
-- ============================================================
UPDATE `vertical-theory-489419-a7.automacoes.leads_disponibilizados_diario` T
SET
  compra_no_mes = (
    SELECT CASE WHEN COUNT(*) > 0 THEN 'Sim' ELSE 'Não' END
    FROM `vertical-theory-489419-a7.silver.vendas` v
    WHERE (
      (T.frente IN ('Perdidos', 'Perdidos IA') AND REGEXP_REPLACE(CAST(v.celular AS STRING), r'[^0-9]', '') = SUBSTR(T.contato, 3))
      OR
      (T.frente NOT IN ('Perdidos', 'Perdidos IA') AND CAST(v.cpf AS STRING) = T.chave)
    )
    AND DATE_TRUNC(DATE(v.data_venda), MONTH) = T.mes_ref
    AND DATE(v.data_venda) >= DATE('2026-08-18')
    AND (
      UPPER(v.marcadopor) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
      OR UPPER(v.marcadopor) LIKE '%RAIANE SANTANA SOUZA SANTOS%'
      OR UPPER(v.marcadopor) = UPPER(NOME_CELESTE)   -- NOVO (22/10/2026)
      -- NOVO (18/09/2026): da Gisela só entra venda classificada como RESGATE
      -- ALTERADO (10/10/2026): vendas da Gisela só até 09/10
      OR (UPPER(v.marcadopor) LIKE '%GISELA MADEIRA PINTO%' AND v.tipo_consulta = 'RESGATE' AND DATE(v.data_venda) < DATE '2026-10-10')
    )
  ),
  valor_total_no_mes = (
    SELECT COALESCE(SUM(v.valor_total), 0)
    FROM `vertical-theory-489419-a7.silver.vendas` v
    WHERE (
      (T.frente IN ('Perdidos', 'Perdidos IA') AND REGEXP_REPLACE(CAST(v.celular AS STRING), r'[^0-9]', '') = SUBSTR(T.contato, 3))
      OR
      (T.frente NOT IN ('Perdidos', 'Perdidos IA') AND CAST(v.cpf AS STRING) = T.chave)
    )
    AND DATE_TRUNC(DATE(v.data_venda), MONTH) = T.mes_ref
    AND DATE(v.data_venda) >= DATE('2026-08-18')
    AND (
      UPPER(v.marcadopor) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
      OR UPPER(v.marcadopor) LIKE '%RAIANE SANTANA SOUZA SANTOS%'
      OR UPPER(v.marcadopor) = UPPER(NOME_CELESTE)   -- NOVO (22/10/2026)
      -- NOVO (18/09/2026): da Gisela só entra venda classificada como RESGATE
      -- ALTERADO (10/10/2026): vendas da Gisela só até 09/10
      OR (UPPER(v.marcadopor) LIKE '%GISELA MADEIRA PINTO%' AND v.tipo_consulta = 'RESGATE' AND DATE(v.data_venda) < DATE '2026-10-10')
    )
  ),
  fechou_mais_que_consulta = (
    SELECT CASE WHEN COUNTIF(v.macro_produto != 'CONSULTA') > 0 THEN 'Sim' ELSE 'Não' END
    FROM `vertical-theory-489419-a7.silver.vendas` v
    WHERE (
      (T.frente IN ('Perdidos', 'Perdidos IA') AND REGEXP_REPLACE(CAST(v.celular AS STRING), r'[^0-9]', '') = SUBSTR(T.contato, 3))
      OR
      (T.frente NOT IN ('Perdidos', 'Perdidos IA') AND CAST(v.cpf AS STRING) = T.chave)
    )
    AND DATE_TRUNC(DATE(v.data_venda), MONTH) = T.mes_ref
    AND DATE(v.data_venda) >= DATE('2026-08-18')
    AND (
      UPPER(v.marcadopor) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
      OR UPPER(v.marcadopor) LIKE '%RAIANE SANTANA SOUZA SANTOS%'
      OR UPPER(v.marcadopor) = UPPER(NOME_CELESTE)   -- NOVO (22/10/2026)
      -- NOVO (18/09/2026): da Gisela só entra venda classificada como RESGATE
      -- ALTERADO (10/10/2026): vendas da Gisela só até 09/10
      OR (UPPER(v.marcadopor) LIKE '%GISELA MADEIRA PINTO%' AND v.tipo_consulta = 'RESGATE' AND DATE(v.data_venda) < DATE '2026-10-10')
    )
  ),
  data_compra_no_mes = (
    SELECT MAX(DATE(v.data_venda))
    FROM `vertical-theory-489419-a7.silver.vendas` v
    WHERE (
      (T.frente IN ('Perdidos', 'Perdidos IA') AND REGEXP_REPLACE(CAST(v.celular AS STRING), r'[^0-9]', '') = SUBSTR(T.contato, 3))
      OR
      (T.frente NOT IN ('Perdidos', 'Perdidos IA') AND CAST(v.cpf AS STRING) = T.chave)
    )
    AND DATE_TRUNC(DATE(v.data_venda), MONTH) = T.mes_ref
    AND DATE(v.data_venda) >= DATE('2026-08-18')
    AND (
      UPPER(v.marcadopor) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
      OR UPPER(v.marcadopor) LIKE '%RAIANE SANTANA SOUZA SANTOS%'
      OR UPPER(v.marcadopor) = UPPER(NOME_CELESTE)   -- NOVO (22/10/2026)
      -- NOVO (18/09/2026): da Gisela só entra venda classificada como RESGATE
      -- ALTERADO (10/10/2026): vendas da Gisela só até 09/10
      OR (UPPER(v.marcadopor) LIKE '%GISELA MADEIRA PINTO%' AND v.tipo_consulta = 'RESGATE' AND DATE(v.data_venda) < DATE '2026-10-10')
    )
  )
WHERE T.mes_ref = DATE_TRUNC(CURRENT_DATE(), MONTH);


-- ============================================================
-- PASSO 6: recalcula compareceu_no_mes, venda_na_data_comparecimento e
-- venda_antecipada_comparecimento só para o mês corrente.
-- ============================================================
UPDATE `vertical-theory-489419-a7.automacoes.leads_disponibilizados_diario` T
SET
  compareceu_no_mes = (
    SELECT CASE WHEN COUNT(*) > 0 THEN 'Sim' ELSE 'Não' END
    FROM `vertical-theory-489419-a7.gold.atendimentos` a
    WHERE (
      (T.frente IN ('Perdidos', 'Perdidos IA') AND a.celular_sem_ddd = SUBSTR(T.contato, 3))
      OR
      (T.frente NOT IN ('Perdidos', 'Perdidos IA') AND CAST(a.cpf AS STRING) = T.chave)
    )
    AND a.status IN (2, 5)
    AND (
      UPPER(a.marcadopor) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
      OR UPPER(a.marcadopor) LIKE '%RAIANE SANTANA SOUZA SANTOS%'
        OR UPPER(a.marcadopor) = UPPER(NOME_CELESTE)   -- NOVO (22/10/2026)
    )
    AND DATE_TRUNC(DATE(a.data), MONTH) = T.mes_ref
    AND DATE(a.data) >= DATE('2026-08-18')
  ),
  data_compareceu_no_mes = (
    SELECT MAX(DATE(a.data))
    FROM `vertical-theory-489419-a7.gold.atendimentos` a
    WHERE (
      (T.frente IN ('Perdidos', 'Perdidos IA') AND a.celular_sem_ddd = SUBSTR(T.contato, 3))
      OR
      (T.frente NOT IN ('Perdidos', 'Perdidos IA') AND CAST(a.cpf AS STRING) = T.chave)
    )
    AND a.status IN (2, 5)
    AND (
      UPPER(a.marcadopor) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
      OR UPPER(a.marcadopor) LIKE '%RAIANE SANTANA SOUZA SANTOS%'
        OR UPPER(a.marcadopor) = UPPER(NOME_CELESTE)   -- NOVO (22/10/2026)
    )
    AND DATE_TRUNC(DATE(a.data), MONTH) = T.mes_ref
    AND DATE(a.data) >= DATE('2026-08-18')
  ),
  venda_na_data_comparecimento = CASE
    WHEN T.compra_no_mes = 'Sim'
      AND T.fechou_mais_que_consulta = 'Sim'
      AND (
        SELECT MAX(DATE(a.data))
        FROM `vertical-theory-489419-a7.gold.atendimentos` a
        WHERE (
          (T.frente IN ('Perdidos', 'Perdidos IA') AND a.celular_sem_ddd = SUBSTR(T.contato, 3))
          OR
          (T.frente NOT IN ('Perdidos', 'Perdidos IA') AND CAST(a.cpf AS STRING) = T.chave)
        )
        AND a.status IN (2, 5)
        AND (
          UPPER(a.marcadopor) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
          OR UPPER(a.marcadopor) LIKE '%RAIANE SANTANA SOUZA SANTOS%'
        OR UPPER(a.marcadopor) = UPPER(NOME_CELESTE)   -- NOVO (22/10/2026)
        )
        AND DATE_TRUNC(DATE(a.data), MONTH) = T.mes_ref
        AND DATE(a.data) >= DATE('2026-08-18')
      ) = T.data_compra_no_mes
    THEN 'Sim'
    ELSE 'Não'
  END,
  venda_antecipada_comparecimento = CASE
    WHEN T.compra_no_mes = 'Sim'
      AND T.fechou_mais_que_consulta = 'Sim'
      AND T.data_compra_no_mes < (
        SELECT MAX(DATE(a.data))
        FROM `vertical-theory-489419-a7.gold.atendimentos` a
        WHERE (
          (T.frente IN ('Perdidos', 'Perdidos IA') AND a.celular_sem_ddd = SUBSTR(T.contato, 3))
          OR
          (T.frente NOT IN ('Perdidos', 'Perdidos IA') AND CAST(a.cpf AS STRING) = T.chave)
        )
        AND a.status IN (2, 5)
        AND (
          UPPER(a.marcadopor) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
          OR UPPER(a.marcadopor) LIKE '%RAIANE SANTANA SOUZA SANTOS%'
        OR UPPER(a.marcadopor) = UPPER(NOME_CELESTE)   -- NOVO (22/10/2026)
        )
        AND DATE_TRUNC(DATE(a.data), MONTH) = T.mes_ref
        AND DATE(a.data) >= DATE('2026-08-18')
      )
    THEN 'Sim'
    ELSE 'Não'
  END
WHERE T.mes_ref = DATE_TRUNC(CURRENT_DATE(), MONTH);

-- ============================================================
-- PASSO 7: sincroniza status e data_atualizacao com o registro mais recente do lead
-- em resgate_leads_diario, só para o mês corrente.
-- ============================================================
MERGE `vertical-theory-489419-a7.automacoes.leads_disponibilizados_diario` T
USING (
  SELECT chave, frente, status, data_atualizacao
  FROM `vertical-theory-489419-a7.automacoes.resgate_leads_diario`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY chave, frente ORDER BY data_execucao DESC) = 1
) S
ON T.chave = S.chave AND T.frente = S.frente
WHEN MATCHED AND T.mes_ref = DATE_TRUNC(CURRENT_DATE(), MONTH) THEN
  UPDATE SET
    status = S.status,
    data_atualizacao = S.data_atualizacao;


-- ============================================================
-- PASSO 8: calcula operador — marcadopor se já agendou, senão
-- quem mandou a última mensagem pra esse contato.
-- ============================================================
MERGE `vertical-theory-489419-a7.automacoes.leads_disponibilizados_diario` T
USING (
  WITH base AS (
    SELECT chave, frente, contato
    FROM `vertical-theory-489419-a7.automacoes.leads_disponibilizados_diario`
    WHERE mes_ref = DATE_TRUNC(CURRENT_DATE(), MONTH)
    QUALIFY ROW_NUMBER() OVER (PARTITION BY chave, frente ORDER BY data_disponibilizacao DESC) = 1
  ),

  agendamento AS (
    SELECT
      base.chave,
      base.frente,
      a.marcadopor AS operador_agendamento
    FROM base
    JOIN `vertical-theory-489419-a7.gold.atendimentos` a
      ON (base.frente IN ('Perdidos', 'Perdidos IA') AND a.celular_sem_ddd = SUBSTR(base.contato, 3))
      OR (base.frente NOT IN ('Perdidos', 'Perdidos IA') AND CAST(a.cpf AS STRING) = base.chave)
    WHERE (
        UPPER(a.marcadopor) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
        OR UPPER(a.marcadopor) LIKE '%RAIANE SANTANA SOUZA SANTOS%'
        OR UPPER(a.marcadopor) = UPPER(NOME_CELESTE)   -- NOVO (22/10/2026)
      )
    QUALIFY ROW_NUMBER() OVER (PARTITION BY base.chave, base.frente ORDER BY a.marcacao DESC) = 1
  ),

  mensagem AS (
    SELECT
      base.chave,
      base.frente,
      m.colaborador AS operador_mensagem   -- ALTERADO (22/10/2026): inclui 'Celeste' (user_id 0)
    FROM base
    JOIN `vertical-theory-489419-a7.gold.mensagens_resgate` m
      ON m.celular = base.contato
    -- ALTERADO (10/10/2026): mensagens da Gisela só valem como operador até 09/10
    -- (mensagens_resgate já não traz Gisela a partir de 10/10; filtro mantido por segurança).
    WHERE NOT (m.user_id = 85574 AND base.frente != 'Orcamento')
      AND NOT (m.user_id = 85574 AND DATE(m.created_at) >= DATE '2026-10-10')
    QUALIFY ROW_NUMBER() OVER (PARTITION BY base.chave, base.frente ORDER BY m.created_at DESC) = 1
  )

  SELECT
    base.chave,
    base.frente,
    COALESCE(agendamento.operador_agendamento, mensagem.operador_mensagem) AS operador
  FROM base
  LEFT JOIN agendamento ON base.chave = agendamento.chave AND base.frente = agendamento.frente
  LEFT JOIN mensagem ON base.chave = mensagem.chave AND base.frente = mensagem.frente
) S
ON T.chave = S.chave AND T.frente = S.frente
WHEN MATCHED THEN
  UPDATE SET operador = S.operador;


-- ============================================================
-- gold.resgate_metricas_diarias (recriada por último)
-- Grão: data x colaborador x frente
-- ============================================================
-- ALTERADO (16/10/2026): a Gisela volta a aparecer nesta tabela SOMENTE com
-- vendas (vendas / valor_total_vendas), a partir de 10/10/2026 (fecha o
-- buraco). Mensagens, leads conversados, marcações, agendamentos e
-- comparecimentos dela continuam fora. Frente sempre 'Orcamento'.
-- ============================================================
CREATE OR REPLACE TABLE gold.resgate_metricas_diarias AS
WITH mensagens_resgate AS (
  SELECT
    a.id AS mensagem_id,
    CASE
      WHEN a.user_id = 91826 THEN 'Raiane Santana Souza Santos'
      WHEN a.user_id = 97804 THEN 'Maria Fernanda Oliveira Martins'
      WHEN a.user_id = 85574 THEN 'Gisela Madeira Pinto'
    END AS colaborador,
    a.created_at,
    REGEXP_EXTRACT(b.contact_id, r'(55\d+)$') AS celular
  FROM `bronze.mktzap_mensagens` AS a
  LEFT JOIN bronze.mktzap_conversas AS b ON a.history_id = b.id
  WHERE a.sent_by_operator = 1 AND a.user_id IN (97804, 91826, 85574)
    -- ALTERADO (10/10/2026): mensagens da Gisela só até 09/10
    AND NOT (a.user_id = 85574 AND DATE(a.created_at) >= DATE '2026-10-10')
  UNION ALL   -- NOVO (22/10/2026): mensagens da Celeste (espelho do Firestore)
  SELECT
    FARM_FINGERPRINT(m._id) AS mensagem_id,
    'Celeste' AS colaborador,
    FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E3SZ', m.recebido_em) AS created_at,   -- STRING, como no MarketZap
    CAST(c.contato AS STRING) AS celular
  FROM `vertical-theory-489419-a7.ia_atendimento.mensagens` m
  JOIN `vertical-theory-489419-a7.ia_atendimento.conversas` c ON c._id = m._pai_id
  WHERE m.direcao IN ('celeste', 'template')
    AND (c.teste IS NULL OR c.teste = FALSE)
    AND DATE(m.recebido_em) >= INICIO_CELESTE
),

base AS (
  SELECT colaborador, celular, mensagem_id, DATE(created_at) AS data
  FROM mensagens_resgate WHERE celular IS NOT NULL
),

primeiro_contato AS (
  SELECT celular, MIN(data) AS data_primeiro_contato FROM base GROUP BY celular
),

leads_frente_diario AS (
  SELECT DISTINCT contato AS celular, chave, frente, data_execucao
  FROM `vertical-theory-489419-a7.automacoes.resgate_leads_diario`
),

frente_chave_mes AS (
  SELECT DATE_TRUNC(data_execucao, MONTH) AS mes, chave, frente
  FROM leads_frente_diario
  WHERE chave IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY DATE_TRUNC(data_execucao, MONTH), chave
    ORDER BY data_execucao DESC,
      CASE frente WHEN 'Inativos' THEN 1 WHEN 'Canceladas' THEN 2
                  WHEN 'Orcamento' THEN 3 WHEN 'Perdidos IA' THEN 4 ELSE 5 END   -- ALTERADO (22/10/2026)
  ) = 1
),

frente_contato_mes AS (
  SELECT DATE_TRUNC(data_execucao, MONTH) AS mes, celular AS contato, frente
  FROM leads_frente_diario
  WHERE celular IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY DATE_TRUNC(data_execucao, MONTH), celular
    ORDER BY data_execucao DESC,
      CASE frente WHEN 'Inativos' THEN 1 WHEN 'Canceladas' THEN 2
                  WHEN 'Orcamento' THEN 3 WHEN 'Perdidos IA' THEN 4 ELSE 5 END   -- ALTERADO (22/10/2026)
  ) = 1
),

base_dia_raw AS (
  SELECT b.data, b.colaborador, b.celular, b.mensagem_id, p.data_primeiro_contato,
    COALESCE(fc.frente, 'Perdidos') AS frente
  FROM base AS b
  JOIN primeiro_contato AS p ON b.celular = p.celular
  LEFT JOIN frente_contato_mes AS fc
    ON b.celular = fc.contato
    AND DATE_TRUNC(b.data, MONTH) = fc.mes
),

base_dia AS (
  SELECT * EXCEPT(frente),
    CASE
      WHEN colaborador = 'Celeste' THEN 'Perdidos IA'   -- NOVO (22/10/2026)
      WHEN colaborador = 'Gisela Madeira Pinto' THEN 'Orcamento'
      WHEN colaborador = 'Maria Fernanda Oliveira Martins'
       AND data <= DATE '2026-08-31'
       AND frente NOT IN ('Canceladas', 'Inativos') THEN 'Inativos'
      -- ALTERADO (10/10/2026): Orcamento -> Perdidos da Maria Fernanda só de 01/09 a 09/10
      WHEN colaborador = 'Maria Fernanda Oliveira Martins'
       AND data >= DATE '2026-09-01'
       AND data <  DATE '2026-10-10'
       AND frente = 'Orcamento' THEN 'Perdidos'
      ELSE frente
    END AS frente
  FROM base_dia_raw
),

base_mes AS (
  SELECT celular, colaborador, frente, DATE_TRUNC(data, MONTH) AS mes
  FROM base_dia WHERE data < CURRENT_DATE()
),

atend_raw AS (
  SELECT a.data, a.marcacao, a.cpf, a.status, a.marcadopor,
    COALESCE(fkm.frente, fcm.frente, IF(a.marcadopor = NOME_CELESTE, 'Perdidos IA', 'Perdidos')) AS frente_marcacao,   -- ALTERADO (22/10/2026)
    COALESCE(fkd.frente, fcd.frente, IF(a.marcadopor = NOME_CELESTE, 'Perdidos IA', 'Perdidos')) AS frente_data
  FROM gold.atendimentos AS a
  LEFT JOIN frente_chave_mes AS fkm
    ON CAST(a.cpf AS STRING) = fkm.chave
    AND DATE_TRUNC(DATE(a.marcacao), MONTH) = fkm.mes
  LEFT JOIN frente_contato_mes AS fcm
    ON CONCAT('55', REGEXP_REPLACE(CAST(a.celular_sem_ddd AS STRING), r'[^0-9]', '')) = fcm.contato
    AND DATE_TRUNC(DATE(a.marcacao), MONTH) = fcm.mes
  LEFT JOIN frente_chave_mes AS fkd
    ON CAST(a.cpf AS STRING) = fkd.chave
    AND DATE_TRUNC(DATE(a.data), MONTH) = fkd.mes
  LEFT JOIN frente_contato_mes AS fcd
    ON CONCAT('55', REGEXP_REPLACE(CAST(a.celular_sem_ddd AS STRING), r'[^0-9]', '')) = fcd.contato
    AND DATE_TRUNC(DATE(a.data), MONTH) = fcd.mes
  WHERE a.marcadopor IN ('Raiane Santana Souza Santos', 'Maria Fernanda Oliveira Martins', NOME_CELESTE)   -- ALTERADO (22/10/2026)
    AND a.tipo_procedimento != 'PC - AVALIAÇÃO'
),

atend AS (
  SELECT * EXCEPT(frente_marcacao, frente_data),
    CASE
      WHEN marcadopor = NOME_CELESTE THEN 'Perdidos IA'   -- NOVO (22/10/2026)
      WHEN marcadopor = 'Maria Fernanda Oliveira Martins'
       AND DATE(marcacao) <= DATE '2026-08-31'
       AND frente_marcacao NOT IN ('Canceladas', 'Inativos') THEN 'Inativos'
      -- ALTERADO (10/10/2026): Orcamento -> Perdidos da Maria Fernanda só de 01/09 a 09/10
      WHEN marcadopor = 'Maria Fernanda Oliveira Martins'
       AND DATE(marcacao) >= DATE '2026-09-01'
       AND DATE(marcacao) <  DATE '2026-10-10'
       AND frente_marcacao = 'Orcamento' THEN 'Perdidos'
      ELSE frente_marcacao
    END AS frente_marcacao,
    CASE
      WHEN marcadopor = NOME_CELESTE THEN 'Perdidos IA'   -- NOVO (22/10/2026)
      WHEN marcadopor = 'Maria Fernanda Oliveira Martins'
       AND DATE(data) <= DATE '2026-08-31'
       AND frente_data NOT IN ('Canceladas', 'Inativos') THEN 'Inativos'
      -- ALTERADO (10/10/2026): Orcamento -> Perdidos da Maria Fernanda só de 01/09 a 09/10
      WHEN marcadopor = 'Maria Fernanda Oliveira Martins'
       AND DATE(data) >= DATE '2026-09-01'
       AND DATE(data) <  DATE '2026-10-10'
       AND frente_data = 'Orcamento' THEN 'Perdidos'
      ELSE frente_data
    END AS frente_data
  FROM atend_raw
),

vend_raw AS (
  SELECT DATE(v.data_venda) AS data, v.cpf, v.macro_produto, v.valor_total,
    -- ALTERADO (16/10/2026): a partir de 16/10, venda RESGATE em que o nome_usuario
    -- (quem emitiu a receita) é a Maria Fernanda conta para ela, mesmo que o
    -- marcadopor seja outra pessoa (mesma regra de tipo_consulta na silver.vendas).
    CASE
      WHEN DATE(v.data_venda) >= DATE '2026-10-16'
       AND UPPER(v.nome_usuario) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
      THEN 'Maria Fernanda Oliveira Martins'
      ELSE v.marcadopor
    END AS marcadopor,
    COALESCE(fk.frente, fc.frente, IF(v.marcadopor = NOME_CELESTE, 'Perdidos IA', 'Perdidos')) AS frente   -- ALTERADO (22/10/2026)
  FROM silver.vendas AS v
  LEFT JOIN frente_chave_mes AS fk
    ON CAST(v.cpf AS STRING) = fk.chave
    AND DATE_TRUNC(DATE(v.data_venda), MONTH) = fk.mes
  LEFT JOIN frente_contato_mes AS fc
    ON CONCAT('55', REGEXP_REPLACE(CAST(v.celular AS STRING), r'[^0-9]', '')) = fc.contato
    AND DATE_TRUNC(DATE(v.data_venda), MONTH) = fc.mes
  WHERE v.tipo_consulta = 'RESGATE'
    AND (
      v.marcadopor IN (
        'Raiane Santana Souza Santos',
        'Maria Fernanda Oliveira Martins',
        'Gisela Madeira Pinto',
        NOME_CELESTE   -- NOVO (22/10/2026)
      )
      -- ALTERADO (16/10/2026): entra também pelo nome_usuario da Maria Fernanda
      OR (
        DATE(v.data_venda) >= DATE '2026-10-16'
        AND UPPER(v.nome_usuario) LIKE '%MARIA FERNANDA OLIVEIRA MARTINS%'
      )
    )
    -- ALTERADO (16/10/2026): removido o corte das vendas da Gisela a partir de 10/10;
    -- as vendas RESGATE dela voltam a contar (só vendas, sem o resto do funil).
),

vend AS (
  SELECT * EXCEPT(frente),
    CASE
      WHEN marcadopor = NOME_CELESTE THEN 'Perdidos IA'   -- NOVO (22/10/2026)
      WHEN marcadopor = 'Gisela Madeira Pinto' THEN 'Orcamento'
      WHEN marcadopor = 'Maria Fernanda Oliveira Martins'
       AND data <= DATE '2026-08-31'
       AND frente NOT IN ('Canceladas', 'Inativos') THEN 'Inativos'
      -- ALTERADO (10/10/2026): Orcamento -> Perdidos da Maria Fernanda só de 01/09 a 09/10
      WHEN marcadopor = 'Maria Fernanda Oliveira Martins'
       AND data >= DATE '2026-09-01'
       AND data <  DATE '2026-10-10'
       AND frente = 'Orcamento' THEN 'Perdidos'
      ELSE frente
    END AS frente
  FROM vend_raw
),

fatos AS (
  SELECT data, colaborador, frente,
    COUNT(DISTINCT celular) AS leads_distintos_conversados,
    COUNT(DISTINCT mensagem_id) AS total_mensagens_enviadas,
    COUNT(DISTINCT CASE WHEN data = data_primeiro_contato THEN celular END)
      AS novos_leads_distintos_chamados,
    0 AS marcacoes, 0 AS agendamentos, 0 AS agendamento_decorrido,
    0 AS comparecimentos, 0 AS vendas, 0 AS valor_total_vendas
  FROM base_dia GROUP BY data, colaborador, frente
  UNION ALL
  SELECT data, 'Total', frente,
    COUNT(DISTINCT celular), COUNT(DISTINCT mensagem_id),
    COUNT(DISTINCT CASE WHEN data = data_primeiro_contato THEN celular END),
    0, 0, 0, 0, 0, 0
  FROM base_dia GROUP BY data, frente

  UNION ALL
  SELECT DATE(marcacao), marcadopor, frente_marcacao,
    0, 0, 0, COUNT(DISTINCT cpf), 0, 0, 0, 0, 0
  FROM atend GROUP BY 1, 2, 3
  UNION ALL
  SELECT DATE(marcacao), 'Total', frente_marcacao,
    0, 0, 0, COUNT(DISTINCT cpf), 0, 0, 0, 0, 0
  FROM atend GROUP BY 1, 3

  UNION ALL
  SELECT data, marcadopor, frente_data, 0, 0, 0, 0,
    COUNT(DISTINCT cpf),
    COUNT(DISTINCT CASE WHEN data < CURRENT_DATE() THEN cpf END),
    COUNT(DISTINCT CASE WHEN status = 2 THEN cpf END), 0, 0
  FROM atend GROUP BY 1, 2, 3
  UNION ALL
  SELECT data, 'Total', frente_data, 0, 0, 0, 0,
    COUNT(DISTINCT cpf),
    COUNT(DISTINCT CASE WHEN data < CURRENT_DATE() THEN cpf END),
    COUNT(DISTINCT CASE WHEN status = 2 THEN cpf END), 0, 0
  FROM atend GROUP BY 1, 3

  UNION ALL
  SELECT data, marcadopor, frente, 0, 0, 0, 0, 0, 0, 0,
    COUNT(DISTINCT CASE WHEN macro_produto != 'CONSULTA' THEN cpf END),
    SUM(valor_total)
  FROM vend GROUP BY 1, 2, 3
  UNION ALL
  SELECT data, 'Total', frente, 0, 0, 0, 0, 0, 0, 0,
    COUNT(DISTINCT CASE WHEN macro_produto != 'CONSULTA' THEN cpf END),
    SUM(valor_total)
  FROM vend GROUP BY 1, 3

  UNION ALL
  SELECT dt, colab, fr, 0, 0, 0, 0, 0, 0, 0, 0, 0
  FROM UNNEST(GENERATE_DATE_ARRAY(DATE '2026-01-01', LAST_DAY(CURRENT_DATE(), MONTH))) AS dt
  CROSS JOIN UNNEST(['Raiane Santana Souza Santos',
                     'Maria Fernanda Oliveira Martins',
                     'Gisela Madeira Pinto', 'Celeste', 'Total']) AS colab   -- ALTERADO (22/10/2026): Celeste
  CROSS JOIN UNNEST(['Orcamento', 'Inativos', 'Canceladas', 'Perdidos', 'Perdidos IA']) AS fr   -- ALTERADO (22/10/2026)
  -- NOVO (22/10/2026): a Celeste só existe em 'Perdidos IA' e a partir do lançamento; as humanas não têm 'Perdidos IA'
  WHERE NOT (colab = 'Celeste' AND (fr != 'Perdidos IA' OR dt < INICIO_CELESTE))
    AND NOT (colab NOT IN ('Celeste', 'Total') AND fr = 'Perdidos IA')
    AND NOT (colab = 'Raiane Santana Souza Santos' AND dt >= DATE '2026-09-18')
    AND NOT (colab = 'Gisela Madeira Pinto' AND dt <  DATE '2026-09-18')
    -- ALTERADO (16/10/2026): removido o corte da Gisela a partir de 10/10 — o esqueleto
    -- de datas dela (frente Orcamento) continua, para receber as vendas.
    AND NOT (colab = 'Gisela Madeira Pinto' AND fr != 'Orcamento')
),

unificado AS (
  SELECT data, colaborador, frente,
    SUM(leads_distintos_conversados) AS leads_distintos_conversados,
    SUM(total_mensagens_enviadas) AS total_mensagens_enviadas,
    SUM(novos_leads_distintos_chamados) AS novos_leads_distintos_chamados,
    SUM(marcacoes) AS marcacoes,
    SUM(agendamentos) AS agendamentos,
    SUM(agendamento_decorrido) AS agendamento_decorrido,
    SUM(comparecimentos) AS comparecimentos,
    SUM(vendas) AS vendas,
    SUM(valor_total_vendas) AS valor_total_vendas
  FROM fatos GROUP BY data, colaborador, frente
),

metricas_mensais AS (
  SELECT mes, colaborador, frente,
    COUNT(DISTINCT celular) AS leads_distintos_conversados_mes
  FROM base_mes GROUP BY mes, colaborador, frente
  UNION ALL
  SELECT mes, 'Total', frente, COUNT(DISTINCT celular)
  FROM base_mes GROUP BY mes, frente
),

calendario_uteis AS (
  SELECT dt AS data_cal,
    CASE WHEN EXTRACT(DAYOFWEEK FROM dt) NOT IN (1, 7)
      AND dt NOT IN (SELECT DATE(f.data) FROM `vertical-theory-489419-a7.silver.feriados` f)
    THEN 1 ELSE 0 END AS dia_util
  FROM UNNEST(GENERATE_DATE_ARRAY(DATE '2026-01-01', LAST_DAY(CURRENT_DATE(), MONTH))) AS dt
),

dias_uteis_acumulado AS (
  SELECT data_cal, dia_util,
    COALESCE(SUM(CASE WHEN data_cal < CURRENT_DATE() THEN dia_util ELSE 0 END) OVER (
      PARTITION BY DATE_TRUNC(data_cal, MONTH) ORDER BY data_cal
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS dias_uteis_ate_data
  FROM calendario_uteis
)

SELECT
  u.* EXCEPT(data),
  u.data,
  COALESCE(mm.leads_distintos_conversados_mes, 0) AS leads_distintos_conversados_mes,
  COALESCE(d.dias_uteis_ate_data, 0) AS dias_uteis_ate_data,
  CASE WHEN d.dia_util = 1 THEN 'Sim' ELSE 'Não' END AS dia_util,
  CASE WHEN u.data >= CURRENT_DATE() THEN 'Sim' ELSE 'Não' END AS data_futura
FROM unificado AS u
LEFT JOIN dias_uteis_acumulado AS d ON u.data = d.data_cal
LEFT JOIN metricas_mensais AS mm
  ON DATE_TRUNC(u.data, MONTH) = mm.mes
  AND u.colaborador = mm.colaborador
  AND u.frente = mm.frente
ORDER BY data, colaborador, frente;