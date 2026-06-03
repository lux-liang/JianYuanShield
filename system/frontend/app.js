const API = `${window.location.protocol}//${window.location.hostname}:8026`;

function text(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value == null || value === "" ? "-" : String(value);
}

function fmt(value) {
  if (value == null || value === "") return "-";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(4) : String(value);
}

function rows(containerId, records, cells) {
  const body = document.getElementById(containerId);
  body.innerHTML = "";
  if (!records || records.length === 0) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="${cells.length}">pending</td>`;
    body.appendChild(tr);
    return;
  }
  records.forEach((record) => {
    const tr = document.createElement("tr");
    tr.innerHTML = cells.map((cell) => `<td>${cell(record)}</td>`).join("");
    body.appendChild(tr);
  });
}

async function getJSON(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
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
  return summary?.num_images || summary?.images || progress?.num_images || progress?.processed_images || progress?.completed_images || "-";
}

function statusFrom(payload) {
  const summary = payload?.summary || {};
  const progress = payload?.progress || {};
  return summary.status || progress.status || (payload?.results_csv_exists ? "running" : "pending");
}

function cleanAttack(payload) {
  return payload?.summary?.attacks?.clean || {};
}

async function load() {
  try {
    const [health, modules, hidden, sepmark, lidmark, waveguard, aggregate, report] = await Promise.all([
      getJSON("/api/health"),
      getJSON("/api/modules"),
      getJSON("/api/benchmark/hidden-lfw-full"),
      getJSON("/api/benchmark/sepmark"),
      getJSON("/api/benchmark/lidmark-lfw-eval"),
      getJSON("/api/benchmark/waveguard"),
      getJSON("/api/benchmark/aggregate"),
      getJSON("/api/competition-report"),
    ]);

    text("health", `health: ${health.ok ? "OK" : "FAIL"}`);
    text("hiddenStatus", statusFrom(hidden));
    text("hiddenCount", `${sampleCount(hidden.summary, hidden.progress)} images`);
    text("sepmarkStatus", statusFrom(sepmark));
    text("sepmarkCount", `${sampleCount(sepmark.summary, sepmark.progress)} images`);
    text("lidmarkStatus", statusFrom(lidmark));
    text("lidmarkCount", `${sampleCount(lidmark.summary, lidmark.progress)} images`);
    text("waveguardStatus", statusFrom(waveguard));
    text("waveguardCount", `${sampleCount(waveguard.summary, waveguard.progress)} images`);
    text("reportStatus", report.exists?.json ? "ready" : "pending");
    text("aggregatePath", aggregate.report_md_path || "pending");
    const sepClean = cleanAttack(sepmark);
    const hiddenClean = cleanAttack(hidden);
    text("mainConclusion", `SepMark clean Acc-C ${fmt(sepClean.mean_bit_accuracy)} / Acc-RF ${fmt(sepClean.mean_bit_accuracy_rf)}`);
    text("contrastConclusion", `HiDDeN clean Acc ${fmt(hiddenClean.mean_bit_accuracy)}，作为真实弱对照`);
    text("boundaryConclusion", "LIDMark=smoke，WaveGuard=checkpoint load，未伪造成正式指标");

    const moduleList = document.getElementById("moduleList");
    moduleList.innerHTML = "";
    modules.forEach((item) => {
      const node = document.createElement("section");
      node.className = "module-item";
      node.innerHTML = `
        <div><strong>${item.name}</strong><span>${item.result}</span></div>
        <p>${item.function}</p>
        <small>${item.model_status}</small>
      `;
      moduleList.appendChild(node);
    });

    rows("comparisonRows", aggregate.comparison, [
      (r) => r.method || "-",
      (r) => r.checkpoint_type || "-",
      (r) => r.data_type || "-",
      (r) => r.num_images || r.images || r.count || "-",
      (r) => fmt(r.clean_bit_error || r.mean_bit_error),
      (r) => fmt(r.clean_bit_accuracy || r.mean_bit_accuracy),
      (r) => r.defense_ready || r.can_use_for_defense || "-",
      (r) => r.status || "-",
    ]);

    rows("hiddenRows", attackSummaries(hidden.summary), [
      (r) => r.attack_type || r.attack || "-",
      (r) => fmt(r.mean_bit_error),
      (r) => fmt(r.mean_bit_accuracy),
      (r) => fmt(r.mean_psnr),
      (r) => fmt(r.mean_ssim),
      (r) => fmt(r.success_rate),
    ]);

    rows("sepmarkRows", attackSummaries(sepmark.summary), [
      (r) => r.attack_type || r.attack || "-",
      (r) => fmt(r.mean_bit_error),
      (r) => fmt(r.mean_bit_accuracy),
      (r) => fmt(r.mean_bit_error_rf),
      (r) => fmt(r.mean_bit_accuracy_rf),
      (r) => fmt(r.success_rate),
    ]);

    rows("waveguardRows", attackSummaries(waveguard.full_benchmark?.summary || waveguard.small_benchmark?.summary), [
      (r) => r.attack_type || r.attack || "-",
      (r) => fmt(r.mean_bit_error_detector || r.mean_bit_error),
      (r) => fmt(r.mean_bit_accuracy_detector || r.mean_bit_accuracy),
      (r) => fmt(r.mean_bit_error_tracer),
      (r) => fmt(r.mean_bit_accuracy_tracer),
      (r) => fmt(r.success_rate),
    ]);

    const grid = document.getElementById("hiddenGrid");
    if (hidden.grid_image) grid.src = `${API}${hidden.grid_image}?t=${Date.now()}`;
    const sepmarkGrid = document.getElementById("sepmarkGrid");
    if (sepmark.grid_image) sepmarkGrid.src = `${API}${sepmark.grid_image}?t=${Date.now()}`;
    const curve = document.getElementById("degradationCurve");
    if (aggregate.degradation_curve) curve.src = `${API}${aggregate.degradation_curve}?t=${Date.now()}`;

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
      <span>JSON: ${report.json_path}</span>
      <span>CSV: ${report.csv_path}</span>
      <span>Markdown: ${report.markdown_path}</span>
    `;
  } catch (error) {
    text("health", `error: ${error.message}`);
  }
}

load();
setInterval(load, 30000);
