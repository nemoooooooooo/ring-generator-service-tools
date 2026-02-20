// ───────────────────────────────────────────────────────────
// State
// ───────────────────────────────────────────────────────────
const state = {
  currentJobId: null,
  pollTimer: null,
  abortController: null,
  payloads: { request: {}, response: {}, result: {}, schema: {} },
  activeTab: "request",
  uploadedGlbFile: null,
};

// ───────────────────────────────────────────────────────────
// DOM refs
// ───────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const els = {
  glbPath: $("glbPath"),
  glbUpload: $("glbUpload"),
  glbFileInfo: $("glbFileInfo"),
  resolution: $("resolution"),
  sessionId: $("sessionId"),
  execMode: $("execMode"),
  pollMs: $("pollMs"),
  screenshotBtn: $("screenshotBtn"),
  cancelBtn: $("cancelBtn"),
  progressBar: $("progressBar"),
  statusBar: $("statusBar"),
  temporalBaseUrl: $("temporalBaseUrl"),
  temporalWorkflow: $("temporalWorkflow"),
  temporalAuth: $("temporalAuth"),
  temporalApiKey: $("temporalApiKey"),
  temporalOnBehalf: $("temporalOnBehalf"),
  temporalCard: $("temporalCard"),
  healthDot: $("healthDot"),
  healthText: $("healthText"),
  healthJson: $("healthJson"),
  refreshHealthBtn: $("refreshHealthBtn"),
  schemaBtn: $("schemaBtn"),
  screenshotGrid: $("screenshotGrid"),
  galleryCount: $("galleryCount"),
  payloadPre: $("payloadPre"),
  lightbox: $("lightbox"),
  lightboxImg: $("lightboxImg"),
  lightboxLabel: $("lightboxLabel"),
};

// ───────────────────────────────────────────────────────────
// Helpers
// ───────────────────────────────────────────────────────────
function setStatus(text, type = "") {
  els.statusBar.textContent = text;
  els.statusBar.className = "status-bar" + (type ? ` ${type}` : "");
}

function setProgress(pct) {
  els.progressBar.style.width = `${Math.min(100, Math.max(0, pct))}%`;
}

function showPayload(tab, data) {
  state.payloads[tab] = data;
  if (state.activeTab === tab) {
    els.payloadPre.textContent = JSON.stringify(data, null, 2);
  }
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function postJson(url, body, signal) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

// ───────────────────────────────────────────────────────────
// GLB file upload handling
// ───────────────────────────────────────────────────────────
els.glbUpload.addEventListener("change", () => {
  const file = els.glbUpload.files?.[0];
  if (file) {
    state.uploadedGlbFile = file;
    els.glbFileInfo.style.display = "block";
    els.glbFileInfo.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
  } else {
    state.uploadedGlbFile = null;
    els.glbFileInfo.style.display = "none";
  }
});

// ───────────────────────────────────────────────────────────
// Payload tab switching
// ───────────────────────────────────────────────────────────
document.querySelectorAll(".payload-tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".payload-tabs button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.activeTab = btn.dataset.tab;
    els.payloadPre.textContent = JSON.stringify(state.payloads[state.activeTab] || {}, null, 2);
  });
});

// ───────────────────────────────────────────────────────────
// Health
// ───────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    const res = await fetch("/health");
    const data = await res.json();
    els.healthDot.className = "health-dot ok";
    els.healthText.textContent = `OK — ${data.active_jobs || 0} active, queue ${data.queue_size || 0}`;
    els.healthJson.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    els.healthDot.className = "health-dot err";
    els.healthText.textContent = `Offline: ${err.message}`;
    els.healthJson.textContent = JSON.stringify({ error: err.message }, null, 2);
  }
}

els.refreshHealthBtn.addEventListener("click", checkHealth);

