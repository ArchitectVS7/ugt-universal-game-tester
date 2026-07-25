import ast
import operator

# Arithmetic operators for reward formulas
OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

# Comparison operators for feature map assertions
COMPARATORS = {
    ast.Eq:    operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt:    operator.lt,
    ast.LtE:   operator.le,
    ast.Gt:    operator.gt,
    ast.GtE:   operator.ge,
}

class SafeEvaluator:
    def __init__(self, formula_string, strict=False):
        """
        strict=False (default): missing state keys evaluate to 0. Used by reward
        formulas, where partial state is tolerable.
        strict=True: missing state keys raise KeyError. Used by feature-map
        preconditions and assertions, so a bad state path fails loudly instead of
        passing vacuously (O2: no vacuous passes).
        """
        self.formula_string = formula_string
        self.strict = strict
        try:
            self.node = ast.parse(formula_string, mode='eval').body
        except SyntaxError as e:
            raise ValueError(f"Invalid formula syntax: '{formula_string}' - {e}")

    def evaluate(self, state_dict, extra_context=None):
        """
        Evaluate the formula against a given state dictionary.
        Supports variables in the form of 'state.credits' or 'state["credits"]' by nested dict lookup.

        extra_context: optional dict of additional top-level variables (e.g. {"before": before_state}).
        Reward formula callers omit extra_context; assertion evaluators pass {"before": before_state}.
        """
        context = {"state": state_dict}
        if extra_context:
            context.update(extra_context)
        return self._eval(self.node, context)

    def _eval(self, node, context):
        if isinstance(node, ast.Constant):  # Python >= 3.8
            return node.value
        elif hasattr(ast, "Num") and isinstance(node, getattr(ast, "Num")):  # Python < 3.8
            return node.n
        elif isinstance(node, ast.BinOp):
            left = self._eval(node.left, context)
            right = self._eval(node.right, context)
            op_type = type(node.op)
            if op_type not in OPERATORS:
                raise TypeError(f"Unsupported binary operator: {op_type.__name__}")
            return OPERATORS[op_type](left, right)
        elif isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if isinstance(node.op, ast.Not):
                return not self._eval(node.operand, context)
            operand = self._eval(node.operand, context)
            if op_type not in OPERATORS:
                raise TypeError(f"Unsupported unary operator: {op_type.__name__}")
            return OPERATORS[op_type](operand)
        elif isinstance(node, ast.Compare):
            left = self._eval(node.left, context)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval(comparator, context)
                op_type = type(op)
                if op_type not in COMPARATORS:
                    raise TypeError(f"Unsupported comparison operator: {op_type.__name__}")
                if not COMPARATORS[op_type](left, right):
                    return False
                left = right
            return True
        elif isinstance(node, ast.BoolOp):
            values = [self._eval(v, context) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            return any(values)
        elif isinstance(node, ast.Name):
            if node.id in context:
                return context[node.id]
            raise NameError(f"Undefined variable in reward formula: '{node.id}'")
        elif isinstance(node, ast.Attribute):
            # Evaluate attribute lookups, e.g., state.credits
            value = self._eval(node.value, context)
            if isinstance(value, dict):
                if node.attr in value:
                    return value[node.attr]
                if self.strict:
                    raise KeyError(
                        f"State key '{node.attr}' not found in state dict "
                        f"(available: {list(value.keys())}). "
                        f"Check your bridge returns this field."
                    )
                # Default to 0 if a nested state key is missing
                return 0
            raise TypeError(f"Cannot lookup attribute '{node.attr}' on non-dictionary: {type(value)}")
        elif isinstance(node, ast.Subscript):
            # Support brackets lookups, e.g., state['credits']
            value = self._eval(node.value, context)
            index = self._eval(node.slice, context)
            if isinstance(value, dict):
                if index in value:
                    return value[index]
                if self.strict:
                    raise KeyError(
                        f"State key '{index}' not found in state dict "
                        f"(available: {list(value.keys())}). "
                        f"Check your bridge returns this field."
                    )
                return 0
            raise TypeError(f"Cannot index non-dictionary: {type(value)}")
        elif isinstance(node, ast.Call):
            # Support safe built-in functions: min, max, abs
            SAFE_FUNCS = {"min": min, "max": max, "abs": abs}
            if isinstance(node.func, ast.Name) and node.func.id in SAFE_FUNCS:
                args = [self._eval(arg, context) for arg in node.args]
                return SAFE_FUNCS[node.func.id](*args)
            func_name = getattr(node.func, 'id', '?')
            raise NameError(f"Unsupported function in reward formula: '{func_name}'")
        else:
            raise TypeError(f"Unsupported syntax structure in reward formula: {type(node).__name__}")

def evaluate_reward_formula(formula, state_dict, extra_context=None):
    """Evaluate a reward formula. Pass extra_context={"before": prev_state} for delta formulas."""
    evaluator = SafeEvaluator(formula)
    return evaluator.evaluate(state_dict, extra_context=extra_context)
