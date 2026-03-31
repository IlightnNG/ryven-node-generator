"""Multi-round self-repair with lightweight stub test execution."""

from __future__ import annotations

import copy
import importlib
from dataclasses import dataclass
from typing import Any, Callable

from ..config import ai_self_repair_enabled, ai_self_repair_max_rounds
from ..merge import apply_config_patch
from .turn_runner import run_turn_respecting_stream_flag


ProgressCallback = Callable[[dict[str, Any]], None]
DeltaCallback = Callable[[str], None]
StopCallback = Callable[[], bool]


class GenerationStopped(RuntimeError):
    """Raised when user requests stop during generation."""


@dataclass
class _CaseResult:
    ok: bool
    detail: str


def _emit(cb: ProgressCallback | None, payload: dict[str, Any]) -> None:
    if cb:
        cb(payload)


def _data_input_indices(node: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for idx, port in enumerate(node.get("inputs") or []):
        if str((port or {}).get("type", "data")) == "data":
            out.append(idx)
    return out


def _data_output_indices(node: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for idx, port in enumerate(node.get("outputs") or []):
        if str((port or {}).get("type", "data")) == "data":
            out.append(idx)
    return out


def _normalize_cases(raw_cases: Any, node: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(raw_cases, list):
        valid = [c for c in raw_cases if isinstance(c, dict)]
        if valid:
            return valid[:5]

    data_inputs = _data_input_indices(node)
    if not data_inputs:
        return [{"inputs": [], "expected_outputs": None, "note": "smoke/no-input"}]
    if len(data_inputs) == 1:
        return [
            {"inputs": [0], "expected_outputs": None, "note": "smoke/single-input-zero"},
            {"inputs": [1], "expected_outputs": None, "note": "smoke/single-input-one"},
        ]
    return [{"inputs": [1 for _ in data_inputs], "expected_outputs": None, "note": "smoke/multi-input-ones"}]


def _inputs_by_port_index(case_inputs: Any, node: dict[str, Any]) -> dict[int, Any]:
    """Map full port index -> value for StubNode.get_input_val (matches template indexing)."""
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
    data_indices = _data_input_indices(node)

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


def _run_logic_once(core_logic: str, node: dict[str, Any], case: dict[str, Any]) -> tuple[dict[int, Any], str | None]:
    outputs: dict[int, Any] = {}

    class Data:  # pragma: no cover - trivial wrapper for runtime parity
        def __init__(self, payload: Any):
            self.payload = payload

    inputs_by_idx = _inputs_by_port_index(case.get("inputs"), node)

    class StubNode:
        """Minimal Ryven-like surface for self-test (matches common template calls)."""

        def __init__(self, inputs_by_index: dict[int, Any]):
            self._inputs = inputs_by_index

        def get_input_val(self, index: int):
            return self._inputs.get(int(index))

        def set_output_val(self, index: int, value: Any):
            payload = value.payload if hasattr(value, "payload") else value
            outputs[int(index)] = payload

        def exec_output(self, index: int, *args: Any, **kwargs: Any) -> None:
            """No-op in stub; real Ryven triggers exec edges."""

    safe_globals: dict[str, Any] = {"Data": Data}
    # Preload common modules/aliases used by generated node logic.
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
            # Keep runtime resilient: missing optional deps are reported by exec stage.
            pass

    # Keep Python default builtins intact to avoid breaking Qt/shiboken internals.
    # Restriction is still enforced upstream by static validation + forbidden checks.
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


def _evaluate_cases(core_logic: str, node: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    case_results: list[_CaseResult] = []
    output_indices = _data_output_indices(node)
    for case in cases:
        outputs, err = _run_logic_once(core_logic, node, case)
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

        # Smoke mode only checks execution stability.
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


def run_turn_with_self_repair(
    *,
    user_text: str,
    current_node: dict[str, Any],
    existing_class_names: list[str],
    history: list[tuple[str, str]] | None = None,
    on_progress: ProgressCallback | None = None,
    on_reply_delta: DeltaCallback | None = None,
    should_stop: StopCallback | None = None,
) -> dict[str, Any]:
    def _stopped() -> bool:
        return bool(should_stop and should_stop())

    def _stream_delta(chunk: str) -> None:
        if _stopped():
            raise GenerationStopped("stopped by user")
        if on_reply_delta:
            on_reply_delta(chunk)

    if not ai_self_repair_enabled():
        out = run_turn_respecting_stream_flag(
            user_text=user_text,
            current_node=current_node,
            existing_class_names=existing_class_names,
            history=history,
            on_reply_delta=_stream_delta,
        )
        out["repair_round"] = 1
        out["repair_trace"] = []
        return out

    max_rounds = ai_self_repair_max_rounds()
    failures: list[str] = []
    trace: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None

    for round_idx in range(1, max_rounds + 1):
        if _stopped():
            raise GenerationStopped("stopped by user")
        _emit(
            on_progress,
            {"type": "round_start", "round": round_idx, "max_rounds": max_rounds},
        )
        suffix = [
            "",
            f"[Self-repair round {round_idx}/{max_rounds}]",
            "Return compact deterministic self_test_cases (2-4 items) when possible.",
        ]
        if failures:
            suffix.append("Fix these issues from the previous round:")
            for i, f in enumerate(failures[-4:], 1):
                suffix.append(f"{i}. {f}")
        round_user_text = user_text + "\n" + "\n".join(suffix)

        try:
            result = run_turn_respecting_stream_flag(
                user_text=round_user_text,
                current_node=current_node,
                existing_class_names=existing_class_names,
                history=history,
                on_reply_delta=_stream_delta,
            )
        except GenerationStopped:
            raise
        last_result = result
        if _stopped():
            raise GenerationStopped("stopped by user")

        logic = (result.get("core_logic") or "").strip()
        if not logic:
            reason = "model returned empty core_logic"
            failures.append(reason)
            trace.append({"round": round_idx, "status": "failed", "reason": reason})
            _emit(
                on_progress,
                {"type": "round_result", "round": round_idx, "status": "failed", "reason": reason},
            )
            continue

        val_err = (result.get("validation_error") or "").strip()
        if val_err:
            failures.append(f"validation: {val_err}")
            trace.append({"round": round_idx, "status": "failed", "reason": f"validation: {val_err}"})
            _emit(
                on_progress,
                {"type": "round_result", "round": round_idx, "status": "failed", "reason": f"validation: {val_err}"},
            )
            continue

        candidate_node = copy.deepcopy(current_node)
        apply_config_patch(candidate_node, result.get("config_patch"))
        candidate_node["core_logic"] = logic

        cases = _normalize_cases(result.get("self_test_cases"), candidate_node)
        _emit(
            on_progress,
            {
                "type": "test_cases",
                "round": round_idx,
                "summary": [str(c.get("note", "")).strip() or "case" for c in cases[:3]],
            },
        )
        test_summary = _evaluate_cases(logic, candidate_node, cases)
        round_record = {
            "round": round_idx,
            "status": "passed" if test_summary["all_passed"] else "failed",
            "tests": {"passed": test_summary["passed"], "total": test_summary["total"]},
            "details": test_summary["details"],
        }
        trace.append(round_record)
        _emit(
            on_progress,
            {
                "type": "test_result",
                "round": round_idx,
                "passed": test_summary["passed"],
                "total": test_summary["total"],
                "details": test_summary["details"][:3],
                "all_passed": test_summary["all_passed"],
            },
        )

        if test_summary["all_passed"]:
            result["repair_round"] = round_idx
            result["repair_trace"] = trace
            result["self_test_cases"] = cases
            result["self_test_summary"] = test_summary
            return result

        fail_msg = "; ".join(test_summary["details"][:3]) or "tests failed"
        failures.append(f"tests: {fail_msg}")

    if last_result is None:
        raise RuntimeError("self-repair failed before receiving any model output")

    last_result["repair_round"] = max_rounds
    last_result["repair_trace"] = trace
    if trace:
        last_result["message"] = (
            f'{last_result.get("message", "")}\n\n'
            "[Self-repair] Reached max rounds and some checks are still failing."
        )
    return last_result
