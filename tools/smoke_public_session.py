#!/usr/bin/env python3
"""End-to-end HTTPS session smoke test without printing credentials or tokens."""

from __future__ import annotations

import argparse
from http.cookiejar import CookieJar
import json
from pathlib import Path
import ssl
import sys
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener


def _request(
    opener: Any,
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any, dict[str, object]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        response = opener.open(request, timeout=30)
    except HTTPError as exc:
        response = exc
    raw = response.read()
    try:
        document = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeError, json.JSONDecodeError):
        document = {}
    return response.status, response.headers, document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", type=Path, required=True)
    arguments = parser.parse_args()

    base_url = arguments.base_url.rstrip("/")
    if not base_url.startswith("https://"):
        parser.error("base URL must use HTTPS")
    password = arguments.password_file.read_text(encoding="utf-8").rstrip("\r\n")
    if not password:
        parser.error("password file is empty")

    cookies = CookieJar()
    opener = build_opener(
        HTTPSHandler(context=ssl.create_default_context()),
        HTTPCookieProcessor(cookies),
    )
    session_url = f"{base_url}/api/session"
    login_url = f"{session_url}/login"
    logout_url = f"{session_url}/logout"

    unauthenticated_status, _, _ = _request(opener, session_url)
    login_status, login_headers, login_document = _request(
        opener,
        login_url,
        method="POST",
        payload={
            "username": arguments.username,
            "password": password,
            "remember": False,
        },
    )
    set_cookie = login_headers.get("Set-Cookie", "")
    session_status, _, session_document = _request(opener, session_url)
    csrf = session_document.get("csrf")
    if not isinstance(csrf, str):
        csrf = ""
    protected_status, _, _ = _request(
        opener,
        f"{base_url}/api/provenance/verify",
        method="POST",
        payload={},
        headers={"X-JYS-CSRF": csrf},
    )
    logout_status, _, logout_document = _request(
        opener,
        logout_url,
        method="POST",
        payload={},
        headers={"X-JYS-CSRF": csrf},
    )
    post_logout_status, _, _ = _request(opener, session_url)

    base_path = urlsplit(base_url).path.strip("/")
    expected_cookie_path = f"/{base_path}/" if base_path else "/"
    checks = {
        "unauthenticated_session_status": unauthenticated_status,
        "login_status": login_status,
        "login_authenticated": login_document.get("authenticated") is True,
        "cookie_httponly": "httponly" in set_cookie.lower(),
        "cookie_secure": "secure" in set_cookie.lower(),
        "cookie_samesite": "samesite=" in set_cookie.lower(),
        "cookie_path_scoped": f"path={expected_cookie_path}" in set_cookie.lower(),
        "session_status": session_status,
        "session_authenticated": session_document.get("authenticated") is True,
        "csrf_present": bool(csrf),
        "authenticated_invalid_post_status": protected_status,
        "logout_status": logout_status,
        "logout_authenticated": logout_document.get("authenticated") is False,
        "post_logout_session_status": post_logout_status,
    }
    success = (
        unauthenticated_status == 401
        and login_status == 200
        and all(
            checks[name] is True
            for name in (
                "login_authenticated",
                "cookie_httponly",
                "cookie_secure",
                "cookie_samesite",
                "cookie_path_scoped",
                "session_authenticated",
                "csrf_present",
                "logout_authenticated",
            )
        )
        and session_status == 200
        and protected_status == 422
        and logout_status == 200
        and post_logout_status == 401
    )
    checks["status"] = "passed" if success else "failed"
    print(json.dumps(checks, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
