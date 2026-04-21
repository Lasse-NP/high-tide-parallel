# utils.py
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

import html
import os
import re
import subprocess
import threading
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from gettext import gettext as _
from pathlib import Path
from typing import Any, List, TYPE_CHECKING

import requests
from requests.adapters import HTTPAdapter
from colorthief import ColorThief
from tidalapi import MixV2
from urllib3.util.retry import Retry
from gi.repository import Adw, Gdk, Gio, GLib

import tidalapi
from tidalapi.artist import DEFAULT_ARTIST_IMG
from tidalapi.album import Album
from tidalapi.artist import Artist
from tidalapi.mix import Mix
from tidalapi.playlist import Playlist
from tidalapi.media import Track
from tidalapi.types import ItemOrder, OrderDirection

from ..widgets.default_image_widget import HTDefaultImageWidget
from ..pages import HTAlbumPage, HTArtistPage, HTMixPage, HTPlaylistPage, HTCollectionPage
from .cache import HTCache

if TYPE_CHECKING:
    from .player_object import PlayerObject

logger = logging.getLogger(__name__)

favourite_mixes: List[Mix] = []
favourite_tracks: List[Track] = []
favourite_artists: List[Artist] = []
favourite_albums: List[Album] = []
favourite_playlists: List[Playlist] = []
playlist_and_favorite_playlists: List[Playlist] = []
user_playlists: List[Playlist] = []

navigation_view: Adw.NavigationView | None = None
player_object: PlayerObject | None = None
session: tidalapi.Session | None = None
toast_overlay: Adw.ToastOverlay | None = None
cache: HTCache | None = None
CACHE_DIR: str = ""
IMG_DIR: str = ""

def init() -> None:
    """Initialize the utils module by setting up cache directories and global objects.

    Sets up the cache directory structure, creates necessary directories,
    and initializes the global cache object for TIDAL API responses.
    """
    global CACHE_DIR
    CACHE_DIR = os.environ.get("XDG_CACHE_HOME")
    if CACHE_DIR == "" or CACHE_DIR is None or "high-tide" not in CACHE_DIR:
        CACHE_DIR = f"{os.environ.get('HOME')}/.cache/high-tide"
    global IMG_DIR
    IMG_DIR = f"{CACHE_DIR}/images"

    if not os.path.exists(IMG_DIR):
        os.makedirs(IMG_DIR)

    global session
    global navigation_view
    global player_object
    global toast_overlay
    global cache
    session = None
    cache = HTCache(session)


def get_alsa_devices() -> List[dict]:
    """Get ALSA devices"""
    try:
        alsa_devices = get_alsa_devices_from_aplay()
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        alsa_devices = get_alsa_devices_from_proc()
    return alsa_devices


def get_alsa_devices_from_aplay() -> List[dict]:
    """Get ALSA devices from aplay -l"""
    result = subprocess.run(["aplay", "-l"], capture_output=True, text=True)

    devices = [
        {
            "hw_device": "default",
            "name": _("Default"),
        }
    ]
    for line in result.stdout.split("\n"):
        # Example String: card 3: KA13 [FiiO KA13], device 0: USB Audio [USB Audio]
        match = re.match(
            r"^card\s+\d+:\s+([^[]+)\s+\[([^]]+)],\s+device\s+(\d+):\s+([^[]+)\s+\[([^]]+)]",
            line,
        )
        if match:
            card_short_name = match.group(1).strip()  # "KA13"
            card_full_name = match.group(2).strip()  # "FiiO KA13"
            device = int(match.group(3))  # 0
            device_short_name = match.group(4).strip()  # "USB Audio"
            device_full_name = match.group(5).strip()  # "USB Audio"

            # Persistent device string
            hw_string = f"hw:CARD={card_short_name},DEV={device}"
            devices.append(
                {
                    "hw_device": hw_string,
                    "name": f"{card_full_name} - {device_full_name} ({hw_string})",
                }
            )

    return devices


