// Extracted from templates/instances/content.html so browsers cache it instead of re-downloading it inline.
function switchInstanceTab(tab) {
  document.getElementById('sectionFolders').style.display = tab === 'folders' ? 'block' : 'none';
  document.getElementById('sectionAssets').style.display = tab === 'assets' ? 'block' : 'none';

  document.getElementById('tabBtnFolders').className = tab === 'folders' ? 'btn btn-primary' : 'btn btn-outlined';
  document.getElementById('tabBtnAssets').className = tab === 'assets' ? 'btn btn-primary' : 'btn btn-outlined';

  try {
    sessionStorage.setItem('instance_active_tab_' + instanceId, tab);
    const url = new URL(window.location.href);
    url.searchParams.set('tab', tab);
    window.history.replaceState({}, '', url.toString());
  } catch (e) { }

  if (tab === 'assets') {
    const urlParams = new URLSearchParams(window.location.search);
    if (!urlParams.get('categoryId')) {
      const catSelect = document.getElementById('categoryFilter');
      if (catSelect && catSelect.value) {
        catSelect.value = '';
        filterSubcategoryOptions('');
      }
    }
    if (!urlParams.get('subCategoryId')) {
      const subSelect = document.getElementById('subCategoryFilter');
      if (subSelect && subSelect.value) {
        subSelect.value = '';
      }
    }
  }
}

function openCreateFolderModal(folderType = 'category', parentCatId = '', parentSuperId = '') {
  const modal = document.getElementById('createFolderModal');
  const typeRadios = document.getElementsByName('folder_type');
  typeRadios.forEach(r => {
    r.checked = r.value === folderType;
  });
  onFolderTypeChange(folderType);

  const superSelect = document.getElementById('parentSuperSelect');
  if (superSelect) superSelect.value = parentSuperId || '';

  if (parentCatId) {
    const pSelect = document.getElementById('parentCategorySelect');
    if (pSelect) pSelect.value = parentCatId;
  }

  document.getElementById('folderNameInput').value = '';
  document.getElementById('folderThumbInput').value = '';
  modal.style.display = 'flex';
  document.getElementById('folderNameInput').focus();
}

function closeCreateFolderModal() {
  document.getElementById('createFolderModal').style.display = 'none';
}

function onFolderTypeChange(type) {
  const parentWrap = document.getElementById('parentCategoryWrap');
  document.getElementById('parentSuperWrap').style.display = type === 'category' ? 'block' : 'none';
  parentWrap.style.display = type === 'subcategory' ? 'block' : 'none';
}

