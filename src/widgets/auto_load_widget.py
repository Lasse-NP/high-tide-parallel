# auto_load_widget.py
#
# Copyright 2025 Nokse <nokse@posteo.com>
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

import threading

from gi.repository import GLib, GObject, Gtk

from ..disconnectable_iface import IDisconnectable
from ..lib import utils
from .card_widget import HTCardWidget
from .generic_track_widget import HTGenericTrackWidget
from ..lib.draggable_attribute import HTDraggableList

import logging

logger = logging.getLogger(__name__)


@Gtk.Template(
    resource_path="/io/github/nokse22/high-tide/ui/widgets/auto_load_widget.ui"
)
class HTAutoLoadWidget(Gtk.Box, IDisconnectable):
    __gtype_name__ = "HTAutoLoadWidget"

    content = Gtk.Template.Child()
    spinner = Gtk.Template.Child()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        IDisconnectable.__init__(self)

        self.function = None
        self.type = None

        self.parent = None

        self.is_loading = False

        self.items = []
        self.playlist = None
        self._track_widget_map: dict = {}
        self._last_playing_id = None
        self._song_changed_handler = None

        self.items_limit = 50
        self.items_n = 0

        self.handler_id = None
        self.scrolled_window = None

        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

    def reset(self):
        """Reset the widget so it can be reused with new data"""
        self.items = []
        self.items_n = 0
        self.type = None
        self.is_loading = False
        self._track_widget_map = {}
        self._last_playing_id = None

        if self.parent is not None:
            child = self.parent.get_first_child()
            while child:
                self.parent.remove(child)
                child = self.parent.get_first_child()

    def set_function(self, function: callable) -> None:
        """
        Set the function to use to fetch new items, it needs to support limit and
            offset arguments

        Args:
            function (callable): the function to call
        """
        self.function = function

    def set_items(self, items: list) -> None:
        """
        Call once to set the initial items to display. Subsequent calls are supported.

        Args:
            items (list): the list of items
        """
        self.reset()

        if not items:
            return

        self.items = list(items)

        self.type = utils.get_type(self.items[0])

        def _add():
            if self.type == "track":
                self._add_tracks(self.items)
            elif self.type is not None:
                self._add_cards(self.items)

            self.items_n = len(self.items)

        GLib.idle_add(_add)

    def set_scrolled_window(self, scrolled_window) -> None:
        """
        Set the scrolled window

        Args:
            scrolled_window (Gtk.ScrolledWindow): the scrolled window
        """
        if self.scrolled_window is not None and self.handler_id is not None:
            GObject.signal_handler_disconnect(self.scrolled_window, self.handler_id)
            self.signals = [
                (obj, hid) for obj, hid in self.signals
                if not (obj is self.scrolled_window and hid == self.handler_id)
            ]

        self.scrolled_window = scrolled_window
        self.handler_id = self.scrolled_window.connect(
            "edge-reached", self._on_edge_reached
        )
        self.signals.append((self.scrolled_window, self.handler_id))

    def set_reorder_enabled(self, enabled: bool) -> None:
        if hasattr(self, "_draggable") and self._draggable:
            self._draggable.set_reorder_enabled(enabled)

    def th_load_items(self) -> None:
        """Load more items, this function can be called in a thread"""
        if self.is_loading or not self.function:
            return
        self.is_loading = True
        self.spinner.set_visible(True)
        new_items = []
        new_items = self.function(limit=self.items_limit, offset=self.items_n)
        self.items.extend(new_items)
        if new_items == []:
            GObject.signal_handler_disconnect(self.scrolled_window, self.handler_id)
            self.spinner.set_visible(False)
            return
        elif self.type is None:
            self.type = utils.get_type(new_items[0])

        def _add():
            if self.type == "track":
                self._add_tracks(new_items)
            elif self.type is not None:
                self._add_cards(new_items)

            self.items_n += len(new_items)
            self.spinner.set_visible(False)
            self.is_loading = False

        GLib.idle_add(_add)

    def _on_edge_reached(self, scrolled_window, pos):
        GObject.signal_handler_block(self.scrolled_window, self.handler_id)
        if pos == Gtk.PositionType.BOTTOM:
            threading.Thread(target=self.th_load_items).start()
        GObject.signal_handler_unblock(self.scrolled_window, self.handler_id)

    def _is_owned_playlist(self) -> bool:
        from tidalapi.playlist import UserPlaylist
        if not isinstance(self.playlist, UserPlaylist):
            return False
        if not utils.session or not utils.session.user:
            return False
        return bool(
            self.playlist.creator and
            self.playlist.creator.id == utils.session.user.id
        )

    def _add_tracks(self, new_items):
        if self.parent is None:
            self.parent = Gtk.ListBox(css_classes=["tracks-list-box"])
            self.content.set_child(self.parent)
            self.signals.append(
                (
                    self.parent,
                    self.parent.connect("row-activated", self._on_tracks_row_selected),
                )
            )

            if self._is_owned_playlist():
                self.parent.add_css_class("draggable-box")
                self._draggable = HTDraggableList()
                self._draggable.setup(
                    self.parent,
                    self.items,
                    row_factory=lambda track, i: HTGenericTrackWidget(track, playlist=self.playlist),
                    on_reorder=lambda src, dst: threading.Thread(
                        target=self.playlist.move_by_index,
                        args=(src, dst)
                    ).start()
                )

        for index, track in enumerate(new_items):
            listing = HTGenericTrackWidget(track, playlist=self.playlist)
            self.disconnectables.append(listing)
            listing.index = index + self.items_n
            listing.set_name(str(index + self.items_n))
            self._track_widget_map[track.id] = listing
            self.parent.append(listing)

        if utils.player_object and self._song_changed_handler is None:
            self._song_changed_handler = utils.player_object.connect(
                "song-changed", self._on_song_changed
            )

        self._sync_playing_state()

    def _on_map(self, *args):
        if utils.player_object and self._song_changed_handler is None:
            self._song_changed_handler = utils.player_object.connect(
                "song-changed", self._on_song_changed
            )
        self._sync_playing_state()

    def _on_unmap(self, *args):
        if utils.player_object and self._song_changed_handler is not None:
            utils.player_object.disconnect(self._song_changed_handler)
            self._song_changed_handler = None
        if self._last_playing_id and self._last_playing_id in self._track_widget_map:
            self._track_widget_map[self._last_playing_id].remove_css_class("playing-track")
        self._last_playing_id = None

    def _sync_playing_state(self):
        if not utils.player_object or not utils.player_object.playing_track:
            return

        playing_id = utils.player_object.playing_track.id

        if playing_id in self._track_widget_map:
            self._track_widget_map[playing_id].add_css_class("playing-track")
            self._last_playing_id = playing_id

    def _on_song_changed(self, player) -> None:
        new_id = player.playing_track.id if player.playing_track else None

        if self._last_playing_id and self._last_playing_id in self._track_widget_map:
            self._track_widget_map[self._last_playing_id].remove_css_class("playing-track")

        if new_id and new_id in self._track_widget_map:
            self._track_widget_map[new_id].add_css_class("playing-track")

        self._last_playing_id = new_id

    def _add_cards(self, new_items):
        if self.parent is None:
            self.parent = Gtk.FlowBox(selection_mode=0)
            self.content.set_child(self.parent)

        for index, item in enumerate(new_items):
            card = HTCardWidget(item)
            self.disconnectables.append(card)
            self.parent.append(card)

    def _on_tracks_row_selected(self, list_box, row):
        utils.player_object.play_this(self.items, row.index)
