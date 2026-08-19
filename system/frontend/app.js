function normalizeApiBase(value) {
  const configured = String(value || "").trim();
  if (!configured && window.location.protocol === "file:") return "http://127.0.0.1:8026";
  const parsed = new URL(configured || window.location.origin, window.location.origin);
  if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("JYS_API_BASE must be an HTTP(S) origin or same-origin /api prefix without credentials");
  }
  return `${parsed.origin}${parsed.pathname.replace(/\/+$/, "")}`;
}

// Production defaults to the current TLS origin. The gateway owns the user
// session and injects the server-side API key while proxying /api to 127.0.0.1:8026.
const deployedPathApi = window.location.pathname === "/jys"
  || window.location.pathname.startsWith("/jys/")
  ? "/jys/api"
  : window.location.pathname === "/jianyuanshield"
    || window.location.pathname.startsWith("/jianyuanshield/")
    ? "/jianyuanshield/api"
    : "";
const API = normalizeApiBase(window.JYS_API_BASE || deployedPathApi);
const TRUST_CONTRACTS = window.JYSTrustContracts || null;

function apiURL(path) {
  if (typeof path !== "string" || !path.startsWith("/api/")) throw new Error("invalid API path");
  return API.endsWith("/api") ? `${API}${path.slice(4)}` : `${API}${path}`;
}

let currentFilter = "all";
let lastPayload = null;
let readinessLabel = "syncing";
let readinessPercent = 0;
let protectModelGate = new Map();
let protectBusy = false;

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
  if (["no", "false", "fail"].includes(raw.trim())) return "failed";
  if (["unverified", "review_required", "review", "blocked", "unavailable", "proxy_only", "not_assessed"].some((key) => raw.includes(key))) return "pending";
  if (["missing", "not_found", "not_ready", "incomplete", "not_generated"].some((key) => raw.includes(key))) return "missing";
  if (["failed", "read_failed", "offline", "network_error", "http_error"].some((key) => raw.includes(key))) return "failed";
  if (["running", "partial", "smoke", "single_smoke", "checkpoint_load"].some((key) => raw.includes(key))) return "smoke";
  if (["pending", "review", "unknown", "wait"].some((key) => raw.includes(key))) return "pending";
  if (["yes", "true", "ready", "verified", "real", "complete", "real_lfw_benchmark"].some((key) => raw.includes(key))) return "real";
  return "neutral";
}

function badge(value) {
  const label = value == null || value === "" ? "-" : String(value);
  return `<span class="status-badge status-${statusKey(label)}">${escapeHTML(label)}</span>`;
}

function setCardStatus(id, value) {
  const card = document.querySelector(`[data-status-card="${id}"]`);
  if (!card) return;
  card.classList.remove("status-real", "status-ready", "status-complete", "status-running", "status-smoke", "status-partial", "status-pending", "status-missing", "status-failed", "status-neutral");
  const key = statusKey(value);
  card.classList.add(`status-${key}`);
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
    const timeoutMs = path === "/api/models/status" ? 60000 : 15000;
    res = await fetchWithTimeout(apiURL(path), {}, timeoutMs);
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
  const res = await fetchWithTimeout(apiURL(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }, 130000);
  const payload = await res.json();
  if (!res.ok) {
    const apiError = payload?.error || {};
    throw new ApiError({ code: apiError.code, message: apiError.message, path, status: res.status });
  }
  return payload;
}

