"""Acceptance tests for the stratified survey estimator."""

import json
import math
import os
import statistics
import subprocess
import sys

import pytest


ENTRY = os.environ.get("SURVEY_VARIANCE_ENTRY", "/app/stratified_survey_variance.py")


def sample():
    return {
        "survey_id": "VISIT-2026",
        "confidence_level": 0.95,
        "strata": [
            {"stratum_id": "SMALL", "population": 100, "responses": [1.0, 2.0, 3.0, 4.0]},
            {"stratum_id": "LARGE", "population": 300, "responses": [8.0, 10.0, 12.0]},
        ],
    }


def write(path, payload, raw=None):
    if raw is None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    path.write_bytes(raw.encode("utf-8"))
    return path


def invoke(tmp_path, payload, *, raw=None, name="report"):
    source = write(tmp_path / "survey.json", payload, raw=raw)
    output = tmp_path / f"{name}.json"
    result = subprocess.run(
        [sys.executable, ENTRY, str(source), str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result, source, output


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def expected_rows(payload):
    total = sum(item["population"] for item in payload["strata"])
    rows = []
    estimate = 0.0
    variance = 0.0
    for item in payload["strata"]:
        population = item["population"]
        values = item["responses"]
        sample_size = len(values)
        sample_mean = statistics.fmean(values)
        sample_variance = statistics.variance(values)
        weight = population / total
        contribution = weight * weight * (1 - sample_size / population) * sample_variance / sample_size
        estimate += weight * sample_mean
        variance += contribution
        rows.append((sample_mean, contribution))
    return estimate, math.sqrt(variance), rows


def test_successful_run_is_quiet(tmp_path):
    """题面：「复核工具从命令行接收两个位置参数；文件位置不靠环境变量传递。」"""
    result, _, output = invoke(tmp_path, sample())
    assert result.returncode == 0 and result.stdout == "" and result.stderr == "" and output.is_file()


def test_stratified_estimate_uses_population_weights(tmp_path):
    """题面：「总体均值的分层估计为 `sum(N_h/N * m_h)`。」"""
    payload = sample()
    estimate, _, _ = expected_rows(payload)
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 0 and read(output)["estimate"] == pytest.approx(estimate)


def test_standard_error_uses_finite_population_correction(tmp_path):
    """题面：「标准误是该方差的正平方根。」"""
    payload = sample()
    _, standard_error, _ = expected_rows(payload)
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 0 and read(output)["standard_error"] == pytest.approx(standard_error)


def test_stratum_contributions_follow_the_formula(tmp_path):
    """题面：「最后一栏是该层对总体均值方差的贡献，不是标准误。」"""
    payload = sample()
    _, _, rows = expected_rows(payload)
    result, _, output = invoke(tmp_path, payload)
    observed = [item["variance_contribution"] for item in read(output)["strata"]]
    assert result.returncode == 0 and observed == pytest.approx([row[1] for row in rows])


def test_census_stratum_has_zero_variance_contribution(tmp_path):
    """题面：「某层已经全查时，该层的有限总体修正因子为 0。」"""
    payload = sample()
    payload["strata"][0]["population"] = 4
    result, _, output = invoke(tmp_path, payload)
    rows = read(output)["strata"]
    assert result.returncode == 0 and rows[0]["variance_contribution"] == pytest.approx(0.0)


def test_confidence_interval_uses_requested_level(tmp_path):
    """题面：「置信区间以估计值为中心，半宽为 `z * 标准误`」。"""
    payload = sample()
    result, _, output = invoke(tmp_path, payload)
    document = read(output)
    z_value = statistics.NormalDist().inv_cdf(0.975)
    expected_half = z_value * document["standard_error"]
    assert result.returncode == 0
    assert document["estimate"] - document["ci_low"] == pytest.approx(expected_half)
    assert document["ci_high"] - document["estimate"] == pytest.approx(expected_half)


def test_top_level_key_set_is_exact(tmp_path):
    """题面：「外层对象没有清单外字段。」"""
    payload = sample()
    payload["operator"] = "day"
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_stratum_key_set_is_exact(tmp_path):
    """题面：「每一层由三个指定字段构成：」"""
    payload = sample()
    payload["strata"][0]["weight"] = 1.0
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_duplicate_json_key_is_refused(tmp_path):
    """题面：「回访材料只要无法按上述 schema 读取，命令就以 1 结束。」"""
    raw = (
        '{"survey_id":"A1","confidence_level":0.9,"strata":['
        '{"stratum_id":"A","population":3,"responses":[1,2]},'
        '{"stratum_id":"B","population":3,"responses":[1,2]},'
        '{"stratum_id":"C","population":3,"responses":[1,2]}],'
        '"strata":[]}'
    )
    result, _, output = invoke(tmp_path, None, raw=raw)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


@pytest.mark.parametrize("survey_id", ["A", " leading", "trailing ", "A" * 49, "A\nB"])
def test_survey_identifier_is_strict(tmp_path, survey_id):
    """题面：「`survey_id` 由两至四十八个字符组成；编号不能以空白包住，也不可在内部夹控制字符。」"""
    payload = sample()
    payload["survey_id"] = survey_id
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_survey_identifier_bounds_are_inclusive(tmp_path):
    """题面：「`survey_id` 由两至四十八个字符组成；编号不能以空白包住，也不可在内部夹控制字符。」"""
    accepted = []
    for index, identifier in enumerate(("A1", "A" * 48), 1):
        payload = sample()
        payload["survey_id"] = identifier
        accepted.append(invoke(tmp_path, payload, name=f"case-a{index}"))
    rejected = []
    for index, identifier in enumerate(("A", "A" * 49), 1):
        payload = sample()
        payload["survey_id"] = identifier
        rejected.append(invoke(tmp_path, payload, name=f"case-b{index}"))
    assert all(result.returncode == 0 and output.is_file() for result, _, output in accepted)
    assert all(result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()
               for result, _, output in rejected)


def test_boolean_population_is_refused(tmp_path):
    """题面：「布尔值不能当整数或小数。」"""
    payload = sample()
    payload["strata"][0]["population"] = True
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_too_few_responses_are_refused(tmp_path):
    """题面：「`responses` 是 2 到 500 个有限数值，数量不得超过该层人口数。」"""
    payload = sample()
    payload["strata"][0]["responses"] = [1.0]
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_sample_larger_than_population_is_refused(tmp_path):
    """题面：「`responses` 是 2 到 500 个有限数值，数量不得超过该层人口数。」"""
    payload = sample()
    payload["strata"][0]["population"] = 3
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_confidence_level_bounds_are_enforced(tmp_path):
    """题面：「`confidence_level` 是 0.8 到 0.999 的有限数。」"""
    payload = sample()
    payload["confidence_level"] = 1.0
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_output_has_exact_key_order(tmp_path):
    """题面：「复核单的排版必须紧凑，并以一个 LF 收尾。」"""
    result, _, output = invoke(tmp_path, sample())
    raw = output.read_bytes()
    document = json.loads(raw)
    assert result.returncode == 0
    assert list(document) == ["survey_id", "status", "estimate", "standard_error", "ci_low", "ci_high", "strata"]
    assert b": " not in raw and raw.endswith(b"\n") and raw.count(b"\n") == 1


def test_strata_output_preserves_input_order(tmp_path):
    """题面：「各层结果沿用回访单中的层序。」"""
    payload = sample()
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 0
    assert [item["stratum_id"] for item in read(output)["strata"]] == ["SMALL", "LARGE"]


def test_stratum_results_have_exact_keys(tmp_path):
    """题面：「每个层结果固定保留五个字段：」"""
    result, _, output = invoke(tmp_path, sample())
    document = read(output)
    expected = {"stratum_id", "sample_size", "population", "mean", "variance_contribution"}
    assert result.returncode == 0
    assert set(document["strata"][0]) == expected
    assert set(document["strata"][1]) == expected


def test_absent_parent_is_io_failure(tmp_path):
    """题面：「复核单所在目录不能写、目标已被目录占用或路径失效时」"""
    source = write(tmp_path / "survey.json", sample())
    output = tmp_path / "absent-parent" / "report.json"
    result = subprocess.run(
        [sys.executable, ENTRY, str(source), str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1 and result.stderr == "运行拒收: IO_FAILURE\n" and not output.exists()


def test_bad_input_preserves_existing_output(tmp_path):
    """题面：「被拒收的回访批次不应向终端抛出 `traceback`。」"""
    result, source, output = invoke(tmp_path, sample())
    before = output.read_bytes()
    payload = sample()
    payload["confidence_level"] = True
    write(source, payload)
    rejected = subprocess.run(
        [sys.executable, ENTRY, str(source), str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0 and rejected.returncode == 1
    assert output.read_bytes() == before and "traceback" not in rejected.stderr.lower()


def test_repeat_run_is_byte_identical(tmp_path):
    """题面：「拿同一份回访材料重跑复核，统计单应保持相同字节。」"""
    result, source, output = invoke(tmp_path, sample())
    first = output.read_bytes()
    second = subprocess.run(
        [sys.executable, ENTRY, str(source), str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0 and second.returncode == 0 and output.read_bytes() == first
