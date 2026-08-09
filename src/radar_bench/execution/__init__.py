"""Executable v0.7 investigation benchmark contracts and runner boundary."""

from radar_bench.execution.v07 import (
    COMMON_CAPABILITIES,
    FROZEN_V05_COMMIT,
    REQUIRED_V07_ARTIFACTS,
    HermeticExecutor,
    adapt_frozen_request,
    evaluate_pilot,
    freeze_audit,
    preparation_audit,
    validate_manifest,
    validate_request,
    v07_gates,
)
from radar_bench.execution.docker_runtime import DockerRuntime, inspect_docker_runtime
from radar_bench.execution.canonical import (
    CANONICAL_PROTOCOL_VERSION,
    CanonicalHarness,
    validate_candidate_view,
)

__all__ = [
    "COMMON_CAPABILITIES",
    "FROZEN_V05_COMMIT",
    "REQUIRED_V07_ARTIFACTS",
    "HermeticExecutor",
    "adapt_frozen_request",
    "evaluate_pilot",
    "freeze_audit",
    "preparation_audit",
    "validate_manifest",
    "validate_request",
    "v07_gates",
    "DockerRuntime",
    "inspect_docker_runtime",
    "CANONICAL_PROTOCOL_VERSION",
    "CanonicalHarness",
    "validate_candidate_view",
]
