/**
 * Bulk actions and view switcher handler for Categories, Subcategories, and Assets
 * Supports: select all, unselect all, enable, disable, set premium, set normal,
 * and view toggling (List view vs. Block/Card view).
 */

function updateBulkActionsBar() {
  const bar = document.getElementById('bulkActionsBar');
  const countEl = document.getElementById('bulkSelectedCount');
  const masterCb = document.getElementById('masterSelectAll');

  const allCheckboxes = Array.from(document.querySelectorAll('.row-select-checkbox'));
  const allUniqueIds = new Set(allCheckboxes.map(cb => cb.value).filter(Boolean));

  const checkedBoxes = allCheckboxes.filter(cb => cb.checked);
  const checkedUniqueIds = new Set(checkedBoxes.map(cb => cb.value).filter(Boolean));
  const count = checkedUniqueIds.size;

  if (countEl) {
    countEl.textContent = count;
  }

  if (bar) {
    if (count > 0) {
      bar.style.display = 'flex';
      bar.classList.add('active');
    } else {
      bar.style.display = 'none';
      bar.classList.remove('active');
    }
  }

  if (masterCb && allUniqueIds.size > 0) {
    if (count === allUniqueIds.size) {
      masterCb.checked = true;
      masterCb.indeterminate = false;
    } else if (count > 0) {
      masterCb.checked = false;
      masterCb.indeterminate = true;
    } else {
      masterCb.checked = false;
      masterCb.indeterminate = false;
    }
  }

  // Update card selected states
  document.querySelectorAll('.asset-card').forEach(card => {
    const cb = card.querySelector('.row-select-checkbox');
    if (cb) {
      card.classList.toggle('card-selected', cb.checked);
    }
  });
}

function handleRowCheckboxChange(event) {
  const target = event.target;
  const val = target.value;
  const isChecked = target.checked;

  // Synchronize any twin checkboxes (e.g. between list and block views)
  if (val) {
    document.querySelectorAll(`.row-select-checkbox[value="${val}"]`).forEach(cb => {
      cb.checked = isChecked;
    });
  }

  updateBulkActionsBar();
}

function toggleMasterSelect(checked) {
  const allCheckboxes = document.querySelectorAll('.row-select-checkbox');
  allCheckboxes.forEach(cb => {
    cb.checked = checked;
  });
  updateBulkActionsBar();
}

function bulkSelectAll() {
  toggleMasterSelect(true);
}

function bulkUnselectAll() {
  toggleMasterSelect(false);
}

function promptBulkDelete() {
  const checkedBoxes = Array.from(document.querySelectorAll('.row-select-checkbox:checked'));
  const ids = Array.from(new Set(checkedBoxes.map(cb => cb.value).filter(Boolean)));

  if (ids.length === 0) {
    if (typeof showToast === 'function') {
      showToast('Please select at least one item to delete.', 'warning');
    } else {
      alert('Please select at least one item to delete.');
    }
    return;
  }

  const path = window.location.pathname;
  const entityName = path.includes('/admin/assets')
    ? 'asset'
    : path.includes('/admin/subcategories')
    ? 'subcategory'
    : 'category';
  const capitalizedEntity = entityName.charAt(0).toUpperCase() + entityName.slice(1);

  if (typeof showConfirmModal === 'function') {
    showConfirmModal({
      title: `Delete Selected ${capitalizedEntity}s`,
      body: `Are you sure you want to delete <strong>${ids.length}</strong> selected ${entityName}(s)?<br><br><div class="alert alert-error" style="margin-bottom:0; font-size:0.88rem;">⚠️ This will delete the database record(s) AND permanently remove associated media files from storage on disk.</div>`,
      confirmText: `Delete ${ids.length} ${capitalizedEntity}(s)`,
      cancelText: 'Cancel',
      isCritical: true,
      onConfirm: () => {
        executeBulkAction('delete');
      }
    });
  } else {
    if (confirm(`Are you sure you want to delete ${ids.length} selected ${entityName}(s)?`)) {
      executeBulkAction('delete');
    }
  }
}

