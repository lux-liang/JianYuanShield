# API Contract

This document defines the stable API contract for the JianYuanShield backend and frontend integration.

## Compatibility Rules

- Existing successful response fields should not be removed or renamed.
- New fields may be added in a backward-compatible way.
- Benchmark endpoints keep legacy fields such as `summary`, `progress`, `results_csv_exists`, and `sample_results`.
- Benchmark endpoints also expose `normalized`, which is the preferred stable schema for new code.
- Error responses use the unified shape defined below.

## Base URL

Default local backend:

```text
http://127.0.0.1:8026
```

The frontend may override the backend URL with:

```text
?api=http://127.0.0.1:8026
```

or:

```js
window.JYS_API_BASE
```

## Unified Error Response

All handled backend errors return:

```json
{
  "ok": false,
  "error": {
    "code": "not_found",
    "message": "report not found",
    "path": "/api/reports/not-a-real-report"
  }
}
```

Optional validation details may be included:

```json
{
  "ok": false,
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "path": "/api/tasks/demo-run",
    "details": []
  }
}
```

Current error codes:

```text
not_found
http_error
validation_error
internal_error
```

Frontend-only error codes:

```text
network_error
invalid_json
api_error
```

## Health

```http
GET /api/health
```

Response:

```json
{
  "ok": true,
  "root": "/path/to/JianYuanShield",
  "mode": "demo_simulation",
  "version": "0.1.0",
  "timestamp": 1780000000,
  "started_at": 1780000000,
  "uptime_seconds": 12,
  "log_file": "/path/to/logs/backend.log",
  "settings": {
    "log_level": "INFO",
    "enable_demo": true
  },
  "modules": {
    "backend": "ok",
    "artifacts": "ok",
    "benchmarks": "ok",
    "demo": "ok"
  }
}
```

Stable fields:

```text
ok
root
mode
version
timestamp
started_at
uptime_seconds
log_file
settings
modules
```

## Artifacts Status

```http
GET /api/artifacts/status
```

Purpose: single source of truth for local data, weights, benchmark outputs, reports, and visual assets.

Top-level response fields:

```text
generated_at
root
ready_for_demo
checks
missing
summary
groups
datasets
weights
benchmarks
reports
assets
manifest
```

`checks` fields:

```json
{
  "dataset_ready": true,
  "weights_ready": true,
  "benchmark_ready": true,
  "aggregate_ready": true,
  "report_ready": true,
  "assets_ready": true
}
```

`ready_for_demo` is true when:

```text
dataset_ready
weights_ready
benchmark_ready
aggregate_ready
report_ready
```

`assets_ready` is reported but is not currently required for `ready_for_demo`.

`summary` fields:

```json
{
  "dataset_images": 13233,
  "checkpoint_files": 4,
  "benchmark_outputs": 5,
  "asset_files": 12,
  "status": "ready"
}
```

Dataset item shape:

```json
{
  "name": "lfw_full",
  "path": "/abs/path",
  "relative_path": "datasets/lfw_full_upload",
  "exists": true,
  "files": 13233,
  "image_count": 13233,
  "ready": true,
  "status": "ready"
}
```

Weight item shape:

```json
{
  "name": "sepmark",
  "path": "/abs/path",
  "relative_path": "weights/mea/SepMark",
  "exists": true,
  "files": 1,
  "checkpoint_count": 1,
  "ready": true,
  "status": "ready"
}
```

Benchmark status item shape:

```json
{
  "name": "sepmark_lfw",
  "path": "/abs/path",
  "relative_path": "system/reports/sepmark_lfw_benchmark",
  "exists": true,
  "files": 4,
  "summary_exists": true,
  "progress_exists": true,
  "results_csv_exists": true,
  "result_rows": 1000,
  "status": "complete",
  "complete": true,
  "ready": true,
  "num_images": 13233,
  "mode": "real_checkpoint",
  "data_type": "real_lfw_images"
}
```

## Benchmark Endpoints

Current benchmark endpoints:

```http
GET /api/benchmark/hidden-lfw-full
GET /api/benchmark/sepmark
GET /api/benchmark/lidmark-lfw-eval
GET /api/benchmark/waveguard
GET /api/benchmark/aggregate
```

