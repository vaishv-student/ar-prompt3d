import { generateModel } from "./generate.js";
import { createVoiceInput, isVoiceSupported } from "./voice.js";
import { createWebcamScene } from "./webcamScene.js";
import { createXRScene, isXRSupported } from "./xrScene.js";

const els = {
  startScreen: document.getElementById("start-screen"),
  startWebcamBtn: document.getElementById("start-webcam-btn"),
  startArBtn: document.getElementById("start-ar-btn"),
  arSupportNote: document.getElementById("ar-support-note"),
  errorBanner: document.getElementById("error-banner"),
  uiOverlay: document.getElementById("ui-overlay"),
  modeLabel: document.getElementById("mode-label"),
  progressPanel: document.getElementById("progress-panel"),
  progressFill: document.getElementById("progress-fill"),
  progressText: document.getElementById("progress-text"),
  objectList: document.getElementById("object-list"),
  promptInput: document.getElementById("prompt-input"),
  micBtn: document.getElementById("mic-btn"),
  generateBtn: document.getElementById("generate-btn"),
  placementHint: document.getElementById("placement-hint"),
  video: document.getElementById("camera-feed"),
  canvas: document.getElementById("three-canvas"),
};

let activeScene = null; // webcam-scene or xr-scene handle
let generating = false;

function showError(message) {
  els.errorBanner.textContent = message;
  els.errorBanner.hidden = false;
  setTimeout(() => { els.errorBanner.hidden = true; }, 6000);
}

function renderObjectList(list) {
  els.objectList.innerHTML = "";
  for (const obj of list) {
    const li = document.createElement("li");
    if (obj.selected) li.classList.add("selected");
    const span = document.createElement("span");
    span.textContent = obj.label;
    li.appendChild(span);
    li.addEventListener("click", () => activeScene?.selectObject?.(obj.id));

    const del = document.createElement("button");
    del.textContent = "✕";
    del.title = "Remove";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      activeScene.deleteObject(obj.id);
    });
    li.appendChild(del);
    els.objectList.appendChild(li);
  }
}

function setPlacing(active) {
  els.placementHint.hidden = !active;
}

async function boot() {
  const xrOk = await isXRSupported();
  if (xrOk) {
    els.startArBtn.hidden = false;
    els.arSupportNote.textContent = "This device supports WebXR AR.";
  } else {
    els.arSupportNote.textContent =
      "No AR-capable device detected -- using camera preview mode (see README).";
  }

  els.startWebcamBtn.addEventListener("click", async () => {
    try {
      const scene = createWebcamScene({
        videoEl: els.video,
        canvasEl: els.canvas,
        onObjectsChanged: renderObjectList,
        onPlacingChange: setPlacing,
      });
      await scene.start();
      activeScene = scene;
      els.modeLabel.textContent = "Camera preview mode (no SLAM tracking)";
      enterAppUI();
    } catch (err) {
      showError(`Could not start camera: ${err.message}`);
    }
  });

  els.startArBtn.addEventListener("click", async () => {
    try {
      const scene = createXRScene({
        canvasEl: els.canvas,
        onObjectsChanged: renderObjectList,
        onPlacingChange: setPlacing,
      });
      await scene.enter();
      activeScene = scene;
      els.modeLabel.textContent = "WebXR AR (hit-test)";
      enterAppUI();
    } catch (err) {
      showError(`Could not start AR session: ${err.message}`);
    }
  });

  if (isVoiceSupported()) {
    const recognition = createVoiceInput({
      onStart: () => els.micBtn.classList.add("listening"),
      onEnd: () => els.micBtn.classList.remove("listening"),
      onError: (e) => { els.micBtn.classList.remove("listening"); showError(`Voice input error: ${e}`); },
      onResult: (transcript) => { els.promptInput.value = transcript; },
    });
    els.micBtn.addEventListener("click", () => recognition.start());
  } else {
    els.micBtn.disabled = true;
    els.micBtn.title = "Voice input not supported in this browser";
  }

  els.generateBtn.addEventListener("click", handleGenerate);
  els.promptInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleGenerate();
  });
}

function enterAppUI() {
  els.startScreen.hidden = true;
  els.uiOverlay.hidden = false;
}

async function handleGenerate() {
  if (generating || !activeScene) return;
  const prompt = els.promptInput.value.trim();
  if (!prompt) return;

  generating = true;
  els.generateBtn.disabled = true;
  els.progressPanel.hidden = false;
  els.progressFill.style.width = "0%";
  els.progressText.textContent = "Starting generation…";

  try {
    const glbUrl = await generateModel(prompt, (progress, status) => {
      els.progressFill.style.width = `${progress}%`;
      els.progressText.textContent = `${status?.toLowerCase() ?? "generating"}… ${progress}%`;
    });
    els.progressPanel.hidden = true;
    await activeScene.beginPlacement(glbUrl, prompt);
    els.promptInput.value = "";
  } catch (err) {
    showError(`Generation failed: ${err.message}`);
    els.progressPanel.hidden = true;
  } finally {
    generating = false;
    els.generateBtn.disabled = false;
  }
}

boot().catch((err) => showError(`Startup error: ${err.message}`));
