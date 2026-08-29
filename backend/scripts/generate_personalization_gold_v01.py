from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATASET_VERSION = "personalization-v0.1"
LABEL_PROTOCOL_VERSION = "personalization-label-v1"
ROOT = Path(__file__).resolve().parents[1] / "tests" / "gold" / "personalization" / "v01"
PROVENANCE = (
    "annotator=rule-v1; protocol=personalization-label-v1; "
    "generated=2026-08-29; kind=synthetic_fixed"
)


@dataclass(frozen=True)
class UserSpec:
    suffix: str
    kind: str
    occupation: str
    interests: tuple[str, ...]
    region: str
    topics: tuple[tuple[str, str, str], ...]
    repositories: tuple[tuple[str, str], ...]
    products: tuple[str, ...]
    adjacent_products: tuple[str, ...] = ()
    watches_security: bool = False
    prior_feedback: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ItemSpec:
    suffix: str
    title: str
    summary: str
    source_family: str
    publisher: str
    url: str
    product: str
    kind: str
    redundancy_group: str
    tokens: tuple[str, ...]
    lexical_traps_for: tuple[str, ...] = ()
    adjacent_products: tuple[str, ...] = ()
    ambiguous_for: tuple[str, ...] = ()


PILOT_USERS = (
    UserSpec("01", "cold_start", "student", (), "us", (), (), ()),
    UserSpec(
        "02",
        "cold_start",
        "bootcamp graduate",
        ("ui",),
        "us",
        (("React", "technology", "high"),),
        (),
        ("react",),
    ),
    UserSpec(
        "03",
        "cold_start",
        "junior sre",
        ("ops",),
        "eu",
        (("Kubernetes", "technology", "normal"),),
        (),
        ("kubernetes",),
        ("docker", "go"),
    ),
    UserSpec(
        "04",
        "cold_start",
        "data intern",
        ("notebooks",),
        "jp",
        (("Python", "technology", "normal"),),
        (),
        ("python",),
        ("django", "fastapi"),
    ),
    UserSpec(
        "05",
        "history_rich",
        "frontend engineer",
        ("ui", "web"),
        "us",
        (
            ("React", "technology", "high"),
            ("TypeScript", "technology", "high"),
            ("Next.js", "technology", "normal"),
        ),
        (("facebook/react", "JavaScript"), ("vercel/next.js", "TypeScript")),
        ("react", "typescript", "nextjs"),
        ("vercel",),
        False,
        (("React 18 upgrade notes", "important"), ("unrelated rust blog", "not_relevant")),
    ),
    UserSpec(
        "06",
        "history_rich",
        "platform engineer",
        ("containers",),
        "de",
        (
            ("Kubernetes", "technology", "high"),
            ("Go", "technology", "high"),
            ("Docker", "technology", "normal"),
        ),
        (("kubernetes/kubernetes", "Go"),),
        ("kubernetes", "go", "docker"),
    ),
    UserSpec(
        "07",
        "history_rich",
        "backend engineer",
        ("apis",),
        "gb",
        (
            ("Python", "technology", "high"),
            ("Django", "technology", "high"),
            ("FastAPI", "technology", "normal"),
        ),
        (("django/django", "Python"), ("encode/fastapi", "Python")),
        ("python", "django", "fastapi"),
    ),
    UserSpec(
        "08",
        "history_rich",
        "systems engineer",
        ("memory-safety",),
        "us",
        (("Rust", "technology", "high"), ("WebAssembly", "technology", "normal")),
        (("rust-lang/rust", "Rust"),),
        ("rust", "wasm"),
    ),
    UserSpec(
        "09",
        "history_rich",
        "jvm engineer",
        ("enterprise",),
        "in",
        (("Java", "technology", "high"), ("Spring", "technology", "normal")),
        (("spring-projects/spring-boot", "Java"),),
        ("java", "spring"),
    ),
    UserSpec(
        "10",
        "history_rich",
        "security engineer",
        ("cve", "osv"),
        "us",
        (("security", "technology", "high"), ("CVE", "technology", "high")),
        (("github/advisory-database", ""),),
        ("security",),
        (),
        True,
        (("previous GHSA on a selected repo", "important"),),
    ),
    UserSpec(
        "11",
        "history_rich",
        "rails engineer",
        ("mvc",),
        "br",
        (("Rails", "technology", "high"), ("Ruby", "technology", "high")),
        (("rails/rails", "Ruby"),),
        ("rails", "ruby"),
    ),
    UserSpec(
        "12",
        "history_rich",
        "sre",
        ("incidents",),
        "us",
        (("GitHub Actions", "service", "high"), ("statuspage", "service", "normal")),
        (("actions/runner", "Go"),),
        ("github-actions",),
        ("github",),
        False,
        (("yesterday's Actions incident", "important"),),
    ),
)

