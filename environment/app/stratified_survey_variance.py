#!/usr/bin/env python3
"""Legacy pooled survey mean calculator."""

import json
import math
import sys
from pathlib import Path


def main(argv):
    if len(argv) != 3:
        return 1
    source, target = Path(argv[1]), Path(argv[2])
    payload = json.loads(source.read_text(encoding="utf-8"))
    values = [value for stratum in payload["strata"] for value in stratum["responses"]]
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    half = 1.96 * math.sqrt(variance / len(values))
    result = {
        "survey_id": payload["survey_id"],
        "status": "complete",
        "estimate": mean,
        "standard_error": math.sqrt(variance / len(values)),
        "ci_low": mean - half,
        "ci_high": mean + half,
        "strata": [],
    }
    target.write_text(json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
