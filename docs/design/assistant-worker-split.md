# Assistant Worker Split

The current assistant API process still owns request/response handling, SSE
streaming, startup zombie recovery, and the periodic zombie reaper. The next
runtime split should keep the API focused on HTTP and move cron/queue-heavy
work into an `assistant-worker` process.

Target shape:

- API: FastAPI routes, SSE streaming, request validation, and short-lived
  orchestration for interactive analysis.
- Worker: periodic reaper, future retry queues, prompt-cache refresh, and
  LLM-heavy work that should not consume API worker slots.
- Shared code: both processes import the same `app.core`, `app.infra`, models,
  and database modules from the assistant-service package.

The first executable seam is `python -m app.workers.reaper`, which runs the
same periodic reaper loop the API starts during lifespan. A future compose
service can use the assistant-service image and replace the command with that
module without editing `app.core`.
