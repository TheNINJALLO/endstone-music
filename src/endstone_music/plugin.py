
from pathlib import Path
import json
import os

from endstone.plugin import Plugin
from endstone.event import event_handler, EventPriority, PlayerInteractEvent, PlayerJoinEvent, PlayerQuitEvent, BlockBreakEvent
from endstone.command import Command, CommandSender
from endstone import ColorFormat, Player
from endstone.form import ActionForm, ModalForm, Dropdown, TextInput, Slider, Toggle

from endstone_music.pack_generator import PackGenerator
from endstone_music.playlists import atomic_json
from endstone_music.music_controls import MusicControls, block_key, JUKEBOX, type_id

class EndstoneMusicPlugin(MusicControls, Plugin):
    api_version = "0.11"
    
    commands = {
        "cmusic": {
            "description": "Manage custom music triggers and resource packs",
            "usages": ["/cmusic", "/cmusic <reload|generate|migrate|playlists|stop|next|status>", "/cmusic <play|give> <id: str>", "/cmusic <playlist> <create|delete> <id: str>", "/cmusic <playlist> <add> <id: str> <sound: str> [seconds: float]", "/cmusic <playlist> <remove> <id: str> <track: int>", "/cmusic <playlist> <move> <id: str> <from: int> <to: int>", "/cmusic <playlist> <loop> <id: str> <on|off>"],
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
        self.register_events(self)
        
        # Ensure data folder exists
        self.data_path = Path(self.data_folder)
        self.data_path.mkdir(parents=True, exist_ok=True)
        
        self.upload_dir = self.data_path / "uploads"
        self.upload_dir.mkdir(exist_ok=True)
        
        self.cmusic_config_file = self.data_path / "config.json"
        self.load_config()
        
        self.generator = PackGenerator(data_path=self.data_path)
        
        # Track currently playing custom sounds per player (player_name -> set of sound names)
        self.playing_sounds = {}
        self.legacy_sound_tokens = {}
        self.legacy_join_tasks = []
        self.legacy_generation = 0
        self.setup_music()

    def load_config(self):
        if not self.cmusic_config_file.exists():
            default_config = {
                "pack_name": "Endstone Music Pack",
                "target_world_name": "Bedrock level",
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
            with open(self.cmusic_config_file, "r") as f:
                self.cmusic_config = json.load(f)

    def save_config(self):
        atomic_json(self.cmusic_config_file, self.cmusic_config)

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name == "cmusic":
            if not self.require_operator(sender):
                return True
            if args and self.music_command(sender, args):
                return True
            if not args and isinstance(sender, Player):
                self.send_main_menu(sender)
                return True

            if not args:
                sender.send_message(f"{ColorFormat.RED}Usage: /cmusic <reload|generate>")
                return False
            
            action = args[0].lower()
            
            if action == "reload":
                try:
                    # Validate both files before disturbing the current session.
                    candidate = json.loads(self.cmusic_config_file.read_text(encoding="utf-8"))
                    if not isinstance(candidate, dict) or not isinstance(candidate.get("triggers", []), list):
                        raise ValueError("Invalid config structure")
                    self.playlists.reload()
                except (ValueError, OSError) as error:
                    sender.send_message(f"Reload failed; current music unchanged: {error}")
                    return True
                self.music.stop()
                self.legacy_generation += 1
                for task in self.legacy_join_tasks:
                    task.cancel()
                self.legacy_join_tasks.clear()
                self.cmusic_config = candidate
                sender.send_message(f"{ColorFormat.GREEN}Configuration reloaded!")
                return True
                
            if action == "generate":
                sender.send_message(f"{ColorFormat.YELLOW}Generating resource pack...")
                
                # Find server root
                server_root = self.data_path.parent.parent.absolute()
                if not (server_root / "worlds").exists():
                    server_root = Path(os.getcwd())
                
                worlds_dir = server_root / "worlds"
                world_name = self.cmusic_config.get("target_world_name", "Bedrock level")
                if not isinstance(world_name, str) or Path(world_name).name != world_name:
                    sender.send_message("Invalid target_world_name; must be a direct world folder name.")
                    return True
                
                # Find the world folder (case-insensitive search)
                target_world = None
                if worlds_dir.exists():
                    for child in worlds_dir.iterdir():
                        if child.is_dir() and not child.is_symlink() and child.name.lower() == world_name.lower():
                            target_world = child
                            break
                    # Exact match fallback
                    if not target_world and (worlds_dir / world_name).is_dir() and not (worlds_dir / world_name).is_symlink():
                        target_world = worlds_dir / world_name
                
                if not target_world:
                    sender.send_message(f"{ColorFormat.RED}Could not find world '{world_name}' in {worlds_dir}")
                    sender.send_message(f"{ColorFormat.RED}Please check your config.json target_world_name setting.")
                    return False
                
                # Resource packs go INSIDE the world folder
                resource_packs_dir = target_world / "resource_packs"
                resource_packs_dir.mkdir(parents=True, exist_ok=True)
                
                sender.send_message(f"{ColorFormat.GRAY}Using paths:")
                sender.send_message(f"{ColorFormat.GRAY}  World: {target_world}")
                sender.send_message(f"{ColorFormat.GRAY}  Resource packs: {resource_packs_dir}")
                
                try:
                    sounds = self.generator.generate(
                        self.upload_dir, resource_packs_dir,
                        self.cmusic_config.get("pack_name", "Music Pack"),
                        self.playlists.data["playlists"]
                    )
                except Exception as error:
                    self.logger.error(f"Pack generation failed: {error}")
                    sender.send_message(f"Pack generation failed; uploads retained: {error}")
                    return True
                
                sender.send_message(f"{ColorFormat.GREEN}Pack generated with {len(sounds)} sounds!")
                
                # Save sounds registry for dropdown
                registry_file = self.data_path / "sounds_registry.json"
                atomic_json(registry_file, sounds)
                atomic_json(self.data_path / "global_sounds_registry.json", sounds)
                
                # Update world_resource_packs.json
                try:
                    installed = self.generator.install_to_world(worlds_dir, world_name)
                except (ValueError, OSError) as error:
                    sender.send_message(f"Packs generated but world activation failed: {error}. Check backups before restarting.")
                    return True
                if installed:
                    sender.send_message(f"{ColorFormat.GREEN}Installed to world '{world_name}'. Please RESTART the server.")
                else:
                    sender.send_message(f"{ColorFormat.YELLOW}Pack created but could not update world_resource_packs.json automatically.")
                    
                return True
            
            if action == "migrate":
                sender.send_message(f"{ColorFormat.YELLOW}Migrating existing sounds to 'neutral' category...")
                
                # Find server root and world
                server_root = self.data_path.parent.parent.absolute()
                if not (server_root / "worlds").exists():
                    server_root = Path(os.getcwd())
                
                worlds_dir = server_root / "worlds"
                world_name = self.cmusic_config.get("target_world_name", "Bedrock level")
                if not isinstance(world_name, str) or Path(world_name).name != world_name:
                    sender.send_message("Invalid target_world_name; must be a direct world folder name.")
                    return True
                
                # Find the world folder
                target_world = None
                if worlds_dir.exists():
                    for child in worlds_dir.iterdir():
                        if child.is_dir() and not child.is_symlink() and child.name.lower() == world_name.lower():
                            target_world = child
                            break
                    if not target_world and (worlds_dir / world_name).is_dir() and not (worlds_dir / world_name).is_symlink():
                        target_world = worlds_dir / world_name
                
                if not target_world:
                    sender.send_message(f"{ColorFormat.RED}Could not find world '{world_name}'")
                    return False
                
                resource_packs_dir = target_world / "resource_packs"
                
                # Run migration
                result = self.generator.migrate_sound_categories(resource_packs_dir)
                
                if result["success"]:
                    sender.send_message(f"{ColorFormat.GREEN}{result['message']}")
                    if result["migrated_count"] > 0:
                        sender.send_message(f"{ColorFormat.GREEN}Please RESTART the server to apply changes.")
                else:
                    sender.send_message(f"{ColorFormat.RED}{result['message']}")
                
                return True
                
        return False

    def get_available_sounds(self) -> list[str]:
        # Standard vanilla sounds
        sounds = ["music.game.creative", "music.game.survival", "music.record.cat", "random.levelup", "random.orb"]
        
        # Load from registry file if it exists (created after /cmusic generate)
        registry_file = self.data_path / "sounds_registry.json"
        if registry_file.exists():
            try:
                with open(registry_file, "r") as f:
                    custom_sounds = json.load(f)
                    sounds.extend(custom_sounds)
            except:
                pass
        else:
            # Fallback: scan uploads folder
            extensions = ["*.ogg", "*.mp3", "*.wav"]
            for ext in extensions:
                for file in self.upload_dir.glob(ext):
                    sounds.append(f"custom.{file.stem}")
        
        return sorted(list(set(sounds)))
    
    def silent_command(self, cmd: str):
        """Run a command (feedback assumed already disabled on server)."""
        self.server.dispatch_command(self.server.command_sender, cmd)
    
    def stop_custom_sounds_for_player(self, player_name: str):
        """Stop only custom plugin sounds for a specific player, not vanilla sounds."""
        if not hasattr(self, "legacy_sound_tokens"):
            self.legacy_sound_tokens = {}
        self.legacy_sound_tokens[player_name] = self.legacy_sound_tokens.get(player_name, 0) + 1
        if player_name in self.playing_sounds:
            for sound in self.playing_sounds[player_name]:
                # Only stop custom sounds (from our plugin)
                self.silent_command(f'stopsound "{player_name}" {sound}')
            self.playing_sounds[player_name] = set()
    
    def track_playing_sound(self, player_name: str, sound: str):
        """Track that a custom sound is now playing for a player."""
        if player_name not in self.playing_sounds:
            self.playing_sounds[player_name] = set()
        self.playing_sounds[player_name].add(sound)
    
    def stop_vanilla_sounds_for_player(self, player_name: str):
        """Stop vanilla music and ambient sounds for a player so custom sounds are heard clearly."""
        # Stop vanilla music categories
        self.silent_command(f'stopsound "{player_name}" music.game')
        self.silent_command(f'stopsound "{player_name}" music.menu')
        # Stop ambient sounds
        self.silent_command(f'stopsound "{player_name}" ambient.weather')
        self.silent_command(f'stopsound "{player_name}" ambient.cave')
    
    def stop_vanilla_sounds_for_target(self, target: str):
        """Stop vanilla music and ambient sounds for a target selector (like @a with position)."""
        # Stop vanilla music categories
        self.silent_command(f'stopsound {target} music.game')
        self.silent_command(f'stopsound {target} music.menu')
        # Stop ambient sounds
        self.silent_command(f'stopsound {target} ambient.weather')
        self.silent_command(f'stopsound {target} ambient.cave')


    def send_main_menu(self, player: Player):
        form = ActionForm(
            title="Music Plugin Menu",
            content="Choose an action:"
        )
        form.add_button("Global Music / Playlists", on_click=self.send_playlists_menu)
        form.add_button("Add New Trigger", icon="textures/ui/color_plus", on_click=self.send_add_trigger_form)
        form.add_button("Manage Triggers", icon="textures/ui/settings_glyph_color_2x", on_click=self.send_list_triggers_form)
        form.add_button("Join Sound Settings", icon="textures/ui/sound_glyph_color_2x", on_click=self.send_join_sound_form)
        form.add_button("Per-Player Join Sounds", icon="textures/ui/icon_multiplayer", on_click=self.send_player_join_sounds_menu)
        form.add_button("Generate Pack", icon="textures/ui/refresh", on_click=lambda p: p.perform_command("cmusic generate"))
        form.add_button("Reload Config", icon="textures/ui/redo", on_click=lambda p: p.perform_command("cmusic reload"))
        
        player.send_form(form)
    
    def send_join_sound_form(self, player: Player):
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
                TextInput(label="Message", placeholder="Optional message to player")
            ],
            on_submit=self.handle_add_trigger_submit
        )
        player.send_form(form)

    def handle_add_trigger_submit(self, player: Player, json_str: str):
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
            "message": data[9]
        }
        
        self.cmusic_config["triggers"].append(new_trigger)
        self.save_config()
        player.send_message(f"{ColorFormat.GREEN}Trigger added! Mode: {mode}, Sound: {sound_choice}, Distance: {data[6]}")

    @event_handler(ignore_cancelled=True)
    def on_player_interact(self, event: PlayerInteractEvent):
        if self.handle_music_interaction(event):
            return
        # Legacy triggers remain configured but cannot interfere with a global session.
        if self.music.session:
            return
        # Get item name (may be None if no item in hand)
        item_name = ""
        if event.item:
            item_type = event.item.type
            item_name = (item_type.id if hasattr(item_type, 'id') else str(item_type)).replace("minecraft:", "")
        
        # Get block name
        block_name = "air"
        if event.block:
            block_type = event.block.type
            block_name = (block_type.id if hasattr(block_type, 'id') else str(block_type)).replace("minecraft:", "")
        
        for trigger in self.cmusic_config.get("triggers", []):
            trigger_item = trigger.get("item", "").replace("minecraft:", "")
            trigger_block = trigger.get("block", "").replace("minecraft:", "")
            mode = trigger.get("mode", "item_block")  # Default to legacy behavior
            
            # Determine match based on mode
            matched = False
            
            if mode == "item_only":
                # Only check item, ignore block - requires item
                if item_name:
                    matched = (trigger_item == "*" or trigger_item == item_name)
            elif mode == "block_only":
                # Only check block, ignore item - works even with empty hand
                matched = (trigger_block == block_name) if event.block else False
            else:  # item_block (default)
                # Both item AND block must match
                item_match = (trigger_item == "*" or trigger_item == item_name)
                block_match = (trigger_block == block_name) if event.block else False
                matched = item_match and block_match
            
            if matched:
                sound = trigger.get("sound")
                volume = trigger.get("volume", 1.0)
                pitch = trigger.get("pitch", 1.0)
                distance = trigger.get("distance", 50.0)
                message = trigger.get("message")
                broadcast = trigger.get("broadcast", False)
                
                if sound:
                    # Determine position and targeting based on mode
                    if mode == "item_only":
                        # For item_only, sound follows the player (personal audio like headphones)
                        pos_x = event.player.location.x
                        pos_y = event.player.location.y
                        pos_z = event.player.location.z
                        
                        if broadcast:
                            # Play to ALL players when broadcast is enabled
                            target = "@a"
                            # Stop custom sounds for all online players
                            for online_player in self.server.online_players:
                                self.stop_custom_sounds_for_player(online_player.name)
                                self.stop_vanilla_sounds_for_player(online_player.name)
                        else:
                            # Use player name targeting so sound follows them
                            target = f"\"{event.player.name}\""
                            # Item sounds only affect the triggering player
                            self.stop_custom_sounds_for_player(event.player.name)
                            # Stop vanilla music/ambient for this player
                            self.stop_vanilla_sounds_for_player(event.player.name)
                    else:
                        # For block modes, sound plays from block position (positional audio)
                        if event.block:
                            pos_x = event.block.x + 0.5
                            pos_y = event.block.y + 0.5
                            pos_z = event.block.z + 0.5
                        else:
                            pos_x = event.player.location.x
                            pos_y = event.player.location.y
                            pos_z = event.player.location.z
                        
                        # Use positional targeting - any player within distance will hear it
                        target = f"@a[x={int(pos_x)},y={int(pos_y)},z={int(pos_z)},r={int(distance)}]"
                        
                        # Stop vanilla music/ambient for players in range
                        self.stop_vanilla_sounds_for_target(target)
                        
                        # Stop custom plugin sounds based on broadcast setting
                        if broadcast:
                            # Stop custom sounds for all online players (server-wide)
                            for online_player in self.server.online_players:
                                self.stop_custom_sounds_for_player(online_player.name)
                        else:
                            # Only stop custom sounds for the triggering player
                            self.stop_custom_sounds_for_player(event.player.name)
                    
                    # Play the sound
                    if mode == "item_only":
                        # For item_only, use minimumVolume=1.0 so sound stays at full volume
                        # as player moves away from trigger point (simulates following the player)
                        cmd = f"playsound {sound} {target} {pos_x} {pos_y} {pos_z} {volume} {pitch} 1.0"
                    else:
                        # For block modes, normal positional audio (fades with distance)
                        cmd = f"playsound {sound} {target} {pos_x} {pos_y} {pos_z} {volume} {pitch}"
                    self.silent_command(cmd)
                    
                    # Track this sound
                    if mode == "item_only":
                        # Item mode only tracks for the triggering player
                        self.track_playing_sound(event.player.name, sound)
                    elif broadcast:
                        # Track for all players (so their sounds get stopped on next trigger)
                        for online_player in self.server.online_players:
                            self.track_playing_sound(online_player.name, sound)
                    else:
                        # Only track for the triggering player
                        self.track_playing_sound(event.player.name, sound)
                    
                if message:
                    if broadcast:
                        self.server.broadcast_message(message)
                    else:
                        event.player.send_message(message)
                
                break

    @event_handler
    def on_player_join(self, event: PlayerJoinEvent):
        player = event.player
        if self.music.session:
            player.send_message("Server music is playing; you will join at the next track.")
            return
        player_name = player.name
        
        # Check for player-specific join sound first
        player_sounds = self.cmusic_config.get("player_join_sounds", {})
        
        if player_name in player_sounds:
            player_config = player_sounds[player_name]
            sound = player_config.get("sound", "music.game.creative")
            volume = player_config.get("volume", 1.0)
            pitch = player_config.get("pitch", 1.0)
            duration = player_config.get("duration", 15)  # seconds
        else:
            # Fall back to default join sound
            join_config = self.cmusic_config.get("join_sound", {})
            
            if not join_config.get("enabled", False):
                return
            
            sound = join_config.get("sound", "music.game.creative")
            volume = join_config.get("volume", 1.0)
            pitch = join_config.get("pitch", 1.0)
            duration = join_config.get("duration", 15)  # seconds
        
        self.stop_custom_sounds_for_player(player_name)
        player.play_sound(player.location, sound, volume, pitch)
        self.track_playing_sound(player.name, sound)

        # Stop only this legacy sound, never all sounds or a newer global session.
        generation = self.legacy_generation
        sound_token = self.legacy_sound_tokens[player_name]
        handle = []
        def stop_sound():
            if handle and handle[0] in self.legacy_join_tasks:
                self.legacy_join_tasks.remove(handle[0])
            if generation != self.legacy_generation or self.music.session or self.legacy_sound_tokens.get(player_name) != sound_token:
                return
            try:
                player.stop_sound(sound)
            except RuntimeError:
                pass
        task = self.server.scheduler.run_task(self, stop_sound, delay=max(1, int(duration * 20)))
        handle.append(task)
        self.legacy_join_tasks.append(task)

    @event_handler(ignore_cancelled=True)
    def on_music_block_break(self, event: BlockBreakEvent):
        if type_id(event.block) != JUKEBOX:
            return
        if not self.require_operator(event.player):
            event.cancel()
            return
        # Cleanup observes the actual loaded block on the next periodic tick, so a
        # later protection listener cancelling this break keeps the binding intact.

    @event_handler
    def on_music_player_quit(self, event: PlayerQuitEvent):
        identity = str(event.player.unique_id)
        self.global_listeners.pop(identity, None)
        self.music_clicks.pop(identity, None)
        self.playing_sounds.pop(event.player.name, None)
        self.legacy_sound_tokens.pop(event.player.name, None)

    def on_disable(self):
        self.shutdown_music()
        self.legacy_generation = getattr(self, "legacy_generation", 0) + 1
        for task in getattr(self, "legacy_join_tasks", []):
            task.cancel()
        self.legacy_join_tasks = []


# Existing management UI remains available, with permission rechecks on every callback.
def _guard_legacy_ui(method):
    from functools import wraps
    @wraps(method)
    def guarded(self, player, *args, **kwargs):
        if not self.require_operator(player):
            return
        try:
            return method(self, player, *args, **kwargs)
        except (ValueError, TypeError, IndexError, KeyError, AttributeError) as error:
            player.send_message(f"Invalid or outdated form response: {error}. Reopen the menu.")
    return guarded


for _name in list(vars(EndstoneMusicPlugin)):
    if _name.startswith(("send_", "handle_", "delete_")):
        setattr(EndstoneMusicPlugin, _name, _guard_legacy_ui(getattr(EndstoneMusicPlugin, _name)))
