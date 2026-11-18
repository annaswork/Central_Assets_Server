/**
 * client-cropper.js - Interactive Client-side Media Cropper
 *
 * Features:
 * 1. Works with Images (PNG, WebP, JPEG), Animated GIFs, and Videos (MP4, WebM, MOV).
 * 2. Strict Transparency Preservation:
 *    - Automatically scans pixels for alpha values (A < 255).
 *    - Never exports transparent canvases to JPEG (which burns transparency to black/white).
 *    - Exports to lossless PNG or WebP with alpha preserved.
 * 3. Handles aspect ratio constraints (9:16, 1:1, 4:3, 16:9, or Free).
 * 4. Draggable selection box with corner handles and bounded coordinates.
 * 5. Returns cropped File object for images, or { file, cropRegion } for server-side video/GIF cropping.
 */

export class MediaCropper {
  constructor(options = {}) {
    this.targetAspectRatio = options.defaultAspectRatio ?? null; // e.g. 9/16, 1, 4/3, null = Free
    this.presets = options.presets || [
      { label: 'Free', ratio: null },
      { label: '9:16 (Portrait)', ratio: 9 / 16 },
      { label: '1:1 (Square)', ratio: 1 },
      { label: '4:3 (Card)', ratio: 4 / 3 },
      { label: '16:9 (Landscape)', ratio: 16 / 9 },
    ];

    this.onCrop = options.onCrop || (() => {});
    this.onCancel = options.onCancel || (() => {});

    // Internal State
    this._file = null;
    this._sourceImage = null;
    this._canvas = null;
    this._ctx = null;
    this._scale = 1;
    this._cropArea = { x: 0, y: 0, width: 0, height: 0 };
    this._isDragging = false;
    this._activeHandle = null;
    this._dragStart = { x: 0, y: 0 };
    this._modal = null;
    this._isVideo = false;
  }

  /**
   * Opens the modal dialog for a File (Image, GIF, or Video).
   * @param {File} file
   * @returns {Promise<File | { file: File, cropRegion: object }>}
   */
  async open(file) {
    this._file = file;
    this._isVideo = file.type.startsWith('video/');

    return new Promise((resolve, reject) => {
      this._loadMediaFrame(file)
        .then((imgElement) => {
          this._sourceImage = imgElement;
          this._renderModal();
          this._resolve = resolve;
          this._reject = reject;
        })
        .catch(reject);
    });
  }

  /**
   * Extracts a previewable frame from video or image.
   */
  _loadMediaFrame(file) {
    return new Promise((resolve, reject) => {
      if (this._isVideo) {
        const video = document.createElement('video');
        const objUrl = URL.createObjectURL(file);
        video.src = objUrl;
        video.muted = true;
        video.preload = 'metadata';

        video.addEventListener('loadeddata', () => {
          video.currentTime = 0;
        });

        video.addEventListener('seeked', () => {
          const cvs = document.createElement('canvas');
          cvs.width = video.videoWidth;
          cvs.height = video.videoHeight;
          const ctx = cvs.getContext('2d');
          ctx.drawImage(video, 0, 0);

          const img = new Image();
          img.onload = () => {
            URL.revokeObjectURL(objUrl);
            resolve(img);
          };
          img.src = cvs.toDataURL('image/png'); // Use PNG for frame capture
        });

        video.addEventListener('error', () => {
          URL.revokeObjectURL(objUrl);
          reject(new Error('Failed to load video preview frame'));
        });
      } else {
        const img = new Image();
        const objUrl = URL.createObjectURL(file);
        img.onload = () => {
          URL.revokeObjectURL(objUrl);
          resolve(img);
        };
        img.onerror = () => {
          URL.revokeObjectURL(objUrl);
          reject(new Error('Failed to load image'));
        };
        img.src = objUrl;
      }
    });
  }

