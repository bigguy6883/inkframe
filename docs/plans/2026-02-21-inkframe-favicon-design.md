# InkFrame Favicon & PWA Icons — Design

**Date:** 2026-02-21

## Goal

Add a recognizable favicon and PWA icon to InkFrame so it shows a meaningful image when saved as a browser bookmark or home screen shortcut.

## Icon Concept

Photo/landscape style (iOS Photos app aesthetic):
- Rounded square background in warm amber/orange (`#E8763A`)
- White sun circle in the upper-right quadrant
- Dark mountain silhouette in the lower half
- High contrast — reads clearly at 16px, 32px, and 192px

## Files

| File | Purpose |
|------|---------|
| `static/icon.svg` | SVG icon used for favicon, apple-touch-icon, and PWA |
| `static/manifest.json` | PWA manifest enabling home screen install |
| `templates/base.html` | Add 3 `<link>` tags in `<head>` |

## manifest.json

```json
{
  "name": "InkFrame",
  "short_name": "InkFrame",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#1a1a2e",
  "theme_color": "#E8763A",
  "icons": [
    { "src": "/static/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable" }
  ]
}
```

## base.html additions

```html
<link rel="icon" type="image/svg+xml" href="{{ url_for('static', filename='icon.svg') }}">
<link rel="apple-touch-icon" href="{{ url_for('static', filename='icon.svg') }}">
<link rel="manifest" href="{{ url_for('static', filename='manifest.json') }}">
```
