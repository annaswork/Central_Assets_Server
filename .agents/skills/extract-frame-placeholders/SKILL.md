---
name: extract-frame-placeholders
description: Detect transparent frame placeholders in images, extract bounding box coordinates, generate mask overlays, and export structured layout JSON using OpenCV. Use when extracting coordinates, bounding boxes, or transparent alpha regions from frame and collage templates.
---

# Extract Frame Placeholders

This skill automatically analyzes frame templates or collage layouts containing transparent alpha regions, detects placeholder cutouts, and extracts structured layout metadata.

## Schema Specification

When adding data in a `Frames` block, the extracted metadata is saved in `moreFields` in the following format:

```json
{
  "image_url": "path to image",
  "coordinates": [
    {
      "x": 100,
      "y": 150,
      "height": 450,
      "width": 300,
      "rotation": 0.0,
      "elevation": 0
    }
  ]
}
```

### Constraints and Field Types
- **`image_url`**: Path or URL to the frame image asset.
- **`x`**: Integer (number without decimals) indicating the top-left X coordinate of the placeholder bounding box.
- **`y`**: Integer (number without decimals) indicating the top-left Y coordinate of the placeholder bounding box.
- **`height`**: Integer (number without decimals) indicating the height of the placeholder.
- **`width`**: Integer (number without decimals) indicating the width of the placeholder.
- **`rotation`**: Float strictly normalized between **-45.0 and 45.0** degrees.
- **`elevation`**: Non-negative integer indicating the stacking order (lower elevation rendered first/behind, higher elevation rendered on top).

## Rotation Normalization Algorithm
OpenCV's `cv2.minAreaRect` outputs angles in `[-90, 0)` or `[0, 90)`. To enforce the canonical orientation range `[-45.0, 45.0]`, the rotation and dimension swapping is normalized as:

```python
rot = float(raw_angle)
while rot > 45.0:
    rot -= 90.0
    width, height = height, width
while rot < -45.0:
    rot += 90.0
    width, height = height, width
rot = round(max(-45.0, min(45.0, rot)), 2)
```

## Integer Rounding
`x`, `y`, `height`, and `width` must always be numbers without any decimals:
```python
x = int(round(float(center_x - width / 2.0)))
y = int(round(float(center_y - height / 2.0)))
width = int(round(width))
height = int(round(height))
```

## Python Detection Function
The core utility is implemented in `utils/frame_detector.py`:
- `detect_frame_placeholders(image_bytes: bytes) -> dict`
- `detect_frame_placeholders_from_file_or_url(image_source: str | bytes) -> dict`

## API Endpoints
- `POST /api/v1/media/frames/detect` (Accepts multipart image file or `{ "image_url": "..." }`)
- `GET /api/v1/media/detect-frames?imageUrl=...` (Accepts query parameter `imageUrl` or POST body)