"""Phase 31: synthetic-name protocol + parameter-sweep experiments.

Covers:
  * parse_synthetic_name / apply_overrides edge cases
  * resolver extensions on get_domain / get_capacity_model
  * registry @-character invariant
  * ParameterSweep validation
  * ExperimentDefinition round-trip through definition_json
  * Experiment.run axis expansion (slow — runs transforms)
  * reader compatibility: synthetic names flow through
    volume_sensitivity / compute_viability_summary / diagnostics
"""

from __future__ import annotations

import json

import pytest

from transforms import economics
from core.capacity_models import get_capacity_model
from core.delivery_domains import get_domain
from core.experiments import (
    ExperimentDefinition, ParameterSweep, definition_from_dict,
    get_experiment,
)
from core.parameter_sweeps import (
    apply_overrides, assert_no_reserved_chars, parse_synthetic_name,
)


# ─────────────────────────────────────────────────────────────────────────────
# parse_synthetic_name
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_plain_name_returns_empty_overrides():
    assert parse_synthetic_name("food_delivery") == ("food_delivery", {})


def test_parse_single_override():
    base, ov = parse_synthetic_name("food_delivery@saturation_volume_per_day=1500")
    assert base == "food_delivery"
    assert ov == {"saturation_volume_per_day": 1500}
    assert isinstance(ov["saturation_volume_per_day"], int)


def test_parse_multiple_overrides_and_float_coercion():
    base, ov = parse_synthetic_name(
        "food_delivery@saturation_volume_per_day=1500,premium_share=0.25"
    )
    assert base == "food_delivery"
    assert ov["saturation_volume_per_day"] == 1500
    assert ov["premium_share"] == pytest.approx(0.25)
    assert isinstance(ov["premium_share"], float)


def test_parse_non_numeric_value_stays_string():
    """Trial coercion must not mangle string values."""
    _base, ov = parse_synthetic_name("food_delivery@name=custom_label")
    assert ov["name"] == "custom_label"
    assert isinstance(ov["name"], str)


def test_parse_malformed_pair_raises():
    with pytest.raises(ValueError, match="missing '='"):
        parse_synthetic_name("food_delivery@no_equals")


def test_parse_empty_base_raises():
    with pytest.raises(ValueError, match="empty base"):
        parse_synthetic_name("@field=1")


def test_parse_empty_override_block_raises():
    with pytest.raises(ValueError, match="empty override block"):
        parse_synthetic_name("food_delivery@")


# ─────────────────────────────────────────────────────────────────────────────
# apply_overrides + resolvers
# ─────────────────────────────────────────────────────────────────────────────

def test_apply_overrides_unknown_field_raises_with_valid_list():
    base = get_domain("food_delivery")
    with pytest.raises(KeyError, match="valid fields"):
        apply_overrides(base, {"not_a_field": 1}, synthetic_name="x@not_a_field=1")


def test_get_domain_resolves_synthetic_name():
    d = get_domain("food_delivery@saturation_volume_per_day=1500")
    assert d.saturation_volume_per_day == 1500
    # Synthetic identity preserved in .name → survives round-trips
    # through snapshot tables keyed on dom.name.
    assert d.name == "food_delivery@saturation_volume_per_day=1500"
    # Untouched fields inherit the base.
    assert d.volume_value_decay_rate == get_domain("food_delivery").volume_value_decay_rate


def test_get_domain_plain_name_behaviour_unchanged():
    assert get_domain("food_delivery").saturation_volume_per_day == 4000
    with pytest.raises(KeyError):
        get_domain("food_deliveryy")   # misspell still strict


def test_get_domain_unknown_base_in_synthetic_name_raises():
    with pytest.raises(KeyError, match="unknown delivery_domain base"):
        get_domain("nope@saturation_volume_per_day=1500")


def test_get_capacity_model_resolves_synthetic_name():
    c = get_capacity_model("pilot_capacity@operator_to_drone_ratio=0.30")
    assert c.operator_to_drone_ratio == pytest.approx(0.30)
    assert c.name == "pilot_capacity@operator_to_drone_ratio=0.30"


def test_registry_names_cannot_contain_separator():
    with pytest.raises(AssertionError, match="reserved"):
        assert_no_reserved_chars(["ok_name", "bad@name"], "test_registry")


# ─────────────────────────────────────────────────────────────────────────────
# ParameterSweep validation
# ─────────────────────────────────────────────────────────────────────────────

def test_parameter_sweep_valid_construction():
    s = ParameterSweep(
        dimension="delivery_domain", base_name="food_delivery",
        parameter="saturation_volume_per_day", values=[1500, 2500],
    )
    assert s.synthetic_names() == [
        "food_delivery@saturation_volume_per_day=1500",
        "food_delivery@saturation_volume_per_day=2500",
    ]


def test_parameter_sweep_rejects_unsupported_dimension():
    # delivery_domain + capacity_model are supported; anything else (e.g.
    # scenario / economic_model) must be rejected by the gate.
    with pytest.raises(ValueError, match="not yet supported"):
        ParameterSweep(
            dimension="economic_model", base_name="suburban_standard",
            parameter="delivery_fee", values=[5.0],
        )