async function fetchWithTimeout(resource, options = {}, timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(resource, { ...options, signal: controller.signal });
  } catch (error) {
    if (error.name === "AbortError") throw new Error(`请求超时（${Math.round(timeoutMs / 1000)}s）`);
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function formatApiError(error) {
  if (error instanceof ApiError) {
    return `${error.code}: ${error.message} (${error.path})`;
  }
  return `error: ${error.message || String(error)}`;
}

function renderErrorState(error) {
  const formatted = formatApiError(error);
  text("health", "visual node: ONLINE · evidence source: OFFLINE");
  text("evidenceReady", "read-only");
  text("lastUpdated", "边缘节点在线 · 等待可信算力节点");
  text("heroMetric", "4");
  text("heroMetricSuffix", "");
  text("heroMetricLabel", "核心可信判据");
  text("mainConclusion", "边缘节点在线 · 实时证据源尚未连接");
  text("contrastConclusion", "可浏览系统叙事与交互结构；正式性能结论仍由签名证据门禁单独放行。");
  text("boundaryConclusion", "当前页面处于只读状态，不把离线状态伪装为模型在线或证据已验证。");
  text("heroPrimaryAction", "查看取证流程");
  const bar = document.getElementById("readinessBar");
  if (bar) bar.style.width = "8%";
  const checklist = document.getElementById("artifactChecklist");
  if (checklist) {
    checklist.innerHTML = `
      <div>
        <strong>可视化节点</strong>
        ${badge("online")}
      </div>
      <div>
        <strong>实时证据源</strong>
        ${badge("offline")}
      </div>
    `;
  }
  const track = document.getElementById("tickerTrack");
  if (track) {
    track.innerHTML = `
      <span class="ticker-item is-real"><i class="tk-dot"></i><span class="tk-key">VISUAL</span><span class="tk-val">ONLINE</span></span>
      <span class="ticker-item is-pending"><i class="tk-dot"></i><span class="tk-key">EVIDENCE</span><span class="tk-val">READ-ONLY</span></span>
      <span class="ticker-item is-pending"><i class="tk-dot"></i><span class="tk-key">CLAIMS</span><span class="tk-val">NOT ASSERTED</span></span>`;
    track.style.animation = "none";
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
  return summary?.num_images || summary?.n_images || summary?.images || summary?.requested_images || progress?.num_images || progress?.processed_images || progress?.completed_images || "-";
}

function statusFrom(payload) {
  const summary = payload?.summary || {};
  const progress = payload?.progress || {};
  const artifactStatus = summary.status || progress.status || (payload?.results_csv_exists ? "artifact_present" : "pending");
  if (payload?.claim_valid === true) return "evidence_verified";
  if (artifactStatus !== "pending") return "evidence_review_required";
  return "pending";
}

const ASSET_CHECK_META = {
  dataset_ready: {
    label: "数据集",
    path: "datasets/lfw_full_upload 或 datasets/samples",
    missing: "缺少可用图片，接口在线但无法进入真实样本流程。",
  },
  weights_ready: {
    label: "权重",
    path: "weights/mea、weights/lidmark、weights/kadnet",
    missing: "缺少模型 checkpoint，推理会退化或保持待生成状态。",
  },
  benchmark_ready: {
    label: "Benchmark",
    path: "JYS_REPORT_ROOT 下的 *_benchmark 评测目录",
    missing: "缺少全量评测输出，概览和 Benchmark 表格会显示待生成。",
  },
  aggregate_ready: {
    label: "聚合",
    path: "system/reports/aggregate_real_benchmarks",
    missing: "缺少聚合报告，方法对比和退化曲线无法完整展示。",
  },
  report_ready: {
    label: "报告",
    path: "system/reports/jianyuanshield_competition_report",
    missing: "缺少 JSON / CSV / Markdown 报告包。",
  },
  assets_ready: {
    label: "图表资产",
    path: "system/assets",
    missing: "缺少图表截图或可视化资产。",
  },
};

function readinessSnapshot(payload) {
  const checks = payload.artifacts?.checks || null;
  if (!checks) return { percent: 0, ready: false, missing: [], checks: null };
  const entries = Object.entries(checks);
  const readyCount = entries.filter(([, ok]) => Boolean(ok)).length;
  const percent = entries.length ? Math.round((readyCount / entries.length) * 100) : 0;
  const missing = entries.filter(([, ok]) => !ok).map(([key]) => key);
  return {
    percent: payload.artifacts.ready_for_demo ? 100 : percent,
    ready: Boolean(payload.artifacts.ready_for_demo),
    missing,
    checks,
  };
}

function cleanAttack(payload) {
  return payload?.summary?.attacks?.clean || {};
}

function readComparisonRows(aggregate) {
  return (aggregate?.comparison || []).map((row) => ({
    ...row,
    claimValid: row.claim_valid === true,
    checkpointLabel: row.checkpoint_type || row.mode || row.checkpoint || "-",
    dataLabel: row.data_type || row.data || "-",
    countLabel: row.num_images || row.images || row.count || row.requested_images || "-",
    defenseLabel: row.claim_valid === true ? (row.defense_ready || row.can_use_for_defense || row.can_defense || "yes") : "no",
    statusLabel: row.claim_valid === true ? (row.status || "verified") : "evidence_review_required",
  }));
}

function filterRows(records) {
  if (currentFilter === "all") return records;
  return records.filter((record) => {
    const haystack = `${record.checkpointLabel} ${record.defenseLabel} ${record.statusLabel}`.toLowerCase();
    if (currentFilter === "real") return record.claimValid === true;
    if (currentFilter === "smoke") return haystack.includes("smoke") || haystack.includes("partial") || haystack.includes("running");
    if (currentFilter === "pending") return haystack.includes("pending") || haystack.includes("no") || haystack.includes("failed") || haystack.includes("missing");
    return true;
  });
}

function setImage(id, src) {
  const image = document.getElementById(id);
  if (!image) return;
  if (!src) {
    image.removeAttribute("src");
    delete image.dataset.path;
    image.style.opacity = "0";
    return;
  }
  // 内容路径没变就不动 src，避免每轮轮询都重新下载大图并闪烁
  if (image.dataset.path === src) return;
  image.dataset.path = src;
  image.style.opacity = "0.45";
  image.onload = () => {
    image.style.opacity = "1";
  };
  image.src = `${apiURL(src)}?t=${Date.now()}`;
}

/* 就绪度环 + 状态词：percent 驱动 conic 环（--p 平滑过渡）与数字滚动，
   readinessLabel 仍供 ticker 使用 */
function renderReadiness(percent, label) {
  readinessPercent = percent;
  readinessLabel = label;
  const state = percent >= 90 ? "ready" : percent >= 60 ? "partial" : "low";
  const word = state === "ready" ? "READY" : state === "partial" ? "PARTIAL" : "NEEDS ASSETS";
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
    const snapshot = readinessSnapshot(payload);
    renderReadiness(snapshot.percent, snapshot.ready ? "ready for demo" : `本地资产 ${snapshot.percent}%`);
    text("lastUpdated", `资产 ${payload.artifacts.summary?.status || "unknown"} · 最后同步 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`);
    renderArtifactChecklist(snapshot.checks, payload.artifacts.summary);
    renderAssetDetails(payload);
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
  renderReadiness(percent, `本地资产 ${percent}%`);
  text("lastUpdated", `最后同步 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`);
}

function renderArtifactChecklist(checks, summary) {
  const container = document.getElementById("artifactChecklist");
  if (!container) return;
  container.innerHTML = Object.entries(ASSET_CHECK_META).map(([key, meta]) => `
    <div>
      <strong>${escapeHTML(meta.label)}</strong>
      ${badge(checks?.[key] ? "ready" : "missing")}
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

function renderAssetDetails(payload) {
  const container = document.getElementById("assetDetailList");
  if (!container) return;
  const snapshot = readinessSnapshot(payload);
  const localBadge = document.getElementById("localStatusBadge");
  const localSummary = document.getElementById("localStatusSummary");
  const healthOk = Boolean(payload.health?.ok);

  if (localBadge) {
    localBadge.textContent = healthOk
      ? (snapshot.ready ? "ready" : `${snapshot.missing.length} missing`)
      : "backend failed";
    localBadge.className = `panel-badge ${healthOk ? (snapshot.ready ? "real" : "warning") : "danger"}`;
  }

  if (localSummary) {
    localSummary.textContent = healthOk
      ? (snapshot.ready
        ? "后端在线，运行资产和证据产物已满足当前工作流要求。"
        : `后端在线，但还缺 ${snapshot.missing.length} 类本地资产；这不是前端故障。`)
      : "后端健康检查失败，请先确认 API 服务是否启动。";
  }

  if (!healthOk) {
    container.innerHTML = `
      <div class="asset-detail asset-failed">
        <strong>后端服务异常</strong>
        <span>检查 ${escapeHTML(API)} 是否可访问，或重新启动 uvicorn 服务。</span>
        ${badge("failed")}
      </div>
    `;
    return;
  }

  if (snapshot.ready) {
    container.innerHTML = `
      <div class="asset-detail asset-ready">
        <strong>运行资产完整</strong>
        <span>可以直接进入溯源工作台、可信审计和稳健性评估。</span>
        ${badge("ready")}
      </div>
    `;
    return;
  }

  container.innerHTML = snapshot.missing.map((key) => {
    const meta = ASSET_CHECK_META[key] || { label: key, path: "-", missing: "本地资产未找到。" };
    return `
      <div class="asset-detail">
        <strong>${escapeHTML(meta.label)}</strong>
        <span>${escapeHTML(meta.missing)}<code>${escapeHTML(meta.path)}</code></span>
        ${badge("missing")}
      </div>
    `;
  }).join("");
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
  const records = aggregate?.claim_valid === true
    ? filterRows(readComparisonRows(aggregate))
    : [];
  rows("comparisonRows", records, [
    (r) => escapeHTML(r.method || "-"),
    (r) => badge(r.checkpointLabel),
    (r) => escapeHTML(r.dataLabel),
    num((r) => escapeHTML(r.countLabel)),
    num((r) => fmt(r.clean_bit_error ?? r.mean_bit_error)),
    num((r) => fmtScore(r.clean_bit_accuracy ?? r.mean_bit_accuracy)),
    (r) => badge(r.defenseLabel),
    (r) => badge(r.statusLabel),
  ]);
}


function renderMeaMatrix(mea) {
  const models = mea?.models?.length ? mea.models : ["LIDMark", "KAD-Net", "SepMark", "WaveGuard"];
  const matrix = mea?.matrix || {};
  const badge = document.getElementById("meaMatrixBadge");
  const thead = document.getElementById("meaMatrixHead");
  const tbody = document.getElementById("meaMatrixBody");
  if (!tbody) return;
  if (thead) {
    thead.innerHTML = `<th>Source ↓ / Attacker →</th>${models.map((model) => `<th>${escapeHTML(model)}</th>`).join("")}`;
  }
  if (badge) {
    badge.textContent = mea?.claim_valid ? `verified · n=${mea.images_per_cell}/格` : "evidence review";
    badge.className = `panel-badge ${mea?.claim_valid ? "real" : "warning"}`;
  }
  if (mea?.claim_valid !== true) {
    tbody.innerHTML = `<tr><td colspan="${models.length + 1}"><span class="verdict-warn">矩阵 artifact 尚未通过 checkpoint、数据清单与签名门禁，数值已隐藏</span></td></tr>`;
    tbody.__sig = tbody.innerHTML;
    return;
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
        const first = cell.aggregates?.source_bit_accuracy?.mean ?? cell.first_acc;
        const second = cell.aggregates?.attacker_bit_accuracy?.mean ?? cell.second_acc;
        return `<td style="text-align:center">${gradeIcon(first)} / ${gradeIcon(second)}</td>`;
      }).join("")}
    </tr>`;
  }).join("");
  if (tbody.__sig === html) return;
  tbody.__sig = html;
  tbody.innerHTML = html;
}

function evidencePercent(value, decimals = 2) {
  return `${(Number(value) * 100).toFixed(decimals)}%`;
}

function farVerdict(value) {
  if (value <= 0.05) return "num-ok";
  if (value <= 0.15) return "num-warn";
  return "num-risk";
}

function renderSimSwapEvidence(payload) {
  const badgeElement = document.getElementById("simswapEvidenceBadge");
  const statusElement = document.getElementById("simswapEvidenceStatus");
  const body = document.getElementById("simswapEvidenceRows");
  const gateDetails = document.getElementById("simswapGateDetails");
  if (!badgeElement || !statusElement || !body || !gateDetails) return;
  try {
    if (!TRUST_CONTRACTS) throw new Error("前端证据契约模块未加载");
    const evidence = TRUST_CONTRACTS.validateSimSwapEvidence(payload);
    text("simswapPairCoverage", "256 / 64 / 192");
    text("simswapResultCoverage", "1024 / 1024");
    text("simswapIdentityCoverage", "1792 / 1792");
    text("simswapClaimState", "PUBLISHABLE");
    badgeElement.textContent = "verified · publishable";
    badgeElement.className = "panel-badge real";
    statusElement.textContent = "固定 n256 证据已通过覆盖、实现哈希与签名门禁；身份指标明确限定为流程内 ArcFace 迁移证据（非独立身份验证器）";
    const controlLabels = {
      unwatermarked: "无水印",
      wrong_message: "错误消息",
      cross_record: "跨记录",
    };
    const html = evidence.rows.map((row) => {
      const controls = row.controls.map((control) => `
        <span><b>${escapeHTML(controlLabels[control.name])}</b> ${control.successes}/${control.total}
        → <strong class="${farVerdict(control.high)}">${escapeHTML(evidencePercent(control.high, 2))}</strong></span>`).join("");
      return `<tr>
        <td><span class="simswap-model"><strong>${escapeHTML(row.model)}</strong><small>third-party watermark baseline</small></span></td>
        <td class="num">${row.tar.successes}/${row.tar.total} · ${escapeHTML(evidencePercent(row.tar.estimate, 2))}</td>
        <td class="num">${fmtScore(row.tar.low)}</td>
        <td class="num">${row.far.successes}/${row.far.total} · <span class="${farVerdict(row.far.estimate)}">${escapeHTML(evidencePercent(row.far.estimate, 2))}</span></td>
        <td><span class="simswap-controls">${controls}</span></td>
        <td><span class="simswap-identity"><strong>${escapeHTML(evidencePercent(row.conservativeIdentityLcb, 2))} conservative</strong><small>clean ${escapeHTML(evidencePercent(row.cleanIdentity.low, 2))} · watermarked ${escapeHTML(evidencePercent(row.watermarkedIdentity.low, 2))}</small></span></td>
        <td><span class="simswap-identity"><strong>${escapeHTML(evidencePercent(row.conservativeConditionedLcb, 2))} conservative</strong><small>clean ${row.cleanConditioned.successes}/${row.cleanConditioned.total} · clean+watermarked ${row.watermarkedConditioned.successes}/${row.watermarkedConditioned.total}</small></span></td>
      </tr>`;
    }).join("");
    if (body.__sig !== html) {
      body.__sig = html;
      body.innerHTML = html;
    }
    gateDetails.innerHTML = [
      `<span>implementation hashes<br><strong class="verdict-ok">VERIFIED</strong></span>`,
      `<span>signature profile<br><strong>${escapeHTML(evidence.signature.profile)}</strong></span>`,
      `<span>signer pin<br><strong>${escapeHTML(evidence.signature.public_key_fingerprint_sha256.slice(0, 16))}…</strong></span>`,
      `<span>manifest<br><strong>${escapeHTML(evidence.signature.manifest_sha256.slice(0, 16))}…</strong></span>`,
      `<span>identity scope<br><strong>PIPELINE INTERNAL · independent=false</strong></span>`,
    ].join("");
  } catch (error) {
    text("simswapPairCoverage", "—");
    text("simswapResultCoverage", "—");
    text("simswapIdentityCoverage", "—");
    text("simswapClaimState", "NOT PUBLISHABLE");
    badgeElement.textContent = "不可发布";
    badgeElement.className = "panel-badge danger";
    const failedGates = Object.entries(payload?.release_gate || {})
      .filter(([, value]) => value !== true)
      .map(([key]) => key);
    const suffix = failedGates.length ? ` · 阻断：${failedGates.join(", ")}` : "";
    statusElement.textContent = `不可发布 · ${error.message}${suffix}`;
    const blocked = `<tr><td colspan="7"><span class="verdict-risk">数值已隐藏：真实换脸响应未通过完整发布契约</span></td></tr>`;
    if (body.__sig !== blocked) {
      body.__sig = blocked;
      body.innerHTML = blocked;
    }
    gateDetails.innerHTML = `<span>schema / run_id</span><span>256 / 64 / 192 · 1024 · 1792</span><span>implementation hash</span><span>signature / signer pin</span>`;
  }
}

const MODEL_GATE_REASON = {
  checkpoint_unavailable_or_hash_mismatch: "checkpoint 缺失或哈希不符",
  checkpoint_unregistered: "未登记",
  calibration_unverified: "校准未验收",
  weight_manifest_untrusted: "权重清单未验签",
};

function updateProtectButton() {
  const button = document.getElementById("protectBtn");
  const select = document.getElementById("protectModel");
  const selected = protectModelGate.get(select?.value);
  if (button) button.disabled = protectBusy || selected?.provenance_ready !== true;
}

function renderProvenanceModelStatus(payload) {
  const select = document.getElementById("protectModel");
  const statusElement = document.getElementById("protectModelStatus");
  if (!select || !statusElement) return;
  try {
    if (!TRUST_CONTRACTS) throw new Error("前端模型门禁模块未加载");
    const validated = TRUST_CONTRACTS.validateModelStatus(payload);
    protectModelGate = new Map(validated.options.map((item) => [item.model, item]));
    const current = protectModelGate.get(select.value);
    const selectedModel = current?.provenance_ready ? current.model : validated.preferredModel;
    select.innerHTML = validated.options.map((item) => {
      const reason = item.provenance_ready
        ? "provenance ready"
        : item.reason_codes.map((code) => MODEL_GATE_REASON[code] || code).join(" / ");
      return `<option value="${escapeHTML(item.model)}"${item.provenance_ready ? "" : " disabled"}>${escapeHTML(item.model)} · ${escapeHTML(reason)}</option>`;
    }).join("");
    if (selectedModel) select.value = selectedModel;
    select.disabled = !selectedModel;
    const blocked = validated.options
      .filter((item) => !item.provenance_ready)
      .map((item) => `${item.model}: ${item.reason_codes.map((code) => MODEL_GATE_REASON[code] || code).join("、")}`);
    if (selectedModel) {
      statusElement.textContent = `默认 ${selectedModel} · registered + calibrated + trusted；禁用项：${blocked.join("；") || "无"}`;
      statusElement.className = "model-gate-status ready";
    } else {
      statusElement.textContent = `不可保护：无 provenance-ready 模型 · ${blocked.join("；")}`;
      statusElement.className = "model-gate-status blocked";
    }
  } catch (error) {
    protectModelGate = new Map();
    select.innerHTML = TRUST_CONTRACTS?.MODEL_ORDER?.map((model) => `<option disabled>${escapeHTML(model)} · 状态不可验证</option>`).join("") || "";
    select.disabled = true;
    statusElement.textContent = `不可保护：${error.message}`;
    statusElement.className = "model-gate-status blocked";
  }
  updateProtectButton();
}

/* ═══ 实时证据 Ticker ═══
   汇总各模块状态 / 就绪度 / MEA / 报告 / 审计 / 签名 / 健康为一条横向滚动流。
   内容签名未变则不重建 DOM，避免每轮轮询打断滚动动画。 */
function statusClass(value) {
  const k = statusKey(value);
  if (k === "real") return "is-real";
  if (k === "smoke") return "is-smoke";
  if (k === "missing") return "is-missing";
  if (k === "failed") return "is-failed";
  if (k === "pending") return "is-pending";
  return "";
}

/* 把后端冗长状态（如 real_lfw_benchmark / running）归一成短醒目 token，ticker 更清爽 */
function shortStatus(value) {
  const k = statusKey(value);
  if (k === "real") return "READY";
  if (k === "smoke") return "RUNNING";
  if (k === "missing") return "MISSING";
  if (k === "failed") return "FAILED";
  if (k === "pending") return "WAITING";
  return String(value || "-").toUpperCase();
}

function renderTicker(payload, audit) {
  const track = document.getElementById("tickerTrack");
  if (!track) return;
  const items = [];
  const push = (key, val, statusVal) =>
    items.push({ key, val: val == null || val === "" ? "-" : String(val), cls: statusClass(statusVal ?? val) });

  const mod = (key, s) => push(key, shortStatus(s), s);
  const forensicsView = window.location.hash.replace(/^#\/?/, "") === "forensics";
  if (forensicsView && payload.modelsStatus?.["KAD-Net"]) {
    const kad = payload.modelsStatus["KAD-Net"];
    push("H100", payload.health?.ok ? "ONLINE" : "OFFLINE", payload.health?.ok ? "ready" : "failed");
    push("KAD-Net", kad.provenance_ready ? "READY" : "GATED", kad.provenance_ready ? "ready" : "pending");
    push("登记权重", kad.registered ? "VERIFIED" : "MISSING", kad.registered ? "ready" : "missing");
    push("校准阈值", kad.verification_threshold == null ? "-" : `${(Number(kad.verification_threshold) * 100).toFixed(1)}%`, kad.calibrated ? "ready" : "pending");
    push("证据签名", kad.trusted ? "PINNED" : "REVIEW", kad.trusted ? "ready" : "pending");
    push("保护→传播→溯源", "LIVE", kad.provenance_ready ? "ready" : "pending");
  } else {
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
    push(
      "SimSwap n256",
      payload.simswap?.claim_valid === true ? "PUBLISHABLE" : "BLOCKED",
      payload.simswap?.claim_valid === true ? "ready" : "pending",
    );
    push("报告", payload.report?.exists?.json ? "ready" : "pending");
  }
  if (!forensicsView && audit) {
    const blocking = (audit.blocking_findings || []).length;
    push("审计阻断", blocking, blocking === 0 ? "ready" : "pending");
    const sig = audit.signature || {};
    push("Ed25519", sig.verified ? "verified" : (sig.status || "pending"), sig.verified ? "ready" : "pending");
  }
  if (!forensicsView && payload.claims) {
    push(
      "CLAIMS",
      payload.claims.ready_for_claims ? "PUBLISHABLE" : "REVIEW",
      payload.claims.ready_for_claims ? "ready" : "pending",
    );
  }
  if (!forensicsView) push("HEALTH", payload.health?.ok ? "OK" : "FAIL", payload.health?.ok ? "ready" : "pending");

  const itemHTML = items.map((it) =>
    `<span class="ticker-item ${it.cls}"><i class="tk-dot"></i><span class="tk-key">${escapeHTML(it.key)}</span><span class="tk-val">${escapeHTML(it.val)}</span></span>`
  ).join("");
  if (track.__sig === itemHTML) return;
  track.__sig = itemHTML;
  track.innerHTML = itemHTML;
}

function renderPayload(payload) {
  const { health, modules, hidden, sepmark, lidmark, waveguard, kadnet, meaMatrix, simswap, modelsStatus, aggregate, report, claims } = payload;
  const localReady = readinessSnapshot(payload);

  text("apiEndpoint", `API · ${API.replace(/^https?:\/\//, "")}`);
  text("health", `health: ${health.ok ? "OK" : "FAIL"}`);

  const statusMap = {
    hiddenStatus: statusFrom(hidden),
    sepmarkStatus: statusFrom(sepmark),
    lidmarkStatus: statusFrom(lidmark),
    waveguardStatus: statusFrom(waveguard),
    reportStatus: report.claim_valid ? "evidence_verified" : (report.exists?.json ? "evidence_review_required" : "pending"),
    kadnetStatus: statusFrom(kadnet),
  };

  Object.entries(statusMap).forEach(([id, value]) => {
    text(id, value);
    setCardStatus(id, value);
  });

  const evidenceCount = (item, summary, progress, pending) => {
    if (item?.claim_valid !== true) return "证据待复核 · 数值隐藏";
    const count = sampleCount(summary, progress);
    return count === "-" ? pending : `${count} images`;
  };
  const waveguardFormal = waveguard.full_benchmark?.claim_valid === true
    ? waveguard.full_benchmark
    : waveguard.small_benchmark?.claim_valid === true
      ? waveguard.small_benchmark
      : null;
  text("hiddenCount", evidenceCount(hidden, hidden.summary, hidden.progress, "等待 benchmark 结果"));
  text("sepmarkCount", evidenceCount(sepmark, sepmark.summary, sepmark.progress, "等待 benchmark 结果"));
  text("lidmarkCount", evidenceCount(lidmark, lidmark.summary, lidmark.progress, "等待 LIDMark eval 结果"));
  text("waveguardCount", waveguardFormal
    ? evidenceCount(waveguardFormal, waveguardFormal.summary, waveguardFormal.progress, "等待 WaveGuard 结果")
    : "证据待复核 · 数值隐藏");
  text("kadnetCount", evidenceCount(kadnet, kadnet.summary, {}, "等待 KAD-Net 结果"));
  text("aggregatePath", aggregate.report_md_path || "pending");

  countField("heroMetric", localReady.percent, { decimals: 0 });
  text("heroMetricSuffix", "%");
  text("heroPrimaryAction", "上传图片取证");
  text("heroMetricLabel", "本地资产就绪度");
  text(
    "mainConclusion",
    health.ok
      ? (localReady.ready ? "本机状态：后端在线 · 运行资产完整" : `本机状态：后端在线 · 缺少 ${localReady.missing.length} 类本地资产`)
      : "本机状态：后端健康检查失败",
  );
  text(
    "contrastConclusion",
    claims?.ready_for_claims
      ? "声明门禁：全部必需证据已验证，可发布结论"
      : `声明门禁：研究复核中 · ${claims?.summary?.blocked_required ?? "-"} 项必需声明被阻断`,
  );
  text(
    "boundaryConclusion",
    "真实 Deepfake、性能数字与司法效力须由签名 artifact 单独放行；simulation 不进入结论。",
  );

  updateReadiness(payload);
  renderMeaMatrix(meaMatrix);
  renderSimSwapEvidence(simswap);
  renderProvenanceModelStatus(modelsStatus);
  renderModules(modules);
  renderComparison(aggregate);

  rows("hiddenRows", hidden.claim_valid === true ? attackSummaries(hidden.summary) : [], [
    (r) => badge(r.attack_type || r.attack || "-"),
    num((r) => fmt(r.mean_bit_error)),
    num((r) => fmtScore(r.mean_bit_accuracy)),
    num((r) => fmt(r.mean_psnr)),
    num((r) => fmt(r.mean_ssim)),
    num((r) => fmtScore(r.success_rate)),
  ]);

  rows("sepmarkRows", sepmark.claim_valid === true ? attackSummaries(sepmark.summary) : [], [
    (r) => badge(r.attack_type || r.attack || "-"),
    num((r) => fmt(r.mean_bit_error)),
    num((r) => fmtScore(r.mean_bit_accuracy)),
    num((r) => fmt(r.mean_bit_error_rf)),
    num((r) => fmtScore(r.mean_bit_accuracy_rf)),
    num((r) => fmtScore(r.success_rate)),
  ]);

  rows("waveguardRows", waveguardFormal ? attackSummaries(waveguardFormal.summary) : [], [
    (r) => badge(r.attack_type || r.attack || "-"),
    num((r) => fmt(r.mean_bit_error_tracer ?? r.mean_bit_error)),
    num((r) => fmtScore(r.mean_bit_accuracy_tracer ?? r.mean_bit_accuracy)),
    num((r) => fmt(r.mean_bit_error_detector)),
    num((r) => fmtScore(r.mean_bit_accuracy_detector)),
    num((r) => fmtScore(r.success_rate)),
  ]);

  rows("kadnetRows", kadnet.claim_valid === true ? attackSummaries(kadnet.summary) : [], [
    (r) => badge(r.attack_type || r.attack || "-"),
    num((r) => fmt(r.mean_bit_error)),
    num((r) => fmtScore(r.mean_bit_accuracy)),
    num((r) => fmt(r.mean_psnr)),
    num((r) => fmt(r.mean_ssim)),
    num((r) => fmtScore(r.success_rate)),
  ]);

  setImage("hiddenGrid", hidden.claim_valid === true ? hidden.grid_image : null);
  setImage("sepmarkGrid", sepmark.claim_valid === true ? sepmark.grid_image : null);
  setImage("degradationCurve", aggregate.claim_valid === true ? aggregate.degradation_curve : null);

  document.getElementById("lidmarkJson").textContent = JSON.stringify({
    claim_valid: lidmark.claim_valid === true,
    claim_status: lidmark.claim_status,
    checkpoint_type: lidmark.checkpoint_type,
    summary: lidmark.claim_valid === true ? lidmark.summary : "hidden_until_evidence_gate_passes",
  }, null, 2);

  document.getElementById("waveguardJson").textContent = JSON.stringify({
    claim_valid: Boolean(waveguardFormal),
    claim_status: waveguardFormal?.claim_status || "evidence_review_required",
    checkpoint_type: waveguardFormal?.checkpoint_type || waveguard.checkpoint_type,
    summary: waveguardFormal?.summary || "hidden_until_evidence_gate_passes",
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
    `<div class="audit-item"><strong>release gate</strong><span>运行状态与研究结论发布状态独立计算；阻断项 ${escapeHTML((audit.blocking_findings || []).length)} 个。</span>${badge(audit.ready_for_claims ? "ready" : "review")}</div>`,
    `<div class="audit-item"><strong>Ed25519 signature</strong><span>${escapeHTML(signature.status || "not_generated")} · fingerprint ${escapeHTML((signature.public_key_fingerprint_sha256 || "-").slice(0, 16))}</span>${badge(signature.verified ? "ready" : "review")}</div>`,
    ...findings.map((item) => `<div class="audit-item"><strong>${escapeHTML(item.code)}</strong><span>${escapeHTML(item.message)}</span>${badge(item.severity)}</div>`),
    ...limits.map((message) => `<div class="audit-item"><strong>protocol</strong><span>${escapeHTML(message)}</span>${badge("review")}</div>`),
  ].join("") || `<div class="audit-item"><strong>verified</strong><span>未发现自动审计异常</span>${badge("ready")}</div>`;
}

function renderDemo(result) {
  const source = result.execution_valid ? "checkpoint 单样本执行" : "simulation";
  text("demoStatus", `${result.task_id} · ${source} · 正式声明未放行`);
  const artifacts = document.getElementById("demoArtifacts");
  artifacts.innerHTML = Object.entries(result.artifacts || {}).map(([name, src]) => `
    <figure><img src="${escapeHTML(apiURL(src))}" alt="${escapeHTML(name)}"><figcaption>${escapeHTML(name)}</figcaption></figure>
  `).join("");
  document.getElementById("demoEvidence").textContent = JSON.stringify({
    mode: result.mode,
    execution_valid: result.execution_valid,
    claim_valid: result.claim_valid,
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
  ["simswap", "/api/benchmark/simswap-lfw"],
  ["modelsStatus", "/api/models/status"],
  ["aggregate", "/api/benchmark/aggregate"],
  ["report", "/api/competition-report"],
  ["audit", "/api/evidence/audit"],
  ["claims", "/api/claims"],
];

async function load() {
  try {
    const activeView = window.location.hash.replace(/^#\/?/, "") || "overview";
    // 现场取证页只请求运行闭环必需的数据，避免同时验算整套 benchmark
    // 证据包而占满推理节点；切到其他视图时再加载完整证据面板。
    const selectedEndpoints = activeView === "forensics"
      ? ENDPOINTS.filter(([key]) => ["health", "modelsStatus"].includes(key))
      : ENDPOINTS;
    // allSettled：单个接口失败只降级对应面板，不拖垮整页
    const results = await Promise.allSettled(selectedEndpoints.map(([, path]) => getJSON(path)));
    const data = {};
    const failed = [];
    results.forEach((res, index) => {
      const [key, path] = selectedEndpoints[index];
      if (res.status === "fulfilled") {
        data[key] = res.value;
      } else {
        data[key] = null;
        failed.push({ key, path, error: res.reason });
      }
    });

    // 后端整体不可用才进入整页错误态
    if (failed.length === selectedEndpoints.length) {
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
      simswap: data.simswap || {},
      modelsStatus: data.modelsStatus || {},
      aggregate: data.aggregate || {},
      report: data.report || { exists: {} },
      claims: data.claims || { ready_for_claims: false, summary: {} },
    };
    renderPayload(lastPayload);

    if (activeView === "forensics") {
      const readyModels = Object.entries(lastPayload.modelsStatus || {})
        .filter(([, status]) => status && typeof status === "object" && status.provenance_ready === true)
        .map(([model]) => model);
      if (lastPayload.health.ok && readyModels.length) {
        renderReadiness(100, `H100 · ${readyModels.join(" + ")} ready`);
        text("lastUpdated", `H100 实机推理已就绪 · ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`);
      }
    }

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
  overview: { title: "资产总览", sub: "运行状态、可信资产与证据边界" },
  forensics: { title: "溯源工作台", sub: "保护登记、传播变换与盲核验" },
  benchmark: { title: "稳健性评估", sub: "统一协议、方法对比与退化曲线" },
  audit: { title: "可信审计", sub: "协议、实现、权重与签名证据" },
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

window.addEventListener("hashchange", () => {
  applyRoute();
  load();
});
applyRoute();

/* ═══ 社会背景与政策响应：自动轮播，可手动选择 ═══ */

const POLICY_STEPS = [
  {
    year: "2022",
    tag: "治理起点",
    title: "互联网信息服务深度合成管理规定",
    text: "深度合成服务提供者应对生成或编辑的信息内容采取技术措施添加标识。项目以主动水印与取证记录响应“可识别、可追溯”的技术需求。",
    source: "https://www.cac.gov.cn/2022-12/11/c_1672221949354811.htm",
  },
  {
    year: "2023",
    tag: "发展与安全",
    title: "生成式人工智能服务管理暂行办法",
    text: "政策同时强调促进生成式人工智能健康发展、规范应用和保护合法权益。项目把技术创新与失败关闭、证据边界共同纳入系统设计。",
    source: "https://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm",
  },
  {
    year: "2025",
    tag: "全链路标识",
    title: "人工智能生成合成内容标识办法",
    text: "显式标识、文件元数据隐式标识与传播服务责任形成协同要求，并于 2025 年 9 月 1 日施行。项目重点补充跨攻击鲁棒核验和争议证据链。",
    source: "https://www.cac.gov.cn/2025-03/14/c_1743654685899683.htm",
  },
  {
    year: "JYS",
    tag: "项目响应",
    title: "鉴源盾 · 可验证内容身份基础设施",
    text: "从创作时登记，到传播后盲解码，再到争议时验签；以统一攻击协议检验标识经历压缩、换脸和二次嵌入后的恢复能力。",
    source: "#/forensics",
  },
];

let policyIndex = 0;
let policyTimer;

function renderPolicy(index) {
  policyIndex = (index + POLICY_STEPS.length) % POLICY_STEPS.length;
  const step = POLICY_STEPS[policyIndex];
  document.querySelectorAll("[data-policy-index]").forEach((button, buttonIndex) => button.classList.toggle("active", buttonIndex === policyIndex));
  document.getElementById("policyYear").textContent = step.year;
  document.getElementById("policyTag").textContent = step.tag;
  document.getElementById("policyDetailTitle").textContent = step.title;
  document.getElementById("policyDetailText").textContent = step.text;
  const source = document.getElementById("policySource");
  source.href = step.source;
  source.textContent = policyIndex === POLICY_STEPS.length - 1 ? "进入溯源工作台 →" : "查看官方原文 ↗";
  if (step.source.startsWith("#")) {
    source.removeAttribute("target");
    source.removeAttribute("rel");
  } else {
    source.target = "_blank";
    source.rel = "noopener noreferrer";
  }
}

function startPolicyRotation() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  clearInterval(policyTimer);
  policyTimer = setInterval(() => renderPolicy(policyIndex + 1), 5200);
}

document.querySelectorAll("[data-policy-index]").forEach((button) => {
  button.addEventListener("click", () => {
    renderPolicy(Number(button.dataset.policyIndex));
    startPolicyRotation();
  });
});
const policyStage = document.querySelector(".policy-stage");
policyStage?.addEventListener("mouseenter", () => clearInterval(policyTimer));
policyStage?.addEventListener("mouseleave", startPolicyRotation);
policyStage?.addEventListener("focusin", () => clearInterval(policyTimer));
policyStage?.addEventListener("focusout", startPolicyRotation);
startPolicyRotation();

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
  link.href = apiURL(`/api/competition-report/download/${link.dataset.reportFormat}`);
});

document.querySelectorAll("[data-signature-file]").forEach((link) => {
  link.href = apiURL(`/api/evidence/signature/download/${link.dataset.signatureFile}`);
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

/* 本地传播实验：所有变换都由浏览器 Canvas 真实生成，不伪造模型核验结果。 */
const localEvidence = {
  sourceFile: null,
  sourceHash: "",
  registeredHash: "",
  currentBlob: null,
  currentHash: "",
  attacks: [],
};

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

async function sha256Blob(blob) {
  const buffer = await blob.arrayBuffer();
  if (globalThis.crypto?.subtle) {
    const digest = await crypto.subtle.digest("SHA-256", buffer);
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  }
  /* 公网节点暂为 HTTP；WebCrypto 在非安全上下文不可用，因此使用同算法的本地实现。 */
  const bytes = new Uint8Array(buffer);
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  const bitLength = bytes.length * 8;
  view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000), false);
  view.setUint32(paddedLength - 4, bitLength >>> 0, false);
  const constants = [
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
  ];
  const state = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
  const words = new Uint32Array(64);
  const rotate = (value, count) => (value >>> count) | (value << (32 - count));
  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let i = 0; i < 16; i += 1) words[i] = view.getUint32(offset + i * 4, false);
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotate(words[i - 15], 7) ^ rotate(words[i - 15], 18) ^ (words[i - 15] >>> 3);
      const s1 = rotate(words[i - 2], 17) ^ rotate(words[i - 2], 19) ^ (words[i - 2] >>> 10);
      words[i] = (words[i - 16] + s0 + words[i - 7] + s1) >>> 0;
    }
    let [a,b,c,d,e,f,g,h] = state;
    for (let i = 0; i < 64; i += 1) {
      const sum1 = rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25);
      const choice = (e & f) ^ (~e & g);
      const temp1 = (h + sum1 + choice + constants[i] + words[i]) >>> 0;
      const sum0 = rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (sum0 + majority) >>> 0;
      h = g; g = f; f = e; e = (d + temp1) >>> 0; d = c; c = b; b = a; a = (temp1 + temp2) >>> 0;
    }
    [a,b,c,d,e,f,g,h].forEach((value, index) => { state[index] = (state[index] + value) >>> 0; });
  }
  return state.map((value) => value.toString(16).padStart(8, "0")).join("");
}

function shortHash(hash) {
  return hash ? `${hash.slice(0, 12)}…${hash.slice(-8)}` : "—";
}

function canvasToBlob(canvas, type = "image/png", quality) {
  return new Promise((resolve, reject) => canvas.toBlob(
    (blob) => blob ? resolve(blob) : reject(new Error("浏览器未能生成传播文件")),
    type,
    quality,
  ));
}

function base64ToBlob(base64, type = "image/png") {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return new Blob([bytes], { type });
}

async function imageFromBlob(blob) {
  const url = URL.createObjectURL(blob);
  try {
    const image = new Image();
    image.decoding = "async";
    image.src = url;
    await image.decode();
    return image;
  } finally {
    URL.revokeObjectURL(url);
  }
}

function drawImageToAttackCanvas(image, width = image.naturalWidth, height = image.naturalHeight) {
  const canvas = document.getElementById("attackCanvas");
  const longest = Math.max(width, height);
  const scale = longest > 1400 ? 1400 / longest : 1;
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const context = canvas.getContext("2d", { alpha: true });
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  document.getElementById("attackPlaceholder").hidden = true;
}

function setDemoProgress(step) {
  document.querySelectorAll(".demo-progress li").forEach((item, index) => {
    item.classList.toggle("active", index === step - 1);
    item.classList.toggle("completed", index < step - 1);
  });
}

function addDemoTimeline(title, detail) {
  const timeline = document.getElementById("demoEvidenceTimeline");
  if (!timeline) return;
  if (timeline.dataset.started !== "true") {
    timeline.innerHTML = "";
    timeline.dataset.started = "true";
  }
  const now = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  const item = document.createElement("li");
  item.innerHTML = `<time>${escapeHTML(now)}</time><div><strong>${escapeHTML(title)}</strong><small>${escapeHTML(detail)}</small></div>`;
  timeline.appendChild(item);
}

function setVerdict(name, label, state, note) {
  const output = document.getElementById(`verdict${name}`);
  const noteNode = document.getElementById(`verdict${name}Note`);
  const article = output?.closest("article");
  if (output) output.textContent = label;
  if (noteNode) noteNode.textContent = note;
  if (article) {
    article.classList.remove("pass", "fail", "review");
    if (state) article.classList.add(state);
  }
}

function resetLiveVerdicts() {
  setVerdict("Exact", "原图", "pass", "当前文件与上传原图字节一致");
  setVerdict("Watermark", "待登记", "review", "必须由真实模型完成盲解码");
  setVerdict("Metadata", "未检查", "review", "Canvas 传播后将重新编码标识层");
  setVerdict("Claim", "待门禁", "review", "登记、校准、阈值与签名共同放行");
  text("liveScore", "—");
  text("liveThreshold", "—");
}

async function refreshAttackArtifact(type = "image/png", quality) {
  const canvas = document.getElementById("attackCanvas");
  localEvidence.currentBlob = await canvasToBlob(canvas, type, quality);
  localEvidence.currentHash = await sha256Blob(localEvidence.currentBlob);
}

async function loadSourceImage(file) {
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) throw new Error("图片超过 5 MB，请更换现场样本");
  const image = await imageFromBlob(file);
  localEvidence.sourceFile = file;
  localEvidence.sourceHash = await sha256Blob(file);
  localEvidence.registeredHash = localEvidence.sourceHash;
  localEvidence.attacks = [];
  drawImageToAttackCanvas(image);
  localEvidence.currentBlob = file;
  localEvidence.currentHash = localEvidence.sourceHash;

  const preview = document.getElementById("sourcePreview");
  if (preview.dataset.objectUrl) URL.revokeObjectURL(preview.dataset.objectUrl);
  const previewUrl = URL.createObjectURL(file);
  preview.dataset.objectUrl = previewUrl;
  preview.src = previewUrl;
  preview.hidden = false;
  document.getElementById("sourcePlaceholder").hidden = true;
  document.getElementById("sourceFileMeta").innerHTML = `
    <div><dt>文件</dt><dd title="${escapeHTML(file.name)}">${escapeHTML(file.name)} · ${formatBytes(file.size)}</dd></div>
    <div><dt>尺寸</dt><dd>${image.naturalWidth} × ${image.naturalHeight} px</dd></div>
    <div><dt>SHA-256</dt><dd title="${localEvidence.sourceHash}">${shortHash(localEvidence.sourceHash)}</dd></div>`;
  document.querySelectorAll("[data-local-attack]").forEach((button) => { button.disabled = false; });
  document.getElementById("useAttackForVerify").disabled = false;
  document.getElementById("attackLog").innerHTML = '<span class="done">原始版本已装载</span>';
  resetLiveVerdicts();
  setDemoProgress(1);
  addDemoTimeline("原始内容进入浏览器", `${file.name} · ${image.naturalWidth}×${image.naturalHeight} · SHA-256 ${shortHash(localEvidence.sourceHash)}`);
  text("protectStatus", "原图已就绪；填写创作者引用后可保护登记");
}

