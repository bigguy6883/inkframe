# InkFrame

Self-hosted e-ink photo frame with a mobile-first web interface. Drag and drop photos from your phone or computer — no cloud sync or Google account needed.

## Hardware

- Raspberry Pi (any model with GPIO and WiFi)
- [Inky Impression 5.7"](https://shop.pimoroni.com/products/inky-impression-5-7) 7-color e-ink display (600x448)
- 4 physical buttons (built into the Inky Impression)

## Features

### Photo Management
- Drag-and-drop upload from any browser (JPG, PNG, GIF, BMP, WebP, TIFF)
- Gallery view with thumbnails, bulk select, and tap-to-display
- Up to 20 MB per upload (configurable)
- Installable as a Progressive Web App (PWA) on mobile

### Display
- **Three fit modes**: contain (letterboxed), cover (fills display), stretch
- **Crop mode**: center, or smart — YuNet DNN face detection shifts cover crops toward faces, with edge-based saliency fallback
- **Saturation control**: adjustable e-ink color vibrancy (0.0-1.0)
- **Orientation**: horizontal or vertical
- **Auto-reprocess**: changing fit mode, crop mode, or orientation reprocesses all display images in the background, with a startup staleness check as fallback

### Slideshow
- Automatic photo cycling with configurable interval (5 min to 24 hours)
- **Random** (default): shuffle-bag guarantees every photo shown once before any repeat, keeps recently shown photos away from the front of a fresh shuffle, and counts gallery-picked photos as shown for the cycle; position survives restarts
- **Sequential**: cycles in upload order, position survives restarts
- Auto-starts on boot when enabled (default: on)
- History stack for navigating back through recent photos
- Slideshow state (position, shuffle bag) persists across restarts

### Physical Buttons

| Button | GPIO | Function |
|--------|------|----------|
| A | 5 | Info screen (IP, WiFi status, QR code, photo count) |
| B | 6 | Previous photo |
| C | 16 | Next photo |
| D | 24 | Short press: AP setup mode / Hold 2s: reboot |

### WiFi Setup
- Built-in access point mode for first-time setup (SSID: `inkframe-setup`, password: `photoframe`)
- Captive portal auto-redirects to WiFi configuration page (handles iOS, Android, and Windows detection endpoints)
- QR code on info screen for quick web access
- Info screen shows color-coded WiFi status (green = connected, red = disconnected)

### Web Interface
- **Gallery** (`/`): upload zone, photo grid, display controls (next/prev/info), slideshow start/stop
- **Settings** (`/settings`): fit mode, crop mode, orientation, saturation slider, slideshow interval and order
- **WiFi Setup** (`/setup/wifi`): network scanner with signal strength indicators

## Install

```bash
git clone https://github.com/bigguy6883/inkframe.git
cd inkframe
./install.sh
```

The install script handles:
- System packages (including OpenCV via apt to avoid slow ARM compilation)
- Python virtual environment and dependencies
- YuNet face detection model download
- SPI enablement
- Hostname configuration (`photos.local`)
- systemd service setup (`inkframe.service`)

## Usage

After install, open `http://photos.local/` from any device on the same network.

```bash
# Service management
sudo systemctl start|stop|restart inkframe
sudo journalctl -u inkframe -f
```

## API

All endpoints are available at `http://photos.local/api/`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/photos/upload` | Upload a photo (multipart form) |
| GET | `/api/photos?limit=20&offset=0` | List photos (paginated) |
| DELETE | `/api/photos/<id>` | Delete a photo |
| POST | `/api/photos/delete-bulk` | Bulk delete (`{"ids": [1,2,3]}`) |
| POST | `/api/display/next` | Show next photo |
| POST | `/api/display/prev` | Show previous photo |
| POST | `/api/display/show/<id>` | Show specific photo |
| POST | `/api/display/info` | Show info screen |
| POST | `/api/slideshow/start` | Start slideshow |
| POST | `/api/slideshow/stop` | Stop slideshow |
| GET | `/api/settings` | Get all settings |
| POST | `/api/settings` | Update settings (deep merge) |
| GET | `/api/status` | System status |

## Project Structure

```
app.py              # Flask routes, GPIO buttons, startup
display.py          # E-ink display abstraction, info screens
image_processor.py  # Upload processing, resize, face detection
models.py           # SQLite database + JSON settings
scheduler.py        # Slideshow cycling with APScheduler
wifi_manager.py     # WiFi AP/client mode via NetworkManager
install.sh          # Automated setup script
inkframe.service    # systemd service definition
templates/          # Jinja2 templates (gallery, settings, wifi setup)
static/             # CSS and JS (vanilla, no frameworks)
data/               # Runtime data (gitignored)
  originals/        # Original uploads preserved as-is
  display/          # Pre-rendered 600x448 PNG for e-ink
  thumbnails/       # 300x200 JPEG for web gallery
config/             # SQLite DB + JSON settings (gitignored)
```

## Requirements

- Raspberry Pi OS (Bookworm or Trixie)
- Python 3.11+ (tested with 3.13 on Trixie)
- SPI enabled for e-ink display
- NetworkManager for WiFi management

## Future Ideas

### Near-term
- **Favorites**: heart-toggle in gallery, favorites-only slideshow filter (DB field already exists)
- **Display schedule**: configurable sleep hours to blank the display overnight
- **Gallery sorting**: sort by date taken, name, or random (EXIF data already captured)

### Medium-term
- **All-faces centering**: crop to include all detected faces instead of just the largest
- **Albums/tags**: group photos into collections, slideshow per album
- **E-ink photo effects**: enhanced dithering, B&W mode, sepia, aggressive 7-color palette mapping
- **Shared upload link**: generate a temporary token URL so others can upload without network access

### Longer-term
- **Date/weather overlay**: optional on-screen date, time, or weather info (requires API key)
- **Backup & restore**: download all originals as zip, export/import settings
- **OTA updates**: check for updates and pull new code from the web UI
- **Multi-frame sync**: one server driving multiple InkFrame displays with different albums
- **Cross-frame sharing**: push photos between InkFrame devices over the internet

## License

MIT
