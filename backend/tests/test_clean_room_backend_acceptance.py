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
    assert "timeout=8" in source
