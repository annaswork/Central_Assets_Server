// Extracted from templates/partials/csv_update_modal.html so browsers cache it instead of re-downloading it inline.
let currentCsvTargetEndpoint = '';
let selectedCsvFile = null;
let hasPerformedCsvUpdate = false;

function openCsvUpdateModal(endpoint) {
  currentCsvTargetEndpoint = endpoint;
  selectedCsvFile = null;
  hasPerformedCsvUpdate = false;

  const modal = document.getElementById('csvUpdateModal');
  const fileInput = document.getElementById('csvModalFileInput');
  const prompt = document.getElementById('csvFileSelectPrompt');
  const fileInfo = document.getElementById('csvFileSelectedInfo');
  const submitBtn = document.getElementById('csvModalSubmitBtn');
  const resultsDiv = document.getElementById('csvModalResults');
  const cancelBtn = document.getElementById('csvModalCancelBtn');
  const submitText = document.getElementById('csvSubmitBtnText');

  if (fileInput) fileInput.value = '';
  if (prompt) prompt.style.display = 'block';
  if (fileInfo) fileInfo.style.display = 'none';
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.style.display = 'inline-flex';
  }
  if (submitText) submitText.textContent = 'Upload & Update';
  if (cancelBtn) cancelBtn.textContent = 'Cancel';
  if (resultsDiv) resultsDiv.style.display = 'none';

  // Analyze active filters in current URL
  const searchParams = new URLSearchParams(window.location.search);
  const filterNotice = document.getElementById('csvModalFilterNotice');
  const activeFilters = [];

  if (searchParams.get('categoryId')) {
    activeFilters.push(`Category ID: ${searchParams.get('categoryId')}`);
  }
  if (searchParams.get('subCategoryId')) {
    activeFilters.push(`Subcategory ID: ${searchParams.get('subCategoryId')}`);
  }
  if (searchParams.get('search')) {
    activeFilters.push(`Search: "${searchParams.get('search')}"`);
  }
  if (searchParams.get('q')) {
    activeFilters.push(`Search: "${searchParams.get('q')}"`);
  }

  if (filterNotice) {
    if (activeFilters.length > 0) {
      filterNotice.style.background = 'var(--app-premium-container, #78350f)';
      filterNotice.style.color = 'var(--app-premium, #fbbf24)';
      filterNotice.style.border = '1px solid rgba(251, 191, 36, 0.3)';
      filterNotice.innerHTML = `
        <span style="font-size:1.1rem; line-height:1;">⚠️</span>
        <div>
          <strong>Active filter applied:</strong> ${activeFilters.join(', ')}<br>
          <span style="font-size:0.8rem; opacity:0.9;">CSV updates will <strong>only apply</strong> to items matching this filter. Other items in the CSV will be safely skipped.</span>
        </div>
      `;
    } else {
      filterNotice.style.background = 'var(--md-sys-color-surface-container, #1e293b)';
      filterNotice.style.color = 'var(--md-sys-color-on-surface-variant, #94a3b8)';
      filterNotice.style.border = '1px solid var(--md-sys-color-outline-variant, #334155)';
      filterNotice.innerHTML = `
        <span style="font-size:1.1rem; line-height:1;">ℹ️</span>
        <div>
          <strong>No active filter:</strong> CSV updates will match against all items in this section.
        </div>
      `;
    }
  }

  if (modal) modal.style.display = 'flex';
}

function closeCsvUpdateModal() {
  const modal = document.getElementById('csvUpdateModal');
  if (modal) modal.style.display = 'none';
  if (hasPerformedCsvUpdate) {
    window.location.reload();
  }
}

function handleCsvModalBackdrop(event) {
  if (event.target.id === 'csvUpdateModal') {
    closeCsvUpdateModal();
  }
}

function handleCsvDragOver(event) {
  event.preventDefault();
  event.stopPropagation();
  const dz = document.getElementById('csvDropzone');
  if (dz) dz.classList.add('dragover');
}

function handleCsvDragLeave(event) {
  event.preventDefault();
  event.stopPropagation();
  const dz = document.getElementById('csvDropzone');
  if (dz) dz.classList.remove('dragover');
}

function handleCsvDrop(event) {
  event.preventDefault();
  event.stopPropagation();
  const dz = document.getElementById('csvDropzone');
  if (dz) dz.classList.remove('dragover');

  if (event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files.length > 0) {
    const file = event.dataTransfer.files[0];
    if (file.name.toLowerCase().endsWith('.csv')) {
      setSelectedCsvFile(file);
    } else {
      alert('Please select a valid .csv file.');
    }
  }
}

function handleCsvFileSelected(event) {
  const file = event.target.files && event.target.files[0];
  if (file) {
    if (file.name.toLowerCase().endsWith('.csv')) {
      setSelectedCsvFile(file);
    } else {
      alert('Please select a valid .csv file.');
      event.target.value = '';
    }
  }
}

