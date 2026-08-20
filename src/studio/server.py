"""Local HTTP studio: homepage form, job API, and dashboard serving."""
from __future__ import annotations

import json
import os
import re
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

import requests

from . import jobs
from .window import ALLOWED_DAYS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOME_HTML = Path(__file__).with_name("home.html")
_SAFE_DIR = re.compile(r"^output[-A-Za-z0-9._]*$")
_SAFE_JOB = re.compile(r"^[a-f0-9]{6,32}$")
_NAV_LINKS = '<div class="nav-links">'
_OLD_BRAND = '<div class="brand"><span class="brand-accent">On-Chain</span> Token Crash</div>'
_HOME_BRAND = '<div class="brand"><a id="nav-home-brand" href="/"><span class="brand-accent">On-Chain</span> Token Crash</a></div>'
_HOME_LINK = '<a id="nav-home" href="/">Home</a>'
_HOME_SCRIPT = (
    '<script data-studio-home="1">'
    'document.querySelectorAll("#nav-home,#nav-home-brand")'
    '.forEach(function(el){el.href="/";});'
    "</script>\n"
)


def inject_studio_home(html: bytes) -> bytes:
    """Ensure served dashboards can return to the studio homepage."""
    text = html.decode("utf-8", errors="replace")
    if _NAV_LINKS in text and 'id="nav-home"' not in text:
        text = text.replace(_NAV_LINKS, _NAV_LINKS + "\n      " + _HOME_LINK, 1)
    if _OLD_BRAND in text:
        text = text.replace(_OLD_BRAND, _HOME_BRAND, 1)
    text = re.sub(
        r'(id="nav-home(?:-brand)?"[^>]*href=")[^"]*"',
        r'\1/"',
        text,
    )
    if 'data-studio-home="1"' not in text:
        text = text.replace("</body>", _HOME_SCRIPT + "</body>", 1)
    return text.encode("utf-8")


def list_runs() -> list[dict[str, Any]]:
    """Completed local analyses that already have a dashboard."""
    rows: list[dict[str, Any]] = []
    for out_dir in sorted(PROJECT_ROOT.glob("output*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not out_dir.is_dir():
            continue
        dash = out_dir / "dashboard.html"
        profile_path = out_dir / "token_profile.json"
        if not dash.exists() or not profile_path.exists():
            continue
        try:
            profile = json.loads(profile_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        risk: dict[str, Any] = {}
        risk_path = out_dir / "risk_assessment.json"
        if risk_path.exists():
            try:
                risk = json.loads(risk_path.read_text())
            except (OSError, json.JSONDecodeError):
                risk = {}
        pools: list[Any] = []
        pools_path = out_dir / "verified_pools.json"
        if pools_path.exists():
            try:
                loaded = json.loads(pools_path.read_text())
                if isinstance(loaded, list):
                    pools = loaded
            except (OSError, json.JSONDecodeError):
                pools = []
        rows.append({
            "dir": out_dir.name,
            "symbol": profile.get("symbol") or out_dir.name,
            "name": profile.get("name") or "",
            "address": profile.get("address") or "",
            "num_pools": len(pools),
            "risk_score": float(risk.get("final_score") or 0),
            "risk_level": risk.get("risk_level") or "N/A",
        })
    return rows


def _latest_block() -> tuple[bool, Optional[int], str]:
    """Look up latest block with a short timeout and no 429 retry loop."""
    url = (os.environ.get("ETH_RPC_URL") or os.environ.get("RPC_URL") or "").strip()
    if not url:
        return False, None, "ETH_RPC_URL is not set"
    try:
        resp = requests.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []},
            timeout=4,
        )
        payload = resp.json() if resp.content else {}
    except Exception as exc:
        return False, None, str(exc)
    err = payload.get("error") if isinstance(payload, dict) else None
    if resp.status_code == 429 or (isinstance(err, dict) and err.get("code") == 429):
        return False, None, "RPC quota exceeded (429). Enter from-block manually."
    if err:
        return False, None, str(err.get("message") or err)
    result = payload.get("result") if isinstance(payload, dict) else None
    if not result:
        return False, None, "RPC returned HTTP {}".format(resp.status_code)
    try:
        return True, int(result, 16), ""
    except (TypeError, ValueError):
        return False, None, "invalid eth_blockNumber result"


def _safe_output_dir(name: str) -> Optional[Path]:
    if not _SAFE_DIR.match(name or ""):
        return None
    path = (PROJECT_ROOT / name).resolve()
    if path.parent != PROJECT_ROOT.resolve() or not path.is_dir():
        return None
    return path


class StudioHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        print(fmt % args)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in ("/", "/index.html"):
            self._send_bytes(HOME_HTML.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/status":
            rpc_ok, latest, err = _latest_block()
            self._send_json({
                "rpc_ok": rpc_ok,
                "latest_block": latest,
                "rpc_error": err,
                "running": jobs.has_active_job(),
            })
            return
        if path == "/api/runs":
            self._send_json(list_runs())
            return
        if path == "/api/jobs":
            self._send_json(jobs.list_jobs())
            return
        if path.startswith("/api/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            if not _SAFE_JOB.match(job_id):
                self._send_json({"error": "unknown job"}, 404)
                return
            job = jobs.get_job(job_id)
            if not job:
                self._send_json({"error": "unknown job"}, 404)
                return
            self._send_json(job)
            return
        if path.startswith("/run/"):
            self._serve_run(path)
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/analyze":
            self.send_error(404, "Not found")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(max(0, min(length, 32_768)))
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"error": "invalid JSON"}, 400)
            return
        token = str(payload.get("token") or "").strip()
        try:
            days = int(payload.get("days"))
        except (TypeError, ValueError):
            self._send_json({"error": "days must be 7 or 30"}, 400)
            return
        if days not in ALLOWED_DAYS:
            self._send_json({"error": "days must be 7 or 30"}, 400)
            return
        from_block = payload.get("from_block")
        try:
            from_parsed = int(from_block) if from_block not in (None, "",) else None
        except (TypeError, ValueError):
            self._send_json({"error": "from_block must be an integer"}, 400)
            return
        to_block = None
        if from_parsed is None:
            rpc_ok, latest, err = _latest_block()
            if not rpc_ok or latest is None:
                self._send_json({"error": "RPC unavailable: {}".format(err)}, 503)
                return
            to_block = latest
        try:
            job = jobs.enqueue(token, days, from_block=from_parsed, to_block=to_block)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
            return
        self._send_json(job, 202)

    def _serve_run(self, path: str) -> None:
        parts = [part for part in path.split("/") if part]
        # /run/<output-dir>/dashboard.html
        if len(parts) != 3 or parts[0] != "run" or parts[2] != "dashboard.html":
            self.send_error(404, "Not found")
            return
        out = _safe_output_dir(parts[1])
        if out is None:
            self.send_error(404, "Not found")
            return
        dash = out / "dashboard.html"
        if not dash.is_file():
            self.send_error(404, "Dashboard not generated yet")
            return
        self._send_bytes(
            inject_studio_home(dash.read_bytes()),
            "text/html; charset=utf-8",
            no_store=True,
        )

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        *,
        no_store: bool = False,
    ) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    socketserver.TCPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer((host, port), StudioHandler)
    print("Studio: http://{}:{}/".format(host, port))
    print("Bind localhost only unless you pass a different --host.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
