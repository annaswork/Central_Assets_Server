// Extracted from templates/manager/instances/content.html so browsers cache it instead of re-downloading it inline.
function switchTab(tab) {
  document.getElementById('sectionFolders').style.display = tab === 'folders' ? 'block' : 'none';
  document.getElementById('sectionAssets').style.display = tab === 'assets' ? 'block' : 'none';
  document.getElementById('tabBtnFolders').className = tab === 'folders' ? 'btn btn-primary' : 'btn btn-outlined';
  document.getElementById('tabBtnAssets').className = tab === 'assets' ? 'btn btn-primary' : 'btn btn-outlined';

  try {
    sessionStorage.setItem('manager_instance_tab_' + instanceId, tab);
    const url = new URL(window.location.href);
    url.searchParams.set('active_section', tab);
    url.searchParams.set('tab', tab);
    window.history.replaceState({}, '', url.toString());
  } catch (e) { }

  if (tab === 'assets') {
    const urlParams = new URLSearchParams(window.location.search);
    if (!urlParams.get('categoryId') && !urlParams.get('selected_cat')) {
      const catSelect = document.getElementById('managerCategoryFilter');
      if (catSelect && catSelect.value) {
        catSelect.value = '';
        filterManagerSubcategoryOptions('');
      }
    }
    if (!urlParams.get('subCategoryId') && !urlParams.get('selected_subcat')) {
      const subSelect = document.getElementById('managerSubCategoryFilter');
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

    const res = await fetch(`/manager/instances/${instanceId}/folders/create`, {
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
    const res = await fetch(`/manager/instances/${instanceId}/categories/${catId}`, { method: 'DELETE' });
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
    const res = await fetch(`/manager/instances/${instanceId}/subcategories/${subId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to detach sub-folder');
    window.location.reload();
  } catch (err) {
    alert('Error detaching sub-folder: ' + err.message);
  }
}

// --- Referenced Assets AJAX Filtering & Subcategory Dynamic Scoping (Manager) ---
function filterManagerSubcategoryOptions(selectedCatId) {
  const subSelect = document.getElementById('managerSubCategoryFilter');
  if (!subSelect) return;
  const currentSubVal = subSelect.value;
  let currentSubValid = false;

  const catSelect = document.getElementById('managerCategoryFilter');
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
  const superSel = document.getElementById('managerSuperAssetFilter');
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

function handleManagerCategoryFilterChange(catId) {
  filterManagerSubcategoryOptions(catId);
  applyManagerAssetFilters();
}

function handleManagerSubCategoryFilterChange(subSelect) {
  const opt = subSelect.options[subSelect.selectedIndex];
  const catSelect = document.getElementById('managerCategoryFilter');
  if (opt && opt.dataset.categoryId && catSelect && !catSelect.value) {
    catSelect.value = opt.dataset.categoryId;
    filterManagerSubcategoryOptions(opt.dataset.categoryId);
  }
  applyManagerAssetFilters();
}

function handleManagerAssetSearchSubmit(e) {
  if (e) e.preventDefault();
  applyManagerAssetFilters();
}

function handleManagerClearAssetFilters(e, clearType) {
  if (e) e.preventDefault();
  if (clearType !== 'search') {
    const superSel = document.getElementById('managerSuperAssetFilter');
    if (superSel) superSel.value = '';
    filterManagerCategoryOptionsBySuper();
  }
  if (clearType === 'search') {
    const qInp = document.getElementById('managerAssetSearchInput');
    if (qInp) qInp.value = '';
  } else if (clearType === 'filters') {
    const catSelect = document.getElementById('managerCategoryFilter');
    const subSelect = document.getElementById('managerSubCategoryFilter');
    const typeSelect = document.getElementById('managerTypeFilter');
    const sortSelect = document.getElementById('managerAssetSortSelect');
    if (catSelect) catSelect.value = '';
    if (subSelect) subSelect.value = '';
    if (typeSelect) typeSelect.value = '';
    if (sortSelect) sortSelect.value = 'sequence';
    filterManagerSubcategoryOptions('');
  } else {
    // all
    const catSelect = document.getElementById('managerCategoryFilter');
    const subSelect = document.getElementById('managerSubCategoryFilter');
    const typeSelect = document.getElementById('managerTypeFilter');
    const sortSelect = document.getElementById('managerAssetSortSelect');
    const qInp = document.getElementById('managerAssetSearchInput');
    if (catSelect) catSelect.value = '';
    if (subSelect) subSelect.value = '';
    if (typeSelect) typeSelect.value = '';
    if (sortSelect) sortSelect.value = 'sequence';
    if (qInp) qInp.value = '';
    filterManagerSubcategoryOptions('');
  }
  applyManagerAssetFilters();
}

// Super category scopes the category options (and through them the subcategory options)
function filterManagerCategoryOptionsBySuper() {
  const superSel = document.getElementById('managerSuperAssetFilter');
  const catSelect = document.getElementById('managerCategoryFilter');
  if (!catSelect) return;
  const superId = superSel ? superSel.value : '';
  Array.from(catSelect.options).forEach((opt, idx) => {
    if (idx === 0) return;
    const show = !superId || opt.dataset.superId === superId;
    opt.hidden = !show;
    opt.style.display = show ? '' : 'none';
  });
}

function handleManagerSuperFilterChange() {
  const catSelect = document.getElementById('managerCategoryFilter');
  const subSelect = document.getElementById('managerSubCategoryFilter');
  if (catSelect) catSelect.value = '';
  if (subSelect) subSelect.value = '';
  filterManagerCategoryOptionsBySuper();
  filterManagerSubcategoryOptions('');
  applyManagerAssetFilters();
}

async function applyManagerAssetFilters() {
  const catSelect = document.getElementById('managerCategoryFilter');
  const subSelect = document.getElementById('managerSubCategoryFilter');
  const typeSelect = document.getElementById('managerTypeFilter');
  const sortSelect = document.getElementById('managerAssetSortSelect');
  const qInput = document.getElementById('managerAssetSearchInput');

  const selectedCat = catSelect ? catSelect.value : '';
  const selectedSub = subSelect ? subSelect.value : '';
  const selectedType = typeSelect ? typeSelect.value : '';
  const selectedSort = sortSelect ? sortSelect.value : 'sequence';
  const selectedQ = qInput ? qInput.value.trim() : '';

  const params = new URLSearchParams();
  params.set('active_section', 'assets');
  params.set('tab', 'assets');
  const superSel = document.getElementById('managerSuperAssetFilter');
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

  const filterClearBtn = document.getElementById('managerAssetFilterClearBtn');
  const hasFilterActive = Boolean(selectedSuper || selectedCat || selectedSub || selectedType || (selectedSort && selectedSort !== 'sequence'));
  if (filterClearBtn) {
    filterClearBtn.style.display = hasFilterActive ? 'inline-flex' : 'none';
  }

  const searchClearBtn = document.getElementById('managerAssetSearchClearBtn');
  if (searchClearBtn) {
    searchClearBtn.style.display = selectedQ ? 'inline-flex' : 'none';
  }

  const container = document.getElementById('managerAssetTableContainer');
  if (container) container.style.opacity = '0.35';

  try {
    const res = await fetch(fetchUrl);
    if (!res.ok) throw new Error('Failed to fetch filtered manager assets');
    const htmlText = await res.text();
    const doc = new DOMParser().parseFromString(htmlText, 'text/html');

    const newContainer = doc.getElementById('managerAssetTableContainer');
    if (newContainer && container) {
      container.innerHTML = newContainer.innerHTML;
      // Re-mark still-selected assets in the freshly rendered rows/cards.
      [...selectedAssetIds].forEach(id => setAssetSelected(id, true));
    }

    const newTabBtn = doc.getElementById('tabBtnAssets');
    const curTabBtn = document.getElementById('tabBtnAssets');
    if (newTabBtn && curTabBtn) {
      curTabBtn.innerHTML = newTabBtn.innerHTML;
    }

    if (typeof initAssetDragDrop === 'function') {
      initAssetDragDrop();
    }
  } catch (err) {
    console.error('Error applying manager asset filters:', err);
  } finally {
    if (container) container.style.opacity = '1';
  }
}

const contentParams = new URLSearchParams(window.location.search);
if (!contentParams.get('categoryId') && !contentParams.get('selected_cat')) {
  const catFilter = document.getElementById('managerCategoryFilter');
  if (catFilter) catFilter.value = '';
}
if (!contentParams.get('subCategoryId') && !contentParams.get('selected_subcat')) {
  const subFilter = document.getElementById('managerSubCategoryFilter');
  if (subFilter) subFilter.value = '';
}

filterManagerCategoryOptionsBySuper();
const curMgrCatInit = document.getElementById('managerCategoryFilter');
if (curMgrCatInit && curMgrCatInit.value) {
  filterManagerSubcategoryOptions(curMgrCatInit.value);
} else {
  filterManagerSubcategoryOptions('');
}

// Restore saved tab if no query params present
const savedTab = sessionStorage.getItem('manager_instance_tab_' + instanceId);
if (!contentParams.has('tab') && !contentParams.has('active_section') && !contentParams.has('categoryId') && !contentParams.has('subCategoryId') && !contentParams.has('sort') && !contentParams.has('type') && !contentParams.has('q') && !contentParams.has('folder_cat') && !contentParams.has('folder_search') && !contentParams.has('folder_sort')) {
  if (savedTab === 'assets') {
    switchTab('assets');
  }
}

let importCategoriesLoaded = false;

function openImportModal() {
  const m = document.getElementById('importModal');
  m.style.display = 'flex';
  if (!importCategoriesLoaded) loadImportCategories();
}

async function loadImportCategories() {
  const list = document.getElementById('importCategoryList');
  const message = (text) => {
    const d = document.createElement('div');
    d.style.cssText = 'text-align:center; padding:2rem; color:var(--md-sys-color-on-surface-variant);';
    d.textContent = text;
    list.replaceChildren(d);
  };
  try {
    const res = await fetch(`/manager/instances/${instanceId}/picker/categories`);
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.message || 'Failed to load central categories');
    const items = data.items || [];
    importCategoriesLoaded = true;
    if (!items.length) return message('No central categories available.');
    list.replaceChildren(...items.map((c) => {
      const label = document.createElement('label');
      label.style.cssText = 'display:flex; align-items:center; gap:0.75rem; padding:0.65rem 0.85rem; border:1px solid var(--md-sys-color-outline-variant); border-radius:var(--radius-sm); cursor:pointer;';
      label.innerHTML = '<input type="checkbox" name="selected_categories" style="width:18px; height:18px;">'
        + '<span style="font-size:1.25rem;">📁</span>'
        + '<div style="flex:1;"><div style="font-weight:600; font-size:0.9rem;"></div>'
        + '<div style="font-size:0.75rem; color:var(--md-sys-color-outline);"></div></div>';
      label.querySelector('input').value = c.id;
      const [nameEl, metaEl] = label.querySelectorAll('div > div');
      nameEl.textContent = c.name;
      metaEl.textContent = `${c.subcategory_count || 0} sub-folders • ${c.asset_count || 0} assets in catalog`;
      return label;
    }));
  } catch (err) {
    message('Could not load central categories: ' + err.message + '. Close and reopen to retry.');
  }
}

function closeImportModal() {
  const m = document.getElementById('importModal');
  m.style.display = 'none';
}

async function submitImport() {
  const checkboxes = document.querySelectorAll('input[name="selected_categories"]:checked');
  const selectedIds = Array.from(checkboxes).map(cb => cb.value);

  if (selectedIds.length === 0) {
    alert('Please select at least one category to import.');
    return;
  }

  try {
    const res = await fetch(`/manager/instances/${instanceId}/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category_ids: selectedIds })
    });
    const data = await res.json();
    if (data.success) {
      window.location.reload();
    } else {
      alert('Import failed: ' + (data.error || 'Unknown error'));
    }
  } catch (err) {
    alert('Network error while importing.');
  }
}

