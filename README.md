# 📨 tg-send-cli

Send files to Telegram contacts from your CLI with a pretty TUI.

[![PyPI](https://img.shields.io/pypi/v/tg-send-cli)](https://pypi.org/project/tg-send-cli/)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org)

## Features

- **Pretty TUI** — Colors, progress bars, and unicode symbols
- **Fuzzy search** — Find contacts by typing part of their name
- **Easy install** — One command installation

## Installation

```bash
uv tool install tg-send-cli
```

Or with pip:

```bash
pip install tg-send-cli
```

## Setup

Before first use, you need Telegram API credentials:

1. Go to [my.telegram.org](https://my.telegram.org)
2. Log in with your phone number
3. Create a new application
4. Copy your **API ID** and **API Hash**

The tool will prompt you for these on first run.

## Usage

```bash
tgsend photo.jpg        # Send a photo
tgsend document.pdf     # Send a document
tgsend video.mp4        # Send a video
```

### Contact Selection

- **Type** to fuzzy search through contacts
- **↑↓** to navigate
- **Enter** to select
- **Esc** to cancel

### First Run

On first run, you'll be prompted to:
1. Enter your Telegram API credentials
2. Authenticate with your phone number

Your session is saved locally at `~/.telegram_file_sender/`.

## License

MIT
