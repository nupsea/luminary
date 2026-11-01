"""Every key a chat node returns is declared on ChatState.

The graph drops an undeclared key without an error, so a value a node computes for
the receipt or the done event reads null downstream; the receipt's budget fields
shipped null that way once. This reads each registered node's return statements.
"""

import ast
import inspect
import sys
import textwrap
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.runtime.chat_graph import build_chat_graph
from app.types import ChatState


def _functions(module) -> dict[str, ast.AST]:
    tree = ast.parse(inspect.getsource(module))
    return {
        n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _own_nodes(fn: ast.AST):
    """The function's statements, not those of functions nested inside it."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _call_keys(call: ast.AST, functions: dict[str, ast.AST], seen: set[str]) -> set[str]:
    """Keys returned by a same-module function this expression calls, followed once."""
    call = call.value if isinstance(call, ast.Await) else call
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
        return set()
    callee = call.func.id
    if callee not in functions or callee in seen:
        return set()
    seen.add(callee)
    return _returned_keys(functions[callee], functions, seen)


def _dict_keys(node: ast.Dict, functions: dict[str, ast.AST], seen: set[str]) -> set[str]:
    keys = set()
    for key, value in zip(node.keys, node.values, strict=True):
        if key is None:  # {**helper(), ...}
            keys |= _call_keys(value, functions, seen)
        elif isinstance(key, ast.Constant) and isinstance(key.value, str):
            keys.add(key.value)
    return keys


def _returned_keys(fn: ast.AST, functions: dict[str, ast.AST], seen: set[str]) -> set[str]:
    keys: set[str] = set()
    names: set[str] = set()
    for node in _own_nodes(fn):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        value = node.value.value if isinstance(node.value, ast.Await) else node.value
        if isinstance(value, ast.Dict):
            keys |= _dict_keys(value, functions, seen)
        elif isinstance(value, ast.Name):
            names.add(value.id)
        else:
            keys |= _call_keys(value, functions, seen)
    # A dict built under a name and returned: its literal, `d["k"] = ...`, `d.update({...})`.
    for node in _own_nodes(fn):
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in names:
                    if isinstance(node.value, ast.Dict):
                        keys |= _dict_keys(node.value, functions, seen)
                    else:
                        keys |= _call_keys(node.value, functions, seen)
                elif (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in names
                    and isinstance(target.slice, ast.Constant)
                ):
                    keys.add(target.slice.value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "update"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in names
            and node.args
            and isinstance(node.args[0], ast.Dict)
        ):
            keys |= _dict_keys(node.args[0], functions, seen)
    return keys


def _keys_by_node() -> dict[str, set[str]]:
    by_node = {}
    for name, spec in build_chat_graph().nodes.items():
        fn = getattr(spec.runnable, "afunc", None) or spec.runnable.func
        functions = _functions(sys.modules[fn.__module__])
        by_node[name] = _returned_keys(functions[fn.__name__], functions, {fn.__name__})
    return by_node


def test_every_key_a_chat_node_returns_is_declared():
    declared = set(ChatState.__annotations__)
    undeclared = {
        node: sorted(keys - declared) for node, keys in _keys_by_node().items() if keys - declared
    }
    assert undeclared == {}


def test_the_reader_sees_what_the_nodes_return():
    """Guards the reader: a reader that found no keys would pass the test above vacuously."""
    by_node = _keys_by_node()
    assert {"_llm_prompt", "_passages_sent", "cited_chunks"} <= by_node["synthesize_node"]
    # direct_node returns {**_empty_result(), ...}: found only by following the spread.
    assert {"answer", "cited_chunks", "transparency"} <= by_node["direct_node"]
    assert "chunks" in by_node["search_node"]
    assert "intent" in by_node["classify_node"]


def test_the_graph_drops_an_undeclared_key():
    """Why the check exists: LangGraph neither keeps nor rejects a key outside the schema."""

    class State(TypedDict):
        kept: int

    def node(state):
        return {"kept": 1, "undeclared": 2}

    builder = StateGraph(State)
    builder.add_node("node", node)
    builder.add_edge(START, "node")
    builder.add_edge("node", END)

    assert builder.compile().invoke({"kept": 0}) == {"kept": 1}


def test_the_reader_follows_a_returned_name_and_a_helper():
    source = textwrap.dedent(
        """
        def helper():
            return {"from_helper": 1}

        def base():
            return {"from_spread": 1}

        def node(state):
            out = {"literal": 1}
            out["subscript"] = 2
            out.update({"updated": 3})
            if state:
                return out
            if state is None:
                return {**base(), "beside_spread": 4}
            return helper()
        """
    )
    functions = {n.name: n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)}
    assert _returned_keys(functions["node"], functions, {"node"}) == {
        "literal",
        "subscript",
        "updated",
        "from_spread",
        "beside_spread",
        "from_helper",
    }
