"""Lightweight shell command guards (inspired by Claude Code bashSecurity ideas, simplified)."""

from __future__ import annotations

import re
import shlex
from typing import Tuple

# Patterns that are almost always unsafe for an embedded agent
_DANGEROUS_RES = (
    re.compile(r"\|\s*bash\b", re.I),
    re.compile(r"\|\s*sh\b", re.I),
    re.compile(r"curl\s+[^|]*\|", re.I),
    re.compile(r"wget\s+[^|]*\|", re.I),
    re.compile(r"Invoke-WebRequest|IWR\b|iex\b|Invoke-Expression", re.I),
    re.compile(r"powershell\s+-e(nc)?\d?", re.I),
    re.compile(r"certutil\s+-", re.I),
    re.compile(r"regsvr32\b", re.I),
    re.compile(r"mkfs\b", re.I),
    re.compile(r"dd\s+if=", re.I),
    re.compile(r":\(\)\s*\{", re.I),  # fork bomb
)


def check_shell_command(command: str) -> Tuple[bool, str]:
    """Return (allowed, reason_if_blocked)."""
    cmd = (command or "").strip()
    if not cmd:
        return False, "empty command"
    if len(cmd) > 8000:
        return False, "command too long (max 8000 chars)"

    lower = cmd.lower()
    for bad in ("&", "&&", "|", ";", "`", "$("):
        # Allow simple single commands only — reduce injection surface
        if bad in cmd:
            # Permit common chaining only on Unix-style if very limited — still risky.
            # For maximum safety default: block pipelines and command separators.
            if bad in ("|", "`", "$("):
                return False, f"disallowed character sequence ({bad!r}) — use a single simple command"
            if bad == "&" and "&&" not in cmd and "&" in cmd:
                return False, "background/delegation & is not allowed"
            if bad == "&&" or bad == ";":
                return False, "command chaining (&& or ;) is not allowed — run one command per call"

    if "\n" in cmd or "\r" in cmd:
        return False, "multiline commands not allowed"

    for rx in _DANGEROUS_RES:
        if rx.search(cmd):
            return False, f"blocked pattern: {rx.pattern!r}"

    # Block obvious recursive delete of root / wide paths
    if re.search(r"\brm\s+(-[rf]+\s+)?/[ \t]*(/|\s)", cmd):
        return False, "refusing rm on filesystem root"
    try:
        parts = shlex.split(cmd, posix=True)
    except ValueError as e:
        return False, f"shell parse error: {e}"
    if not parts:
        return False, "empty argv"
    base = parts[0].lower()
    if base in ("sudo", "su", "ssh", "scp", "nc", "netcat", "telnet"):
        return False, f"command {base!r} is not allowed"

    return True, ""
