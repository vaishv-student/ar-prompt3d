"""
Static file server + local Shap-E text-to-3D generator for AR-Prompt3D.

Generation runs entirely on this machine (Hugging Face `diffusers`'
ShapEPipeline, https://huggingface.co/openai/shap-e) rather than through a
hosted API. This was a deliberate pivot: both Meshy AI and Tripo3D's REST
APIs turned out to require prepaid credits with no usable free tier for a
fresh account, despite marketing claiming otherwise. Running the model
locally removes that dependency entirely -- no billing, no quota that can
run dry mid-demo or during grading -- at the cost of needing a one-time
~GB-scale model download and a few pip installs (diffusers, transformers,
accelerate, trimesh; torch is also required).

The client is unaware of this: it still talks to the same
/api/generate -> /api/status/{id} -> /api/model/{id}.glb contract as the
original hosted-API design, so no frontend code needed to change.

Usage:
    python3 server/app.py [port]

First call to /api/generate lazily loads the pipeline (downloads model
weights from Hugging Face Hub on first run) and runs generation in a
background thread; the client polls status as before.
"""

import json
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT / "public"
CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)

NUM_INFERENCE_STEPS = 32
GUIDANCE_SCALE = 15.0
FRAME_SIZE = 64
# Rough wall-clock estimate for this machine/config, used only to drive a
# smooth-looking progress bar (diffusers' ShapEPipeline doesn't expose a
# per-step callback). Measured ~25s for a single generation on this
# machine (Apple Silicon, MPS backend) once the pipeline is loaded.
ESTIMATED_SECONDS = 28

TASKS = {}
TASKS_LOCK = threading.Lock()

_pipeline = None
_pipeline_lock = threading.Lock()


def get_pipeline():
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            import torch
            from diffusers import ShapEPipeline

            device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
            sys.stderr.write(f"[shap-e] loading pipeline on {device} (first call only)...\n")
            pipe = ShapEPipeline.from_pretrained("openai/shap-e", torch_dtype=torch.float32)
            _pipeline = pipe.to(device)
            sys.stderr.write("[shap-e] pipeline ready\n")
        return _pipeline


def run_generation(task_id, prompt):
    import torch
    from diffusers.utils import export_to_ply
    import trimesh

    def set_task(**kwargs):
        with TASKS_LOCK:
            TASKS[task_id].update(kwargs)

    stop_ticker = threading.Event()

    def progress_ticker():
        start = time.time()
        while not stop_ticker.is_set():
            elapsed = time.time() - start
            pct = min(95, int(90 * elapsed / ESTIMATED_SECONDS))
            set_task(progress=pct)
            time.sleep(0.5)

    ticker = threading.Thread(target=progress_ticker, daemon=True)
    ticker.start()
    try:
        set_task(status="IN_PROGRESS", progress=1)
        pipe = get_pipeline()
        result = pipe(
            prompt,
            guidance_scale=GUIDANCE_SCALE,
            num_inference_steps=NUM_INFERENCE_STEPS,
            frame_size=FRAME_SIZE,
            output_type="mesh",
        )
        ply_path = CACHE_DIR / f"{task_id}.ply"
        export_to_ply(result.images[0], str(ply_path))
        mesh = trimesh.load(str(ply_path))
        # Shap-E's default mesh orientation renders from below; rotate to
        # something reasonable for a tabletop AR placement.
        rot = trimesh.transformations.rotation_matrix(-3.14159 / 2, [1, 0, 0])
        mesh = mesh.apply_transform(rot)
        glb_path = CACHE_DIR / f"{task_id}.glb"
        mesh.export(str(glb_path), file_type="glb")
        ply_path.unlink(missing_ok=True)
        set_task(status="SUCCEEDED", progress=100)
    except Exception as e:
        sys.stderr.write(f"[shap-e] generation failed for {task_id}: {e}\n")
        set_task(status="FAILED", error=str(e))
    finally:
        stop_ticker.set()


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
            task_id = uuid.uuid4().hex
            with TASKS_LOCK:
                TASKS[task_id] = {"prompt": prompt, "status": "PENDING", "progress": 0, "created": time.time()}
            threading.Thread(target=run_generation, args=(task_id, prompt[:600]), daemon=True).start()
            self._send_json({"taskId": task_id})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_status(self, task_id):
        if not TASK_ID_RE.match(task_id):
            return self._send_json({"error": "invalid task id"}, 400)
        with TASKS_LOCK:
            task = TASKS.get(task_id)
        if not task:
            return self._send_json({"error": "unknown task id"}, 404)
        out = {"status": task["status"], "progress": task["progress"]}
        if task["status"] == "SUCCEEDED":
            out["glbUrl"] = f"/api/model/{task_id}.glb"
        elif task["status"] == "FAILED":
            out["error"] = task.get("error", "generation failed")
        self._send_json(out)

    def _handle_model(self, filename):
        task_id = filename[:-len(".glb")] if filename.endswith(".glb") else filename
        if not TASK_ID_RE.match(task_id):
            return self._send_json({"error": "invalid task id"}, 400)
        glb_path = CACHE_DIR / f"{task_id}.glb"
        if not glb_path.is_file():
            return self._send_json({"error": "model not ready"}, 404)
        data = glb_path.read_bytes()
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
        }.get(ext, "application/octet-stream")

        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"AR-Prompt3D running at http://localhost:{port} (local Shap-E generation)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