HOLD_USERS = (
    UserSpec("01", "cold_start", "designer", (), "ca", (), (), ()),
    UserSpec(
        "02",
        "cold_start",
        "ios intern",
        ("mobile",),
        "us",
        (("Swift", "technology", "high"),),
        (),
        ("swift",),
    ),
    UserSpec(
        "03",
        "cold_start",
        "new hire",
        ("cli",),
        "ie",
        (("Go", "technology", "normal"),),
        (),
        ("go",),
        ("docker",),
    ),
    UserSpec(
        "04",
        "cold_start",
        "android intern",
        ("mobile",),
        "kr",
        (("Java", "technology", "normal"),),
        (),
        ("java",),
    ),
    UserSpec(
        "05",
        "history_rich",
        "web engineer",
        ("ssr",),
        "us",
        (
            ("React", "technology", "high"),
            ("Next.js", "technology", "high"),
        ),
        (("vercel/next.js", "TypeScript"), ("facebook/react", "JavaScript")),
        ("react", "nextjs"),
        ("vercel",),
    ),
    UserSpec(
        "06",
        "history_rich",
        "cluster engineer",
        ("scheduling",),
        "nl",
        (("Kubernetes", "technology", "high"), ("Docker", "technology", "normal")),
        (("kubernetes/kubernetes", "Go"),),
        ("kubernetes", "docker"),
        ("go",),
    ),
    UserSpec(
        "07",
        "history_rich",
        "python web engineer",
        ("orm",),
        "au",
        (("Django", "technology", "high"), ("Python", "technology", "high")),
        (("django/django", "Python"),),
        ("django", "python"),
        ("fastapi",),
    ),
    UserSpec(
        "08",
        "history_rich",
        "ios engineer",
        ("swiftui",),
        "us",
        (("Swift", "technology", "high"), ("iOS", "technology", "normal")),
        (("apple/swift", "C++"),),
        ("swift", "ios"),
    ),
    UserSpec(
        "09",
        "history_rich",
        "go engineer",
        ("services",),
        "pl",
        (("Go", "technology", "high"), ("Docker", "technology", "normal")),
        (("moby/moby", "Go"),),
        ("go", "docker"),
        ("kubernetes",),
    ),
    UserSpec(
        "10",
        "history_rich",
        "spring engineer",
        ("jvm",),
        "fr",
        (("Java", "technology", "high"), ("Spring", "technology", "high")),
        (("spring-projects/spring-framework", "Java"),),
        ("java", "spring"),
    ),
    UserSpec(
        "11",
        "history_rich",
        "ruby engineer",
        ("monoliths",),
        "jp",
        (("Rails", "technology", "high"), ("Ruby", "technology", "normal")),
        (("rails/rails", "Ruby"),),
        ("rails", "ruby"),
    ),
    UserSpec(
        "12",
        "history_rich",
        "cloud sre",
        ("reliability",),
        "us",
        (("AWS", "service", "high"), ("statuspage", "service", "high")),
        (),
        ("aws",),
        (),
        True,
    ),
)

