"""Run the clean-room backend portion of the M7 integrated journey."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from run_process_recovery_drill import (
    _free_port,
    _request,
    _start_api,
    _start_worker,
    _stop,
    _wait_for_status,
)

BACKEND = Path(__file__).resolve().parents[1]


def _json_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    access_token: str | None = None,
) -> tuple[int | None, dict[str, Any]]:
    status, body = _request(
        f"{base_url}{path}",
        method=method,
        payload=payload,
        access_token=access_token,
    )
    if body:
        decoded = json.loads(body)
    else:
        decoded = {}
    if not isinstance(decoded, dict):
        raise RuntimeError(f"{method} {path} returned a non-object response")
    return status, decoded


def _stage(
    stages: list[dict[str, Any]],
    name: str,
    *,
    ok: bool,
    detail: str,
) -> None:
    stages.append({"stage": name, "ok": ok, "detail": detail})
    if not ok:
        raise RuntimeError(f"{name}: {detail}")


def _emit(result: dict[str, Any], output: Path | None) -> None:
    public_result = dict(result)
    public_result.pop("user_id", None)
    payload = json.dumps(public_result, ensure_ascii=False, indent=2) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    workdir = Path(tempfile.mkdtemp(prefix="bulletfeed-clean-room-"))
    database_path = workdir / "data" / "bulletfeed.db"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(BACKEND) + os.pathsep + env.get("PYTHONPATH", ""),
            "BULLETFEED_ACCEPTANCE_HARNESS": "1",
            "BULLETFEED_DATABASE_PATH": str(database_path),
            "BULLETFEED_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "BULLETFEED_GITHUB_CLIENT_ID": "",
            "BULLETFEED_GITHUB_CLIENT_SECRET": "",
            "BULLETFEED_RSS_ALLOWED_HOSTS": "react.dev",
            "BULLETFEED_WEB_ALLOWED_HOSTS": "cisa.gov,react.dev",
            "BULLETFEED_WORKER_IDLE_SECONDS": "0.25",
            "BULLETFEED_WORKER_POLL_SECONDS": "1",
        }
    )
    api = None
    worker = None
    stages: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "acceptance_version": "m7-clean-room-backend-v1",
        "mode": "fresh_ephemeral_backend",
        "stages": stages,
        "limitations": [
            "source acquisition uses the local acceptance seed fixture; "
            "live OAuth and real user enrollment are excluded"
        ],
    }
    try:
        worker = _start_worker(env)
        api = _start_api(env, port)
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_status(f"{base_url}/health", 200, timeout_seconds=40, label="API health")
        _wait_for_status(
            f"{base_url}/health/ready",
            200,
            timeout_seconds=40,
            label="worker readiness",
        )
        _stage(stages, "stack", ok=True, detail="fresh database, API, and worker are ready")

        status, session = _json_request(base_url, "/v1/sessions", method="POST", payload={})
        if status != 200 or not session.get("accessToken") or not session.get("userId"):
            _stage(stages, "session", ok=False, detail=f"HTTP {status}")
        access_token = str(session["accessToken"])
        user_id = str(session["userId"])
        result["user_id"] = user_id
        _stage(stages, "session", ok=True, detail="anonymous session persisted")

        status, _ = _json_request(
            base_url,
            "/v1/me/profile",
            method="PUT",
            payload={"occupation": "backend engineer", "interests": ["React"], "region": "jp"},
            access_token=access_token,
        )
        _stage(stages, "onboarding_profile", ok=status == 200, detail=f"HTTP {status}")
        status, topic = _json_request(
            base_url,
            "/v1/me/topics",
            method="POST",
            payload={"name": "React", "type": "technology"},
            access_token=access_token,
        )
        _stage(
            stages,
            "interest",
            ok=status == 201 and topic.get("name") == "React",
            detail=f"HTTP {status}",
        )
        status, onboarding = _json_request(
            base_url,
            "/v1/me/onboarding",
            method="PUT",
            payload={
                "profile": {
                    "occupation": "backend engineer",
                    "interests": ["React"],
                    "region": "jp",
                },
                "topics": ["React", "TypeScript", "Vite", "JavaScript", "Node.js"],
                "connectGithub": False,
            },
            access_token=access_token,
        )
        _stage(
            stages,
            "onboarding_ready",
            ok=status == 200 and onboarding.get("state") == "ready",
            detail=f"HTTP {status}; state={onboarding.get('state')}",
        )

        status, recommendations = _json_request(
            base_url,
            "/v1/me/source-recommendations",
            access_token=access_token,
        )
        items = recommendations.get("items", [])
        rss = next(
            (
                item
                for item in items
                if isinstance(item, dict)
                and item.get("family") == "rss_atom"
                and item.get("actionability") == "subscribe"
                and not item.get("discoveryOnly")
            ),
            None,
        )
        _stage(
            stages,
            "discovery",
            ok=status == 200 and rss is not None,
            detail=f"HTTP {status}; candidates={len(items)}",
        )
        status, decision = _json_request(
            base_url,
            f"/v1/me/source-recommendations/{rss['id']}",
            method="POST",
            payload={"decision": "approved"},
            access_token=access_token,
        )
        _stage(
            stages,
            "activation",
            ok=status == 200 and decision.get("recommendationStatus") == "approved",
            detail=f"HTTP {status}",
        )
        status, subscriptions = _json_request(
            base_url,
            "/v1/me/sources",
            access_token=access_token,
        )
        _stage(
            stages,
            "subscription",
            ok=status == 200 and bool(subscriptions.get("items")),
            detail=f"HTTP {status}; subscriptions={len(subscriptions.get('items', []))}",
        )

        status, seeded = _json_request(
            base_url,
            "/__acceptance__/seed-statuspage",
            method="POST",
            payload={"userId": user_id},
        )
        event_ids = seeded.get("eventIds", [])
        _stage(
            stages,
            "acquisition_projection",
            ok=status == 200 and bool(event_ids) and seeded.get("projectedItemCount", 0) > 0,
            detail=f"HTTP {status}; events={len(event_ids)}",
        )
        status, feed = _json_request(
            base_url,
            "/v1/feed?limit=5",
            access_token=access_token,
        )
        feed_items = feed.get("items", [])
        first = feed_items[0] if feed_items else {}
        _stage(
            stages,
            "feed",
            ok=status == 200 and bool(feed_items),
            detail=f"HTTP {status}; cards={len(feed_items)}",
        )
        status, detail = _json_request(
            base_url,
            f"/v1/events/{first.get('eventId')}?fromFeedItem={first.get('id')}",
            access_token=access_token,
        )
        _stage(
            stages,
            "evidence",
            ok=status == 200 and bool(detail.get("sources")) and bool(detail.get("timeline")),
            detail=f"HTTP {status}; sources={len(detail.get('sources', []))}",
        )
        status, exposure = _json_request(
            base_url,
            "/v1/feed/exposures",
            method="POST",
            payload={
                "items": [
                    {
                        "deliveryId": first.get("deliveryId"),
                        "displayedAt": "2026-08-30T00:00:00Z",
                        "dwellMs": 1_500,
                        "visibleRatio": 0.8,
                        "detailOpened": True,
                    }
                ]
            },
            access_token=access_token,
        )
        _stage(
            stages,
            "exposure",
            ok=status == 200 and exposure.get("accepted", 0) > 0,
            detail=f"HTTP {status}; accepted={exposure.get('accepted', 0)}",
        )
        status, _ = _json_request(
            base_url,
            f"/v1/feed/items/{first.get('id')}/feedback",
            method="POST",
            payload={"type": "learned_now"},
            access_token=access_token,
        )
        _stage(stages, "feedback", ok=status == 200, detail=f"HTTP {status}")
        status, read = _json_request(
            base_url,
            f"/v1/feed/items/{first.get('id')}/read",
            method="PUT",
            access_token=access_token,
        )
        _stage(
            stages,
            "read_state",
            ok=status == 200 and read.get("status") == "read",
            detail=f"HTTP {status}; status={read.get('status')}",
        )
        status, subsequent = _json_request(
            base_url,
            "/v1/feed?status=unread&limit=5",
            access_token=access_token,
        )
        unread_ids = {item.get("id") for item in subsequent.get("items", []) if isinstance(item, dict)}
        _stage(
            stages,
            "subsequent_feed",
            ok=status == 200 and first.get("id") not in unread_ids,
            detail=f"HTTP {status}; cards={len(subsequent.get('items', []))}",
        )
        result["status"] = "passed"
        _emit(result, args.output)
        return 0
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        _emit(result, args.output)
        return 1
    finally:
        _stop(api)
        _stop(worker)
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
