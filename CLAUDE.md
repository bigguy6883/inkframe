# photos.local - E-Ink Photo Frame

## Overview

E-ink photo frame with web-based photo upload. Users drag-and-drop photos from their phone or computer browser. No Google API or cloud sync needed.

## Architecture

- Flask web app serving on port 80
- Drag-drop upload via browser (mobile-first)
- Three-tier image storage: originals, display-ready 800x480, thumbnails 300x200
- Inky Impression 7.3" 7-color e-ink display with saturation control
- MockDisplay for headless dev (saves to data/mock_display.png)
- APScheduler for slideshow cycling
- SQLite for photo metadata, JSON for settings

## Project Structure

```
app.py              # Flask routes, GPIO buttons, startup
display.py          # E-ink + MockDisplay, info screens, debouncing
image_processor.py  # Upload processing, resize, thumbnails, EXIF
models.py           # SQLite DB + JSON settings
scheduler.py        # Photo cycling with APScheduler
wifi_manager.py     # WiFi AP/client mode (NetworkManager)
templates/          # Jinja2 templates
  base.html, index.html, settings.html, setup_wifi.html
static/
  css/style.css
  js/upload.js, gallery.js
data/               # Gitignored runtime data
  originals/        # Original uploads
  display/          # Pre-rendered 800x480 PNG
  thumbnails/       # 300x200 JPEG for web gallery
config/             # Gitignored settings + DB
```

## Key Commands

```bash
# Dev (on homelab, no display hardware)
source venv/bin/activate
python3 -c "from app import app; app.run(host='0.0.0.0', port=8080)"

# Service management (on target Pi)
sudo systemctl start|stop|restart photos
sudo journalctl -u photos -f
```

## API Endpoints

- `POST /api/photos/upload` - Upload photo (multipart)
- `GET /api/photos` - List photos (paginated)
- `DELETE /api/photos/<id>` - Delete photo
- `POST /api/photos/delete-bulk` - Bulk delete
- `POST /api/display/next|prev|info` - Display control
- `POST /api/display/show/<id>` - Show specific photo
- `POST /api/slideshow/start|stop` - Slideshow control
- `GET|POST /api/settings` - Settings CRUD
- `GET /api/status` - System status

## GPIO Buttons (BCM)

| Pin | Function |
|-----|----------|
| 5   | Show info screen |
| 6   | Previous photo |
| 16  | Next photo |
| 24  | Setup mode / hold: reboot |
