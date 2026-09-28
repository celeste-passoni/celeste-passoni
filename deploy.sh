#!/usr/bin/env bash
# Publica a Celeste no Cloud Run.  Uso: ./deploy.sh [gateway|orquestrador|painel|jobs|todos]
# Pré-requisitos: gcloud autenticado no projeto; segredos criados no Secret Manager.
set -euo pipefail
PROJETO="vertical-theory-489419-a7"; REGIAO="southamerica-east1"
IMAGEM="${REGIAO}-docker.pkg.dev/${PROJETO}/celeste/celeste:$(date +%Y%m%d-%H%M%S)"
ALVO="${1:-todos}"

echo ">> construindo imagem ${IMAGEM}"
gcloud builds submit --project "$PROJETO" --region "$REGIAO" --tag "$IMAGEM" --quiet .

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
  gcloud run deploy celeste-painel --project "$PROJETO" --region "$REGIAO" --image "$IMAGEM"     --service-account "celeste-painel@${PROJETO}.iam.gserviceaccount.com"     --allow-unauthenticated --timeout 60 --memory 512Mi --cpu 1 --min-instances 0 --max-instances 2     --set-env-vars "SERVICO=painel,GCP_PROJECT=${PROJETO},GCP_REGION=${REGIAO}" --quiet
  echo ">> painel: $(gcloud run services describe celeste-painel --project "$PROJETO" --region "$REGIAO" --format 'value(status.url)')  (usuário passoni; senha no segredo painel-senha)"
}

deploy_jobs() {
  gcloud run deploy celeste-jobs --project "$PROJETO" --region "$REGIAO" --image "$IMAGEM"     --service-account "celeste-jobs@${PROJETO}.iam.gserviceaccount.com"     --no-allow-unauthenticated --timeout 900 --concurrency 1 --memory 1Gi --cpu 1 --min-instances 0 --max-instances 1     --set-env-vars "SERVICO=jobs,GCP_PROJECT=${PROJETO},GCP_REGION=${REGIAO}" --quiet
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
}

case "$ALVO" in
  painel) deploy_painel ;;
  jobs) deploy_jobs ;;
  orquestrador) deploy_orq ;;
  gateway) deploy_gw ;;
  todos) deploy_orq; deploy_gw; deploy_painel; deploy_jobs ;;
  *) echo "alvo inválido: $ALVO"; exit 1 ;;
esac
