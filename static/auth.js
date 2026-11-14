"use strict";

// Loads ClerkJS on demand and hands out session tokens for API calls. The server sends
// tokens back only through the Authorization header, never through cookies.
window.appAuth = (() => {
  let loading = null;

  function loadScript(src, attributes = {}) {
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.crossOrigin = "anonymous";
      for (const [name, value] of Object.entries(attributes)) script.setAttribute(name, value);
      script.addEventListener("load", () => resolve());
      script.addEventListener("error", () => reject(new Error(`Could not load ${src}`)));
      document.head.append(script);
    });
  }

  // Resolves to { enabled, configured, clerk }. enabled is false when the server runs
  // with RAG_AUTH_DISABLED; configured is false when the Clerk keys are missing.
  function load() {
    if (!loading) {
      loading = (async () => {
        const response = await fetch("/auth/config");
        if (!response.ok) throw new Error("Could not load the sign-in settings.");
        const config = await response.json();
        if (!config.enabled) return { enabled: false, configured: true, clerk: null };
        if (!config.configured) return { enabled: true, configured: false, clerk: null };
        const base = `https://${config.frontend_api}/npm`;
        await loadScript(`${base}/@clerk/ui@1/dist/ui.browser.js`);
        await loadScript(`${base}/@clerk/clerk-js@6/dist/clerk.browser.js`, {
          "data-clerk-publishable-key": config.publishable_key,
        });
        await window.Clerk.load({ ui: { ClerkUI: window.__internal_ClerkUICtor } });
        return { enabled: true, configured: true, clerk: window.Clerk };
      })();
      // Let a later call try again after a network failure.
      loading.catch(() => { loading = null; });
    }
    return loading;
  }

  async function authHeaders() {
    const state = await load();
    const token = state.clerk?.session ? await state.clerk.session.getToken() : null;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  return { load, authHeaders };
})();
