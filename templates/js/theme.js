/**
 * Light / Dark theme management.
 * Persists user choice in localStorage under "ui.theme".
 * Defaults to OS prefers-color-scheme.
 */

(function () {
  const STORAGE_KEY = "ui.theme";

  function getPreferredTheme() {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") {
      return stored;
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(STORAGE_KEY, theme);
    updateToggleIcons(theme);
  }

  function updateToggleIcons(theme) {
    const iconSpan = document.getElementById("themeIcon");
    if (iconSpan) {
      iconSpan.textContent = theme === "dark" ? "☀️" : "🌙";
    }
    const textSpan = document.getElementById("themeText");
    if (textSpan) {
      textSpan.textContent = theme === "dark" ? "Light Mode" : "Dark Mode";
    }
    document.querySelectorAll(".theme-toggle-btn").forEach(function (btn) {
      btn.setAttribute("title", theme === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode");
      const icon = btn.querySelector(".nav-icon, span:first-child");
      if (icon && icon.id !== "themeIcon") {
        icon.textContent = theme === "dark" ? "☀️" : "🌙";
      }
    });
  }

  // Initialize theme on DOM ready
  document.addEventListener("DOMContentLoaded", function () {
    const currentTheme = document.documentElement.getAttribute("data-theme") || getPreferredTheme();
    applyTheme(currentTheme);

    const toggleBtns = document.querySelectorAll("#themeToggleBtn, .theme-toggle-btn");
    toggleBtns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        const active = document.documentElement.getAttribute("data-theme");
        const nextTheme = active === "dark" ? "light" : "dark";
        applyTheme(nextTheme);
      });
    });

    // Listen for OS system theme changes
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function (e) {
      if (!localStorage.getItem(STORAGE_KEY)) {
        applyTheme(e.matches ? "dark" : "light");
      }
    });
  });
})();
