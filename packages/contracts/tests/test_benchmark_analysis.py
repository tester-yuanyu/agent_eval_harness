import pytest


@pytest.mark.parametrize("ks", [(0,), (-1,), (True,), (1.0,), (), (1, 1)])
def test_analysis_policy_rejects_invalid_k(ks):
    from eval_contracts.benchmark_analysis import AnalysisPolicy

    with pytest.raises(ValueError):
        AnalysisPolicy(ks=ks)
