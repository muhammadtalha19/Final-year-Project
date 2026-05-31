from typing import Any, Dict, List, Optional


def build_diagnostics(
    generated_commands: List[Dict[str, Any]],
    provider_messages: List[str],
    action_hint: str = "",
    raw_error_summary: str = "",
    next_steps: Optional[List[str]] = None,
    log_commands: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "generated_commands": generated_commands or [],
        "provider_messages": provider_messages or [],
        "action_hint": action_hint,
        "raw_error_summary": raw_error_summary,
        "next_steps": next_steps or [],
        "log_commands": log_commands or [],
    }
