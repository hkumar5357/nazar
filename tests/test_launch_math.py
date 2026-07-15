"""Tests for the launch-economics simulator (BRIEF §5.6).

Covers: hand-checked formulas on the defaults scenario, the contribution<=0
edge case (paybacks -> None), JSON schema/rounding/determinism of the
written artifact (two runs produce byte-identical output — no generation
timestamp inside the file, R4 run metadata lives in runs/ instead), and
that all three REFERENCE_SCENARIOS' embedded outputs match a fresh
compute() call (the cross-check the React dashboard relies on).
"""

import json

import pytest

from pipeline import launch_math, provenance, runlog


# --- compute(): hand-checked formulas ---------------------------------------


def test_compute_defaults_matches_hand_calculation():
    # Hand check (BRIEF §5.6 defaults: price 150, matcha 4.5/g x 2g,
    # packaging 20, copack 12, commission 30%, CAC 250, repeat 25%,
    # 2 orders/month/repeater):
    #   cogs = 4.5*2 + 20 + 12 = 41
    #   net_revenue = 150 * 0.70 = 105
    #   contribution_per_order = 105 - 41 = 64
    #   payback_orders = 250 / 64 = 3.90625 -> 3.91
    #   payback_months = 3.90625 / (0.25*2) = 7.8125 -> 7.81
    out = launch_math.compute(launch_math.PARAM_DEFAULTS)
    assert out == {
        "cogs": 41.0,
        "net_revenue": 105.0,
        "contribution_per_order": 64.0,
        "payback_orders": 3.91,
        "payback_months": 7.81,
    }


def test_compute_lean_scenario_matches_hand_calculation():
    # price 120, commission 35%, CAC 400, other params at default.
    #   cogs = 41 (unchanged)
    #   net_revenue = 120 * 0.65 = 78
    #   contribution_per_order = 78 - 41 = 37
    #   payback_orders = 400 / 37 = 10.810810... -> 10.81
    #   payback_months = 10.810810... / 0.5 = 21.621621... -> 21.62
    params = dict(launch_math.PARAM_DEFAULTS)
    params.update({"price_inr": 120, "qcom_commission_pct": 35, "cac_inr": 400})
    out = launch_math.compute(params)
    assert out == {
        "cogs": 41.0,
        "net_revenue": 78.0,
        "contribution_per_order": 37.0,
        "payback_orders": 10.81,
        "payback_months": 21.62,
    }


def test_compute_favourable_scenario_matches_hand_calculation():
    # price 180, commission 25%, CAC 150, other params at default.
    #   cogs = 41 (unchanged)
    #   net_revenue = 180 * 0.75 = 135
    #   contribution_per_order = 135 - 41 = 94
    #   payback_orders = 150 / 94 = 1.595744... -> 1.6
    #   payback_months = 1.595744... / 0.5 = 3.191489... -> 3.19
    params = dict(launch_math.PARAM_DEFAULTS)
    params.update({"price_inr": 180, "qcom_commission_pct": 25, "cac_inr": 150})
    out = launch_math.compute(params)
    assert out == {
        "cogs": 41.0,
        "net_revenue": 135.0,
        "contribution_per_order": 94.0,
        "payback_orders": 1.6,
        "payback_months": 3.19,
    }


def test_compute_missing_param_raises():
    params = dict(launch_math.PARAM_DEFAULTS)
    del params["cac_inr"]
    with pytest.raises(ValueError, match="missing required params"):
        launch_math.compute(params)


def test_compute_ignores_extra_params():
    params = dict(launch_math.PARAM_DEFAULTS)
    params["some_unrelated_key"] = "ignored"
    out = launch_math.compute(params)
    assert out["cogs"] == 41.0


# --- edge case: contribution <= 0 -> None paybacks --------------------------