document.getElementById("protectFile")?.addEventListener("change", async (event) => {
  try {
    await loadSourceImage(event.target.files?.[0]);
  } catch (error) {
    event.target.value = "";
    text("protectStatus", `图片读取失败：${error.message}`);
  }
});

document.querySelectorAll("[data-local-attack]").forEach((button) => {
  button.disabled = true;
  button.addEventListener("click", async () => {
    if (!localEvidence.currentBlob) return;
    const type = button.dataset.localAttack;
    button.disabled = true;
    try {
      const canvas = document.getElementById("attackCanvas");
      const copy = document.createElement("canvas");
      copy.width = canvas.width;
      copy.height = canvas.height;
      copy.getContext("2d").drawImage(canvas, 0, 0);
      let label = "";

      if (type === "jpeg") {
        await refreshAttackArtifact("image/jpeg", .55);
        drawImageToAttackCanvas(await imageFromBlob(localEvidence.currentBlob));
        label = "JPEG 55%";
      } else if (type === "crop") {
        const cropWidth = Math.max(1, Math.round(copy.width * .8));
        const cropHeight = Math.max(1, Math.round(copy.height * .8));
        canvas.width = cropWidth;
        canvas.height = cropHeight;
        canvas.getContext("2d").drawImage(copy, (copy.width - cropWidth) / 2, (copy.height - cropHeight) / 2, cropWidth, cropHeight, 0, 0, cropWidth, cropHeight);
        label = "中心裁剪 80%";
      } else if (type === "resize") {
        canvas.width = Math.max(1, Math.round(copy.width * .75));
        canvas.height = Math.max(1, Math.round(copy.height * .75));
        canvas.getContext("2d").drawImage(copy, 0, 0, canvas.width, canvas.height);
        label = "缩放至 75%";
      } else if (type === "metadata") {
        label = "元数据移除";
      }

      if (type !== "jpeg") await refreshAttackArtifact("image/png");
      localEvidence.attacks.push(label);
      const chip = document.createElement("span");
      chip.className = "done";
      chip.textContent = `${localEvidence.attacks.length}. ${label}`;
      document.getElementById("attackLog").appendChild(chip);
      setVerdict("Exact", localEvidence.currentHash === localEvidence.registeredHash ? "一致" : "不一致", localEvidence.currentHash === localEvidence.registeredHash ? "pass" : "fail", `传播文件 SHA-256 ${shortHash(localEvidence.currentHash)}`);
      setVerdict("Metadata", "已移除", "fail", "浏览器重编码不会保留原文件元数据");
      setVerdict("Watermark", "待盲核验", "review", "视觉相似不能替代解码结果");
      setVerdict("Claim", "待门禁", "review", "需以盲核验事件和签名记录判断");
      setDemoProgress(3);
      addDemoTimeline("生成传播版本", `${localEvidence.attacks.join(" → ")} · ${canvas.width}×${canvas.height} · ${formatBytes(localEvidence.currentBlob.size)}`);
    } catch (error) {
      addDemoTimeline("传播变换失败", error.message);
    } finally {
      button.disabled = false;
    }
  });
});

