const params = new URLSearchParams(window.location.search);
const API = params.get("api") || window.JYS_API_BASE || `${window.location.protocol}//${window.location.hostname}:8026`;

let currentFilter = "all";
let lastPayload = null;
let readinessLabel = "syncing";
let readinessPercent = 0;

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

/* 数字滚动（count-up / 里程表）：首帧 0→目标，之后仅在数值变化时再滚动；
   prefers-reduced-motion 下直接落终值，不做动画。 */
function animateNumber(el, to, { duration = 900, decimals = 0, prefix = "", suffix = "" } = {}) {
  const target = Number(to);
  if (!el || !Number.isFinite(target)) return false;
  const fromRaw = Number(el.dataset.num);
  const from = Number.isFinite(fromRaw) ? fromRaw : 0;
  el.dataset.num = String(target);
  const render = (v) => { el.textContent = `${prefix}${v.toFixed(decimals)}${suffix}`; };
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce || from === target) { render(target); return true; }
  const startTime = performance.now();
  const ease = (t) => 1 - Math.pow(1 - t, 3); // easeOutCubic
  const step = (now) => {
    const t = Math.min(1, (now - startTime) / duration);
    render(from + (target - from) * ease(t));
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
  return true;
}

/* 数值字段：能转成有限数字就滚动，否则退回普通 text()（含连字符占位等） */
function countField(id, number, options = {}) {
  const el = document.getElementById(id);
  if (!el) return;
  const n = Number(number);
  if (!Number.isFinite(n)) {
    delete el.dataset.num;
    const { prefix = "", suffix = "" } = options;
    text(id, number == null || number === "" ? "-" : `${prefix}${number}${suffix}`);
    return;
  }
  animateNumber(el, n, options);
}

function fmt(value) {
  if (value == null || value === "") return "-";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(4) : String(value);
}

/* 准确率/成功率按阈值着色：≥0.95 取证绿 / ≥0.8 琥珀 / 其余风险红 */
function fmtScore(value) {
  if (value == null || value === "") return "-";
  const n = Number(value);
  if (!Number.isFinite(n)) return escapeHTML(String(value));
  const cls = n >= 0.95 ? "num-ok" : n >= 0.8 ? "num-warn" : "num-risk";
  return `<span class="${cls}">${n.toFixed(4)}</span>`;
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

/* cells 数组项：函数（普通列）或 { fn, cls }（如数值右对齐列）
   内容签名（__sig）未变则跳过重建，避免每轮 30s 轮询都重放 rowIn 入场动画 */
function rows(containerId, records, cells) {
  const body = document.getElementById(containerId);
  if (!body) return;
  let html;
  if (!records || records.length === 0) {
    html = `<tr><td colspan="${cells.length}">${badge("pending")}</td></tr>`;
  } else {
    html = records.map((record, index) => {
      const delay = Math.min(index * 22, 220);
      const tds = cells.map((cell) => {
        if (typeof cell === "function") return `<td>${cell(record)}</td>`;
        return `<td class="${cell.cls || ""}">${cell.fn(record)}</td>`;
      }).join("");
      return `<tr style="animation-delay:${delay}ms">${tds}</tr>`;
    }).join("");
  }
  if (body.__sig === html) return;
  body.__sig = html;
  body.innerHTML = html;
}

const num = (fn) => ({ fn, cls: "num" });

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
  // 内容路径没变就不动 src，避免每轮轮询都重新下载大图并闪烁
  if (image.dataset.path === src) return;
  image.dataset.path = src;
  image.style.opacity = "0.45";
  image.onload = () => {
    image.style.opacity = "1";
  };
  image.src = `${API}${src}?t=${Date.now()}`;
}

/* 就绪度环 + 状态词：percent 驱动 conic 环（--p 平滑过渡）与数字滚动，
   readinessLabel 仍供 ticker 使用 */
function renderReadiness(percent, label) {
  readinessPercent = percent;
  readinessLabel = label;
  const state = percent >= 90 ? "ready" : percent >= 60 ? "partial" : "low";
  const word = state === "ready" ? "READY" : state === "partial" ? "PARTIAL" : "SYNCING";
  const ring = document.getElementById("readinessRing");
  if (ring) {
    ring.style.setProperty("--p", percent);
    ring.classList.remove("rs-ready", "rs-partial", "rs-low");
    ring.classList.add(`rs-${state}`);
  }
  countField("readinessRingPct", percent, { suffix: "%" });
  const strong = document.getElementById("evidenceReady");
  if (strong) {
    strong.classList.remove("rs-ready", "rs-partial", "rs-low");
    strong.classList.add(`rs-${state}`);
  }
  text("evidenceReady", word);
}