async function handleCreateFolderSubmit(e) {
  e.preventDefault();
  const folderType = document.querySelector('input[name="folder_type"]:checked').value;
  const name = document.getElementById('folderNameInput').value.trim();
  const parentCategoryId = document.getElementById('parentCategorySelect').value;
  const thumbnailUrl = document.getElementById('folderThumbInput').value.trim();

  if (!name) return;

  const btn = document.getElementById('submitFolderBtn');
  btn.disabled = true;
  btn.textContent = 'Creating...';

  try {
    const payload = {
      folder_type: folderType,
      name: name,
      parent_category_id: folderType === 'subcategory' ? parentCategoryId : '',
      parent_super_category_id: folderType === 'category' ? document.getElementById('parentSuperSelect').value : '',
      thumbnail_url: thumbnailUrl
    };

    const res = await fetch(`/admin/instances/${instanceId}/folders/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.message || 'Failed to create folder');

    window.location.reload();
  } catch (err) {
    alert('Error creating folder: ' + err.message);
    btn.disabled = false;
    btn.textContent = 'Create Folder';
  }
}

async function detachCategoryFolder(catId, catName) {
  if (!confirm(`Detach folder "${catName}" and all its referenced sub-folders and assets from this app instance? Central data remains untouched.`)) {
    return;
  }
  try {
    const res = await fetch(`/admin/instances/${instanceId}/categories/${catId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to detach category folder');
    window.location.reload();
  } catch (err) {
    alert('Error detaching folder: ' + err.message);
  }
}

async function detachSubcategoryFolder(subId, subName) {
  if (!confirm(`Detach sub-folder "${subName}" and its referenced assets from this app instance? Central data remains untouched.`)) {
    return;
  }
  try {
    const res = await fetch(`/admin/instances/${instanceId}/subcategories/${subId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to detach sub-folder');
    window.location.reload();
  } catch (err) {
    alert('Error detaching sub-folder: ' + err.message);
  }
}

async function updateAssetOverride(assetId, field, value) {
  const payload = {};
  payload[field] = value;

  try {
    const res = await fetch(`/admin/instances/${instanceId}/assets/${assetId}/override`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('Failed to update override');
  } catch (err) {
    alert('Error updating override: ' + err.message);
  }
}

async function handlePricedToggle(assetId, isChecked) {
  const creditsInput = document.getElementById(`credits-${assetId}`);
  if (creditsInput) {
    if (isChecked) {
      creditsInput.style.opacity = '1';
      creditsInput.style.pointerEvents = 'auto';
      creditsInput.disabled = false;
      if (!creditsInput.value || parseInt(creditsInput.value) <= 0) {
        creditsInput.value = 5;
      }
    } else {
      creditsInput.style.opacity = '0.4';
      creditsInput.style.pointerEvents = 'none';
      creditsInput.disabled = true;
    }
  }
  const creditsVal = creditsInput ? (parseInt(creditsInput.value) || 5) : 5;
  const payload = {
    is_priced: isChecked,
    rewarded_credits: creditsVal
  };
  try {
    const res = await fetch(`/admin/instances/${instanceId}/assets/${assetId}/override`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('Failed to update priced setting');
  } catch (err) {
    alert('Error updating priced setting: ' + err.message);
  }
}

async function handleCreditsChange(assetId, val) {
  const creditsVal = Math.max(0, parseInt(val) || 0);
  try {
    const res = await fetch(`/admin/instances/${instanceId}/assets/${assetId}/override`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rewarded_credits: creditsVal })
    });
    if (!res.ok) throw new Error('Failed to update credits');
  } catch (err) {
    alert('Error updating credits: ' + err.message);
  }
}

let currentRenamingAssetId = null;
let currentRenamingFolderType = null;

// folderType ('super_category' | 'category' | 'subcategory') renames a folder instead of an asset.
function promptCustomName(assetId, currentName, folderType = null) {
  currentRenamingAssetId = assetId;
  currentRenamingFolderType = folderType;
  const modal = document.getElementById('renameAssetModal');
  const input = document.getElementById('renameAssetInput');
  if (modal && input) {
    modal.querySelector('h3').textContent = folderType ? 'Rename Folder' : 'Rename Asset';
    input.value = currentName || '';
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    setTimeout(() => {
      input.focus();
      input.select();
    }, 50);
  }
}

function closeRenameModal() {
  const modal = document.getElementById('renameAssetModal');
  if (modal) {
    modal.style.display = 'none';
    document.body.style.overflow = '';
  }
  currentRenamingAssetId = null;
}

function handleRenameBackdropClick(e) {
  if (e.target && e.target.id === 'renameAssetModal') {
    closeRenameModal();
  }
}

async function saveRenameModal() {
  if (!currentRenamingAssetId) return;
  const input = document.getElementById('renameAssetInput');
  const newName = input ? input.value.trim() : '';
  const saveBtn = document.getElementById('renameAssetSaveBtn');
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
  }
  try {
    if (currentRenamingFolderType) {
      // An empty name clears the rename and restores the original folder name.
      const res = await fetch(`/admin/instances/${instanceId}/folders/${currentRenamingFolderType}/${currentRenamingAssetId}/override`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName })
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).message || `HTTP ${res.status}`);
    } else {
      await updateAssetOverride(currentRenamingAssetId, 'name', newName);
    }
    closeRenameModal();
    window.location.reload();
  } catch (err) {
    alert('Error renaming asset: ' + err.message);
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Changes';
    }
  }
}

async function removeReference(assetId) {
  if (!confirm('Remove this asset reference from the current app instance? The central asset will remain untouched.')) {
    return;
  }

  try {
    const res = await fetch(`/admin/instances/${instanceId}/assets/${assetId}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error('Failed to remove asset reference');
    window.location.reload();
  } catch (err) {
    alert('Error detaching reference: ' + err.message);
  }
}

// --- Referenced Assets AJAX Filtering & Subcategory Dynamic Scoping ---
function filterSubcategoryOptions(selectedCatId) {
  const subSelect = document.getElementById('subCategoryFilter');
  if (!subSelect) return;
  const currentSubVal = subSelect.value;
  let currentSubValid = false;

  const catSelect = document.getElementById('categoryFilter');
  let validCatIds = [];
  if (selectedCatId) {
    validCatIds.push(selectedCatId);
    if (catSelect) {
      const selectedOpt = catSelect.options[catSelect.selectedIndex];
      if (selectedOpt && selectedOpt.dataset.sourceId) {
        validCatIds.push(selectedOpt.dataset.sourceId);
      }
    }
  }
  const superSel = document.getElementById('superAssetFilter');
  const superId = superSel ? superSel.value : '';
  if (!selectedCatId && superId && catSelect) {
    Array.from(catSelect.options).forEach((o, i) => { if (i && !o.hidden) validCatIds.push(o.value, o.dataset.sourceId); });
  }
  const scoped = Boolean(selectedCatId || superId);

  Array.from(subSelect.options).forEach((opt, idx) => {
    if (idx === 0) return; // Keep "All Subcategories"
    const catId = opt.dataset.categoryId || opt.dataset.catId || '';
    if (!scoped || validCatIds.includes(catId)) {
      opt.hidden = false;
      opt.style.display = '';
      if (opt.value === currentSubVal) currentSubValid = true;
    } else {
      opt.hidden = true;
      opt.style.display = 'none';
    }
  });

  if (scoped && !currentSubValid) {
    subSelect.value = '';
  }
}

function handleCategoryFilterChange(catId) {
  filterSubcategoryOptions(catId);
  applyAssetFilters();
}

function handleSubCategoryFilterChange(subSelect) {
  const opt = subSelect.options[subSelect.selectedIndex];
  const catSelect = document.getElementById('categoryFilter');
  if (opt && opt.dataset.categoryId && catSelect && !catSelect.value) {
    catSelect.value = opt.dataset.categoryId;
    filterSubcategoryOptions(opt.dataset.categoryId);
  }
  applyAssetFilters();
}

function handleAssetSearchSubmit(e) {
  if (e) e.preventDefault();
  applyAssetFilters();
}

function handleClearAssetFilters(e, clearType) {
  if (e) e.preventDefault();
  if (clearType !== 'search') {
    const superSel = document.getElementById('superAssetFilter');
    if (superSel) superSel.value = '';
    filterCategoryOptionsBySuper();
  }
  if (clearType === 'search') {
    const qInp = document.getElementById('assetSearchInput');
    if (qInp) qInp.value = '';
  } else if (clearType === 'filters') {
    const catSelect = document.getElementById('categoryFilter');
    const subSelect = document.getElementById('subCategoryFilter');
    const typeSelect = document.getElementById('typeFilter');
    const sortSelect = document.getElementById('assetSortSelect');
    if (catSelect) catSelect.value = '';
    if (subSelect) subSelect.value = '';
    if (typeSelect) typeSelect.value = '';
    if (sortSelect) sortSelect.value = 'sequence';
    filterSubcategoryOptions('');
  } else {
    // all
    const catSelect = document.getElementById('categoryFilter');
    const subSelect = document.getElementById('subCategoryFilter');
    const typeSelect = document.getElementById('typeFilter');
    const sortSelect = document.getElementById('assetSortSelect');
    const qInp = document.getElementById('assetSearchInput');
    if (catSelect) catSelect.value = '';
    if (subSelect) subSelect.value = '';
    if (typeSelect) typeSelect.value = '';
    if (sortSelect) sortSelect.value = 'sequence';
    if (qInp) qInp.value = '';
    filterSubcategoryOptions('');
  }
  applyAssetFilters();
}

// Super category scopes the category options (and through them the subcategory options)
function filterCategoryOptionsBySuper() {
  const superSel = document.getElementById('superAssetFilter');
  const catSelect = document.getElementById('categoryFilter');
  if (!catSelect) return;
  const superId = superSel ? superSel.value : '';
  Array.from(catSelect.options).forEach((opt, idx) => {
    if (idx === 0) return;
    const show = !superId || opt.dataset.superId === superId;
    opt.hidden = !show;
    opt.style.display = show ? '' : 'none';
  });
}

function handleSuperFilterChange() {
  const catSelect = document.getElementById('categoryFilter');
  const subSelect = document.getElementById('subCategoryFilter');
  if (catSelect) catSelect.value = '';
  if (subSelect) subSelect.value = '';
  filterCategoryOptionsBySuper();
  filterSubcategoryOptions('');
  applyAssetFilters();
}

async function applyAssetFilters() {
  const catSelect = document.getElementById('categoryFilter');
  const subSelect = document.getElementById('subCategoryFilter');
  const typeSelect = document.getElementById('typeFilter');
  const sortSelect = document.getElementById('assetSortSelect');
  const qInput = document.getElementById('assetSearchInput');

  const selectedCat = catSelect ? catSelect.value : '';
  const selectedSub = subSelect ? subSelect.value : '';
  const selectedType = typeSelect ? typeSelect.value : '';
  const selectedSort = sortSelect ? sortSelect.value : 'sequence';
  const selectedQ = qInput ? qInput.value.trim() : '';

  const params = new URLSearchParams();
  params.set('tab', 'assets');
  const superSel = document.getElementById('superAssetFilter');
  const selectedSuper = superSel ? superSel.value : '';
  if (selectedSuper) params.set('superCategoryId', selectedSuper);
  if (selectedCat) params.set('categoryId', selectedCat);
  const keepPageSize = new URLSearchParams(window.location.search).get('page_size');
  if (keepPageSize) params.set('page_size', keepPageSize);
  if (selectedSub) params.set('subCategoryId', selectedSub);
  if (selectedType) params.set('type', selectedType);
  if (selectedSort && selectedSort !== 'sequence') params.set('sort', selectedSort);
  if (selectedQ) params.set('q', selectedQ);

  const fetchUrl = `${window.location.pathname}?${params.toString()}`;
  window.history.replaceState({}, '', fetchUrl);

  const filterClearBtn = document.getElementById('assetFilterClearBtn');
  const hasFilterActive = Boolean(selectedSuper || selectedCat || selectedSub || selectedType || (selectedSort && selectedSort !== 'sequence'));
  if (filterClearBtn) {
    filterClearBtn.style.display = hasFilterActive ? 'inline-flex' : 'none';
  }

  const searchClearBtn = document.getElementById('assetSearchClearBtn');
  if (searchClearBtn) {
    searchClearBtn.style.display = selectedQ ? 'inline-flex' : 'none';
  }

  const container = document.getElementById('assetTableContainer');
  if (container) container.style.opacity = '0.35';

  try {
    const res = await fetch(fetchUrl);
    if (!res.ok) throw new Error('Failed to fetch filtered assets');
    const htmlText = await res.text();
    const doc = new DOMParser().parseFromString(htmlText, 'text/html');

    const newContainer = doc.getElementById('assetTableContainer');
    if (newContainer && container) {
      container.innerHTML = newContainer.innerHTML;
    }

    const newTabBtn = doc.getElementById('tabBtnAssets');
    const curTabBtn = document.getElementById('tabBtnAssets');
    if (newTabBtn && curTabBtn) {
      curTabBtn.innerHTML = newTabBtn.innerHTML;
    }

    if (typeof initAssetTableDragDrop === 'function') {
      initAssetTableDragDrop();
    }
  } catch (err) {
    console.error('Error applying asset filters:', err);
  } finally {
    if (container) container.style.opacity = '1';
  }
}

// On fresh load without query params, check saved tab in sessionStorage
const contentParams = new URLSearchParams(window.location.search);
if (!contentParams.get('categoryId')) {
  const catFilter = document.getElementById('categoryFilter');
  if (catFilter) catFilter.value = '';
}
if (!contentParams.get('subCategoryId')) {
  const subFilter = document.getElementById('subCategoryFilter');
  if (subFilter) subFilter.value = '';
}

filterCategoryOptionsBySuper();
const curCatInit = document.getElementById('categoryFilter');
if (curCatInit && curCatInit.value) {
  filterSubcategoryOptions(curCatInit.value);
} else {
  filterSubcategoryOptions('');
}

const savedTab = sessionStorage.getItem('instance_active_tab_' + instanceId);
if (!contentParams.has('tab') && !contentParams.has('categoryId') && !contentParams.has('subCategoryId') && !contentParams.has('sort') && !contentParams.has('type') && !contentParams.has('q') && !contentParams.has('folder_cat') && !contentParams.has('folder_search') && !contentParams.has('folder_sort')) {
  if (savedTab === 'assets') {
    switchInstanceTab('assets');
  }
}

// Floating Toast Notification
function showToast(msg, type = 'info') {
  let toast = document.getElementById('instanceToast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'instanceToast';
    toast.style.cssText = 'display:none; position:fixed; bottom:24px; right:24px; z-index:99999; padding:0.75rem 1.25rem; border-radius:8px; font-size:0.875rem; font-weight:600; box-shadow:0 6px 20px rgba(0,0,0,0.4); pointer-events:none; transition:opacity 0.2s ease;';
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.style.display = 'block';
  toast.style.opacity = '1';
  if (type === 'success') {
    toast.style.background = '#10b981';
    toast.style.color = '#ffffff';
  } else if (type === 'error') {
    toast.style.background = '#ef4444';
    toast.style.color = '#ffffff';
  } else {
    toast.style.background = '#2563eb';
    toast.style.color = '#ffffff';
  }
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => { toast.style.display = 'none'; }, 200);
  }, 2500);
}

// Drag & Drop for Referenced Assets Table
function initAssetTableDragDrop() {
  const tbody = document.getElementById('reorderableTbody');
  if (!tbody) return;

  let draggedRow = null;

  tbody.querySelectorAll('.asset-drag-row').forEach(row => {
    row.setAttribute('draggable', 'true');

    row.addEventListener('dragstart', function (e) {
      draggedRow = this;
      this.style.opacity = '0.4';
      this.style.background = 'var(--md-sys-color-surface-container-high, #334155)';
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', this.dataset.assetId || '');
    });

    row.addEventListener('dragover', function (e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (!draggedRow || draggedRow === this) return;

      const bounding = this.getBoundingClientRect();
      const offset = bounding.y + (bounding.height / 2);
      if (e.clientY - offset > 0) {
        this.after(draggedRow);
      } else {
        this.before(draggedRow);
      }
    });

    row.addEventListener('dragend', function () {
      this.style.opacity = '1';
      this.style.background = '';
      draggedRow = null;

      // Update sequence inputs to natural 1, 2, 3...
      const rows = tbody.querySelectorAll('.asset-drag-row');
      const orderedIds = [];
      rows.forEach((r, idx) => {
        const inp = r.querySelector('.asset-seq-input');
        if (inp) inp.value = assetOffset() + idx + 1;
        if (r.dataset.assetId) orderedIds.push(r.dataset.assetId);
      });

      // Persist new order to server
      saveAssetOrder(orderedIds);
    });
  });
}

// Rows on page N continue the sequence of earlier pages
function assetOffset() {
  const tbody = document.getElementById('reorderableTbody');
  return parseInt((tbody && tbody.dataset.offset) || '0', 10);
}

async function saveAssetOrder(orderedIds) {
  if (!orderedIds || orderedIds.length === 0) return;
  showToast('Saving sequence order...', 'info');
  try {
    const res = await fetch(`/admin/instances/${instanceId}/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'asset',
        start: assetOffset(),
        ordered_ids: orderedIds
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || 'Failed to save reorder');
    showToast('✓ Sequence order updated (1, 2, 3...)', 'success');
  } catch (err) {
    showToast('Error saving order: ' + err.message, 'error');
  }
}

// Handle typing sequence number directly into Seq input
window.handleAssetSeqChange = function (assetId, newPosition) {
  const tbody = document.getElementById('reorderableTbody');
  if (!tbody) return;
  const rows = Array.from(tbody.querySelectorAll('.asset-drag-row'));
  const fromIndex = rows.findIndex(r => r.dataset.assetId === assetId);
  if (fromIndex === -1) return;

  const targetIndex = Math.max(0, Math.min(newPosition - 1 - assetOffset(), rows.length - 1));
  const movingRow = rows[fromIndex];
  const targetRow = rows[targetIndex];

  if (fromIndex < targetIndex) {
    targetRow.after(movingRow);
  } else if (fromIndex > targetIndex) {
    targetRow.before(movingRow);
  }

  // Renumber all rows to 1, 2, 3...
  const newRows = tbody.querySelectorAll('.asset-drag-row');
  const orderedIds = [];
  newRows.forEach((r, idx) => {
    const inp = r.querySelector('.asset-seq-input');
    if (inp) inp.value = assetOffset() + idx + 1;
    if (r.dataset.assetId) orderedIds.push(r.dataset.assetId);
  });

  saveAssetOrder(orderedIds);
};

// Drag & Drop for Category Folders
function initFolderDragDrop() {
  const container = document.getElementById('folderCardsContainer');
  if (!container) return;

  let draggedCard = null;

  container.querySelectorAll('.folder-card').forEach(card => {
    card.setAttribute('draggable', 'true');

    card.addEventListener('dragstart', function (e) {
      draggedCard = this;
      this.style.opacity = '0.4';
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', this.dataset.catId || '');
    });

    card.addEventListener('dragover', function (e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (!draggedCard || draggedCard === this) return;

      const bounding = this.getBoundingClientRect();
      const offset = bounding.y + (bounding.height / 2);
      if (e.clientY - offset > 0) {
        this.after(draggedCard);
      } else {
        this.before(draggedCard);
      }
    });

    card.addEventListener('dragend', async function () {
      this.style.opacity = '1';
      draggedCard = null;

      // Update folder sequence badges to #1, #2, #3...
      const cards = container.querySelectorAll('.folder-card');
      const orderedIds = [];
      cards.forEach((c, idx) => {
        const badge = c.querySelector('.folder-seq-badge');
        if (badge) badge.textContent = `#${idx + 1}`;
        if (c.dataset.catId) orderedIds.push(c.dataset.catId);
      });

      if (orderedIds.length > 0) {
        showToast('Saving folder order...', 'info');
        try {
          const res = await fetch(`/admin/instances/${instanceId}/reorder`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              type: 'category',
              ordered_ids: orderedIds
            })
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.message || 'Failed to save folder order');
          showToast('✓ Folder order updated', 'success');
        } catch (err) {
          showToast('Error saving folder order: ' + err.message, 'error');
        }
      }
    });
  });
}

