"""Endstone adapter for the operator-only, server-wide music controller."""
from __future__ import annotations
import json
import time
from endstone import Player
from endstone.form import ActionForm, ModalForm, TextInput, Toggle
from endstone.inventory import ItemStack
from endstone_music.playlists import PlaylistStore, Playback
from endstone_music.pack_generator import GLOBAL_PREFIX

PERMISSION = "endstone_music.command.cmusic"
JUKEBOX = "endstone_music:jukebox"
ITEM_PREFIX = "endstone_music:playlist_"


def type_id(value):
    return (value.type.id if hasattr(value.type, "id") else str(value.type)) if value else ""


def block_key(block):
    return json.dumps([block.dimension.name, block.x, block.y, block.z], separators=(",", ":"))


class MusicControls:
    def setup_music(self):
        self.playlists = PlaylistStore(self.data_path / "playlists.json")
        self.global_listeners = {}
        self.music = Playback(self._play_global, self._stop_global)
        self.music_clicks = {}
        self.music_tick_count = 0
        self.music_task = self.server.scheduler.run_task(self, self._music_tick, delay=1, period=1)

    def require_operator(self, sender):
        if not sender.has_permission(PERMISSION):
            sender.send_message("Only music operators can control server-wide music.")
            return False
        return True

    def _play_global(self, track):
        self.legacy_generation += 1
        for task in self.legacy_join_tasks:
            task.cancel()
        self.legacy_join_tasks.clear()
        self.global_listeners = {}
        sound = GLOBAL_PREFIX + track["sound"]
        for player in self.server.online_players:
            self.stop_custom_sounds_for_player(player.name)
            player.play_sound(player.location, sound, track.get("volume", 1.0), track.get("pitch", 1.0))
            self.global_listeners[str(player.unique_id)] = player

    def _stop_global(self, sound):
        # Only the alias this session owns; no wildcard/category/global music stop.
        for player in list(self.global_listeners.values()):
            try:
                player.stop_sound(GLOBAL_PREFIX + sound)
            except RuntimeError:
                pass  # Player disconnected before stop.
        self.global_listeners.clear()

    def _music_tick(self):
        try:
            self.music_tick_count += 1
            if self.music_tick_count % 20 == 0:
                # Enumerate loaded chunks before block lookup; never load a chunk for music.
                for key in list(self.playlists.data["jukeboxes"]):
                    state = self.jukebox_state(key)
                    if state == "missing":
                        self.playlists.unbind(key)
                    if state != "present" and self.music.session and self.music.session["source"] == key:
                        self.music.stop()
            self.music.tick()
        except Exception as error:
            self.music.stop()
            self.logger.error(f"Global playback stopped: {error}")

    def shutdown_music(self):
        if hasattr(self, "music_task"):
            self.music_task.cancel()
        if hasattr(self, "music"):
            self.music.stop()
        if hasattr(self, "music_clicks"):
            self.music_clicks.clear()

    def start_playlist(self, sender, name, source=None):
        if not self.require_operator(sender):
            return
        if source is not None and (self.jukebox_state(source) != "present" or self.playlists.data["jukeboxes"].get(source) != name):
            raise ValueError("Jukebox was removed, unloaded or relinked; reopen its menu")
        playlist = self.playlists.data["playlists"].get(name)
        if playlist is None:
            raise ValueError("Playlist not found")
        registered = set(self.get_available_sounds())
        # Global playback supports generated 2D aliases only, never unverified vanilla IDs.
        generated = self.data_path / "global_sounds_registry.json"
        safe = set(json.loads(generated.read_text(encoding="utf-8"))) if generated.exists() else set()
        for track in playlist["tracks"]:
            if track["sound"] not in registered or track["sound"] not in safe:
                raise ValueError(f"Generate the resource pack before playing {track['sound']}; global playback needs its 2D alias")
        self.music.start(name, playlist, source)
        sender.send_message(f"Playing {name} for everyone. Late joiners enter at the next track.")

    def music_command(self, sender, args):
        action = args[0].lower()
        if action not in ("play", "stop", "next", "status", "playlists", "playlist", "give"):
            return False
        if not self.require_operator(sender):
            return True
        try:
            if action == "play" and len(args) == 2:
                self.start_playlist(sender, args[1])
            elif action == "stop" and len(args) == 1:
                self.music.stop()
                sender.send_message("Global music stopped.")
            elif action == "next" and len(args) == 1:
                self.music.next()
            elif action == "status":
                s = self.music.session
                sender.send_message(f"Playing {s['name']}, track {s['index'] + 1}: {s['track']['sound']}" if s else "Global music is stopped.")
            elif action == "playlists":
                if isinstance(sender, Player):
                    self.send_playlists_menu(sender)
                else:
                    sender.send_message("Playlists: " + ", ".join(self.playlists.data["playlists"]))
            elif action == "give" and len(args) == 2 and isinstance(sender, Player):
                item = JUKEBOX if args[1] == "jukebox" else ITEM_PREFIX + args[1]
                if args[1] != "jukebox" and args[1] not in self.playlists.data["playlists"]:
                    raise ValueError("Playlist not found")
                leftovers = sender.inventory.add_item(ItemStack(item, 1))
                sender.send_message("Inventory full; make space and retry." if leftovers else "Music item added. Playlist items work when used on a block; use on the custom jukebox to bind it.")
            elif action == "playlist":
                self.edit_playlist_command(sender, args[1:])
            else:
                raise ValueError("Usage: /cmusic play <id> | stop | next | status | playlists | give <id|jukebox>")
        except (ValueError, KeyError, TypeError, IndexError, RuntimeError) as error:
            sender.send_message(f"Music: {error}")
        return True

    def edit_playlist_command(self, sender, args):
        if len(args) < 2:
            raise ValueError("playlist create|add|remove|move|loop|delete <id> [arguments]")
        action, name = args[:2]
        existing = self.playlists.data["playlists"].get(name)
        if action == "create" and len(args) == 2:
            if existing is not None:
                raise ValueError("Playlist already exists")
            self.playlists.put(name, [], False)
        elif action == "delete" and len(args) == 2:
            self.playlists.delete(name)
            if self.music.session and self.music.session["name"] == name:
                self.music.stop()
        elif existing is not None:
            tracks = list(existing["tracks"])
            loop = existing["loop"]
            if action == "add" and len(args) in (3, 4):
                durations = self.track_durations()
                duration = float(args[3]) if len(args) == 4 else durations.get(args[2])
                tracks.append({"sound": args[2], "duration": duration, "volume": 1.0, "pitch": 1.0})
            elif action == "remove" and len(args) == 3:
                index = int(args[2]) - 1
                if not 0 <= index < len(tracks):
                    raise ValueError("Track number out of range")
                tracks.pop(index)
            elif action == "move" and len(args) == 4:
                first, last = int(args[2]) - 1, int(args[3]) - 1
                if not 0 <= first < len(tracks) or not 0 <= last < len(tracks):
                    raise ValueError("Track number out of range")
                tracks.insert(last, tracks.pop(first))
            elif action == "loop" and len(args) == 3 and args[2] in ("on", "off"):
                loop = args[2] == "on"
            else:
                raise ValueError("Invalid playlist edit arguments")
            self.playlists.put(name, tracks, loop)
        else:
            raise ValueError("Playlist not found")
        sender.send_message("Playlist saved. Active playback keeps its snapshot until restarted. Generate/restart packs for new custom item IDs.")

    def track_durations(self):
        path = self.data_path / "track_durations.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def send_playlists_menu(self, player):
        if not self.require_operator(player):
            return
        form = ActionForm(title="Global Music", content="Operator-only • all players • no distance fading with generated pack. Late joins wait for next track.")
        form.add_button("Create playlist", on_click=lambda p: self.send_playlist_editor(p))
        form.add_button("Stop global music", on_click=lambda p: self.music_command(p, ["stop"]))
        form.add_button("Next track", on_click=lambda p: self.music_command(p, ["next"]))
        form.add_button("Give custom jukebox", on_click=lambda p: self.music_command(p, ["give", "jukebox"]))
        for name in sorted(self.playlists.data["playlists"]):
            form.add_button(name, on_click=lambda p, n=name: self.send_playlist_actions(p, n))
        player.send_form(form)

    def send_playlist_actions(self, player, name, source=None):
        if not self.require_operator(player):
            return
        form = ActionForm(title=f"Playlist: {name}", content="Play starts a new server-wide session. Edit order in the playlist editor.")
        form.add_button("Play for everyone", on_click=lambda p: self.safe_start(p, name, source))
        form.add_button("Stop global music", on_click=lambda p: self.music_command(p, ["stop"]))
        form.add_button("Next track", on_click=lambda p: self.music_command(p, ["next"]))
        form.add_button("Edit playlist", on_click=lambda p: self.send_playlist_editor(p, name))
        form.add_button("Give playlist item", on_click=lambda p: self.music_command(p, ["give", name]))
        if source is not None:
            form.add_button("Unlink this jukebox", on_click=lambda p: self.unbind_jukebox(p, source))
        player.send_form(form)

    def safe_start(self, player, name, source=None):
        try:
            self.start_playlist(player, name, source)
        except (ValueError, RuntimeError) as error:
            player.send_message(f"Music: {error}")

    def send_playlist_editor(self, player, name=None):
        if not self.require_operator(player):
            return
        current = self.playlists.data["playlists"].get(name, {"tracks": [], "loop": False})
        encoded = "; ".join(f"{t['sound']}={t['duration']}" for t in current["tracks"])
        form = ModalForm(title="Playlist editor", controls=[TextInput(label="Playlist ID (lowercase letters, digits, underscores)", default_value=name or ""), TextInput(label="Ordered tracks: custom.song=seconds; custom.other=seconds (duration optional after generation)", default_value=encoded), Toggle(label="Loop playlist", default_value=current["loop"])], on_submit=lambda p, raw: self.save_playlist_form(p, raw, name))
        player.send_form(form)

    def save_playlist_form(self, player, raw, original):
        if not self.require_operator(player):
            return
        try:
            values = json.loads(raw)
            if values is None:
                return
            if not isinstance(values, list) or len(values) != 3 or type(values[2]) is not bool:
                raise ValueError("Invalid form response")
            name = values[0].strip()
            if original and name != original:
                raise ValueError("IDs cannot be renamed in this editor; create a new playlist")
            if not original and name in self.playlists.data["playlists"]:
                raise ValueError("That playlist already exists")
            durations = self.track_durations()
            tracks = []
            for entry in values[1].split(";"):
                if not entry.strip():
                    continue
                parts = entry.strip().split("=")
                if len(parts) > 2:
                    raise ValueError("Use sound=seconds separated by semicolons")
                sound = parts[0].strip()
                duration = float(parts[1]) if len(parts) == 2 else durations.get(sound)
                old_tracks = self.playlists.data["playlists"].get(original, {}).get("tracks", [])
                previous = next((t for t in old_tracks if t["sound"] == sound), {})
                tracks.append({"sound": sound, "duration": duration, "volume": previous.get("volume", 1.0), "pitch": previous.get("pitch", 1.0)})
            self.playlists.put(name, tracks, values[2])
            player.send_message("Playlist saved. Generate and restart the pack before giving a new playlist item.")
            self.send_playlist_actions(player, name)
        except (ValueError, TypeError, AttributeError) as error:
            player.send_message(f"Playlist unchanged: {error}")

    def handle_music_interaction(self, event):
        from endstone.event import PlayerInteractEvent
        if event.action not in (PlayerInteractEvent.Action.RIGHT_CLICK_AIR, PlayerInteractEvent.Action.RIGHT_CLICK_BLOCK):
            return False
        item, block = type_id(event.item), type_id(event.block)
        if not item.startswith(ITEM_PREFIX) and block != JUKEBOX:
            return False
        event.cancel()
        if not self.require_operator(event.player):
            return True
        # One accepted interaction per player per half-second, including duplicate packets.
        identity = str(event.player.unique_id)
        now = time.monotonic()
        if now - self.music_clicks.get(identity, -1e6) < .5:
            return True
        self.music_clicks[identity] = now
        name = item[len(ITEM_PREFIX):] if item.startswith(ITEM_PREFIX) else None
        if name and name not in self.playlists.data["playlists"]:
            event.player.send_message("This playlist no longer exists.")
            return True
        if block == JUKEBOX:
            key = block_key(event.block)
            if name:
                self.playlists.bind(key, name)
                event.player.send_message(f"Jukebox linked to {name}.")
            name = self.playlists.data["jukeboxes"].get(key)
            if name:
                self.send_playlist_actions(event.player, name, key)
            else:
                form = ActionForm(title="Link jukebox", content="Select a playlist. Only operators can control this block.")
                for candidate in sorted(self.playlists.data["playlists"]):
                    form.add_button(candidate, on_click=lambda p, n=candidate, k=key: self.bind_jukebox(p, k, n))
                event.player.send_form(form)
        elif name:
            self.safe_start(event.player, name)
        return True

    def bind_jukebox(self, player, key, name):
        if self.require_operator(player):
            try:
                if self.jukebox_state(key) != "present":
                    raise ValueError("Jukebox removed or unloaded; reopen its menu")
                self.playlists.bind(key, name)
                self.send_playlist_actions(player, name, key)
            except ValueError as error:
                player.send_message(str(error))

    def jukebox_state(self, key):
        dimension_name, x, y, z = json.loads(key)
        dimension = self.server.level.get_dimension(dimension_name)
        if dimension is None:
            return "unloaded"
        if not any(chunk.x == x // 16 and chunk.z == z // 16 for chunk in dimension.loaded_chunks):
            return "unloaded"
        return "present" if type_id(dimension.get_block_at(x, y, z)) == JUKEBOX else "missing"

    def unbind_jukebox(self, player, key):
        if not self.require_operator(player):
            return
        self.playlists.unbind(key)
        if self.music.session and self.music.session["source"] == key:
            self.music.stop()
        player.send_message("Jukebox unlinked.")
