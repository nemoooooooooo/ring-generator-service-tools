// ───────────────────────────────────────────────────────────
// State
// ───────────────────────────────────────────────────────────
const state = {
  currentJobId: null,
  pollTimer: null,
  abortController: null,
  payloads: { request: {}, response: {}, result: {}, schema: {} },
  activeTab: "request",
  screenshotDataUris: [],
};

// ───────────────────────────────────────────────────────────
// DOM refs
// ───────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const els = {
  screenshots: $("screenshots"),
  loadScreenshotsBtn: $("loadScreenshotsBtn"),
  screenshotsFileInput: $("screenshotsFileInput"),
  loadFromServiceBtn: $("loadFromServiceBtn"),
  screenshotCount: $("screenshotCount"),
  code: $("code"),
  loadCodeBtn: $("loadCodeBtn"),
  codeFileInput: $("codeFileInput"),
  codeLength: $("codeLength"),
  userPrompt: $("userPrompt"),
  llmName: $("llmName"),
  sessionId: $("sessionId"),
  execMode: $("execMode"),
  pollMs: $("pollMs"),
  validateBtn: $("validateBtn"),
  cancelBtn: $("cancelBtn"),
  progressBar: $("progressBar"),
  statusBar: $("statusBar"),
  screenshotterUrl: $("screenshotterUrl"),
  ssGlbPath: $("ssGlbPath"),
  fetchScreenshotsBtn: $("fetchScreenshotsBtn"),
  ssStatus: $("ssStatus"),
  temporalBaseUrl: $("temporalBaseUrl"),
  temporalWorkflow: $("temporalWorkflow"),
  temporalAuth: $("temporalAuth"),
  temporalApiKey: $("temporalApiKey"),
  temporalOnBehalf: $("temporalOnBehalf"),
  temporalCard: $("temporalCard"),
  screenshotterCard: $("screenshotterCard"),
  healthDot: $("healthDot"),
  healthText: $("healthText"),
  healthJson: $("healthJson"),
  refreshHealthBtn: $("refreshHealthBtn"),
  schemaBtn: $("schemaBtn"),
  resultPanel: $("resultPanel"),
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

function truncateDataUri(uri, maxLen = 80) {
  if (!uri || uri.length <= maxLen) return uri;
  return uri.substring(0, maxLen) + "...";
}

function buildPayloadForDisplay(payload) {
  const display = { ...payload };
  if (display.screenshots && Array.isArray(display.screenshots)) {
    display.screenshots = display.screenshots.map((s, i) =>
      `[${i}] ${truncateDataUri(s)}`
    );
    display._screenshot_count = payload.screenshots.length;
  }
  return display;
}

// ───────────────────────────────────────────────────────────
// Screenshot count & code length live update
// ───────────────────────────────────────────────────────────
function updateScreenshotCount() {
  const count = state.screenshotDataUris.length;
  els.screenshotCount.textContent = `${count} screenshot${count !== 1 ? "s" : ""}`;
}

els.code.addEventListener("input", () => {
  els.codeLength.textContent = `${els.code.value.length} chars`;
});

// ───────────────────────────────────────────────────────────
// Load screenshots from JSON file
// ───────────────────────────────────────────────────────────
els.loadScreenshotsBtn.addEventListener("click", () => {
  els.screenshotsFileInput.click();
});

els.screenshotsFileInput.addEventListener("change", () => {
  const file = els.screenshotsFileInput.files?.[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const data = JSON.parse(e.target.result);
      let uris = [];

      if (Array.isArray(data)) {
        uris = data.filter((s) => typeof s === "string");
      } else if (data.screenshots && Array.isArray(data.screenshots)) {
        uris = data.screenshots
          .map((s) => (typeof s === "string" ? s : s.data_uri))
          .filter(Boolean);
      }

      if (uris.length === 0) {
        setStatus("No valid screenshot data URIs found in file.", "err");
        return;
      }

      state.screenshotDataUris = uris;
      els.screenshots.value = JSON.stringify(uris.map((u) => truncateDataUri(u, 60)));
      updateScreenshotCount();
      setStatus(`Loaded ${uris.length} screenshots from file.`, "ok");
    } catch (err) {
      setStatus(`Failed to parse JSON: ${err.message}`, "err");
    }
  };
  reader.readAsText(file);
});

// ───────────────────────────────────────────────────────────
// Load code from .py file
// ───────────────────────────────────────────────────────────
els.loadCodeBtn.addEventListener("click", () => {
  els.codeFileInput.click();
});