def test_parameter_sweep_rejects_unknown_base():
    with pytest.raises(KeyError):
        ParameterSweep(
            dimension="delivery_domain", base_name="nope",
            parameter="saturation_volume_per_day", values=[1500],
        )


def test_parameter_sweep_rejects_unknown_parameter():
    with pytest.raises(KeyError, match="valid fields"):
        ParameterSweep(
            dimension="delivery_domain", base_name="food_delivery",
            parameter="saturation_volume_per_dy", values=[1500],
        )


def test_parameter_sweep_rejects_empty_values():
    with pytest.raises(ValueError, match="non-empty"):
        ParameterSweep(
            dimension="delivery_domain", base_name="food_delivery",
            parameter="saturation_volume_per_day", values=[],
        )


# ─────────────────────────────────────────────────────────────────────────────
# ExperimentDefinition round-trip
# ─────────────────────────────────────────────────────────────────────────────

def _sweep_defn() -> ExperimentDefinition:
    return ExperimentDefinition(
        name="test_sweep", run_ids=[], scenarios=[],
        economic_models=["suburban_standard"],
        delivery_domains=["food_delivery"],
        scale_models=["pilot_program"],
        parameter_sweeps=[ParameterSweep(
            dimension="delivery_domain", base_name="food_delivery",
            parameter="saturation_volume_per_day", values=[1500, 2500],
        )],
    )


def test_definition_roundtrips_through_json():
    defn = _sweep_defn()
    payload = json.loads(json.dumps(defn.to_dict()))
    rebuilt = definition_from_dict(payload)
    assert rebuilt == defn
    assert isinstance(rebuilt.parameter_sweeps[0], ParameterSweep)


def test_definition_rejects_non_sweep_entries():
    with pytest.raises(TypeError, match="ParameterSweep"):
        ExperimentDefinition(
            name="bad", run_ids=[], scenarios=[], economic_models=[],
            delivery_domains=[], scale_models=[],
            parameter_sweeps=[{"dimension": "delivery_domain"}],
        )


def test_builtin_food_saturation_sensitivity_registered():
    defn = get_experiment("food_saturation_sensitivity")
    assert defn.parameter_sweeps
    assert defn.parameter_sweeps[0].parameter == "saturation_volume_per_day"
    # Baseline row included explicitly per append-only semantics.
    assert "food_delivery" in defn.delivery_domains


# ─────────────────────────────────────────────────────────────────────────────
# Reader compatibility: synthetic names flow through the analytical stack
# ─────────────────────────────────────────────────────────────────────────────

SYNTH = "food_delivery@saturation_volume_per_day=1500"


@pytest.fixture
def synthetic_domain_db(writable_db) -> str:
    """A DB with snapshots under the base domain AND one synthetic variant."""
    db, _rid = writable_db
    economics.run(db, delivery_domain="food_delivery")
    economics.run(db, delivery_domain=get_domain(SYNTH))
    return db


def test_volume_sensitivity_emits_synthetic_rows(synthetic_domain_db: str):
    from core.volume_sensitivity import volume_sensitivity
    rows = volume_sensitivity(synthetic_domain_db)
    synth_rows = [r for r in rows if r["delivery_domain"] == SYNTH]
    assert synth_rows, "synthetic domain produced no sensitivity rows"
    # The resolved ceiling must be the swept value, not the base's 4000.
    assert all(r["saturation_volume_per_day"] == 1500 for r in synth_rows)


def test_viability_summary_emits_distinct_synthetic_cell(synthetic_domain_db: str):
    from core.volume_sensitivity import compute_viability_summary
    cells = compute_viability_summary(synthetic_domain_db)
    domains = {c["delivery_domain"] for c in cells}
    assert SYNTH in domains
    assert "food_delivery" in domains   # base coexists
    synth = next(c for c in cells if c["delivery_domain"] == SYNTH)
    assert synth["addressable_ceiling"] == 1500


def test_diagnostics_resolve_synthetic_names(synthetic_domain_db: str):
    from core.portfolio_summary import diagnose_viability_cells
    diags = [d for d in diagnose_viability_cells(synthetic_domain_db)
             if d["delivery_domain"] == SYNTH]
    assert diags
    for d in diags:
        # Anchor must respect the swept ceiling (largest sweep point ≤ 1500).
        assert d["anchor_deliveries_per_day"] <= 1500
        # Cost breakdown still reconstructs (capacity side untouched).
        assert d["cost_breakdown_at_anchor"]


