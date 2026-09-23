# Preserving Transparency in Image & Video Cropping

A common defect in media processing pipelines is **transparency loss**: when an image with a transparent background (PNG, WebP, GIF, or SVG) is cropped, the transparent area turns pitch black or stark white.

This reference provides the technical causes, exact formulas, and battle-tested code patterns for frontend canvas, backend Python/Pillow, and FFmpeg video pipelines to guarantee zero loss of transparency.

---

## 1. Why Transparency Is Lost (Root Causes)

| Step in Pipeline | Naive Implementation (Buggy) | Why It Destroys Transparency |
| :--- | :--- | :--- |
| **Frontend Canvas Export** | `canvas.toBlob(blob => ..., 'image/jpeg')` | **JPEG format does not support an alpha channel.** Canvas replaces transparent pixels with solid black (`#000000`) or white (`#FFFFFF`). |
| **Canvas 2D Context** | Filling canvas before drawing or neglecting transparent clear | `ctx.fillRect()` paints over the alpha layer. |
| **Pillow Backend Loading** | `im.convert('RGB')` | Discards the `A` (alpha) channel completely, turning transparent areas black. |
| **Pillow Cropping & Saving** | Saving an `RGBA` image as `.jpg` or saving a transparent `.gif` without disposal/transparency metadata | Throws an error or replaces transparency with black frames. |
| **FFmpeg GIF / Video** | Standard single-pass GIF encoding | FFmpeg defaults to a 256-color palette where transparency is mapped to color 0 (black/green). |

---

## 2. Frontend (HTML5 Canvas) Alpha-Safe Cropping

### The Transparency Detector Function

Before exporting a cropped canvas, inspect the original file type and scan the pixels for alpha values:

```javascript
/**
 * Detects whether an image has transparency:
 * 1. Fast path: file MIME type (PNG, WebP, GIF, SVG)
 * 2. Deep path: pixel alpha channel inspection
 *
 * @param {HTMLCanvasElement} canvas
 * @param {File|Blob|string} originalSource
 * @returns {boolean}
 */
export function hasTransparency(canvas, originalSource) {
  // If original format is JPEG, it cannot have transparency
  if (originalSource && originalSource.type === 'image/jpeg') {
    return false;
  }

  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = imageData.data;

  // Each pixel has 4 values: [r, g, b, a]. Check if any alpha < 255.
  for (let i = 3; i < data.length; i += 4) {
    if (data[i] < 255) {
      return true; // Found at least one transparent/semi-transparent pixel
    }
  }

  return false;
}
```

### Canvas Safe Export Pattern

```javascript
/**
 * Exports a cropped canvas to a File/Blob while strictly preserving transparency.
 *
 * @param {HTMLCanvasElement} croppedCanvas
 * @param {File} originalFile
 * @param {string} defaultName
 * @returns {Promise<File>}
 */
export function exportCroppedCanvas(croppedCanvas, originalFile, defaultName = 'cropped') {
  return new Promise((resolve, reject) => {
    const isTransparent = hasTransparency(croppedCanvas, originalFile);
    
    // Choose format: PNG preserves lossless alpha; WebP is also supported.
    // Never use JPEG if transparency is detected or if original was PNG/WebP!
    let mimeType = 'image/jpeg';
    let extension = '.jpg';
    let quality = 0.95;

    if (isTransparent || originalFile.type === 'image/png' || originalFile.type === 'image/webp') {
      mimeType = originalFile.type === 'image/webp' ? 'image/webp' : 'image/png';
      extension = originalFile.type === 'image/webp' ? '.webp' : '.png';
      quality = undefined; // PNG is lossless
    }

    croppedCanvas.toBlob(
      (blob) => {
        if (!blob) {
          return reject(new Error('Canvas toBlob conversion failed'));
        }
        const fileName = `${defaultName}_${Date.now()}${extension}`;
        const file = new File([blob], fileName, { type: mimeType });
        resolve(file);
      },
      mimeType,
      quality
    );
  });
}
```

---

## 3. Backend Python (Pillow) Alpha-Safe Cropping

### Static Images (PNG, WebP, TIFF)

When cropping with Pillow, check `image.mode` and preserve `RGBA`:

