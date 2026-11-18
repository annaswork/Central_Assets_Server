/**
 * Sidebar Collapse & Responsiveness Management.
 * Persists desktop collapse state in localStorage under "ui.sidebar_collapsed".
 * Handles mobile drawer toggle and backdrop.
 */

(function () {
  const STORAGE_KEY = "ui.sidebar_collapsed";

  function isCollapsed() {
    return document.documentElement.classList.contains("sidebar-collapsed");
  }

  function setSidebarCollapsed(collapsed) {
    if (collapsed) {
      document.documentElement.classList.add("sidebar-collapsed");
      localStorage.setItem(STORAGE_KEY, "true");
    } else {
      document.documentElement.classList.remove("sidebar-collapsed");
      localStorage.setItem(STORAGE_KEY, "false");
    }
    updateCollapseIcons(collapsed);
  }

  function updateCollapseIcons(collapsed) {
    const collapseBtn = document.getElementById("sidebarCollapseBtn");
    if (collapseBtn) {
      collapseBtn.setAttribute("title", collapsed ? "Expand Sidebar" : "Collapse Sidebar");
      collapseBtn.setAttribute("aria-label", collapsed ? "Expand Sidebar" : "Collapse Sidebar");
    }
  }

  function toggleMobileDrawer() {
    document.documentElement.classList.toggle("sidebar-mobile-open");
  }

  function closeMobileDrawer() {
    document.documentElement.classList.remove("sidebar-mobile-open");
  }

  document.addEventListener("DOMContentLoaded", function () {
    // Sync collapse icon state with existing class
    updateCollapseIcons(isCollapsed());

    // Desktop internal collapse button in sidebar header
    const sidebarCollapseBtn = document.getElementById("sidebarCollapseBtn");
    if (sidebarCollapseBtn) {
      sidebarCollapseBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        setSidebarCollapsed(!isCollapsed());
      });
    }

    // Topbar toggle button (collapses/expands on desktop, opens drawer on mobile)
    const topbarToggleBtn = document.getElementById("topbarSidebarToggleBtn");
    if (topbarToggleBtn) {
      topbarToggleBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        if (window.innerWidth < 600) {
          toggleMobileDrawer();
        } else {
          setSidebarCollapsed(!isCollapsed());
        }
      });
    }

    // Mobile backdrop click to close
    const backdrop = document.getElementById("sidebarBackdrop");
    if (backdrop) {
      backdrop.addEventListener("click", closeMobileDrawer);
    }

    // Close mobile drawer and dropdown on Esc key
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        closeMobileDrawer();
        const menu = document.getElementById("navUserDropdownMenu");
        if (menu) menu.classList.remove("show");
      }
    });

    // Close mobile drawer when clicking a nav-link inside it
    const drawerLinks = document.querySelectorAll(".nav-drawer .nav-link");
    drawerLinks.forEach(function (link) {
      link.addEventListener("click", function () {
        if (window.innerWidth < 600) {
          closeMobileDrawer();
        }
      });
    });

    // Uncollapse sidebar when collapsed and any icon/link in nav-drawer is clicked
    const navDrawer = document.getElementById("navDrawer") || document.querySelector(".nav-drawer");
    if (navDrawer) {
      navDrawer.addEventListener("click", function (e) {
        if (isCollapsed()) {
          if (e.target.closest("#sidebarCollapseBtn")) return;
          setSidebarCollapsed(false);
        }
      });
    }

    // Close dropdown menu when clicking anywhere outside
    document.addEventListener("click", function (e) {
      const menu = document.getElementById("navUserDropdownMenu");
      const row = document.getElementById("navUserRow");
      if (menu && menu.classList.contains("show")) {
        if (row && row.contains(e.target)) return;
        if (!menu.contains(e.target)) {
          menu.classList.remove("show");
        }
      }
    });
  });

  // Upward User Dropdown Menu Toggle
  window.toggleUserDropdown = function (e) {
    if (e) e.stopPropagation();
    const menu = document.getElementById("navUserDropdownMenu");
    if (menu) {
      menu.classList.toggle("show");
    }
  };
})();
