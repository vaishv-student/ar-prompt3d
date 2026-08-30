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
  server + a proxy in front of Meshy AI's text-to-3D API, so the API key
  never reaches the browser.

No Node/npm is required anywhere in this project.

## Setup

1. Get a Meshy API key at <https://www.meshy.ai/settings/api>.
2. Run:

   ```bash
   export MESHY_API_KEY=your_key_here
   python3 server/app.py 8000
   ```

3. Open <http://localhost:8000> in Chrome (voice input needs a
   Chromium-based browser; the rest works anywhere with WebGL).
4. Click **Start (camera preview mode)** and allow camera access.
5. Type or speak a prompt (e.g. "a small potted cactus"), click
   **Generate**, wait for it to finish (progress bar shows Meshy's
   reported percentage), then tap anywhere in the scene to place it.
6. Click a placed object in the list to select it, then drag to move it
   or scroll/pinch to resize it. Delete with the ✕ button.

On an ARCore-capable Android phone in Chrome, the start screen instead
offers **Enter AR**, using the real WebXR hit-test path.

## Open-source / third-party components

- [Three.js](https://threejs.org) (MIT) — rendering, `GLTFLoader`.
- [WebXR Device API](https://www.w3.org/TR/webxr/) — browser-native AR.
- [Meshy AI](https://www.meshy.ai) — hosted text-to-3D generation API
  (commercial, used via our own account; no model weights or proprietary
  code redistributed).

All AR interaction logic (placement, selection, drag, scale) and the
generation proxy server are original code written for this project.
