import threading

from gi.repository import Adw, Gio, GObject, Gtk

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

    def __init__(self, track):
        IDisconnectable.__init__(self)
        super().__init__()

        self.track = track

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