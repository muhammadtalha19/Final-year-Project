import json
import os
from typing import Any, Dict

from cryptography.fernet import Fernet


SENSITIVE_KEYS = {
    "AWS_SECRET_ACCESS_KEY",
    "AZURE_CLIENT_SECRET",
    "GCP_SERVICE_ACCOUNT_JSON",
    "private_key",
    "client_secret",
    "access_token",
    "refresh_token",
}


def is_encryption_configured() -> bool:
    return bool(os.getenv("CREDENTIAL_ENCRYPTION_KEY"))


def encrypt_credentials(credentials: Dict[str, Any]) -> str:
    fernet = _fernet()
    payload = json.dumps(credentials or {}, sort_keys=True).encode("utf-8")
    return fernet.encrypt(payload).decode("utf-8")


def decrypt_credentials(encrypted: str) -> Dict[str, Any]:
    if not encrypted:
        return {}
    fernet = _fernet()
    payload = fernet.decrypt(encrypted.encode("utf-8"))
    data = json.loads(payload.decode("utf-8"))
    return data if isinstance(data, dict) else {}


def mask_secret(value: str) -> str:
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"{value[:2]}{'*' * max(len(value) - 4, 4)}{value[-2:]}"


def _fernet() -> Fernet:
    key = os.getenv("CREDENTIAL_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("Credential encryption key is not configured.")
    return Fernet(key.encode("utf-8"))
