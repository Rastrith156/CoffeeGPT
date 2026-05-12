# Docker Notes

The project keeps the runtime orchestration in the root `docker-compose.yml` and the application image definition in `backend/Dockerfile`.

Use:

```powershell
docker compose up -d postgres redis qdrant
docker compose up backend
```

Add `celery_worker` after the backend is stable if you want asynchronous ingestion through Redis.
