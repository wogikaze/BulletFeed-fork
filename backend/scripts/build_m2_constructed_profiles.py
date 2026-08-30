"""Build versioned constructed persona-family profiles for M2."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CORPUS = Path(__file__).resolve().parents[1] / "tests" / "gold" / "real_world_validation" / "v01"


@dataclass(frozen=True)
class Template:
    name: str
    interests: tuple[str, ...]
    products: tuple[str, ...]
    repositories: tuple[str, ...]
    ecosystem: str
    security: str


TEMPLATES = (
    Template(
        "python_backend_developer",
        ("Python", "FastAPI", "pydantic", "uvicorn", "starlette"),
        ("FastAPI",),
        ("fastapi/fastapi",),
        "popular",
        "medium",
    ),
    Template(
        "web_frontend_engineer",
        ("TypeScript", "React", "react-dom", "vite", "webpack"),
        ("React",),
        ("facebook/react",),
        "popular",
        "low",
    ),
    Template(
        "security_conscious_oss_maintainer",
        ("security", "CVE", "cryptography", "bcrypt", "bandit"),
        ("OSV",),
        ("google/osv-scanner",),
        "popular",
        "high",
    ),
    Template(
        "ml_infrastructure_engineer",
        ("Python", "PyTorch", "numpy", "pandas", "transformers"),
        ("PyTorch",),
        ("pytorch/pytorch",),
        "popular",
        "medium",
    ),
    Template(
        "student_learning_compilers",
        ("LLVM", "WebAssembly", "wasm-bindgen", "compiler"),
        ("LLVM",),
        ("llvm/llvm-project",),
        "niche",
        "low",
    ),
    Template(
        "self_hosting_enthusiast",
        ("Linux", "containers", "docker", "nginx", "caddy"),
        ("Caddy",),
        ("caddyserver/caddy",),
        "niche",
        "high",
    ),
    Template(
        "rust_compiler_contributor",
        ("Rust", "LLVM", "serde", "cargo", "rustls"),
        ("Rust",),
        ("rust-lang/rust",),
        "popular",
        "high",
    ),
    Template(
        "android_app_developer",
        ("Android", "Kotlin", "gradle"),
        ("Android",),
        ("android/kotlin",),
        "popular",
        "medium",
    ),
    Template(
        "javascript_tooling_maintainer",
        ("JavaScript", "npm", "eslint", "prettier", "vitest"),
        ("npm",),
        (),
        "popular",
        "medium",
    ),
    Template(
        "typescript_platform_engineer",
        ("TypeScript", "Node.js", "typescript", "hono"),
        ("TypeScript",),
        (),
        "popular",
        "low",
    ),
    Template(
        "node_service_operator",
        ("Node.js", "Express", "express", "fastify", "koa"),
        ("Express",),
        ("expressjs/express",),
        "popular",
        "medium",
    ),
    Template(
        "python_data_scientist",
        ("Python", "pandas", "numpy", "scipy"),
        ("pandas",),
        ("pandas-dev/pandas",),
        "popular",
        "low",
    ),
    Template(
        "django_api_builder",
        ("Django", "Python", "django", "sqlalchemy"),
        ("Django",),
        ("django/django",),
        "popular",
        "medium",
    ),
    Template(
        "rust_web_service_builder",
        ("Rust", "HTTP", "tokio", "reqwest", "axum"),
        ("Tokio",),
        ("tokio-rs/tokio",),
        "niche",
        "medium",
    ),
    Template(
        "kubernetes_platform_sre",
        ("Kubernetes", "Go", "kubernetes", "helm"),
        ("Kubernetes",),
        ("kubernetes/kubernetes",),
        "popular",
        "high",
    ),
    Template(
        "cloud_security_engineer",
        ("security", "AWS", "boto3", "botocore"),
        ("AWS",),
        (),
        "popular",
        "high",
    ),
    Template(
        "database_reliability_engineer",
        ("PostgreSQL", "SQL", "sqlx", "diesel"),
        ("PostgreSQL",),
        (),
        "niche",
        "high",
    ),
    Template(
        "observability_engineer",
        ("OpenTelemetry", "Kubernetes", "tracing", "prometheus"),
        ("OpenTelemetry",),
        (),
        "niche",
        "high",
    ),
    Template(
        "mobile_release_engineer",
        ("Android", "Kotlin", "react-native", "expo"),
        ("Android",),
        (),
        "popular",
        "medium",
    ),
    Template(
        "open_source_documentarian",
        ("documentation", "Markdown", "docusaurus", "vitepress"),
        ("Docs",),
        (),
        "niche",
        "low",
    ),
    Template(
        "package_release_manager",
        ("packages", "releases", "PyPI", "npm", "crates.io"),
        ("PyPI",),
        (),
        "popular",
        "medium",
    ),
    Template(
        "developer_experience_engineer",
        ("CLI", "Rust", "Cargo", "clap", "click"),
        ("Cargo",),
        ("rust-lang/cargo",),
        "niche",
        "low",
    ),
    Template(
        "edge_runtime_engineer",
        ("JavaScript", "WebAssembly", "Cloudflare Workers", "hono"),
        ("Cloudflare Workers",),
        (),
        "niche",
        "medium",
    ),
    Template(
        "ai_application_builder",
        ("Python", "AI", "Transformers", "torch", "huggingface"),
        ("Transformers",),
        ("huggingface/transformers",),
        "popular",
        "medium",
    ),
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _load(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    return payload


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _first_real_event_id(events: list[dict[str, Any]]) -> str:
    return next(event["event_id"] for event in events if event["is_real_event"])


def _profile(template: Template, split: str, variant: int, known_event_id: str) -> dict[str, Any]:
    profile_id = f"prf_m2_{split[0]}_{_slug(template.name)}_{variant:02d}"
    history_rich = variant >= 2
    return {
        "profile_id": profile_id,
        "split": split,
        "constructed_profile": True,
        "cohort": "history_rich" if history_rich else "cold_start",
        "persona_template": template.name,
        "language_focus": ("en", "ja", "mixed")[variant % 3],
        "interest_breadth": "broad" if len(template.interests) > 1 else "narrow",
        "ecosystem": template.ecosystem,
        "explicit_interests": list(template.interests),
        "followed_products": list(template.products),
        "selected_repositories": list(template.repositories),
        "security_sensitivity": template.security,
        "known_before_event_ids": [known_event_id] if history_rich else [],
        "prior_feedback": [f"constructed:{template.name}:prior"] if history_rich else [],
    }


def main() -> None:
    split_rows: dict[str, list[dict[str, Any]]] = {}
    existing_ids: dict[str, set[str]] = {}
    for split in ("pilot", "dev"):
        split_rows[split] = _load(CORPUS / split / "profiles.json")
        existing_ids[split] = {row["profile_id"] for row in split_rows[split]}

    event_ids = {
        split: _first_real_event_id(_load(CORPUS / split / "events.json"))
        for split in ("pilot", "dev")
    }
    added = 0
    updated = 0
    for template in TEMPLATES:
        for variant in range(4):
            split = "pilot" if variant < 2 else "dev"
            row = _profile(template, split, variant, event_ids[split])
            if row["profile_id"] in existing_ids[split]:
                split_rows[split] = [
                    row if item["profile_id"] == row["profile_id"] else item
                    for item in split_rows[split]
                ]
                updated += 1
                continue
            split_rows[split].append(row)
            existing_ids[split].add(row["profile_id"])
            added += 1

    for split, rows in split_rows.items():
        _write(CORPUS / split / "profiles.json", rows)
        index_path = CORPUS / split / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["profile_ids"] = [row["profile_id"] for row in rows]
        _write(index_path, index)
    print(
        json.dumps(
            {
                "added": added,
                "updated": updated,
                "profile_count": sum(len(rows) for rows in split_rows.values()),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