  /**
   * Checks if an HTMLCanvasElement contains transparent pixels.
   */
  hasTransparency(canvas) {
    if (this._file && this._file.type === 'image/jpeg') {
      return false; // JPEG cannot have transparency
    }
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const data = imgData.data;

    for (let i = 3; i < data.length; i += 4) {
      if (data[i] < 255) {
        return true;
      }
    }
    return false;
  }

  /**
   * Builds the modal UI overlay.
   */
  _renderModal() {
    this._modal = document.createElement('div');
    this._modal.className = 'cropper-modal-overlay';
    this._modal.style.cssText = `
      position: fixed; inset: 0; z-index: 99999;
      background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(8px);
      display: flex; align-items: center; justify-content: center;
      padding: 20px; font-family: system-ui, -apple-system, sans-serif;
    `;

    const container = document.createElement('div');
    container.style.cssText = `
      background: #1e293b; color: #f8fafc; border-radius: 12px;
      padding: 24px; max-width: 90vw; max-height: 90vh;
      display: flex; flex-direction: column; gap: 16px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5);
    `;

    // Header & Preset Controls
    const header = document.createElement('div');
    header.style.cssText = 'display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;';
    header.innerHTML = `
      <div>
        <h3 style="margin: 0; font-size: 1.1rem; font-weight: 600;">Crop Media Asset</h3>
        <span style="font-size: 0.8rem; color: #94a3b8;">${this._file.name} (${this._sourceImage.width}×${this._sourceImage.height}px)</span>
      </div>
      <div id="ratio-buttons" style="display: flex; gap: 6px;"></div>
    `;

    // Canvas Container
    const canvasWrap = document.createElement('div');
    canvasWrap.style.cssText = `
      position: relative; overflow: auto; max-height: 60vh;
      background: #0f172a; border-radius: 8px; display: flex; align-items: center; justify-content: center;
      background-image: linear-gradient(45deg, #1e293b 25%, transparent 25%), linear-gradient(-45deg, #1e293b 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #1e293b 75%), linear-gradient(-45deg, transparent 75%, #1e293b 75%);
      background-size: 16px 16px; background-position: 0 0, 0 8px, 8px -8px, -8px 0px;
    `;

    this._canvas = document.createElement('canvas');
    this._ctx = this._canvas.getContext('2d');
    canvasWrap.appendChild(this._canvas);

    // Footer actions
    const footer = document.createElement('div');
    footer.style.cssText = 'display: flex; justify-content: space-between; align-items: center;';
    footer.innerHTML = `
      <div id="crop-dim-info" style="font-size: 0.85rem; color: #cbd5e1; font-family: monospace;"></div>
      <div style="display: flex; gap: 10px;">
        <button id="cropper-cancel-btn" style="padding: 8px 16px; border-radius: 6px; background: #334155; color: #f8fafc; border: none; cursor: pointer;">Cancel</button>
        <button id="cropper-apply-btn" style="padding: 8px 20px; border-radius: 6px; background: #3b82f6; color: white; font-weight: 600; border: none; cursor: pointer;">Apply Crop</button>
      </div>
    `;

    container.appendChild(header);
    container.appendChild(canvasWrap);
    container.appendChild(footer);
    this._modal.appendChild(container);
    document.body.appendChild(this._modal);

    // Setup aspect ratio buttons
    const ratioGroup = header.querySelector('#ratio-buttons');
    this.presets.forEach((preset) => {
      const btn = document.createElement('button');
      btn.textContent = preset.label;
      btn.style.cssText = `
        padding: 4px 10px; font-size: 0.8rem; border-radius: 4px; border: 1px solid #475569;
        background: ${this.targetAspectRatio === preset.ratio ? '#3b82f6' : '#1e293b'};
        color: white; cursor: pointer;
      `;
      btn.addEventListener('click', () => {
        this.targetAspectRatio = preset.ratio;
        ratioGroup.querySelectorAll('button').forEach((b) => (b.style.background = '#1e293b'));
        btn.style.background = '#3b82f6';
        this._initCropArea();
        this._draw();
      });
      ratioGroup.appendChild(btn);
    });

    // Wire up actions
    footer.querySelector('#cropper-cancel-btn').addEventListener('click', () => this._handleCancel());
    footer.querySelector('#cropper-apply-btn').addEventListener('click', () => this._handleApply());

    this._setupCanvasScale();
    this._initCropArea();
    this._bindEvents();
    this._draw();
  }

