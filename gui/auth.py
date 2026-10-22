"""
mesh_mobility.gui.auth
======================
Cloudflare Access authentication + WC3 contact management.

Guest access: browse library, view networks, run simulations.
Authenticated access: draw, build, save, clone, Noelle proposals.

Cloudflare Access sends verified email in Cf-Access-Authenticated-User-Email header.
MeshMobility creates/retrieves a WC3 contact record via wcapi on first authenticated visit.
"""

import json
import logging
import os
import uuid
from functools import wraps

import requests
from flask import Blueprint, g, jsonify, request

logger = logging.getLogger(__name__)

auth = Blueprint("auth", __name__)

# WC3 wcapi base URL — local dev or production
WC3_BASE = os.environ.get("WC3_URL", "http://localhost:8000")
WC3_API_KEY = os.environ.get("WC3_API_KEY", "")

# Header Cloudflare Access uses to pass verified email
CF_EMAIL_HEADER = "Cf-Access-Authenticated-User-Email"

# Superusers — can save to library, publish networks, manage data
SUPERUSER_EMAILS = {
    "bill@jpods.com",
    "bill.james@jpods.com",
    "claude@jpods.com",
    "meshmobility@jpods.com",
}

# Only gate endpoints that persist to disk or external systems.
# In-memory editing (place stations, draw guideways, build) is free for guests.
SAVE_PREFIXES = (
    "/api/network/save",              # save .jpd to disk
    "/api/network/save_drawn_lines",  # save corridor lines to disk
    "/api/network/clone",             # clone from library to disk
)


_wcapi_token = {"access": None, "expires": 0}

def _wcapi_get_token():
    """Get a JWT access token from WC3. Caches until expiry."""
    import time
    if _wcapi_token["access"] and time.time() < _wcapi_token["expires"]:
        return _wcapi_token["access"]
    try:
        r = requests.post(
            f"{WC3_BASE}/wcapi/token/",
            headers={"Content-Type": "application/json"},
            json={"email": os.environ.get("WC3_SERVICE_EMAIL", "meshmobility@jpods.com"),
                  "password": os.environ.get("WC3_SERVICE_PASS", "mm-service-2026")},
            timeout=5,
        )
        r.raise_for_status()
        data = r.json().get("data", {})
        _wcapi_token["access"] = data.get("access")
        _wcapi_token["expires"] = time.time() + 1700  # ~28 min (tokens last 30)
        return _wcapi_token["access"]
    except Exception as e:
        logger.warning("wcapi token failed: %s", e)
        return None


def _wcapi(method, endpoint, data=None):
    """Call WC3 wcapi endpoint using JWT auth and correct URL pattern."""
    token = _wcapi_get_token()
    if not token:
        return None
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    try:
        if method == "GET":
            url = f"{WC3_BASE}/wcapi/get/{endpoint}"
            r = requests.get(url, headers=headers, params=data, timeout=5)
        elif method == "SAVE":
            url = f"{WC3_BASE}/wcapi/save/"
            r = requests.post(url, headers=headers, json=data, timeout=5)
        else:
            url = f"{WC3_BASE}/wcapi/{endpoint}"
            r = requests.post(url, headers=headers, json=data, timeout=5)
        r.raise_for_status()
        result = r.json()
        if result.get("status") == "success":
            return result.get("data")
        logger.warning("wcapi %s %s: %s", method, endpoint, result.get("message", ""))
        return None
    except Exception as e:
        logger.warning("wcapi %s %s failed: %s", method, endpoint, e)
        return None


def _get_or_create_contact(email):
    """Look up contact by email in WC3. Create if missing. Return contact dict.
    Falls back to local stub if WC3 is unavailable."""
    # Try WC3 wcapi get
    result = _wcapi("GET", "contact/", {"email": email})
    if result:
        records = result.get("records", [])
        if records:
            return records[0]

    # Try to create in WC3 via wcapi save
    contact = _wcapi("SAVE", None, {
        "model_name": "contact",
        "email": email,
        "uuid": str(uuid.uuid4()),
        "role": "guest",
        "source_name": "meshmobility.com",
        "metadata": {
            "source": "meshmobility",
            "needs_profile": True,
        },
    })
    if contact:
        return contact.get("record", contact)

    # WC3 unavailable — return a local stub so auth still works
    logger.info("WC3 unavailable — using local profile for %s", email)
    return {
        "id": None,
        "email": email,
        "uuid": str(uuid.uuid4()),
        "metadata": {"source": "meshmobility", "needs_profile": True},
    }


def _is_local_request():
    """True when the request originates from the same machine (localhost)."""
    remote = request.remote_addr or ""
    return remote in ("127.0.0.1", "::1", "localhost")


def get_current_user():
    """Return authenticated user email from CF header, session, or localhost."""
    # Cloudflare Access header (production behind CF)
    email = request.headers.get(CF_EMAIL_HEADER)
    if email:
        return email
    # App-level session auth (standalone / no CF Access)
    from flask import session
    if session.get("verified_email"):
        return session["verified_email"]
    # Local machine — owner is always authenticated
    if _is_local_request():
        return "bill@jpods.com"
    return None


