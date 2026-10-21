// Extracted from templates/partials/reorder_modal.html so browsers cache it instead of re-downloading it inline.
(function() {
  // Reorder State
  let reorderType = 'category'; // 'category' | 'subcategory' | 'asset'
  let currentItems = [];
  let initialItemsOrder = [];
  let hasUnsavedChanges = false;
  let dragSrcIndex = null;

  // Cached lists for filters
  let cachedCategories = [];
  let cachedSubcategories = [];

  window.openCentralReorderModal = async function(type, options = {}) {
    reorderType = type;
    hasUnsavedChanges = false;
    document.getElementById('reorderUnsavedIndicator').style.display = 'none';
    document.getElementById('reorderResetBtn').style.display = 'none';
    document.getElementById('reorderSearchInput').value = '';

    // Setup Titles
    const titleEl = document.getElementById('reorderModalTitle');
    const subtitleEl = document.getElementById('reorderModalSubtitle');
    const catFilterWrap = document.getElementById('reorderCatFilterWrap');
    const subFilterWrap = document.getElementById('reorderSubFilterWrap');

    if (type === 'category') {
      titleEl.textContent = 'Reorder Categories';
      subtitleEl.textContent = 'Drag cards or type sequence numbers to set the global category order.';
      catFilterWrap.style.display = 'none';
      subFilterWrap.style.display = 'none';
    } else if (type === 'subcategory') {
      titleEl.textContent = 'Reorder Subcategories';
      subtitleEl.textContent = 'Filter by category, then drag or type sequence numbers to reorder subcategories.';
      catFilterWrap.style.display = 'block';
      subFilterWrap.style.display = 'none';
    } else if (type === 'asset') {
      titleEl.textContent = 'Reorder Assets';
      subtitleEl.textContent = 'Filter by category and subcategory, then drag or type sequence numbers to reorder assets.';
      catFilterWrap.style.display = 'block';
      subFilterWrap.style.display = 'block';
    }

    // Open Modal UI
    const modal = document.getElementById('centralReorderModal');
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';

    // Populate category & subcategory dropdowns
    await populateReorderFilters(options);

    // Fetch and render items
    await fetchAndRenderReorderItems();
  };

  window.closeCentralReorderModal = function() {
    if (hasUnsavedChanges) {
      if (!confirm("You have unsaved sequence changes. Are you sure you want to close?")) {
        return;
      }
    }
    const modal = document.getElementById('centralReorderModal');
    modal.style.display = 'none';
    document.body.style.overflow = '';
  };

  window.handleReorderModalBackdrop = function(e) {
    if (e.target.id === 'centralReorderModal') {
      closeCentralReorderModal();
    }
  };

  async function populateReorderFilters(options) {
    // 1. Fetch categories if needed
    if (reorderType === 'subcategory' || reorderType === 'asset') {
      if (!cachedCategories || cachedCategories.length === 0) {
        try {
          const res = await fetch('/admin/api/reorder/items?type=category');
          if (res.ok) {
            const data = await res.json();
            cachedCategories = data.items || [];
          }
        } catch (e) {
          console.error("Failed to load categories for reorder filter:", e);
        }
      }

      const catSelect = document.getElementById('reorderCategorySelect');
      catSelect.innerHTML = '';
      if (reorderType === 'subcategory') {
        catSelect.innerHTML += '<option value="">All Categories</option>';
      }

      cachedCategories.forEach(cat => {
        const opt = document.createElement('option');
        opt.value = cat.id;
        opt.textContent = cat.name;
        catSelect.appendChild(opt);
      });

      // Pre-select category if provided or in active page
      if (options.categoryId) {
        catSelect.value = options.categoryId;
      } else if (reorderType === 'asset' && cachedCategories.length > 0) {
        catSelect.value = cachedCategories[0].id;
      }
    }

    // 2. Fetch subcategories if needed (for asset)
    if (reorderType === 'asset') {
      await updateSubcategoryOptions(options.subCategoryId);
    }
  }

  async function updateSubcategoryOptions(preselectSubId = null) {
    const catSelect = document.getElementById('reorderCategorySelect');
    const subSelect = document.getElementById('reorderSubcategorySelect');
    const selectedCatId = catSelect.value;

    subSelect.innerHTML = '<option value="">All Subcategories in Category</option>';
    if (!selectedCatId) return;

    try {
      const res = await fetch(`/admin/api/reorder/items?type=subcategory&categoryId=${encodeURIComponent(selectedCatId)}`);
      if (res.ok) {
        const data = await res.json();
        cachedSubcategories = data.items || [];
        cachedSubcategories.forEach(sub => {
          const opt = document.createElement('option');
          opt.value = sub.id;
          opt.textContent = sub.name;
          subSelect.appendChild(opt);
        });

        if (preselectSubId) {
          subSelect.value = preselectSubId;
        } else if (cachedSubcategories.length > 0) {
          subSelect.value = cachedSubcategories[0].id;
        }
      }
    } catch (e) {
      console.error("Failed to load subcategories for filter:", e);
    }
  }

  window.handleReorderCategoryChange = async function() {
    if (reorderType === 'asset') {
      await updateSubcategoryOptions();
    }
    await fetchAndRenderReorderItems();
  };

  window.handleReorderSubcategoryChange = async function() {
    await fetchAndRenderReorderItems();
  };

  async function fetchAndRenderReorderItems() {
    const spinner = document.getElementById('reorderLoadingSpinner');
    const emptyNotice = document.getElementById('reorderEmptyNotice');
    const listContainer = document.getElementById('reorderItemsList');
    spinner.style.display = 'flex';
    emptyNotice.style.display = 'none';
    listContainer.innerHTML = '';

    const catSelect = document.getElementById('reorderCategorySelect');
    const subSelect = document.getElementById('reorderSubcategorySelect');

    let url = `/admin/api/reorder/items?type=${encodeURIComponent(reorderType)}`;
    if (reorderType === 'subcategory' && catSelect.value) {
      url += `&categoryId=${encodeURIComponent(catSelect.value)}`;
    } else if (reorderType === 'asset') {
      if (catSelect.value) url += `&categoryId=${encodeURIComponent(catSelect.value)}`;
      if (subSelect.value) url += `&subCategoryId=${encodeURIComponent(subSelect.value)}`;
    }

    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error("Failed to load items");
      const data = await res.json();
      currentItems = data.items || [];
      initialItemsOrder = currentItems.map(item => item.id);
      hasUnsavedChanges = false;
      document.getElementById('reorderUnsavedIndicator').style.display = 'none';
      document.getElementById('reorderResetBtn').style.display = 'none';

      renderReorderItemsList();
    } catch (err) {
      console.error("Reorder fetch error:", err);
      listContainer.innerHTML = `<div style="color:var(--app-danger, #ef4444); text-align:center; padding:1.5rem;">Failed to load items for reordering.</div>`;
    } finally {
      spinner.style.display = 'none';
    }
  }

  function renderReorderItemsList() {
    const listContainer = document.getElementById('reorderItemsList');
    const emptyNotice = document.getElementById('reorderEmptyNotice');
    const countBadge = document.getElementById('reorderItemsCountBadge');

    listContainer.innerHTML = '';
    countBadge.textContent = `${currentItems.length} items`;

    if (currentItems.length === 0) {
      emptyNotice.style.display = 'block';
      return;
    }

    emptyNotice.style.display = 'none';

    currentItems.forEach((item, index) => {
      const card = document.createElement('div');
      card.className = 'reorder-item-card';
      card.dataset.id = item.id;
      card.dataset.index = index;
      card.setAttribute('draggable', 'true');

      // Thumbnail / Icon
      let thumbHtml = '';
      if (item.thumbnail_url) {
        thumbHtml = `<img src="${item.thumbnail_url}" alt="${item.name}" class="reorder-card-thumb" onerror="this.style.display='none'">`;
      } else {
        const iconChar = reorderType === 'category' ? '📁' : reorderType === 'subcategory' ? '📂' : '🎨';
        thumbHtml = `<div class="reorder-card-thumb placeholder">${iconChar}</div>`;
      }

      // Badges
      let badgesHtml = '';
      if (!item.is_enabled) {
        badgesHtml += `<span class="badge badge-disabled" style="font-size:0.68rem; padding:1px 6px;">Disabled</span>`;
      }
      if (item.is_premium) {
        badgesHtml += `<span class="badge badge-premium" style="font-size:0.68rem; padding:1px 6px;">Premium</span>`;
      }

      card.innerHTML = `
        <div class="reorder-drag-handle" title="Drag to reorder">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="9" cy="5" r="1"></circle>
            <circle cx="9" cy="12" r="1"></circle>
            <circle cx="9" cy="19" r="1"></circle>
            <circle cx="15" cy="5" r="1"></circle>
            <circle cx="15" cy="12" r="1"></circle>
            <circle cx="15" cy="19" r="1"></circle>
          </svg>
        </div>

        <div class="reorder-seq-wrapper" title="Type a sequence number to reposition directly">
          <input type="number" class="reorder-seq-input" min="1" max="${currentItems.length}" value="${index + 1}" data-id="${item.id}" data-index="${index}" onchange="handleSeqNumberInputChange(${index}, this.value)">
        </div>

        ${thumbHtml}

        <div class="reorder-card-info">
          <span class="reorder-card-title">${escapeHtml(item.name)}</span>
          ${item.folder_name ? `<span class="reorder-card-sub">${escapeHtml(item.folder_name)}</span>` : ''}
        </div>

        <div class="reorder-card-actions">
          ${badgesHtml}
          <button type="button" class="btn-nudge-arrow" onclick="moveItemNudge(${index}, -1)" ${index === 0 ? 'disabled' : ''} title="Move Up">▲</button>
          <button type="button" class="btn-nudge-arrow" onclick="moveItemNudge(${index}, 1)" ${index === currentItems.length - 1 ? 'disabled' : ''} title="Move Down">▼</button>
        </div>
      `;

      // Drag Events
      setupCardDragEvents(card, index);

      listContainer.appendChild(card);
    });
  }

  function setupCardDragEvents(card, index) {
    card.addEventListener('dragstart', function(e) {
      dragSrcIndex = index;
      card.classList.add('is-dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', index.toString());
    });

    card.addEventListener('dragover', function(e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      card.classList.add('drag-over');
    });

    card.addEventListener('dragleave', function() {
      card.classList.remove('drag-over');
    });

    card.addEventListener('drop', function(e) {
      e.preventDefault();
      card.classList.remove('drag-over');
      const targetIndex = parseInt(card.dataset.index, 10);
      if (dragSrcIndex !== null && dragSrcIndex !== targetIndex) {
        moveItemPlacement(dragSrcIndex, targetIndex);
      }
    });

    card.addEventListener('dragend', function() {
      card.classList.remove('is-dragging');
      document.querySelectorAll('.reorder-item-card').forEach(c => c.classList.remove('drag-over'));
      dragSrcIndex = null;
    });
  }

  // Move item placement and update list
  function moveItemPlacement(fromIndex, toIndex) {
    if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0 || fromIndex >= currentItems.length || toIndex >= currentItems.length) {
      return;
    }
    const moved = currentItems.splice(fromIndex, 1)[0];
    currentItems.splice(toIndex, 0, moved);

    markUnsaved();
    renderReorderItemsList();
  }

  window.moveItemNudge = function(index, delta) {
    const targetIndex = index + delta;
    if (targetIndex >= 0 && targetIndex < currentItems.length) {
      moveItemPlacement(index, targetIndex);
    }
  };

  // Change sequence by typing it out in the number input
  window.handleSeqNumberInputChange = function(itemIndex, newSeqValue) {
    const parsed = parseInt(newSeqValue, 10);
    if (isNaN(parsed) || parsed < 1) {
      renderReorderItemsList();
      return;
    }
    // Convert 1-indexed entered position to 0-indexed destination
    const targetIndex = Math.min(Math.max(parsed - 1, 0), currentItems.length - 1);
    moveItemPlacement(itemIndex, targetIndex);
  };

  function markUnsaved() {
    hasUnsavedChanges = true;
    document.getElementById('reorderUnsavedIndicator').style.display = 'inline-block';
    document.getElementById('reorderResetBtn').style.display = 'inline-flex';
  }

  window.resetReorderItemsOrder = function() {
    // Re-sort currentItems based on initial order
    const orderMap = new Map(initialItemsOrder.map((id, idx) => [id, idx]));
    currentItems.sort((a, b) => (orderMap.get(a.id) ?? 999) - (orderMap.get(b.id) ?? 999));

    hasUnsavedChanges = false;
    document.getElementById('reorderUnsavedIndicator').style.display = 'none';
    document.getElementById('reorderResetBtn').style.display = 'none';
    renderReorderItemsList();
  };

  window.filterReorderCardsList = function(searchTerm) {
    const q = (searchTerm || '').toLowerCase().trim();
    const cards = document.querySelectorAll('#reorderItemsList .reorder-item-card');
    cards.forEach(card => {
      const title = (card.querySelector('.reorder-card-title')?.textContent || '').toLowerCase();
      const sub = (card.querySelector('.reorder-card-sub')?.textContent || '').toLowerCase();
      if (!q || title.includes(q) || sub.includes(q)) {
        card.style.display = 'flex';
      } else {
        card.style.display = 'none';
      }
    });
  };

  window.saveCentralReorderOrder = async function() {
    const saveBtn = document.getElementById('reorderSaveBtn');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    const orderedIds = currentItems.map(item => item.id);

    try {
      const res = await fetch('/admin/api/reorder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: reorderType,
          ordered_ids: orderedIds
        })
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.message || "Failed to save reorder");
      }

      hasUnsavedChanges = false;
      document.getElementById('reorderUnsavedIndicator').style.display = 'none';
      document.getElementById('reorderResetBtn').style.display = 'none';

      // Reload window so the table displays updated order
      window.location.reload();
    } catch (err) {
      alert("Error saving order: " + err.message);
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Order';
    }
  };

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

})();