  _setupCanvasScale() {
    const maxW = Math.min(window.innerWidth * 0.8, 800);
    const maxH = Math.min(window.innerHeight * 0.55, 550);

    const scaleW = maxW / this._sourceImage.width;
    const scaleH = maxH / this._sourceImage.height;
    this._scale = Math.min(1, scaleW, scaleH);

    this._canvas.width = Math.round(this._sourceImage.width * this._scale);
    this._canvas.height = Math.round(this._sourceImage.height * this._scale);
  }

  _initCropArea() {
    const canvasW = this._canvas.width;
    const canvasH = this._canvas.height;

    if (this.targetAspectRatio) {
      let w = canvasW * 0.8;
      let h = w / this.targetAspectRatio;
      if (h > canvasH * 0.8) {
        h = canvasH * 0.8;
        w = h * this.targetAspectRatio;
      }
      this._cropArea = {
        x: (canvasW - w) / 2,
        y: (canvasH - h) / 2,
        width: w,
        height: h,
      };
    } else {
      this._cropArea = {
        x: canvasW * 0.1,
        y: canvasH * 0.1,
        width: canvasW * 0.8,
        height: canvasH * 0.8,
      };
    }
  }

  _bindEvents() {
    this._canvas.addEventListener('mousedown', (e) => this._onMouseDown(e));
    window.addEventListener('mousemove', (e) => this._onMouseMove(e));
    window.addEventListener('mouseup', () => this._onMouseUp());
  }