document.getElementById("useAttackForVerify")?.addEventListener("click", () => {
  if (!localEvidence.currentBlob) return;
  const extension = localEvidence.currentBlob.type === "image/jpeg" ? "jpg" : "png";
  const file = new File([localEvidence.currentBlob], `propagated-${Date.now()}.${extension}`, { type: localEvidence.currentBlob.type });
  try {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    const input = document.getElementById("verifyFile");
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    text("verifyStatus", `传播版本已送入 · ${formatBytes(file.size)} · 点击执行 Decode Only`);
    setDemoProgress(4);
    addDemoTimeline("传播版本送入核验", `${file.name} · 只提交观测图片与 content_id`);
    document.getElementById("verifyForm").scrollIntoView({ behavior: "smooth", block: "center" });
  } catch (error) {
    text("verifyStatus", `浏览器无法自动装载文件：${error.message}`);
  }
});

function formalEvidenceBadge(result, expectedProvenance) {
  const valid = result?.mode === "real_checkpoint"
    && result?.claim_valid === true
    && result?.result_provenance === expectedProvenance
    && result?.checkpoint_registered === true
    && result?.checkpoint_calibrated === true
    && result?.evidence_signature?.signed === true;
  return valid
    ? '<span class="verdict-ok">✔ checkpoint、校准与签名门禁通过</span>'
    : '<span class="verdict-warn">⚠ 操作完成，但正式证据未放行</span>';
}

