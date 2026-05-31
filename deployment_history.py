import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4


def load_deployment_history(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    records = list(reversed(_read_records()))
    return records[:limit] if limit else records


def add_deployment_record(result: Dict[str, Any]) -> Dict[str, Any]:
    record = _record_from_result(result)
    records = _read_records()
    records.append(record)
    _write_records(records)
    return record


def get_deployment_record(deployment_id: str) -> Optional[Dict[str, Any]]:
    return next((record for record in _read_records() if record.get("id") == deployment_id), None)


def update_deployment_record(deployment_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    records = _read_records()
    for record in records:
        if record.get("id") == deployment_id:
            record.update(updates)
            _write_records(records)
            return record
    return None


def _history_path() -> Path:
    configured = os.getenv("DEPLOYMENT_HISTORY_FILE", "deployments.json")
    path = Path(configured)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent / path


def _read_records() -> List[Dict[str, Any]]:
    path = _history_path()
    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8") as handle:
            records = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return []

    return records if isinstance(records, list) else []


def _write_records(records: List[Dict[str, Any]]) -> None:
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(records, handle, indent=2)
    temp_path.replace(path)


def _record_from_result(result: Dict[str, Any]) -> Dict[str, Any]:
    decision = result.get("decision", {})
    deployment = result.get("deployment", {})
    return {
        "id": uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app_name": result.get("app"),
        "app_type": result.get("app_type"),
        "image": result.get("image"),
        "selected_provider": decision.get("selected_provider"),
        "execution_provider": decision.get("execution_provider"),
        "status": result.get("status"),
        "deployment_mode": result.get("deployment_mode"),
        "instance_id": deployment.get("instance_id"),
        "app_names": deployment.get("app_names", []),
        "service_names": deployment.get("service_names", []),
        "deployment": deployment,
        "generated_commands": result.get("generated_commands", []),
        "public_endpoints": result.get("public_endpoints", []),
        "health_check": result.get("health_check", {}),
        "provider_readiness": result.get("provider_readiness", {}),
        "docker_image_validation": result.get("docker_image_validation", {}),
        "diagnostics": result.get("diagnostics", {}),
        "cleanup_result": result.get("cleanup_result", {}),
        "decision_reason": decision.get("reason"),
        "evaluated_providers": decision.get("evaluated_providers", []),
    }
