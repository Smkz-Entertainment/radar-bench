from __future__ import annotations

import hashlib
import io
import json
import copy
import tempfile
import unittest
import zipfile
from pathlib import Path
from urllib.error import URLError
from unittest.mock import MagicMock, patch

from radar_bench import cli
from radar_bench.artifacts import (
    ArtifactBundle,
    ArtifactContractError,
    ArtifactFile,
    CATALOG_RELATIVE,
    MAX_ARCHIVE_UNCOMPRESSED_BYTES,
    MAX_FILE_BYTES,
    SUITE_RELATIVE,
    _bundle_digest,
    _download,
    _load_bundles,
    _pypi_project_version,
    _read_remote_json,
    _safe_relative,
    _source_url,
    _validate_archive,
    fetch_artifacts,
    verify_artifacts,
)

ROOT = Path(__file__).resolve().parents[1]


class _Response(io.BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class ArtifactTests(unittest.TestCase):
    def _wheel(self, root: Path, name: str = "demo-1.0-py3-none-any.whl") -> Path:
        path = root / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("demo-1.0.dist-info/METADATA", "Metadata-Version: 2.1\n")
        return path

    def _bundle(self, root: Path, *, status: str = "RECONSTRUCT_ONLY") -> ArtifactBundle:
        source = self._wheel(root)
        file_digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
        file = ArtifactFile(source.name, file_digest, source.stat().st_size)
        return ArtifactBundle(
            artifact_id="demo-wheelhouse",
            case_ids=("CASE-1",),
            incidents=("demo",),
            format="wheelhouse",
            architecture="x86_64",
            python="3.11",
            total_bytes=file.size,
            bundle_digest=_bundle_digest({file.name: (file.digest, file.size)}),
            redistribution_status=status,
            provenance=("https://pypi.org/",),
            files=(file,),
        )

    def _load_error(
        self,
        *,
        catalog_mutator=None,
        suite_mutator=None,
        manifest_mutator=None,
        all_manifests_mutator=None,
    ) -> str:
        catalog = json.loads((ROOT / CATALOG_RELATIVE).read_text(encoding="utf-8"))
        suite = json.loads((ROOT / SUITE_RELATIVE).read_text(encoding="utf-8"))
        manifests = {}
        for entry in suite["historical_cases"]:
            path = (ROOT / SUITE_RELATIVE).parent / entry["manifest"]
            manifests[path.resolve()] = json.loads(path.read_text(encoding="utf-8"))
        if catalog_mutator:
            catalog_mutator(catalog)
        if suite_mutator:
            suite_mutator(suite)
        if manifest_mutator:
            manifest_mutator(next(iter(manifests.values())))
        if all_manifests_mutator:
            all_manifests_mutator(manifests)

        catalog_path = (ROOT / CATALOG_RELATIVE).resolve()
        suite_path = (ROOT / SUITE_RELATIVE).resolve()

        def read_json(path: Path):
            resolved = path.resolve()
            if resolved == catalog_path:
                return catalog
            if resolved == suite_path:
                return suite
            return manifests[resolved]

        with patch("radar_bench.artifacts._read_json", side_effect=read_json):
            with self.assertRaises(ArtifactContractError) as raised:
                _load_bundles(ROOT, "decisive-v1")
        return str(raised.exception)

    def test_public_catalog_and_missing_root_are_fail_closed(self) -> None:
        result = verify_artifacts(ROOT, "decisive-v1")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["network_used"])
        self.assertEqual(len(result["bundles"]), 5)
        self.assertEqual(len(result["errors"]), 5)

        self.assertEqual(_safe_relative(ROOT, "../case-sealing/x.json", ROOT / "corpus/v0.7/decisive-v1").parent.name, "case-sealing")
        with self.assertRaises(ArtifactContractError):
            _safe_relative(ROOT, "../../../../outside.json", ROOT / "corpus/v0.7/decisive-v1")
        with self.assertRaises(ArtifactContractError):
            _safe_relative(ROOT, str(ROOT / "outside.json"))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            with self.assertRaises(ArtifactContractError):
                from radar_bench.artifacts import _read_json

                _read_json(path)
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ArtifactContractError):
                _read_json(path)
            path.write_text("{}", encoding="utf-8")
            with patch("radar_bench.artifacts.MAX_JSON_BYTES", 1):
                with self.assertRaisesRegex(ArtifactContractError, "exceeds size limit"):
                    _read_json(path)
        with self.assertRaisesRegex(ArtifactContractError, "unsupported artifact suite"):
            _load_bundles(ROOT, "not-a-suite")

    def test_verify_checks_digests_layout_and_archive_safety(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            artifact_root = root / "artifacts"
            bundle_root = artifact_root / bundle.artifact_id
            bundle_root.mkdir(parents=True)
            source = root / bundle.files[0].name
            (bundle_root / source.name).write_bytes(source.read_bytes())
            with patch("radar_bench.artifacts._load_bundles", return_value=({}, (bundle,))), patch(
                "radar_bench.artifacts._catalog_digest", return_value="catalog"
            ):
                ready = verify_artifacts(root, "decisive-v1", artifact_root)
            self.assertEqual(ready["status"], "READY")

            (bundle_root / "unexpected.whl").write_bytes(source.read_bytes())
            with patch("radar_bench.artifacts._load_bundles", return_value=({}, (bundle,))), patch(
                "radar_bench.artifacts._catalog_digest", return_value="catalog"
            ):
                extra = verify_artifacts(root, "decisive-v1", artifact_root)
            self.assertEqual(extra["status"], "BLOCKED")
            self.assertTrue(any("unexpected file" in error for error in extra["errors"]))

            self.assertEqual(_validate_archive(source), [])
            unsafe = root / "unsafe.whl"
            with zipfile.ZipFile(unsafe, "w") as archive:
                archive.writestr("../escape.txt", "bad")
            self.assertTrue(_validate_archive(unsafe))
            self.assertTrue(_validate_archive(root / "not-a-wheel.txt"))
            invalid = root / "invalid.whl"
            invalid.write_bytes(b"not a zip")
            self.assertTrue(any("invalid wheel" in error for error in _validate_archive(invalid)))

            archive = MagicMock()
            archive.__enter__.return_value = archive
            archive.__exit__.return_value = None
            archive.infolist.return_value = [
                MagicMock(filename="large-a", file_size=MAX_FILE_BYTES + 1),
                MagicMock(filename="large-b", file_size=MAX_ARCHIVE_UNCOMPRESSED_BYTES),
            ]
            archive.testzip.return_value = "large-a"
            with patch("radar_bench.artifacts.zipfile.ZipFile", return_value=archive):
                errors = _validate_archive(root / "synthetic.whl")
            self.assertTrue(any("member exceeds" in error for error in errors))
            self.assertIn("archive uncompressed size exceeds limit", errors)
            self.assertIn("archive CRC check failed", errors)

            nested = bundle_root / "nested"
            nested.mkdir()
            (nested / "file.whl").write_bytes(source.read_bytes())
            with patch("radar_bench.artifacts._load_bundles", return_value=({}, (bundle,))), patch(
                "radar_bench.artifacts._catalog_digest", return_value="catalog"
            ):
                unsafe_layout = verify_artifacts(root, "decisive-v1", artifact_root)
            self.assertTrue(any("unsafe bundle entry" in error for error in unsafe_layout["errors"]))

    def test_verify_rejects_size_digest_and_bundle_limit_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            artifact_root = root / "artifacts"
            bundle_root = artifact_root / bundle.artifact_id
            bundle_root.mkdir(parents=True)
            source = root / bundle.files[0].name
            destination = bundle_root / source.name
            destination.write_bytes(source.read_bytes())

            from radar_bench.artifacts import _verify_bundle

            wrong_size = ArtifactFile(source.name, bundle.files[0].digest, bundle.files[0].size + 1)
            size_result = _verify_bundle(
                ArtifactBundle(**{**bundle.__dict__, "files": (wrong_size,)}), artifact_root
            )
            self.assertTrue(any("size mismatch" in error for error in size_result["errors"]))
            wrong_digest = ArtifactFile(source.name, "sha256:" + "0" * 64, bundle.files[0].size)
            digest_result = _verify_bundle(
                ArtifactBundle(**{**bundle.__dict__, "files": (wrong_digest,)}), artifact_root
            )
            self.assertTrue(any("digest mismatch" in error for error in digest_result["errors"]))
            with patch("radar_bench.artifacts.MAX_BUNDLE_BYTES", 0):
                limited = _verify_bundle(bundle, artifact_root)
            self.assertIn("bundle exceeds total size limit", limited["errors"])
            bad_bundle_digest = ArtifactBundle(**{**bundle.__dict__, "bundle_digest": "sha256:" + "0" * 64})
            digest_bundle = _verify_bundle(bad_bundle_digest, artifact_root)
            self.assertIn("bundle digest mismatch", digest_bundle["errors"])

    def test_pypi_resolution_and_download_verify_exact_bytes(self) -> None:
        self.assertEqual(_pypi_project_version("python_dateutil-2.8.2-py2.py3-none-any.whl"), ("python-dateutil", "2.8.2"))
        filename = "demo-1.0-py3-none-any.whl"
        url = "https://files.pythonhosted.org/packages/demo.whl"
        with patch(
            "radar_bench.artifacts._read_remote_json",
            return_value={"urls": [{"filename": filename, "url": url}]},
        ):
            self.assertEqual(_source_url(filename, {}), url)
        with self.assertRaises(ArtifactContractError):
            _source_url("bad.txt", {})
        with self.assertRaises(ArtifactContractError):
            _pypi_project_version("short.whl")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._wheel(root)
            payload = source.read_bytes()
            expected = ArtifactFile(source.name, "sha256:" + hashlib.sha256(payload).hexdigest(), len(payload))
            destination = root / "downloaded.whl"
            with patch("radar_bench.artifacts.urlopen", return_value=_Response(payload)):
                _download(url, destination, expected)
            self.assertEqual(destination.read_bytes(), payload)
            with self.assertRaises(ArtifactContractError):
                _download("http://example.invalid/file.whl", root / "rejected.whl", expected)

            destination.write_bytes(payload)
            with patch.object(Path, "is_symlink", return_value=True):
                with self.assertRaises(ArtifactContractError):
                    _download(url, destination, expected)
            partial = destination.with_name(destination.name + ".part.whl")
            partial.write_bytes(payload)
            destination.unlink()
            with patch.object(Path, "is_symlink", return_value=True):
                with self.assertRaises(ArtifactContractError):
                    _download(url, destination, expected)

            oversized = _Response(payload)
            oversized.headers["Content-Length"] = str(expected.size + 1)
            with patch("radar_bench.artifacts.urlopen", return_value=oversized):
                with self.assertRaises(ArtifactContractError):
                    _download(url, destination, expected)
            streaming_oversized = _Response(payload + b"x")
            streaming_oversized.headers["Content-Length"] = "0"
            with patch("radar_bench.artifacts.urlopen", return_value=streaming_oversized):
                with self.assertRaises(ArtifactContractError):
                    _download(url, destination, expected)
            with patch("radar_bench.artifacts.urlopen", side_effect=URLError("offline")):
                with self.assertRaises(ArtifactContractError):
                    _download(url, destination, expected)
            with patch("radar_bench.artifacts.urlopen", return_value=_Response(b"wrong")):
                with self.assertRaises(ArtifactContractError):
                    _download(url, destination, expected)
            invalid_payload = b"invalid wheel bytes"
            invalid_expected = ArtifactFile(
                source.name,
                "sha256:" + hashlib.sha256(invalid_payload).hexdigest(),
                len(invalid_payload),
            )
            with patch("radar_bench.artifacts.urlopen", return_value=_Response(invalid_payload)):
                with self.assertRaises(ArtifactContractError):
                    _download(url, destination, invalid_expected)

    def test_remote_json_and_fetch_are_bounded(self) -> None:
        payload = json.dumps({"urls": []}).encode("utf-8")
        with patch("radar_bench.artifacts.urlopen", return_value=_Response(payload)):
            self.assertEqual(_read_remote_json("https://pypi.org/pypi/demo/1.0/json")["urls"], [])
        with self.assertRaises(ArtifactContractError):
            _read_remote_json("https://example.invalid/demo.json")

        too_large_header = _Response(b"{}")
        too_large_header.headers["Content-Length"] = str(4 * 1024 * 1024 + 1)
        with patch("radar_bench.artifacts.urlopen", return_value=too_large_header):
            with self.assertRaises(ArtifactContractError):
                _read_remote_json("https://pypi.org/pypi/demo/1.0/json")
        too_large_payload = _Response(b"x" * (4 * 1024 * 1024 + 1))
        too_large_payload.headers["Content-Length"] = "0"
        with patch("radar_bench.artifacts.urlopen", return_value=too_large_payload):
            with self.assertRaises(ArtifactContractError):
                _read_remote_json("https://pypi.org/pypi/demo/1.0/json")
        for bad_payload in (b"not json", b"\xff", b"[]"):
            with patch("radar_bench.artifacts.urlopen", return_value=_Response(bad_payload)):
                with self.assertRaises(ArtifactContractError):
                    _read_remote_json("https://pypi.org/pypi/demo/1.0/json")
            with patch("radar_bench.artifacts.urlopen", side_effect=URLError("offline")):
                with self.assertRaises(ArtifactContractError):
                    _read_remote_json("https://pypi.org/pypi/demo/1.0/json")

        filename = "demo-1.0-py3-none-any.whl"
        with patch("radar_bench.artifacts._read_remote_json", return_value={"urls": {}}):
            with self.assertRaises(ArtifactContractError):
                _source_url(filename, {})
        with patch("radar_bench.artifacts._read_remote_json", return_value={"urls": []}):
            with self.assertRaises(ArtifactContractError):
                _source_url(filename, {})
        with patch(
            "radar_bench.artifacts._read_remote_json",
            return_value={"urls": [{"filename": filename, "url": "https://example.invalid/file.whl"}]},
        ):
            with self.assertRaises(ArtifactContractError):
                _source_url(filename, {})

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            source = root / bundle.files[0].name

            def fake_download(_url: str, destination: Path, _expected: ArtifactFile) -> None:
                destination.write_bytes(source.read_bytes())

            with patch("radar_bench.artifacts._load_bundles", return_value=({}, (bundle,))), patch(
                "radar_bench.artifacts._catalog_digest", return_value="catalog"
            ), patch("radar_bench.artifacts._source_url", return_value="https://files.pythonhosted.org/demo.whl"), patch(
                "radar_bench.artifacts._download", side_effect=fake_download
            ) as download:
                fetched = fetch_artifacts(root, "decisive-v1", root / "external")
            self.assertEqual(fetched["status"], "READY")
            self.assertTrue(fetched["network_used"])
            self.assertTrue(download.called)
            self.assertTrue((root / "external" / "provenance.json").is_file())

            with patch("radar_bench.artifacts._load_bundles", return_value=({}, (bundle,))), patch(
                "radar_bench.artifacts._catalog_digest", return_value="catalog"
            ), patch("radar_bench.artifacts._source_url") as source_url, patch(
                "radar_bench.artifacts._download"
            ) as second_download:
                second = fetch_artifacts(root, "decisive-v1", root / "external")
            self.assertEqual(second["status"], "READY")
            source_url.assert_not_called()
            second_download.assert_not_called()

    def test_fetch_rejects_unresolved_redistribution_and_invalid_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root, status="UNCLEAR_DO_NOT_PUBLISH")
            with patch("radar_bench.artifacts._load_bundles", return_value=({}, (bundle,))), patch(
                "radar_bench.artifacts._catalog_digest", return_value="catalog"
            ):
                result = fetch_artifacts(root, "decisive-v1", root / "external")
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("redistribution status" in error for error in result["errors"]))

        with patch(
            "radar_bench.artifacts._load_bundles",
            side_effect=ArtifactContractError("bad catalog"),
        ):
            result = verify_artifacts(ROOT, "decisive-v1")
        self.assertEqual(result["status"], "INVALID")
        with patch(
            "radar_bench.artifacts._load_bundles",
            side_effect=ArtifactContractError("bad catalog"),
        ):
            result = fetch_artifacts(ROOT, "decisive-v1")
        self.assertEqual(result["status"], "INVALID")

    def test_catalog_contract_rejects_malformed_public_metadata(self) -> None:
        mutations = [
            (lambda catalog: catalog.update(schema_version="0.9"), "wrong suite identity"),
            (lambda catalog: catalog.update(bundles=[]), "five bundles"),
            (lambda catalog: catalog["bundles"].__setitem__(0, {}), "invalid bundle"),
            (
                lambda catalog: catalog["bundles"][0].update(artifact_id="../escape"),
                "invalid artifact ID",
            ),
            (
                lambda catalog: catalog["bundles"][1].__setitem__(
                    "artifact_id", catalog["bundles"][0]["artifact_id"]
                ),
                "duplicate artifact ID",
            ),
        ]
        for mutate, message in mutations:
            with self.subTest(message=message):
                self.assertIn(message, self._load_error(catalog_mutator=mutate))

        self.assertIn(
            "five historical cases",
            self._load_error(suite_mutator=lambda suite: suite.update(historical_cases=[])),
        )
        self.assertIn(
            "historical suite entry",
            self._load_error(suite_mutator=lambda suite: suite["historical_cases"].__setitem__(0, None)),
        )
        self.assertIn(
            "missing artifact bundle",
            self._load_error(manifest_mutator=lambda manifest: manifest.pop("artifact_bundle")),
        )
        self.assertIn(
            "catalog missing bundle",
            self._load_error(
                manifest_mutator=lambda manifest: manifest["artifact_bundle"].update(bundle_id="missing")
            ),
        )
        self.assertIn(
            "invalid file inventory",
            self._load_error(
                manifest_mutator=lambda manifest: manifest["artifact_bundle"].update(files=None)
            ),
        )
        self.assertIn(
            "invalid catalog file",
            self._load_error(catalog_mutator=lambda catalog: catalog["bundles"][0]["files"].__setitem__(0, None)),
        )
        self.assertIn(
            "invalid file metadata",
            self._load_error(catalog_mutator=lambda catalog: catalog["bundles"][0]["files"][0].update(size=-1)),
        )
        self.assertIn(
            "file sets differ",
            self._load_error(
                manifest_mutator=lambda manifest: manifest["artifact_bundle"]["files"].popitem()
            ),
        )
        self.assertIn(
            "digest differs",
            self._load_error(
                manifest_mutator=lambda manifest: manifest["artifact_bundle"]["files"].__setitem__(
                    next(iter(manifest["artifact_bundle"]["files"])), "sha256:" + "0" * 64
                )
            ),
        )
        self.assertIn(
            "total size differs",
            self._load_error(catalog_mutator=lambda catalog: catalog["bundles"][0].update(total_bytes=0)),
        )
        self.assertIn(
            "bundle digest differs",
            self._load_error(
                catalog_mutator=lambda catalog: catalog["bundles"][0].update(
                    bundle_digest="sha256:" + "0" * 64
                )
            ),
        )
        self.assertIn(
            "invalid bundle metadata",
            self._load_error(catalog_mutator=lambda catalog: catalog["bundles"][0].update(bundle_digest="bad")),
        )
        self.assertIn(
            "invalid redistribution status",
            self._load_error(catalog_mutator=lambda catalog: catalog["bundles"][0].update(redistribution_status="BAD")),
        )
        self.assertIn(
            "does not map case",
            self._load_error(catalog_mutator=lambda catalog: catalog["bundles"][0].update(case_ids=[])),
        )

        def duplicate_all(manifests):
            first = copy.deepcopy(next(iter(manifests.values())))
            for path in manifests:
                manifests[path] = copy.deepcopy(first)

        self.assertIn(
            "five distinct bundles",
            self._load_error(
                suite_mutator=lambda suite: [
                    entry.update(case_id=suite["historical_cases"][0]["case_id"])
                    for entry in suite["historical_cases"]
                ],
                all_manifests_mutator=duplicate_all,
            ),
        )

    def test_fetch_reports_download_failure_and_cli_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            with patch("radar_bench.artifacts._load_bundles", return_value=({}, (bundle,))), patch(
                "radar_bench.artifacts._source_url", return_value="https://files.pythonhosted.org/demo.whl"
            ), patch(
                "radar_bench.artifacts._download", side_effect=ArtifactContractError("download failed")
            ), patch(
                "radar_bench.artifacts._catalog_digest", return_value="catalog"
            ):
                result = fetch_artifacts(root, "decisive-v1", root / "external")
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("download failed", result["errors"])

        ready = {"status": "READY"}
        blocked = {"status": "BLOCKED"}
        invalid = {"status": "INVALID"}
        with patch("radar_bench.cli.fetch_artifacts", return_value=ready):
            self.assertEqual(cli.main(["artifacts", "fetch", "--suite", "decisive-v1"]), 0)
        with patch("radar_bench.cli.fetch_artifacts", return_value=blocked):
            self.assertEqual(cli.main(["artifacts", "fetch", "--suite", "decisive-v1"]), 4)
        with patch("radar_bench.cli.fetch_artifacts", return_value=invalid):
            self.assertEqual(cli.main(["artifacts", "fetch", "--suite", "decisive-v1"]), 2)
        with patch("radar_bench.cli.verify_artifacts", return_value=ready):
            self.assertEqual(cli.main(["artifacts", "verify", "--suite", "decisive-v1"]), 0)
        with patch("radar_bench.cli.verify_artifacts", return_value=blocked):
            self.assertEqual(cli.main(["artifacts", "verify", "--suite", "decisive-v1"]), 4)
        with patch("radar_bench.cli.verify_artifacts", return_value=invalid):
            self.assertEqual(cli.main(["artifacts", "verify", "--suite", "decisive-v1"]), 2)


if __name__ == "__main__":
    unittest.main()
