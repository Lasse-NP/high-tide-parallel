# generic_track_widget.py
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

from gi.repository import Gio, GLib, GObject, Gtk, Gdk
from tidalapi.playlist import UserPlaylist

from ..disconnectable_iface import IDisconnectable
from ..lib import utils

import logging

logger = logging.getLogger(__name__)


@Gtk.Template(
    resource_path="/io/github/nokse22/high-tide/ui/widgets/generic_track_widget.ui"
)
class HTGenericTrackWidget(Gtk.ListBoxRow, IDisconnectable):
    """A widget for displaying a single track with playback and menu options.

    This widget shows track information including title, artist, album, duration,
    and cover art. It provides context menu actions for playing, adding to queue,
    adding to playlists, and other track-related operations.
    """

    __gtype_name__ = "HTGenericTrackWidget"

    image_overlay = Gtk.Template.Child()
    image = Gtk.Template.Child()
    play_revealer = Gtk.Template.Child()
    play_overlay_button = Gtk.Template.Child()
    track_progress_bar = Gtk.Template.Child()

    track_title_label = Gtk.Template.Child()
    track_duration_label = Gtk.Template.Child()
    playlists_submenu = Gtk.Template.Child()
    _grid = Gtk.Template.Child()
    explicit_label = Gtk.Template.Child()

    artist_label = Gtk.Template.Child()
    artist_label_2 = Gtk.Template.Child()
    track_album_label = Gtk.Template.Child()

    menu_button = Gtk.Template.Child()
    track_menu = Gtk.Template.Child()

    index = GObject.Property(type=int, default=0)

    def __init__(self, track, playlist=None):
        IDisconnectable.__init__(self)
        super().__init__()

        self.menu_activated = False
        self.track = track
        self.playlist = playlist
        self.is_owner = self._check_ownership()

        self.signals.append(
            (
                self.artist_label,
                self.artist_label.connect("activate-link", utils.open_uri),
            )
        )
        self.signals.append(
            (
                self.artist_label_2,
                self.artist_label_2.connect("activate-link", utils.open_uri),
            )
        )
        self.signals.append(
            (
                self.track_album_label,
                self.track_album_label.connect("activate-link", utils.open_uri),
            )
        )

        self.signals.append(
            (
                self.menu_button,
                self.menu_button.connect("notify::active", self._on_menu_activate),
            )
        )

        self.track_album_label.set_album(self.track.album)
        self.track_title_label.set_label(
            self.track.full_name
            if hasattr(self.track, "full_name")
            else self.track.name
        )
        self.artist_label.set_artists(self.track.artists)

        self.explicit_label.set_visible(self.track.explicit)

        self.track_duration_label.set_label(utils.pretty_duration(self.track.duration))

        if not self.track.available:
            self.set_activatable(False)
            self.set_sensitive(False)

        threading.Thread(
            target=utils.add_image, args=(self.image, self.track.album)
        ).start()

        self.action_group = Gio.SimpleActionGroup()
        self.insert_action_group("trackwidget", self.action_group)

        motion_controller = Gtk.EventControllerMotion()
        motion_controller.connect("enter", self._on_hover_enter)
        motion_controller.connect("leave", self._on_hover_leave)
        self.add_controller(motion_controller)
        self.play_overlay_button.connect("clicked", self._on_play_clicked)

        self._popover = Gtk.PopoverMenu.new_from_model(self.track_menu)
        self._popover.set_parent(self)
        self._popover.set_has_arrow(False)

        right_click = Gtk.GestureClick.new()
        right_click.set_button(3)
        right_click.connect("pressed", self._on_right_click)
        self.add_controller(right_click)

        if self.is_owner:
            drag_source = Gtk.DragSource()
            drag_source.set_actions(Gdk.DragAction.MOVE)
            drag_source.connect("prepare", self._on_drag_prepare)
            drag_source.connect("drag-begin", self._on_drag_begin)
            self.add_controller(drag_source)

        self.set_cursor_from_name("pointer")

    def _check_ownership(self) -> bool:
        if not isinstance(self.playlist, UserPlaylist):
            return False
        if not utils.session.user:
            return False
        return bool(self.playlist.creator and self.playlist.creator.id == utils.session.user.id)

    def _on_right_click(self, gesture, n_press, x, y) -> None:
        self._on_menu_activate()  # ensure menu items are populated
        rect = Gdk.Rectangle()
        rect.x = int(x) + 80
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()

    def _on_menu_activate(self, *args):
        if self.menu_activated:
            return
        self.menu_activated = True

        if self.is_owner:
            entries = [(_("Remove from playlist"), "remove-from-playlist", self._remove_from_playlist),
                       (_("Add to my collection"), "add-to-my-collection", self._th_add_to_my_collection)]
        else:
            entries = [
                (_("Add to my collection"), "add-to-my-collection", self._th_add_to_my_collection),
            ]

        entries += [
            (_("Go to album"), f"win.push-album-page::{self.track.album.id}", None),
            (_("Go to track radio"), f"win.push-track-radio-page::{self.track.id}", None),
            (_("Play next"), "play-next", self._play_next),
            (_("Add to queue"), "add-to-queue", self._add_to_queue),
            (_("Copy share url"), "copy-share-url", self._copy_share_url),
        ]

        for label, action_name, callback in entries:
            if callback is not None:
                action = Gio.SimpleAction.new(action_name, None)
                self.signals.append((action, action.connect("activate", callback)))
                self.action_group.add_action(action)
                self.track_menu.append(label, f"trackwidget.{action_name}")
            else:
                self.track_menu.append(label, action_name)

        add_to_playlist_action = Gio.SimpleAction.new(
            "add-to-playlist", GLib.VariantType.new("n")
        )
        self.signals.append(
            (add_to_playlist_action, add_to_playlist_action.connect("activate", self._add_to_playlist))
        )
        self.action_group.add_action(add_to_playlist_action)

        for index, playlist in enumerate(utils.user_playlists):
            item = Gio.MenuItem.new()
            item.set_label(playlist.name)
            item.set_action_and_target_value(
                "trackwidget.add-to-playlist", GLib.Variant.new_int16(index)
            )
            self.playlists_submenu.insert_item(index, item)

    def _play_next(self, *args):
        utils.player_object.add_next(self.track)

    def _add_to_queue(self, *args):
        utils.player_object.add_to_queue(self.track)

    def _th_add_to_my_collection(self, *args):
        threading.Thread(target=self.th_add_to_my_collection, args=()).start()

    def th_add_to_my_collection(self):
        utils.session.user.favorites.add_track(self.track.id)

    def _remove_from_playlist(self, *args):
        def _th():
            self.playlist.remove_by_indices([self.get_index()])
            GLib.idle_add(self.get_parent().remove, self)

        threading.Thread(target=_th).start()

    def _add_to_playlist(self, action, parameter):
        playlist_index = parameter.get_int16()
        selected_playlist = utils.user_playlists[playlist_index]

        if isinstance(selected_playlist, UserPlaylist):
            selected_playlist.add([self.track.id])

            logger.info(f"Added to playlist: {selected_playlist.name}")

    def _copy_share_url(self, *args):
        utils.share_this(self.track)

    def add_css_class(self, css_class: str) -> None:
        super().add_css_class(css_class)
        if css_class == "playing-track":
            self.play_revealer.set_reveal_child(True)
            self.track_progress_bar.set_visible(True)
            self._slider_handler = utils.player_object.connect(
                "update-slider", self._on_update_slider
            )

    def remove_css_class(self, css_class: str) -> None:
        super().remove_css_class(css_class)
        if css_class == "playing-track":
            self.play_revealer.set_reveal_child(False)
            self.track_progress_bar.set_visible(False)
            self.track_progress_bar.set_size_request(0, -1)
            if hasattr(self, "_slider_handler") and self._slider_handler:
                utils.player_object.disconnect(self._slider_handler)
                self._slider_handler = None

    def _on_update_slider(self, player) -> None:
        duration = player.query_duration()
        position = player.query_position(default=0)
        if duration and duration > 0:
            fraction = position / duration
            total_width = self.get_allocated_width()
            width = min(int(total_width * fraction), total_width)
            self.track_progress_bar.set_size_request(width, -1)

    def _on_hover_enter(self, *args) -> None:
        self.play_revealer.set_reveal_child(True)

    def _on_hover_leave(self, *args) -> None:
        if self.has_css_class("playing-track"):
            return
        self.play_revealer.set_reveal_child(False)

    def _on_play_clicked(self, *args) -> None:
        self.activate()

    def _on_drag_prepare(self, source, x, y):
        return Gdk.ContentProvider.new_for_value(self.get_index())

    def _on_drag_begin(self, source, drag):
        paintable = Gtk.WidgetPaintable.new(self)
        source.set_icon(paintable, self.get_width() // 2, self.get_height() // 2)