PILOT_ITEMS = (
    ItemSpec(
        "01",
        "React 19.1.0 released",
        "facebook/react tagged v19.1.0 with compiler and Actions fixes.",
        "github_release",
        "facebook/react",
        "https://github.com/facebook/react/releases/tag/v19.1.0",
        "react",
        "release",
        "react-19-1",
        ("react", "19.1", "release"),
    ),
    ItemSpec(
        "02",
        "React 19.1 blog: what changed",
        "The React blog recaps the 19.1 compiler rollout and upgrade notes.",
        "rss_atom",
        "react.dev",
        "https://react.dev/blog/2026/03/01/react-19-1",
        "react",
        "news",
        "react-19-1",
        ("react", "19.1", "blog"),
    ),
    ItemSpec(
        "03",
        "GHSA-react-xss-2026",
        "A high-severity XSS advisory affects React server components.",
        "github_advisory",
        "GitHub Advisory Database",
        "https://github.com/advisories/GHSA-react-xss-2026",
        "react",
        "advisory",
        "react-xss-2026",
        ("react", "xss", "ghsa"),
    ),
    ItemSpec(
        "04",
        "OSV-2026-react-xss",
        "OSV mirrors the React server-component XSS as a high severity record.",
        "osv",
        "OSV",
        "https://osv.dev/vulnerability/OSV-2026-react-xss",
        "react",
        "advisory",
        "react-xss-2026",
        ("react", "xss", "osv"),
    ),
    ItemSpec(
        "05",
        "Kubernetes v1.32.0 released",
        "kubernetes/kubernetes published v1.32.0 with scheduler and DRA updates.",
        "github_release",
        "kubernetes/kubernetes",
        "https://github.com/kubernetes/kubernetes/releases/tag/v1.32.0",
        "kubernetes",
        "release",
        "k8s-1-32",
        ("kubernetes", "1.32", "release"),
        (),
        ("go", "docker"),
    ),
    ItemSpec(
        "06",
        "GHSA-k8s-privilege-2026",
        "Privilege escalation in the Kubernetes kubelet credential provider.",
        "github_advisory",
        "GitHub Advisory Database",
        "https://github.com/advisories/GHSA-k8s-privilege-2026",
        "kubernetes",
        "advisory",
        "k8s-privilege-2026",
        ("kubernetes", "privilege", "ghsa"),
    ),
    ItemSpec(
        "07",
        "Django 5.2 released",
        "django/django tagged 5.2 with async ORM improvements.",
        "github_release",
        "django/django",
        "https://github.com/django/django/releases/tag/5.2",
        "django",
        "release",
        "django-5-2",
        ("django", "5.2", "release"),
        (),
        ("python", "fastapi"),
    ),
    ItemSpec(
        "08",
        "FastAPI 0.115.12 released",
        "encode/fastapi tagged 0.115.12 with OpenAPI callback fixes.",
        "github_release",
        "encode/fastapi",
        "https://github.com/encode/fastapi/releases/tag/0.115.12",
        "fastapi",
        "release",
        "fastapi-0-115-12",
        ("fastapi", "0.115", "release"),
        (),
        ("python", "django"),
    ),
    ItemSpec(
        "09",
        "Rust 1.82.0 released",
        "rust-lang/rust tagged 1.82.0 with new lint and cargo updates.",
        "github_release",
        "rust-lang/rust",
        "https://github.com/rust-lang/rust/releases/tag/1.82.0",
        "rust",
        "release",
        "rust-1-82",
        ("rust", "1.82", "release"),
    ),
    ItemSpec(
        "10",
        "GitHub Actions: webhook delivery outage",
        "GitHub Status reports degraded Actions webhook delivery worldwide.",
        "statuspage",
        "www.githubstatus.com",
        "https://www.githubstatus.com/incidents/actions-webhooks-2026",
        "github-actions",
        "outage",
        "gh-actions-webhooks-2026",
        ("github", "actions", "outage"),
    ),
    ItemSpec(
        "11",
        "IAEA nuclear reactor inspection briefing",
        "An IAEA feed notes a scheduled reactor containment inspection in Europe.",
        "rss_atom",
        "iaea.org",
        "https://www.iaea.org/news/reactor-inspection-2026",
        "nuclear-reactor",
        "news",
        "iaea-reactor-inspection",
        ("nuclear", "reactor", "inspection"),
        ("react",),
    ),
    ItemSpec(
        "12",
        "Project Reactor 3.7.0 released",
        "reactor/reactor-core tagged 3.7.0 for the Java reactive library.",
        "github_release",
        "reactor/reactor-core",
        "https://github.com/reactor/reactor-core/releases/tag/v3.7.0",
        "project-reactor",
        "release",
        "project-reactor-3-7",
        ("reactor", "3.7", "release"),
        ("react",),
    ),
    ItemSpec(
        "13",
        "How to react during an incident",
        "An operations newsletter about staying calm and how to react under load.",
        "rss_atom",
        "incident-weekly",
        "https://incident.example/feed/how-to-react",
        "incident-advice",
        "news",
        "how-to-react-incident",
        ("react", "incident", "advice"),
        ("react",),
    ),
    ItemSpec(
        "14",
        "Treating iron rust on outdoor steel",
        "A hardware JSON feed explains rust conversion coatings for iron fences.",
        "json_feed",
        "shop-hardware",
        "https://hardware.example/feeds/rust-coating.json",
        "corrosion",
        "news",
        "iron-rust-coating",
        ("rust", "iron", "coating"),
        ("rust",),
    ),
    ItemSpec(
        "15",
        "Pokémon GO map outage",
        "Niantic Status: Pokémon GO live map tiles are failing in several regions.",
        "statuspage",
        "status.nianticlabs.com",
        "https://status.nianticlabs.com/incidents/pokemon-go-map",
        "pokemon-go",
        "outage",
        "pokemon-go-map",
        ("pokemon", "go", "outage"),
        ("go",),
    ),
    ItemSpec(
        "16",
        "Python Weekly issue 712",
        "This week's Python newsletter covers typing, packaging, and CPython news.",
        "json_feed",
        "pythonweekly.com",
        "https://www.pythonweekly.com/archive/712.json",
        "python",
        "news",
        "python-weekly-712",
        ("python", "weekly", "typing"),
        (),
        ("django", "fastapi"),
    ),
)

