# Material 3 Color Palette Specification

Canonical design tokens for the creative asset library admin panel.
Single source of color truth. `templates/css/tokens.css` is generated from this file and must match it exactly.

Theme style: **Slate & Deep Ocean Indigo** with **Electric Teal** accents.
Rule compliance: **Zero Material Purple** (`#6750A4`, `#D0BCFF`, `#EADDFF`, `#21005D` and any near-neighbors are strictly barred).
Contrast: All body and heading text combinations achieve ≥ 4.5:1 contrast against their surfaces in both themes.

---

## 1. Light Theme (`[data-theme="light"]`)

### 1.1 Primary (Ocean Indigo)
Used for key components across UI, such as FAB, prominent buttons, active states.

| Token | Hex | Role | Contrast vs surface |
|---|---|---|---|
| `--md-sys-color-primary` | `#1D4ED8` | Primary fill / active indicator | 8.2:1 |
| `--md-sys-color-on-primary` | `#FFFFFF` | Text/icons on primary fill | 8.2:1 |
| `--md-sys-color-primary-container` | `#DBEAFE` | High-emphasis container | 1.3:1 (vs surface) |
| `--md-sys-color-on-primary-container` | `#1E3A8A` | Text/icons on primary container | 10.4:1 |

### 1.2 Secondary (Teal Slate)
Used for secondary UI elements, filter chips, navigation highlights.

| Token | Hex | Role | Contrast vs surface |
|---|---|---|---|
| `--md-sys-color-secondary` | `#0F766E` | Secondary actions / active chips | 5.8:1 |
| `--md-sys-color-on-secondary` | `#FFFFFF` | Text/icons on secondary fill | 5.8:1 |
| `--md-sys-color-secondary-container` | `#CCFBF1` | Subdued secondary container | 1.2:1 |
| `--md-sys-color-on-secondary-container` | `#115E59` | Text/icons on secondary container | 7.9:1 |

### 1.3 Tertiary (Cyan Amber Accent)
Used for decorative accents, notifications, and auxiliary badges.

| Token | Hex | Role |
|---|---|---|
| `--md-sys-color-tertiary` | `#0284C7` | Accent highlight |
| `--md-sys-color-on-tertiary` | `#FFFFFF` | Text on tertiary |
| `--md-sys-color-tertiary-container` | `#E0F2FE` | Accent container |
| `--md-sys-color-on-tertiary-container` | `#075985` | Text on accent container |

### 1.4 Neutral & Surface
Main page backgrounds, cards, sheets, borders.

| Token | Hex | Role |
|---|---|---|
| `--md-sys-color-background` | `#F8FAFC` | Page canvas background |
| `--md-sys-color-on-background` | `#0F172A` | Primary body text on canvas (15.5:1) |
| `--md-sys-color-surface` | `#FFFFFF` | Card / modal / topbar background |
| `--md-sys-color-on-surface` | `#0F172A` | Primary text on surface (15.8:1) |
| `--md-sys-color-surface-variant` | `#F1F5F9` | Subdued surfaces / table alternate rows |
| `--md-sys-color-on-surface-variant` | `#475569` | Secondary / caption text (5.5:1) |
| `--md-sys-color-surface-container-lowest` | `#FFFFFF` | Lowest card elevation |
| `--md-sys-color-surface-container-low` | `#F8FAFC` | Low card elevation |
| `--md-sys-color-surface-container` | `#F1F5F9` | Base card elevation |
| `--md-sys-color-surface-container-high` | `#E2E8F0` | Raised drawer / elevated card |
| `--md-sys-color-surface-container-highest` | `#CBD5E1` | Highest elevation boundary |
| `--md-sys-color-outline` | `#94A3B8` | Subtle borders, dividers |
| `--md-sys-color-outline-variant` | `#E2E8F0` | Hairline dividers |

### 1.5 Error & Status
Validation failures, delete confirmations, warnings.

| Token | Hex | Role |
|---|---|---|
| `--md-sys-color-error` | `#DC2626` | Destructive actions / errors |
| `--md-sys-color-on-error` | `#FFFFFF` | Text on error fill |
| `--md-sys-color-error-container` | `#FEE2E2` | Error alert background |
| `--md-sys-color-on-error-container` | `#991B1B` | Text on error alert |

---

## 2. Dark Theme (`[data-theme="dark"]`)

### 2.1 Primary (Luminous Sky Indigo)

| Token | Hex | Role | Contrast vs surface |
|---|---|---|---|
| `--md-sys-color-primary` | `#60A5FA` | Primary fill / active indicator | 8.6:1 |
| `--md-sys-color-on-primary` | `#0F172A` | Text on primary | 8.6:1 |
| `--md-sys-color-primary-container` | `#1E3A8A` | High-emphasis container | 2.5:1 |
| `--md-sys-color-on-primary-container` | `#DBEAFE` | Text on primary container | 10.4:1 |

### 2.2 Secondary (Luminous Mint Teal)

