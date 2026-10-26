"""Validate private journal objects without interpreting Windows modes as ACLs."""

import ctypes
import os
import stat
from functools import lru_cache
from pathlib import Path
from typing import Any

_DWORD = ctypes.c_uint32
_WORD = ctypes.c_uint16
_BYTE = ctypes.c_ubyte
_POINTER = ctypes.c_void_p
_BOOL = ctypes.c_int32
_SECURITY_INFORMATION = 0x00000001 | 0x00000004  # Owner and DACL.
_SE_FILE_OBJECT = 1
_SE_DACL_PRESENT = 0x0004
_SE_DACL_PROTECTED = 0x1000
_FILE_ATTRIBUTE_DIRECTORY = 0x0010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
_TRUSTED_SIDS = frozenset({"S-1-5-18", "S-1-5-32-544"})
_OWNER_RIGHTS = "S-1-3-4"


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("sid", _POINTER), ("attributes", _DWORD)]


class _TokenUser(ctypes.Structure):
    _fields_ = [("user", _SidAndAttributes)]


class _AclHeader(ctypes.Structure):
    _fields_ = [
        ("revision", _BYTE),
        ("reserved", _BYTE),
        ("size", _WORD),
        ("ace_count", _WORD),
        ("reserved2", _WORD),
    ]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [("ace_count", _DWORD), ("bytes_in_use", _DWORD), ("bytes_free", _DWORD)]


class _AceHeader(ctypes.Structure):
    _fields_ = [("kind", _BYTE), ("flags", _BYTE), ("size", _WORD)]


class _OrdinaryAce(ctypes.Structure):
    _fields_ = [("header", _AceHeader), ("mask", _DWORD), ("sid_start", _DWORD)]


class _FileTime(ctypes.Structure):
    _fields_ = [("low", _DWORD), ("high", _DWORD)]


class _FileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", _DWORD),
        ("created", _FileTime),
        ("accessed", _FileTime),
        ("written", _FileTime),
        ("volume_serial", _DWORD),
        ("size_high", _DWORD),
        ("size_low", _DWORD),
        ("links", _DWORD),
        ("index_high", _DWORD),
        ("index_low", _DWORD),
    ]


