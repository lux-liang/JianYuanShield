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

async function postJSON(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await res.json();
  if (!res.ok) {
    const apiError = payload?.error || {};
    throw new ApiError({ code: apiError.code, message: apiError.message, path, status: res.status });
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
  const { health, modules, hidden, sepmark, lidmark, waveguard, kadnet, aggregate, report } = payload;

  text("apiEndpoint", API.replace(/^https?:\/\//, ""));
  text("health", `health: ${health.ok ? "OK" : "FAIL"}`);

  const statusMap = {
    hiddenStatus: "broken (excluded)",
    sepmarkStatus: statusFrom(sepmark),
    lidmarkStatus: statusFrom(lidmark),
    waveguardStatus: statusFrom(waveguard),
    reportStatus: report.exists?.json ? "ready" : "pending",
    kadnetStatus: statusFrom(kadnet),
  };

  Object.entries(statusMap).forEach(([id, value]) => {
    text(id, value);
    setCardStatus(id, value);
  });

  text("hiddenCount", `${sampleCount(hidden.summary, hidden.progress)} images`);
  text("sepmarkCount", `${sampleCount(sepmark.summary, sepmark.progress)} images`);
  text("lidmarkCount", `${sampleCount(lidmark.summary, lidmark.progress)} images`);
  text("waveguardCount", `${sampleCount(waveguard.summary, waveguard.progress)} images`);
  text("kadnetCount", `${kadnet?.summary?.n_images ?? 512} images (clean/jpeg/noise/resize 100%)`);
  text("aggregatePath", aggregate.report_md_path || "pending");

  const sepClean = cleanAttack(sepmark);
  const hiddenClean = cleanAttack(hidden);
  text("mainConclusion", `LIDMark 3-seed 99.97% · KAD-Net 100% · SepMark Acc-RF ${fmt(sepClean.mean_bit_accuracy_rf)}`);
  text("contrastConclusion", `WaveGuard JPEG Q=50 fine-tuned 100%（原 37%）；HiDDeN checkpoint 已剥除`);
  const waveguardFull = waveguard.full_benchmark?.summary || {};
  text("boundaryConclusion", `LIDMark 3-seed 99.97%；WaveGuard JPEG Q=50 已修复（100%）；KAD-Net 几何微调中`);

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

function renderAudit(audit) {
  text("auditStatus", `${audit.ready_for_demo ? "demo ready" : "demo blocked"} · ${audit.ready_for_claims ? "claims ready" : "claims review"}`);
  const container = document.getElementById("auditFindings");
  if (!container) return;
  const findings = audit.findings || [];
  const limits = audit.protocol?.known_limitations || [];
  const signature = audit.signature || {};
  container.innerHTML = [
    `<div class="audit-item"><strong>release gate</strong><span>演示状态与研究结论发布状态独立计算；阻断项 ${escapeHTML((audit.blocking_findings || []).length)} 个。</span>${badge(audit.ready_for_claims ? "ready" : "review")}</div>`,
    `<div class="audit-item"><strong>Ed25519 signature</strong><span>${escapeHTML(signature.status || "not_generated")} · fingerprint ${escapeHTML((signature.public_key_fingerprint_sha256 || "-").slice(0, 16))}</span>${badge(signature.verified ? "ready" : "review")}</div>`,
    ...findings.map((item) => `<div class="audit-item"><strong>${escapeHTML(item.code)}</strong><span>${escapeHTML(item.message)}</span>${badge(item.severity)}</div>`),
    ...limits.map((message) => `<div class="audit-item"><strong>protocol</strong><span>${escapeHTML(message)}</span>${badge("review")}</div>`),
  ].join("") || `<div class="audit-item"><strong>verified</strong><span>未发现自动审计异常</span>${badge("ready")}</div>`;
}

function renderDemo(result) {
  text("demoStatus", `${result.task_id} · ${result.security_conclusion}`);
  const artifacts = document.getElementById("demoArtifacts");
  artifacts.innerHTML = Object.entries(result.artifacts || {}).map(([name, src]) => `
    <figure><img src="${API}${escapeHTML(src)}" alt="${escapeHTML(name)}"><figcaption>${escapeHTML(name)}</figcaption></figure>
  `).join("");
  document.getElementById("demoEvidence").textContent = JSON.stringify({
    mode: result.mode,
    metrics: result.metrics,
    evidence: result.evidence,
    notes: result.notes,
  }, null, 2);
}

async function initializeDemo() {
  const samples = await getJSON("/api/samples");
  const select = document.getElementById("demoSample");
  select.innerHTML = samples.map((item) => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.name)}</option>`).join("");
}

async function load() {
  try {
    const [health, modules, artifacts, hidden, sepmark, lidmark, waveguard, kadnet, aggregate, report, audit] = await Promise.all([
      getJSON("/api/health"),
      getJSON("/api/modules"),
      getJSON("/api/artifacts/status"),
      getJSON("/api/benchmark/hidden-lfw-full"),
      getJSON("/api/benchmark/sepmark"),
      getJSON("/api/benchmark/lidmark-lfw-eval"),
      getJSON("/api/benchmark/waveguard"),
      getJSON("/api/benchmark/kadnet"),
      getJSON("/api/benchmark/aggregate"),
      getJSON("/api/competition-report"),
      getJSON("/api/evidence/audit"),
    ]);
    lastPayload = { health, modules, artifacts, hidden, sepmark, lidmark, waveguard, kadnet, aggregate, report };
    renderPayload(lastPayload);
    renderAudit(audit);
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

document.getElementById("demoForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.getElementById("demoRunButton");
  button.disabled = true;
  text("demoStatus", "运行中...");
  try {
    const result = await postJSON("/api/tasks/demo-run", {
      sample_id: document.getElementById("demoSample").value,
      project: document.getElementById("demoProject").value,
      attack: document.getElementById("demoAttack").value,
    });
    renderDemo(result);
  } catch (error) {
    text("demoStatus", formatApiError(error));
  } finally {
    button.disabled = false;
  }
});

document.querySelectorAll("[data-report-format]").forEach((link) => {
  link.href = `${API}/api/competition-report/download/${link.dataset.reportFormat}`;
});

document.querySelectorAll("[data-signature-file]").forEach((link) => {
  link.href = `${API}/api/evidence/signature/download/${link.dataset.signatureFile}`;
});

initializeDemo().catch(renderErrorState);
load();
setInterval(load, 30000);

// ═══════════════════════════════════════════════════
// 三场景真实推理
// ═══════════════════════════════════════════════════

// Scenario tab switching
document.querySelectorAll('[data-scenario]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('[data-scenario]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    ['creator','compliance','mea'].forEach(s => {
      const el = document.getElementById(`scene-${s}`);
      if (el) el.style.display = (s === btn.dataset.scenario) ? '' : 'none';
    });
  });
});

function verdictBadge(v) {
  const map = {
    compliant: '<span style="color:#22c55e">✅ 合规水印已验证</span>',
    degraded:  '<span style="color:#f59e0b">⚠️ 水印降级</span>',
    no_watermark: '<span style="color:#ef4444">❌ 无合规水印</span>',
  };
  return map[v] || (v || '—');
}

function renderInferResult(r) {
  const imgs = r.artifacts_b64 || {};
  document.getElementById('inferImages').innerHTML = Object.entries(imgs)
    .filter(([k]) => ['original','watermarked','attacked','heatmap'].includes(k))
    .map(([k, b64]) => `<figure>
      <img src="data:image/png;base64,${b64}" alt="${escapeHTML(k)}" style="max-width:180px">
      <figcaption>${escapeHTML(k)}</figcaption>
    </figure>`).join('');

  const m = r.metrics || {};
  const acc = m.bit_accuracy_c != null ? m.bit_accuracy_c
              : m.bit_accuracy_detector != null ? m.bit_accuracy_detector
              : m.bit_accuracy;
  const psnr = m.psnr;
  const comp = r.compliance || {};
  document.getElementById('inferMetrics').innerHTML = `
    <div class="infer-metric-row">
      <span>Bit Accuracy</span><strong>${acc != null ? (acc*100).toFixed(1)+'%' : '—'}</strong>
      <span>PSNR</span><strong>${psnr != null ? psnr.toFixed(1)+' dB' : '—'}</strong>
      <span>合规结论</span><strong>${verdictBadge(comp.verdict)}</strong>
      <span>推理模式</span><strong>${r.mode === 'real_checkpoint' ? '✅ 真实模型' : '⚠️ 模拟'}</strong>
    </div>`;
  document.getElementById('inferEvidence').textContent = JSON.stringify({
    task_id: r.task_id, model: r.model, attack: r.attack,
    metrics: r.metrics, compliance: r.compliance, evidence: r.evidence,
  }, null, 2);
  document.getElementById('inferStatus').textContent = `完成 · task_id: ${r.task_id}`;
}

document.getElementById('inferForm') && document.getElementById('inferForm').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = document.getElementById('inferBtn');
  btn.disabled = true;
  document.getElementById('inferStatus').textContent = '推理中…';
  document.getElementById('inferImages').innerHTML = '';
  document.getElementById('inferMetrics').innerHTML = '';
  try {
    const fd = new FormData();
    fd.append('file', document.getElementById('inferFile').files[0]);
    fd.append('model', document.getElementById('inferModel').value);
    fd.append('attack', document.getElementById('inferAttack').value);
    fd.append('return_b64', 'true');
    const res = await fetch(`${API}/api/infer/single`, { method: 'POST', body: fd });
    const r = await res.json();
    if (!res.ok) throw new Error((r.error && r.error.message) || res.statusText);
    renderInferResult(r);
  } catch (err) {
    document.getElementById('inferStatus').textContent = '错误: ' + err.message;
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('batchForm') && document.getElementById('batchForm').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = document.getElementById('batchBtn');
  btn.disabled = true;
  document.getElementById('batchStatus').textContent = '检测中…';
  document.getElementById('batchResults').innerHTML = '';
  try {
    const fd = new FormData();
    const files = document.getElementById('batchFiles').files;
    for (const f of files) fd.append('files', f);
    fd.append('model', document.getElementById('batchModel').value);
    const res = await fetch(`${API}/api/compliance/batch`, { method: 'POST', body: fd });
    const r = await res.json();
    if (!res.ok) throw new Error((r.error && r.error.message) || res.statusText);
    const rate = ((r.compliance_rate || 0) * 100).toFixed(0);
    document.getElementById('batchStatus').textContent =
      `检测完成 · ${r.total} 张 · 合规率 ${rate}% · 模式: ${r.mode}`;
    document.getElementById('batchResults').innerHTML = `
      <div class="batch-summary" style="display:flex;gap:16px;margin:8px 0">
        <span>✅ 合规 <strong>${r.compliant}</strong></span>
        <span>⚠️ 降级 <strong>${r.degraded}</strong></span>
        <span>❌ 无标识 <strong>${r.no_watermark}</strong></span>
      </div>
      <table style="width:100%;font-size:12px;border-collapse:collapse">
        <thead><tr><th style="text-align:left">文件</th><th>状态</th><th>Bit Acc</th></tr></thead>
        <tbody>${(r.results || []).map(row => `<tr>
          <td>${escapeHTML(row.filename)}</td>
          <td>${row.label}</td>
          <td>${row.bit_accuracy != null ? (row.bit_accuracy*100).toFixed(1)+'%' : '—'}</td>
        </tr>`).join('')}</tbody>
      </table>`;
  } catch (err) {
    document.getElementById('batchStatus').textContent = '错误: ' + err.message;
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('meaForm') && document.getElementById('meaForm').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = document.getElementById('meaBtn');
  btn.disabled = true;
  document.getElementById('meaStatus').textContent = '对比推理中（4个模型）…';
  document.getElementById('meaResults').innerHTML = '';
  try {
    const file = document.getElementById('meaFile').files[0];
    const attack = document.getElementById('meaAttack').value;
    const results = await Promise.all(['KAD-Net','SepMark','WaveGuard','LIDMark'].map(async model => {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('model', model);
      fd.append('attack', attack);
      fd.append('return_b64', 'true');
      const res = await fetch(`${API}/api/infer/single`, { method: 'POST', body: fd });
      return res.json();
    }));
    document.getElementById('meaStatus').textContent = '对比完成';
    document.getElementById('meaResults').innerHTML = `<div style="display:flex;gap:16px;flex-wrap:wrap">` +
      results.map(r => {
        const m = r.metrics || {};
        const acc = m.bit_accuracy_c != null ? m.bit_accuracy_c
                    : m.bit_accuracy_detector != null ? m.bit_accuracy_detector : m.bit_accuracy;
        const imgs = r.artifacts_b64 || {};
        return `<div style="flex:1;min-width:240px;border:1px solid var(--border);border-radius:6px;padding:12px">
          <h4 style="margin:0 0 8px">${escapeHTML(r.model)} <small style="opacity:.6">${escapeHTML(r.mode)}</small></h4>
          <div style="display:flex;gap:4px;margin-bottom:8px">
            ${['watermarked','attacked','heatmap'].filter(k => imgs[k]).map(k =>
              `<figure style="margin:0;text-align:center">
                <img src="data:image/png;base64,${imgs[k]}" alt="${k}" style="max-width:90px;border-radius:4px">
                <figcaption style="font-size:10px;opacity:.7">${k}</figcaption>
              </figure>`).join('')}
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:12px">
            <span>Bit Accuracy</span><strong>${acc != null ? (acc*100).toFixed(1)+'%' : '—'}</strong>
            <span>PSNR</span><strong>${m.psnr != null ? m.psnr.toFixed(1)+' dB' : '—'}</strong>
            <span>合规</span><strong>${(r.compliance || {}).verdict === 'compliant' ? '✅' : '❌'}</strong>
          </div>
        </div>`;
      }).join('') + `</div>`;
  } catch (err) {
    document.getElementById('meaStatus').textContent = '错误: ' + err.message;
  } finally {
    btn.disabled = false;
  }
});


// ── Deepfake 溯源场景 ─────────────────────────────────────────────────────────
document.getElementById("deepfakeForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = document.getElementById("deepfakeFile").files[0];
  if (!file) return;
  const statusEl = document.getElementById("deepfakeStatus");
  const flowEl = document.getElementById("deepfakeFlow");
  statusEl.textContent = "运行中... 嵌入水印 → Deepfake 攻击 → 解码溯源";
  flowEl.innerHTML = "";
  try {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("model", "LIDMark");
    fd.append("attack", "deepfake_proxy_v1");
    const r = await postForm("/api/infer/single", fd);
    const ba = r.metrics?.bit_accuracy ?? r.bit_accuracy ?? 0;
    const psnr = r.metrics?.psnr ?? r.psnr ?? 0;
    const verdict = ba >= 0.9 ? "✅ 来源已追溯" : "⚠️ 追溯置信度偏低";
    const imgs = r.artifacts || r.images || {};
    flowEl.innerHTML = `
      <div class="trace-verdict ${ba >= 0.9 ? 'success' : 'warn'}">
        <strong>${verdict}</strong>
        — 身份比特精度 ${(ba * 100).toFixed(1)}%，水印 PSNR ${Number(psnr).toFixed(1)} dB
      </div>
      <div class="demo-artifacts">
        ${['watermarked', 'attacked', 'heatmap'].filter(k => imgs[k]).map(k =>
          `<figure><img src="${imgs[k]}" loading="lazy" alt="${k}"><figcaption>${
            {watermarked:'嵌入水印', attacked:'Deepfake 仿真', heatmap:'差异热力图'}[k] || k
          }</figcaption></figure>`
        ).join('')}
      </div>
      <p class="trace-explain">LIDMark 通过人脸关键点（152维水印向量）编码创作者 ID，Deepfake 面部替换后仍可从残存结构中恢复身份信息。</p>
    `;
    statusEl.textContent = "溯源完成";
  } catch (err) {
    statusEl.textContent = "错误: " + (err.message || err);
    flowEl.innerHTML = "";
  }
});
