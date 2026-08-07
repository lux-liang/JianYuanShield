from __future__ import annotations

import ast
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image

from system.backend import infer, security
from system.backend.routes import _validate_attack, _validate_model, artifact_file


_SIMSWAP_RUNNER = Path("system/scripts/run_simswap_lfw_robustness.py")
_SIMSWAP_ARCFACE_SHA256 = (
    "52ea5ce4902017b77a2bb811dd9a82f57dee3883e06c18a42d288437263c7a20"
)


def _exact_pinned_arcface_legacy_load(
    *,
    relative_path: Path,
    tree: ast.AST,
    call: ast.Call,
) -> bool:
    """Recognize only SimSwap's exact-hash-gated official full-Module load."""

    if relative_path != _SIMSWAP_RUNNER:
        return False
    enclosing = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(descendant is call for descendant in ast.walk(node))
    ]
    if len(enclosing) != 1 or enclosing[0].name != "_load_official_arcface_checkpoint":
        return False
    function = enclosing[0]
    if not call.args or not isinstance(call.args[0], ast.Name) or call.args[0].id != "handle":
        return False
    weights_only = next(
        (keyword.value for keyword in call.keywords if keyword.arg == "weights_only"),
        None,
    )
    if not isinstance(weights_only, ast.Constant) or weights_only.value is not False:
        return False

    guarded_with: ast.With | None = None
    for candidate in ast.walk(function):
        if not isinstance(candidate, ast.With):
            continue
        if not any(descendant is call for statement in candidate.body for descendant in ast.walk(statement)):
            continue
        if len(candidate.items) != 1:
            return False
        item = candidate.items[0]
        context = item.context_expr
        if not (
            isinstance(context, ast.Call)
            and isinstance(context.func, ast.Name)
            and context.func.id == "_verified_checkpoint_handle"
            and len(context.args) == 1
            and isinstance(context.args[0], ast.Name)
            and context.args[0].id == "path"
            and isinstance(item.optional_vars, ast.Name)
            and item.optional_vars.id == "handle"
        ):
            return False
        trusted = next(
            (
                keyword.value
                for keyword in context.keywords
                if keyword.arg == "trusted_sha256"
            ),
            None,
        )
        if not isinstance(trusted, ast.Name) or trusted.id != "ARCFACE_SHA256":
            return False
        guarded_with = candidate
    if guarded_with is None:
        return False

    pinned_constant = False
    helper_source = ""
    source_text = Path(__file__).resolve().parents[1].joinpath(relative_path).read_text(
        encoding="utf-8"
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "ARCFACE_SHA256"
            for target in node.targets
        ):
            pinned_constant = (
                isinstance(node.value, ast.Constant)
                and node.value.value == _SIMSWAP_ARCFACE_SHA256
            )
        if isinstance(node, ast.FunctionDef) and node.name == "_verified_checkpoint_handle":
            helper_source = ast.get_source_segment(source_text, node) or ""
    return pinned_constant and all(
        marker in helper_source
        for marker in (
            '_sha256_stream(handle)',
            'actual != trusted_sha256',
            'raise RuntimeError',
            'handle.seek(0)',
            'yield handle',
        )
    )


