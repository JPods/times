/**
 * auth.js — MeshMobility authentication and contact profile
 *
 * Guest access: browse, view, simulate — no login needed.
 * Authenticated: draw, build, save — requires Cloudflare email verification.
 * On first authenticated visit, shows profile form to collect contact info.
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
    if (_status.authenticated && _status.needs_profile) {
      showProfileForm();
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
      badge.textContent = "Guest";
      badge.title = "Browsing as guest — verify email to edit";
      badge.style.color = "#fc0";
    }
  }

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
          We do not knowingly collect age data.
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

  function requireAuth(action) {
    if (isAuthenticated()) return true;
    if (typeof setStatus === "function")
      setStatus("Sign in required to " + (action || "use this feature"));
    if (typeof App !== "undefined" && App.flash)
      App.flash("Please verify your email to " + (action || "use this feature"), 5000);
    return false;
  }

  function getEmail() {
    return _status ? _status.email : null;
  }

  function getStatus() {
    return _status;
  }

  return { check, showProfileForm, submitProfile, skipProfile, isAuthenticated, requireAuth, getEmail, getStatus };
})();

// Check auth on page load
document.addEventListener("DOMContentLoaded", () => Auth.check());
