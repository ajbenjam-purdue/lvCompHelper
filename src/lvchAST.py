import ast

from pathlib import Path
from datetime import datetime
from graphlib import TopologicalSorter, CycleError
from typing import Callable, Any
from abc import ABC
import math

import logging

logger = logging.getLogger(__name__)

_GENERIC_ARGS = ['x', 'y', 'z', 'a', 'b', 'c']

class Function(ABC):
    """Parent class for functions
    
    A function should accept user-facing arguments on the python side (`args_py`) and manage internal arguments on the C side (`args_tr`) for transient state.
    Arguments for `args_py` will be passed as doubles while those for `args_tr` will be passed as pointers.
    """
    name:str = ""
    args_py:list[str] = []
    args_tr:list[str] = []
    header_dependencies:list[str] = []
    body:str = ""
    docstring:str = ""
    
    def __init__(self) -> None:
        pass
    
    @property
    def body_lines(self) -> list[str]:
        return [x.strip() for x in self.body.split("\n")]
    
    @property
    def fixed_registers(self) -> int:
        """Return the number of fixed regsiters needed for the call"""
        return len(self.args_py)
    
    @property
    def transient_registers(self) -> int:
        """Return the number of transient registers needed"""
        return len(self.args_tr)

    @property
    def signature_py(self) -> str:
        return f"{self.name}({", ".join([f"{i}" for i in self.args_py])})"

    @property
    def signature(self) -> str:
        return f"double {self.name}({", ".join([f"double {i}" for i in self.args_py] + [f"double* {i}" for i in self.args_tr])})"
    
    @property
    def docs(self) -> str:
        return "  " + "\n    ".join([x.strip() for x in self.docstring.strip().split('\n')])
    
    def __str__(self) -> str:
        """Return the C string representation of the function"""
        
        tail:str = "}"
        return "\n\t".join([self.signature + " {"] + self.body_lines) + "\n" + tail

class Dummy(Function):
    name:str = "_dummy"
    args_py:list[str] = []
    args_tr:list[str] = []
    header_dependencies:list[str] = []
    body:str = """
    // Dummy test function to return 1.0
    return 1.0;
    """
    docstring:str = """
    A dummy test function to return 1.0
    Accepts no arguments
    """

class PID(Function):
    name:str = "PID"
    args_py:list[str] = ["pv", "sp", "gain_p", "gain_d", "gain_i"]
    args_tr:list[str] = ["last_pv", "acc_err"]
    header_dependencies:list[str] = ["math.h"]
    body:str = """
    // PID Controller
    // Uses pure gains (not times)
    
    double p_err = sp - pv;       // Proportional error
    double d_err = *last_pv - pv; // Derivative error
    *acc_err += p_err;            // Integral error
    *last_pv = pv;                // Proc var
    
    return gain_p * p_err + gain_d * d_err + gain_i * *acc_err;
    """
    docstring:str = """
    Create a transient PID controller following gain logic.
    pv: process variable
    sp: setpoint
    gain_p: proportional gain
    gain_d: derivative gain
    gain_i: integral gain
    """

class PIDa(Function):
    name:str = "PID"
    args_py:list[str] = ["pv", "sp", "gain_p", "gain_d", "gain_i", "wu_err", "out_lo", "out_hi"]
    args_tr:list[str] = ["last_pv", "acc_err"]
    header_dependencies:list[str] = ["math.h"]
    body:str = """
    // Advanced PID Controller
    // Uses pure gains (not times)
    // Includes an anti-windup maximum proportional error
    // If |pv-sp| is greater than this, integration does not occur
    // Includes low and high limits for the output
    
    double p_err = sp - pv;       // Proportional error
    double d_err = *last_pv - pv; // Derivative error
    if (fabs(p_err) <= wu_err) {
        *acc_err += p_err; // Integral error
    }
    else {
        *acc_err = 0;
    }
    *last_pv = pv; // Proc var
    
    double cmd = gain_p * p_err + gain_d * d_err + gain_i * *acc_err;
    
    // Limit output
    return fmin(out_hi, fmax(cmd, out_lo));
    """
    docstring:str = """
    Create an advanced transient PID controller following gain logic.
    pv: process variable
    sp: setpoint
    gain_p: proportional gain
    gain_d: derivative gain
    gain_i: integral gain
    wu_err: windup error (|pv-sp| must be less than this for integration)
    out_lo: output limit low
    out_hi: output limit high
    """

class Elapsed(Function):
    name:str = "elapsed"
    args_py:list[str] = []
    args_tr:list[str] = ["start_s", "start_ns"]
    header_dependencies:list[str] = ["time.h"]
    body:str = """
    // Elapsed time in seconds
    
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    
    if (*start_s == 0.0) {
        *start_s  = (double)now.tv_sec;
        *start_ns = (double)now.tv_nsec;
        return 0.0;
    }
    
    double total_elapsed = (now.tv_sec - *start_s) + (now.tv_nsec - *start_ns) * 1e-9;
    return total_elapsed;
    """
    docstring:str = """
    Return the elapsed time from the start of the logging in seconds.
    """

