# player_object.py
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

import logging
import random
import threading
import base64
import time
from enum import IntEnum
from gettext import gettext as _
from pathlib import Path
from typing import Any, List, Union

from gi.repository import GLib, GObject, Gst

from tidalapi.album import Album
from tidalapi.artist import Artist
from tidalapi.mix import Mix, MixV2
from tidalapi.playlist import Playlist
from tidalapi.media import Track, ManifestMimeType, Stream

from . import discord_rpc, utils

logger = logging.getLogger(__name__)


class RepeatType(IntEnum):
    NONE = 0
    SONG = 1
    LIST = 2


class AudioSink(IntEnum):
    AUTO = 0
    PULSE = 1
    ALSA = 2
    JACK = 3
    OSS = 4
    PIPEWIRE = 5


class PlayerObject(GObject.GObject):
    """Handles player logic, queue, and shuffle functionality."""

    current_song_index = GObject.Property(type=int, default=-1)
    can_go_next = GObject.Property(type=bool, default=True)
    can_go_prev = GObject.Property(type=bool, default=True)

    __gsignals__ = {
        "songs-list-changed": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "update-slider": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "song-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "song-added-to-queue": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "duration-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "volume-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "buffering": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(
        self,
        preferred_sink: AudioSink = AudioSink.AUTO,
        alsa_device: str = "default",
        normalize: bool = False,
        quadratic_volume: bool = False,
    ) -> None:
        GObject.GObject.__init__(self)

        Gst.init(None)

        version_str = Gst.version_string()
        logger.info(f"GStreamer version: {version_str}")

        self.pipeline = Gst.Pipeline.new("dash-player")

        self.playbin = Gst.ElementFactory.make("playbin3", "playbin")
        if self.playbin:
            self.playbin.connect("about-to-finish", self.play_next_gapless)
            self.gapless_enabled = True
        else:
            logger.error("Could not create playbin3 element, trying playbin...")
            self.playbin = Gst.ElementFactory.make("playbin", "playbin")
            self.gapless_enabled = False

        if preferred_sink == AudioSink.PIPEWIRE:
            self.gapless_enabled = False

        self.use_about_to_finish = True

        if self.playbin:
            self.pipeline.add(self.playbin)
        else:
            logger.error("No Playbin object to add to pipeline...")

        self.normalize = normalize
        self.quadratic_volume = quadratic_volume
        self.most_recent_rg_tags = ""

        self.discord_rpc_enabled = True

        self.alsa_device: str = alsa_device
        # Configure audio sink
        self._setup_audio_sink(preferred_sink)

        # Set up message bus
        self._bus = self.pipeline.get_bus()
        self._bus.add_signal_watch()
        self._bus.connect("message::eos", self._on_bus_eos)
        self._bus.connect("message::error", self._on_bus_error)
        self._bus.connect("message::buffering", self._on_buffering_message)
        self._bus.connect("message::stream-start", self._on_track_start)

        # Initialize state utils
        self._shuffle = False
        self._playing = False
        self._repeat_type = RepeatType.NONE

        self.id_list: List[str] = []

        self.queue: List[Track] = []
        self.current_mix_album_playlist: Union[Mix, MixV2, Album, Playlist, Artist, List[Track], Track] | None = None
        self._tracks_to_play: List[Track] = []
        self.tracks_to_play: List[Track] = []
        self._shuffled_tracks_to_play: List[Track] = []
        self.played_songs: List[Track] = []
        self.playing_track: Track | None = None
        self.song_album: Album | None = None
        self.duration = self.query_duration()
        self.manifest: Any | None = None
        self.stream: Stream | None = None
        self.update_timer: int | None = None
        self.seek_after_sink_reload: float | None = None
        self.seeked_to_end = False
        self._pending_seek_fraction: float | None = None
        self._seek_timer: int | None = None

        # next track variables for gapless
        self.next_track: Any | None = None
        self._next_track_prefetched: bool = False

        # DEBUG DATA: buffering state tracking
        self._buffering = False
        self._buffering_started_at: float | None = None
        self._last_buffer_percent: int = 100
        self._stream_start_time: float | None = None

    # DEBUG DATA: state-change handler
    def _on_state_changed(self, bus: Any, message: Any) -> None:
        """Log pipeline state transitions to catch stalls between PAUSED and PLAYING."""
        # Only log state changes on the top-level pipeline, not child elements
        if message.src != self.pipeline:
            return
        old_state, new_state, pending_state = message.parse_state_changed()
        logger.debug(
            f"[STATE] {Gst.Element.state_get_name(old_state)}"
            f" → {Gst.Element.state_get_name(new_state)}"
            f" (pending: {Gst.Element.state_get_name(pending_state)})"
        )
        # A pipeline stuck with a non-VOID_PENDING pending state is a stall signal
        if new_state == Gst.State.PAUSED and pending_state == Gst.State.PLAYING:
            logger.warning(
                "[STATE] Pipeline is stuck transitioning PAUSED → PLAYING. "
                "This may be the cause of the infinite buffering freeze."
            )

    @GObject.Property(type=bool, default=False)
    def playing(self) -> bool:
        return self._playing

    @playing.setter
    def playing(self, _playing: bool) -> None:
        self._playing = _playing
        self.notify("playing")

    @GObject.Property(type=bool, default=False)
    def shuffle(self) -> bool:
        return self._shuffle

    @shuffle.setter
    def shuffle(self, _shuffle: bool) -> None:
        if self._shuffle == _shuffle:
            return

        self._shuffle = _shuffle
        self.notify("shuffle")
        self._update_shuffle_queue()
        # self.emit("song-changed")

    @GObject.Property(type=int, default=0)
    def repeat_type(self) -> RepeatType:
        return self._repeat_type

    @repeat_type.setter
    def repeat_type(self, _repeat_type: RepeatType) -> None:
        self._repeat_type = RepeatType(_repeat_type)
        self.notify("repeat-type")

    def _setup_audio_sink(self, sink_type: AudioSink) -> None:
        """Configure the audio sink using parse_launch for simplicity."""
        sink_map = {
            AudioSink.AUTO: "autoaudiosink",
            AudioSink.PULSE: "pulsesink",
            AudioSink.ALSA: f"volume name=alsa-vol ! alsasink device={self.alsa_device}",
            AudioSink.JACK: "jackaudiosink",
            AudioSink.OSS: "osssink",
            AudioSink.PIPEWIRE: "pipewiresink",
        }

        sink_name = sink_map.get(sink_type, "autoaudiosink")

        # add normalization to pipeline if set by settings
        normalization = ""
        if self.normalize:
            # the pre-amp value is set to match tidal webs volume
            normalization = (
                f"taginject name=rgtags {self.most_recent_rg_tags} ! "
                f"rgvolume name=rgvol pre-amp=4.0 fallback-gain=-10 headroom=6.0 ! "
                f"rglimiter ! audioconvert !"
            )

        pipeline_str = (
            f"queue ! audioconvert ! {normalization} audioresample ! {sink_name}"
        )

        if sink_type == AudioSink.PIPEWIRE:
            self.gapless_enabled = False
        else:
            self.gapless_enabled = True

        try:
            audio_bin = Gst.parse_bin_from_description(pipeline_str, True)
            if not audio_bin:
                raise RuntimeError("Failed to create audio bin")
            if not self.playbin:
                raise RuntimeError("Playbin is not available")
            self.playbin.set_property("audio-sink", audio_bin)
        except GLib.Error:
            logger.exception("Error creating pipeline")
            fallback_sink = Gst.ElementFactory.make("autoaudiosink", None)
            if self.playbin and fallback_sink:
                self.playbin.set_property("audio-sink", fallback_sink)
        except RuntimeError as e:
            logger.error(f"Could not set audio sink: {e}")

    def change_audio_sink(self, sink_type: AudioSink) -> None:
        """Change the audio sink while maintaining playback state.

        Args:
            sink_type (int): The audio sink `AudioSink` enum
        """
        self.use_about_to_finish = False
        # Play the same track again after reload
        self.next_track = self.playing_track
        was_playing: bool = self._playing
        position: int = self.query_position() or 0
        duration: int = self.query_duration()

        if self.playbin:
            saved_volume = self.playbin.get_property("volume")
            self.pipeline.set_state(Gst.State.NULL)
            self._setup_audio_sink(sink_type)
            self.playbin.set_property("volume", saved_volume)

            if was_playing and duration != 0:
                self.pipeline.set_state(Gst.State.PLAYING)
                self.seek_after_sink_reload = position / duration
            self.use_about_to_finish = True

    def _on_bus_eos(self, *args) -> None:
        """Handle end of stream."""
        # DEBUG DATA
        pos_ns = self.query_position()
        dur_ns = self.query_duration()
        pos_s = pos_ns / 1_000_000_000 if pos_ns else 0
        dur_s = dur_ns / 1_000_000_000 if dur_ns else 0
        track_id = self.playing_track.id if self.playing_track else "none"
        logger.debug(
            f"[EOS] track={track_id} position={pos_s:.1f}s duration={dur_s:.1f}s "
            f"tracks_remaining={len(self._tracks_to_play)} queue={len(self.queue)} "
            f"gapless_enabled={self.gapless_enabled}"
        )
        if dur_s > 0 and pos_s < dur_s * 0.95:
            logger.warning(
                f"[EOS] EOS fired at {pos_s:.1f}s but track duration is {dur_s:.1f}s "
                f"— this is a premature EOS and likely the source of the freeze."
            )

        if self._repeat_type == RepeatType.SONG:
            self.seeked_to_end = False
            self.seek(0)
            self.play()
            return

        if self._repeat_type == RepeatType.LIST and not self._tracks_to_play:
            GLib.idle_add(self.play_next)
            return

        if not self.tracks_to_play or not self.queue:
            self.pause()
        if not self.gapless_enabled:
            GLib.idle_add(self.play_next)

    def _on_bus_error(self, bus: Any, message: Any) -> None:
        """Handle pipeline errors."""
        err, debug = message.parse_error()
        logger.error(f"Error: {err.message}")
        logger.error(f"Debug info: {debug}")

        # DEBUG DATA
        pos_ns = self.query_position()
        dur_ns = self.query_duration()
        pos_s = pos_ns / 1_000_000_000 if pos_ns else 0
        dur_s = dur_ns / 1_000_000_000 if dur_ns else 0
        track_id = self.playing_track.id if self.playing_track else "none"
        logger.error(
            f"[BUS_ERROR] track={track_id} position={pos_s:.1f}s duration={dur_s:.1f}s "
            f"buffering={self._buffering} last_buffer_pct={self._last_buffer_percent}"
        )

        # Use string compare instead of error codes (Seems to be just generic error)
        if "Internal data stream error" in err.message and "not-linked" in debug:
            logger.error(
                "Stream error: Element not linked. Attempting to restart pipeline..."
            )
            if self.playing_track:
                self.play_track(self.playing_track)

        elif (
            "Error outputting to audio device" in err.message
            and "disconnected" in err.message
        ):
            utils.send_toast(_("ALSA Audio Device is not available"), 5)
            self.pause()
            self.pipeline.set_state(Gst.State.NULL)

    def _on_buffering_message(self, bus: Any, message: Any) -> None:
        buffer_per: int = message.parse_buffering()
        mode, avg_in, avg_out, buff_left = message.parse_buffering_stats()

        now = time.monotonic()

        if buffer_per < 100 and not self._buffering:
            # Buffering just started
            self._buffering = True
            self._buffering_started_at = now
            pos_ns = self.query_position()
            pos_s = pos_ns / 1_000_000_000 if pos_ns else 0
            track_id = self.playing_track.id if self.playing_track else "none"
            logger.warning(
                f"[BUFFER] Buffering started at {pos_s:.1f}s into track={track_id} "
                f"pct={buffer_per}% avg_in={avg_in}bps avg_out={avg_out}bps"
            )

        elif buffer_per < self._last_buffer_percent and self._buffering:
            # Buffer is draining rather than filling — stall risk
            logger.warning(
                f"[BUFFER] Buffer draining: {self._last_buffer_percent}% → {buffer_per}% "
                f"avg_in={avg_in}bps avg_out={avg_out}bps buff_left={buff_left}ms"
            )

        elif buffer_per == 100 and self._buffering:
            # Buffering resolved
            elapsed = now - self._buffering_started_at if self._buffering_started_at else 0
            logger.info(
                f"[BUFFER] Buffering resolved after {elapsed:.1f}s (pct=100%)"
            )
            self._buffering = False
            self._buffering_started_at = None

        elif self._buffering and self._buffering_started_at:
            # Still buffering — log every 5s so we can see if it's stuck
            elapsed = now - self._buffering_started_at
            if int(elapsed) % 5 == 0 and int(elapsed) > 0:
                logger.warning(
                    f"[BUFFER] Still buffering after {elapsed:.0f}s — "
                    f"pct={buffer_per}% avg_in={avg_in}bps avg_out={avg_out}bps "
                    f"buff_left={buff_left}ms"
                )

        self._last_buffer_percent = buffer_per
        if not self._next_track_prefetched:
            self.emit("buffering", buffer_per)

    def set_track(self, track: Track | None = None):
        """Sets the currently Playing track

        Args:
            track: If set, the playing track is set to it.
            Otherwise self.next_track is used
        """
        if self.playing_track:
            incoming = track or self.next_track
            if self.playing_track and incoming and self.playing_track.id != incoming.id:
                old_mpd = Path(utils.CACHE_DIR, f"manifest_{self.playing_track.id}.mpd")
                if old_mpd.exists():
                    try:
                        old_mpd.unlink()
                    except OSError:
                        pass
        if not track and not self.next_track:
            # This method has already been called in _play_track_url
            return
        if track:
            self.playing_track = track
        else:
            self.playing_track = self.next_track
            self.next_track = None
        if self.playing_track:
            self.song_album = self.playing_track.album
        self.can_go_next = len(self._tracks_to_play) > 0
        self.can_go_prev = len(self.played_songs) > 0
        self.duration = self.query_duration()
        # Should only trigger when track is enqueued on start without playback
        if not self.duration and self.playing_track:
            # self.duration is microseconds, but self.playing_track.duration is seconds
            self.duration = self.playing_track.duration * 1_000_000_000
        self.notify("can-go-prev")
        self.notify("can-go-next")
        self.emit("song-changed")

    def _on_track_start(self, bus: Any, message: Any):
        """This Method is called when a new track starts playing

        Args:
            bus: required by Gst
            message: required by Gst
        """
        # DEBUG DATA
        self._stream_start_time = time.monotonic()
        self._buffering = False
        self._buffering_started_at = None
        self._last_buffer_percent = 100
        incoming_id = (
            self.next_track.id if self.next_track and isinstance(self.next_track, Track)
            else (self.playing_track.id if self.playing_track else "unknown")
        )
        logger.debug(
            f"[TRACK_START] stream-start signal for track={incoming_id} "
            f"use_about_to_finish={self.use_about_to_finish} "
            f"gapless_enabled={self.gapless_enabled} "
            f"next_track={'set' if self.next_track else 'none'}"
        )

        # apply replaygain first to avoid volume clipping
        # (Idk if that will happen but its the only thing that has effect on audio in here)
        if self.stream:
            self.apply_replaygain_tags()
        self.set_track()

        if self.discord_rpc_enabled and self.playing_track:
            discord_rpc.set_activity(self.playing_track, 0)

        if self.update_timer:
            GLib.source_remove(self.update_timer)
        self.update_timer = GLib.timeout_add(16, self._update_slider_callback)

        self.seeked_to_end = False
        if self.seek_after_sink_reload:
            self.seek(self.seek_after_sink_reload)
            self.seek_after_sink_reload = None

        self.can_go_prev = len(self.played_songs) > 0
        # Only notify to deactivate
        if not self.can_go_prev:
            self.notify("can-go-prev")
            GLib.timeout_add(2000, self.previous_timer_callback)

    def play_this(
            self, thing: Union[Mix, MixV2, Album, Playlist, Artist, List[Track], Track], index: int = 0
    ) -> None:
        """Play tracks from a mix, album, playlist, or artist.

        Args:
            thing: An object (Mix, Album, Playlist, Artist, or list of Tracks) to play
            index (int): The index of the track to start playing (default: 0)
        """
        self.current_mix_album_playlist = thing
        tracks: List[Track] = self.get_track_list(thing)

        if not tracks:
            logger.info("No tracks found to play")
            return

        self._tracks_to_play = tracks[index:] + tracks[:index]
        if not self._tracks_to_play:
            return

        track: Track = self._tracks_to_play.pop(0)

        if not track.available:
            self.play_this(thing, index + 1)
        else:
            self.tracks_to_play = self._tracks_to_play
            self.played_songs = []

            if self._shuffle:
                self._update_shuffle_queue()

            # Will result in play() call later
            self.playing = True
            self.play_track(track)

    def shuffle_this(
            self, thing: Union[Mix, MixV2, Album, Playlist, Artist, List[Track], Track]
    ) -> None:
        """Same as play_this, but enables shuffle mode.

        Args:
            thing: An object (Mix, Album, Playlist, Artist, or list of Tracks) to play
        """
        tracks: List[Track] = self.get_track_list(thing)
        self.play_this(thing, random.randint(0, len(tracks)))
        self.shuffle = True

    def get_track_list(
        self, thing: Union[Mix, MixV2, Album, Playlist, Artist, List[Track], Track]
    ) -> List[Track]:
        """Convert various sources into a list of tracks.

        Args:
            thing: A TIDAL object (Mix, Album, Playlist, Artist, or list of Tracks)

        Returns:
            list: List of Track objects, or None if conversion failed
        """
        tracks_list: List[Track] | None = None

        if isinstance(thing, Mix):
            tracks_list = [t for t in thing.items() if isinstance(t, Track)]
        elif isinstance(thing, MixV2):
            retrieved = thing.get(thing.id)
            tracks_list = [t for t in (retrieved._items or []) if isinstance(t, Track)]
        elif isinstance(thing, Album):
            tracks_list = thing.tracks()
        elif isinstance(thing, Playlist):
            tracks_list = thing.tracks()
        elif isinstance(thing, Artist):
            tracks_list = thing.get_top_tracks()
        elif isinstance(thing, list):
            tracks_list = thing
        elif isinstance(thing, Track):
            tracks_list = [thing]

        if tracks_list is None:
            return []
        self.id_list = [str(track.id) for track in tracks_list]
        return tracks_list

    def play(self) -> None:
        """Start playback of the current track."""
        self.playing = True
        self.pipeline.set_state(Gst.State.PLAYING)

        if self.discord_rpc_enabled and self.playing_track:
            discord_rpc.set_activity(
                self.playing_track, ((self.query_position() or 0) // 1_000_000_000)
            )
        if self.update_timer:
            GLib.source_remove(self.update_timer)
        self.update_timer = GLib.timeout_add(16, self._update_slider_callback)

    def pause(self) -> None:
        """Pause playback of the current track."""
        self.playing = False
        self.pipeline.set_state(Gst.State.PAUSED)

        if self.discord_rpc_enabled:
            discord_rpc.set_activity()

    def play_pause(self) -> None:
        """Toggle between play and pause states."""
        if self._playing:
            self.pause()
        else:
            self.play()

    def play_track(self, track: Track, gapless=False, prefetched=False) -> None:
        """Play a specific track immediately or enqueue it for gapless playback

        Args:
            track: The Track object to play
            gapless: Whether to enqueue the track for gapless playback
            prefetched: Whether the next track has already been fetched
        """
        logger.debug(
            f"[PLAY_TRACK] Dispatching thread for track={track.id} "
            f"title='{getattr(track, 'name', '?')}' gapless={gapless}"
        )

        if not gapless:
            self.next_track = None
            self._next_track_prefetched = False

        threading.Thread(target=self._play_track_thread, args=(track, gapless, prefetched)).start()

    def _play_prefetched_track(self, track: Track) -> None:
        """Start a prefetched track non-gaplessly without re-fetching the stream.

        The pipeline already has the URI set from the gapless prefetch.
        We just need to tear it down and restart it so playback begins from the start.
        """
        logger.debug(f"[PIPELINE] Restarting prefetched track={track.id} without re-fetch")
        if self.playbin:
            self.use_about_to_finish = False
            saved_volume = self.playbin.get_property("volume")
            self.pipeline.set_state(Gst.State.NULL)
            self.playbin.set_property("volume", saved_volume)
            self.set_track(track)
            if self._playing:
                self.play()
            self.use_about_to_finish = True

    def _play_track_thread(self, track: Track, gapless=False, prefetched=False) -> None:
        """Thread for loading and playing a track.

        Args:
            track: The Track object to play
            gapless: Whether to enqueue the track for gapless playback
        """

        if prefetched:
            logger.debug(f"[FETCH] Skipping fetch for track={track.id} — already prefetched")
            GLib.idle_add(self._play_prefetched_track, track)
            return

        self.stream = None
        self.manifest = None

        t_start = time.monotonic()
        logger.debug(
            f"[FETCH] Starting stream fetch for track={track.id} gapless={gapless}"
        )

        try:
            stream = track.get_stream()
            if stream is None:
                raise RuntimeError(f"Failed to get stream for track={track.id}")
            self.stream = stream
            t_stream = time.monotonic()
            logger.debug(
                f"[FETCH] get_stream() took {t_stream - t_start:.2f}s "
                f"mime_type={stream.manifest_mime_type}"
            )
            manifest = stream.get_stream_manifest()
            if manifest is None:
                raise RuntimeError(f"Failed to get manifest for track={track.id}")
            self.manifest = manifest
            t_manifest = time.monotonic()
            logger.debug(
                f"[FETCH] get_stream_manifest() took {t_manifest - t_stream:.2f}s"
            )

            # When not gapless there is a race condition between get_stream() and on_track_start
            if not gapless:
                self.apply_replaygain_tags()

            music_url: str = ""

            if stream.manifest_mime_type == ManifestMimeType.MPD:
                data = stream.get_manifest_data()
                major, minor, micro, nano = Gst.version()
                if data:
                    # file:// MPD support in adaptivedemux2 landed in 1.26
                    if (major, minor) >= (1, 26):
                        mpd_path = Path(utils.CACHE_DIR, f"manifest_{track.id}.mpd")
                        if not mpd_path.exists():
                            with open(mpd_path, "w") as file:
                                file.write(data)
                        music_url = "file://{}".format(mpd_path)
                    else:
                        if isinstance(data, str):
                            mpd_bytes = data.encode("utf-8")
                        elif isinstance(data, bytes):
                            mpd_bytes = data
                        else:
                            raise RuntimeError(f"Unexpected manifest data type: {type(data)}")

                        mpd_b64 = base64.b64encode(mpd_bytes).decode("ascii")
                        music_url = "data:application/dash+xml;base64," + mpd_b64
                else:
                    raise AttributeError("No MPD manifest available!")
            elif stream.manifest_mime_type == ManifestMimeType.BTS:
                urls = manifest.get_urls()
                if isinstance(urls, list):
                    music_url = urls[0]

            logger.debug(
                f"[FETCH] Total fetch time {time.monotonic() - t_start:.2f}s "
                f"url_prefix={str(music_url)[:80]}"
            )

            GLib.idle_add(self._play_track_url, track, music_url, gapless)
        except Exception:
            logger.exception(
                f"[FETCH] Error getting track URL for track={track.id} "
                f"after {time.monotonic() - t_start:.2f}s"
            )

    def apply_replaygain_tags(self):
        """Apply ReplayGain normalization tags to the current track if enabled."""
        if not self.playbin:
            raise RuntimeError("Playbin is not available")
        stream = self.stream
        if stream is None:
            raise RuntimeError("Stream is not available")

        audio_sink = self.playbin.get_property("audio-sink")
        rgtags = audio_sink.get_by_name("rgtags") if audio_sink else None

        tags = ""

        # https://github.com/EbbLabs/python-tidal/issues/332
        # Rather quiet album than broken eardrums
        if stream.track_replay_gain != 1.0:
            tags = (
                f"replaygain-track-gain={stream.track_replay_gain},"
                f"replaygain-track-peak={stream.track_peak_amplitude}"
            )

        if stream.album_replay_gain != 1.0:
            tags = (
                f"replaygain-album-gain={stream.album_replay_gain},"
                f"replaygain-album-peak={stream.album_peak_amplitude}"
            )

        if rgtags and isinstance(rgtags, Gst.Element):
            rgtags.set_property("tags", tags)
            logger.info("Applied RG Tags")
        # Save replaygain tags for every song to avoid missing tags when
        # toggling the option
        self.most_recent_rg_tags = f"tags={tags}"

    def _play_track_url(self, track, music_url, gapless=False):
        """Set up and play track from URL."""

        logger.debug(
            f"[PIPELINE] Setting URI for track={track.id} gapless={gapless} "
            f"use_about_to_finish={self.use_about_to_finish} "
            f"playing={self._playing}"
        )
        if self.playbin:
            if not gapless:
                self.use_about_to_finish = False
                saved_volume = self.playbin.get_property("volume")
                self.pipeline.set_state(Gst.State.NULL)
                self.playbin.set_property("volume", saved_volume)
            self.playbin.set_property("uri", music_url)
        else:
            raise RuntimeError("Playbin is not available")

        logger.info(music_url)

        if gapless:
            self.next_track = track
            self._next_track_prefetched = True
        else:
            self.set_track(track)

        if not gapless and self._playing:
            self.play()

        if not gapless:
            self.use_about_to_finish = True

        logger.debug(
            f"[PIPELINE] URI set complete for track={track.id} "
            f"pipeline_state={self.pipeline.get_state(0)[1]}"
        )

    def play_next_gapless(self, playbin: Any):
        """Enqueue the next track for gapless playback.

        Args:
            playbin: required by Gst
        """

        if self._repeat_type == RepeatType.SONG:
            logger.info("[GAPLESS] Ignoring about-to-finish: repeat-one active, EOS will seek to 0")
            return

        # DEBUG DATA
        pos_ns = self.query_position()
        dur_ns = self.query_duration()
        pos_s = pos_ns / 1_000_000_000 if pos_ns else 0
        dur_s = dur_ns / 1_000_000_000 if dur_ns else 0
        logger.debug(
            f"[GAPLESS] about-to-finish fired at {pos_s:.1f}s / {dur_s:.1f}s "
            f"gapless_enabled={self.gapless_enabled} "
            f"use_about_to_finish={self.use_about_to_finish} "
            f"tracks_remaining={len(self.tracks_to_play)}"
        )

        # playbin is need as arg, but we access it later over self
        if self.gapless_enabled and self.use_about_to_finish and self.tracks_to_play:
            GLib.idle_add(self.play_next, True)
            logger.info("Trying gapless playbck")
        else:
            logger.info(
                f"[GAPLESS] Ignoring about-to-finish: "
                f"gapless_enabled={self.gapless_enabled} "
                f"use_about_to_finish={self.use_about_to_finish} "
                f"tracks_to_play={len(self.tracks_to_play)}"
            )

    def play_next(self, gapless=False):
        """Play the next track in the queue or playlist.

        Args:
            gapless: Whether to enqueue the track in gapless mode
        """

        logger.debug(
            f"[PLAY_NEXT] gapless={gapless} next_track={'set' if self.next_track else 'none'} "
            f"repeat={RepeatType(self._repeat_type).name} queue={len(self.queue)} "
            f"tracks_remaining={len(self._tracks_to_play)} "
            f"shuffle={self._shuffle}"
        )

        # A track is already enqueued from an about-to-finish
        if self.next_track:
            logger.info("Using already enqueued track from gapless")
            track = self.next_track
            if track and isinstance(track, Track):
                prefetched = self._next_track_prefetched
                self.next_track = None
                self._next_track_prefetched = False
                if self.playing_track:
                    self.played_songs.append(self.playing_track)
                self.play_track(track, gapless=gapless, prefetched=prefetched)
                return

        if self._repeat_type == RepeatType.SONG and not gapless:
            self.seek(0)
            self.apply_replaygain_tags()
            return
        if self._repeat_type == RepeatType.SONG:
            if self.playing_track:
                self.play_track(self.playing_track, gapless=True)
            return

        if self.playing_track:
            self.played_songs.append(self.playing_track)

        if self.queue:
            track = self.queue.pop(0)
            self.play_track(track, gapless=gapless)
            return

        if not self._tracks_to_play and self._repeat_type == RepeatType.LIST:
            self._tracks_to_play = self.played_songs
            self.tracks_to_play = self._tracks_to_play
            self.played_songs = []

        if not self._tracks_to_play:
            logger.info("[PLAY_NEXT] No more tracks — pausing.")
            self.pause()
            return

        track_list = []
        if self._shuffle:
            track_list = self._shuffled_tracks_to_play
        else:
            track_list = self._tracks_to_play

        if track_list and len(track_list) > 0:
            track = track_list.pop(0)
            logger.debug(f"[PLAY_NEXT] Advancing to track={track.id}")
            self.play_track(track, gapless=gapless)

    def play_previous(self):
        """Play the previous track or restart current track if near beginning."""
        # if not in the first 2 seconds of the track restart song
        if (self.query_position() or 0) > 2 * Gst.SECOND:
            self.seek(0)
            self.can_go_prev = len(self.played_songs) > 0
            # only notify when can't go to previous
            if not self.can_go_prev:
                self.notify("can-go-prev")
                GLib.timeout_add(2000, self.previous_timer_callback)
            return

        if not self.played_songs:
            return

        last_index = len(self.played_songs) - 1
        track = self.played_songs.pop(last_index)
        if self.playing_track:
            self._tracks_to_play.insert(0, self.playing_track)
        self.play_track(track)

    def previous_timer_callback(self):
        """Send a notify Event after 2s of the song playing"""
        self.can_go_prev = True
        self.notify("can-go-prev")

    def _update_shuffle_queue(self):
        if self._shuffle:
            self._shuffled_tracks_to_play = self._tracks_to_play.copy()
            random.shuffle(self._shuffled_tracks_to_play)
            self.tracks_to_play = self._shuffled_tracks_to_play
        else:
            self.tracks_to_play = self._tracks_to_play

    def add_to_queue(self, track):
        """Add a track to the end of the play queue.

        Args:
            track: The Track object to add to the queue
        """
        self.queue.append(track)
        self.emit("song-added-to-queue")

    def add_next(self, track):
        """Add a track to the top of the queue.

        Args:
            track: The Track object to play next
        """
        self.queue.insert(0, track)
        self.emit("song-added-to-queue")

    def query_volume(self):
        """Get the current playback volume.

        Returns:
            float: Current volume level (0.0 to 1.0), adjusted for quadratic scaling if enabled
        """
        if self.playbin:
            volume = self.playbin.get_property("volume")
            if self.quadratic_volume:
                return round(volume ** (1 / 2), 2)
            else:
                return round(volume, 2)
        else:
            raise RuntimeError("Playbin is not available")

    def change_volume(self, value):
        """Set the playback volume.

        Args:
            value (float): Volume level (0.0 to 1.0), will be squared if quadratic volume is enabled
        """
        volume_value = value ** 2 if self.quadratic_volume else value
        if self.playbin:
            audio_sink = self.playbin.get_property("audio-sink")
            if audio_sink:
                alsa_vol = audio_sink.get_by_name("alsa-vol")
                if alsa_vol:
                    alsa_vol.set_property("volume", volume_value)
                    self.emit("volume-changed", value)
                    return
        if self.playbin:
            self.playbin.set_property("volume", volume_value)
        self.emit("volume-changed", value)

    def _update_slider_callback(self):
        """Update playback slider and duration."""
        self.update_timer = None
        if not self.duration:
            logger.warning("Duration missing, trying again")
            self.duration = self.query_duration()
        self.emit("update-slider")
        return self._playing

    def query_duration(self):
        """Get the duration of the current track.

        Returns:
            int: Duration in nanoseconds, or 0 if query failed
        """
        if self.playbin:
            success, duration = self.playbin.query_duration(Gst.Format.TIME)
            return duration if success else 0
        else:
            raise RuntimeError("Playbin is not available")

    def query_position(self, default=0) -> int | None:
        """Get the current playback position.

        Args:
            default (int): Default value to return if query fails (default: 0)

        Returns:
            int: Position in nanoseconds, or default value if query failed
        """
        # stays locked at the scrubbed location instead of twitching backwards.
        if getattr(self, "_pending_seek_fraction", None) is not None:
            duration = self.query_duration()
            if duration:
                return int((self._pending_seek_fraction or 0.0) * duration)
        if self.playbin:
            success, position = self.playbin.query_position(Gst.Format.TIME)
            return position if success else default
        else:
            raise RuntimeError("Playbin is not available")

    def seek(self, seek_fraction):
        """Seek to a position in the current track.

        Args:
            seek_fraction (float): Position as a fraction of total duration (0.0 to 1.0)
        """

        # If a seek close to the end is performed then skip
        # Avoids UI desync and stuck tracks
        if not self.seeked_to_end and seek_fraction > 0.98:
            self.use_about_to_finish = False
            self.seeked_to_end = True
            self.play_next()
            return

        # Store the latest requested seek fraction
        self._pending_seek_fraction = seek_fraction

        # If there's already a delayed seek pending, cancel it
        if self._seek_timer is not None:
            GLib.source_remove(self._seek_timer)
        self._seek_timer = GLib.timeout_add(150, self._execute_pending_seek)

        # Schedule the seek execution for a short time in the future
        # This absorbs rapid consecutive requests so GStreamer's dashdemux doesn't get locked up
        self._seek_timer = GLib.timeout_add(150, self._execute_pending_seek)

    def _execute_pending_seek(self):
        """Actually sends the seek command to the GStreamer pipeline."""
        self._seek_timer = None
        if self._pending_seek_fraction is None:
            return GLib.SOURCE_REMOVE

        seek_fraction = self._pending_seek_fraction
        self._pending_seek_fraction = None

        duration = self.query_duration()
        if duration > 0 and self.playbin:
            position = int(seek_fraction * duration)
            self.playbin.seek_simple(
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                position
            )
            if self.discord_rpc_enabled:
                discord_rpc.set_activity(self.playing_track, position // 1_000_000_000)

        return GLib.SOURCE_REMOVE

    def set_discord_rpc(self, enabled: bool = True):
        """Enable or disable Discord Rich Presence integration.

        Args:
            enabled (bool): Whether to enable Discord RPC (default: True)
        """
        self.discord_rpc_enabled = enabled
        if enabled and self._playing:
            discord_rpc.set_activity(
                self.playing_track,
                int((self.query_position() or 0) // 1_000_000_000),
            )
        elif enabled:
            discord_rpc.set_activity()
        else:
            discord_rpc.disconnect()

    def get_index(self):
        """Get the index of the currently playing track in the playlist.

        Returns:
            int: Index of current track, or 0 if not found
        """
        for index, track_id in enumerate(self.id_list):
            if isinstance(self.playing_track, Track) and track_id == self.playing_track.id:
                return index
        return 0
