from __future__ import annotations

from collections import Counter
from pathlib import Path

from app.evaluation.real_world_validation import load_real_world_validation

_V01 = Path(__file__).parent / "gold" / "real_world_validation" / "v01"

_PERSONAS = {
    "rust_compiler_contributor",
    "android_app_developer",
    "python_backend_developer",
    "web_frontend_engineer",
    "security_conscious_oss_maintainer",
    "ml_infrastructure_engineer",
    "student_learning_compilers",
    "self_hosting_enthusiast",
}


def test_constructed_profiles_meet_b2_slices() -> None:
    corpus = load_real_world_validation(_V01)
    assert len(corpus.profiles) == 50
    assert all(profile.constructed_profile for profile in corpus.profiles)
    cohorts = Counter(profile.cohort for profile in corpus.profiles)
    assert cohorts["cold_start"] == 25
    assert cohorts["history_rich"] == 25
    splits = Counter(profile.split for profile in corpus.profiles)
    assert splits["pilot"] == 20
    assert splits["dev"] == 15
    assert splits["blind"] == 15
    assert _PERSONAS <= {profile.persona_template for profile in corpus.profiles}
    assert {profile.language_focus for profile in corpus.profiles} == {"en", "ja", "mixed"}
    assert {profile.interest_breadth for profile in corpus.profiles} == {"broad", "narrow"}
    assert {profile.ecosystem for profile in corpus.profiles} == {"popular", "niche"}
    history = [profile for profile in corpus.profiles if profile.cohort == "history_rich"]
    assert all(profile.known_before_event_ids or profile.prior_feedback for profile in history)
    cold = [profile for profile in corpus.profiles if profile.cohort == "cold_start"]
    assert all(not profile.known_before_event_ids for profile in cold)
