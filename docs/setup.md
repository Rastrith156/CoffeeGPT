# Setup Guide

## Local prerequisites

- Python `3.11+`
- Docker Desktop
- LM Studio for Windows

The current machine already reports Python `3.12.10`, which satisfies the version requirement.

## Backend bootstrap

Run the helper script from the project root:

```powershell
.\scripts\bootstrap_backend.ps1
```

This script:

- creates `backend\venv` if needed
- upgrades `pip`
- installs `backend\requirements.txt`
- creates `.env` from `.env.example` if it does not already exist

## Infrastructure services

Start the backing services with Docker:

```powershell
.\scripts\stack_up.ps1
```

This brings up:

- PostgreSQL
- Redis
- Qdrant

## LM Studio

Start the LM Studio local server and load the model you want the backend to use:

```powershell
lms load "dolphin-2.9-llama3-8b-256k-smashed"
lms server start --port 1234
```

## Run the API

```powershell
.\scripts\run_backend.ps1
```

Primary endpoints:

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/api/v1/health/detailed`

## Readiness checklist

- `backend` imports successfully
- `postgres` health is `ok`
- `redis` health is `ok`
- `qdrant` is reachable
- `lmstudio` is reachable and the configured model is available
- `ingest/trigger` can write files into `data/raw` and `data/processed`
