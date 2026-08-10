from __future__ import annotations

from pathlib import Path

import pytest

import radar_bench.artifacts as artifacts


def test_source_url_cache_is_exact_per_filename(monkeypatch: pytest.MonkeyPatch) -> None:
    first = "demo-1.2.3-cp311-cp311-manylinux_2_17_x86_64.whl"
    second = "demo-1.2.3-cp311-abi3-manylinux_2_17_x86_64.whl"
    metadata_calls: list[str] = []

    def metadata(url: str) -> dict[str, object]:
        metadata_calls.append(url)
        return {
            "urls": [
                {
                    "filename": first,
                    "url": f"https://files.pythonhosted.org/packages/a/{first}",
                },
                {
                    "filename": second,
                    "url": f"https://files.pythonhosted.org/packages/b/{second}",
                },
            ]
        }

    monkeypatch.setattr(artifacts, "_read_remote_json", metadata)
    cache: dict[str, str] = {}
    first_url = artifacts._source_url(first, cache)
    second_url = artifacts._source_url(second, cache)

    assert first_url.endswith("/" + first)
    assert second_url.endswith("/" + second)
    assert first_url != second_url
    assert set(cache) == {first, second}
    assert len(metadata_calls) == 2


def test_source_url_rejects_a_metadata_url_for_the_wrong_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filename = "demo-1.2.3-cp311-cp311-manylinux_2_17_x86_64.whl"
    monkeypatch.setattr(
        artifacts,
        "_read_remote_json",
        lambda _url: {
            "urls": [
                {
                    "filename": filename,
                    "url": "https://files.pythonhosted.org/packages/a/not-the-file.whl",
                }
            ]
        },
    )
    with pytest.raises(artifacts.ArtifactContractError):
        artifacts._source_url(filename, {})


def test_download_revalidates_final_redirect_url_and_filename(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    filename = "demo-1.2.3-cp311-cp311-manylinux_2_17_x86_64.whl"
    expected = artifacts.ArtifactFile(filename, "sha256:" + "0" * 64, 1)

    class Response:
        headers: dict[str, str] = {}

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def geturl(self) -> str:
            return "https://files.pythonhosted.org/packages/a/not-the-file.whl"

        def read(self, _size: int) -> bytes:
            return b"x"

    monkeypatch.setattr(artifacts, "urlopen", lambda *_args, **_kwargs: Response())
    destination = tmp_path / filename
    with pytest.raises(artifacts.ArtifactContractError, match="redirect"):
        artifacts._download(
            f"https://files.pythonhosted.org/packages/a/{filename}",
            destination,
            expected,
        )
    assert not destination.exists()
    assert not destination.with_name(destination.name + ".part.whl").exists()


def test_archive_validation_rejects_traversal(tmp_path: Path) -> None:
    import zipfile

    wheel = tmp_path / "unsafe.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("../escape.py", "pass")
    errors = artifacts._validate_archive(wheel)
    assert any("unsafe archive member" in error for error in errors)
