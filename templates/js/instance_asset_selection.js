/**
 * Asset selection for an app instance's assets page (admin + manager): table row checkboxes (.asset-checkbox)
 * and block-view card checkboxes (.asset-card-checkbox) share one selection. Swipe selection on the cards is
 * wired up in partials/instance_asset_view_toggle.html.
 */
const selectedAssetIds = new Set();

// Selects/deselects an asset in both the table row and its block-view card.
function setAssetSelected(assetId, isChecked) {
  document.querySelectorAll(`.asset-checkbox[value="${assetId}"], .asset-card-checkbox[value="${assetId}"]`).forEach(cb => {
    cb.checked = isChecked;
    const card = cb.closest('.asset-card');
    if (card) card.classList.toggle('card-selected', isChecked);
  });
  if (isChecked) {
    selectedAssetIds.add(assetId);
  } else {
    selectedAssetIds.delete(assetId);
  }
  updateAssetSelectionUI();
}

function onAssetCheckboxChange(checkbox) {
  setAssetSelected(checkbox.value, checkbox.checked);
}

function toggleSelectAllAssets(isChecked) {
  document.querySelectorAll('.asset-checkbox').forEach(cb => setAssetSelected(cb.value, isChecked));
}

function clearSelectedAssets() {
  [...selectedAssetIds].forEach(id => setAssetSelected(id, false));
}

function updateAssetSelectionUI() {
  const count = selectedAssetIds.size;
  const bar = document.getElementById('assetBulkActionsBar');
  const countSpan = document.getElementById('selectedAssetCount');
  const selectAll = document.getElementById('selectAllAssetsCheckbox');
  const allCbs = document.querySelectorAll('.asset-checkbox');

  if (countSpan) countSpan.textContent = count;
  if (bar) bar.style.display = count > 0 ? 'inline-flex' : 'none';
  if (selectAll) {
    selectAll.checked = (allCbs.length > 0 && count === allCbs.length);
    selectAll.indeterminate = (count > 0 && count < allCbs.length);
  }
}
