"""
Static file server + Meshy text-to-3D proxy for AR-Prompt3D.

Runs with the Python 3 standard library only (no npm/node, no pip installs
needed). The proxy exists so the Meshy API key never reaches the browser and
so the client doesn't have to deal with Meshy's CORS/signed-URL rules
directly.

Usage:
    export MESHY_API_KEY="your_key_here"
    python3 server/app.py [port]
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT / "public"
CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)

MESHY_API_KEY = os.environ.get("MESHY_API_KEY", "")
MESHY_BASE = "https://api.meshy.ai/openapi/v2/text-to-3d"

# In-memory record of tasks we've created, so /api/model/<id>.glb knows
# where to fetch the signed asset from without re-polling Meshy.
TASKS = {}


def meshy_request(method, url, body=None):
    if not MESHY_API_KEY:
        raise RuntimeError(
            "MESHY_API_KEY is not set. Get a key at "
            "https://www.meshy.ai/settings/api and run:\n"
            "  export MESHY_API_KEY=your_key_here"
        )
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {MESHY_API_KEY}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
            result = meshy_request("POST", MESHY_BASE, {
                "mode": "preview",
                "prompt": prompt[:600],
                "ai_model": "latest",
                "target_polycount": 15000,
                "should_remesh": True,
            })
            task_id = result["result"]
            TASKS[task_id] = {"prompt": prompt, "created": time.time()}
            self._send_json({"taskId": task_id})
        except RuntimeError as e:
            self._send_json({"error": str(e)}, 500)
        except urllib.error.HTTPError as e:
            self._send_json({"error": f"Meshy API error: {e.read().decode('utf-8', 'ignore')}"}, 502)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_status(self, task_id):
        try:
            result = meshy_request("GET", f"{MESHY_BASE}/{task_id}")
            status = result.get("status")
            out = {
                "status": status,
                "progress": result.get("progress", 0),
            }
            if status == "SUCCEEDED":
                glb_url = result.get("model_urls", {}).get("glb")
                TASKS.setdefault(task_id, {})["glbUrl"] = glb_url
                out["glbUrl"] = f"/api/model/{task_id}.glb"
            elif status == "FAILED":
                out["error"] = result.get("task_error", {}).get("message", "generation failed")
            self._send_json(out)
        except RuntimeError as e:
            self._send_json({"error": str(e)}, 500)
        except urllib.error.HTTPError as e:
            self._send_json({"error": f"Meshy API error: {e.read().decode('utf-8', 'ignore')}"}, 502)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_model(self, filename):
        task_id = filename[:-len(".glb")] if filename.endswith(".glb") else filename
        cache_path = CACHE_DIR / f"{task_id}.glb"
        if not cache_path.exists():
            record = TASKS.get(task_id)
            glb_url = record.get("glbUrl") if record else None
            if not glb_url:
                # Fall back to asking Meshy directly in case our in-memory
                # record was lost (e.g. server restarted).
                try:
                    result = meshy_request("GET", f"{MESHY_BASE}/{task_id}")
                    glb_url = result.get("model_urls", {}).get("glb")
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
    if not MESHY_API_KEY:
        print(
            "WARNING: MESHY_API_KEY is not set. Generation requests will "
            "fail until you run:\n  export MESHY_API_KEY=your_key_here",
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
