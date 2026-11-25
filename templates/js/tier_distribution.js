// Shared Tier & Frequency Distribution module for Admin & Manager instance content pages.
// Parameterized via window.TIER_PORTAL_BASE ('/admin' or '/manager') and global `instanceId`.

const tierDistributionMemory = {}; // keyed by scope key (scopeId, 'bulk_all', 'bulk_cat_<id>', 'bulk_sel')
let activeBulkContext = null; // null in single mode, else { mode, parentCategoryId, subcategoryIds, nonEmptyCounts, previewTotal }

function _tierPortalBase() {
  if (window.TIER_PORTAL_BASE) return window.TIER_PORTAL_BASE;
  return document.getElementById('managerSubCategoryFilter') ? '/manager' : '/admin';
}

function _refreshAssetTableAfterTierChange() {
  if (typeof applyAssetFilters === 'function') return applyAssetFilters();
  if (typeof applyManagerAssetFilters === 'function') return applyManagerAssetFilters();
  return Promise.resolve();
}

function _parseJsonSafe(raw) {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed && Object.keys(parsed).length > 0 ? parsed : null;
  } catch (_) {
    return null;
  }
}

function _escapeHtml(text) {
  const d = document.createElement('div');
  d.textContent = text == null ? '' : String(text);
  return d.innerHTML;
}

function clampCountsForTotal(totalCount, premCount, rewCount) {
  if (totalCount <= 1) return { prem: 0, rew: 0 };
  const maxAllowed = totalCount - 1;
  const prem = Math.max(0, parseInt(premCount) || 0);
  const rew = Math.max(0, parseInt(rewCount) || 0);
  if (prem + rew <= maxAllowed) return { prem, rew };

  if (prem > 0 && rew > 0 && maxAllowed >= 2) {
    let effPrem = Math.round(maxAllowed * (prem / (prem + rew)));
    effPrem = Math.max(1, Math.min(maxAllowed - 1, effPrem));
    return { prem: effPrem, rew: maxAllowed - effPrem };
  }
  if (prem > 0 && (rew === 0 || prem >= rew)) return { prem: maxAllowed, rew: 0 };
  if (rew > 0) return { prem: 0, rew: maxAllowed };
  return { prem: 0, rew: 0 };
}

function resolveClientEffectiveCounts(totalCount, countMode, premVal, rewVal) {
  if (countMode === 'percentage') {
    const rawP = Math.round(totalCount * Math.max(0, parseFloat(premVal) || 0) / 100);
    const rawR = Math.round(totalCount * Math.max(0, parseFloat(rewVal) || 0) / 100);
    return clampCountsForTotal(totalCount, rawP, rawR);
  }
  return clampCountsForTotal(totalCount, premVal, rewVal);
}

