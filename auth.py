import os
from datetime import datetime
from typing import Any, Dict

from flask import flash, redirect, request, url_for
from flask_login import LoginManager, login_user

try:
    from authlib.integrations.flask_client import OAuth
except ImportError:  # pragma: no cover - requirements install Authlib.
    OAuth = None

from database import db
from models import User


login_manager = LoginManager()
login_manager.login_view = "login"
oauth = OAuth() if OAuth else None
oauth_clients: Dict[str, Any] = {}


PROVIDERS = {
    "github": {
        "label": "GitHub",
        "client_id_env": "GITHUB_CLIENT_ID",
        "client_secret_env": "GITHUB_CLIENT_SECRET",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "access_token_url": "https://github.com/login/oauth/access_token",
        "api_base_url": "https://api.github.com/",
        "client_kwargs": {"scope": "read:user user:email"},
    },
    "google": {
        "label": "Google",
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",
        "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
        "client_kwargs": {"scope": "openid email profile"},
    },
    "microsoft": {
        "label": "Microsoft",
        "client_id_env": "MICROSOFT_CLIENT_ID",
        "client_secret_env": "MICROSOFT_CLIENT_SECRET",
        "server_metadata_url": "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
        "client_kwargs": {"scope": "openid email profile User.Read"},
    },
}


@login_manager.user_loader
def load_user(user_id: str):
    if not str(user_id).isdigit():
        return None
    return db.session.get(User, int(user_id))


def init_auth(app):
    login_manager.init_app(app)
    if oauth:
        oauth.init_app(app)
        register_oauth_clients()


def provider_configured(provider: str) -> bool:
    meta = PROVIDERS[provider]
    return bool(os.getenv(meta["client_id_env"]) and os.getenv(meta["client_secret_env"]))


def oauth_status():
    return [
        {
            "name": name,
            "label": meta["label"],
            "configured": provider_configured(name),
        }
        for name, meta in PROVIDERS.items()
    ]


def register_oauth_clients():
    if not oauth:
        return
    for name, meta in PROVIDERS.items():
        if not provider_configured(name) or name in oauth_clients:
            continue
        kwargs = {
            "name": name,
            "client_id": os.getenv(meta["client_id_env"]),
            "client_secret": os.getenv(meta["client_secret_env"]),
            "client_kwargs": meta["client_kwargs"],
        }
        for key in ["authorize_url", "access_token_url", "api_base_url", "server_metadata_url"]:
            if key in meta:
                kwargs[key] = meta[key]
        oauth.register(**kwargs)
        oauth_clients[name] = oauth.create_client(name)


def oauth_callback_url(provider: str) -> str:
    base = os.getenv("OAUTH_REDIRECT_BASE_URL", request.url_root.rstrip("/")).rstrip("/")
    return f"{base}/auth/{provider}/callback"


def begin_oauth(provider: str):
    if provider not in PROVIDERS:
        flash("Unsupported OAuth provider.")
        return redirect(url_for("login"))
    if not provider_configured(provider):
        flash(f"{PROVIDERS[provider]['label']} login is not configured on this server.")
        return redirect(url_for("login"))
    register_oauth_clients()
    client = oauth_clients.get(provider)
    if not client:
        flash(f"{PROVIDERS[provider]['label']} login is unavailable.")
        return redirect(url_for("login"))
    return client.authorize_redirect(oauth_callback_url(provider))


def complete_oauth(provider: str):
    if provider not in PROVIDERS or not provider_configured(provider):
        raise ValueError("OAuth provider is not configured.")
    register_oauth_clients()
    client = oauth_clients.get(provider)
    if not client:
        raise ValueError("OAuth provider is unavailable.")
    token = client.authorize_access_token()
    profile = fetch_oauth_profile(provider, client, token)
    user = upsert_oauth_user(provider, profile)
    login_user(user)
    return user


def fetch_oauth_profile(provider: str, client, token) -> Dict[str, Any]:
    if provider == "github":
        user = client.get("user").json()
        emails = client.get("user/emails").json()
        primary = next((email for email in emails if email.get("primary")), {})
        return {
            "oauth_id": str(user.get("id")),
            "name": user.get("name") or user.get("login") or "GitHub User",
            "email": primary.get("email") or user.get("email"),
            "email_verified": bool(primary.get("verified")),
            "avatar_url": user.get("avatar_url"),
        }
    if provider == "google":
        info = client.parse_id_token(token)
        return {
            "oauth_id": str(info.get("sub")),
            "name": info.get("name") or info.get("email") or "Google User",
            "email": info.get("email"),
            "email_verified": bool(info.get("email_verified")),
            "avatar_url": info.get("picture"),
        }
    info = client.parse_id_token(token)
    email = info.get("email") or info.get("preferred_username")
    return {
        "oauth_id": str(info.get("sub") or info.get("oid")),
        "name": info.get("name") or email or "Microsoft User",
        "email": email,
        "email_verified": True,
        "avatar_url": None,
    }


def upsert_oauth_user(provider: str, profile: Dict[str, Any]) -> User:
    email = (profile.get("email") or "").strip().lower()
    oauth_id = str(profile.get("oauth_id") or "")
    if not email or not oauth_id:
        raise ValueError("OAuth provider did not return a usable identity.")

    user = User.query.filter_by(auth_provider=provider, oauth_id=oauth_id).first()
    if not user:
        existing = User.query.filter_by(email=email).first()
        if existing:
            if not profile.get("email_verified"):
                raise ValueError("OAuth email must be verified before linking to an existing account.")
            user = existing
            user.auth_provider = user.auth_provider or provider
            user.oauth_id = oauth_id
        else:
            user = User(
                name=profile.get("name") or email.split("@")[0],
                email=email,
                password_hash=None,
                auth_provider=provider,
                oauth_id=oauth_id,
            )
            db.session.add(user)

    user.name = profile.get("name") or user.name
    user.avatar_url = profile.get("avatar_url")
    user.email_verified = bool(profile.get("email_verified"))
    user.last_login_at = datetime.utcnow()
    db.session.commit()
    return user