// Floating Toast Notification Helper
function showToast(msg, type = 'info') {
  let toast = document.getElementById('managerInstanceToast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'managerInstanceToast';
    toast.style.cssText = 'position:fixed; bottom:24px; right:24px; z-index:99999; padding:0.75rem 1.25rem; border-radius:8px; font-size:0.875rem; font-weight:600; box-shadow:0 6px 20px rgba(0,0,0,0.4); pointer-events:none; transition:opacity 0.2s ease;';
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

// Asset Overrides: is_enabled, is_premium, sequence
async function updateAssetOverride(assetId, field, value) {
  const payload = {};
  payload[field] = value;
  showToast(`Saving asset ${field.replace('_', ' ')}...`, 'info');
  try {
    const res = await fetch(`/manager/instances/${instanceId}/assets/${assetId}/override`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || 'Failed to update asset override');
    showToast('✓ Asset updated successfully', 'success');
  } catch (err) {
    showToast('Error updating asset: ' + err.message, 'error');
  }
}

// Handle toggling Priced flag
// ponytail: one PATCH per selected asset (fine for a page of assets); add a bulk route if selections get large.
async function bulkSetAssetOverride(field, value) {
  const ids = [...selectedAssetIds];
  if (!ids.length) return;
  const results = await withLoading(`Updating ${ids.length} asset(s)…`, async () => {
    const r = await Promise.allSettled(ids.map(id =>
      fetch(`/manager/instances/${instanceId}/assets/${id}/override`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [field]: value })
      }).then(res => { if (!res.ok) throw new Error(res.status); })
    ));
    clearSelectedAssets();
    await applyManagerAssetFilters();
    return r;
  });
  const failed = results.filter(r => r.status === 'rejected').length;
  showToast(failed ? `Updated ${ids.length - failed} asset(s), ${failed} failed` : `Updated ${ids.length} asset(s)`, failed ? 'error' : 'success');
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
  showToast(isChecked ? 'Enabling priced (default 5 credits)...' : 'Disabling priced...', 'info');
  try {
    const res = await fetch(`/manager/instances/${instanceId}/assets/${assetId}/override`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || 'Failed to update asset override');
    showToast('✓ Priced setting updated', 'success');
  } catch (err) {
    showToast('Error updating priced flag: ' + err.message, 'error');
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
      const res = await fetch(`/manager/instances/${instanceId}/folders/${currentRenamingFolderType}/${currentRenamingAssetId}/override`, {
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
    showToast('Error renaming asset: ' + err.message, 'error');
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Changes';
    }
  }
}

