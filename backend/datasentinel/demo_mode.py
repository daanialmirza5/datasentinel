"""Read-only demo mode for public deployments.

When ``DATASENTINEL_DEMO_MODE=true`` the API refuses anything that would store user-supplied data
or change the curated workspace (uploads, deletes, rule and lineage edits). The fault lab, rule
runs and reports remain available because they only create generated or derived data, which
expires under the retention policy.
"""

from __future__ import annotations

import json
import re

from starlette.types import ASGIApp, Receive, Scope, Send

ALLOWED_WRITES = [
    re.compile(r"^/api/v1/experiments$"),
    re.compile(r"^/api/v1/experiments/[\w-]+/regenerate$"),
    re.compile(r"^/api/v1/experiments/[\w-]+$"),  # reset (delete) generated lab data
    re.compile(r"^/api/v1/reports$"),
    re.compile(r"^/api/v1/datasets/[\w-]+/validate$"),
    re.compile(r"^/api/v1/maintenance/(retention|integrity)$"),
]


class DemoModeMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in ("POST", "PATCH", "PUT", "DELETE"):
            path = scope["path"]
            if not any(pattern.match(path) for pattern in ALLOWED_WRITES):
                body = json.dumps(
                    {
                        "error": {
                            "code": "demo_mode",
                            "message": "This is a read-only public demo. Run DataSentinel locally "
                            "to import your own data or edit rules and lineage.",
                        },
                        "request_id": scope.get("state", {}).get("request_id"),
                    }
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
