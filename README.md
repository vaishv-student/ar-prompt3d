# AR-Prompt3D

Extended Reality 2025-2026 — Supplemental Project, Topic 2.

An AR web app: describe an object by voice or text, and an AI model
generates it on the fly and places it in your real physical space.

## How it works

- **Client** (`public/`): vanilla JS + Three.js (loaded from a CDN via an
  import map — no `npm install` needed). Two presentation paths behind a
  shared placement/interaction API:
  - `webcamScene.js` — webcam-passthrough fallback (used for development
    and the demo, since no AR-capable device was available). No SLAM
    tracking; objects are placed via a fixed-depth ray-cast from the
    pointer and stay in screen-relative space.
  - `xrScene.js` — real WebXR `immersive-ar` hit-test path for devices
    that support it (untested on hardware, but standards-compliant).
- **Server** (`server/app.py`): Python static file server whose
  `/api/generate` route runs **Shap-E** (OpenAI's text-to-3D model, via
  Hugging Face `diffusers`) locally, in a background thread, rather than
  calling a hosted API.

Only the server needs Python packages (see below); the client itself
needs no Node/npm and no build step.

### Why local generation instead of a hosted API

Both Meshy AI's and Tripo3D's REST APIs were tried first. Both require
prepaid credits with no usable free tier for a fresh account, despite
marketing claiming otherwise (Tripo3D's dashboard showed a $0 balance and
"no card bound" even though sign-up is advertised as giving free credits).
Running Shap-E locally sidesteps that entirely: no billing, and no risk of
a demo failing later because a free-tier quota ran out. The proxy's
`/api/generate` → `/api/status/{id}` → `/api/model/{id}.glb` contract is
unchanged from the original hosted-API design, so the client needed zero
changes for this pivot.

## Setup

1. Install the Python dependencies (first run also downloads the Shap-E
   model weights from Hugging Face Hub, a few hundred MB, cached after
   that):

   ```bash
   pip3 install --user -r server/requirements.txt
   ```

2. Run:

   ```bash
   python3 server/app.py 8000
   ```

3. Open <http://localhost:8000> in Chrome (voice input needs a
   Chromium-based browser; the rest works anywhere with WebGL).
4. Click **Start (camera preview mode)** and allow camera access.
5. Type or speak a prompt (e.g. "a small potted cactus"), click
   **Generate**, wait for it to finish (progress bar shown while Shap-E
   runs), then tap anywhere in the scene to place it.
6. Click a placed object in the list to select it, then drag to move it
   or scroll/pinch to resize it. Delete with the ✕ button.

On an ARCore-capable Android phone in Chrome, the start screen instead
offers **Enter AR**, using the real WebXR hit-test path.

## Open-source / third-party components

- [Three.js](https://threejs.org) (MIT) — rendering, `GLTFLoader`.
- [WebXR Device API](https://www.w3.org/TR/webxr/) — browser-native AR.
- [Shap-E](https://github.com/openai/shap-e) (OpenAI, MIT) via
  [Hugging Face `diffusers`](https://huggingface.co/docs/diffusers) —
  text-to-3D generation, run locally; pretrained weights from
  [`openai/shap-e`](https://huggingface.co/openai/shap-e) on the Hub.
- [trimesh](https://trimesh.org) (MIT) — PLY→GLB mesh conversion.

All AR interaction logic (placement, selection, drag, scale), the
generation server, and the threaded task/progress/caching layer around
Shap-E are original code written for this project.