HOLD_ITEMS = (
    ItemSpec(
        "01",
        "Next.js 15.3.0 released",
        "vercel/next.js tagged 15.3.0 with Turbopack stability work.",
        "github_release",
        "vercel/next.js",
        "https://github.com/vercel/next.js/releases/tag/v15.3.0",
        "nextjs",
        "release",
        "next-15-3",
        ("next.js", "15.3", "release"),
        (),
        ("react", "vercel"),
    ),
    ItemSpec(
        "02",
        "Next.js 15.3 upgrade notes",
        "The Next.js JSON feed republishes the 15.3 upgrade checklist.",
        "json_feed",
        "nextjs.org",
        "https://nextjs.org/feed/15-3.json",
        "nextjs",
        "news",
        "next-15-3",
        ("next.js", "15.3", "upgrade"),
        (),
        ("react",),
    ),
    ItemSpec(
        "03",
        "OSV-2026-k8s-cve",
        "OSV lists a Kubernetes API server authorization bypass.",
        "osv",
        "OSV",
        "https://osv.dev/vulnerability/OSV-2026-k8s-cve",
        "kubernetes",
        "advisory",
        "k8s-authz-2026",
        ("kubernetes", "cve", "osv"),
    ),
    ItemSpec(
        "04",
        "GHSA-django-sqli-2026",
        "SQL injection in Django's JSONField lookup on selected versions.",
        "github_advisory",
        "GitHub Advisory Database",
        "https://github.com/advisories/GHSA-django-sqli-2026",
        "django",
        "advisory",
        "django-sqli-2026",
        ("django", "sql", "ghsa"),
        (),
        ("python",),
    ),
    ItemSpec(
        "05",
        "Spring Boot 3.4.3 released",
        "spring-projects/spring-boot tagged 3.4.3 with actuator fixes.",
        "github_release",
        "spring-projects/spring-boot",
        "https://github.com/spring-projects/spring-boot/releases/tag/v3.4.3",
        "spring",
        "release",
        "spring-boot-3-4-3",
        ("spring", "boot", "release"),
        (),
        ("java",),
    ),
    ItemSpec(
        "06",
        "Rails 8.0.2 released",
        "rails/rails tagged 8.0.2 with security and Active Job fixes.",
        "github_release",
        "rails/rails",
        "https://github.com/rails/rails/releases/tag/v8.0.2",
        "rails",
        "release",
        "rails-8-0-2",
        ("rails", "8.0", "release"),
        (),
        ("ruby",),
    ),
    ItemSpec(
        "07",
        "Swift 6.1 released",
        "apple/swift tagged 6.1 with typed throws refinements.",
        "github_release",
        "apple/swift",
        "https://github.com/apple/swift/releases/tag/swift-6.1",
        "swift",
        "release",
        "swift-6-1",
        ("swift", "6.1", "release"),
    ),
    ItemSpec(
        "08",
        "Vercel Edge network degraded",
        "Vercel Status: edge function invocations are failing in iad1.",
        "statuspage",
        "www.vercel-status.com",
        "https://www.vercel-status.com/incidents/edge-iad1",
        "vercel",
        "outage",
        "vercel-edge-iad1",
        ("vercel", "edge", "outage"),
        (),
        ("nextjs", "react"),
    ),
    ItemSpec(
        "09",
        "ReactOS 0.4.15 released",
        "ReactOS, the Windows-compatible OS, tagged 0.4.15 with USB fixes.",
        "github_release",
        "reactos/reactos",
        "https://github.com/reactos/reactos/releases/tag/0.4.15",
        "reactos",
        "release",
        "reactos-0-4-15",
        ("reactos", "0.4.15", "release"),
        ("react",),
    ),
    ItemSpec(
        "10",
        "Java island earthquake status",
        "A geology RSS feed reports aftershocks on the island of Java.",
        "rss_atom",
        "earthquake-watch",
        "https://earthquake.example/java-aftershocks",
        "java-island",
        "news",
        "java-island-quake",
        ("java", "island", "earthquake"),
        ("java",),
    ),
    ItemSpec(
        "11",
        "SWIFT interbank outage advisory",
        "A payments advisory describes a SWIFT network settlement delay.",
        "github_advisory",
        "payments-advisories",
        "https://advisories.example/swift-settlement",
        "swift-network",
        "advisory",
        "swift-settlement",
        ("swift", "interbank", "settlement"),
        ("swift",),
    ),
    ItemSpec(
        "12",
        "Railway rails replacement program",
        "A transit JSON feed covers steel railway rails being replaced downtown.",
        "json_feed",
        "city-transit",
        "https://transit.example/feeds/railway-rails.json",
        "railway",
        "news",
        "railway-rails-replacement",
        ("railway", "rails", "replacement"),
        ("rails",),
    ),
    ItemSpec(
        "13",
        "Go 1.24.1 released",
        "golang/go tagged 1.24.1 with runtime and crypto fixes.",
        "github_release",
        "golang/go",
        "https://github.com/golang/go/releases/tag/go1.24.1",
        "go",
        "release",
        "go-1-24-1",
        ("go", "1.24", "release"),
        (),
        ("docker", "kubernetes"),
    ),
    ItemSpec(
        "14",
        "AWS US-EAST-1 API errors",
        "AWS Health: elevated 5xx from EC2 and S3 APIs in us-east-1.",
        "statuspage",
        "health.aws.amazon.com",
        "https://health.aws.amazon.com/incidents/use1-api-2026",
        "aws",
        "outage",
        "aws-use1-2026",
        ("aws", "us-east-1", "outage"),
    ),
    ItemSpec(
        "15",
        "OSV-2026-spring-actuator",
        "OSV records an unauthenticated Spring Boot actuator exposure.",
        "osv",
        "OSV",
        "https://osv.dev/vulnerability/OSV-2026-spring-actuator",
        "spring",
        "advisory",
        "spring-actuator-2026",
        ("spring", "actuator", "osv"),
        (),
        ("java",),
    ),
    ItemSpec(
        "16",
        "Kubernetes changelog digest",
        "A weekly RSS digest of kubernetes/kubernetes merged changelog entries.",
        "rss_atom",
        "k8s-changelog",
        "https://k8s.example/rss/changelog",
        "kubernetes",
        "news",
        "k8s-changelog-weekly",
        ("kubernetes", "changelog", "digest"),
        (),
        ("go", "docker"),
        ("go",),
    ),
)


