import ast

from pathlib import Path
from datetime import datetime
from graphlib import TopologicalSorter, CycleError

import logging

logger = logging.getLogger(__name__)

class CMathTranspiler(ast.NodeVisitor):
    """
    Walks a Python expression AST and emits C
    """
    
    # Two arg operations
    BIN_OPS:dict[object, str] = {
        ast.Add: "+",
        ast.Sub: "-",
        ast.Mult: "*",
        ast.Div: "/",
        ast.Mod: "fmod",
        ast.Pow: "pow"
    }
    
    # - or +
    UNARY_OPS:dict[object, str] = {
        ast.UAdd: "+",
        ast.USub: "-"
    }

    # Comparisons
    CMP_OPS:dict[object, str] = {
        ast.Gt: ">", ast.GtE: ">=",
        ast.Lt: "<", ast.LtE: "<=",
        ast.Eq: "==", ast.NotEq: "!="
    }

    # Booleans
    BOOL_OPS:dict[object, str] = {
        ast.And: "&&",
        ast.Or: "||",
    }

    # Whitelist of allowed C math funcs and expected argument counts
    MATH_FUNCS:dict[str,int] = {
        "sin": 1, "cos": 1, "tan": 1, 
        "exp": 1, "log": 1, "log10": 1, "sqrt": 1, "fabs": 1, "abs": 1,
        "ceil": 1, "floor": 1, "round": 1,
        "pow": 2, "fmin": 2, "fmax": 2
    }

    CONSTANTS:dict[str,str] = {
        "pi": "3.14159265",
        "tau": "6.28318531",
        "e": "2.71828182"
    }

    def __init__(self, phys_map: dict[str, int], virt_map: dict[str, int]):
        """Create Transpiler object with the provided maps

        Args:
            phys_map (dict[str, int]): A map of physical strings to their array positions
            virt_map (dict[str, int]): A map of virtual strings to their new array positions
        """
        self.phys_map = phys_map
        self.virt_map = virt_map
        
        # Placeholder for future use
        self.dependencies: set[str] = set()

    def transpile(self, expr_str: str) -> tuple[str, set[str]]:
        """Transpile a string and return the result and its dependencies

        Args:
            expr_str (str): The string to evaluate

        Returns:
            tuple[str, set[str]]: the resulting C string and its dependencies
        """
        
        logger.info(f"Transpiling string \"{expr_str}\"")
        
        try:
            # Reset placeholder
            self.dependencies.clear()
            
            # Parse and translate
            tree = ast.parse(expr_str, mode="eval")
            c_expr = self.visit(tree.body)
            
            return c_expr, set(self.dependencies)
        except ValueError as e:
            logger.error(f"Invalid name: {e}")
        except Exception as e:
            logger.error(f"General exception: {e}")
        
        return "", set()
        

    def visit_Constant(self, node: ast.Constant) -> str:
        """Visit a constant and force any number to a double literal

        Args:
            node (ast.Constant): The node to visit

        Raises:
            ValueError: Raised if a constant is not an int or float

        Returns:
            str: The node's representation
        """

        if isinstance(node.value, (int, float)):
            return repr(float(node.value))
        raise ValueError(f"Unsupported constant: {node.value}")

    def visit_Name(self, node: ast.Name) -> str:
        """Visit a name (const or channel, virt or phys). 
        If the name is virtual, a dependency is created

        Args:
            node (ast.Name): The node to visit

        Raises:
            ValueError: Raised if the node is not found to one of the specified types

        Returns:
            str: the resulting C string
        """
        
        if node.id in self.CONSTANTS:
            return self.CONSTANTS[node.id]
        if node.id in self.phys_map:
            return f"phys[{self.phys_map[node.id]}]"
        if node.id in self.virt_map:
            self.dependencies.add(node.id)
            return f"virt[{self.virt_map[node.id]}]"
        raise ValueError(f"Unknown channel or identifier: '{node.id}'")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> str:
        op_type = type(node.op)
        if op_type not in self.UNARY_OPS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        operand = self.visit(node.operand)
        return f"({self.UNARY_OPS[op_type]}{operand})"

    def visit_BinOp(self, node: ast.BinOp) -> str:
        
        op_type = type(node.op)
        if op_type not in self.BIN_OPS:
            raise ValueError(f"Unsupported binary operator: {op_type.__name__}")
        
        left = self.visit(node.left)
        right = self.visit(node.right)
        op_str = self.BIN_OPS[op_type]

        # Exponents and float modulo translate to C functions
        if op_type in (ast.Pow, ast.Mod):
            return f"{op_str}({left}, {right})"
        
        # Guard against division by zero to prevent NaN/Inf propagation in RT loop
        if op_type is ast.Div:
            
            if isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant):
                
                # Left and right are constants or names, static eval
                return f"{float(left) / float(right)}"
            
            elif isinstance(node.right, ast.Constant):
                
                # Right is constant, eval for divbyzero
                if float(right) != 0:
                    return f"({left}) / ({right})"
                else:
                    raise ZeroDivisionError(f"Denominator statically evaluates to zero: {left} / {right}")
            
            # Guard is necessary
            return f"(({right}) != 0.0 ? ({left}) / ({right}) : 0.0)"

        return f"({left} {op_str} {right})"

    def visit_Call(self, node: ast.Call) -> str:
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only direct function calls are allowed.")
        func_name = node.func.id
        if func_name not in self.MATH_FUNCS:
            raise ValueError(f"Unsupported function: '{func_name}()'")
        
        expected_args = self.MATH_FUNCS[func_name]
        if len(node.args) != expected_args:
            raise ValueError(f"'{func_name}()' expects {expected_args} args, got {len(node.args)}")

        c_func = "fabs" if func_name == "abs" else func_name
        args = ", ".join(self.visit(arg) for arg in node.args)
        return f"{c_func}({args})"

    def visit_Compare(self, node: ast.Compare) -> str:
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise ValueError("Chained comparisons (e.g. a < b < c) are not supported; use 'and'.")
        left = self.visit(node.left)
        op_type = type(node.ops[0])
        if op_type not in self.CMP_OPS:
            raise ValueError(f"Unsupported comparison: {op_type.__name__}")
        right = self.visit(node.comparators[0])
        return f"({left} {self.CMP_OPS[op_type]} {right})"

    def visit_BoolOp(self, node: ast.BoolOp) -> str:
        op_str = self.BOOL_OPS[type(node.op)]
        values = [self.visit(v) for v in node.values]
        return "(" + f" {op_str} ".join(values) + ")"

    def visit_IfExp(self, node: ast.IfExp) -> str:
        # Supports Python inline conditional: "a if t_amb > 100 else b" -> "(cond ? a : b)"
        cond = self.visit(node.test)
        body = self.visit(node.body)
        orelse = self.visit(node.orelse)
        return f"({cond} ? {body} : {orelse})"

    def generic_visit(self, node: ast.AST):
        raise ValueError(f"Disallowed syntax in expression: {type(node).__name__}")


