from __future__ import annotations

from codeprobe.core.infra.docker import DockerComposeParser, DockerfileParser
from codeprobe.core.infra.shell import ShellEnvResolver


def test_docker_compose_parser():
    compose_yaml = """
version: '3.8'
services:
  web:
    image: python:3.11-slim
    container_name: web-app
    ports:
      - "8000:8000"
    depends_on:
      - db
      - redis
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/testdb
      - REDIS_HOST=redis
      - DEBUG=1
    env_file:
      - .env.local
    volumes:
      - ./src:/app/src
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: testdb
      POSTGRES_USER: user
      POSTGRES_PASSWORD: secretpassword
    ports:
      - "5432:5432"
    volumes:
      - db-data:/var/lib/postgresql/data
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
volumes:
  db-data:
"""
    units = DockerComposeParser.parse(compose_yaml, file_path="docker-compose.yml")
    by_name = {u.name: u for u in units}

    assert "web" in by_name
    assert "db" in by_name
    assert "redis" in by_name

    web_svc = by_name["web"]
    assert web_svc.kind == "docker_service"
    assert "8000:8000" in web_svc.signature
    # web depends on db and redis!
    assert "db" in web_svc.calls
    assert "redis" in web_svc.calls
    # web has env vars
    assert "DATABASE_URL" in web_svc.calls
    assert "REDIS_HOST" in web_svc.calls

    db_svc = by_name["db"]
    assert "5432:5432" in db_svc.signature
    assert "POSTGRES_DB" in db_svc.calls
    assert "POSTGRES_USER" in db_svc.calls


def test_dockerfile_parser():
    dockerfile_content = """
# Build stage
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci

# Production stage
FROM node:18-alpine
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
EXPOSE 3000 8080
CMD ["node", "dist/main.js"]
"""
    units = DockerfileParser.parse(dockerfile_content, file_path="Dockerfile")
    assert len(units) == 1
    df = units[0]
    assert df.kind == "dockerfile"
    assert "3000" in df.calls
    assert "8080" in df.calls
    assert "NODE_ENV" in df.calls
    assert "PORT" in df.calls
    assert "node:18-alpine" in df.calls
    assert "EXPOSE 3000" in df.docstring or "ExposedPorts" in df.docstring


def test_shell_script_parser():
    sh_content = """
#!/usr/bin/env bash
set -e

export DEPLOY_ENV="production"
export REGION="ap-southeast-1"

build_image() {
    docker build -t app:$DEPLOY_ENV .
}

deploy_k8s() {
    kubectl apply -f deploy/$REGION/
}

echo "Deploying to $DEPLOY_ENV in ${REGION}"
build_image
deploy_k8s
"""
    units = ShellEnvResolver.parse_shell_script(
        sh_content, file_path="scripts/deploy.sh"
    )
    by_name = {u.name: u for u in units}

    assert "DEPLOY_ENV" in by_name
    assert by_name["DEPLOY_ENV"].kind == "env_var"

    assert "REGION" in by_name
    assert by_name["REGION"].kind == "env_var"

    assert "build_image" in by_name
    assert by_name["build_image"].kind == "function"

    assert "deploy_k8s" in by_name
    assert by_name["deploy_k8s"].kind == "function"

    assert "deploy.sh" in by_name
    assert by_name["deploy.sh"].kind == "shell_script"


def test_env_file_parser():
    env_content = """
# Production secrets
DATABASE_URL=postgresql://app:pass@db.internal:5432/prod
SECRET_KEY=supersecretjwtkey12345
REDIS_PORT=6379
STRIPE_WEBHOOK_SECRET=whsec_abc123
"""
    units = ShellEnvResolver.parse_env_file(env_content, file_path=".env.production")
    by_name = {u.name: u for u in units}

    assert "DATABASE_URL" in by_name
    assert by_name["DATABASE_URL"].kind == "env_var"
    assert "SECRET_KEY" in by_name
    assert by_name["SECRET_KEY"].kind == "env_var"
    assert "REDIS_PORT" in by_name
    assert by_name["REDIS_PORT"].kind == "env_var"
    assert ".env.production" in by_name
    assert by_name[".env.production"].kind == "env_file"
    assert "DATABASE_URL" in by_name[".env.production"].calls
