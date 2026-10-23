"""Verification test for CBC solver availability."""
from pulp import PULP_CBC_CMD, LpMaximize, LpProblem, LpVariable


def test_cbc_solver_is_available():
    solver = PULP_CBC_CMD(msg=False)
    assert solver.available(), "CBC ソルバーがシステムにインストールされていません (coinor-cbc)"


def test_cbc_solver_solves_simple_milp():
    prob = LpProblem("test_simple", LpMaximize)
    x = LpVariable("x", lowBound=0, cat="Integer")
    y = LpVariable("y", lowBound=0, cat="Integer")
    prob += x + y
    prob += 2 * x + y <= 10
    solver = PULP_CBC_CMD(msg=False)
    status = prob.solve(solver)
    assert status == 1  # Optimal
    assert prob.objective.value() == 10.0