  _getCanvasCoords(e) {
    const rect = this._canvas.getBoundingClientRect();
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    };
  }

  _onMouseDown(e) {
    const { x, y } = this._getCanvasCoords(e);
    const { x: cx, y: cy, width: cw, height: ch } = this._cropArea;
    const handleSize = 12;

    // Check corner handles
    if (Math.hypot(x - (cx + cw), y - (cy + ch)) <= handleSize) {
      this._activeHandle = 'br';
    } else if (Math.hypot(x - cx, y - (cy + ch)) <= handleSize) {
      this._activeHandle = 'bl';
    } else if (Math.hypot(x - (cx + cw), y - cy) <= handleSize) {
      this._activeHandle = 'tr';
    } else if (Math.hypot(x - cx, y - cy) <= handleSize) {
      this._activeHandle = 'tl';
    } else if (x >= cx && x <= cx + cw && y >= cy && y <= cy + ch) {
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
      this._cropArea.x = Math.max(0, Math.min(this._cropArea.x + dx, this._canvas.width - this._cropArea.width));
      this._cropArea.y = Math.max(0, Math.min(this._cropArea.y + dy, this._canvas.height - this._cropArea.height));
    } else if (this._activeHandle) {
      this._resizeCropArea(dx, dy);
    }

    this._dragStart = { x, y };
    this._draw();
  }

  _resizeCropArea(dx, dy) {
    const tr = this.targetAspectRatio;
    const area = this._cropArea;

    if (this._activeHandle === 'br') {
      const newW = Math.max(40, area.width + dx);
      const newH = tr ? newW / tr : Math.max(40, area.height + dy);
      if (area.x + newW <= this._canvas.width && area.y + newH <= this._canvas.height) {
        area.width = newW;
        area.height = newH;
      }
    } else if (this._activeHandle === 'tl') {
      const newW = Math.max(40, area.width - dx);
      const newH = tr ? newW / tr : Math.max(40, area.height - dy);
      const newX = area.x + area.width - newW;
      const newY = area.y + area.height - newH;
      if (newX >= 0 && newY >= 0) {
        area.x = newX;
        area.y = newY;
        area.width = newW;
        area.height = newH;
      }
    }
  }

  _onMouseUp() {
    this._isDragging = false;
    this._activeHandle = null;
  }

  _draw() {
    this._ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);
    this._ctx.drawImage(this._sourceImage, 0, 0, this._canvas.width, this._canvas.height);

    // Dark backdrop overlay
    this._ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
    this._ctx.fillRect(0, 0, this._canvas.width, this._canvas.height);

    const { x, y, width, height } = this._cropArea;

    // Clear the active crop region
    this._ctx.clearRect(x, y, width, height);
    this._ctx.drawImage(
      this._sourceImage,
      x / this._scale,
      y / this._scale,
      width / this._scale,
      height / this._scale,
      x,
      y,
      width,
      height
    );

    // Stroke boundary
    this._ctx.strokeStyle = '#38bdf8';
    this._ctx.lineWidth = 2;
    this._ctx.strokeRect(x, y, width, height);

    // Corner Handles
    this._ctx.fillStyle = '#ffffff';
    const corners = [
      [x, y],
      [x + width, y],
      [x, y + height],
      [x + width, y + height],
    ];
    corners.forEach(([cx, cy]) => {
      this._ctx.beginPath();
      this._ctx.arc(cx, cy, 5, 0, Math.PI * 2);
      this._ctx.fill();
      this._ctx.stroke();
    });

    // Update dimensions display
    const realW = Math.round(width / this._scale);
    const realH = Math.round(height / this._scale);
    const dimEl = this._modal.querySelector('#crop-dim-info');
    if (dimEl) {
      dimEl.textContent = `Crop Area: ${realW} × ${realH} px`;
    }
  }

  async _handleApply() {
    const realX = Math.round(this._cropArea.x / this._scale);
    const realY = Math.round(this._cropArea.y / this._scale);
    const realW = Math.round(this._cropArea.width / this._scale);
    const realH = Math.round(this._cropArea.height / this._scale);

    const cropRegion = { x: realX, y: realY, width: realW, height: realH };

    if (this._isVideo || this._file.name.toLowerCase().endsWith('.gif')) {
      // For Video and Animated GIF, perform crop server-side using FFmpeg/Pillow
      this._cleanupModal();
      this._resolve({ file: this._file, cropRegion });
      return;
    }

    // Static Image Client-side Crop
    const croppedCanvas = document.createElement('canvas');
    croppedCanvas.width = realW;
    croppedCanvas.height = realH;
    const cCtx = croppedCanvas.getContext('2d');

    cCtx.drawImage(this._sourceImage, realX, realY, realW, realH, 0, 0, realW, realH);

    // CRITICAL: Check transparency before export
    const hasAlpha = this.hasTransparency(croppedCanvas);
    let mimeType = 'image/jpeg';
    let ext = '.jpg';
    let quality = 0.95;

    if (hasAlpha || this._file.type === 'image/png' || this._file.type === 'image/webp') {
      mimeType = this._file.type === 'image/webp' ? 'image/webp' : 'image/png';
      ext = this._file.type === 'image/webp' ? '.webp' : '.png';
      quality = undefined; // PNG lossless
    }

    croppedCanvas.toBlob(
      (blob) => {
        const outName = `${this._file.name.replace(/\.[^/.]+$/, '')}_cropped${ext}`;
        const finalFile = new File([blob], outName, { type: mimeType });
        this._cleanupModal();
        this._onCrop(finalFile);
        this._resolve(finalFile);
      },
      mimeType,
      quality
    );
  }

  _handleCancel() {
    this._cleanupModal();
    this._onCancel();
    if (this._reject) this._reject(new Error('User cancelled cropping'));
  }

  _cleanupModal() {
    if (this._modal && this._modal.parentNode) {
      this._modal.parentNode.removeChild(this._modal);
    }
  }
}
