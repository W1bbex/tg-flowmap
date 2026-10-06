from __future__ import annotations

import ast
from typing import Any, Dict, Optional


def evaluate_ast_node(
    node: ast.AST,
    local_vars: Optional[Dict[str, Any]] = None,
    global_vars: Optional[Dict[str, Any]] = None,
) -> Any:
    """Best-effort extraction of literal values or string representations from AST nodes."""
    if local_vars is None:
        local_vars = {}
    if global_vars is None:
        global_vars = {}

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.BinOp):
        left = evaluate_ast_node(node.left, local_vars, global_vars)
        right = evaluate_ast_node(node.right, local_vars, global_vars)
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
                return evaluate_ast_node(val, local_vars, global_vars)
            return val
        if global_vars and node.id in global_vars:
            val = global_vars[node.id]
            if isinstance(val, list) and val and isinstance(val[0], ast.AST):
                val = val[-1]
            if isinstance(val, ast.AST):
                return evaluate_ast_node(val, local_vars, global_vars)
            return val
        return f"${node.id}"

    if isinstance(node, ast.Attribute):
        return f"${node.attr}"

    if isinstance(node, ast.Call):
        # Support dict.get(key, default) lookup (e.g. ICONS.get("sound"))
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            dict_obj = evaluate_ast_node(node.func.value, local_vars, global_vars)
            if isinstance(dict_obj, dict) and node.args:
                key = evaluate_ast_node(node.args[0], local_vars, global_vars)
                default = None
                if len(node.args) > 1:
                    default = evaluate_ast_node(node.args[1], local_vars, global_vars)
                for kw in node.keywords:
                    if kw.arg == "default":
                        default = evaluate_ast_node(kw.value, local_vars, global_vars)
                return dict_obj.get(key, default)

        # Support dict(other_dict)
        if isinstance(node.func, ast.Name) and node.func.id == "dict" and node.args:
            arg_val = evaluate_ast_node(node.args[0], local_vars, global_vars)
            if isinstance(arg_val, dict):
                return dict(arg_val)

        # Support str(x), int(x), float(x)
        if isinstance(node.func, ast.Name) and node.func.id in ("str", "int", "float") and node.args:
            arg_val = evaluate_ast_node(node.args[0], local_vars, global_vars)
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
                key_val = evaluate_ast_node(k, local_vars, global_vars)
                if key_val is not None:
                    d[str(key_val)] = evaluate_ast_node(v, local_vars, global_vars)
        return d

    if isinstance(node, ast.List):
        return [evaluate_ast_node(elt, local_vars, global_vars) for elt in node.elts]

    return None


# Backward-compatible alias
_ast_to_value = evaluate_ast_node


def extract_module_constants(tree: ast.AST) -> Dict[str, Any]:
    """Collects top-level module constants like CANONICAL_ICONS, EMOJI_BTN_*, etc.
    Supports standard Assign and PEP 526 AnnAssign.
    """
    constants: Dict[str, Any] = {}
    for stmt in getattr(tree, "body", []):
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    val = evaluate_ast_node(stmt.value, {}, constants)
                    if val is not None:
                        constants[target.id] = val
        elif isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name) and stmt.value:
                val = evaluate_ast_node(stmt.value, {}, constants)
                if val is not None:
                    constants[stmt.target.id] = val
    return constants
