#!/bin/bash
# photos.local installation script

set -e

echo "=== photos.local Installation ==="
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "Please run without sudo. The script will request sudo when needed."
    exit 1
fi

cd /home/pi/photos

# Install system dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev libopenjp2-7 libtiff-dev fonts-dejavu python3-opencv opencv-data

# Enable SPI for Inky display
echo "Enabling SPI..."
sudo raspi-config nonint do_spi 0

# Create virtual environment
echo "Creating Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activate and install dependencies
echo "Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Symlink system OpenCV into venv (compiling from source is too slow on Pi)
VENV_SP=$(python3 -c 'import site; print(site.getsitepackages()[0])')
CV2_SO=$(python3 -c 'import importlib.util; spec = importlib.util.find_spec("cv2"); print(spec.origin if spec else "")' 2>/dev/null || true)
if [ -z "$CV2_SO" ]; then
    SYS_CV2=$(find /usr/lib/python3/dist-packages -name 'cv2*.so' 2>/dev/null | head -1)
    if [ -n "$SYS_CV2" ]; then
        ln -sf "$SYS_CV2" "$VENV_SP/"
        echo "Symlinked system OpenCV into venv"
    fi
fi

# Create directories
echo "Creating directories..."
mkdir -p config data/originals data/display data/thumbnails

# Initialize database
if [ ! -f "config/photos.db" ]; then
    echo "Initializing database..."
    python3 -c "import models; models.init_db()"
fi

# Set hostname
CURRENT_HOSTNAME=$(hostname)
if [ "$CURRENT_HOSTNAME" != "photos" ]; then
    echo "Setting hostname to 'photos'..."
    sudo hostnamectl set-hostname photos
fi

# Install and enable systemd service
echo "Installing systemd service..."
sudo cp photos.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable photos

echo ""
echo "=== Installation Complete ==="
echo ""
echo "To start the service:"
echo "  sudo systemctl start photos"
echo ""
echo "To view logs:"
echo "  sudo journalctl -u photos -f"
echo ""
echo "The web interface will be available at:"
echo "  http://photos.local/"
echo ""

read -p "Start the service now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo systemctl start photos
    echo "Service started!"
fi