def png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (20, 40, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


class SecurityTests(unittest.TestCase):
    def test_checkpoint_loads_use_weights_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        offenders: list[str] = []
        for directory in (root / "system", root / "scripts"):
            for path in directory.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    function = node.func
                    is_torch_load = (
                        isinstance(function, ast.Attribute)
                        and function.attr == "load"
                        and isinstance(function.value, ast.Name)
                        and function.value.id == "torch"
                    )
                    if not is_torch_load:
                        continue
                    weights_only = next(
                        (keyword.value for keyword in node.keywords if keyword.arg == "weights_only"),
                        None,
                    )
                    if not isinstance(weights_only, ast.Constant) or weights_only.value is not True:
                        if _exact_pinned_arcface_legacy_load(
                            relative_path=path.relative_to(root),
                            tree=tree,
                            call=node,
                        ):
                            continue
                        offenders.append(f"{path.relative_to(root)}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_valid_image_payload_is_accepted(self) -> None:
        payload = png_bytes()
        self.assertIs(security.validate_image_bytes(payload, media_type="image/png"), payload)

    def test_media_type_must_match_content(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            security.validate_image_bytes(png_bytes(), media_type="image/jpeg")
        self.assertEqual(raised.exception.status_code, 415)

    def test_pixel_limit_is_enforced_before_decode(self) -> None:
        limited = SimpleNamespace(
            max_image_pixels=16,
            max_upload_bytes=security.settings.max_upload_bytes,
            require_api_key=False,
            api_key=None,
        )
        with patch.object(security, "settings", limited):
            with self.assertRaises(HTTPException) as raised:
                security.validate_image_bytes(png_bytes((8, 8)), media_type="image/png")
        self.assertEqual(raised.exception.status_code, 413)

    def test_identifiers_reject_path_traversal(self) -> None:
        for value in ("../secret", "/tmp/file", "a/b", "a\\b"):
            with self.subTest(value=value), self.assertRaises(HTTPException):
                security.validate_identifier(value, field="task_id")

    def test_api_key_is_fail_closed_when_required(self) -> None:
        configured = SimpleNamespace(require_api_key=True, api_key="expected")
        with patch.object(security, "settings", configured):
            with self.assertRaises(HTTPException) as raised:
                security.require_api_key("wrong")
            self.assertEqual(raised.exception.status_code, 401)
            self.assertIsNone(security.require_api_key("expected"))

    def test_model_and_attack_values_are_allowlisted(self) -> None:
        self.assertEqual(_validate_model("LIDMark"), "LIDMark")
        self.assertEqual(_validate_attack("jpeg50"), "jpeg50")
        self.assertEqual(_validate_attack("deepfake_proxy_v1"), "deepfake_proxy_v1")
        self.assertEqual(_validate_attack("gaussian_noise_sigma_3"), "gaussian_noise_sigma_3")
        with self.assertRaises(HTTPException):
            _validate_model("../../model")
        with self.assertRaises(HTTPException):
            _validate_attack("custom-shell-token")

    def test_artifact_route_rejects_path_traversal(self) -> None:
        with self.assertRaises(HTTPException) as context:
            artifact_file("../../etc/passwd")
        self.assertEqual(context.exception.status_code, 404)

    def test_ttl_cleanup_only_removes_ephemeral_task_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            reports = root / "reports"
            expired = assets / ("a" * 12)
            protected = assets / "provenance"
            expired.mkdir(parents=True)
            protected.mkdir()
            reports.mkdir()
            (reports / f"{'a' * 12}.json").write_text(
                json.dumps({
                    "schema_version": "infer-single.v1",
                    "task_id": "a" * 12,
                }),
                encoding="utf-8",
            )
            unmarked = assets / ("b" * 12)
            unmarked.mkdir()
            orphan_id = "c" * 12
            orphan_report = reports / f"{orphan_id}.json"
            orphan_report.write_text(
                json.dumps({
                    "schema_version": "infer-single.v1",
                    "task_id": orphan_id,
                }),
                encoding="utf-8",
            )
            os.utime(expired, (1, 1))
            os.utime(unmarked, (1, 1))
            os.utime(orphan_report, (1, 1))
            with (
                patch.object(infer, "ASSETS", assets),
                patch.object(infer, "REPORTS", reports),
                patch.object(infer, "settings", SimpleNamespace(artifact_ttl_seconds=10)),
            ):
                removed = infer.cleanup_expired_inference_artifacts(now=100)
            self.assertEqual(removed, 2)
            self.assertFalse(expired.exists())
            self.assertFalse((reports / f"{'a' * 12}.json").exists())
            self.assertTrue(protected.exists())
            self.assertTrue(unmarked.exists())
            self.assertFalse(orphan_report.exists())


if __name__ == "__main__":
    unittest.main()
