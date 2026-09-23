# Crop Algorithms & FFmpeg Encoding Engineering

This reference covers the mathematical models, aspect ratio algorithms, codec alignment constraints, and FFmpeg filter engineering required for cropping images and videos reliably.

---

## 1. Aspect Ratio Mathematics

An aspect ratio $R$ is defined as:
$$R = \frac{\text{Width}}{\text{Height}}$$

Common aspect ratios in modern applications:
- **Portrait / Stories / Wallpapers / Reels**: $9:16 = 0.5625$
- **Standard Video**: $16:9 \approx 1.7778$
- **Square (Instagram / Avatars)**: $1:1 = 1.0000$
- **Classic Subcategory Cards**: $4:3 \approx 1.3333$
- **Classic Photography**: $3:2 = 1.5000$

### Automated Aspect Ratio Crop Calculation

When an asset is uploaded and does not match the target aspect ratio $R_{\text{target}}$, the maximum fitting bounding box is calculated by comparing $R_{\text{current}} = \frac{W_{\text{source}}}{H_{\text{source}}}$ against $R_{\text{target}}$:

```python
def compute_aspect_crop_box(
    source_width: int,
    source_height: int,
    target_ratio: float = 9 / 16,
    position: str = "center" # "center", "top", "bottom"
) -> dict[str, int]:
    """
    Computes crop dimensions to fit target_ratio while maximizing area.
    Enforces even-pixel dimensions required by video codecs.
    """
    current_ratio = source_width / source_height
    
    if current_ratio > target_ratio:
        # Source is wider than target -> Keep full height, crop width
        crop_h = source_height
        crop_w = round(source_height * target_ratio)
    else:
        # Source is taller than target -> Keep full width, crop height
        crop_w = source_width
        crop_h = round(source_width / target_ratio)
        
    # CRITICAL: Enforce even dimensions for H.264 / H.265 video codecs
    crop_w -= (crop_w % 2)
    crop_h -= (crop_h % 2)
    
    # Calculate position offsets
    x_offset = (source_width - crop_w) // 2 # Center horizontally
    
    if position == "top":
        y_offset = 0
    elif position == "bottom":
        y_offset = source_height - crop_h
    else: # "center"
        y_offset = (source_height - crop_h) // 2
        
    # Clamp offsets to prevent out-of-bounds indexing
    x_offset = max(0, min(x_offset, source_width - crop_w))
    y_offset = max(0, min(y_offset, source_height - crop_h))
    
    return {
        "crop_w": crop_w,
        "crop_h": crop_h,
        "x_offset": x_offset,
        "y_offset": y_offset
    }
```

---

## 2. The Even-Dimension Rule (Codec Requirement)

### The Problem:
Modern video encoders using YUV 4:2:0 chroma subsampling (H.264/AVC, H.265/HEVC, VP9, AV1) group pixels into $2 \times 2$ chroma blocks.
If a crop produces an odd width or height (e.g. $1079 \times 1920$ or $720 \times 1281$), FFmpeg will crash with errors like:
```text
[libx264 @ 0x...] width not divisible by 2 (1079x1920)
Error initializing output stream: Error while opening encoder for output stream #0:0
```

### The Solution:
Always align both width and height to even integers:
```python
crop_width = crop_width - (crop_width % 2)
crop_height = crop_height - (crop_height % 2)
```

---

## 3. Interactive Custom Cropping (Bounding Box Clamping)

When a user selects a custom rectangle in a frontend UI with coordinates `(x, y, width, height)` in source image space:

```python
def clamp_custom_crop(
    x: int,
    y: int,
    width: int,
    height: int,
    source_w: int,
    source_h: int
) -> tuple[int, int, int, int]:
    """Clamps user coordinates and enforces even dimensions."""
    # Ensure minimum dimensions
    w = max(2, width)
    h = max(2, height)
    
    # Enforce even dimensions
    w -= (w % 2)
    h -= (h % 2)
    
    # Clamp bounds
    clamped_x = max(0, min(x, source_w - w))
    clamped_y = max(0, min(y, source_h - h))
    
    return clamped_x, clamped_y, w, h
```

---

## 4. FFmpeg Video Crop Command Engineering

### Complete Video Cropping CLI Command

```bash
ffmpeg -y \
  -i input.mp4 \
  -vf "crop=${CROP_W}:${CROP_H}:${X_OFFSET}:${Y_OFFSET}" \
  -c:v libx264 \
  -preset medium \
  -crf 23 \
  -pix_fmt yuv420p \
  -c:a aac \
  -b:a 128k \
  -movflags +faststart \
  output.mp4
```

### Explanation of Arguments:
- `-y`: Overwrite output file without asking.
- `-vf "crop=w:h:x:y"`: The primary video filter for slicing rectangle `w x h` from coordinate `x, y`.
- `-c:v libx264`: H.264 video codec for ubiquitous device compatibility.
- `-preset medium`: Balance between compression speed and file size.
- `-crf 23`: Constant Rate Factor (visually lossless quality, 18–28 range).
- `-pix_fmt yuv420p`: Standard pixel format compatible with QuickTime, Android, iOS, and all web browsers.
- `-c:a aac -b:a 128k`: Encodes audio track with AAC; if video has no audio, pass `-an` instead of failing.
- `-movflags +faststart`: Relocates MP4 metadata index (`moov` atom) to the beginning for immediate web streaming playback.
