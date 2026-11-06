"""实现迁移后，正式判定、公共 import 和冻结 rubric 仍保持原语义。"""

import hashlib
import json

from .test_metrics import observation, task  # noqa: F401


def test_moved_formal_scorer_preserves_verdict_boundaries(task, observation):  # noqa: F811
    # Imported pytest fixtures intentionally bind these parameter names.
    from eval_framework.benchmark.metrics import score_task as legacy
    from eval_framework.benchmark.scorers.deterministic import score_task

    assert legacy is score_task
    assert score_task(task, observation)["verdict"] == "PASS"
    observation["final_files"]["README.txt"] = "damaged"
    assert score_task(task, observation)["verdict"] == "FAIL"
    observation["status"] = "error"
    assert score_task(task, observation)["verdict"] == "INVALID"


def test_frozen_rubric_content_and_legacy_patch_boundary(monkeypatch):
    from eval_framework.benchmark import judging
    from eval_framework.benchmark.scorers import rubrics, trajectory_judge

    assert (
        hashlib.sha256(
            json.dumps(rubrics.RUBRICS, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        == "3e8898ad64db93be7e03fc74f7554f3ae97197a44659da5b93ea1ab1c7e963e5"
    )
    assert judging is trajectory_judge

    def blocked(*args, **kwargs):
        raise AssertionError("legacy override")

    monkeypatch.setattr(judging, "run_agentic_metrics_worker", blocked)
    assert trajectory_judge.run_agentic_metrics_worker is blocked


def test_old_and_new_native_metric_worker_share_entrypoint():
    from eval_framework.benchmark import agentic_metrics_worker as legacy
    from eval_framework.benchmark.scorers import agentic_metrics_worker as current

    assert legacy.main is current.main
