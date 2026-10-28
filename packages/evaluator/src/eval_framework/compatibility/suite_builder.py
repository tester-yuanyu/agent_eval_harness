"""Translate deprecated CLI inputs into the declarative Suite protocol."""

from __future__ import annotations

from pathlib import Path

from ..contracts.models import (
    DatasetSource,
    LoadedSuiteDefinition,
    SuiteDefinition,
)
from ..contracts.store import canonical_json_bytes, sha256_bytes
from ..plugins.models import PluginReference
from ..schemas import DatasetFilters, RunConfig


def build_legacy_suite(
    *,
    dataset: str | Path,
    provider: str,
    capability_bundle: str | Path | None,
    filters: DatasetFilters | None,
    run_config: RunConfig,
) -> LoadedSuiteDefinition:
    source = Path(dataset).expanduser().resolve(strict=True)
    raw = source.read_bytes()
    provider_plugin_id = (
        "mini_agent_provider_v1" if provider == "mini_agent" else provider
    )
    resolved_config = run_config.model_copy(update={"filters": filters})
    sources = [DatasetSource(path=source.name, sha256=sha256_bytes(raw))]
    for manifest_path in (
        source.with_suffix(".manifest.json"),
        source.parent / "generation_manifest.json",
    ):
        if manifest_path.is_file():
            sources.append(
                DatasetSource(
                    path=manifest_path.name,
                    sha256=sha256_bytes(manifest_path.read_bytes()),
                )
            )
    definition = SuiteDefinition(
        suite_id=f"legacy_{source.stem}",
        suite_version="compatibility-v1",
        lifecycle_state="UNKNOWN",
        dataset_loader=PluginReference(
            plugin_id="legacy_jsonl_eval_case_v1",
            version="1.0.0",
        ),
        dataset_sources=sources,
        provider=PluginReference(
            plugin_id=provider_plugin_id,
            version="1.0.0",
        ),
        run_config=resolved_config,
    )
    runtime_provider_config = {"verify_current": True}
    if capability_bundle is not None:
        runtime_provider_config["bundle_override"] = str(
            Path(capability_bundle).expanduser().resolve(strict=True)
        )
    return LoadedSuiteDefinition(
        definition=definition,
        source_path=None,
        root=source.parent,
        source_sha256=sha256_bytes(
            canonical_json_bytes(definition.model_dump(mode="json"))
        ),
        origin="legacy_compatibility",
        runtime_provider_config=runtime_provider_config,
    )
