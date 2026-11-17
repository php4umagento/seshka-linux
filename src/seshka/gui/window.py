from __future__ import annotations

import time
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from seshka import __version__
from seshka.format import format_bytes, format_limit, human_age
from seshka.gui.icons import pixbuf
from seshka.models import Proc, RunningSession, SessionGroup
from seshka.store import Store

CSS_PATH = Path(__file__).with_name("style.css")


class MainWindow(Gtk.Window):
    def __init__(self, store: Store, on_quit=None) -> None:
        super().__init__(title="seshka")
        self.store = store
        self.on_quit = on_quit
        self.set_default_size(500, 640)
        self.set_resizable(True)
        self.get_style_context().add_class("seshka-window")
        self._tab = "leftover"
        self._confirm_kill_all = False
        self._building = False
        self._expanded: set[int] = set()

        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-application-prefer-dark-theme", True)

        self._load_css()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.get_style_context().add_class("seshka-root")
        self.add(root)

        root.pack_start(self._build_header(), False, False, 0)
        root.pack_start(self._build_tabs(), False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(160)
        root.pack_start(self.stack, True, True, 0)

        self.leftover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.sessions_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.settings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.about_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.stack.add_named(self._scroll(self.leftover_box), "leftover")
        self.stack.add_named(self._scroll(self.sessions_box), "sessions")
        self.stack.add_named(self._scroll(self.settings_box), "settings")
        self.stack.add_named(self._scroll(self.about_box), "about")

        root.pack_start(self._build_footer(), False, False, 0)

        self._build_settings()
        self._build_about()
        self.rebuild()
        self.connect("delete-event", self._on_close)

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(str(CSS_PATH))
        except GLib.Error as exc:
            print(f"seshka: CSS load failed: {exc}", file=__import__("sys").stderr)
            return
        screen = Gdk.Screen.get_default()
        if screen:
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
            )

    def _scroll(self, child: Gtk.Widget) -> Gtk.ScrolledWindow:
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(child)
        return sw

    # --- header / tabs / footer -------------------------------------------------

    def _build_header(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(16)
        box.set_margin_bottom(8)
        box.set_margin_start(16)
        box.set_margin_end(14)

        self.doll = Gtk.Image.new_from_pixbuf(pixbuf("closed", 40))
        box.pack_start(self.doll, False, False, 0)

        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        title = Gtk.Label(label="seshka", xalign=0)
        title.get_style_context().add_class("header-title")
        self.summary = Gtk.Label(label="Scanning…", xalign=0)
        self.summary.get_style_context().add_class("header-summary")
        titles.pack_start(title, False, False, 0)
        titles.pack_start(self.summary, False, False, 0)
        box.pack_start(titles, True, True, 0)

        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh.set_relief(Gtk.ReliefStyle.NONE)
        refresh.get_style_context().add_class("header-refresh")
        refresh.set_tooltip_text("Refresh now")
        refresh.connect("clicked", lambda *_: self.store.refresh())
        box.pack_end(refresh, False, False, 0)
        return box

    def _build_tabs(self) -> Gtk.Box:
        wrap = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        wrap.set_margin_start(12)
        wrap.set_margin_end(12)
        wrap.set_margin_bottom(10)
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        bar.get_style_context().add_class("tab-bar")
        wrap.pack_start(bar, True, True, 0)

        self.tab_buttons: dict[str, Gtk.Button] = {}
        self.tab_badges: dict[str, Gtk.Label] = {}
        for key, label in (
            ("leftover", "Leftover"),
            ("sessions", "Sessions"),
            ("settings", "Settings"),
            ("about", "About"),
        ):
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.get_style_context().add_class("tab-btn")
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            text = Gtk.Label(label=label)
            text.set_name(f"tab-label-{key}")
            inner.pack_start(text, False, False, 0)
            if key in ("leftover", "sessions"):
                badge = Gtk.Label(label="0")
                badge.get_style_context().add_class("tab-badge")
                badge.set_no_show_all(True)
                inner.pack_start(badge, False, False, 0)
                self.tab_badges[key] = badge
            btn.add(inner)
            btn.connect("clicked", self._on_tab, key)
            bar.pack_start(btn, True, True, 0)
            self.tab_buttons[key] = btn
        return wrap

    def _build_footer(self) -> Gtk.Box:
        self.footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.footer.get_style_context().add_class("footer")
        self.footer.set_margin_top(0)
        for edge in ("start", "end"):
            getattr(self.footer, f"set_margin_{edge}")(12)
        self.footer.set_margin_top(8)
        self.footer.set_margin_bottom(10)

        self.footer_meta = Gtk.Label(label="", xalign=0)
        self.footer_meta.get_style_context().add_class("footer-meta")
        self.footer.pack_start(self.footer_meta, True, True, 0)

        self.footer_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.footer.pack_end(self.footer_actions, False, False, 0)
        return self.footer

    # --- settings / about -------------------------------------------------------

    def _build_settings(self) -> None:
        self.settings_box.set_margin_top(4)
        self.settings_box.set_margin_bottom(12)

        self._section_label(self.settings_box, "REFRESH")
        refresh_card = self._settings_card()
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.pack_start(Gtk.Label(label="Check for processes every", xalign=0), True, True, 0)
        self.interval_combo = Gtk.ComboBoxText()
        for seconds, label in ((10, "10 s"), (30, "30 s"), (60, "1 min"), (300, "5 min")):
            self.interval_combo.append(str(seconds), label)
        self.interval_combo.set_active_id(str(self.store.settings.refresh_interval))
        if self.interval_combo.get_active_id() is None:
            self.interval_combo.set_active_id("30")
        self.interval_combo.connect("changed", self._on_interval)
        row.pack_end(self.interval_combo, False, False, 0)
        refresh_card.pack_start(row, False, False, 0)
        self.settings_box.pack_start(refresh_card, False, False, 0)

        self._section_label(self.settings_box, "IDLE SESSIONS")
        idle_card = self._settings_card()
        idle_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        idle_row.pack_start(Gtk.Label(label="Idle longer than", xalign=0), True, True, 0)
        self.idle_combo = Gtk.ComboBoxText()
        for minutes, label in (
            (30, "30 min"),
            (60, "1 h"),
            (120, "2 h"),
            (240, "4 h"),
            (480, "8 h"),
        ):
            self.idle_combo.append(str(minutes), label)
        self.idle_combo.set_active_id(str(self.store.settings.idle_limit_minutes))
        if self.idle_combo.get_active_id() is None:
            self.idle_combo.set_active_id("120")
        self.idle_combo.connect("changed", self._on_idle_limit)
        idle_row.pack_end(self.idle_combo, False, False, 0)
        idle_card.pack_start(idle_row, False, False, 0)
        self.auto_idle = Gtk.CheckButton(label="Automatically end idle sessions")
        self.auto_idle.set_active(self.store.settings.ends_idle_sessions)
        self.auto_idle.connect("toggled", self._on_auto_idle)
        idle_card.pack_start(self.auto_idle, False, False, 8)
        hint = Gtk.Label(
            label="Off by default. Ending a session keeps the conversation — resume with claude --resume.",
            xalign=0,
        )
        hint.set_line_wrap(True)
        hint.get_style_context().add_class("card-subtitle")
        idle_card.pack_start(hint, False, False, 0)
        self.settings_box.pack_start(idle_card, False, False, 0)

        self._section_label(self.settings_box, "PROTECTED")
        prot_card = self._settings_card()
        intro = Gtk.Label(
            label="A process whose command contains one of these is skipped by Kill all and Kill session.",
            xalign=0,
        )
        intro.set_line_wrap(True)
        intro.get_style_context().add_class("card-subtitle")
        prot_card.pack_start(intro, False, False, 0)
        self.protected_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        prot_card.pack_start(self.protected_list, False, False, 8)
        add_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.protected_entry = Gtk.Entry()
        self.protected_entry.set_placeholder_text("e.g. docker")
        self.protected_entry.connect("activate", self._on_add_protected)
        add_btn = self._pill("Add", "pill-muted", self._on_add_protected)
        add_row.pack_start(self.protected_entry, True, True, 0)
        add_row.pack_end(add_btn, False, False, 0)
        prot_card.pack_start(add_row, False, False, 0)
        self.settings_box.pack_start(prot_card, False, False, 0)
        self._rebuild_protected_list()

    def _build_about(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(28)
        box.set_halign(Gtk.Align.CENTER)
        img = Gtk.Image.new_from_pixbuf(pixbuf("closed", 96))
        title = Gtk.Label(label=f"seshka-linux {__version__}")
        title.get_style_context().add_class("clean-title")
        detail = Gtk.Label(
            label=(
                "Kill what Claude Code left behind.\n"
                "Maintained by PHP4U.\n"
                "Inspired by seshka for macOS by JigJoy.\n\n"
                "MIT License · See THIRD_PARTY.md for upstream icons.\n"
                "Nothing leaves your machine."
            )
        )
        detail.set_justify(Gtk.Justification.CENTER)
        detail.set_line_wrap(True)
        detail.get_style_context().add_class("clean-detail")
        box.pack_start(img, False, False, 0)
        box.pack_start(title, False, False, 0)
        box.pack_start(detail, False, False, 0)
        self.about_box.pack_start(box, True, True, 20)

    def _section_label(self, parent: Gtk.Box, text: str) -> None:
        label = Gtk.Label(label=text, xalign=0)
        label.get_style_context().add_class("settings-label")
        parent.pack_start(label, False, False, 0)

    def _settings_card(self) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.get_style_context().add_class("settings-section")
        return card

    # --- rebuild ----------------------------------------------------------------

    def rebuild(self) -> None:
        if self._building:
            return
        self._building = True
        try:
            count = self.store.orphan_count
            self.doll.set_from_pixbuf(pixbuf("open" if count else "closed", 40))
            if count == 0:
                self.summary.set_text("All clean")
            else:
                sessions = len(self.store.orphans)
                self.summary.set_text(
                    f"{count} leftover process{'es' if count != 1 else ''} from "
                    f"{sessions} closed session{'s' if sessions != 1 else ''} · "
                    f"{format_bytes(self.store.orphan_memory)}"
                )

            self._set_badge("leftover", count)
            self._set_badge("sessions", len(self.store.idle_sessions_list()))
            self._sync_tabs()
            self._rebuild_leftovers()
            self._rebuild_sessions()
            self._rebuild_protected_list()
            self._rebuild_footer()
        finally:
            self._building = False

    def _set_badge(self, key: str, count: int) -> None:
        badge = self.tab_badges.get(key)
        if not badge:
            return
        if count > 0:
            badge.set_text(str(count))
            badge.show()
        else:
            badge.hide()

    def _sync_tabs(self) -> None:
        for key, btn in self.tab_buttons.items():
            ctx = btn.get_style_context()
            if key == self._tab:
                ctx.add_class("active")
            else:
                ctx.remove_class("active")
        self.stack.set_visible_child_name(self._tab)

    def _rebuild_footer(self) -> None:
        for child in list(self.footer_actions.get_children()):
            self.footer_actions.remove(child)

        if self.store.freed and self._tab == "leftover":
            self.footer_meta.set_text(
                f"Freed {format_bytes(self.store.freed.bytes)} · "
                f"{self.store.freed.count} process"
                f"{'es' if self.store.freed.count != 1 else ''} killed"
            )
            self.footer_meta.get_style_context().remove_class("footer-meta")
            self.footer_meta.get_style_context().add_class("footer-success")
        else:
            self.footer_meta.get_style_context().remove_class("footer-success")
            self.footer_meta.get_style_context().add_class("footer-meta")
            if self.store.last_scan:
                ago = max(0, int(time.time() - self.store.last_scan))
                self.footer_meta.set_text(f"Updated {human_age(ago)} ago")
            else:
                self.footer_meta.set_text("Scanning…")

        if self._confirm_kill_all and self._tab == "leftover":
            killable = self.store.killable_orphans()
            self.footer_meta.set_text(
                f"Kill {len(killable)} processes and free {format_bytes(sum(p.memory for p in killable))}?"
            )
            self.footer_actions.pack_start(
                self._pill("Cancel", "pill-muted", lambda *_: self._set_confirm(False)),
                False,
                False,
                0,
            )
            self.footer_actions.pack_start(
                self._pill("Kill them", "pill-red-filled", self._do_kill_all),
                False,
                False,
                0,
            )
        else:
            if self._tab == "leftover" and self.store.killable_orphans():
                self.footer_actions.pack_start(
                    self._pill("Kill all leftovers", "pill-red", lambda *_: self._set_confirm(True)),
                    False,
                    False,
                    0,
                )
            self.footer_actions.pack_start(
                self._pill("Quit", "pill-muted", self._quit),
                False,
                False,
                0,
            )
        self.footer_actions.show_all()

    def _rebuild_leftovers(self) -> None:
        self._clear(self.leftover_box)
        if not self.store.orphans:
            self.leftover_box.pack_start(self._clean_view(), True, True, 0)
        else:
            for group in self.store.orphans:
                self.leftover_box.pack_start(self._group_card(group), False, False, 0)
        self.leftover_box.show_all()

    def _rebuild_sessions(self) -> None:
        self._clear(self.sessions_box)
        idle = self.store.idle_sessions_list()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.set_margin_start(12)
        toolbar.set_margin_end(12)
        toolbar.set_margin_top(4)
        toolbar.set_margin_bottom(8)
        label = Gtk.Label(
            label=f"Idle limit {format_limit(self.store.settings.idle_limit_minutes)}",
            xalign=0,
        )
        label.get_style_context().add_class("card-subtitle")
        toolbar.pack_start(label, True, True, 0)
        end_idle = self._pill(
            f"End idle ({len(idle)})",
            "pill-red" if idle else "pill-muted",
            lambda *_: self.store.kill_idle_sessions(),
        )
        end_idle.set_sensitive(bool(idle))
        toolbar.pack_end(end_idle, False, False, 0)
        self.sessions_box.pack_start(toolbar, False, False, 0)

        if not self.store.sessions:
            empty = self._empty_block(
                "No open sessions",
                "No Claude Code process is running right now.",
            )
            self.sessions_box.pack_start(empty, True, True, 40)
        else:
            for session in self.store.sessions:
                self.sessions_box.pack_start(self._session_card(session), False, False, 0)
        self.sessions_box.show_all()

    def _rebuild_protected_list(self) -> None:
        if not hasattr(self, "protected_list"):
            return
        self._clear(self.protected_list)
        for pattern in self.store.settings.protected_patterns:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            lock = Gtk.Label(label="🔒")
            name = Gtk.Label(label=pattern, xalign=0)
            name.get_style_context().add_class("cmd")
            row.pack_start(lock, False, False, 0)
            row.pack_start(name, True, True, 0)
            rm = self._pill("Remove", "pill-muted", lambda *_ , p=pattern: self._remove_protected(p))
            row.pack_end(rm, False, False, 0)
            self.protected_list.pack_start(row, False, False, 0)
        self.protected_list.show_all()

    def _clean_view(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_top(40)
        box.set_margin_bottom(40)

        just_cleaned = self.store.freed is not None
        img = Gtk.Image.new_from_pixbuf(pixbuf("open" if just_cleaned else "closed", 132))
        box.pack_start(img, False, False, 0)

        if self.store.freed:
            hero = Gtk.Label(label=f"Freed {format_bytes(self.store.freed.bytes)}")
            hero.get_style_context().add_class("freed-hero")
            detail = Gtk.Label(
                label=(
                    f"{self.store.freed.count} process"
                    f"{'es' if self.store.freed.count != 1 else ''} killed. "
                    "Nothing left running."
                )
            )
            detail.get_style_context().add_class("clean-detail")
            box.pack_start(hero, False, False, 4)
            box.pack_start(detail, False, False, 0)
            # Snap doll shut after a beat
            def close_doll():
                img.set_from_pixbuf(pixbuf("closed", 132))
                return False

            from gi.repository import GLib

            GLib.timeout_add(900, close_doll)
        else:
            title = Gtk.Label(label="No leftover processes")
            title.get_style_context().add_class("clean-title")
            detail = Gtk.Label(
                label="Nothing started by a closed Claude Code session is still running."
            )
            detail.set_line_wrap(True)
            detail.set_max_width_chars(42)
            detail.set_justify(Gtk.Justification.CENTER)
            detail.get_style_context().add_class("clean-detail")
            box.pack_start(title, False, False, 4)
            box.pack_start(detail, False, False, 0)
        return box

    def _empty_block(self, title: str, detail: str) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_halign(Gtk.Align.CENTER)
        t = Gtk.Label(label=title)
        t.get_style_context().add_class("clean-title")
        d = Gtk.Label(label=detail)
        d.set_line_wrap(True)
        d.get_style_context().add_class("clean-detail")
        box.pack_start(t, False, False, 0)
        box.pack_start(d, False, False, 0)
        return box

    # --- cards ------------------------------------------------------------------

    def _group_card(self, group: SessionGroup) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.get_style_context().add_class("session-card")

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.set_margin_start(10)
        head.set_margin_end(10)
        head.set_margin_top(8)
        head.set_margin_bottom(8)

        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=group.title or group.project, xalign=0)
        title.get_style_context().add_class("card-title")
        title.set_ellipsize(Pango.EllipsizeMode.END)
        parts = []
        if group.title:
            parts.append(group.project)
        parts.append(group.short_id)
        parts.append(f"{len(group.procs)} process{'es' if len(group.procs) != 1 else ''}")
        parts.append(format_bytes(group.memory))
        sub = Gtk.Label(label=" · ".join(parts), xalign=0)
        sub.get_style_context().add_class("card-subtitle")
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        titles.pack_start(title, False, False, 0)
        titles.pack_start(sub, False, False, 0)
        head.pack_start(titles, True, True, 0)

        killable = [p for p in group.procs if not self.store.is_protected(p)]
        if killable:
            btn = self._pill(
                f"Kill {len(killable)}",
                "pill-red",
                lambda *_ , g=group: self.store.kill_session(g),
            )
            head.pack_end(btn, False, False, 0)
        card.pack_start(head, False, False, 0)
        card.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        for proc in group.procs:
            card.pack_start(self._proc_row(proc), False, False, 0)
        return card

    def _session_card(self, session: RunningSession) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.get_style_context().add_class("session-card")

        idle = session.idle_seconds()
        if session.status == "idle" and idle is not None:
            state = f"idle {human_age(idle)}"
        elif session.status == "busy":
            state = "working"
        else:
            state = session.status

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.set_margin_start(10)
        head.set_margin_end(10)
        head.set_margin_top(8)
        head.set_margin_bottom(8)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=session.title or session.project, xalign=0)
        title.get_style_context().add_class("card-title")
        title.set_ellipsize(Pango.EllipsizeMode.END)
        sub = Gtk.Label(
            label=(
                f"{state} · open {human_age(session.process.age_s)} · "
                f"{format_bytes(session.memory)} · {len(session.procs)} bg"
            ),
            xalign=0,
        )
        sub.get_style_context().add_class("card-subtitle")
        titles.pack_start(title, False, False, 0)
        titles.pack_start(sub, False, False, 0)
        head.pack_start(titles, True, True, 0)
        head.pack_end(
            self._pill("End session", "pill-red", lambda *_ , s=session: self.store.kill_running(s)),
            False,
            False,
            0,
        )
        card.pack_start(head, False, False, 0)

        if session.procs:
            card.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
            for proc in session.procs:
                card.pack_start(self._proc_row(proc), False, False, 0)
        return card

    def _proc_row(self, proc: Proc) -> Gtk.Box:
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        wrap.get_style_context().add_class("proc-row")

        row = Gtk.EventBox()
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        inner.set_margin_start(10)
        inner.set_margin_end(8)
        inner.set_margin_top(6)
        inner.set_margin_bottom(6)

        age = Gtk.Label(label=human_age(proc.age_s), xalign=0)
        age.set_width_chars(3)
        age.get_style_context().add_class("age")
        inner.pack_start(age, False, False, 0)

        if proc.ports:
            port = proc.ports[0]
            chip_text = f":{port}" if len(proc.ports) == 1 else f":{port} +{len(proc.ports) - 1}"
            chip = Gtk.Label(label=chip_text)
            chip.get_style_context().add_class("port-chip")
            inner.pack_start(chip, False, False, 0)

        cmd = Gtk.Label(label=proc.short_command, xalign=0)
        cmd.get_style_context().add_class("cmd")
        cmd.set_ellipsize(Pango.EllipsizeMode.END)
        inner.pack_start(cmd, True, True, 0)

        mem = Gtk.Label(label=format_bytes(proc.memory), xalign=1)
        mem.get_style_context().add_class("mem")
        if proc.memory >= 500 * 1024 * 1024:
            mem.get_style_context().add_class("mem-heavy")
        inner.pack_start(mem, False, False, 0)

        protected = self.store.is_protected(proc)
        killing = proc.pid in self.store.killing
        if protected:
            lock = Gtk.Label(label="🔒")
            lock.set_tooltip_text("Protected")
            inner.pack_end(lock, False, False, 0)
        elif not killing:
            kill = Gtk.Button(label="✕")
            kill.get_style_context().add_class("icon-kill")
            kill.set_relief(Gtk.ReliefStyle.NONE)
            kill.set_tooltip_text("Kill this process")
            kill.connect("clicked", lambda *_ , p=proc: self.store.kill([p]))
            inner.pack_end(kill, False, False, 0)

        row.add(inner)
        row.connect("button-press-event", self._toggle_expand, proc.pid)
        wrap.pack_start(row, False, False, 0)

        if proc.pid in self._expanded:
            wrap.pack_start(self._proc_details(proc), False, False, 0)
        return wrap

    def _proc_details(self, proc: Proc) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(28)
        box.set_margin_end(10)
        box.set_margin_bottom(8)
        self._detail(box, "PID", f"{proc.pid}  parent {proc.ppid}")
        self._detail(box, "Memory", format_bytes(proc.memory))
        if proc.helpers:
            self._detail(box, "Helpers", f"{len(proc.helpers)} helper processes")
        if proc.ports:
            self._detail(box, "Ports", ", ".join(proc.ports))
        if proc.cwd:
            home = str(Path.home())
            cwd = "~" + proc.cwd[len(home) :] if proc.cwd.startswith(home) else proc.cwd
            self._detail(box, "Folder", cwd)
        self._detail(box, "Command", proc.command)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if self.store.is_protected(proc):
            actions.pack_start(
                self._pill("Unprotect", "pill-muted", lambda *_ , p=proc: self._unprotect(p)),
                False,
                False,
                0,
            )
        else:
            actions.pack_start(
                self._pill(
                    f"Protect {proc.executable}",
                    "pill-muted",
                    lambda *_ , p=proc: self._protect(p),
                ),
                False,
                False,
                0,
            )
        actions.pack_end(
            self._pill("Kill", "pill-red", lambda *_ , p=proc: self.store.kill([p])),
            False,
            False,
            0,
        )
        box.pack_start(actions, False, False, 4)
        return box

    def _detail(self, parent: Gtk.Box, label: str, value: str) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        l = Gtk.Label(label=label, xalign=0)
        l.set_width_chars(8)
        l.get_style_context().add_class("detail-label")
        v = Gtk.Label(label=value, xalign=0)
        v.get_style_context().add_class("detail-value")
        v.set_line_wrap(True)
        v.set_selectable(True)
        row.pack_start(l, False, False, 0)
        row.pack_start(v, True, True, 0)
        parent.pack_start(row, False, False, 0)

    # --- helpers / handlers -----------------------------------------------------

    def _pill(self, label: str, style: str, callback) -> Gtk.Button:
        btn = Gtk.Button(label=label)
        btn.get_style_context().add_class("pill")
        btn.get_style_context().add_class(style)
        btn.connect("clicked", callback)
        return btn

    def _clear(self, box: Gtk.Box) -> None:
        for child in list(box.get_children()):
            box.remove(child)

    def _on_tab(self, _btn, key: str) -> None:
        self._tab = key
        self._confirm_kill_all = False
        self._sync_tabs()
        self._rebuild_footer()

    def _toggle_expand(self, _widget, event, pid: int):
        if getattr(event, "button", 1) != 1:
            return False
        if pid in self._expanded:
            self._expanded.remove(pid)
        else:
            self._expanded.add(pid)
        self.rebuild()
        return True

    def _set_confirm(self, value: bool) -> None:
        self._confirm_kill_all = value
        self._rebuild_footer()

    def _do_kill_all(self, *_args) -> None:
        self._confirm_kill_all = False
        self.store.kill_all_orphans()

    def _on_interval(self, combo: Gtk.ComboBoxText) -> None:
        active = combo.get_active_id()
        if not active:
            return
        self.store.settings.refresh_interval = int(active)
        self.store.save_settings()

    def _on_idle_limit(self, combo: Gtk.ComboBoxText) -> None:
        active = combo.get_active_id()
        if not active:
            return
        self.store.settings.idle_limit_minutes = int(active)
        self.store.save_settings()
        self.rebuild()

    def _on_auto_idle(self, button: Gtk.CheckButton) -> None:
        self.store.settings.ends_idle_sessions = button.get_active()
        self.store.save_settings()
        if button.get_active():
            self.store.refresh()

    def _on_add_protected(self, *_args) -> None:
        pattern = self.protected_entry.get_text().strip()
        if not pattern:
            return
        if pattern not in self.store.settings.protected_patterns:
            self.store.settings.protected_patterns.append(pattern)
            self.store.save_settings()
        self.protected_entry.set_text("")
        self.rebuild()

    def _remove_protected(self, pattern: str) -> None:
        self.store.settings.protected_patterns = [
            p for p in self.store.settings.protected_patterns if p != pattern
        ]
        self.store.save_settings()
        self.rebuild()

    def _protect(self, proc: Proc) -> None:
        self.store.protect(proc)
        self.rebuild()

    def _unprotect(self, proc: Proc) -> None:
        self.store.unprotect(proc)
        self.rebuild()

    def _quit(self, *_args) -> None:
        if self.on_quit:
            self.on_quit()
        else:
            Gtk.main_quit()

    def _on_close(self, *_args):
        self.hide()
        return True
