from __future__ import annotations

import asyncio
import base64
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.database import Database
from app.db.topic_catalog import canonical_topic
from app.security import TokenCipher
from app.services import github
from app.services.http import require_json
from app.services.repository_sbom_topics import sbom_topic_signal_text
from app.stores.me_store import MeStore

_MAX_REPOSITORIES = 12
_MAX_MANIFESTS_PER_REPOSITORY = 10
_MAX_MANIFEST_BYTES = 160_000
_MIN_TOPIC_SCORE = 15

_MANIFEST_NAMES = {
    "package.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "gradle.properties",
    "cargo.toml",
    "go.mod",
    "pom.xml",
    "composer.json",
    "gemfile",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}

_PACKAGE_SIGNALS: tuple[tuple[str, str, int], ...] = (
    # JS / TS
    ("typescript", "TypeScript", 24),
    ("react-native", "React Native", 30),
    ("react", "React", 24),
    ("next", "Next.js", 30),
    ("nuxt", "Nuxt", 30),
    ("vue", "Vue", 24),
    ("sveltekit", "SvelteKit", 30),
    ("svelte", "Svelte", 24),
    ("angular", "Angular", 28),
    ("vite", "Vite", 22),
    ("tailwindcss", "Tailwind CSS", 22),
    ("express", "Express", 24),
    ("fastify", "Fastify", 26),
    ("@nestjs", "NestJS", 30),
    ("prisma", "Prisma", 28),
    ("drizzle-orm", "Drizzle ORM", 28),
    ("@apollo", "Apollo GraphQL", 26),
    ("graphql", "GraphQL", 20),
    ("firebase", "Firebase", 26),
    ("@supabase", "Supabase", 28),
    ("@aws-sdk", "AWS", 28),
    ("aws-sdk", "AWS", 24),
    ("openai", "OpenAI API", 28),
    ("@anthropic-ai", "Anthropic API", 30),
    ("@google/generative-ai", "Gemini API", 30),
    ("stripe", "Stripe", 26),
    ("@sentry", "Sentry", 24),
    # Python
    ("fastapi", "FastAPI", 30),
    ("django", "Django", 30),
    ("flask", "Flask", 26),
    ("sqlalchemy", "SQLAlchemy", 26),
    ("psycopg", "PostgreSQL", 24),
    ("asyncpg", "PostgreSQL", 24),
    ("redis", "Redis", 20),
    ("pymongo", "MongoDB", 24),
    ("langchain", "LangChain", 28),
    ("llama-index", "LlamaIndex", 28),
    ("torch", "PyTorch", 28),
    ("tensorflow", "TensorFlow", 28),
    ("anthropic", "Anthropic API", 28),
    ("google-generativeai", "Gemini API", 28),
    ("sentry-sdk", "Sentry", 24),
    ("opentelemetry", "OpenTelemetry", 24),
    # JVM / Android
    ("com.android.application", "Android", 34),
    ("com.android.library", "Android", 30),
    ("org.jetbrains.kotlin.android", "Kotlin", 32),
    ("org.jetbrains.kotlin.jvm", "Kotlin", 28),
    ("org.jetbrains.compose", "Jetpack Compose", 24),
    ("androidx.compose", "Jetpack Compose", 34),
    ("androidx.room", "Room", 28),
    ("com.google.firebase", "Firebase", 28),
    ("io.ktor", "Ktor", 30),
    ("org.springframework.boot", "Spring Boot", 32),
    # Rust / Go
    ("axum", "Axum", 28),
    ("actix-web", "Actix Web", 28),
    ("tokio", "Rust", 18),
    ("github.com/gin-gonic/gin", "Gin", 30),
    ("google.golang.org/grpc", "gRPC", 28),
    ("k8s.io/", "Kubernetes", 24),
    # Infra / observability
    ("terraform", "Terraform", 26),
    ("opentofu", "OpenTofu", 28),
    ("provider \"aws\"", "AWS", 32),
    ("aws_", "AWS", 28),
    ("provider \"google\"", "Google Cloud", 32),
    ("google_project", "Google Cloud", 26),
    ("provider \"azurerm\"", "Microsoft Azure", 32),
    ("azurerm_", "Microsoft Azure", 28),
    ("kubernetes", "Kubernetes", 26),
    ("helm", "Helm", 22),
    ("prometheus", "Prometheus", 24),
    ("grafana", "Grafana", 20),
    ("datadog", "Datadog", 24),
    ("cloudflare", "Cloudflare", 20),
    ("wrangler", "Cloudflare Workers", 30),
)


def _manifest_candidate(path: str) -> bool:
    lowered = path.casefold()
    name = lowered.rsplit("/", 1)[-1]
    if name in _MANIFEST_NAMES:
        return True
    if lowered.startswith(".github/workflows/") and lowered.endswith((".yml", ".yaml")):
        return True
    if lowered.endswith(".tf") and lowered.count("/") <= 2:
        return True
    if name.startswith("requirements") and name.endswith(".txt"):
        return True
    return False


