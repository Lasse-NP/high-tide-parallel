# carousel.py
#
# Copyright 2023 Nokse
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Callable
import logging

from gi.repository import Gtk, GLib

from ..disconnectable_iface import IDisconnectable
from ..lib import utils
from ..widgets.card_widget import HTCardWidget

logger = logging.getLogger(__name__)


@Gtk.Template(
    resource_path="/io/github/nokse22/high-tide/ui/widgets/carousel_widget.ui"
)
class HTCarouselWidget(Gtk.Box, IDisconnectable):
    """A horizontal scrolling carousel widget for displaying multiple TIDAL items.

    This widget creates a scrollable carousel with navigation arrows to display
    collections of TIDAL content (albums, artists, playlists, etc.) in a
    horizontal layout. It supports "See More" functionality to navigate to
    detailed pages and automatic card creation for TIDAL items.
    """

    __gtype_name__ = "HTCarouselWidget"

    title_label = Gtk.Template.Child()
    next_button = Gtk.Template.Child()
    prev_button = Gtk.Template.Child()
    carousel = Gtk.Template.Child()
    more_button = Gtk.Template.Child()

    def __init__(self, _title=""):
        IDisconnectable.__init__(self)
        super().__init__()

        self.signals.append((
            self.next_button,
            self.next_button.connect("clicked", self.carousel_go_next),
        ))

        self.signals.append((
            self.prev_button,
            self.prev_button.connect("clicked", self.carousel_go_prev),
        ))

        self.signals.append((
            self.more_button,
            self.more_button.connect("clicked", self.on_more_clicked),
        ))

        self.n_pages = 0
        self._clone_count = 0

        self.title = _title
        self.title_label.set_label(self.title)

        self.more_function = None

        self.items = []

    def set_more_function(self, function: Callable) -> None:
        """Set the function to call when the "See More" button is clicked.

        Args:
            function: A callable that returns page content
        """
        self.more_button.set_visible(True)
        self.more_function = function

    def set_items(self, items_list) -> None:
        """Set the list of items to display in the carousel.

        Creates card widgets for each item in the list and adds them to the carousel.

        Args:
            items_list: List of TIDAL objects to display as cards
        """
        self.items = list(items_list)
        self._build_carousel()

    def _build_carousel(self) -> None:
        # Clear existing
        while self.carousel.get_n_pages() > 0:
            self.carousel.remove(self.carousel.get_nth_page(0))

        if not self.items:
            return

        if len(self.items) >= 8:
            self.more_button.set_visible(True)

        # Number of clones on each side
        display_items = self.items[:8]
        self._clone_count = min(6, len(display_items))

        # Append clones of last N items at the start
        for item in display_items[-self._clone_count:]:
            card = HTCardWidget(item)
            self.disconnectables.append(card)
            self.carousel.append(card)

        # Append real items
        for item in display_items:
            card = HTCardWidget(item)
            self.disconnectables.append(card)
            self.carousel.append(card)

        # Append clones of first N items at the end
        for item in display_items[:self._clone_count]:
            card = HTCardWidget(item)
            self.disconnectables.append(card)
            self.carousel.append(card)

        # Start at the first real item (after the leading clones)
        GLib.idle_add(self._jump_to_real_start)
        GLib.idle_add(self._update_button_states)

    def _jump_to_real_start(self) -> None:
        start_page = self.carousel.get_nth_page(self._clone_count)
        if start_page:
            self.carousel.scroll_to(start_page, False)


    def on_more_clicked(self, *args):
        """Handle "See More" button clicks by navigating to a detailed page"""
        from ..pages import HTFromFunctionPage

        if self.more_function is None:
            page = HTFromFunctionPage(self.title)
            page.set_items(self.items)
        else:
            page = HTFromFunctionPage(self.title)
            page.set_function(self.more_function)

        page.load()
        utils.navigation_view.push(page)

    def _get_visible_count(self) -> int:
        """How many cards fit in the current viewport width."""
        carousel_width = self.get_allocated_width()
        card_width = 167 + 6  # card width-request + spacing
        visible = max(1, carousel_width // card_width)
        logger.debug(f"carousel_width={carousel_width}, card_width={card_width}, visible_count={visible}")
        return visible

    def _update_button_states(self) -> None:
        total = self.carousel.get_n_pages()
        self.prev_button.set_sensitive(total > 1)
        self.next_button.set_sensitive(total > 1)

    def carousel_go_next(self, *args):
        """Navigate to the next page in the carousel"""
        pos = round(self.carousel.get_position())
        total = self.carousel.get_n_pages()
        real_count = min(len(self.items), 8)
        next_pos = pos + 2

        next_page = self.carousel.get_nth_page(next_pos)
        if next_page is not None:
            self.carousel.scroll_to(next_page, True)

        if next_pos >= self._clone_count + real_count:
            real_pos = next_pos - real_count
            GLib.timeout_add(300, self._silent_jump, real_pos)

    def carousel_go_prev(self, *args):
        """Navigate to the previous page in the carousel"""
        pos = round(self.carousel.get_position())
        real_count = min(len(self.items), 8)
        prev_pos = pos - 2

        prev_page = self.carousel.get_nth_page(prev_pos)
        if prev_page is not None:
            self.carousel.scroll_to(prev_page, True)

        if prev_pos < self._clone_count:
            real_pos = prev_pos + real_count
            GLib.timeout_add(300, self._silent_jump, real_pos)

    def _silent_jump(self, pos) -> bool:
        page = self.carousel.get_nth_page(pos)
        if page:
            self.carousel.scroll_to(page, False)
        return False

    def remove_item_by_id(self, item_id) -> None:
        for i in range(self.carousel.get_n_pages()):
            card = self.carousel.get_nth_page(i)
            if hasattr(card, 'item') and card.item and card.item.id == item_id:
                self.carousel.remove(card)
                self.n_pages = self.carousel.get_n_pages()
                self.next_button.set_sensitive(self.n_pages > 2)
                return

    def update_items(self, new_items) -> None:
        # Fade out
        self.set_opacity(0.3)

        # Clear carousel
        while self.carousel.get_n_pages() > 0:
            self.carousel.remove(self.carousel.get_nth_page(0))

        self.items = new_items
        self.n_pages = 0

        for index, item in enumerate(self.items):
            if index >= 8:
                self.more_button.set_visible(True)
                break
            card = HTCardWidget(item)
            self.disconnectables.append(card)
            self.carousel.append(card)
            self.n_pages = self.carousel.get_n_pages()
            if self.n_pages != 2:
                self.next_button.set_sensitive(True)

        # Fade back in
        self.set_opacity(1.0)
