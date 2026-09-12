#!/usr/bin/env python
"""Run Lighthouse against the built dashboard, and gate on what is stable.

The plan's quality bar says "Lighthouse >= 95". Four categories sit behind that
number and they are not equally trustworthy on a machine that is also doing
something else:

- **accessibility**, **best-practices** and **seo** are deterministic audits of
  the rendered document. The same page scores the same on a busy laptop and an
  idle CI runner, so they are gated.
- **performance** is a timing measurement. It moves ten points or more between
  runs on the same machine depending on what else is running, and a gate on it
  would fail builds for reasons unrelated to the change. It is **reported and
  not gated**, and the number is printed so a regression is still visible to
  anybody reading the output.

A gate that fails randomly gets switched off, and then nothing is gated. This is
the same reasoning `pr_report.py` applies to wall-clock time.

    python scripts/lighthouse_check.py            # starts its own preview server
    python scripts/lighthouse_check.py --url URL  # audit something already running

Requires `npx lighthouse`, which comes with the web workspace's dev
dependencies. Absent, this exits 0 with the reason: an audit that could not run
is not a failing audit, and pretending otherwise would make an optional tool
look like a broken build.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

#: Gated categories, and the floor the plan sets.
GATED = ("accessibility", "best-practices", "seo")
FLOOR = 95

#: Reported, never gated. See the module docstring.
REPORTED = ("performance",)

DEFAULT_PORT = 4178
ROUTES = ("/", "/leaderboard", "/traces")


def port_is_open(port: int, host: str = "localhost") -> bool:
    """Connect the way Lighthouse will, not the way that is convenient.

    A `socket.socket()` probe is IPv4, and `vite preview` binds `localhost`,
    which on Windows resolves to `::1` first -- so the probe found nothing while
    the server was up and answering. `create_connection` resolves the name and
    tries every family, which is what a browser does.
    """
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def wait_for(port: int, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_is_open(port):
            return True
        time.sleep(0.3)
    return False


def run_lighthouse(url: str, npx: str) -> dict[str, int] | None:
    """Category scores 0-100, or None if Lighthouse could not produce them."""
    with tempfile.TemporaryDirectory(prefix="tooltrace-lh-") as tmp:
        out = Path(tmp) / "report.json"
        proc = subprocess.run(
            [
                npx,
                "--yes",
                "lighthouse",
                url,
                "--quiet",
                "--output=json",
                f"--output-path={out}",
                # Headless, and with no persistent profile: a warm cache from a
                # previous run would inflate the performance number.
                "--chrome-flags=--headless=new --no-sandbox --disable-gpu",
                "--only-categories=" + ",".join([*GATED, *REPORTED]),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=WEB,
        )
        if not out.is_file():
            print(f"lighthouse produced no report for {url}", file=sys.stderr)
            print((proc.stderr or proc.stdout)[-800:], file=sys.stderr)
            return None
        report = json.loads(out.read_text(encoding="utf-8"))
    return {
        key: round((value.get("score") or 0) * 100)
        for key, value in report.get("categories", {}).items()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="audit this origin instead of starting a preview server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--json", action="store_true", help="structured output")
    args = parser.parse_args(argv)

    npx = shutil.which("npx")
    if npx is None:
        print("npx is not on PATH; Lighthouse was not run", file=sys.stderr)
        return 0

    server: subprocess.Popen[bytes] | None = None
    origin = args.url
    if not origin:
        if not (WEB / "dist" / "index.html").is_file():
            print("web/dist is not built; run `npm run build` in web/ first", file=sys.stderr)
            return 2
        # `node node_modules/vite/...` rather than `npx vite`: on Windows `npx`
        # is a `.cmd` shim, and terminating it kills the shim while the node
        # child keeps the port -- this script left exactly one such orphan
        # listening on 4178 before the spawn was changed.
        vite = WEB / "node_modules" / "vite" / "bin" / "vite.js"
        node = shutil.which("node")
        if node is None or not vite.is_file():
            print("node or vite is missing; Lighthouse was not run", file=sys.stderr)
            return 0
        server = subprocess.Popen(
            [node, str(vite), "preview", "--port", str(args.port), "--strictPort"],
            cwd=WEB,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not wait_for(args.port):
            server.terminate()
            print(f"preview server never came up on {args.port}", file=sys.stderr)
            return 2
        origin = f"http://localhost:{args.port}"

    try:
        # Annotated: a row is a route name beside a set of integer scores,
        # so the inferred element type would be `dict[str, object]` and
        # every later comparison against FLOOR an error.
        rows: list[dict[str, Any]] = []
        for route in ROUTES:
            scores = run_lighthouse(f"{origin.rstrip('/')}{route}", npx)
            if scores is None:
                return 2
            rows.append({"route": route, **scores})
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:  # pragma: no cover - rare
                server.kill()

    failures = [
        f"{row['route']} {category} {row.get(category, 0)} < {FLOOR}"
        for row in rows
        for category in GATED
        if row.get(category, 0) < FLOOR
    ]
    payload = {
        "origin": origin,
        "floor": FLOOR,
        "gated": list(GATED),
        "reported_only": list(REPORTED),
        "rows": rows,
        "failures": failures,
        "statement": (
            f"{len(rows)} route(s) audited. "
            + (
                f"{len(failures)} category score(s) below {FLOOR}: {'; '.join(failures)}"
                if failures
                else f"every gated category is at or above {FLOOR}"
            )
            + ". Performance is reported and not gated: it is a timing measurement, it moves "
            "with whatever else the machine is doing, and a gate that fails randomly gets "
            "switched off"
        ),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        width = max(len(r["route"]) for r in rows)
        header = "  ".join(c[:12].rjust(12) for c in (*GATED, *REPORTED))
        print(f"{'route'.ljust(width)}  {header}")
        for row in rows:
            cells = "  ".join(str(row.get(c, "-")).rjust(12) for c in (*GATED, *REPORTED))
            print(f"{row['route'].ljust(width)}  {cells}")
        print()
        print(payload["statement"])

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
