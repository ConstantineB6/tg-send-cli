#!/usr/bin/env python3
"""Send files to Telegram contacts from your CLI."""

import asyncio
import argparse
import json
import shutil
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, DownloadColumn, TransferSpeedColumn
from rich.prompt import Prompt
from rich.live import Live
from rich.layout import Layout
from rich.table import Table
from rich import box
from thefuzz import fuzz
from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout as PTLayout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.cursor_shapes import CursorShape
import unicodedata


def get_display_width(s: str) -> int:
    """Calculate the display width of a string, accounting for wide characters like emojis."""
    width = 0
    for char in s:
        if unicodedata.east_asian_width(char) in ('F', 'W'):
            width += 2
        elif unicodedata.category(char) in ('Mn', 'Me', 'Cf'):
            width += 0  # Combining/format characters
        else:
            width += 1
    return width


def truncate_to_width(s: str, max_width: int) -> tuple[str, int]:
    """Truncate string to fit within max_width, returns (truncated_string, actual_width)."""
    width = 0
    result = []
    for char in s:
        char_width = 2 if unicodedata.east_asian_width(char) in ('F', 'W') else 1
        if unicodedata.category(char) in ('Mn', 'Me', 'Cf'):
            char_width = 0
        if width + char_width > max_width - 1:  # -1 for ellipsis
            result.append('…')
            width += 1
            break
        result.append(char)
        width += char_width
    return ''.join(result), width


def pad_to_width(s: str, target_width: int) -> str:
    """Pad string with spaces to reach target display width."""
    current_width = get_display_width(s)
    padding_needed = target_width - current_width
    return s + ' ' * max(0, padding_needed)


console = Console()

SESSION_DIR = Path.home() / ".telegram_file_sender"
SESSION_PATH = SESSION_DIR / "session_name"
CONFIG_FILE = SESSION_DIR / "config"


def ensure_session_dir():
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


def get_credentials_or_none() -> tuple[int, str] | None:
    """Get API credentials from config file, returns None if not configured."""
    if CONFIG_FILE.exists():
        lines = CONFIG_FILE.read_text().strip().split('\n')
        if len(lines) >= 2:
            return int(lines[0]), lines[1]
    return None


def get_credentials() -> tuple[int, str]:
    """Get API credentials from config file or prompt user."""
    creds = get_credentials_or_none()
    if creds:
        return creds

    console.print(Panel(
        "[bold yellow]First-time setup[/bold yellow]\n\n"
        "You need Telegram API credentials.\n"
        "Get them at [cyan]https://my.telegram.org[/cyan]",
        border_style="yellow"
    ))
    console.print()

    api_id = Prompt.ask("[cyan]API ID[/cyan]")
    api_hash = Prompt.ask("[cyan]API Hash[/cyan]")

    try:
        api_id_int = int(api_id)
    except ValueError:
        console.print("[red]✗ API ID must be a number[/red]")
        sys.exit(1)

    CONFIG_FILE.write_text(f"{api_id_int}\n{api_hash}\n")
    console.print("[green]✓ Credentials saved[/green]\n")

    return api_id_int, api_hash


def save_credentials(api_id: int, api_hash: str):
    """Save API credentials to config file."""
    ensure_session_dir()
    CONFIG_FILE.write_text(f"{api_id}\n{api_hash}\n")


def print_header():
    console.print(Panel.fit(
        "[bold cyan]📨 Telegram File Sender[/bold cyan]",
        border_style="cyan",
        padding=(0, 2)
    ))
    console.print()


def get_dialog_type(dialog) -> str:
    if dialog.is_user:
        return "👤 User"
    elif dialog.is_group:
        return "👥 Group"
    elif dialog.is_channel:
        return "📢 Channel"
    else:
        return "💬 Chat"


def get_dialog_type_simple(dialog) -> str:
    """Return simple type string for JSON output."""
    if dialog.is_user:
        return "user"
    elif dialog.is_group:
        return "group"
    elif dialog.is_channel:
        return "channel"
    else:
        return "chat"