def _user_id(split: str, suffix: str) -> str:
    prefix = "pgold-p-u" if split == "pilot" else "pgold-h-u"
    return f"{prefix}-{suffix}"


def _item_id(split: str, suffix: str) -> str:
    prefix = "pgold-p-i" if split == "pilot" else "pgold-h-i"
    return f"{prefix}-{suffix}"


def _judgment_id(split: str, index: int) -> str:
    prefix = "pgold-p-j" if split == "pilot" else "pgold-h-j"
    return f"{prefix}-{index:04d}"


def _user_payload(split: str, spec: UserSpec) -> dict[str, object]:
    return {
        "user_id": _user_id(split, spec.suffix),
        "split": split,
        "kind": spec.kind,
        "profile": {
            "occupation": spec.occupation,
            "interests": list(spec.interests),
            "region": spec.region,
        },
        "topics": [
            {"name": name, "type": topic_type, "priority": priority}
            for name, topic_type, priority in spec.topics
        ],
        "repositories": [
            {"full_name": full_name, "language": language} for full_name, language in spec.repositories
        ],
        "prior_feedback": [
            {"summary": summary, "feedback": feedback} for summary, feedback in spec.prior_feedback
        ],
        "products": list(spec.products),
        "adjacent_products": list(spec.adjacent_products),
        "watches_security": spec.watches_security,
    }