function setSelectedCsvFile(file) {
  selectedCsvFile = file;
  const prompt = document.getElementById('csvFileSelectPrompt');
  const fileInfo = document.getElementById('csvFileSelectedInfo');
  const nameEl = document.getElementById('csvSelectedFileName');
  const sizeEl = document.getElementById('csvSelectedFileSize');
  const submitBtn = document.getElementById('csvModalSubmitBtn');

  if (prompt) prompt.style.display = 'none';
  if (fileInfo) fileInfo.style.display = 'block';
  if (nameEl) nameEl.textContent = file.name;
  if (sizeEl) sizeEl.textContent = `${(file.size / 1024).toFixed(1)} KB`;
  if (submitBtn) submitBtn.disabled = false;
}

async function submitCsvUpdate() {
  if (!selectedCsvFile || !currentCsvTargetEndpoint) return;

  const submitBtn = document.getElementById('csvModalSubmitBtn');
  const submitText = document.getElementById('csvSubmitBtnText');
  const cancelBtn = document.getElementById('csvModalCancelBtn');
  const resultsDiv = document.getElementById('csvModalResults');
  const summaryEl = document.getElementById('csvResultsSummary');
  const detailsEl = document.getElementById('csvResultsDetails');

  if (submitBtn) submitBtn.disabled = true;
  if (submitText) submitText.textContent = 'Updating...';

  const formData = new FormData();
  formData.append('csv_file', selectedCsvFile);

  // Preserve active filters in form data and endpoint query
  const searchParams = new URLSearchParams(window.location.search);
  for (const [key, val] of searchParams.entries()) {
    formData.append(key, val);
  }

  const separator = currentCsvTargetEndpoint.includes('?') ? '&' : '?';
  const targetUrl = `${currentCsvTargetEndpoint}${window.location.search ? separator + window.location.search.substring(1) : ''}`;

  try {
    const res = await fetch(targetUrl, {
      method: 'POST',
      body: formData
    });

    const data = await res.json();
    if (resultsDiv) resultsDiv.style.display = 'flex';

    if (data.success) {
      hasPerformedCsvUpdate = true;
      if (summaryEl) {
        summaryEl.style.background = 'var(--app-success-bg, #14532d)';
        summaryEl.style.color = 'var(--app-success, #4ade80)';
        summaryEl.style.border = '1px solid rgba(74, 222, 128, 0.3)';
        summaryEl.innerHTML = `✓ ${data.message || `Updated ${data.updated_count} item(s).`}`;
      }

      let detailsHtml = '';
      if (data.updated && data.updated.length > 0) {
        detailsHtml += `<div style="color:var(--app-success, #4ade80); font-weight:600; margin-bottom:4px;">Updated:</div>`;
        data.updated.forEach(u => {
          detailsHtml += `<div style="padding:2px 0;">• <strong>${u.name}</strong> (fields: ${u.fields.join(', ')})</div>`;
        });
      }
      if (data.skipped && data.skipped.length > 0) {
        detailsHtml += `<div style="color:var(--app-premium, #fbbf24); font-weight:600; margin-top:8px; margin-bottom:4px;">Skipped / Unmatched in Filter:</div>`;
        data.skipped.forEach(s => {
          detailsHtml += `<div style="padding:2px 0; color:var(--md-sys-color-on-surface-variant, #94a3b8);">• <em>${s.name || 'Unnamed'}</em>: ${s.reason || 'Not found'}</div>`;
        });
      }

      if (detailsEl) {
        detailsEl.innerHTML = detailsHtml;
        detailsEl.style.display = 'block';
      }

      if (submitBtn) submitBtn.style.display = 'none';
      if (cancelBtn) cancelBtn.textContent = 'Done (Reload)';
    } else {
      if (summaryEl) {
        summaryEl.style.background = 'rgba(239, 68, 68, 0.15)';
        summaryEl.style.color = 'var(--md-sys-color-error, #f87171)';
        summaryEl.style.border = '1px solid rgba(239, 68, 68, 0.3)';
        summaryEl.innerHTML = `✕ Error: ${data.message || 'Failed to apply CSV updates'}`;
      }
      if (submitBtn) submitBtn.disabled = false;
      if (submitText) submitText.textContent = 'Try Again';
    }
  } catch (err) {
    if (resultsDiv) resultsDiv.style.display = 'flex';
    if (summaryEl) {
      summaryEl.style.background = 'rgba(239, 68, 68, 0.15)';
      summaryEl.style.color = 'var(--md-sys-color-error, #f87171)';
      summaryEl.style.border = '1px solid rgba(239, 68, 68, 0.3)';
      summaryEl.innerHTML = `✕ Request error: ${err.message}`;
    }
    if (submitBtn) submitBtn.disabled = false;
    if (submitText) submitText.textContent = 'Try Again';
  }
}
