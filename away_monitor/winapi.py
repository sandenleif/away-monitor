"""Duenne ctypes-Huelle um die drei Windows-APIs, die wir brauchen."""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


_user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LastInputInfo)]
_user32.GetLastInputInfo.restype = wintypes.BOOL
_user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_user32.OpenInputDesktop.restype = wintypes.HANDLE
_user32.CloseDesktop.argtypes = [wintypes.HANDLE]
_user32.CloseDesktop.restype = wintypes.BOOL
_user32.LockWorkStation.argtypes = []
_user32.LockWorkStation.restype = wintypes.BOOL
_kernel32.GetTickCount.argtypes = []
_kernel32.GetTickCount.restype = wintypes.DWORD
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL

_UINT32_MASK = 0xFFFFFFFF
_DESKTOP_SWITCHDESKTOP = 0x0100
_ERROR_ALREADY_EXISTS = 183
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79

# Muss bis zum Prozessende leben -- gibt Windows den Mutex frei, koennte
# eine zweite Instanz starten.
_instance_handle = None


def idle_seconds() -> float:
    """Sekunden seit der letzten Maus-/Tastatureingabe (systemweit)."""
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(_LastInputInfo)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        log.warning("GetLastInputInfo fehlgeschlagen (%d)", ctypes.get_last_error())
        return 0.0
    # dwTime und GetTickCount sind beide 32-Bit und laufen nach 49,7 Tagen Uptime
    # ueber. Die Maskierung haelt die Differenz auch ueber den Ueberlauf korrekt --
    # GetTickCount64 hier zu mischen ergaebe danach absurde Idle-Zeiten.
    delta_ms = (_kernel32.GetTickCount() - info.dwTime) & _UINT32_MASK
    return delta_ms / 1000.0


def is_session_locked() -> bool:
    """True bei aktivem Sperrbildschirm (auch bei UAC-Secure-Desktop)."""
    handle = _user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
    if not handle:
        return True
    _user32.CloseDesktop(handle)
    return False


def lock_workstation() -> bool:
    """Sperrt die Sitzung. Braucht keine Adminrechte."""
    if _user32.LockWorkStation():
        return True
    log.error("LockWorkStation fehlgeschlagen (%d)", ctypes.get_last_error())
    return False


def claim_single_instance(name: str) -> bool:
    """Benannter Mutex als Instanzsperre. False heisst: es laeuft schon eine.

    Zwei Instanzen vertragen sich nicht -- DirectShow gibt die Kamera exklusiv
    heraus, die zweite bekaeme nie ein Bild. Laesst sich der Mutex gar nicht
    anlegen, wird der Start trotzdem zugelassen: lieber zwei Instanzen als eine
    App, die sich wegen einer Randbedingung nicht mehr starten laesst.
    """
    global _instance_handle
    handle = _kernel32.CreateMutexW(None, False, name)
    error = ctypes.get_last_error()
    if not handle:
        log.warning("Instanzsperre nicht anlegbar (%d) -- Start wird zugelassen", error)
        return True
    if error == _ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return False
    _instance_handle = handle
    return True


def instance_is_running(name: str) -> bool:
    """Nachsehen, ohne die Sperre zu uebernehmen."""
    handle = _kernel32.CreateMutexW(None, False, name)
    error = ctypes.get_last_error()
    if not handle:
        return False
    _kernel32.CloseHandle(handle)
    return error == _ERROR_ALREADY_EXISTS


def virtual_screen() -> tuple[int, int, int, int]:
    """Rechteck ueber *alle* Bildschirme als (x, y, breite, hoehe).

    Tk kennt nur den Hauptbildschirm. Wer einen Monitor links oder oberhalb
    stehen hat, arbeitet dort mit negativen Koordinaten -- gegen
    winfo_screenwidth() geklemmt landet ein Fenster von dort wieder auf dem
    Hauptbildschirm."""
    metric = _user32.GetSystemMetrics
    return (metric(_SM_XVIRTUALSCREEN), metric(_SM_YVIRTUALSCREEN),
            metric(_SM_CXVIRTUALSCREEN), metric(_SM_CYVIRTUALSCREEN))