function generateClientTierSequence(total, premCount, rewCount, nFreq, pFreq, rFreq, alternatePaid = false) {
  if (total <= 0) return [];
  let remPrem = Math.max(0, premCount);
  let remRew = Math.max(0, rewCount);
  let remNorm = Math.max(0, total - remPrem - remRew);

  const res = [];
  let paidTurn = remPrem > 0 ? 'premium' : 'rewarded';

  while (res.length < total) {
    const nBatch = Math.min(nFreq, remNorm, total - res.length);
    for (let i = 0; i < nBatch; i++) {
      res.push('normal');
      remNorm--;
    }

    if (res.length < total) {
      if (alternatePaid) {
        const choosePrem = (paidTurn === 'premium' && remPrem > 0) || (paidTurn === 'rewarded' && remRew === 0 && remPrem > 0);
        const chooseRew = !choosePrem && remRew > 0;
        if (choosePrem) {
          const pBatch = Math.min(pFreq, remPrem, total - res.length);
          for (let i = 0; i < pBatch; i++) {
            res.push('premium');
            remPrem--;
          }
          paidTurn = 'rewarded';
        } else if (chooseRew) {
          const rBatch = Math.min(rFreq, remRew, total - res.length);
          for (let i = 0; i < rBatch; i++) {
            res.push('rewarded');
            remRew--;
          }
          paidTurn = 'premium';
        }
      } else {
        if (remPrem > 0) {
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

function inferSettingsFromTierSequence(tierList, total, maxAllowed) {
  if (!tierList || tierList.length === 0) return null;
  let premCount = 0;
  let rewCount = 0;
  for (const t of tierList) {
    if (t === 'premium') premCount++;
    else if (t === 'rewarded') rewCount++;
  }
  if (premCount === 0 && rewCount === 0) return null;

  const normRuns = [], premRuns = [], rewRuns = [];
  let currentTier = null, currentLen = 0;
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

  let alternatePaid = false;
  if (premCount > 0 && rewCount > 0) {
    const firstPrem = tierList.indexOf('premium');
    const firstRew = tierList.indexOf('rewarded');
    const lo = Math.min(firstPrem, firstRew);
    const hi = Math.max(firstPrem, firstRew);
    for (let i = lo + 1; i < hi; i++) {
      if (tierList[i] === 'normal') {
        alternatePaid = true;
        break;
      }
    }
  }

  const boundedPrem = Math.min(premCount, maxAllowed);
  const boundedRew = Math.min(rewCount, Math.max(0, maxAllowed - boundedPrem));
  return {
    count_mode: 'fixed',
    premium_count: boundedPrem,
    rewarded_count: boundedRew,
    normal_frequency: normRuns.length > 0 ? normRuns[0] : 3,
    premium_frequency: premRuns.length > 0 ? premRuns[0] : 2,
    rewarded_frequency: rewRuns.length > 0 ? rewRuns[0] : 1,
    alternate_paid: alternatePaid,
  };
}

function _inferDomFallbackSettings(scopeType, scopeId, targetType, total, maxAllowed) {
  if (scopeType === 'category' && targetType === 'subcategory') {
    const catCard = document.querySelector(`.folder-card[data-cat-id="${scopeId}"], .manager-cat-card[data-cat-id="${scopeId}"]`)
      || document.querySelector(`[data-parent-cat-id="${scopeId}"]`);
    if (catCard) {
      const subCards = catCard.querySelectorAll('.admin-sub-card, .manager-sub-card, .sub-folder-card');
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
        return inferSettingsFromTierSequence(tierList, total, maxAllowed);
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
      return inferSettingsFromTierSequence(tierList, total, maxAllowed);
    }
  }
  return null;
}

function _applySettingsToModalFields(prior, total, maxAllowed, isBulk) {
  const mode = (isBulk && prior && prior.count_mode === 'percentage') ? 'percentage' : 'fixed';
  document.querySelectorAll('input[name="tierDistCountMode"]').forEach(r => {
    r.checked = r.value === mode;
  });

  if (mode === 'percentage') {
    const pPct = Math.min(99, Math.max(0, parseFloat(prior.premium_percent) || 0));
    const rPct = Math.min(99 - pPct, Math.max(0, parseFloat(prior.rewarded_percent) || 0));
    document.getElementById('tierDistPremiumCount').value = pPct;
    document.getElementById('tierDistRewardedCount').value = rPct;
  } else {
    let defaultPrem = Math.min(Math.floor(total / 3), maxAllowed);
    let defaultRew = 0;
    if (prior && (prior.premium_count !== undefined || prior.rewarded_count !== undefined)) {
      defaultPrem = Math.min(Math.max(0, parseInt(prior.premium_count) || 0), maxAllowed);
      defaultRew = Math.min(Math.max(0, parseInt(prior.rewarded_count) || 0), Math.max(0, maxAllowed - defaultPrem));
    }
    document.getElementById('tierDistPremiumCount').value = defaultPrem;
    document.getElementById('tierDistRewardedCount').value = defaultRew;
  }

  document.getElementById('tierDistNormalFreq').value = (prior && parseInt(prior.normal_frequency)) || 3;
  document.getElementById('tierDistPremiumFreq').value = (prior && parseInt(prior.premium_frequency)) || 2;
  document.getElementById('tierDistRewardedFreq').value = (prior && parseInt(prior.rewarded_frequency)) || 1;
  document.getElementById('tierDistAlternatePaid').checked = Boolean(prior && prior.alternate_paid);

  _syncCountModeUI(mode);
  onTierDistCountChange();
}

function _syncCountModeUI(mode) {
  const isPct = mode === 'percentage';
  const premLbl = document.getElementById('tierDistPremLabel');
  const rewLbl = document.getElementById('tierDistRewLabel');
  const normLbl = document.getElementById('tierDistNormalCardLabel');
  if (premLbl) premLbl.textContent = isPct ? '⭐ Premium %' : '⭐ Premium Count';
  if (rewLbl) rewLbl.textContent = isPct ? '🎁 Rewarded %' : '🎁 Rewarded Count';
  if (normLbl) normLbl.textContent = isPct ? 'Free / Normal %' : 'Free / Normal Items';
}

function openTierDistributionModalFromElem(btn) {
  if (!btn) return;
  openTierDistributionModal(
    btn.dataset.scopeType || 'category',
    btn.dataset.scopeId || '',
    btn.dataset.scopeName || '',
    parseInt(btn.dataset.totalCount) || 0,
    btn.dataset.targetType || 'subcategory',
    _parseJsonSafe(btn.dataset.tierSettings)
  );
}

function openTierDistributionModal(scopeType, scopeId, scopeName, totalCount, targetType, passedSettings = null) {
  const total = parseInt(totalCount) || 0;
  if (total <= 0) {
    alert(`No ${targetType}s found in "${scopeName}" to distribute tiers across.`);
    return;
  }
  const modal = document.getElementById('tierDistributionModal');
  if (!modal) return;

  activeBulkContext = null;
  document.getElementById('tierDistScopeType').value = scopeType;
  document.getElementById('tierDistScopeId').value = scopeId;
  document.getElementById('tierDistTargetType').value = targetType;
  document.getElementById('tierDistTotalCount').value = total;

  const bulkRow = document.getElementById('tierDistBulkModeRow');
  if (bulkRow) bulkRow.style.display = 'none';

  const targetLabel = targetType === 'subcategory' ? 'Sub-folders' : 'Assets';
  const scopeLabel = scopeType === 'category' ? 'Category' : 'Sub-folder';

  document.getElementById('tierDistModalTitle').textContent = `⚡ Distribute Tiers in ${scopeName}`;
  document.getElementById('tierDistModalSubtitle').textContent = `Target: ${targetLabel} in this ${scopeLabel} (Total: ${total} items)`;

  const maxAllowed = Math.max(0, total - 1);
  const banner = document.getElementById('tierDistRuleBanner');
  if (banner) {
    banner.innerHTML = `<span>ℹ️ <strong>Rule:</strong> Out of <strong>${total}</strong> items, at most <strong style="color:var(--md-sys-color-primary, #6366f1);">${maxAllowed}</strong> can be set to Premium / Rewarded combined. At least <strong>1 item</strong> must remain Free/Normal.</span>`;
  }

  let prior = tierDistributionMemory[scopeId] || passedSettings;
  if (!prior || Object.keys(prior).length === 0) {
    prior = _inferDomFallbackSettings(scopeType, scopeId, targetType, total, maxAllowed);
  }

  _applySettingsToModalFields(prior, total, maxAllowed, false);
  modal.style.display = 'flex';
}

function _openBulkSubcategoryAssetsModal({ mode, titleLabel, parentCategoryId = null, subcategories = [], passedSettings = null, memoryKey = '' }) {
  const nonEmpty = subcategories.filter(s => (parseInt(s.assetsCount) || 0) > 0);
  if (subcategories.length === 0) {
    alert('No subcategories found in the selected scope.');
    return;
  }
  if (nonEmpty.length === 0) {
    alert(`All ${subcategories.length} selected sub-folder(s) have 0 assets. Import or add assets first.`);
    return;
  }

  const modal = document.getElementById('tierDistributionModal');
  if (!modal) return;

  const counts = nonEmpty.map(s => parseInt(s.assetsCount) || 0);
  const minAssets = Math.min(...counts);
  const maxAssets = Math.max(...counts);
  const totalAssets = counts.reduce((a, b) => a + b, 0);
  const emptyCount = subcategories.length - nonEmpty.length;
  const maxAllowed = Math.max(0, maxAssets - 1);

  activeBulkContext = {
    mode,
    parentCategoryId,
    subcategoryIds: subcategories.map(s => s.id),
    nonEmptyCounts: counts,
    minAssets,
    maxAssets,
    totalAssets,
    emptyCount,
    memoryKey,
  };

  document.getElementById('tierDistScopeType').value = 'bulk_subcategories';
  document.getElementById('tierDistScopeId').value = memoryKey;
  document.getElementById('tierDistTargetType').value = 'asset';
  document.getElementById('tierDistTotalCount').value = maxAssets;

  const bulkRow = document.getElementById('tierDistBulkModeRow');
  if (bulkRow) bulkRow.style.display = 'block';

  document.getElementById('tierDistModalTitle').textContent = `⚡ Bulk Distribute Assets — ${titleLabel}`;
  const rangeStr = minAssets === maxAssets ? `${maxAssets} assets each` : `${minAssets}–${maxAssets} assets/sub-folder`;
  const emptyStr = emptyCount > 0 ? `, ${emptyCount} empty skipped` : '';
  document.getElementById('tierDistModalSubtitle').textContent =
    `Target: ${nonEmpty.length} non-empty sub-folders (${totalAssets} total assets; ${rangeStr}${emptyStr})`;

  const banner = document.getElementById('tierDistRuleBanner');
  if (banner) {
    banner.innerHTML =
      `<span>ℹ️ <strong>Bulk Sub-folder Rule:</strong> Same rule applies per sub-folder. Every non-empty sub-folder keeps at least <strong>1 Free/Normal asset</strong> — smaller sub-folders clamp proportionally (empty folders skipped).</span>`;
  }

  let prior = tierDistributionMemory[memoryKey] || passedSettings;
  if (!prior && nonEmpty.length > 0) {
    const largestWithSettings = nonEmpty
      .slice()
      .sort((a, b) => (b.assetsCount || 0) - (a.assetsCount || 0))
      .find(s => s.tierSettings && Object.keys(s.tierSettings).length > 0);
    if (largestWithSettings) prior = largestWithSettings.tierSettings;
  }

  _applySettingsToModalFields(prior, maxAssets, maxAllowed, true);
  modal.style.display = 'flex';
}

function openBulkAllSubcategoriesTierModal(btn) {
  const subs = window.INSTANCE_BULK_SUB_META || [];
  _openBulkSubcategoryAssetsModal({
    mode: 'all',
    titleLabel: 'All Sub-folders in App',
    subcategories: subs,
    passedSettings: btn ? _parseJsonSafe(btn.dataset.bulkAssetSettings) : null,
    memoryKey: 'bulk_all',
  });
}

function openBulkCategorySubcategoriesTierModal(btn) {
  if (!btn) return;
  const catId = btn.dataset.catId || '';
  const catSourceId = btn.dataset.catSourceId || '';
  const catName = btn.dataset.catName || 'Category';
  const allSubs = window.INSTANCE_BULK_SUB_META || [];
  const subs = allSubs.filter(s => s.categoryId === catId || (catSourceId && s.categoryId === catSourceId));
  _openBulkSubcategoryAssetsModal({
    mode: 'category',
    titleLabel: `All Sub-folders in ${catName}`,
    parentCategoryId: catId,
    subcategories: subs,
    passedSettings: _parseJsonSafe(btn.dataset.bulkAssetSettings),
    memoryKey: `bulk_cat_${catId}`,
  });
}

function openBulkSelectedSubcategoriesTierModal() {
  if (typeof selectedFolderItems === 'undefined' || selectedFolderItems.size === 0) {
    alert('Please select at least one category or subcategory first.');
    return;
  }
  const allSubs = window.INSTANCE_BULK_SUB_META || [];
  const selectedSubMap = new Map();

  selectedFolderItems.forEach(item => {
    if (item.type === 'subcategory') {
      const match = allSubs.find(s => s.id === item.id);
      if (match) selectedSubMap.set(match.id, match);
    } else if (item.type === 'category') {
      allSubs.forEach(s => {
        if (s.categoryId === item.id || s.categorySourceId === item.id) {
          selectedSubMap.set(s.id, s);
        }
      });
    }
  });

  const subs = Array.from(selectedSubMap.values());
  _openBulkSubcategoryAssetsModal({
    mode: 'selected',
    titleLabel: `${subs.length} Selected Sub-folder(s)`,
    subcategories: subs,
    passedSettings: null,
    memoryKey: 'bulk_selected',
  });
}

function onTierDistCountModeChange() {
  const mode = _getSelectedCountMode();
  _syncCountModeUI(mode);
  const premInput = document.getElementById('tierDistPremiumCount');
  const rewInput = document.getElementById('tierDistRewardedCount');
  if (mode === 'percentage') {
    const total = parseInt(document.getElementById('tierDistTotalCount').value) || 1;
    const pVal = parseInt(premInput.value) || 0;
    const rVal = parseInt(rewInput.value) || 0;
    premInput.value = Math.min(99, Math.round((pVal / total) * 100));
    rewInput.value = Math.min(99 - (parseInt(premInput.value) || 0), Math.round((rVal / total) * 100));
  } else {
    const total = parseInt(document.getElementById('tierDistTotalCount').value) || 1;
    const maxAllowed = Math.max(0, total - 1);
    const pPct = parseFloat(premInput.value) || 0;
    const rPct = parseFloat(rewInput.value) || 0;
    const eff = resolveClientEffectiveCounts(total, 'percentage', pPct, rPct);
    premInput.value = Math.min(eff.prem, maxAllowed);
    rewInput.value = Math.min(eff.rew, Math.max(0, maxAllowed - eff.prem));
  }
  onTierDistCountChange();
}

function _getSelectedCountMode() {
  if (!activeBulkContext) return 'fixed';
  const checked = document.querySelector('input[name="tierDistCountMode"]:checked');
  return checked ? checked.value : 'fixed';
}

function onTierDistCountChange() {
  const total = parseInt(document.getElementById('tierDistTotalCount').value) || 0;
  const mode = _getSelectedCountMode();
  const isPct = mode === 'percentage';
  const maxAllowed = isPct ? 99 : Math.max(0, total - 1);

  const premInput = document.getElementById('tierDistPremiumCount');
  const rewInput = document.getElementById('tierDistRewardedCount');

  let premVal = isPct ? parseFloat(premInput.value) : parseInt(premInput.value);
  if (isNaN(premVal) || premVal < 0) premVal = 0;
  else if (premVal > maxAllowed) {
    premVal = maxAllowed;
    premInput.value = premVal;
  }
  premInput.max = maxAllowed;
  document.getElementById('tierDistPremMaxHint').textContent = isPct ? `${maxAllowed}%` : maxAllowed;

  const maxRewarded = Math.max(0, maxAllowed - premVal);
  let rewVal = isPct ? parseFloat(rewInput.value) : parseInt(rewInput.value);
  if (isNaN(rewVal) || rewVal < 0) rewVal = 0;
  else if (rewVal > maxRewarded) {
    rewVal = maxRewarded;
    rewInput.value = rewVal;
  }
  rewInput.max = maxRewarded;
  document.getElementById('tierDistRewMaxHint').textContent = isPct ? `${maxRewarded}%` : maxRewarded;

  const normalDisplay = isPct
    ? `${Math.max(1, Math.round((100 - premVal - rewVal) * 10) / 10)}%`
    : Math.max(1, total - premVal - rewVal);
  document.getElementById('tierDistNormalCount').textContent = normalDisplay;

  const rewBox = document.getElementById('tierDistRewFreqBox');
  if (rewBox) {
    rewBox.style.opacity = rewVal > 0 ? '1' : '0.4';
    const rInput = document.getElementById('tierDistRewardedFreq');
    if (rInput) rInput.disabled = rewVal <= 0;
  }

  updateTierPreviewRibbon();
}

function onTierDistFreqChange() {
  ['tierDistNormalFreq', 'tierDistPremiumFreq', 'tierDistRewardedFreq'].forEach(id => {
    const inp = document.getElementById(id);
    if (inp) {
      const v = parseInt(inp.value);
      if (!isNaN(v) && v < 1) inp.value = 1;
    }
  });
  updateTierPreviewRibbon();
}

function updateTierPreviewRibbon() {
  const total = parseInt(document.getElementById('tierDistTotalCount').value) || 0;
  const mode = _getSelectedCountMode();
  const premRaw = parseFloat(document.getElementById('tierDistPremiumCount').value) || 0;
  const rewRaw = parseFloat(document.getElementById('tierDistRewardedCount').value) || 0;

  const eff = resolveClientEffectiveCounts(total, mode, premRaw, rewRaw);
  const premCount = eff.prem;
  const rewCount = eff.rew;
  const normalCount = Math.max(1, total - premCount - rewCount);

  const nFreq = parseInt(document.getElementById('tierDistNormalFreq').value) || 3;
  const pFreq = parseInt(document.getElementById('tierDistPremiumFreq').value) || 2;
  const rFreq = parseInt(document.getElementById('tierDistRewardedFreq').value) || 1;
  const alternatePaid = Boolean(document.getElementById('tierDistAlternatePaid')?.checked);

  const altHint = document.getElementById('tierDistAltHint');
  if (altHint) {
    altHint.textContent = alternatePaid
      ? `Alternating order: ${nFreq} Free → ${pFreq} Prem → ${nFreq} Free → ${rFreq} Rew`
      : `Combined order: ${nFreq} Free → ${pFreq} Prem → ${rFreq} Rew`;
  }

  const sequence = generateClientTierSequence(total, premCount, rewCount, nFreq, pFreq, rFreq, alternatePaid);
  const ribbon = document.getElementById('tierDistPreviewRibbon');
  if (!ribbon) return;

  ribbon.innerHTML = '';
  sequence.forEach((tier, idx) => {
    const pill = document.createElement('span');
    pill.style.cssText = 'flex-shrink:0; font-size:0.75rem; font-weight:600; padding:0.25rem 0.6rem; border-radius:12px; display:inline-flex; align-items:center; gap:0.25rem; white-space:nowrap;';
    if (tier === 'premium') {
      pill.style.background = '#f59e0b';
      pill.style.color = '#000';
      pill.textContent = `⭐ #${idx + 1} Prem`;
    } else if (tier === 'rewarded') {
      pill.style.background = '#10b981';
      pill.style.color = '#fff';
      pill.textContent = `🎁 #${idx + 1} Rew`;
    } else {
      pill.style.background = 'var(--md-sys-color-surface-container-high, #313244)';
      pill.style.color = 'var(--md-sys-color-on-surface, #cdd6f4)';
      pill.textContent = `#${idx + 1} Free`;
    }
    ribbon.appendChild(pill);
  });

  const pPct = total > 0 ? Math.round((premCount / total) * 100) : 0;
  const rPct = total > 0 ? Math.round((rewCount / total) * 100) : 0;
  const nPct = total > 0 ? Math.round((normalCount / total) * 100) : 0;

  const badgeElem = document.getElementById('tierDistSummaryBadge');
  if (badgeElem) {
    if (rewCount > 0 && premCount > 0 && alternatePaid) {
      badgeElem.textContent = `Pattern: ${nFreq} Free → ${pFreq} Prem → ${nFreq} Free → ${rFreq} Rew`;
    } else {
      badgeElem.textContent = `Pattern: ${nFreq} Free → ${pFreq} Prem${rewCount > 0 ? ` → ${rFreq} Rew` : ''}`;
    }
  }
  const textElem = document.getElementById('tierDistSummaryText');
  if (textElem) {
    const scopePrefix = activeBulkContext
      ? `Sample preview (${total}-asset sub-folder): `
      : 'Distribution breakdown: ';
    textElem.textContent = `${scopePrefix}${normalCount} Free (${nPct}%), ${premCount} Premium (${pPct}%), ${rewCount} Rewarded (${rPct}%) — Total: ${total}`;
  }
}

function openTierDistributionForCurrentFilter() {
  const subSelect = document.getElementById('subCategoryFilter') || document.getElementById('managerSubCategoryFilter');
  const catSelect = document.getElementById('categoryFilter') || document.getElementById('managerCategoryFilter');

  if (subSelect && subSelect.value) {
    const opt = subSelect.options[subSelect.selectedIndex];
    const name = opt ? opt.text : 'Sub-folder';
    const totalCount = parseInt(window.lastAssetTotal || document.querySelectorAll('#reorderableTable tbody tr').length || 10);
    const prior = tierDistributionMemory[subSelect.value] || _parseJsonSafe(opt?.dataset?.tierSettings);
    openTierDistributionModal('subcategory', subSelect.value, name, totalCount, 'asset', prior);
  } else if (catSelect && catSelect.value) {
    const opt = catSelect.options[catSelect.selectedIndex];
    const name = opt ? opt.text : 'Category';
    const totalCount = parseInt(window.lastAssetTotal || document.querySelectorAll('#reorderableTable tbody tr').length || 10);
    const prior = tierDistributionMemory[catSelect.value] || _parseJsonSafe(opt?.dataset?.tierSettings);
    openTierDistributionModal('category', catSelect.value, name, totalCount, 'asset', prior);
  } else {
    alert('Please select a Category or Sub-folder in the filters to distribute tiers.');
  }
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

async function applyTierDistribution() {
  const btn = document.getElementById('tierDistApplyBtn');
  const originalText = btn.textContent;
  const portalBase = _tierPortalBase();

  const normalFreq = parseInt(document.getElementById('tierDistNormalFreq').value) || 3;
  const premiumFreq = parseInt(document.getElementById('tierDistPremiumFreq').value) || 2;
  const rewardedFreq = parseInt(document.getElementById('tierDistRewardedFreq').value) || 1;
  const alternatePaid = Boolean(document.getElementById('tierDistAlternatePaid')?.checked);

  btn.disabled = true;
  btn.textContent = 'Applying...';

  try {
    if (activeBulkContext) {
      const countMode = _getSelectedCountMode();
      const premVal = countMode === 'percentage'
        ? (parseFloat(document.getElementById('tierDistPremiumCount').value) || 0)
        : (parseInt(document.getElementById('tierDistPremiumCount').value) || 0);
      const rewVal = countMode === 'percentage'
        ? (parseFloat(document.getElementById('tierDistRewardedCount').value) || 0)
        : (parseInt(document.getElementById('tierDistRewardedCount').value) || 0);

      const body = {
        apply_to_all: activeBulkContext.mode === 'all',
        parent_category_id: activeBulkContext.mode === 'category' ? activeBulkContext.parentCategoryId : null,
        subcategory_ids: activeBulkContext.mode === 'selected' ? activeBulkContext.subcategoryIds : [],
        count_mode: countMode,
        premium_count: countMode === 'fixed' ? premVal : 0,
        rewarded_count: countMode === 'fixed' ? rewVal : 0,
        premium_percent: countMode === 'percentage' ? premVal : 0,
        rewarded_percent: countMode === 'percentage' ? rewVal : 0,
        normal_frequency: normalFreq,
        premium_frequency: premiumFreq,
        rewarded_frequency: rewardedFreq,
        alternate_paid: alternatePaid,
      };

      const res = await fetch(`${portalBase}/instances/${instanceId}/bulk-distribute-assets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || data.detail || 'Failed to bulk distribute assets');

      const d = data.data || {};
      const bulkSettings = d.settings || {};
      if (activeBulkContext.memoryKey) {
        tierDistributionMemory[activeBulkContext.memoryKey] = bulkSettings;
      }

      if (activeBulkContext.mode === 'all') {
        document.querySelectorAll('.btn-bulk-all-sub-assets').forEach(b => {
          b.dataset.bulkAssetSettings = JSON.stringify(bulkSettings);
        });
      } else if (activeBulkContext.mode === 'category' && activeBulkContext.parentCategoryId) {
        document.querySelectorAll(`.btn-bulk-cat-sub-assets[data-cat-id="${activeBulkContext.parentCategoryId}"]`).forEach(b => {
          b.dataset.bulkAssetSettings = JSON.stringify(bulkSettings);
        });
      }

      // Sync updated individual subcategory settings cleanly into caches and DOM buttons
      (d.subcategories_summary || []).forEach(subSum => {
        tierDistributionMemory[subSum.subcategory_id] = subSum.settings;
        document.querySelectorAll(`.btn-distribute-tiers[data-scope-id="${subSum.subcategory_id}"]`).forEach(b => {
          b.dataset.tierSettings = JSON.stringify(subSum.settings);
        });
        document.querySelectorAll(`select option[value="${subSum.subcategory_id}"]`).forEach(opt => {
          opt.dataset.tierSettings = JSON.stringify(subSum.settings);
        });
        if (Array.isArray(window.INSTANCE_BULK_SUB_META)) {
          const entry = window.INSTANCE_BULK_SUB_META.find(m => m.id === subSum.subcategory_id);
          if (entry) entry.tierSettings = subSum.settings;
        }
      });

      if (activeBulkContext.mode === 'selected' && typeof clearSelectedFolders === 'function') {
        clearSelectedFolders();
      }

      closeTierDistributionModal();
      const summaryMsg =
        `✓ Updated ${d.total_assets_updated || 0} assets across ${d.updated_subcategories_count || 0} sub-folder(s) ` +
        `(${d.premium_assigned || 0} Prem, ${d.rewarded_assigned || 0} Rew, ${d.normal_assigned || 0} Free)` +
        (d.skipped_empty_subcategories_count ? ` • ${d.skipped_empty_subcategories_count} empty skipped` : '');
      if (typeof showToast === 'function') showToast(summaryMsg, 'success');
      else alert(summaryMsg);

      await _refreshAssetTableAfterTierChange();
      return;
    }

    // Single scope mode (category -> subcategories OR subcategory/category -> assets)
    const scopeType = document.getElementById('tierDistScopeType').value;
    const scopeId = document.getElementById('tierDistScopeId').value;
    const targetType = document.getElementById('tierDistTargetType').value;
    const premiumCount = parseInt(document.getElementById('tierDistPremiumCount').value) || 0;
    const rewardedCount = parseInt(document.getElementById('tierDistRewardedCount').value) || 0;

    const res = await fetch(`${portalBase}/instances/${instanceId}/distribute-tiers`, {
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
        rewarded_frequency: rewardedFreq,
        alternate_paid: alternatePaid,
      }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.message || data.detail || 'Failed to distribute tiers');

    closeTierDistributionModal();
    const okMsg = `✓ Successfully distributed ${premiumCount} premium and ${rewardedCount} rewarded items!`;
    if (typeof showToast === 'function') showToast(okMsg, 'success');
    else alert(okMsg);

    const savedSettings = (data.data && data.data.settings) || {
      target_type: targetType,
      count_mode: 'fixed',
      premium_count: premiumCount,
      rewarded_count: rewardedCount,
      normal_frequency: normalFreq,
      premium_frequency: premiumFreq,
      rewarded_frequency: rewardedFreq,
      alternate_paid: alternatePaid,
    };
    tierDistributionMemory[scopeId] = savedSettings;

    document.querySelectorAll(`.btn-distribute-tiers[data-scope-id="${scopeId}"]`).forEach(b => {
      b.dataset.tierSettings = JSON.stringify(savedSettings);
    });
    document.querySelectorAll(`select option[value="${scopeId}"]`).forEach(opt => {
      opt.dataset.tierSettings = JSON.stringify(savedSettings);
    });
    if (scopeType === 'subcategory' && Array.isArray(window.INSTANCE_BULK_SUB_META)) {
      const entry = window.INSTANCE_BULK_SUB_META.find(m => m.id === scopeId);
      if (entry) entry.tierSettings = savedSettings;
    }

    if (data.data && data.data.assignments) {
      data.data.assignments.forEach(item => {
        document.querySelectorAll(`[data-premium-tag="${item.id}"]`).forEach(p => {
          p.hidden = !item.is_premium;
          p.style.display = item.is_premium ? 'inline-block' : 'none';
        });
        document.querySelectorAll(`[data-rewarded-tag="${item.id}"]`).forEach(p => {
          p.hidden = !item.is_rewarded;
          p.style.display = item.is_rewarded ? 'inline-block' : 'none';
        });
        document.querySelectorAll(`[data-folder-premium-cb="${item.id}"]`).forEach(cb => {
          cb.checked = item.is_premium;
        });
        document.querySelectorAll(`[data-folder-rewarded-cb="${item.id}"]`).forEach(cb => {
          cb.checked = item.is_rewarded;
        });

        const row = document.querySelector(`tr[data-asset-id="${item.id}"]`);
        if (row) {
          const premCb = row.querySelector('input[onchange*="is_premium"]');
          if (premCb) premCb.checked = item.is_premium;
          const rewCb = row.querySelector('input[onchange*="is_rewarded"]');
          if (rewCb) rewCb.checked = item.is_rewarded;
        }
      });
    }

    await _refreshAssetTableAfterTierChange();
  } catch (err) {
    alert('Error applying tier distribution: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}
