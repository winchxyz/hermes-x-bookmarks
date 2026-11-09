"""Find the user's real Desktop folder (OneDrive-redirected on many Windows machines).

Windows: ``SHGetKnownFolderPath(FOLDERID_Desktop)``, then the "User Shell Folders" registry
value, then ``~/Desktop``. macOS: ``~/Desktop``. Linux: ``xdg-user-dir DESKTOP``, then
``~/Desktop``. Never raises: the last resort is the home folder.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"


def _windows_known_folder() -> Path | None:
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        guid = GUID()
        ctypes.oledll.ole32.CLSIDFromString(FOLDERID_DESKTOP, ctypes.byref(guid))
        out = ctypes.c_wchar_p()
        ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                                   ctypes.byref(out))
        try:
            return Path(out.value) if out.value else None
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)
    except Exception:  # noqa: BLE001 - any failure falls through to the next method
        return None


def _windows_registry() -> Path | None:
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows"
                             r"\CurrentVersion\Explorer\User Shell Folders")
        with key:
            value, _ = winreg.QueryValueEx(key, "Desktop")
        return Path(os.path.expandvars(value)) if value else None
    except Exception:  # noqa: BLE001
        return None


def _xdg_desktop() -> Path | None:
    exe = shutil.which("xdg-user-dir")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "DESKTOP"], capture_output=True, text=True, timeout=5,
                             check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    home = str(Path.home())
    return Path(out) if out and out.rstrip("/") != home.rstrip("/") else None


def desktop_dir(platform: str | None = None) -> Path:
    plat = platform or sys.platform
    candidates: list[Path | None] = []
    if plat.startswith("win"):
        candidates += [_windows_known_folder(), _windows_registry()]
    elif plat.startswith("linux"):
        candidates.append(_xdg_desktop())
    candidates.append(Path.home() / "Desktop")
    for c in candidates:
        if c is not None and c.is_dir():
            return c
    return Path.home()
