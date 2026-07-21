"""Pure unit tests for services/survey.py's validate_answer - no DB needed."""

import pytest

from demosense.models.survey import Question, QuestionKind
from demosense.services.survey import validate_answer


def make_question(kind, *, is_required=False, config=None) -> Question:
    return Question(kind=kind, prompt="test", is_required=is_required, config=config or {})


def test_ordinal_within_range_ok():
    q = make_question(QuestionKind.ordinal, config={"min": 1, "max": 5})
    validate_answer(q, value_numeric=3)


def test_ordinal_above_max_rejected():
    q = make_question(QuestionKind.ordinal, config={"min": 1, "max": 5})
    with pytest.raises(ValueError):
        validate_answer(q, value_numeric=7)


def test_ordinal_below_min_rejected():
    q = make_question(QuestionKind.ordinal, config={"min": 1, "max": 5})
    with pytest.raises(ValueError):
        validate_answer(q, value_numeric=0)


def test_required_question_missing_value_rejected():
    q = make_question(QuestionKind.text, is_required=True)
    with pytest.raises(ValueError):
        validate_answer(q)


def test_optional_question_missing_value_ok():
    q = make_question(QuestionKind.text, is_required=False)
    validate_answer(q)  # should not raise


def test_wrong_field_for_kind_rejected():
    q = make_question(QuestionKind.text)
    with pytest.raises(ValueError):
        validate_answer(q, value_numeric=5)  # text question, numeric value given


def test_single_choice_valid_option_ok():
    q = make_question(QuestionKind.single_choice, config={"options": ["a", "b", "c"]})
    validate_answer(q, value_choice=["b"])


def test_single_choice_invalid_option_rejected():
    q = make_question(QuestionKind.single_choice, config={"options": ["a", "b", "c"]})
    with pytest.raises(ValueError):
        validate_answer(q, value_choice=["z"])


def test_single_choice_multiple_selected_rejected():
    q = make_question(QuestionKind.single_choice, config={"options": ["a", "b", "c"]})
    with pytest.raises(ValueError):
        validate_answer(q, value_choice=["a", "b"])


def test_multi_choice_subset_of_options_ok():
    q = make_question(QuestionKind.multi_choice, config={"options": ["satellite", "cable", "other"]})
    validate_answer(q, value_choice=["satellite", "other"])


def test_multi_choice_invalid_option_rejected():
    q = make_question(QuestionKind.multi_choice, config={"options": ["satellite", "cable"]})
    with pytest.raises(ValueError):
        validate_answer(q, value_choice=["dialup"])


def test_multi_choice_freeform_within_max_items_ok():
    q = make_question(QuestionKind.multi_choice, config={"freeform": True, "max_items": 5})
    validate_answer(q, value_choice=["housing", "jobs", "roads"])


def test_multi_choice_freeform_exceeds_max_items_rejected():
    q = make_question(QuestionKind.multi_choice, config={"freeform": True, "max_items": 5})
    with pytest.raises(ValueError):
        validate_answer(q, value_choice=["a", "b", "c", "d", "e", "f"])


def test_text_within_max_length_ok():
    q = make_question(QuestionKind.text, config={"max_length": 10})
    validate_answer(q, value_text="short")


def test_text_exceeds_max_length_rejected():
    q = make_question(QuestionKind.text, config={"max_length": 10})
    with pytest.raises(ValueError):
        validate_answer(q, value_text="this is way too long for the limit")


def test_boolean_value_ok():
    q = make_question(QuestionKind.boolean)
    validate_answer(q, value_bool=True)