def get_alsa_devices_from_proc() -> List[dict]:
    """Get ALSA devices from files in /proc/asound"""
    cards = {}
    card_names = {}
    with open("/proc/asound/cards", "r") as f:
        for line in f:
            # Example String:  3 [KA13           ]: USB-Audio - FiiO KA13
            match = re.match(r"^\s*(\d+)\s+\[([^]]+)]\s*:\s*.+?\s-\s(.+)$", line)
            if match:
                index = int(match.group(1))
                shortname = match.group(2).strip()
                fullname = match.group(3).strip()
                cards[index] = fullname
                card_names[index] = shortname

    devices = [
        {
            "hw_device": "default",
            "name": _("Default"),
        }
    ]
    with open("/proc/asound/devices", "r") as f:
        for line in f:
            # Example String:  19: [ 3- 0]: digital audio playback
            match = re.match(
                r"^\s*\d+:\s+\[\s*(\d+)-\s*(\d+)]:\s*digital audio playback", line
            )
            if match:
                card, device = int(match.group(1)), int(match.group(2))
                card_name = cards.get(card, f"Card {card}")
                short_name = card_names.get(card, f"{card}")

                # Persistent device string
                hw_string = f"hw:CARD={short_name},DEV={device}"

                devices.append(
                    {
                        "hw_device": hw_string,
                        "name": f"{card_name} ({hw_string})",
                    }
                )

    return devices


def get_artist(artist_id: str) -> Artist:
    """Get an artist object by ID from the cache.

    Args:
        artist_id: The TIDAL artist ID

    Returns:
        Artist: The artist object from TIDAL API
    """
    global cache
    return cache.get_artist(artist_id)


def get_album(album_id: str) -> Album:
    """Get an album object by ID from the cache.

    Args:
        album_id: The TIDAL album ID

    Returns:
        Album: The album object from TIDAL API
    """
    global cache
    return cache.get_album(album_id)


def get_track(track_id: str) -> Track:
    """Get a track object by ID from the cache.

    Args:
        track_id: The TIDAL track ID

    Returns:
        Track: The track object from TIDAL API
    """
    global cache
    return cache.get_track(track_id)


def get_playlist(playlist_id: str) -> Playlist:
    """Get a playlist object by ID from the cache.

    Args:
        playlist_id: The TIDAL playlist ID

    Returns:
        Playlist: The playlist object from TIDAL API
    """
    global cache
    return cache.get_playlist(playlist_id)


def get_mix(mix_id: str) -> Mix:
    """Get a mix object by ID from the cache.

    Args:
        mix_id: The TIDAL mix ID

    Returns:
        Mix: The mix object from TIDAL API
    """
    global cache
    return cache.get_mix(mix_id)


def get_favourites() -> None:
    """Load all user favorites from TIDAL API and cache them globally.

    Retrieves and caches the user's favorite mixes, tracks, artists, albums,
    playlists, and user-created playlists for quick access throughout the app.
    """
    global favourite_mixes
    global favourite_tracks
    global favourite_artists
    global favourite_albums
    global favourite_playlists
    global playlist_and_favorite_playlists
    global user_playlists

    user = session.user

    def fetch_artists():
        return "artists", user.favorites.artists()

    def fetch_tracks():
        return "tracks", user.favorites.tracks(
            order=ItemOrder.Date, order_direction=OrderDirection.Descending)

    def fetch_albums():
        return "albums", user.favorites.albums()

    def fetch_playlists():
        return "playlists", user.favorites.playlists()

    def fetch_mixes():
        return "mixes", user.favorites.mixes()

    def fetch_user_playlists():
        return "user_playlists", user.playlists()

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(fetch_artists),
            executor.submit(fetch_tracks),
            executor.submit(fetch_albums),
            executor.submit(fetch_playlists),
            executor.submit(fetch_mixes),
            executor.submit(fetch_user_playlists),
        ]
        for future in as_completed(futures):
            key, value = future.result()
            match key:
                case "artists":
                    favourite_artists = value
                case "tracks":
                    favourite_tracks = value
                case "albums":
                    favourite_albums = value
                case "playlists":
                    favourite_playlists = value
                    playlist_and_favorite_playlists = value
                case "mixes":
                    favourite_mixes = value
                case "user_playlists":
                    user_playlists = value


