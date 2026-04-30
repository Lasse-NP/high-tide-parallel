# capped_grid_widget.py

from gettext import gettext as _
from gi.repository import Gtk
from ..widgets.card_widget import HTCardWidget


class HTCappedGridWidget(Gtk.Box):
    def __init__(self, items: list, title: str = "", row_limit: int = 4, columns: int = 5):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        self._all_items = list(items)
        self._columns = columns
        self._rows_expand_step = 2
        self._shown = 0

        self._title_label = Gtk.Label(
            label=title,
            halign=Gtk.Align.START,
            css_classes=["title-3"],
        )
        self.append(self._title_label)

        self._flow_box = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            min_children_per_line=columns,
            max_children_per_line=columns,
            homogeneous=True,
            css_classes=["no-hover-flowbox"],
        )
        self.append(self._flow_box)

        self._expand_btn = Gtk.Button(
            halign=Gtk.Align.CENTER,
            icon_name="pan-down-symbolic",
            css_classes=["circular"],
        )
        self._expand_btn.connect("clicked", self._on_expand)
        self.append(self._expand_btn)

        self._show_items(row_limit * columns)

    def _show_items(self, count: int):
        """Append up to `count` more items from where we left off."""
        batch = self._all_items[self._shown: self._shown + count]
        for item in batch:
            self._flow_box.append(HTCardWidget(item))
        self._shown += len(batch)
        self._expand_btn.set_visible(self._shown < len(self._all_items))

    def _on_expand(self, _btn):
        self._show_items(self._columns * self._rows_expand_step)

    def update_items(self, items: list):
        self._all_items = list(items)
        self._shown = 0
        child = self._flow_box.get_first_child()
        while child:
            self._flow_box.remove(child)
            child = self._flow_box.get_first_child()
        self._show_items(3 * self._columns)  # reset to initial row_limit

    def remove_item_by_id(self, item_id):
        child = self._flow_box.get_first_child()
        while child:
            inner = child.get_child()  # FlowBoxChild wraps the card
            if hasattr(inner, 'item') and inner.item and inner.item.id == item_id:
                self._flow_box.remove(child)
                self._all_items = [i for i in self._all_items if i.id != item_id]
                self._shown = max(0, self._shown - 1)
                return
            child = child.get_next_sibling()