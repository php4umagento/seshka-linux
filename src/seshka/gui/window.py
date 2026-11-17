from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk, Pango

from seshka import __version__
from seshka.format import format_bytes, human_age
from seshka.models import Proc, RunningSession, SessionGroup
from seshka.store import Store


class MainWindow(Gtk.Window):
    def __init__(self, store: Store) -> None:
        super().__init__(title="seshka")
        self.store = store
        self.set_default_size(520, 640)
        self.set_border_width(0)
        self._building = False

        css = Gtk.CssProvider()
        css.load_from_data(
            b"""
            .header-title { font-weight: 600; font-size: 15px; }
            .muted { opacity: 0.7; font-size: 11px; }
            .tab-bar { padding: 4px; border-radius: 10px; background: alpha(@theme_fg_color, 0.06); }
            .row-pid { font-family: monospace; }
            .danger { color: #c0392b; }
            """
        )
        screen = Gdk.Screen.get_default()
        if screen:
            Gtk.StyleContext.add_provider_for_screen(
                screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        self.header = self._build_header()
        root.pack_start(self.header, False, False, 0)

        self.notebook = Gtk.Notebook()
        self.notebook.set_tab_pos(Gtk.PositionType.TOP)
        root.pack_start(self.notebook, True, True, 0)

        self.leftover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.sessions_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.settings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.about_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        self.notebook.append_page(self._scroll(self.leftover_box), Gtk.Label(label="Leftover"))
        self.notebook.append_page(self._scroll(self.sessions_box), Gtk.Label(label="Sessions"))
        self.notebook.append_page(self._scroll(self.settings_box), Gtk.Label(label="Settings"))
        self.notebook.append_page(self._scroll(self.about_box), Gtk.Label(label="About"))

        self.footer = self._build_footer()
        root.pack_start(self.footer, False, False, 0)

        self._build_settings()
        self._build_about()
        self.rebuild()

        self.connect("delete-event", self._on_close)

    def _scroll(self, child: Gtk.Widget) -> Gtk.ScrolledWindow:
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(child)
        return sw

    def _build_header(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(14)
        box.set_margin_bottom(10)
        box.set_margin_start(14)
        box.set_margin_end(14)

        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label="seshka", xalign=0)
        title.get_style_context().add_class("header-title")
        self.summary = Gtk.Label(label="Scanning…", xalign=0)
        self.summary.get_style_context().add_class("muted")
        titles.pack_start(title, False, False, 0)
        titles.pack_start(self.summary, False, False, 0)
        box.pack_start(titles, True, True, 0)

        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text("Refresh now")
        refresh.connect("clicked", lambda *_: self.store.refresh())
        box.pack_end(refresh, False, False, 0)
        return box

    def _build_footer(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(12)

        self.freed_label = Gtk.Label(label="", xalign=0)
        self.freed_label.get_style_context().add_class("muted")
        box.pack_start(self.freed_label, True, True, 0)

        self.kill_all_btn = Gtk.Button(label="Kill all leftovers")
        self.kill_all_btn.get_style_context().add_class("destructive-action")
        self.kill_all_btn.connect("clicked", self._on_kill_all)
        box.pack_end(self.kill_all_btn, False, False, 0)
        return box

    def _build_settings(self) -> None:
        self.settings_box.set_margin_start(16)
        self.settings_box.set_margin_end(16)
        self.settings_box.set_margin_top(12)
        self.settings_box.set_margin_bottom(12)

        self.interval_adj = Gtk.Adjustment(
            value=self.store.settings.refresh_interval,
            lower=5,
            upper=600,
            step_increment=5,
            page_increment=30,
        )
        interval = Gtk.SpinButton(adjustment=self.interval_adj, climb_rate=1, digits=0)
        interval.connect("value-changed", self._on_interval)

        self.idle_adj = Gtk.Adjustment(
            value=self.store.settings.idle_limit_minutes,
            lower=30,
            upper=24 * 60,
            step_increment=15,
            page_increment=60,
        )
        idle = Gtk.SpinButton(adjustment=self.idle_adj, climb_rate=1, digits=0)
        idle.connect("value-changed", self._on_idle_limit)

        self.auto_idle = Gtk.CheckButton(label="Automatically end idle sessions")
        self.auto_idle.set_active(self.store.settings.ends_idle_sessions)
        self.auto_idle.connect("toggled", self._on_auto_idle)

        self.protected_entry = Gtk.Entry()
        self.protected_entry.set_text(", ".join(self.store.settings.protected_patterns))
        self.protected_entry.set_placeholder_text("comma-separated substrings")
        save_prot = Gtk.Button(label="Save protected patterns")
        save_prot.connect("clicked", self._on_save_protected)

        for label, widget in (
            ("Refresh interval (seconds)", interval),
            ("Idle limit (minutes)", idle),
            ("", self.auto_idle),
            ("Protected command patterns", self.protected_entry),
            ("", save_prot),
        ):
            if label:
                self.settings_box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
            self.settings_box.pack_start(widget, False, False, 0)

        hint = Gtk.Label(
            label="Protected patterns are never killed by Kill all / Kill session / End idle.",
            xalign=0,
        )
        hint.set_line_wrap(True)
        hint.get_style_context().add_class("muted")
        self.settings_box.pack_start(hint, False, False, 0)

    def _build_about(self) -> None:
        self.about_box.set_margin_start(16)
        self.about_box.set_margin_end(16)
        self.about_box.set_margin_top(16)
        lines = [
            f"seshka-linux {__version__}",
            "Kill what Claude Code left behind.",
            "",
            "Inspired by the macOS app seshka by JigJoy.",
            "https://github.com/jigjoy-ai/seshka",
            "",
            "MIT License. Processes never leave your machine —",
            "seshka only reads /proc and signals your own processes.",
        ]
        for line in lines:
            lbl = Gtk.Label(label=line, xalign=0)
            lbl.set_selectable(True)
            self.about_box.pack_start(lbl, False, False, 0)

    def rebuild(self) -> None:
        if self._building:
            return
        self._building = True
        try:
            count = self.store.orphan_count
            if count == 0:
                self.summary.set_text("All clean")
            else:
                sessions = len(self.store.orphans)
                self.summary.set_text(
                    f"{count} leftover process{'es' if count != 1 else ''} from "
                    f"{sessions} closed session{'s' if sessions != 1 else ''} · "
                    f"{format_bytes(self.store.orphan_memory)}"
                )

            if self.store.freed:
                self.freed_label.set_text(
                    f"Freed {format_bytes(self.store.freed.bytes)} "
                    f"({self.store.freed.count} process{'es' if self.store.freed.count != 1 else ''})"
                )
            elif self.store.last_auto_end:
                self.freed_label.set_text(
                    f"Auto-ended {self.store.last_auto_end.count} idle session(s)"
                )
            else:
                self.freed_label.set_text("")

            self.kill_all_btn.set_sensitive(bool(self.store.killable_orphans()))
            self._rebuild_leftovers()
            self._rebuild_sessions()
        finally:
            self._building = False

    def _clear(self, box: Gtk.Box) -> None:
        for child in list(box.get_children()):
            box.remove(child)

    def _rebuild_leftovers(self) -> None:
        self._clear(self.leftover_box)
        if not self.store.orphans:
            self.leftover_box.pack_start(
                self._empty(
                    "No leftover processes",
                    "Nothing started by a closed Claude Code session is still running.",
                ),
                True,
                True,
                40,
            )
        else:
            for group in self.store.orphans:
                self.leftover_box.pack_start(self._group_widget(group, orphan=True), False, False, 0)
        self.leftover_box.show_all()

    def _rebuild_sessions(self) -> None:
        self._clear(self.sessions_box)
        idle = self.store.idle_sessions_list()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.set_margin_start(12)
        toolbar.set_margin_end(12)
        toolbar.set_margin_top(8)
        btn = Gtk.Button(label=f"End idle ({len(idle)})")
        btn.set_sensitive(bool(idle))
        btn.connect("clicked", lambda *_: self.store.kill_idle_sessions())
        toolbar.pack_end(btn, False, False, 0)
        self.sessions_box.pack_start(toolbar, False, False, 0)

        if not self.store.sessions:
            self.sessions_box.pack_start(
                self._empty("No open sessions", "No Claude Code process is running."),
                True,
                True,
                40,
            )
        else:
            for session in self.store.sessions:
                self.sessions_box.pack_start(self._session_widget(session), False, False, 0)
        self.sessions_box.show_all()

    def _empty(self, title: str, detail: str) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        t = Gtk.Label(label=title)
        t.get_style_context().add_class("header-title")
        d = Gtk.Label(label=detail)
        d.set_line_wrap(True)
        d.get_style_context().add_class("muted")
        box.pack_start(t, False, False, 0)
        box.pack_start(d, False, False, 0)
        box.set_halign(Gtk.Align.CENTER)
        return box

    def _group_widget(self, group: SessionGroup, *, orphan: bool) -> Gtk.Box:
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        wrap.set_margin_start(12)
        wrap.set_margin_end(12)
        wrap.set_margin_top(10)
        wrap.set_margin_bottom(4)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = group.title or group.project
        label = Gtk.Label(
            label=f"{title} · {group.short_id} · {format_bytes(group.memory)}",
            xalign=0,
        )
        label.set_ellipsize(Pango.EllipsizeMode.END)
        head.pack_start(label, True, True, 0)
        kill = Gtk.Button(label="Kill session")
        kill.connect("clicked", lambda *_: self.store.kill_session(group))
        head.pack_end(kill, False, False, 0)
        wrap.pack_start(head, False, False, 0)

        for proc in group.procs:
            wrap.pack_start(self._proc_row(proc), False, False, 0)
        return wrap

    def _session_widget(self, session: RunningSession) -> Gtk.Box:
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        wrap.set_margin_start(12)
        wrap.set_margin_end(12)
        wrap.set_margin_top(10)
        wrap.set_margin_bottom(4)

        idle = session.idle_seconds()
        if session.status == "idle" and idle is not None:
            state = f"idle {human_age(idle)}"
        elif session.status == "busy":
            state = "working"
        else:
            state = session.status

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = session.title or session.project
        label = Gtk.Label(
            label=(
                f"{title} · {state} · open {human_age(session.process.age_s)} · "
                f"{format_bytes(session.memory)} · {len(session.procs)} bg"
            ),
            xalign=0,
        )
        label.set_ellipsize(Pango.EllipsizeMode.END)
        head.pack_start(label, True, True, 0)
        end = Gtk.Button(label="End session")
        end.connect("clicked", lambda *_ , s=session: self.store.kill_running(s))
        head.pack_end(end, False, False, 0)
        wrap.pack_start(head, False, False, 0)

        for proc in session.procs:
            wrap.pack_start(self._proc_row(proc), False, False, 0)
        return wrap

    def _proc_row(self, proc: Proc) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ports = f" :{','.join(proc.ports)}" if proc.ports else ""
        helpers = f" (+{len(proc.helpers)})" if proc.helpers else ""
        protected = " 🔒" if self.store.is_protected(proc) else ""
        text = (
            f"{proc.pid}  {human_age(proc.age_s)}  {format_bytes(proc.memory)}"
            f"{ports}  {proc.short_command}{helpers}{protected}"
        )
        label = Gtk.Label(label=text, xalign=0)
        label.get_style_context().add_class("row-pid")
        label.set_ellipsize(Pango.EllipsizeMode.END)
        row.pack_start(label, True, True, 0)

        kill = Gtk.Button(label="Kill")
        kill.set_sensitive(proc.pid not in self.store.killing and not self.store.is_protected(proc))
        kill.connect("clicked", lambda *_ , p=proc: self.store.kill([p]))
        row.pack_end(kill, False, False, 0)
        return row

    def _on_kill_all(self, *_args) -> None:
        self.store.kill_all_orphans()

    def _on_interval(self, button: Gtk.SpinButton) -> None:
        self.store.settings.refresh_interval = int(button.get_value())
        self.store.save_settings()

    def _on_idle_limit(self, button: Gtk.SpinButton) -> None:
        self.store.settings.idle_limit_minutes = int(button.get_value())
        self.store.save_settings()

    def _on_auto_idle(self, button: Gtk.CheckButton) -> None:
        self.store.settings.ends_idle_sessions = button.get_active()
        self.store.save_settings()
        if button.get_active():
            self.store.refresh()

    def _on_save_protected(self, *_args) -> None:
        raw = self.protected_entry.get_text()
        patterns = [p.strip() for p in raw.split(",") if p.strip()]
        self.store.settings.protected_patterns = patterns
        self.store.save_settings()

    def _on_close(self, *_args):
        self.hide()
        return True  # keep process alive via tray
