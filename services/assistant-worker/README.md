# assistant-worker

Reserved worker process slot for assistant-service long-running work.

No compose service is enabled yet. The intended first command is run from the
assistant-service package/image:

```bash
python -m app.workers.reaper
```

That module shares `app.core`, `app.infra`, models, and database settings with
the API process, so wiring this directory into a future image or compose
service should not require changes inside `app.core`.
