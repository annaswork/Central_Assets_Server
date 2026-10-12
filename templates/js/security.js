/**
 * Security & Anti-Inspection Module
 * Disables context menu (right-click) and developer inspection keyboard shortcuts.
 */
(function() {
  'use strict';

  // 1. Prevent Right-Click Context Menu (Inspect, View Page Source)
  document.addEventListener('contextmenu', function(e) {
    e.preventDefault();
    e.stopPropagation();
    return false;
  }, true);

  // 2. Prevent Keyboard Inspection Shortcuts
  window.addEventListener('keydown', function(e) {
    var key = e.key || '';
    var keyCode = e.keyCode || e.which || 0;
    var isCtrl = Boolean(e.ctrlKey || e.metaKey); // Ctrl (Windows/Linux) or Cmd (macOS)
    var isShift = Boolean(e.shiftKey);
    var isAlt = Boolean(e.altKey);
    var lowerKey = key.toLowerCase();

    // F12 (DevTools toggle)
    if (key === 'F12' || keyCode === 123) {
      e.preventDefault();
      e.stopPropagation();
      return false;
    }

    // Ctrl + Shift + I (Inspect Elements)
    // Ctrl + Shift + J (Developer Console)
    // Ctrl + Shift + C (Inspect Element Picker)
    // Ctrl + Shift + K (Firefox Web Console)
    // Ctrl + Shift + E (Firefox Network Monitor)
    if (isCtrl && isShift) {
      if (
        lowerKey === 'i' || lowerKey === 'j' || lowerKey === 'c' ||
        lowerKey === 'k' || lowerKey === 'e' ||
        keyCode === 73 || keyCode === 74 || keyCode === 67 ||
        keyCode === 75 || keyCode === 69
      ) {
        e.preventDefault();
        e.stopPropagation();
        return false;
      }
    }

    // macOS Shortcuts: Cmd + Option + I / J / C / U
    if (isCtrl && isAlt) {
      if (
        lowerKey === 'i' || lowerKey === 'j' || lowerKey === 'c' || lowerKey === 'u' ||
        keyCode === 73 || keyCode === 74 || keyCode === 67 || keyCode === 85
      ) {
        e.preventDefault();
        e.stopPropagation();
        return false;
      }
    }

    // Ctrl + U (View Page Source)
    if (isCtrl && (lowerKey === 'u' || keyCode === 85)) {
      e.preventDefault();
      e.stopPropagation();
      return false;
    }

    // Ctrl + S (Save Page As HTML)
    if (isCtrl && !isShift && (lowerKey === 's' || keyCode === 83)) {
      e.preventDefault();
      e.stopPropagation();
      return false;
    }
  }, true);

  // 3. Prevent dragging sensitive elements (e.g. images / anchors) to outside inspection tools
  document.addEventListener('dragstart', function(e) {
    var target = e.target;
    var tag = (target && target.tagName ? target.tagName.toLowerCase() : '');
    if (tag === 'img' || tag === 'a' || tag === 'svg') {
      e.preventDefault();
    }
  }, true);

  // 4. Anti-Debugging Pause (triggers debugger halt if DevTools is opened via browser menus)
  setInterval(function() {
    (function() {
      Function('debugger')();
    })();
  }, 1000);
})();
