# Medical Research Agent - API + browser UI in one container.
#   docker build -t medresearch-agent .
#   docker run -p 8000:8000 --env-file .env medresearch-agent
FROM python:3.13-slim

WORKDIR /app
COPY requirements-genomics.txt requirements-serve.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements-genomics.txt

COPY config.py ./
COPY agent/ agent/
COPY tools/ tools/
COPY rag/ rag/
COPY eval/ eval/
COPY serve/ serve/
COPY genomics/ genomics/
COPY pharmacovigilance/ pharmacovigilance/
COPY data/faers_demo.db data/faers_demo.db
COPY data/faers_real.db data/faers_real.db

# Render supplies PORT (normally 10000). Default stays 8000 for local Docker.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn serve.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
