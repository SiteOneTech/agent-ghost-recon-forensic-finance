"""Job endpoints: preview, launch and cancel (admin); list, detail, events as JSON or SSE, and log (viewer)."""

from __future__ import annotations

import asyncio
import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import commands, jobfiles, procs, readmodel
from ..auth import Principal
from ..commands import CommandError, LaunchRequest
from ..deps import ApiError, ConsoleContext, client_ip, get_ctx, require
from ..store import ACTIVE_STATUSES, JOB_STATUSES, TERMINAL_STATUSES
from .cases import get_case_or_404

router = APIRouter(tags=["jobs"])
HEARTBEAT_S = 15.0
_STATUS_KEYS = ("status", "phase", "session_id", "case_id")


class LaunchBody(BaseModel):
    command: Literal["new-open-case", "rerun-case", "review-case"]
    folder: str = Field(min_length=1, max_length=4096)
    name: str = Field("", max_length=1000)
    currency: str = Field("", max_length=16)
    lang: str = Field("", max_length=16)
    out: str = Field("", max_length=4096)
    notes: str = Field("", max_length=100_000)  # commands.plan enforces MAX_NOTES with a clear message
    # SHA-256 of the context.md the preview showed ("none": it had none); a launch refuses one changed since then.
    context_sha256: Optional[str] = Field(None, pattern=r"^([0-9a-f]{64}|none)$")

    def to_request(self) -> LaunchRequest:
        return LaunchRequest(**self.model_dump())


def _api_error(exc: CommandError) -> ApiError:
    return ApiError(exc.status, exc.code, exc.message)


def _job_or_404(ctx: ConsoleContext, job_id: int) -> dict:
    job = ctx.cstore.get_job(job_id)
    if not job:
        raise ApiError(404, "not_found", f"ejecución no encontrada: {job_id}")
    return job


def _redacted(text):
    """Spec §9: the console never shows secret values. Log tails, job errors, the agent's final text and event details
    pass through Hermes' redactor before any viewer sees them (forced: this is a display boundary, whatever
    ``security.redact_secrets`` says)."""
    from agent.redact import redact_sensitive_text
    return redact_sensitive_text(text, force=True) if text else text


def _event(event: dict) -> dict:
    return {**event, "detail": _redacted(event.get("detail"))}


def _view(ctx: ConsoleContext, job: dict) -> dict:
    view = readmodel.job_view(ctx.store, ctx.cstore, job, profile_args=procs.profile_args(),
                              dashboard_url=ctx.settings.dashboard_url)
    view["display"] = commands.display_command(view["argv"]) if view["argv"] else ""
    view["error"], view["result_text"] = _redacted(view["error"]), _redacted(view["result_text"])
    return view


@router.post("/jobs/preview")
def preview(body: LaunchBody, principal: Principal = Depends(require("admin")),
            ctx: ConsoleContext = Depends(get_ctx)):
    try:
        return ctx.jobs.preview(body.to_request(), principal.username)
    except CommandError as exc:
        raise _api_error(exc) from exc


@router.post("/jobs", status_code=202)
def launch(body: LaunchBody, request: Request, principal: Principal = Depends(require("admin")),
           ctx: ConsoleContext = Depends(get_ctx)):
    try:
        job = ctx.jobs.launch(body.to_request(), principal, ip=client_ip(request))
    except CommandError as exc:
        raise _api_error(exc) from exc
    return {"job": _view(ctx, job)}


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: int, request: Request, principal: Principal = Depends(require("admin")),
           ctx: ConsoleContext = Depends(get_ctx)):
    try:
        job = ctx.jobs.cancel(job_id, principal, ip=client_ip(request))
    except CommandError as exc:
        raise _api_error(exc) from exc
    return {"job": _view(ctx, job)}


