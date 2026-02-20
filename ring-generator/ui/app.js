import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

// ───────────────────────────────────────────────────────────
// State
// ───────────────────────────────────────────────────────────
const state = {
  currentJobId: null,
  pollTimer: null,
  abortController: null,
  payloads: { request: {}, response: {}, result: {}, cost: {} },
  activeTab: "request",
};

// ───────────────────────────────────────────────────────────
// DOM refs
// ───────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const els = {
  prompt: $("prompt"),
  imageInput: $("imageInput"),
  imgPreview: $("imgPreview"),
  maxRetries: $("maxRetries"),
  maxCost: $("maxCost"),
  execMode: $("execMode"),
  pollMs: $("pollMs"),
  generateBtn: $("generateBtn"),
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
  viewerCanvas: $("viewer-canvas"),
  payloadPre: $("payloadPre"),
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

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result;
      const b64 = dataUrl.split(",")[1];
      resolve(b64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// ───────────────────────────────────────────────────────────
// Image preview
// ───────────────────────────────────────────────────────────
els.imageInput.addEventListener("change", () => {
  const file = els.imageInput.files?.[0];
  if (file) {
    const reader = new FileReader();
    reader.onload = (e) => {
      els.imgPreview.src = e.target.result;
      els.imgPreview.style.display = "block";
    };
    reader.readAsDataURL(file);
  } else {
    els.imgPreview.style.display = "none";
  }
});

// ───────────────────────────────────────────────────────────
// Temporal card visibility
// ───────────────────────────────────────────────────────────
els.execMode.addEventListener("change", () => {
  els.temporalCard.style.display =
    els.execMode.value === "temporal" ? "flex" : "flex";
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
    showPayload("response", data);
    state.activeTab = "response";
    document.querySelectorAll(".payload-tabs button").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === "response");
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
  const prompt = els.prompt.value.trim();
  const imageFile = els.imageInput.files?.[0];

  if (!prompt && !imageFile) {
    throw new Error("Enter a text prompt or upload a reference image.");
  }

  const payload = {
    prompt: prompt || undefined,
    llm_name: document.querySelector('input[name="llm"]:checked').value,
    max_retries: parseInt(els.maxRetries.value) || 3,
    max_cost_usd: parseFloat(els.maxCost.value) || 5.0,
  };

  if (imageFile) {
    payload.image_b64 = await fileToBase64(imageFile);
    payload.image_mime = imageFile.type || "image/jpeg";
  }

  return payload;
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

  const result = res.data.result || res.data;
  return result;
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

  const pollMs = parseInt(els.pollMs.value) || 2000;

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
// Temporal (/temporal proxy via Temporal pipeline)
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
    return_nodes: ["ring-generate"],
  };

  setStatus("Starting Temporal workflow...", "working");
  setProgress(10);

  const fullRequest = { temporal_base_url: baseUrl, workflow_name: workflowName, ...temporalPayload, headers };
  showPayload("request", fullRequest);

  // Start workflow via Temporal pipeline
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

  // Poll status
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

  // Get result
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

  // Extract result from Temporal response (may be nested)
  const genResult = findResultRecursively(resultData);
  if (!genResult) throw new Error("No generation result found in Temporal response");
  return genResult;
}

function findResultRecursively(node) {
  if (!node || typeof node !== "object") return null;
  if (typeof node.glb_path === "string" || typeof node.session_id === "string") return node;
  if (Array.isArray(node)) {
    for (const item of node) {
      const found = findResultRecursively(item);
      if (found) return found;
    }
    return null;
  }
  for (const value of Object.values(node)) {
    const found = findResultRecursively(value);
    if (found) return found;
  }
  return null;
}