els.schemaBtn.addEventListener("click", async () => {
  try {
    const res = await fetch("/tool/schema");
    const data = await res.json();
    showPayload("schema", data);
    showPayload("response", data);
    state.activeTab = "schema";
    document.querySelectorAll(".payload-tabs button").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === "schema");
    });
    els.payloadPre.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    setStatus(`Schema fetch failed: ${err.message}`, "err");
  }
});

// ───────────────────────────────────────────────────────────
// Build request payload
// ───────────────────────────────────────────────────────────
async function buildPayload() {
  const glbPath = els.glbPath.value.trim();
  const hasUpload = !!state.uploadedGlbFile;

  if (!glbPath && !hasUpload) {
    throw new Error("Provide a GLB file path or upload a .glb file.");
  }

  const payload = {
    resolution: parseInt(els.resolution.value) || 1024,
  };

  const sessionId = els.sessionId.value.trim();
  if (sessionId) payload.session_id = sessionId;

  if (glbPath) {
    payload.glb_path = glbPath;
  }

  return payload;
}

async function uploadGlbFirst(signal) {
  if (!state.uploadedGlbFile) return null;

  const formData = new FormData();
  formData.append("file", state.uploadedGlbFile);

  setStatus("Uploading GLB file...", "working");
  const res = await fetch("/upload-glb", {
    method: "POST",
    body: formData,
    signal,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data?.detail || `Upload failed (${res.status})`);
  }
  return data.glb_path;
}

// ───────────────────────────────────────────────────────────
// Standalone sync (/run)
// ───────────────────────────────────────────────────────────
async function runSync(payload, signal) {
  setStatus("Sending to /run (sync, blocking)...", "working");
  setProgress(20);
  showPayload("request", payload);

  const res = await postJson("/run", payload, signal);
  showPayload("response", res.data);

  if (!res.ok) {
    throw new Error(res.data?.detail || res.data?.error || `HTTP ${res.status}`);
  }

  return res.data.result || res.data;
}

// ───────────────────────────────────────────────────────────
// Standalone async (/jobs)
// ───────────────────────────────────────────────────────────
let asyncStartTime = 0;

async function runAsync(payload, signal) {
  asyncStartTime = Date.now();
  setStatus("Submitting job to /jobs...", "working");
  setProgress(10);
  showPayload("request", payload);

  const startRes = await postJson("/jobs", payload, signal);
  showPayload("response", startRes.data);

  if (!startRes.ok) {
    throw new Error(startRes.data?.detail || startRes.data?.error || `HTTP ${startRes.status}`);
  }

  const jobId = startRes.data.job_id;
  state.currentJobId = jobId;
  setStatus(`Job queued: ${jobId}. Polling...`, "working");
  setProgress(15);

  const pollMs = parseInt(els.pollMs.value) || 3000;
  await sleep(500);

  while (true) {
    if (signal?.aborted) throw new Error("Cancelled");

    const pollRes = await fetch(`/jobs/${encodeURIComponent(jobId)}/result`, { signal });
    const pollData = await pollRes.json();
    showPayload("response", pollData);

    if (pollData.status === "succeeded") {
      return pollData.result;
    }
    if (pollData.status === "failed") {
      showPayload("result", pollData.result || {});
      throw new Error(pollData.error || "Job failed");
    }
    if (pollData.status === "cancelled") {
      throw new Error("Job was cancelled");
    }

    const progress = pollData.progress || 0;
    const elapsed = ((Date.now() - asyncStartTime) / 1000).toFixed(0);
    setProgress(15 + progress * 0.75);
    setStatus(`Job ${jobId}: ${pollData.detail || pollData.status} (${progress}%) — ${elapsed}s elapsed`, "working");

    await sleep(pollMs);
  }
}

