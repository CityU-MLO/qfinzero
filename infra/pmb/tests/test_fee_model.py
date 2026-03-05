from models.session import FeeModel


def test_fee_model_default_exercise_fee_is_zero():
    fm = FeeModel()
    assert fm.option_exercise_fee == 0.0


def test_fee_model_custom_exercise_fee():
    fm = FeeModel(option_exercise_fee=5.0)
    assert fm.option_exercise_fee == 5.0
