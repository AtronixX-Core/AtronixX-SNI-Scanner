"""
AX-Scanner :: ui.py
Terminal rendering: colors, banner, spinners, boxed tables. Stdlib only —
no extra pip dependency required just to look good.
"""

import shutil
import sys
import threading
import time
import itertools

from core.config import PRODUCT_NAME, VERSION, BRAND_LINE, CLI_COMMAND


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[38;5;196m"
    GREEN = "\033[38;5;46m"
    YELLOW = "\033[38;5;220m"
    CYAN = "\033[38;5;51m"
    WHITE = "\033[38;5;255m"
    GREY = "\033[38;5;240m"
    BLUE = "\033[38;5;33m"


def _width():
    return shutil.get_terminal_size(fallback=(80, 24)).columns


def hr(char="─", color=C.GREY):
    print(f"{color}{char * _width()}{C.RESET}")


def center(text, color=""):
    plain_len = len(text)
    pad = max((_width() - plain_len) // 2, 0)
    print(" " * pad + f"{color}{text}{C.RESET}")


_FONT = {
    "A": [" ███ ", "█   █", "█████", "█   █", "█   █"],
    "T": ["█████", "  █  ", "  █  ", "  █  ", "  █  "],
    "R": ["████ ", "█   █", "████ ", "█  █ ", "█   █"],
    "O": [" ███ ", "█   █", "█   █", "█   █", " ███ "],
    "N": ["█   █", "██  █", "█ █ █", "█  ██", "█   █"],
    "I": ["███", " █ ", " █ ", " █ ", "███"],
    "X": ["█   █", " █ █ ", "  █  ", " █ █ ", "█   █"],
}


def _logo(word="ATRONIXX"):
    rows = ["", "", "", "", ""]
    for ch in word:
        g = _FONT[ch]
        for i in range(5):
            rows[i] += g[i] + " "
    return rows


def _kv(label, value, color=None):
    color = color or C.WHITE
    print(f" {C.RED}├─{C.RESET} {C.GREY}{label:<11}{C.RESET}: {color}{value}{C.RESET}")


def print_banner(status=None):
    """status: optional dict with 'agent', 'probe', 'last_scan' entries
    (see ax_scanner._collect_status) — shown as a live panel."""
    from core.config import CHANNEL_HANDLE, SUPPORT_HANDLE
    print()
    for row in _logo():
        print(f" {C.RED}{C.BOLD}{row}{C.RESET}")
    print(f"      {C.RED}[ S N I   S C A N N E R ]{C.RESET}   {C.GREY}v{VERSION}{C.RESET}")
    print()
    width = min(_width() - 2, 72)
    print(f" {C.GREY}{'─' * width}{C.RESET}")
    print(f" {C.WHITE}{C.BOLD}Reality / XHTTP SNI Intelligence{C.RESET} {C.GREY}|{C.RESET} "
          f"{C.GREY}per-carrier, measured from your network{C.RESET}")
    print(f" {C.GREY}{'─' * width}{C.RESET}")

    if status:
        print(f" {C.RED}⚡ AGENT{C.RESET}")
        _kv("STATUS", status.get("agent", "unknown"),
            C.GREEN if status.get("agent_ok") else C.YELLOW)
        print(f" {C.RED}⚡ PROBE CLIENT{C.RESET}")
        _kv("CONNECTED", status.get("probe", "none"),
            C.GREEN if status.get("probe_ok") else C.YELLOW)
        ls = status.get("last_scan")
        print(f" {C.RED}⚡ LAST SCAN{C.RESET}")
        _kv("RESULT", ls or "no scan yet")
        print(f" {C.GREY}{'─' * width}{C.RESET}")

    print(f" {C.WHITE}{C.BOLD}CHANNEL{C.RESET} : {C.RED}{CHANNEL_HANDLE}{C.RESET}"
          f"   {C.GREY}|{C.RESET}   {C.WHITE}{C.BOLD}SUPPORT{C.RESET} : {C.RED}{SUPPORT_HANDLE}{C.RESET}")
    print(f" {C.GREY}{'─' * width}{C.RESET}")
    print()


def info(msg):
    print(f" {C.CYAN}ℹ{C.RESET}  {msg}")


def ok(msg):
    print(f" {C.GREEN}✅{C.RESET} {msg}")


def warn(msg):
    print(f" {C.YELLOW}⚠️ {C.RESET} {msg}")


def err(msg):
    print(f" {C.RED}❌{C.RESET} {msg}")


class Spinner:
    """Simple context-manager spinner for long-running steps."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message):
        self.message = message
        self._stop = threading.Event()
        self._thread = None

    def _spin(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                break
            sys.stdout.write(f"\r {C.CYAN}{frame}{C.RESET} {self.message}   ")
            sys.stdout.flush()
            time.sleep(0.08)
        sys.stdout.write("\r" + " " * (len(self.message) + 10) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop.set()
        if self._thread:
            self._thread.join()

    def update(self, message):
        self.message = message


def progress_bar(done, total, width=30):
    pct = 0 if total == 0 else int(done * 100 / total)
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    sys.stdout.write(f"\r {C.CYAN}{bar}{C.RESET} {pct:3d}%  ({done}/{total})")
    sys.stdout.flush()
    if done >= total:
        print()


def status_icon(success):
    return f"{C.GREEN}✅{C.RESET}" if success else f"{C.RED}❌{C.RESET}"


def print_results_table(title, rows, columns):
    """
    rows: list of dicts
    columns: list of (key, header, width) tuples
    """
    width = _width()
    box_w = min(width - 2, sum(w for _, _, w in columns) + len(columns) * 3 + 2)

    print()
    print(f" {C.BOLD}{C.WHITE}┌{'─' * (box_w - 2)}┐{C.RESET}")
    title_line = f" {title} "
    pad = box_w - 2 - len(title_line)
    print(f" {C.BOLD}{C.WHITE}│{C.CYAN}{title_line}{' ' * max(pad,0)}{C.WHITE}│{C.RESET}")
    print(f" {C.BOLD}{C.WHITE}├{'─' * (box_w - 2)}┤{C.RESET}")

    header = " │ ".join(f"{h:<{w}}" for _, h, w in columns)
    print(f" {C.WHITE}│ {C.BOLD}{header}{C.RESET}{C.WHITE} │{C.RESET}")
    print(f" {C.WHITE}├{'─' * (box_w - 2)}┤{C.RESET}")

    for row in rows:
        cells = []
        for key, _, w in columns:
            val = str(row.get(key, ""))
            cells.append(f"{val:<{w}}")
        line = " │ ".join(cells)
        print(f" {C.WHITE}│ {line}{C.WHITE} │{C.RESET}")

    print(f" {C.WHITE}└{'─' * (box_w - 2)}┘{C.RESET}")
    print()
