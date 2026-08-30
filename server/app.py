"""
Static file server + Tripo3D text-to-3D proxy for AR-Prompt3D.

Runs with the Python 3 standard library only (no npm/node, no pip installs
needed). The proxy exists so the Tripo3D API key never reaches the browser
and so the client doesn't have to deal with a third-party origin's CORS or
signed-URL rules directly.

Tripo3D was chosen over Meshy AI (the original target) because Meshy's REST
API requires prepaid credits with no free tier, while new Tripo3D API
accounts get 300 free credits (no card required), enough for many
generations during development and grading.

Usage:
    export TRIPO_API_KEY="your_key_here"
    python3 server/app.py [port]
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Tripo3D task ids are opaque tokens; reject anything else before it
# touches the filesystem or gets forwarded upstream (defense against path
# traversal via a crafted /api/status/<id> or /api/model/<id>.glb request).
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT / "public"
CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)

TRIPO_API_KEY = os.environ.get("TRIPO_API_KEY", "")
TRIPO_BASE = "https://openapi.tripo3d.ai/v3"
# Overridable in case the API requires an explicit "model" field; leave
# unset to omit the field and let Tripo3D pick its own default first.
TRIPO_MODEL = os.environ.get("TRIPO_MODEL", "")

# In-memory record of tasks we've created, so /api/model/<id>.glb knows
# where to fetch the asset from without re-polling Tripo3D.
TASKS = {}


def tripo_request(method, url, body=None):
    if not TRIPO_API_KEY:
        raise RuntimeError(
            "TRIPO_API_KEY is not set. Get a key at "
            "https://platform.tripo3d.ai (API Keys page) and run:\n"
            "  export TRIPO_API_KEY=your_key_here"
        )
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TRIPO_API_KEY}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
        sys.stderr.write(f"[tripo] {method} {url} -> {raw[:500]}\n")
        return json.loads(raw)


def _unwrap(result):
    """Tripo3D wraps responses as {code, data, message}; unwrap defensively
    since the exact envelope wasn't confirmed against live docs."""
    if isinstance(result, dict) and "data" in result:
        return result["data"]
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, obj, status=200):
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    # ---- routing -----------------------------------------------------

    def do_GET(self):
        if self.path.startswith("/api/status/"):
            return self._handle_status(self.path[len("/api/status/"):])
        if self.path.startswith("/api/model/"):
            return self._handle_model(self.path[len("/api/model/"):])
        return self._serve_static()

    def do_POST(self):
        if self.path == "/api/generate":
            return self._handle_generate()
        self._send_json({"error": "not found"}, 404)

    # ---- API handlers --------------------------------------------------

    def _handle_generate(self):
        try:
            body = self._read_json_body()
            prompt = (body.get("prompt") or "").strip()
            if not prompt:
                return self._send_json({"error": "prompt is required"}, 400)
            req_body = {
                "type": "text_to_model",
                "prompt": prompt[:600],
                "texture": False,  # keep the interactive loop fast; see report
            }
            if TRIPO_MODEL:
                req_body["model"] = TRIPO_MODEL
            result = _unwrap(tripo_request("POST", f"{TRIPO_BASE}/generation/text-to-model", req_body))
            task_id = result.get("task_id") or result.get("id")
            if not task_id:
                return self._send_json({"error": f"unexpected create response: {result}"}, 502)
            TASKS[task_id] = {"prompt": prompt, "created": time.time()}
            self._send_json({"taskId": task_id})
        except RuntimeError as e:
            self._send_json({"error": str(e)}, 500)
        except urllib.error.HTTPError as e:
            self._send_json({"error": f"Tripo3D API error ({e.code}): {e.read().decode('utf-8', 'ignore')}"}, 502)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_status(self, task_id):
        if not TASK_ID_RE.match(task_id):
            return self._send_json({"error": "invalid task id"}, 400)
        try:
            result = _unwrap(tripo_request("GET", f"{TRIPO_BASE}/tasks/{task_id}"))
            raw_status = str(result.get("status", "")).lower()
            progress = result.get("progress", 0)
            # normalize onto the same vocabulary the client expects
            if raw_status in ("success", "succeeded", "completed", "done"):
                status = "SUCCEEDED"
            elif raw_status in ("failed", "error", "cancelled", "canceled"):
                status = "FAILED"
            else:
                status = "IN_PROGRESS"
            out = {"status": status, "progress": progress, "_raw_status": raw_status}
            if status == "SUCCEEDED":
                output = result.get("output", {}) or {}
                glb_url = output.get("model_url") or output.get("pbr_model") or output.get("base_model")
                if not glb_url:
                    return self._send_json(
                        {"error": f"succeeded but no model URL found in response: {result}"}, 502
                    )
                TASKS.setdefault(task_id, {})["glbUrl"] = glb_url
                out["glbUrl"] = f"/api/model/{task_id}.glb"
            elif status == "FAILED":
                out["error"] = result.get("message") or result.get("error") or "generation failed"
            self._send_json(out)
        except RuntimeError as e:
            self._send_json({"error": str(e)}, 500)
        except urllib.error.HTTPError as e:
            self._send_json({"error": f"Tripo3D API error ({e.code}): {e.read().decode('utf-8', 'ignore')}"}, 502)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_model(self, filename):
        task_id = filename[:-len(".glb")] if filename.endswith(".glb") else filename
        if not TASK_ID_RE.match(task_id):
            return self._send_json({"error": "invalid task id"}, 400)
        cache_path = CACHE_DIR / f"{task_id}.glb"
        if not cache_path.exists():
            record = TASKS.get(task_id)
            glb_url = record.get("glbUrl") if record else None
            if not glb_url:
                # Fall back to asking Tripo3D directly in case our
                # in-memory record was lost (e.g. server restarted).
                try:
                    result = _unwrap(tripo_request("GET", f"{TRIPO_BASE}/tasks/{task_id}"))
                    output = result.get("output", {}) or {}
                    glb_url = output.get("model_url") or output.get("pbr_model") or output.get("base_model")
                except Exception as e:
                    return self._send_json({"error": str(e)}, 502)
            if not glb_url:
                return self._send_json({"error": "model not ready"}, 404)
            try:
                with urllib.request.urlopen(glb_url, timeout=60) as resp:
                    cache_path.write_bytes(resp.read())
            except Exception as e:
                return self._send_json({"error": f"failed to fetch model: {e}"}, 502)

        data = cache_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "model/gltf-binary")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=31536000")
        self.end_headers()
        self.wfile.write(data)

    # ---- static files ----------------------------------------------------

    def _serve_static(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            path = "/index.html"
        file_path = (PUBLIC_DIR / path.lstrip("/")).resolve()
        if PUBLIC_DIR not in file_path.parents and file_path != PUBLIC_DIR:
            return self._send_json({"error": "forbidden"}, 403)
        if not file_path.is_file():
            return self._send_json({"error": "not found"}, 404)

        content_type = "application/octet-stream"
        ext = file_path.suffix.lower()
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json",
            ".glb": "model/gltf-binary",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".svg": "image/svg+xml",
        }.get(ext, content_type)

        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    if not TRIPO_API_KEY:
        print(
            "WARNING: TRIPO_API_KEY is not set. Generation requests will "
            "fail until you run:\n  export TRIPO_API_KEY=your_key_here",
            file=sys.stderr,
        )
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"AR-Prompt3D running at http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
