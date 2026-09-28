FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src PORT=8080
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY config ./config
COPY knowledge ./knowledge
COPY prompts ./prompts
COPY src ./src
# SERVICO = gateway | orquestrador | painel | jobs
ENV SERVICO=gateway
CMD ["sh", "-c", "uvicorn celeste.${SERVICO}.app:app --host 0.0.0.0 --port ${PORT}"]