def test_compute_zero_contribution_gives_none_paybacks():
    # net_revenue == cogs exactly: price*(1-commission/100) == cogs.
    # cogs = 41 with defaults; pick price/commission so net_revenue = 41.
    # price_inr=41/(1-0.30)=58.571..., simpler: set commission so that
    # net_revenue lands exactly on cogs using price 150 -> commission such
    # that 150*(1-c/100) = 41 -> c = 100*(1 - 41/150) = 72.6667%. Easier:
    # hold price/commission fixed and inflate cogs via matcha cost so
    # contribution is exactly zero.
    params = dict(launch_math.PARAM_DEFAULTS)
    # net_revenue at defaults = 105 (see test above). Set cogs = 105 exactly
    # by raising packaging_inr: cogs = 4.5*2+packaging+12 = 105
    # -> packaging = 105 - 9 - 12 = 84.
    params["packaging_inr"] = 84
    out = launch_math.compute(params)
    assert out["contribution_per_order"] == 0.0
    assert out["payback_orders"] is None
    assert out["payback_months"] is None


def test_compute_negative_contribution_gives_none_paybacks():
    params = dict(launch_math.PARAM_DEFAULTS)
    params["packaging_inr"] = 200  # blows cogs far past net_revenue
    out = launch_math.compute(params)
    assert out["contribution_per_order"] < 0
    assert out["payback_orders"] is None
    assert out["payback_months"] is None


# --- REFERENCE_SCENARIOS cross-check ----------------------------------------


def test_reference_scenarios_present_and_named():
    ids = [s["id"] for s in launch_math.REFERENCE_SCENARIOS]
    assert ids == ["defaults", "lean", "favourable"]


@pytest.mark.parametrize("scenario", launch_math.REFERENCE_SCENARIOS, ids=lambda s: s["id"])
def test_reference_scenario_outputs_match_compute(scenario):
    assert launch_math.compute(scenario["params"]) == scenario["outputs"]


def test_reference_scenarios_cover_every_param_id():
    for scenario in launch_math.REFERENCE_SCENARIOS:
        assert set(scenario["params"]) == set(launch_math.PARAM_IDS)


def test_lean_is_the_stress_case_relative_to_defaults():
    lean = next(s for s in launch_math.REFERENCE_SCENARIOS if s["id"] == "lean")
    defaults = next(s for s in launch_math.REFERENCE_SCENARIOS if s["id"] == "defaults")
    assert lean["outputs"]["contribution_per_order"] < defaults["outputs"]["contribution_per_order"]
    assert lean["outputs"]["payback_orders"] > defaults["outputs"]["payback_orders"]
    assert lean["outputs"]["payback_months"] > defaults["outputs"]["payback_months"]


def test_favourable_is_better_than_defaults():
    favourable = next(s for s in launch_math.REFERENCE_SCENARIOS if s["id"] == "favourable")
    defaults = next(s for s in launch_math.REFERENCE_SCENARIOS if s["id"] == "defaults")
    assert favourable["outputs"]["contribution_per_order"] > defaults["outputs"]["contribution_per_order"]
    assert favourable["outputs"]["payback_orders"] < defaults["outputs"]["payback_orders"]
    assert favourable["outputs"]["payback_months"] < defaults["outputs"]["payback_months"]


# --- PARAMS schema -----------------------------------------------------------

EXPECTED_PARAM_IDS = [
    "price_inr",
    "matcha_cost_per_g",
    "matcha_g_per_serve",
    "packaging_inr",
    "copack_inr",
    "qcom_commission_pct",
    "cac_inr",
    "repeat_rate_pct",
    "orders_per_month_per_repeater",
]


def test_params_have_expected_ids_in_order():
    assert [p["id"] for p in launch_math.PARAMS] == EXPECTED_PARAM_IDS


def test_params_each_have_required_fields():
    required = {"id", "label", "unit", "default", "min", "max", "step", "source_note"}
    for p in launch_math.PARAMS:
        assert required <= set(p), f"{p['id']} missing fields: {required - set(p)}"
        assert p["min"] <= p["default"] <= p["max"], p["id"]
        assert isinstance(p["source_note"], str) and len(p["source_note"]) > 20, p["id"]
        # No fabricated point-citation: source notes describe RANGES, and
        # every note is written as a public-benchmark claim, not a specific
        # dated source (PROTOCOL: no fabricated citations).
        assert "benchmark" in p["source_note"].lower(), p["id"]