document.getElementById("protectForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const model = document.getElementById("protectModel").value;
  const protectFile = document.getElementById("protectFile").files[0];
  if (!protectFile) {
    text("protectStatus", "请先选择原创图片");
    return;
  }
  if (protectModelGate.get(model)?.provenance_ready !== true) {
    text("protectStatus", "不可保护：所选模型未同时通过 checkpoint 登记、校准与签名清单门禁");
    updateProtectButton();
    return;
  }
  protectBusy = true;
  updateProtectButton();
  text("protectStatus", "正在嵌入唯一来源消息并登记…");
  document.getElementById("protectResult").innerHTML = "";
  try {
    const fd = new FormData();
    fd.append("file", protectFile);
    fd.append("creator_ref", document.getElementById("creatorRef").value);
    fd.append("model", model);
    const res = await fetchWithTimeout(apiURL("/api/provenance/protect"), { method: "POST", body: fd }, 240000);
    const result = await res.json();
    if (!res.ok) throw new Error((result.error && result.error.message) || res.statusText);
    document.getElementById("verifyContentId").value = result.content_id;
    const imageSource = result.protected_image?.png_base64
      ? `data:image/png;base64,${result.protected_image.png_base64}`
      : apiURL(result.protected_image?.url || "/api/invalid-artifact");
    document.getElementById("protectResult").innerHTML = `
      <details class="registration-receipt">
        <summary><span>登记回执</span><code>${escapeHTML(shortHash(result.content_id))}</code></summary>
        <div class="registration-receipt-body">
          <figure><img src="${escapeHTML(imageSource)}" alt="已保护图片"><figcaption>protected asset</figcaption></figure>
          <div class="infer-metric-row">
            <span>内容 ID</span><strong>${escapeHTML(result.content_id)}</strong>
            <span>创作者引用</span><strong>${escapeHTML(result.creator_ref)}</strong>
            <span>原图留存</span><strong>${result.privacy?.original_persisted ? "是" : "否"}</strong>
            <span>正式证据</span><strong>${formalEvidenceBadge(result, "registered_protection_record")}</strong>
          </div>
        </div>
      </details>`;
    document.getElementById("protectEvidence").textContent = JSON.stringify(result, null, 2);
    text("protectStatus", `保护与登记完成 · ${result.content_id} · ${result.evidence_status}`);
    try {
      let protectedBlob;
      if (result.protected_image?.png_base64) {
        protectedBlob = base64ToBlob(result.protected_image.png_base64);
      } else {
        const artifactResponse = await fetch(imageSource);
        if (!artifactResponse.ok) throw new Error("保护图下载失败");
        protectedBlob = await artifactResponse.blob();
      }
      const protectedImage = await imageFromBlob(protectedBlob);
      drawImageToAttackCanvas(protectedImage);
      localEvidence.currentBlob = protectedBlob;
      localEvidence.currentHash = await sha256Blob(protectedBlob);
      localEvidence.registeredHash = result.protected_sha256 || localEvidence.currentHash;
      localEvidence.attacks = [];
      document.getElementById("attackLog").innerHTML = '<span class="done">已保护版本进入传播台</span>';
      document.getElementById("useAttackForVerify").disabled = false;
      setVerdict("Exact", "登记版本", "pass", `受保护文件 SHA-256 ${shortHash(localEvidence.registeredHash)}`);
      setVerdict("Metadata", result.aigc_labeling ? "完整" : "未声明", result.aigc_labeling ? "pass" : "review", result.aigc_labeling ? "GB 45438-2025 标识已写入保护图" : "本次保护未请求 AIGC 显式标识");
      addDemoTimeline("受保护版本进入传播台", `${formatBytes(protectedBlob.size)} · checkpoint ${shortHash(result.checkpoint_sha256)}`);
    } catch (artifactError) {
      addDemoTimeline("保护图未能进入传播台", artifactError.message);
    }
    setVerdict("Watermark", "已嵌入", "pass", `已登记内容 ID ${result.content_id}`);
    setVerdict("Claim", result.claim_valid === true ? "登记有效" : "待核验", result.claim_valid === true ? "pass" : "review", result.claim_valid === true ? "来源登记已通过当前证据门禁" : "仍需传播后盲核验事件收口");
    setDemoProgress(2);
    addDemoTimeline("创建来源登记", `${result.content_id} · ${result.creator_ref} · ${result.evidence_status || "状态未返回"}`);
  } catch (err) {
    text("protectStatus", `失败：${err.message}`);
    addDemoTimeline("来源登记未完成", err.message);
  } finally {
    protectBusy = false;
    updateProtectButton();
  }
});

