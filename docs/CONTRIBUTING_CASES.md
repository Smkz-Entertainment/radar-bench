# Contributing cases

Screen roughly twenty candidates before claiming a corpus gate. For each rejection, record one of `ARTIFACT_UNAVAILABLE`, `PLATFORM_UNAVAILABLE`, `HISTORICAL_BUILD_UNREPRODUCIBLE`, `DEPENDENCY_NOT_ARCHIVED`, `NONDETERMINISTIC`, or `REQUIRES_UNAVAILABLE_HARDWARE`, plus evidence.

Promote a case only when it can be replayed from archived local artifacts, with independent control and candidate runs, fresh reruns, network denial, and evaluator gold physically absent from the candidate environment. Do not add case-specific executor logic.
