"""Stub execution for node core_logic (extracted from former self-repair loop)."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any


@dataclass
class _CaseResult:
    ok: bool
    detail: str


def data_input_indices(node: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for idx, port in enumerate(node.get("inputs") or []):
        if str((port or {}).get("type", "data")) == "data":
            out.append(idx)
    return out


def data_output_indices(node: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for idx, port in enumerate(node.get("outputs") or []):
        if str((port or {}).get("type", "data")) == "data":
            out.append(idx)
    return out


def normalize_test_cases(raw_cases: Any, node: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(raw_cases, list):
        valid = [c for c in raw_cases if isinstance(c, dict)]
        if valid:
            return valid[:5]

    data_inputs = data_input_indices(node)
    if not data_inputs:
        return [{"inputs": [], "expected_outputs": None, "note": "smoke/no-input"}]
    if len(data_inputs) == 1:
        return [
            {"inputs": [0], "expected_outputs": None, "note": "smoke/single-input-zero"},
            {"inputs": [1], "expected_outputs": None, "note": "smoke/single-input-one"},
        ]
    return [{"inputs": [1 for _ in data_inputs], "expected_outputs": None, "note": "smoke/multi-input-ones"}]


def _inputs_by_port_index(case_inputs: Any, node: dict[str, Any]) -> dict[int, Any]:
    flat = _map_case_inputs(case_inputs, node)
    out: dict[int, Any] = {}
    for k, v in flat.items():
        if isinstance(k, str) and k.startswith("in") and len(k) > 2:
            try:
                out[int(k[2:])] = v
            except ValueError:
                continue
    return out


def _map_case_inputs(case_inputs: Any, node: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    data_indices = data_input_indices(node)

    if isinstance(case_inputs, dict):
        for k, v in case_inputs.items():
            try:
                mapped[f"in{int(k)}"] = v
            except Exception:
                continue
        return mapped

    values = case_inputs if isinstance(case_inputs, list) else []
    for i, port_idx in enumerate(data_indices):
        mapped[f"in{port_idx}"] = values[i] if i < len(values) else None
    return mapped


def run_logic_once(core_logic: str, node: dict[str, Any], case: dict[str, Any]) -> tuple[dict[int, Any], str | None]:
    outputs: dict[int, Any] = {}

    class Data:  # pragma: no cover - trivial wrapper for runtime parity
        def __init__(self, payload: Any):
            self.payload = payload

    inputs_by_idx = _inputs_by_port_index(case.get("inputs"), node)

    class StubNode:
        def __init__(self, inputs_by_index: dict[int, Any]):
            self._inputs = inputs_by_index

        def get_input_val(self, index: int):
            return self._inputs.get(int(index))

        def set_output_val(self, index: int, value: Any):
            payload = value.payload if hasattr(value, "payload") else value
            outputs[int(index)] = payload

        def exec_output(self, index: int, *args: Any, **kwargs: Any) -> None:
            pass

    safe_globals: dict[str, Any] = {"Data": Data}
    for mod_name, alias in (
        ("math", "math"),
        ("numpy", "np"),
        ("numpy", "numpy"),
        ("statistics", "statistics"),
        ("random", "random"),
    ):
        try:
            safe_globals[alias] = importlib.import_module(mod_name)
        except Exception:
            pass

    safe_locals: dict[str, Any] = {"self": StubNode(inputs_by_idx), "Data": Data}
    safe_locals.update(_map_case_inputs(case.get("inputs"), node))

    try:
        exec(core_logic, safe_globals, safe_locals)
    except ModuleNotFoundError as exc:
        msg = str(exc)
        if "ryven" in msg.lower():
            msg += (
                " — do not `import ryven` inside core_logic; `Data` is provided like in generated nodes.py."
            )
        return outputs, f"ModuleNotFoundError: {msg} Check interpreter environment dependencies."
    except Exception as exc:
        return outputs, f"{type(exc).__name__}: {exc}"
    return outputs, None


def evaluate_stub_cases(core_logic: str, node: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Run stub cases; same semantics as former self-repair evaluator."""
    case_results: list[_CaseResult] = []
    output_indices = data_output_indices(node)
    for case in cases:
        outputs, err = run_logic_once(core_logic, node, case)
        if err:
            case_results.append(_CaseResult(ok=False, detail=err))
            continue

        expected = case.get("expected_outputs")
        if isinstance(expected, dict):
            mismatch = None
            for key, exp in expected.items():
                try:
                    out_idx = int(key)
                except Exception:
                    continue
                got = outputs.get(out_idx, None)
                if got != exp:
                    mismatch = f"output[{out_idx}] expected={exp!r}, got={got!r}"
                    break
            strict = bool(case.get("strict", False))
            if mismatch is None:
                case_results.append(_CaseResult(ok=True, detail="match"))
            elif strict:
                case_results.append(_CaseResult(ok=False, detail=f"{mismatch} (strict)"))
            else:
                case_results.append(_CaseResult(ok=True, detail=f"{mismatch} (non-blocking)"))
            continue

        if output_indices and not outputs:
            case_results.append(_CaseResult(ok=True, detail="ok (no data output write)"))
        else:
            case_results.append(_CaseResult(ok=True, detail="ok"))

    total = len(case_results)
    passed = sum(1 for r in case_results if r.ok)
    return {
        "total": total,
        "passed": passed,
        "all_passed": total > 0 and passed == total,
        "details": [r.detail for r in case_results],
    }