Single benchmark response shape:

```json
{
  "summary": {},
  "progress": {},
  "results_csv_path": "/abs/path/results.csv",
  "results_csv_exists": true,
  "sample_results": [],
  "method": "SepMark",
  "checkpoint_type": "official_mea_checkpoint",
  "data_type": "real_lfw_images",
  "normalized": {}
}
```

`/api/benchmark/waveguard` may also include:

```text
full_benchmark
small_benchmark
```

Each nested benchmark payload follows the same single benchmark response shape.

## Normalized Benchmark Schema

Preferred schema for new code:

```json
{
  "schema_version": "benchmark.v1",
  "method": "SepMark",
  "mode": "real_checkpoint",
  "status": "complete",
  "checkpoint_type": "official_mea_checkpoint",
  "data_type": "real_lfw_images",
  "num_images": 13233,
  "results_csv_exists": true,
  "attacks": [
    {
      "attack": "clean",
      "status": "complete",
      "count": 13233,
      "metrics": {
        "mean_bit_error": 0.01,
        "mean_bit_accuracy": 0.99
      }
    }
  ]
}
```

Stable fields:

```text
schema_version
method
mode
status
checkpoint_type
data_type
num_images
results_csv_exists
attacks
```

Attack item stable fields:

```text
attack
status
count
metrics
```

Metrics are method-specific and should be treated as an open dictionary.

## Aggregate Benchmark

```http
GET /api/benchmark/aggregate
```

Response fields:

```text
summary
comparison_csv_path
comparison
report_md_path
degradation_curve
paths
```

`comparison` is read from `method_comparison.csv` and is intentionally flexible.
New code should prefer `normalized` for single-model benchmark endpoints and use aggregate comparison only for cross-method tables.

## Competition Report

```http
GET /api/competition-report
```

Response:

```json
{
  "report": {},
  "json_path": "/abs/path/report.json",
  "csv_path": "/abs/path/report.csv",
  "markdown_path": "/abs/path/report.md",
  "exists": {
    "json": true,
    "csv": true,
    "markdown": true
  }
}
```

## Modules

```http
GET /api/modules
```

Returns the six platform modules used by the frontend navigation.

Module item fields:

```text
name
function
model_status
result
sample
metrics
defense_ready
```

## Demo APIs

```http
GET /api/samples
GET /api/samples/{sample_id}/image
POST /api/tasks/demo-run
GET /api/reports/{task_id}
GET /api/real-evals
```

`POST /api/tasks/demo-run` request:

```json
{
  "sample_id": "sample_face_001",
  "project": "LIDMark",
  "attack": "multi_embedding+jpeg_50+blur"
}
```

Demo responses are not benchmark evidence. They are runtime simulation outputs and should not be mixed with benchmark summaries.

## Frontend Dependencies

The static frontend currently depends on:

```text
GET /api/health
GET /api/modules
GET /api/artifacts/status
GET /api/benchmark/hidden-lfw-full
GET /api/benchmark/sepmark
GET /api/benchmark/lidmark-lfw-eval
GET /api/benchmark/waveguard
GET /api/benchmark/aggregate
GET /api/competition-report
GET /artifacts/{path}
```

Frontend error handling expects the unified error response shape for non-2xx API responses.
# JianYuanShield API Contract

## Core

- `GET /api/health`
- `GET /api/artifacts/status`
- `GET /api/evidence/audit`
- `GET /api/samples`
- `POST /api/tasks/demo-run`
- `GET /api/reports/{task_id}`

## Benchmarks

- `GET /api/benchmark/hidden-lfw-full`
- `GET /api/benchmark/sepmark`
- `GET /api/benchmark/lidmark-lfw-eval`
- `GET /api/benchmark/waveguard`
- `GET /api/benchmark/aggregate`

## Competition Report

- `GET /api/competition-report`
- `GET /api/competition-report/download/json`
- `GET /api/competition-report/download/csv`
- `GET /api/competition-report/download/markdown`

Demo task responses use `forensic-task.v1` and include SHA-256 evidence. Evidence audits use `evidence-audit.v1`.