els.codeFileInput.addEventListener("change", () => {
  const file = els.codeFileInput.files?.[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (e) => {
    els.code.value = e.target.result;
    els.codeLength.textContent = `${els.code.value.length} chars`;
    setStatus(`Loaded code from ${file.name}`, "ok");
  };
  reader.readAsText(file);
});

// ───────────────────────────────────────────────────────────
// Fetch screenshots from screenshotter service
// ───────────────────────────────────────────────────────────
els.fetchScreenshotsBtn.addEventListener("click", async () => {
  const baseUrl = els.screenshotterUrl.value.trim();
  const glbPath = els.ssGlbPath.value.trim();

  if (!baseUrl || !glbPath) {
    els.ssStatus.textContent = "Provide both screenshotter URL and GLB path.";
    return;
  }

  els.ssStatus.textContent = "Submitting screenshot job...";
  els.fetchScreenshotsBtn.disabled = true;

  try {
    const payload = { glb_path: glbPath, resolution: 1024 };
    const startRes = await postJson(`${baseUrl}/jobs`, payload);

    if (!startRes.ok) {
      throw new Error(startRes.data?.detail || `HTTP ${startRes.status}`);
    }

    const jobId = startRes.data.job_id;
    els.ssStatus.textContent = `Job ${jobId} — polling...`;

    while (true) {
      await sleep(2000);
      const pollRes = await fetch(`${baseUrl}/jobs/${jobId}/result`);
      const pollData = await pollRes.json();

      if (pollData.status === "succeeded") {
        const screenshots = pollData.result?.screenshots || [];
        const uris = screenshots.map((s) => s.data_uri).filter(Boolean);

        state.screenshotDataUris = uris;
        els.screenshots.value = JSON.stringify(uris.map((u) => truncateDataUri(u, 60)));
        updateScreenshotCount();
        els.ssStatus.textContent = `Fetched ${uris.length} screenshots.`;
        break;
      }
      if (pollData.status === "failed") {
        throw new Error(pollData.error || "Screenshot job failed");
      }
      if (pollData.status === "cancelled") {
        throw new Error("Screenshot job cancelled");
      }

      els.ssStatus.textContent = `Job ${jobId}: ${pollData.detail || pollData.status} (${pollData.progress || 0}%)`;
    }
  } catch (err) {
    els.ssStatus.textContent = `Error: ${err.message}`;
  } finally {
    els.fetchScreenshotsBtn.disabled = false;
  }
});

// ───────────────────────────────────────────────────────────
// Also load from screenshotter via the "Load from Service" button
// ───────────────────────────────────────────────────────────
els.loadFromServiceBtn.addEventListener("click", () => {
  els.screenshotterCard.scrollIntoView({ behavior: "smooth", block: "center" });
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
function getScreenshots() {
  if (state.screenshotDataUris.length > 0) {
    return state.screenshotDataUris;
  }
  const raw = els.screenshots.value.trim();
  if (!raw) return [];

  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.filter((s) => typeof s === "string");
  } catch (_) {}

  return [];
}

function buildPayload() {
  const screenshots = getScreenshots();
  const code = els.code.value.trim();
  const userPrompt = els.userPrompt.value.trim();
  const llmName = els.llmName.value;

  if (screenshots.length === 0) {
    throw new Error("Provide at least one screenshot (data URI).");
  }
  if (!code) {
    throw new Error("Blender code is required.");
  }

  const payload = {
    screenshots,
    code,
    user_prompt: userPrompt,
    llm_name: llmName,
  };

  const sessionId = els.sessionId.value.trim();
  if (sessionId) payload.session_id = sessionId;

  return payload;
}

// ───────────────────────────────────────────────────────────
// Standalone sync (/run)
// ───────────────────────────────────────────────────────────
async function runSync(payload, signal) {
  setStatus("Sending to /run (sync, blocking)...", "working");
  setProgress(20);
  showPayload("request", buildPayloadForDisplay(payload));

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
  showPayload("request", buildPayloadForDisplay(payload));

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
    return_nodes: ["ring-validate"],
  };

  setStatus("Starting Temporal workflow...", "working");
  setProgress(10);

  const fullRequest = { temporal_base_url: baseUrl, workflow_name: workflowName, ...temporalPayload, headers };
  showPayload("request", buildPayloadForDisplay(fullRequest));

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

  const validateResult = findValidateResult(resultData);
  if (!validateResult) throw new Error("No validation result found in Temporal response");
  return validateResult;
}

function findValidateResult(node) {
  if (!node || typeof node !== "object") return null;
  if (typeof node.is_valid === "boolean") return node;
  if (Array.isArray(node)) {
    for (const item of node) {
      const found = findValidateResult(item);
      if (found) return found;
    }
    return null;
  }
  for (const value of Object.values(node)) {
    const found = findValidateResult(value);
    if (found) return found;
  }
  return null;
}

// ───────────────────────────────────────────────────────────
// Render validation result
// ───────────────────────────────────────────────────────────
function renderResult(result, inputScreenshots) {
  const panel = els.resultPanel;
  panel.innerHTML = "";

  // Verdict banner
  const banner = document.createElement("div");
  banner.className = `result-banner ${result.is_valid ? "valid" : "invalid"}`;

  const verdictEl = document.createElement("div");
  verdictEl.className = `verdict ${result.is_valid ? "valid" : "invalid"}`;
  verdictEl.textContent = result.is_valid ? "VALID" : "INVALID";

  const msgEl = document.createElement("div");
  msgEl.className = "msg";
  msgEl.textContent = result.message || "";

  banner.appendChild(verdictEl);
  banner.appendChild(msgEl);
  panel.appendChild(banner);

  // Details grid
  const grid = document.createElement("div");
  grid.className = "result-detail-grid";

  const details = [
    { label: "Regenerated", value: result.regenerated ? "Yes" : "No", cls: result.regenerated ? "yellow" : "green" },
    { label: "LLM Cost", value: `$${(result.cost || 0).toFixed(4)}`, cls: "yellow" },
    { label: "Tokens In", value: String(result.tokens?.input_tokens || 0), cls: "blue" },
    { label: "Tokens Out", value: String(result.tokens?.output_tokens || 0), cls: "blue" },
    { label: "LLM Used", value: result.llm_used || "—", cls: "blue" },
    { label: "GLB Path", value: result.glb_path || "—", cls: result.glb_path ? "green" : "" },
  ];

  details.forEach((d) => {
    const card = document.createElement("div");
    card.className = "detail-card";
    card.innerHTML = `<div class="label">${d.label}</div><div class="value ${d.cls}">${d.value}</div>`;
    grid.appendChild(card);
  });

  panel.appendChild(grid);

  // Input screenshots preview
  if (inputScreenshots && inputScreenshots.length > 0) {
    const ssSection = document.createElement("div");
    ssSection.innerHTML = '<h3 style="font-size:0.82rem;color:var(--accent);margin-bottom:6px">Input Screenshots</h3>';

    const ssGrid = document.createElement("div");
    ssGrid.className = "screenshot-preview-grid";

    inputScreenshots.forEach((uri, idx) => {
      const thumb = document.createElement("div");
      thumb.className = "screenshot-thumb";
      thumb.title = `Click to enlarge — Screenshot ${idx + 1}`;

      const img = document.createElement("img");
      img.src = uri;
      img.alt = `Screenshot ${idx + 1}`;
      img.loading = "lazy";

      const label = document.createElement("div");
      label.className = "thumb-label";
      label.textContent = `#${idx + 1}`;

      thumb.appendChild(img);
      thumb.appendChild(label);
      thumb.addEventListener("click", () => openLightbox(uri, `Input Screenshot ${idx + 1}`));
      ssGrid.appendChild(thumb);
    });

    ssSection.appendChild(ssGrid);
    panel.appendChild(ssSection);
  }

  // Corrected code
  if (result.corrected_code) {
    const codeSection = document.createElement("div");
    codeSection.className = "corrected-code-section";
    codeSection.innerHTML = `<h3>Corrected Code</h3><pre>${escapeHtml(result.corrected_code)}</pre>`;
    panel.appendChild(codeSection);
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
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
// Main validation handler
// ───────────────────────────────────────────────────────────
async function runValidation() {
  const controller = new AbortController();
  state.abortController = controller;

  els.validateBtn.disabled = true;
  els.cancelBtn.disabled = false;
  setProgress(0);
  els.resultPanel.innerHTML = '<div class="result-placeholder">Running validation...</div>';

  try {
    const payload = buildPayload();
    const mode = els.execMode.value;
    const inputScreenshots = [...payload.screenshots];

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

    renderResult(result, inputScreenshots);

    setProgress(100);

    const verdict = result.is_valid ? "VALID" : "INVALID";
    const regen = result.regenerated ? " (regenerated)" : "";
    setStatus(
      `Done! Verdict: ${verdict}${regen} | cost: $${(result.cost || 0).toFixed(4)} | LLM: ${result.llm_used || "?"}`,
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
    els.validateBtn.disabled = false;
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
els.validateBtn.addEventListener("click", runValidation);
els.cancelBtn.addEventListener("click", cancelJob);

// ───────────────────────────────────────────────────────────
// Init
// ───────────────────────────────────────────────────────────
checkHealth();
setInterval(checkHealth, 30000);
showPayload("request", { hint: "Fill in screenshots + code and click Validate Ring to see the request payload here." });

(async () => {
  try {
    const res = await fetch("/tool/schema");
    const data = await res.json();
    showPayload("schema", data);
  } catch (_) { /* non-critical */ }
})();
