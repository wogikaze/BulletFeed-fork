"""Run the constructed M1 personas through the real FastAPI state transitions."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from statistics import median
from typing import Any
from unittest.mock import patch

from cryptography.fernet import Fernet

from app.config import get_settings
from app.database import Database
from app.evaluation.m1_zero_to_useful import M1Persona, built_in_personas
from app.routers.acceptance_harness import _statuspage_summary
from app.sync_worker import WatchSyncWorker

BACKEND = Path(__file__).resolve().parents[1]
STAGES = (
    "account",
    "onboarding_profile",
    "topic_recommendation",
    "interests",
    "onboarding_ready",
    "discovery",
    "activation",
    "subscription",
    "worker_subscription",
    "acquisition",
    "feed",
    "evidence",
    "exposure",
    "feedback",
    "read",
    "subsequent_feed",
    "tenant_isolation",
)


def _call(
    client,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    access_token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    response = client.request(method, path, json=payload, headers=headers)
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


def _stage(
    stages: list[dict[str, Any]],
    name: str,
    *,
    ok: bool,
    detail: str,
    metrics: dict[str, Any] | None = None,
) -> None:
    stages.append(
        {
            "stage": name,
            "ok": ok,
            "detail": detail,
            "metrics": metrics or {},
        }
    )
    if not ok:
        raise RuntimeError(f"{name}: {detail}")


def _topic_selection(persona: M1Persona) -> list[str]:
    candidates = (*persona.topics, "React", "TypeScript", "Python", "Rust", "Kubernetes")
    selected: list[str] = []
    seen: set[str] = set()
    for topic in candidates:
        key = topic.casefold()
        if key in seen:
            continue
        seen.add(key)
        selected.append(topic)
    return selected[:5]


def _run_persona(app, database: Database, persona: M1Persona) -> dict[str, Any]:
    from app.dependencies import get_database

    stages: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "persona_id": persona.persona_id,
        "cohort": persona.cohort,
        "language": persona.language,
        "breadth": persona.breadth,
        "security": persona.security,
        "intended_empty_feed": bool(persona.expect_empty_reason),
        "unexpected_empty_feed": False,
        "broken_evidence": False,
        "tenant_leak": False,
        "stages": stages,
    }
    app.dependency_overrides[get_database] = lambda: database
    client = None
    try:
        from fastapi.testclient import TestClient

        client = TestClient(app)
        status, session = _call(client, "/v1/sessions", method="POST", payload={})
        token = session.get("accessToken")
        user_id = session.get("userId")
        _stage(
            stages,
            "account",
            ok=status == 200 and isinstance(token, str) and isinstance(user_id, str),
            detail=f"HTTP {status}",
        )
        status, outsider_session = _call(client, "/v1/sessions", method="POST", payload={})
        outsider_token = outsider_session.get("accessToken")
        if status != 200 or not isinstance(outsider_token, str):
            raise RuntimeError(f"outsider account: HTTP {status}")
        auth = str(token)
        outsider_auth = str(outsider_token)
        profile_interests = list(persona.topics) or [""]
        profile_payload = {
            "occupation": f"{persona.language} {persona.breadth} engineer",
            "interests": profile_interests,
            "region": persona.language,
        }
        status, _ = _call(
            client,
            "/v1/me/profile",
            method="PUT",
            payload=profile_payload,
            access_token=auth,
        )
        _stage(stages, "onboarding_profile", ok=status == 200, detail=f"HTTP {status}")
        status, recommendations = _call(
            client,
            "/v1/me/topic-recommendations",
            access_token=auth,
        )
        _stage(
            stages,
            "topic_recommendation",
            ok=status == 200 and isinstance(recommendations.get("items"), list),
            detail=f"HTTP {status}",
        )

        if persona.expect_empty_reason:
            status, onboarding = _call(
                client,
                "/v1/me/onboarding",
                method="PUT",
                payload={"profile": profile_payload, "topics": [], "connectGithub": False},
                access_token=auth,
            )
            onboarding_status = status
            _stage(
                stages,
                "interests",
                ok=status == 422,
                detail=f"HTTP {status}; expected abstention",
            )
            status, feed = _call(client, "/v1/feed?limit=5", access_token=auth)
            items = feed.get("items", [])
            empty_ok = status in {200, 409} and not items
            _stage(
                stages,
                "onboarding_ready",
                ok=onboarding_status == 422 and onboarding.get("state") != "ready",
                detail=f"HTTP {onboarding_status}; state={onboarding.get('state')}",
            )
            _stage(stages, "feed", ok=empty_ok, detail=f"HTTP {status}; cards={len(items)}")
            _stage(stages, "evidence", ok=True, detail="no cards for intended abstention")
            _stage(stages, "exposure", ok=True, detail="no cards")
            _stage(stages, "feedback", ok=True, detail="no cards")
            _stage(stages, "read", ok=True, detail="no cards")
            _stage(stages, "subsequent_feed", ok=True, detail="no cards")
            report["surfaced"] = 0
            report["useful_proxy_at_5"] = 0
            report["useful_proxy_at_10"] = 0
            report["cards_to_first_useful"] = None
            report["unexpected_empty_feed"] = False
            client.close()
            return report

        topic = persona.topics[0]
        status, _ = _call(
            client,
            "/v1/me/topics",
            method="POST",
            payload={"name": topic, "type": "technology"},
            access_token=auth,
        )
        _stage(stages, "interests", ok=status == 201, detail=f"HTTP {status}")
        onboarding_topics = _topic_selection(persona)
        status, onboarding = _call(
            client,
            "/v1/me/onboarding",
            method="PUT",
            payload={
                "profile": profile_payload,
                "topics": onboarding_topics,
                "connectGithub": False,
            },
            access_token=auth,
        )
        _stage(
            stages,
            "onboarding_ready",
            ok=status == 200 and onboarding.get("state") == "ready",
            detail=f"HTTP {status}; state={onboarding.get('state')}",
            metrics={"topic_count": len(onboarding_topics)},
        )
        status, recommendations = _call(
            client,
            "/v1/me/source-recommendations",
            access_token=auth,
        )
        candidates = recommendations.get("items", [])
        approvable = next(
            (
                item
                for item in candidates
                if isinstance(item, dict)
                and item.get("family") == "rss_atom"
                and item.get("actionability") == "subscribe"
                and not item.get("discoveryOnly")
            ),
            next(
                (
                    item
                    for item in candidates
                    if isinstance(item, dict) and item.get("actionability") == "subscribe"
                ),
                None,
            ),
        )
        _stage(
            stages,
            "discovery",
            ok=status == 200 and approvable is not None,
            detail=f"HTTP {status}; candidates={len(candidates)}",
        )
        status, decision = _call(
            client,
            f"/v1/me/source-recommendations/{approvable['id']}",
            method="POST",
            payload={"decision": "approved"},
            access_token=auth,
        )
        _stage(
            stages,
            "activation",
            ok=status == 200 and decision.get("recommendationStatus") == "approved",
            detail=f"HTTP {status}",
        )
        status, subscriptions = _call(
            client,
            "/v1/me/sources",
            access_token=auth,
        )
        _stage(
            stages,
            "subscription",
            ok=status == 200 and bool(subscriptions.get("items")),
            detail=f"HTTP {status}; subscriptions={len(subscriptions.get('items', []))}",
        )
        status, worker_subscription = _call(
            client,
            "/v1/me/sources",
            method="POST",
            payload={"kind": "statuspage", "pageId": "abcd1234"},
            access_token=auth,
        )
        _stage(
            stages,
            "worker_subscription",
            ok=status in {200, 201} and worker_subscription.get("kind") == "statuspage",
            detail=f"HTTP {status}; kind={worker_subscription.get('kind')}",
        )
        worker = WatchSyncWorker(
            get_settings(),
            database,
            poll_interval_seconds=60,
            batch_size=1,
        )
        worker_now = int(time.time())
        with database.connect() as connection:
            connection.execute(
                """
                UPDATE source_sync_jobs
                SET next_run_at = ?, lease_until = 0, lease_token = NULL
                WHERE NOT (source_type = 'statuspage' AND source_key = 'abcd1234')
                """,
                (worker_now + 3_600,),
            )
            connection.execute(
                """
                UPDATE source_sync_jobs
                SET next_run_at = ?, lease_until = 0, lease_token = NULL
                WHERE source_type = 'statuspage' AND source_key = 'abcd1234'
                """,
                (worker_now,),
            )

        async def fixture_statuspage_summary(settings, page_id: str) -> dict[str, Any]:
            del settings, page_id
            return _statuspage_summary()

        with patch("app.services.statuspage.get_summary", new=fixture_statuspage_summary):
            worker_result = asyncio.run(worker.run_once(now=worker_now))
        with database.connect() as connection:
            observation_count = connection.execute(
                "SELECT COUNT(*) AS count FROM observations WHERE source_type = 'statuspage'"
            ).fetchone()["count"]
        _stage(
            stages,
            "acquisition",
            ok=(
                worker_result.attempted > 0
                and worker_result.succeeded > 0
                and worker_result.failed == 0
                and observation_count > 0
            ),
            detail=(
                f"worker attempted={worker_result.attempted}; "
                f"succeeded={worker_result.succeeded}; failed={worker_result.failed}; "
                f"observations={observation_count}"
            ),
            metrics={
                "worker_attempted": worker_result.attempted,
                "worker_succeeded": worker_result.succeeded,
                "worker_failed": worker_result.failed,
                "observation_count": int(observation_count),
            },
        )
        status, feed = _call(client, "/v1/feed?limit=5", access_token=auth)
        items = feed.get("items", [])
        first = items[0] if items else {}
        unexpected_empty = status == 200 and not items
        report["unexpected_empty_feed"] = unexpected_empty
        _stage(
            stages,
            "feed",
            ok=status == 200 and bool(items),
            detail=f"HTTP {status}; cards={len(items)}",
        )
        status, detail = _call(
            client,
            f"/v1/events/{first.get('eventId')}?fromFeedItem={first.get('id')}",
            access_token=auth,
        )
        evidence_ok = status == 200 and bool(detail.get("sources")) and bool(detail.get("timeline"))
        report["broken_evidence"] = not evidence_ok
        _stage(
            stages,
            "evidence",
            ok=evidence_ok,
            detail=f"HTTP {status}; sources={len(detail.get('sources', []))}",
        )
        status, exposure = _call(
            client,
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
            access_token=auth,
        )
        _stage(
            stages,
            "exposure",
            ok=status == 200 and exposure.get("accepted", 0) > 0,
            detail=f"HTTP {status}; accepted={exposure.get('accepted', 0)}",
        )
        status, _ = _call(
            client,
            f"/v1/feed/items/{first.get('id')}/feedback",
            method="POST",
            payload={"type": "learned_now"},
            access_token=auth,
        )
        _stage(stages, "feedback", ok=status == 200, detail=f"HTTP {status}")
        status, read = _call(
            client,
            f"/v1/feed/items/{first.get('id')}/read",
            method="PUT",
            access_token=auth,
        )
        _stage(
            stages,
            "read",
            ok=status == 200 and read.get("status") == "read",
            detail=f"HTTP {status}; status={read.get('status')}",
        )
        status, subsequent = _call(
            client,
            "/v1/feed?status=unread&limit=5",
            access_token=auth,
        )
        unread_ids = {
            item.get("id") for item in subsequent.get("items", []) if isinstance(item, dict)
        }
        _stage(
            stages,
            "subsequent_feed",
            ok=status == 200 and first.get("id") not in unread_ids,
            detail=f"HTTP {status}; cards={len(subsequent.get('items', []))}",
        )
        status, outsider_feed = _call(client, "/v1/feed?limit=5", access_token=outsider_auth)
        outsider_items = outsider_feed.get("items", [])
        tenant_leak = status == 200 and bool(outsider_items)
        report["tenant_leak"] = tenant_leak
        stages[-1]["metrics"] = {"removed_read_card": first.get("id") not in unread_ids}
        _stage(
            stages,
            "tenant_isolation",
            ok=not tenant_leak,
            detail=f"HTTP {status}; outsider_cards={len(outsider_items)}",
        )
        report["surfaced"] = len(items)
        report["useful_proxy_at_5"] = min(5, len(items))
        report["useful_proxy_at_10"] = min(10, len(items))
        report["cards_to_first_useful"] = 1 if items else None
        client.close()
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if client is not None:
            client.close()
        app.dependency_overrides.clear()
    report["earliest_failure"] = next(
        (stage["stage"] for stage in stages if not stage["ok"]),
        None,
    )
    return report


def _summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    first = sorted(
        report["cards_to_first_useful"]
        for report in reports
        if report.get("cards_to_first_useful") is not None
    )
    return {
        "sample_count": len(reports),
        "surfaced_card_count": sum(int(report.get("surfaced", 0)) for report in reports),
        "useful_proxy_at_5_total": sum(
            int(report.get("useful_proxy_at_5", 0)) for report in reports
        ),
        "useful_proxy_at_10_total": sum(
            int(report.get("useful_proxy_at_10", 0)) for report in reports
        ),
        "cards_to_first_useful": {
            "sample_count": len(first),
            "median": median(first) if first else None,
            "max": max(first) if first else None,
        },
    }


def run_qualification(personas: tuple[M1Persona, ...]) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="bulletfeed-m1-api-"))
    settings_path = root / "settings.db"
    os.environ.update(
        {
            "BULLETFEED_ACCEPTANCE_HARNESS": "1",
            "BULLETFEED_DATABASE_PATH": str(settings_path),
            "BULLETFEED_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "BULLETFEED_GITHUB_CLIENT_ID": "",
            "BULLETFEED_GITHUB_CLIENT_SECRET": "",
            "BULLETFEED_RSS_ALLOWED_HOSTS": (
                "react.dev,blog.python.org,kubernetes.io,github.blog,"
                "blog.jetbrains.com,android-developers.googleblog.com,"
                "blog.flutter.dev,blog.cloudflare.com,openai.com,blog.rust-lang.org,"
                "bun.sh,svelte.dev"
            ),
            "BULLETFEED_WEB_ALLOWED_HOSTS": "react.dev,cisa.gov",
        }
    )
    from app.main import app

    reports = []
    for index, persona in enumerate(personas, start=1):
        database = Database(root / f"persona-{index}.db")
        database.initialize()
        reports.append(_run_persona(app, database, persona))
    stage_failure_counts = {
        stage: sum(
            1
            for report in reports
            if any(row["stage"] == stage and not row["ok"] for row in report["stages"])
        )
        for stage in STAGES
    }
    return {
        "harness_version": "m1-api-qualification-v1",
        "label_source": "constructed",
        "mode": "fresh_api_testclient_database_per_persona_worker_backed",
        "persona_count": len(reports),
        "attempted": len(reports),
        "failed_persona_ids": [
            report["persona_id"] for report in reports if report.get("earliest_failure")
        ],
        "unexpected_empty_feed": sum(
            bool(report.get("unexpected_empty_feed")) for report in reports
        ),
        "broken_evidence": sum(bool(report.get("broken_evidence")) for report in reports),
        "tenant_leak": sum(bool(report.get("tenant_leak")) for report in reports),
        "stage_failure_counts": stage_failure_counts,
        "metrics": _summary(reports),
        "reports": reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    report = run_qualification(built_in_personas())
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 1 if report["failed_persona_ids"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
