---
name: media-cropper-upload
description: >-
  Use this skill when implementing, refactoring, or troubleshooting image and video cropping mechanisms,
  preserving transparent backgrounds (no black/white background fill on crop), or handling the upload,
  validation, and poster-frame extraction of all video and animation assets (MP4, WebM, MOV, GIF,
  Animated WebP, APNG, and Lottie JSON animations).
---

# Media Cropper & Video Asset Upload Pipeline

This skill provides production-grade mechanisms, algorithms, and code templates for:
1. **Interactive & Automated Cropping** for static images, animated GIFs, and videos.
2. **Strict Transparency Preservation**: Guarantees that if an input image or animation has no background (transparent alpha channel), the cropped result also has no background.
3. **Comprehensive Video Asset Upload Pipeline**: Specifications and validation logic for all video and animation asset types (MP4, WebM, MOV, GIF, APNG, and Lottie JSON).

---

## Quick Reference & Architectural Assets

| Resource | Purpose | Link |
| :--- | :--- | :--- |
| **Transparency Guide** | Complete guide to alpha channels, canvas pitfalls, and Pillow/FFmpeg alpha retention. | [transparency-preservation.md](./references/transparency-preservation.md) |
| **Upload Pipeline Spec** | Full taxonomy, magic bytes, validation, and poster extraction for all video/animation types. | [video-asset-upload-pipeline.md](./references/video-asset-upload-pipeline.md) |
| **Crop Algorithms & FFmpeg** | Aspect ratio math, even dimensions rule (`w%2==0`), and FFmpeg filter engineering. | [crop-algorithms-ffmpeg.md](./references/crop-algorithms-ffmpeg.md) |
| **CLI & Python Utility** | Standalone executable and importable module for alpha-safe media cropping. | [crop_media.py](./scripts/crop_media.py) |
| **Frontend Cropper Component** | Reusable ES6 Canvas visual cropper with draggable handles and alpha retention. | [client-cropper.js](./examples/client-cropper.js) |

---

## 1. The Zero-Background-Loss Guarantee (Alpha Preservation)

### The Core Problem:
Transparent pixels in PNG, WebP, and GIF files are represented by an Alpha channel (`A = 0`).
When cropped naively:
- **Canvas / Frontend**: Exporting via `canvas.toBlob(..., 'image/jpeg')` strips the alpha channel, turning transparent backgrounds solid black or white.
- **Pillow / Backend**: Calling `img.convert('RGB')` or saving an RGBA image as JPEG flattens the alpha layer to black.
- **FFmpeg / GIF**: Single-pass GIF re-encoding maps transparency to palette color index 0 (black).

### The Golden Rules:
1. **Never export transparent images to JPEG**: If the source has an alpha channel, or is a PNG, WebP, SVG, or transparent GIF, output as **PNG** or **WebP** (`image/png` / `image/webp`).
2. **Pixel Alpha Inspection**:
   In Javascript, use `ctx.getImageData()` to scan for `data[i + 3] < 255`. If true, enforce PNG/WebP.
3. **Pillow Mode Preservation**:
   Check `img.mode in ("RGBA", "LA")` or `(img.mode == "P" and "transparency" in img.info)`. Preserve `RGBA` mode and save as `PNG` (`optimize=True`) or `WEBP` (`lossless=True`).
4. **GIF Frame Iterator with Transparency**:
   When processing GIF frames with Pillow, iterate using `ImageSequence.Iterator(im)`, copy `im.info.get('transparency')`, and set `disposal=2` (restore to background) to prevent frame ghosting.
5. **FFmpeg Palette Generation**:
   When cropping GIFs with FFmpeg, use dual-pass palette generation:
   `[0:v]crop=w:h:x:y,split[a][b];[a]palettegen=reserve_transparent=1:stats_mode=single[p];[b][p]paletteuse=alpha_threshold=128`.

*Detailed code patterns available in [transparency-preservation.md](./references/transparency-preservation.md).*

---

## 2. All Kinds of Video & Animation Assets (Taxonomy & Rules)

Modern systems must support three distinct tiers of motion assets:

```text
Video & Animation Assets
├── 1. Standard Video Containers (MP4, WebM, MOV, AVI)
│   ├── H.264 / H.265 / VP9 / AV1 video streams + AAC / Opus audio
│   └── Requires: Even-dimension alignment (w%2==0, h%2==0), faststart MP4 flag
├── 2. Animated Raster Formats (GIF, Animated WebP, APNG)
│   ├── Multi-frame image sequence with frame durations and palette/alpha
│   └── Requires: Disposal method retention, multi-frame crop, 8-bit or 1-bit alpha preservation
└── 3. Vector & Programmatic Animations (Lottie JSON, dotLottie)
    ├── JSON keyframe data (Adobe After Effects Bodymovin)
    └── Requires: Canvas/SVG viewport scaling (NOT raster FFmpeg cropped!), transparent poster generation
```

### Upload Handling Specifications:

