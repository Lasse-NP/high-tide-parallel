# collection_page.py
#
# Copyright 2024 Nokse22
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

from gettext import gettext as _

from ..lib import utils
from .page import Page
from ..widgets.carousel_widget import HTCarouselWidget

from tidalapi.media import Track
from tidalapi.album import Album
from tidalapi.artist import Artist
from tidalapi.mix import Mix
from tidalapi.playlist import Playlist


class HTCollectionPage(Page):
    """A page to display the collection (the user's library)"""

    __gtype_name__ = "HTCollectionPage"

    def _load_async(self) -> None: ...

    def _load_finish(self) -> None:
        self.set_tag("collection")
        self.set_title(_("Collection"))

        self._build_carousels()

        self.connect("showing", self._on_showing)

    def _on_showing(self, *args) -> None:
        self._rebuild_all()

    def refresh(self, item=None, removed=True) -> None:
        """Re-fetch favourites from TIDAL and rebuild a carousel."""
        self._rebuild(item, removed)

    def _rebuild(self, item, removed) -> None:
        type_to_title = {
            Track: _("Tracks"),
            Album: _("Albums"),
            Artist: _("Artists"),
            Mix: _("My Mixes and Radios"),
            Playlist: _("Playlists"),
        }

        type_to_items = {
            Track: utils.favourite_tracks,
            Album: utils.favourite_albums,
            Artist: utils.favourite_artists,
            Mix: utils.favourite_mixes,
            Playlist: utils.playlist_and_favorite_playlists,
        }

        if item is None or type(item) not in type_to_title:
            self._rebuild_all()
            return

        title = type_to_title[type(item)]

        child = self.content.get_first_child()
        while child:
            if isinstance(child, HTCarouselWidget) and child.title == title:
                print(f"Found carousel '{title}', removed={removed}")
                if removed:
                    child.remove_item_by_id(item.id)
                else:
                    child.update_items(type_to_items[type(item)])
                return
            child = child.get_next_sibling()
        print(f"Carousel '{title}' not found!")

    def _rebuild_all(self) -> None:
        child = self.content.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.content.remove(child)
            child = next_child
        self._build_carousels()

    def _build_carousels(self) -> None:
        self.new_carousel_for(_("My Mixes and Radios"), utils.favourite_mixes)
        self.new_carousel_for(_("Playlists"), utils.playlist_and_favorite_playlists)
        self.new_carousel_for(_("Albums"), utils.favourite_albums)
        self.new_carousel_for(_("Tracks"), utils.favourite_tracks)
        self.new_carousel_for(_("Artists"), utils.favourite_artists)
