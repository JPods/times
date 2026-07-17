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

# Only gate endpoints that persist to disk or external systems.
# In-memory editing (place stations, draw guideways, build) is free for guests.
SAVE_PREFIXES = (
    "/api/network/save",              # save .jpd to disk
    "/api/network/save_drawn_lines",  # save corridor lines to disk
    "/api/network/clone",             # clone from library to disk
)


def _wcapi(method, endpoint, data=None):
    """Call WC3 wcapi endpoint."""
    url = f"{WC3_BASE}/wcapi/{endpoint}"
    headers = {"Content-Type": "application/json"}
    if WC3_API_KEY:
        headers["Authorization"] = f"Bearer {WC3_API_KEY}"
    try:
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=5)
        else:
            r = requests.post(url, headers=headers, json=data, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("wcapi %s %s failed: %s", method, endpoint, e)
        return None


def _get_or_create_contact(email):
    """Look up contact by email in WC3. Create if missing. Return contact dict."""
    result = _wcapi("GET", f"contacts/?email={email}")
    if result and result.get("results"):
        return result["results"][0]
    # Not found — create minimal contact (user will fill in details)
    contact = _wcapi("POST", "contacts/", {
        "email": email,
        "uuid": str(uuid.uuid4()),
        "role": "guest",
        "metadata": {
            "source": "meshmobility",
            "needs_profile": True,
        },
    })
    return contact


def get_current_user():
    """Return the authenticated user email from Cloudflare header, or None."""
    return request.headers.get(CF_EMAIL_HEADER)


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


@auth.before_app_request
def _inject_user():
    """Set g.user_email on every request if Cloudflare header present."""
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

    return jsonify({
        "authenticated": True,
        "email": email,
        "contact_id": contact.get("id") if contact else None,
        "uuid": contact.get("uuid") if contact else None,
        "name": contact.get("attention", "") if contact else "",
        "needs_profile": needs_profile,
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
    update = {
        "name_first": data.get("name_first", "").strip(),
        "name_last": data.get("name_last", "").strip(),
        "company": data.get("organization", "").strip(),
        "address_full": data.get("city_region", "").strip(),
        "metadata": {
            **(contact.get("metadata") or {}),
            "source": "meshmobility",
            "needs_profile": False,
            "interest": data.get("interest", "").strip(),
            "notify_updates": data.get("notify_updates", False),
        },
    }

    result = _wcapi("POST", f"contacts/{contact_id}/", update)
    if result:
        return jsonify({"ok": True, "contact_id": contact_id})
    return jsonify({"error": "Failed to update profile"}), 500


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
