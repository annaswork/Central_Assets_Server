/**
 * Dialogs & Toast Notifications utility module.
 * Provides accessible confirmation modals, critical warning dialogs, and animated toasts.
 */

function ensureToastContainer() {
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  return container;
}

function showToast(message, type = 'success', duration = 4500) {
  const container = ensureToastContainer();
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;

  const icon = type === 'success' ? '✓' : (type === 'error' ? '⚠️' : 'ℹ️');
  toast.innerHTML = `
    <span style="font-weight:bold; font-size:1.1rem;">${icon}</span>
    <span style="flex:1;">${message}</span>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(12px) scale(0.97)';
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 320);
  }, duration);
}

function showConfirmModal(options) {
  const {
    title = 'Confirm Action',
    body = 'Are you sure you want to proceed?',
    confirmText = 'Confirm',
    cancelText = 'Cancel',
    isCritical = false,
    onConfirm = () => {},
    onCancel = () => {}
  } = options;

  // Remove any existing modal
  const existing = document.getElementById('activeConfirmModal');
  if (existing) existing.remove();

  const backdrop = document.createElement('div');
  backdrop.id = 'activeConfirmModal';
  backdrop.className = 'modal-backdrop';

  const box = document.createElement('div');
  box.className = `modal-box ${isCritical ? 'modal-critical' : ''}`;

  const icon = isCritical ? '🚨' : '❓';
  const titleClass = isCritical ? 'modal-title-critical' : 'modal-title-confirm';

  box.innerHTML = `
    <div class="modal-header">
      <span style="font-size:1.75rem;">${icon}</span>
      <h3 class="${titleClass}">${title}</h3>
    </div>
    <div class="modal-body">
      ${body}
    </div>
    <div class="modal-footer">
      <button type="button" class="btn btn-outlined" id="modalCancelBtn">${cancelText}</button>
      <button type="button" class="btn ${isCritical ? 'btn-destructive' : 'btn-primary'}" id="modalConfirmBtn">${confirmText}</button>
    </div>
  `;

  backdrop.appendChild(box);
  document.body.appendChild(backdrop);

  const close = () => {
    backdrop.style.opacity = '0';
    setTimeout(() => backdrop.remove(), 150);
  };

  document.getElementById('modalCancelBtn').addEventListener('click', () => {
    close();
    onCancel();
  });

  document.getElementById('modalConfirmBtn').addEventListener('click', () => {
    close();
    onConfirm();
  });

  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) {
      close();
      onCancel();
    }
  });
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Generate a sequential non-colliding candidate filename given a taken set.
 */
function getNextCandidateName(filename, takenSet) {
  if (!filename) return 'file_1';
  const lastDot = filename.lastIndexOf('.');
  const ext = lastDot !== -1 ? filename.slice(lastDot) : '';
  const stem = lastDot !== -1 ? filename.slice(0, lastDot) : filename;
  const match = stem.match(/^(.*?)([_\-\s]?)(\d+)$/);
  let baseStem = stem;
  let sep = '_';
  let counter = 1;
  if (match && match[1]) {
    baseStem = match[1];
    sep = match[2] || '_';
    counter = parseInt(match[3], 10) + 1;
  }
  while (true) {
    const candidate = `${baseStem}${sep}${counter}${ext}`;
    if (!takenSet || !takenSet.has(candidate.toLowerCase())) {
      return candidate;
    }
    counter++;
  }
}

/**
 * Interactive Popup Editor to Rename New Filename upon Collision or Similarity.
 *
 * @param {Object} options
 * @param {string} options.filename - The new file's proposed name (e.g. 'neon_horizon.png')
 * @param {string} [options.existingMatch] - Name of conflicting file/asset
 * @param {string} [options.conflictType] - 'exact' or 'similar'
 * @param {string} [options.suggestedFilename] - Suggested non-conflicting filename
 * @param {string} [options.title] - Optional title for popup
 * @param {Function} [options.onRename] - Callback(newFilename)
 * @param {Function} [options.onCancel] - Callback()
 * @returns {Promise<string|null>} - Resolves with new filename or null if cancelled
 */
function showRenameModal(options) {
  return new Promise((resolve) => {
    const {
      filename = '',
      existingMatch = '',
      conflictType = 'exact',
      suggestedFilename = '',
      title = 'Rename File — Filename Conflict Detected',
      onRename = () => {},
      onCancel = () => {},
    } = options;

    const existing = document.getElementById('activeRenameModal');
    if (existing) existing.remove();

    const isExact = conflictType === 'exact';
    const lastDot = filename.lastIndexOf('.');
    const ext = lastDot !== -1 ? filename.slice(lastDot) : '';
    const stem = lastDot !== -1 ? filename.slice(0, lastDot) : filename;

    const initialVal = suggestedFilename || (stem + '_1' + ext);

    // Build smart alternative suggestions chips
    const suggestions = [];
    if (suggestedFilename && suggestedFilename !== initialVal) {
      suggestions.push(suggestedFilename);
    }
    const alt1 = stem + '_v2' + ext;
    const alt2 = stem + '_copy' + ext;
    if (!suggestions.includes(alt1) && alt1 !== initialVal) suggestions.push(alt1);
    if (!suggestions.includes(alt2) && alt2 !== initialVal) suggestions.push(alt2);

    const chipsHtml = suggestions.length > 0
      ? `<div style="display:flex; align-items:center; gap:0.4rem; flex-wrap:wrap; font-size:0.8rem; margin-top:0.6rem;">
           <span style="color:var(--md-sys-color-on-surface-variant);">Suggestions:</span>
           ${suggestions.map(s => `<button type="button" class="rename-suggestion-chip" data-chip="${escapeHtml(s)}">${escapeHtml(s)}</button>`).join('')}
         </div>`
      : '';

    const backdrop = document.createElement('div');
    backdrop.id = 'activeRenameModal';
    backdrop.className = 'modal-backdrop';

    const box = document.createElement('div');
    box.className = 'modal-box rename-modal-box';

    box.innerHTML = `
      <div class="modal-header">
        <span style="font-size:1.85rem;">✏️</span>
        <div>
          <h3 style="margin:0; font-size:1.15rem; color:var(--md-sys-color-on-surface);">${escapeHtml(title)}</h3>
          <div style="font-size:0.83rem; color:var(--md-sys-color-on-surface-variant); margin-top:2px;">
            A file or asset with this conflicting filename already exists.
          </div>
        </div>
      </div>

      <div class="modal-body" style="padding-top:0.5rem;">
        <div class="rename-conflict-banner">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.35rem; font-size:0.8rem;">
            <span style="color:var(--md-sys-color-on-surface-variant); font-weight:500;">Existing Match:</span>
            <span class="badge badge-error">Filename Conflict</span>
          </div>
          <div style="font-family:monospace; font-weight:600; word-break:break-all; font-size:0.9rem; color:var(--md-sys-color-error);">
            ${escapeHtml(existingMatch || filename)}
          </div>
        </div>

        <div class="form-group" style="margin-bottom:0.75rem;">
          <label class="label" for="renameModalInput" style="display:flex; justify-content:space-between; margin-bottom:0.35rem;">
            <span>New Filename *</span>
            <span style="font-size:0.8rem; font-weight:normal; color:var(--md-sys-color-primary);" id="renameModalExtHint">${escapeHtml(ext)}</span>
          </label>
          <input type="text" id="renameModalInput" class="input" value="${escapeHtml(initialVal)}" style="font-family:monospace; font-size:0.95rem; font-weight:500; width:100%; box-sizing:border-box;" autocomplete="off" spellcheck="false">
          <div id="renameModalError" style="display:none; color:var(--md-sys-color-error); font-size:0.8rem; margin-top:0.35rem; font-weight:500;"></div>
        </div>

        ${chipsHtml}
      </div>

      <div class="modal-footer">
        <button type="button" class="btn btn-outlined" id="renameModalCancelBtn">Cancel / Skip</button>
        <button type="button" class="btn btn-primary" id="renameModalSubmitBtn">Rename &amp; Continue</button>
      </div>
    `;

    backdrop.appendChild(box);
    document.body.appendChild(backdrop);

    const input = document.getElementById('renameModalInput');
    const errEl = document.getElementById('renameModalError');
    const submitBtn = document.getElementById('renameModalSubmitBtn');
    const cancelBtn = document.getElementById('renameModalCancelBtn');

    // Auto-focus and select stem
    if (input) {
      input.focus();
      const dotIdx = input.value.lastIndexOf('.');
      if (dotIdx > 0) {
        input.setSelectionRange(0, dotIdx);
      } else {
        input.select();
      }
    }

    // Handle suggestion chip clicks
    box.querySelectorAll('.rename-suggestion-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const val = chip.getAttribute('data-chip');
        if (input && val) {
          input.value = val;
          input.focus();
          if (errEl) errEl.style.display = 'none';
        }
      });
    });

    const close = () => {
      backdrop.style.opacity = '0';
      setTimeout(() => backdrop.remove(), 150);
    };

    const handleCancel = () => {
      close();
      onCancel();
      resolve(null);
    };

    const handleSubmit = () => {
      const trimmed = (input ? input.value : '').trim();
      if (!trimmed) {
        if (errEl) {
          errEl.textContent = 'Filename cannot be empty.';
          errEl.style.display = 'block';
        }
        if (input) input.focus();
        return;
      }
      if (existingMatch && trimmed.toLowerCase() === existingMatch.toLowerCase()) {
        if (errEl) {
          errEl.textContent = 'Please choose a name different from the existing match.';
          errEl.style.display = 'block';
        }
        if (input) input.focus();
        return;
      }

      close();
      onRename(trimmed);
      resolve(trimmed);
    };

    cancelBtn.addEventListener('click', handleCancel);
    submitBtn.addEventListener('click', handleSubmit);

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleSubmit();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        handleCancel();
      } else {
        if (errEl) errEl.style.display = 'none';
      }
    });

    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) {
        handleCancel();
      }
    });
  });
}

// Auto-show toast on page load if toastMessage is present in dataset or URL params
document.addEventListener('DOMContentLoaded', () => {
  const main = document.getElementById('mainContent');
  if (main && main.dataset.toastMessage) {
    showToast(main.dataset.toastMessage, 'success');
  } else {
    const params = new URLSearchParams(window.location.search);
    if (params.has('deleted') && params.has('name')) {
      const name = params.get('name');
      showToast(`'${name}' and associated storage files were deleted.`, 'success');
      // Clean query param from URL without reload
      const cleanUrl = window.location.pathname;
      window.history.replaceState({}, document.title, cleanUrl);
    }
  }
});

