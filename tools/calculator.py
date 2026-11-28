import ast
import math
import operator
from typing import Union

from tools.base import BaseTool


class CalculatorTool(BaseTool):
    cost_per_call = 0.0
    side_effects = False
    idempotent = True
    name = "calculator"
    description = "Evaluate a mathematical expression safely."
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The mathematical expression to evaluate."
            }
        },
        "required": ["expression"]
    }
    MAX_EXPRESSION_LENGTH = 200
    MAX_ABS_NUMBER = 1e12
    MAX_POWER_EXPONENT = 100
    MAX_ABS_RESULT = 1e100

    def run(self, **kwargs) -> str:
        expression = kwargs.get("expression", "")
        if not expression:
            return "Error: 'expression' is required."

        try:
            result = self._safe_eval(expression)
            return str(result)
        except ZeroDivisionError:
            return "Error: division by zero."
        except Exception as e:
            return f"Error: invalid expression. {str(e)}"

    def _validate_number(self, value, max_abs: float) -> Union[int, float]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("Only int and float are allowed.")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Non-finite numbers (inf / NaN) are not allowed.")
        if abs(value) > max_abs:
            raise ValueError(f"Number exceeds limit (|value| ≤ {max_abs:.0e}).")
        return value

    def _validate_power(self, base: Union[int, float], exponent: Union[int, float]) -> None:
        if abs(exponent) > self.MAX_POWER_EXPONENT:
            raise ValueError(f"Exponent too large (|exp| ≤ {self.MAX_POWER_EXPONENT}).")

        if base < 0 and isinstance(exponent, float) and not exponent.is_integer():
            raise ValueError("Fractional powers of negative numbers are not supported.")

        if base != 0 and exponent > 0:
            projected_digits = abs(exponent) * math.log10(abs(base))
            if projected_digits > math.log10(self.MAX_ABS_RESULT):
                raise ValueError(f"Result would exceed limit (|result| ≤ {self.MAX_ABS_RESULT:.0e}).")

    def _safe_eval(self, expression: str) -> Union[int, float]:
        if len(expression) > self.MAX_EXPRESSION_LENGTH:
            raise ValueError(f"Expression too long (max {self.MAX_EXPRESSION_LENGTH} characters).")

        allowed_operators = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.USub: operator.neg,
            ast.Mod: operator.mod,
        }

        def eval_node(node):
            if isinstance(node, ast.Constant):
                return self._validate_number(node.value, self.MAX_ABS_NUMBER)

            elif isinstance(node, ast.BinOp):
                left = eval_node(node.left)
                right = eval_node(node.right)
                op_type = type(node.op)
                if op_type not in allowed_operators:
                    raise TypeError(f"Operator {op_type} is not allowed.")
                if op_type is ast.Pow:
                    self._validate_power(left, right)
                result = allowed_operators[op_type](left, right)
                return self._validate_number(result, self.MAX_ABS_RESULT)

            elif isinstance(node, ast.UnaryOp):
                operand = eval_node(node.operand)
                op_type = type(node.op)
                if op_type not in allowed_operators:
                    raise TypeError(f"Unary operator {op_type} is not allowed.")
                result = allowed_operators[op_type](operand)
                return self._validate_number(result, self.MAX_ABS_RESULT)

            else:
                raise TypeError("Unsupported expression.")

        tree = ast.parse(expression, mode="eval")
        return eval_node(tree.body)