"""Read (never change) who may read a folder on Windows."""

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

assert sys.platform == "win32"  # also tells the type checker the rest is Windows only

SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION = 0x4
ACCESS_ALLOWED_ACE_TYPE = 0
INHERIT_ONLY_ACE = 0x8
ACL_SIZE_INFORMATION_CLASS = 2
TOKEN_QUERY = 0x8
TOKEN_USER_CLASS = 1
# FILE_READ_DATA, GENERIC_READ, GENERIC_ALL
READ_BITS = 0x1 | 0x80000000 | 0x10000000

# Accounts that may always read a user's profile: the local system, administrators,
# and OWNER RIGHTS (whoever owns the folder, i.e. the user).
TRUSTED_SIDS = frozenset({"S-1-5-18", "S-1-5-32-544", "S-1-3-4"})


class AclSizeInformation(ctypes.Structure):
    _fields_ = [
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    ]


class AceHeader(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", wintypes.WORD),
    ]


class AccessAllowedAce(ctypes.Structure):
    _fields_ = [
        ("Header", AceHeader),
        ("Mask", wintypes.DWORD),
        ("SidStart", wintypes.DWORD),
    ]


def _windll() -> ctypes.LibraryLoader[ctypes.WinDLL]:
    """The Windows DLLs, with argument types declared: without them ctypes passes
    handles and pointers as 32-bit integers and 64-bit values get cut."""
    windll: ctypes.LibraryLoader[ctypes.WinDLL] = getattr(ctypes, "windll")  # noqa: B009
    advapi32, kernel32 = windll.advapi32, windll.kernel32
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetAclInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_int,
    ]
    advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    return windll


def _sid_string(sid: int) -> str:
    windll = _windll()
    text = wintypes.LPWSTR()
    if not windll.advapi32.ConvertSidToStringSidW(ctypes.c_void_p(sid), ctypes.byref(text)):
        return "?"
    try:
        return text.value or "?"
    finally:
        windll.kernel32.LocalFree(text)


def current_user_sid() -> str:
    windll = _windll()
    token = wintypes.HANDLE()
    windll.advapi32.OpenProcessToken(
        windll.kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)
    )
    try:
        size = wintypes.DWORD()
        windll.advapi32.GetTokenInformation(token, TOKEN_USER_CLASS, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        windll.advapi32.GetTokenInformation(
            token, TOKEN_USER_CLASS, buffer, size, ctypes.byref(size)
        )
        # TOKEN_USER starts with SID_AND_ATTRIBUTES, whose first field is the SID pointer.
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents.value
        return _sid_string(sid_pointer or 0)
    finally:
        windll.kernel32.CloseHandle(token)


def other_readers(path: Path) -> list[str]:
    """SIDs other than this user, SYSTEM and administrators allowed to read the folder."""
    windll = _windll()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = windll.advapi32.GetNamedSecurityInfoW(
        str(path),
        SE_FILE_OBJECT,
        DACL_SECURITY_INFORMATION,
        None,
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if status != 0:
        return [f"(could not read permissions: error {status})"]
    try:
        if not dacl.value:
            return ["(no access list: everyone can read)"]
        info = AclSizeInformation()
        windll.advapi32.GetAclInformation(
            dacl, ctypes.byref(info), ctypes.sizeof(info), ACL_SIZE_INFORMATION_CLASS
        )
        allowed = TRUSTED_SIDS | {current_user_sid()}
        readers: list[str] = []
        for index in range(info.AceCount):
            ace_pointer = ctypes.c_void_p()
            windll.advapi32.GetAce(dacl, index, ctypes.byref(ace_pointer))
            ace = ctypes.cast(ace_pointer, ctypes.POINTER(AccessAllowedAce)).contents
            if ace.Header.AceType != ACCESS_ALLOWED_ACE_TYPE:
                continue
            if ace.Header.AceFlags & INHERIT_ONLY_ACE or not ace.Mask & READ_BITS:
                continue
            sid = _sid_string((ace_pointer.value or 0) + AccessAllowedAce.SidStart.offset)
            if sid not in allowed:
                readers.append(sid)
        return readers
    finally:
        windll.kernel32.LocalFree(descriptor)
