"use strict";

// Store structured state, never rendered HTML or credentials.
const BrowserState = {
  read(name) {
    try {
      const saved = JSON.parse(localStorage.getItem(`stroke-companion:${name}`));
      return saved?.version === 1 && saved.data && typeof saved.data === "object" ? saved.data : null;
    } catch { return null; }
  },
  write(name, data) {
    try {
      localStorage.setItem(`stroke-companion:${name}`, JSON.stringify({ version: 1, data }));
      return true;
    } catch { return false; }
  },
  remove(name) {
    try { localStorage.removeItem(`stroke-companion:${name}`); } catch { /* Storage may be disabled. */ }
  },
};
