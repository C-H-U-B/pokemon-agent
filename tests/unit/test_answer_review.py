import runpy
from pathlib import Path
import pytest

review = runpy.run_path(str(Path(__file__).resolve().parents[2] / "benchmarks/review_answers.py"))


@pytest.mark.parametrize("actual", [
    {"pokemon": "Raichu", "level": 20, "version": "red-blue"},
    {"pokemon": "Pikachu", "level": 30, "version": "red-blue"},
    {"pokemon": "Pikachu", "level": 20, "version": "sun-moon"},
    {"pokemon": "Pikachu", "level": 20},
])
def test_structured_reference_rejects_plausible_wrong_answers(actual):
    assert not review["matches_reference"](actual, {"pokemon": "Pikachu", "level": 20, "version": "red-blue"})


def test_complete_lists_reject_omissions_and_duplicates():
    match = review["matches_reference"]
    assert match([{"id": 2}, {"id": 1}], [{"id": 1}, {"id": 2}])
    assert not match([{"id": 1}], [{"id": 1}, {"id": 2}])
    assert not match([{"id": 1}, {"id": 1}], [{"id": 1}, {"id": 2}])


def test_grounding_pass_does_not_count_as_factual_success():
    case = {"id": "X", "grounding_decision": "PASS", "reference": {}, "review": {}}
    result = review["summarize"]([case])
    assert result["reviewed"] == 0
    assert result["pending"] == 1
    assert result["factually_correct"] == 0


def test_partial_review_is_rejected():
    with pytest.raises(ValueError, match="incomplète"):
        review["summarize"]([{"id": "X", "reference": {}, "review": {"factually_correct": True}}])
