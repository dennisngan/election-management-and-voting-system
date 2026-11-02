# syntax=docker/dockerfile:1
FROM mysql:8.4@sha256:a0225d1ea6631c8bc2385dc4c2faba17bbf1834ecf369e1659a9a382bd8d5dd7 AS mysql-tools
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv
FROM python:3.14-slim-bookworm@sha256:516b51cb9db2ef061e465c803e50f64361b82cefd91e525b889b967b83e83527

COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libssl3 libstdc++6 libncurses6 libtinfo6 zlib1g \
    && rm -rf /var/lib/apt/lists/*
COPY --from=mysql-tools /usr/bin/mysql /usr/bin/mysqldump /usr/local/bin/
RUN mysql --version && mysqldump --version

WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-default-groups --group server --group reports
COPY . .
RUN python -m election.deployment identity > /app/release.json \
    && useradd --uid 10001 --create-home election
USER 10001:10001
EXPOSE 8443
CMD ["python", "-m", "election.deployment", "serve"]
