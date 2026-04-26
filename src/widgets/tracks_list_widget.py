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

from typing import Callable, List

from gi.repository import Gtk
from tidalapi.media import Track

from ..disconnectable_iface import IDisconnectable
from ..lib import utils
from .generic_track_widget import HTGenericTrackWidget

import logging

logger = logging.getLogger(__name__)


@Gtk.Template(
    resource_path="/io/github/nokse22/high-tide/ui/widgets/tracks_list_widget.ui"
)
class HTTracksListWidget(Gtk.Box, IDisconnectable):
    """It is used to display multiple elements side by side
    with navigation arrows"""

    __gtype_name__ = "HTTracksListWidget"

    tracks_list_box = Gtk.Template.Child()
    more_button = Gtk.Template.Child()
    title_label = Gtk.Template.Child()

    def __init__(self, title):
        IDisconnectable.__init__(self)
        super().__init__()

        logger.debug(f"[TRACKS_LIST] __init__ called, id={id(self)}")

        self.signals.append(
            (
                self.more_button,
                self.more_button.connect("clicked", self._on_more_clicked),
            )
        )

        self.n_pages = 0

        self.title_name: str = title
        self.title_label.set_label(title)

        self.get_function: Callable = None

        self.signals.append(
            (
                self.tracks_list_box,
                self.tracks_list_box.connect(
                    "row-activated", self._on_tracks_row_selected
                ),
            )
        )

        self.tracks: List[Track] = []
        self._track_widget_map: dict = {}
        self._last_playing_id = None
        self._song_changed_handler = None

        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

        self.set_cursor_from_name("pointer")

    def _on_map(self, *args):
        """Called when this widget becomes visible on screen."""
        if utils.player_object and self._song_changed_handler is None:
            self._song_changed_handler = utils.player_object.connect(
                "song-changed", self._on_song_changed
            )
        # Sync immediately in case a song is already playing
        self._sync_playing_state()

    def _on_unmap(self, *args):
        """Called when this widget is hidden or removed from screen."""
        if utils.player_object and self._song_changed_handler is not None:
            utils.player_object.disconnect(self._song_changed_handler)
            self._song_changed_handler = None
        # Clear the highlight so it's not stale when we come back
        if self._last_playing_id and self._last_playing_id in self._track_widget_map:
            self._track_widget_map[self._last_playing_id].remove_css_class("playing-track")
        self._last_playing_id = None

    def _sync_playing_state(self):
        """Apply highlight to whichever track is currently playing, if it's in this list."""
        if not utils.player_object or not utils.player_object.playing_track:
            return
        playing_id = utils.player_object.playing_track.id
        if playing_id in self._track_widget_map:
            self._track_widget_map[playing_id].add_css_class("playing-track")
            self._last_playing_id = playing_id

    def set_more_function(self, function: Callable) -> None:
        """Set the function to fetch more items

        Args:
            function: the function"""
        self.get_function = function
        self.more_button.set_visible(True)

    def set_tracks_list(self, tracks_list: List[Track]) -> None:
        self.tracks = tracks_list

        self._add_tracks()

    def _add_tracks(self):
        for index, track in enumerate(self.tracks):
            listing = HTGenericTrackWidget(track)
            self.disconnectables.append(listing)
            listing.set_name(str(index))
            self._track_widget_map[track.id] = listing
            self.tracks_list_box.append(listing)

        if utils.player_object and utils.player_object.playing_track:
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

    def _on_more_clicked(self, *args) -> None:
        from ..pages import HTFromFunctionPage

        page = HTFromFunctionPage(self.title_name)
        page.set_function(self.get_function)
        page.load()
        utils.navigation_view.push(page)

    def _on_tracks_row_selected(self, list_box, row) -> None:
        index = int(row.get_name())

        utils.player_object.play_this(self.tracks, index)
