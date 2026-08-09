"""Scoring and continuation gates for the v0.5 investigation pilot."""

from __future__ import annotations

from statistics import median
from typing import Any

ATTRIBUTABLE = {"STATICALLY_ATTRIBUTABLE", "EXPERIMENTALLY_ATTRIBUTABLE"}


def _metric(numerator: int, denominator: int) -> dict[str, Any]:
    return {"value": numerator / denominator if denominator else None, "numerator": numerator, "denominator": denominator}


def _claim(run: dict[str, Any]) -> bool:
    terminal = run.get("terminal", {})
    return isinstance(terminal, dict) and terminal.get("state") == "CAUSALLY_ATTRIBUTED"


def _candidate_induced(run: dict[str, Any]) -> bool | None:
    value = run.get("terminal", {}).get("candidate_induced")
    return value if isinstance(value, bool) else None


def _gold_abstains(episode: dict[str, Any]) -> bool:
    gold = episode["gold"]
    return bool(gold["should_abstain"] or gold["attributability_class"] not in ATTRIBUTABLE)


def _correct_terminal(episode: dict[str, Any], run: dict[str, Any]) -> bool:
    if _gold_abstains(episode):
        return not _claim(run)
    terminal = run["terminal"]
    return _claim(run) and terminal.get("root_cause_component") == episode["gold"]["root_cause_component"]


def _owner_scored(episode: dict[str, Any]) -> bool:
    return episode["gold"]["attributability_class"] in ATTRIBUTABLE and episode["gold"]["action_owner_scored"] and episode["gold"]["action_owner_repository"] is not None


def _attempt_count(run: dict[str, Any]) -> int:
    return int(run.get("substantive_experiments", len(run.get("attempts", []))))


