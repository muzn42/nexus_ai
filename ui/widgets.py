"""
NEXUS AI v2 — Özel Widget Bileşenleri
StrokeLabel (dış çizgili metin) ve ToolTip.
"""
import tkinter as tk


class ToolTip:
    """Bir widget'a fare ile üzerine gelince çıkan bilgi baloncuğu."""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.widget.bind("<Enter>", self._show)
        self.widget.bind("<Leave>", self._hide)

    def update_text(self, text: str):
        self.text = text

    def _show(self, event=None):
        if self.tipwindow or not self.text:
            return
        try:
            x, y, cx, cy = self.widget.bbox("insert")
        except Exception:
            x, y, cx, cy = 0, 0, 0, 20
        x = x + self.widget.winfo_rootx() + 25
        y = y + cy + self.widget.winfo_rooty() + 25
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry("+%d+%d" % (x, y))
        tw.attributes("-topmost", True)

        label = tk.Label(
            tw, text=self.text, justify=tk.LEFT,
            background="#1a1a2e", foreground="#e0e0e0",
            relief=tk.SOLID, borderwidth=1,
            font=("Segoe UI", 10), padx=8, pady=4
        )
        label.pack()

    def _hide(self, event=None):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()


class StrokeLabel(tk.Canvas):
    """
    Dış çizgili (stroke/outline) metin Canvas'ı.
    Oyun HUD'ları gibi her arka planda okunabilir metin sağlar.
    """

    def __init__(self, master, text="", font_family="Segoe UI", font_size=22,
                 text_color="#FFFFFF", stroke_color="#000000", stroke_width=2, **kwargs):
        if "bg" not in kwargs and "background" not in kwargs:
            try:
                kwargs["bg"] = master.cget("bg")
            except Exception:
                kwargs["bg"] = "black"

        super().__init__(master, highlightthickness=0, **kwargs)
        self._text = text
        self._font_family = font_family
        self._font_size = font_size
        self._text_color = text_color
        self._stroke_color = stroke_color
        self._stroke_width = stroke_width
        self._fade_alpha = 1.0

        self.bind("<Configure>", self._on_resize)
        self._redraw()

    def config_text(self, text=None, text_color=None, font_size=None,
                    stroke_color=None, stroke_width=None):
        changed = False
        if text is not None and text != self._text:
            self._text = text
            changed = True
        if text_color is not None:
            self._text_color = text_color
            changed = True
        if font_size is not None:
            self._font_size = int(font_size)
            changed = True
        if stroke_color is not None:
            self._stroke_color = stroke_color
            changed = True
        if stroke_width is not None:
            self._stroke_width = int(stroke_width)
            changed = True
        if changed:
            self._redraw()

    def _on_resize(self, event):
        self._redraw()

    def _redraw(self):
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()

        if width <= 1 or height <= 1:
            return

        x = width / 2
        y = height / 2

        current_font = (self._font_family, self._font_size, "bold")

        # Dış çizgi (stroke)
        if self._stroke_width > 0:
            sw = self._stroke_width
            for dx in range(-sw, sw + 1):
                for dy in range(-sw, sw + 1):
                    if dx == 0 and dy == 0:
                        continue
                    self.create_text(
                        x + dx, y + dy, text=self._text, font=current_font,
                        fill=self._stroke_color, width=width - 20, justify="center"
                    )

        # Ana metin
        self.create_text(
            x, y, text=self._text, font=current_font,
            fill=self._text_color, width=width - 20, justify="center"
        )