def _manifest_priority(path: str) -> tuple[int, int, str]:
    lowered = path.casefold()
    name = lowered.rsplit("/", 1)[-1]
    priority = 5
    primary_manifests = {
        "package.json",
        "pyproject.toml",
        "build.gradle.kts",
        "build.gradle",
        "cargo.toml",
        "go.mod",
        "pom.xml",
    }
    secondary_manifests = {"dockerfile", "docker-compose.yml", "docker-compose.yaml"}
    if name in primary_manifests:
        priority = 0
    elif name.startswith("requirements") or name in secondary_manifests:
        priority = 1
    elif lowered.startswith(".github/workflows/"):
        priority = 2
    elif lowered.endswith(".tf"):
        priority = 3
    return (priority, lowered.count("/"), lowered)


async def _repository_manifest_texts(
    settings: Settings,
    owner: str,
    repository: str,
    token: str,
) -> dict[str, str]:
    metadata = await github.repository_accessible(settings, owner, repository, token)
    if metadata is None:
        return {}
    default_branch = metadata.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        return {}

    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, trust_env=False) as client:
        tree_response = await client.get(
            f"{github.API_URL}/repos/{owner}/{repository}/git/trees/{quote(default_branch, safe='')}",
            headers=github._headers(token),
            params={"recursive": 1},
        )
        tree_data = await require_json(tree_response, "GitHub repository tree")
        if not isinstance(tree_data, dict) or not isinstance(tree_data.get("tree"), list):
            return {}
        paths = [
            item.get("path")
            for item in tree_data["tree"]
            if isinstance(item, dict)
            and item.get("type") == "blob"
            and isinstance(item.get("path"), str)
            and _manifest_candidate(item["path"])
            and int(item.get("size") or 0) <= _MAX_MANIFEST_BYTES
        ]
        selected_paths = sorted(paths, key=_manifest_priority)[:_MAX_MANIFESTS_PER_REPOSITORY]

        async def fetch_text(path: str) -> tuple[str, str] | None:
            response = await client.get(
                f"{github.API_URL}/repos/{owner}/{repository}/contents/{quote(path, safe='/')}",
                headers=github._headers(token),
                params={"ref": default_branch},
            )
            if response.status_code == 404:
                return None
            data = await require_json(response, "GitHub repository manifest")
            if not isinstance(data, dict) or data.get("encoding") != "base64":
                return None
            content = data.get("content")
            if not isinstance(content, str):
                return None
            try:
                raw = base64.b64decode(content, validate=False)
                if len(raw) > _MAX_MANIFEST_BYTES:
                    return None
                return path, raw.decode("utf-8", errors="replace")
            except (ValueError, UnicodeError):
                return None

        fetched = await asyncio.gather(*(fetch_text(path) for path in selected_paths))
    return {path: text for item in fetched if item is not None for path, text in [item]}


def _package_tokens(path: str, text: str) -> set[str]:
    lowered_path = path.casefold()
    lowered = text.casefold()
    tokens = set(re.findall(r"[@a-z0-9_.+/-]{2,}", lowered))
    if lowered_path.endswith("package.json"):
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                sections = (
                    "dependencies",
                    "devDependencies",
                    "peerDependencies",
                    "optionalDependencies",
                )
                for section in sections:
                    dependencies = payload.get(section)
                    if isinstance(dependencies, dict):
                        tokens.update(str(name).casefold() for name in dependencies)
                package_manager = payload.get("packageManager")
                if isinstance(package_manager, str):
                    tokens.add(package_manager.split("@", 1)[0].casefold())
        except json.JSONDecodeError:
            pass
    return tokens


def infer_topics_from_signals(
    languages: dict[str, int],
    github_topics: list[str],
    manifests: dict[str, str],
) -> list[str]:
    scores: defaultdict[str, int] = defaultdict(int)

    def add(raw_name: str, weight: int) -> None:
        canonical = canonical_topic(raw_name)
        if canonical is not None:
            scores[canonical[0]] += weight

    for rank, (language, _) in enumerate(
        sorted(languages.items(), key=lambda item: item[1], reverse=True)[:6]
    ):
        add(language, max(16, 34 - rank * 4))

    for topic in github_topics[:20]:
        add(topic, 24)

    for path, text in manifests.items():
        lowered_path = path.casefold()
        lowered = text.casefold()
        tokens = _package_tokens(path, text)
        name = lowered_path.rsplit("/", 1)[-1]

        if name == "package.json":
            add("Node.js", 20)
            if "pnpm" in tokens:
                add("pnpm", 22)
            elif "yarn" in tokens:
                add("Yarn", 22)
            else:
                add("npm", 16)
        if name in {"pyproject.toml", "poetry.lock"} or name.startswith("requirements"):
            add("Python", 20)
            if "poetry" in lowered or "tool.poetry" in lowered:
                add("Poetry", 24)
        if name.startswith("build.gradle") or name.startswith("settings.gradle"):
            add("Gradle", 22)
        if name == "cargo.toml":
            add("Rust", 22)
        if name == "go.mod":
            add("Go", 22)
        if name == "pom.xml":
            add("Java", 18)
            add("Maven", 24)
        if "dockerfile" in name or name.startswith("docker-compose") or name.startswith("compose."):
            add("Docker", 28)
        if lowered_path.startswith(".github/workflows/"):
            add("GitHub Actions", 28)
        if lowered_path.endswith(".tf"):
            add("Terraform", 30)

        for needle, topic_name, weight in _PACKAGE_SIGNALS:
            normalized = needle.casefold()
            if normalized in tokens or normalized in lowered:
                add(topic_name, weight)

        if "postgres" in lowered or "postgresql" in lowered:
            add("PostgreSQL", 22)
        if "mysql" in lowered:
            add("MySQL", 22)
        if "redis" in lowered:
            add("Redis", 20)
        if "mongodb" in lowered or "mongo:" in lowered:
            add("MongoDB", 22)
        if "kubernetes" in lowered or "kubectl" in lowered:
            add("Kubernetes", 24)
        if "cloudflare/wrangler" in lowered or "wrangler" in tokens:
            add("Cloudflare Workers", 30)

    ranked = [
        name
        for name, score in sorted(scores.items(), key=lambda item: (-item[1], item[0].casefold()))
        if score >= _MIN_TOPIC_SCORE
    ]
    return ranked[:20]