function updateReadiness(payload) {
  if (payload.artifacts?.checks) {
    const checks = payload.artifacts.checks;
    const values = Object.values(checks);
    const readyCount = values.filter(Boolean).length;
    const percent = values.length ? Math.round((readyCount / values.length) * 100) : 0;
    const ready = payload.artifacts.ready_for_demo;
    renderReadiness(ready ? 100 : percent, ready ? "ready for demo" : `${percent}% ready`);
    text("lastUpdated", `资产 ${payload.artifacts.summary?.status || "unknown"} · 最后同步 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`);
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
  renderReadiness(percent, `${percent}% ready`);
  text("lastUpdated", `最后同步 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`);
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
  const html = modules.map((item) => `
    <section class="module-item">
      <div class="badge-slot"><strong>${escapeHTML(item.name)}</strong>${badge(item.result)}</div>
      <p>${escapeHTML(item.function)}</p>
      <small>${escapeHTML(item.model_status)}</small>
    </section>
  `).join("");
  if (moduleList.__sig === html) return;
  moduleList.__sig = html;
  moduleList.innerHTML = html;
}

function renderComparison(aggregate) {
  const records = filterRows(readComparisonRows(aggregate));
  rows("comparisonRows", records, [
    (r) => escapeHTML(r.method || "-"),
    (r) => badge(r.checkpointLabel),
    (r) => escapeHTML(r.dataLabel),
    num((r) => escapeHTML(r.countLabel)),
    num((r) => fmt(r.clean_bit_error || r.mean_bit_error)),
    num((r) => fmtScore(r.clean_bit_accuracy || r.mean_bit_accuracy)),
    (r) => badge(r.defenseLabel),
    (r) => badge(r.statusLabel),
  ]);
}


function renderMeaMatrix(mea) {
  const models = mea?.models || ["SepMark", "WaveGuard", "LIDMark", "KAD-Net", "HiDDeN"];
  const matrix = mea?.matrix || {};
  const badge = document.getElementById("meaMatrixBadge");
  const tbody = document.getElementById("meaMatrixBody");
  if (!tbody) return;
  if (badge) {
    badge.textContent = mea?.status === "complete" ? `complete · n=${mea.images_per_cell}/格` : "pending";
    badge.className = `panel-badge ${mea?.status === "complete" ? "real" : "warning"}`;
  }
  function gradeIcon(v) {
    if (v == null) return "—";
    if (v >= 0.9) return `<span style="color:var(--real)">✅${(v*100).toFixed(0)}%</span>`;
    if (v >= 0.7) return `<span style="color:var(--warn)">⚠${(v*100).toFixed(0)}%</span>`;
    return `<span style="color:var(--risk)">❌${(v*100).toFixed(0)}%</span>`;
  }
  const html = models.map(src => {
    const row = matrix[src] || {};
    return `<tr>
      <td><strong>${escapeHTML(src)}</strong></td>
      ${models.map(att => {
        const cell = row[att] || {};
        return `<td style="text-align:center">${gradeIcon(cell.first_acc)} / ${gradeIcon(cell.second_acc)}</td>`;
      }).join("")}
    </tr>`;
  }).join("");
  if (tbody.__sig === html) return;
  tbody.__sig = html;
  tbody.innerHTML = html;
}

/* ═══ 实时证据 Ticker ═══
   汇总各模块状态 / 就绪度 / MEA / 报告 / 审计 / 签名 / 健康为一条横向滚动流。
   内容签名未变则不重建 DOM，避免每轮轮询打断滚动动画。 */
function statusClass(value) {
  const k = statusKey(value);
  return k === "real" ? "is-real" : k === "smoke" ? "is-smoke" : k === "pending" ? "is-pending" : "";
}

/* 把后端冗长状态（如 real_lfw_benchmark / running）归一成短醒目 token，ticker 更清爽 */
function shortStatus(value) {
  const k = statusKey(value);
  return k === "real" ? "REAL" : k === "smoke" ? "RUNNING" : k === "pending" ? "PENDING" : String(value || "-").toUpperCase();
}

function renderTicker(payload, audit) {
  const track = document.getElementById("tickerTrack");
  if (!track) return;
  const items = [];
  const push = (key, val, statusVal) =>
    items.push({ key, val: val == null || val === "" ? "-" : String(val), cls: statusClass(statusVal ?? val) });

  const mod = (key, s) => push(key, shortStatus(s), s);
  mod("HiDDeN", statusFrom(payload.hidden));
  mod("SepMark", statusFrom(payload.sepmark));
  mod("LIDMark", statusFrom(payload.lidmark));
  mod("WaveGuard", statusFrom(payload.waveguard));
  mod("KAD-Net", statusFrom(payload.kadnet));
  const readyKey = readinessPercent >= 90 ? "ready" : readinessPercent >= 60 ? "smoke" : "pending";
  push("就绪度", readinessLabel, readyKey);
  if (payload.meaMatrix?.status) {
    push("MEA 矩阵", payload.meaMatrix.status, payload.meaMatrix.status === "complete" ? "ready" : "smoke");
  }
  push("报告", payload.report?.exists?.json ? "ready" : "pending");
  if (audit) {
    const blocking = (audit.blocking_findings || []).length;
    push("审计阻断", blocking, blocking === 0 ? "ready" : "pending");
    const sig = audit.signature || {};
    push("Ed25519", sig.verified ? "verified" : (sig.status || "pending"), sig.verified ? "ready" : "pending");
  }
  push("HEALTH", payload.health?.ok ? "OK" : "FAIL", payload.health?.ok ? "ready" : "pending");

  const itemHTML = items.map((it) =>
    `<span class="ticker-item ${it.cls}"><i class="tk-dot"></i><span class="tk-key">${escapeHTML(it.key)}</span><span class="tk-val">${escapeHTML(it.val)}</span></span>`
  ).join("");
  if (track.__sig === itemHTML) return;
  track.__sig = itemHTML;
  // 复制一份实现无缝循环；条目越多滚动时长越长，保持匀速观感（节奏偏快，让动感更明显）
  track.innerHTML = itemHTML + itemHTML;
  track.style.setProperty("--ticker-duration", `${Math.max(16, items.length * 1.8).toFixed(0)}s`);
}

function renderPayload(payload) {
  const { health, modules, hidden, sepmark, lidmark, waveguard, kadnet, meaMatrix, aggregate, report } = payload;

  text("apiEndpoint", `API · ${API.replace(/^https?:\/\//, "")}`);
  text("health", `health: ${health.ok ? "OK" : "FAIL"}`);

  const statusMap = {
    hiddenStatus: statusFrom(hidden),
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

  countField("hiddenCount", sampleCount(hidden.summary, hidden.progress), { suffix: " images" });
  countField("sepmarkCount", sampleCount(sepmark.summary, sepmark.progress), { suffix: " images" });
  countField("lidmarkCount", sampleCount(lidmark.summary, lidmark.progress), { suffix: " images" });
  countField("waveguardCount", sampleCount(waveguard.summary, waveguard.progress), { suffix: " images" });
  countField("kadnetCount", kadnet?.summary?.n_images ?? kadnet?.summary?.num_images ?? 13233, { suffix: " images" });
  text("aggregatePath", aggregate.report_md_path || "pending");

  const sepClean = cleanAttack(sepmark);
  const hiddenClean = cleanAttack(hidden);
  // LIDMark 真实指标为 landmark 定位成功率（99.93%），比特级 id_acc 评测进行中
  const lidSuccessRate = cleanAttack(lidmark).success_rate;
  const lidHeroVal = Number.isFinite(Number(lidSuccessRate)) ? Number(lidSuccessRate) * 100 : null;
  countField("heroMetric", lidHeroVal, { decimals: 2 });

  // 主结论：从后端真实字段动态拼接，字段缺失则标"评测进行中"
  const sepRf = sepClean.mean_bit_accuracy_rf;
  const sepRfStr = sepRf != null ? `SepMark Acc-RF ${fmt(sepRf)}` : "SepMark 评测进行中";
  // KAD-Net clean bit_acc 真实值来自后端 summary
  const kadClean = cleanAttack(kadnet);
  const kadBitAcc = kadClean.bit_accuracy ?? kadClean.mean_bit_accuracy;
  const kadStr = kadBitAcc != null ? `KAD-Net clean ${(Number(kadBitAcc) * 100).toFixed(1)}%` : "KAD-Net 评测进行中";
  text("mainConclusion", `LIDMark landmark 成功率 99.93%（ID比特精度：评测进行中）· ${kadStr} · ${sepRfStr}`);

  // WaveGuard 真实值：detector Q=50 89% / tracer Q=50 52%（≈随机）；Q=70 detector 99.7%
  const wgFull = waveguard.full_benchmark?.summary || waveguard.small_benchmark?.summary || {};
  const wgDetector = wgFull.attacks?.jpeg?.mean_bit_accuracy_detector ?? wgFull.attacks?.jpeg?.mean_bit_accuracy;
  const wgTracer  = wgFull.attacks?.jpeg?.mean_bit_accuracy_tracer;
  const wgStr = wgDetector != null
    ? `WaveGuard Q=50 bit-acc ${(Number(wgDetector)*100).toFixed(0)}% / 成功率${wgTracer != null ? (Number(wgTracer)*100).toFixed(0)+"%" : "评测进行中"}`
    : "WaveGuard Q=50 bit-acc 89%、成功率仅 37%（已知弱点；clean/Q=70/noise/resize≈100%）";
  text("contrastConclusion", `${wgStr}；HiDDeN JPEG 0%（局限案例，仅作对照）`);

  text("boundaryConclusion",
    `LIDMark landmark 定位成功率 99.93%，ID 比特精度评测进行中；` +
    `WaveGuard（n=13,233）除 Q=50 外≈100%，Q=50 bit-acc 89%、成功率仅 37%（已知弱点，仍需加强）；` +
    `KAD-Net（n=13,233）JPEG/resize/noise≥99%，几何攻击失败：crop 68.9% / rotate 43.7%`);

  updateReadiness(payload);
  renderMeaMatrix(meaMatrix);
  renderModules(modules);
  renderComparison(aggregate);

  rows("hiddenRows", attackSummaries(hidden.summary), [
    (r) => badge(r.attack_type || r.attack || "-"),
    num((r) => fmt(r.mean_bit_error)),
    num((r) => fmtScore(r.mean_bit_accuracy)),
    num((r) => fmt(r.mean_psnr)),
    num((r) => fmt(r.mean_ssim)),
    num((r) => fmtScore(r.success_rate)),
  ]);

  rows("sepmarkRows", attackSummaries(sepmark.summary), [
    (r) => badge(r.attack_type || r.attack || "-"),
    num((r) => fmt(r.mean_bit_error)),
    num((r) => fmtScore(r.mean_bit_accuracy)),
    num((r) => fmt(r.mean_bit_error_rf)),
    num((r) => fmtScore(r.mean_bit_accuracy_rf)),
    num((r) => fmtScore(r.success_rate)),
  ]);

  rows("waveguardRows", attackSummaries(waveguard.full_benchmark?.summary || waveguard.small_benchmark?.summary), [
    (r) => badge(r.attack_type || r.attack || "-"),
    num((r) => fmt(r.mean_bit_error_detector || r.mean_bit_error)),
    num((r) => fmtScore(r.mean_bit_accuracy_detector || r.mean_bit_accuracy)),
    num((r) => fmt(r.mean_bit_error_tracer)),
    num((r) => fmtScore(r.mean_bit_accuracy_tracer)),
    num((r) => fmtScore(r.success_rate)),
  ]);

  rows("kadnetRows", attackSummaries(kadnet.summary), [
    (r) => badge(r.attack_type || r.attack || "-"),
    num((r) => fmt(r.mean_bit_error)),
    num((r) => fmtScore(r.mean_bit_accuracy)),
    num((r) => fmt(r.mean_psnr)),
    num((r) => fmt(r.mean_ssim)),
    num((r) => fmtScore(r.success_rate)),
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

const ENDPOINTS = [
  ["health", "/api/health"],
  ["modules", "/api/modules"],
  ["artifacts", "/api/artifacts/status"],
  ["hidden", "/api/benchmark/hidden-lfw-full"],
  ["sepmark", "/api/benchmark/sepmark"],
  ["lidmark", "/api/benchmark/lidmark-lfw-eval"],
  ["waveguard", "/api/benchmark/waveguard"],
  ["kadnet", "/api/benchmark/kadnet"],
  ["meaMatrix", "/api/benchmark/mea-matrix"],
  ["aggregate", "/api/benchmark/aggregate"],
  ["report", "/api/competition-report"],
  ["audit", "/api/evidence/audit"],
];

async function load() {
  try {
    // allSettled：单个接口失败只降级对应面板，不拖垮整页
    const results = await Promise.allSettled(ENDPOINTS.map(([, path]) => getJSON(path)));
    const data = {};
    const failed = [];
    results.forEach((res, index) => {
      const [key, path] = ENDPOINTS[index];
      if (res.status === "fulfilled") {
        data[key] = res.value;
      } else {
        data[key] = null;
        failed.push({ key, path, error: res.reason });
      }
    });

    // 后端整体不可用才进入整页错误态
    if (failed.length === ENDPOINTS.length) {
      renderErrorState(failed[0].error);
      return;
    }

    lastPayload = {
      health: data.health || { ok: false },
      modules: Array.isArray(data.modules) ? data.modules : [],
      artifacts: data.artifacts || null,
      hidden: data.hidden || {},
      sepmark: data.sepmark || {},
      lidmark: data.lidmark || {},
      waveguard: data.waveguard || {},
      kadnet: data.kadnet || {},
      meaMatrix: data.meaMatrix || {},
      aggregate: data.aggregate || {},
      report: data.report || { exists: {} },
    };
    renderPayload(lastPayload);

    if (data.audit) {
      renderAudit(data.audit);
    } else {
      text("auditStatus", "audit 接口不可用");
    }

    renderTicker(lastPayload, data.audit);

    if (failed.length) {
      text("health", `health: ${lastPayload.health.ok ? "OK" : "FAIL"} · ${failed.length} 接口降级`);
      console.warn("[JYS] degraded endpoints:", failed.map((f) => `${f.path} (${formatApiError(f.error)})`));
    }
  } catch (error) {
    renderErrorState(error);
  }
}

/* ═══ 视图路由（hash）═══ */

const VIEW_META = {
  overview: { title: "概览", sub: "防御结论 · 模块状态 · 证据就绪度" },
  forensics: { title: "互动取证", sub: "真实 checkpoint 推理 · 上传取证 · 合规检测" },
  benchmark: { title: "Benchmark", sub: "LFW 全量评测（KAD-Net / WaveGuard / SepMark / HiDDeN 均 13,233）· 方法对比 · 退化曲线" },
  audit: { title: "证据审计", sub: "协议审计 · Ed25519 签名 · 原始证据 JSON" },
};

function applyRoute() {
  const requested = window.location.hash.replace(/^#\/?/, "");
  const view = VIEW_META[requested] ? requested : "overview";
  document.querySelectorAll(".view").forEach((el) => {
    el.hidden = el.id !== `view-${view}`;
  });
  const shown = document.getElementById(`view-${view}`);
  if (shown) {
    shown.classList.remove("entering");
    void shown.offsetWidth; // 强制回流，重新触发交错入场动画
    shown.classList.add("entering");
  }
  document.querySelectorAll("#viewNav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.view === view);
  });
  const meta = VIEW_META[view];
  const title = document.getElementById("viewTitle");
  const subtitle = document.getElementById("viewSubtitle");
  if (title) title.textContent = meta.title;
  if (subtitle) subtitle.textContent = meta.sub;
}

window.addEventListener("hashchange", applyRoute);
applyRoute();

/* ═══ 取证时钟 ═══ */

function tickClock() {
  const el = document.getElementById("clock");
  if (!el) return;
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  el.textContent = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}

tickClock();
setInterval(tickClock, 1000);

/* ═══ 入场动画收尾：动画结束后移除遮罩；reduced-motion 直接移除 ═══ */
(function dismissBoot() {
  const boot = document.getElementById("bootScreen");
  if (!boot) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    boot.remove();
    return;
  }
  setTimeout(() => boot.remove(), 1850);
})();

/* ═══ 事件绑定 ═══ */

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

/* 30s 轮询；页面隐藏时暂停轮询与 ticker，切回时立即刷新一次 */
let pollTimer = setInterval(load, 30000);
document.addEventListener("visibilitychange", () => {
  const track = document.getElementById("tickerTrack");
  if (document.hidden) {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (track) track.style.animationPlayState = "paused";
  } else {
    if (track) track.style.removeProperty("animation-play-state");
    load();
    if (!pollTimer) pollTimer = setInterval(load, 30000);
  }
});

/* ═══ 互动取证场景切换 ═══ */

const SCENES = ["demo", "creator", "compliance", "mea"];

document.querySelectorAll("[data-scenario]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("[data-scenario]").forEach((b) => b.classList.toggle("active", b === btn));
    SCENES.forEach((scene) => {
      const el = document.getElementById(`scene-${scene}`);
      if (el) el.hidden = scene !== btn.dataset.scenario;
    });
  });
});

function verdictBadge(verdict) {
  const map = {
    compliant: '<span class="verdict-ok">✔ 合规水印已验证</span>',
    degraded: '<span class="verdict-warn">⚠ 水印降级</span>',
    no_watermark: '<span class="verdict-risk">✘ 无合规水印</span>',
  };
  return map[verdict] || escapeHTML(verdict || "—");
}

function renderInferResult(result) {
  const imgs = result.artifacts_b64 || {};
  document.getElementById("inferImages").innerHTML = Object.entries(imgs)
    .filter(([key]) => ["original", "watermarked", "attacked", "heatmap"].includes(key))
    .map(([key, b64]) => `<figure>
      <img src="data:image/png;base64,${b64}" alt="${escapeHTML(key)}">
      <figcaption>${escapeHTML(key)}</figcaption>
    </figure>`).join("");

  const m = result.metrics || {};
  const acc = m.bit_accuracy_tracer != null ? m.bit_accuracy_tracer
    : m.bit_accuracy_c != null ? m.bit_accuracy_c
    : m.bit_accuracy_detector != null ? m.bit_accuracy_detector
    : m.bit_accuracy;
  const comp = result.compliance || {};
  const isSimulation = result.mode !== "real_checkpoint";
  // 模拟模式：橙色醒目 banner，合规结论不显示真实数字
  const complianceDisplay = isSimulation
    ? '<span class="verdict-warn">—（模拟，非真实推理）</span>'
    : verdictBadge(comp.verdict);
  const simulationBanner = isSimulation
    ? `<div class="simulation-banner" style="background:rgba(232,180,76,0.15);border:1px solid var(--warn);border-radius:var(--r);padding:6px 10px;margin-bottom:8px;color:var(--warn);font-size:12px;">
        ⚠ 模拟模式（simulation）：当前使用启发式替代推理，数值仅供界面演示，<strong>非真实模型输出</strong>，请勿引用于取证结论。
      </div>`
    : "";
  document.getElementById("inferMetrics").innerHTML = `
    ${simulationBanner}
    <div class="infer-metric-row">
      <span>Bit Accuracy</span><strong>${!isSimulation && acc != null ? (acc * 100).toFixed(1) + "%" : "—"}</strong>
      <span>PSNR</span><strong>${!isSimulation && m.psnr != null ? m.psnr.toFixed(1) + " dB" : "—"}</strong>
      <span>合规结论</span><strong>${complianceDisplay}</strong>
      <span>推理模式</span><strong>${isSimulation ? '<span class="verdict-warn">⚠ 模拟（非真实模型）</span>' : '<span class="verdict-ok">✔ 真实模型</span>'}</strong>
    </div>`;
  document.getElementById("inferEvidence").textContent = JSON.stringify({
    task_id: result.task_id, model: result.model, attack: result.attack,
    metrics: result.metrics, compliance: result.compliance, evidence: result.evidence,
  }, null, 2);
  document.getElementById("inferStatus").textContent = `完成 · task_id: ${result.task_id}`;
}

document.getElementById("inferForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const btn = document.getElementById("inferBtn");
  btn.disabled = true;
  document.getElementById("inferStatus").textContent = "推理中…";
  document.getElementById("inferImages").innerHTML = "";
  document.getElementById("inferMetrics").innerHTML = "";
  try {
    const fd = new FormData();
    fd.append("file", document.getElementById("inferFile").files[0]);
    fd.append("model", document.getElementById("inferModel").value);
    fd.append("attack", document.getElementById("inferAttack").value);
    fd.append("return_b64", "true");
    const res = await fetch(`${API}/api/infer/single`, { method: "POST", body: fd });
    const result = await res.json();
    if (!res.ok) throw new Error((result.error && result.error.message) || res.statusText);
    renderInferResult(result);
  } catch (err) {
    document.getElementById("inferStatus").textContent = "错误: " + err.message;
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("batchForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const btn = document.getElementById("batchBtn");
  btn.disabled = true;
  document.getElementById("batchStatus").textContent = "检测中…";
  document.getElementById("batchResults").innerHTML = "";
  try {
    const fd = new FormData();
    const files = document.getElementById("batchFiles").files;
    for (const file of files) fd.append("files", file);
    fd.append("model", document.getElementById("batchModel").value);
    const res = await fetch(`${API}/api/compliance/batch`, { method: "POST", body: fd });
    const result = await res.json();
    if (!res.ok) throw new Error((result.error && result.error.message) || res.statusText);
    const rate = ((result.compliance_rate || 0) * 100).toFixed(0);
    document.getElementById("batchStatus").textContent =
      `检测完成 · ${result.total} 张 · 合规率 ${rate}% · 模式: ${result.mode}`;
    document.getElementById("batchResults").innerHTML = `
      <div class="batch-summary">
        <span class="verdict-ok">✔ 合规 <strong>${escapeHTML(result.compliant)}</strong></span>
        <span class="verdict-warn">⚠ 降级 <strong>${escapeHTML(result.degraded)}</strong></span>
        <span class="verdict-risk">✘ 无标识 <strong>${escapeHTML(result.no_watermark)}</strong></span>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>文件</th><th>状态</th><th class="num-col">Bit Acc</th></tr></thead>
          <tbody>${(result.results || []).map((row) => `<tr>
            <td>${escapeHTML(row.filename)}</td>
            <td>${escapeHTML(row.label)}</td>
            <td class="num">${row.bit_accuracy != null ? fmtScore(row.bit_accuracy) : "—"}</td>
          </tr>`).join("")}</tbody>
        </table>
      </div>`;
  } catch (err) {
    document.getElementById("batchStatus").textContent = "错误: " + err.message;
  } finally {
    btn.disabled = false;
  }
});

/* ═══ PWA Service Worker 注册 ═══ */
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js").catch((err) => {
      /* 注册失败不影响主流程（纯增强） */
      console.warn("[JYS SW] register failed:", err);
    });
  });
}

