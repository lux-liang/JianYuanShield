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
let sourceImportBusy = false;
let verifyImportBusy = false;
let appStarted = false;
let pollTimer = null;
let gpuStatus = null;
let routeMotionTimer = null;
let dashboardIntroTimer = null;

// Authentication is owned by the same-origin gateway. The signed session is
// kept in a Secure/HttpOnly cookie; JavaScript retains only the per-session
// CSRF value returned by the gateway and never stores a password or bearer token.
const LEGACY_ACCESS_SESSION_KEYS = Object.freeze(["jys.demo.access.v1", "jys.demo.access.v2"]);
const ACCESS_FALLBACK_NAME = "鉴源管理员";
let accessSession = null;

function removeLegacyAccessSessions() {
  try { LEGACY_ACCESS_SESSION_KEYS.forEach((key) => window.sessionStorage.removeItem(key)); } catch (_) { /* storage unavailable */ }
  try { LEGACY_ACCESS_SESSION_KEYS.forEach((key) => window.localStorage.removeItem(key)); } catch (_) { /* storage unavailable */ }
}

function normalizeAccessPayload(payload) {
  const session = payload?.session || payload;
  if (!session || typeof session !== "object" || !session.username) return null;
  const csrfToken = payload?.csrf || payload?.csrf_token || payload?.csrfToken || session.csrf_token || session.csrfToken;
  return {
    username: String(session.username),
    displayName: String(session.display_name || session.displayName || ACCESS_FALLBACK_NAME),
    role: String(session.role || "平台访问"),
    expiresAt: Number(session.expires_at || session.expiresAt || 0),
    csrfToken: typeof csrfToken === "string" ? csrfToken : "",
  };
}

function sessionHeaders(base = {}) {
  const headers = { ...base };
  if (accessSession?.csrfToken) headers["X-JYS-CSRF"] = accessSession.csrfToken;
  return headers;
}

async function sessionRequest(path, options = {}) {
  const response = await fetchWithTimeout(apiURL(path), options, 15000);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.error?.message || payload?.message || `HTTP ${response.status}`;
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function closeUserMenu() {
  const menu = document.getElementById("userMenu");
  const trigger = document.getElementById("userTrigger");
  if (menu) menu.hidden = true;
  if (trigger) trigger.setAttribute("aria-expanded", "false");
}

function showApplication(session) {
  const login = document.getElementById("loginView");
  const shell = document.getElementById("appShell");
  if (login) login.hidden = true;
  if (shell) shell.hidden = false;
  document.body.classList.remove("login-active");
  document.body.classList.add("authenticated");
  const displayName = session.displayName || ACCESS_FALLBACK_NAME;
  text("userDisplayName", displayName);
  text("userMenuName", displayName);
  text("userAvatar", displayName.slice(0, 1));
  text("profileDisplayName", displayName);
  text("profileAvatar", displayName.slice(0, 1));
  text("profileApiEndpoint", API.endsWith("/api") ? API : `${API}/api`);
  beginDashboardIntro();
  startApplication();
}

function showLogin() {
  const login = document.getElementById("loginView");
  const shell = document.getElementById("appShell");
  if (shell) shell.hidden = true;
  if (login) login.hidden = false;
  document.body.classList.remove("authenticated");
  document.body.classList.add("login-active");
  closeUserMenu();
}

async function initializeAccess() {
  const form = document.getElementById("loginForm");
  const username = document.getElementById("loginUsername");
  const password = document.getElementById("loginPassword");
  const remember = document.getElementById("rememberSession");
  const error = document.getElementById("loginError");
  const passwordToggle = document.getElementById("passwordToggle");
  const trigger = document.getElementById("userTrigger");

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    error.textContent = "正在建立安全会话…";
    try {
      const payload = await sessionRequest("/api/session/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: username.value.trim(),
          password: password.value,
          remember: Boolean(remember.checked),
        }),
      });
      const session = normalizeAccessPayload(payload);
      if (!session?.csrfToken) throw new Error("会话响应不完整，请联系管理员");
      accessSession = session;
      error.textContent = "";
      form.classList.remove("login-shake");
      password.value = "";
      showApplication(session);
    } catch (loginError) {
      error.textContent = loginError.status === 429
        ? "尝试次数过多，请稍后再试。"
        : loginError.status === 503
          ? "安全会话服务暂不可用，请联系管理员。"
          : "账号或访问口令有误，请重新输入。";
      form.classList.remove("login-shake");
      void form.offsetWidth;
      form.classList.add("login-shake");
      password.value = "";
      password.focus();
    } finally {
      submit.disabled = false;
    }
  });

  passwordToggle?.addEventListener("click", () => {
    const reveal = password.type === "password";
    password.type = reveal ? "text" : "password";
    passwordToggle.setAttribute("aria-pressed", String(reveal));
    passwordToggle.setAttribute("aria-label", reveal ? "隐藏访问口令" : "显示访问口令");
    password.focus();
  });

  trigger?.addEventListener("click", () => {
    const menu = document.getElementById("userMenu");
    const open = menu?.hidden !== false;
    if (menu) menu.hidden = !open;
    trigger.setAttribute("aria-expanded", String(open));
  });

  const logout = async () => {
    try {
      await sessionRequest("/api/session/logout", {
        method: "POST",
        headers: sessionHeaders({ "Content-Type": "application/json" }),
        body: "{}",
      });
    } catch (_) { /* local logout still completes if the gateway is unavailable */ }
    accessSession = null;
    stopApplication();
    showLogin();
    form?.reset();
    error.textContent = "";
    window.setTimeout(() => username?.focus(), 0);
  };
  document.getElementById("logoutButton")?.addEventListener("click", logout);
  document.getElementById("profileLogoutButton")?.addEventListener("click", logout);

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".user-control")) closeUserMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeUserMenu();
  });

  removeLegacyAccessSessions();
  try {
    const payload = await sessionRequest("/api/session");
    const session = normalizeAccessPayload(payload);
    if (!session?.csrfToken) throw new Error("invalid session response");
    accessSession = session;
    showApplication(session);
  } catch (_) {
    accessSession = null;
    showLogin();
    window.setTimeout(() => username?.focus(), 0);
  }
}

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
  if (["待补测", "缺少基线"].some((key) => raw.includes(key))) return "missing";
  if (["待复核", "待验证", "等待", "待校验"].some((key) => raw.includes(key))) return "pending";
  if (["已验证", "已实测", "实测可用", "实证可用", "已就绪"].some((key) => raw.includes(key))) return "real";
  if (["unverified", "review_required", "review", "blocked", "unavailable", "proxy_only", "not_assessed"].some((key) => raw.includes(key))) return "pending";
  if (["missing", "not_found", "not_ready", "incomplete", "not_generated"].some((key) => raw.includes(key))) return "missing";
  if (["failed", "read_failed", "unreachable", "network_error", "http_error"].some((key) => raw.includes(key))) return "failed";
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
  if (card.closest("#view-overview")) {
    card.hidden = key !== "real";
    const summary = card.closest(".summary-row");
    if (summary) summary.hidden = ![...summary.querySelectorAll(".stat")].some((item) => item.classList.contains("status-real"));
  }
}

/* cells 数组项：函数（普通列）或 { fn, cls }（如数值右对齐列）
   内容签名（__sig）未变则跳过重建，避免每轮 30s 轮询都重放 rowIn 入场动画 */