// Handle changing Credits value
async function handleCreditsChange(assetId, val) {
  const creditsVal = Math.max(0, parseInt(val) || 0);
  showToast(`Saving credits (${creditsVal})...`, 'info');
  try {
    const res = await fetch(`/manager/instances/${instanceId}/assets/${assetId}/override`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rewarded_credits: creditsVal })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || 'Failed to update credits');
    showToast('✓ Credits updated successfully', 'success');
  } catch (err) {
    showToast('Error updating credits: ' + err.message, 'error');
  }
}

// --- Multiple Asset Selection & Bulk Tag Management ---
let targetSingleAssetId = null;

function openBulkTagsModal() {
  targetSingleAssetId = null;
  if (selectedAssetIds.size === 0) {
    showToast('Please select at least one asset first', 'error');
    return;
  }
  document.getElementById('tagModalTitle').textContent = 'Add Tags to Selected Assets';
  document.getElementById('tagModalSubtitle').innerHTML = `Applying tags to <strong>${selectedAssetIds.size}</strong> selected asset(s) in this app instance.`;
  document.getElementById('tagModalInput').value = '';
  const addRadio = document.querySelector('input[name="tagApplyMode"][value="add"]');
  if (addRadio) addRadio.checked = true;
  document.getElementById('addTagsModal').style.display = 'flex';
  setTimeout(() => {
    const inp = document.getElementById('tagModalInput');
    if (inp) inp.focus();
  }, 50);
}

function openSingleAssetTagModal(assetId, assetName) {
  targetSingleAssetId = assetId;
  document.getElementById('tagModalTitle').textContent = `Manage Tags for "${assetName}"`;
  document.getElementById('tagModalSubtitle').innerHTML = `Updating tags for <strong>${assetName}</strong> in this app instance.`;

  const wrap = document.getElementById(`assetTagsWrap_${assetId}`);
  let existingTags = [];
  if (wrap) {
    const badges = wrap.querySelectorAll('.badge');
    badges.forEach(b => existingTags.push(b.textContent.trim()));
  }
  document.getElementById('tagModalInput').value = existingTags.join(', ');
  const addRadio = document.querySelector('input[name="tagApplyMode"][value="add"]');
  if (addRadio) addRadio.checked = true;
  document.getElementById('addTagsModal').style.display = 'flex';
  setTimeout(() => {
    const inp = document.getElementById('tagModalInput');
    if (inp) inp.focus();
  }, 50);
}

function closeTagsModal() {
  document.getElementById('addTagsModal').style.display = 'none';
  targetSingleAssetId = null;
}

