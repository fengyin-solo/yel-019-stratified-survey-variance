#!/usr/bin/env python3
"""Finite-population corrected stratified mean estimator."""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import sys
import tempfile
from pathlib import Path


TOP_KEYS = {"survey_id", "confidence_level", "strata"}
STRATUM_KEYS = {"stratum_id", "population", "responses"}
ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]{0,23}$")


class Refusal(Exception):
    def __init__(self, kind):
        self.kind = kind


def fail(kind):
    sys.stderr.write(f"运行拒收: {kind}\n")
    raise SystemExit(1)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refusal("BAD_INPUT")
        result[key] = value
    return result


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != TOP_KEYS:
        raise Refusal("BAD_INPUT")
    survey_id = payload["survey_id"]
    if (
        not isinstance(survey_id, str)
        or not 2 <= len(survey_id) <= 48
        or survey_id != survey_id.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in survey_id)
    ):
        raise Refusal("BAD_INPUT")
    confidence = payload["confidence_level"]
    if not finite(confidence) or not 0.8 <= confidence <= 0.999:
        raise Refusal("BAD_INPUT")
    strata = payload["strata"]
    if not isinstance(strata, list) or not 2 <= len(strata) <= 12:
        raise Refusal("BAD_INPUT")
    seen = set()
    cleaned = []
    for item in strata:
        if not isinstance(item, dict) or set(item) != STRATUM_KEYS:
            raise Refusal("BAD_INPUT")
        identifier = item["stratum_id"]
        if not isinstance(identifier, str) or not ID_PATTERN.fullmatch(identifier) or identifier in seen:
            raise Refusal("BAD_INPUT")
        seen.add(identifier)
        population = item["population"]
        if isinstance(population, bool) or not isinstance(population, int) or not 2 <= population <= 1_000_000_000:
            raise Refusal("BAD_INPUT")
        responses = item["responses"]
        if not isinstance(responses, list) or not 2 <= len(responses) <= 500:
            raise Refusal("BAD_INPUT")
        if any(not finite(value) for value in responses) or len(responses) > population:
            raise Refusal("BAD_INPUT")
        cleaned.append(
            {
                "stratum_id": identifier,
                "population": population,
                "responses": [float(value) for value in responses],
            }
        )
    return survey_id, float(confidence), cleaned


def estimate(confidence, strata):
    total_population = sum(item["population"] for item in strata)
    mean = 0.0
    variance = 0.0
    rows = []
    for item in strata:
        population = item["population"]
        responses = item["responses"]
        sample_size = len(responses)
        sample_mean = statistics.fmean(responses)
        sample_variance = statistics.variance(responses)
        weight = population / total_population
        contribution = (
            weight
            * weight
            * (1.0 - sample_size / population)
            * sample_variance
            / sample_size
        )
        mean += weight * sample_mean
        variance += contribution
        rows.append(
            {
                "stratum_id": item["stratum_id"],
                "sample_size": sample_size,
                "population": population,
                "mean": sample_mean,
                "variance_contribution": contribution,
            }
        )
    standard_error = math.sqrt(max(0.0, variance))
    z_value = statistics.NormalDist().inv_cdf(0.5 + confidence / 2.0)
    half_width = z_value * standard_error
    return {
        "survey_id": None,
        "status": "complete",
        "estimate": mean,
        "standard_error": standard_error,
        "ci_low": mean - half_width,
        "ci_high": mean + half_width,
        "strata": rows,
    }


def publish(target, payload):
    if not target.parent.is_dir() or target.is_dir() or not os.access(target.parent, os.W_OK):
        raise Refusal("IO_FAILURE")
    old = target.read_bytes() if target.exists() else None
    stage = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=".survey-", dir=target.parent)
        stage = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(stage, target)
        stage = None
    except OSError:
        if old is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(old)
        raise Refusal("IO_FAILURE")
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)


def main(argv):
    if len(argv) != 3:
        fail("BAD_INPUT")
    source, target = Path(argv[1]), Path(argv[2])
    try:
        payload = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=strict_pairs)
        survey_id, confidence, strata = validate(payload)
        result = estimate(confidence, strata)
        result["survey_id"] = survey_id
        encoded = (json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        publish(target, encoded)
        return 0
    except Refusal as exc:
        fail(exc.kind)
    except (OSError, UnicodeError, ValueError):
        fail("BAD_INPUT")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