def is_favourited(item: Any) -> bool:
    """Check if a TIDAL item is in the user's favorites.

    Args:
        item: A TIDAL object (Track, Mix, Album, Artist, or Playlist)

    Returns:
        bool: True if the item is favorited, False otherwise
    """
    global favourite_mixes
    global favourite_tracks
    global favourite_artists
    global favourite_albums
    global favourite_playlists

    if isinstance(item, Track):
        for fav in favourite_tracks:
            if fav.id == item.id:
                return True
    elif isinstance(item, Mix):
        for fav in favourite_mixes:
            if fav.id == item.id:
                return True
    elif isinstance(item, Album):
        for fav in favourite_albums:
            if fav.id == item.id:
                return True
    elif isinstance(item, Artist):
        for fav in favourite_artists:
            if fav.id == item.id:
                return True
    elif isinstance(item, Playlist):
        for fav in favourite_playlists:
            if fav.id == item.id:
                return True

    return False


def send_toast(toast_title: str, timeout: int) -> None:
    """Display a toast notification to the user.

    Args:
        toast_title (str): The message to display in the toast
        timeout (int): Duration in seconds before the toast disappears
    """
    toast_overlay.add_toast(Adw.Toast(title=toast_title, timeout=timeout))

def th_add_to_my_collection(btn: Any, item: Any) -> None:
    """Thread function to add a TIDAL item to the user's favorites.

    Args:
        btn: The favorite button widget (for UI updates)
        item: The TIDAL item to add to favorites
    """
    if isinstance(item, Track):
        favourite_tracks.insert(0, item)
    elif isinstance(item, Album):
        favourite_albums.insert(0, item)
    elif isinstance(item, Artist):
        favourite_artists.insert(0, item)
    elif isinstance(item, Playlist):
        favourite_playlists.insert(0, item)
        playlist_and_favorite_playlists.insert(0, item)
    elif isinstance(item, Mix):
        favourite_mixes.insert(0, item)

    if navigation_view:
        btn.set_icon_name("heart-filled-symbolic")
        page = navigation_view.find_page("collection")
        if isinstance(page, HTCollectionPage):
            GLib.idle_add(page.refresh, item, False)

    if isinstance(item, Track):
        result = session.user.favorites.add_track(str(item.id))
    elif isinstance(item, Mix):
        return
    elif isinstance(item, Album):
        result = session.user.favorites.add_album(str(item.id))
    elif isinstance(item, Artist):
        result = session.user.favorites.add_artist(str(item.id))
    elif isinstance(item, Playlist):
        result = session.user.favorites.add_playlist(str(item.id))
    else:
        result = False

    if result:
        send_toast(_("Successfully added to my collection"), 2)
    else:
        # Rollback
        if isinstance(item, Track):
            favourite_tracks[:] = [t for t in favourite_tracks if t.id != item.id]
        elif isinstance(item, Album):
            favourite_albums[:] = [a for a in favourite_albums if a.id != item.id]
        elif isinstance(item, Artist):
            favourite_artists[:] = [a for a in favourite_artists if a.id != item.id]
        elif isinstance(item, Playlist):
            favourite_playlists[:] = [p for p in favourite_playlists if p.id != item.id]
            playlist_and_favorite_playlists[:] = [p for p in playlist_and_favorite_playlists if p.id != item.id]
        elif isinstance(item, Mix):
            favourite_mixes[:] = [m for m in favourite_mixes if m.id != item.id]

        send_toast(_("Failed to add item to my collection"), 2)
        if navigation_view:
            btn.set_icon_name("heart-outline-thick-symbolic")
            page = navigation_view.find_page("collection")
            if isinstance(page, HTCollectionPage):
                GLib.idle_add(page.refresh, item, True)