class Time_delta(Function):
    name:str = "time_delta"
    args_py:list[str] = []
    args_tr:list[str] = ["prev_s", "prev_ns"]
    header_dependencies:list[str] = ["time.h"]
    body:str = """
    // Elapsed time in seconds
    
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    
    if (*prev_s == 0.0) {
        *prev_s  = (double)now.tv_sec;
        *prev_ns = (double)now.tv_nsec;
        return 1.0;
    }
    
    double elapsed = (now.tv_sec - *prev_s) + (now.tv_nsec - *prev_ns) * 1e-9;
    *prev_s = (double)now.tv_sec;
    *prev_ns = (double)now.tv_nsec;
    
    return elapsed;
    """
    docstring:str = """
    Return the elapsed time from the start of the logging in seconds (or zero on startup).
    """

class _safe_divide(Function):
    name:str = "_safe_divide"
    args_py:list[str] = ["x", "y"]
    args_tr:list[str] = []
    header_dependencies:list[str] = []
    body:str = """
    // Zero-checked division
    
    return y != 0.0 ? x / y : 0.0;
    """
    docstring:str="""
    Return (x / y) or 0.0 if y is zero.
    """

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
    MATH_FUNCS:dict[str, tuple[int, str, list[str], Callable[[Any], float]]] = {
        "sin": (1, "Returns the sine of the input (radians)", ["math.h"], math.sin),
        "cos": (1, "Returns the cosine of the input (radians)", ["math.h"], math.cos),
        "tan": (1, "Returns the tangent of the input (radians)", ["math.h"], math.tan),
        "exp": (1, "Returns Euler's number raised to the input power", ["math.h"], math.exp),
        "log": (1, "Returns the natural logarithm of the input", ["math.h"], math.log),
        "log10": (1, "Returns the base-10 logarithm of the input", ["math.h"], math.log10),
        "sqrt": (1, "Returns the square root of the input", ["math.h"], math.sqrt), 
        "fabs": (1, "Returns the absolute value of the input. Same as abs()", ["math.h"], abs),
        "abs": (1, "Returns the absolute value of the input. Same as fabs()", ["math.h"], abs),
        "ceil": (1, "Returns the ceiling-rounded value of the input", ["math.h"], math.ceil), 
        "floor": (1, "Returns the floor-rounded value of the input", ["math.h"], math.floor), 
        "round": (1, "Returns the half-up-rounded value fo the input", ["math.h"], round),
        "pow": (2, "Returns the x to the y power", ["math.h"], math.pow),  # type: ignore
        "fmin": (2, "Returns the minimum of x and y", ["math.h"], min), 
        "fmax": (2, "Returns the maximum of x and y", ["math.h"], max)
    }

    CONSTANTS:dict[str, str] = {
        "pi": "3.14159265",
        "tau": "6.28318531",
        "e": "2.71828182"
    }

    # Third party C function names and binds
    FUNCTIONS:dict[str, type[Function]] = {
        "dummy" : Dummy,
        "pid" : PID,
        "pida" : PIDa,
        "elapsed" : Elapsed,
        "time_delta" : Time_delta,
        "_safe_divide" : _safe_divide
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
        self.channel_deps: set[str] = set()
        self.function_deps: set[str] = set()
        self.builtin_deps: set[str] = set()
        self.tr_idx: int = 0

    def transpile(self, expr_str: str) -> tuple[str, set[str], str]:
        """Transpile a string and return the result and its dependencies

        Args:
            expr_str (str): The string to evaluate

        Returns:
            tuple[str, set[str]]: the resulting C string and its dependencies
        """
        
        logger.info(f"Transpiling string \"{expr_str}\"")
        
        try:
            # Reset placeholders
            self.channel_deps.clear()
            
            # Parse and translate
            tree = ast.parse(expr_str, mode="eval")
            c_expr = self.visit(tree.body)
            
            return c_expr, set(self.channel_deps), ""
        except Exception as e:
            logger.error(f"Can't transpile \"{expr_str}\": {e}")
            return "", set(), f"{e}"

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
            self.channel_deps.add(node.id)
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
            
            # Add to get math.h
            self.builtin_deps.add("pow")
            
            return f"{op_str}({left}, {right})"
        
        # Guard against division by zero to prevent NaN/Inf propagation in RT loop
        if op_type is ast.Div:
            
            if isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant):
                
                # Left and right are constants or names, static eval
                if float(right) == 0.0:
                    return f"0.0"
                return f"{float(left) / float(right)}"
            
            elif isinstance(node.right, ast.Constant):
                
                # Right is constant, eval for divbyzero
                if float(right) != 0:
                    return f"({left}) * ({1.0 / float(right)})"
                else:
                    raise ZeroDivisionError(f"Denominator statically evaluates to zero: {left} / {right}")
            
            # Guard is necessary
            self.function_deps.add("_safe_divide")
            return f"_safe_divide({left}, {right})"
        elif op_type is ast.Mult:
            
            if isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant):
                
                return f"{float(left) * float(right)}"
            
        return f"({left} {op_str} {right})"

    def visit_Call(self, node: ast.Call) -> str:
        
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only direct function calls are allowed.")
        
        func_name = node.func.id
        args_raw = [str(self.visit(arg)) for arg in node.args]
        
        if func_name in self.MATH_FUNCS:
            expected_args = self.MATH_FUNCS[func_name][0]
            if len(node.args) != expected_args:
                raise ValueError(f"'{func_name}()' expects {expected_args} args, got {len(node.args)}")

            # Check for static expr
            if all([isinstance(arg, ast.Constant) for arg in node.args]):
                
                # Evaluate with python analog
                return f"{self.MATH_FUNCS[func_name][3](*[float(self.visit(x)) for x in node.args])}"
            
            c_func = "fabs" if func_name == "abs" else func_name
            self.builtin_deps.add(func_name)
            
            return f"{c_func}({", ".join(args_raw)})"
        
        elif func_name in self.FUNCTIONS:
            
            func = self.FUNCTIONS[func_name]()
             
            if len(node.args) != func.fixed_registers:
                raise AttributeError(f"Invalid arguments! Expected: {func.signature_py}, received {len(node.args)} arguments: {", ".join(args_raw)}")
            
            args:list[str] = [arg for arg in args_raw]
            
            for _ in range(func.transient_registers):
                args.append(f"&trans[{self.tr_idx}]")
                self.tr_idx += 1
            
            self.function_deps.add(func_name)
            
            return f"{func_name}({", ".join(args)})"
        
        else: 
            
            raise ValueError(f"Unsupported function: '{func_name}()'")

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