async function executeBulkAction(action) {
  const checkedBoxes = Array.from(document.querySelectorAll('.row-select-checkbox:checked'));
  const ids = Array.from(new Set(checkedBoxes.map(cb => cb.value).filter(Boolean)));

  if (ids.length === 0) {
    if (typeof showToast === 'function') {
      showToast('Please select at least one item.', 'warning');
    } else {
      alert('Please select at least one item.');
    }
    return;
  }

  // Determine target endpoint based on current pathname
  const path = window.location.pathname;
  let endpoint = '';
  if (path.includes('/admin/categories')) {
    endpoint = '/admin/categories/bulk-actions';
  } else if (path.includes('/admin/subcategories')) {
    endpoint = '/admin/subcategories/bulk-actions';
  } else if (path.includes('/admin/assets')) {
    endpoint = '/admin/assets/bulk-actions';
  } else {
    endpoint = path.replace(/\/$/, '') + '/bulk-actions';
  }

  const buttons = document.querySelectorAll('#bulkActionsBar .bulk-btn');
  buttons.forEach(btn => {
    btn.disabled = true;
    btn.style.opacity = '0.6';
  });

  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      },
      body: JSON.stringify({ ids: ids, action: action })
    });

    const data = await res.json();
    if (res.ok && data.success) {
      if (typeof showToast === 'function') {
        showToast(data.message || 'Items updated successfully', 'success');
      }
      setTimeout(() => {
        window.location.reload();
      }, 500);
    } else {
      const errMsg = data.message || data.detail || 'Failed to update items';
      if (typeof showToast === 'function') {
        showToast(errMsg, 'error');
      } else {
        alert(errMsg);
      }
      buttons.forEach(btn => {
        btn.disabled = false;
        btn.style.opacity = '1';
      });
    }
  } catch (err) {
    if (typeof showToast === 'function') {
      showToast('Network or server error during bulk action.', 'error');
    } else {
      alert('Network or server error during bulk action.');
    }
    buttons.forEach(btn => {
      btn.disabled = false;
      btn.style.opacity = '1';
    });
  }
}

/**
 * View Switcher for Assets Page (List vs. Block/Card View)
 */
function setAssetView(mode) {
  const listView = document.getElementById('assetListView');
  const blockView = document.getElementById('assetBlockView');
  const btnList = document.getElementById('viewBtnList');
  const btnBlock = document.getElementById('viewBtnBlock');
  const colsPicker = document.getElementById('colsPickerAdmin');

  if (!listView || !blockView) return;

  if (mode === 'block') {
    listView.style.display = 'none';
    blockView.style.display = 'grid';
    if (btnList) btnList.classList.remove('active');
    if (btnBlock) btnBlock.classList.add('active');
    if (colsPicker) colsPicker.style.display = 'inline-flex';
    try {
      localStorage.setItem('admin_asset_view', 'block');
    } catch (e) {}
  } else {
    listView.style.display = 'block';
    blockView.style.display = 'none';
    if (btnList) btnList.classList.add('active');
    if (btnBlock) btnBlock.classList.remove('active');
    if (colsPicker) colsPicker.style.display = 'none';
    try {
      localStorage.setItem('admin_asset_view', 'list');
    } catch (e) {}
  }
}

/**
 * Configure items per row (5 to 8) for Admin Card/Block view
 */
function setGridColumns(cols) {
  cols = parseInt(cols, 10);
  if (isNaN(cols) || cols < 5 || cols > 8) cols = 6;
  const blockView = document.getElementById('assetBlockView');
  if (blockView) {
    blockView.classList.remove('grid-cols-5', 'grid-cols-6', 'grid-cols-7', 'grid-cols-8');
    blockView.classList.add(`grid-cols-${cols}`);
  }
  document.querySelectorAll('#colsPickerAdmin .cols-picker-btn').forEach(btn => {
    btn.classList.toggle('active', parseInt(btn.dataset.cols, 10) === cols);
  });
  try {
    localStorage.setItem('admin_asset_cols', cols);
  } catch (e) {}
}

