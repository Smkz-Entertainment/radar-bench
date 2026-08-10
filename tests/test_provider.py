from __future__ import annotations

import pytest

import radar_bench.providers.subprocess_provider as provider_module
from radar_bench.execution.process import BoundedCapture
from radar_bench.providers.subprocess_provider import SubprocessProvider


def test_subprocess_provider_rejects_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        provider_module,
        "run_bounded",
        lambda *_args, **_kwargs: BoundedCapture(
            returncode=0,
            output_bytes=2,
            output_digest="sha256:" + "0" * 64,
            output_limit_exceeded=False,
            timed_out=False,
            excerpt="{}",
            payload=b"{}",
            cleanup_error="PROCESS_CLEANUP_TIMEOUT",
        ),
    )

    with pytest.raises(RuntimeError, match="cleanup failed"):
        SubprocessProvider(["provider"]).predict({"request": "value"})