async function submitTagsModal() {
  const rawInput = document.getElementById('tagModalInput').value.trim();
  const modeEl = document.querySelector('input[name="tagApplyMode"]:checked');
  const mode = modeEl ? modeEl.value : 'add';

  const tags = rawInput.split(',').map(t => t.trim()).filter(t => t.length > 0);
  if (tags.length === 0 && mode !== 'replace') {
    showToast('Please enter at least one tag', 'error');
    return;
  }

  const assetIds = targetSingleAssetId ? [targetSingleAssetId] : Array.from(selectedAssetIds);
  if (assetIds.length === 0) {
    showToast('No assets selected', 'error');
    return;
  }

  const btn = document.getElementById('btnApplyTags');
  const origHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span>Saving...</span>';

  try {
    const res = await withLoading(`Applying tags to ${assetIds.length} asset(s)…`, () => fetch(`/manager/instances/${instanceId}/assets/bulk-tags`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        asset_ids: assetIds,
        tags: tags,
        mode: mode
      })
    }));
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || 'Failed to update tags');

    showToast(`✓ ${data.message || 'Tags updated successfully'}`, 'success');
    closeTagsModal();

    // Update DOM tags dynamically for each asset
    if (data.asset_tags) {
      for (const [aid, tList] of Object.entries(data.asset_tags)) {
        const wrap = document.getElementById(`assetTagsWrap_${aid}`);
        if (wrap) {
          const assetName = wrap.dataset.assetName || 'asset';
          let html = '';
          if (tList && tList.length > 0) {
            tList.forEach(t => {
              html += `<span class="badge" style="background:var(--md-sys-color-secondary-container, #e2e8f0); color:var(--md-sys-color-on-secondary-container, #1e293b); font-size:0.75rem; padding:0.12rem 0.45rem; border-radius:10px;">${t}</span> `;
            });
          } else {
            html = `<span class="no-tags-hint" style="color:var(--md-sys-color-outline); font-size:0.75rem; font-style:italic;">No tags</span> `;
          }
          html += `<button type="button" class="btn-edit-tags-single" onclick="openSingleAssetTagModal('${aid}', '${assetName.replace(/'/g, "\\'")}')" title="Edit tags for this asset" style="background:none; border:none; color:var(--md-sys-color-primary); cursor:pointer; font-size:0.8rem; padding:0.1rem 0.3rem; border-radius:4px; opacity:0.7;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.7'">✏️</button>`;
          wrap.innerHTML = html;
        }
      }
    }

    clearSelectedAssets();
  } catch (err) {
    showToast('Error applying tags: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = origHtml;
  }
}

// Handle typing sequence number directly into asset Seq input
window.handleAssetSeqChange = function (assetId, newPosition) {
  const tbody = document.getElementById('managerAssetTbody');
  if (!tbody) return;
  const rows = Array.from(tbody.querySelectorAll('.manager-asset-row'));
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

  // Renumber all rows to natural 1, 2, 3...
  const newRows = tbody.querySelectorAll('.manager-asset-row');
  const orderedIds = [];
  newRows.forEach((r, idx) => {
    const inp = r.querySelector('.asset-seq-input');
    if (inp) inp.value = assetOffset() + idx + 1;
    if (r.dataset.assetId) orderedIds.push(r.dataset.assetId);
  });

  saveAssetOrder(orderedIds);
};

// Rows on page N continue the sequence of earlier pages
function assetOffset() {
  const tbody = document.getElementById('managerAssetTbody');
  return parseInt((tbody && tbody.dataset.offset) || '0', 10);
}