def get_functions() -> list[str]:
    transpiler = CMathTranspiler({}, {})
    
    # Get all funcs
    math_funcs = [f"{func_name}({", ".join([_GENERIC_ARGS[i] for i in range(func_args[0])])})\n  {func_args[1]}"
                  for func_name, func_args in transpiler.MATH_FUNCS.items()]
    cust_funcs = [f"{func().signature_py}\n{func().docs}"
                  for func in transpiler.FUNCTIONS.values()]
    
    # Show only ext funcs
    return [x for x in math_funcs + cust_funcs if not x.startswith("_")]

def generate_c_library(phys_channels: list[str], virt_labels: list[str], virt_formulas: list[str], tab_spaces: int=0) -> tuple[str, int]:
    # This CAN return a tuple!
    phys_map = {name: i for i, name in enumerate(phys_channels)}
    virt_map = {name: i for i, name in enumerate(virt_labels)}

    transpiler = CMathTranspiler(phys_map, virt_map)
    c_statements:dict[str,str] = {}
    c_valid:dict[str,tuple[bool, str]] = {}
    graph:dict[str,set[str]] = {}

    for v_name, formula in zip(virt_labels, virt_formulas):
        c_expr, deps, c_err = transpiler.transpile(formula)
        c_valid[v_name] = (c_expr != "", c_err)
        c_statements[v_name] = c_expr if c_expr != "" else "0.0"
        graph[v_name] = deps

    # Topologically sort virtual channels so dependencies are always computed first
    try:
        sorter = TopologicalSorter(graph)
        execution_order = list(sorter.static_order())
    except CycleError as e:
        raise ValueError(f"Circular dependency detected in virtual channels: {e}")

    # Get header deps
    header_deps:set[str] = set()
    for dep in transpiler.builtin_deps:
        for a in transpiler.MATH_FUNCS[dep][2]:
            header_deps.add(a)
    for dep in transpiler.function_deps:
        for a in transpiler.FUNCTIONS[dep]().header_dependencies:
            header_deps.add(a)
    
    lines = [
        f"// Generated by main.py ({Path().resolve()}, {datetime.now()})\n",
        *[f"#include <{x}>" for x in header_deps], ""]

    if transpiler.function_deps:
        lines.extend([
            f"// Generated dependencies\n",
            *[str(transpiler.FUNCTIONS[func]())+"\n" for func in transpiler.function_deps],
            "// End generated dependencies\n"
        ])
    
    # Signature: void evaluate_channels(double* phys, double* virt, double* trans)
        # double* phys: physical channel array (read)
        # double* virt: virtual channel array (write)
        # double* trans: transient data to carry data from previous frames
    lines.append("void evaluate_channels (const double* phys, double* virt, double* trans) {\n")
    if len(execution_order) > 0:
        lines.extend([
            f"\t// {v_name} = {virt_formulas[virt_labels.index(v_name)]}"
            f"{"" if c_valid[v_name][0] else f"\n\t// {c_valid[v_name][1]}"}\n"
            f"\tvirt[{virt_map[v_name]}] = {c_statements[v_name]};\n"
            for v_name in execution_order
        ])
    else:
        lines.append("\t// No inputs provided\n")
    lines.extend(["}", "", "// End of generated code"])
    if tab_spaces > 0:
        lines = [line.replace('\t', ' ' * tab_spaces) for line in lines]
    return ("\n".join(lines), transpiler.tr_idx)
