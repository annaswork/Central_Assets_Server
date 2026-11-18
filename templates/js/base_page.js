// Extracted from templates/base.html so browsers cache it instead of re-downloading it inline.
function refreshCurrentPage(btn) {
  if (btn) {
    btn.classList.add('refreshing');
  }
  window.location.reload();
}

// Global Search Functionality
let searchDebounceTimer = null;
let currentHighlightedIndex = -1;

function clearGlobalSearch() {
  const input = document.getElementById('globalSearchInput');
  const clearBtn = document.getElementById('globalSearchClearBtn');
  const dropdown = document.getElementById('globalSearchDropdown');
  if (input) {
    input.value = '';
    input.focus();
  }
  if (clearBtn) clearBtn.style.display = 'none';
  if (dropdown) dropdown.style.display = 'none';
  currentHighlightedIndex = -1;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function highlightMatch(text, query) {
  if (!text || !query) return escapeHtml(text);
  const escaped = escapeHtml(text);
  const qClean = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const regex = new RegExp(`(${qClean})`, 'gi');
  return escaped.replace(regex, '<mark class="gs-highlight">$1</mark>');
}

function renderGlobalSearchResults(data, query) {
  const dropdown = document.getElementById('globalSearchDropdown');
  const container = document.getElementById('globalSearchResults');
  if (!dropdown || !container) return;

  const total = (data.categories?.length || 0)
              + (data.subcategories?.length || 0)
              + (data.assets?.length || 0)
              + (data.instances?.length || 0)
              + (data.keys?.length || 0);
  currentHighlightedIndex = -1;

  if (total === 0) {
    container.innerHTML = `
      <div class="gs-empty-state">
        <svg viewBox="0 0 24 24" width="28" height="28" stroke="currentColor" stroke-width="1.8" fill="none"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
        <p>No matches found for "<strong>${escapeHtml(query)}</strong>"</p>
      </div>
    `;
    dropdown.style.display = 'block';
    return;
  }

  let html = '';

  // 1. Categories
  if (data.categories && data.categories.length > 0) {
    html += `
      <div class="gs-section-header">
        <span class="gs-section-title">📁 Categories (${data.categories.length})</span>
      </div>
      <div class="gs-section-items">
    `;
    data.categories.forEach(cat => {
      const thumb = cat.thumbnail_url
        ? `<img src="${cat.thumbnail_url}" class="gs-item-thumb" alt="" onerror="this.style.display='none'">`
        : `<div class="gs-item-icon">📁</div>`;
      html += `
        <a href="/admin/categories?q=${encodeURIComponent(cat.name)}" class="gs-result-item" data-type="category">
          ${thumb}
          <div class="gs-item-info">
            <div class="gs-item-name">${highlightMatch(cat.name, query)}</div>
            <div class="gs-item-meta">Category • /${escapeHtml(cat.folder_name || '')}</div>
          </div>
          <span class="gs-item-tag">View Category →</span>
        </a>
      `;
    });
    html += `</div>`;
  }

  // 2. Subcategories
  if (data.subcategories && data.subcategories.length > 0) {
    html += `
      <div class="gs-section-header">
        <span class="gs-section-title">📂 Subcategories (${data.subcategories.length})</span>
      </div>
      <div class="gs-section-items">
    `;
    data.subcategories.forEach(sub => {
      const thumb = sub.thumbnail_url
        ? `<img src="${sub.thumbnail_url}" class="gs-item-thumb" alt="" onerror="this.style.display='none'">`
        : `<div class="gs-item-icon">📂</div>`;
      const catName = sub.category_name || 'Category';
      html += `
        <a href="/admin/subcategories?categoryId=${encodeURIComponent(sub.category_id)}&q=${encodeURIComponent(sub.name)}" class="gs-result-item" data-type="subcategory">
          ${thumb}
          <div class="gs-item-info">
            <div class="gs-item-name">${highlightMatch(sub.name, query)}</div>
            <div class="gs-item-meta">Subcategory in <strong>${escapeHtml(catName)}</strong></div>
          </div>
          <span class="gs-item-tag">View Subcategory →</span>
        </a>
      `;
    });
    html += `</div>`;
  }

  // 3. Assets
  if (data.assets && data.assets.length > 0) {
    html += `
      <div class="gs-section-header">
        <span class="gs-section-title">🎨 Assets (${data.assets.length})</span>
      </div>
      <div class="gs-section-items">
    `;
    data.assets.forEach(asset => {
      const thumb = asset.thumbnail_url
        ? `<img src="${asset.thumbnail_url}" class="gs-item-thumb" alt="" onerror="this.style.display='none'">`
        : `<div class="gs-item-icon">🎨</div>`;
      const catSub = [asset.category_name, asset.subcategory_name].filter(Boolean).join(' › ');
      html += `
        <a href="/admin/assets/${asset.id}/edit" class="gs-result-item" data-type="asset">
          ${thumb}
          <div class="gs-item-info">
            <div class="gs-item-name">${highlightMatch(asset.name, query)}</div>
            <div class="gs-item-meta">${escapeHtml(catSub || 'Central Asset')}</div>
          </div>
          <span class="gs-item-tag gs-tag-edit">Edit Asset ✏️</span>
        </a>
      `;
    });
    html += `</div>`;
  }

  // 4. App Instances
  if (data.instances && data.instances.length > 0) {
    html += `
      <div class="gs-section-header">
        <span class="gs-section-title">📱 App Instances (${data.instances.length})</span>
      </div>
      <div class="gs-section-items">
    `;
    data.instances.forEach(inst => {
      const thumb = inst.icon_url
        ? `<img src="${inst.icon_url}" class="gs-item-thumb" alt="" onerror="this.style.display='none'">`
        : `<div class="gs-item-icon">📱</div>`;
      const pkg = inst.package_name ? `Package: ${escapeHtml(inst.package_name)}` : 'App Instance';
      html += `
        <a href="/admin/instances/${inst.id}/content" class="gs-result-item" data-type="instance">
          ${thumb}
          <div class="gs-item-info">
            <div class="gs-item-name">${highlightMatch(inst.name, query)}</div>
            <div class="gs-item-meta">${pkg}</div>
          </div>
          <span class="gs-item-tag">Manage Content →</span>
        </a>
      `;
    });
    html += `</div>`;
  }

  // 5. API Keys
  if (data.keys && data.keys.length > 0) {
    html += `
      <div class="gs-section-header">
        <span class="gs-section-title">🔑 API Keys (${data.keys.length})</span>
      </div>
      <div class="gs-section-items">
    `;
    data.keys.forEach(k => {
      const prefixInfo = k.key_prefix ? `Prefix: <code>${escapeHtml(k.key_prefix)}</code>` : 'API Key';
      const scopeInfo = k.app_instance_name ? ` • App: ${escapeHtml(k.app_instance_name)}` : '';
      const statusDot = k.is_active
        ? `<span style="display:inline-block; width:7px; height:7px; border-radius:50%; background:#22c55e; margin-left:0.35rem;" title="Active"></span>`
        : `<span style="display:inline-block; width:7px; height:7px; border-radius:50%; background:#ef4444; margin-left:0.35rem;" title="Revoked"></span>`;
      html += `
        <a href="/admin/keys" class="gs-result-item" data-type="key">
          <div class="gs-item-icon">🔑</div>
          <div class="gs-item-info">
            <div class="gs-item-name" style="display:flex; align-items:center;">
              <span>${highlightMatch(k.name, query)}</span>
              ${statusDot}
            </div>
            <div class="gs-item-meta">${prefixInfo}${scopeInfo}</div>
          </div>
          <span class="gs-item-tag">View Keys →</span>
        </a>
      `;
    });
    html += `</div>`;
  }

  // Footer
  html += `
    <div class="gs-footer">
      <a href="/admin/assets?q=${encodeURIComponent(query)}" class="gs-footer-link">
        Search all assets for "<strong>${escapeHtml(query)}</strong>" →
      </a>
    </div>
  `;

  container.innerHTML = html;
  dropdown.style.display = 'block';
}

document.addEventListener('DOMContentLoaded', function() {
  const searchInput = document.getElementById('globalSearchInput');
  const clearBtn = document.getElementById('globalSearchClearBtn');
  const spinner = document.getElementById('globalSearchSpinner');
  const dropdown = document.getElementById('globalSearchDropdown');

  if (searchInput) {
    searchInput.addEventListener('input', function(e) {
      const query = e.target.value.trim();
      if (clearBtn) clearBtn.style.display = query ? 'inline-flex' : 'none';

      if (!query) {
        if (dropdown) dropdown.style.display = 'none';
        if (spinner) spinner.style.display = 'none';
        currentHighlightedIndex = -1;
        return;
      }

      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = setTimeout(async () => {
        if (spinner) spinner.style.display = 'block';
        try {
          const res = await fetch(`/admin/api/search?q=${encodeURIComponent(query)}&limit=6`);
          if (!res.ok) throw new Error('Search failed');
          const data = await res.json();
          renderGlobalSearchResults(data, query);
        } catch (err) {
          console.error('Global search error:', err);
        } finally {
          if (spinner) spinner.style.display = 'none';
        }
      }, 200);
    });

    searchInput.addEventListener('keydown', function(e) {
      const items = dropdown ? dropdown.querySelectorAll('.gs-result-item') : [];
      if (!dropdown || dropdown.style.display === 'none') {
        if (e.key === 'Enter') {
          const val = searchInput.value.trim();
          if (val) {
            window.location.href = `/admin/assets?q=${encodeURIComponent(val)}`;
          }
        }
        return;
      }

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (items.length > 0) {
          currentHighlightedIndex = (currentHighlightedIndex + 1) % items.length;
          items.forEach((it, idx) => it.classList.toggle('gs-highlighted', idx === currentHighlightedIndex));
          items[currentHighlightedIndex]?.scrollIntoView({ block: 'nearest' });
        }
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (items.length > 0) {
          currentHighlightedIndex = (currentHighlightedIndex - 1 + items.length) % items.length;
          items.forEach((it, idx) => it.classList.toggle('gs-highlighted', idx === currentHighlightedIndex));
          items[currentHighlightedIndex]?.scrollIntoView({ block: 'nearest' });
        }
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (currentHighlightedIndex >= 0 && items[currentHighlightedIndex]) {
          window.location.href = items[currentHighlightedIndex].href;
        } else {
          const val = searchInput.value.trim();
          if (val) {
            window.location.href = `/admin/assets?q=${encodeURIComponent(val)}`;
          }
        }
      } else if (e.key === 'Escape') {
        dropdown.style.display = 'none';
        searchInput.blur();
      }
    });

    // Focus search when dropdown opens on click if query present
    searchInput.addEventListener('focus', function() {
      if (searchInput.value.trim() && dropdown && dropdown.innerHTML.trim()) {
        dropdown.style.display = 'block';
      }
    });
  }

  // Close dropdown when clicking outside
  document.addEventListener('click', function(e) {
    const container = document.getElementById('globalSearchContainer');
    if (container && !container.contains(e.target) && dropdown) {
      dropdown.style.display = 'none';
      currentHighlightedIndex = -1;
    }
  });

  // Global keyboard shortcut: Ctrl+K or Cmd+K or '/'
  document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      if (searchInput) {
        e.preventDefault();
        searchInput.focus();
        searchInput.select();
      }
    } else if (e.key === '/' && document.activeElement !== searchInput) {
      const tag = (document.activeElement?.tagName || '').toLowerCase();
      if (tag !== 'input' && tag !== 'textarea' && tag !== 'select') {
        if (searchInput) {
          e.preventDefault();
          searchInput.focus();
          searchInput.select();
        }
      }
    }
  });

  // Format UTC dates
  document.querySelectorAll('.table-date-cell[data-utc]').forEach(function(el) {
    var raw = el.getAttribute('data-utc');
    if (!raw) return;
    var d = new Date(raw);
    if (!isNaN(d.getTime())) {
      el.textContent = d.toLocaleString('en-US', {
        month: 'numeric',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true
      });
    }
  });
});