// ───────────────────────────────────────────────────────────
// Temporal
// ───────────────────────────────────────────────────────────
function temporalHeaders() {
  const h = {};
  if (els.temporalAuth.value.trim()) h.Authorization = els.temporalAuth.value.trim();
  if (els.temporalApiKey.value.trim()) h["X-API-Key"] = els.temporalApiKey.value.trim();
  if (els.temporalOnBehalf.value.trim()) h["X-On-Behalf-Of"] = els.temporalOnBehalf.value.trim();
  return h;
}

async function runTemporal(payload, signal) {
  const baseUrl = els.temporalBaseUrl.value.trim();
  const workflowName = els.temporalWorkflow.value.trim();
  if (!baseUrl || !workflowName) throw new Error("Temporal Base URL and Workflow Name are required.");

  const headers = temporalHeaders();
  const temporalPayload = {
    payload,
    return_nodes: ["ring-screenshot"],
  };

  setStatus("Starting Temporal workflow...", "working");
  setProgress(10);

  const fullRequest = { temporal_base_url: baseUrl, workflow_name: workflowName, ...temporalPayload, headers };
  showPayload("request", fullRequest);

  const body = JSON.stringify(temporalPayload);
  const startHeaders = { "Content-Type": "application/json", ...headers };
  const startRes = await fetch(`${baseUrl}/run/${workflowName}`, {
    method: "POST",
    headers: startHeaders,
    body,
    signal,
  });
  const startData = await startRes.json().catch(() => ({}));
  showPayload("response", startData);

  if (!startRes.ok) {
    throw new Error(startData?.detail || `Temporal start failed (${startRes.status})`);
  }

  const workflowId = startData.workflow_id;
  setStatus(`Temporal workflow started: ${workflowId}. Polling...`, "working");
  setProgress(20);

  const pollMs = parseInt(els.pollMs.value) || 3000;

  while (true) {
    if (signal?.aborted) throw new Error("Cancelled");

    const statusRes = await fetch(`${baseUrl}/status/${workflowId}`, {
      headers: { ...headers },
      signal,
    });
    const statusData = await statusRes.json().catch(() => ({}));

    const progressState = statusData?.progress?.state;
    const completed = statusData?.progress?.completed_nodes || 0;
    const total = statusData?.progress?.total_nodes || 1;
    setProgress(20 + (completed / total) * 60);
    setStatus(`Temporal: ${progressState || "running"} (${completed}/${total} nodes)`, "working");

    if (progressState === "completed" || progressState === "failed") break;
    await sleep(pollMs);
  }

  setStatus("Fetching Temporal result...", "working");
  setProgress(85);

  const resultRes = await fetch(`${baseUrl}/result/${workflowId}`, {
    headers: { ...headers },
    signal,
  });
  const resultData = await resultRes.json().catch(() => ({}));
  showPayload("response", resultData);

  if (!resultRes.ok) {
    throw new Error(resultData?.detail || `Result fetch failed (${resultRes.status})`);
  }

  const screenshotResult = findScreenshotResult(resultData);
  if (!screenshotResult) throw new Error("No screenshot result found in Temporal response");
  return screenshotResult;
}

function findScreenshotResult(node) {
  if (!node || typeof node !== "object") return null;
  if (Array.isArray(node.screenshots)) return node;
  if (Array.isArray(node)) {
    for (const item of node) {
      const found = findScreenshotResult(item);
      if (found) return found;
    }
    return null;
  }
  for (const value of Object.values(node)) {
    const found = findScreenshotResult(value);
    if (found) return found;
  }
  return null;
}

// ───────────────────────────────────────────────────────────
// Screenshot gallery rendering
// ───────────────────────────────────────────────────────────
function renderGallery(screenshots) {
  els.screenshotGrid.innerHTML = "";

  if (!screenshots || screenshots.length === 0) {
    els.screenshotGrid.innerHTML = '<div class="screenshot-placeholder">No screenshots returned.</div>';
    els.galleryCount.textContent = "";
    return;
  }

  els.galleryCount.textContent = `(${screenshots.length} views)`;

  screenshots.forEach((shot, idx) => {
    const cell = document.createElement("div");
    cell.className = "screenshot-cell";
    cell.title = `Click to enlarge — ${shot.name}`;

    const img = document.createElement("img");
    img.src = shot.data_uri;
    img.alt = shot.name;
    img.loading = "lazy";

    const label = document.createElement("div");
    label.className = "label";
    label.textContent = shot.name;

    cell.appendChild(img);
    cell.appendChild(label);

    cell.addEventListener("click", () => openLightbox(shot.data_uri, shot.name));

    els.screenshotGrid.appendChild(cell);
  });
}

