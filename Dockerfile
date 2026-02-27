FROM python:3.11-slim

WORKDIR /app

# Dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && rm -rf /var/lib/apt/lists/*

# Instalar pacote
COPY pyproject.toml ./
COPY *.py ./
COPY data/mapeamento_criticas_manual.json data/

RUN pip install --no-cache-dir -e .

# Config SSE
ENV TOKENIZERS_PARALLELISM=false
ENV FASTMCP_HOST=0.0.0.0
ENV FASTMCP_PORT=8200

EXPOSE 8200

CMD ["python", "mcp_server.py", "--transport", "sse"]
