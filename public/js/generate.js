/**
 * Client for the local /api/* proxy in front of Meshy's text-to-3D API.
 * Handles task creation and polling; resolves with a same-origin GLB URL.
 */

export async function generateModel(prompt, onProgress) {
  const createRes = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  const createBody = await createRes.json();
  if (!createRes.ok) throw new Error(createBody.error || "generation request failed");

  const taskId = createBody.taskId;
  const started = Date.now();
  const timeoutMs = 5 * 60 * 1000;

  while (true) {
    if (Date.now() - started > timeoutMs) {
      throw new Error("generation timed out");
    }
    await sleep(2000);
    const statusRes = await fetch(`/api/status/${taskId}`);
    const status = await statusRes.json();
    if (!statusRes.ok) throw new Error(status.error || "status check failed");

    if (onProgress) onProgress(status.progress ?? 0, status.status);

    if (status.status === "SUCCEEDED") {
      return status.glbUrl;
    }
    if (status.status === "FAILED" || status.status === "CANCELED") {
      throw new Error(status.error || `generation ${status.status.toLowerCase()}`);
    }
    // else PENDING / IN_PROGRESS -> keep polling
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