def test_params_defaults_match_brief_5_6():
    defaults = launch_math.PARAM_DEFAULTS
    assert defaults == {
        "price_inr": 150,
        "matcha_cost_per_g": 4.5,
        "matcha_g_per_serve": 2,
        "packaging_inr": 20,
        "copack_inr": 12,
        "qcom_commission_pct": 30,
        "cac_inr": 250,
        "repeat_rate_pct": 25,
        "orders_per_month_per_repeater": 2,
    }


# --- build_output() / JSON artifact schema -----------------------------------


def test_build_output_schema():
    out = launch_math.build_output()
    assert out["banner"] == "Simulation on public benchmarks — not a forecast."
    assert out["params"] == launch_math.PARAMS
    assert out["reference_scenarios"] == launch_math.REFERENCE_SCENARIOS
    assert out["formulas"] == launch_math.FORMULAS
    assert out["provenance"] == provenance.summarize({})
    assert "author-asserted" in out["benchmarks_note"]
    assert out["provenance"]["contains_fixture_data"] is False


def test_build_output_json_serializable_and_no_nan_or_inf():
    out = launch_math.build_output()
    text = json.dumps(out)
    assert "NaN" not in text
    assert "Infinity" not in text


def test_build_output_no_timestamp_leakage():
    # The artifact itself must carry no generation timestamp (deterministic
    # bytes requirement) — run timing lives in runs/*/run.json instead.
    out = launch_math.build_output()
    text = json.dumps(out)
    for forbidden in ("started_at", "finished_at", "retrieved_at", "generated_at"):
        assert forbidden not in text


# --- CLI: writes file, deterministic bytes, logs via runlog (R4) ------------


def test_main_writes_deterministic_bytes_and_logs_run(tmp_path, monkeypatch):
    app_data = tmp_path / "app" / "public" / "data"
    output_path = app_data / "launch_math.json"
    runs_dir = tmp_path / "runs"

    monkeypatch.setattr(launch_math, "APP_DATA", app_data)
    monkeypatch.setattr(launch_math, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(runlog, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(runlog, "RUNS_DIR", runs_dir)

    rc1 = launch_math.main([])
    assert rc1 == 0
    assert output_path.exists()
    bytes_1 = output_path.read_bytes()

    rc2 = launch_math.main([])
    assert rc2 == 0
    bytes_2 = output_path.read_bytes()

    assert bytes_1 == bytes_2, "launch_math.json must be byte-identical across runs"

    payload = json.loads(bytes_1)
    assert payload["banner"] == "Simulation on public benchmarks — not a forecast."
    assert [s["id"] for s in payload["reference_scenarios"]] == [
        "defaults",
        "lean",
        "favourable",
    ]

    # R4: every run is logged, including the second (identical-output) run.
    expected_sha256 = runlog.sha256_file(output_path)
    run_dirs = sorted(runs_dir.iterdir())
    assert len(run_dirs) == 2
    for run_dir in run_dirs:
        record = json.loads((run_dir / "run.json").read_text())
        assert record["command"] == "launch_math"
        assert record["status"] == "ok"
        assert record["outputs"] == [
            {
                "path": str(output_path.relative_to(tmp_path)),
                "sha256": expected_sha256,
            }
        ]


def test_main_output_matches_build_output(tmp_path, monkeypatch):
    app_data = tmp_path / "app" / "public" / "data"
    output_path = app_data / "launch_math.json"
    runs_dir = tmp_path / "runs"

    monkeypatch.setattr(launch_math, "APP_DATA", app_data)
    monkeypatch.setattr(launch_math, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(runlog, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(runlog, "RUNS_DIR", runs_dir)

    launch_math.main([])
    written = json.loads(output_path.read_text())
    assert written == launch_math.build_output()