/**
 * Swipe selection for Block/Card view
 * When user clicks down on a selection box and hovers across other cards,
 * they all get selected seamlessly.
 */
let isSwipeSelecting = false;
let swipeTargetState = true;
let lastSwipeStart = 0;

function applyCheckboxState(cb, state) {
  if (cb.checked === state) return;
  cb.checked = state;
  const val = cb.value;
  if (val) {
    document.querySelectorAll(`.row-select-checkbox[value="${val}"]`).forEach(other => {
      other.checked = state;
    });
  }
}

function initSwipeSelection() {
  const blockView = document.getElementById('assetBlockView');
  if (!blockView) return;

  function handleSwipeStart(e) {
    if (e.button !== undefined && e.button !== 0) return;

    const targetCheckbox = e.target.closest('.row-select-checkbox');
    const targetTopbar = e.target.closest('.asset-card-topbar');
    const targetCard = e.target.closest('.asset-card');

    if (!targetCard || (!targetCheckbox && !targetTopbar)) return;

    const cb = targetCard.querySelector('.row-select-checkbox');
    if (!cb) return;

    const now = Date.now();
    if (now - lastSwipeStart < 50) return;
    lastSwipeStart = now;

    e.preventDefault();
    isSwipeSelecting = true;
    swipeTargetState = !cb.checked;

    applyCheckboxState(cb, swipeTargetState);
    targetCard.classList.toggle('card-selected', swipeTargetState);
    updateBulkActionsBar();

    document.body.classList.add('is-swipe-selecting');
    blockView.classList.add('is-swiping');
  }

  function handleSwipeMove(e) {
    if (!isSwipeSelecting) return;

    const el = document.elementFromPoint(e.clientX, e.clientY);
    if (!el) return;

    const card = el.closest('.asset-card');
    if (card && blockView.contains(card)) {
      const cb = card.querySelector('.row-select-checkbox');
      if (cb && cb.checked !== swipeTargetState) {
        applyCheckboxState(cb, swipeTargetState);
        card.classList.toggle('card-selected', swipeTargetState);
        updateBulkActionsBar();
      }
    }
  }

  function handleSwipeEnd() {
    if (isSwipeSelecting) {
      isSwipeSelecting = false;
      document.body.classList.remove('is-swipe-selecting');
      blockView.classList.remove('is-swiping');
      updateBulkActionsBar();
    }
  }

  // Pointer events for modern mouse, pen, and touch
  blockView.addEventListener('pointerdown', handleSwipeStart);
  window.addEventListener('pointermove', handleSwipeMove);
  window.addEventListener('pointerup', handleSwipeEnd);
  window.addEventListener('pointercancel', handleSwipeEnd);

  // Mouse event fallbacks
  blockView.addEventListener('mousedown', handleSwipeStart);
  window.addEventListener('mousemove', handleSwipeMove);
  window.addEventListener('mouseup', handleSwipeEnd);
}

document.addEventListener('DOMContentLoaded', function() {
  // Bind change listeners to all row checkboxes
  document.querySelectorAll('.row-select-checkbox').forEach(cb => {
    cb.addEventListener('change', handleRowCheckboxChange);
  });

  // Initialize view mode for assets if view switcher exists
  const btnBlock = document.getElementById('viewBtnBlock');
  if (btnBlock) {
    let savedMode = 'list';
    try {
      const urlParams = new URLSearchParams(window.location.search);
      const viewParam = urlParams.get('view');
      if (viewParam === 'block' || viewParam === 'list') {
        savedMode = viewParam;
      } else {
        savedMode = localStorage.getItem('admin_asset_view') || 'list';
      }
    } catch (e) {}

    if (savedMode === 'block') {
      setAssetView('block');
    }

    let savedCols = 6;
    try {
      savedCols = localStorage.getItem('admin_asset_cols') || 6;
    } catch (e) {}
    setGridColumns(savedCols);
  }

  // Initialize swipe selection on block cards
  initSwipeSelection();
});
