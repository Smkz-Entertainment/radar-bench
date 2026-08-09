"""Benchmark-integrity audits for the frozen v0.5 investigator."""

from radar_bench.integrity.v06 import (
    DECOY_EXPERIMENTS,
    REQUIRED_V06_ARTIFACTS,
    action_space_audit,
    anti_oracle_baselines,
    counterfactual_audit,
    decoy_audit,
    grouped_holdout_audit,
    investigator_freeze_audit,
    metadata_channel_audit,
    real_execution_audit,
    replay_concordance_audit,
    v06_gates,
)

__all__ = [
    "DECOY_EXPERIMENTS",
    "REQUIRED_V06_ARTIFACTS",
    "action_space_audit",
    "anti_oracle_baselines",
    "counterfactual_audit",
    "decoy_audit",
    "grouped_holdout_audit",
    "investigator_freeze_audit",
    "metadata_channel_audit",
    "real_execution_audit",
    "replay_concordance_audit",
    "v06_gates",
]
