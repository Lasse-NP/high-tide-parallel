# link_card_widget.py
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

from gi.repository import Gtk, Gio
from ..disconnectable_iface import IDisconnectable
from ..lib import utils

logger = logging.getLogger(__name__)

_GRADIENT_PAIRS = [
    ("#3584e4", "#0d2f6e"),
    ("#e5a50a", "#7a3500"),
    ("#2ec27e", "#0d4a2a"),
    ("#e01b24", "#5a0a0d"),
    ("#9141ac", "#321050"),
    ("#c64600", "#5a1500"),
    ("#865e3c", "#2e1a0a"),
    ("#1c71d8", "#0a2a6e"),
    ("#57e389", "#0d4a2a"),
    ("#ff7800", "#6e2000"),
    ("#dc8add", "#4a0a5a"),
    ("#f66151", "#5a0a0d"),
]

def _gradient_for(title: str) -> tuple[str, str]:
    pair = _GRADIENT_PAIRS[hash(title) % len(_GRADIENT_PAIRS)]
    return pair[0], pair[1]


class HTLinkCardWidget(Gtk.Button, IDisconnectable):
    __gtype_name__ = "HTLinkCardWidget"

    def __init__(self, page_link):
        IDisconnectable.__init__(self)
        super().__init__(
            margin_start=6,
            margin_end=6,
            margin_top=3,
            margin_bottom=3,
            hexpand=True,
            width_request=200,
            vexpand=True,
            css_classes=["page-link-card"],
            overflow=Gtk.Overflow.HIDDEN,
        )
        self.page_link = page_link
        self._cancellable = Gio.Cancellable.new()

        color_from, color_to = _gradient_for(page_link.title)

        # Unique name so CSS targets only this instance
        unique_name = f"plc_{abs(hash(page_link.title))}"
        self.set_name(unique_name)

        provider = Gtk.CssProvider()
        provider.load_from_string(f"""
            #{unique_name} {{
                background: linear-gradient(135deg, {color_from}, {color_to});
                border-radius: 14px;
                border: none;
                box-shadow: none;
                padding: 0;
                min-height: 90px;
            }}
            #{unique_name}:hover {{
                background: linear-gradient(135deg, alpha({color_from}, 0.85), alpha({color_to}, 0.85));
            }}
        """)
        self.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        label = Gtk.Label(
            label=page_link.title,
            ellipsize=3,
            xalign=0.5,
            yalign=0.5,
            css_classes=["page-link-card-label"],
        )
        self.set_child(label)

        self.signals.append((self, self.connect("clicked", self._on_clicked)))

    def _on_clicked(self, btn):
        from ..pages.generic_page import HTGenericPage
        page = HTGenericPage.new_from_function(self.page_link.get).load()
        utils.navigation_view.push(page)

    def disconnect_signals(self):
        self._cancellable.cancel()
        super().disconnect_signals()