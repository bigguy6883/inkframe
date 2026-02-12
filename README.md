# photos.local

E-ink photo frame with a web-based upload interface. Drag and drop photos from your phone or computer — no cloud sync or Google account needed.

## Hardware

- Raspberry Pi (any model with GPIO)
- Inky Impression 7-color e-ink display (600x448)
- 4 physical buttons for navigation

## Features

- Mobile-first drag-and-drop photo upload
- Automatic slideshow with configurable interval and order
- Display fit modes: contain, cover, stretch
- Smart recenter: YuNet face detection shifts cover crops toward faces
- E-ink saturation control
- WiFi setup via captive portal
- Physical buttons for next/prev/info/reboot

## Install

```bash
git clone https://github.com/bigguy6883/photos.git
cd photos
./install.sh
```

The install script handles system packages, Python venv, dependencies, model downloads, and systemd service setup.

## Usage

The web interface is available at `http://photos.local/` after install. Upload photos from any device on the same network.

```bash
# Service management
sudo systemctl start|stop|restart photos
sudo journalctl -u photos -f
```

## Requirements

- Raspberry Pi OS (Bookworm/Trixie)
- Python 3.11+
- SPI enabled for e-ink display

## License

MIT