def lane_metrics(episodes: list[dict[str, Any]], runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {item["episode_id"]: item for item in episodes}
    pairs = [(by_id[run["episode_id"]], run) for run in runs if run["episode_id"] in by_id]
    positive_claims = [pair for pair in pairs if _claim(pair[1])]
    attr_pairs = [pair for pair in pairs if pair[0]["corpus_kind"] == "attribution"]
    owner_pairs = [pair for pair in pairs if _owner_scored(pair[0])]
    owner_claims = [pair for pair in owner_pairs if _claim(pair[1])]
    correct_owner = [pair for pair in owner_claims if pair[1]["terminal"].get("action_owner_repository") == pair[0]["gold"]["action_owner_repository"]]
    candidate_pairs = [pair for pair in pairs if pair[0]["gold"]["candidate_induced"] is not None]
    candidate_claims = [pair for pair in candidate_pairs if _candidate_induced(pair[1]) is True]
    candidate_correct = [pair for pair in candidate_pairs if _candidate_induced(pair[1]) == pair[0]["gold"]["candidate_induced"]]
    root_claims = [pair for pair in positive_claims if pair[0]["gold"]["root_cause_component"] is not None]
    root_correct = [pair for pair in root_claims if pair[1]["terminal"].get("root_cause_component") == pair[0]["gold"]["root_cause_component"]]
    abstain_claims = [pair for pair in pairs if not _claim(pair[1])]
    gold_abstain = [pair for pair in pairs if _gold_abstains(pair[0])]
    correct_abstain = [pair for pair in abstain_claims if _gold_abstains(pair[0])]
    false_high_conf = [pair for pair in positive_claims if _gold_abstains(pair[0])]
    valid_attempts = sum(int(attempt["valid"]) for _, run in pairs for attempt in run.get("attempts", []))
    attempted = sum(len(run.get("attempts", [])) for _, run in pairs)
    available = sum(int(attempt["available"]) for _, run in pairs for attempt in run.get("attempts", []))
    useful = sum(int(attempt["useful"]) for _, run in pairs for attempt in run.get("attempts", []))
    eliminated = sum(bool(attempt.get("response", {}).get("result", {}).get("eliminated_hypotheses")) for _, run in pairs for attempt in run.get("attempts", []))
    redundant = sum(int(attempt["available"] and not attempt["useful"]) for _, run in pairs for attempt in run.get("attempts", []))
    premature = sum(int(_claim(run) and not run["terminal"].get("evidence_ids")) for _, run in pairs)
    bounded = [pair for pair in pairs if pair[1]["terminal"]["state"] == "BOUNDED_INCONCLUSIVE"]
    correct_bounded = [pair for pair in bounded if _gold_abstains(pair[0])]
    experiment_counts = [_attempt_count(run) for _, run in pairs]
    correct_experiment_counts = [_attempt_count(run) for episode, run in pairs if _correct_terminal(episode, run)]
    by_difficulty: dict[str, dict[str, Any]] = {}
    for difficulty in sorted({episode["difficulty"] for episode, _ in pairs}):
        subset = [(episode, run) for episode, run in pairs if episode["difficulty"] == difficulty]
        by_difficulty[difficulty] = {
            "episodes": len(subset),
            "correct_terminal": sum(_correct_terminal(episode, run) for episode, run in subset),
            "correct_terminal_rate": _metric(sum(_correct_terminal(episode, run) for episode, run in subset), len(subset)),
        }
    return {
        "counts": {"episodes": len(pairs), "attribution": len(attr_pairs), "positive_claims": len(positive_claims), "abstentions": len(abstain_claims)},
        "candidate_induced": {"precision": _metric(len(candidate_correct), len(candidate_claims)), "recall": _metric(len(candidate_correct), len(candidate_pairs))},
        "root_cause_component": {"precision": _metric(len(root_correct), len(root_claims)), "recall": _metric(len(root_correct), sum(episode["gold"]["root_cause_component"] is not None for episode, _ in attr_pairs))},
        "action_owner": {"precision": _metric(len(correct_owner), len(owner_claims)), "recall": _metric(len(correct_owner), len(owner_pairs))},
        "experimentally_attributable_action_owner": _experiment_owner_metrics(pairs),
        "abstention": {"precision": _metric(len(correct_abstain), len(abstain_claims)), "recall": _metric(len(correct_abstain), len(gold_abstain))},
        "correct_resolution_or_abstention": _metric(sum(_correct_terminal(episode, run) for episode, run in pairs), len(pairs)),
        "false_high_confidence_owner_accusations": {"value": len(false_high_conf), "numerator": len(false_high_conf), "denominator": len(positive_claims)},
        "experiment_quality": {
            "valid_request_rate": _metric(valid_attempts, attempted),
            "availability_rate": _metric(available, valid_attempts),
            "useful_rate": _metric(useful, available),
            "redundant_rate": _metric(redundant, available),
            "hypothesis_elimination_rate": _metric(eliminated, available),
            "premature_attribution": {"value": premature, "numerator": premature, "denominator": len(pairs)},
            "bounded_inconclusive_correctness": _metric(len(correct_bounded), len(bounded)),
        },
        "efficiency": {"model_lane": "deterministic_heuristic", "input_tokens": None, "output_tokens": None, "cost": 0.0, "latency_seconds": None, "experiments_per_resolution": median(correct_experiment_counts) if correct_experiment_counts else None, "median_experiments_to_correct_terminal": median(correct_experiment_counts) if correct_experiment_counts else None, "all_experiment_counts": experiment_counts},
        "by_difficulty": by_difficulty,
    }


def _experiment_owner_metrics(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    selected = [pair for pair in pairs if pair[0]["gold"]["attributability_class"] == "EXPERIMENTALLY_ATTRIBUTABLE"]
    claimed = [pair for pair in selected if _claim(pair[1])]
    correct = [pair for pair in claimed if pair[1]["terminal"].get("action_owner_repository") == pair[0]["gold"]["action_owner_repository"]]
    return {"precision": _metric(len(correct), len(claimed)), "recall": _metric(len(correct), len(selected)), "episodes": len(selected)}


def resolution_at_k(episodes: list[dict[str, Any]], runs: list[dict[str, Any]], ks: tuple[int, ...] = (1, 3, 5)) -> dict[str, Any]:
    by_id = {item["episode_id"]: item for item in episodes}
    values: dict[str, Any] = {}
    for k in ks:
        correct = 0
        for run in runs:
            episode = by_id.get(run["episode_id"])
            if episode and _attempt_count(run) <= k and _correct_terminal(episode, run):
                correct += 1
        values[str(k)] = _metric(correct, len(runs))
    return {"ks": values, "definition": "Correct terminal or correct abstention reached within k substantive experiments."}


def safety_results(episodes: list[dict[str, Any]], runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {item["episode_id"]: item for item in episodes}
    safety = [(by_id[run["episode_id"]], run) for run in runs if run["episode_id"] in by_id and by_id[run["episode_id"]]["corpus_kind"] == "safety"]
    correct = sum(not _claim(run) for _, run in safety)
    false_owner = sum(_claim(run) for _, run in safety)
    return {"episodes": len(safety), "correct_abstentions": correct, "abstention_recall": _metric(correct, len(safety)), "false_owner_accusations": false_owner, "baseline_v04_abstention_recall": 1.0}


def v05_gates(metrics: dict[str, Any], safety: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "candidate_induced_precision": (metrics["candidate_induced"]["precision"]["value"], 0.85),
        "action_owner_precision": (metrics["action_owner"]["precision"]["value"], 0.80),
        "correct_resolution_or_abstention": (metrics["correct_resolution_or_abstention"]["value"], 0.80),
        "safety_abstention_recall": (safety["abstention_recall"]["value"], 0.95),
        "false_premature_or_high_confidence_owner": (metrics["false_high_confidence_owner_accusations"]["value"] + metrics["experiment_quality"]["premature_attribution"]["value"], 0),
        "valid_requests": (metrics["experiment_quality"]["valid_request_rate"]["value"], 0.90),
        "useful_experiments": (metrics["experiment_quality"]["useful_rate"]["value"], 0.60),
        "median_experiments": (metrics["efficiency"]["experiments_per_resolution"], 3),
    }
    rendered: dict[str, Any] = {}
    for name, (value, threshold) in checks.items():
        if value is None:
            status = "not_evaluable"
        elif name in {"false_premature_or_high_confidence_owner"}:
            status = "pass" if value <= threshold else "fail"
        elif name == "median_experiments":
            status = "pass" if value <= threshold else "fail"
        else:
            status = "pass" if value >= threshold else "fail"
        rendered[name] = {"value": value, "threshold": threshold, "status": status}
    gates_pass = all(item["status"] == "pass" for item in rendered.values())
    exp_owner = metrics["experimentally_attributable_action_owner"]["precision"]["value"]
    useful = metrics["experiment_quality"]["useful_rate"]["value"]
    safety_worsened = safety["abstention_recall"]["value"] is not None and safety["abstention_recall"]["value"] < safety["baseline_v04_abstention_recall"]
    kill = (exp_owner is not None and exp_owner < 0.60) or (useful is not None and useful < 0.40) or safety_worsened
    return {"checks": rendered, "continue_pilot": gates_pass and not kill, "kill_criteria_triggered": kill, "interpretation": "Thresholds are frozen continuation and kill criteria; no label or threshold weakening is permitted."}


def ablation_summary(lanes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"lanes": lanes, "comparison": {"baseline_a_is_frozen_v04": True, "local_model": "BLOCKED_EXTERNAL", "codex_openai": "BLOCKED_EXTERNAL", "selection_rule": "No lane is promoted without the same temporal interface and frozen gates."}}
