"""Background analyze jobs for the local studio (one at a time)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .window import chart_span_for_days, output_dir_name, window_ending_at, window_from_start

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_QUEUE: list[str] = []
_WORKER_STARTED = False


def list_jobs() -> list[dict[str, Any]]:
    with _LOCK:
        return [dict(_JOBS[jid]) for jid in reversed(list(_JOBS.keys()))]


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def has_active_job() -> bool:
    with _LOCK:
        return any(
            job.get("status") in ("queued", "running") for job in _JOBS.values()
        )


def enqueue(
    token: str,
    days: int,
    *,
    from_block: Optional[int] = None,
    to_block: Optional[int] = None,
) -> dict[str, Any]:
    token = (token or "").strip()
    if not token or len(token) > 80:
        raise ValueError("token must be a symbol, name, or 0x address")
    if from_block is None and to_block is None:
        raise ValueError("need from_block or a latest to_block")
    if from_block is not None:
        start, end = window_from_start(from_block, days)
    else:
        start, end = window_ending_at(int(to_block), days)
    out_dir = output_dir_name(token, days, start)
    job_id = uuid.uuid4().hex[:10]
    job = {
        "id": job_id,
        "token": token,
        "days": int(days),
        "from_block": start,
        "to_block": end,
        "output_dir": out_dir,
        "status": "queued",
        "log": "Queued behind the current analysis.\n",
        "error": "",
        "dashboard": "/run/{}/dashboard.html".format(out_dir),
        "created_at": time.time(),
    }
    with _LOCK:
        _JOBS[job_id] = job
        _QUEUE.append(job_id)
        _ensure_worker()
        return dict(job)


def _ensure_worker() -> None:
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True
    threading.Thread(target=_worker, name="studio-analyze", daemon=True).start()


def _append(job_id: str, line: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["log"] = (job.get("log") or "") + line
        if len(job["log"]) > 200_000:
            job["log"] = job["log"][-160_000:]


def _set_status(job_id: str, **fields: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.update(fields)


def _worker() -> None:
    while True:
        with _LOCK:
            job_id = _QUEUE.pop(0) if _QUEUE else None
        if not job_id:
            time.sleep(0.4)
            continue
        job = get_job(job_id)
        if not job:
            continue
        _run_analyze(job)


def _run_analyze(job: dict[str, Any]) -> None:
    job_id = job["id"]
    _set_status(job_id, status="running")
    cmd = [
        sys.executable, "-m", "src.cli", "analyze", str(job["token"]),
        "--from-block", str(job["from_block"]),
        "--to-block", str(job["to_block"]),
        "--output-dir", str(job["output_dir"]),
        "--chart-span", chart_span_for_days(job["days"]),
        "--index-source", "auto",
    ]
    _append(job_id, "$ {}\n".format(" ".join(cmd)))
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
        )
    except Exception as exc:
        _set_status(job_id, status="error", error=str(exc))
        _append(job_id, "failed to start: {}\n".format(exc))
        return
    assert proc.stdout is not None
    for line in proc.stdout:
        _append(job_id, line)
    code = proc.wait()
    dash = PROJECT_ROOT / job["output_dir"] / "dashboard.html"
    if code == 0 and dash.exists():
        _set_status(job_id, status="done")
        _append(job_id, "\nDashboard ready: {}\n".format(dash))
    else:
        _set_status(
            job_id,
            status="error",
            error="analyze exited {}".format(code),
        )
        _append(job_id, "\nanalyze exited {}\n".format(code))
