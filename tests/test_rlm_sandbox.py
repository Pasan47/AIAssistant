import pytest

from app.rlm.sandbox import PlanBudgetExceeded, PlanRejected, run_plan


def fake_search(query, **kwargs):
    return [{"chunk_id": f"{query}#1"}]


def test_valid_plan_runs_and_dedupes():
    code = 'results = []\nfor q in ["a", "b", "a"]:\n    results += search(q, top_k=5)\nresult = results'
    assert [c["chunk_id"] for c in run_plan(code, fake_search, 5)] == ["a#1", "b#1"]


@pytest.mark.parametrize("code", [
    "import os", "result = __import__('os')", "x = search('a').append(1)",
    "while True:\n    pass", "result = [c for c in []]", "open('/etc/passwd')",
])
def test_malicious_plans_rejected(code):
    with pytest.raises(PlanRejected):
        run_plan(code, fake_search, 5)


def test_search_budget_enforced():
    with pytest.raises(PlanBudgetExceeded):
        run_plan('for q in ["1","2","3"]:\n    search(q)\nresult = []', fake_search, 2)