```python
from PIL import Image
from pathlib import Path

def has_alpha(image: Image.Image) -> bool:
    """Check if PIL Image contains an alpha channel or palette transparency."""
    if image.mode in ("RGBA", "LA"):
        # Check if any pixel actually has alpha < 255
        extrema = image.getchannel("A").getextrema()
        return extrema[0] < 255
    if image.mode == "P" and "transparency" in image.info:
        return True
    return False

def crop_image_preserve_transparency(
    input_path: Path,
    output_path: Path,
    crop_box: tuple[int, int, int, int] # (left, top, right, bottom)
) -> None:
    """
    Crops an image while guaranteeing transparency is preserved.
    Never converts RGBA to RGB directly without proper alpha handling.
    """
    with Image.open(input_path) as img:
        cropped = img.crop(crop_box)
        
        # Check if alpha exists
        if has_alpha(img) or img.mode in ("RGBA", "LA"):
            # Ensure mode is RGBA
            if cropped.mode != "RGBA":
                cropped = cropped.convert("RGBA")
            
            # Destination must be PNG or WebP (never JPEG)
            target_ext = output_path.suffix.lower()
            if target_ext in (".jpg", ".jpeg"):
                output_path = output_path.with_suffix(".png")
            
            if output_path.suffix.lower() == ".webp":
                cropped.save(output_path, format="WEBP", lossless=True)
            else:
                cropped.save(output_path, format="PNG", optimize=True)
        else:
            # Safe to save as JPEG/RGB if source had no alpha
            if cropped.mode in ("RGBA", "P"):
                cropped = cropped.convert("RGB")
            cropped.save(output_path, quality=95)
```

---

## 4. Multi-Frame Animated GIF Transparency

Naively saving a GIF frame-by-frame loses transparency because:
1. `frame.info['transparency']` is dropped.
2. `disposal` method is reset to default, causing ghosting/tearing.

### Pillow Multi-Frame Solution:

```python
from PIL import Image, ImageSequence

def crop_animated_gif_preserve_transparency(
    input_path: Path,
    output_path: Path,
    crop_box: tuple[int, int, int, int] # (x, y, x + w, y + h)
) -> None:
    with Image.open(input_path) as im:
        loop = im.info.get("loop", 0)
        frames = []
        durations = []
        disposals = []
        
        # Check if base image has transparency
        transparency = im.info.get("transparency", None)
        
        for frame in ImageSequence.Iterator(im):
            # Maintain RGBA mode during crop to keep alpha mask
            f_rgba = frame.convert("RGBA")
            cropped_frame = f_rgba.crop(crop_box)
            
            # Convert back to adaptive palette with transparency preservation
            # Or preserve frame directly
            frames.append(cropped_frame)
            durations.append(frame.info.get("duration", 100))
            # Disposal method 2 = restore to background (essential for transparent animations)
            disposals.append(frame.info.get("disposal", 2))

        save_args = {
            "save_all": True,
            "append_images": frames[1:],
            "duration": durations,
            "loop": loop,
            "disposal": disposals,
            "optimize": False
        }
        
        # Save first frame with transparency args
        frames[0].save(output_path, format="GIF", **save_args)
```

---

## 5. FFmpeg Transparency Preservation (GIF and Alpha Videos)

When cropping transparent GIFs or ProRes/VP9 alpha videos using FFmpeg, naive single-pass encoding strips the transparent palette.

### Two-Pass FFmpeg Palette Generation with Transparency:

```bash
# Crop GIF with dual-pass palettegen preserving alpha channel:
ffmpeg -y -i input.gif -filter_complex \
  "[0:v]crop=w=400:h=400:x=50:y=50,split[v1][v2];\
   [v1]palettegen=reserve_transparent=1:stats_mode=single[p];\
   [v2][p]paletteuse=alpha_threshold=128" \
  output.gif
```

### Key FFmpeg Flags for Transparency:
- `reserve_transparent=1`: Forces FFmpeg to dedicate index 0 or 255 specifically to the alpha transparent color.
- `alpha_threshold=128`: Values below 128 opacity map to 100% transparent.
- `stats_mode=single`: Generates a per-frame or unified palette preventing frame flicker on transparent backgrounds.
- For WebM with alpha (VP9): Use `-c:v libvpx-vp9 -pix_fmt yuva420p`.
- For QuickTime MOV with alpha: Use `-c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le`.
