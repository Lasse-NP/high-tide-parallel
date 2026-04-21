# card_widget.py
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
import threading
from gettext import gettext as _
from typing import Union, cast

from gi.repository import Adw, GLib, Gtk

from tidalapi import PlaylistCreator
from tidalapi.album import Album
from tidalapi.artist import Artist, DEFAULT_ARTIST_IMG
from tidalapi.mix import Mix, MixV2
from tidalapi.playlist import Playlist
from tidalapi.media import Track
from tidalapi.page import PageItem

from ..widgets.default_image_widget import HTDefaultImageWidget
from ..disconnectable_iface import IDisconnectable
from ..lib import utils


@Gtk.Template(resource_path="/io/github/nokse22/high-tide/ui/widgets/card_widget.ui")
class HTCardWidget(Adw.BreakpointBin, IDisconnectable):
    """A card widget that adapts to display different types of TIDAL content.

    This widget automatically configures itself based on the type of TIDAL item
    it receives (Track, Album, Artist, Playlist, Mix) and displays appropriate
    information and imagery. It handles click events to navigate to detail pages
    or start playback for tracks.
    """

    __gtype_name__ = "HTCardWidget"

    image = Gtk.Template.Child()
    click_gesture = Gtk.Template.Child()
    title_label = Gtk.Template.Child()
    detail_label = Gtk.Template.Child()

    track_artist_label = Gtk.Template.Child()

    def __init__(self, item: Union[Track, Album, Artist, Playlist, Mix, MixV2]) -> None:
        """Initialize the card widget with a TIDAL item.

        Args:
            item: A TIDAL object (Track, Album, Artist, Playlist, or Mix) to display
        """
        IDisconnectable.__init__(self)
        super().__init__()

        self.signals.append(
            (
                self.track_artist_label,
                self.track_artist_label.connect("activate-link", utils.open_uri),
            )
        )

        self.signals.append(
            (
                self.click_gesture,
                self.click_gesture.connect("released", self._on_click),
            )
        )

        self.item: Union[Track, Album, Artist, Playlist, Mix, MixV2] = item

        self.action: str | None = None

        self._populate()

        self.set_cursor_from_name("pointer")

    def _populate(self):
        if isinstance(self.item, MixV2) or isinstance(self.item, Mix):
            self._make_mix_card()
            self.action = "win.push-mix-page"
        elif isinstance(self.item, Album):
            self._make_album_card()
            self.action = "win.push-album-page"
        elif isinstance(self.item, Playlist):
            self._make_playlist_card()
            self.action = "win.push-playlist-page"
        elif isinstance(self.item, Artist):
            self._make_artist_card()
            self.action = "win.push-artist-page"
        elif isinstance(self.item, Track):
            self._make_track_card()
        elif isinstance(self.item, PageItem):
            self._make_page_item_card()

    def _make_track_card(self) -> None:
        """Configure the card to display a Track item"""
        specific_track = cast(Track, self.item)
        self.title_label.set_label(specific_track.name)
        self.title_label.set_tooltip_text(specific_track.name)
        self.track_artist_label.set_artists(specific_track.artists)
        self.track_artist_label.set_label(
            _("Track by {}").format(self.track_artist_label.get_label())
        )
        self.detail_label.set_visible(False)

        threading.Thread(target=utils.add_image, args=(self.image, specific_track.album)).start()

    def _make_mix_card(self) -> None:
        """Configure the card to display a Mix item"""
        specific_mix = cast(Mix, self.item)
        self.title_label.set_label(specific_mix.title)
        self.title_label.set_tooltip_text(specific_mix.title)
        self.detail_label.set_label(specific_mix.sub_title)
        self.track_artist_label.set_visible(False)

        threading.Thread(target=utils.add_image, args=(self.image, self.item)).start()

    def _make_album_card(self) -> None:
        """Configure the card to display an Album item"""
        specific_album = cast(Album, self.item)
        self.title_label.set_label(specific_album.name)
        self.title_label.set_tooltip_text(specific_album.name)
        self.track_artist_label.set_artists(specific_album.artists)
        self.detail_label.set_visible(False)

        threading.Thread(target=utils.add_image, args=(self.image, self.item)).start()

    def _make_playlist_card(self) -> None:
        """Configure the card to display a Playlist item"""
        specific_playlist = cast(Playlist, self.item)
        self.title_label.set_label(specific_playlist.name)
        self.title_label.set_tooltip_text(specific_playlist.name)
        self.track_artist_label.set_visible(False)

        creator_name = "TIDAL"
        if specific_playlist.creator is not None:
            if isinstance(specific_playlist.creator, PlaylistCreator) and specific_playlist.creator.name is not None:
                creator_name = specific_playlist.creator.name
        self.detail_label.set_label(_("By {}").format(creator_name))

        threading.Thread(target=utils.add_image, args=(self.image, self.item)).start()

    def _make_artist_card(self) -> None:
        """Configure the card to display an Artist item"""
        specific_artist = cast(Artist, self.item)
        self.title_label.set_label(specific_artist.name)
        self.title_label.set_tooltip_text(specific_artist.name)
        self.detail_label.set_label(_("Artist"))
        self.track_artist_label.set_visible(False)

        if specific_artist.picture == DEFAULT_ARTIST_IMG:
            name = specific_artist.name if specific_artist.name is not None else "Unknown"
            item_id = specific_artist.id if specific_artist.id is not None else 0
            placeholder = HTDefaultImageWidget(name, item_id, size=155)
            placeholder.add_css_class("default-image-box")
            parent = self.image.get_parent()
            parent.remove(self.image)
            parent.prepend(placeholder)
            utils.setup_artist_image(self.item, placeholder)
        else:
            threading.Thread(target=utils.add_image, args=(self.image, self.item)).start()

    def _make_page_item_card(self) -> None:
        """Configure the card to display a PageItem"""
        assert isinstance(self.item, PageItem)
        page_item = self.item

        def _get_item():
            if page_item.type == "PLAYLIST":
                self.item = utils.get_playlist(page_item.artifact_id)
            elif page_item.type == "TRACK":
                self.item = utils.get_track(page_item.artifact_id)
            elif page_item.type == "ARTIST":
                self.item = utils.get_artist(page_item.artifact_id)
            elif page_item.type == "ALBUM":
                self.item = utils.get_album(page_item.artifact_id)

            GLib.idle_add(self._populate)

        threading.Thread(target=_get_item).start()

    def _on_click(self, *_) -> None:
        """Handle click events on the card.

        For non-track items, activates the appropriate navigation action to show
        the detail page. For track items, starts playback immediately.
        """
        if self.action:
            self.activate_action(self.action, GLib.Variant("s", str(self.item.id)))
        elif isinstance(self.item, Track):
            if utils.player_object:
                utils.player_object.play_this(self.item)
        elif isinstance(self.item, PageItem) and self.item.type == "TRACK":
            page_item = self.item
            def _get():
                if utils.player_object:
                    resolved = page_item.get()
                    if isinstance(resolved, Track):
                        utils.player_object.play_this(resolved)

            threading.Thread(target=_get).start()
