"""Small, strict Windows Job Object owner. No fallback to unowned execution."""
from __future__ import annotations

import os
import time

if os.name == "nt":
    import ctypes
    from ctypes import wintypes as w

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ULONG_PTR = ctypes.c_size_t

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", w.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", w.DWORD), ("Affinity", ULONG_PTR),
                    ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class ACCOUNTING(ctypes.Structure):
        _fields_ = [(n, ctypes.c_longlong) for n in (
            "TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime",
            "ThisPeriodTotalKernelTime")] + [(n, w.DWORD) for n in (
            "TotalPageFaultCount", "TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses")]

    def _sig(name, args, result):
        fn = getattr(k32, name)
        fn.argtypes, fn.restype = args, result
        return fn

    _create = _sig("CreateJobObjectW", [ctypes.c_void_p, w.LPCWSTR], w.HANDLE)
    _set = _sig("SetInformationJobObject", [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL)
    _query = _sig("QueryInformationJobObject", [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)], w.BOOL)
    _assign = _sig("AssignProcessToJobObject", [w.HANDLE, w.HANDLE], w.BOOL)
    _terminate = _sig("TerminateJobObject", [w.HANDLE, w.UINT], w.BOOL)
    _close = _sig("CloseHandle", [w.HANDLE], w.BOOL)
    _times = _sig("GetProcessTimes", [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4, w.BOOL)
    _open_thread = _sig("OpenThread", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)
    _cancel_io = _sig("CancelSynchronousIo", [w.HANDLE], w.BOOL)

    def _check(ok):
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def process_creation_time(handle):
        values = [w.FILETIME() for _ in range(4)]
        _check(_times(w.HANDLE(int(handle)), *(ctypes.byref(v) for v in values)))
        return (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime

    def cancel_thread_io(thread):
        """Interrupt a stuck anonymous-pipe operation before closing its stream."""
        if thread.native_id is None:
            return
        handle = _open_thread(0x0001, False, thread.native_id)  # THREAD_TERMINATE
        if handle:
            try:
                _cancel_io(handle)  # ERROR_NOT_FOUND simply means no pending I/O.
            finally:
                _close(handle)

    class Job:
        def __init__(self):
            self.handle = _create(None, None)  # non-inheritable, unnamed
            _check(self.handle)
            try:
                limits = EXTENDED_LIMIT()
                limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
                _check(_set(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
            except BaseException:
                self.close()
                raise

        def assign(self, process_handle):
            _check(_assign(self.handle, w.HANDLE(int(process_handle))))

        def active(self):
            info = ACCOUNTING()
            _check(_query(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None))
            return info.ActiveProcesses

        def terminate_and_wait(self, timeout=1.0):
            _check(_terminate(self.handle, 1))
            deadline = time.monotonic() + timeout
            while True:
                if self.active() == 0:
                    return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.01)

        def close(self):
            if self.handle:
                handle, self.handle = self.handle, None
                _check(_close(handle))
else:
    class Job:
        def __init__(self):
            raise OSError("Windows Job Objects require Windows")

    def process_creation_time(handle):
        raise OSError("Windows process identity requires Windows")

    def cancel_thread_io(thread):
        return
