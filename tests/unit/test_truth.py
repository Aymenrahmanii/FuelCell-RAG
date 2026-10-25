"""The system YAML truths must load, and their numbers must be physically consistent.

If a generator or golden question ever disagrees with these files, the truth wins, so it is
worth catching typos here.
"""

import pytest

from fcrag.truth import SystemTruth, TruthParameter, ureg

FARADAY = 96485.33  # C/mol
H2_MOLAR_MASS = 2.016  # g/mol
H2_LHV = 120.0  # kJ/g


def stack_id(system: SystemTruth) -> str:
    return next(c.id for c in system.components if c.type == "stack")


def value(system: SystemTruth, key: str, component: str | None = None) -> float:
    return system.lookup(key, component).value


def test_three_systems_load(systems: dict[str, SystemTruth]) -> None:
    assert sorted(systems) == ["A", "B", "C"]


@pytest.mark.parametrize("code", ["A", "B", "C"])
def test_stack_electrics_consistent(systems: dict[str, SystemTruth], code: str) -> None:
    s = systems[code]
    stk = stack_id(s)
    cells = value(s, "cell_count", stk)
    current = value(s, "rated_current", stk)

    assert current == pytest.approx(
        value(s, "rated_current_density", stk) * value(s, "active_area", stk), rel=0.01
    )
    stack_v = value(s, "stack_voltage_rated", stk)
    assert stack_v == pytest.approx(cells * value(s, "cell_voltage_rated", stk), rel=0.01)
    assert value(s, "rated_gross_power", stk) * 1000 == pytest.approx(stack_v * current, rel=0.01)
    assert value(s, "open_circuit_voltage", stk) > stack_v


@pytest.mark.parametrize("code", ["A", "B", "C"])
def test_hydrogen_and_efficiency_consistent(systems: dict[str, SystemTruth], code: str) -> None:
    s = systems[code]
    stk = stack_id(s)
    per_module = s.code == "B"
    h2_key = "h2_consumption_rated_per_module" if per_module else "h2_consumption_rated"
    net_key = "rated_net_power_per_module" if per_module else "rated_net_power"

    reacted = (
        value(s, "rated_current", stk) * value(s, "cell_count", stk) / (2 * FARADAY) * H2_MOLAR_MASS
    )
    consumed = value(s, h2_key)
    assert reacted <= consumed <= reacted * 1.05, "consumption = reacted H2 plus a few % purge"

    efficiency = value(s, net_key) / (consumed * H2_LHV) * 100
    assert efficiency == pytest.approx(value(s, "system_efficiency_rated"), abs=1.0)
    assert value(s, net_key) < value(s, "rated_gross_power", stk)


def test_system_b_module_totals(systems: dict[str, SystemTruth]) -> None:
    b = systems["B"]
    modules = value(b, "module_count")
    assert value(b, "rated_net_power") == modules * value(b, "rated_net_power_per_module")
    assert value(b, "h2_consumption_rated") == pytest.approx(
        modules * value(b, "h2_consumption_rated_per_module")
    )


def test_every_unit_is_pint_parseable(systems: dict[str, SystemTruth]) -> None:
    params: list[TruthParameter] = []
    for s in systems.values():
        params += s.parameters
        for c in s.components:
            params += c.parameters
    for p in params:
        p.quantity()  # raises on an unknown unit


def test_superseded_values_drive_current_version(systems: dict[str, SystemTruth]) -> None:
    hum = systems["A"].lookup("pressure_drop_dry_side", "A-HUM")
    assert hum.current_doc_version == 2
    assert hum.superseded[0].value != hum.value
    assert systems["A"].lookup("rated_net_power").current_doc_version == 1


def test_lookup_errors_name_the_problem(systems: dict[str, SystemTruth]) -> None:
    with pytest.raises(KeyError, match="no component"):
        systems["A"].lookup("cell_count", "A-XXX")
    with pytest.raises(KeyError, match="no parameter"):
        systems["A"].lookup("warranty_period")


def test_temperature_converts() -> None:
    assert ureg.Quantity(85, "degC").to("K").magnitude == pytest.approx(358.15)