async function saveAssetOrder(orderedIds) {
  if (!orderedIds || orderedIds.length === 0) return;
  showToast('Saving asset sequence order...', 'info');
  try {
    const res = await withLoading('Saving asset order…', () => fetch(`/manager/instances/${instanceId}/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'asset',
        start: assetOffset(),
        ordered_ids: orderedIds
      })
    }));
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || 'Failed to save asset order');
    showToast('✓ Asset sequence updated', 'success');
  } catch (err) {
    showToast('Error saving asset order: ' + err.message, 'error');
  }
}

// Category Reordering (Up/Down)
window.moveCategory = function (catId, direction) {
  const container = document.getElementById('managerCategoriesContainer');
  if (!container) return;
  const cards = Array.from(container.querySelectorAll('.manager-cat-card'));
  const idx = cards.findIndex(c => c.dataset.catId === catId);
  if (idx === -1) return;

  const targetIdx = idx + direction;
  if (targetIdx < 0 || targetIdx >= cards.length) return;

  const movingCard = cards[idx];
  const targetCard = cards[targetIdx];

  if (direction > 0) {
    targetCard.after(movingCard);
  } else {
    targetCard.before(movingCard);
  }

  // Update badges
  const updatedCards = container.querySelectorAll('.manager-cat-card');
  const orderedIds = [];
  updatedCards.forEach((c, i) => {
    const badge = c.querySelector('.cat-seq-badge');
    if (badge) badge.textContent = `#${i + 1}`;
    if (c.dataset.catId) orderedIds.push(c.dataset.catId);
  });

  saveCategoryOrder(orderedIds);
};

async function saveCategoryOrder(orderedIds) {
  if (!orderedIds || orderedIds.length === 0) return;
  showToast('Saving category sequence...', 'info');
  try {
    const res = await fetch(`/manager/instances/${instanceId}/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'category',
        ordered_ids: orderedIds
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || 'Failed to save category order');
    showToast('✓ Category sequence updated', 'success');
  } catch (err) {
    showToast('Error saving category order: ' + err.message, 'error');
  }
}

// Subcategory Reordering (Up/Down)
window.moveSubcategory = function (subId, parentCatId, direction) {
  const grid = document.querySelector(`.subcategories-grid[data-parent-cat-id="${parentCatId}"]`);
  if (!grid) return;
  const cards = Array.from(grid.querySelectorAll('.manager-sub-card'));
  const idx = cards.findIndex(c => c.dataset.subId === subId);
  if (idx === -1) return;

  const targetIdx = idx + direction;
  if (targetIdx < 0 || targetIdx >= cards.length) return;

  const movingCard = cards[idx];
  const targetCard = cards[targetIdx];

  if (direction > 0) {
    targetCard.after(movingCard);
  } else {
    targetCard.before(movingCard);
  }

  // Update badges
  const updatedCards = grid.querySelectorAll('.manager-sub-card');
  const orderedIds = [];
  updatedCards.forEach((c, i) => {
    const badge = c.querySelector('.sub-seq-badge');
    if (badge) badge.textContent = `#${i + 1}`;
    if (c.dataset.subId) orderedIds.push(c.dataset.subId);
  });

  saveSubcategoryOrder(orderedIds);
};

async function saveSubcategoryOrder(orderedIds) {
  if (!orderedIds || orderedIds.length === 0) return;
  showToast('Saving subcategory sequence...', 'info');
  try {
    const res = await fetch(`/manager/instances/${instanceId}/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'subcategory',
        ordered_ids: orderedIds
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || 'Failed to save subcategory order');
    showToast('✓ Subcategory sequence updated', 'success');
  } catch (err) {
    showToast('Error saving subcategory order: ' + err.message, 'error');
  }
}

// 1. Drag & Drop for Asset Table Rows
function initAssetDragDrop() {
  const tbody = document.getElementById('managerAssetTbody');
  if (!tbody) return;
  let draggedRow = null;

  tbody.querySelectorAll('.manager-asset-row').forEach(row => {
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

      const rows = tbody.querySelectorAll('.manager-asset-row');
      const orderedIds = [];
      rows.forEach((r, idx) => {
        const inp = r.querySelector('.asset-seq-input');
        if (inp) inp.value = assetOffset() + idx + 1;
        if (r.dataset.assetId) orderedIds.push(r.dataset.assetId);
      });

      saveAssetOrder(orderedIds);
    });
  });
}

// 2. Drag & Drop for Category Folders
function initCategoryDragDrop() {
  const container = document.getElementById('managerCategoriesContainer');
  if (!container) return;
  let draggedCat = null;

  container.querySelectorAll('.manager-cat-card').forEach(card => {
    card.addEventListener('dragstart', function (e) {
      draggedCat = this;
      this.style.opacity = '0.4';
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', this.dataset.catId || '');
    });

    card.addEventListener('dragover', function (e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (!draggedCat || draggedCat === this) return;

      const bounding = this.getBoundingClientRect();
      const offset = bounding.y + (bounding.height / 2);
      if (e.clientY - offset > 0) {
        this.after(draggedCat);
      } else {
        this.before(draggedCat);
      }
    });

    card.addEventListener('dragend', function () {
      this.style.opacity = '1';
      draggedCat = null;

      const cards = container.querySelectorAll('.manager-cat-card');
      const orderedIds = [];
      cards.forEach((c, idx) => {
        const badge = c.querySelector('.cat-seq-badge');
        if (badge) badge.textContent = `#${idx + 1}`;
        if (c.dataset.catId) orderedIds.push(c.dataset.catId);
      });

      saveCategoryOrder(orderedIds);
    });
  });
}

// 3. Drag & Drop for Subcategories within Grid
function initSubcategoryDragDrop() {
  document.querySelectorAll('.subcategories-grid').forEach(grid => {
    let draggedSub = null;

    grid.querySelectorAll('.manager-sub-card').forEach(card => {
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

      card.addEventListener('dragend', function () {
        this.style.opacity = '1';
        draggedSub = null;

        const cards = grid.querySelectorAll('.manager-sub-card');
        const orderedIds = [];
        cards.forEach((c, idx) => {
          const badge = c.querySelector('.sub-seq-badge');
          if (badge) badge.textContent = `#${idx + 1}`;
          if (c.dataset.subId) orderedIds.push(c.dataset.subId);
        });

        saveSubcategoryOrder(orderedIds);
      });
    });
  });
}

// Initialize all drag & drop on load
initAssetDragDrop();
initCategoryDragDrop();
initSubcategoryDragDrop();

// --- Tier & Frequency Distribution ---

const tierDistributionMemory = {}; // in-memory cache keyed by scopeId

function openTierDistributionModalFromElem(btn) {
  if (!btn) return;
  const scopeType = btn.dataset.scopeType || 'category';
  const scopeId = btn.dataset.scopeId || '';
  const scopeName = btn.dataset.scopeName || '';
  const totalCount = parseInt(btn.dataset.totalCount) || 0;
  const targetType = btn.dataset.targetType || 'subcategory';
  let savedSettings = null;
  if (btn.dataset.tierSettings) {
    try {
      savedSettings = JSON.parse(btn.dataset.tierSettings);
    } catch (_) {}
  }
  openTierDistributionModal(scopeType, scopeId, scopeName, totalCount, targetType, savedSettings);
}

function inferSettingsFromTierSequence(tierList, total, maxAllowed) {
  if (!tierList || tierList.length === 0) return null;

  let premCount = 0;
  let rewCount = 0;
  let normCount = 0;

  for (const t of tierList) {
    if (t === 'premium') premCount++;
    else if (t === 'rewarded') rewCount++;
    else normCount++;
  }

  if (premCount === 0 && rewCount === 0) {
    return null;
  }

  // Find consecutive batch runs
  const normRuns = [];
  const premRuns = [];
  const rewRuns = [];

  let currentTier = null;
  let currentLen = 0;

  for (const t of tierList) {
    if (t === currentTier) {
      currentLen++;
    } else {
      if (currentTier === 'normal') normRuns.push(currentLen);
      else if (currentTier === 'premium') premRuns.push(currentLen);
      else if (currentTier === 'rewarded') rewRuns.push(currentLen);
      currentTier = t;
      currentLen = 1;
    }
  }
  if (currentTier === 'normal') normRuns.push(currentLen);
  else if (currentTier === 'premium') premRuns.push(currentLen);
  else if (currentTier === 'rewarded') rewRuns.push(currentLen);

  const nFreq = normRuns.length > 0 ? normRuns[0] : 3;
  const pFreq = premRuns.length > 0 ? premRuns[0] : 2;
  const rFreq = rewRuns.length > 0 ? rewRuns[0] : 1;

  const boundedPrem = Math.min(premCount, maxAllowed);
  const boundedRew = Math.min(rewCount, Math.max(0, maxAllowed - boundedPrem));

  return {
    premium_count: boundedPrem,
    rewarded_count: boundedRew,
    normal_frequency: nFreq,
    premium_frequency: pFreq,
    rewarded_frequency: rFreq,
  };
}