// ───────────────────────────────────────────────────────────
// Main generate handler
// ───────────────────────────────────────────────────────────
async function generate() {
  const controller = new AbortController();
  state.abortController = controller;

  els.generateBtn.disabled = true;
  els.cancelBtn.disabled = false;
  setProgress(0);

  try {
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
    showPayload("cost", {
      cost_summary: result.cost_summary,
      retry_log: result.retry_log,
      llm_used: result.llm_used,
      blender_elapsed: result.blender_elapsed,
      glb_size: result.glb_size,
      needs_validation: result.needs_validation,
    });

    setProgress(95);

    // Load GLB in viewer
    if (result.session_id) {
      const glbUrl = `/sessions/${result.session_id}/model.glb?t=${Date.now()}`;
      loadModel(glbUrl);
    } else if (result.glb_path) {
      setStatus("GLB generated but path is server-local. Check response payload.", "ok");
    }

    setProgress(100);
    const cost = result.cost_summary?.total_usd ?? 0;
    const retries = result.retry_log?.length ?? 0;
    const totalElapsed = ((Date.now() - asyncStartTime) / 1000).toFixed(1);
    setStatus(
      `Done in ${totalElapsed}s! session=${result.session_id || "?"} | cost=$${cost.toFixed(4)} | attempts=${retries} | ` +
      `glb=${((result.glb_size || 0) / 1024).toFixed(1)}KB | validation=${result.needs_validation ? "needed" : "skip"}`,
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
    els.generateBtn.disabled = false;
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
// Three.js viewer
// ───────────────────────────────────────────────────────────
let renderer, scene, camera, controls, gltfLoader;
let currentModel = null;

function initViewer() {
  const container = els.viewerCanvas;
  if (!container) return;

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x101622);

  camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.01, 500);
  camera.position.set(0, 2, 5);

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.2;
  container.appendChild(renderer.domElement);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.target.set(0, 0, 0);

  // Lighting
  const hemi = new THREE.HemisphereLight(0xffffff, 0x223344, 1.2);
  scene.add(hemi);

  const key = new THREE.DirectionalLight(0xffffff, 2.0);
  key.position.set(4, 8, 5);
  scene.add(key);

  const fill = new THREE.DirectionalLight(0xffffff, 0.6);
  fill.position.set(-4, 4, -3);
  scene.add(fill);

  const rim = new THREE.DirectionalLight(0xffffff, 0.8);
  rim.position.set(0, 4, -8);
  scene.add(rim);

  // Grid
  const grid = new THREE.GridHelper(10, 20, 0x2f415f, 0x1e2a3d);
  grid.position.y = -1.5;
  scene.add(grid);

  gltfLoader = new GLTFLoader();

  window.addEventListener("resize", () => {
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
  });

  function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }
  animate();
}

function loadModel(url) {
  if (!gltfLoader || !scene) return;

  gltfLoader.load(
    url,
    (gltf) => {
      if (currentModel) scene.remove(currentModel);

      currentModel = new THREE.Group();
      const model = gltf.scene;

      const box = new THREE.Box3().setFromObject(model);
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z) || 1;
      const scale = 2.5 / maxDim;

      model.updateMatrixWorld(true);
      model.traverse((child) => {
        if (child.isMesh && child.geometry) {
          const geo = child.geometry.clone();
          geo.applyMatrix4(child.matrixWorld);
          if (!geo.attributes.normal) geo.computeVertexNormals();

          const mat = new THREE.MeshStandardMaterial({
            color: 0xd4af37,
            metalness: 0.95,
            roughness: 0.15,
          });

          const mesh = new THREE.Mesh(geo, mat);
          mesh.castShadow = true;
          mesh.receiveShadow = true;
          currentModel.add(mesh);
        }
      });

      currentModel.scale.setScalar(scale);
      scene.add(currentModel);

      const newBox = new THREE.Box3().setFromObject(currentModel);
      const center = newBox.getCenter(new THREE.Vector3());
      controls.target.copy(center);
      camera.position.set(center.x, center.y + 2, center.z + 5);
      controls.update();
    },
    undefined,
    (err) => {
      console.error("GLB load error:", err);
      setStatus(`3D load failed: ${err?.message || "unknown"}`, "err");
    }
  );
}

// ───────────────────────────────────────────────────────────
// Wire events
// ───────────────────────────────────────────────────────────
els.generateBtn.addEventListener("click", generate);
els.cancelBtn.addEventListener("click", cancelJob);

// ───────────────────────────────────────────────────────────
// Init
// ───────────────────────────────────────────────────────────
initViewer();
checkHealth();
setInterval(checkHealth, 30000);
showPayload("request", { hint: "Generate a ring to see the request payload here." });
