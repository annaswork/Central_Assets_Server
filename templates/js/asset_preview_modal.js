// Extracted from templates/partials/asset_preview_modal.html so browsers cache it instead of re-downloading it inline.
(function() {
  let currentPreviewAssetId = null;
  let currentPreviewData = null;

  window.openAssetPreviewModal = async function(assetId) {
    if (!assetId) return;
    currentPreviewAssetId = assetId;

    const modal = document.getElementById('assetPreviewModal');
    if (!modal) return;

    // Reset fields to loading state
    document.getElementById('previewAssetTitle').textContent = 'Loading Asset...';
    document.getElementById('previewAssetSubtitle').textContent = '—';
    document.getElementById('previewThumbnailImg').style.display = 'none';
    document.getElementById('previewThumbnailPlaceholder').style.display = 'flex';
    document.getElementById('previewViewsVal').textContent = '—';
    document.getElementById('previewDownloadsVal').textContent = '—';
    document.getElementById('previewAccessVal').textContent = '—';
    document.getElementById('previewDescriptionVal').textContent = '—';
    document.getElementById('previewCreatedVal').textContent = '—';
    document.getElementById('previewUpdatedVal').textContent = '—';
    document.getElementById('previewEnabledVal').textContent = '—';
    document.getElementById('previewMoreFieldsCountBadge').textContent = 'Loading fields...';

    // Set Edit button link
    const apiPrefix = window.location.pathname.startsWith('/manager') ? '/manager' : '/admin';
    const isManager = window.location.pathname.startsWith('/manager');
    const editBtn = document.getElementById('previewEditBtn');
    if (editBtn) {
      if (isManager) {
        editBtn.style.display = 'none';
      } else {
        editBtn.style.display = '';
        const currentUrl = window.location.pathname + window.location.search;
        editBtn.href = `/admin/assets/${assetId}/edit?return_url=${encodeURIComponent(currentUrl)}`;
      }
    }

    const resetBtn = document.getElementById('previewResetStatsBtn');
    const toggleStatusBtn = document.getElementById('previewToggleStatusBtn');
    if (isManager) {
      if (resetBtn) resetBtn.style.display = 'none';
      if (toggleStatusBtn) toggleStatusBtn.style.display = 'none';
    } else {
      if (resetBtn) resetBtn.style.display = '';
      if (toggleStatusBtn) toggleStatusBtn.style.display = '';
    }

    // Show modal immediately
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';

    try {
      const res = await fetch(`${apiPrefix}/api/assets/${assetId}/preview`, {
        headers: { 'Accept': 'application/json' }
      });
      if (!res.ok) {
        throw new Error(`Failed to load asset (HTTP ${res.status})`);
      }
      const data = await res.json();
      currentPreviewData = data;
      renderAssetPreview(data);
    } catch (err) {
      console.error('Error loading asset preview:', err);
      document.getElementById('previewAssetTitle').textContent = 'Error Loading Asset';
      document.getElementById('previewAssetSubtitle').textContent = err.message || 'Could not load asset details';
      document.getElementById('previewMoreFieldsCountBadge').textContent = 'Unable to load fields';
    }
  };

  function renderAssetPreview(data) {
    if (!data) return;

    // Header
    document.getElementById('previewAssetTitle').textContent = data.name || 'Untitled Asset';
    const subtext = `${data.category_name || 'Category'} · ${data.subcategory_name || 'Subcategory'}`;
    document.getElementById('previewAssetSubtitle').textContent = subtext;

    // Thumbnail
    const thumbImg = document.getElementById('previewThumbnailImg');
    const thumbPlaceholder = document.getElementById('previewThumbnailPlaceholder');
    if (data.thumbnail_url && data.thumbnail_url.trim()) {
      thumbImg.src = data.thumbnail_url;
      thumbImg.style.display = 'block';
      thumbPlaceholder.style.display = 'none';
    } else {
      thumbImg.style.display = 'none';
      thumbPlaceholder.style.display = 'flex';
    }

    // Stats
    document.getElementById('previewViewsVal').textContent = data.views ?? 0;
    document.getElementById('previewDownloadsVal').textContent = data.downloads ?? 0;

    const accessVal = document.getElementById('previewAccessVal');
    const accessIcon = document.getElementById('previewAccessIcon');
    if (data.is_premium) {
      accessVal.textContent = 'Premium';
      accessIcon.textContent = '★';
      accessIcon.style.color = '#F59E0B';
    } else {
      accessVal.textContent = 'Free';
      accessIcon.textContent = '○';
      accessIcon.style.color = 'inherit';
    }

    // Details
    document.getElementById('previewDescriptionVal').textContent = data.description || 'No description provided.';
    document.getElementById('previewCreatedVal').textContent = data.created_at_formatted || '—';
    document.getElementById('previewUpdatedVal').textContent = data.updated_at_formatted || '—';

    const enabledEl = document.getElementById('previewEnabledVal');
    const toggleBtn = document.getElementById('previewToggleStatusBtn');
    if (data.is_enabled) {
      enabledEl.innerHTML = '<span style="color:#10B981; font-weight:600;">✓ Yes</span>';
      if (toggleBtn) {
        toggleBtn.textContent = 'Disable';
        toggleBtn.className = 'btn btn-outlined btn-preview-danger';
      }
    } else {
      enabledEl.innerHTML = '<span style="color:#EF4444; font-weight:600;">✗ No (Disabled)</span>';
      if (toggleBtn) {
        toggleBtn.textContent = 'Enable';
        toggleBtn.className = 'btn btn-outlined btn-preview-success';
      }
    }

    // More Fields summary & embedded rendering
    const blocks = data.more_fields_blocks || [];
    let totalFiles = 0;
    blocks.forEach(b => {
      if (b.items && Array.isArray(b.items)) {
        totalFiles += b.items.length;
      } else if (b.coordinates && Array.isArray(b.coordinates)) {
        totalFiles += b.coordinates.length;
      }
    });

    const badgeEl = document.getElementById('previewMoreFieldsCountBadge');
    if (blocks.length === 0) {
      badgeEl.textContent = 'No additional fields or media';
    } else {
      const blockStr = `${blocks.length} block${blocks.length === 1 ? '' : 's'}`;
      const itemStr = totalFiles > 0 ? ` · ${totalFiles} file${totalFiles === 1 ? '' : 's'}` : '';
      badgeEl.textContent = `${blockStr}${itemStr} — click to explore in popup`;
    }

    // Embed all more_fields blocks (and frames marked boxes) directly in preview modal body
    renderEmbeddedMoreFields(document.getElementById('previewEmbeddedMoreFields'), blocks, data);
  }

  function getBlockIcon(type) {
    if (type === 'frames' || (type && type.includes('frame'))) return '🖼️';
    if (type && type.startsWith('image')) return '🖼️';
    if (type && type.startsWith('video')) return '🎬';
    if (type && type.startsWith('audio')) return '🎵';
    if (type === 'string_list') return '🏷️';
    if (type === 'json_data') return '{ }';
    if (type && (type.includes('gif') || type.includes('animation'))) return '✨';
    return '📄';
  }

  function renderMediaItemsList(container, block) {
    if (block.items && block.items.length > 0) {
      const scrollContainer = document.createElement('div');
      scrollContainer.className = 'morefields-items-scroll';

      block.items.forEach((fileItem, fileIdx) => {
        const itemCard = document.createElement('div');
        itemCard.className = 'morefields-scroll-item';

        const isAudio = fileItem.is_audio || (block.type && block.type.startsWith('audio'));
        const isVideo = fileItem.is_video || (block.type && block.type.startsWith('video'));
        const isGif = fileItem.is_gif;
        const isAnim = fileItem.is_animation;

        let previewHtml = '';
        if (isAudio) {
          previewHtml = `
            <div class="morefields-scroll-preview morefields-scroll-preview--audio">
              <div class="morefields-audio-icon-wrap-lg">🎵</div>
              <audio controls preload="none" class="morefields-audio-el-lg" src="${escapeHtml(fileItem.url)}"></audio>
              <span class="morefields-type-pill pill-audio">AUDIO</span>
            </div>
          `;
        } else if (isVideo) {
          previewHtml = `
            <div class="morefields-scroll-preview morefields-scroll-preview--video">
              <video controls preload="metadata" playsinline class="morefields-video-el-lg" src="${escapeHtml(fileItem.url)}"></video>
              <span class="morefields-type-pill pill-video">VIDEO</span>
            </div>
          `;
        } else {
          let pillClass = isGif ? 'pill-gif' : (isAnim ? 'pill-anim' : '');
          let pillText = isGif ? 'GIF' : (isAnim ? 'ANIMATION' : '');
          let pillHtml = pillText ? `<span class="morefields-type-pill ${pillClass}">${pillText}</span>` : '';
          previewHtml = `
            <div class="morefields-scroll-preview morefields-scroll-preview--image" onclick="window.open('${escapeHtml(fileItem.url)}', '_blank')">
              ${pillHtml}
              <img src="${escapeHtml(fileItem.url)}" alt="${escapeHtml(fileItem.filename)}" loading="lazy" class="morefields-scroll-img">
              <a href="${escapeHtml(fileItem.url)}" target="_blank" rel="noopener noreferrer" class="morefields-scroll-overlay" title="Open Full Size" onclick="event.stopPropagation()">↗</a>
            </div>
          `;
        }

        let metaRows = '';
        metaRows += `<div class="morefields-meta-row"><span class="morefields-meta-label">Filename</span><span class="morefields-meta-val" title="${escapeHtml(fileItem.filename)}">${escapeHtml(fileItem.filename)}</span></div>`;
        if (fileItem.format) {
          metaRows += `<div class="morefields-meta-row"><span class="morefields-meta-label">Format</span><span class="morefields-meta-val">${escapeHtml(String(fileItem.format).toUpperCase())}</span></div>`;
        }
        if (fileItem.filesize_formatted && fileItem.filesize_formatted !== '—') {
          metaRows += `<div class="morefields-meta-row"><span class="morefields-meta-label">Size</span><span class="morefields-meta-val">${escapeHtml(fileItem.filesize_formatted)}</span></div>`;
        }
        if (fileItem.dimensions && !isAudio) {
          metaRows += `<div class="morefields-meta-row"><span class="morefields-meta-label">Dimensions</span><span class="morefields-meta-val">${escapeHtml(fileItem.dimensions)}</span></div>`;
        }
        if (fileItem.duration_formatted && fileItem.duration_formatted !== '—') {
          metaRows += `<div class="morefields-meta-row"><span class="morefields-meta-label">Duration</span><span class="morefields-meta-val">${escapeHtml(fileItem.duration_formatted)}</span></div>`;
        }
        if (fileItem.media_kind) {
          metaRows += `<div class="morefields-meta-row"><span class="morefields-meta-label">Kind</span><span class="morefields-meta-val morefields-meta-kind">${escapeHtml(fileItem.media_kind.charAt(0).toUpperCase() + fileItem.media_kind.slice(1))}</span></div>`;
        }

        itemCard.innerHTML = `
          ${previewHtml}
          <div class="morefields-scroll-meta">
            <div class="morefields-scroll-meta-header">
              <span class="morefields-scroll-file-num">#${fileIdx + 1}</span>
              <a href="${escapeHtml(fileItem.url)}" target="_blank" rel="noopener noreferrer" class="morefields-file-link">Open File ↗</a>
            </div>
            <div class="morefields-meta-table">
              ${metaRows}
            </div>
          </div>
        `;
        scrollContainer.appendChild(itemCard);
      });
      container.appendChild(scrollContainer);
    } else {
      container.innerHTML = '<div class="morefields-block-empty">No files uploaded in this block.</div>';
    }
  }

  function renderEmbeddedMoreFields(container, blocks, assetData) {
    if (!container) return;
    container.innerHTML = '';
    if (!blocks || blocks.length === 0) return;

    const titleEl = document.createElement('div');
    titleEl.className = 'asset-preview-section-title';
    titleEl.style.marginTop = '1.25rem';
    titleEl.style.marginBottom = '0.75rem';
    titleEl.textContent = `MORE FIELDS & MEDIA (${blocks.length} BLOCK${blocks.length === 1 ? '' : 'S'})`;
    container.appendChild(titleEl);

    blocks.forEach((block, idx) => {
      const isFrames = block.type === 'frames' || (block.coordinates && Array.isArray(block.coordinates)) || (block.placeholders && Array.isArray(block.placeholders));
      const icon = getBlockIcon(block.type);
      const itemCount = isFrames
        ? (block.coordinates ? block.coordinates.length : (block.placeholders ? block.placeholders.length : 0))
        : ((block.items && Array.isArray(block.items)) ? block.items.length : 0);
      const countUnit = isFrames ? 'slot' : 'file';

      const blockCard = document.createElement('div');
      blockCard.style.cssText = 'background:var(--md-sys-color-surface-container, #1e1e2e); border:1px solid var(--md-sys-color-outline-variant, #313244); border-radius:12px; padding:1rem; margin-bottom:1rem;';

      const headerRow = document.createElement('div');
      headerRow.style.cssText = 'display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;';
      headerRow.innerHTML = `
        <div style="font-weight:600; color:var(--md-sys-color-on-surface); font-size:0.95rem; display:flex; align-items:center; gap:0.5rem;">
          <span>${icon}</span>
          <span>${escapeHtml(block.label || block.key)}</span>
        </div>
        <div style="display:flex; align-items:center; gap:0.4rem;">
          <span class="morefields-type-badge">${escapeHtml(block.type)}</span>
          ${itemCount > 0 ? `<span class="morefields-count-badge" style="font-size:0.72rem; padding:2px 6px;">${itemCount} ${countUnit}${itemCount === 1 ? '' : 's'}</span>` : ''}
        </div>
      `;
      blockCard.appendChild(headerRow);

      const bodyEl = document.createElement('div');
      if (isFrames) {
        renderFramesPreviewBlock(bodyEl, block, assetData);
      } else if (['image_list', 'image_single', 'video_list', 'video_single', 'audio_list', 'audio_single'].includes(block.type) || (block.items && block.items.length > 0 && block.items[0].url)) {
        renderMediaItemsList(bodyEl, block);
      } else if (block.type === 'string_list') {
        const tagBox = document.createElement('div');
        tagBox.className = 'morefields-tags-list';
        if (block.items && block.items.length > 0) {
          block.items.forEach(item => {
            const pill = document.createElement('span');
            pill.className = 'morefields-tag-bubble';
            pill.textContent = `# ${item}`;
            tagBox.appendChild(pill);
          });
        } else {
          tagBox.innerHTML = '<div class="morefields-block-empty">Empty list</div>';
        }
        bodyEl.appendChild(tagBox);
      } else {
        const pre = document.createElement('pre');
        pre.className = 'morefields-code-view';
        pre.textContent = typeof block.data !== 'undefined'
          ? (typeof block.data === 'object' ? JSON.stringify(block.data, null, 2) : String(block.data))
          : (typeof block.raw_data !== 'undefined' ? JSON.stringify(block.raw_data, null, 2) : '—');
        bodyEl.appendChild(pre);
      }

      blockCard.appendChild(bodyEl);
      container.appendChild(blockCard);
    });
  }

  // Open Secondary More Fields Modal
  window.openAssetMoreFieldsModal = function() {
    if (!currentPreviewData) return;
    const modal = document.getElementById('assetMoreFieldsModal');
    if (!modal) return;

    // Set Header Titles
    document.getElementById('moreFieldsModalTitle').textContent = `${currentPreviewData.name || 'Asset'} — More Fields`;
    document.getElementById('moreFieldsModalSubtitle').textContent = 
      `${currentPreviewData.category_name || 'Category'} · ${currentPreviewData.subcategory_name || 'Subcategory'}`;

    renderMoreFieldsModal(currentPreviewData.more_fields_blocks || []);

    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  };

  function renderMoreFieldsModal(blocks) {
    const tabBar = document.getElementById('moreFieldsTabBar');
    const tabContent = document.getElementById('moreFieldsTabContent');
    const totalBadge = document.getElementById('moreFieldsTotalBadge');
    tabBar.innerHTML = '';
    tabContent.innerHTML = '';

    if (!blocks || blocks.length === 0) {
      tabBar.style.display = 'none';
      tabContent.innerHTML = `
        <div style="text-align:center; padding:3rem 1.5rem; color:#64748B;">
          <div style="font-size:2.5rem; margin-bottom:0.75rem;">📦</div>
          <div style="font-size:1.05rem; font-weight:600; color:#cbd5e1;">No More Fields Configured</div>
          <div style="font-size:0.85rem; margin-top:0.35rem;">This asset does not contain any additional media blocks or custom attributes.</div>
        </div>
      `;
      if (totalBadge) totalBadge.textContent = '0 blocks';
      return;
    }

    tabBar.style.display = 'flex';

    let totalFilesCount = 0;
    blocks.forEach(b => {
      if (b.items && Array.isArray(b.items)) totalFilesCount += b.items.length;
      else if (b.coordinates && Array.isArray(b.coordinates)) totalFilesCount += b.coordinates.length;
    });
    if (totalBadge) {
      totalBadge.textContent = `${blocks.length} block${blocks.length === 1 ? '' : 's'}${totalFilesCount > 0 ? ` (${totalFilesCount} files/items)` : ''}`;
    }

    // Build tabs and panels
    blocks.forEach((block, idx) => {
      const isFrames = block.type === 'frames' || (block.coordinates && Array.isArray(block.coordinates));
      const itemCount = isFrames
        ? (block.coordinates ? block.coordinates.length : 0)
        : ((block.items && Array.isArray(block.items)) ? block.items.length : 0);
      const countUnit = isFrames ? 'slot' : 'file';

      // --- Tab Button ---
      const tab = document.createElement('button');
      tab.className = 'morefields-tab-btn' + (idx === 0 ? ' active' : '');
      tab.setAttribute('data-tab-idx', idx);
      const icon = getBlockIcon(block.type);
      const countHtml = itemCount > 0 ? `<span class="morefields-tab-count">${itemCount}</span>` : '';
      tab.innerHTML = `
        <span class="morefields-tab-icon">${icon}</span>
        <span class="morefields-tab-label">${escapeHtml(block.label || block.key)}</span>
        ${countHtml}
      `;
      tab.onclick = function() { switchMoreFieldsTab(idx); };
      tabBar.appendChild(tab);

      // --- Tab Panel ---
      const panel = document.createElement('div');
      panel.className = 'morefields-tab-panel' + (idx === 0 ? ' active' : '');
      panel.setAttribute('data-panel-idx', idx);

      // Panel header with type badge
      const panelHeader = document.createElement('div');
      panelHeader.className = 'morefields-panel-header';
      panelHeader.innerHTML = `
        <div class="morefields-panel-title-row">
          <span class="morefields-panel-icon">${icon}</span>
          <span class="morefields-panel-title">${escapeHtml(block.label || block.key)}</span>
        </div>
        <div class="morefields-panel-badges">
          <span class="morefields-type-badge">${escapeHtml(block.type)}</span>
          ${itemCount > 0 ? `<span class="morefields-count-badge">${itemCount} ${countUnit}${itemCount === 1 ? '' : 's'}</span>` : ''}
        </div>
      `;
      panel.appendChild(panelHeader);

      // Panel body content
      const panelBody = document.createElement('div');
      panelBody.className = 'morefields-panel-body';

      if (block.type === 'string_list') {
        const tagBox = document.createElement('div');
        tagBox.className = 'morefields-tags-list';
        if (block.items && block.items.length > 0) {
          block.items.forEach(item => {
            const pill = document.createElement('span');
            pill.className = 'morefields-tag-bubble';
            pill.textContent = `# ${item}`;
            tagBox.appendChild(pill);
          });
        } else {
          tagBox.innerHTML = '<div class="morefields-block-empty">Empty list</div>';
        }
        panelBody.appendChild(tagBox);

      } else if (isFrames) {
        renderFramesPreviewBlock(panelBody, block, currentPreviewData);

      } else if (['image_list', 'image_single', 'video_list', 'video_single', 'audio_list', 'audio_single'].includes(block.type) || (block.items && block.items.length > 0 && block.items[0].url)) {
        renderMediaItemsList(panelBody, block);

      } else {
        const pre = document.createElement('pre');
        pre.className = 'morefields-code-view';
        pre.textContent = typeof block.data !== 'undefined'
          ? (typeof block.data === 'object' ? JSON.stringify(block.data, null, 2) : String(block.data))
          : (typeof block.raw_data !== 'undefined' ? JSON.stringify(block.raw_data, null, 2) : '—');
        panelBody.appendChild(pre);
      }

      panel.appendChild(panelBody);
      tabContent.appendChild(panel);
    });
  }

  function renderFramesPreviewBlock(container, block, assetData) {
    const coords = block.coordinates || block.placeholders || [];
    const frameImgUrl = block.image_url || block.imageUrl || (assetData ? (assetData.thumbnail_url || assetData.thumbnailUrl) : '');
    const editorUrl = assetData && assetData.id ? `/admin/assets/${assetData.id}/frames` : '#';

    const wrap = document.createElement('div');
    wrap.className = 'morefields-frames-view';

    // 1. Top action header
    const topBar = document.createElement('div');
    topBar.className = 'morefields-frames-topbar';
    topBar.innerHTML = `
      <div class="morefields-frames-info">
        <span class="morefields-frames-badge">🖼️ ${coords.length} Placeholder Slot${coords.length === 1 ? '' : 's'}</span>
        ${block.width && block.height ? `<span class="morefields-frames-dims">Template Size: ${block.width} × ${block.height} px</span>` : ''}
      </div>
      <div class="morefields-frames-actions">
        ${!window.location.pathname.startsWith('/manager') && assetData && assetData.id ? `
          <a href="${editorUrl}" class="btn btn-primary" style="font-size:0.78rem; padding:4px 10px; display:inline-flex; align-items:center; gap:4px; text-decoration:none;">
            <span>Interactive Editor 🖼️</span>
          </a>
        ` : ''}
        ${frameImgUrl ? `
          <a href="${escapeHtml(frameImgUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-outlined" style="font-size:0.78rem; padding:4px 10px; text-decoration:none;" title="Open Full Frame Image">
            <span>Full Image ↗</span>
          </a>
        ` : ''}
      </div>
    `;
    wrap.appendChild(topBar);

    if (!frameImgUrl) {
      const emptyNotice = document.createElement('div');
      emptyNotice.className = 'morefields-block-empty';
      emptyNotice.textContent = 'No frame image provided for this block.';
      wrap.appendChild(emptyNotice);
      container.appendChild(wrap);
      return;
    }

    // 2. Main content: Two-column grid (Image stage on left, Coordinates table on right)
    const contentGrid = document.createElement('div');
    contentGrid.className = 'morefields-frames-grid';

    // Left: Frame Canvas Stage with responsive bounding box overlays
    const stageCol = document.createElement('div');
    stageCol.className = 'morefields-frames-stage-col';

    const stageWrap = document.createElement('div');
    stageWrap.className = 'morefields-frames-stage-wrap';

    const imgEl = document.createElement('img');
    imgEl.src = frameImgUrl;
    imgEl.alt = 'Frame Template';
    imgEl.className = 'morefields-frames-img';

    const overlayLayer = document.createElement('div');
    overlayLayer.className = 'morefields-frames-overlay-layer';

    stageWrap.appendChild(imgEl);
    stageWrap.appendChild(overlayLayer);
    stageCol.appendChild(stageWrap);
    contentGrid.appendChild(stageCol);

    // Function to render bounding boxes according to coordinates on the image
    function renderBoxes(naturalW, naturalH) {
      overlayLayer.innerHTML = '';
      const baseW = naturalW || block.width || 1080;
      const baseH = naturalH || block.height || 1080;

      coords.forEach((coord, idx) => {
        const box = document.createElement('div');
        box.className = 'morefields-frame-box';
        box.setAttribute('data-slot-idx', idx);

        const x = parseFloat(coord.x || 0);
        const y = parseFloat(coord.y || 0);
        const w = parseFloat(coord.width || 0);
        const h = parseFloat(coord.height || 0);
        const rot = parseFloat(coord.rotation || 0);

        const leftPct = (x / baseW) * 100;
        const topPct = (y / baseH) * 100;
        const widthPct = (w / baseW) * 100;
        const heightPct = (h / baseH) * 100;

        box.style.left = `${leftPct}%`;
        box.style.top = `${topPct}%`;
        box.style.width = `${widthPct}%`;
        box.style.height = `${heightPct}%`;
        box.style.transform = `rotate(${rot}deg)`;
        box.style.transformOrigin = 'center center';

        const rotText = Math.abs(rot) > 0.05 ? `<span class="slot-rot-pill">${rot > 0 ? '+' : ''}${rot}°</span>` : '';
        box.innerHTML = `
          <div class="morefields-frame-box-header">
            <span class="slot-num-badge">#${idx + 1}</span>
            ${rotText}
          </div>
          <div class="morefields-frame-box-footer">
            <span class="slot-dims-badge">${Math.round(w)}×${Math.round(h)}</span>
          </div>
        `;

        box.addEventListener('mouseenter', () => highlightSlot(idx, true));
        box.addEventListener('mouseleave', () => highlightSlot(idx, false));
        box.addEventListener('click', (e) => {
          e.stopPropagation();
          focusSlotRow(idx);
        });

        overlayLayer.appendChild(box);
      });
    }

    if (imgEl.complete && imgEl.naturalWidth) {
      renderBoxes(imgEl.naturalWidth, imgEl.naturalHeight);
    } else {
      imgEl.onload = function() {
        renderBoxes(imgEl.naturalWidth, imgEl.naturalHeight);
      };
    }

    // Right: Slot Inspector Table
    const tableCol = document.createElement('div');
    tableCol.className = 'morefields-frames-table-col';

    const tableCard = document.createElement('div');
    tableCard.className = 'morefields-frames-table-card';
    tableCard.innerHTML = `
      <div class="morefields-frames-table-header">
        <span style="font-weight:600; color:#f1f5f9; font-size:0.85rem;">Bounding Box Coordinates</span>
        <span style="font-size:0.75rem; color:#94a3b8;">${coords.length} slot${coords.length === 1 ? '' : 's'}</span>
      </div>
      <div class="morefields-frames-table-scroll">
        <table class="morefields-frames-table">
          <thead>
            <tr>
              <th>Slot</th>
              <th>Position (X, Y)</th>
              <th>Dimensions</th>
              <th>Rotation</th>
              <th>Elevation</th>
            </tr>
          </thead>
          <tbody>
            ${coords.map((c, idx) => `
              <tr class="morefields-slot-row" data-slot-idx="${idx}">
                <td>
                  <span class="slot-table-badge">Slot #${idx + 1}</span>
                </td>
                <td><code>(${Math.round(c.x || 0)}, ${Math.round(c.y || 0)})</code></td>
                <td><code>${Math.round(c.width || 0)} × ${Math.round(c.height || 0)}</code></td>
                <td>
                  ${Math.abs(parseFloat(c.rotation || 0)) > 0.05
                    ? `<span class="slot-table-rot">${c.rotation > 0 ? '+' : ''}${c.rotation}°</span>`
                    : `<span style="color:#64748b;">0°</span>`}
                </td>
                <td>
                  <span class="slot-table-elev">z:${c.elevation !== undefined ? c.elevation : idx}</span>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
    tableCol.appendChild(tableCard);
    contentGrid.appendChild(tableCol);
    wrap.appendChild(contentGrid);
    container.appendChild(wrap);

    function highlightSlot(idx, isHighlight) {
      const box = overlayLayer.querySelector(`.morefields-frame-box[data-slot-idx="${idx}"]`);
      const row = tableCard.querySelector(`.morefields-slot-row[data-slot-idx="${idx}"]`);
      if (box) box.classList.toggle('active-highlight', isHighlight);
      if (row) row.classList.toggle('active-highlight', isHighlight);
    }

    function focusSlotRow(idx) {
      const row = tableCard.querySelector(`.morefields-slot-row[data-slot-idx="${idx}"]`);
      if (row) {
        row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        row.classList.add('active-highlight');
        setTimeout(() => row.classList.remove('active-highlight'), 1200);
      }
    }

    tableCard.querySelectorAll('.morefields-slot-row').forEach(row => {
      const idx = parseInt(row.getAttribute('data-slot-idx'), 10);
      row.addEventListener('mouseenter', () => highlightSlot(idx, true));
      row.addEventListener('mouseleave', () => highlightSlot(idx, false));
    });
  }

  function switchMoreFieldsTab(idx) {
    // Pause any playing media in all panels
    const allPanels = document.querySelectorAll('#moreFieldsTabContent .morefields-tab-panel');
    allPanels.forEach(p => {
      p.querySelectorAll('audio, video').forEach(el => {
        try { el.pause(); } catch(e) {}
      });
    });

    // Deactivate all tabs
    document.querySelectorAll('#moreFieldsTabBar .morefields-tab-btn').forEach(btn => {
      btn.classList.remove('active');
    });
    // Hide all panels
    allPanels.forEach(p => p.classList.remove('active'));

    // Activate selected tab + panel
    const activeTab = document.querySelector(`#moreFieldsTabBar .morefields-tab-btn[data-tab-idx="${idx}"]`);
    const activePanel = document.querySelector(`#moreFieldsTabContent .morefields-tab-panel[data-panel-idx="${idx}"]`);
    if (activeTab) activeTab.classList.add('active');
    if (activePanel) activePanel.classList.add('active');
  }

  window.refreshAssetPreviewStats = async function() {
    if (!currentPreviewAssetId) return;
    const btn = document.getElementById('previewRefreshStatsBtn');
    if (btn) btn.disabled = true;

    try {
      const apiPrefix = window.location.pathname.startsWith('/manager') ? '/manager' : '/admin';
      const res = await fetch(`${apiPrefix}/api/assets/${currentPreviewAssetId}/preview`);
      if (!res.ok) throw new Error('Failed to refresh stats');
      const data = await res.json();
      currentPreviewData = data;
      document.getElementById('previewViewsVal').textContent = data.views ?? 0;
      document.getElementById('previewDownloadsVal').textContent = data.downloads ?? 0;
      if (typeof showAppToast === 'function') {
        showAppToast('Asset stats refreshed.', 'success');
      }
    } catch (err) {
      console.error(err);
      if (typeof showAppToast === 'function') {
        showAppToast('Failed to refresh stats', 'error');
      }
    } finally {
      if (btn) btn.disabled = false;
    }
  };

  window.resetAssetPreviewStats = async function() {
    if (!currentPreviewAssetId) return;
    if (!confirm('Are you sure you want to reset views and downloads to 0 for this asset?')) {
      return;
    }

    const btn = document.getElementById('previewResetStatsBtn');
    if (btn) btn.disabled = true;

    try {
      const res = await fetch(`/admin/api/assets/${currentPreviewAssetId}/reset-stats`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' }
      });
      if (!res.ok) throw new Error('Failed to reset stats');
      const data = await res.json();
      document.getElementById('previewViewsVal').textContent = '0';
      document.getElementById('previewDownloadsVal').textContent = '0';

      // Also update table row live if present on page
      updateTableRowStats(currentPreviewAssetId, 0, 0);

      if (typeof showAppToast === 'function') {
        showAppToast('Views and downloads reset to 0.', 'success');
      }
    } catch (err) {
      console.error(err);
      if (typeof showAppToast === 'function') {
        showAppToast('Failed to reset stats', 'error');
      }
    } finally {
      if (btn) btn.disabled = false;
    }
  };

  window.toggleAssetPreviewStatus = async function() {
    if (!currentPreviewAssetId) return;
    const btn = document.getElementById('previewToggleStatusBtn');
    if (btn) btn.disabled = true;

    try {
      const res = await fetch(`/admin/api/assets/${currentPreviewAssetId}/toggle-status`, {
        method: 'POST',
        headers: { 'Accept': 'application/json' }
      });
      if (!res.ok) throw new Error('Failed to toggle status');
      const data = await res.json();

      const enabledEl = document.getElementById('previewEnabledVal');
      if (data.is_enabled) {
        enabledEl.innerHTML = '<span style="color:#10B981; font-weight:600;">✓ Yes</span>';
        btn.textContent = 'Disable';
        btn.className = 'btn btn-outlined btn-preview-danger';
      } else {
        enabledEl.innerHTML = '<span style="color:#EF4444; font-weight:600;">✗ No (Disabled)</span>';
        btn.textContent = 'Enable';
        btn.className = 'btn btn-outlined btn-preview-success';
      }

      if (typeof showAppToast === 'function') {
        showAppToast(data.message || 'Status updated.', 'success');
      }
    } catch (err) {
      console.error(err);
      if (typeof showAppToast === 'function') {
        showAppToast('Failed to toggle status', 'error');
      }
    } finally {
      if (btn) btn.disabled = false;
    }
  };

  function updateTableRowStats(assetId, views, downloads) {
    // List table view
    const viewCol = document.querySelector(`tr[data-asset-id="${assetId}"] [data-label="Views"]`);
    if (viewCol) {
      viewCol.innerHTML = `<span style="display:inline-flex; align-items:center; gap:0.3rem; font-weight:500;"><span style="opacity:0.65;">👁</span> ${views}</span>`;
    }
    const dlCol = document.querySelector(`tr[data-asset-id="${assetId}"] [data-label="Downloads"]`);
    if (dlCol) {
      dlCol.innerHTML = `<span style="display:inline-flex; align-items:center; gap:0.3rem; font-weight:500;"><span style="opacity:0.65;">⬇</span> ${downloads}</span>`;
    }
  }

  window.closeAssetMoreFieldsModal = function() {
    const modal = document.getElementById('assetMoreFieldsModal');
    if (modal) {
      modal.querySelectorAll('audio, video').forEach(el => {
        try { el.pause(); } catch(e) {}
      });
      modal.style.display = 'none';
    }
    const previewModal = document.getElementById('assetPreviewModal');
    if (previewModal && previewModal.style.display === 'flex') {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
  };

  window.closeAllAssetModals = function() {
    window.closeAssetMoreFieldsModal();
    window.closeAssetPreviewModal();
  };

  window.closeAssetPreviewModal = function() {
    const moreModal = document.getElementById('assetMoreFieldsModal');
    if (moreModal) {
      moreModal.querySelectorAll('audio, video').forEach(el => {
        try { el.pause(); } catch(e) {}
      });
      moreModal.style.display = 'none';
    }
    const modal = document.getElementById('assetPreviewModal');
    if (modal) {
      modal.querySelectorAll('audio, video').forEach(el => {
        try { el.pause(); } catch(e) {}
      });
      modal.style.display = 'none';
    }
    document.body.style.overflow = '';
    currentPreviewAssetId = null;
    currentPreviewData = null;
  };

  window.handleAssetPreviewBackdropClick = function(e) {
    if (e.target && e.target.id === 'assetPreviewModal') {
      closeAssetPreviewModal();
    }
  };

  window.handleAssetMoreFieldsBackdropClick = function(e) {
    if (e.target && e.target.id === 'assetMoreFieldsModal') {
      closeAssetMoreFieldsModal();
    }
  };

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      const moreModal = document.getElementById('assetMoreFieldsModal');
      if (moreModal && moreModal.style.display === 'flex') {
        closeAssetMoreFieldsModal();
        return;
      }
      const modal = document.getElementById('assetPreviewModal');
      if (modal && modal.style.display === 'flex') {
        closeAssetPreviewModal();
      }
    }
  });

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
})();