class _WindowsSecurity:
    """Read the small ACL grammar used by Python's private journal directory."""

    def __init__(self) -> None:
        loader = getattr(ctypes, "WinDLL")
        self.advapi: Any = loader("advapi32", use_last_error=True)
        self.kernel: Any = loader("kernel32", use_last_error=True)
        outputs = [ctypes.POINTER(_POINTER)] * 5
        self.advapi.GetNamedSecurityInfoW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_int,
            _DWORD,
            *outputs,
        ]
        self.advapi.GetNamedSecurityInfoW.restype = _DWORD
        self.advapi.GetSecurityInfo.argtypes = [_POINTER, ctypes.c_int, _DWORD, *outputs]
        self.advapi.GetSecurityInfo.restype = _DWORD
        self.advapi.GetSecurityDescriptorControl.argtypes = [
            _POINTER,
            ctypes.POINTER(_WORD),
            ctypes.POINTER(_DWORD),
        ]
        self.advapi.GetSecurityDescriptorControl.restype = _BOOL
        self.advapi.IsValidAcl.argtypes = [_POINTER]
        self.advapi.IsValidAcl.restype = _BOOL
        self.advapi.GetAclInformation.argtypes = [_POINTER, _POINTER, _DWORD, ctypes.c_int]
        self.advapi.GetAclInformation.restype = _BOOL
        self.advapi.GetAce.argtypes = [_POINTER, _DWORD, ctypes.POINTER(_POINTER)]
        self.advapi.GetAce.restype = _BOOL
        self.advapi.IsValidSid.argtypes = [_POINTER]
        self.advapi.IsValidSid.restype = _BOOL
        self.advapi.GetLengthSid.argtypes = [_POINTER]
        self.advapi.GetLengthSid.restype = _DWORD
        self.advapi.ConvertSidToStringSidW.argtypes = [
            _POINTER,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        self.advapi.ConvertSidToStringSidW.restype = _BOOL
        self.advapi.OpenProcessToken.argtypes = [_POINTER, _DWORD, ctypes.POINTER(_POINTER)]
        self.advapi.OpenProcessToken.restype = _BOOL
        self.advapi.GetTokenInformation.argtypes = [
            _POINTER,
            ctypes.c_int,
            _POINTER,
            _DWORD,
            ctypes.POINTER(_DWORD),
        ]
        self.advapi.GetTokenInformation.restype = _BOOL
        self.kernel.GetCurrentProcess.argtypes = []
        self.kernel.GetCurrentProcess.restype = _POINTER
        self.kernel.CloseHandle.argtypes = [_POINTER]
        self.kernel.CloseHandle.restype = _BOOL
        self.kernel.LocalFree.argtypes = [_POINTER]
        self.kernel.LocalFree.restype = _POINTER
        self.kernel.GetFileInformationByHandle.argtypes = [
            _POINTER,
            ctypes.POINTER(_FileInformation),
        ]
        self.kernel.GetFileInformationByHandle.restype = _BOOL
        self.allowed_owners = _TRUSTED_SIDS | {self._current_user_sid()}

    def _sid_text(self, sid: _POINTER) -> str:
        if not sid or not self.advapi.IsValidSid(sid):
            raise ValueError("Invalid security identifier")
        text = ctypes.c_wchar_p()
        if not self.advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise OSError("Security identifier unavailable")
        try:
            if text.value is None:
                raise ValueError("Missing security identifier")
            return text.value
        finally:
            self.kernel.LocalFree(ctypes.cast(text, _POINTER))

    def _current_user_sid(self) -> str:
        token = _POINTER()
        if not self.advapi.OpenProcessToken(
            self.kernel.GetCurrentProcess(),
            0x0008,
            ctypes.byref(token),
        ):
            raise OSError("Process identity unavailable")
        try:
            needed = _DWORD()
            self.advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
            if needed.value < ctypes.sizeof(_TokenUser):
                raise ValueError("Missing process identity")
            buffer = ctypes.create_string_buffer(needed.value)
            if not self.advapi.GetTokenInformation(
                token,
                1,
                buffer,
                needed.value,
                ctypes.byref(needed),
            ):
                raise OSError("Process identity unavailable")
            user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
            return self._sid_text(_POINTER(user.user.sid))
        finally:
            self.kernel.CloseHandle(token)

    def _acl_private(
        self, descriptor: _POINTER, owner: _POINTER, dacl: _POINTER, *, directory: bool
    ) -> bool:
        if not descriptor or not owner or not dacl:
            return False
        control, revision = _WORD(), _DWORD()
        if not self.advapi.GetSecurityDescriptorControl(
            descriptor,
            ctypes.byref(control),
            ctypes.byref(revision),
        ):
            return False
        if not control.value & _SE_DACL_PRESENT:
            return False
        if directory and not control.value & _SE_DACL_PROTECTED:
            return False
        if self._sid_text(owner) not in self.allowed_owners or not self.advapi.IsValidAcl(dacl):
            return False
        header = ctypes.cast(dacl, ctypes.POINTER(_AclHeader)).contents
        information = _AclSizeInformation()
        if not self.advapi.GetAclInformation(
            dacl,
            ctypes.byref(information),
            ctypes.sizeof(information),
            2,
        ):
            return False
        if (
            information.ace_count != header.ace_count
            or not ctypes.sizeof(_AclHeader) <= information.bytes_in_use <= header.size
        ):
            return False
        start = dacl.value
        if start is None:
            return False
        end = start + information.bytes_in_use
        for index in range(information.ace_count):
            entry = _POINTER()
            if not self.advapi.GetAce(dacl, index, ctypes.byref(entry)) or entry.value is None:
                return False
            address = entry.value
            if address < start + ctypes.sizeof(_AclHeader) or address + 4 > end:
                return False
            ace = ctypes.cast(entry, ctypes.POINTER(_AceHeader)).contents
            sid_offset = _OrdinaryAce.sid_start.offset
            if ace.kind not in (0, 1) or ace.size < sid_offset + 8 or address + ace.size > end:
                return False
            sid_address = address + sid_offset
            count = _BYTE.from_address(sid_address + 1).value
            sid_length = 8 + count * 4
            if count > 15 or sid_offset + sid_length > ace.size:
                return False
            sid = _POINTER(sid_address)
            if not self.advapi.IsValidSid(sid) or self.advapi.GetLengthSid(sid) != sid_length:
                return False
            # Denials cannot grant access. Inherit-only grants still affect children.
            if ace.kind == 0 and self._sid_text(sid) not in self.allowed_owners | {_OWNER_RIGHTS}:
                return False
        return True

    def private(
        self, *, path: Path | None = None, handle: int | None = None, directory: bool = False
    ) -> bool:
        owner, dacl, descriptor = _POINTER(), _POINTER(), _POINTER()
        try:
            if path is not None:
                result = self.advapi.GetNamedSecurityInfoW(
                    str(path.absolute()),
                    _SE_FILE_OBJECT,
                    _SECURITY_INFORMATION,
                    ctypes.byref(owner),
                    None,
                    ctypes.byref(dacl),
                    None,
                    ctypes.byref(descriptor),
                )
            else:
                result = self.advapi.GetSecurityInfo(
                    _POINTER(handle),
                    _SE_FILE_OBJECT,
                    _SECURITY_INFORMATION,
                    ctypes.byref(owner),
                    None,
                    ctypes.byref(dacl),
                    None,
                    ctypes.byref(descriptor),
                )
            return result == 0 and self._acl_private(
                descriptor,
                owner,
                dacl,
                directory=directory,
            )
        finally:
            if descriptor:
                self.kernel.LocalFree(descriptor)

    def private_descriptor(self, descriptor: int) -> bool:
        import msvcrt

        handle = int(getattr(msvcrt, "get_osfhandle")(descriptor))
        information = _FileInformation()
        if not self.kernel.GetFileInformationByHandle(_POINTER(handle), ctypes.byref(information)):
            return False
        if information.attributes & (_FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT):
            return False
        return self.private(handle=handle)


@lru_cache(maxsize=1)
def _windows_security() -> _WindowsSecurity:
    return _WindowsSecurity()


def _private_path(path: Path, *, directory: bool) -> bool:
    try:
        details = path.lstat()
        correct_kind = stat.S_ISDIR(details.st_mode) if directory else stat.S_ISREG(details.st_mode)
        if not correct_kind:
            return False
        if os.name == "nt":
            attributes = getattr(details, "st_file_attributes", None)
            if not isinstance(attributes, int) or attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                return False
            return _windows_security().private(path=path, directory=directory)
        expected = 0o700 if directory else 0o600
        return os.name == "posix" and stat.S_IMODE(details.st_mode) == expected
    except OSError, ValueError, TypeError, AttributeError, OverflowError, ctypes.ArgumentError:
        return False


def private_directory(path: Path) -> bool:
    """Check an existing private journal directory; never change its permissions."""
    return _private_path(path, directory=True)


def private_file(path: Path) -> bool:
    """Check an existing private regular file; never follow a symlink or junction."""
    return _private_path(path, directory=False)


def private_file_descriptor(descriptor: int) -> bool:
    """Check the actual open regular file before writing any journal bytes."""
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            return False
        if os.name == "nt":
            return _windows_security().private_descriptor(descriptor)
        return os.name == "posix" and stat.S_IMODE(details.st_mode) == 0o600
    except OSError, ValueError, TypeError, AttributeError, OverflowError, ctypes.ArgumentError:
        return False
