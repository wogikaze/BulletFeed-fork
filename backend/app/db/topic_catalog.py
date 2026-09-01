from __future__ import annotations

import re
from collections.abc import Iterable

from app.database import Database

# Runtime topic catalog. Keep this independent from demo fixtures so production
# startup never needs the demo event/feed seed module.
TOPIC_CATALOG: list[tuple[str, str, str]] = [
    # Languages / runtimes
    ("topic_kotlin", "Kotlin", "technology"),
    ("topic_java", "Java", "technology"),
    ("topic_python", "Python", "technology"),
    ("topic_javascript", "JavaScript", "technology"),
    ("topic_typescript", "TypeScript", "technology"),
    ("topic_go", "Go", "technology"),
    ("topic_rust", "Rust", "technology"),
    ("topic_llvm", "LLVM", "technology"),
    ("topic_swift", "Swift", "technology"),
    ("topic_dart", "Dart", "technology"),
    ("topic_ruby", "Ruby", "technology"),
    ("topic_php", "PHP", "technology"),
    ("topic_csharp", "C#", "technology"),
    ("topic_cpp", "C++", "technology"),
    ("topic_nodejs", "Node.js", "technology"),
    ("topic_bun", "Bun", "technology"),
    ("topic_deno", "Deno", "technology"),
    # Mobile / client
    ("topic_android", "Android", "technology"),
    ("topic_compose", "Jetpack Compose", "technology"),
    ("topic_android_gradle_plugin", "Android Gradle Plugin", "technology"),
    ("topic_flutter", "Flutter", "technology"),
    ("topic_react_native", "React Native", "technology"),
    ("topic_ios", "iOS", "technology"),
    ("topic_swiftui", "SwiftUI", "technology"),
    # Web / app frameworks
    ("topic_react", "React", "technology"),
    ("topic_nextjs", "Next.js", "technology"),
    ("topic_vue", "Vue", "technology"),
    ("topic_nuxt", "Nuxt", "technology"),
    ("topic_svelte", "Svelte", "technology"),
    ("topic_sveltekit", "SvelteKit", "technology"),
    ("topic_angular", "Angular", "technology"),
    ("topic_vite", "Vite", "technology"),
    ("topic_tailwind", "Tailwind CSS", "technology"),
    ("topic_fastapi", "FastAPI", "technology"),
    ("topic_django", "Django", "technology"),
    ("topic_flask", "Flask", "technology"),
    ("topic_rails", "Ruby on Rails", "technology"),
    ("topic_spring", "Spring Boot", "technology"),
    ("topic_ktor", "Ktor", "technology"),
    ("topic_express", "Express", "technology"),
    ("topic_fastify", "Fastify", "technology"),
    ("topic_nestjs", "NestJS", "technology"),
    ("topic_aspnet", "ASP.NET Core", "technology"),
    ("topic_laravel", "Laravel", "technology"),
    ("topic_axum", "Axum", "technology"),
    ("topic_actix", "Actix Web", "technology"),
    ("topic_gin", "Gin", "technology"),
    # Data / messaging
    ("topic_postgresql", "PostgreSQL", "technology"),
    ("topic_mysql", "MySQL", "technology"),
    ("topic_sqlite", "SQLite", "technology"),
    ("topic_redis", "Redis", "technology"),
    ("topic_mongodb", "MongoDB", "technology"),
    ("topic_elasticsearch", "Elasticsearch", "technology"),
    ("topic_opensearch", "OpenSearch", "technology"),
    ("topic_clickhouse", "ClickHouse", "technology"),
    ("topic_kafka", "Apache Kafka", "technology"),
    ("topic_rabbitmq", "RabbitMQ", "technology"),
    ("topic_prisma", "Prisma", "technology"),
    ("topic_sqlalchemy", "SQLAlchemy", "technology"),
    ("topic_drizzle", "Drizzle ORM", "technology"),
    ("topic_room", "Room", "technology"),
    # Cloud / infrastructure
    ("topic_aws", "AWS", "service"),
    ("topic_gcp", "Google Cloud", "service"),
    ("topic_azure", "Microsoft Azure", "service"),
    ("topic_cloudflare", "Cloudflare", "service"),
    ("topic_workers", "Cloudflare Workers", "service"),
    ("topic_vercel", "Vercel", "service"),
    ("topic_netlify", "Netlify", "service"),
    ("topic_firebase", "Firebase", "service"),
    ("topic_supabase", "Supabase", "service"),
    ("topic_docker", "Docker", "technology"),
    ("topic_kubernetes", "Kubernetes", "technology"),
    ("topic_terraform", "Terraform", "technology"),
    ("topic_opentofu", "OpenTofu", "technology"),
    ("topic_ansible", "Ansible", "technology"),
    ("topic_helm", "Helm", "technology"),
    ("topic_nginx", "NGINX", "technology"),
    # CI/CD / developer platform
    ("topic_github", "GitHub", "service"),
    ("topic_github_actions", "GitHub Actions", "service"),
    ("topic_gitlab", "GitLab", "service"),
    ("topic_circleci", "CircleCI", "service"),
    ("topic_gradle", "Gradle", "technology"),
    ("topic_maven", "Maven", "technology"),
    ("topic_npm", "npm", "technology"),
    ("topic_pnpm", "pnpm", "technology"),
    ("topic_yarn", "Yarn", "technology"),
    ("topic_poetry", "Poetry", "technology"),
    # APIs / protocols
    ("topic_graphql", "GraphQL", "technology"),
    ("topic_grpc", "gRPC", "technology"),
    ("topic_openapi", "OpenAPI", "technology"),
    ("topic_apollo", "Apollo GraphQL", "technology"),
    # AI / ML
    ("topic_openai", "OpenAI API", "service"),
    ("topic_anthropic", "Anthropic API", "service"),
    ("topic_gemini", "Gemini API", "service"),
    ("topic_huggingface", "Hugging Face", "service"),
    ("topic_langchain", "LangChain", "technology"),
    ("topic_llamaindex", "LlamaIndex", "technology"),
    ("topic_pytorch", "PyTorch", "technology"),
    ("topic_tensorflow", "TensorFlow", "technology"),
    # Observability / security
    ("topic_opentelemetry", "OpenTelemetry", "technology"),
    ("topic_prometheus", "Prometheus", "technology"),
    ("topic_grafana", "Grafana", "service"),
    ("topic_sentry", "Sentry", "service"),
    ("topic_datadog", "Datadog", "service"),
    ("topic_renovate", "Renovate", "service"),
    ("topic_dependabot", "Dependabot", "service"),
    # Common product/platform dependencies
    ("topic_stripe", "Stripe", "service"),
    ("topic_twilio", "Twilio", "service"),
    ("topic_sendgrid", "SendGrid", "service"),
    ("topic_auth0", "Auth0", "service"),
    ("topic_clerk", "Clerk", "service"),
    # Companies frequently followed as change sources
    ("topic_company_google", "Google", "company"),
    ("topic_company_microsoft", "Microsoft", "company"),
    ("topic_company_apple", "Apple", "company"),
    ("topic_company_amazon", "Amazon", "company"),
    ("topic_company_meta", "Meta", "company"),
    ("topic_company_openai", "OpenAI", "company"),
    ("topic_company_cloudflare", "Cloudflare", "company"),
    ("topic_company_jetbrains", "JetBrains", "company"),
]


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


