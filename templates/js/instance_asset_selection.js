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

// Blocking "working…" popup shown while an asset action runs. Native <dialog>.showModal() supplies the
// backdrop and blocks clicks; Esc is ignored so it can't be dismissed mid-request.
async function withLoading(message, fn) {
  let dlg = document.getElementById('assetLoadingDialog');
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.id = 'assetLoadingDialog';
    dlg.className = 'asset-loading-dialog';
    dlg.innerHTML = '<div class="asset-loading-spinner" aria-hidden="true"></div><p role="status"></p>';
    dlg.addEventListener('cancel', e => e.preventDefault());
    document.body.append(dlg);
  }
  dlg.querySelector('p').textContent = message;
  if (!dlg.open) dlg.showModal();
  try {
    return await fn();
  } finally {
    dlg.close();
  }
}

// Prevent HTML5 draggable parent cards (category/subcategory folders) from hijacking pointer clicks on inner buttons/controls.
(function initDraggableCardControlGuard() {
  const CARD_SELECTOR = '.manager-cat-card, .manager-sub-card, .admin-cat-card, .admin-sub-card, .folder-card, .instance-cat-card, .instance-sub-card, [data-draggable-card]';
  const CONTROL_SELECTOR = 'button, a, input, select, label, textarea, summary, [role="button"], .instance-cat-primary-actions, .instance-cat-toolbar, .instance-sub-actions, .instance-sub-footer';
  const suppressedCards = [];
  const enabledCards = [];

  function releaseEnabledCards() {
    while (enabledCards.length > 0) {
      enabledCards.pop().draggable = false;
    }
  }

  function restoreSuppressedCards() {
    while (suppressedCards.length > 0) {
      suppressedCards.pop().draggable = true;
    }
    releaseEnabledCards();
  }

  function handlePointerDown(e) {
    releaseEnabledCards();
    const el = e.target && e.target.nodeType === 1 ? e.target : (e.target ? e.target.parentElement : null);
    if (!el || !el.closest) return;

    const nearestCard = el.closest(CARD_SELECTOR);
    const ctrl = el.closest(CONTROL_SELECTOR);
    const innerOnclick = el.closest('[onclick]');
    const hitsControl = Boolean(ctrl || (innerOnclick && innerOnclick !== nearestCard));

    if (hitsControl) {
      let cur = el;
      while (cur) {
        if (cur.draggable === true) {
          cur.draggable = false;
          if (!cur.matches || !cur.matches(CARD_SELECTOR)) {
            suppressedCards.push(cur);
          }
        }
        cur = cur.parentElement;
      }
      return;
    }

    if (nearestCard) {
      nearestCard.draggable = true;
      enabledCards.push(nearestCard);
    }
  }

  document.addEventListener('pointerdown', handlePointerDown, true);
  document.addEventListener('mousedown', handlePointerDown, true);
  document.addEventListener('pointerup', restoreSuppressedCards, true);
  document.addEventListener('mouseup', restoreSuppressedCards, true);
  document.addEventListener('pointercancel', restoreSuppressedCards, true);
  document.addEventListener('dragend', restoreSuppressedCards, true);
  window.addEventListener('blur', restoreSuppressedCards);
  document.addEventListener('dragstart', (e) => {
    const el = e.target && e.target.nodeType === 1 ? e.target : (e.target ? e.target.parentElement : null);
    if (el && el.closest && el.closest('button, a, input, select, label, textarea')) {
      e.preventDefault();
    }
  }, true);
})();
