from tools.calculator import CalculatorTool


def test_calculator_evaluates_basic_expression():
    assert CalculatorTool().run(expression="2 + 3 * 4") == "14"


def test_calculator_rejects_function_calls():
    assert "Error" in CalculatorTool().run(expression="__import__('os').system('ls')")


def test_calculator_rejects_division_by_zero():
    result = CalculatorTool().run(expression="1 / 0")
    assert "division by zero" in result.lower()


def test_calculator_rejects_non_finite_result():
    # overflow → inf → caught by number validator
    result = CalculatorTool().run(expression="10 ** 400")
    assert "Error" in result


def test_calculator_rejects_fractional_power_of_negative():
    result = CalculatorTool().run(expression="(-2) ** 0.5")
    assert "Error" in result


def test_calculator_rejects_oversized_exponent():
    result = CalculatorTool().run(expression="2 ** 10000")
    assert "Error" in result


def test_calculator_rejects_oversized_expression():
    expr = "1" + (" + 1" * 200)
    result = CalculatorTool().run(expression=expr)
    assert "Error" in result


def test_calculator_rejects_empty_expression():
    assert "Error" in CalculatorTool().run(expression="")


def test_calculator_supports_modulo():
    assert CalculatorTool().run(expression="10 % 3") == "1"


def test_calculator_supports_unary_minus():
    assert CalculatorTool().run(expression="-(3 + 4)") == "-7"


def test_calculator_rejects_unknown_operator():
    # bitwise & is not in the allowed operator set
    assert "Error" in CalculatorTool().run(expression="5 & 3")


def test_calculator_rejects_nan_input():
    # NaN literals are not parseable as valid floats by ast.literal_eval
    assert "Error" in CalculatorTool().run(expression="float('nan')")
