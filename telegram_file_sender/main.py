#!/usr/bin/env python3
"""Send files to Telegram contacts from your CLI."""

import asyncio
import argparse
import shutil
import sys
from pathlib import Path

from telethon import TelegramClient
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


def get_credentials() -> tuple[int, str]:
    """Get API credentials from config file or prompt user."""
    if CONFIG_FILE.exists():
        lines = CONFIG_FILE.read_text().strip().split('\n')
        if len(lines) >= 2:
            return int(lines[0]), lines[1]

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


async def main(file_path: str):
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


def cli():
    parser = argparse.ArgumentParser(
        description="📨 Send files to Telegram contacts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  tsf photo.jpg          Send a photo
  tsf document.pdf       Send a document
  tsf video.mp4          Send a video

First run will prompt for Telegram authentication.
        """
    )
    parser.add_argument("file_path", help="Path to the file to send")
    args = parser.parse_args()

    asyncio.run(main(args.file_path))


if __name__ == "__main__":
    cli()
