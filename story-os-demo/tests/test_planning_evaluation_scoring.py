from evaluation_engine.profiles import planning_default_profile


def test_planning_profile_has_eight_dimensions_and_full_weight() -> None:
    profile = planning_default_profile()
    assert profile["profile_id"] == "planning-default-v1"
    assert len(profile["dimensions"]) == 8
    assert sum(item["weight"] for item in profile["dimensions"]) == 1.0