function openTierDistributionModal(scopeType, scopeId, scopeName, totalCount, targetType, passedSettings = null) {
  const total = parseInt(totalCount) || 0;
  if (total <= 0) {
    alert(`No ${targetType}s found in "${scopeName}" to distribute tiers across.`);
    return;
  }

  const modal = document.getElementById('tierDistributionModal');
  if (!modal) return;

  document.getElementById('tierDistScopeType').value = scopeType;
  document.getElementById('tierDistScopeId').value = scopeId;
  document.getElementById('tierDistTargetType').value = targetType;
  document.getElementById('tierDistTotalCount').value = total;

  const targetLabel = targetType === 'subcategory' ? 'Sub-folders' : 'Assets';
  const scopeLabel = scopeType === 'category' ? 'Category' : 'Sub-folder';

  document.getElementById('tierDistModalTitle').innerHTML = `⚡ Distribute Tiers in ${scopeName}`;
  document.getElementById('tierDistModalSubtitle').textContent = `Target: ${targetLabel} in this ${scopeLabel} (Total: ${total} items)`;

  document.getElementById('tierDistTotalNotice').textContent = total;
  const maxAllowed = Math.max(0, total - 1);
  document.getElementById('tierDistMaxNotice').textContent = maxAllowed;

  // Retrieve prior settings: Memory cache -> Passed/Persisted settings -> DOM count fallback -> defaults
  let prior = tierDistributionMemory[scopeId] || passedSettings;
  if (!prior || Object.keys(prior).length === 0) {
    // If not saved, see if we can derive from current visible DOM elements
    if (scopeType === 'category' && targetType === 'subcategory') {
      let catCard = document.querySelector(`.folder-card[data-cat-id="${scopeId}"], .manager-cat-card[data-cat-id="${scopeId}"]`);
      if (!catCard) {
        catCard = document.querySelector(`[data-parent-cat-id="${scopeId}"]`);
      }
      if (catCard) {
        const subCards = catCard.querySelectorAll('.admin-sub-card, .sub-folder-card');
        if (subCards.length > 0) {
          const tierList = [];
          subCards.forEach(card => {
            const premCb = card.querySelector('[data-folder-premium-cb]');
            const rewCb = card.querySelector('[data-folder-rewarded-cb]');
            let isPrem = premCb ? premCb.checked : false;
            let isRew = rewCb ? rewCb.checked : false;
            if (!premCb && !rewCb) {
              isPrem = card.querySelector('.asset-card-premium-pill:not(.asset-card-rewarded-pill):not([style*="display: none"]):not([hidden])') !== null;
              isRew = card.querySelector('.asset-card-rewarded-pill:not([style*="display: none"]):not([hidden])') !== null;
            }
            if (isPrem) tierList.push('premium');
            else if (isRew) tierList.push('rewarded');
            else tierList.push('normal');
          });
          prior = inferSettingsFromTierSequence(tierList, total, maxAllowed);
        }
      }
    } else if (targetType === 'asset') {
      const rows = document.querySelectorAll('#reorderableTable tbody tr[data-asset-id]');
      if (rows.length > 0) {
        const tierList = [];
        rows.forEach(r => {
          const premCb = r.querySelector('input[onchange*="is_premium"]');
          const rewCb = r.querySelector('input[onchange*="is_rewarded"]');
          const isPrem = premCb ? premCb.checked : false;
          const isRew = rewCb ? rewCb.checked : false;
          if (isPrem) tierList.push('premium');
          else if (isRew) tierList.push('rewarded');
          else tierList.push('normal');
        });
        prior = inferSettingsFromTierSequence(tierList, total, maxAllowed);
      }
    }
  }

  let defaultPrem = Math.min(Math.floor(total / 3), maxAllowed);
  let defaultRew = 0;
  let defaultNFreq = 3;
  let defaultPFreq = 2;
  let defaultRFreq = 1;

  if (prior && (prior.premium_count !== undefined || prior.rewarded_count !== undefined)) {
    const savedP = parseInt(prior.premium_count) || 0;
    defaultPrem = Math.min(savedP, maxAllowed);
    const savedR = parseInt(prior.rewarded_count) || 0;
    defaultRew = Math.min(savedR, Math.max(0, maxAllowed - defaultPrem));
    defaultNFreq = parseInt(prior.normal_frequency) || 3;
    defaultPFreq = parseInt(prior.premium_frequency) || 2;
    defaultRFreq = parseInt(prior.rewarded_frequency) || 1;
  }

  document.getElementById('tierDistPremiumCount').value = defaultPrem;
  document.getElementById('tierDistRewardedCount').value = defaultRew;
  document.getElementById('tierDistNormalFreq').value = defaultNFreq;
  document.getElementById('tierDistPremiumFreq').value = defaultPFreq;
  document.getElementById('tierDistRewardedFreq').value = defaultRFreq;

  onTierDistCountChange();
  modal.style.display = 'flex';
}

function closeTierDistributionModal() {
  const modal = document.getElementById('tierDistributionModal');
  if (modal) modal.style.display = 'none';
}

function handleTierDistBackdropClick(event) {
  if (event.target.id === 'tierDistributionModal') {
    closeTierDistributionModal();
  }
}