// Drag & Drop for Subcategory Folders within Category
function initSubcategoryDragDrop() {
  document.querySelectorAll('.admin-sub-grid').forEach(grid => {
    let draggedSub = null;

    grid.querySelectorAll('.admin-sub-card').forEach(card => {
      card.setAttribute('draggable', 'true');

      card.addEventListener('dragstart', function (e) {
        draggedSub = this;
        this.style.opacity = '0.4';
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', this.dataset.subId || '');
      });

      card.addEventListener('dragover', function (e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        if (!draggedSub || draggedSub === this) return;

        const bounding = this.getBoundingClientRect();
        const offset = bounding.y + (bounding.height / 2);
        if (e.clientY - offset > 0) {
          this.after(draggedSub);
        } else {
          this.before(draggedSub);
        }
      });

      card.addEventListener('dragend', async function () {
        this.style.opacity = '1';
        draggedSub = null;

        const cards = grid.querySelectorAll('.admin-sub-card');
        const orderedIds = [];
        cards.forEach((c, idx) => {
          const badge = c.querySelector('.admin-sub-seq-badge');
          if (badge) badge.textContent = `#${idx + 1}`;
          if (c.dataset.subId) orderedIds.push(c.dataset.subId);
        });

        if (orderedIds.length > 0) {
          showToast('Saving sub-folder order...', 'info');
          try {
            const res = await fetch(`/admin/instances/${instanceId}/reorder`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                type: 'subcategory',
                ordered_ids: orderedIds
              })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.message || 'Failed to save sub-folder order');
            showToast('✓ Sub-folder order updated', 'success');
          } catch (err) {
            showToast('Error saving sub-folder order: ' + err.message, 'error');
          }
        }
      });
    });
  });
}

// Initialize on page load
initAssetTableDragDrop();
initFolderDragDrop();
initSubcategoryDragDrop();