def fuzzy_search(dialogs: list, query: str) -> list[tuple[int, int]]:
    """Returns list of (original_index, score) sorted by score descending."""
    if not query:
        return [(i, 100) for i in range(len(dialogs))]

    results = []
    for i, dialog in enumerate(dialogs):
        name = dialog.name or ""
        score = fuzz.partial_ratio(query.lower(), name.lower())
        if score > 40:
            results.append((i, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    elif size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes} B"


def build_contact_display(dialogs: list, filtered_indices: list[int], selected: int, query: str, cursor_pos: int, max_rows: int, term_width: int, file_name: str = "", file_size: int = 0) -> list:
    """Build the contact list display as prompt_toolkit formatted text."""
    result = []
    pad = "  "
    content_width = term_width - 4  # Account for padding on both sides

    # Header
    result.append(("class:header", f"{pad}╭────────────────────────────╮\n"))
    result.append(("class:header", f"{pad}│  📨 Telegram File Sender   │\n"))
    result.append(("class:header", f"{pad}╰────────────────────────────╯\n"))
    result.append(("", "\n"))

    # File info
    if file_name:
        size_str = format_file_size(file_size)
        result.append(("class:dim", f"{pad}📎 "))
        result.append(("class:file", file_name))
        result.append(("class:dim", f"  ({size_str})\n"))
        result.append(("", "\n"))

    # Search box - spans full width
    search_inner_width = content_width - 2  # -2 for left/right borders
    result.append(("class:searchbox", f"{pad}╭{'─' * search_inner_width}╮\n"))
    if query:
        # Split query at cursor position
        before_cursor = query[:cursor_pos]
        after_cursor = query[cursor_pos:]

        # 🔍 = 2 width, space = 1
        before_width = get_display_width(before_cursor)
        after_width = get_display_width(after_cursor)

        # Cursor is shown by highlighting the next character (or a space if at end)
        if after_cursor:
            cursor_char = after_cursor[0]
            after_cursor = after_cursor[1:]
            cursor_width = get_display_width(cursor_char)
            after_width = get_display_width(after_cursor)
        else:
            cursor_char = " "
            cursor_width = 1

        used_width = 2 + 1 + before_width + cursor_width + after_width  # 🔍 + space + before + cursor_char + after
        padding_needed = search_inner_width - used_width - 1  # -1 for leading space

        result.append(("class:searchbox", f"{pad}│ "))
        result.append(("", "🔍 "))
        result.append(("class:search-text", before_cursor))
        result.append(("class:cursor", cursor_char))
        result.append(("class:search-text", after_cursor))
        result.append(("", " " * max(0, padding_needed)))
        result.append(("class:searchbox", "│\n"))
    else:
        # 🔍 = 2 width, " Type to search..." = 17
        used_width = 2 + 1 + 17  # 🔍 + space + placeholder text
        padding_needed = search_inner_width - used_width - 1  # -1 for leading space
        result.append(("class:searchbox", f"{pad}│ "))
        result.append(("", "🔍 "))
        result.append(("class:placeholder", "Type to search..."))
        result.append(("", " " * max(0, padding_needed)))
        result.append(("class:searchbox", "│\n"))
    result.append(("class:searchbox", f"{pad}╰{'─' * search_inner_width}╯\n"))
    result.append(("", "\n"))

    # Contact list - reserve lines for header (5) + file info (2) + search (3) + footer (3) + "more" line (1)
    reserved_lines = 14 if file_name else 12
    visible_count = min(len(filtered_indices), max_rows - reserved_lines)
    # Show one less if we need the "more" indicator
    show_more = len(filtered_indices) > visible_count
    if show_more:
        visible_count = max(1, visible_count - 1)

    # Calculate name width: total - padding(4) - arrow(4) - type(12)
    name_width = content_width - 16
    type_col_width = 12

    if not filtered_indices:
        result.append(("class:warning", f"{pad}  No matches found\n"))
    else:
        start = 0
        if selected >= visible_count:
            start = selected - visible_count + 1

        for i in range(start, min(start + visible_count, len(filtered_indices))):
            idx = filtered_indices[i]
            dialog = dialogs[idx]
            name = (dialog.name or "(unnamed)")

            # Truncate and pad accounting for display width
            if get_display_width(name) > name_width:
                name, _ = truncate_to_width(name, name_width)
            name_padded = pad_to_width(name, name_width)
            dtype = get_dialog_type(dialog)

            if i == selected:
                line = f"{pad}  → {name_padded} {dtype}\n"
                result.append(("class:selected", line))
            else:
                result.append(("class:item", f"{pad}    {name_padded} "))
                result.append(("class:dim", f"{dtype}\n"))

        # Show "more" indicator
        if show_more:
            remaining = len(filtered_indices) - visible_count
            result.append(("class:more", f"{pad}    ↓ {remaining} more contact{'s' if remaining != 1 else ''}...\n"))

    result.append(("", "\n"))
    result.append(("class:hint", f"{pad}↑↓ navigate  •  enter select  •  esc cancel"))

    return result


def select_contact_sync(dialogs: list, file_name: str = "", file_size: int = 0) -> int | None:
    """Interactive contact selection with fuzzy search using prompt_toolkit."""
    term_size = shutil.get_terminal_size()
    max_rows = term_size.lines
    term_width = term_size.columns

    state = {
        "query": "",
        "cursor_pos": 0,
        "selected": 0,
        "filtered_indices": list(range(len(dialogs))),
        "result": None,
        "cancelled": False,
    }

    def update_filter():
        state["filtered_indices"] = [idx for idx, _ in fuzzy_search(dialogs, state["query"])]
        if state["selected"] >= len(state["filtered_indices"]):
            state["selected"] = max(0, len(state["filtered_indices"]) - 1)

    def get_display():
        # Re-check terminal size for dynamic resizing
        size = shutil.get_terminal_size()
        return build_contact_display(
            dialogs,
            state["filtered_indices"],
            state["selected"],
            state["query"],
            state["cursor_pos"],
            size.lines,
            size.columns,
            file_name,
            file_size
        )

    kb = KeyBindings()

    @kb.add(Keys.Up)
    def move_up(event):
        if state["selected"] > 0:
            state["selected"] -= 1

    @kb.add(Keys.Down)
    def move_down(event):
        if state["selected"] < len(state["filtered_indices"]) - 1:
            state["selected"] += 1

    @kb.add(Keys.Enter)
    def select(event):
        if state["filtered_indices"]:
            state["result"] = state["filtered_indices"][state["selected"]]
        event.app.exit()

    @kb.add(Keys.Escape, eager=True)
    def cancel(event):
        state["cancelled"] = True
        event.app.exit()

    @kb.add(Keys.ControlC)
    def ctrl_c(event):
        state["cancelled"] = True
        event.app.exit()

    @kb.add(Keys.Left)
    def move_left(event):
        if state["cursor_pos"] > 0:
            state["cursor_pos"] -= 1

    @kb.add(Keys.Right)
    def move_right(event):
        if state["cursor_pos"] < len(state["query"]):
            state["cursor_pos"] += 1

    @kb.add(Keys.Backspace)
    def backspace(event):
        if state["query"] and state["cursor_pos"] > 0:
            q = state["query"]
            state["query"] = q[:state["cursor_pos"] - 1] + q[state["cursor_pos"]:]
            state["cursor_pos"] -= 1
            update_filter()

    @kb.add(Keys.Escape, Keys.Backspace)  # Option+Backspace sends Escape+Backspace on macOS
    def delete_word(event):
        if state["query"] and state["cursor_pos"] > 0:
            q = state["query"]
            left_part = q[:state["cursor_pos"]].rstrip()
            if ' ' in left_part:
                new_pos = left_part.rfind(' ') + 1
            else:
                new_pos = 0
            state["query"] = q[:new_pos] + q[state["cursor_pos"]:]
            state["cursor_pos"] = new_pos
            update_filter()

    @kb.add(Keys.ControlU)  # Cmd+Backspace sends ^U
    def delete_all(event):
        state["query"] = ""
        state["cursor_pos"] = 0
        state["selected"] = 0
        update_filter()

    @kb.add(Keys.ControlW)  # Alternative for delete word
    def delete_word_alt(event):
        if state["query"] and state["cursor_pos"] > 0:
            q = state["query"]
            left_part = q[:state["cursor_pos"]].rstrip()
            if ' ' in left_part:
                new_pos = left_part.rfind(' ') + 1
            else:
                new_pos = 0
            state["query"] = q[:new_pos] + q[state["cursor_pos"]:]
            state["cursor_pos"] = new_pos
            update_filter()

    @kb.add(Keys.Any)
    def type_char(event):
        char = event.data
        if char.isprintable() and len(char) == 1:
            q = state["query"]
            state["query"] = q[:state["cursor_pos"]] + char + q[state["cursor_pos"]:]
            state["cursor_pos"] += 1
            state["selected"] = 0
            update_filter()

    style = Style.from_dict({
        "header": "#00d7ff bold",  # Cyan like loading state
        "searchbox": "#555555",
        "dim": "#666666",
        "search": "#00d7ff",
        "search-text": "#ffffff bold",
        "cursor": "#000000 bg:#00d7ff",  # Black text on cyan background
        "placeholder": "#666666 italic",
        "warning": "#ffaa00",
        "selected": "#00d7ff bold reverse",  # Cyan, reversed for selection
        "item": "#cccccc",
        "more": "#00d7ff italic",
        "hint": "#555555",
        "file": "#ffffff bold",
    })

    app = Application(
        layout=PTLayout(Window(FormattedTextControl(lambda: get_display(), show_cursor=False))),
        key_bindings=kb,
        style=style,
        full_screen=True,
        mouse_support=False,
        erase_when_done=True,
        cursor=CursorShape.BLINKING_UNDERLINE,
    )

    app.run()

    if state["cancelled"]:
        return None
    return state["result"]


async def select_contact(dialogs: list, file_name: str = "", file_size: int = 0) -> int | None:
    """Async wrapper for contact selection."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, select_contact_sync, dialogs, file_name, file_size)


async def send_file_with_progress(client: TelegramClient, target, file_path: Path):
    """Send file with a pretty progress bar."""
    file_size = file_path.stat().st_size
    file_name = file_path.name

    console.print(f"\n[bold]Sending[/bold] [cyan]{file_name}[/cyan] [dim]({file_size / 1024 / 1024:.2f} MB)[/dim]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40, complete_style="green", finished_style="bright_green"),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Uploading", total=file_size)

        async def progress_callback(current, total):
            progress.update(task, completed=current)

        await client.send_file(
            target.id,
            str(file_path),
            progress_callback=progress_callback
        )

    console.print(f"\n[bold green]✓[/bold green] File sent successfully!")


# =============================================================================
# Interactive TUI mode (default)
# =============================================================================

async def main_interactive(file_path: str):
    """Interactive TUI mode for sending files."""
    ensure_session_dir()

    path = Path(file_path)
    if not path.exists():
        console.print(f"[bold red]✗ Error:[/bold red] File not found: [cyan]{file_path}[/cyan]")
        sys.exit(1)

    if not path.is_file():
        console.print(f"[bold red]✗ Error:[/bold red] Not a file: [cyan]{file_path}[/cyan]")
        sys.exit(1)

    file_size = path.stat().st_size

    # Show loading spinner immediately
    console.clear()
    print_header()
    console.print(f"[dim]File:[/dim] [cyan]{path.name}[/cyan] [dim]({format_file_size(file_size)})[/dim]\n")

    api_id, api_hash = get_credentials()
    client = TelegramClient(str(SESSION_PATH), api_id, api_hash)

    try:
        with console.status("[bold cyan]Connecting...[/bold cyan]", spinner="dots"):
            await client.connect()

        if not await client.is_user_authorized():
            console.print("[yellow]Authentication required[/yellow]")
            console.print("[dim]Enter phone with country code, e.g. +1234567890[/dim]\n")

            def get_code():
                console.print("\n[dim]A code was sent to your Telegram app[/dim]")
                return Prompt.ask("[cyan]Enter code[/cyan]")

            def get_password():
                console.print("\n[dim]Your account has 2FA enabled[/dim]")
                return Prompt.ask("[cyan]Telegram 2FA password[/cyan]", password=True)

            await client.start(
                phone=lambda: Prompt.ask("[cyan]Phone number[/cyan]"),
                code_callback=get_code,
                password=get_password,
            )

        with console.status("[bold cyan]Loading contacts...[/bold cyan]", spinner="dots"):
            dialogs = await client.get_dialogs(limit=100)

        console.clear()
        selected_idx = await select_contact(dialogs, path.name, file_size)
        console.clear()

        if selected_idx is None:
            console.print("\n[yellow]Cancelled[/yellow]")
            return

        target = dialogs[selected_idx]
        console.print(f"\n[dim]Sending to:[/dim] [bold]{target.name}[/bold]")

        await send_file_with_progress(client, target, path)

    except KeyboardInterrupt:
        console.print("\n\n[yellow]Interrupted[/yellow]")
    finally:
        await client.disconnect()


# =============================================================================
# LLM-friendly CLI commands (non-interactive, JSON output)
# =============================================================================

def output_json(data: dict):
    """Print JSON output."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def output_error(message: str, code: str = "error"):
    """Print error as JSON and exit."""
    output_json({"success": False, "error": code, "message": message})
    sys.exit(1)


async def cmd_config(args):
    """Configure API credentials."""
    ensure_session_dir()

    if args.api_id and args.api_hash:
        save_credentials(args.api_id, args.api_hash)
        output_json({
            "success": True,
            "message": "Credentials saved"
        })
    else:
        creds = get_credentials_or_none()
        if creds:
            output_json({
                "success": True,
                "configured": True,
                "api_id": creds[0]
            })
        else:
            output_json({
                "success": True,
                "configured": False,
                "message": "No credentials configured. Use --api-id and --api-hash to configure."
            })


async def cmd_auth(args):
    """Handle authentication flow."""
    ensure_session_dir()

    creds = get_credentials_or_none()
    if not creds:
        output_error("No API credentials configured. Run 'tgsend config --api-id ID --api-hash HASH' first.", "no_credentials")

    api_id, api_hash = creds
    client = TelegramClient(str(SESSION_PATH), api_id, api_hash)

    try:
        await client.connect()

        # Check if already authorized
        if await client.is_user_authorized():
            me = await client.get_me()
            output_json({
                "success": True,
                "status": "authorized",
                "user": {
                    "id": me.id,
                    "first_name": me.first_name,
                    "last_name": me.last_name,
                    "username": me.username,
                    "phone": me.phone
                }
            })
            return

        # Not authorized - need phone number
        if not args.phone:
            output_json({
                "success": True,
                "status": "need_phone",
                "message": "Provide phone number with --phone"
            })
            return

        # Send code request
        if not args.code:
            try:
                result = await client.send_code_request(args.phone)
                output_json({
                    "success": True,
                    "status": "code_sent",
                    "phone_code_hash": result.phone_code_hash,
                    "message": "Code sent to Telegram app. Provide code with --code"
                })
            except Exception as e:
                output_error(str(e), "send_code_failed")
            return

        # Verify code
        try:
            # We need to send code request again to get the hash, or user provides it
            if args.phone_code_hash:
                phone_code_hash = args.phone_code_hash
            else:
                # Re-send to get hash (Telegram will use cached code)
                result = await client.send_code_request(args.phone)
                phone_code_hash = result.phone_code_hash

            await client.sign_in(args.phone, args.code, phone_code_hash=phone_code_hash)

            me = await client.get_me()
            output_json({
                "success": True,
                "status": "authorized",
                "user": {
                    "id": me.id,
                    "first_name": me.first_name,
                    "last_name": me.last_name,
                    "username": me.username,
                    "phone": me.phone
                }
            })

        except SessionPasswordNeededError:
            if not args.password:
                output_json({
                    "success": True,
                    "status": "need_password",
                    "message": "2FA is enabled. Provide password with --password"
                })
                return

            try:
                await client.sign_in(password=args.password)
                me = await client.get_me()
                output_json({
                    "success": True,
                    "status": "authorized",
                    "user": {
                        "id": me.id,
                        "first_name": me.first_name,
                        "last_name": me.last_name,
                        "username": me.username,
                        "phone": me.phone
                    }
                })
            except Exception as e:
                output_error(str(e), "password_failed")

        except PhoneCodeInvalidError:
            output_error("Invalid code", "invalid_code")
        except Exception as e:
            output_error(str(e), "sign_in_failed")

    finally:
        await client.disconnect()


async def cmd_contacts(args):
    """List or search contacts."""
    ensure_session_dir()

    creds = get_credentials_or_none()
    if not creds:
        output_error("No API credentials configured.", "no_credentials")

    api_id, api_hash = creds
    client = TelegramClient(str(SESSION_PATH), api_id, api_hash)

    try:
        await client.connect()

        if not await client.is_user_authorized():
            output_error("Not authenticated. Run 'tgsend auth' first.", "not_authorized")

        dialogs = await client.get_dialogs(limit=args.limit or 100)

        # Apply search filter if provided
        if args.search:
            search_results = fuzzy_search(dialogs, args.search)
            filtered_dialogs = [(dialogs[idx], score) for idx, score in search_results]
        else:
            filtered_dialogs = [(d, 100) for d in dialogs]

        contacts = []
        for dialog, score in filtered_dialogs:
            contact = {
                "id": dialog.id,
                "name": dialog.name,
                "type": get_dialog_type_simple(dialog),
            }
            if args.search:
                contact["match_score"] = score
            contacts.append(contact)

        output_json({
            "success": True,
            "count": len(contacts),
            "contacts": contacts
        })

    finally:
        await client.disconnect()


async def cmd_send(args):
    """Send file to a contact (non-interactive)."""
    ensure_session_dir()

    path = Path(args.file)
    if not path.exists():
        output_error(f"File not found: {args.file}", "file_not_found")

    if not path.is_file():
        output_error(f"Not a file: {args.file}", "not_a_file")

    creds = get_credentials_or_none()
    if not creds:
        output_error("No API credentials configured.", "no_credentials")

    api_id, api_hash = creds
    client = TelegramClient(str(SESSION_PATH), api_id, api_hash)

    try:
        await client.connect()

        if not await client.is_user_authorized():
            output_error("Not authenticated. Run 'tgsend auth' first.", "not_authorized")

        # Find target
        target = None

        if args.to_id:
            # Direct ID
            try:
                target = await client.get_entity(args.to_id)
            except Exception as e:
                output_error(f"Could not find entity with ID {args.to_id}: {e}", "entity_not_found")
        elif args.to:
            # Fuzzy search by name
            dialogs = await client.get_dialogs(limit=100)
            search_results = fuzzy_search(dialogs, args.to)
            if not search_results:
                output_error(f"No contact found matching '{args.to}'", "contact_not_found")

            best_match_idx, score = search_results[0]
            if score < 60:
                output_error(f"No good match found for '{args.to}'. Best match: '{dialogs[best_match_idx].name}' (score: {score})", "low_match_score")

            target = dialogs[best_match_idx]
        else:
            output_error("Specify recipient with --to (name) or --to-id (Telegram ID)", "no_recipient")

        # Send file
        file_size = path.stat().st_size

        await client.send_file(target.id, str(path))

        output_json({
            "success": True,
            "message": "File sent",
            "file": {
                "name": path.name,
                "size": file_size,
                "size_human": format_file_size(file_size)
            },
            "recipient": {
                "id": target.id,
                "name": getattr(target, 'name', None) or getattr(target, 'title', None) or str(target.id)
            }
        })

    finally:
        await client.disconnect()


async def cmd_status(args):
    """Check authentication status."""
    ensure_session_dir()

    creds = get_credentials_or_none()
    if not creds:
        output_json({
            "success": True,
            "configured": False,
            "authenticated": False,
            "message": "No API credentials configured"
        })
        return

    api_id, api_hash = creds
    client = TelegramClient(str(SESSION_PATH), api_id, api_hash)

    try:
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            output_json({
                "success": True,
                "configured": True,
                "authenticated": True,
                "user": {
                    "id": me.id,
                    "first_name": me.first_name,
                    "last_name": me.last_name,
                    "username": me.username,
                    "phone": me.phone
                }
            })
        else:
            output_json({
                "success": True,
                "configured": True,
                "authenticated": False,
                "message": "Credentials configured but not authenticated"
            })

    finally:
        await client.disconnect()


# =============================================================================
# CLI entry point
# =============================================================================

def cli():
    # Check if first arg looks like a file path (not a subcommand)
    subcommands = {"config", "status", "auth", "contacts", "send", "-h", "--help"}

    if len(sys.argv) >= 2 and sys.argv[1] not in subcommands:
        # Treat as file path - interactive mode
        if sys.argv[1].startswith("-"):
            # It's a flag, show help
            pass
        else:
            asyncio.run(main_interactive(sys.argv[1]))
            return

    parser = argparse.ArgumentParser(
        description="📨 Send files to Telegram contacts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Interactive mode:
  tgsend photo.jpg              Open TUI to select contact and send

LLM-friendly commands (JSON output):
  tgsend config --api-id ID --api-hash HASH   Configure credentials
  tgsend status                               Check auth status
  tgsend auth --phone +1234567890             Start authentication
  tgsend auth --phone +1234567890 --code 12345   Complete authentication
  tgsend contacts                             List contacts
  tgsend contacts --search "john"             Search contacts
  tgsend send file.jpg --to "John"            Send file by name
  tgsend send file.jpg --to-id 123456789      Send file by ID
        """
    )

    subparsers = parser.add_subparsers(dest="command")

    # Config command
    config_parser = subparsers.add_parser("config", help="Configure API credentials")
    config_parser.add_argument("--api-id", type=int, help="Telegram API ID")
    config_parser.add_argument("--api-hash", help="Telegram API Hash")

    # Status command
    subparsers.add_parser("status", help="Check authentication status")

    # Auth command
    auth_parser = subparsers.add_parser("auth", help="Authenticate with Telegram")
    auth_parser.add_argument("--phone", help="Phone number with country code (e.g., +1234567890)")
    auth_parser.add_argument("--code", help="Verification code from Telegram")
    auth_parser.add_argument("--phone-code-hash", help="Phone code hash from code_sent response")
    auth_parser.add_argument("--password", help="2FA password if enabled")

    # Contacts command
    contacts_parser = subparsers.add_parser("contacts", help="List or search contacts")
    contacts_parser.add_argument("--search", "-s", help="Fuzzy search query")
    contacts_parser.add_argument("--limit", "-l", type=int, default=100, help="Max contacts to fetch")

    # Send command
    send_parser = subparsers.add_parser("send", help="Send file (non-interactive)")
    send_parser.add_argument("file", help="Path to file to send")
    send_parser.add_argument("--to", help="Recipient name (fuzzy matched)")
    send_parser.add_argument("--to-id", type=int, help="Recipient Telegram ID")

    args = parser.parse_args()

    # Route to appropriate handler
    if args.command == "config":
        asyncio.run(cmd_config(args))
    elif args.command == "status":
        asyncio.run(cmd_status(args))
    elif args.command == "auth":
        asyncio.run(cmd_auth(args))
    elif args.command == "contacts":
        asyncio.run(cmd_contacts(args))
    elif args.command == "send":
        asyncio.run(cmd_send(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    cli()
