from __future__ import annotations

"""Compact terminal formatting for the interactive menu."""

from typing import Optional, Sequence

# If user types a menu number at "press enter", reuse it for the next 请选择
_pending_choice: Optional[str] = None


def trunc(text: str, width: int = 28) -> str:
    s = " ".join((text or "").split())
    if len(s) <= width:
        return s
    return s[: max(0, width - 1)] + "…"


def clear_pending() -> None:
    global _pending_choice
    _pending_choice = None


def pause(hint: str = "回车继续") -> None:
    """Pause; if user types a digit, keep it for the next menu 请选择."""
    global _pending_choice
    raw = input(f"\n[{hint}] ").rstrip()
    token = raw.strip()
    if token.isdigit():
        _pending_choice = token
    else:
        _pending_choice = None


def ask(prompt: str, default: str = "") -> str:
    global _pending_choice
    if _pending_choice is not None and prompt == "请选择":
        value = _pending_choice
        _pending_choice = None
        print(f"{prompt}: {value}")
        return value

    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    return raw if raw else default


def header(title: str, *, crumb: str = "") -> None:
    line = "─" * 42
    print()
    print(line)
    if crumb:
        print(f"  {crumb}")
        print(f"  › {title}")
    else:
        print(f"  {title}")
    print(line)


def pick(title: str, options: list[tuple[str, str]], *, crumb: str = "", back: str = "返回") -> str:
    header(title, crumb=crumb)
    width = len(str(len(options)))
    for i, (_key, label) in enumerate(options, start=1):
        print(f"  {str(i).rjust(width)}. {label}")
    print(f"  {str(0).rjust(width)}. {back}")
    choice = ask("请选择")
    if choice in ("", "0", "q", "Q"):
        return ""
    try:
        idx = int(choice)
    except ValueError:
        print("  · 无效选项")
        return ""
    if idx < 1 or idx > len(options):
        print("  · 无效选项")
        return ""
    return options[idx - 1][0]


def print_rows(headers: Sequence[str], rows: Sequence[Sequence[str]], widths: Sequence[int]) -> None:
    cells = [trunc(h, w) for h, w in zip(headers, widths)]
    print("  " + "  ".join(c.ljust(w) for c, w in zip(cells, widths)))
    print("  " + "  ".join("─" * w for w in widths))
    for row in rows:
        parts = [trunc(str(cell), w) for cell, w in zip(row, widths)]
        print("  " + "  ".join(p.ljust(w) for p, w in zip(parts, widths)))


def channel_label(username: Optional[str], title: str, telegram_id: int) -> str:
    if username:
        return f"@{username}"
    return title or str(telegram_id)
