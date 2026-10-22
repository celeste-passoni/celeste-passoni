-- ============================================================================
-- PROPOSTA (22/10/2026) — frente "Perdidos IA" (Celeste) no funil de resgate.
-- Alterações sobre a query diária do funil (resgate_leads_diario → mensagens_resgate →
-- leads_disponibilizados_diario → resgate_metricas_diarias). NÃO EXECUTAR: texto para aprovação.
--
-- Decisões da clínica (22/10/2026):
--   1. template enviado conta como mensagem e como lead conversado;
--   2. janela: leads criados entre 4 e 3 meses atrás, sem outra exclusão;
--   3. marcadopor da Celeste no TI Saúde: ver AVISO abaixo (hoje grava "Tecnologia");
--   4. vendas: a silver.vendas passa a classificar marcadopor = Celeste como tipo_consulta = 'RESGATE';
--   5. query agendada roda às 05:00; espelho Firestore→BigQuery (job celeste-espelho) às 23:30, antes dela;
--   6. coluna Total soma a Celeste junto das humanas.
--
-- Pré-requisitos fora desta query:
--   • ligar o agendador `celeste-espelho` (hoje pausado): cria o dataset `ia_atendimento` com as tabelas
--     `conversas` e `mensagens` (sem o texto das mensagens; ids em `_id`, conversa em `_pai_id`, datas em ISO);
--   • a carga da base da Celeste (job carregar-base, 06:00) passa a LER a frente 'Perdidos IA' desta tabela
--     em vez de rodar a própria query (painel = Power BI por construção);
--   • confirmar o nome do usuário da API no TI Saúde (AVISO abaixo).
--
-- AVISO (marcadopor): o agendamento real feito pela Celeste em 11/10/2026 (teste da Tati) está em
-- gold.atendimentos com marcadopor = 'Tecnologia', não 'Celeste'. Ou o usuário da API ainda se chama
-- Tecnologia, ou foi renomeado depois e a gold mostra o nome da época. Abaixo uso a constante
-- NOME_CELESTE em todos os filtros; basta trocar num lugar só.
-- ============================================================================

DECLARE NOME_CELESTE STRING DEFAULT 'Celeste';         -- texto exato de marcadopor no TI Saúde
DECLARE INICIO_CELESTE DATE DEFAULT DATE '2026-10-26';  -- dia do lançamento (esqueleto de datas)

-- ----------------------------------------------------------------------------
-- PASSO 1 — nova CTE, junto de orcamento/canceladas/perdidos. Status e opt-out vêm do espelho da Celeste.
-- ----------------------------------------------------------------------------
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
      DATETIME(TIMESTAMP(COALESCE(c.opt_out_em, c.agendado_em, c.ultima_msg_celeste_em))) AS data_atualizacao
    FROM `vertical-theory-489419-a7.gold.leads` t
    LEFT JOIN (   -- conversa mais recente da Celeste com o número (exclui conversas de teste)
      SELECT contato, status, opt_out, opt_out_em, agendado_em, ultima_msg_celeste_em
      FROM `vertical-theory-489419-a7.ia_atendimento.conversas`
      WHERE (teste IS NULL OR teste = FALSE)
      QUALIFY ROW_NUMBER() OVER (PARTITION BY contato ORDER BY criado_em DESC) = 1
    ) c
      ON c.contato = CONCAT('55', REGEXP_REPLACE(CAST(t.celular_sem_ddd AS STRING), r'[^0-9]', ''))
    WHERE LOWER(CAST(t.agendou AS STRING)) IN ('não', 'nao')
      AND DATE(t.created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 MONTH)   -- entre 4 e 3 meses atrás
      AND DATE(t.created_at) <  DATE_SUB(CURRENT_DATE(), INTERVAL 3 MONTH)
      AND LOWER(CAST(t.dentro_2_dias_uteis AS STRING)) IN ('não', 'nao')
      AND LOWER(CAST(t.participou_acao_lead_perdidos AS STRING)) = 'não'
      AND (c.opt_out IS NULL OR c.opt_out = FALSE)                             -- opt-out na Celeste = 'Não quer'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY t.celular_sem_ddd ORDER BY t.created_at DESC) = 1
  )
  -- ... e no SELECT final do USING:
  -- UNION ALL SELECT * FROM perdidos_ia

-- ----------------------------------------------------------------------------
-- gold.mensagens_resgate — bloco da Celeste (UNION ALL com `base`, antes de `com_frente`).
-- Ids do WhatsApp são strings; FARM_FINGERPRINT mantém o tipo INT64 das colunas existentes.
-- direcao 'template' = template da esteira; 'celeste' = balão da IA (texto fixo ou modelo). Ambos contam (decisão 1).
-- ----------------------------------------------------------------------------
  celeste AS (
    SELECT
      FARM_FINGERPRINT(m._id)      AS mensagem_id,
      FARM_FINGERPRINT(m._pai_id)  AS history_id,
      0                            AS user_id,
      'Celeste'                    AS colaborador,
      1                            AS sent_by_operator,
      0                            AS sent_by_auto,
      TIMESTAMP(m.recebido_em)     AS received_at,
      CAST(NULL AS STRING)         AS message,          -- o espelho não traz o texto (privacidade)
      TIMESTAMP(m.recebido_em)     AS created_at,
      CAST(NULL AS INT64)          AS sector_id,
      CAST(NULL AS STRING)         AS protocol,
      c.contato                    AS contact_id,
      CAST(NULL AS INT64)          AS messages_count,
      CAST(NULL AS INT64)          AS closed_by_user_id,
      c.contato                    AS celular,
      'Perdidos IA'                AS frente_original,
      CASE WHEN EXTRACT(DAYOFWEEK FROM DATE(TIMESTAMP(m.recebido_em), 'America/Sao_Paulo')) NOT IN (1, 7)
            AND DATE(TIMESTAMP(m.recebido_em), 'America/Sao_Paulo') NOT IN (SELECT DATE(fer.data) FROM `vertical-theory-489419-a7.silver.feriados` fer)
           THEN 'Sim' ELSE 'Não' END AS dia_util,
      CASE WHEN DATE(TIMESTAMP(m.recebido_em), 'America/Sao_Paulo') >= CURRENT_DATE() THEN 'Sim' ELSE 'Não' END AS data_futura
    FROM `vertical-theory-489419-a7.ia_atendimento.mensagens` m
    JOIN `vertical-theory-489419-a7.ia_atendimento.conversas` c ON c._id = m._pai_id
    WHERE m.direcao IN ('celeste', 'template')
      AND (c.teste IS NULL OR c.teste = FALSE)
      AND DATE(TIMESTAMP(m.recebido_em), 'America/Sao_Paulo') >= INICIO_CELESTE
  )
  -- com_frente passa a ler: SELECT ... FROM base UNION ALL SELECT ... FROM celeste
  -- (o CASE de frente não precisa mudar: 'Perdidos IA' cai no ELSE frente_original)