function onTierDistCountChange() {
  const total = parseInt(document.getElementById('tierDistTotalCount').value) || 0;
  const maxAllowed = Math.max(0, total - 1);

  const premInput = document.getElementById('tierDistPremiumCount');
  const rewInput = document.getElementById('tierDistRewardedCount');

  let premVal = parseInt(premInput.value);
  if (isNaN(premVal) || premVal < 0) {
    premVal = 0;
  } else if (premVal > maxAllowed) {
    premVal = maxAllowed;
    premInput.value = premVal;
  }
  premInput.max = maxAllowed;
  document.getElementById('tierDistPremMaxHint').textContent = maxAllowed;

  const maxRewarded = Math.max(0, maxAllowed - premVal);
  let rewVal = parseInt(rewInput.value);
  if (isNaN(rewVal) || rewVal < 0) {
    rewVal = 0;
  } else if (rewVal > maxRewarded) {
    rewVal = maxRewarded;
    rewInput.value = rewVal;
  }
  rewInput.max = maxRewarded;
  document.getElementById('tierDistRewMaxHint').textContent = maxRewarded;

  const normalCount = Math.max(1, total - premVal - rewVal);
  document.getElementById('tierDistNormalCount').textContent = normalCount;

  const rewBox = document.getElementById('tierDistRewFreqBox');
  if (rewBox) {
    rewBox.style.opacity = rewVal > 0 ? '1' : '0.4';
    const rInput = document.getElementById('tierDistRewardedFreq');
    if (rInput) rInput.disabled = (rewVal <= 0);
  }

  updateTierPreviewRibbon();
}

function onTierDistFreqChange() {
  const nFreqInput = document.getElementById('tierDistNormalFreq');
  const pFreqInput = document.getElementById('tierDistPremiumFreq');
  const rFreqInput = document.getElementById('tierDistRewardedFreq');

  let nFreq = parseInt(nFreqInput.value);
  if (!isNaN(nFreq) && nFreq < 1) nFreqInput.value = 1;
  let pFreq = parseInt(pFreqInput.value);
  if (!isNaN(pFreq) && pFreq < 1) pFreqInput.value = 1;
  let rFreq = parseInt(rFreqInput.value);
  if (!isNaN(rFreq) && rFreq < 1) rFreqInput.value = 1;

  updateTierPreviewRibbon();
}

function generateClientTierSequence(total, premCount, rewCount, nFreq, pFreq, rFreq) {
  if (total <= 0) return [];
  let remPrem = premCount;
  let remRew = rewCount;
  let remNorm = Math.max(0, total - premCount - rewCount);

  const res = [];
  while (res.length < total) {
    const nBatch = Math.min(nFreq, remNorm, total - res.length);
    for (let i = 0; i < nBatch; i++) {
      res.push('normal');
      remNorm--;
    }
    if (remPrem > 0 && res.length < total) {
      const pBatch = Math.min(pFreq, remPrem, total - res.length);
      for (let i = 0; i < pBatch; i++) {
        res.push('premium');
        remPrem--;
      }
    }
    if (remRew > 0 && res.length < total) {
      const rBatch = Math.min(rFreq, remRew, total - res.length);
      for (let i = 0; i < rBatch; i++) {
        res.push('rewarded');
        remRew--;
      }
    }
    if (remPrem === 0 && remRew === 0) {
      while (res.length < total) {
        res.push('normal');
        remNorm--;
      }
    }
  }
  return res;
}

function updateTierPreviewRibbon() {
  const total = parseInt(document.getElementById('tierDistTotalCount').value) || 0;
  const premCount = parseInt(document.getElementById('tierDistPremiumCount').value) || 0;
  const rewCount = parseInt(document.getElementById('tierDistRewardedCount').value) || 0;
  const normalCount = Math.max(1, total - premCount - rewCount);

  const nFreq = parseInt(document.getElementById('tierDistNormalFreq').value) || 3;
  const pFreq = parseInt(document.getElementById('tierDistPremiumFreq').value) || 2;
  const rFreq = parseInt(document.getElementById('tierDistRewardedFreq').value) || 1;

  const sequence = generateClientTierSequence(total, premCount, rewCount, nFreq, pFreq, rFreq);
  const ribbon = document.getElementById('tierDistPreviewRibbon');
  if (!ribbon) return;

  ribbon.innerHTML = '';
  sequence.forEach((tier, idx) => {
    const pill = document.createElement('span');
    pill.style.cssText = 'flex-shrink:0; font-size:0.75rem; font-weight:600; padding:0.25rem 0.6rem; border-radius:12px; display:inline-flex; align-items:center; gap:0.25rem; white-space:nowrap;';
    if (tier === 'premium') {
      pill.style.background = '#f59e0b';
      pill.style.color = '#000';
      pill.innerHTML = `⭐ #${idx + 1} Prem`;
    } else if (tier === 'rewarded') {
      pill.style.background = '#10b981';
      pill.style.color = '#fff';
      pill.innerHTML = `🎁 #${idx + 1} Rew`;
    } else {
      pill.style.background = 'var(--md-sys-color-surface-container-high, #313244)';
      pill.style.color = 'var(--md-sys-color-on-surface, #cdd6f4)';
      pill.innerHTML = `#${idx + 1} Free`;
    }
    ribbon.appendChild(pill);
  });

  const pPct = total > 0 ? Math.round((premCount / total) * 100) : 0;
  const rPct = total > 0 ? Math.round((rewCount / total) * 100) : 0;
  const nPct = total > 0 ? Math.round((normalCount / total) * 100) : 0;

  const badgeElem = document.getElementById('tierDistSummaryBadge');
  if (badgeElem) {
    badgeElem.textContent = `Pattern: ${nFreq} Free → ${pFreq} Prem${rewCount > 0 ? ` → ${rFreq} Rew` : ''}`;
  }
  const textElem = document.getElementById('tierDistSummaryText');
  if (textElem) {
    textElem.textContent = `Distribution breakdown: ${normalCount} Free (${nPct}%), ${premCount} Premium (${pPct}%), ${rewCount} Rewarded (${rPct}%) — Total: ${total}`;
  }
}

