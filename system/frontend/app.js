const params = new URLSearchParams(window.location.search);
const API = params.get("api") || window.JYS_API_BASE || `${window.location.protocol}//${window.location.hostname}:8026`;

let currentFilter = "all";
let lastPayload = null;

class ApiError extends Error {
  constructor({ code, message, path, status, details }) {
    super(message || "API request failed");
    this.name = "ApiError";
    this.code = code || "api_error";
    this.path = path || "-";
    this.status = status || 0;
    this.details = details;
  }
}

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function text(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  const next = value == null || value === "" ? "-" : String(value);
  if (el.textContent !== next) {
    el.textContent = next;
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  }
}

function fmt(value) {
  if (value == null || value === "") return "-";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(4) : String(value);
}

function statusKey(value) {
  const raw = String(value || "").toLowerCase();
  if (["yes", "true", "ready", "real", "complete", "real_lfw_benchmark"].some((key) => raw.includes(key))) return "real";
  if (["running", "partial", "smoke", "single_smoke", "checkpoint_load"].some((key) => raw.includes(key))) return "smoke";
  if (["pending", "failed", "missing", "read_failed", "no", "false"].some((key) => raw.includes(key))) return "pending";
  return "neutral";
}

function badge(value) {
  const label = value == null || value === "" ? "-" : String(value);
  return `<span class="status-badge status-${statusKey(label)}">${escapeHTML(label)}</span>`;
}

function setCardStatus(id, value) {
  const card = document.querySelector(`[data-status-card="${id}"]`);
  if (!card) return;
  card.classList.remove("status-real", "status-ready", "status-complete", "status-running", "status-smoke", "status-partial", "status-pending", "status-missing", "status-failed");
  const key = statusKey(value);
  card.classList.add(`status-${key === "neutral" ? "pending" : key}`);
}