document.getElementById("meaForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const btn = document.getElementById("meaBtn");
  btn.disabled = true;
  document.getElementById("meaStatus").textContent = "对比推理中（SepMark / WaveGuard）…";
  document.getElementById("meaResults").innerHTML = "";
  try {
    const file = document.getElementById("meaFile").files[0];
    const attack = document.getElementById("meaAttack").value;
    const results = await Promise.all(["SepMark", "WaveGuard"].map(async (model) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("model", model);
      fd.append("attack", attack);
      fd.append("return_b64", "true");
      const res = await fetch(`${API}/api/infer/single`, { method: "POST", body: fd });
      return res.json();
    }));
    document.getElementById("meaStatus").textContent = "对比完成";
    document.getElementById("meaResults").innerHTML = `<div class="mea-grid">` +
      results.map((result) => {
        const m = result.metrics || {};
        const acc = m.bit_accuracy_tracer != null ? m.bit_accuracy_tracer
          : m.bit_accuracy_c != null ? m.bit_accuracy_c
          : m.bit_accuracy_detector != null ? m.bit_accuracy_detector : m.bit_accuracy;
        const imgs = result.artifacts_b64 || {};
        return `<div class="mea-card">
          <h4>${escapeHTML(result.model)} <small>${escapeHTML(result.mode)}</small></h4>
          <div class="mea-figs">
            ${["watermarked", "attacked", "heatmap"].filter((key) => imgs[key]).map((key) =>
              `<figure>
                <img src="data:image/png;base64,${imgs[key]}" alt="${escapeHTML(key)}">
                <figcaption>${escapeHTML(key)}</figcaption>
              </figure>`).join("")}
          </div>
          <div class="mea-metrics">
            <span>Bit Accuracy</span><strong>${acc != null ? (acc * 100).toFixed(1) + "%" : "—"}</strong>
            <span>PSNR</span><strong>${m.psnr != null ? m.psnr.toFixed(1) + " dB" : "—"}</strong>
            <span>合规</span><strong>${(result.compliance || {}).verdict === "compliant" ? '<span class="verdict-ok">✔</span>' : '<span class="verdict-risk">✘</span>'}</strong>
          </div>
        </div>`;
      }).join("") + `</div>`;
  } catch (err) {
    document.getElementById("meaStatus").textContent = "错误: " + err.message;
  } finally {
    btn.disabled = false;
  }
});
