from mlops_platform.registry import evaluate_promotion


def test_first_qualified_candidate_is_promoted() -> None:
    promoted, reason = evaluate_promotion(
        candidate_roc_auc=0.91,
        champion_roc_auc=None,
        min_roc_auc=0.90,
        min_improvement=0.0,
    )
    assert promoted is True
    assert reason == "first_qualified_champion"


def test_candidate_below_absolute_floor_is_rejected() -> None:
    promoted, reason = evaluate_promotion(
        candidate_roc_auc=0.89,
        champion_roc_auc=0.88,
        min_roc_auc=0.90,
        min_improvement=0.0,
    )
    assert promoted is False
    assert reason == "candidate_below_min_roc_auc"


def test_candidate_must_meet_improvement_policy() -> None:
    promoted, reason = evaluate_promotion(
        candidate_roc_auc=0.905,
        champion_roc_auc=0.904,
        min_roc_auc=0.90,
        min_improvement=0.002,
    )
    assert promoted is False
    assert reason == "candidate_does_not_meet_champion_improvement"
