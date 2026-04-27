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

from gi.repository import Adw, GLib, Gtk, Gio, Gdk

from tidalapi import PlaylistCreator
from tidalapi.album import Album
from tidalapi.artist import Artist, DEFAULT_ARTIST_IMG
from tidalapi.mix import Mix, MixV2
from tidalapi.playlist import Playlist, UserPlaylist
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

    image_overlay = Gtk.Template.Child()
    image = Gtk.Template.Child()
    play_revealer = Gtk.Template.Child()
    play_overlay_button = Gtk.Template.Child()
    click_gesture = Gtk.Template.Child()
    title_label = Gtk.Template.Child()
    detail_label = Gtk.Template.Child()
    card_menu = Gtk.Template.Child()
    _context_menu_button = Gtk.Template.Child()

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

        self._menu_activated = False
        self._action_group = Gio.SimpleActionGroup()
        self.insert_action_group("cardwidget", self._action_group)

        self._popover = Gtk.PopoverMenu.new_from_model(self.card_menu)
        self._popover.set_parent(self)
        self._popover.set_has_arrow(False)

        right_click = Gtk.GestureClick.new()
        right_click.set_button(3)
        right_click.connect("pressed", self._on_right_click)
        self.add_controller(right_click)

        motion_controller = Gtk.EventControllerMotion()
        motion_controller.connect("enter", self._on_hover_enter)
        motion_controller.connect("leave", self._on_hover_leave)
        self.image_overlay.add_controller(motion_controller)

        self.play_overlay_button.connect("clicked", self._on_play_overlay_clicked)

        self._song_changed_handler: int | None = None
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

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
            self.image_overlay.set_child(placeholder)
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

    def _on_menu_activate(self):
        if self._menu_activated:
            return
        self._menu_activated = True

        if isinstance(self.item, Album):
            self.card_menu.append(_("Go to album"), f"win.push-album-page::{self.item.id}")
        elif isinstance(self.item, Artist):
            self.card_menu.append(_("Go to artist"), f"win.push-artist-page::{self.item.id}")
        elif isinstance(self.item, Playlist):
            self.card_menu.append(_("Go to playlist"), f"win.push-playlist-page::{self.item.id}")

            add_to_playlist_submenu = Gio.Menu.new()
            for index, playlist in enumerate(utils.user_playlists):
                item = Gio.MenuItem.new()
                item.set_label(playlist.name)
                item.set_action_and_target_value(
                    "cardwidget.add-to-playlist", GLib.Variant.new_int16(index)
                )
                add_to_playlist_submenu.append_item(item)

            add_to_playlist_action = Gio.SimpleAction.new("add-to-playlist", GLib.VariantType.new("n"))
            add_to_playlist_action.connect("activate", self._add_to_playlist)
            self._action_group.add_action(add_to_playlist_action)

            self.card_menu.append_submenu(_("Add to a playlist"), add_to_playlist_submenu)
        elif isinstance(self.item, (Mix, MixV2)):
            self.card_menu.append(_("Go to mix"), f"win.push-mix-page::{self.item.id}")
        elif isinstance(self.item, Track):
            self.card_menu.append(_("Go to album"), f"win.push-album-page::{self.item.album.id}")
            self.card_menu.append(_("Go to track radio"), f"win.push-track-radio-page::{self.item.id}")

            play_next = Gio.SimpleAction.new("play-next", None)
            play_next.connect("activate", lambda *_: utils.player_object.add_next(self.item))
            self._action_group.add_action(play_next)
            self.card_menu.append(_("Play next"), "cardwidget.play-next")

            add_to_queue = Gio.SimpleAction.new("add-to-queue", None)
            add_to_queue.connect("activate", lambda *_: utils.player_object.add_to_queue(self.item))
            self._action_group.add_action(add_to_queue)
            self.card_menu.append(_("Add to queue"), "cardwidget.add-to-queue")

            add_to_playlist_submenu = Gio.Menu.new()
            for index, playlist in enumerate(utils.user_playlists):
                item = Gio.MenuItem.new()
                item.set_label(playlist.name)
                item.set_action_and_target_value(
                    "cardwidget.add-to-playlist", GLib.Variant.new_int16(index)
                )
                add_to_playlist_submenu.append_item(item)

            add_to_playlist_action = Gio.SimpleAction.new("add-to-playlist", GLib.VariantType.new("n"))
            add_to_playlist_action.connect("activate", self._add_to_playlist)
            self._action_group.add_action(add_to_playlist_action)

            self.card_menu.append_submenu(_("Add to a playlist"), add_to_playlist_submenu)

        if not isinstance(self.item, Artist):
            add_to_col = Gio.SimpleAction.new("add-to-collection", None)
            add_to_col.connect("activate", lambda *_: threading.Thread(
                target=utils.th_add_to_my_collection, args=(None, self.item)
            ).start())
            self._action_group.add_action(add_to_col)
            self.card_menu.append(_("Add to my collection"), "cardwidget.add-to-collection")

        if isinstance(self.item, (Track, Album, Artist, Playlist)):
            copy_share = Gio.SimpleAction.new("copy-share-url", None)
            copy_share.connect("activate", lambda *_: utils.share_this(self.item))
            self._action_group.add_action(copy_share)
            self.card_menu.append(_("Copy share URL"), "cardwidget.copy-share-url")

    def _on_right_click(self, gesture, n_press, x, y) -> None:
        if isinstance(self.item, PageItem):
            return
        self._on_menu_activate()
        rect = Gdk.Rectangle()
        rect.x = int(x) + 80
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()

    def _add_to_playlist(self, action, parameter):
        playlist_index = parameter.get_int16()
        selected_playlist = utils.user_playlists[playlist_index]
        if isinstance(selected_playlist, UserPlaylist):
            if isinstance(self.item, Playlist):
                def _th():
                    tracks = self.item.tracks()
                    selected_playlist.add([t.id for t in tracks])

                threading.Thread(target=_th).start()
            else:
                selected_playlist.add([self.item.id])

    def _on_hover_enter(self, *args) -> None:
        self.play_revealer.set_reveal_child(True)

    def _on_hover_leave(self, *args) -> None:
        self.play_revealer.set_reveal_child(False)

    def _on_play_overlay_clicked(self, *args) -> None:
        """Start playback of this card's item, respecting current shuffle state."""
        player = utils.player_object
        if not player:
            return

        item = self.item
        if isinstance(item, PageItem):
            return

        threading.Thread(target=player.play_this, args=(item,)).start()

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

    def _on_map(self, *args) -> None:
        if utils.player_object and self._song_changed_handler is None:
            self._song_changed_handler = utils.player_object.connect(
                "song-changed", self._on_song_changed
            )
        self._sync_playing_state()

    def _on_unmap(self, *args) -> None:
        if utils.player_object and self._song_changed_handler is not None:
            utils.player_object.disconnect(self._song_changed_handler)
            self._song_changed_handler = None
        self.remove_css_class("playing-card")

    def _sync_playing_state(self) -> None:
        if not utils.player_object or not utils.player_object.playing_track:
            return
        if self._is_currently_playing():
            self.add_css_class("playing-card")

    def _on_song_changed(self, player) -> None:
        if self._is_currently_playing():
            self.add_css_class("playing-card")
        else:
            self.remove_css_class("playing-card")

    def _is_currently_playing(self) -> bool:
        player = utils.player_object
        if not player or not player.playing_track:
            return False
        track = player.playing_track
        if isinstance(self.item, Track):
            return self.item.id == track.id
        if isinstance(self.item, Album) and track.album:
            return self.item.id == track.album.id
        if isinstance(self.item, Playlist):
            cmap = player.current_mix_album_playlist
            return isinstance(cmap, Playlist) and cmap.id == self.item.id
        if isinstance(self.item, (Mix, MixV2)):
            cmap = player.current_mix_album_playlist
            return isinstance(cmap, (Mix, MixV2)) and cmap.id == self.item.id
        if isinstance(self.item, Artist):
            cmap = player.current_mix_album_playlist
            return isinstance(cmap, Artist) and cmap.id == self.item.id
        return False
