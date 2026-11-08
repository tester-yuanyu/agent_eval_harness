from eval_framework.benchmark.runner import code_identity


def test_shared_value_rules_change_both_runtime_and_provider_scoring_identity(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from eval_contracts import observation_assertions
    from eval_framework.benchmark.mini_scoring import MiniAgentDomain

    dependency = tmp_path / "observation_assertions.py"
    dependency.write_text("first value encoding")
    monkeypatch.setattr(observation_assertions, "__file__", str(dependency))
    domain = MiniAgentDomain.__new__(MiniAgentDomain)
    domain.capabilities = SimpleNamespace(bundle=SimpleNamespace(
        capability_bundle_sha256="unchanged-reference"
    ))
    runtime_before = code_identity(["oracle.py"])
    scoring_before = domain.identity()
    dependency.write_text("changed value encoding")
    assert code_identity(["oracle.py"]) != runtime_before
    assert domain.identity() != scoring_before
    assert domain.identity()["reference_bundle"] == "unchanged-reference"


def test_current_identity_binds_extracted_source_dependencies(tmp_path, monkeypatch):
    from eval_framework.benchmark import layer_sources

    dependency = tmp_path / "tracer.py"
    dependency.write_text("first implementation")
    monkeypatch.setattr(
        layer_sources, "layer_source_paths",
        lambda: {"eval_framework/harness/tracer.py": dependency},
    )
    first = code_identity(["oracle.py"])
    dependency.write_text("changed implementation")
    assert code_identity(["oracle.py"]) != first


def test_source_closure_covers_shared_contract_and_extracted_modules():
    from eval_framework.benchmark.layer_sources import layer_source_paths

    sources = layer_source_paths()
    assert {
        "eval_contracts/benchmark.py",
        "eval_framework/harness/tracer.py",
        "eval_framework/environments/inspect_file_tools.py",
        "eval_framework/benchmark/scorers/executable.py",
        "eval_framework/aggregator/summaries.py",
        "eval_framework/orchestration/config.py",
    } <= sources.keys()
    assert all(path.is_file() for path in sources.values())
