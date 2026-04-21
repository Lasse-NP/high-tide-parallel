# window.py
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
import math
import threading
from gettext import gettext as _
from typing import Callable
from datetime import datetime, timezone

import cairo
import tidalapi
import tidalapi.user as tidal_user
from gi.repository import Adw, Gio, GLib, GObject, Gst, Gtk, Xdp
from tidalapi.media import Quality

from .lib import HTCache, PlayerObject, RepeatType, SecretStore, utils
from .login import LoginDialog
from .mpris import MPRIS
from .pages import (HTAlbumPage, HTArtistPage, HTCollectionPage, HTExplorePage,
                    HTGenericPage, HTMixPage, HTNotLoggedInPage,
                    HTPlaylistPage)
from .widgets import (HTGenericTrackWidget, HTLinkLabelWidget, HTLyricsWidget,
                      HTQueueWidget, HTQueueItemWidget)

import logging
logger = logging.getLogger(__name__)

# from .new_playlist import NewPlaylistWindow

GObject.type_register(HTGenericTrackWidget)
GObject.type_register(HTQueueItemWidget)
GObject.type_register(HTLinkLabelWidget)
GObject.type_register(HTQueueWidget)
GObject.type_register(HTLyricsWidget)


@Gtk.Template(resource_path="/io/github/nokse22/high-tide/ui/window.ui")
class HighTideWindow(Adw.ApplicationWindow):
    __gtype_name__ = "HighTideWindow"

    progress_bar = Gtk.Template.Child()
    duration_label = Gtk.Template.Child()
    time_played_label = Gtk.Template.Child()
    shuffle_button = Gtk.Template.Child()
    navigation_view = Gtk.Template.Child()
    play_button = Gtk.Template.Child()
    small_progress_bar = Gtk.Template.Child()
    song_title_label = Gtk.Template.Child()
    playing_track_picture = Gtk.Template.Child()
    playing_track_image = Gtk.Template.Child()
    artist_label = Gtk.Template.Child()
    miniplayer_artist_label = Gtk.Template.Child()
    volume_button = Gtk.Template.Child()
    in_my_collection_button = Gtk.Template.Child()
    explicit_label = Gtk.Template.Child()
    queue_widget = Gtk.Template.Child()
    lyrics_widget = Gtk.Template.Child()
    repeat_button = Gtk.Template.Child()
    home_button = Gtk.Template.Child()
    explore_button = Gtk.Template.Child()
    collection_button = Gtk.Template.Child()
    player_lyrics_queue = Gtk.Template.Child()
    navigation_buttons = Gtk.Template.Child()
    buffer_spinner = Gtk.Template.Child()
    quality_label = Gtk.Template.Child()
    toast_overlay = Gtk.Template.Child()
    playing_track_widget = Gtk.Template.Child()
    player_headerbar = Gtk.Template.Child()
    sidebar_stack = Gtk.Template.Child()
    go_next_button = Gtk.Template.Child()
    go_prev_button = Gtk.Template.Child()
    track_radio_button = Gtk.Template.Child()
    album_button = Gtk.Template.Child()
    copy_share_link = Gtk.Template.Child()

    app_id_dialog = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.settings = Gio.Settings.new("io.github.nokse22.high-tide")

        self.settings.bind(
            "window-width", self, "default-width", Gio.SettingsBindFlags.DEFAULT
        )
        self.settings.bind(
            "window-height", self, "default-height", Gio.SettingsBindFlags.DEFAULT
        )
        self.settings.bind(
            "run-background", self, "hide-on-close", Gio.SettingsBindFlags.DEFAULT
        )

        self.create_action_with_target(
            "push-artist-page", GLib.VariantType.new("s"), self.on_push_artist_page
        )

        self.create_action_with_target(
            "push-album-page", GLib.VariantType.new("s"), self.on_push_album_page
        )

        self.create_action_with_target(
            "push-playlist-page", GLib.VariantType.new("s"), self.on_push_playlist_page
        )

        self.create_action_with_target(
            "push-mix-page", GLib.VariantType.new("s"), self.on_push_mix_page
        )

        self.create_action_with_target(
            "push-track-radio-page",
            GLib.VariantType.new("s"),
            self.on_push_track_radio_page,
        )

        self.create_action_with_target(
            "push-artist-radio-page",
            GLib.VariantType.new("s"),
            self.on_push_artist_radio_page,
        )

        # self.create_action_with_target(
        #     'play-next',
        #     GLib.VariantType.new("s"),
        #     self.on_play_next)

        self.player_object = PlayerObject(
            self.settings.get_int("preferred-sink"),
            self.settings.get_string("alsa-device"),
            self.settings.get_boolean("normalize"),
            self.settings.get_boolean("quadratic-volume"),
        )
        utils.player_object = self.player_object
        self.player_object.set_discord_rpc(self.settings.get_boolean("discord-rpc"))

        self.volume_button.set_value(
            self.settings.get_int("last-volume") / 10
        )

        self.player_object.connect("notify::shuffle", self.on_shuffle_changed)
        self.player_object.connect("update-slider", self.update_slider)
        self.player_object.connect("song-changed", self.on_song_changed)
        self.player_object.connect("song-added-to-queue", self.on_song_added_to_queue)
        self.player_object.connect("notify::playing", self.update_controls)
        self.player_object.connect("buffering", self.on_song_buffering)
        self.player_object.connect("notify::repeat-type", self.update_repeat_button)
        self.player_object.connect(
            "notify::can-go-next",
            lambda *_: self.go_next_button.set_sensitive(
                self.player_object.can_go_next
            ),
        )
        self.player_object.connect(
            "notify::can-go-prev",
            lambda *_: self.go_prev_button.set_sensitive(
                self.player_object.can_go_prev
            ),
        )

        self._anim_angle = 0.0
        self._anim_timer = None
        self._anim_color = (1.0, 1.0, 1.0)
        self.buffer_spinner.set_draw_func(self._draw_buffer_animation)

        self.player_object.repeat_type = self.settings.get_int("repeat")
        if self.player_object.repeat_type == RepeatType.NONE:
            self.repeat_button.set_icon_name("media-playlist-consecutive-symbolic")
        elif self.player_object.repeat_type == RepeatType.LIST:
            self.repeat_button.set_icon_name("media-playlist-repeat-symbolic")
        elif self.player_object.repeat_type == RepeatType.SONG:
            self.repeat_button.set_icon_name("playlist-repeat-song-symbolic")

        self.artist_label.connect("activate-link", utils.open_uri)
        self.miniplayer_artist_label.connect("activate-link", utils.open_uri)

        self.session = utils.create_tidal_session()

        utils.session = self.session
        utils.navigation_view = self.navigation_view
        utils.toast_overlay = self.toast_overlay
        utils.cache = HTCache(self.session)

        self.user = self.session.user

        self.select_quality(self.settings.get_int("quality"))

        self.current_mix = None
        self.player_object.current_song_index = 0
        self.previous_fraction = 0
        self.favourite_playlists = []
        self.my_playlists = []

        self.image_canc = None

        self.queued_uri = None
        self.is_logged_in = False
        self._collection_page = None

        self.videoplayer = Gtk.MediaFile.new()

        self.video_covers_enabled = self.settings.get_boolean("video-covers")
        self.in_background = False

        self._header_css_provider = Gtk.CssProvider()
        self.playing_track_widget.get_style_context().add_provider(
            self._header_css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.queue_widget_updated = False

        threading.Thread(target=self.th_login, args=()).start()

        MPRIS(self.player_object)

        self.portal = Xdp.Portal()

        self.portal.set_background_status(_("Playing Music"))

        self.connect("notify::is-active", self.stop_video_in_background)

        if not self.settings.get_boolean("app-id-change-understood"):
            self.app_id_dialog.present(self)

        if self.get_application().dev_tooltips:
            self._apply_dev_tooltips(self)

    @Gtk.Template.Callback("on_app_id_response_cb")
    def on_app_id_response_cb(self, dialog, response):
        self.app_id_dialog.close()

    @Gtk.Template.Callback("on_app_id_check_toggled_cb")
    def on_app_id_check_toggled_cb(self, check_btn):
        self.app_id_dialog.set_response_enabled("close", check_btn.get_active())

    @Gtk.Template.Callback("on_app_id_closed_cb")
    def on_app_id_closed_cb(self, dialog):
        self.settings.set_boolean("app-id-change-understood", True)

    #
    #   LOGIN
    #

    def new_login(self):
        """Open a new login dialog for user authentication"""

        login_dialog = LoginDialog(self, self.session)
        login_dialog.present(self)

    def th_login(self):
        self.secret_store = SecretStore(self.session)
        try:
            expiry_str = self.secret_store.token_dictionary.get("expiry-time", "")
            expiry = datetime.fromisoformat(expiry_str) if expiry_str else None
            token_valid = expiry and datetime.now() < expiry

            if token_valid:
                self.session.token_type = self.secret_store.token_dictionary["token-type"]
                self.session.access_token = self.secret_store.token_dictionary["access-token"]
                self.session.refresh_token = self.secret_store.token_dictionary["refresh-token"]
                self.session.expiry_time = expiry
                self.session.session_id = self.secret_store.token_dictionary.get("session-id")
                self.session.country_code = self.secret_store.token_dictionary.get("country-code")
                self.session.locale = "en_US"
                user_id = self.secret_store.token_dictionary.get("user-id")
                if user_id:
                    self.session.user = tidal_user.User(self.session, user_id=int(user_id)).factory()
            else:
                self.session.load_oauth_session(
                    self.secret_store.token_dictionary["token-type"],
                    self.secret_store.token_dictionary["access-token"],
                    self.secret_store.token_dictionary["refresh-token"],
                    self.secret_store.token_dictionary["expiry-time"],
                )
                self.secret_store.save()
        except Exception:
            logger.exception("Error while logging in!")
            GLib.idle_add(self.on_login_failed)
            return

        GLib.idle_add(self.on_logged_in)
        threading.Thread(target=self._th_load_favourites, daemon=True).start()

    def _th_load_favourites(self):
        utils.get_favourites()
        GLib.idle_add(self._on_favourites_loaded)

    def _on_favourites_loaded(self):
        if self._collection_page:
            self._collection_page.rebuild_if_changed()

    def logout(self):
        """Log out the current user and return to login screen.

        Clears stored authentication tokens and navigates back to the
        not logged in page.
        """
        self.secret_store.clear()

        page = HTNotLoggedInPage().load()
        self.navigation_view.replace([page])

    def on_logged_in(self):
        """Handle successful user login"""
        logger.info("logged in")


        page = HTGenericPage.new_from_function(utils.session.home).load()
        page.set_tag("home")
        self.navigation_view.replace([page])
        self.player_lyrics_queue.set_sensitive(True)
        self.navigation_buttons.set_sensitive(True)

        threading.Thread(target=self.th_set_last_playing_song, args=()).start()
        self._collection_page = HTCollectionPage().load()

        self.is_logged_in = True

        if self.queued_uri:
            utils.open_tidal_uri(self.queued_uri)

    def on_login_failed(self):
        """Handle failed login attempts"""
        logger.error("login failed")

        page = HTNotLoggedInPage().load()
        self.navigation_view.replace([page])

    def th_set_last_playing_song(self):
        index = self.settings.get_int("last-playing-index")
        thing_id = self.settings.get_string("last-playing-thing-id")
        thing_type = self.settings.get_string("last-playing-thing-type")

        logger.info(f"Last playing: {thing_id} of type {thing_type} index: {index}")

        thing = None

        try:
            if thing_type == "mix":
                thing = self.session.mix(thing_id)
            elif thing_type == "album":
                thing = self.session.album(thing_id)
            elif thing_type == "playlist":
                thing = self.session.playlist(thing_id)
            elif thing_type == "track":
                thing = self.session.track(thing_id)
        except Exception:
            logger.exception("Error while setting last played song")

        if thing is None:
            return

        self.player_object.play_this(thing, index)

        self.player_object.pause()

    #
    #   UPDATES UI
    #

    def on_song_changed(self, *args):
        """Handle song change events from the player.

        Updates the UI elements when the currently playing song changes,
        including album art, track information, and video covers.
        """
        logger.info("song changed")
        album = self.player_object.song_album
        track = self.player_object.playing_track

        if track is None:
            return

        track_name = track.full_name if hasattr(track, "full_name") else track.name
        self.song_title_label.set_label(track_name)
        self.song_title_label.set_tooltip_text(track_name)
        self.artist_label.set_artists(track.artists)
        self.explicit_label.set_visible(track.explicit)

        self.set_quality_label()

        self.track_radio_button.set_action_target_value(
            GLib.Variant("s", str(track.id))
        )
        self.album_button.set_action_target_value(GLib.Variant("s", str(album.id)))

        if utils.is_favourited(track):
            self.in_my_collection_button.set_icon_name("heart-filled-symbolic")
        else:
            self.in_my_collection_button.set_icon_name("heart-outline-thick-symbolic")

        self.save_last_playing_thing()

        if self.image_canc:
            self.image_canc.cancel()
            self.image_canc = Gio.Cancellable.new()

        # Remove old video cover should maybe be threaded
        if self.video_covers_enabled:
            self.videoplayer.pause()
            self.videoplayer.clear()

        if self.video_covers_enabled and album.video_cover:
            threading.Thread(
                target=utils.add_video_cover,
                args=(
                    self.playing_track_picture,
                    self.videoplayer,
                    album,
                    self.in_background,
                    self.image_canc,
                ),
            ).start()
        else:
            threading.Thread(
                target=utils.add_picture,
                args=(self.playing_track_picture, album, self.image_canc),
            ).start()

        threading.Thread(
            target=utils.add_image, args=(self.playing_track_image, album)
        ).start()

        threading.Thread(target=self.th_add_lyrics_to_page, args=()).start()

        self.control_bar_artist = track.artist
        self.update_slider()

        if self.queue_widget.get_mapped():
            self.queue_widget.update_all(self.player_object)
            self.queue_widget_updated = True
        else:
            self.queue_widget_updated = False

        threading.Thread(
            target=self._th_update_header_color,
            args=(album,)
        ).start()

    def _th_update_header_color(self, album) -> None:
        image_path = utils.get_image_url(album)
        GLib.idle_add(self.update_header_color, image_path)

    def update_header_color(self, image_path: str | None) -> None:
        if not image_path:
            self._header_css_provider.load_from_string("")
            self._anim_color = (1.0, 1.0, 1.0)
            return

        color = utils.get_dominant_color(image_path)
        if not color:
            self._header_css_provider.load_from_string("")
            self._anim_color = (1.0, 1.0, 1.0)
            return

        r, g, b = color
        self._anim_color = (r / 255, g / 255, b / 255)
        css = f"""
        * {{
            background: linear-gradient(
                to right,
                rgba({r}, {g}, {b}, 0.4),
                rgba({r}, {g}, {b}, 0.0)
            );
        }}
        """
        self._header_css_provider.load_from_string(css)

    def save_last_playing_thing(self):
        """Save the current playing context to settings for persistence.

        Stores information about the currently playing track and its source
        (album, playlist, mix, etc.) so playback can resume on app restart.
        """
        mix_album_playlist = self.player_object.current_mix_album_playlist
        track = self.player_object.playing_track

        if mix_album_playlist is not None and not isinstance(mix_album_playlist, list):
            self.settings.set_string(
                "last-playing-thing-id", str(mix_album_playlist.id)
            )
            self.settings.set_string(
                "last-playing-thing-type", utils.get_type(mix_album_playlist)
            )
        elif isinstance(mix_album_playlist, list):
            self.settings.set_string("last-playing-thing-id", "")
            self.settings.set_string("last-playing-thing-type", "")
        if track is not None:
            self.settings.set_int("last-playing-index", self.player_object.get_index())

    def stop_video_in_background(self, window, param):
        self.in_background = not self.is_active()
        album = self.player_object.song_album
        if not self.video_covers_enabled or not album or not album.video_cover:
            return

        if self.is_active():
            self.videoplayer.play()
        else:
            self.videoplayer.pause()

    def _draw_buffer_animation(self, area, cr, width, height):
        margin = 24 # Match Cover Image Margin
        border_width = 6 # Border Size
        corner_radius = 24 # Border Radius
        offset = 8 # Offset - Manual Tweaking

        inset = margin / 2 + border_width / 2 + offset
        x = inset
        y = inset
        w = width - inset * 2
        h = height - inset * 2
        r = corner_radius - border_width / 2 - offset

        angle = self._anim_angle
        cr_r, cr_g, cr_b = self._anim_color

        # Draw two lines opposite each other
        for i in range(2):
            a = angle + i * math.pi

            cr.save()
            cr.new_sub_path()
            cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2) # Top Left Arc
            cr.arc(x + w - r, y + r, r, 3 * math.pi / 2, 0) # Top Right Arc
            cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2) # Bottom Right Arc
            cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi) # Bottom Left Arc
            cr.close_path()

            lead_x = width / 2 + (w / 2) * math.cos(a) # Calculate X of head
            lead_y = height / 2 + (h / 2) * math.sin(a) # Calculate Y of head

            grad = cairo.RadialGradient(lead_x, lead_y, 0, lead_x, lead_y, max(w, h) * 0.8)
            grad.add_color_stop_rgba(0.0, min(cr_r * 1.5, 1.0), min(cr_g * 1.5, 1.0), min(cr_b * 1.5, 1.0), 0.6)
            grad.add_color_stop_rgba(0.4, cr_r, cr_g, cr_b, 0.8)
            grad.add_color_stop_rgba(1.0, 0.0, 0.0, 0.0, 0.0)

            cr.set_source(grad)
            cr.set_line_width(border_width)
            cr.stroke()
            cr.restore()

    def _start_buffer_animation(self):
        """Start the rotation timer."""
        if self._anim_timer is not None:
            return
        self._anim_timer = GLib.timeout_add(16, self._anim_tick)

    def _stop_buffer_animation(self):
        """Stop the rotation timer."""
        if self._anim_timer is not None:
            GLib.source_remove(self._anim_timer)
            self._anim_timer = None

    def _anim_tick(self):
        """Advance angle and queue redraw."""
        self._anim_angle += 0.10  # radians per frame, adjust for speed.
        if self._anim_angle > 2 * 3.14159:
            self._anim_angle -= 2 * 3.14159
        self.buffer_spinner.queue_draw()
        return GLib.SOURCE_CONTINUE

    def set_quality_label(self):
        """Update the quality label with current track's audio information.

        Displays information about the current track's codec, bit depth,
        sample rate, and audio quality in the UI.
        """
        codec = None
        bit_depth = None
        sample_rate = None

        stream = self.player_object.stream
        if stream:
            if stream.bit_depth:
                bit_depth = f"{stream.bit_depth}-bit"
            if stream.sample_rate:
                sample_rate = f"{stream.sample_rate / 1000:.1f} kHz"
            if stream.audio_quality:
                match stream.audio_quality:
                    case "LOW":
                        bitrate = "96 kbps"
                    case "HIGH":
                        bitrate = "320 kbps"
                    case _:
                        bitrate = "Lossless"

        manifest = self.player_object.manifest
        if manifest:
            if manifest.codecs:
                codec = manifest.codecs
                if codec == "MP4A":
                    codec = "AAC"
                self.quality_label.set_visible(False)

        quality_text = f"{codec}"

        if bit_depth or sample_rate:
            quality_details = []
            if bit_depth and codec != "AAC":
                quality_details.append(bit_depth)
            if sample_rate and codec != "AAC":
                quality_details.append(sample_rate)
            if bitrate and codec == "AAC":
                quality_details.append(bitrate)

            if quality_details:
                quality_text += f" ({' / '.join(quality_details)})"

        self.quality_label.set_label(quality_text)
        self.quality_label.set_visible(True)

    def update_controls(self, *args):
        """Update playback control button states based on player status"""
        if self.player_object.playing:
            self.play_button.set_icon_name("media-playback-pause-symbolic")
        else:
            self.play_button.set_icon_name("media-playback-start-symbolic")

    def update_repeat_button(self, player, repeat_type):
        """Update the repeat button icon based on current repeat mode"""
        match self.player_object.repeat_type:
            case RepeatType.NONE:
                self.repeat_button.set_icon_name("media-playlist-consecutive-symbolic")
            case RepeatType.SONG:
                self.repeat_button.set_icon_name("media-playlist-repeat-symbolic")
            case RepeatType.LIST:
                self.repeat_button.set_icon_name("playlist-repeat-song-symbolic")
        self.update_repeat_tooltip()

    def update_repeat_tooltip(self):
        """Update the repeat button tooltip based on current repeat mode"""
        match self.player_object.repeat_type:
            case RepeatType.NONE:
                self.repeat_button.set_tooltip_text(_("Repeat: Off"))
            case RepeatType.SONG:
                self.repeat_button.set_tooltip_text(_("Repeat: Song"))
            case RepeatType.LIST:
                self.repeat_button.set_tooltip_text(_("Repeat: List"))

    def on_song_buffering(self, player, percentage):
        if percentage != 100:
            self.buffer_spinner.set_visible(True)
            self._start_buffer_animation()
        else:
            self.buffer_spinner.set_visible(False)
            self._stop_buffer_animation()

    #
    #   CALLBACKS
    #

    @Gtk.Template.Callback("on_play_button_clicked")
    def on_play_button_clicked(self, btn):
        self.player_object.play_pause()

    @Gtk.Template.Callback("on_share_clicked")
    def on_share_clicked(self, *args):
        track = self.player_object.playing_track
        if track:
            utils.share_this(track)

    @Gtk.Template.Callback("on_skip_forward_button_clicked")
    def on_skip_forward_button_clicked_func(self, widget):
        self.player_object.play_next()

    @Gtk.Template.Callback("on_skip_backward_button_clicked")
    def on_skip_backward_button_clicked_func(self, widget):
        self.player_object.play_previous()

    @Gtk.Template.Callback("on_home_button_clicked")
    def on_home_button_clicked_func(self, widget):
        self.navigation_view.pop_to_tag("home")

    @Gtk.Template.Callback("on_explore_button_clicked")
    def on_explore_button_clicked_func(self, widget):
        if self.navigation_view.find_page("explore"):
            self.navigation_view.pop_to_tag("explore")
            return

        page = HTExplorePage().load()
        self.navigation_view.push(page)

    @Gtk.Template.Callback("on_collection_button_clicked")
    def on_collection_button_clicked_func(self, widget):
        if self.navigation_view.find_page("collection"):
            self.navigation_view.pop_to_tag("collection")
            return

        self.navigation_view.push(self._collection_page)

    @Gtk.Template.Callback("on_repeat_clicked")
    def on_repeat_clicked(self, *args):
        if self.player_object.repeat_type == RepeatType.NONE:
            self.player_object.repeat_type = RepeatType.SONG
        elif self.player_object.repeat_type == RepeatType.LIST:
            self.player_object.repeat_type = RepeatType.NONE
        elif self.player_object.repeat_type == RepeatType.SONG:
            self.player_object.repeat_type = RepeatType.LIST

        self.settings.set_int("repeat", self.player_object.repeat_type)

    @Gtk.Template.Callback("on_in_my_collection_button_clicked")
    def on_in_my_collection_button_clicked(self, btn):
        utils.on_in_to_my_collection_button_clicked(
            btn, self.player_object.playing_track
        )

    @Gtk.Template.Callback("on_shuffle_button_toggled")
    def on_shuffle_button_toggled(self, btn):
        self.player_object.shuffle = btn.get_active()

    @Gtk.Template.Callback("on_volume_changed")
    def on_volume_changed_func(self, widget):
        value = widget.get_value()
        self.player_object.change_volume(value)
        self.settings.set_int("last-volume", int(value * 10))

    @Gtk.Template.Callback("on_slider_seek")
    def on_slider_seek(self, *args):
        seek_fraction = self.progress_bar.get_value()

        if abs(seek_fraction - self.previous_fraction) == 0.0:
            return

        logger.info(f"seeking: {abs(seek_fraction - self.previous_fraction)}")

        self.player_object.seek(seek_fraction)
        self.previous_fraction = seek_fraction

    @Gtk.Template.Callback("on_seek_from_lyrics")
    def on_seek_from_lyrics(self, lyrics_widget, time_ms):
        end_value = self.duration / Gst.SECOND

        if end_value == 0:
            return

        position = time_ms / 1000

        self.player_object.seek(position / end_value)

    def on_song_added_to_queue(self, *args):
        if self.queue_widget.get_mapped():
            self.queue_widget.update_queue(self.player_object)
            self.queue_widget_updated = True
        else:
            self.queue_widget_updated = False

    @Gtk.Template.Callback("on_queue_widget_mapped")
    def on_queue_widget_mapped(self, *args):
        if not self.queue_widget_updated:
            self.queue_widget.update_all(self.player_object)
            self.queue_widget_updated = True

    @Gtk.Template.Callback("on_navigation_view_page_popped")
    def on_navigation_view_page_popped_func(self, nav_view, nav_page):
        if nav_page is self._collection_page:
            return
        nav_page.disconnect_all()

    @Gtk.Template.Callback("on_visible_page_changed")
    def on_visible_page_changed(self, nav_view, *args):
        match self.navigation_view.get_visible_page().get_tag():
            case "home":
                self.home_button.set_active(True)
            case "explore":
                self.explore_button.set_active(True)
            case "collection":
                self.collection_button.set_active(True)

    @Gtk.Template.Callback("on_sidebar_page_changed")
    def on_sidebar_page_changed(self, *args):
        if self.sidebar_stack.get_visible_child_name() == "player":
            self.playing_track_widget.set_visible(False)
        else:
            self.playing_track_widget.set_visible(True)

    def on_shuffle_changed(self, *args):
        self.shuffle_button.set_active(self.player_object.shuffle)

    def update_slider(self, *args):
        """Update the progress bar and playback information.

        Called periodically to update the progress bar, song duration, current position
        and volume level.
        """
        # Just copy the duration from player here to avoid ui desync from player object
        self.duration = self.player_object.duration
        end_value = self.duration / Gst.SECOND

        current = self.player_object.query_volume()
        if abs(self.volume_button.get_value() - current) > 0.01:
            self.volume_button.set_value(current)

        position = self.player_object.query_position(default=None)
        if position is None:
            return
        position_s = position / Gst.SECOND

        self.lyrics_widget.set_time(position_s)
        self.duration_label.set_label(utils.pretty_duration(end_value))
        self.time_played_label.set_label(utils.pretty_duration(position_s))

        fraction = None
        if end_value != 0:
            fraction = position_s / end_value
        if fraction:
            self.small_progress_bar.set_fraction(fraction)
            self.progress_bar.get_adjustment().set_value(fraction)
            self.previous_fraction = fraction

    def th_add_lyrics_to_page(self):
        try:
            lyrics = self.player_object.playing_track.lyrics()
            if lyrics:
                if lyrics.subtitles:
                    GLib.idle_add(self.lyrics_widget.set_lyrics, lyrics.subtitles)
                elif lyrics.text:
                    GLib.idle_add(self.lyrics_widget.set_lyrics, lyrics.text)
            else:
                self.lyrics_widget.clear()
        except Exception:
            self.lyrics_widget.clear()

    def select_quality(self, pos):
        match pos:
            case 0:
                self.session.audio_quality = Quality.low_96k
            case 1:
                self.session.audio_quality = Quality.low_320k
            case 2:
                self.session.audio_quality = Quality.high_lossless
            case 3:
                self.session.audio_quality = Quality.hi_res_lossless

        self.settings.set_int("quality", pos)

    def change_audio_sink(self, sink):
        if self.settings.get_int("preferred-sink") != sink:
            self.player_object.change_audio_sink(sink)
            self.settings.set_int("preferred-sink", sink)

    def change_alsa_device(self, device: str):
        if self.settings.get_string("alsa-device") != device:
            self.settings.set_string("alsa-device", device)
            self.player_object.alsa_device = device
            self.player_object.change_audio_sink(
                self.settings.get_int("preferred-sink")
            )

    def change_normalization(self, state):
        if self.player_object.normalize != state:
            self.player_object.normalize = state
            self.settings.set_boolean("normalize", state)
            # recreate audio pipeline, kinda dirty ngl
            self.player_object.change_audio_sink(
                self.settings.get_int("preferred-sink")
            )

    def change_quadratic_volume(self, state):
        if self.settings.get_boolean("quadratic-volume") != state:
            self.player_object.quadratic_volume = state
            self.settings.set_boolean("quadratic-volume", state)

    def change_video_covers_enabled(self, state):
        if self.settings.get_boolean("video-covers") != state:
            self.video_covers_enabled = state
            self.settings.set_boolean("video-covers", state)

            album = self.player_object.song_album
            if not album:
                return

            self.videoplayer.pause()
            self.videoplayer.clear()

            if self.video_covers_enabled and album.video_cover:
                threading.Thread(
                    target=utils.add_video_cover,
                    args=(
                        self.playing_track_picture,
                        self.videoplayer,
                        album,
                        self.image_canc,
                    ),
                ).start()
            else:
                threading.Thread(
                    target=utils.add_picture,
                    args=(self.playing_track_picture, album, self.image_canc),
                ).start()

    def change_discord_rpc_enabled(self, state):
        if self.settings.get_boolean("discord-rpc") != state:
            self.settings.set_boolean("discord-rpc", state)
            self.player_object.set_discord_rpc(state)

    #
    #   PAGES ACTIONS CALLBACKS
    #

    def on_push_artist_page(self, action, parameter):
        if parameter.get_string() == "":
            return
        page = HTArtistPage.new_from_id(parameter.get_string()).load()
        self.navigation_view.push(page)

    def on_push_album_page(self, action, parameter):
        if parameter.get_string() == "":
            return
        page = HTAlbumPage.new_from_id(parameter.get_string()).load()
        self.navigation_view.push(page)

    def on_push_playlist_page(self, action, parameter):
        if parameter.get_string() == "":
            return
        page = HTPlaylistPage.new_from_id(parameter.get_string()).load()
        self.navigation_view.push(page)

    def on_push_mix_page(self, action, parameter):
        if parameter.get_string() == "":
            return
        page = HTMixPage.new_from_id(parameter.get_string()).load()
        self.navigation_view.push(page)

    def on_push_track_radio_page(self, action, parameter):
        if parameter.get_string() == "":
            return
        page = HTMixPage.new_from_track(parameter.get_string()).load()
        self.navigation_view.push(page)

    def on_push_artist_radio_page(self, action, parameter):
        if parameter.get_string() == "":
            return
        page = HTMixPage.new_from_artist(parameter.get_string()).load()
        self.navigation_view.push(page)

    #
    #
    #

    def create_action_with_target(
        self, name: str, target_type: GLib.VariantType, callback: Callable
    ):
        """Create a new GAction with a target parameter.

        Args:
            name (str): The action name
            target_type: The GVariant type for the target parameter
            callback: The callback function to execute when action is triggered
        """

        action = Gio.SimpleAction.new(name, target_type)
        action.connect("activate", callback)
        self.add_action(action)
        return action

    def _apply_dev_tooltips(self, widget) -> None:
        """Developer tool to show component names as you hover over via tooltip."""
        name = type(widget).__name__
        gtype = widget.get_name()  # returns the GType name e.g. "GtkButton"
        template_name = None

        # Try to find the template child name by checking our own attributes
        for attr_name in dir(self):
            try:
                if getattr(self, attr_name) is widget:
                    template_name = attr_name
                    break
            except Exception:
                pass

        if template_name:
            tooltip = f"{template_name} ({gtype})"
        else:
            tooltip = gtype

        widget.set_tooltip_text(tooltip)

        # Recurse into children
        child = widget.get_first_child()
        while child:
            self._apply_dev_tooltips(child)
            child = child.get_next_sibling()