def _item_payload(split: str, spec: ItemSpec) -> dict[str, object]:
    return {
        "item_id": _item_id(split, spec.suffix),
        "split": split,
        "title": spec.title,
        "summary": spec.summary,
        "source_family": spec.source_family,
        "publisher": spec.publisher,
        "url": spec.url,
        "product": spec.product,
        "kind": spec.kind,
        "redundancy_group": spec.redundancy_group,
        "tokens": list(spec.tokens),
        "lexical_traps_for": list(spec.lexical_traps_for),
        "adjacent_products": list(spec.adjacent_products),
        "ambiguous_for": list(spec.ambiguous_for),
    }


def _label(user: UserSpec, item: ItemSpec) -> tuple[int, int, bool, bool, bool, str]:
    user_products = set(user.products)
    trapped = bool(user_products & set(item.lexical_traps_for))
    ambiguous = bool(user_products & set(item.ambiguous_for))
    exact = item.product in user_products
    security_hit = user.watches_security and item.kind == "advisory"
    adjacent = bool(
        item.product in set(user.adjacent_products)
        or user_products & set(item.adjacent_products)
    )

    if trapped and not exact:
        return (
            0,
            0,
            False,
            True,
            False,
            f"Lexical overlap with {sorted(user_products & set(item.lexical_traps_for))} "
            f"but the item is about {item.product}, not the user's product.",
        )
    if ambiguous and not exact and not security_hit:
        return (
            1,
            0,
            False,
            False,
            True,
            f"Possible {item.product} connection for {user.occupation}, but the product sense is unresolved.",
        )
    if exact or security_hit:
        if item.kind in {"advisory", "outage"}:
            relevance, importance = 3, 3
        elif item.kind == "release":
            relevance, importance = 3, 2
        else:
            relevance, importance = 2, 2
        why = "security watch matches an advisory" if security_hit and not exact else f"item product {item.product} matches the user profile"
        return relevance, importance, True, False, False, why
    if adjacent:
        return (
            2,
            1,
            True,
            False,
            False,
            f"Adjacent product {item.product} is related to the user's topics.",
        )
    if user.kind == "cold_start" and not user.products:
        return 0, 0, False, False, False, "Cold-start user has no topics, repositories, or feedback."
    return 0, 0, False, False, False, f"No topical or repository overlap with {item.product}."


