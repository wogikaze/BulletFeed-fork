import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from scripts.run_clean_room_backend_acceptance import _verify_representative_upgrade  # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def test_representative_upgrade_preserves_state_and_reaches_current_head(tmp_path: Path) -> None:
    assert _verify_representative_upgrade(tmp_path / "upgrade.db") is True


def test_clean_room_harness_does_not_live_crawl_during_seed() -> None:
    source = (SCRIPTS_DIR / "run_clean_room_backend_acceptance.py").read_text(encoding="utf-8")
    assert 'BULLETFEED_EMBED_SOURCE_SYNC_WORKER": "0"' in source
    assert 'BULLETFEED_REQUEST_TIMEOUT_SECONDS": "1"' in source
    feed_idx = source.index("/v1/feed?limit=5")
    assert "timeout=8" in source[feed_idx : feed_idx + 180]
    evidence_idx = source.index("/v1/events/")
    assert "timeout=8" in source[evidence_idx : evidence_idx + 220]
    read_idx = source.index("/v1/feed/items/{first.get('id')}/read")
    assert "timeout=8" in source[read_idx : read_idx + 180]
    unread_idx = source.index("/v1/feed?status=unread&limit=5")
    assert "timeout=8" in source[unread_idx : unread_idx + 180]


def test_clean_room_trace_keeps_acquisition_and_projection_separate() -> None:
    source = (SCRIPTS_DIR / "run_clean_room_backend_acceptance.py").read_text(encoding="utf-8")
    seed_idx = source.index('"/__acceptance__/seed-statuspage"')
    seed_block = source[seed_idx : seed_idx + 1_000]
    assert '"acquisition",' in seed_block
    assert '"projection",' in seed_block
    assert '"acquisition_projection"' not in seed_block
