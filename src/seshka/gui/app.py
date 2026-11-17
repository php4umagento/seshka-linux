from __future__ import annotations

import signal
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")

from gi.repository import AyatanaAppIndicator3 as AppIndicator3
from gi.repository import GLib, Gtk

from seshka.gui.icons import icon_path
from seshka.gui.window import MainWindow
from seshka.store import Store


class Application:
    def __init__(self) -> None:
        self.store = Store()
        self.window = MainWindow(self.store)
        self.indicator = AppIndicator3.Indicator.new(
            "seshka-linux",
            icon_path("closed"),
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_menu(self._build_menu())
        self.store.subscribe(lambda: GLib.idle_add(self._on_store_changed))
        self._timer_id: int | None = None
        self._restart_timer()
        self.store.refresh()

    def _build_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()

        open_item = Gtk.MenuItem(label="Open seshka")
        open_item.connect("activate", self._show_window)
        menu.append(open_item)

        refresh = Gtk.MenuItem(label="Refresh")
        refresh.connect("activate", lambda *_: self.store.refresh())
        menu.append(refresh)

        menu.append(Gtk.SeparatorMenuItem())

        self.kill_all_item = Gtk.MenuItem(label="Kill all leftovers")
        self.kill_all_item.connect("activate", lambda *_: self.store.kill_all_orphans())
        menu.append(self.kill_all_item)

        self.end_idle_item = Gtk.MenuItem(label="End idle sessions")
        self.end_idle_item.connect("activate", lambda *_: self.store.kill_idle_sessions())
        menu.append(self.end_idle_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", self._quit)
        menu.append(quit_item)

        menu.show_all()
        return menu

    def _show_window(self, *_args) -> None:
        self.window.show_all()
        self.window.present()

    def _quit(self, *_args) -> None:
        Gtk.main_quit()

    def _restart_timer(self) -> None:
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
        interval_ms = max(5, self.store.settings.refresh_interval) * 1000
        self._timer_id = GLib.timeout_add(interval_ms, self._on_timer)

    def _on_timer(self) -> bool:
        self.store.refresh()
        # Recreate timer if interval changed
        self._restart_timer()
        return False

    def _on_store_changed(self) -> bool:
        count = self.store.orphan_count
        self.indicator.set_icon_full(
            icon_path("open" if count else "closed"),
            f"{count} leftovers" if count else "clean",
        )
        if count:
            self.indicator.set_label(str(count), "")
        else:
            self.indicator.set_label("", "")
        self.kill_all_item.set_sensitive(bool(self.store.killable_orphans()))
        self.end_idle_item.set_sensitive(bool(self.store.idle_sessions_list()))
        self.window.rebuild()
        # Keep timer in sync with settings changes
        return False

    def run(self) -> int:
        self._show_window()
        Gtk.main()
        return 0


def main(argv: list[str] | None = None) -> int:
    # Allow Ctrl-C in terminal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        app = Application()
    except Exception as exc:
        print(f"Failed to start GUI: {exc}", file=sys.stderr)
        print(
            "Requires GTK 3 and Ayatana AppIndicator "
            "(packages: gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1).",
            file=sys.stderr,
        )
        return 1
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