def th_remove_from_my_collection(btn: Any, item: Any) -> None:
    """Thread function to remove a TIDAL item from the user's favorites.

    Args:
        btn: The favorite button widget (for UI updates)
        item: The TIDAL item to remove from favorites
    """

    if isinstance(item, Track):
        logger.debug(f"Removing {item.id} from favourites, list has {[t.id for t in favourite_tracks]}")
        favourite_tracks[:] = [t for t in favourite_tracks if t.id != item.id]
    elif isinstance(item, Album):
        favourite_albums[:] = [a for a in favourite_albums if a.id != item.id]
    elif isinstance(item, Artist):
        favourite_artists[:] = [a for a in favourite_artists if a.id != item.id]
    elif isinstance(item, Playlist):
        favourite_playlists[:] = [p for p in favourite_playlists if p.id != item.id]
        playlist_and_favorite_playlists[:] = [p for p in playlist_and_favorite_playlists if p.id != item.id]
    elif isinstance(item, Mix):
        favourite_mixes[:] = [m for m in favourite_mixes if m.id != item.id]

    if navigation_view:
        btn.set_icon_name("heart-outline-thick-symbolic")
        page = navigation_view.find_page("collection")
        if isinstance(page, HTCollectionPage):
            GLib.idle_add(page.refresh, item, True)

    if isinstance(item, Track):
        result = session.user.favorites.remove_track(str(item.id))
    elif isinstance(item, Mix):
        return
    elif isinstance(item, Album):
        result = session.user.favorites.remove_album(str(item.id))
    elif isinstance(item, Artist):
        result = session.user.favorites.remove_artist(str(item.id))
    elif isinstance(item, Playlist):
        result = session.user.favorites.remove_playlist(str(item.id))
    else:
        result = False

    if result:
        send_toast(_("Successfully removed from my collection"), 2)
    else:
        # Rollback — re-add to local list and refresh
        if isinstance(item, Track):
            favourite_tracks.append(item)
        elif isinstance(item, Album):
            favourite_albums.append(item)
        elif isinstance(item, Artist):
            favourite_artists.append(item)
        elif isinstance(item, Playlist):
            favourite_playlists.append(item)
            playlist_and_favorite_playlists.append(item)
        elif isinstance(item, Mix):
            favourite_mixes.append(item)

        send_toast(_("Failed to remove item from my collection"), 2)
        if navigation_view:
            btn.set_icon_name("heart-filled-symbolic")
            page = navigation_view.find_page("collection")
            if isinstance(page, HTCollectionPage):
                GLib.idle_add(page.refresh, item, False)


def on_in_to_my_collection_button_clicked(btn: Any, item: Any) -> None:
    """Handle favorite/unfavorite button clicks by starting appropriate thread.

    Args:
        btn: The favorite button that was clicked
        item: The TIDAL item to add or remove from favorites
    """
    if btn.get_icon_name() == "heart-outline-thick-symbolic":
        threading.Thread(target=th_add_to_my_collection, args=(btn, item)).start()
    else:
        threading.Thread(target=th_remove_from_my_collection, args=(btn, item)).start()


def share_this(item: Any) -> None:
    """Copy a TIDAL item's share URL to the system clipboard.

    Args:
        item: A TIDAL object with a share_url attribute
    """
    clipboard: Gdk.Clipboard = Gdk.Display().get_default().get_clipboard()

    share_url: str | None = None

    if isinstance(item, Track):
        share_url = item.share_url
    elif isinstance(item, Album):
        share_url = item.share_url
    elif isinstance(item, Artist):
        share_url = item.share_url
    elif isinstance(item, Playlist):
        share_url = item.share_url
    else:
        return

    if share_url:
        clipboard.set(share_url + "?u")

        send_toast(_("Copied share URL in the clipboard"), 2)


def get_type(item: Any) -> str:
    """Get the string type identifier for a TIDAL item.

    Args:
        item: A TIDAL object (Track, Mix, Album, Artist, or Playlist)

    Returns:
        str: The type as a lowercase string ("track", "mix", "mixv2", "album", "artist", or "playlist")
    """
    match item:
        case Track():
            return "track"
        case Mix():
            return "mix"
        case MixV2():
            return "mixv2"
        case Album():
            return "album"
        case Artist():
            return "artist"
        case Playlist():
            return "playlist"
        case _:
            return ""


