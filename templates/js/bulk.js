/**
 * Bulk file drag-and-drop ingestion and staging table preview.
 */

(function () {
  window.initBulkUploader = function (dropZoneId, stagingTableId) {
    const dropZone = document.getElementById(dropZoneId);
    const stagingTable = document.getElementById(stagingTableId);
    if (!dropZone || !stagingTable) return;

    const tbody = stagingTable.querySelector("tbody");
    const commitBtn = document.getElementById("commitBulkBtn");
    let stagedFiles = [];

    dropZone.addEventListener("dragover", function (e) {
      e.preventDefault();
      dropZone.style.borderColor = "var(--md-sys-color-primary)";
    });

    dropZone.addEventListener("dragleave", function () {
      dropZone.style.borderColor = "var(--md-sys-color-outline)";
    });

    dropZone.addEventListener("drop", function (e) {
      e.preventDefault();
      dropZone.style.borderColor = "var(--md-sys-color-outline)";
      handleFiles(e.dataTransfer.files);
    });

    const fileInput = document.getElementById("bulkFileInput");
    if (fileInput) {
      fileInput.addEventListener("change", function () {
        handleFiles(this.files);
      });
    }

    function cleanFilenameToTitle(name) {
      const stem = name.replace(/\.[^/.]+$/, "");
      return stem
        .replace(/[_-]+/g, " ")
        .replace(/\s+/g, " ")
        .trim();
    }

    function handleFiles(files) {
      Array.from(files).forEach((file) => {
        const title = cleanFilenameToTitle(file.name);
        const item = { file, title };
        stagedFiles.push(item);

        const row = document.createElement("tr");
        row.innerHTML = `
          <td>${file.name}</td>
          <td><input type="text" class="input" value="${title}" style="min-height:36px;"></td>
          <td>${(file.size / 1024).toFixed(1)} KB</td>
          <td><button type="button" class="btn btn-destructive" style="min-height:32px; padding:2px 8px;">✕</button></td>
        `;

        row.querySelector("input").addEventListener("input", function () {
          item.title = this.value;
        });

        row.querySelector("button").addEventListener("click", function () {
          const idx = stagedFiles.indexOf(item);
          if (idx !== -1) stagedFiles.splice(idx, 1);
          row.remove();
          updateCommitButton();
        });

        tbody.appendChild(row);
      });

      updateCommitButton();
    }

    function updateCommitButton() {
      if (commitBtn) {
        commitBtn.disabled = stagedFiles.length === 0;
        commitBtn.textContent = `Create ${stagedFiles.length} Assets`;
      }
    }
  };
})();
