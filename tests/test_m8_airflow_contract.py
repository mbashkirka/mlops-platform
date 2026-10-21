from pathlib import Path

import yaml


def test_monitoring_config_has_explicit_retraining_policy() -> None:
    config = yaml.safe_load(Path("configs/train.yaml").read_text(encoding="utf-8"))
    monitoring = config["monitoring"]

    assert monitoring["psi_retrain_threshold"] == 0.20
    assert monitoring["drifted_feature_ratio_threshold"] == 0.25
    assert monitoring["min_batch_rows"] >= 100
    assert monitoring["max_non_finite_ratio"] == 0.0


def test_monitoring_dag_branches_and_triggers_training_dag() -> None:
    source = Path("dags/mlops_monitoring_pipeline.py").read_text(encoding="utf-8")

    assert 'dag_id="mlops_monitoring_pipeline"' in source
    assert "@task.branch" in source
    assert 'return "trigger_retraining"' in source
    assert "TriggerDagRunOperator" in source
    assert 'trigger_dag_id="mlops_training_pipeline"' in source
    assert "wait_for_completion=True" in source


def test_m8_smoke_covers_stable_and_drifted_paths() -> None:
    source = Path("scripts/monitoring_smoke.sh").read_text(encoding="utf-8")

    assert "--mode stable" in source
    assert "--mode drifted" in source
    assert 'decision["action"] == "no_action"' in source
    assert 'decision["action"] == "retrain"' in source
    assert "M8 drift monitoring + retraining smoke: PASSED" in source


def test_reference_profile_is_part_of_dvc_training_lineage() -> None:
    dvc = yaml.safe_load(Path("dvc.yaml").read_text(encoding="utf-8"))
    train = dvc["stages"]["train"]

    assert "src/mlops_platform/monitoring.py" in train["deps"]
    assert "artifacts/reference_profile.json" in train["outs"]