-- ----------------------------------------------------------------------------
-- PASSO COLABORADOR — primeira linha do CASE:
-- ----------------------------------------------------------------------------
--   WHEN frente = 'Perdidos IA' THEN 'Celeste'
-- (PASSO ATRIBUICAO não muda: continua só para frente = 'Perdidos'.)

-- ----------------------------------------------------------------------------
-- PASSOS 4, 5, 6 e 8 (leads_disponibilizados_diario) — em TODAS as listas de marcadopor acrescentar:
-- ----------------------------------------------------------------------------
--   OR UPPER(a.marcadopor) = UPPER(NOME_CELESTE)        -- atendimentos (passos 4, 6 e 8)
--   OR UPPER(v.marcadopor) = UPPER(NOME_CELESTE)        -- vendas (passo 5)
-- Passo 8, CTE `mensagem`: trocar o CASE de user_id por `m.colaborador AS operador_mensagem`
-- (gold.mensagens_resgate já traz 'Celeste' com user_id 0).
-- Nos passos 4–6 o casamento por contato (frente = 'Perdidos') vale também para 'Perdidos IA':
--   trocar  (T.frente = 'Perdidos' AND ...)  por  (T.frente IN ('Perdidos', 'Perdidos IA') AND ...)
--   e       (T.frente != 'Perdidos' AND ...) por  (T.frente NOT IN ('Perdidos', 'Perdidos IA') AND ...)

-- ----------------------------------------------------------------------------
-- gold.resgate_metricas_diarias
-- ----------------------------------------------------------------------------
-- (a) CTE `mensagens_resgate` (recalculada do bronze): UNION ALL com o mesmo bloco `celeste` acima,
--     projetado em (mensagem_id, colaborador, created_at, celular).
-- (b) `frente_chave_mes` e `frente_contato_mes`, prioridade:
--       CASE frente WHEN 'Inativos' THEN 1 WHEN 'Canceladas' THEN 2 WHEN 'Orcamento' THEN 3
--                   WHEN 'Perdidos IA' THEN 4 ELSE 5 END
-- (c) `base_dia`: mensagem da Celeste é sempre 'Perdidos IA' (antes do CASE atual):
--       WHEN colaborador = 'Celeste' THEN 'Perdidos IA'
-- (d) `atend_raw`: WHERE a.marcadopor IN ('Raiane Santana Souza Santos', 'Maria Fernanda Oliveira Martins', NOME_CELESTE)
--     e frente padrão da Celeste: COALESCE(fkm.frente, fcm.frente, IF(a.marcadopor = NOME_CELESTE, 'Perdidos IA', 'Perdidos'))
--     (idem para frente_data). Em `atend`: WHEN marcadopor = NOME_CELESTE THEN 'Perdidos IA' no início dos dois CASE.
-- (e) `vend_raw`: v.marcadopor IN (..., NOME_CELESTE); em `vend`: WHEN marcadopor = NOME_CELESTE THEN 'Perdidos IA'.
-- (f) esqueleto de datas (`fatos`, último UNION):
--       CROSS JOIN UNNEST(['Raiane Santana Souza Santos', 'Maria Fernanda Oliveira Martins',
--                          'Gisela Madeira Pinto', 'Celeste', 'Total']) AS colab
--       CROSS JOIN UNNEST(['Orcamento', 'Inativos', 'Canceladas', 'Perdidos', 'Perdidos IA']) AS fr
--       WHERE ... AND NOT (colab = 'Celeste' AND (fr != 'Perdidos IA' OR dt < INICIO_CELESTE))
--                 AND NOT (colab != 'Celeste' AND colab != 'Total' AND fr = 'Perdidos IA')
--     'Total' soma a Celeste (decisão 6): os UNIONs de 'Total' já agregam por frente sem filtrar colaborador.

-- ----------------------------------------------------------------------------
-- Lado da Celeste (código, a aprovar separadamente):
--   • jobs/base_leads.py: SELECT chave, contato, nome, data, info_extra
--                         FROM automacoes.resgate_leads_diario WHERE frente = 'Perdidos IA' AND data_execucao = CURRENT_DATE()
--     (quem saiu da tabela sai da base; quem entrou, entra). Agendador carregar-base às 06:00, ligado.
--   • agendador celeste-espelho às 23:30, ligado.
--   • painel: card "leads disponibilizados no mês" lendo a mesma tabela (automacoes.leads_disponibilizados_diario, frente 'Perdidos IA').
-- ----------------------------------------------------------------------------