def open_uri(label: str, uri: str) -> bool:
    """Open a URI by navigating to the appropriate page in the application.

    Args:
        label: Display label for the URI (currently unused)
        uri: A URI string in format "type:id" (e.g., "artist:123456")
    """

    if not navigation_view:
        logger.warning("Navigation view not available")
        return False

    uri_parts = uri.split(":")
    match uri_parts[0]:
        case "track":
            def _open_track():
                track = get_track(uri_parts[1])
                if navigation_view and track.album:
                    album_page = HTAlbumPage.new_from_id(str(track.album.id)).load()
                    GLib.idle_add(navigation_view.push, album_page)
            threading.Thread(target=_open_track).start()
        case "artist":
            page = HTArtistPage.new_from_id(uri_parts[1]).load()
            navigation_view.push(page)
        case "album":
            page = HTAlbumPage.new_from_id(uri_parts[1]).load()
            navigation_view.push(page)
        case "mix" | "mixv2":
            page = HTMixPage.new_from_id(uri_parts[1]).load()
            navigation_view.push(page)
        case "playlist":
            page = HTPlaylistPage.new_from_id(uri_parts[1]).load()
            navigation_view.push(page)
    return True


def open_tidal_uri(uri: str) -> None:
    """Handles opening uri like tidal://track/1234"""

    if not uri.startswith("tidal://"):
        raise ValueError("Invalid URI format: URI must start with 'tidal://'")

    uri_parts = uri[8:].split("/")

    if len(uri_parts) < 2:
        raise ValueError(f"Invalid URI format: {uri}")

    content_type = uri_parts[0].lower()
    content_id = uri_parts[1]

    if not content_id:
        raise ValueError(f"Invalid content ID in URI: {uri}")

    if not navigation_view:
        logger.warning("Navigation view not available")
        return

    match content_type:
        case "track":
            def _open_track():
                track = get_track(content_id)
                if navigation_view and track.album:
                    album_page = HTAlbumPage.new_from_id(str(track.album.id)).load()
                    GLib.idle_add(navigation_view.push, album_page)
            threading.Thread(target=_open_track).start()
        case "artist":
            page = HTArtistPage.new_from_id(content_id).load()
            navigation_view.push(page)
        case "album":
            page = HTAlbumPage.new_from_id(content_id).load()
            navigation_view.push(page)
        case "mix" | "mixv2":
            page = HTMixPage.new_from_id(content_id).load()
            navigation_view.push(page)
        case "playlist":
            page = HTPlaylistPage.new_from_id(content_id).load()
            navigation_view.push(page)
        case _:
            logger.warning(f"Unsupported content type: {content_type}")
            return


def th_play_track(track_id: str) -> None:
    """Thread function to play a specific track by ID.

    Args:
        track_id: The TIDAL track ID to play
    """
    track: Track = session.track(track_id)

    player_object.play_this([track])