| Asset Type | Allowed MIME Types | Max Size | Inspection Tool | Poster Frame Extraction |
| :--- | :--- | :--- | :--- | :--- |
| **MP4 / MOV** | `video/mp4`, `video/quicktime` | 50 MB | `ffprobe` (v:0, audio) | FFmpeg `-ss 00:00:00 -vframes 1` |
| **WebM** | `video/webm` | 50 MB | `ffprobe` (v:0, audio) | FFmpeg `-ss 00:00:00 -vframes 1` |
| **Animated GIF** | `image/gif` | 15 MB | Pillow / `ffprobe` | Pillow frame 0 `convert('RGBA')` -> PNG |
| **Animated WebP** | `image/webp` | 20 MB | Pillow / `ffprobe` | Pillow frame 0 `convert('RGBA')` -> PNG |
| **Lottie JSON** | `application/json` | 5 MB | JSON schema (`v`, `layers`) | `py-lottie` / Cairo or transparent PNG fallback |

*Detailed upload pipeline and magic bytes code available in [video-asset-upload-pipeline.md](./references/video-asset-upload-pipeline.md).*

---

## 3. Cropping Engine & Aspect Ratio Math

### Aspect Ratio Formulas:
$$R_{\text{target}} = \frac{\text{Target Width}}{\text{Target Height}}$$
- Common Presets: `9:16` (0.5625), `16:9` (1.7778), `1:1` (1.0000), `4:3` (1.3333).

### Automated Dimension Slicing:
- If $\frac{W}{H} > R_{\text{target}}$: Source is wider than target. Set `crop_h = H`, `crop_w = round(H * R_target)`.
- If $\frac{W}{H} \le R_{\text{target}}$: Source is taller than target. Set `crop_w = W`, `crop_h = round(W / R_target)`.

### Codec Even-Dimension Rule:
Video encoders using YUV 4:2:0 subsampling will fail if dimensions are odd numbers:
```python
crop_w -= (crop_w % 2)
crop_h -= (crop_h % 2)
```

### Video Crop FFmpeg Command:
```bash
ffmpeg -y -i input.mp4 -vf "crop=${CROP_W}:${CROP_H}:${X}:${Y}" \
  -c:v libx264 -preset medium -crf 23 -pix_fmt yuv420p \
  -c:a aac -b:a 128k -movflags +faststart output.mp4
```
*(If video has no audio stream, replace `-c:a aac -b:a 128k` with `-an`)*.

---

## 4. How to Use in Your Project

### Option A: Python CLI or Backend Module
Use the provided script [crop_media.py](./scripts/crop_media.py):

```bash
# Crop an image to 1:1 square preserving transparency:
python3 scripts/crop_media.py logo.png -o logo_square.png --ratio 1:1

# Crop an animated GIF to 9:16 portrait preserving animation & transparency:
python3 scripts/crop_media.py sticker.gif -o sticker_portrait.gif --ratio 9:16

# Crop a video with custom coordinates:
python3 scripts/crop_media.py video.mp4 -o video_cropped.mp4 --crop 100,50,720,1280
```

Or import directly into FastAPI/Flask:
```python
from scripts.crop_media import crop_image, crop_animated_gif, crop_video

# Crop transparent PNG/WebP without turning background black
crop_image(input_path, output_path, target_ratio=9/16)
```

### Option B: Frontend Visual Cropper
Import [client-cropper.js](./examples/client-cropper.js) into your admin panel or web app:

```javascript
import { MediaCropper } from './client-cropper.js';

const cropper = new MediaCropper({
  defaultAspectRatio: 9 / 16, // Lock to 9:16 portrait, or null for Free
});

fileInput.addEventListener('change', async (e) => {
  const file = e.target.files[0];
  try {
    const result = await cropper.open(file);
    if (result instanceof File) {
      // Cropped image with transparency preserved!
      uploadFile(result);
    } else {
      // Video or GIF with { file, cropRegion: { x, y, width, height } }
      uploadVideoWithCrop(result.file, result.cropRegion);
    }
  } catch (err) {
    console.log('Crop cancelled or failed', err);
  }
});
```

---

## 5. Verification Checklist

When implementing or testing media cropping in any project, verify the following:
- [ ] **Transparent PNG Test**: Upload a PNG with transparent background. Crop it. Confirm the exported file is `.png`, has mode `RGBA`, and the transparent background remains 100% transparent.
- [ ] **Transparent GIF Test**: Upload an animated GIF with transparent background. Crop it. Verify all frames still animate and the transparent background is intact without black artifacts.
- [ ] **Odd Dimensions Test**: Attempt a crop resulting in odd dimensions (e.g., 721x1281). Verify the script rounds down to even pixels (720x1280) so FFmpeg does not fail.
- [ ] **Audio Track Test**: Crop a video with sound and a silent video. Confirm audio plays in sync on the former, and no encoding errors occur on the latter.
- [ ] **Lottie JSON Asset**: Verify Lottie JSON animations are not sent to FFmpeg raster cropping, but instead rendered to canvas with vector scaling or saved directly.
- [ ] **Faststart Flag**: Verify MP4 headers contain `moov` before `mdat` for instant playback over HTTP.
