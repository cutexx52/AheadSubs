from queue import SimpleQueue
from threading import Event


class SettingsTray:
    def __init__(self):
        import pystray
        from PIL import Image, ImageDraw

        self.actions = SimpleQueue()
        self.ready = Event()
        image = Image.new("RGBA", (64, 64))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((1, 1, 62, 62), radius=13, fill="#17506b")
        draw.rounded_rectangle((10, 15, 53, 48), radius=5, fill="white")
        for bounds in ((17, 24, 32, 28), (36, 24, 47, 28), (17, 35, 26, 39), (30, 35, 47, 39)):
            draw.rounded_rectangle(bounds, radius=2, fill="#17506b")
        self.icon = pystray.Icon(
            "Subtitle Relay", image, "Subtitle Relay",
            menu=pystray.Menu(
                pystray.MenuItem("打开设置", lambda: self.actions.put("open"), default=True),
                pystray.MenuItem("退出 Subtitle Relay", lambda: self.actions.put("quit")),
            ),
        )
        self.icon.run_detached(self._show)

    def _show(self, icon):
        try:
            icon.visible = True
        finally:
            self.ready.set()

    def close(self):
        self.ready.wait(2)
        self.icon.visible = False
        self.icon.stop()