function openTierDistributionForCurrentFilter() {
  const subSelect = document.getElementById('managerSubCategoryFilter');
  const catSelect = document.getElementById('managerCategoryFilter');

  if (subSelect && subSelect.value) {
    const opt = subSelect.options[subSelect.selectedIndex];
    const name = opt ? opt.text : 'Sub-folder';
    const totalCount = parseInt(window.lastAssetTotal || document.querySelectorAll('#reorderableTable tbody tr').length || 10);
    let prior = tierDistributionMemory[subSelect.value] || null;
    if (!prior && opt && opt.dataset.tierSettings) {
      try {
        const parsed = JSON.parse(opt.dataset.tierSettings);
        if (parsed && Object.keys(parsed).length > 0) prior = parsed;
      } catch (_) {}
    }
    openTierDistributionModal('subcategory', subSelect.value, name, totalCount, 'asset', prior);
  } else if (catSelect && catSelect.value) {
    const opt = catSelect.options[catSelect.selectedIndex];
    const name = opt ? opt.text : 'Category';
    const totalCount = parseInt(window.lastAssetTotal || document.querySelectorAll('#reorderableTable tbody tr').length || 10);
    let prior = tierDistributionMemory[catSelect.value] || null;
    if (!prior && opt && opt.dataset.tierSettings) {
      try {
        const parsed = JSON.parse(opt.dataset.tierSettings);
        if (parsed && Object.keys(parsed).length > 0) prior = parsed;
      } catch (_) {}
    }
    openTierDistributionModal('category', catSelect.value, name, totalCount, 'asset', prior);
  } else {
    alert('Please select a Category or Sub-folder in the filters to distribute tiers.');
  }
}

async function applyTierDistribution() {
  const btn = document.getElementById('tierDistApplyBtn');
  const originalText = btn.textContent;

  const scopeType = document.getElementById('tierDistScopeType').value;
  const scopeId = document.getElementById('tierDistScopeId').value;
  const targetType = document.getElementById('tierDistTargetType').value;

  const premiumCount = parseInt(document.getElementById('tierDistPremiumCount').value) || 0;
  const rewardedCount = parseInt(document.getElementById('tierDistRewardedCount').value) || 0;
  const normalFreq = parseInt(document.getElementById('tierDistNormalFreq').value) || 3;
  const premiumFreq = parseInt(document.getElementById('tierDistPremiumFreq').value) || 2;
  const rewardedFreq = parseInt(document.getElementById('tierDistRewardedFreq').value) || 1;

  btn.disabled = true;
  btn.textContent = 'Applying...';

  try {
    const res = await fetch(`/manager/instances/${instanceId}/distribute-tiers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scope_type: scopeType,
        scope_id: scopeId,
        target_type: targetType,
        premium_count: premiumCount,
        rewarded_count: rewardedCount,
        normal_frequency: normalFreq,
        premium_frequency: premiumFreq,
        rewarded_frequency: rewardedFreq
      })
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.message || data.detail || 'Failed to distribute tiers');

    closeTierDistributionModal();
    if (typeof showToast === 'function') {
      showToast(`✓ Successfully distributed ${premiumCount} premium and ${rewardedCount} rewarded items!`, 'success');
    } else {
      alert(`Successfully distributed ${premiumCount} premium and ${rewardedCount} rewarded items!`);
    }

    // Save into memory cache
    const savedSettings = {
      target_type: targetType,
      premium_count: premiumCount,
      rewarded_count: rewardedCount,
      normal_frequency: normalFreq,
      premium_frequency: premiumFreq,
      rewarded_frequency: rewardedFreq
    };
    tierDistributionMemory[scopeId] = savedSettings;

    // Update dataset on any button matching this scopeId
    document.querySelectorAll(`.btn-distribute-tiers[data-scope-id="${scopeId}"]`).forEach(b => {
      b.dataset.tierSettings = JSON.stringify(savedSettings);
    });

    // Update dataset on any filter option matching this scopeId
    document.querySelectorAll(`select option[value="${scopeId}"]`).forEach(opt => {
      opt.dataset.tierSettings = JSON.stringify(savedSettings);
    });

    // Update UI elements in DOM if visible
    if (data.data && data.data.assignments) {
      data.data.assignments.forEach(item => {
        // Update subcategory pills
        const premPills = document.querySelectorAll(`[data-premium-tag="${item.id}"]`);
        premPills.forEach(p => {
          p.hidden = !item.is_premium;
          p.style.display = item.is_premium ? 'inline-block' : 'none';
        });

        const rewPills = document.querySelectorAll(`[data-rewarded-tag="${item.id}"]`);
        rewPills.forEach(p => {
          p.hidden = !item.is_rewarded;
          p.style.display = item.is_rewarded ? 'inline-block' : 'none';
        });

        // Update folder checkboxes if present
        const premCbs = document.querySelectorAll(`[data-folder-premium-cb="${item.id}"]`);
        premCbs.forEach(cb => { cb.checked = item.is_premium; });
        const rewCbs = document.querySelectorAll(`[data-folder-rewarded-cb="${item.id}"]`);
        rewCbs.forEach(cb => { cb.checked = item.is_rewarded; });

        // Update table checkboxes if on assets view
        const row = document.querySelector(`tr[data-asset-id="${item.id}"]`);
        if (row) {
          const premCb = row.querySelector('input[onchange*="is_premium"]');
          if (premCb) premCb.checked = item.is_premium;
          const rewCb = row.querySelector('input[onchange*="is_rewarded"]');
          if (rewCb) rewCb.checked = item.is_rewarded;
        }
      });
    }

    if (typeof applyManagerAssetFilters === 'function') {
      await applyManagerAssetFilters();
    }
  } catch (err) {
    alert('Error applying tier distribution: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}
