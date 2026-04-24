
from gi.repository import Adw, Gtk, Gdk
from . import utils

class SmoothScroller:

    def __init__(self, scrolled_window: Gtk.ScrolledWindow):
        self._scrolled_window = scrolled_window
        self._target_value = 0.0
        self._animation = None

        controller = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL |
            Gtk.EventControllerScrollFlags.KINETIC
        )
        controller.connect("scroll", self._on_scroll)
        scrolled_window.add_controller(controller)

    def _on_scroll(self, controller, dx, dy) -> bool:
        if not utils.smooth_scroll_enabled:
            return False
        adj = self._scrolled_window.get_vadjustment()
        step = adj.get_page_size() * 0.15
        self._target_value = max(
            adj.get_lower(),
            min(adj.get_upper() - adj.get_page_size(),
                self._target_value + dy * step)
        )

        if self._animation:
            self._animation.pause()

        target = Adw.PropertyAnimationTarget.new(adj, "value")
        self._animation = Adw.TimedAnimation.new(
            self._scrolled_window, adj.get_value(), self._target_value, 200, target
        )
        self._animation.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        self._animation.play()

        return True