def _build_split(split: str, users: tuple[UserSpec, ...], items: tuple[ItemSpec, ...]) -> tuple[list, list, list]:
    user_rows = [_user_payload(split, spec) for spec in users]
    item_rows = [_item_payload(split, spec) for spec in items]
    judgments: list[dict[str, object]] = []
    index = 1
    for user in users:
        for item in items:
            relevance, importance, should_surface, hard_negative, ambiguous, rationale = _label(user, item)
            judgments.append(
                {
                    "judgment_id": _judgment_id(split, index),
                    "user_id": _user_id(split, user.suffix),
                    "item_id": _item_id(split, item.suffix),
                    "relevance": relevance,
                    "importance_to_user": importance,
                    "should_surface": should_surface,
                    "redundancy_group": item.redundancy_group,
                    "rationale": rationale,
                    "provenance": PROVENANCE,
                    "ambiguous": ambiguous,
                    "hard_negative": hard_negative,
                    "label_protocol_version": LABEL_PROTOCOL_VERSION,
                    "dataset_version": DATASET_VERSION,
                    "split": split,
                }
            )
            index += 1
    return user_rows, item_rows, judgments


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    pilot_users, pilot_items, pilot_judgments = _build_split("pilot", PILOT_USERS, PILOT_ITEMS)
    hold_users, hold_items, hold_judgments = _build_split("blind", HOLD_USERS, HOLD_ITEMS)
    users = [*pilot_users, *hold_users]
    items = [*pilot_items, *hold_items]
    judgments = [*pilot_judgments, *hold_judgments]

    _write(ROOT / "users.json", users)
    _write(ROOT / "items.json", items)
    _write(ROOT / "judgments.json", judgments)
    _write(ROOT / "pilot" / "users.json", pilot_users)
    _write(ROOT / "pilot" / "judgments.json", pilot_judgments)
    _write(
        ROOT / "pilot" / "index.json",
        {
            "split": "pilot",
            "dataset_version": DATASET_VERSION,
            "bundle_ids": ["pgold-pilot-v01"],
            "user_ids": [row["user_id"] for row in pilot_users],
            "item_ids": [row["item_id"] for row in pilot_items],
            "judgment_ids": [row["judgment_id"] for row in pilot_judgments],
        },
    )
    _write(ROOT / "blind" / "users.json", hold_users)
    _write(ROOT / "blind" / "judgments.json", hold_judgments)
    _write(
        ROOT / "blind" / "index.json",
        {
            "split": "blind",
            "dataset_version": DATASET_VERSION,
            "bundle_ids": ["pgold-holdout-v01"],
            "user_ids": [row["user_id"] for row in hold_users],
            "item_ids": [row["item_id"] for row in hold_items],
            "judgment_ids": [row["judgment_id"] for row in hold_judgments],
        },
    )
    families = sorted({row["source_family"] for row in items})
    _write(
        ROOT / "gold_manifest_v01.json",
        {
            "dataset_id": "bulletfeed-personalization-gold-v0.1",
            "dataset_version": DATASET_VERSION,
            "label_protocol_version": LABEL_PROTOCOL_VERSION,
            "minimum_users": 20,
            "minimum_judgments": 300,
            "minimum_source_families": 4,
            "source_families": families,
            "files": {
                "users": "users.json",
                "items": "items.json",
                "judgments": "judgments.json",
                "label_schema": "label_schema.json",
                "pilot_index": "pilot/index.json",
                "holdout_index": "blind/index.json",
            },
            "splits": {
                "pilot": {
                    "users": len(pilot_users),
                    "items": len(pilot_items),
                    "judgments": len(pilot_judgments),
                },
                "blind": {
                    "users": len(hold_users),
                    "items": len(hold_items),
                    "judgments": len(hold_judgments),
                },
            },
        },
    )
    print(
        f"wrote {len(users)} users, {len(items)} items, {len(judgments)} judgments "
        f"({len(pilot_judgments)} pilot / {len(hold_judgments)} holdout)"
    )


if __name__ == "__main__":
    main()
