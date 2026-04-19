# queue_widget.py
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

from gi.repository import Gtk, Gdk

from ..widgets.generic_track_widget import HTGenericTrackWidget
from ..widgets.queue_item_widget import HTQueueItemWidget


@Gtk.Template(resource_path="/io/github/nokse22/high-tide/ui/widgets/queue_widget.ui")
class HTQueueWidget(Gtk.Box):
    """It is used to display the track queue, including played tracks,
    tracks to play and tracks added to the queue"""

    __gtype_name__ = "HTQueueWidget"

    played_songs_list = Gtk.Template.Child()
    queued_songs_list = Gtk.Template.Child()
    next_songs_list = Gtk.Template.Child()

    played_songs_box = Gtk.Template.Child()
    queued_songs_box = Gtk.Template.Child()
    next_songs_box = Gtk.Template.Child()

    def _setup_drop_target(self, list_box, player_list, list_type) -> None:
        for controller in list_box.observe_controllers():
            if isinstance(controller, Gtk.DropTarget):
                list_box.remove_controller(controller)

        drop_target = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)
        drop_target.connect("drop", self._on_drop, list_box, player_list, list_type)
        drop_target.connect("motion", self._on_drag_motion, list_box, list_type)
        drop_target.connect("leave", self._on_drag_leave, list_box)
        list_box.add_controller(drop_target)

    def _on_drop(self, target, value, x, y, list_box, player_list, list_type) -> bool:

        self._hide_drop_indicator(list_box)

        try:
            drag_list_type, source_index = value.split(":")
            source_index = int(source_index)
        except (ValueError, AttributeError):
            return False

        if drag_list_type != list_type:
            return False

        # Find which row we dropped onto based on y coordinate
        dest_row = list_box.get_row_at_y(int(y))
        if dest_row is None:
            dest_index = len(player_list) - 1
        else:
            dest_index = int(dest_row.get_name())

        if source_index == dest_index:
            return False

        # Reorder in the actual player list
        track = player_list.pop(source_index)
        player_list.insert(dest_index, track)

        # Refresh the list UI
        self._rebuild_list(list_box, player_list, list_type)
        return True

    def _on_drag_motion(self, target, x, y, list_box, list_type):
        drag_list_type = HTQueueItemWidget.current_drag_list_type

        if drag_list_type is not None and drag_list_type != list_type:
            self._hide_drop_indicator(list_box)
            return 0

        self._show_drop_indicator(list_box, int(y))
        return Gdk.DragAction.MOVE

    def _on_drag_leave(self, target, list_box):
        self._hide_drop_indicator(list_box)

    def _show_drop_indicator(self, list_box, y) -> None:
        # Remove existing indicator
        self._hide_drop_indicator(list_box)

        # Find the row at this y position
        row = list_box.get_row_at_y(y)
        if row:
            index = list_box.get_children().index(row) if hasattr(list_box, 'get_children') else int(row.get_name())
            row.add_css_class("drop-target-above")
            list_box._indicator_row = row
        else:
            # Past the last row — highlight the last row's bottom
            last = None
            i = 0
            while list_box.get_row_at_index(i):
                last = list_box.get_row_at_index(i)
                i += 1
            if last:
                last.add_css_class("drop-target-below")
                list_box._indicator_row = last

    def _hide_drop_indicator(self, list_box) -> None:
        row = getattr(list_box, '_indicator_row', None)
        if row:
            row.remove_css_class("drop-target-above")
            row.remove_css_class("drop-target-below")
            list_box._indicator_row = None

    def _rebuild_list(self, list_box, player_list, list_type) -> None:
        child = list_box.get_row_at_index(0)
        while child:
            list_box.remove(child)
            child = list_box.get_row_at_index(0)
        for index, track in enumerate(player_list):
            listing = HTQueueItemWidget(track, list_type=list_type)
            listing.set_name(str(index))
            list_box.append(listing)

    def update_all(self, player) -> None:
        """Updates played songs, queue and next songs"""
        self.update_played_songs(player)
        self.update_queue(player)
        self.update_next_songs(player)

    def update_played_songs(self, player) -> None:
        """Updates played songs"""
        child = self.played_songs_list.get_row_at_index(0)
        while child:
            self.played_songs_list.remove(child)
            del child
            child = self.played_songs_list.get_row_at_index(0)

        if len(player.played_songs) > 0:
            self.played_songs_box.set_visible(True)
            for index, track in enumerate(player.played_songs):
                listing = HTGenericTrackWidget(track)
                listing.set_name(str(index))
                self.played_songs_list.append(listing)
        else:
            self.played_songs_box.set_visible(False)

    def update_queue(self, player) -> None:
        """Updates the queue"""
        child = self.queued_songs_list.get_row_at_index(0)
        while child:
            self.queued_songs_list.remove(child)
            del child
            child = self.queued_songs_list.get_row_at_index(0)

        if len(player.queue) > 0:
            self.queued_songs_box.set_visible(True)
            for index, track in enumerate(player.queue):
                listing = HTQueueItemWidget(track, list_type="queue")
                listing.set_name(str(index))
                self.queued_songs_list.append(listing)
            self._setup_drop_target(self.queued_songs_list, player.queue, "queue")
        else:
            self.queued_songs_box.set_visible(False)

    def update_next_songs(self, player) -> None:
        """Updates next songs"""
        child = self.next_songs_list.get_row_at_index(0)
        while child:
            self.next_songs_list.remove(child)
            del child
            child = self.next_songs_list.get_row_at_index(0)

        if len(player.tracks_to_play) > 0:
            self.next_songs_box.set_visible(True)
            for index, track in enumerate(player.tracks_to_play):
                listing = HTQueueItemWidget(track, list_type="next")
                listing.set_name(str(index))
                self.next_songs_list.append(listing)
            self._setup_drop_target(self.next_songs_list, player.tracks_to_play, "next")
        else:
            self.next_songs_box.set_visible(False)