def pretty_duration(secs: float | None) -> str:
    """Format a duration in seconds to a human-readable string.

    Args:
        secs (float): Duration in seconds (float allows millisecond precision)

    Returns:
        str: Formatted duration string (MM:SS.mmm or HH:MM:SS.mmm for durations over an hour)
    """
    if not secs:
        return "00:00.000"

    hours = int(secs // 3600)
    minutes = int((secs % 3600) // 60)
    seconds = int(secs % 60)
    ms = int((secs % 1) * 1000)

    if hours > 0:
        return f"{hours}:{minutes:02}:{seconds:02}.{ms:03}"
    else:
        return f"{minutes:02}:{seconds:02}.{ms:03}"

def get_best_dimensions(widget: Any) -> int:
    """Determine the best image dimensions for a widget.

    Args:
        widget: A GTK widget to measure

    Returns:
        int: The best image dimension from available sizes (80, 160, 320, 640, 1280)
    """
    edge = widget.get_height()
    dimensions = [80, 160, 320, 640, 1280]
    # The function for fractional scaling is not available in GTKWidget
    scale = 1.0
    native = widget.get_native()
    if native:
        surface = native.get_surface()
        if surface:
            scale = surface.get_scale()
    return next((x for x in dimensions if x > (edge * scale)), dimensions[-1])


def get_image_url(item: Any, dimensions: int = 320) -> str | None:
    """Get the local file path for an item's image, downloading if necessary.

    Args:
        item: A TIDAL object with image data
        dimensions (int): The desired image dimensions (default: 320)

    Returns:
        str: Path to the local image file, or None if download failed
    """
    if hasattr(item, 'picture') and item.picture == DEFAULT_ARTIST_IMG:
        return None
    if hasattr(item, "id"):
        file_path = Path(f"{IMG_DIR}/{item.id}_{dimensions}.jpg")
    else:
        file_path = Path(f"{IMG_DIR}/{uuid.uuid4()}_{dimensions}.jpg")

    logger.debug(f"Image path: {file_path}, exists: {file_path.is_file()}")

    if file_path.is_file():
        return str(file_path)

    try:
        picture_url = item.image(dimensions=dimensions)
        response = requests.get(picture_url)
    except Exception:
        logger.exception("Could not get image")
        return None
    if response.status_code == 200:
        picture_data = response.content

        with open(file_path, "wb") as file:
            file.write(picture_data)

    return str(file_path)


def get_dominant_color(image_path: str) -> tuple[int, int, int] | None:

    try:
        ct = ColorThief(image_path)
        return ct.get_color(quality=1)
    except Exception:
        logger.exception("Could not get dominant color")
        return None

def setup_artist_image(artist, widget: HTDefaultImageWidget) -> None:
    """Fetch dominant color from artist's top track and apply to widget."""

    def _th():
        try:
            top_tracks = artist.get_top_tracks(limit=1)
            if top_tracks:
                image_path = get_image_url(top_tracks[0].album)
                if image_path:
                    color = get_dominant_color(image_path)
                    if color:
                        widget.set_color(color)
        except Exception:
            pass  # keep default color on failure

    threading.Thread(target=_th).start()


def add_picture(
    widget: Any, item: Any, cancellable: Gio.Cancellable = Gio.Cancellable.new()
) -> None:
    """Retrieve and set an image for a widget from a TIDAL item.

    Downloads the image if necessary and sets it on the widget using set_filename().

    Args:
        widget: A GTK widget that supports set_filename()
        item: A TIDAL object with image data
        cancellable: Optional GCancellable for canceling the operation
    """

    if cancellable is None:
        cancellable = Gio.Cancellable.new()

    def _add_picture(widget, file_path, cancellable):
        if not cancellable.is_cancelled():
            widget.set_filename(file_path)

    GLib.idle_add(
        _add_picture,
        widget,
        get_image_url(item, get_best_dimensions(widget)),
        cancellable,
    )


def add_image(
    widget: Any, item: Any, cancellable: Gio.Cancellable = Gio.Cancellable.new()
) -> None:
    """Retrieve and set an image for a widget from a TIDAL item.

    Downloads the image if necessary and sets it on the widget using set_from_file().

    Args:
        widget: A GTK widget that supports set_from_file()
        item: A TIDAL object with image data
        cancellable: Optional GCancellable for canceling the operation
    """

    def _add_image(
        widget: Any, file_path: str | None, cancellable: Gio.Cancellable
    ) -> None:
        if not cancellable.is_cancelled():
            if file_path is not None:
                widget.set_from_file(file_path)

    GLib.idle_add(_add_image, widget, get_image_url(item), cancellable)


def get_video_cover_url(item: Any, dimensions: int = 320) -> str | None:
    """Get the local file path for an item's video cover, downloading if necessary.

    Args:
        item: A TIDAL object with video data
        dimensions (int): The desired video dimensions (default: 640)

    Returns:
        str: Path to the local video file, or None if download failed
    """
    if hasattr(item, "id"):
        file_path = Path(f"{IMG_DIR}/{item.id}_{dimensions}.mp4")
    else:
        file_path = Path(f"{IMG_DIR}/{uuid.uuid4()}_{dimensions}.mp4")

    if file_path.is_file():
        return str(file_path)

    try:
        video_url = item.video(dimensions=dimensions)
        response = requests.get(video_url)
    except Exception:
        logger.exception("Could not get video")
        return None
    if response.status_code == 200:
        picture_data = response.content

        with open(file_path, "wb") as file:
            file.write(picture_data)

    return str(file_path)


def add_video_cover(
    widget: Any,
    videoplayer: Any,
    item: Any,
    in_bg: bool,
    cancellable: Gio.Cancellable = Gio.Cancellable.new(),
) -> None:
    """Retrieve and set a video cover for a video player widget from a TIDAL item.

    Downloads the video if necessary and configures the video player.

    Args:
        widget: The container widget
        videoplayer: The GtkMediaFile
        item: A TIDAL object with video data
        in_bg (bool): Whether the window is currently in background (not in focus)
        cancellable: Optional GCancellable for canceling the operation
    """

    if cancellable is None:
        cancellable = Gio.Cancellable.new()

    def _add_video_cover(
        widget: Any,
        videoplayer: Any,
        file_path: str | None,
        in_bg: bool,
        cancellable: Gio.Cancellable,
    ) -> None:
        if not cancellable.is_cancelled() and file_path:
            videoplayer.set_loop(True)
            videoplayer.set_filename(file_path)
            widget.set_paintable(videoplayer)
            if not in_bg:
                videoplayer.play()

    GLib.idle_add(
        _add_video_cover,
        widget,
        videoplayer,
        get_video_cover_url(item, get_best_dimensions(widget)),
        in_bg,
        cancellable,
    )


def add_image_to_avatar(
    widget: Any, item: Any, cancellable: Gio.Cancellable = Gio.Cancellable.new()
) -> None:
    """Retrieve and set an image for an Adwaita Avatar widget from a TIDAL item.

    Args:
        widget: An Adw.Avatar widget
        item: A TIDAL object with image data
        cancellable: Optional GCancellable for canceling the operation
    """

    def _add_image_to_avatar(
        avatar_widget: Any, file_path: str | None, cancellable: Gio.Cancellable
    ) -> None:
        if not cancellable.is_cancelled():
            if file_path is None:
                return
            try:
                logger.debug(f"Setting avatar image from {file_path}")
                file = Gio.File.new_for_path(file_path)
                image = Gdk.Texture.new_from_file(file)
                widget.set_custom_image(image)
                logger.debug("Avatar image set successfully")
            except Exception:
                logger.exception(f"Failed to set avatar image from {file_path}")

    GLib.idle_add(_add_image_to_avatar, widget, get_image_url(item), cancellable)


def replace_links(text: str) -> str:
    """Replace TIDAL wimpLink tags in text with clickable HTML links.

    Converts [wimpLink artistId="123"]Artist Name[/wimpLink] format links
    to proper HTML anchor tags for display in markup-enabled widgets.

    Args:
        text (str): Input text containing wimpLink tags

    Returns:
        str: HTML-escaped text with wimpLink tags converted to anchor tags
    """
    # Define regular expression pattern to match [wimpLink ...]...[/wimpLink] tags
    pattern = r"\[wimpLink (artistId|albumId)=&quot;(\d+)&quot;\]([^[]+)\[\/wimpLink\]"

    # Escape HTML in the entire text
    escaped_text = html.escape(text)

    # Define a function to replace the matched pattern with the desired format
    def replace(match_obj: Any) -> str:
        link_type = match_obj.group(1)
        id_value = match_obj.group(2)
        label = match_obj.group(3)

        if link_type == "artistId":
            return f'<a href="artist:{id_value}">{label}</a>'
        elif link_type == "albumId":
            return f'<a href="album:{id_value}">{label}</a>'
        else:
            return label

    # Replace <br/> with two periods
    escaped_text = escaped_text.replace("&lt;br/&gt;", "\n")

    # Use re.sub() to perform the replacement
    replaced_text = re.sub(pattern, replace, escaped_text)

    return replaced_text


def create_tidal_session():
    tidal_session = tidalapi.Session()
    retry = Retry(connect=3, backoff_factor=0.5)
    adapter = HTTPAdapter(max_retries=retry)
    tidal_session.request_session.mount("https://", adapter)
    return tidal_session


def setup_logging():
    global CACHE_DIR

    log_to_file = os.getenv("LOG_TO_FILE")
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    handlers = []
    if log_to_file:
        handlers.append(logging.FileHandler(CACHE_DIR + "/high-tide.log"))
    handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )
