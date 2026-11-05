"""Persistent custom jukebox insert/eject hooks on the server thread."""

import json
from copy import deepcopy

from .items import decode_item, encode_item
from .library import atomic_json
from .playback import Position, dimension_key


def block_key(block):
    return f"{dimension_key(block.dimension)}|{block.x}|{block.y}|{block.z}"


class JukeboxController:
    def __init__(self, plugin, library, engine, path):
        self.plugin, self.library, self.engine, self.path = plugin, library, engine, path
        self.entries = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("jukeboxes"), dict):
                raise ValueError(f"Invalid jukebox storage: {path}; existing data was preserved")
            self.entries = data["jukeboxes"]
            for key, entry in self.entries.items():
                if key != f"{entry['dimension']}|{entry['x']}|{entry['y']}|{entry['z']}" or not isinstance(entry.get("item"), dict):
                    raise ValueError(f"Invalid stored jukebox: {key}")
        self._restore_sources()

    def _save(self, entries):
        atomic_json(self.path, {"schema_version": 1, "jukeboxes": entries})
        self.entries = entries

    def _start(self, key, entry):
        if not self.engine.adapter.supported:
            return
        disc = self.library.discs.get(entry["disc"])
        preset = self.library.jukeboxes.get(entry["preset"])
        if disc is None or preset is None:
            return
        self.engine.start(
            "box:" + key, disc.tracks,
            position=Position(entry["dimension"], entry["x"] + 0.5, entry["y"] + 0.5, entry["z"] + 0.5),
            radius=preset["radius"], volume=preset["volume"], pitch=preset["pitch"],
            loop=disc.loop, spatial_profile=entry["preset"], follow_player=preset.get("follow_player", True),
        )

    def _restore_sources(self):
        for key, entry in self.entries.items():
            self._start(key, entry)

    def handle_interact(self, player, block):
        key = block_key(block)
        if key in self.entries:
            if player.is_sneaking:
                if "box:" + key in self.engine.sources:
                    self.engine.skip("box:" + key)
                else:
                    self._start(key, self.entries[key])
                self.engine.prefer_source(player, "box:" + key)
                player.send_message("§aJukebox track advanced.")
            else:
                self.eject(player, key)
            return True
        preset_id = self.plugin.cmusic_config.get("jukebox_bindings", {}).get(key)
        if preset_id is None:
            preset_id = next((name for name, preset in self.library.jukeboxes.items()
                              if preset["block"] == str(block.type)), None)
        if preset_id not in self.library.jukeboxes or self.library.jukeboxes[preset_id]["block"] != str(block.type):
            return False
        if preset_id is None:
            return False
        inventory = player.inventory
        held = inventory.get_item(inventory.held_item_slot)
        disc = self.library.disc_from_item(held)
        if disc is None:
            return False
        # Do not load a custom playlist over a vanilla disc already in the block.
        if any(str(name).split(":")[-1] in ("record_bit", "has_record") and value
               for name, value in block.data.block_states.items()):
            player.send_message("§eEject the existing vanilla disc first.")
            return True
        original = encode_item(held)
        saved = deepcopy(original)
        saved["amount"] = 1
        remaining = deepcopy(original)
        remaining["amount"] -= 1
        entry = {
            "disc": disc.id, "preset": preset_id, "item": saved,
            "dimension": dimension_key(block.dimension), "x": block.x, "y": block.y, "z": block.z,
        }
        entries = dict(self.entries)
        entries[key] = entry
        # Validate before changing the hand, including a native NBT round trip.
        json.dumps(entry, allow_nan=False)
        decode_item(saved)
        # All inventory/storage operations occur in the same main-thread callback.
        inventory.set_item(inventory.held_item_slot, decode_item(remaining) if remaining["amount"] else None)
        try:
            self._save(entries)
        except Exception:
            inventory.set_item(inventory.held_item_slot, decode_item(original))
            raise
        try:
            self._start(key, entry)
            self.engine.prefer_source(player, "box:" + key)
        except Exception as error:
            # The stored disc remains ejectable even if playback cannot start.
            self.plugin.logger.error(f"Stored disc in {key}, but playback failed: {error}")
            player.send_message("§eDisc inserted; playback unavailable. Click again to eject it.")
            return True
        player.send_message(f"§aNow playing: {disc.title}")
        return True

    def eject(self, player, key):
        entry = self.entries.get(key)
        if entry is None:
            return True
        slot = player.inventory.first_empty
        if slot < 0:
            player.send_message("§eMake space in your inventory before ejecting this disc.")
            return False
        item = decode_item(entry["item"])
        player.inventory.set_item(slot, item)
        entries = dict(self.entries)
        del entries[key]
        try:
            self._save(entries)
        except Exception:
            player.inventory.set_item(slot, None)
            raise
        self.engine.stop("box:" + key)
        self.engine.tick()
        player.send_message("§aDisc ejected.")
        return True

    def tick(self):
        dimensions = {dimension_key(dim): dim for dim in self.plugin.server.level.dimensions}
        for key, entry in self.entries.items():
            source = self.engine.sources.get("box:" + key)
            if source is None:
                continue
            dimension = dimensions.get(entry["dimension"])
            try:
                block = None if dimension is None else dimension.get_block_at(entry["x"], entry["y"], entry["z"])
            except RuntimeError:
                # Some unloaded chunks are reported as errors instead of None.
                # Already pushed albums must keep advancing while they are away.
                block = None
            preset = self.library.jukeboxes.get(entry["preset"])
            source.unavailable = block is None
            source.paused = preset is None or block is not None and str(block.type) != preset["block"]