document.getElementById("verifyForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const btn = document.getElementById("verifyBtn");
  const verifyFile = document.getElementById("verifyFile").files[0];
  if (!verifyFile) {
    text("verifyStatus", "请先装载传播后图片");
    return;
  }
  btn.disabled = true;
  text("verifyStatus", "正在盲解码并查询登记记录…");
  document.getElementById("verifyResult").innerHTML = "";
  try {
    const fd = new FormData();
    fd.append("file", verifyFile);
    fd.append("content_id", document.getElementById("verifyContentId").value.trim());
    const res = await fetchWithTimeout(apiURL("/api/provenance/verify"), { method: "POST", body: fd }, 240000);
    const result = await res.json();
    if (!res.ok) throw new Error((result.error && result.error.message) || res.statusText);
    document.getElementById("verifyResult").innerHTML = `<div class="infer-metric-row">
      <span>登记消息匹配</span><strong>${result.verified ? '<span class="verdict-ok">✔ 达到协议阈值</span>' : '<span class="verdict-risk">✘ 未达到协议阈值</span>'}</strong>
      <span>Bit Accuracy</span><strong>${Number.isFinite(Number(result.bit_accuracy)) ? (Number(result.bit_accuracy) * 100).toFixed(1) + "%" : "—"}</strong>
      <span>精确文件匹配</span><strong>${result.exact_protected_file_match ? "是" : "否（可能经历传播变换）"}</strong>
      <span>登记主体</span><strong>${escapeHTML(result.creator_ref)}</strong>
      <span>正式证据</span><strong>${formalEvidenceBadge(result, "registered_blind_verification")}</strong>
    </div>`;
    document.getElementById("verifyEvidence").textContent = JSON.stringify(result, null, 2);
    text("verifyStatus", `${result.verified ? "消息匹配" : "消息不匹配"} · event_id: ${result.event_id}`);
    const score = Number(result.bit_accuracy);
    const thresholdCandidate = result.verification_threshold ?? result.success_threshold ?? result.threshold ?? result.registered_threshold ?? result.protocol_threshold ?? result.decision_threshold;
    const threshold = Number(thresholdCandidate);
    setVerdict("Exact", result.exact_protected_file_match ? "一致" : "不一致", result.exact_protected_file_match ? "pass" : "fail", result.exact_protected_file_match ? "观测文件与已保护文件字节完全一致" : "文件变化不等于来源关系失效");
    setVerdict("Watermark", result.verified ? "恢复成功" : "未达阈值", result.verified ? "pass" : "fail", Number.isFinite(score) ? `Bit Accuracy ${(score * 100).toFixed(1)}%` : "服务端未返回有效恢复得分");
    if (typeof result.aigc_metadata_intact === "boolean") {
      setVerdict("Metadata", result.aigc_metadata_intact ? "完整" : "缺失", result.aigc_metadata_intact ? "pass" : "fail", "结果来自服务端标识完整性检查");
    } else {
      setVerdict("Metadata", "未判定", "review", "当前核验接口未返回元数据完整性证据");
    }
    setVerdict("Claim", result.claim_valid === true ? "有效" : "未放行", result.claim_valid === true ? "pass" : "fail", result.claim_valid === true ? "模型登记、校准、阈值与签名门禁均通过" : "至少一项正式证据门禁未通过");
    text("liveScore", Number.isFinite(score) ? `${(score * 100).toFixed(1)}%` : "—");
    text("liveThreshold", Number.isFinite(threshold) ? `${(threshold * 100).toFixed(1)}%` : "接口未返回");
    setDemoProgress(5);
    addDemoTimeline("盲核验事件写入", `${result.event_id || "event_id 未返回"} · ${result.verified ? "登记消息恢复" : "未达到登记阈值"} · claim ${result.claim_valid === true ? "valid" : "not released"}`);
  } catch (err) {
    text("verifyStatus", `失败：${err.message}`);
    setVerdict("Watermark", "无结果", "review", "核验服务未返回可验证结果");
    setVerdict("Claim", "未放行", "review", "没有盲核验事件，不形成来源结论");
    addDemoTimeline("盲核验未完成", err.message);
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
    const res = await fetchWithTimeout(apiURL("/api/compliance/batch"), { method: "POST", body: fd }, 130000);
    const result = await res.json();
    if (!res.ok) throw new Error((result.error && result.error.message) || res.statusText);
    const rate = result.compliance_rate == null ? null : (result.compliance_rate * 100).toFixed(0);
    document.getElementById("batchStatus").textContent = rate == null
      ? `未执行合规判定 · ${result.warning || result.reason || "blind detector 不可用"}`
      : `检测完成 · ${result.total} 张 · 合规率 ${rate}% · 模式: ${result.mode}`;
    document.getElementById("batchResults").innerHTML = `
      <div class="batch-summary">
        <span class="verdict-warn">${escapeHTML(result.warning || "等待盲检能力")}</span>
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

const COLLABORATION_PROFILES = {
  balanced: { risk_aversion: 0.6, fidelity_weight: 0.2, minimum_worst_case_protocol_normalized_margin: 0.45 },
  security: { risk_aversion: 0.9, fidelity_weight: 0.1, minimum_worst_case_protocol_normalized_margin: 0.7 },
  quality: { risk_aversion: 0.4, fidelity_weight: 0.45, minimum_worst_case_protocol_normalized_margin: 0.45 },
};

function collaborationPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : "—";
}

function assertCollaborationResponse(result, requestedThreats, requestedProfile) {
  const contracts = globalThis.JYSTrustContracts;
  if (!contracts?.validateCollaborationResponse) {
    throw new Error("协同信任合约未加载");
  }
  return contracts.validateCollaborationResponse(
    result,
    requestedThreats,
    requestedProfile,
  ).response;
}

document.getElementById("collaborationForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.getElementById("collaborationRun");
  const status = document.getElementById("collaborationStatus");
  const output = document.getElementById("collaborationResult");
  const badgeElement = document.getElementById("collaborationBadge");
  const threats = [...document.querySelectorAll('input[name="collaborationThreat"]:checked')]
    .map((input) => ({ model: input.value, exposure: 1.0 }));
  if (!threats.length) {
    status.textContent = "至少选择一个二次嵌入威胁模型";
    output.innerHTML = "";
    badgeElement.textContent = "fail closed";
    badgeElement.className = "panel-badge warning";
    return;
  }
  const profileName = document.getElementById("collaborationProfile").value;
  const profile = COLLABORATION_PROFILES[profileName] || COLLABORATION_PROFILES.balanced;
  button.disabled = true;
  status.textContent = "正在验签逐图证据并计算 217 身份簇置信前沿…";
  output.innerHTML = "";
  badgeElement.textContent = "verifying";
  badgeElement.className = "panel-badge muted";
  try {
    const result = assertCollaborationResponse(await postJSON("/api/collaboration/recommend", {
      threats,
      candidate_models: ["LIDMark", "KAD-Net", "SepMark", "WaveGuard"],
      ...profile,
    }), threats, profile);
    const selected = result.recommendation;
    const ranking = (result.ranking || []).map((item, index) => `
      <tr>
        <td>#${index + 1}</td>
        <td><strong>${escapeHTML(item.model)}</strong>${item.pareto_optimal ? ' <span class="status-badge">Pareto</span>' : ""}</td>
        <td class="num">${escapeHTML(Number(item.score).toFixed(3))}</td>
        <td class="num">${escapeHTML(collaborationPercent(item.expected_source_protocol_normalized_margin_cluster_lcb))}</td>
        <td class="num">${escapeHTML(collaborationPercent(item.worst_case_source_protocol_normalized_margin_cluster_lcb))}</td>
      </tr>`).join("");
    const classLabels = {
      coexistence: ["共存风险观测", "verdict-ok"],
      source_dominant: ["来源占优", "verdict-warn"],
      source_overwritten: ["来源被覆盖", "verdict-risk"],
      destructive_collision: ["破坏性冲突", "verdict-risk"],
    };
    const interactions = (result.interaction_plan || []).map((item) => {
      const meta = classLabels[item.class] || [item.class || "未知", "verdict-risk"];
      return `<article class="collaboration-cell">
        <div><strong>${escapeHTML(item.attacker_model)}</strong><span class="${meta[1]}">${escapeHTML(meta[0])}</span></div>
        <small>来源归一化 margin 聚类 LCB ${escapeHTML(collaborationPercent(item.source_protocol_normalized_margin_cluster_lcb))} · 后嵌 ${escapeHTML(collaborationPercent(item.attacker_protocol_normalized_margin_cluster_lcb))}</small>
        <code>PLANNED POLICY HINT · ${escapeHTML(item.policy_hint || "planned_block_second_embedding")}</code>
      </article>`;
    }).join("");
    const evidence = result.evidence || {};
    const releaseSignature = evidence.release_signature || {};
    const scoring = result.scoring || {};
    const stability = scoring.selection_stability || {};
    const ablation = result.ablation || {};
    const legacyModel = ablation.legacy_iid_raw_accuracy?.selected_model || "none";
    const selectedFrequency = collaborationPercent(stability.selected_model_frequency);
    output.innerHTML = `
      <div class="collaboration-hero">
        <span>RECOMMENDED SINGLE-MODEL DEPLOYMENT</span>
        <strong>${escapeHTML(selected.model)}</strong>
        <small>置信调整得分 ${escapeHTML(Number(selected.score).toFixed(3))} · 最差协议归一化 margin 聚类 LCB ${escapeHTML(collaborationPercent(selected.worst_case_source_protocol_normalized_margin_cluster_lcb))}</small>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>Rank</th><th>Model</th><th>Score</th><th>期望 margin 聚类 LCB</th><th>最差 margin 聚类 LCB</th></tr></thead>
        <tbody>${ranking}</tbody>
      </table></div>
      <div class="collaboration-cells">${interactions}</div>
      <pre class="collaboration-evidence">images=${escapeHTML(evidence.image_count ?? "—")} identities=${escapeHTML(evidence.identity_count ?? "—")} repeated_identities=${escapeHTML(evidence.repeated_identity_count ?? "—")} max_cluster=${escapeHTML(evidence.max_cluster_size ?? "—")}
bootstrap=${escapeHTML(scoring.uncertainty_method || "—")} seed=${escapeHTML(scoring.bootstrap_seed ?? "—")} resamples=${escapeHTML(scoring.bootstrap_resamples ?? "—")} family=${escapeHTML(scoring.family_size ?? "—")}
selection_stability=${escapeHTML(selectedFrequency)} old_iid=${escapeHTML(legacyModel)} new_cluster=${escapeHTML(ablation.identity_cluster_normalized_policy_selected_model || "none")} changed=${escapeHTML(String(ablation.selection_changed))}
cells=${escapeHTML(evidence.cells ?? "—")} rows=${escapeHTML(evidence.rows ?? "—")}
policy=${escapeHTML(evidence.policy_sha256 || "—")}
summary=${escapeHTML(evidence.summary_sha256 || "—")}
protocol=${escapeHTML(evidence.protocol_sha256 || "—")}
manifest=${escapeHTML(releaseSignature.manifest_sha256 || "—")}
signer=${escapeHTML(releaseSignature.public_key_fingerprint_sha256 || "—")}</pre>`;
    status.textContent = "部署建议已生成但未自动执行 · 217 身份等权、96 项选择族与 20,000 次聚类重采样可复算";
    badgeElement.textContent = "evidence verified";
    badgeElement.className = "panel-badge real";
  } catch (error) {
    status.textContent = `策略阻断：${formatApiError(error)}`;
    badgeElement.textContent = "fail closed";
    badgeElement.className = "panel-badge warning";
  } finally {
    button.disabled = false;
  }
});

document.getElementById("meaForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const btn = document.getElementById("meaBtn");
  btn.disabled = true;
  document.getElementById("meaStatus").textContent = "对比推理中（4个正式候选）…";
  document.getElementById("meaResults").innerHTML = "";
  try {
    const file = document.getElementById("meaFile").files[0];
    const attack = document.getElementById("meaAttack").value;
    const results = await Promise.all(["LIDMark", "KAD-Net", "SepMark", "WaveGuard"].map(async (model) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("model", model);
      fd.append("attack", attack);
      fd.append("return_b64", "true");
      const res = await fetchWithTimeout(apiURL("/api/infer/single"), { method: "POST", body: fd }, 130000);
      const body = await res.json();
      if (!res.ok) throw new Error((body.error && body.error.message) || `HTTP ${res.status}`);
      return body;
    }));
    const allCheckpoint = results.every((result) => result.execution_valid === true);
    document.getElementById("meaStatus").textContent = allCheckpoint
      ? "checkpoint 单样本对比完成 · 不代表正式 Benchmark 结论"
      : "流程模拟完成 · 不可用于性能结论";
    document.getElementById("meaResults").innerHTML = `<div class="mea-grid">` +
      results.map((result) => {
        const m = result.metrics || {};
        const acc = m.bit_accuracy_tracer != null ? m.bit_accuracy_tracer
          : m.bit_accuracy_c != null ? m.bit_accuracy_c
          : m.bit_accuracy_detector != null ? m.bit_accuracy_detector : m.bit_accuracy;
        const imgs = result.artifacts_b64 || {};
        return `<div class="mea-card">
          <h4>${escapeHTML(result.model)} <small>${result.execution_valid ? "checkpoint 单样本 · 未放行" : "simulation · 不可作结论"}</small></h4>
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
            <span>声明状态</span><strong><span class="verdict-warn">待正式 Benchmark 证据</span></strong>
          </div>
        </div>`;
      }).join("") + `</div>`;
  } catch (err) {
    document.getElementById("meaStatus").textContent = "错误: " + err.message;
  } finally {
    btn.disabled = false;
  }
});
