# Nudgy backend. Build from the repo root: docker build -f backend/Dockerfile -t nudgy-backend .
FROM python:3.11-slim

WORKDIR /srv
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/prompts ./prompts
COPY backend/config ./config
RUN pip install --no-cache-dir ".[postgres]"

# All configuration comes from env vars (see .env.example); never bake secrets into the image.
ENV NUDGY_ENV=production
# SQLite by default (single instance); set NUDGY_DATABASE_URL=postgresql+psycopg://… to scale out.
ENV NUDGY_DATABASE_URL=sqlite:////data/nudgy.db
RUN mkdir /data && chown nobody /data
VOLUME /data
EXPOSE 8787
USER nobody
CMD ["uvicorn", "app.main:app", "--app-dir", "/srv", "--host", "0.0.0.0", "--port", "8787", "--proxy-headers"]
