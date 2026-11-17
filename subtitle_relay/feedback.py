import ctypes as ct
import time
import tkinter as tk
from ctypes import wintypes as win


class PotFeedback:
    """Brief playback messages, without moving keyboard focus out of PotPlayer."""

    def __init__(self, hwnd):
        self.player = hwnd
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.text = tk.Label(self.root, bg="#20252b", fg="white", font=("Segoe UI", 11),
                             padx=12, pady=8, wraplength=420, justify="left")
        self.text.pack()
        self.root.update_idletasks()
        self.user = ct.WinDLL("user32")
        self.user.GetParent.argtypes = [win.HWND]
        self.user.GetParent.restype = win.HWND
        self.user.GetWindowRect.argtypes = [win.HWND, ct.POINTER(win.RECT)]
        self.user.SetWindowLongW.argtypes = [win.HWND, ct.c_int, win.LONG]
        self.user.GetWindowLongW.argtypes = [win.HWND, ct.c_int]
        self.user.SetWindowPos.argtypes = [win.HWND, win.HWND, ct.c_int, ct.c_int, ct.c_int, ct.c_int, win.UINT]
        self.window = self.user.GetParent(self.root.winfo_id())
        style = self.user.GetWindowLongW(self.window, -20)
        self.user.SetWindowLongW(self.window, -20, style | 0x08000080)
        self.latest = None

    def report(self, state, message):
        self.root.update()
        if state == self.latest:
            return
        self.latest = state
        self.text.configure(text=f"Subtitle Relay · {message}")
        self.root.update_idletasks()
        rect = win.RECT()
        self.user.GetWindowRect(self.player, ct.byref(rect))
        self.root.deiconify()
        self.user.SetWindowPos(self.window, win.HWND(-1), rect.left + 12, rect.top + 35,
                               self.text.winfo_reqwidth(), self.text.winfo_reqheight(), 0x50)
        if hasattr(self, "timer"):
            self.root.after_cancel(self.timer)
        self.timer = self.root.after(2700, self.root.withdraw)
        self.root.update()

    def close(self, linger=0):
        deadline = time.monotonic() + linger
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.05)
        self.root.destroy()
