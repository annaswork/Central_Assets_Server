/**
 * Background Upload Manager & Bottom-Right Real-time Progress Popup Widget
 * Tracks large file uploads via XMLHttpRequest with upload progress events.
 */
(function() {
  'use strict';

  // 2 MB threshold for large files
  const LARGE_FILE_THRESHOLD_BYTES = 2 * 1024 * 1024;

  class BackgroundUploadManager {
    constructor() {
      this.activeTasks = new Map(); // id -> task
      this.completedTasks = new Map(); // id -> task
      this.isMinimized = false;
      this.autoDismissTimer = null;
      this.container = null;
      this.listeners = new Set();
      this.idCounter = 1;
    }

    formatBytes(bytes) {
      if (!bytes || bytes <= 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return (bytes / Math.pow(k, i)).toFixed(i > 0 ? 1 : 0) + ' ' + sizes[i];
    }

    formatSpeed(bytesPerSec) {
      if (!bytesPerSec || bytesPerSec <= 0) return '';
      return this.formatBytes(bytesPerSec) + '/s';
    }

    getMimeIcon(mime, filename) {
      const lowerMime = (mime || '').toLowerCase();
      const lowerName = (filename || '').toLowerCase();
      if (lowerMime.startsWith('image/') || /\.(png|jpe?g|webp|gif|svg)$/i.test(lowerName)) return '🖼️';
      if (lowerMime.startsWith('audio/') || /\.(mp3|wav|m4a|aac|ogg)$/i.test(lowerName)) return '🎵';
      if (lowerMime.startsWith('video/') || /\.(mp4|webm|mov|mkv)$/i.test(lowerName)) return '🎬';
      if (lowerMime.includes('json') || lowerName.endsWith('.json')) return '📄';
      return '📦';
    }

    ensureContainer() {
      if (this.container && document.body && document.body.contains(this.container)) {
        return this.container;
      }
      let el = document.getElementById('bgUploadPopupContainer');
      if (!el && document.body) {
        el = document.createElement('div');
        el.id = 'bgUploadPopupContainer';
        el.className = 'bg-upload-container';
        document.body.appendChild(el);
      }
      this.container = el;
      return el;
    }

    hasActiveUploads() {
      return this.activeTasks.size > 0;
    }

    getActiveUploads() {
      return Array.from(this.activeTasks.values());
    }

    waitForAll() {
      if (!this.hasActiveUploads()) {
        return Promise.resolve();
      }
      return new Promise((resolve) => {
        const check = () => {
          if (!this.hasActiveUploads()) {
            resolve();
          } else {
            setTimeout(check, 250);
          }
        };
        setTimeout(check, 250);
      });
    }

    toggleMinimize() {
      this.isMinimized = !this.isMinimized;
      this.render();
    }

    dismiss() {
      this.activeTasks.clear();
      this.completedTasks.clear();
      if (this.autoDismissTimer) {
        clearTimeout(this.autoDismissTimer);
        this.autoDismissTimer = null;
      }
      if (this.container) {
        this.container.innerHTML = '';
        this.container.style.display = 'none';
      }
    }

    upload(file, options = {}) {
      const taskId = 'upload_' + (this.idCounter++) + '_' + Date.now();
      const folder = options.folder || 'misc';
      const catId = options.categoryId || '';
      const subId = options.subCategoryId || '';
      const assetName = options.assetName || '';
      const assetFolder = options.assetFolder || '';
      const assetId = options.assetId || '';
      const clientHints = options.clientHints || {};

      const task = {
        id: taskId,
        file: file,
        filename: file.name,
        size: file.size,
        loaded: 0,
        total: file.size || 1,
        percent: 0,
        speed: 0,
        lastLoaded: 0,
        lastTime: Date.now(),
        status: 'uploading', // 'uploading' | 'processing' | 'done' | 'error'
        error: null,
        result: null,
        xhr: null,
        startTime: Date.now(),
        onProgress: options.onProgress,
        onSuccess: options.onSuccess,
        onError: options.onError
      };

      this.activeTasks.set(taskId, task);
      if (this.autoDismissTimer) {
        clearTimeout(this.autoDismissTimer);
        this.autoDismissTimer = null;
      }
      this.render();

      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        task.xhr = xhr;

        const formData = new FormData();
        formData.append('file', file);
        formData.append('folder', folder);
        if (catId) formData.append('categoryId', catId);
        if (subId) formData.append('subCategoryId', subId);
        if (assetName) formData.append('assetName', assetName);
        if (assetFolder) formData.append('assetFolder', assetFolder);
        if (assetId) formData.append('assetId', assetId);

        if (clientHints) {
          if (clientHints.duration_ms) formData.append('duration_ms', clientHints.duration_ms);
          if (clientHints.duration) formData.append('duration', clientHints.duration);
          if (clientHints.width) formData.append('width', clientHints.width);
          if (clientHints.height) formData.append('height', clientHints.height);
          if (clientHints.filesize) formData.append('filesize', clientHints.filesize);
          else if (file.size) formData.append('filesize', file.size);
        } else if (file.size) {
          formData.append('filesize', file.size);
        }

        // Upload progress event listener
        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable) {
            const now = Date.now();
            const timeDiff = (now - task.lastTime) / 1000;
            if (timeDiff >= 0.25) {
              const loadedDiff = e.loaded - task.lastLoaded;
              task.speed = loadedDiff / timeDiff;
              task.lastLoaded = e.loaded;
              task.lastTime = now;
            }

            task.loaded = e.loaded;
            task.total = e.total;
            task.percent = Math.min(99, Math.round((e.loaded / e.total) * 100));
            if (task.percent >= 99) {
              task.status = 'processing';
            }

            if (typeof task.onProgress === 'function') {
              task.onProgress({
                percent: task.percent,
                loaded: task.loaded,
                total: task.total,
                speed: task.speed,
                file: task.file,
                status: task.status
              });
            }
            this.render();
          }
        });

        // Load complete (Server response)
        xhr.addEventListener('load', () => {
          let json = {};
          try {
            json = JSON.parse(xhr.responseText || '{}');
          } catch (e) {
            json = {};
          }

          if (xhr.status >= 200 && xhr.status < 300) {
            task.percent = 100;
            task.status = 'done';
            const uploadData = json.data || json || {};
            const result = {
              url: uploadData.url || '',
              thumbnail_url: uploadData.thumbnail_url || uploadData.thumb_url || null,
              filename: uploadData.filename || file.name,
              mime: uploadData.mime || file.type,
              size_bytes: uploadData.size_bytes || uploadData.filesize || file.size,
              filesize: uploadData.filesize || uploadData.size_bytes || file.size,
              width: uploadData.width || null,
              height: uploadData.height || null,
              dimensions: uploadData.dimensions || null,
              duration: uploadData.duration || null,
              duration_ms: uploadData.duration_ms || null,
              sha256: uploadData.sha256 || null
            };
            task.result = result;
            this.activeTasks.delete(taskId);
            this.completedTasks.set(taskId, task);

            if (typeof task.onProgress === 'function') {
              task.onProgress({
                percent: 100,
                loaded: task.total,
                total: task.total,
                speed: 0,
                file: task.file,
                status: 'done'
              });
            }
            if (typeof task.onSuccess === 'function') {
              task.onSuccess(result);
            }
            this.render();
            this.scheduleAutoDismiss();
            resolve(result);
          } else {
            task.status = 'error';
            const errMsg = json.error?.message || json.message || `Upload failed with status ${xhr.status}`;
            task.error = errMsg;
            this.activeTasks.delete(taskId);
            this.completedTasks.set(taskId, task);

            if (typeof task.onError === 'function') {
              task.onError(new Error(errMsg));
            }
            this.render();
            reject(new Error(errMsg));
          }
        });

        // Network error
        xhr.addEventListener('error', () => {
          task.status = 'error';
          task.error = 'Network upload error';
          this.activeTasks.delete(taskId);
          this.completedTasks.set(taskId, task);
          if (typeof task.onError === 'function') {
            task.onError(new Error('Network error during background upload'));
          }
          this.render();
          reject(new Error('Network error during background upload'));
        });

        // Abort
        xhr.addEventListener('abort', () => {
          task.status = 'error';
          task.error = 'Upload cancelled';
          this.activeTasks.delete(taskId);
          this.completedTasks.set(taskId, task);
          this.render();
          reject(new Error('Upload cancelled'));
        });

        xhr.open('POST', '/api/v1/media/upload');
        xhr.send(formData);
      });
    }

    scheduleAutoDismiss() {
      if (this.autoDismissTimer) {
        clearTimeout(this.autoDismissTimer);
      }
      if (this.activeTasks.size === 0 && this.completedTasks.size > 0) {
        this.autoDismissTimer = setTimeout(() => {
          this.dismiss();
        }, 6000);
      }
    }

    render() {
      const container = this.ensureContainer();
      if (!container) return;

      const allTasks = [...this.activeTasks.values(), ...this.completedTasks.values()];

      if (allTasks.length === 0) {
        container.style.display = 'none';
        container.innerHTML = '';
        return;
      }

      container.style.display = 'block';

      const activeCount = this.activeTasks.size;
      const completedCount = this.completedTasks.size;
      const primaryActiveTask = activeCount > 0 ? this.activeTasks.values().next().value : null;

      // Minimized view: sleek pill at bottom-right
      if (this.isMinimized) {
        let pillText = 'Uploads';
        if (primaryActiveTask) {
          pillText = `☁️ ${primaryActiveTask.percent}% • ${primaryActiveTask.filename}`;
        } else if (completedCount > 0) {
          pillText = `✓ ${completedCount} file(s) uploaded`;
        }

        container.innerHTML = `
          <div class="bg-upload-minimized" onclick="window.BackgroundUploader.toggleMinimize()" title="Click to expand upload progress">
            <span class="bg-upload-pulse-dot ${activeCount > 0 ? 'active' : ''}"></span>
            <span class="bg-upload-minimized-text">${this.escapeHtml(pillText)}</span>
            <button type="button" class="bg-upload-btn-icon" aria-label="Expand">▲</button>
          </div>
        `;
        return;
      }

      // Full Card view
      let itemsHtml = '';
      allTasks.slice(-4).reverse().forEach((t) => {
        const icon = this.getMimeIcon(t.file?.type, t.filename);
        let statusBadge = '';
        let fillClass = '';

        if (t.status === 'uploading') {
          statusBadge = `<span class="bg-upload-status-badge uploading">${t.percent}%</span>`;
          fillClass = 'uploading';
        } else if (t.status === 'processing') {
          statusBadge = `<span class="bg-upload-status-badge processing">Processing...</span>`;
          fillClass = 'processing';
        } else if (t.status === 'done') {
          statusBadge = `<span class="bg-upload-status-badge done">✓ Done</span>`;
          fillClass = 'done';
        } else {
          statusBadge = `<span class="bg-upload-status-badge error" title="${this.escapeHtml(t.error || '')}">✕ Failed</span>`;
          fillClass = 'error';
        }

        const sizeInfo = t.status === 'done'
          ? this.formatBytes(t.size)
          : `${this.formatBytes(t.loaded)} / ${this.formatBytes(t.total)}`;
        const speedInfo = t.status === 'uploading' && t.speed > 0 ? ` • ${this.formatSpeed(t.speed)}` : '';

        itemsHtml += `
          <div class="bg-upload-item">
            <div class="bg-upload-item-header">
              <div class="bg-upload-item-name-group">
                <span class="bg-upload-item-icon">${icon}</span>
                <span class="bg-upload-item-name" title="${this.escapeHtml(t.filename)}">${this.escapeHtml(t.filename)}</span>
              </div>
              <div class="bg-upload-item-status-group">
                ${statusBadge}
              </div>
            </div>

            <div class="bg-upload-progress-track">
              <div class="bg-upload-progress-fill ${fillClass}" style="width: ${t.status === 'done' ? 100 : t.percent}%;"></div>
            </div>

            <div class="bg-upload-item-footer">
              <span class="bg-upload-item-meta">${sizeInfo}${speedInfo}</span>
              ${t.status === 'error' && t.error ? `<span class="bg-upload-error-detail">${this.escapeHtml(t.error)}</span>` : ''}
            </div>
          </div>
        `;
      });

      const headerTitle = activeCount > 0
        ? `Uploading in background (${activeCount} active)`
        : `Uploads complete (${completedCount})`;

      container.innerHTML = `
        <div class="bg-upload-popup">
          <div class="bg-upload-header">
            <div class="bg-upload-header-title-group">
              <span class="bg-upload-header-icon ${activeCount > 0 ? 'spinning' : ''}">☁️</span>
              <span class="bg-upload-header-title">${this.escapeHtml(headerTitle)}</span>
            </div>
            <div class="bg-upload-header-actions">
              <button type="button" class="bg-upload-btn-icon" onclick="window.BackgroundUploader.toggleMinimize()" title="Minimize to pill">─</button>
              <button type="button" class="bg-upload-btn-icon" onclick="window.BackgroundUploader.dismiss()" title="Close popup">✕</button>
            </div>
          </div>

          <div class="bg-upload-body">
            ${itemsHtml}
          </div>
        </div>
      `;
    }

    escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }
  }

  window.BackgroundUploadManager = BackgroundUploadManager;
  window.BackgroundUploader = new BackgroundUploadManager();
  window.LARGE_FILE_THRESHOLD_BYTES = LARGE_FILE_THRESHOLD_BYTES;

  // Auto-render when DOM is ready
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => {
        window.BackgroundUploader.ensureContainer();
      });
    } else {
      window.BackgroundUploader.ensureContainer();
    }
  }
})();
