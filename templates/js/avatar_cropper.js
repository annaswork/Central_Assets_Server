/**
 * avatar_cropper.js - Square (1:1) Avatar Popup Cropper with Alpha Transparency Preservation
 *
 * Adheres strictly to media-cropper-upload skill:
 * - 1:1 Aspect ratio locked.
 * - Draggable and corner-resizable square crop box.
 * - Alpha channel scanning: never saves transparent pixels to JPEG.
 * - Direct integration with HTML file inputs and circular preview elements.
 */

(function (window) {
  'use strict';

  class AvatarCropperModal {
    constructor(file, options = {}) {
      this.file = file;
      this.onCrop = options.onCrop || (() => {});
      this.onCancel = options.onCancel || (() => {});

      this._modal = null;
      this._canvas = null;
      this._ctx = null;
      this._sourceImage = null;
      this._scale = 1;

      // Crop area in canvas coordinates
      this._cropArea = { x: 0, y: 0, size: 100 };
      this._isDragging = false;
      this._activeHandle = null;
      this._dragStart = { x: 0, y: 0 };
    }

    async open() {
      return new Promise((resolve, reject) => {
        this._resolve = resolve;
        this._reject = reject;

        const reader = new FileReader();
        reader.onload = (e) => {
          const img = new Image();
          img.onload = () => {
            this._sourceImage = img;
            this._render();
          };
          img.onerror = () => reject(new Error('Failed to load image file'));
          img.src = e.target.result;
        };
        reader.onerror = () => reject(new Error('Failed to read file'));
        reader.readAsDataURL(this.file);
      });
    }

    hasTransparency(canvas) {
      if (this.file && this.file.type === 'image/jpeg') return false;
      const ctx = canvas.getContext('2d', { willReadFrequently: true });
      const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const data = imgData.data;
      for (let i = 3; i < data.length; i += 4) {
        if (data[i] < 255) return true;
      }
      return false;
    }

    _render() {
      this._modal = document.createElement('div');
      this._modal.className = 'avatar-cropper-modal-overlay';
      this._modal.style.cssText = `
        position: fixed; inset: 0; z-index: 999999;
        background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(8px);
        display: flex; align-items: center; justify-content: center;
        padding: 1.5rem; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      `;

      const dialog = document.createElement('div');
      dialog.style.cssText = `
        background: #1e293b; color: #f8fafc; border-radius: 14px;
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.6);
        max-width: 92vw; max-height: 92vh; width: 560px;
        display: flex; flex-direction: column; overflow: hidden;
        border: 1px solid rgba(255, 255, 255, 0.1);
      `;

      // Header
      const header = document.createElement('div');
      header.style.cssText = `
        padding: 1rem 1.25rem; border-bottom: 1px solid #334155;
        display: flex; justify-content: space-between; align-items: center;
      `;
      header.innerHTML = `
        <div>
          <h3 style="margin: 0; font-size: 1.05rem; font-weight: 600; color: #f8fafc;">Crop Avatar (Square)</h3>
          <span style="font-size: 0.8rem; color: #94a3b8;">Drag to position or resize square selection</span>
        </div>
        <button type="button" id="cropCloseBtn" style="background: none; border: none; color: #94a3b8; font-size: 1.4rem; cursor: pointer; line-height: 1;">&times;</button>
      `;

      // Canvas Body
      const body = document.createElement('div');
      body.style.cssText = `
        padding: 1.25rem; display: flex; flex-direction: column; align-items: center; justify-content: center;
        background: #0f172a; position: relative; overflow: hidden;
      `;

      const canvasContainer = document.createElement('div');
      canvasContainer.style.cssText = `
        position: relative; border-radius: 8px; overflow: hidden;
        background-image: linear-gradient(45deg, #1e293b 25%, transparent 25%), linear-gradient(-45deg, #1e293b 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #1e293b 75%), linear-gradient(-45deg, transparent 75%, #1e293b 75%);
        background-size: 16px 16px; background-position: 0 0, 0 8px, 8px -8px, -8px 0px;
        box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08);
      `;

      this._canvas = document.createElement('canvas');
      this._ctx = this._canvas.getContext('2d');
      canvasContainer.appendChild(this._canvas);
      body.appendChild(canvasContainer);

      // Footer
      const footer = document.createElement('div');
      footer.style.cssText = `
        padding: 0.85rem 1.25rem; border-top: 1px solid #334155;
        display: flex; justify-content: space-between; align-items: center; background: #1e293b;
      `;
      footer.innerHTML = `
        <div id="cropDimInfo" style="font-size: 0.82rem; color: #94a3b8; font-family: monospace;"></div>
        <div style="display: flex; gap: 0.65rem;">
          <button type="button" id="cropCancelBtn" style="padding: 0.5rem 1rem; border-radius: 6px; background: #334155; color: #f8fafc; border: none; font-size: 0.88rem; cursor: pointer; font-weight: 500;">Cancel</button>
          <button type="button" id="cropApplyBtn" style="padding: 0.5rem 1.25rem; border-radius: 6px; background: #0066cc; color: #ffffff; border: none; font-size: 0.88rem; cursor: pointer; font-weight: 600;">Crop & Apply</button>
        </div>
      `;

      dialog.appendChild(header);
      dialog.appendChild(body);
      dialog.appendChild(footer);
      this._modal.appendChild(dialog);
      document.body.appendChild(this._modal);

      // Event handlers
      header.querySelector('#cropCloseBtn').addEventListener('click', () => this._handleCancel());
      footer.querySelector('#cropCancelBtn').addEventListener('click', () => this._handleCancel());
      footer.querySelector('#cropApplyBtn').addEventListener('click', () => this._handleApply());

      this._setupScale();
      this._initCropArea();
      this._bindEvents();
      this._draw();
    }

    _setupScale() {
      const maxW = Math.min(window.innerWidth * 0.85, 480);
      const maxH = Math.min(window.innerHeight * 0.52, 380);

      const scaleW = maxW / this._sourceImage.width;
      const scaleH = maxH / this._sourceImage.height;
      this._scale = Math.min(1, scaleW, scaleH);

      this._canvas.width = Math.round(this._sourceImage.width * this._scale);
      this._canvas.height = Math.round(this._sourceImage.height * this._scale);
    }

    _initCropArea() {
      const w = this._canvas.width;
      const h = this._canvas.height;
      const size = Math.round(Math.min(w, h) * 0.85);

      this._cropArea = {
        x: Math.round((w - size) / 2),
        y: Math.round((h - size) / 2),
        size: size
      };
    }

    _bindEvents() {
      this._canvas.addEventListener('mousedown', (e) => this._onMouseDown(e));
      this._onMouseMoveListener = (e) => this._onMouseMove(e);
      this._onMouseUpListener = () => this._onMouseUp();

      window.addEventListener('mousemove', this._onMouseMoveListener);
      window.addEventListener('mouseup', this._onMouseUpListener);

      // Touch support
      this._canvas.addEventListener('touchstart', (e) => {
        if (e.touches.length === 1) {
          const t = e.touches[0];
          this._onMouseDown({ clientX: t.clientX, clientY: t.clientY });
        }
      }, { passive: false });

      window.addEventListener('touchmove', (e) => {
        if (e.touches.length === 1 && (this._isDragging || this._activeHandle)) {
          e.preventDefault();
          const t = e.touches[0];
          this._onMouseMove({ clientX: t.clientX, clientY: t.clientY });
        }
      }, { passive: false });

      window.addEventListener('touchend', () => this._onMouseUp());
    }

    _getCanvasCoords(e) {
      const rect = this._canvas.getBoundingClientRect();
      return {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top
      };
    }

    _onMouseDown(e) {
      const { x, y } = this._getCanvasCoords(e);
      const { x: cx, y: cy, size } = this._cropArea;
      const handleRadius = 14;

      // Check corner handles: br, bl, tr, tl
      if (Math.hypot(x - (cx + size), y - (cy + size)) <= handleRadius) {
        this._activeHandle = 'br';
      } else if (Math.hypot(x - cx, y - (cy + size)) <= handleRadius) {
        this._activeHandle = 'bl';
      } else if (Math.hypot(x - (cx + size), y - cy) <= handleRadius) {
        this._activeHandle = 'tr';
      } else if (Math.hypot(x - cx, y - cy) <= handleRadius) {
        this._activeHandle = 'tl';
      } else if (x >= cx && x <= cx + size && y >= cy && y <= cy + size) {
        this._isDragging = true;
      } else {
        return;
      }

      this._dragStart = { x, y };
    }

    _onMouseMove(e) {
      if (!this._isDragging && !this._activeHandle) return;

      const { x, y } = this._getCanvasCoords(e);
      const dx = x - this._dragStart.x;
      const dy = y - this._dragStart.y;

      if (this._isDragging) {
        this._cropArea.x = Math.max(0, Math.min(this._cropArea.x + dx, this._canvas.width - this._cropArea.size));
        this._cropArea.y = Math.max(0, Math.min(this._cropArea.y + dy, this._canvas.height - this._cropArea.size));
      } else if (this._activeHandle === 'br') {
        const delta = Math.max(dx, dy);
        const newSize = Math.max(40, this._cropArea.size + delta);
        if (this._cropArea.x + newSize <= this._canvas.width && this._cropArea.y + newSize <= this._canvas.height) {
          this._cropArea.size = newSize;
        }
      } else if (this._activeHandle === 'tl') {
        const delta = Math.min(dx, dy);
        const newSize = Math.max(40, this._cropArea.size - delta);
        const newX = this._cropArea.x + (this._cropArea.size - newSize);
        const newY = this._cropArea.y + (this._cropArea.size - newSize);
        if (newX >= 0 && newY >= 0) {
          this._cropArea.x = newX;
          this._cropArea.y = newY;
          this._cropArea.size = newSize;
        }
      }

      this._dragStart = { x, y };
      this._draw();
    }

    _onMouseUp() {
      this._isDragging = false;
      this._activeHandle = null;
    }

    _draw() {
      const cw = this._canvas.width;
      const ch = this._canvas.height;
      const { x, y, size } = this._cropArea;

      this._ctx.clearRect(0, 0, cw, ch);
      this._ctx.drawImage(this._sourceImage, 0, 0, cw, ch);

      // Darkened outer mask
      this._ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
      this._ctx.fillRect(0, 0, cw, ch);

      // Clear the active crop square
      this._ctx.clearRect(x, y, size, size);
      this._ctx.drawImage(
        this._sourceImage,
        x / this._scale,
        y / this._scale,
        size / this._scale,
        size / this._scale,
        x,
        y,
        size,
        size
      );

      // Stroke boundary
      this._ctx.strokeStyle = '#38bdf8';
      this._ctx.lineWidth = 2;
      this._ctx.strokeRect(x, y, size, size);

      // Circular guide overlay inside the square
      this._ctx.save();
      this._ctx.beginPath();
      this._ctx.arc(x + size / 2, y + size / 2, size / 2, 0, Math.PI * 2);
      this._ctx.strokeStyle = 'rgba(255, 255, 255, 0.45)';
      this._ctx.setLineDash([4, 4]);
      this._ctx.stroke();
      this._ctx.restore();

      // Corner handles
      const corners = [
        [x, y],
        [x + size, y],
        [x, y + size],
        [x + size, y + size]
      ];
      this._ctx.fillStyle = '#ffffff';
      corners.forEach(([cx, cy]) => {
        this._ctx.beginPath();
        this._ctx.arc(cx, cy, 5, 0, Math.PI * 2);
        this._ctx.fill();
        this._ctx.strokeStyle = '#0284c7';
        this._ctx.lineWidth = 2;
        this._ctx.stroke();
      });

      // Update dimension text
      const realSize = Math.round(size / this._scale);
      const info = this._modal.querySelector('#cropDimInfo');
      if (info) {
        info.textContent = `Crop: ${realSize} × ${realSize} px`;
      }
    }

    async _handleApply() {
      const realX = Math.round(this._cropArea.x / this._scale);
      const realY = Math.round(this._cropArea.y / this._scale);
      const realSize = Math.round(this._cropArea.size / this._scale);

      const croppedCanvas = document.createElement('canvas');
      croppedCanvas.width = realSize;
      croppedCanvas.height = realSize;
      const cCtx = croppedCanvas.getContext('2d');

      cCtx.drawImage(
        this._sourceImage,
        realX, realY, realSize, realSize,
        0, 0, realSize, realSize
      );

      // Transparency preservation: enforce PNG/WebP if source or crop has transparency
      const hasAlpha = this.hasTransparency(croppedCanvas);
      let mimeType = 'image/jpeg';
      let ext = '.jpg';
      let quality = 0.92;

      if (hasAlpha || this.file.type === 'image/png' || this.file.type === 'image/webp') {
        mimeType = this.file.type === 'image/webp' ? 'image/webp' : 'image/png';
        ext = this.file.type === 'image/webp' ? '.webp' : '.png';
        quality = undefined; // PNG lossless
      }

      croppedCanvas.toBlob((blob) => {
        const outName = `${this.file.name.replace(/\.[^/.]+$/, '')}_square${ext}`;
        const croppedFile = new File([blob], outName, { type: mimeType });
        const previewUrl = URL.createObjectURL(blob);
        let base64DataUrl = '';
        try {
          base64DataUrl = croppedCanvas.toDataURL(mimeType, quality);
        } catch (e) {
          console.warn('Could not extract data URL:', e);
        }

        this._cleanup();
        this.onCrop(croppedFile, previewUrl, base64DataUrl);
        if (this._resolve) this._resolve({ file: croppedFile, previewUrl, dataUrl: base64DataUrl });
      }, mimeType, quality);
    }

    _handleCancel() {
      this._cleanup();
      this.onCancel();
      if (this._reject) this._reject(new Error('User cancelled cropping'));
    }

    _cleanup() {
      window.removeEventListener('mousemove', this._onMouseMoveListener);
      window.removeEventListener('mouseup', this._onMouseUpListener);
      if (this._modal && this._modal.parentNode) {
        this._modal.parentNode.removeChild(this._modal);
      }
    }
  }

  /**
   * Helper to attach avatar cropper to any file input.
   * @param {string} fileInputSelector - CSS selector or element for <input type="file">
   * @param {string} previewContainerSelector - CSS selector or element for preview circular container
   */
  function setupAvatarCropper(fileInputSelector, previewContainerSelector) {
    const input = typeof fileInputSelector === 'string'
      ? document.querySelector(fileInputSelector)
      : fileInputSelector;

    const previewContainer = typeof previewContainerSelector === 'string'
      ? document.querySelector(previewContainerSelector)
      : previewContainerSelector;

    if (!input) return;

    input.addEventListener('change', async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;

      if (!file.type.startsWith('image/')) {
        return; // Non-image file, skip cropper
      }

      // Provide immediate preview of selected file
      if (previewContainer) {
        try {
          const rawPreview = URL.createObjectURL(file);
          previewContainer.innerHTML = `<img src="${rawPreview}" alt="Avatar Preview" style="width:100%; height:100%; object-fit:cover; border-radius:50%;">`;
        } catch (e) {}
      }

      try {
        const cropper = new AvatarCropperModal(file);
        const { file: croppedFile, previewUrl, dataUrl } = await cropper.open();

        // Update the file input with the cropped File object via DataTransfer
        try {
          const dt = new DataTransfer();
          dt.items.add(croppedFile);
          input.files = dt.files;
        } catch (dtErr) {
          console.warn('DataTransfer not available:', dtErr);
        }

        // Also set hidden avatar_data_url input for guaranteed form submission
        const dataUrlInput = document.getElementById('adminAvatarDataUrl') || document.querySelector('input[name="avatar_data_url"]');
        if (dataUrlInput && dataUrl) {
          dataUrlInput.value = dataUrl;
        }

        // Reset removal flag if previously clicked
        const removeInput = document.getElementById('adminRemoveAvatar') || document.querySelector('input[name="remove_avatar"]');
        if (removeInput) {
          removeInput.value = '0';
        }

        // Update the circular avatar preview container with cropped result
        if (previewContainer) {
          previewContainer.innerHTML = `<img src="${previewUrl}" alt="Avatar Preview" style="width:100%; height:100%; object-fit:cover; border-radius:50%;">`;
        }
      } catch (err) {
        console.log('Avatar cropping cancelled or bypassed, using raw image upload:', err);
      }
    });
  }

  // Export to global scope
  window.AvatarCropperModal = AvatarCropperModal;
  window.setupAvatarCropper = setupAvatarCropper;

})(window);