# ─────────────────────────────────────────────────────────────────────────────
# Experiment.run integration (slow — runs the transform pipeline)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.slow
def test_experiment_run_expands_sweep_axis(writable_db):
    import sqlite3
    db, _rid = writable_db
    exp_result = __import__("core.experiments", fromlist=["Experiment"]) \
        .Experiment(_sweep_defn(), db).run()
    assert exp_result["status"] == "completed", exp_result.get("error")
    # 1 run × 1 model × (1 base + 2 synthetic domains) × 1 scale = 3 combos.
    assert exp_result["combinations"] == 3
    conn = sqlite3.connect(db)
    try:
        names = {r[0] for r in conn.execute(
            "SELECT DISTINCT domain_name FROM trip_economics_snapshots"
        ).fetchall()}
    finally:
        conn.close()
    assert "food_delivery@saturation_volume_per_day=1500" in names
    assert "food_delivery@saturation_volume_per_day=2500" in names


@pytest.mark.slow
def test_cli_adhoc_sweep_end_to_end(writable_db):
    import subprocess, sys
    db, _rid = writable_db
    res = subprocess.run(
        [sys.executable, "run_experiment.py",
         "--sweep", "delivery_domain.saturation_volume_per_day",
         "--base", "food_delivery",
         "--values", "1500,2500",
         "--db", db],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip(), "expected experiment_run_id on stdout"


# ═════════════════════════════════════════════════════════════════════════════
# Phase 32: capacity-model sweeps + what-if
# ═════════════════════════════════════════════════════════════════════════════

CAP_SYNTH = "pilot_capacity@operator_to_drone_ratio=0.3"


def test_get_capacity_model_preserves_synthetic_name():
    c = get_capacity_model(CAP_SYNTH)
    assert c.operator_to_drone_ratio == pytest.approx(0.3)
    assert c.name == CAP_SYNTH
    # Untouched fields inherit the base.
    assert c.deliveries_per_drone_per_day == \
        get_capacity_model("pilot_capacity").deliveries_per_drone_per_day


def test_capacity_invalid_parameter_raises():
    with pytest.raises(KeyError, match="valid fields"):
        get_capacity_model("pilot_capacity@not_a_field=1")


def test_capacity_parameter_sweep_validates():
    s = ParameterSweep(
        dimension="capacity_model", base_name="pilot_capacity",
        parameter="operator_to_drone_ratio", values=[0.6, 0.3],
    )
    assert s.synthetic_names() == [
        "pilot_capacity@operator_to_drone_ratio=0.6",
        "pilot_capacity@operator_to_drone_ratio=0.3",
    ]


def test_builtin_capacity_experiment_registered():
    defn = get_experiment("pilot_operator_ratio_sensitivity")
    sweep = defn.parameter_sweeps[0]
    assert sweep.dimension == "capacity_model"
    assert sweep.base_name == "pilot_capacity"


@pytest.mark.slow
def test_capacity_whatif_surfaces_in_viability_grid(writable_db):
    """End-to-end: run the built-in capacity experiment, then confirm the
    synthetic capacities are discovered and produce distinct viability
    cells with the overridden parameter applied."""
    from core.experiments import (
        Experiment, discover_synthetic_capacities, get_experiment,
    )
    from core.volume_sensitivity import compute_viability_summary
    db, _rid = writable_db
    # economics snapshots for the base domain must exist for the read path.
    economics.run(db, delivery_domain="retail_package")

    result = Experiment(get_experiment("pilot_operator_ratio_sensitivity"), db).run()
    assert result["status"] == "completed", result.get("error")

    discovered = discover_synthetic_capacities(db)
    assert "pilot_capacity@operator_to_drone_ratio=0.3" in discovered

    cells = compute_viability_summary(db)
    caps = {c["capacity_model"] for c in cells}
    assert "pilot_capacity@operator_to_drone_ratio=0.3" in caps
    assert "pilot_capacity" in caps   # base coexists


@pytest.mark.slow
def test_viability_grid_scopes_to_most_recent_experiment(writable_db):
    """Running multiple capacity what-ifs must NOT accumulate every
    variant in the grid — only the single most-recent experiment's
    variants appear alongside the registered profiles."""
    import time
    from core.experiments import (
        Experiment, ExperimentDefinition, ParameterSweep,
    )
    from core.volume_sensitivity import compute_viability_summary
    db, _rid = writable_db
    economics.run(db, delivery_domain="retail_package")

    def _whatif(values):
        defn = ExperimentDefinition(
            name="_whatif_test", run_ids=[], scenarios=[],
            economic_models=["suburban_standard"],
            delivery_domains=["retail_package"], scale_models=["pilot_program"],
            parameter_sweeps=[ParameterSweep(
                dimension="capacity_model", base_name="pilot_capacity",
                parameter="operator_to_drone_ratio", values=values,
            )],
        )
        Experiment(defn, db).run()

    _whatif([0.6, 0.5]); time.sleep(1.05)
    _whatif([0.25, 0.15])

    caps = {c["capacity_model"] for c in compute_viability_summary(db)}
    # The latest experiment's variants are present…
    assert "pilot_capacity@operator_to_drone_ratio=0.25" in caps
    assert "pilot_capacity@operator_to_drone_ratio=0.15" in caps
    # …and the earlier experiment's variants are NOT.
    assert "pilot_capacity@operator_to_drone_ratio=0.6" not in caps
    assert "pilot_capacity@operator_to_drone_ratio=0.5" not in caps