def generate_c_library(phys_channels: list[str], virt_labels: list[str], virt_formulas: list[str], tab_spaces: int=0) -> str:
    phys_map = {name: i for i, name in enumerate(phys_channels)}
    virt_map = {name: i for i, name in enumerate(virt_labels)}

    transpiler = CMathTranspiler(phys_map, virt_map)
    c_statements:dict[str,str] = {}
    c_valid:dict[str,bool] = {}
    graph:dict[str,set[str]] = {}

    for v_name, formula in zip(virt_labels, virt_formulas):
        c_expr, deps = transpiler.transpile(formula)
        c_valid[v_name] = c_expr != ""
        c_statements[v_name] = c_expr if c_expr != "" else "0.0"
        graph[v_name] = deps

    # Topologically sort virtual channels so dependencies are always computed first
    try:
        sorter = TopologicalSorter(graph)
        execution_order = list(sorter.static_order())
    except CycleError as e:
        raise ValueError(f"Circular dependency detected in virtual channels: {e}")

    lines = [
        f"// Generated by main.py ({Path().resolve()}, {datetime.now()})\n",
        "#include <math.h>\n",
        "void evaluate_channels (const double* __restrict__ phys, double* __restrict__ virt) {\n"
    ]
    if len(execution_order) > 0:
        lines.extend([
            f"\t// {v_name} = {virt_formulas[virt_labels.index(v_name)]}"
            f"{"" if c_valid[v_name] else " (INVALID)"}\n"
            f"\tvirt[{virt_map[v_name]}] = {c_statements[v_name]};\n"
            for v_name in execution_order
        ])
    else:
        lines.append("\t// No inputs provided\n")
    lines.extend(["}", "", "// End of generated code"])
    if tab_spaces > 0:
        lines = [line.replace('\t', ' ' * tab_spaces) for line in lines]
    return "\n".join(lines)