function rows(containerId, records, cells, emptyLabel = "等待评测数据") {
  const body = document.getElementById(containerId);
  if (!body) return;
  let html;
  if (!records || records.length === 0) {
    html = `<tr><td colspan="${cells.length}">${badge(emptyLabel)}</td></tr>`;
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

async function getJSON(path, requestedTimeoutMs = null) {
  let res;
  try {
    const endpointTimeouts = {
      "/api/models/status": 60000,
      "/api/evidence/audit": 90000,
      "/api/competition-report": 60000,
      "/api/claims": 60000,
    };
    const timeoutMs = requestedTimeoutMs || endpointTimeouts[path] || 15000;
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
    headers: sessionHeaders({ "Content-Type": "application/json" }),
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
    const response = await fetch(resource, { credentials: "same-origin", ...options, signal: controller.signal });
    if (response.status === 401 && accessSession) {
      accessSession = null;
      stopApplication();
      showLogin();
    }
    return response;
  } catch (error) {
    if (error.name === "AbortError") throw new Error(`请求超时（${Math.round(timeoutMs / 1000)}s）`);
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function formatApiError(error) {
  if (error instanceof ApiError) {
    return `请求失败 · ${error.message} · ${error.path}`;
  }
  return `请求失败 · ${error.message || String(error)}`;
}

function renderErrorState(error) {
  const formatted = formatApiError(error);
  console.warn("[JYS] evidence refresh:", formatted);
  text("heroMetric", "H100");
  text("heroMetricSuffix", "");
  text("heroMetricLabel", "在线取证算力");
  text("mainConclusion", "H100 算力链路正在建立");
  text("contrastConclusion", "图片上传后将进入保护、传播变换与盲解码裁决流程。");
  text("boundaryConclusion", "链路恢复后，显存、利用率、温度与推理队列会自动刷新。");
  text("heroPrimaryAction", "上传图片取证");
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
  if (payload?.claim_valid === true) return "实测已验证";
  if (payload?.normalized?.status === "missing") return "基线待补测";
  if (artifactStatus !== "pending") return "研究评测待复核";
  return "等待评测";
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
    missing: "缺少模型权重，推理会退化或保持待生成状态。",
  },
  benchmark_ready: {
    label: "评测产物",
    path: "JYS_REPORT_ROOT 下的 *_benchmark 评测目录",
    missing: "缺少全量评测输出，概览和攻击实验表格会显示待生成。",
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

function aggregateEvidenceReady(aggregate) {
  const summary = aggregate?.summary || {};
  const required = Array.isArray(summary.required_methods) ? summary.required_methods : [];
  const complete = new Set(Array.isArray(summary.complete_methods) ? summary.complete_methods : []);
  const sources = summary.sources || {};
  const signature = summary.evidence_signature || {};
  return summary.status === "complete"
    && required.length > 0
    && required.every((method) => complete.has(method)
      && sources?.[method]?.status === "complete"
      && (sources?.[method]?.failed_requirements || []).length === 0)
    && signature.verified === true
    && signature.signer_pinned === true;
}

function readComparisonRows(aggregate) {
  const aggregateVerified = aggregateEvidenceReady(aggregate);
  const sourceRows = aggregate?.comparison?.length
    ? aggregate.comparison
    : (aggregate?.summary?.rows || []);
  return sourceRows.map((row) => {
    const claimValid = row.claim_valid === true || aggregateVerified;
    return ({
      ...row,
      claimValid,
      checkpointLabel: humanWeightStatus(row.checkpoint_type || row.mode || row.checkpoint),
      dataLabel: row.data_type || row.data || "-",
      countLabel: row.num_images || row.images || row.count || row.requested_images || "-",
      defenseLabel: claimValid ? "实测可用" : "研究评测",
      statusLabel: claimValid ? "签名证据已验证" : "待复核",
    });
  });
}

function humanWeightStatus(value) {
  const raw = String(value || "").toLowerCase();
  if (raw.includes("official") || raw.includes("real")) return "正式权重";
  if (raw.includes("smoke") || raw.includes("partial")) return "流程权重";
  if (raw.includes("missing") || raw.includes("unavailable")) return "权重待补充";
  return value || "状态待确认";
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

/* 证据就绪度仅服务评测视图；页眉环由 H100 实时显存状态驱动。 */
function renderReadiness(percent, label) {
  readinessPercent = percent;
  readinessLabel = label;
}

function updateReadiness(payload) {
  if (payload.artifacts?.checks) {
    const snapshot = readinessSnapshot(payload);
    renderReadiness(snapshot.percent, snapshot.ready ? "演示就绪" : `本地资产 ${snapshot.percent}%`);
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
        <strong>${escapeHTML(summary.dataset_images || 0)} images / ${escapeHTML(summary.checkpoint_files || 0)} weights</strong>
        ${badge(summary.status || "待确认")}
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
  const healthOk = Boolean(payload.health?.ok || payload.artifacts?.checks);

  if (localBadge) {
    localBadge.textContent = healthOk
      ? (snapshot.ready ? "就绪" : `${snapshot.missing.length} 项待补充`)
      : "后端异常";
    localBadge.className = `panel-badge ${healthOk ? (snapshot.ready ? "real" : "warning") : "danger"}`;
  }

  if (localSummary) {
    localSummary.textContent = healthOk
      ? (snapshot.ready
        ? "后端在线，运行资产和证据产物已满足当前工作流要求。"
        : `后端在线；仍缺 ${snapshot.missing.length} 类本地资产，前端运行正常。`)
      : "后端健康检查失败，请先确认 API 服务是否启动。";
  }

  if (!healthOk) {
    container.innerHTML = `
      <div class="asset-detail asset-failed">
        <strong>后端服务异常</strong>
        <span>检查 ${escapeHTML(API)} 是否可访问，或重新启动接口服务进程。</span>
        ${badge("failed")}
      </div>
    `;
    return;
  }

  if (!snapshot.checks) {
    if (localBadge) {
      localBadge.textContent = "待确认";
      localBadge.className = "panel-badge muted";
    }
    if (localSummary) localSummary.textContent = "资产清单接口暂未返回完整检查项，已保留可用工作流。";
    container.innerHTML = `
      <div class="asset-detail asset-pending">
        <strong>资产清单待同步</strong>
        <span>当前页面仍可浏览模型状态与已发布证据，完整资产检查将在接口恢复后自动补齐。</span>
        ${badge("待确认")}
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

function moduleNameLabel(value) {
  return String(value || "-").replace("Deepfake 攻击模拟", "换脸攻击模拟");
}

function moduleFunctionLabel(value) {
  return String(value || "-")
    .replaceAll("baseline", "基线")
    .replaceAll("checkpoint-backed validation required", "需要基于模型权重完成验证")
    .replaceAll("official SimSwap/LFW n256 evidence is signature gated", "官方 SimSwap/LFW n256 证据受签名门禁保护")
    .replaceAll("protocol and adapter contract implemented", "协议与适配器契约已实现")
    .replaceAll("repository-tracked checkpoint matrix required", "需要仓库登记的权重矩阵")
    .replaceAll("decode-only provenance API implemented", "仅解码的来源接口已实现")
    .replaceAll("unavailable checkpoints fail closed", "权重不可用时按失败关闭")
    .replaceAll("claim-as-code gate blocks unverified performance claims", "声明即代码门禁会阻断未验证性能主张");
}

function moduleStatusLabel(value) {
  const labels = {
    implemented_pending_validation: "已实现 · 待验证",
    real_n256_evidence_available: "n256 实证可用",
    protocol_ready_results_pending: "协议就绪 · 结果待补",
    evidence_review_required: "证据待复核",
  };
  return labels[String(value || "")] || shortStatus(value);
}

function renderModules(modules) {
  const moduleList = document.getElementById("moduleList");
  if (!moduleList) return;
  const html = modules.map((item) => `
    <section class="module-item">
      <div class="badge-slot"><strong>${escapeHTML(moduleNameLabel(item.name))}</strong>${badge(moduleStatusLabel(item.result))}</div>
      <p>${escapeHTML(moduleFunctionLabel(item.function))}</p>
      <small>${escapeHTML(moduleFunctionLabel(item.model_status))}</small>
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
    (r) => badge(r.attack || r.attack_type || "-"),
    (r) => badge(r.checkpointLabel),
    (r) => escapeHTML(r.dataLabel),
    num((r) => escapeHTML(r.countLabel)),
    num((r) => fmt(r.clean_bit_error ?? r.mean_bit_error)),
    num((r) => fmtScore(r.clean_bit_accuracy ?? r.mean_bit_accuracy)),
    (r) => badge(r.defenseLabel),
    (r) => badge(r.statusLabel),
  ], "四模型汇总评测正在生成");
}


function renderMeaMatrix(mea) {
  const models = mea?.models?.length ? mea.models : ["LIDMark", "KAD-Net", "SepMark", "WaveGuard"];
  const matrix = mea?.matrix || {};
  const badge = document.getElementById("meaMatrixBadge");
  const thead = document.getElementById("meaMatrixHead");
  const tbody = document.getElementById("meaMatrixBody");
  if (!tbody) return;
  if (thead) {
    thead.innerHTML = `<th>来源模型 ↓ / 后嵌模型 →</th>${models.map((model) => `<th>${escapeHTML(model)}</th>`).join("")}`;
  }
  if (badge) {
    badge.textContent = mea?.claim_valid ? `实测已验证 · n=${mea.images_per_cell}/格` : "研究矩阵待复核";
    badge.className = `panel-badge ${mea?.claim_valid ? "real" : "warning"}`;
  }
  const hasMatrix = models.some((source) => Object.keys(matrix[source] || {}).length > 0);
  if (!hasMatrix) {
    tbody.innerHTML = `<tr><td colspan="${models.length + 1}"><span class="verdict-warn">有向冲突矩阵正在生成，完成后自动载入</span></td></tr>`;
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

function researchWilsonMetric(value) {
  const successes = Number(value?.successes);
  const total = Number(value?.total);
  const estimate = Number(value?.estimate);
  const low = Number(value?.wilson_95_low);
  const high = Number(value?.wilson_95_high);
  if (![successes, total, estimate, low, high].every(Number.isFinite) || total <= 0) return null;
  return { successes, total, estimate, low, high };
}

function readResearchSimSwapRows(payload) {
  const order = TRUST_CONTRACTS?.MODEL_ORDER || Object.keys(payload?.model_results || {});
  return order.map((model) => {
    const result = payload?.model_results?.[model];
    if (result?.status !== "complete") return null;
    const tar = researchWilsonMetric(result.holdout?.tar);
    const far = researchWilsonMetric(result.holdout?.far);
    const cleanIdentity = researchWilsonMetric(result.identity_migration?.clean_swap);
    const watermarkedIdentity = researchWilsonMetric(result.identity_migration?.watermarked_swap);
    const controls = ["unwatermarked", "wrong_message", "cross_record"].map((name) => {
      const metric = researchWilsonMetric(result.holdout?.far_by_negative_control?.[name]);
      return metric ? { name, ...metric } : null;
    }).filter(Boolean);
    if (!tar || !far || !cleanIdentity || !watermarkedIdentity || controls.length !== 3) return null;
    return {
      model,
      tar,
      far,
      controls,
      cleanIdentity,
      watermarkedIdentity,
      conservativeIdentityLcb: Math.min(cleanIdentity.low, watermarkedIdentity.low),
    };
  }).filter(Boolean);
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
    text("simswapClaimState", "已验证");
    badgeElement.textContent = "签名证据已验证";
    badgeElement.className = "panel-badge real";
    statusElement.textContent = "固定 n256 实测已通过覆盖、实现哈希与签名校验；身份指标用于衡量本次换脸流程中的身份迁移一致性";
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
        <td><span class="simswap-model"><strong>${escapeHTML(row.model)}</strong><small>第三方主动水印对照模型</small></span></td>
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
      `<span>实现哈希<br><strong class="verdict-ok">已验证</strong></span>`,
      `<span>签名配置<br><strong>${escapeHTML(evidence.signature.profile)}</strong></span>`,
      `<span>签名者指纹<br><strong>${escapeHTML(evidence.signature.public_key_fingerprint_sha256.slice(0, 16))}…</strong></span>`,
      `<span>证据清单<br><strong>${escapeHTML(evidence.signature.manifest_sha256.slice(0, 16))}…</strong></span>`,
      `<span>身份指标范围<br><strong>本次换脸流程内验证</strong></span>`,
    ].join("");
  } catch (error) {
    const coverage = payload?.coverage || {};
    const researchRows = readResearchSimSwapRows(payload);
    const hasResearchEvidence = researchRows.length > 0;
    text("simswapPairCoverage", hasResearchEvidence
      ? `${coverage.num_pairs || "—"} / ${coverage.calibration_pairs || "—"} / ${coverage.holdout_pairs || "—"}`
      : "—");
    text("simswapResultCoverage", hasResearchEvidence
      ? `${coverage.result_rows || "—"} / ${coverage.expected_result_rows || "—"}`
      : "—");
    text("simswapIdentityCoverage", hasResearchEvidence
      ? `${coverage.identity_embedding_rows || "—"} / ${coverage.expected_identity_embedding_rows || "—"}`
      : "—");
    text("simswapClaimState", hasResearchEvidence ? "研究实测" : "待复核");
    badgeElement.textContent = hasResearchEvidence ? "完整实测 · 签名待补全" : "证据校验待复核";
    badgeElement.className = "panel-badge warning";
    const failedGates = Object.entries(payload?.release_gate || {})
      .filter(([, value]) => value !== true)
      .map(([key]) => key);
    statusElement.textContent = hasResearchEvidence
      ? "4 个模型的换脸留出集、负对照与身份迁移结果均已完成；资产清单、实现哈希和签名信任待补全，当前按研究评测呈现"
      : "本轮未形成可比结论：缺少完整样本覆盖或签名证据包，已按失败关闭处理";
    const controlLabels = {
      unwatermarked: "无水印",
      wrong_message: "错误消息",
      cross_record: "跨记录",
    };
    const blocked = hasResearchEvidence
      ? researchRows.map((row) => {
        const controls = row.controls.map((control) => `
          <span><b>${escapeHTML(controlLabels[control.name])}</b> ${control.successes}/${control.total}
          → <strong class="${farVerdict(control.high)}">${escapeHTML(evidencePercent(control.high, 2))}</strong></span>`).join("");
        return `<tr>
          <td><span class="simswap-model"><strong>${escapeHTML(row.model)}</strong><small>第三方主动水印基线</small></span></td>
          <td class="num">${row.tar.successes}/${row.tar.total} · ${escapeHTML(evidencePercent(row.tar.estimate, 2))}</td>
          <td class="num">${fmtScore(row.tar.low)}</td>
          <td class="num">${row.far.successes}/${row.far.total} · <span class="${farVerdict(row.far.estimate)}">${escapeHTML(evidencePercent(row.far.estimate, 2))}</span></td>
          <td><span class="simswap-controls">${controls}</span></td>
          <td><span class="simswap-identity"><strong>${escapeHTML(evidencePercent(row.conservativeIdentityLcb, 2))} 保守下界</strong><small>原始 ${escapeHTML(evidencePercent(row.cleanIdentity.low, 2))} · 水印 ${escapeHTML(evidencePercent(row.watermarkedIdentity.low, 2))}</small></span></td>
          <td><span class="simswap-identity"><strong>待签名证据补全</strong><small>完整签名响应后自动载入</small></span></td>
        </tr>`;
      }).join("")
      : `<tr><td colspan="7"><span class="verdict-warn">本轮未形成可比结论 · 缺少完整样本覆盖或签名证据包，已按失败关闭处理</span></td></tr>`;
    if (body.__sig !== blocked) {
      body.__sig = blocked;
      body.innerHTML = blocked;
    }
    gateDetails.innerHTML = hasResearchEvidence
      ? [
        `<span>数据结构 / 运行编号<br><strong class="verdict-ok">已匹配</strong></span>`,
        `<span>核心覆盖<br><strong>${escapeHTML(`${coverage.result_rows || "—"}/${coverage.expected_result_rows || "—"} 条结果`)}</strong></span>`,
        `<span>待补证据<br><strong>${escapeHTML(failedGates.length ? `${failedGates.length} 项` : "签名复核")}</strong></span>`,
        `<span>当前口径<br><strong>研究评测</strong></span>`,
      ].join("")
      : `<span>数据结构 / 运行编号</span><span>样本覆盖</span><span>实现哈希</span><span>签名 / 签名者指纹</span>`;
  }
}

const MODEL_GATE_REASON = {
  checkpoint_unavailable_or_hash_mismatch: "模型文件缺失或完整性校验未通过",
  checkpoint_unregistered: "模型权重未纳入可信清单",
  calibration_unverified: "核验阈值待校准",
  weight_manifest_untrusted: "模型清单签名待验证",
};

function updateProtectButton() {
  const button = document.getElementById("protectBtn");
  const select = document.getElementById("protectModel");
  const selected = protectModelGate.get(select?.value);
  if (button) button.disabled = protectBusy || sourceImportBusy || selected?.available !== true;
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
    const selectedModel = current?.available ? current.model : validated.preferredModel;
    select.innerHTML = validated.options.map((item) =>
      `<option value="${escapeHTML(item.model)}"${item.available ? "" : " disabled"}>${escapeHTML(item.model)}</option>`
    ).join("");
    if (selectedModel) select.value = selectedModel;
    select.disabled = !selectedModel;
    const unavailable = validated.options
      .filter((item) => !item.available)
      .map((item) => `${item.model}: ${item.reason_codes.map((code) => MODEL_GATE_REASON[code] || code).join("、")}`);
    if (selectedModel) {
      const selectedStatus = protectModelGate.get(selectedModel);
      const modeLabel = selectedStatus?.provenance_ready
        ? "来源登记模型已验证"
        : "模型可运行 · 当前用于研究演示";
      const details = [
        modeLabel,
      ].filter(Boolean);
      statusElement.textContent = details.join(" · ");
      statusElement.className = selectedStatus?.provenance_ready ? "model-gate-status ready" : "model-gate-status research";
    } else {
      statusElement.textContent = `当前没有可运行的主动水印模型：${unavailable.join("；") || "请检查模型服务"}`;
      statusElement.className = "model-gate-status blocked";
    }
  } catch (error) {
    protectModelGate = new Map();
    select.innerHTML = TRUST_CONTRACTS?.MODEL_ORDER?.map((model) => `<option disabled>${escapeHTML(model)} · 状态不可验证</option>`).join("") || "";
    select.disabled = true;
    statusElement.textContent = `来源登记暂不可用：${error.message}`;
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
  const labels = {
    real: "就绪",
    smoke: "运行中",
    missing: "待补充",
    failed: "失败",
    pending: "待复核",
    neutral: "待确认",
  };
  const key = statusKey(value);
  return labels[key] || String(value || "-");
}

function renderGpuConnectionState(message = "正在连接在线算力") {
  const ring = document.getElementById("readinessRing");
  if (ring) {
    ring.style.setProperty("--p", 0);
    ring.classList.remove("rs-ready", "rs-partial", "rs-low");
    ring.classList.add("rs-partial");
  }
  text("readinessRingPct", "--");
  text("evidenceReady", "正在连接 H100");
  text("lastUpdated", message);
  text("health", "H100 · 连接中");
  text("profileGpuStatus", "正在连接 H100");
  updateOverviewFlowState();
  renderTicker(lastPayload || {}, lastPayload?.audit);
}

function renderGpuStatus(status) {
  if (!status?.ok || !status.gpu?.memory) {
    renderGpuConnectionState();
    return;
  }
  gpuStatus = status;
  const ring = document.getElementById("readinessRing");
  if (ring) {
    ring.style.setProperty("--p", 100);
    ring.classList.remove("rs-ready", "rs-partial", "rs-low");
    ring.classList.add("rs-ready");
  }
  text("readinessRingPct", "ON");
  text("evidenceReady", "H100 在线");
  text("lastUpdated", "在线取证算力可用");
  text("health", "H100 · 在线");
  text("profileGpuStatus", "H100 在线算力已连接");
  updateOverviewFlowState({ online: true });

  const activeView = window.location.hash.replace(/^#\/?/, "") || "overview";
  if (activeView === "overview") {
    text("heroMetric", "H100");
    text("heroMetricSuffix", "");
    text("heroMetricLabel", "在线取证算力");
    text("mainConclusion", "H100 在线 · 上传图片即可启动来源保护与盲解码溯源");
    text("contrastConclusion", "算力区仅展示在线状态；模型门禁、攻击评测与签名证据按当前视图加载。");
  }
  renderTicker(lastPayload || {}, lastPayload?.audit);
}

async function refreshGpuStatus() {
  try {
    const status = await getJSON("/api/system/gpu", 4500);
    renderGpuStatus(status);
  } catch (error) {
    console.warn("[JYS] H100 status refresh:", formatApiError(error));
    gpuStatus = null;
    renderGpuConnectionState("H100 链路重连中");
  }
}

function renderTicker(payload, audit) {
  const track = document.getElementById("tickerTrack");
  if (!track) return;
  const items = [];
  const push = (key, val, statusVal) =>
    items.push({ key, val: val == null || val === "" ? "-" : String(val), cls: statusClass(statusVal ?? val) });

  const mod = (key, s) => push(key, shortStatus(s), s);
  if (gpuStatus?.ok && gpuStatus.gpu) {
    const inference = gpuStatus.inference || {};
    push("算力", "H100 在线", "ready");
    if (Number(inference.running) > 0 || Number(inference.queued) > 0) {
      push("任务", `${inference.running ?? 0} 运行 · ${inference.queued ?? 0} 排队`, "running");
    }
  } else {
    push("连接", "连接中", "pending");
  }
  const activeView = window.location.hash.replace(/^#\/?/, "") || "overview";
  if (activeView === "forensics" && payload.modelsStatus?.["KAD-Net"]) {
    const kad = payload.modelsStatus["KAD-Net"];
    push("KAD-Net", kad.provenance_ready ? "就绪" : "受门禁", kad.provenance_ready ? "ready" : "pending");
    push("登记权重", kad.registered ? "已验证" : "待补充", kad.registered ? "ready" : "missing");
    push("校准阈值", kad.verification_threshold == null ? "-" : `${(Number(kad.verification_threshold) * 100).toFixed(1)}%`, kad.calibrated ? "ready" : "pending");
    push("证据签名", kad.trusted ? "已固定" : "待复核", kad.trusted ? "ready" : "pending");
    push("保护→传播→溯源", kad.provenance_ready ? "在线" : "待启动", kad.provenance_ready ? "ready" : "pending");
  } else if (activeView === "overview") {
    const modelStates = Object.values(payload.modelsStatus || {}).filter((item) => item && typeof item === "object");
    const provenanceReady = modelStates.filter((item) => item.provenance_ready === true).length;
    push("来源模型", `${provenanceReady}/${modelStates.length || "-"} 就绪`, provenanceReady ? "ready" : "pending");
    push("声明策略", "失败关闭", "ready");
  } else if (activeView === "benchmark") {
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
      payload.simswap?.claim_valid === true
        ? "已验证"
        : readResearchSimSwapRows(payload.simswap).length > 0 ? "研究实测" : "待复核",
      payload.simswap?.claim_valid === true ? "ready" : "pending",
    );
    push("统一协议", "固定", "ready");
  }
  if (activeView === "audit" && audit) {
    const blocking = (audit.blocking_findings || []).length;
    push("审计阻断", blocking, blocking === 0 ? "ready" : "pending");
    const sig = audit.signature || {};
    push("Ed25519", sig.verified ? "verified" : (sig.status || "pending"), sig.verified ? "ready" : "pending");
  }
  if (activeView === "audit" && payload.claims) {
    push(
      "声明",
      payload.claims.ready_for_claims ? "已验证" : "待复核",
      payload.claims.ready_for_claims ? "ready" : "pending",
    );
  }
  const itemHTML = items.map((it) =>
    `<span class="ticker-item ${it.cls}"><i class="tk-dot"></i><span class="tk-key">${escapeHTML(it.key)}</span><span class="tk-val">${escapeHTML(it.val)}</span></span>`
  ).join("");
  if (track.__sig === itemHTML) return;
  track.__sig = itemHTML;
  track.innerHTML = itemHTML;
}

function renderPayload(payload) {
  const { modules, hidden, sepmark, lidmark, waveguard, kadnet, meaMatrix, simswap, modelsStatus, aggregate, report } = payload;

  text("apiEndpoint", `接口 · ${API.replace(/^https?:\/\//, "")}`);

  updateOverviewFlowState({
    online: Boolean(gpuStatus?.ok),
    modelsReady: Object.values(modelsStatus || {}).some((item) => item?.provenance_ready === true),
    audited: Boolean(report?.claim_valid === true),
  });

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
    if (item?.normalized?.status === "missing") return "本轮未纳入正式实测";
    if (item?.claim_valid !== true) return "研究评测待复核";
    const count = sampleCount(summary, progress);
    return count === "-" ? pending : `${count} 张实测图像`;
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
    : "研究评测待复核");
  text("kadnetCount", evidenceCount(kadnet, kadnet.summary, {}, "等待 KAD-Net 结果"));
  const comparisonRows = readComparisonRows(aggregate);
  const comparisonMethods = new Set(comparisonRows.map((row) => row.method).filter(Boolean));
  const comparisonAttacks = new Set(comparisonRows.map((row) => row.attack || row.attack_type).filter(Boolean));
  const comparisonSamples = comparisonRows.map((row) => Number(row.countLabel)).find(Number.isFinite);
  text(
    "aggregatePath",
    comparisonRows.length
      ? `${comparisonMethods.size} 模型 · ${comparisonSamples?.toLocaleString("zh-CN") || "-"} 张 LFW · ${comparisonAttacks.size} 类攻击`
      : "四模型评测汇总",
  );

  text("heroMetric", "H100");
  text("heroMetricSuffix", "");
  text("heroPrimaryAction", "上传图片取证");
  text("heroMetricLabel", "在线取证算力");
  text("mainConclusion", "H100 算力链路已接入在线图片取证流程");
  text("contrastConclusion", "显卡状态与推理队列来自算力节点实时采样，上传任务直接进入来源保护与核验链路。");
  text(
    "boundaryConclusion",
    "真实换脸、性能数字与司法效力须由签名证据包单独放行；流程模拟不进入正式结论。",
  );

  updateReadiness(payload);
  renderMeaMatrix(meaMatrix);
  renderSimSwapEvidence(simswap);
  renderProvenanceModelStatus(modelsStatus);
  renderModules(modules);
  renderComparison(aggregate);
  if (gpuStatus?.ok) renderGpuStatus(gpuStatus);

  rows("hiddenRows", hidden.claim_valid === true ? attackSummaries(hidden.summary) : [], [
    (r) => badge(r.attack_type || r.attack || "-"),
    num((r) => fmt(r.mean_bit_error)),
    num((r) => fmtScore(r.mean_bit_accuracy)),
    num((r) => fmt(r.mean_psnr)),
    num((r) => fmt(r.mean_ssim)),
    num((r) => fmtScore(r.success_rate)),
  ], "HiDDeN 基线待补测 · 本轮未纳入正式实测");

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
  setImage("degradationCurve", aggregateEvidenceReady(aggregate) ? aggregate.degradation_curve : null);

  document.getElementById("lidmarkJson").textContent = JSON.stringify({
    claim_valid: lidmark.claim_valid === true,
    claim_status: lidmark.claim_status,
    checkpoint_type: lidmark.checkpoint_type,
    summary: lidmark.summary || null,
    display_status: lidmark.claim_valid === true ? "实测已验证" : "研究评测待复核",
  }, null, 2);

  document.getElementById("waveguardJson").textContent = JSON.stringify({
    claim_valid: Boolean(waveguardFormal),
    claim_status: waveguardFormal?.claim_status || "evidence_review_required",
    checkpoint_type: waveguardFormal?.checkpoint_type || waveguard.checkpoint_type,
    summary: waveguardFormal?.summary || null,
    display_status: waveguardFormal ? "实测已验证" : "研究评测待复核",
  }, null, 2);

  document.getElementById("reportPaths").innerHTML = `
    <span>JSON: ${escapeHTML(report.json_path)}</span>
    <span>CSV: ${escapeHTML(report.csv_path)}</span>
    <span>Markdown: ${escapeHTML(report.markdown_path)}</span>
  `;
}

function renderAudit(audit) {
  text("auditStatus", `${audit.ready_for_demo ? "演示证据就绪" : "演示证据待复核"} · ${audit.ready_for_claims ? "声明已验证" : "声明待复核"}`);
  text("profileAuditStatus", audit.ready_for_claims ? "声明已验证" : "声明待复核");
  const container = document.getElementById("auditFindings");
  if (!container) return;
  const findings = audit.findings || [];
  const limits = audit.protocol?.known_limitations || [];
  const signature = audit.signature || {};
  container.innerHTML = [
    `<div class="audit-item"><strong>发布门禁</strong><span>运行状态与研究结论发布状态独立计算；阻断项 ${escapeHTML((audit.blocking_findings || []).length)} 个。</span>${badge(audit.ready_for_claims ? "ready" : "review")}</div>`,
    `<div class="audit-item"><strong>签名验证</strong><span>${escapeHTML(signature.status || "未生成")} · 指纹 ${escapeHTML((signature.public_key_fingerprint_sha256 || "-").slice(0, 16))}</span>${badge(signature.verified ? "ready" : "review")}</div>`,
    ...findings.map((item) => `<div class="audit-item"><strong>${escapeHTML(item.code)}</strong><span>${escapeHTML(item.message)}</span>${badge(item.severity)}</div>`),
    ...limits.map((message) => `<div class="audit-item"><strong>协议边界</strong><span>${escapeHTML(message)}</span>${badge("review")}</div>`),
  ].join("") || `<div class="audit-item"><strong>已核验</strong><span>未发现自动审计异常</span>${badge("ready")}</div>`;
}

function renderDemo(result) {
  const source = result.execution_valid ? "模型权重单样本执行" : "流程模拟";
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

const ENDPOINTS = [
  ["artifacts", "/api/artifacts/status"],
  ["modules", "/api/modules"],
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

const VIEW_ENDPOINT_KEYS = {
  overview: new Set(["artifacts", "modules", "modelsStatus"]),
  forensics: new Set(["modelsStatus"]),
  benchmark: new Set(["hidden", "sepmark", "lidmark", "waveguard", "kadnet", "meaMatrix", "simswap", "aggregate"]),
  audit: new Set(["lidmark", "waveguard", "report", "audit", "claims"]),
  profile: new Set(["modelsStatus", "audit"]),
};

const ROUTE_TO_VIEW = Object.freeze({
  overview: "overview",
  register: "forensics",
  transform: "forensics",
  verify: "forensics",
  forensics: "forensics",
  benchmark: "benchmark",
  audit: "audit",
  profile: "profile",
});

const WORKFLOW_ROUTES = new Set(["register", "transform", "verify", "forensics"]);

async function load() {
  try {
    const activeRoute = window.location.hash.replace(/^#\/?/, "") || "overview";
    const activeView = ROUTE_TO_VIEW[activeRoute] || "overview";
    // 按视图只加载当前可见证据，避免首页同时触发整套 benchmark，
    // 让单并发推理节点被无关请求占满。进入对应视图后再按需加载。
    const selectedKeys = VIEW_ENDPOINT_KEYS[activeView] || VIEW_ENDPOINT_KEYS.overview;
    const selectedEndpoints = ENDPOINTS.filter(([key]) => selectedKeys.has(key));
    // allSettled：单个接口失败只降级对应面板，不拖垮整页
    const requests = selectedEndpoints.map(([key, path]) => getJSON(path).then((value) => {
      // 模型状态由边缘节点直接提供；到达后立即解锁来源登记，
      // 无需等待 H100 健康检查和重型证据接口完成。
      if (key === "modelsStatus") renderProvenanceModelStatus(value);
      if (key === "audit") renderAudit(value);
      return value;
    }));
    const results = await Promise.allSettled(requests);
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

    // 当前视图证据源整体不可用时保留交互工作台，H100 状态由独立通道刷新。
    if (failed.length === selectedEndpoints.length) {
      renderErrorState(failed[0].error);
      return;
    }

    lastPayload = {
      health: gpuStatus || { ok: false },
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
      audit: data.audit || {},
      claims: data.claims || { ready_for_claims: false, summary: {} },
    };
    renderPayload(lastPayload);

    if (activeView === "forensics") {
      const readyModels = Object.entries(lastPayload.modelsStatus || {})
        .filter(([, status]) => status && typeof status === "object" && status.provenance_ready === true)
        .map(([model]) => model);
      if (gpuStatus?.ok && readyModels.length) renderReadiness(100, `H100 · ${readyModels.join(" + ")} 已就绪`);
    }

    if (data.audit) renderAudit(data.audit);

    renderTicker(lastPayload, lastPayload.audit);

    if (failed.length) {
      console.warn("[JYS] degraded endpoints:", failed.map((f) => `${f.path} (${formatApiError(f.error)})`));
    }
  } catch (error) {
    renderErrorState(error);
  }
}

/* ═══ 视图路由（hash）═══ */

const VIEW_META = {
  overview: { title: "首页", sub: "系统全景与可信工作流" },
  register: { title: "来源登记", sub: "上传内容并建立可验证身份" },
  transform: { title: "传播实验", sub: "模拟压缩、裁剪与再编码" },
  verify: { title: "来源核验", sub: "盲解码并恢复登记来源" },
  forensics: { title: "来源核验", sub: "登记、传播与盲解码裁决" },
  benchmark: { title: "攻击实验", sub: "统一协议下的鲁棒性评测" },
  audit: { title: "证据中心", sub: "发布门禁与可复核证据" },
  profile: { title: "个人中心", sub: "访问身份与工作入口" },
};

function applyRoute() {
  const requested = window.location.hash.replace(/^#\/?/, "");
  const route = VIEW_META[requested] ? requested : "overview";
  const view = ROUTE_TO_VIEW[route] || "overview";
  document.querySelectorAll(".view").forEach((el) => {
    el.hidden = el.id !== `view-${view}`;
  });
  const shown = document.getElementById(`view-${view}`);
  if (shown) {
    shown.classList.remove("entering");
    void shown.offsetWidth; // 强制回流，重新触发交错入场动画
    shown.classList.add("entering");
  }
  const appShell = document.getElementById("appShell");
  appShell?.classList.remove("route-switching");
  void appShell?.offsetWidth;
  appShell?.classList.add("route-switching");
  window.clearTimeout(routeMotionTimer);
  routeMotionTimer = window.setTimeout(() => appShell?.classList.remove("route-switching"), 720);
  document.body.dataset.view = view;
  document.body.dataset.workflowStep = WORKFLOW_ROUTES.has(route) ? (route === "forensics" ? "register" : route) : "none";
  const navigationView = WORKFLOW_ROUTES.has(route) ? "forensics" : route;
  document.querySelectorAll("#viewNav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.view === navigationView);
  });
  const meta = VIEW_META[route] || VIEW_META.overview;
  const title = document.getElementById("viewTitle");
  const subtitle = document.getElementById("viewSubtitle");
  if (title) title.textContent = meta.title;
  if (subtitle) subtitle.textContent = meta.sub;
}

window.addEventListener("hashchange", () => {
  applyRoute();
  if (appStarted) load();
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
  setTimeout(() => boot.remove(), 1200);
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

function updateOverviewFlowState({ online = false, modelsReady = false, audited = false } = {}) {
  text("livePulseText", online ? "H100 节点在线" : "正在连接 H100");
  text("liveStageRegister", online ? "可启动" : "待连接");
  text("liveStageTransform", modelsReady ? "可观测" : "待观测");
  text("liveStageDecode", modelsReady ? "模型就绪" : "待核验");
  text("liveStageAudit", audited ? "已核验" : "待审计");
}

function beginDashboardIntro() {
  const steps = [...document.querySelectorAll(".live-step")];
  if (!steps.length) return;
  window.clearTimeout(dashboardIntroTimer);
  document.body.classList.remove("dashboard-entering");
  void document.body.offsetWidth;
  document.body.classList.add("dashboard-entering");
  steps.forEach((step, index) => {
    step.classList.remove("is-live");
    window.setTimeout(() => step.classList.add("is-live"), 220 + index * 230);
  });
  dashboardIntroTimer = window.setTimeout(() => document.body.classList.remove("dashboard-entering"), 1550);
}

function startApplication() {
  if (appStarted) return;
  appStarted = true;
  applyRoute();
  tickClock();
  startPolicyRotation();
  load();
  refreshGpuStatus();
  pollTimer = setInterval(refreshGpuStatus, 12000);
}

function stopApplication() {
  appStarted = false;
  clearInterval(policyTimer);
  policyTimer = null;
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

initializeAccess();

/* H100 状态每 4 秒轻量采样；页面隐藏时暂停，返回后立即刷新。 */
document.addEventListener("visibilitychange", () => {
  if (!appStarted) return;
  const track = document.getElementById("tickerTrack");
  if (document.hidden) {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (track) track.style.animationPlayState = "paused";
  } else {
    if (track) track.style.removeProperty("animation-play-state");
    refreshGpuStatus();
    if (!pollTimer) pollTimer = setInterval(refreshGpuStatus, 12000);
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
  verifyFile: null,
  sourceHash: "",
  registeredHash: "",
  currentBlob: null,
  currentHash: "",
  attacks: [],
};

const TRACE_CASE_ORDER = Object.freeze(["source", "registered", "edited", "submitted", "verified"]);
const TRACE_CASE_DETAILS = Object.freeze({
  source: "traceCaseSource",
  registered: "traceCaseRegistered",
  edited: "traceCaseEdited",
  submitted: "traceCaseSubmitted",
  verified: "traceCaseVerified",
});
const TRACE_CASE_LABELS = Object.freeze({
  idle: "待开始",
  source: "图片已载入",
  registered: "来源已登记",
  edited: "传播版本已生成",
  submitted: "等待盲核验",
  verified: "可具体溯源",
  failed: "阈值未通过",
});

function updateTraceCase(step = "idle", detail = "", state = step) {
  const casePanel = document.querySelector(".trace-case-panel");
  const activeStep = step === "failed" ? "submitted" : step;
  const activeIndex = TRACE_CASE_ORDER.indexOf(activeStep);
  if (casePanel) casePanel.dataset.state = state;
  document.querySelectorAll("[data-case-step]").forEach((item, index) => {
    item.classList.toggle("active", index === activeIndex && state !== "verified");
    item.classList.toggle("completed", activeIndex >= 0 && index < activeIndex || state === "verified" && index <= activeIndex);
    item.classList.toggle("failed", state === "failed" && item.dataset.caseStep === activeStep);
  });
  if (detail) {
    const detailElement = document.getElementById(TRACE_CASE_DETAILS[activeStep]);
    if (detailElement) detailElement.textContent = detail;
  }
}

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

const DIRECT_UPLOAD_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const CAMERA_IMPORT_MAX_BYTES = 30 * 1024 * 1024;
const API_IMAGE_MAX_BYTES = 5 * 1024 * 1024;
const NORMALIZED_IMAGE_TARGET_BYTES = Math.floor(4.75 * 1024 * 1024);
const NORMALIZED_IMAGE_MAX_PIXELS = 12_000_000;
const NORMALIZED_IMAGE_MAX_EDGE = 4096;
const HEIF_EXTENSIONS = new Set(["heic", "heif", "hif"]);
const RAW_EXTENSIONS = new Set(["dng", "raw", "cr2", "cr3", "nef", "arw", "raf", "orf", "rw2"]);
let heicConverterPromise = null;

function fileExtension(file) {
  const match = String(file?.name || "").toLowerCase().match(/\.([a-z0-9]+)$/);
  return match ? match[1] : "";
}

function inferredImageType(file) {
  const extension = fileExtension(file);
  if (extension === "jpg" || extension === "jpeg") return "image/jpeg";
  if (extension === "png") return "image/png";
  if (extension === "webp") return "image/webp";
  if (HEIF_EXTENSIONS.has(extension)) return "image/heic";
  return String(file?.type || "").toLowerCase();
}

function isHeifFile(file) {
  const mediaType = String(file?.type || "").toLowerCase();
  return HEIF_EXTENSIONS.has(fileExtension(file))
    || mediaType === "image/heic"
    || mediaType === "image/heif"
    || mediaType === "image/heic-sequence"
    || mediaType === "image/heif-sequence";
}

function compatibleJpegName(file) {
  const stem = String(file?.name || "phone-photo").replace(/\.[^.]+$/, "") || "phone-photo";
  return `${stem}-compatible.jpg`;
}

function loadHeicConverter() {
  if (typeof window.heic2any === "function") return Promise.resolve(window.heic2any);
  if (!heicConverterPromise) {
    heicConverterPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "./vendor/heic2any.min.js?v=0.0.4";
      script.async = true;
      script.onload = () => {
        if (typeof window.heic2any === "function") resolve(window.heic2any);
        else reject(new Error("HEIC 转换组件未正确加载"));
      };
      script.onerror = () => reject(new Error("HEIC 转换组件加载失败，请刷新页面后重试"));
      document.head.appendChild(script);
    }).catch((error) => {
      heicConverterPromise = null;
      throw error;
    });
  }
  return heicConverterPromise;
}

async function convertHeifToJpeg(file) {
  const converter = await loadHeicConverter();
  let converted;
  try {
    converted = await converter({ blob: file, toType: "image/jpeg", quality: .94 });
  } catch (error) {
    throw new Error(`HEIC / HEIF 转换失败：${error?.message || "请在相册中导出为 JPEG 后重试"}`);
  }
  const blob = Array.isArray(converted) ? converted[0] : converted;
  if (!(blob instanceof Blob) || !blob.size) throw new Error("HEIC / HEIF 文件中没有可读取的照片帧");
  return new File([blob], compatibleJpegName(file), {
    type: "image/jpeg",
    lastModified: file.lastModified || Date.now(),
  });
}

function normalizedImageSize(width, height) {
  const pixelScale = Math.sqrt(NORMALIZED_IMAGE_MAX_PIXELS / Math.max(1, width * height));
  const edgeScale = NORMALIZED_IMAGE_MAX_EDGE / Math.max(1, width, height);
  const scale = Math.min(1, pixelScale, edgeScale);
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

function imageCanvas(image, width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { alpha: false });
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);
  context.drawImage(image, 0, 0, width, height);
  return canvas;
}

async function jpegWithinUploadLimit(canvas, sourceFile) {
  const qualities = [.92, .86, .8, .74, .68, .62];
  let workingCanvas = canvas;
  let smallestBlob = null;
  for (let resizeAttempt = 0; resizeAttempt < 4; resizeAttempt += 1) {
    for (const quality of qualities) {
      const blob = await canvasToBlob(workingCanvas, "image/jpeg", quality);
      if (!smallestBlob || blob.size < smallestBlob.size) smallestBlob = blob;
      if (blob.size <= NORMALIZED_IMAGE_TARGET_BYTES) {
        return new File([blob], compatibleJpegName(sourceFile), {
          type: "image/jpeg",
          lastModified: sourceFile.lastModified || Date.now(),
        });
      }
    }
    const shrink = Math.min(.88, Math.sqrt(NORMALIZED_IMAGE_TARGET_BYTES / Math.max(1, smallestBlob.size)) * .94);
    const nextWidth = Math.max(1, Math.round(workingCanvas.width * shrink));
    const nextHeight = Math.max(1, Math.round(workingCanvas.height * shrink));
    const nextCanvas = document.createElement("canvas");
    nextCanvas.width = nextWidth;
    nextCanvas.height = nextHeight;
    const context = nextCanvas.getContext("2d", { alpha: false });
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, nextWidth, nextHeight);
    context.drawImage(workingCanvas, 0, 0, nextWidth, nextHeight);
    workingCanvas = nextCanvas;
  }
  throw new Error("照片自动压缩后仍超过 5 MB，请在相册中降低分辨率后重试");
}

async function normalizeImportedImage(selectedFile) {
  if (!selectedFile) return null;
  if (selectedFile.size > CAMERA_IMPORT_MAX_BYTES) {
    throw new Error("原始照片超过 30 MB，请先在相册中导出较小版本");
  }
  if (RAW_EXTENSIONS.has(fileExtension(selectedFile))) {
    throw new Error("暂不直接处理 RAW / DNG 底片，请先从相册导出为 JPEG、PNG 或 HEIC");
  }

  let uploadFile = selectedFile;
  const changes = [];
  if (isHeifFile(selectedFile)) {
    uploadFile = await convertHeifToJpeg(selectedFile);
    changes.push("HEIC / HEIF 已转为 JPEG");
  } else {
    const inferredType = inferredImageType(selectedFile);
    if (DIRECT_UPLOAD_IMAGE_TYPES.has(inferredType) && uploadFile.type !== inferredType) {
      uploadFile = new File([selectedFile], selectedFile.name, {
        type: inferredType,
        lastModified: selectedFile.lastModified || Date.now(),
      });
    }
  }

  let image;
  try {
    image = await imageFromBlob(uploadFile);
  } catch (_) {
    throw new Error("浏览器无法读取该照片；支持手机 HEIC / HEIF、JPEG、PNG 和 WEBP，RAW 请先导出为 JPEG");
  }

  const pixelCount = image.naturalWidth * image.naturalHeight;
  const needsCompatibleJpeg = !DIRECT_UPLOAD_IMAGE_TYPES.has(uploadFile.type)
    || uploadFile.size > API_IMAGE_MAX_BYTES
    || pixelCount > NORMALIZED_IMAGE_MAX_PIXELS
    || Math.max(image.naturalWidth, image.naturalHeight) > NORMALIZED_IMAGE_MAX_EDGE;
  if (needsCompatibleJpeg) {
    const target = normalizedImageSize(image.naturalWidth, image.naturalHeight);
    uploadFile = await jpegWithinUploadLimit(imageCanvas(image, target.width, target.height), selectedFile);
    image = await imageFromBlob(uploadFile);
    changes.push(`已优化为 ${image.naturalWidth} × ${image.naturalHeight} 的兼容 JPEG`);
  }

  if (uploadFile.size > API_IMAGE_MAX_BYTES) throw new Error("兼容图片仍超过 5 MB，请换用较小照片");
  return {
    file: uploadFile,
    image,
    originalFile: selectedFile,
    note: changes.join("；"),
  };
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

function applyDeepfakeProxy(canvas, source, type) {
  const width = source.width;
  const height = source.height;
  const patchWidth = Math.max(24, Math.round(width * .42));
  const patchHeight = Math.max(24, Math.round(height * .56));
  const sourceX = Math.round((width - patchWidth) / 2);
  const sourceY = Math.round(height * .2);
  const patch = document.createElement("canvas");
  patch.width = patchWidth;
  patch.height = patchHeight;
  const patchContext = patch.getContext("2d");
  if ("filter" in patchContext) {
    patchContext.filter = type === "faceshifter"
      ? "saturate(1.16) contrast(1.06)"
      : "blur(.45px) saturate(.86) brightness(1.03)";
  }
  patchContext.drawImage(source, sourceX, sourceY, patchWidth, patchHeight, 0, 0, patchWidth, patchHeight);

  const context = canvas.getContext("2d");
  canvas.width = width;
  canvas.height = height;
  context.drawImage(source, 0, 0);
  const offsetX = type === "faceshifter" ? Math.round(width * .025) : -Math.round(width * .018);
  const offsetY = type === "faceshifter" ? Math.round(height * .008) : -Math.round(height * .012);
  const targetX = sourceX + offsetX;
  const targetY = sourceY + offsetY;
  context.save();
  context.beginPath();
  context.ellipse(
    targetX + patchWidth / 2,
    targetY + patchHeight / 2,
    patchWidth * .47,
    patchHeight * .48,
    0,
    0,
    Math.PI * 2,
  );
  context.clip();
  context.globalAlpha = .92;
  if (type === "faceshifter") {
    context.translate(targetX + patchWidth / 2, targetY + patchHeight / 2);
    context.scale(-1, 1);
    context.drawImage(patch, -patchWidth / 2, -patchHeight / 2, patchWidth, patchHeight);
  } else {
    context.drawImage(patch, targetX, targetY, patchWidth, patchHeight);
  }
  context.restore();
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

function setVerdictHero(headline, summary, state = "waiting") {
  text("verdictHeadline", headline);
  text("verdictSummary", summary);
  const hero = document.getElementById("verdictHero");
  if (hero) hero.dataset.state = state;
}

function resetLiveVerdicts() {
  setVerdict("Exact", "原图", "pass", "当前文件与上传原图字节一致");
  setVerdict("Watermark", "待登记", "review", "必须由真实模型完成盲解码");
  setVerdict("Metadata", "未检查", "review", "Canvas 传播后将重新编码标识层");
  setVerdict("Claim", "待门禁", "review", "登记、校准、阈值与签名共同放行");
  text("liveScore", "—");
  text("liveThreshold", "—");
  setVerdictHero("原始内容已就绪", "登记主体编号、内容 ID 与主动水印处于待绑定状态", "source");
}

async function refreshAttackArtifact(type = "image/png", quality) {
  const canvas = document.getElementById("attackCanvas");
  localEvidence.currentBlob = await canvasToBlob(canvas, type, quality);
  localEvidence.currentHash = await sha256Blob(localEvidence.currentBlob);
}

async function loadSourceImage(selectedFile) {
  if (!selectedFile) return;
  const imported = await normalizeImportedImage(selectedFile);
  const file = imported.file;
  const image = imported.image;
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
  const importedName = imported.originalFile.name === file.name
    ? file.name
    : `${imported.originalFile.name} → ${file.name}`;
  document.getElementById("sourceFileMeta").innerHTML = `
    <div><dt>文件</dt><dd title="${escapeHTML(importedName)}">${escapeHTML(importedName)} · ${formatBytes(file.size)}</dd></div>
    <div><dt>尺寸</dt><dd>${image.naturalWidth} × ${image.naturalHeight} px</dd></div>
    <div><dt>SHA-256</dt><dd title="${localEvidence.sourceHash}">${shortHash(localEvidence.sourceHash)}</dd></div>`;
  document.querySelectorAll("[data-local-attack]").forEach((button) => { button.disabled = false; });
  document.getElementById("useAttackForVerify").disabled = false;
  document.getElementById("attackLog").innerHTML = '<span class="done">原始版本已装载</span>';
  resetLiveVerdicts();
  setDemoProgress(1);
  addDemoTimeline("原始内容进入浏览器", `${importedName} · ${image.naturalWidth}×${image.naturalHeight} · SHA-256 ${shortHash(localEvidence.sourceHash)}`);
  updateTraceCase("source", `${file.name} 已载入，SHA-256 ${shortHash(localEvidence.sourceHash)}`);
  text("protectStatus", imported.note
    ? `手机照片已导入：${imported.note}；填写登记主体编号后可完成来源登记`
    : "原图已就绪；填写登记主体编号后可完成来源登记");
}

document.getElementById("protectFile")?.addEventListener("change", async (event) => {
  localEvidence.sourceFile = null;
  sourceImportBusy = true;
  updateProtectButton();
  text("protectStatus", "正在读取并检查照片格式…");
  try {
    await loadSourceImage(event.target.files?.[0]);
  } catch (error) {
    event.target.value = "";
    text("protectStatus", `图片读取失败：${error.message}`);
  } finally {
    sourceImportBusy = false;
    updateProtectButton();
  }
});

document.getElementById("verifyFile")?.addEventListener("change", async (event) => {
  const selectedFile = event.target.files?.[0];
  localEvidence.verifyFile = null;
  if (!selectedFile) return;
  verifyImportBusy = true;
  const button = document.getElementById("verifyBtn");
  if (button) button.disabled = true;
  text("verifyStatus", "正在读取并检查观测照片…");
  try {
    const imported = await normalizeImportedImage(selectedFile);
    localEvidence.verifyFile = imported.file;
    text("verifyStatus", imported.note
      ? `观测照片已导入：${imported.note} · ${formatBytes(imported.file.size)}`
      : `观测照片已装载 · ${formatBytes(imported.file.size)} · 等待内容 ID`);
  } catch (error) {
    event.target.value = "";
    text("verifyStatus", `图片读取失败：${error.message}`);
  } finally {
    verifyImportBusy = false;
    if (button) button.disabled = false;
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
      } else if (type === "faceshifter" || type === "fsgan") {
        applyDeepfakeProxy(canvas, copy, type);
        label = type === "faceshifter" ? "FaceShifter 代理" : "FSGAN 代理";
      }

      if (type !== "jpeg") await refreshAttackArtifact("image/png");
      localEvidence.attacks.push(label);
      const chip = document.createElement("span");
      chip.className = "done";
      chip.textContent = `${localEvidence.attacks.length}. ${label}`;
      document.getElementById("attackLog").appendChild(chip);
      setVerdict("Exact", localEvidence.currentHash === localEvidence.registeredHash ? "一致" : "不一致", localEvidence.currentHash === localEvidence.registeredHash ? "pass" : "fail", `传播文件 SHA-256 ${shortHash(localEvidence.currentHash)}`);
      setVerdict("Metadata", "已移除", "fail", "浏览器重编码已清除原文件元数据");
      setVerdict("Watermark", "待盲核验", "review", "来源关系等待模型解码确认");
      setVerdict("Claim", "待门禁", "review", "需以盲核验事件和签名记录判断");
      setVerdictHero("文件已经改变 · 来源待核验", `${localEvidence.attacks.join(" → ")} 已改变字节身份，来源关系等待主动水印解码`, "changed");
      setDemoProgress(3);
      addDemoTimeline("生成传播版本", `${localEvidence.attacks.join(" → ")} · ${canvas.width}×${canvas.height} · ${formatBytes(localEvidence.currentBlob.size)}`);
      updateTraceCase("edited", `${localEvidence.attacks.join(" → ")} · 已生成新的观测文件`);
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
    text("verifyStatus", `传播版本已送入 · ${formatBytes(file.size)} · 等待核验事件`);
    setDemoProgress(4);
    addDemoTimeline("传播版本送入核验", `${file.name} · 只提交观测图片与 content_id`);
    updateTraceCase("submitted", `${file.name} 与内容 ID 已送入盲核验`);
    window.location.hash = "#/verify";
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
    ? '<span class="verdict-ok">✔ 模型权重、核验阈值与签名门禁通过</span>'
    : '<span class="verdict-warn">⚠ 研究模式完成，但正式证据未放行</span>';
}

function verificationFailureSummary(result) {
  const assessment = verificationAssessment(result);
  return `${assessment.summary}系统保持失败关闭，不据此确认来源不存在。`;
}

function verificationAssessment(result) {
  const score = Number(result?.bit_accuracy);
  const threshold = Number(
    result?.verification_threshold
      ?? result?.success_threshold
      ?? result?.threshold
      ?? result?.registered_threshold
      ?? result?.protocol_threshold
      ?? result?.decision_threshold,
  );
  const model = result?.model || "当前模型";
  const scoreText = Number.isFinite(score) ? `${(score * 100).toFixed(1)}%` : "未返回有效得分";
  const thresholdText = Number.isFinite(threshold) ? `${(threshold * 100).toFixed(1)}%` : "未返回有效阈值";
  const margin = Number.isFinite(score) && Number.isFinite(threshold) ? score - threshold : null;
  const marginText = margin == null ? "无法计算" : `${margin >= 0 ? "+" : ""}${(margin * 100).toFixed(1)} 个百分点`;
  const exact = result?.exact_protected_file_match === true;
  const verified = result?.verified === true;
  const claimValid = result?.claim_valid === true;

  if (verified && claimValid) {
    return {
      state: "verified",
      title: "可具体溯源",
      summary: `${model} 盲解码得分 ${scoreText} 已达到核验阈值 ${thresholdText}，登记消息、内容 ID 和事件记录已经闭合。`,
      short: "来源消息与正式证据门禁均已闭合",
      scoreText,
      thresholdText,
      marginText,
    };
  }
  if (verified) {
    return {
      state: "review",
      title: "来源消息已恢复，但正式声明未放行",
      summary: `${model} 盲解码得分 ${scoreText} 达到阈值 ${thresholdText}，但签名、权重、校准或实现门禁仍未闭合。`,
      short: "消息恢复成功，但签名证据尚未闭合",
      scoreText,
      thresholdText,
      marginText,
    };
  }
  if (!Number.isFinite(score) || !Number.isFinite(threshold)) {
    return {
      state: "blocked",
      title: "没有形成可判定的阈值对比",
      summary: `${model} 未返回完整的盲解码得分或登记阈值，当前不能判定来源关系。`,
      short: "缺少有效得分或阈值",
      scoreText,
      thresholdText,
      marginText,
    };
  }
  if (exact) {
    return {
      state: "rejected",
      title: "文件未被改动，但消息恢复未达阈值",
      summary: `${model} 盲解码得分 ${scoreText}，核验阈值 ${thresholdText}，差值 ${marginText}；观测文件与登记保护文件完全一致。`,
      short: "原文件一致但解码阈值未通过",
      scoreText,
      thresholdText,
      marginText,
    };
  }
  return {
    state: "rejected",
    title: "传播编辑可能超过当前模型鲁棒范围",
    summary: `${model} 盲解码得分 ${scoreText}，核验阈值 ${thresholdText}，差值 ${marginText}；观测文件已经发生二次编辑。`,
    short: "传播变换过强或内容 ID 不匹配",
    scoreText,
    thresholdText,
    marginText,
  };
}

function verificationCaseMarkup(result, assessment) {
  const contentId = document.getElementById("verifyContentId")?.value.trim() || result?.content_id || "未返回";
  const eventId = result?.event_id || "未返回";
  return `<section class="verification-case-card state-${escapeHTML(assessment.state)}">
    <div class="verification-case-head"><span>CASE 01 · 核验判定</span><strong>${escapeHTML(assessment.title)}</strong></div>
    <p>${escapeHTML(assessment.summary)}</p>
    <div class="verification-case-metrics"><span>盲解码得分<strong>${escapeHTML(assessment.scoreText)}</strong></span><span>登记阈值<strong>${escapeHTML(assessment.thresholdText)}</strong></span><span>安全裕量<strong>${escapeHTML(assessment.marginText)}</strong></span></div>
    <code>content_id=${escapeHTML(contentId)} · event_id=${escapeHTML(eventId)}</code>
  </section>`;
}

document.getElementById("protectForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const model = document.getElementById("protectModel").value;
  const protectFile = localEvidence.sourceFile;
  if (!protectFile) {
    text("protectStatus", "请先选择原创图片");
    return;
  }
  if (protectModelGate.get(model)?.available !== true) {
    text("protectStatus", "来源登记暂不可用：所选模型运行权重未通过完整性检查");
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
    const res = await fetchWithTimeout(apiURL("/api/provenance/protect"), { method: "POST", headers: sessionHeaders(), body: fd }, 240000);
    const result = await res.json();
    if (!res.ok) throw new Error((result.error && result.error.message) || res.statusText);
    document.getElementById("verifyContentId").value = result.content_id;
    const imageSource = result.protected_image?.png_base64
      ? `data:image/png;base64,${result.protected_image.png_base64}`
      : apiURL(result.protected_image?.url || "/api/invalid-artifact");
    document.getElementById("protectResult").innerHTML = `
      <details class="registration-receipt" open>
        <summary><span>登记回执</span><code>${escapeHTML(shortHash(result.content_id))}</code></summary>
        <div class="registration-receipt-body">
          <figure><img src="${escapeHTML(imageSource)}" alt="已保护图片"><figcaption>已保护图片</figcaption></figure>
          <div class="infer-metric-row">
            <span>内容 ID</span><strong>${escapeHTML(result.content_id)}</strong>
            <span>登记主体编号</span><strong>${escapeHTML(result.creator_ref)}</strong>
            <span>原图留存</span><strong>${result.privacy?.original_persisted ? "是" : "否"}</strong>
            <span>正式证据</span><strong>${formalEvidenceBadge(result, "registered_protection_record")}</strong>
          </div>
        </div>
      </details>`;
    document.getElementById("protectEvidence").textContent = JSON.stringify(result, null, 2);
    text("protectStatus", `来源登记完成 · ${result.content_id} · ${result.evidence_status}`);
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
      addDemoTimeline("受保护版本进入传播台", `${formatBytes(protectedBlob.size)} · 模型权重 ${shortHash(result.checkpoint_sha256)}`);
    } catch (artifactError) {
      addDemoTimeline("保护图未能进入传播台", artifactError.message);
    }
    setVerdict("Watermark", "已嵌入", "pass", `已登记内容 ID ${result.content_id}`);
    setVerdict("Claim", result.claim_valid === true ? "登记有效" : "待核验", result.claim_valid === true ? "pass" : "review", result.claim_valid === true ? "来源登记已通过当前证据门禁" : "仍需传播后盲核验事件收口");
    setVerdictHero("来源登记已经建立", `内容 ID ${shortHash(result.content_id)} · 登记主体 ${result.creator_ref} · 等待传播后盲核验`, "registered");
    updateTraceCase("registered", `内容 ID ${shortHash(result.content_id)} 已建立，登记模型 ${model}`);
    setDemoProgress(2);
    addDemoTimeline("创建来源登记", `${result.content_id} · ${result.creator_ref} · ${result.evidence_status || "状态未返回"}`);
    text("protectStatus", `来源登记完成 · ${result.content_id} · 登记回执已展开，请点击“传播实验”继续`);
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
  if (verifyImportBusy) {
    text("verifyStatus", "照片仍在转换，请稍候");
    return;
  }
  const verifyFile = localEvidence.verifyFile;
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
    const res = await fetchWithTimeout(apiURL("/api/provenance/verify"), { method: "POST", headers: sessionHeaders(), body: fd }, 240000);
    const result = await res.json();
    if (!res.ok) throw new Error((result.error && result.error.message) || res.statusText);
    const assessment = verificationAssessment(result);
    document.getElementById("verifyResult").innerHTML = `<div class="infer-metric-row">
      <span>登记消息匹配</span><strong>${result.verified ? '<span class="verdict-ok">✔ 达到协议阈值</span>' : '<span class="verdict-risk">✘ 未达到协议阈值</span>'}</strong>
      <span>比特准确率</span><strong>${Number.isFinite(Number(result.bit_accuracy)) ? (Number(result.bit_accuracy) * 100).toFixed(1) + "%" : "—"}</strong>
      <span>精确文件匹配</span><strong>${result.exact_protected_file_match ? "是" : "否（可能经历传播变换）"}</strong>
      <span>登记主体</span><strong>${escapeHTML(result.creator_ref)}</strong>
      <span>内容 ID</span><strong>${escapeHTML(document.getElementById("verifyContentId").value.trim())}</strong>
      <span>正式证据</span><strong>${formalEvidenceBadge(result, "registered_blind_verification")}</strong>
    </div>${verificationCaseMarkup(result, assessment)}`;
    document.getElementById("verifyEvidence").textContent = JSON.stringify(result, null, 2);
    text("verifyStatus", `${result.verified ? "消息匹配" : "未达到来源核验阈值"} · ${assessment.short} · 事件编号：${result.event_id}`);
    const score = Number(result.bit_accuracy);
    const thresholdCandidate = result.verification_threshold ?? result.success_threshold ?? result.threshold ?? result.registered_threshold ?? result.protocol_threshold ?? result.decision_threshold;
    const threshold = Number(thresholdCandidate);
    setVerdict("Exact", result.exact_protected_file_match ? "一致" : "不一致", result.exact_protected_file_match ? "pass" : "fail", result.exact_protected_file_match ? "观测文件与已保护文件字节完全一致" : "文件变化不等于来源关系失效");
    setVerdict("Watermark", result.verified ? "恢复成功" : "未达阈值", result.verified ? "pass" : "fail", Number.isFinite(score) ? `比特准确率 ${(score * 100).toFixed(1)}%` : "服务端未返回有效恢复得分");
    if (typeof result.aigc_metadata_intact === "boolean") {
      setVerdict("Metadata", result.aigc_metadata_intact ? "完整" : "缺失", result.aigc_metadata_intact ? "pass" : "fail", "结果来自服务端标识完整性检查");
    } else {
      setVerdict("Metadata", "未判定", "review", "当前核验接口未返回元数据完整性证据");
    }
    setVerdict("Claim", result.claim_valid === true ? "有效" : "未放行", result.claim_valid === true ? "pass" : "fail", result.claim_valid === true ? "模型登记、校准、阈值与签名门禁均通过" : "至少一项正式证据门禁未通过");
    const exact = result.exact_protected_file_match === true;
    if (result.verified && result.claim_valid === true) {
      setVerdictHero(
        exact ? "登记文件完全匹配" : "字节已改变 · 来源仍被恢复",
        exact ? "文件哈希、水印恢复与正式声明共同闭合" : "传播改变了文件本身，但主动水印与签名门禁仍确认登记来源",
        "verified",
      );
    } else if (result.verified) {
      setVerdictHero("来源消息已恢复 · 正式声明未放行", "解码结果达到阈值，但至少一项模型、校准、实现或签名门禁未闭合", "review");
    } else {
      setVerdictHero("本次未达到来源核验阈值", `${assessment.summary}系统保持失败关闭，不据此确认来源不存在。`, "rejected");
    }
    updateTraceCase(
      result.verified ? "verified" : "failed",
      result.verified ? `${assessment.title} · 事件编号 ${result.event_id || "未返回"}` : `${assessment.title} · 事件编号 ${result.event_id || "未返回"}`,
      result.verified ? (result.claim_valid === true ? "verified" : "review") : "failed",
    );
    text("liveScore", Number.isFinite(score) ? `${(score * 100).toFixed(1)}%` : "—");
    text("liveThreshold", Number.isFinite(threshold) ? `${(threshold * 100).toFixed(1)}%` : "接口未返回");
    setDemoProgress(5);
    addDemoTimeline("盲核验事件写入", `${result.event_id || "事件编号未返回"} · ${result.verified ? "登记消息恢复" : verificationFailureSummary(result)} · 声明${result.claim_valid === true ? "有效" : "未放行"}`);
  } catch (err) {
    text("verifyStatus", `失败：${err.message}`);
    setVerdict("Watermark", "无结果", "review", "核验服务未返回可验证结果");
    setVerdict("Claim", "未放行", "review", "没有盲核验事件，不形成来源结论");
    setVerdictHero("核验未完成", "没有形成可验证事件，系统保持失败关闭", "review");
    updateTraceCase("failed", `核验接口未返回可验证事件：${err.message}`, "failed");
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
    const res = await fetchWithTimeout(apiURL("/api/compliance/batch"), { method: "POST", headers: sessionHeaders(), body: fd }, 130000);
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
    status.textContent = "失败关闭：至少选择一个二次嵌入威胁模型；没有完整输入就不生成正式结果";
    output.innerHTML = "";
    badgeElement.textContent = "失败关闭";
    badgeElement.className = "panel-badge warning";
    badgeElement.title = "失败关闭：输入或签名证据不完整时，系统不输出正式部署结论";
    return;
  }
  const profileName = document.getElementById("collaborationProfile").value;
  const profile = COLLABORATION_PROFILES[profileName] || COLLABORATION_PROFILES.balanced;
  button.disabled = true;
  status.textContent = "正在验签逐图证据并计算 217 身份簇置信前沿…";
  output.innerHTML = "";
  badgeElement.textContent = "正在核验";
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
        <span>选定部署模型</span>
        <strong>${escapeHTML(selected.model)}</strong>
        <small>置信调整得分 ${escapeHTML(Number(selected.score).toFixed(3))} · 最差协议归一化 margin 聚类 LCB ${escapeHTML(collaborationPercent(selected.worst_case_source_protocol_normalized_margin_cluster_lcb))}</small>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>排序</th><th>模型</th><th>得分</th><th>期望安全裕量下界</th><th>最差安全裕量下界</th></tr></thead>
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
    status.textContent = "部署结果已生成但未自动执行 · 217 身份等权、96 项选择族与 20,000 次聚类重采样可复算";
    badgeElement.textContent = "证据已验证";
    badgeElement.className = "panel-badge real";
  } catch (error) {
    status.textContent = `失败关闭：签名证据未闭合或响应契约未通过；本次结果不进入正式结论。${formatApiError(error)}`;
    badgeElement.textContent = "失败关闭";
    badgeElement.className = "panel-badge warning";
    badgeElement.title = "失败关闭：逐图结果、固定协议、实现/权重哈希或签名者身份至少一项未通过";
  } finally {
    button.disabled = false;
  }
});

document.getElementById("meaForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const btn = document.getElementById("meaBtn");
  btn.disabled = true;
  document.getElementById("meaStatus").textContent = "正在对比 4 个正式候选模型…";
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
      const res = await fetchWithTimeout(apiURL("/api/infer/single"), { method: "POST", headers: sessionHeaders(), body: fd }, 130000);
      const body = await res.json();
      if (!res.ok) throw new Error((body.error && body.error.message) || `HTTP ${res.status}`);
      return body;
    }));
    const allCheckpoint = results.every((result) => result.execution_valid === true);
    document.getElementById("meaStatus").textContent = allCheckpoint
      ? "单样本对比完成 · 正式评测结论仍需全量证据"
      : "流程模拟完成 · 不生成性能结论";
    document.getElementById("meaResults").innerHTML = `<div class="mea-grid">` +
      results.map((result) => {
        const m = result.metrics || {};
        const acc = m.bit_accuracy_tracer != null ? m.bit_accuracy_tracer
          : m.bit_accuracy_c != null ? m.bit_accuracy_c
          : m.bit_accuracy_detector != null ? m.bit_accuracy_detector : m.bit_accuracy;
        const imgs = result.artifacts_b64 || {};
        return `<div class="mea-card">
          <h4>${escapeHTML(result.model)} <small>${result.execution_valid ? "模型权重单样本 · 等待放行" : "流程模拟 · 仅供流程检查"}</small></h4>
          <div class="mea-figs">
            ${["watermarked", "attacked", "heatmap"].filter((key) => imgs[key]).map((key) =>
              `<figure>
                <img src="data:image/png;base64,${imgs[key]}" alt="${escapeHTML(key)}">
                <figcaption>${escapeHTML(key)}</figcaption>
              </figure>`).join("")}
          </div>
          <div class="mea-metrics">
            <span>比特准确率</span><strong>${acc != null ? (acc * 100).toFixed(1) + "%" : "—"}</strong>
            <span>PSNR</span><strong>${m.psnr != null ? m.psnr.toFixed(1) + " dB" : "—"}</strong>
            <span>声明状态</span><strong><span class="verdict-warn">待正式攻击实验证据</span></strong>
          </div>
        </div>`;
      }).join("") + `</div>`;
  } catch (err) {
    document.getElementById("meaStatus").textContent = "对比失败 · " + err.message;
  } finally {
    btn.disabled = false;
  }
});
