/**
 * Table utilities: master checkbox, selection counting, and bulk actions.
 */

(function () {
  window.initDataTable = function (tableId, bulkActionBarId) {
    const table = document.getElementById(tableId);
    if (!table) return;

    const masterCheckbox = table.querySelector("thead input[type='checkbox']");
    const rowCheckboxes = table.querySelectorAll("tbody input[type='checkbox']");
    const bulkBar = document.getElementById(bulkActionBarId);

    function updateSelection() {
      const selectedCount = Array.from(rowCheckboxes).filter((cb) => cb.checked).length;
      if (bulkBar) {
        bulkBar.style.display = selectedCount > 0 ? "flex" : "none";
        const countSpan = bulkBar.querySelector(".selected-count");
        if (countSpan) countSpan.textContent = selectedCount;
      }
      if (masterCheckbox) {
        masterCheckbox.checked = selectedCount > 0 && selectedCount === rowCheckboxes.length;
        masterCheckbox.indeterminate = selectedCount > 0 && selectedCount < rowCheckboxes.length;
      }
    }

    if (masterCheckbox) {
      masterCheckbox.addEventListener("change", function () {
        rowCheckboxes.forEach((cb) => (cb.checked = masterCheckbox.checked));
        updateSelection();
      });
    }

    rowCheckboxes.forEach((cb) => {
      cb.addEventListener("change", updateSelection);
    });
  };
})();
