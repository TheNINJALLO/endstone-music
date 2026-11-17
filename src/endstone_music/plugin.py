
from pathlib import Path
import json

from endstone.plugin import Plugin
from endstone.event import event_handler, EventPriority, PlayerInteractEvent, PlayerJoinEvent, PlayerQuitEvent, BlockBreakEvent, PacketSendEvent
from endstone.command import Command, CommandSender
from endstone import ColorFormat, Player
from endstone.form import ActionForm, ModalForm, Dropdown, TextInput, Slider, Toggle

from endstone_music.pack_generator import PackGenerator, sound_stem
from endstone_music.runtime import MusicRuntime
from endstone_music.music_controls import MusicControls
from endstone_music.library import atomic_json

class EndstoneMusicPlugin(MusicRuntime, MusicControls, Plugin):
    version = "0.2.3"
    api_version = "0.11"
    
    commands = {
        "cmusic": {
            "description": "Manage custom music triggers and resource packs",
            "usages": ["/cmusic", "/cmusic <reload|generate|migrate|status|stop|next|playlists|recover>", "/cmusic <play|give|bind> <id: str>", "/cmusic give <id: str> <player: str>", "/cmusic playlist <create|delete> <id: str>", "/cmusic playlist add <id: str> <sound: str> [seconds: float]", "/cmusic playlist remove <id: str> <track: int>", "/cmusic playlist move <id: str> <from: int> <to: int>", "/cmusic playlist loop <id: str> <on|off>"],
            "permissions": ["endstone_music.command.cmusic"]
        }
    }
    
    permissions = {
        "endstone_music.command.cmusic": {
            "description": "Allows using the cmusic command",
            "default": "op"
        }
    }

    def on_enable(self):
        self.logger.info("EndstoneMusic is enabling...")
        self.data_path = Path(self.data_folder)
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.upload_dir = self.data_path / "uploads"
        self.upload_dir.mkdir(exist_ok=True)
        self.cmusic_config_file = self.data_path / "config.json"
        self.load_config()
        self.generator = PackGenerator(data_path=self.data_path, logger=self.logger)
        self._enable_music()
        self.register_events(self)

    def load_config(self):
        if not self.cmusic_config_file.exists():
            default_config = {
                "pack_name": "Endstone Music Pack",
                "target_world_name": "Bedrock level",
                "tracks": {},
                "albums": {},
                "discs": {},
                "jukeboxes": {"default": {"block": "minecraft:jukebox", "radius": 32, "volume": 1.0, "pitch": 1.0, "follow_player": True}},
                "join_sound": {
                    "enabled": False,
                    "sound": "music.game.creative",
                    "volume": 1.0,
                    "pitch": 1.0,
                    "duration": 15
                },
                "player_join_sounds": {},
                "triggers": [
                    {
                        "item": "minecraft:stick",
                        "block": "minecraft:grass_block",
                        "sound": "music.game.creative",
                        "volume": 1.0,
                        "pitch": 1.0,
                        "message": "Playing creative music!"
                    }
                ]
            }
            atomic_json(self.cmusic_config_file, default_config)
            self.cmusic_config = default_config
        else:
            with open(self.cmusic_config_file, "r", encoding="utf-8-sig") as f:
                config = json.load(f)
            if not isinstance(config, dict) or not isinstance(config.get("triggers", []), list):
                raise ValueError("Music configuration must be a JSON object containing a trigger list")
            self.cmusic_config = config

    def save_config(self):
        atomic_json(self.cmusic_config_file, self.cmusic_config)

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name == "cmusic":
            if not self.require_operator(sender):
                return True
            if not args and isinstance(sender, Player):
                self.send_main_menu(sender)
                return True

            if not args:
                sender.send_message(f"{ColorFormat.RED}Usage: /cmusic <status|reload|generate|give|bind|stop|recover>")
                return False
            
            try:
                if args[0].lower() in ("play", "next", "playlists", "playlist") or (args[0].lower() == "give" and len(args) == 2 and args[1] not in self.library.discs):
                    return self.music_command(sender, args)
                handled = self._runtime_command(sender, args)
                if handled is not None:
                    return handled
            except Exception as error:
                self.logger.error(f"Music command failed: {error}")
                sender.send_message(f"{ColorFormat.RED}{error}")
                return True

        return False

    def get_available_sounds(self) -> list[str]:
        sounds = {"music.game.creative", "music.game.survival", "music.record.cat", "random.levelup", "random.orb"}
        sounds.update(track.sound for track in self.library.tracks.values())
        registry_file = self.data_path / "sounds_registry.json"
        if registry_file.exists():
            try:
                registered = json.loads(registry_file.read_text(encoding="utf-8-sig"))
                if isinstance(registered, list):
                    sounds.update(sound for sound in registered if isinstance(sound, str))
            except (ValueError, OSError) as error:
                self.logger.warning(f"Could not read music sound registry: {error}")
        return sorted(sounds)

    def send_main_menu(self, player: Player):
        if not self.require_operator(player):
            return
        form = ActionForm(
            title="Music Plugin Menu",
            content="Choose an action:"
        )
        form.add_button("Albums & Discs", on_click=self.send_disc_menu)
        form.add_button("Global Playlists", on_click=self.send_playlists_menu)
        form.add_button("Custom Jukebox Setup", on_click=self.send_jukebox_setup)
        form.add_button("Playback Status", on_click=lambda p: self._runtime_command(p, ["status"]))
        form.add_button("Add New Trigger", icon="textures/ui/color_plus", on_click=self.send_add_trigger_form)
        form.add_button("Manage Triggers", icon="textures/ui/settings_glyph_color_2x", on_click=self.send_list_triggers_form)
        form.add_button("Join Sound Settings", icon="textures/ui/sound_glyph_color_2x", on_click=self.send_join_sound_form)
        form.add_button("Per-Player Join Sounds", icon="textures/ui/icon_multiplayer", on_click=self.send_player_join_sounds_menu)
        form.add_button("Generate Pack", icon="textures/ui/refresh", on_click=lambda p: p.perform_command("cmusic generate"))
        form.add_button("Reload Config", icon="textures/ui/redo", on_click=lambda p: p.perform_command("cmusic reload"))
        
        player.send_form(form)
    
    def send_join_sound_form(self, player: Player):
        if not self.require_operator(player):
            return
        sounds = self.get_available_sounds()
        join_config = self.cmusic_config.get("join_sound", {})
        
        # Find current sound index
        current_sound = join_config.get("sound", "music.game.creative")
        sound_index = sounds.index(current_sound) if current_sound in sounds else 0
        
        form = ModalForm(
            title="Join Sound Settings",
            controls=[
                Toggle(label="Enable Join Sound", default_value=join_config.get("enabled", False)),
                Dropdown(label="Sound", options=sounds, default_index=sound_index),
                Slider(label="Volume", min=0.0, max=2.0, step=0.1, default_value=join_config.get("volume", 1.0)),
                Slider(label="Pitch", min=0.5, max=2.0, step=0.1, default_value=join_config.get("pitch", 1.0)),
                Slider(label="Duration (seconds)", min=15.0, max=300.0, step=5.0, default_value=float(join_config.get("duration", 15)))
            ],
            on_submit=self.handle_join_sound_submit
        )
        player.send_form(form)
    
    def handle_join_sound_submit(self, player: Player, json_str: str):
        if not self.require_operator(player):
            return
        data = json.loads(json_str)
        # [enabled, sound_index, volume, pitch, duration]
        
        sounds = self.get_available_sounds()
        sound_choice = sounds[data[1]] if data[1] < len(sounds) else sounds[0]
        duration = int(data[4]) if len(data) > 4 else 15
        
        self.cmusic_config["join_sound"] = {
            "enabled": data[0],
            "sound": sound_choice,
            "volume": data[2],
            "pitch": data[3],
            "duration": duration
        }
        
        self.save_config()
        status = "enabled" if data[0] else "disabled"
        player.send_message(f"{ColorFormat.GREEN}Join sound {status}! Sound: {sound_choice}, Duration: {duration}s")
    
    def send_player_join_sounds_menu(self, player: Player):
        if not self.require_operator(player):
            return
        player_sounds = self.cmusic_config.get("player_join_sounds", {})
        
        form = ActionForm(
            title="Per-Player Join Sounds",
            content=f"Configured: {len(player_sounds)} player(s)"
        )
        
        form.add_button("Add Player Sound", icon="textures/ui/color_plus", on_click=self.send_add_player_sound_form)
        
        # List existing player sounds
        for player_name in player_sounds:
            config = player_sounds[player_name]
            label = f"{player_name}: {config.get('sound', 'unknown')}"
            form.add_button(label, on_click=lambda p, pn=player_name: self.send_player_sound_action_form(p, pn))
        
        form.add_button("« Back", on_click=self.send_main_menu)
        player.send_form(form)
    
    def send_add_player_sound_form(self, player: Player):
        if not self.require_operator(player):
            return
        sounds = self.get_available_sounds()
        
        form = ModalForm(
            title="Add Player Join Sound",
            controls=[
                TextInput(label="Player Name (exact)", placeholder="PlayerName", default_value=""),
                Dropdown(label="Sound", options=sounds, default_index=0),
                Slider(label="Volume", min=0.0, max=2.0, step=0.1, default_value=1.0),
                Slider(label="Pitch", min=0.5, max=2.0, step=0.1, default_value=1.0),
                Slider(label="Duration (seconds)", min=15.0, max=300.0, step=5.0, default_value=15.0)
            ],
            on_submit=self.handle_add_player_sound_submit
        )
        player.send_form(form)
    
    def handle_add_player_sound_submit(self, player: Player, json_str: str):
        if not self.require_operator(player):
            return
        data = json.loads(json_str)
        # [player_name, sound_index, volume, pitch, duration]
        
        target_player = data[0].strip()
        if not target_player:
            player.send_message(f"{ColorFormat.RED}Player name cannot be empty!")
            return
        
        sounds = self.get_available_sounds()
        sound_choice = sounds[data[1]] if data[1] < len(sounds) else sounds[0]
        duration = int(data[4]) if len(data) > 4 else 15
        
        if "player_join_sounds" not in self.cmusic_config:
            self.cmusic_config["player_join_sounds"] = {}
        
        self.cmusic_config["player_join_sounds"][target_player] = {
            "sound": sound_choice,
            "volume": data[2],
            "pitch": data[3],
            "duration": duration
        }
        
        self.save_config()
        player.send_message(f"{ColorFormat.GREEN}Join sound set for {target_player}: {sound_choice}, Duration: {duration}s")
    
    def send_player_sound_action_form(self, player: Player, target_player_name: str):
        if not self.require_operator(player):
            return
        player_sounds = self.cmusic_config.get("player_join_sounds", {})
        config = player_sounds.get(target_player_name, {})
        
        form = ActionForm(
            title=f"Player: {target_player_name}",
            content=f"Sound: {config.get('sound')}\n"
                    f"Volume: {config.get('volume', 1.0)}\n"
                    f"Pitch: {config.get('pitch', 1.0)}\n"
                    f"Duration: {config.get('duration', 15)}s"
        )
        
        form.add_button("Delete", icon="textures/ui/trash", on_click=lambda p: self.delete_player_sound(p, target_player_name))
        form.add_button("« Back", on_click=self.send_player_join_sounds_menu)
        
        player.send_form(form)
    
    def delete_player_sound(self, player: Player, target_player_name: str):
        if "player_join_sounds" in self.cmusic_config and target_player_name in self.cmusic_config["player_join_sounds"]:
            del self.cmusic_config["player_join_sounds"][target_player_name]
            self.save_config()
            player.send_message(f"{ColorFormat.GREEN}Removed join sound for {target_player_name}")
        else:
            player.send_message(f"{ColorFormat.RED}Player not found!")
        
        self.send_player_join_sounds_menu(player)
    
    def send_list_triggers_form(self, player: Player):
        if not self.require_operator(player):
            return
        triggers = self.cmusic_config.get("triggers", [])
        
        if not triggers:
            player.send_message(f"{ColorFormat.YELLOW}No triggers configured yet. Add one first!")
            return
        
        form = ActionForm(
            title="Manage Triggers",
            content=f"You have {len(triggers)} trigger(s). Select one to edit or delete:"
        )
        
        for i, trigger in enumerate(triggers):
            mode = trigger.get("mode", "item_block")
            sound = trigger.get("sound", "unknown")
            item = trigger.get("item", "*").replace("minecraft:", "")
            block = trigger.get("block", "*").replace("minecraft:", "")
            label = f"#{i+1}: {sound} ({mode})"
            form.add_button(label, on_click=lambda p, idx=i: self.send_trigger_action_form(p, idx))
        
        form.add_button("« Back", on_click=self.send_main_menu)
        player.send_form(form)
    
    def send_trigger_action_form(self, player: Player, trigger_index: int):
        if not self.require_operator(player):
            return
        triggers = self.cmusic_config.get("triggers", [])
        if trigger_index >= len(triggers):
            player.send_message(f"{ColorFormat.RED}Trigger not found!")
            return
        
        trigger = triggers[trigger_index]
        
        form = ActionForm(
            title=f"Trigger #{trigger_index + 1}",
            content=f"Sound: {trigger.get('sound')}\n"
                    f"Mode: {trigger.get('mode', 'item_block')}\n"
                    f"Item: {trigger.get('item')}\n"
                    f"Block: {trigger.get('block')}\n"
                    f"Volume: {trigger.get('volume', 1.0)}\n"
                    f"Pitch: {trigger.get('pitch', 1.0)}\n"
                    f"Broadcast: {trigger.get('broadcast', False)}\n"
                    f"Loop: {trigger.get('loop', False)}\n"
                    f"Follow player: {trigger.get('follow_player', True)}\n"
                    f"Message: {trigger.get('message', '')}"
        )
        
        form.add_button("Delete Trigger", icon="textures/ui/trash", on_click=lambda p: self.delete_trigger(p, trigger_index))
        form.add_button("« Back to List", on_click=self.send_list_triggers_form)
        
        player.send_form(form)
    
    def delete_trigger(self, player: Player, trigger_index: int):
        triggers = self.cmusic_config.get("triggers", [])
        if trigger_index < len(triggers):
            deleted = triggers.pop(trigger_index)
            self.save_config()
            player.send_message(f"{ColorFormat.GREEN}Trigger deleted: {deleted.get('sound')}")
        else:
            player.send_message(f"{ColorFormat.RED}Trigger not found!")
        
        # Go back to list
        self.send_list_triggers_form(player)

    def send_add_trigger_form(self, player: Player):
        if not self.require_operator(player):
            return
        sounds = self.get_available_sounds()
        
        default_item = "minecraft:stick"
        try:
            main_hand = player.inventory.item_in_main_hand
            if main_hand and main_hand.type:
                default_item = main_hand.type.id
        except:
            pass
        
        # Trigger modes
        trigger_modes = ["Item + Block (both required)", "Item Only (any click)", "Block Only (any item)"]
        
        form = ModalForm(
            title="Add Music Trigger",
            controls=[
                Dropdown(label="Trigger Mode", options=trigger_modes, default_index=0),
                TextInput(label="Trigger Item (ID)", placeholder="minecraft:stick", default_value=default_item),
                TextInput(label="Target Block (ID)", placeholder="minecraft:grass_block", default_value="minecraft:grass_block"),
                Dropdown(label="Sound", options=sounds, default_index=0),
                Slider(label="Volume", min=0.0, max=2.0, step=0.1, default_value=1.0),
                Slider(label="Pitch", min=0.5, max=2.0, step=0.1, default_value=1.0),
                Slider(label="Distance (blocks)", min=100.0, max=1000000.0, step=100.0, default_value=1000.0),
                Toggle(label="Play to Everyone (Broadcast)", default_value=False),
                Toggle(label="Loop Sound", default_value=False),
                TextInput(label="Message", placeholder="Optional message to player"),
                Slider(label="Duration in seconds (used if track duration is unknown)", min=1, max=3600, step=1, default_value=180),
                Toggle(label="Follow player for the whole track (no fading)", default_value=True)
            ],
            on_submit=self.handle_add_trigger_submit
        )
        player.send_form(form)

    def handle_add_trigger_submit(self, player: Player, json_str: str):
        if not self.require_operator(player):
            return
        data = json.loads(json_str)
        # [mode, item, block, sound_index, volume, pitch, distance, broadcast, loop, message]
        
        trigger_modes = ["item_block", "item_only", "block_only"]
        mode = trigger_modes[data[0]] if data[0] < len(trigger_modes) else "item_block"
        
        sounds = self.get_available_sounds()
        sound_choice = sounds[data[3]] if data[3] < len(sounds) else sounds[0]
        
        new_trigger = {
            "mode": mode,
            "item": data[1],
            "block": data[2],
            "sound": sound_choice,
            "volume": data[4],
            "pitch": data[5],
            "distance": data[6],
            "broadcast": data[7],
            "loop": data[8],
            "message": data[9],
            "duration": float(data[10]) if len(data) > 10 else 180.0,
            "follow_player": bool(data[11]) if len(data) > 11 else True
        }
        
        self.cmusic_config["triggers"].append(new_trigger)
        self.save_config()
        player.send_message(f"{ColorFormat.GREEN}Trigger added! Mode: {mode}, Sound: {sound_choice}, Distance: {data[6]}")

    @event_handler(priority=EventPriority.HIGHEST, ignore_cancelled=True)
    def on_player_interact(self, event: PlayerInteractEvent):
        try:
            self._interact_music(event)
        except Exception as error:
            self.logger.error(f"Music interaction failed: {error}")
            event.player.send_message("§cMusic interaction failed; check the server log.")

    @event_handler
    def on_player_join(self, event: PlayerJoinEvent):
        self._join_music(event.player)

    @event_handler
    def on_player_quit(self, event: PlayerQuitEvent):
        from endstone_music.audio_adapter import player_key
        key = player_key(event.player)
        self._join_sessions.pop(key, None)
        self._click_times.pop(key, None)
        self._pending_box_bindings.pop(key, None)
        self.music_clicks.pop(key, None)
        self.playback.quit(event.player)

    @event_handler(priority=EventPriority.HIGHEST, ignore_cancelled=True)
    def on_block_break(self, event: BlockBreakEvent):
        from endstone_music.jukebox import block_key
        key = block_key(event.block)
        if key not in self.jukebox_controller.entries:
            return
        try:
            if not self.jukebox_controller.eject(event.player, key):
                event.cancel()
        except Exception as error:
            event.cancel()
            self.logger.error(f"Cannot safely eject jukebox disc: {error}")
            event.player.send_message("§cCould not return the inserted disc. The block was kept intact.")

    @event_handler(priority=EventPriority.HIGHEST, ignore_cancelled=True)
    def on_packet_send(self, event: PacketSendEvent):
        self.audio_adapter.on_packet_send(event)
