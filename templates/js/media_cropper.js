/**
 * media_cropper.js - Production-ready Media Cropper & Audio Cutter Modal
 *
 * Capabilities:
 * 1. Static Images (PNG, WebP, JPEG, SVG):
 *    - Strict transparency preservation: Never converts transparent RGBA to JPEG.
 *    - Client-side canvas pixel alpha scanning (A < 255).
 * 2. Animated GIFs:
 *    - Frame-0 visual cropping; delegates to /api/v1/media/crop for alpha-safe
 *      multi-frame Pillow processing (disposal=2, frame durations, loop count).
 * 3. Videos (MP4, WebM, MOV):
 *    - Frame extraction, draggable aspect-ratio bounding box, even-dimension alignment,
 *      and optional temporal start/end trimming.
 * 4. Audio Files (MP3, WAV, OGG, AAC, M4A):
 *    - Interactive scrubber, playback preview, start/end interval inputs,
 *      audition preview of cut segment, and server-side stream cutting.
 *
 * Exposes: window.MediaCropper
 */

(function () {
  class MediaCropperManager {
    constructor() {
      this.presets = [
        { label: 'Free', ratio: null },
        { label: '1:1 (Square)', ratio: 1 },
        { label: '9:16 (Portrait)', ratio: 9 / 16 },
        { label: '16:9 (Landscape)', ratio: 16 / 9 },
        { label: '4:3 (Card)', ratio: 4 / 3 },
      ];
      this.targetAspectRatio = null;
      this._modal = null;
      this._activeFile = null;
      this._mediaType = 'image'; // 'image' | 'gif' | 'video' | 'audio'
      this._sourceMedia = null;
      this._canvas = null;
      this._ctx = null;
      this._scale = 1;
      this._cropArea = { x: 0, y: 0, width: 0, height: 0 };
      this._isDragging = false;
      this._activeHandle = null;
      this._dragStart = { x: 0, y: 0 };

      // Audio state
      this._audioElement = null;
      this._audioDuration = 0;
      this._audioStartTime = 0;
      this._audioEndTime = 0;
      this._audioPlaying = false;
      this._audioPreviewInterval = null;

      // Video state
      this._videoStartTime = 0;
      this._videoEndTime = 0;
      this._videoDuration = 0;

      // Queue state & cancel control
      this._queueIndex = 0;
      this._queueTotal = 1;
      this._abortController = null;
      this._cancelled = false;
    }

    detectMediaType(file) {
      const type = (file.type || '').toLowerCase();
      const name = (file.name || '').toLowerCase();

      if (type.startsWith('audio/') || name.match(/\.(mp3|wav|ogg|aac|m4a|flac)$/)) {
        return 'audio';
      }
      if (name.endsWith('.gif') || type === 'image/gif') {
        return 'gif';
      }
      if (type.startsWith('video/') || name.match(/\.(mp4|webm|mov|m4v|avi)$/)) {
        return 'video';
      }
      return 'image';
    }

    /**
     * Opens the modal dialog for any media File.
     * @param {File} file
     * @param {Object} options
     * @returns {Promise<File>}
     */
    async open(file, options = {}) {
      if (!file) throw new Error('No file provided to MediaCropper');

      this._activeFile = file;
      this._mediaType = this.detectMediaType(file);
      this.targetAspectRatio = options.defaultAspectRatio ?? null;
      this._queueIndex = options.queueIndex ?? 0;
      this._queueTotal = options.queueTotal ?? 1;
      this._cancelled = false;

      return new Promise((resolve, reject) => {
        this._resolve = resolve;
        this._reject = reject;
        this._initModal();
      });
    }

    _initModal() {
      this._cleanup();

      const isAudio = this._mediaType === 'audio';
      const isVideo = this._mediaType === 'video';
      const isGif = this._mediaType === 'gif';

      const typeLabel = isAudio ? 'Audio' : (isVideo ? 'Video' : (isGif ? 'Animated GIF' : 'Image'));
      const actionVerb = isAudio ? 'Crop Audio Asset' : 'Crop Media Asset';
      const queueBadge = (this._queueTotal > 1)
        ? `<span class="badge" style="background:rgba(56, 189, 248, 0.2); color:#38bdf8; font-size:0.75rem; font-weight:600; padding:2px 8px; border-radius:4px;">Item ${this._queueIndex + 1} of ${this._queueTotal}</span>`
        : '';

      this._modal = document.createElement('div');
      this._modal.className = 'media-cropper-modal-overlay';
      this._modal.id = 'mediaCropperModal';

      const container = document.createElement('div');
      container.className = 'media-cropper-container';

      // Header
      const header = document.createElement('div');
      header.className = 'media-cropper-header';
      header.innerHTML = `
        <div class="media-cropper-title-box">
          <div style="display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap;">
            <span class="media-cropper-badge">${typeLabel}</span>
            ${queueBadge}
            <h3 style="margin:0; font-size:1.1rem; font-weight:600; color:var(--md-sys-color-on-surface, #f8fafc);">${actionVerb}</h3>
          </div>
          <span class="media-cropper-filename" id="cropperFileInfo">Loading ${this._activeFile.name}...</span>
        </div>
        <div style="display:flex; align-items:center; gap:0.6rem; flex-wrap:wrap;">
          ${!isAudio ? '<div id="cropperRatioButtons" class="media-cropper-ratios"></div>' : ''}
          <button type="button" id="cropperHeaderCloseBtn" class="btn btn-outlined" style="min-height:28px; padding:0.15rem 0.55rem; font-size:0.85rem;" title="Close and add original file to saving sequence">✕</button>
        </div>
      `;

      // Content Body
      const body = document.createElement('div');
      body.className = 'media-cropper-body';

      if (isAudio) {
        body.innerHTML = this._buildAudioBodyHtml();
      } else {
        body.innerHTML = `
          <div class="media-cropper-canvas-wrap" id="cropperCanvasWrap">
            <div id="cropperLoadingSpinner" class="media-cropper-spinner-wrap">
              <div class="media-cropper-spinner"></div>
              <span style="font-size:0.85rem; color:#94a3b8;">Loading media frame...</span>
            </div>
          </div>
          ${isVideo ? this._buildVideoTrimHtml() : ''}
        `;
      }

      // Footer
      const footer = document.createElement('div');
      footer.className = 'media-cropper-footer';
      const hasRemainingInQueue = (this._queueTotal > 1) && (this._queueIndex < this._queueTotal - 1);
      footer.innerHTML = `
        <div id="cropperDimInfo" class="media-cropper-dim-info">
          ${isAudio ? 'Drag markers or click bar to set Start & End crop times' : 'Drag corners or area to adjust crop'}
        </div>
        <div style="display:flex; gap:0.6rem; align-items:center; flex-wrap:wrap;">
          ${hasRemainingInQueue ? '<button type="button" id="cropperSkipAllBtn" class="btn btn-outlined" style="min-height:36px; padding:0.4rem 0.85rem; font-size:0.8rem;" title="Keep this and all remaining files as originals without cropping">Keep All Originals</button>' : ''}
          <button type="button" id="cropperCancelBtn" class="btn btn-outlined" style="min-height:36px; padding:0.4rem 1rem;" title="Cancel cropping and add this original file to saving sequence">Cancel (Keep Original)</button>
          <button type="button" id="cropperApplyBtn" class="btn btn-primary" style="min-height:36px; padding:0.4rem 1.25rem;">
            <span id="cropperApplyBtnText">Apply Crop</span>
          </button>
        </div>
      `;

      container.appendChild(header);
      container.appendChild(body);
      container.appendChild(footer);
      this._modal.appendChild(container);
      document.body.appendChild(this._modal);

      // Event listeners
      this._modal.querySelector('#cropperCancelBtn').addEventListener('click', () => this._handleCancel(false));
      const skipAllBtn = this._modal.querySelector('#cropperSkipAllBtn');
      if (skipAllBtn) {
        skipAllBtn.addEventListener('click', () => this._handleCancel(true));
      }
      const headerCloseBtn = this._modal.querySelector('#cropperHeaderCloseBtn');
      if (headerCloseBtn) headerCloseBtn.addEventListener('click', () => this._handleCancel(false));
      this._modal.querySelector('#cropperApplyBtn').addEventListener('click', () => this._handleApply());

      // Backdrop click closes and preserves file in saving sequence
      this._modal.addEventListener('click', (e) => {
        if (e.target === this._modal) {
          this._handleCancel(false);
        }
      });

      // Escape key closes and preserves file in saving sequence
      this._escKeyHandler = (e) => {
        if (e.key === 'Escape') {
          this._handleCancel(false);
        }
      };
      window.addEventListener('keydown', this._escKeyHandler);

      if (isAudio) {
        this._setupAudioControls();
      } else {
        this._setupVisualCropper();
      }
    }

    /* =========================================================================
     * Audio Handling
     * ========================================================================= */

    _buildAudioBodyHtml() {
      return `
        <div class="audio-cropper-panel">
          <div class="audio-player-card">
            <audio id="cropperAudioEl" preload="metadata" style="display:none;"></audio>
            
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.4rem; flex-wrap:wrap; gap:0.5rem;">
              <span style="font-size:0.8rem; color:#94a3b8;">Click audio bar to adjust:</span>
              <div class="audio-mode-selector" id="audioModeSelector">
                <button type="button" id="modeAutoBtn" class="audio-mode-btn active-auto" title="Clicking the audio bar adjusts whichever marker is closest">
                  ⚡ Auto (Closest)
                </button>
                <button type="button" id="modeStartBtn" class="audio-mode-btn" title="Clicking the audio bar will set the Start Time">
                  ◀ Set Start Time
                </button>
                <button type="button" id="modeEndBtn" class="audio-mode-btn" title="Clicking the audio bar will set the End Time">
                  Set End Time ▶
                </button>
              </div>
            </div>

            <div class="audio-playback-row">
              <button type="button" id="audioPlayToggleBtn" class="audio-play-btn" title="Play/Pause">
                <span id="audioPlayIcon">▶</span>
              </button>
              <div class="audio-track-wrap">
                <div class="audio-track-progress" id="audioTrackBar" title="Click bar or drag markers to adjust crop range">
                  <div class="audio-track-fill" id="audioPlayFill"></div>
                  <div class="audio-track-cut-region" id="audioCutRegion" title="Drag to slide the crop window"></div>
                  <div class="audio-track-handle audio-track-handle-start" id="audioStartHandle" title="Start Time marker (Drag or click bar to move)">
                    <span style="font-size:10px; font-weight:bold; color:#052e16; pointer-events:none; user-select:none; line-height:1;">◀</span>
                  </div>
                  <div class="audio-track-handle audio-track-handle-end" id="audioEndHandle" title="End Time marker (Drag or click bar to move)">
                    <span style="font-size:10px; font-weight:bold; color:#451a03; pointer-events:none; user-select:none; line-height:1;">▶</span>
                  </div>
                  <div class="audio-track-head" id="audioPlayHead"></div>
                </div>
                <div class="audio-time-row">
                  <span id="audioCurrentTime" style="font-family:monospace; font-size:0.8rem; color:#94a3b8;">00:00.0</span>
                  <span style="font-size:0.75rem; color:#94a3b8;">Click bar to set Start/End times, or drag <span style="color:#4ade80; font-weight:600;">◀ Start</span> and <span style="color:#fbbf24; font-weight:600;">End ▶</span> handles</span>
                  <span id="audioTotalDuration" style="font-family:monospace; font-size:0.8rem; color:#94a3b8;">--:--</span>
                </div>
              </div>
            </div>

            <div class="audio-trim-grid">
              <div class="audio-trim-field">
                <label class="label" style="font-size:0.8rem; margin-bottom:0.25rem; color:#86efac;">◀ Start Time (s)</label>
                <div style="display:flex; gap:0.25rem; align-items:center;">
                  <input type="number" id="audioStartInput" step="0.1" min="0" value="0.0" class="input" style="min-height:34px; font-family:monospace; border-color:rgba(34,197,94,0.4);">
                  <button type="button" id="setStartToCurrentBtn" class="btn btn-outlined" style="min-height:34px; padding:0.2rem 0.6rem; font-size:0.75rem;" title="Set start to current playhead">Set Here</button>
                </div>
              </div>

              <div class="audio-trim-field">
                <label class="label" style="font-size:0.8rem; margin-bottom:0.25rem; color:#fcd34d;">End Time (s) ▶</label>
                <div style="display:flex; gap:0.25rem; align-items:center;">
                  <input type="number" id="audioEndInput" step="0.1" min="0.1" value="10.0" class="input" style="min-height:34px; font-family:monospace; border-color:rgba(245,158,11,0.4);">
                  <button type="button" id="setEndToCurrentBtn" class="btn btn-outlined" style="min-height:34px; padding:0.2rem 0.6rem; font-size:0.75rem;" title="Set end to current playhead">Set Here</button>
                </div>
              </div>
            </div>

            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:0.75rem; padding-top:0.75rem; border-top:1px solid rgba(255,255,255,0.08); flex-wrap:wrap; gap:0.5rem;">
              <div id="audioCutSummary" style="font-size:0.85rem; color:#38bdf8; font-weight:500; font-family:monospace;">
                Crop Interval: 00:00.0 – 00:10.0 (10.0s)
              </div>
              <button type="button" id="previewCutBtn" class="btn btn-outlined" style="min-height:32px; padding:0.2rem 0.8rem; font-size:0.8rem;">
                ▶ Audition Cropped Audio
              </button>
            </div>
          </div>
        </div>
      `;
    }

    _formatTime(sec) {
      if (isNaN(sec) || sec < 0) sec = 0;
      const m = Math.floor(sec / 60);
      const s = Math.floor(sec % 60);
      const ms = Math.floor((sec % 1) * 10);
      return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${ms}`;
    }

    _setupAudioControls() {
      const audio = this._modal.querySelector('#cropperAudioEl');
      this._audioElement = audio;
      const objUrl = URL.createObjectURL(this._activeFile);
      audio.src = objUrl;

      const playBtn = this._modal.querySelector('#audioPlayToggleBtn');
      const playIcon = this._modal.querySelector('#audioPlayIcon');
      const curTimeEl = this._modal.querySelector('#audioCurrentTime');
      const durTimeEl = this._modal.querySelector('#audioTotalDuration');
      const startInput = this._modal.querySelector('#audioStartInput');
      const endInput = this._modal.querySelector('#audioEndInput');
      const startHandle = this._modal.querySelector('#audioStartHandle');
      const endHandle = this._modal.querySelector('#audioEndHandle');
      const cutRegion = this._modal.querySelector('#audioCutRegion');
      const playFill = this._modal.querySelector('#audioPlayFill');
      const playHead = this._modal.querySelector('#audioPlayHead');
      const trackBar = this._modal.querySelector('#audioTrackBar');
      const previewCutBtn = this._modal.querySelector('#previewCutBtn');

      // Click mode state: 'auto' | 'start' | 'end'
      let clickMode = 'auto';
      const modeStartBtn = this._modal.querySelector('#modeStartBtn');
      const modeEndBtn = this._modal.querySelector('#modeEndBtn');
      const modeAutoBtn = this._modal.querySelector('#modeAutoBtn');

      const setMode = (m) => {
        clickMode = m;
        if (modeStartBtn) modeStartBtn.className = `audio-mode-btn ${m === 'start' ? 'active-start' : ''}`;
        if (modeEndBtn) modeEndBtn.className = `audio-mode-btn ${m === 'end' ? 'active-end' : ''}`;
        if (modeAutoBtn) modeAutoBtn.className = `audio-mode-btn ${m === 'auto' ? 'active-auto' : ''}`;
      };

      if (modeStartBtn) modeStartBtn.addEventListener('click', () => setMode('start'));
      if (modeEndBtn) modeEndBtn.addEventListener('click', () => setMode('end'));
      if (modeAutoBtn) modeAutoBtn.addEventListener('click', () => setMode('auto'));

      if (startInput) startInput.addEventListener('focus', () => setMode('start'));
      if (endInput) endInput.addEventListener('focus', () => setMode('end'));

      audio.addEventListener('error', () => {
        console.warn('Audio decoding failed in browser preview');
        const infoEl = this._modal ? this._modal.querySelector('#cropperFileInfo') : null;
        if (infoEl) infoEl.textContent = `${this._activeFile.name} (Playback preview unavailable)`;
      });

      audio.addEventListener('loadedmetadata', () => {
        this._audioDuration = audio.duration || 10;
        this._audioStartTime = 0;
        this._audioEndTime = Math.min(this._audioDuration, Math.max(5, this._audioDuration * 0.5));
        
        durTimeEl.textContent = this._formatTime(this._audioDuration);
        startInput.max = this._audioDuration;
        endInput.max = this._audioDuration;
        startInput.value = (0).toFixed(1);
        endInput.value = this._audioEndTime.toFixed(1);

        const infoEl = this._modal.querySelector('#cropperFileInfo');
        if (infoEl) {
          infoEl.textContent = `${this._activeFile.name} (${(this._activeFile.size / 1024).toFixed(1)} KB, ${this._formatTime(this._audioDuration)})`;
        }

        this._updateAudioRegionUI();
      });

      const updateUI = () => {
        curTimeEl.textContent = this._formatTime(audio.currentTime);
        if (this._audioDuration > 0) {
          const pct = (audio.currentTime / this._audioDuration) * 100;
          playFill.style.width = `${pct}%`;
          playHead.style.left = `${pct}%`;
        }
      };

      audio.addEventListener('timeupdate', updateUI);

      playBtn.addEventListener('click', () => {
        if (audio.paused) {
          audio.play();
          playIcon.textContent = '⏸';
        } else {
          audio.pause();
          playIcon.textContent = '▶';
        }
      });

      audio.addEventListener('ended', () => {
        playIcon.textContent = '▶';
      });

      // Dragging handles or cut region
      let activeDrag = null; // 'start' | 'end' | 'region'
      let dragStartX = 0;
      let dragInitialStart = 0;
      let dragInitialEnd = 0;
      let hasDragged = false;
      let dragJustEnded = false;

      const getTimeFromEvent = (e) => {
        const rect = trackBar.getBoundingClientRect();
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        const pos = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
        return pos * this._audioDuration;
      };

      if (startHandle) {
        startHandle.addEventListener('mousedown', (e) => {
          e.stopPropagation();
          activeDrag = 'start';
          hasDragged = false;
          dragStartX = e.clientX;
          setMode('start');
        });
        startHandle.addEventListener('touchstart', (e) => {
          e.stopPropagation();
          activeDrag = 'start';
          hasDragged = false;
          dragStartX = e.touches[0].clientX;
          setMode('start');
        }, { passive: true });
      }

      if (endHandle) {
        endHandle.addEventListener('mousedown', (e) => {
          e.stopPropagation();
          activeDrag = 'end';
          hasDragged = false;
          dragStartX = e.clientX;
          setMode('end');
        });
        endHandle.addEventListener('touchstart', (e) => {
          e.stopPropagation();
          activeDrag = 'end';
          hasDragged = false;
          dragStartX = e.touches[0].clientX;
          setMode('end');
        }, { passive: true });
      }

      if (cutRegion) {
        cutRegion.addEventListener('mousedown', (e) => {
          if (e.target === startHandle || e.target === endHandle ||
              (startHandle && startHandle.contains(e.target)) ||
              (endHandle && endHandle.contains(e.target))) return;
          activeDrag = 'region';
          hasDragged = false;
          dragStartX = e.clientX;
          dragInitialStart = this._audioStartTime;
          dragInitialEnd = this._audioEndTime;
        });
        cutRegion.addEventListener('touchstart', (e) => {
          if (e.target === startHandle || e.target === endHandle ||
              (startHandle && startHandle.contains(e.target)) ||
              (endHandle && endHandle.contains(e.target))) return;
          activeDrag = 'region';
          hasDragged = false;
          dragStartX = e.touches[0].clientX;
          dragInitialStart = this._audioStartTime;
          dragInitialEnd = this._audioEndTime;
        }, { passive: true });
      }

      this._audioMouseMoveHandler = (e) => {
        if (!activeDrag || this._audioDuration <= 0) return;
        const curX = e.touches ? e.touches[0].clientX : e.clientX;
        if (Math.abs(curX - dragStartX) > 3) {
          hasDragged = true;
        }
        if (activeDrag === 'start') {
          const t = getTimeFromEvent(e);
          this._audioStartTime = Math.max(0, Math.min(t, this._audioEndTime - 0.1));
          this._updateAudioRegionUI();
        } else if (activeDrag === 'end') {
          const t = getTimeFromEvent(e);
          this._audioEndTime = Math.min(this._audioDuration, Math.max(t, this._audioStartTime + 0.1));
          this._updateAudioRegionUI();
        } else if (activeDrag === 'region') {
          const rect = trackBar.getBoundingClientRect();
          const deltaX = curX - dragStartX;
          const deltaSec = (deltaX / rect.width) * this._audioDuration;
          const windowLen = dragInitialEnd - dragInitialStart;
          let newStart = dragInitialStart + deltaSec;
          let newEnd = dragInitialEnd + deltaSec;
          if (newStart < 0) {
            newStart = 0;
            newEnd = windowLen;
          } else if (newEnd > this._audioDuration) {
            newEnd = this._audioDuration;
            newStart = this._audioDuration - windowLen;
          }
          this._audioStartTime = Math.max(0, newStart);
          this._audioEndTime = Math.min(this._audioDuration, newEnd);
          this._updateAudioRegionUI();
        }
      };

      this._audioMouseUpHandler = () => {
        if (activeDrag) {
          if (hasDragged) {
            dragJustEnded = true;
            setTimeout(() => { dragJustEnded = false; }, 100);
          }
          activeDrag = null;
          hasDragged = false;
        }
      };

      window.addEventListener('mousemove', this._audioMouseMoveHandler);
      window.addEventListener('mouseup', this._audioMouseUpHandler);
      window.addEventListener('touchmove', this._audioMouseMoveHandler, { passive: true });
      window.addEventListener('touchend', this._audioMouseUpHandler);

      // Clicking on trackBar sets start or end time directly
      trackBar.addEventListener('click', (e) => {
        if (dragJustEnded) {
          dragJustEnded = false;
          return;
        }
        if (e.target === startHandle || e.target === endHandle ||
            (startHandle && startHandle.contains(e.target)) ||
            (endHandle && endHandle.contains(e.target))) {
          return;
        }

        const rect = trackBar.getBoundingClientRect();
        const pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        const clickedTime = pos * this._audioDuration;

        let effectiveMode = clickMode;
        if (e.altKey || e.ctrlKey) {
          effectiveMode = 'start';
        } else if (e.shiftKey) {
          effectiveMode = 'end';
        }

        if (effectiveMode === 'start') {
          this._audioStartTime = Math.max(0, Math.min(clickedTime, this._audioEndTime - 0.1));
          audio.currentTime = this._audioStartTime;
          if (startHandle) {
            startHandle.classList.add('pulse');
            setTimeout(() => startHandle.classList.remove('pulse'), 250);
          }
        } else if (effectiveMode === 'end') {
          this._audioEndTime = Math.min(this._audioDuration, Math.max(clickedTime, this._audioStartTime + 0.1));
          audio.currentTime = this._audioEndTime;
          if (endHandle) {
            endHandle.classList.add('pulse');
            setTimeout(() => endHandle.classList.remove('pulse'), 250);
          }
        } else {
          // Auto mode: move whichever marker is closest without leaving auto mode
          const distStart = Math.abs(clickedTime - this._audioStartTime);
          const distEnd = Math.abs(clickedTime - this._audioEndTime);
          if (clickedTime <= this._audioStartTime || distStart <= distEnd) {
            this._audioStartTime = Math.max(0, Math.min(clickedTime, this._audioEndTime - 0.1));
            audio.currentTime = this._audioStartTime;
            if (startHandle) {
              startHandle.classList.add('pulse');
              setTimeout(() => startHandle.classList.remove('pulse'), 250);
            }
          } else {
            this._audioEndTime = Math.min(this._audioDuration, Math.max(clickedTime, this._audioStartTime + 0.1));
            audio.currentTime = this._audioEndTime;
            if (endHandle) {
              endHandle.classList.add('pulse');
              setTimeout(() => endHandle.classList.remove('pulse'), 250);
            }
          }
        }

        updateUI();
        this._updateAudioRegionUI();
      });

      startInput.addEventListener('input', () => {
        let val = parseFloat(startInput.value) || 0;
        val = Math.max(0, Math.min(val, this._audioEndTime - 0.1));
        this._audioStartTime = val;
        this._updateAudioRegionUI();
      });

      endInput.addEventListener('input', () => {
        let val = parseFloat(endInput.value) || 0;
        val = Math.max(this._audioStartTime + 0.1, Math.min(val, this._audioDuration));
        this._audioEndTime = val;
        this._updateAudioRegionUI();
      });

      this._modal.querySelector('#setStartToCurrentBtn').addEventListener('click', () => {
        this._audioStartTime = Math.min(audio.currentTime, this._audioEndTime - 0.1);
        setMode('start');
        this._updateAudioRegionUI();
      });

      this._modal.querySelector('#setEndToCurrentBtn').addEventListener('click', () => {
        this._audioEndTime = Math.max(audio.currentTime, this._audioStartTime + 0.1);
        setMode('end');
        this._updateAudioRegionUI();
      });

      previewCutBtn.addEventListener('click', () => {
        if (this._audioPreviewInterval) clearInterval(this._audioPreviewInterval);
        audio.currentTime = this._audioStartTime;
        audio.play();
        playIcon.textContent = '⏸';

        this._audioPreviewInterval = setInterval(() => {
          if (audio.currentTime >= this._audioEndTime || audio.paused) {
            audio.pause();
            playIcon.textContent = '▶';
            clearInterval(this._audioPreviewInterval);
          }
        }, 50);
      });
    }

    _updateAudioRegionUI() {
      const cutRegion = this._modal.querySelector('#audioCutRegion');
      const startHandle = this._modal.querySelector('#audioStartHandle');
      const endHandle = this._modal.querySelector('#audioEndHandle');
      const cutSummary = this._modal.querySelector('#audioCutSummary');
      const dimInfo = this._modal.querySelector('#cropperDimInfo');
      const startInput = this._modal.querySelector('#audioStartInput');
      const endInput = this._modal.querySelector('#audioEndInput');

      if (this._audioDuration > 0) {
        const leftPct = (this._audioStartTime / this._audioDuration) * 100;
        const widthPct = ((this._audioEndTime - this._audioStartTime) / this._audioDuration) * 100;
        const endPct = (this._audioEndTime / this._audioDuration) * 100;

        if (cutRegion) {
          cutRegion.style.left = `${leftPct}%`;
          cutRegion.style.width = `${widthPct}%`;
        }
        if (startHandle) {
          startHandle.style.left = `${leftPct}%`;
        }
        if (endHandle) {
          endHandle.style.left = `${endPct}%`;
        }
      }

      if (startInput && document.activeElement !== startInput) {
        startInput.value = this._audioStartTime.toFixed(1);
      }
      if (endInput && document.activeElement !== endInput) {
        endInput.value = this._audioEndTime.toFixed(1);
      }

      const diff = Math.max(0, this._audioEndTime - this._audioStartTime);
      const text = `Crop Interval: ${this._formatTime(this._audioStartTime)} – ${this._formatTime(this._audioEndTime)} (${diff.toFixed(1)}s)`;
      if (cutSummary) cutSummary.textContent = text;
      if (dimInfo) dimInfo.textContent = text;
    }

    /* =========================================================================
     * Visual Cropping (Image, GIF, Video)
     * ========================================================================= */

    _buildVideoTrimHtml() {
      return `
        <div class="video-trim-bar" style="margin-top:0.75rem; padding:0.6rem 0.8rem; background:rgba(255,255,255,0.04); border-radius:6px; display:flex; gap:1rem; align-items:center; flex-wrap:wrap;">
          <span style="font-size:0.8rem; color:#94a3b8; font-weight:600;">Optional Video Cut:</span>
          <div style="display:flex; align-items:center; gap:0.4rem;">
            <label style="font-size:0.75rem; color:#cbd5e1;">Start (s):</label>
            <input type="number" id="videoStartInput" min="0" step="0.1" value="0.0" class="input" style="width:75px; min-height:28px; padding:0.1rem 0.3rem; font-size:0.75rem; font-family:monospace;">
          </div>
          <div style="display:flex; align-items:center; gap:0.4rem;">
            <label style="font-size:0.75rem; color:#cbd5e1;">End (s):</label>
            <input type="number" id="videoEndInput" min="0.1" step="0.1" value="0.0" class="input" style="width:75px; min-height:28px; padding:0.1rem 0.3rem; font-size:0.75rem; font-family:monospace;">
          </div>
        </div>
      `;
    }

    async _setupVisualCropper() {
      const ratioContainer = this._modal.querySelector('#cropperRatioButtons');
      if (ratioContainer) {
        this.presets.forEach(p => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.textContent = p.label;
          btn.className = `media-cropper-ratio-btn ${this.targetAspectRatio === p.ratio ? 'active' : ''}`;
          btn.addEventListener('click', () => {
            this.targetAspectRatio = p.ratio;
            ratioContainer.querySelectorAll('button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            this._initCropArea();
            this._draw();
          });
          ratioContainer.appendChild(btn);
        });
      }

      try {
        const mediaSource = await this._loadMediaElement(this._activeFile);
        this._sourceMedia = mediaSource;

        const spinner = this._modal.querySelector('#cropperLoadingSpinner');
        if (spinner) spinner.style.display = 'none';

        const canvasWrap = this._modal.querySelector('#cropperCanvasWrap');
        this._canvas = document.createElement('canvas');
        this._canvas.className = 'media-cropper-canvas';
        this._ctx = this._canvas.getContext('2d');
        canvasWrap.appendChild(this._canvas);

        const infoEl = this._modal.querySelector('#cropperFileInfo');
        if (infoEl) {
          infoEl.textContent = `${this._activeFile.name} (${mediaSource.width}×${mediaSource.height}px, ${(this._activeFile.size / 1024).toFixed(1)} KB)`;
        }

        this._setupCanvasScale();
        this._initCropArea();
        this._bindCanvasEvents();
        this._draw();
      } catch (err) {
        console.error('Failed to load media preview:', err);
        alert('Could not load media preview for cropping: ' + err.message);
        this._handleCancel();
      }
    }

    _loadMediaElement(file) {
      return new Promise((resolve, reject) => {
        const objUrl = URL.createObjectURL(file);

        if (this._mediaType === 'video') {
          const video = document.createElement('video');
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
              this._videoDuration = video.duration || 0;
              const endIn = this._modal.querySelector('#videoEndInput');
              if (endIn && this._videoDuration > 0) endIn.value = this._videoDuration.toFixed(1);
              resolve(img);
            };
            img.src = cvs.toDataURL('image/png');
          });

          video.addEventListener('error', () => {
            URL.revokeObjectURL(objUrl);
            reject(new Error('Video could not be loaded'));
          });
        } else {
          const img = new Image();
          img.onload = () => {
            URL.revokeObjectURL(objUrl);
            resolve(img);
          };
          img.onerror = () => {
            URL.revokeObjectURL(objUrl);
            reject(new Error('Image format could not be decoded'));
          };
          img.src = objUrl;
        }
      });
    }

    _setupCanvasScale() {
      const maxW = Math.min(window.innerWidth * 0.85, 840);
      const maxH = Math.min(window.innerHeight * 0.52, 500);

      const scaleW = maxW / this._sourceMedia.width;
      const scaleH = maxH / this._sourceMedia.height;
      this._scale = Math.min(1, scaleW, scaleH);

      this._canvas.width = Math.round(this._sourceMedia.width * this._scale);
      this._canvas.height = Math.round(this._sourceMedia.height * this._scale);
    }

    _initCropArea() {
      const canvasW = this._canvas.width;
      const canvasH = this._canvas.height;

      if (this.targetAspectRatio) {
        let w = canvasW * 0.85;
        let h = w / this.targetAspectRatio;
        if (h > canvasH * 0.85) {
          h = canvasH * 0.85;
          w = h * this.targetAspectRatio;
        }
        this._cropArea = {
          x: Math.round((canvasW - w) / 2),
          y: Math.round((canvasH - h) / 2),
          width: Math.round(w),
          height: Math.round(h),
        };
      } else {
        this._cropArea = {
          x: Math.round(canvasW * 0.08),
          y: Math.round(canvasH * 0.08),
          width: Math.round(canvasW * 0.84),
          height: Math.round(canvasH * 0.84),
        };
      }
    }

    _bindCanvasEvents() {
      this._canvas.addEventListener('mousedown', (e) => this._onMouseDown(e));
      this._onMouseMoveHandler = (e) => this._onMouseMove(e);
      this._onMouseUpHandler = () => this._onMouseUp();
      window.addEventListener('mousemove', this._onMouseMoveHandler);
      window.addEventListener('mouseup', this._onMouseUpHandler);
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
      const handleSize = 14;

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
      } else if (this._activeHandle === 'tr') {
        const newW = Math.max(40, area.width + dx);
        const newH = tr ? newW / tr : Math.max(40, area.height - dy);
        const newY = area.y + area.height - newH;
        if (newY >= 0 && area.x + newW <= this._canvas.width) {
          area.y = newY;
          area.width = newW;
          area.height = newH;
        }
      } else if (this._activeHandle === 'bl') {
        const newW = Math.max(40, area.width - dx);
        const newH = tr ? newW / tr : Math.max(40, area.height + dy);
        const newX = area.x + area.width - newW;
        if (newX >= 0 && area.y + newH <= this._canvas.height) {
          area.x = newX;
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
      if (!this._ctx || !this._canvas) return;

      this._ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);
      this._ctx.drawImage(this._sourceMedia, 0, 0, this._canvas.width, this._canvas.height);

      // Dark overlay
      this._ctx.fillStyle = 'rgba(15, 23, 42, 0.65)';
      this._ctx.fillRect(0, 0, this._canvas.width, this._canvas.height);

      const { x, y, width, height } = this._cropArea;

      // Draw highlighted region
      this._ctx.clearRect(x, y, width, height);
      this._ctx.drawImage(
        this._sourceMedia,
        x / this._scale,
        y / this._scale,
        width / this._scale,
        height / this._scale,
        x,
        y,
        width,
        height
      );

      // Boundary stroke
      this._ctx.strokeStyle = '#38bdf8';
      this._ctx.lineWidth = 2;
      this._ctx.strokeRect(x, y, width, height);

      // Grid rule-of-thirds lines
      this._ctx.strokeStyle = 'rgba(255, 255, 255, 0.25)';
      this._ctx.lineWidth = 1;
      this._ctx.beginPath();
      this._ctx.moveTo(x + width / 3, y);
      this._ctx.lineTo(x + width / 3, y + height);
      this._ctx.moveTo(x + (2 * width) / 3, y);
      this._ctx.lineTo(x + (2 * width) / 3, y + height);
      this._ctx.moveTo(x, y + height / 3);
      this._ctx.lineTo(x + width, y + height / 3);
      this._ctx.moveTo(x, y + (2 * height) / 3);
      this._ctx.lineTo(x + width, y + (2 * height) / 3);
      this._ctx.stroke();

      // Corner circles
      this._ctx.fillStyle = '#ffffff';
      this._ctx.strokeStyle = '#0284c7';
      this._ctx.lineWidth = 2;
      const corners = [
        [x, y],
        [x + width, y],
        [x, y + height],
        [x + width, y + height],
      ];
      corners.forEach(([cx, cy]) => {
        this._ctx.beginPath();
        this._ctx.arc(cx, cy, 6, 0, Math.PI * 2);
        this._ctx.fill();
        this._ctx.stroke();
      });

      const realW = Math.round(width / this._scale);
      const realH = Math.round(height / this._scale);
      const dimEl = this._modal.querySelector('#cropperDimInfo');
      if (dimEl) {
        dimEl.textContent = `Crop Area: ${realW} × ${realH} px`;
      }
    }

    hasTransparency(canvas) {
      if (this._activeFile && this._activeFile.type === 'image/jpeg') return false;
      const ctx = canvas.getContext('2d', { willReadFrequently: true });
      const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const data = imgData.data;
      for (let i = 3; i < data.length; i += 4) {
        if (data[i] < 255) return true;
      }
      return false;
    }

    /* =========================================================================
     * Apply & Server API Dispatch
     * ========================================================================= */

    async _handleApply() {
      const applyBtn = this._modal.querySelector('#cropperApplyBtn');
      const applyText = this._modal.querySelector('#cropperApplyBtnText');
      applyBtn.disabled = true;
      if (applyText) applyText.textContent = 'Processing media...';
      this._abortController = new AbortController();

      try {
        let finalFile = null;

        if (this._mediaType === 'audio') {
          finalFile = await this._processAudioServer();
        } else if (this._mediaType === 'video' || this._mediaType === 'gif') {
          finalFile = await this._processVisualServer();
        } else {
          // Static image: perform alpha-safe client canvas crop
          finalFile = await this._processImageClient();
        }

        this._cleanup();
        if (this._resolve) this._resolve(finalFile);
      } catch (err) {
        if (err.name === 'AbortError' || this._cancelled) {
          // Cancelled during processing; original file is already resolved and staged
          return;
        }
        console.error('Crop processing failed:', err);
        alert('Cropping failed: ' + (err.message || 'Unknown error'));
        applyBtn.disabled = false;
        if (applyText) applyText.textContent = this._mediaType === 'audio' ? 'Apply Cut' : 'Apply Crop';
      }
    }

    async _processImageClient() {
      const realX = Math.round(this._cropArea.x / this._scale);
      const realY = Math.round(this._cropArea.y / this._scale);
      const realW = Math.round(this._cropArea.width / this._scale);
      const realH = Math.round(this._cropArea.height / this._scale);

      const croppedCanvas = document.createElement('canvas');
      croppedCanvas.width = realW;
      croppedCanvas.height = realH;
      const cCtx = croppedCanvas.getContext('2d');
      cCtx.drawImage(this._sourceMedia, realX, realY, realW, realH, 0, 0, realW, realH);

      const hasAlpha = this.hasTransparency(croppedCanvas);
      let mime = 'image/jpeg';
      let ext = '.jpg';
      let quality = 0.95;

      if (hasAlpha || this._activeFile.type === 'image/png' || this._activeFile.type === 'image/webp') {
        mime = this._activeFile.type === 'image/webp' ? 'image/webp' : 'image/png';
        ext = this._activeFile.type === 'image/webp' ? '.webp' : '.png';
        quality = undefined; // PNG lossless
      }

      return new Promise((resolve) => {
        croppedCanvas.toBlob((blob) => {
          const stem = this._activeFile.name.replace(/\.[^/.]+$/, '');
          const outName = `${stem}_cropped${ext}`;
          resolve(new File([blob], outName, { type: mime, lastModified: Date.now() }));
        }, mime, quality);
      });
    }

    async _processVisualServer() {
      const realX = Math.round(this._cropArea.x / this._scale);
      const realY = Math.round(this._cropArea.y / this._scale);
      const realW = Math.round(this._cropArea.width / this._scale);
      const realH = Math.round(this._cropArea.height / this._scale);

      const formData = new FormData();
      formData.append('file', this._activeFile);
      formData.append('crop_type', this._mediaType);
      formData.append('x', realX);
      formData.append('y', realY);
      formData.append('width', realW);
      formData.append('height', realH);

      if (this._mediaType === 'video') {
        const vStart = parseFloat(this._modal.querySelector('#videoStartInput')?.value || '0');
        const vEnd = parseFloat(this._modal.querySelector('#videoEndInput')?.value || '0');
        if (vStart > 0) formData.append('start_time', vStart);
        if (vEnd > vStart) formData.append('end_time', vEnd);
      }

      const res = await fetch('/api/v1/media/crop', {
        method: 'POST',
        body: formData,
        signal: this._abortController ? this._abortController.signal : undefined,
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => 'Server error');
        throw new Error(`Media server crop failed (${res.status}): ${errText}`);
      }

      const blob = await res.blob();
      const outFilename = res.headers.get('X-Media-Filename') || `${this._activeFile.name.replace(/\.[^/.]+$/, '')}_cropped.${this._mediaType === 'gif' ? 'gif' : 'mp4'}`;
      const outMime = res.headers.get('X-Media-Mime') || blob.type || (this._mediaType === 'gif' ? 'image/gif' : 'video/mp4');

      return new File([blob], outFilename, { type: outMime, lastModified: Date.now() });
    }

    async _processAudioServer() {
      const formData = new FormData();
      formData.append('file', this._activeFile);
      formData.append('crop_type', 'audio');
      formData.append('start_time', this._audioStartTime);
      formData.append('end_time', this._audioEndTime);

      const res = await fetch('/api/v1/media/crop', {
        method: 'POST',
        body: formData,
        signal: this._abortController ? this._abortController.signal : undefined,
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => 'Server error');
        throw new Error(`Audio cut failed (${res.status}): ${errText}`);
      }

      const blob = await res.blob();
      const outFilename = res.headers.get('X-Media-Filename') || `${this._activeFile.name.replace(/\.[^/.]+$/, '')}_cut.mp3`;
      const outMime = res.headers.get('X-Media-Mime') || blob.type || 'audio/mpeg';

      return new File([blob], outFilename, { type: outMime, lastModified: Date.now() });
    }

    _handleCancel(skipAll = false) {
      this._cancelled = true;
      if (this._abortController) {
        this._abortController.abort();
      }
      const origFile = this._activeFile;
      if (origFile) {
        origFile.cropCancelled = true;
        if (skipAll) {
          origFile.skipRemainingCrops = true;
        }
      }
      this._cleanup();
      if (typeof showToast === 'function' && origFile) {
        const msg = skipAll
          ? `Crop skipped: "${origFile.name}" and remaining files added to saving sequence.`
          : `Crop cancelled: "${origFile.name}" added to saving sequence.`;
        showToast(msg, 'info', 3200);
      }
      // Crucial: resolve with the original file so it is added in the saving sequence
      if (this._resolve) {
        this._resolve(origFile);
      }
    }

    _cleanup() {
      if (this._escKeyHandler) {
        window.removeEventListener('keydown', this._escKeyHandler);
        this._escKeyHandler = null;
      }
      if (this._audioPreviewInterval) {
        clearInterval(this._audioPreviewInterval);
        this._audioPreviewInterval = null;
      }
      if (this._audioElement) {
        this._audioElement.pause();
        this._audioElement = null;
      }
      if (this._audioMouseMoveHandler) {
        window.removeEventListener('mousemove', this._audioMouseMoveHandler);
        window.removeEventListener('touchmove', this._audioMouseMoveHandler);
        this._audioMouseMoveHandler = null;
      }
      if (this._audioMouseUpHandler) {
        window.removeEventListener('mouseup', this._audioMouseUpHandler);
        window.removeEventListener('touchend', this._audioMouseUpHandler);
        this._audioMouseUpHandler = null;
      }
      if (this._onMouseMoveHandler) {
        window.removeEventListener('mousemove', this._onMouseMoveHandler);
        this._onMouseMoveHandler = null;
      }
      if (this._onMouseUpHandler) {
        window.removeEventListener('mouseup', this._onMouseUpHandler);
        this._onMouseUpHandler = null;
      }
      if (this._modal && this._modal.parentNode) {
        this._modal.parentNode.removeChild(this._modal);
      }
      this._modal = null;
    }
  }

  window.MediaCropper = new MediaCropperManager();
})();