@router.get("/jobs")
def list_jobs(status: str = "", case: str = "", cursor: str = "", limit: int = Query(100, ge=1, le=500),
              _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    """Newest first; ``next_cursor`` (the last id returned) continues the list while more rows exist."""
    if status and status != "active" and status not in JOB_STATUSES:
        raise ApiError(422, "invalid_argument", f"estado desconocido: {status}")
    if cursor and not (cursor.isascii() and cursor.isdigit()):
        raise ApiError(422, "invalid_argument", f"cursor inválido: {cursor}")
    statuses = ACTIVE_STATUSES if status == "active" else ((status,) if status else ())
    folder = get_case_or_404(ctx, case)["root_path"] if case else ""
    rows = ctx.cstore.list_jobs(statuses=statuses, case_id=case, folder=folder, limit=limit + 1,
                                before_id=int(cursor) if cursor else None)
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [readmodel.job_row(ctx.store, j) for j in rows],
            "next_cursor": str(rows[-1]["id"]) if more else None}


@router.get("/cases/{case_id}/jobs")
def case_jobs(case_id: str, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    case = get_case_or_404(ctx, case_id)
    rows = ctx.cstore.list_jobs(case_id=case_id, folder=case["root_path"])
    return {"items": [readmodel.job_row(ctx.store, j) for j in rows]}


@router.get("/jobs/{job_id}")
def job_detail(job_id: int, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    return _view(ctx, _job_or_404(ctx, job_id))


@router.get("/jobs/{job_id}/events")
def job_events(job_id: int, after: int = Query(0, ge=0), _: Principal = Depends(require("viewer")),
               ctx: ConsoleContext = Depends(get_ctx)):
    _job_or_404(ctx, job_id)
    items, _offset = jobfiles.read_events(jobfiles.events_path(ctx.jobs.jobs_dir, job_id), after=after)
    return {"items": [_event(e) for e in items], "last_seq": items[-1]["seq"] if items else after}


@router.get("/jobs/{job_id}/events/stream")
async def job_stream(job_id: int, request: Request, after: int = Query(0, ge=0),
                     _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    """SSE: ``event`` frames whose id is the event's seq (a reconnect resumes after Last-Event-ID), a ``status``
    frame whenever status/phase/session/case change, ``end`` once the job is over and its events are drained, and a
    comment as heartbeat. The events file is polled every ``stream_poll`` seconds (1 s by default)."""
    _job_or_404(ctx, job_id)
    last = request.headers.get("last-event-id", "")
    start = max(after, int(last)) if last.isascii() and last.isdigit() else after
    path = jobfiles.events_path(ctx.jobs.jobs_dir, job_id)
    poll = ctx.jobs.stream_poll

    async def frames():
        seq, offset, sent, idle = start, 0, None, 0.0
        while not await request.is_disconnected():
            # Job row first: the runner appends its last events and only then sets the terminal status, so a
            # terminal row read BEFORE an empty events read proves nothing is left to send.
            job = ctx.cstore.get_job(job_id)
            items, offset = jobfiles.read_events(path, after=seq, offset=offset)
            for event in items:
                seq = event["seq"]
                yield f"id: {seq}\nevent: event\ndata: {json.dumps(_event(event), ensure_ascii=False)}\n\n"
            state = {key: job.get(key) for key in _STATUS_KEYS}
            if state != sent:
                sent = state
                yield f"event: status\ndata: {json.dumps(state, ensure_ascii=False)}\n\n"
            if job["status"] in TERMINAL_STATUSES and not items:
                yield f"event: end\ndata: {json.dumps({'status': job['status']})}\n\n"
                return
            idle = 0.0 if items else idle + poll
            if idle >= HEARTBEAT_S:
                idle = 0.0
                yield ": keepalive\n\n"
            await asyncio.sleep(poll)

    return StreamingResponse(frames(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@router.get("/jobs/{job_id}/log")
def job_log(job_id: int, _: Principal = Depends(require("viewer")), ctx: ConsoleContext = Depends(get_ctx)):
    _job_or_404(ctx, job_id)
    base = ctx.jobs.jobs_dir
    return {"log": _redacted(jobfiles.tail(jobfiles.log_path(base, job_id))),
            "runner_log": _redacted(jobfiles.tail(jobfiles.runner_log_path(base, job_id), lines=50))}
