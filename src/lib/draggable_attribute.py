
from gi.repository import Gdk, Gtk
from ..widgets.queue_item_widget import HTQueueItemWidget

class HTDraggableList:

    def __init__(self):
        self._list_box = None
        self._items = []
        self._row_factory = None
        self._on_reorder = None
        self._list_type = None
        self._indicator_row = None

    def setup(self, list_box, items, row_factory, on_reorder=None, list_type=None):
        """Set up drag-to-reorder on a list box.

        Args:
            list_box: The GtkListBox to make draggable
            items: The list of items backing the list box (mutated in place)
            row_factory: callable(item, index) -> GtkListBoxRow
            on_reorder: optional callable(source_index, dest_index) called after reorder
        """
        self._list_box = list_box
        self._items = items
        self._row_factory = row_factory
        self._on_reorder = on_reorder
        self._list_type = list_type
        self._indicator_row = None

        self._drop_target = Gtk.DropTarget.new(int, Gdk.DragAction.MOVE)
        self._drop_target.connect("drop", self._on_drop)
        self._drop_target.connect("motion", self._on_drag_motion)
        self._drop_target.connect("leave", self._on_drag_leave)
        self._list_box.add_controller(self._drop_target)

    def set_reorder_enabled(self, enabled: bool) -> None:
        if self._drop_target:
            self._drop_target.set_actions(
                Gdk.DragAction.MOVE if enabled else 0
            )

    def _on_drop(self, target, value, x, y) -> bool:
        self._hide_drop_indicator()

        if self._list_type and self._get_active_drag_type() != self._list_type:
            return False

        try:
            source_index = int(value)
        except (ValueError, TypeError):
            return False

        dest_row = self._list_box.get_row_at_y(int(y))
        dest_index = int(dest_row.get_name()) if dest_row else len(self._items) - 1

        if source_index == dest_index:
            return False

        item = self._items.pop(source_index)
        self._items.insert(dest_index, item)

        self._source_index = source_index
        self._dest_index = dest_index
        self._rebuild_list()

        if self._on_reorder:
            self._on_reorder(source_index, dest_index)

        return True

    def _on_drag_motion(self, target, x, y):
        if self._list_type and self._get_active_drag_type() != self._list_type:
            self._hide_drop_indicator()
            return 0

        self._show_drop_indicator(int(y))
        return Gdk.DragAction.MOVE

    def _get_active_drag_type(self):
        return HTQueueItemWidget.current_drag_list_type

    def _on_drag_leave(self, target):
        self._hide_drop_indicator()

    def _show_drop_indicator(self, y) -> None:
        self._hide_drop_indicator()
        row = self._list_box.get_row_at_y(y)
        if row:
            row.add_css_class("drop-target-above")
            self._indicator_row = row
        else:
            last = None
            i = 0
            while self._list_box.get_row_at_index(i):
                last = self._list_box.get_row_at_index(i)
                i += 1
            if last is not None:
                last.add_css_class("drop-target-below")
                self._indicator_row = last

    def _hide_drop_indicator(self) -> None:
        if self._indicator_row:
            self._indicator_row.remove_css_class("drop-target-above")
            self._indicator_row.remove_css_class("drop-target-below")
            self._indicator_row = None

    def _rebuild_list(self) -> None:
        source_row = self._list_box.get_row_at_index(self._source_index)
        if source_row is None:
            return

        self._list_box.remove(source_row)
        self._list_box.insert(source_row, self._dest_index)

        i = 0
        row = self._list_box.get_row_at_index(i)
        while row:
            row.set_name(str(i))
            row.index = i
            i += 1
            row = self._list_box.get_row_at_index(i)