/**
 * auth.js — MeshMobility authentication and contact profile
 *
 * Guest access: browse, view, simulate, download — no login needed.
 * Authenticated: save to server, clone, compete — requires email verification.
 * Flow: enter email → receive code → verify → fill profile → save enabled.
 */

"use strict";

const Auth = (() => {

  let _status = null;  // cached auth status

  async function check() {
    try {
      const r = await fetch("/api/auth/status");
      _status = await r.json();
    } catch (_) {
      _status = { authenticated: false };
    }
    _updateBadge();
    if (_status.authenticated) {
      _loadConfig(_status.config || {});
      // Show library Save button for superusers only
      const saveBtn = document.getElementById("btn-save-library");
      if (saveBtn) saveBtn.style.display = _status.is_superuser ? "" : "none";
      if (_status.needs_profile) {
        showProfileForm();
      }
    } else {
      // Load from localStorage cache even when not authenticated
      _loadConfig({});
    }
    return _status;
  }

  function _updateBadge() {
    const badge = document.getElementById("auth-badge");
    if (!badge) return;
    if (_status && _status.authenticated) {
      const name = _status.name || _status.email;
      badge.textContent = name;
      badge.title = _status.email;
      badge.style.color = "#4c4";
    } else {
      badge.textContent = "Sign In";
      badge.title = "Verify email to save networks to the server";
      badge.style.color = "#fc0";
      badge.style.cursor = "pointer";
    }
  }

  // --- Email verification dialog ---

  function showSignIn() {
    if (_status && _status.authenticated) {
      showProfileForm();
      return;
    }
    const existing = document.getElementById("signin-dialog-backdrop");
    if (existing) { existing.style.display = "flex"; return; }

    const backdrop = document.createElement("div");
    backdrop.id = "signin-dialog-backdrop";
    backdrop.style.cssText = "position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:10000";

    backdrop.innerHTML = `
      <div style="background:#1a1a2e;border:1px solid #444;border-radius:8px;padding:24px;width:380px;max-width:90vw;color:#ccc;font-family:sans-serif">
        <h3 style="margin:0 0 4px;color:#fff">Sign In to MeshMobility</h3>
        <p style="margin:0 0 16px;font-size:12px;color:#999">Enter your email to receive a verification code. No password needed.</p>

        <div id="signin-step-email">
          <label style="font-size:11px;color:#aaa">Email address</label>
          <input id="si-email" type="email" placeholder="you@example.com"
                 style="width:100%;box-sizing:border-box;padding:8px;margin:4px 0 12px;background:#111;border:1px solid #444;color:#eee;border-radius:4px;font-size:14px">
          <button onclick="Auth._sendCode()" style="width:100%;padding:8px;background:#2a6a3a;border:1px solid #4a8a5a;color:#fff;border-radius:4px;cursor:pointer;font-size:14px">Send Verification Code</button>
        </div>

        <div id="signin-step-code" style="display:none">
          <p style="font-size:12px;color:#8c8;margin-bottom:12px" id="si-sent-msg">Code sent!</p>
          <label style="font-size:11px;color:#aaa">6-digit code</label>
          <input id="si-code" type="text" maxlength="6" placeholder="123456"
                 style="width:100%;box-sizing:border-box;padding:8px;margin:4px 0 12px;background:#111;border:1px solid #444;color:#eee;border-radius:4px;font-size:18px;text-align:center;letter-spacing:6px">
          <button onclick="Auth._verifyCode()" style="width:100%;padding:8px;background:#2a6a3a;border:1px solid #4a8a5a;color:#fff;border-radius:4px;cursor:pointer;font-size:14px">Verify</button>
          <p style="font-size:11px;color:#666;margin-top:8px;text-align:center">
            <a href="#" onclick="Auth._sendCode(); return false" style="color:#5cb8ff">Resend code</a>
          </p>
        </div>

        <div id="signin-error" style="color:#f66;font-size:12px;margin-top:10px;display:none"></div>

        <div style="text-align:center;margin-top:14px">
          <a href="#" onclick="Auth._closeSignIn(); return false" style="color:#666;font-size:12px">Cancel</a>
        </div>
        <p style="font-size:10px;color:#555;margin-top:12px;line-height:1.4;text-align:center">
          Your data is never shared. You control it. You can delete your account at any time.
        </p>
      </div>
    `;
    document.body.appendChild(backdrop);
  }

  async function _sendCode() {
    const email = (document.getElementById("si-email")?.value || "").trim();
    if (!email || !email.includes("@")) {
      _showSignInError("Enter a valid email address");
      return;
    }
    _showSignInError("");
    try {
      const r = await fetch("/api/auth/send_code", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ email }),
      });
      const data = await r.json();
      if (data.ok) {
        document.getElementById("signin-step-email").style.display = "none";
        document.getElementById("signin-step-code").style.display = "block";
        const msg = document.getElementById("si-sent-msg");
        if (data.dev_note) {
          msg.textContent = "Code logged on server (email not configured)";
          msg.style.color = "#fc8";
        } else {
          msg.textContent = `Code sent to ${email}`;
        }
      } else {
        _showSignInError(data.error || "Failed to send code");
      }
    } catch (e) {
      _showSignInError("Connection error: " + e.message);
    }
  }

  async function _verifyCode() {
    const email = (document.getElementById("si-email")?.value || "").trim();
    const code = (document.getElementById("si-code")?.value || "").trim();
    if (!code || code.length !== 6) {
      _showSignInError("Enter the 6-digit code");
      return;
    }
    _showSignInError("");
    try {
      const r = await fetch("/api/auth/verify_code", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ email, code }),
      });
      const data = await r.json();
      if (data.ok) {
        _closeSignIn();
        _status = data;
        _updateBadge();
        if (typeof setStatus === "function") setStatus("Signed in as " + email);
        if (typeof App !== "undefined" && App.flash) App.flash("Email verified! You can now save.", 4000);
        if (data.needs_profile) {
          setTimeout(() => showProfileForm(), 500);
        }
      } else {
        _showSignInError(data.error || "Verification failed");
      }
    } catch (e) {
      _showSignInError("Connection error: " + e.message);
    }
  }

  function _showSignInError(msg) {
    const el = document.getElementById("signin-error");
    if (el) {
      el.textContent = msg;
      el.style.display = msg ? "block" : "none";
    }
  }

  function _closeSignIn() {
    const el = document.getElementById("signin-dialog-backdrop");
    if (el) el.style.display = "none";
  }

  // --- Profile form (shown after email verification) ---

  function showProfileForm() {
    const existing = document.getElementById("profile-dialog-backdrop");
    if (existing) { existing.style.display = "flex"; return; }

    const backdrop = document.createElement("div");
    backdrop.id = "profile-dialog-backdrop";
    backdrop.style.cssText = "position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:10000";

    backdrop.innerHTML = `
      <div style="background:#1a1a2e;border:1px solid #444;border-radius:8px;padding:24px;width:400px;max-width:90vw;color:#ccc;font-family:sans-serif">
        <h3 style="margin:0 0 4px;color:#fff">Welcome to MeshMobility</h3>
        <p style="margin:0 0 16px;font-size:12px;color:#999">Tell us a bit about yourself so we can show you relevant networks.</p>

        <label style="font-size:11px;color:#aaa">Email (verified)</label>
        <input id="pf-email" type="text" readonly style="width:100%;box-sizing:border-box;padding:6px 8px;margin:2px 0 10px;background:#111;border:1px solid #333;color:#888;border-radius:4px"
               value="${_status ? _status.email : ''}">

        <div style="display:flex;gap:8px">
          <div style="flex:1">
            <label style="font-size:11px;color:#aaa">First name</label>
            <input id="pf-first" type="text" style="width:100%;box-sizing:border-box;padding:6px 8px;margin:2px 0 10px;background:#111;border:1px solid #444;color:#eee;border-radius:4px">
          </div>
          <div style="flex:1">
            <label style="font-size:11px;color:#aaa">Last name</label>
            <input id="pf-last" type="text" style="width:100%;box-sizing:border-box;padding:6px 8px;margin:2px 0 10px;background:#111;border:1px solid #444;color:#eee;border-radius:4px">
          </div>
        </div>

        <label style="font-size:11px;color:#aaa">Organization <span style="color:#666">(optional — school, company, city dept)</span></label>
        <input id="pf-org" type="text" style="width:100%;box-sizing:border-box;padding:6px 8px;margin:2px 0 10px;background:#111;border:1px solid #444;color:#eee;border-radius:4px">

        <label style="font-size:11px;color:#aaa">City / Region</label>
        <input id="pf-city" type="text" placeholder="e.g. Tulsa, OK" style="width:100%;box-sizing:border-box;padding:6px 8px;margin:2px 0 10px;background:#111;border:1px solid #444;color:#eee;border-radius:4px">

        <label style="font-size:11px;color:#aaa">What are you interested in? <span style="color:#666">(suggestions welcome)</span></label>
        <textarea id="pf-interest" rows="2" style="width:100%;box-sizing:border-box;padding:6px 8px;margin:2px 0 14px;background:#111;border:1px solid #444;color:#eee;border-radius:4px;resize:vertical"></textarea>

        <div style="font-size:10px;color:#777;margin-bottom:14px;line-height:1.4">
          Your data is never shared. You control it. You can delete your account at any time.
        </div>

        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button onclick="Auth.skipProfile()" style="padding:6px 14px;background:#333;border:1px solid #555;color:#aaa;border-radius:4px;cursor:pointer">Skip for now</button>
          <button onclick="Auth.submitProfile()" style="padding:6px 14px;background:#2a6a3a;border:1px solid #4a8a5a;color:#fff;border-radius:4px;cursor:pointer">Save</button>
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);
  }

  async function submitProfile() {
    const data = {
      name_first: (document.getElementById("pf-first")?.value || "").trim(),
      name_last: (document.getElementById("pf-last")?.value || "").trim(),
      organization: (document.getElementById("pf-org")?.value || "").trim(),
      city_region: (document.getElementById("pf-city")?.value || "").trim(),
      interest: (document.getElementById("pf-interest")?.value || "").trim(),
    };

    if (!data.name_first) {
      document.getElementById("pf-first").style.borderColor = "#f44";
      return;
    }

    try {
      const r = await fetch("/api/auth/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      const result = await r.json();
      if (result.ok) {
        _closeProfile();
        _status.needs_profile = false;
        _status.name = `${data.name_first} ${data.name_last}`.trim();
        _updateBadge();
        if (typeof setStatus === "function") setStatus(`Welcome, ${data.name_first}!`);
      } else {
        alert(result.error || "Failed to save profile");
      }
    } catch (e) {
      alert("Connection error: " + e.message);
    }
  }

  function skipProfile() {
    _closeProfile();
  }

  function _closeProfile() {
    const el = document.getElementById("profile-dialog-backdrop");
    if (el) el.style.display = "none";
  }

  function isAuthenticated() {
    return _status && _status.authenticated;
  }

  // --- .config — user preferences stored in their WC3 contact record ---
  // This is the CarryOn seed. Sync app tokens go between databases.
  // .config tokens go to individuals.

  let _config = {};

  function getConfig(key) {
    return key ? _config[key] : _config;
  }

  async function setConfig(key, value) {
    _config[key] = value;
    // Also persist to localStorage as immediate cache
    try { localStorage.setItem("mm_config", JSON.stringify(_config)); } catch(_) {}
    // Save to WC3 contact record (async, best-effort)
    if (isAuthenticated()) {
      try {
        await fetch("/api/auth/config", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(_config),
        });
      } catch(_) {}
    }
  }

  function _loadConfig(serverConfig) {
    // Merge: server config wins over localStorage cache
    try {
      const local = JSON.parse(localStorage.getItem("mm_config") || "{}");
      _config = { ...local, ...serverConfig };
    } catch(_) {
      _config = serverConfig || {};
    }
    // Apply config to app state
    if (_config.last_city && typeof App !== "undefined" && App._lastCity === undefined) {
      App._lastCity = _config.last_city;
    }
    if (_config.overlays && typeof App !== "undefined" && App._configOverlays === undefined) {
      App._configOverlays = _config.overlays;
    }
  }

  function _isLocal() {
    const h = window.location.hostname;
    return h === "localhost" || h === "127.0.0.1" || h === "::1";
  }

  function requireAuth(action) {
    if (isAuthenticated() || _isLocal()) return true;
    // Show sign-in dialog instead of just a message
    showSignIn();
    if (typeof setStatus === "function")
      setStatus("Sign in required to " + (action || "use this feature"));
    return false;
  }

  function getEmail() {
    return _status ? _status.email : null;
  }

  function getStatus() {
    return _status;
  }

  return {
    check, showSignIn, showProfileForm, submitProfile, skipProfile,
    isAuthenticated, requireAuth, getEmail, getStatus,
    getConfig, setConfig,
    _sendCode, _verifyCode, _closeSignIn,
  };
})();

// Check auth on page load
document.addEventListener("DOMContentLoaded", () => Auth.check());
