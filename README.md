# 📨 tg-send-cli

Send files to Telegram contacts from your CLI with a pretty TUI.

[![PyPI](https://img.shields.io/pypi/v/tg-send-cli)](https://pypi.org/project/tg-send-cli/)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org)

## Features

- **Pretty TUI** — Colors, progress bars, and unicode symbols
- **Fuzzy search** — Find contacts by typing part of their name
- **Pinned contacts** — Pin frequently used contacts to the top
- **Easy install** — One command installation
- **LLM-friendly** — JSON output commands for automation

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

### Interactive Mode (TUI)

```bash
tgsend photo.jpg        # Send a photo
tgsend document.pdf     # Send a document
tgsend video.mp4        # Send a video
```

**Contact Selection:**
- **Type** to fuzzy search through contacts
- **↑↓** to navigate
- **Enter** to select
- **Ctrl+P** to pin/unpin selected contact
- **Esc** to cancel

### LLM-Friendly Commands (JSON Output)

All commands below output JSON for easy parsing by LLMs and scripts.

#### Configure credentials

```bash
tgsend config --api-id 12345 --api-hash "your_hash"
```

#### Check status

```bash
tgsend status
# {"success": true, "configured": true, "authenticated": true, "user": {...}}
```

#### Authenticate

```bash
# Step 1: Request code
tgsend auth --phone "+1234567890"
# {"success": true, "status": "code_sent", "phone_code_hash": "abc123", ...}

# Step 2: Verify code
tgsend auth --phone "+1234567890" --code 12345
# {"success": true, "status": "authorized", "user": {...}}

# If 2FA is enabled:
tgsend auth --phone "+1234567890" --code 12345 --password "your_2fa_password"
```

#### List/search contacts

```bash
# List all contacts
tgsend contacts
# {"success": true, "count": 50, "contacts": [{"id": 123, "name": "John", "type": "user"}, ...]}

# Search contacts
tgsend contacts --search "john"
# {"success": true, "count": 3, "contacts": [{"id": 123, "name": "John Doe", "type": "user", "match_score": 90}, ...]}
```

#### Send file (non-interactive)

```bash
# By name (fuzzy matched)
tgsend send photo.jpg --to "John Doe"

# By Telegram ID
tgsend send photo.jpg --to-id 123456789
```

#### Pinned contacts

```bash
# Pin a contact
tgsend pin "John Doe"

# Unpin a contact
tgsend unpin "John Doe"

# List pinned contacts
tgsend pinned

# List only pinned contacts
tgsend contacts --pinned-only
```

## Session Storage

Your session is saved locally at `~/.telegram_file_sender/`.

## License

MIT