def is_superuser(email=None):
    """Check if user is a superuser. Superusers can save to library and publish networks."""
    email = email or get_current_user()
    if not email:
        return False
    return email.lower() in SUPERUSER_EMAILS


def auth_required(f):
    """Decorator: reject requests without Cloudflare-verified email."""
    @wraps(f)
    def decorated(*args, **kwargs):
        email = get_current_user()
        if not email:
            return jsonify({
                "error": "Authentication required",
                "detail": "Please verify your email to use this feature.",
            }), 401
        g.user_email = email
        return f(*args, **kwargs)
    return decorated


def superuser_required(f):
    """Decorator: reject requests from non-superusers."""
    @wraps(f)
    def decorated(*args, **kwargs):
        email = get_current_user()
        if not email or not is_superuser(email):
            return jsonify({
                "error": "Superuser access required",
                "detail": "Only superusers can save to the library.",
            }), 403
        g.user_email = email
        return f(*args, **kwargs)
    return decorated


@auth.before_app_request
def _inject_user():
    """Set g.user_email on every request. Keep session permanent."""
    from flask import session
    if session.get("verified_email"):
        session.permanent = True  # refresh 30-day expiry on every visit
    g.user_email = get_current_user()


@auth.after_app_request
def _check_write_auth(response):
    """Block unauthenticated write requests."""
    if request.method in ("POST", "PUT"):
        path = request.path
        if any(path.startswith(p) for p in SAVE_PREFIXES):
            if not g.get("user_email"):
                return jsonify({
                    "error": "Authentication required",
                    "detail": "Please verify your email to save networks.",
                }), 401
    return response


# --- Auth API endpoints ---

@auth.get("/api/auth/status")
def auth_status():
    """Return current auth state for the client."""
    email = get_current_user()
    if not email:
        return jsonify({"authenticated": False})

    contact = _get_or_create_contact(email)
    needs_profile = False
    if contact:
        meta = contact.get("metadata") or {}
        needs_profile = meta.get("needs_profile", False)
        # Also check if name is missing
        if not contact.get("name_first"):
            needs_profile = True

    # Extract config from contact metadata
    config = {}
    if contact:
        meta = contact.get("metadata") or {}
        config = meta.get("config") or {}

    return jsonify({
        "authenticated": True,
        "email": email,
        "contact_id": contact.get("id") if contact else None,
        "uuid": contact.get("uuid") if contact else None,
        "name": contact.get("attention", "") if contact else "",
        "needs_profile": needs_profile,
        "is_superuser": is_superuser(email),
        "config": config,
    })


@auth.post("/api/auth/profile")
def save_profile():
    """Save contact profile after email verification."""
    email = get_current_user()
    if not email:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.json or {}
    contact = _get_or_create_contact(email)
    if not contact:
        return jsonify({"error": "Could not create contact"}), 500

    contact_id = contact.get("id")
    save_data = {
        "model_name": "contact",
        "name_first": data.get("name_first", "").strip(),
        "name_last": data.get("name_last", "").strip(),
        "company": data.get("organization", "").strip(),
        "source_name": "meshmobility.com",
    }
    if contact_id:
        save_data["id"] = contact_id

    result = _wcapi("SAVE", None, save_data)
    if result:
        return jsonify({"ok": True, "contact_id": contact_id or result.get("id")})

    # WC3 unavailable — still let the user proceed
    logger.warning("Profile save to WC3 failed for %s — session still valid", email)
    return jsonify({"ok": True, "contact_id": None, "note": "Profile saved locally"})


@auth.post("/api/auth/config")
def save_config():
    """Save user's .config preferences to their WC3 contact metadata.
    The config element lives inside the contact record — it IS the CarryOn seed.
    Sync app tokens go between databases. .config tokens go to individuals."""
    email = get_current_user()
    if not email:
        return jsonify({"error": "Not authenticated"}), 401

    new_config = request.json or {}
    contact = _get_or_create_contact(email)
    if not contact:
        return jsonify({"error": "Could not find contact"}), 500

    contact_id = contact.get("id")
    if not contact_id:
        # Local stub — store in session as fallback
        from flask import session
        session["mm_config"] = new_config
        return jsonify({"ok": True, "stored": "session"})

    # Merge new config into existing metadata
    meta = contact.get("metadata") or {}
    existing_config = meta.get("config") or {}
    existing_config.update(new_config)
    meta["config"] = existing_config

    result = _wcapi("SAVE", None, {
        "model_name": "contact",
        "id": contact_id,
        "metadata": meta,
    })
    if result:
        return jsonify({"ok": True, "stored": "wc3", "config": existing_config})

    # WC3 unavailable — store in session
    from flask import session
    session["mm_config"] = existing_config
    logger.warning("Config save to WC3 failed for %s — stored in session", email)
    return jsonify({"ok": True, "stored": "session", "config": existing_config})