// ───────────────────────────────────────────────────────────
// Lightbox
// ───────────────────────────────────────────────────────────
function openLightbox(src, label) {
  els.lightboxImg.src = src;
  els.lightboxLabel.textContent = label;
  els.lightbox.classList.add("open");
}

els.lightbox.addEventListener("click", () => {
  els.lightbox.classList.remove("open");
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") els.lightbox.classList.remove("open");
});

// ───────────────────────────────────────────────────────────
// Main screenshot handler
// ───────────────────────────────────────────────────────────
async function runScreenshots() {
  const controller = new AbortController();
  state.abortController = controller;

  els.screenshotBtn.disabled = true;
  els.cancelBtn.disabled = false;
  setProgress(0);

  try {
    // If user uploaded a file and no path is typed, upload first
    if (state.uploadedGlbFile && !els.glbPath.value.trim()) {
      const uploadedPath = await uploadGlbFirst(controller.signal);
      if (uploadedPath) {
        els.glbPath.value = uploadedPath;
      }
    }

    const payload = await buildPayload();
    const mode = els.execMode.value;

    let result;
    if (mode === "standalone-sync") {
      result = await runSync(payload, controller.signal);
    } else if (mode === "standalone-async") {
      result = await runAsync(payload, controller.signal);
    } else {
      result = await runTemporal(payload, controller.signal);
    }

    showPayload("result", result);
    setProgress(95);

    renderGallery(result.screenshots || []);

    setProgress(100);

    const numAngles = result.num_angles || result.screenshots?.length || 0;
    const renderElapsed = result.render_elapsed != null ? result.render_elapsed.toFixed(1) : "?";
    const res = result.resolution || "?";

    setStatus(
      `Done! ${numAngles} screenshots @ ${res}px | render time: ${renderElapsed}s | glb: ${result.glb_path || "n/a"}`,
      "ok"
    );
  } catch (err) {
    if (err.name === "AbortError" || err.message === "Cancelled") {
      setStatus("Cancelled by user", "err");
    } else {
      setStatus(`Error: ${err.message}`, "err");
    }
    setProgress(0);
  } finally {
    els.screenshotBtn.disabled = false;
    els.cancelBtn.disabled = true;
    state.abortController = null;
    state.currentJobId = null;
  }
}

// ───────────────────────────────────────────────────────────
// Cancel
// ───────────────────────────────────────────────────────────
async function cancelJob() {
  if (state.abortController) {
    state.abortController.abort();
  }
  if (state.currentJobId) {
    try {
      await fetch(`/jobs/${state.currentJobId}`, { method: "DELETE" });
    } catch (_) { /* best effort */ }
  }
}

// ───────────────────────────────────────────────────────────
// Wire events
// ───────────────────────────────────────────────────────────
els.screenshotBtn.addEventListener("click", runScreenshots);
els.cancelBtn.addEventListener("click", cancelJob);

// ───────────────────────────────────────────────────────────
// Init
// ───────────────────────────────────────────────────────────
checkHealth();
setInterval(checkHealth, 30000);
showPayload("request", { hint: "Fill in a GLB path and click Render Screenshots to see the request payload here." });

// Fetch and show schema on load
(async () => {
  try {
    const res = await fetch("/tool/schema");
    const data = await res.json();
    showPayload("schema", data);
  } catch (_) { /* schema load is non-critical */ }
})();
