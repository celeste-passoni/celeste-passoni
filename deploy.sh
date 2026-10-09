#!/usr/bin/env bash
# Publica a Celeste no Cloud Run.  Uso: ./deploy.sh [gateway|orquestrador|painel|jobs|todos]
# Pré-requisitos: gcloud autenticado no projeto; segredos criados no Secret Manager.
set -euo pipefail
PROJETO="vertical-theory-489419-a7"; REGIAO="southamerica-east1"
ALVO="${1:-todos}"
# IMAGEM_PRONTA=<tag completa> pula o build e só publica (útil quando o build já existe)
if [ -n "${IMAGEM_PRONTA:-}" ]; then
  IMAGEM="$IMAGEM_PRONTA"; echo ">> usando imagem pronta ${IMAGEM}"
else
  IMAGEM="${REGIAO}-docker.pkg.dev/${PROJETO}/celeste/celeste:$(date +%Y%m%d-%H%M%S)"
  echo ">> construindo imagem ${IMAGEM}"
  # a conta de implantação não tem viewer do projeto para transmitir o log: submete assíncrono e consulta o status
  BUILD_ID=$(gcloud builds submit --project "$PROJETO" --region "$REGIAO" --tag "$IMAGEM" --async --quiet --format='value(id)' . 2>/dev/null | tail -1)
  echo ">> build ${BUILD_ID}"
  while :; do
    STATUS=$(gcloud builds describe "$BUILD_ID" --project "$PROJETO" --region "$REGIAO" --format='value(status)')
    case "$STATUS" in
      SUCCESS) echo ">> build concluído"; break ;;
      FAILURE|CANCELLED|TIMEOUT|EXPIRED|INTERNAL_ERROR) echo "build falhou: $STATUS"; exit 1 ;;
      *) sleep 15 ;;
    esac
  done
fi

deploy_orq() {
  gcloud run deploy celeste-orquestrador --project "$PROJETO" --region "$REGIAO" --image "$IMAGEM" \
    --service-account "celeste-orquestrador@${PROJETO}.iam.gserviceaccount.com" \
    --no-allow-unauthenticated --timeout 600 --concurrency 4 --memory 1Gi --cpu 1 --min-instances 0 --max-instances 5 \
    --set-env-vars "SERVICO=orquestrador,GCP_PROJECT=${PROJETO},GCP_REGION=${REGIAO}" --quiet
  # o gateway (via Cloud Tasks, token OIDC) pode invocar o orquestrador
  gcloud run services add-iam-policy-binding celeste-orquestrador --project "$PROJETO" --region "$REGIAO" \
    --member "serviceAccount:celeste-gateway@${PROJETO}.iam.gserviceaccount.com" --role roles/run.invoker --quiet
}

deploy_gw() {
  URL_ORQ=$(gcloud run services describe celeste-orquestrador --project "$PROJETO" --region "$REGIAO" --format 'value(status.url)')
  gcloud run deploy celeste-gateway --project "$PROJETO" --region "$REGIAO" --image "$IMAGEM" \
    --service-account "celeste-gateway@${PROJETO}.iam.gserviceaccount.com" \
    --allow-unauthenticated --timeout 60 --concurrency 40 --memory 512Mi --cpu 1 --min-instances 1 --max-instances 5 \
    --set-env-vars "SERVICO=gateway,GCP_PROJECT=${PROJETO},GCP_REGION=${REGIAO},URL_ORQUESTRADOR=${URL_ORQ},FILA_TASKS=celeste-debounce" --quiet
  echo ">> webhook da Meta: $(gcloud run services describe celeste-gateway --project "$PROJETO" --region "$REGIAO" --format 'value(status.url)')/webhook"
}