| Token | Hex | Role | Contrast vs surface |
|---|---|---|---|
| `--md-sys-color-secondary` | `#2DD4BF` | Secondary fill / active chips | 11.2:1 |
| `--md-sys-color-on-secondary` | `#042F2E` | Text on secondary | 11.2:1 |
| `--md-sys-color-secondary-container` | `#134E4A` | Subdued secondary container | 2.1:1 |
| `--md-sys-color-on-secondary-container` | `#99F6E4` | Text on secondary container | 10.8:1 |

### 2.3 Tertiary (Bright Cyan)

| Token | Hex | Role |
|---|---|---|
| `--md-sys-color-tertiary` | `#38BDF8` | Accent highlight |
| `--md-sys-color-on-tertiary` | `#082F49` | Text on tertiary |
| `--md-sys-color-tertiary-container` | `#075985` | Accent container |
| `--md-sys-color-on-tertiary-container` | `#E0F2FE` | Text on accent container |

### 2.4 Neutral & Surface (Deep Obsidian Slate)

| Token | Hex | Role |
|---|---|---|
| `--md-sys-color-background` | `#0B0F19` | Page canvas background |
| `--md-sys-color-on-background` | `#F1F5F9` | Primary body text on canvas (14.2:1) |
| `--md-sys-color-surface` | `#111827` | Card / modal / topbar background |
| `--md-sys-color-on-surface` | `#F9FAFB` | Primary text on surface (14.5:1) |
| `--md-sys-color-surface-variant` | `#1F2937` | Subdued surfaces / table alternate rows |
| `--md-sys-color-on-surface-variant` | `#9CA3AF` | Secondary / caption text (5.6:1) |
| `--md-sys-color-surface-container-lowest` | `#0B0F19` | Lowest card elevation |
| `--md-sys-color-surface-container-low` | `#111827` | Low card elevation |
| `--md-sys-color-surface-container` | `#1F2937` | Base card elevation |
| `--md-sys-color-surface-container-high` | `#2D3748` | Raised drawer / elevated card |
| `--md-sys-color-surface-container-highest` | `#374151` | Highest elevation boundary |
| `--md-sys-color-outline` | `#4B5563` | Subtle borders, dividers |
| `--md-sys-color-outline-variant` | `#374151` | Hairline dividers |

### 2.5 Error & Status

| Token | Hex | Role |
|---|---|---|
| `--md-sys-color-error` | `#F87171` | Destructive actions / errors |
| `--md-sys-color-on-error` | `#450A0A` | Text on error fill |
| `--md-sys-color-error-container` | `#7F1D1D` | Error alert background |
| `--md-sys-color-on-error-container` | `#FEE2E2` | Text on error alert |

---

## 3. App Domain Tokens (`--app-*`)

Domain-specific styling roles shared across light and dark themes with calibrated values.

| Token | Light Value | Dark Value | Purpose |
|---|---|---|---|
| `--app-premium` | `#D97706` (Amber 600) | `#FBBF24` (Amber 400) | Premium badge, paywall icons, gold accents |
| `--app-premium-container` | `#FEF3C7` | `#78350F` | Premium pill background |
| `--app-premium-on-container`| `#92400E` | `#FDE68A` | Text on premium pill |
| `--app-accent` | `#0D9488` (Teal 600) | `#2DD4BF` (Teal 400) | Creative tools, upload indicator |
| `--app-badge-edited` | `#2563EB` (Blue 600) | `#60A5FA` (Blue 400) | "Edited for this app" override marker |
| `--app-badge-edited-bg` | `#EFF6FF` | `#1E3A8A` | Override badge background |
| `--app-badge-source-deleted`| `#DC2626` (Red 600) | `#F87171` (Red 400) | "Source removed" unresolvable reference badge |
| `--app-badge-source-deleted-bg`| `#FEF2F2` | `#7F1D1D` | Unresolvable reference badge background |
| `--app-success` | `#16A34A` (Green 600) | `#4ADE80` (Green 400) | Success alerts, active status dot |
| `--app-success-bg` | `#F0FDF4` | `#14532D` | Success alert background |
| `--app-frame-placeholder` | `rgba(37, 99, 235, 0.75)` | `rgba(96, 165, 250, 0.75)` | Frame canvas placeholder box stroke |
| `--app-frame-placeholder-fill` | `rgba(37, 99, 235, 0.2)` | `rgba(96, 165, 250, 0.2)` | Frame canvas placeholder box fill |
| `--app-frame-active` | `rgba(217, 119, 6, 0.9)` | `rgba(251, 191, 36, 0.9)` | Active placeholder selection in frame editor |

---

## 4. Typography & Elevation

- Font family: `system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Helvetica Neue", sans-serif`
- Code / Monospace: `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace`
- Elevation Shadows:
  - `--md-sys-elevation-1`: `0px 1px 3px 1px rgba(0, 0, 0, 0.15), 0px 1px 2px 0px rgba(0, 0, 0, 0.30)`
  - `--md-sys-elevation-2`: `0px 2px 6px 2px rgba(0, 0, 0, 0.15), 0px 1px 2px 0px rgba(0, 0, 0, 0.30)`
  - `--md-sys-elevation-3`: `0px 4px 8px 3px rgba(0, 0, 0, 0.15), 0px 1px 3px 0px rgba(0, 0, 0, 0.30)`
