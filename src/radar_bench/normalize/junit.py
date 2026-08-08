"""Safe JUnit XML adapter; external entities and DTDs are not resolved."""

from __future__ import annotations

import xml.etree.ElementTree as ET  # nosec B405 - DTD/entity input rejected above

from radar_bench.normalize.base import NormalizedFailure, normalize_text


def normalize_junit(payload: str) -> NormalizedFailure:
    if "<!DOCTYPE" in payload.upper() or "<!ENTITY" in payload.upper():
        raise ValueError("DTD and external entities are not permitted")
    root = ET.fromstring(payload)  # nosec B314 - DTD/entity input rejected above
    failures, tests = [], []
    for case in root.iter("testcase"):
        name = case.attrib.get("classname", "") + "::" + case.attrib.get("name", "")
        tests.append(name)
        for child in list(case):
            if child.tag in {"failure", "error"}:
                failures.append(
                    (child.text or "") + " " + child.attrib.get("message", "")
                )
    text = "\n".join(failures) or "all tests passed"
    phase = "test" if failures else "unknown"
    return normalize_text(
        text, source_format="junit", phase=phase, test_identifiers=tests
    )
