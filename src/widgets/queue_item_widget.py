import threading

from gi.repository import Adw, Gio, GObject, Gtk, Gdk

from ..lib import utils
from ..disconnectable_iface import IDisconnectable

@Gtk.Template(
    resource_path="/io/github/nokse22/high-tide/ui/widgets/queue_item_widget.ui"
)
class HTQueueItemWidget(Gtk.ListBoxRow, IDisconnectable):

    __gtype_name__ = "HTQueueItemWidget"

    image = Gtk.Template.Child()
    title_label = Gtk.Template.Child()
    artist_label = Gtk.Template.Child()

    current_drag_list_type = None

    def __init__(self, track, list_type):
        IDisconnectable.__init__(self)
        super().__init__()

        self.track = track
        self.list_type = list_type

        self.title_label.set_label(
            self.track.full_name
            if hasattr(self.track, "full_name")
            else self.track.name
        )

        self.signals.append(
            (
                self.artist_label,
                self.artist_label.connect("activate-link", utils.open_uri),
            )
        )

        threading.Thread(
            target=utils.add_image, args=(self.image, self.track.album)
        ).start()

        self.action_group = Gio.SimpleActionGroup()
        self.insert_action_group("queueitemwidget", self.action_group)

        drag_source = Gtk.DragSource()
        drag_source.set_actions(Gdk.DragAction.MOVE)
        drag_source.connect("prepare", self._on_drag_prepare)
        drag_source.connect("drag-begin", self._on_drag_begin)
        drag_source.connect("drag-end", self._on_drag_end)
        self.add_controller(drag_source)

        self.set_cursor_from_name("pointer")

    def _on_drag_prepare(self, source, x, y):
        # Pass the row index as the drag data
        index = int(self.get_name())
        return Gdk.ContentProvider.new_for_value(index)

    def _on_drag_begin(self, source, drag):
        HTQueueItemWidget.current_drag_list_type = self.list_type
        paintable = Gtk.WidgetPaintable.new(self)
        source.set_icon(paintable, self.get_width() // 2, self.get_height() // 2)

    def _on_drag_end(self, source, drag, delete_data):
        HTQueueItemWidget.current_drag_list_type = self.list_type