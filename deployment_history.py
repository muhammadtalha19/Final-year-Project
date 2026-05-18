import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_deployment_history(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    path = _history_path()
    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8") as handle:
            records = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(records, list):
        return []
    records = list(reversed(records))
    return records[:limit] if limit else records


def add_deployment_record(result: Dict[str, Any]) -> Dict[str, Any]:
    record = _record_from_result(result)
    path = _history_path()
    records = list(reversed(load_deployment_history()))
    records.append(record)
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(records, handle, indent=2)
    temp_path.replace(path)
    return record


def _history_path() -> Path:
    configured = os.getenv("DEPLOYMENT_HISTORY_FILE", "deployments.json")
    path = Path(configured)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent / path


def _record_from_result(result: Dict[str, Any]) -> Dict[str, Any]:
    decision = result.get("decision", {})
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app_name": result.get("app"),
        "selected_provider": decision.get("selected_provider"),
        "execution_provider": decision.get("execution_provider"),
        "status": result.get("status"),
        "public_endpoints": result.get("public_endpoints", []),
        "decision_reason": decision.get("reason"),
        "evaluated_providers": decision.get("evaluated_providers", []),
    }