TOPIC_BY_KEY = {_key(name): (name, topic_type) for _, name, topic_type in TOPIC_CATALOG}

# Aliases from repository metadata/package identifiers into user-facing topics.
TOPIC_ALIASES: dict[str, str] = {
    "js": "JavaScript",
    "ts": "TypeScript",
    "node": "Node.js",
    "nodejs": "Node.js",
    "reactjs": "React",
    "next": "Next.js",
    "nextjs": "Next.js",
    "vuejs": "Vue",
    "nuxtjs": "Nuxt",
    "sveltekit": "SvelteKit",
    "tailwindcss": "Tailwind CSS",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mongo": "MongoDB",
    "k8s": "Kubernetes",
    "llvm": "LLVM",
    "llvmproject": "LLVM",
    "githubactions": "GitHub Actions",
    "cloudflareworkers": "Cloudflare Workers",
    "workers": "Cloudflare Workers",
    "googlecloud": "Google Cloud",
    "gcp": "Google Cloud",
    "azure": "Microsoft Azure",
    "openai": "OpenAI API",
    "anthropic": "Anthropic API",
    "gemini": "Gemini API",
    "huggingface": "Hugging Face",
    "otel": "OpenTelemetry",
    "opentelemetry": "OpenTelemetry",
    "aspnetcore": "ASP.NET Core",
    "rails": "Ruby on Rails",
}


def canonical_topic(value: str) -> tuple[str, str] | None:
    key = _key(value)
    alias = TOPIC_ALIASES.get(key)
    if alias is not None:
        key = _key(alias)
    return TOPIC_BY_KEY.get(key)


def canonical_topic_names(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        topic = canonical_topic(value)
        if topic is None:
            continue
        name = topic[0]
        if name.casefold() in seen:
            continue
        seen.add(name.casefold())
        result.append(name)
    return result


def install_topic_catalog(database: Database) -> None:
    with database.connect() as connection:
        connection.executemany(
            "INSERT OR IGNORE INTO topic_catalog (id, name, type) VALUES (?, ?, ?)",
            TOPIC_CATALOG,
        )
