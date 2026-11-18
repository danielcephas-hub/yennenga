# Application en ligne : interface (React, compilée) + service de calcul (Python). Construite depuis la racine :
#   docker compose -f deploiement/docker-compose.yml up -d --build

# 1. Interface
FROM node:24-slim AS interface
WORKDIR /interface
COPY interface/package.json interface/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY interface/ ./
RUN npm run build

# 2. Service
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
COPY deploiement/requirements_service.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# code, paramètres, référentiel territorial et tables produites par la chaîne (python -m dcb.pipeline)
COPY config.yaml ./
COPY src ./src
COPY referentiel ./referentiel
COPY data/processed ./data/processed
COPY outputs/tableau_de_bord ./outputs/tableau_de_bord
COPY outputs/web ./outputs/web
COPY --from=interface /interface/dist ./interface/dist

RUN useradd --system --uid 10001 --no-create-home service && mkdir -p /app/data/entrepot && chown -R service /app/data/entrepot
USER service

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/sante', timeout=4).status == 200 else 1)"
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "dcb.service:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
