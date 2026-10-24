from __future__ import annotations

import ast
from typing import Any, Dict, Optional


def evaluate_ast_node(
    node: ast.AST,
    local_vars: Optional[Dict[str, Any]] = None,
    global_vars: Optional[Dict[str, Any]] = None,
    depth: int = 0,
    max_depth: int = 20,
) -> Any:
    """Best-effort extraction of literal values or string representations from AST nodes."""
    if depth > max_depth or node is None:
        return None

    if local_vars is None:
        local_vars = {}
    if global_vars is None:
        global_vars = {}

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.UnaryOp):
        val = evaluate_ast_node(node.operand, local_vars, global_vars, depth + 1, max_depth)
        if isinstance(node.op, ast.USub) and isinstance(val, (int, float)):
            return -val
        if isinstance(node.op, ast.UAdd) and isinstance(val, (int, float)):
            return +val
        return val

    if isinstance(node, ast.BinOp):
        left = evaluate_ast_node(node.left, local_vars, global_vars, depth + 1, max_depth)
        right = evaluate_ast_node(node.right, local_vars, global_vars, depth + 1, max_depth)
        if isinstance(node.op, ast.Mult) and isinstance(left, str) and isinstance(right, int):
            return left * right
        if isinstance(node.op, ast.Add) and isinstance(left, str) and isinstance(right, str):
            return left + right

    if isinstance(node, ast.JoinedStr):
        parts = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                parts.append(str(part.value))
            elif isinstance(part, ast.FormattedValue):
                var_name = getattr(part.value, "id", None) or getattr(part.value, "attr", "*")
                parts.append(f"{{{var_name}}}")
            else:
                parts.append("*")
        return "".join(parts)

    if isinstance(node, ast.Name):
        if local_vars and node.id in local_vars:
            val = local_vars[node.id]
            # Only unwrap if variable was tracked across assignments as a list of AST nodes
            if isinstance(val, list) and val and isinstance(val[0], ast.AST):
                val = val[-1]
            if isinstance(val, ast.AST):
                return evaluate_ast_node(val, local_vars, global_vars, depth + 1, max_depth)
            return val
        if global_vars and node.id in global_vars:
            val = global_vars[node.id]
            if isinstance(val, list) and val and isinstance(val[0], ast.AST):
                val = val[-1]
            if isinstance(val, ast.AST):
                return evaluate_ast_node(val, local_vars, global_vars, depth + 1, max_depth)
            return val
        return f"${node.id}"

    if isinstance(node, ast.Attribute):
        parent_val = evaluate_ast_node(node.value, local_vars, global_vars, depth + 1, max_depth)
        if parent_val and isinstance(parent_val, str) and parent_val.startswith("$"):
            return f"{parent_val}.{node.attr}"
        return f"${node.attr}"

    if isinstance(node, ast.Call):
        # Support dict.get(key, default) lookup (e.g. ICONS.get("sound"))
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            dict_obj = evaluate_ast_node(node.func.value, local_vars, global_vars, depth + 1, max_depth)
            if isinstance(dict_obj, dict) and node.args:
                key = evaluate_ast_node(node.args[0], local_vars, global_vars, depth + 1, max_depth)
                default = None
                if len(node.args) > 1:
                    default = evaluate_ast_node(node.args[1], local_vars, global_vars, depth + 1, max_depth)
                for kw in node.keywords:
                    if kw.arg == "default":
                        default = evaluate_ast_node(kw.value, local_vars, global_vars, depth + 1, max_depth)
                return dict_obj.get(key, default)

        # Support dict(other_dict)
        if isinstance(node.func, ast.Name) and node.func.id == "dict" and node.args:
            arg_val = evaluate_ast_node(node.args[0], local_vars, global_vars, depth + 1, max_depth)
            if isinstance(arg_val, dict):
                return dict(arg_val)

        # Support str(x), int(x), float(x)
        if isinstance(node.func, ast.Name) and node.func.id in ("str", "int", "float") and node.args:
            arg_val = evaluate_ast_node(node.args[0], local_vars, global_vars, depth + 1, max_depth)
            if arg_val is not None and not str(arg_val).startswith("$"):
                if node.func.id == "int":
                    try:
                        return int(arg_val)
                    except (ValueError, TypeError):
                        pass
                elif node.func.id == "float":
                    try:
                        return float(arg_val)
                    except (ValueError, TypeError):
                        pass
                return str(arg_val)
            arg_id = getattr(node.args[0], "id", "") or getattr(node.args[0], "attr", "")
            return f"{{{arg_id}}}" if arg_id else "N"

        return None

    if isinstance(node, ast.Dict):
        d = {}
        for k, v in zip(node.keys, node.values):
            if k is not None:
                key_val = evaluate_ast_node(k, local_vars, global_vars, depth + 1, max_depth)
                if key_val is not None:
                    d[str(key_val)] = evaluate_ast_node(v, local_vars, global_vars, depth + 1, max_depth)
        return d

    if isinstance(node, ast.List):
        return [evaluate_ast_node(elt, local_vars, global_vars, depth + 1, max_depth) for elt in node.elts]

    if isinstance(node, ast.Tuple):
        return tuple(evaluate_ast_node(elt, local_vars, global_vars, depth + 1, max_depth) for elt in node.elts)

    if isinstance(node, ast.Set):
        return set(evaluate_ast_node(elt, local_vars, global_vars, depth + 1, max_depth) for elt in node.elts)

    if isinstance(node, ast.Subscript):
        val = evaluate_ast_node(node.value, local_vars, global_vars, depth + 1, max_depth)
        slice_node = node.slice
        if hasattr(ast, "Index") and isinstance(slice_node, ast.Index):
            slice_node = slice_node.value
        key = evaluate_ast_node(slice_node, local_vars, global_vars, depth + 1, max_depth)

        if isinstance(val, dict):
            if key in val:
                return val[key]
            if str(key) in val:
                return val[str(key)]
        elif isinstance(val, (list, tuple)) and isinstance(key, int):
            try:
                return val[key]
            except IndexError:
                return None
        elif isinstance(val, str) and val.startswith("$"):
            return f"{val}[{key}]"
        return None

    return None


def _ast_to_value(
    node: ast.AST,
    local_vars: Optional[Dict[str, Any]] = None,
    global_vars: Optional[Dict[str, Any]] = None,
) -> Any:
    """Helper alias for evaluate_ast_node."""
    return evaluate_ast_node(node, local_vars, global_vars)


def extract_module_constants(tree: ast.AST) -> Dict[str, Any]:
    """Extracts top-level constants (UPPERCASE or PascalCase) from module AST."""
    constants: Dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            val = evaluate_ast_node(node.value, global_vars=constants)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = val
        elif isinstance(node, ast.AnnAssign):
            if node.value and isinstance(node.target, ast.Name):
                val = evaluate_ast_node(node.value, global_vars=constants)
                constants[node.target.id] = val
    return constants
