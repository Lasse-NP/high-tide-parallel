
from gi.repository import Gdk, Gtk

class HTDraggableList:

    def setup(self, list_box, items, row_factory, on_reorder=None):
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
        self._indicator_row = None

        drop_target = Gtk.DropTarget.new(int, Gdk.DragAction.MOVE)
        drop_target.connect("drop", self._on_drop)
        drop_target.connect("motion", self._on_drag_motion)
        drop_target.connect("leave", self._on_drag_leave)
        self._list_box.add_controller(drop_target)

    def _on_drop(self, target, value, x, y) -> bool:
        self._hide_drop_indicator()

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

        self._rebuild_list()

        if self._on_reorder:
            self._on_reorder(source_index, dest_index)

        return True

    def _on_drag_motion(self, target, x, y):
        self._show_drop_indicator(int(y))
        return Gdk.DragAction.MOVE

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
            if last:
                last.add_css_class("drop-target-below")
                self._indicator_row = last

    def _hide_drop_indicator(self) -> None:
        if self._indicator_row:
            self._indicator_row.remove_css_class("drop-target-above")
            self._indicator_row.remove_css_class("drop-target-below")
            self._indicator_row = None

    def _rebuild_list(self) -> None:
        child = self._list_box.get_row_at_index(0)
        while child:
            self._list_box.remove(child)
            child = self._list_box.get_row_at_index(0)
        for index, item in enumerate(self._items):
            row = self._row_factory(item, index)
            row.set_name(str(index))
            self._list_box.append(row)