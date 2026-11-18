/**
 * Drag-and-drop table row reordering.
 * Automatically posts sequence reordering to the server.
 */

(function () {
  window.initReorderableTable = function (tableId, instanceId, itemType) {
    const table = document.getElementById(tableId);
    if (!table) return;

    const tbody = table.querySelector("tbody");
    if (!tbody) return;

    let dragRow = null;

    tbody.querySelectorAll("tr").forEach((row) => {
      row.setAttribute("draggable", "true");

      row.addEventListener("dragstart", function (e) {
        dragRow = this;
        this.style.opacity = "0.5";
        e.dataTransfer.effectAllowed = "move";
      });

      row.addEventListener("dragover", function (e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        const bounding = this.getBoundingClientRect();
        const offset = bounding.y + bounding.height / 2;
        if (e.clientY - offset > 0) {
          this.after(dragRow);
        } else {
          this.before(dragRow);
        }
      });

      row.addEventListener("dragend", async function () {
        this.style.opacity = "1";
        dragRow = null;

        // Collect new order of IDs and update visual sequence numbers
        const orderedIds = [];
        tbody.querySelectorAll("tr").forEach((r, idx) => {
          const id = r.dataset.id || r.dataset.assetId;
          if (id) orderedIds.push(id);
          const seqInp = r.querySelector("input[type='number']");
          if (seqInp) seqInp.value = idx + 1;
        });

        // Send reorder request
        try {
          const targetUrl = instanceId
            ? `/admin/instances/${instanceId}/reorder`
            : `/admin/api/reorder`;
          await fetch(targetUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              type: itemType,
              ordered_ids: orderedIds,
            }),
          });
        } catch (err) {
          console.error("Reorder failed:", err);
        }
      });
    });
  };
})();
