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
- **Server** (`server/app.py`): Python-standard-library-only static file
  server + a proxy in front of Tripo3D's text-to-3D API, so the API key
  never reaches the browser.

No Node/npm is required anywhere in this project.

## Setup

1. Get a Tripo3D API key: sign up at <https://platform.tripo3d.ai>, then
   open the **API Keys** page and create one. New accounts get 300 free
   credits (no card required), enough for many generations — each
   untextured generation costs 10 credits.
2. Run:

   ```bash
   export TRIPO_API_KEY=your_key_here
   python3 server/app.py 8000
   ```

3. Open <http://localhost:8000> in Chrome (voice input needs a
   Chromium-based browser; the rest works anywhere with WebGL).
4. Click **Start (camera preview mode)** and allow camera access.
5. Type or speak a prompt (e.g. "a small potted cactus"), click
   **Generate**, wait for it to finish (progress bar shows Tripo3D's
   reported percentage), then tap anywhere in the scene to place it.
6. Click a placed object in the list to select it, then drag to move it
   or scroll/pinch to resize it. Delete with the ✕ button.

On an ARCore-capable Android phone in Chrome, the start screen instead
offers **Enter AR**, using the real WebXR hit-test path.

If generation calls fail with a 502 and a message like "unexpected
response", check the server's stderr log — it prints Tripo3D's raw JSON
response for every call, since parts of Tripo3D's API reference are
JS-rendered and couldn't be fully confirmed ahead of time; the response
shape is usually enough to spot which field name needs adjusting in
`server/app.py`.

## Open-source / third-party components

- [Three.js](https://threejs.org) (MIT) — rendering, `GLTFLoader`.
- [WebXR Device API](https://www.w3.org/TR/webxr/) — browser-native AR.
- [Tripo3D](https://www.tripo3d.ai) — hosted text-to-3D generation API
  (commercial, used via our own account; no model weights or proprietary
  code redistributed).

All AR interaction logic (placement, selection, drag, scale) and the
generation proxy server are original code written for this project.
