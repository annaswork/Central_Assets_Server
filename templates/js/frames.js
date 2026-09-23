/**
 * Interactive Frame Placeholder Canvas Editor.
 * Overlays placeholder boxes on the uploaded frame image.
 * Supports:
 * - Drag inside box to move
 * - 8 resize handles (NW, N, NE, E, SE, S, SW, W) with rotated anchor math
 * - Rotation knob with stem line clamped to [-45°, 45°]
 * - Click & drag on empty canvas to draw new placeholder slots
 * - Keyboard nudge (Arrow keys) & Delete
 * - Real-time two-way synchronization with Inspector inputs and hidden #moreFieldsJson
 */

(function () {
  let editorInstance = null;

  window.initFrameEditor = function (config) {
    const canvas = document.getElementById("frameCanvas");
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    const inspector = document.getElementById("placeholderInspector");
    const jsonInput = document.getElementById("moreFieldsJson");

    // Standardize incoming placeholder / coordinate objects
    let rawCoords = config.coordinates || config.placeholders || [];
    let placeholders = rawCoords.map((c, i) => {
      let rot = parseFloat(c.rotation || 0) || 0;
      let w = parseFloat(c.width || 0) || 0;
      let h = parseFloat(c.height || 0) || 0;
      while (rot > 45) { rot -= 90; const t = w; w = h; h = t; }
      while (rot < -45) { rot += 90; const t = w; w = h; h = t; }
      rot = Math.max(-45, Math.min(45, Math.round(rot * 10) / 10));
      return {
        x: Math.round(parseFloat(c.x || 0)),
        y: Math.round(parseFloat(c.y || 0)),
        width: Math.round(w),
        height: Math.round(h),
        rotation: rot,
        elevation: c.elevation !== undefined ? parseInt(c.elevation, 10) : i,
        index: i + 1,
      };
    });

    let selectedIndex = placeholders.length > 0 ? 0 : -1;
    let hoveredHandle = null; // "rotate", "nw", "n", "ne", "e", "se", "s", "sw", "w", "inside", or null
    let hoveredBoxIndex = -1;

    // Drag interaction state
    let isDragging = false;
    let dragMode = null; // "move", "resize", "rotate", "create"
    let resizeHandle = null; // "nw", "n", "ne", "e", "se", "s", "sw", "w"
    let dragStartPos = { x: 0, y: 0 };
    let initialBoxState = null;
    let resizeAnchorWorld = null;
    let tempCreateBox = null;

    const HANDLE_SIZE = 12;
    const ROTATE_HANDLE_OFFSET = 28;
    const ROTATE_HANDLE_RADIUS = 7;

    const image = new Image();
    image.crossOrigin = "anonymous";
    image.src = config.imageUrl;

    image.onload = function () {
      canvas.width = config.width || image.naturalWidth || 1080;
      canvas.height = config.height || image.naturalHeight || 1080;
      render();
      renderInspector();
      syncJsonInput();
    };

    // If image was already cached/loaded
    if (image.complete && image.naturalWidth) {
      canvas.width = config.width || image.naturalWidth || 1080;
      canvas.height = config.height || image.naturalHeight || 1080;
      render();
      renderInspector();
      syncJsonInput();
    }

    // --- Math & Geometry Helpers ---

    function getCanvasPos(e) {
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      return {
        x: (e.clientX - rect.left) * scaleX,
        y: (e.clientY - rect.top) * scaleY,
      };
    }

    function worldToLocal(wx, wy, box) {
      const cx = box.x + box.width / 2;
      const cy = box.y + box.height / 2;
      const rad = (-box.rotation * Math.PI) / 180;
      const dx = wx - cx;
      const dy = wy - cy;
      return {
        lx: dx * Math.cos(rad) - dy * Math.sin(rad),
        ly: dx * Math.sin(rad) + dy * Math.cos(rad),
      };
    }

    function localToWorld(lx, ly, box) {
      const cx = box.x + box.width / 2;
      const cy = box.y + box.height / 2;
      const rad = (box.rotation * Math.PI) / 180;
      return {
        wx: cx + lx * Math.cos(rad) - ly * Math.sin(rad),
        wy: cy + lx * Math.sin(rad) + ly * Math.cos(rad),
      };
    }

    function hitTestBox(pos, box) {
      const { lx, ly } = worldToLocal(pos.x, pos.y, box);
      const hw = box.width / 2;
      const hh = box.height / 2;
      return Math.abs(lx) <= hw && Math.abs(ly) <= hh;
    }

    function hitTestHandles(pos, box) {
      const { lx, ly } = worldToLocal(pos.x, pos.y, box);
      const hw = box.width / 2;
      const hh = box.height / 2;
      const hTol = HANDLE_SIZE + 4;

      // 1. Rotation knob at (0, -hh - ROTATE_HANDLE_OFFSET)
      const rotDist = Math.hypot(lx - 0, ly - (-hh - ROTATE_HANDLE_OFFSET));
      if (rotDist <= ROTATE_HANDLE_RADIUS + 6) {
        return "rotate";
      }

      // 2. Corner & Edge Resize Handles
      const handles = {
        nw: { x: -hw, y: -hh },
        n:  { x: 0,   y: -hh },
        ne: { x: hw,  y: -hh },
        e:  { x: hw,  y: 0 },
        se: { x: hw,  y: hh },
        s:  { x: 0,   y: hh },
        sw: { x: -hw, y: hh },
        w:  { x: -hw, y: 0 },
      };

      for (const [name, pt] of Object.entries(handles)) {
        if (Math.abs(lx - pt.x) <= hTol / 2 && Math.abs(ly - pt.y) <= hTol / 2) {
          return name;
        }
      }

      // 3. Inside box area
      if (Math.abs(lx) <= hw && Math.abs(ly) <= hh) {
        return "inside";
      }

      return null;
    }

    function getResizeCursor(handleName, rotationDeg) {
      const cursors = ["ns-resize", "nesw-resize", "ew-resize", "nwse-resize"];
      const baseAngles = {
        n: 0,
        ne: 45,
        e: 90,
        se: 135,
        s: 180,
        sw: 225,
        w: 270,
        nw: 315,
      };
      if (typeof baseAngles[handleName] === "undefined") return "default";
      const totalAngle = (baseAngles[handleName] + rotationDeg + 360) % 180;
      const idx = Math.round(totalAngle / 45) % 4;
      return cursors[idx];
    }

    // --- Canvas Rendering ---

    function render() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // 1. Draw Frame background image
      if (image.complete && image.naturalWidth) {
        ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      } else {
        ctx.fillStyle = "#1E293B";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
      }

      // 2. Draw configured placeholder bounding boxes
      placeholders.forEach((p, idx) => {
        ctx.save();
        const isSelected = idx === selectedIndex;
        const isHovered = idx === hoveredBoxIndex && !isSelected;

        const cx = p.x + p.width / 2;
        const cy = p.y + p.height / 2;
        ctx.translate(cx, cy);
        ctx.rotate((p.rotation * Math.PI) / 180);

        const hw = p.width / 2;
        const hh = p.height / 2;

        // Box fill
        if (isSelected) {
          ctx.fillStyle = "rgba(245, 158, 11, 0.28)";
        } else if (isHovered) {
          ctx.fillStyle = "rgba(99, 102, 241, 0.30)";
        } else {
          ctx.fillStyle = "rgba(99, 102, 241, 0.18)";
        }
        ctx.fillRect(-hw, -hh, p.width, p.height);

        // Box border
        ctx.strokeStyle = isSelected ? "#F59E0B" : (isHovered ? "#818CF8" : "#6366F1");
        ctx.lineWidth = isSelected ? 3 : 2;
        if (isSelected) {
          ctx.shadowColor = "rgba(245, 158, 11, 0.6)";
          ctx.shadowBlur = 8;
        }
        ctx.strokeRect(-hw, -hh, p.width, p.height);
        ctx.shadowBlur = 0; // reset shadow

        // Corner slot index badge
        const badgeText = `#${p.index} (z:${p.elevation})`;
        ctx.font = "bold 13px sans-serif";
        const textW = ctx.measureText(badgeText).width;
        ctx.fillStyle = isSelected ? "#D97706" : "#4F46E5";
        ctx.fillRect(-hw, -hh, textW + 12, 22);
        ctx.fillStyle = "#FFFFFF";
        ctx.fillText(badgeText, -hw + 6, -hh + 16);

        // Dimensions label in bottom right corner
        const dimsText = `${Math.round(p.width)}×${Math.round(p.height)}${p.rotation ? ` · ${p.rotation > 0 ? '+' : ''}${p.rotation}°` : ''}`;
        ctx.font = "600 11px sans-serif";
        const dimsW = ctx.measureText(dimsText).width;
        ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
        ctx.fillRect(hw - dimsW - 8, hh - 18, dimsW + 8, 18);
        ctx.fillStyle = "#E2E8F0";
        ctx.fillText(dimsText, hw - dimsW - 4, hh - 5);

        // If selected: Draw 8 Resize Handles + Rotation Stem & Knob
        if (isSelected) {
          // --- Rotation Handle ---
          const rotY = -hh - ROTATE_HANDLE_OFFSET;
          // Stem line
          ctx.beginPath();
          ctx.moveTo(0, -hh);
          ctx.lineTo(0, rotY);
          ctx.strokeStyle = "#F59E0B";
          ctx.lineWidth = 2;
          ctx.stroke();

          // Knob circle
          ctx.beginPath();
          ctx.arc(0, rotY, ROTATE_HANDLE_RADIUS, 0, Math.PI * 2);
          ctx.fillStyle = hoveredHandle === "rotate" ? "#FBBF24" : "#F59E0B";
          ctx.fill();
          ctx.strokeStyle = "#FFFFFF";
          ctx.lineWidth = 2;
          ctx.stroke();

          // --- 8 Resize Handles ---
          const handlePts = [
            { name: "nw", x: -hw, y: -hh },
            { name: "n",  x: 0,   y: -hh },
            { name: "ne", x: hw,  y: -hh },
            { name: "e",  x: hw,  y: 0 },
            { name: "se", x: hw,  y: hh },
            { name: "s",  x: 0,   y: hh },
            { name: "sw", x: -hw, y: hh },
            { name: "w",  x: -hw, y: 0 },
          ];

          const hs = HANDLE_SIZE;
          handlePts.forEach((hp) => {
            const isHov = hoveredHandle === hp.name;
            ctx.fillStyle = isHov ? "#FBBF24" : "#F59E0B";
            ctx.fillRect(hp.x - hs / 2, hp.y - hs / 2, hs, hs);
            ctx.strokeStyle = "#FFFFFF";
            ctx.lineWidth = 1.5;
            ctx.strokeRect(hp.x - hs / 2, hp.y - hs / 2, hs, hs);
          });
        }

        ctx.restore();
      });

      // 3. Draw temporary preview box if creating new slot
      if (dragMode === "create" && tempCreateBox) {
        ctx.save();
        ctx.strokeStyle = "#10B981";
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 4]);
        ctx.fillStyle = "rgba(16, 185, 129, 0.25)";
        ctx.fillRect(tempCreateBox.x, tempCreateBox.y, tempCreateBox.width, tempCreateBox.height);
        ctx.strokeRect(tempCreateBox.x, tempCreateBox.y, tempCreateBox.width, tempCreateBox.height);
        ctx.restore();
      }
    }

    // --- Inspector & Storage Sync ---

    function renderInspector() {
      if (!inspector) return;
      inspector.innerHTML = "";

      if (placeholders.length === 0) {
        inspector.innerHTML = `
          <div style="text-align:center; padding:2rem 1rem; color:var(--md-sys-color-on-surface-variant); font-size:0.85rem;">
            No placeholder slots yet.<br>Click and drag on the canvas or click <strong>"+ Add Slot"</strong> above.
          </div>
        `;
        return;
      }

      placeholders.forEach((p, idx) => {
        const isSel = idx === selectedIndex;
        const card = document.createElement("div");
        card.className = `placeholder-card ${isSel ? "active" : ""}`;
        card.style.background = isSel ? "#1E2333" : "#0E111A";
        card.style.border = isSel ? "1.5px solid #F59E0B" : "1px solid #1E293B";
        card.style.borderRadius = "8px";
        card.style.padding = "0.75rem";
        card.style.transition = "border-color 0.15s ease, background 0.15s ease";

        card.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
            <div style="display:flex; align-items:center; gap:0.4rem;">
              <span style="background:${isSel ? '#D97706' : '#4F46E5'}; color:#fff; font-size:0.7rem; font-weight:700; padding:1px 6px; border-radius:3px;">
                Slot #${p.index}
              </span>
              <span style="font-size:0.75rem; color:#94A3B8;">${Math.round(p.width)} × ${Math.round(p.height)} px</span>
            </div>
            <div style="display:flex; gap:0.35rem;">
              <button type="button" class="btn btn-outlined" style="min-height:24px; font-size:0.75rem; padding:1px 6px; ${isSel ? 'background:#F59E0B; color:#000; border-color:#F59E0B;' : ''}" data-action="select" data-idx="${idx}">
                ${isSel ? "Selected ✓" : "Select"}
              </button>
              <button type="button" class="btn btn-outlined" style="min-height:24px; font-size:0.75rem; padding:1px 6px; color:#EF4444; border-color:#EF4444;" data-action="delete" data-idx="${idx}" title="Delete slot">
                ✕
              </button>
            </div>
          </div>

          <div style="display:grid; grid-template-columns:repeat(2, 1fr); gap:0.4rem; font-size:0.75rem;">
            <div>
              <label style="color:#94A3B8; font-size:0.7rem; display:block; margin-bottom:2px;">X (px)</label>
              <input type="number" step="1" class="input" style="font-size:0.8rem; padding:4px 6px; height:28px; width:100%;" value="${Math.round(p.x)}" data-field="x" data-idx="${idx}">
            </div>
            <div>
              <label style="color:#94A3B8; font-size:0.7rem; display:block; margin-bottom:2px;">Y (px)</label>
              <input type="number" step="1" class="input" style="font-size:0.8rem; padding:4px 6px; height:28px; width:100%;" value="${Math.round(p.y)}" data-field="y" data-idx="${idx}">
            </div>
            <div>
              <label style="color:#94A3B8; font-size:0.7rem; display:block; margin-bottom:2px;">Width (px)</label>
              <input type="number" step="1" min="10" class="input" style="font-size:0.8rem; padding:4px 6px; height:28px; width:100%;" value="${Math.round(p.width)}" data-field="width" data-idx="${idx}">
            </div>
            <div>
              <label style="color:#94A3B8; font-size:0.7rem; display:block; margin-bottom:2px;">Height (px)</label>
              <input type="number" step="1" min="10" class="input" style="font-size:0.8rem; padding:4px 6px; height:28px; width:100%;" value="${Math.round(p.height)}" data-field="height" data-idx="${idx}">
            </div>
            <div>
              <label style="color:#94A3B8; font-size:0.7rem; display:block; margin-bottom:2px;">Rotation (-45° to 45°)</label>
              <input type="number" step="0.5" min="-45" max="45" class="input" style="font-size:0.8rem; padding:4px 6px; height:28px; width:100%;" value="${p.rotation}" data-field="rotation" data-idx="${idx}">
            </div>
            <div>
              <label style="color:#94A3B8; font-size:0.7rem; display:block; margin-bottom:2px;">Elevation (Z-Order)</label>
              <input type="number" step="1" class="input" style="font-size:0.8rem; padding:4px 6px; height:28px; width:100%;" value="${p.elevation}" data-field="elevation" data-idx="${idx}">
            </div>
          </div>
        `;
        inspector.appendChild(card);
      });
    }

    function syncJsonInput() {
      if (!jsonInput) return;
      let existingData = {};
      try {
        existingData = jsonInput.value ? JSON.parse(jsonInput.value) : {};
      } catch (e) {}

      const cleanCoordinates = placeholders.map((p, idx) => {
        let rot = parseFloat(p.rotation || 0) || 0;
        let w = parseFloat(p.width || 0) || 0;
        let h = parseFloat(p.height || 0) || 0;
        while (rot > 45) { rot -= 90; const t = w; w = h; h = t; }
        while (rot < -45) { rot += 90; const t = w; w = h; h = t; }
        rot = Math.max(-45, Math.min(45, Math.round(rot * 10) / 10));
        return {
          x: Math.round(parseFloat(p.x || 0)),
          y: Math.round(parseFloat(p.y || 0)),
          height: Math.round(h),
          width: Math.round(w),
          rotation: rot,
          elevation: p.elevation !== undefined ? parseInt(p.elevation, 10) : idx,
        };
      });

      existingData["frames"] = {
        image_url: config.imageUrl,
        coordinates: cleanCoordinates,
      };
      jsonInput.value = JSON.stringify(existingData);
    }

    function updateSelectedInspectorInputs() {
      if (selectedIndex < 0 || !placeholders[selectedIndex] || !inspector) return;
      const p = placeholders[selectedIndex];
      const fields = ["x", "y", "width", "height", "rotation", "elevation"];
      fields.forEach((f) => {
        const inp = inspector.querySelector(`input[data-field="${f}"][data-idx="${selectedIndex}"]`);
        if (inp && document.activeElement !== inp) {
          inp.value = f === "rotation" ? p[f] : Math.round(p[f]);
        }
      });
    }

    // --- Mouse Event Listeners on Canvas ---

    canvas.addEventListener("mousedown", function (e) {
      if (e.button !== 0) return; // Left click only
      const pos = getCanvasPos(e);
      dragStartPos = pos;

      // 1. Check if hit handle on currently selected box
      if (selectedIndex >= 0 && placeholders[selectedIndex]) {
        const selBox = placeholders[selectedIndex];
        const hit = hitTestHandles(pos, selBox);
        if (hit === "rotate") {
          isDragging = true;
          dragMode = "rotate";
          initialBoxState = { ...selBox };
          return;
        } else if (hit && hit !== "inside") {
          isDragging = true;
          dragMode = "resize";
          resizeHandle = hit;
          initialBoxState = { ...selBox };

          // Determine opposite anchor point in world coordinates
          const hw = selBox.width / 2;
          const hh = selBox.height / 2;
          const anchorsLocal = {
            nw: { lx: hw, ly: hh },
            se: { lx: -hw, ly: -hh },
            ne: { lx: -hw, ly: hh },
            sw: { lx: hw, ly: -hh },
            n:  { lx: 0, ly: hh },
            s:  { lx: 0, ly: -hh },
            w:  { lx: hw, ly: 0 },
            e:  { lx: -hw, ly: 0 },
          };
          const anchor = anchorsLocal[hit];
          resizeAnchorWorld = localToWorld(anchor.lx, anchor.ly, selBox);
          return;
        } else if (hit === "inside") {
          isDragging = true;
          dragMode = "move";
          initialBoxState = { ...selBox };
          return;
        }
      }

      // 2. Check if clicked another existing box to select and move it
      let hitNewIndex = -1;
      for (let i = placeholders.length - 1; i >= 0; i--) {
        if (hitTestBox(pos, placeholders[i])) {
          hitNewIndex = i;
          break;
        }
      }

      if (hitNewIndex >= 0) {
        selectedIndex = hitNewIndex;
        isDragging = true;
        dragMode = "move";
        initialBoxState = { ...placeholders[selectedIndex] };
        render();
        renderInspector();
        return;
      }

      // 3. Clicked empty canvas -> Start drawing a new slot
      selectedIndex = -1;
      isDragging = true;
      dragMode = "create";
      tempCreateBox = { x: pos.x, y: pos.y, width: 0, height: 0 };
      render();
      renderInspector();
    });

    canvas.addEventListener("mousemove", function (e) {
      const pos = getCanvasPos(e);

      if (!isDragging) {
        // Update hover indicators and cursor style
        hoveredHandle = null;
        hoveredBoxIndex = -1;

        if (selectedIndex >= 0 && placeholders[selectedIndex]) {
          const selBox = placeholders[selectedIndex];
          const hit = hitTestHandles(pos, selBox);
          if (hit) {
            hoveredHandle = hit;
            if (hit === "rotate") {
              canvas.style.cursor = "grab";
            } else if (hit === "inside") {
              canvas.style.cursor = "move";
            } else {
              canvas.style.cursor = getResizeCursor(hit, selBox.rotation);
            }
            render();
            return;
          }
        }

        // Check hover over non-selected boxes
        for (let i = placeholders.length - 1; i >= 0; i--) {
          if (hitTestBox(pos, placeholders[i])) {
            hoveredBoxIndex = i;
            canvas.style.cursor = "pointer";
            render();
            return;
          }
        }

        canvas.style.cursor = "crosshair";
        render();
        return;
      }

      // --- Dragging active ---
      if (dragMode === "move" && selectedIndex >= 0 && initialBoxState) {
        const dx = pos.x - dragStartPos.x;
        const dy = pos.y - dragStartPos.y;
        const curBox = placeholders[selectedIndex];
        curBox.x = Math.round(initialBoxState.x + dx);
        curBox.y = Math.round(initialBoxState.y + dy);
        render();
        updateSelectedInspectorInputs();
        syncJsonInput();

      } else if (dragMode === "rotate" && selectedIndex >= 0 && initialBoxState) {
        const cx = initialBoxState.x + initialBoxState.width / 2;
        const cy = initialBoxState.y + initialBoxState.height / 2;
        const vx = pos.x - cx;
        const vy = pos.y - cy;
        const angleRad = Math.atan2(vy, vx);
        let deg = (angleRad * 180) / Math.PI + 90; // offset for 12 o'clock stem
        while (deg > 180) deg -= 360;
        while (deg < -180) deg += 360;
        // Clamp strictly to [-45, 45] per user requirement
        deg = Math.max(-45, Math.min(45, Math.round(deg * 10) / 10));
        placeholders[selectedIndex].rotation = deg;
        canvas.style.cursor = "grabbing";
        render();
        updateSelectedInspectorInputs();
        syncJsonInput();

      } else if (dragMode === "resize" && selectedIndex >= 0 && initialBoxState && resizeAnchorWorld) {
        const curBox = placeholders[selectedIndex];
        const thetaRad = (initialBoxState.rotation * Math.PI) / 180;
        const cos = Math.cos(thetaRad);
        const sin = Math.sin(thetaRad);

        // Vector from fixed anchor to mouse in world coordinates
        const vWorldX = pos.x - resizeAnchorWorld.wx;
        const vWorldY = pos.y - resizeAnchorWorld.wy;

        // Project mouse delta into box's local rotated axis
        const lxFromAnchor = vWorldX * cos + vWorldY * sin;
        const lyFromAnchor = -vWorldX * sin + vWorldY * cos;

        let newW = initialBoxState.width;
        let newH = initialBoxState.height;
        let localShiftX = 0;
        let localShiftY = 0;

        // Width adjustment
        if (["ne", "se", "e"].includes(resizeHandle)) {
          newW = Math.max(20, lxFromAnchor);
          localShiftX = newW / 2;
        } else if (["nw", "sw", "w"].includes(resizeHandle)) {
          newW = Math.max(20, -lxFromAnchor);
          localShiftX = -newW / 2;
        }

        // Height adjustment
        if (["se", "sw", "s"].includes(resizeHandle)) {
          newH = Math.max(20, lyFromAnchor);
          localShiftY = newH / 2;
        } else if (["nw", "ne", "n"].includes(resizeHandle)) {
          newH = Math.max(20, -lyFromAnchor);
          localShiftY = -newH / 2;
        }

        // Compute new center in world coordinates from anchor + local shift
        const newCx = resizeAnchorWorld.wx + (localShiftX * cos - localShiftY * sin);
        const newCy = resizeAnchorWorld.wy + (localShiftX * sin + localShiftY * cos);

        curBox.width = Math.round(newW);
        curBox.height = Math.round(newH);
        curBox.x = Math.round(newCx - newW / 2);
        curBox.y = Math.round(newCy - newH / 2);

        render();
        updateSelectedInspectorInputs();
        syncJsonInput();

      } else if (dragMode === "create") {
        const left = Math.min(dragStartPos.x, pos.x);
        const top = Math.min(dragStartPos.y, pos.y);
        const w = Math.abs(pos.x - dragStartPos.x);
        const h = Math.abs(pos.y - dragStartPos.y);
        tempCreateBox = { x: left, y: top, width: w, height: h };
        render();
      }
    });

    function finishDrag() {
      if (!isDragging) return;

      if (dragMode === "create" && tempCreateBox) {
        if (tempCreateBox.width >= 15 && tempCreateBox.height >= 15) {
          const newSlot = {
            x: Math.round(tempCreateBox.x),
            y: Math.round(tempCreateBox.y),
            width: Math.round(tempCreateBox.width),
            height: Math.round(tempCreateBox.height),
            rotation: 0,
            elevation: placeholders.length,
            index: placeholders.length + 1,
          };
          placeholders.push(newSlot);
          selectedIndex = placeholders.length - 1;
        }
        tempCreateBox = null;
      }

      isDragging = false;
      dragMode = null;
      resizeHandle = null;
      initialBoxState = null;
      resizeAnchorWorld = null;

      render();
      renderInspector();
      syncJsonInput();
    }

    canvas.addEventListener("mouseup", finishDrag);
    canvas.addEventListener("mouseleave", finishDrag);

    // --- Keyboard Shortcuts (Nudge & Delete) ---

    window.addEventListener("keydown", function (e) {
      // Don't intercept if typing in an input field
      if (e.target && ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
      if (selectedIndex < 0 || !placeholders[selectedIndex]) return;

      const selBox = placeholders[selectedIndex];
      const step = e.shiftKey ? 10 : 1;

      if (e.key === "ArrowLeft") {
        selBox.x -= step;
        e.preventDefault();
      } else if (e.key === "ArrowRight") {
        selBox.x += step;
        e.preventDefault();
      } else if (e.key === "ArrowUp") {
        selBox.y -= step;
        e.preventDefault();
      } else if (e.key === "ArrowDown") {
        selBox.y += step;
        e.preventDefault();
      } else if (e.key === "Delete" || e.key === "Backspace") {
        placeholders.splice(selectedIndex, 1);
        placeholders.forEach((p, i) => (p.index = i + 1));
        selectedIndex = Math.min(selectedIndex, placeholders.length - 1);
        e.preventDefault();
      } else if (e.key === "Escape") {
        selectedIndex = -1;
        e.preventDefault();
      } else {
        return;
      }

      render();
      renderInspector();
      syncJsonInput();
    });

    // --- Inspector Event Delegation ---

    if (inspector) {
      inspector.addEventListener("input", function (e) {
        const idx = parseInt(e.target.dataset.idx, 10);
        const field = e.target.dataset.field;
        if (!isNaN(idx) && field && placeholders[idx]) {
          let val = parseFloat(e.target.value) || 0;
          if (field === "rotation") {
            while (val > 45) val -= 90;
            while (val < -45) val += 90;
            val = Math.max(-45, Math.min(45, Math.round(val * 10) / 10));
          } else if (["x", "y", "width", "height", "elevation"].includes(field)) {
            val = Math.round(val);
          }
          placeholders[idx][field] = val;
          render();
          syncJsonInput();
        }
      });

      inspector.addEventListener("click", function (e) {
        const btn = e.target.closest("button");
        if (!btn) return;
        const idx = parseInt(btn.dataset.idx, 10);
        const action = btn.dataset.action;

        if (action === "select") {
          selectedIndex = idx;
          render();
          renderInspector();
        } else if (action === "delete") {
          placeholders.splice(idx, 1);
          placeholders.forEach((p, i) => (p.index = i + 1));
          selectedIndex = Math.min(selectedIndex, placeholders.length - 1);
          render();
          renderInspector();
          syncJsonInput();
        }
      });
    }

    // Helper to add manual slot
    function addSlot() {
      const cw = canvas.width || 1080;
      const ch = canvas.height || 1080;
      const defaultW = Math.round(cw * 0.3);
      const defaultH = Math.round(ch * 0.35);
      const defaultX = Math.round((cw - defaultW) / 2 + (placeholders.length % 5) * 20);
      const defaultY = Math.round((ch - defaultH) / 2 + (placeholders.length % 5) * 20);

      const newSlot = {
        x: defaultX,
        y: defaultY,
        width: defaultW,
        height: defaultH,
        rotation: 0,
        elevation: placeholders.length,
        index: placeholders.length + 1,
      };

      placeholders.push(newSlot);
      selectedIndex = placeholders.length - 1;
      render();
      renderInspector();
      syncJsonInput();

      // Scroll inspector to bottom
      if (inspector) {
        setTimeout(() => {
          inspector.scrollTop = inspector.scrollHeight;
        }, 50);
      }
    }

    // Expose global methods
    window.addManualSlot = addSlot;

    editorInstance = {
      render,
      renderInspector,
      addSlot,
      getPlaceholders: () => placeholders,
    };
  };

  // Fallback if addManualSlot is called before editor init
  window.addManualSlot = function () {
    if (editorInstance && editorInstance.addSlot) {
      editorInstance.addSlot();
    }
  };
})();
