# default_image_widget.py

import random
from gi.repository import Gtk, GLib


class HTDefaultImageWidget(Gtk.Box):
    """A styled placeholder widget showing initials on a colored gradient background."""

    __gtype_name__ = "HTDefaultImageWidget"

    def __init__(self, name: str, seed: int, size: int = 155, color: tuple[int, int, int] | None = None) -> None:
        """
        Args:
            name: The name to generate initials from
            seed: A unique integer to seed the color (e.g. artist ID)
            size: The width and height of the widget in pixels
            color: Optional (r, g, b) tuple to use instead of generated color
        """
        super().__init__()

        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_hexpand(False)
        self.set_vexpand(False)
        self.set_size_request(size, size)
        self._size = size
        self._seed = seed
        self._name = name

        initials = "".join(w[0].upper() for w in name.split()[:2])

        self._label = Gtk.Label(label=initials)
        self._label.set_halign(Gtk.Align.CENTER)
        self._label.set_valign(Gtk.Align.CENTER)
        self._label.set_size_request(size, size)
        self._label.set_xalign(0.5)
        self._label.set_yalign(0.5)

        self.append(self._label)
        self._css_provider = Gtk.CssProvider()
        self.get_style_context().add_provider(
            self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._label.get_style_context().add_provider(
            self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        if color:
            self.set_color(color)
        else:
            self._apply_hue(self._default_hue())

    def _default_hue(self) -> int:
        return random.Random(self._seed).randint(0, 360)

    def set_color(self, color: tuple[int, int, int]) -> None:
        """Update the gradient using an RGB color tuple."""
        r, g, b = color
        # Convert RGB to hue for HSL gradient
        r_, g_, b_ = r / 255, g / 255, b / 255
        max_c = max(r_, g_, b_)
        min_c = min(r_, g_, b_)
        delta = max_c - min_c

        if delta == 0:
            hue = 0
        elif max_c == r_:
            hue = 60 * (((g_ - b_) / delta) % 6)
        elif max_c == g_:
            hue = 60 * (((b_ - r_) / delta) + 2)
        else:
            hue = 60 * (((r_ - g_) / delta) + 4)

        GLib.idle_add(self._apply_hue, int(hue))

    def _apply_hue(self, hue: int) -> None:
        self._css_provider.load_from_string(f"""
            * {{
                background: linear-gradient(
                    to bottom,
                    hsl({hue}, 50%, 38%),
                    hsl({hue}, 50%, 22%)
                );
            }}
            label {{
                background: transparent;
                font-size: {self._size // 3}px;
                font-weight: bold;
                color: hsl({hue}, 60%, 85%);
            }}
        """)