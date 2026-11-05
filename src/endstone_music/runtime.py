"""Music lifecycle, administration, and gameplay integration."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

from endstone import Player
from endstone.event import PlayerInteractEvent
from endstone.form import ActionForm, ModalForm, TextInput, Toggle, Slider

from .audio_adapter import SoundAdapter, player_key
from .jukebox import JukeboxController, block_key
from .library import Library, Track, atomic_json
from .playback import PlaybackEngine, Position
from .playlists import PlaylistStore


class MusicRuntime:
    def _enable_music(self):
        self._music_enabled = True
        self._music_epoch = object()
        self._join_sessions = {}
        self._click_times = {}
        self._pending_box_bindings = {}
        self._generation = None
        self._generation_poll = None
        self._audio_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="music-pack")
        self.audio_adapter = SoundAdapter(self.server, self.logger)
        if not self.audio_adapter.supported:
            self.logger.warning(self.audio_adapter.identity + "; playback disabled until a supported 26.60 runtime is used")
        self._load_library()
        self.playback = PlaybackEngine(self.server, self.audio_adapter, self.logger)
        self.setup_music()
        self.jukebox_controller = JukeboxController(self, self.library, self.playback, self.data_path / "jukeboxes.json")
        self._music_task = self.server.scheduler.run_task(self, self._music_tick, delay=1, period=5)
        self.logger.info(f"26.60 music hooks ready: {len(self.library.tracks)} tracks, {len(self.library.discs)} discs/albums")

    def _load_library(self):
        path = self.data_path / "generated_tracks.json"
        generated = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        self.library = Library(self.cmusic_config, generated)

    def _reload_music(self):
        if self._generation is not None and not self._generation.done():
            raise ValueError("Wait for resource-pack generation before reloading")
        previous = self.cmusic_config
        try:
            self.load_config()
            path = self.data_path / "generated_tracks.json"
            generated = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
            library = Library(self.cmusic_config, generated)
            playlists = PlaylistStore(self.data_path / "playlists.json")
        except Exception:
            self.cmusic_config = previous
            raise
        self.music.stop()
        self.playback.close()
        self._music_epoch = object()
        self._join_sessions.clear()
        self.playlists = playlists
        self.library = library
        self.jukebox_controller = JukeboxController(self, library, self.playback, self.data_path / "jukeboxes.json")

    def _music_tick(self):
        try:
            self._operator_tick()
            self.jukebox_controller.tick()
            self.playback.tick()
        except Exception as error:
            self.logger.error(f"Music tick failed: {error}")

    def on_disable(self):
        self._music_enabled = False
        self._music_epoch = object()
        for task in (getattr(self, "_music_task", None), getattr(self, "_generation_poll", None)):
            if task is not None:
                self.server.scheduler.cancel_task(task.task_id)
        if hasattr(self, "generator"):
            self.generator.cancel()
        if hasattr(self, "playback"):
            self.shutdown_music()
            self.playback.close()
        if hasattr(self, "_audio_worker"):
            self._audio_worker.shutdown(wait=False, cancel_futures=True)
        self._join_sessions = {}
        self._click_times = {}
        self._pending_box_bindings = {}

    def _start_generation(self, sender):
        if self._generation is not None:
            sender.send_message("§eA resource pack is already being generated.")
            return True
        server_root = self.data_path.parent.parent.absolute()
        if not (server_root / "worlds").is_dir():
            server_root = Path.cwd()
        worlds_dir = server_root / "worlds"
        world_name = self.cmusic_config.get("target_world_name", "Bedrock level")
        if Path(world_name).name != world_name or world_name in (".", ".."):
            raise ValueError("target_world_name must be a single directory name")
        world = next((p for p in worlds_dir.iterdir() if p.is_dir() and p.name.casefold() == world_name.casefold()), None) if worlds_dir.is_dir() else None
        if world is None:
            sender.send_message(f"§cWorld '{world_name}' was not found in {worlds_dir}")
            return False
        # Validate the pack stack before conversion or replacing any generated pack.
        stack = world / "world_resource_packs.json"
        if stack.exists():
            entries = json.loads(stack.read_text(encoding="utf-8-sig"))
            if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
                raise ValueError("Invalid world_resource_packs.json; existing pack stack was preserved")
        config = deepcopy(self.cmusic_config)
        epoch = self._music_epoch
        sender_name = sender.name if isinstance(sender, Player) else None

        def generate():
            sounds = self.generator.generate(self.upload_dir, world / "resource_packs",
                                             config.get("pack_name", "Endstone Music Pack"),
                                             self.playlists.data["playlists"], jukeboxes=self.library.jukeboxes)
            atomic_json(self.data_path / "sounds_registry.json", sounds)
            atomic_json(self.data_path / "global_sounds_registry.json", sounds)
            atomic_json(self.data_path / "generated_tracks.json", self.generator.tracks)
            self.generator.install_to_world(worlds_dir, world.name)
            return sounds

        self._generation = self._audio_worker.submit(generate)
        sender.send_message("§eGenerating stereo and positional music assets in the background...")

        def poll():
            if not self._music_enabled or self._music_epoch is not epoch:
                return
            if not self._generation.done():
                return
            self.server.scheduler.cancel_task(self._generation_poll.task_id)
            self._generation_poll = None
            recipient = self.server.get_player(sender_name) if sender_name is not None else self.server.command_sender
            try:
                sounds = self._generation.result()
                self._generation = None
                self._reload_music()
                message = f"§aPack generated with {len(sounds)} sound events. Restart the server and reconnect clients to load it."
            except Exception as error:
                self._generation = None
                self.logger.error(f"Music pack generation failed: {error}")
                message = f"§cMusic pack generation failed: {error}"
            if recipient is not None:
                recipient.send_message(message)

        self._generation_poll = self.server.scheduler.run_task(self, poll, delay=10, period=10)
        return True

    def _runtime_command(self, sender, args):
        if not self.require_operator(sender):
            return True
        if not args:
            return None
        action = args[0].lower()
        if action == "status":
            sender.send_message(f"Music {self.version}: {self.audio_adapter.identity}; adapter supported={self.audio_adapter.supported}")
            sender.send_message(f"Tracks={len(self.library.tracks)}, discs/albums={len(self.library.discs)}, inserted discs={len(self.jukebox_controller.entries)}")
            sender.send_message(f"26.60 playback packets adapted={self.audio_adapter.rewritten_packets}, rejected layouts={self.audio_adapter.rejected_packets}")
            session = self.music.session
            sender.send_message(f"Global playlist: {session['name']} (track {session['index'] + 1})" if session else "Global playlist: stopped")
            return True
        if action in ("generate", "migrate"):
            return self._start_generation(sender)
        if action == "reload":
            self._reload_music()
            sender.send_message("§aMusic configuration reloaded.")
            return True
        if action == "give":
            if len(args) < 2:
                sender.send_message("§eUsage: /cmusic give <disc-or-album-id> [player name]")
                return True
            target = self.server.get_player(" ".join(args[2:])) if len(args) > 2 else sender if isinstance(sender, Player) else None
            if target is None:
                sender.send_message("§cAn online target player is required.")
            elif args[1] not in self.library.discs:
                sender.send_message("§cUnknown disc or album ID.")
            elif target.inventory.add_item(self.library.make_disc(args[1])):
                sender.send_message("§eThe target inventory is full.")
            else:
                sender.send_message(f"§aGave {args[1]} to {target.name}.")
            return True
        if action == "stop":
            self.music.stop()
            self.playback.sources.clear()
            self.playback.tick()
            sender.send_message("§aStopped plugin-owned music. Inserted discs remain ejectable.")
            return True
        if action == "bind" and isinstance(sender, Player):
            if len(args) != 2 or args[1] not in self.library.jukeboxes:
                sender.send_message("§eUsage: /cmusic bind <jukebox-preset-id>")
                return True
            self._pending_box_bindings[player_key(sender)] = args[1]
            sender.send_message("§aRight-click the block to assign this jukebox preset.")
            return True
        if action == "recover" and isinstance(sender, Player):
            self._recover_menu(sender)
            return True
        return None

    def _interact_music(self, event):
        if event.action not in (PlayerInteractEvent.Action.RIGHT_CLICK_AIR, PlayerInteractEvent.Action.RIGHT_CLICK_BLOCK):
            return
        player = event.player
        key = player_key(player)
        now = time.monotonic()
        if event.block is not None and key in self._pending_box_bindings:
            event.cancel()
            preset_id = self._pending_box_bindings[key]
            if str(event.block.type) != self.library.jukeboxes[preset_id]["block"]:
                player.send_message("§eClick a block matching that jukebox preset's block type.")
                return
            if block_key(event.block) in self.jukebox_controller.entries:
                player.send_message("§eEject the inserted disc before changing this jukebox's preset.")
                return
            config = deepcopy(self.cmusic_config)
            config.setdefault("jukebox_bindings", {})[block_key(event.block)] = preset_id
            self._save_library_config(config)
            del self._pending_box_bindings[key]
            player.send_message(f"§aAssigned jukebox preset {preset_id}.")
            return
        if event.block is not None:
            managed = block_key(event.block) in self.jukebox_controller.entries
            custom_disc = self.library.disc_from_item(event.item)
            accepts_disc = custom_disc is not None and any(preset["block"] == str(event.block.type) for preset in self.library.jukeboxes.values())
            if managed or accepts_disc:
                event.cancel()
                if now - self._click_times.get(key, 0) < 0.3:
                    return
                self._click_times[key] = now
                if not self.audio_adapter.supported and not managed:
                    player.send_message("§cThis music adapter requires BDS 26.60 / Endstone 0.11.15. See /cmusic status.")
                    return
                self.jukebox_controller.handle_interact(player, event.block)
                self.playback.tick()
                return
        if self.handle_music_interaction(event):
            return
        if self.music.session:
            return
        item_name = str(event.item.type).removeprefix("minecraft:") if event.item else ""
        block_name = str(event.block.type).removeprefix("minecraft:") if event.block else ""
        for index, trigger in enumerate(self.cmusic_config.get("triggers", [])):
            mode = trigger.get("mode", "item_block")
            item_match = trigger.get("item", "").removeprefix("minecraft:") in ("*", item_name)
            block_match = event.block is not None and trigger.get("block", "").removeprefix("minecraft:") == block_name
            matched = bool(item_name) and item_match if mode == "item_only" else block_match if mode == "block_only" else item_match and block_match
            if not matched or not trigger.get("sound"):
                continue
            if now - self._click_times.get(key, 0) < 0.3:
                return
            self._click_times[key] = now
            sound = trigger["sound"]
            track = self.library.tracks.get(sound)
            if track is None:
                duration = trigger.get("duration", 300)
                if trigger.get("loop") and "duration" not in trigger:
                    player.send_message("§eSet this trigger's duration before enabling looping.")
                    return
                track = Track(sound, sound, float(duration))
            personal = mode == "item_only"
            broadcast = bool(trigger.get("broadcast", False))
            position = None if personal else Position.of(event.block.location)
            listener = ("*" if broadcast else key) if personal else None if broadcast else key
            source_id = f"trigger:{index}:" + ("global" if personal and broadcast else block_key(event.block) if broadcast else key)
            self.playback.start(source_id, (track,), position=position, listener=listener,
                                radius=trigger.get("distance", 50), volume=trigger.get("volume", 1),
                                pitch=trigger.get("pitch", 1), loop=trigger.get("loop", False),
                                follow_player=trigger.get("follow_player", True))
            self.playback.tick()
            if trigger.get("message"):
                player.send_message(trigger["message"])
            break

    def _join_music(self, player):
        key = player_key(player)
        token = object()
        self._join_sessions[key] = token
        epoch, name = self._music_epoch, player.name

        def play_join():
            if not self._music_enabled or self._music_epoch is not epoch or self._join_sessions.get(key) is not token:
                return
            current = self.server.get_player(name)
            if current is None or player_key(current) != key:
                return
            if self.music.session:
                return
            config = self.cmusic_config.get("player_join_sounds", {}).get(name)
            if config is None:
                config = self.cmusic_config.get("join_sound", {})
                if not config.get("enabled", False):
                    return
            elif not config.get("enabled", True):
                return
            try:
                sound = config.get("sound", "music.game.creative")
                duration = float(config.get("duration", 15))
                track = self.library.tracks.get(sound, Track(sound, sound, duration))
                self.playback.start("join:" + key, (track,), listener=key,
                                    volume=config.get("volume", 1), pitch=config.get("pitch", 1), duration=duration)
                self.playback.tick()
            except Exception as error:
                self.logger.warning(f"Join music failed for {name}: {error}")

        self.server.scheduler.run_task(self, play_join, delay=20)

    def send_disc_menu(self, player):
        if not self.require_operator(player):
            return
        form = ActionForm(title="Album and Single-Track Discs", content="Create playlists or give a configured disc to yourself.")
        form.add_button("Create album / single-track disc", on_click=self.send_create_disc_form)
        for disc_id, disc in self.library.discs.items():
            form.add_button(f"{disc.title} ({len(disc.tracks)} tracks)", on_click=lambda p, key=disc_id: self._runtime_command(p, ["give", key]))
        form.add_button("Recover inserted discs", on_click=self._recover_menu)
        player.send_form(form)

    def send_create_disc_form(self, player):
        if not self.require_operator(player):
            return
        available = ", ".join(self.library.tracks)

        def submit(p, response):
            if not self.require_operator(p):
                return
            try:
                values = json.loads(response)
                disc_id, title = str(values[0]).strip(), str(values[1]).strip()
                tracks = [value.strip() for value in str(values[2]).split(",") if value.strip()]
                config = deepcopy(self.cmusic_config)
                config.setdefault("discs", {}).pop(disc_id, None)
                config.setdefault("albums", {})[disc_id] = {"title": title or disc_id, "tracks": tracks, "loop": bool(values[3]), "item": str(values[4]).strip()}
                self._save_library_config(config)
                p.send_message("§aDisc saved. Select it in Albums & Discs to receive an item.")
            except Exception as error:
                p.send_message(f"§cCould not save disc: {error}")

        player.send_form(ModalForm(title="Create Album / Single Disc", controls=[
            TextInput(label="Unique ID", placeholder="my_album"), TextInput(label="Title", placeholder="My Album"),
            TextInput(label="Ordered track IDs, separated by commas", placeholder=available[:200]),
            Toggle(label="Loop playlist", default_value=False), TextInput(label="Base item", default_value="minecraft:music_disc_cat"),
        ], on_submit=submit))

    def _save_library_config(self, config):
        if self._generation is not None and not self._generation.done():
            raise ValueError("Wait for pack generation to finish")
        generated_path = self.data_path / "generated_tracks.json"
        generated = json.loads(generated_path.read_text()) if generated_path.exists() else {}
        Library(config, generated)
        atomic_json(self.cmusic_config_file, config)
        self._reload_music()

    def send_jukebox_setup(self, player):
        if not self.require_operator(player):
            return
        form = ActionForm(title="Custom Jukebox Setups", content="Bind presets to individual blocks or create a new preset.")
        form.add_button("Create / edit preset", on_click=self._jukebox_setup_form)
        for name, preset in self.library.jukeboxes.items():
            form.add_button(f"Bind {name} ({preset['radius']:g} blocks)", on_click=lambda p, key=name: self._runtime_command(p, ["bind", key]))
        player.send_form(form)

    def _jukebox_setup_form(self, player):
        if not self.require_operator(player):
            return
        def submit(p, response):
            if not self.require_operator(p):
                return
            try:
                values = json.loads(response)
                config = deepcopy(self.cmusic_config)
                config.setdefault("jukeboxes", {})[str(values[0]).strip()] = {
                    "block": str(values[1]).strip(), "radius": values[2], "volume": values[3], "pitch": values[4],
                    "follow_player": bool(values[5]),
                }
                self._save_library_config(config)
                p.send_message("§aJukebox preset saved. Run /cmusic generate, then restart to apply its spatial sound range.")
            except Exception as error:
                p.send_message(f"§cCould not save jukebox preset: {error}")

        player.send_form(ModalForm(title="Custom Jukebox Setup", controls=[
            TextInput(label="Preset ID", default_value="default"), TextInput(label="Block ID", default_value="minecraft:jukebox"),
            Slider(label="Hearing radius", min=1, max=256, step=1, default_value=32),
            Slider(label="Volume", min=0, max=2, step=0.1, default_value=1),
            Slider(label="Pitch", min=0.25, max=2, step=0.05, default_value=1),
            Toggle(label="Follow listeners for the whole track or album (no fading)", default_value=True),
        ], on_submit=submit))

    def _recover_menu(self, player):
        if not self.require_operator(player):
            return
        form = ActionForm(title="Inserted Discs", content="Return a stored disc, including one in a removed or unloaded block.")
        for key, entry in self.jukebox_controller.entries.items():
            form.add_button(f"{entry['disc']} at {key}", on_click=lambda p, box=key: self.jukebox_controller.eject(p, box))
        if not self.jukebox_controller.entries:
            form.add_button("No inserted discs", on_click=lambda p: None)
        player.send_form(form)