deploy_painel() {
  gcloud run deploy celeste-painel --project "$PROJETO" --region "$REGIAO" --image "$IMAGEM"     --service-account "celeste-painel@${PROJETO}.iam.gserviceaccount.com"     --allow-unauthenticated --timeout 60 --memory 512Mi --cpu 1 --min-instances 0 --max-instances 2     --set-env-vars "SERVICO=painel,GCP_PROJECT=${PROJETO},GCP_REGION=${REGIAO},URL_ORQUESTRADOR=$(gcloud run services describe celeste-orquestrador --project "$PROJETO" --region "$REGIAO" --format 'value(status.url)'),URL_JOBS=$(gcloud run services describe celeste-jobs --project "$PROJETO" --region "$REGIAO" --format 'value(status.url)')" --quiet
  gcloud run services add-iam-policy-binding celeste-orquestrador --project "$PROJETO" --region "$REGIAO" \
    --member "serviceAccount:celeste-painel@${PROJETO}.iam.gserviceaccount.com" --role roles/run.invoker --quiet
  gcloud run services add-iam-policy-binding celeste-jobs --project "$PROJETO" --region "$REGIAO" \
    --member "serviceAccount:celeste-painel@${PROJETO}.iam.gserviceaccount.com" --role roles/run.invoker --quiet
  echo ">> painel: $(gcloud run services describe celeste-painel --project "$PROJETO" --region "$REGIAO" --format 'value(status.url)')  (usuário passoni; senha no segredo painel-senha)"
}

deploy_jobs() {
  gcloud run deploy celeste-jobs --project "$PROJETO" --region "$REGIAO" --image "$IMAGEM"     --service-account "celeste-jobs@${PROJETO}.iam.gserviceaccount.com"     --no-allow-unauthenticated --timeout 900 --concurrency 1 --memory 1Gi --cpu 1 --min-instances 0 --max-instances 1     --set-env-vars "SERVICO=jobs,GCP_PROJECT=${PROJETO},GCP_REGION=${REGIAO},URL_ORQUESTRADOR=$(gcloud run services describe celeste-orquestrador --project "$PROJETO" --region "$REGIAO" --format 'value(status.url)')" --quiet
  gcloud run services add-iam-policy-binding celeste-orquestrador --project "$PROJETO" --region "$REGIAO" \
    --member "serviceAccount:celeste-jobs@${PROJETO}.iam.gserviceaccount.com" --role roles/run.invoker --quiet
  URL=$(gcloud run services describe celeste-jobs --project "$PROJETO" --region "$REGIAO" --format 'value(status.url)')
  SA="celeste-jobs@${PROJETO}.iam.gserviceaccount.com"
  gcloud run services add-iam-policy-binding celeste-jobs --project "$PROJETO" --region "$REGIAO" --member "serviceAccount:$SA" --role roles/run.invoker --quiet
  agendar() {  # nome cron caminho
    gcloud scheduler jobs describe "$1" --project "$PROJETO" --location "$REGIAO" >/dev/null 2>&1 && ACAO=update || ACAO=create
    gcloud scheduler jobs $ACAO http "$1" --project "$PROJETO" --location "$REGIAO" --schedule "$2" --time-zone "America/Sao_Paulo"       --uri "${URL}$3" --http-method POST --oidc-service-account-email "$SA" --attempt-deadline 900s --quiet
  }
  agendar celeste-carregar-base "0 6 * * *"        /jobs/carregar-base
  agendar celeste-disparos      "*/30 9-18 * * 1-5" /jobs/disparos
  agendar celeste-espelho       "30 23 * * *"       /jobs/espelho
  agendar celeste-lembretes     "0 9-19 * * 1-5"  /jobs/lembretes      # retomada no mesmo dia; fica PAUSADO até a clínica liberar
  agendar celeste-aquecer-cache "0,50 6-23 * * *"  /jobs/aquecer-cache   # 06:00 até 23:50 (cache vale até 00:50)
}

case "$ALVO" in
  painel) deploy_painel ;;
  jobs) deploy_jobs ;;
  orquestrador) deploy_orq ;;
  gateway) deploy_gw ;;
  todos) deploy_orq; deploy_gw; deploy_painel; deploy_jobs ;;
  *) echo "alvo inválido: $ALVO"; exit 1 ;;
esac