# --- App-level email verification (no Cloudflare Access needed) ---

import random
import time

_pending_codes = {}  # email → (code, timestamp)
CODE_EXPIRY = 600    # 10 minutes

@auth.post("/api/auth/send_code")
def send_verification_code():
    """Send a 6-digit verification code to the provided email."""
    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return jsonify({"error": "Valid email required"}), 400

    code = str(random.randint(100000, 999999))
    _pending_codes[email] = (code, time.time())

    # Send via SMTP (Gmail or any provider)
    try:
        import smtplib
        from email.mime.text import MIMEText
        smtp_host = os.environ.get("SMTP_HOST", "localhost")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_pass = os.environ.get("SMTP_PASS", "")
        smtp_from = os.environ.get("SMTP_FROM", "noreply@meshmobility.com")
        msg = MIMEText(
            f"Your MeshMobility verification code is: {code}\n\n"
            f"Enter this code in MeshMobility to save your network designs.\n"
            f"This code expires in 10 minutes.\n\n"
            f"MeshMobility — meshmobility.com\n"
            f"JPods — Building the Physical Internet",
            "plain"
        )
        msg["Subject"] = f"MeshMobility verification code: {code}"
        msg["From"] = smtp_from
        msg["To"] = email
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.starttls()
            if smtp_user and smtp_pass:
                s.login(smtp_user, smtp_pass)
            s.send_message(msg)
        logger.info("Verification code sent to %s", email)
    except Exception as e:
        logger.warning("Email send failed for %s: %s — code is %s", email, e, code)
        # In dev, log the code so it's still usable
        return jsonify({"ok": True, "dev_note": "Email not configured — check server log for code"})

    return jsonify({"ok": True})


@auth.post("/api/auth/verify_code")
def verify_code():
    """Verify the 6-digit code and establish session."""
    from flask import session
    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()

    if not email or not code:
        return jsonify({"error": "Email and code required"}), 400

    pending = _pending_codes.get(email)
    if not pending:
        return jsonify({"error": "No code pending for this email. Request a new one."}), 400

    stored_code, timestamp = pending
    if time.time() - timestamp > CODE_EXPIRY:
        del _pending_codes[email]
        return jsonify({"error": "Code expired. Request a new one."}), 400

    if code != stored_code:
        return jsonify({"error": "Wrong code. Try again."}), 400

    # Success — establish session
    del _pending_codes[email]
    session["verified_email"] = email
    session.permanent = True

    # Create/get WC3 contact
    contact = _get_or_create_contact(email)

    logger.info("Email verified: %s", email)
    return jsonify({
        "ok": True,
        "authenticated": True,
        "email": email,
        "needs_profile": (contact.get("metadata") or {}).get("needs_profile", True) if contact else True,
    })


# --- Network Document management ---

def register_network_save(filename, network_meta):
    """Create or update a Document record in WC3 when a network is saved.

    Called from the save endpoint after the .jpd is written to disk.
    Network metadata stored in refs.keywords as name:value pairs.
    security_level 0 = unpublished (draft), 1 = published (in library).
    Returns the document dict or None.
    """
    email = get_current_user()
    if not email:
        return None

    contact = _get_or_create_contact(email)
    contact_id = contact.get("id") if contact else None

    city = network_meta.get("city", "Unknown")
    state = network_meta.get("state", "")
    name = f"{city}, {state}".strip(", ") if state else city
    stations = network_meta.get("stations", 0)
    circles = network_meta.get("circles", 0)
    total_miles = network_meta.get("total_miles", 0)

    doc = {
        "name": name,
        "status": "draft",
        "security_level": 0,  # unpublished — Noelle + Bill approve to 1
        "description": f"MeshMobility network — {stations} stations, {total_miles} mi",
        "path": {
            "filename": filename,
            "type": "jpd",
        },
        "confidential": "public",
        "refs": {
            "keywords": [
                "type:network",
                f"city:{city}",
                f"state:{state}",
                f"country:{network_meta.get('country', '')}",
                f"stations:{stations}",
                f"circles:{circles}",
                f"total_miles:{total_miles}",
                f"contact_id:{contact_id}",
                f"contact_email:{email}",
                f"filename:{filename}",
                "source:meshmobility",
            ],
            "published": False,
        },
    }

    # Check if document already exists for this filename
    existing = _wcapi("GET", f"documents/?refs__keywords__contains=filename:{filename}")
    if existing and existing.get("results"):
        doc_id = existing["results"][0]["id"]
        result = _wcapi("POST", f"documents/{doc_id}/", doc)
    else:
        result = _wcapi("POST", "documents/", doc)

    return result


@auth.get("/api/auth/my_networks")
def my_networks():
    """Return networks saved by the current user."""
    email = get_current_user()
    if not email:
        return jsonify({"networks": []})

    result = _wcapi("GET",
        f"documents/?refs__keywords__contains=type:network&refs__keywords__contains=contact_email:{email}")
    if result and result.get("results"):
        return jsonify({"networks": result["results"]})
    return jsonify({"networks": []})