@dataclass(frozen=True)
class RepositoryTopicSyncResult:
    added: list[str]
    already_tracked: list[str]
    inspected_repository_count: int
    failed_repository_count: int


async def infer_repository_topics(
    settings: Settings,
    full_name: str,
    token: str,
) -> list[str]:
    owner, repository = full_name.split("/", 1)
    languages, topics, manifests, sbom_text = await asyncio.gather(
        github.get_repository_languages(settings, owner, repository, token),
        github.get_repository_topics(settings, owner, repository, token),
        _repository_manifest_texts(settings, owner, repository, token),
        sbom_topic_signal_text(
            settings,
            owner=owner,
            repository=repository,
            token=token,
        ),
    )
    if sbom_text:
        manifests = {**manifests, "github-sbom": sbom_text}
    return infer_topics_from_signals(languages, topics, manifests)


async def sync_selected_repository_topics(
    database: Database,
    cipher: TokenCipher,
    *,
    user_id: str,
    settings: Settings,
) -> RepositoryTopicSyncResult:
    with database.connect() as connection:
        token_row = connection.execute(
            """
            SELECT c.github_token_encrypted
            FROM users u
            JOIN github_connections c ON u.github_user_id = c.github_user_id
            WHERE u.id = ?
            """,
            (user_id,),
        ).fetchone()
        repositories = [
            row["full_name"]
            for row in connection.execute(
                """
                SELECT full_name
                FROM github_repo_watches
                WHERE user_id = ? AND selected = 1
                ORDER BY full_name ASC
                LIMIT ?
                """,
                (user_id, _MAX_REPOSITORIES),
            ).fetchall()
        ]
    if token_row is None or not repositories:
        return RepositoryTopicSyncResult([], [], 0, 0)
    token = cipher.decrypt(token_row["github_token_encrypted"])

    semaphore = asyncio.Semaphore(4)

    async def inspect(full_name: str) -> tuple[list[str], bool]:
        async with semaphore:
            try:
                return await infer_repository_topics(settings, full_name, token), True
            except Exception:
                # Repository selection is authoritative even when one repository
                # cannot be inspected (deleted repo, transient API failure, etc.).
                return [], False

    inspected = await asyncio.gather(*(inspect(name) for name in repositories))
    inferred_per_repository = [topics for topics, _ok in inspected]
    failed_repository_count = sum(1 for _topics, ok in inspected if not ok)
    inspected_repository_count = len(repositories) - failed_repository_count
    aggregate: defaultdict[str, int] = defaultdict(int)
    for inferred in inferred_per_repository:
        for rank, name in enumerate(inferred):
            aggregate[name] += max(1, 24 - rank)

    store = MeStore(database)
    existing = {topic.name.casefold(): topic.name for topic in store.list_topics(user_id)}
    added: list[str] = []
    already_tracked: list[str] = []
    for name, _ in sorted(aggregate.items(), key=lambda item: (-item[1], item[0].casefold())):
        canonical = canonical_topic(name)
        if canonical is None:
            continue
        display_name, topic_type = canonical
        existing_name = existing.get(display_name.casefold())
        if existing_name is not None:
            if existing_name not in already_tracked and display_name not in added:
                already_tracked.append(existing_name)
            continue
        if len(existing) >= 20:
            continue
        try:
            # Reproject once after the whole inferred-topic batch. Reprojecting
            # for every topic makes repository save exceed the mobile timeout.
            store.add_topic(user_id, display_name, topic_type, reproject=False)
        except HTTPException as error:
            if error.status_code == 409:
                existing[display_name.casefold()] = display_name
                if display_name not in already_tracked:
                    already_tracked.append(display_name)
                continue
            if error.status_code == 422:
                continue
            raise
        existing[display_name.casefold()] = display_name
        added.append(display_name)
    return RepositoryTopicSyncResult(
        added=added,
        already_tracked=already_tracked,
        inspected_repository_count=inspected_repository_count,
        failed_repository_count=failed_repository_count,
    )