function rows(containerId, records, cells) {
  const body = document.getElementById(containerId);
  if (!body) return;
  body.innerHTML = "";
  if (!records || records.length === 0) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="${cells.length}">${badge("pending")}</td>`;
    body.appendChild(tr);
    return;
  }
  records.forEach((record, index) => {
    const tr = document.createElement("tr");
    tr.style.animationDelay = `${Math.min(index * 22, 220)}ms`;
    tr.innerHTML = cells.map((cell) => `<td>${cell(record)}</td>`).join("");
    body.appendChild(tr);
  });
}

async function getJSON(path) {
  let res;
  try {
    res = await fetch(`${API}${path}`);
  } catch (error) {
    throw new ApiError({
      code: "network_error",
      message: error.message || "Network request failed",
      path,
      status: 0,
    });
  }

  let payload = null;
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      payload = await res.json();
    } catch (error) {
      throw new ApiError({
        code: "invalid_json",
        message: error.message || "Invalid JSON response",
        path,
        status: res.status,
      });
    }
  }

  if (!res.ok) {
    const apiError = payload?.error || {};
    throw new ApiError({
      code: apiError.code || "http_error",
      message: apiError.message || `HTTP ${res.status}`,
      path: apiError.path || path,
      status: res.status,
      details: apiError.details,
    });
  }

  return payload;
}

function formatApiError(error) {
  if (error instanceof ApiError) {
    return `${error.code}: ${error.message} (${error.path})`;
  }
  return `error: ${error.message || String(error)}`;
}

function renderErrorState(error) {
  const formatted = formatApiError(error);
  text("health", formatted);
  text("evidenceReady", error instanceof ApiError ? error.code : "offline");
  text("lastUpdated", error instanceof ApiError ? `${error.message} · ${error.path}` : "API 不可用");
  const bar = document.getElementById("readinessBar");
  if (bar) bar.style.width = "8%";
  const checklist = document.getElementById("artifactChecklist");
  if (checklist) {
    checklist.innerHTML = `
      <div>
        <strong>${escapeHTML(error instanceof ApiError ? error.path : "network")}</strong>
        ${badge(error instanceof ApiError ? error.code : "offline")}
      </div>
      <div>
        <strong>${escapeHTML(error.message || "API request failed")}</strong>
        ${badge(error instanceof ApiError && error.status ? `HTTP ${error.status}` : "failed")}
      </div>
    `;
  }
}

function attackSummaries(summary) {
  if (!summary) return [];
  if (Array.isArray(summary.attack_summaries)) return summary.attack_summaries;
  if (summary.attacks && typeof summary.attacks === "object") {
    return Object.entries(summary.attacks).map(([attack_type, values]) => ({ attack_type, ...values }));
  }
  return [];
}

function sampleCount(summary, progress) {
  return summary?.num_images || summary?.images || summary?.requested_images || progress?.num_images || progress?.processed_images || progress?.completed_images || "-";
}

function statusFrom(payload) {
  const summary = payload?.summary || {};
  const progress = payload?.progress || {};
  return summary.status || progress.status || (payload?.results_csv_exists ? "running" : "pending");
}

function cleanAttack(payload) {
  return payload?.summary?.attacks?.clean || {};
}

function readComparisonRows(aggregate) {
  return (aggregate?.comparison || []).map((row) => ({
    ...row,
    checkpointLabel: row.checkpoint_type || row.mode || row.checkpoint || "-",
    dataLabel: row.data_type || row.data || "-",
    countLabel: row.num_images || row.images || row.count || row.requested_images || "-",
    defenseLabel: row.defense_ready || row.can_use_for_defense || row.can_defense || "-",
    statusLabel: row.status || "-",
  }));
}

function filterRows(records) {
  if (currentFilter === "all") return records;
  return records.filter((record) => {
    const haystack = `${record.checkpointLabel} ${record.defenseLabel} ${record.statusLabel}`.toLowerCase();
    if (currentFilter === "real") return haystack.includes("real") || haystack.includes("yes") || haystack.includes("complete");
    if (currentFilter === "smoke") return haystack.includes("smoke") || haystack.includes("partial") || haystack.includes("running");
    if (currentFilter === "pending") return haystack.includes("pending") || haystack.includes("no") || haystack.includes("failed") || haystack.includes("missing");
    return true;
  });
}

function setImage(id, src) {
  const image = document.getElementById(id);
  if (!image || !src) return;
  const next = `${API}${src}?t=${Date.now()}`;
  if (image.src !== next) {
    image.style.opacity = "0.45";
    image.onload = () => {
      image.style.opacity = "1";
    };
    image.src = next;
  }
}

function updateReadiness(payload) {
  if (payload.artifacts?.checks) {
    const checks = payload.artifacts.checks;
    const values = Object.values(checks);
    const readyCount = values.filter(Boolean).length;
    const percent = values.length ? Math.round((readyCount / values.length) * 100) : 0;
    text("evidenceReady", payload.artifacts.ready_for_demo ? "ready for demo" : `${percent}% ready`);
    text("lastUpdated", `资产 ${payload.artifacts.summary?.status || "unknown"} · 最后同步 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`);
    const bar = document.getElementById("readinessBar");
    if (bar) bar.style.width = `${Math.max(percent, 8)}%`;
    renderArtifactChecklist(checks, payload.artifacts.summary);
    return;
  }

  const statuses = [
    statusFrom(payload.hidden),
    statusFrom(payload.sepmark),
    statusFrom(payload.lidmark),
    statusFrom(payload.waveguard),
    payload.report?.exists?.json ? "ready" : "pending",
  ];
  const score = statuses.reduce((sum, item) => {
    const key = statusKey(item);
    if (key === "real") return sum + 1;
    if (key === "smoke") return sum + 0.55;
    return sum;
  }, 0);
  const percent = Math.round((score / statuses.length) * 100);
  text("evidenceReady", `${percent}% ready`);
  text("lastUpdated", `最后同步 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`);
  const bar = document.getElementById("readinessBar");
  if (bar) bar.style.width = `${Math.max(percent, 8)}%`;
}

function renderArtifactChecklist(checks, summary) {
  const container = document.getElementById("artifactChecklist");
  if (!container) return;
  const labels = {
    dataset_ready: "数据集",
    weights_ready: "权重",
    benchmark_ready: "Benchmark",
    aggregate_ready: "聚合",
    report_ready: "报告",
    assets_ready: "图表资产",
  };
  container.innerHTML = Object.entries(labels).map(([key, label]) => `
    <div>
      <strong>${escapeHTML(label)}</strong>
      ${badge(checks[key] ? "ready" : "missing")}
    </div>
  `).join("");
  if (summary) {
    container.innerHTML += `
      <div>
        <strong>${escapeHTML(summary.dataset_images || 0)} images / ${escapeHTML(summary.checkpoint_files || 0)} ckpts</strong>
        ${badge(summary.status || "unknown")}
      </div>
    `;
  }
}

function renderModules(modules) {
  const moduleList = document.getElementById("moduleList");
  if (!moduleList) return;
  moduleList.innerHTML = "";
  modules.forEach((item, index) => {
    const node = document.createElement("section");
    node.className = "module-item";
    node.style.animationDelay = `${index * 45}ms`;
    node.innerHTML = `
      <div><strong>${escapeHTML(item.name)}</strong>${badge(item.result)}</div>
      <p>${escapeHTML(item.function)}</p>
      <small>${escapeHTML(item.model_status)}</small>
    `;
    moduleList.appendChild(node);
  });
}

function renderComparison(aggregate) {
  const records = filterRows(readComparisonRows(aggregate));
  rows("comparisonRows", records, [
    (r) => escapeHTML(r.method || "-"),
    (r) => badge(r.checkpointLabel),
    (r) => escapeHTML(r.dataLabel),
    (r) => escapeHTML(r.countLabel),
    (r) => fmt(r.clean_bit_error || r.mean_bit_error),
    (r) => fmt(r.clean_bit_accuracy || r.mean_bit_accuracy),
    (r) => badge(r.defenseLabel),
    (r) => badge(r.statusLabel),
  ]);
}

function renderPayload(payload) {
  const { health, modules, hidden, sepmark, lidmark, waveguard, aggregate, report } = payload;

  text("apiEndpoint", API.replace(/^https?:\/\//, ""));
  text("health", `health: ${health.ok ? "OK" : "FAIL"}`);

  const statusMap = {
    hiddenStatus: statusFrom(hidden),
    sepmarkStatus: statusFrom(sepmark),
    lidmarkStatus: statusFrom(lidmark),
    waveguardStatus: statusFrom(waveguard),
    reportStatus: report.exists?.json ? "ready" : "pending",
  };

  Object.entries(statusMap).forEach(([id, value]) => {
    text(id, value);
    setCardStatus(id, value);
  });

  text("hiddenCount", `${sampleCount(hidden.summary, hidden.progress)} images`);
  text("sepmarkCount", `${sampleCount(sepmark.summary, sepmark.progress)} images`);
  text("lidmarkCount", `${sampleCount(lidmark.summary, lidmark.progress)} images`);
  text("waveguardCount", `${sampleCount(waveguard.summary, waveguard.progress)} images`);
  text("aggregatePath", aggregate.report_md_path || "pending");

  const sepClean = cleanAttack(sepmark);
  const hiddenClean = cleanAttack(hidden);
  text("mainConclusion", `SepMark clean Acc-C ${fmt(sepClean.mean_bit_accuracy)} / Acc-RF ${fmt(sepClean.mean_bit_accuracy_rf)}`);
  text("contrastConclusion", `HiDDeN clean Acc ${fmt(hiddenClean.mean_bit_accuracy)}，作为真实弱对照`);
  text("boundaryConclusion", "LIDMark=smoke，WaveGuard=checkpoint load，未伪造成正式指标");

  updateReadiness(payload);
  renderModules(modules);
  renderComparison(aggregate);

  rows("hiddenRows", attackSummaries(hidden.summary), [
    (r) => badge(r.attack_type || r.attack || "-"),
    (r) => fmt(r.mean_bit_error),
    (r) => fmt(r.mean_bit_accuracy),
    (r) => fmt(r.mean_psnr),
    (r) => fmt(r.mean_ssim),
    (r) => fmt(r.success_rate),
  ]);

  rows("sepmarkRows", attackSummaries(sepmark.summary), [
    (r) => badge(r.attack_type || r.attack || "-"),
    (r) => fmt(r.mean_bit_error),
    (r) => fmt(r.mean_bit_accuracy),
    (r) => fmt(r.mean_bit_error_rf),
    (r) => fmt(r.mean_bit_accuracy_rf),
    (r) => fmt(r.success_rate),
  ]);

  rows("waveguardRows", attackSummaries(waveguard.full_benchmark?.summary || waveguard.small_benchmark?.summary), [
    (r) => badge(r.attack_type || r.attack || "-"),
    (r) => fmt(r.mean_bit_error_detector || r.mean_bit_error),
    (r) => fmt(r.mean_bit_accuracy_detector || r.mean_bit_accuracy),
    (r) => fmt(r.mean_bit_error_tracer),
    (r) => fmt(r.mean_bit_accuracy_tracer),
    (r) => fmt(r.success_rate),
  ]);

  setImage("hiddenGrid", hidden.grid_image);
  setImage("sepmarkGrid", sepmark.grid_image);
  setImage("degradationCurve", aggregate.degradation_curve);

  document.getElementById("lidmarkJson").textContent = JSON.stringify({
    checkpoint_type: lidmark.checkpoint_type,
    summary: lidmark.summary,
    progress: lidmark.progress,
    results_csv_path: lidmark.results_csv_path,
  }, null, 2);

  document.getElementById("waveguardJson").textContent = JSON.stringify({
    checkpoint_type: waveguard.checkpoint_type,
    summary: waveguard.summary,
    full_benchmark: waveguard.full_benchmark?.summary,
    small_benchmark: waveguard.small_benchmark?.summary,
    progress: waveguard.progress,
    results_csv_path: waveguard.results_csv_path,
  }, null, 2);

  document.getElementById("reportPaths").innerHTML = `
    <span>JSON: ${escapeHTML(report.json_path)}</span>
    <span>CSV: ${escapeHTML(report.csv_path)}</span>
    <span>Markdown: ${escapeHTML(report.markdown_path)}</span>
  `;
}

async function load() {
  try {
    const [health, modules, artifacts, hidden, sepmark, lidmark, waveguard, aggregate, report] = await Promise.all([
      getJSON("/api/health"),
      getJSON("/api/modules"),
      getJSON("/api/artifacts/status"),
      getJSON("/api/benchmark/hidden-lfw-full"),
      getJSON("/api/benchmark/sepmark"),
      getJSON("/api/benchmark/lidmark-lfw-eval"),
      getJSON("/api/benchmark/waveguard"),
      getJSON("/api/benchmark/aggregate"),
      getJSON("/api/competition-report"),
    ]);
    lastPayload = { health, modules, artifacts, hidden, sepmark, lidmark, waveguard, aggregate, report };
    renderPayload(lastPayload);
  } catch (error) {
    renderErrorState(error);
  }
}

document.querySelectorAll("[data-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    currentFilter = button.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach((item) => item.classList.toggle("active", item === button));
    if (lastPayload) renderComparison(lastPayload.aggregate);
  });
});

load();
setInterval(load, 30000);
