import json
import os
import shutil
import uuid
from pathlib import Path
from typing import List, Dict

# Try to use static-ffmpeg if available (pip-installed FFmpeg)
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()  # Adds ffmpeg/ffprobe to PATH
except ImportError:
    pass

try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except ImportError:
    HAS_PYDUB = False

class PackGenerator:
    def __init__(self, key: str = "endstone_music", data_path: Path = None):
        self.key = key
        self.data_path = data_path
        self.metadata_file = data_path / "pack_metadata.json" if data_path else None
        
        # Load or create metadata (UUIDs and version)
        self._load_metadata()
    
    def _load_metadata(self):
        """Load or create pack metadata (UUIDs and version)."""
        if self.metadata_file and self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r") as f:
                    data = json.load(f)
                    self.pack_uuid = data.get("pack_uuid", str(uuid.uuid4()))
                    self.module_uuid = data.get("module_uuid", str(uuid.uuid4()))
                    self.version = data.get("version", [1, 0, 0])
            except:
                self._init_new_metadata()
        else:
            self._init_new_metadata()
    
    def _init_new_metadata(self):
        """Initialize new metadata."""
        self.pack_uuid = str(uuid.uuid4())
        self.module_uuid = str(uuid.uuid4())
        self.version = [1, 0, 0]
    
    def _save_metadata(self):
        """Save metadata to file."""
        if self.metadata_file:
            with open(self.metadata_file, "w") as f:
                json.dump({
                    "pack_uuid": self.pack_uuid,
                    "module_uuid": self.module_uuid,
                    "version": self.version
                }, f, indent=2)
    
    def _bump_version(self):
        """Increment the patch version."""
        self.version[2] += 1
        self._save_metadata()
    
    def generate(self, upload_dir: Path, output_dir: Path, pack_name: str) -> List[str]:
        """
        Generates a resource pack from the upload directory.
        Returns a list of registered sound names (e.g. 'custom.songname').
        """
        if not upload_dir.exists():
            upload_dir.mkdir(parents=True, exist_ok=True)
            return []

        # Bump version on each regeneration
        self._bump_version()
        
        # Create pack directory if it doesn't exist (don't delete existing!)
        pack_dir = output_dir / f"{self.key}_pack"
        pack_dir.mkdir(parents=True, exist_ok=True)
        
        # Internal sound directory
        sounds_dir = pack_dir / "sounds" / "custom"
        sounds_dir.mkdir(parents=True, exist_ok=True)
        
        # Load existing sound definitions if they exist
        sounds_root = pack_dir / "sounds"
        sound_defs_path = sounds_root / "sound_definitions.json"
        
        if sound_defs_path.exists():
            try:
                with open(sound_defs_path, "r") as f:
                    sound_defs = json.load(f)
            except:
                sound_defs = {"format_version": "1.14.0", "sound_definitions": {}}
        else:
            sound_defs = {"format_version": "1.14.0", "sound_definitions": {}}
        
        # Get already registered sound names
        registered_sounds = list(sound_defs.get("sound_definitions", {}).keys())
        
        # Walk uploads - supports ogg, mp3, wav
        extensions = ["*.ogg", "*.mp3", "*.wav"]
        files_to_process = []
        for ext in extensions:
            files_to_process.extend(upload_dir.glob(ext))

        for file in files_to_process:
            # Sanitize file name - replace spaces with underscores
            safe_stem = file.stem.replace(" ", "_").replace("-", "_")
            sound_name = f"custom.{safe_stem}"
            target_path = sounds_dir / f"{safe_stem}.ogg"
            
            # Skip if already registered and file exists
            if sound_name in registered_sounds and target_path.exists():
                print(f"Skipping {file.name}: already registered.")
                continue
            
            # Conversion Logic
            if file.suffix.lower() == ".ogg":
                # Re-process OGG to ensure format if pydub available
                if HAS_PYDUB:
                    try:
                        audio = AudioSegment.from_file(str(file))
                        audio = audio.set_channels(2).set_frame_rate(44100)
                        audio.export(str(target_path), format="ogg", parameters=["-map_metadata", "-1"])
                        print(f"Processed {file.name} to ogg (Stereo, 44.1kHz).")
                    except Exception as e:
                        print(f"Failed to process {file.name}: {e}. Fallback to copy.")
                        shutil.copy2(file, target_path)
                else:
                    shutil.copy2(file, target_path)
            elif HAS_PYDUB:
                try:
                    audio = AudioSegment.from_file(str(file))
                    audio = audio.set_channels(2).set_frame_rate(44100)
                    audio.export(str(target_path), format="ogg", parameters=["-map_metadata", "-1"])
                    print(f"Converted {file.name} to ogg.")
                    # Delete source file after successful conversion
                    try:
                        file.unlink()
                        print(f"Deleted source file: {file.name}")
                    except Exception as e:
                        print(f"Could not delete {file.name}: {e}")
                except Exception as e:
                    print(f"Failed to convert {file.name}: {e}. Skipping.")
                    continue
            else:
                print(f"Skipping {file.name}: pydub not installed or ffmpeg missing.")
                continue

            # Add to definitions
            # Use "neutral" category so vanilla sounds don't stop custom sounds
            sound_defs["sound_definitions"][sound_name] = {
                "category": "neutral",
                "sounds": [
                    f"sounds/custom/{safe_stem}"
                ]
            }
            registered_sounds.append(sound_name)
            
        # Write sound_definitions.json (goes in sounds folder)
        sounds_root = pack_dir / "sounds"
        sounds_root.mkdir(parents=True, exist_ok=True)
        with open(sounds_root / "sound_definitions.json", "w") as f:
            json.dump(sound_defs, f, indent=2)
            
        # Write manifest.json
        manifest = {
            "format_version": 2,
            "header": {
                "description": f"Generated by {self.key}",
                "name": pack_name,
                "uuid": self.pack_uuid,
                "version": self.version.copy(),
                "min_engine_version": [1, 16, 0]
            },
            "modules": [
                {
                    "description": "Custom music",
                    "type": "resources",
                    "uuid": self.module_uuid,
                    "version": self.version.copy()
                }
            ]
        }
        
        with open(pack_dir / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)
        
        # Save sounds registry for easy lookup
        self.last_registered_sounds = registered_sounds
            
        return registered_sounds

    def install_to_world(self, world_dir: Path, world_name: str):
        """
        Updates the world_resource_packs.json to include this pack.
        """
        # Look for the world directory
        target_world = world_dir / world_name
        if not target_world.exists():
            # Try case-insensitive lookup
            for child in world_dir.iterdir():
                if child.is_dir() and child.name.lower() == world_name.lower():
                    target_world = child
                    break
        
        if not target_world.exists():
            print(f"World '{world_name}' not found.")
            return False

        config_path = target_world / "world_resource_packs.json"
        
        current_config = []
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    current_config = json.load(f)
            except:
                current_config = []
        
        # Check if already exists - update version if so
        found = False
        for entry in current_config:
            if entry.get("pack_id") == self.pack_uuid:
                entry["version"] = self.version.copy()  # Update version
                found = True
                break
        
        if not found:
            # Add to top of stack
            new_entry = {
                "pack_id": self.pack_uuid,
                "version": self.version.copy()
            }
            current_config.insert(0, new_entry)
        
        with open(config_path, "w") as f:
            json.dump(current_config, f, indent=2)
            
        return True
    
    def migrate_sound_categories(self, output_dir: Path) -> dict:
        """
        Migrate existing sound_definitions.json to use 'neutral' category instead of 'music'.
        This is a one-time fix for existing packs so vanilla sounds don't stop custom sounds.
        
        Returns a dict with migration results.
        """
        pack_dir = output_dir / f"{self.key}_pack"
        sound_defs_path = pack_dir / "sounds" / "sound_definitions.json"
        
        result = {
            "success": False,
            "migrated_count": 0,
            "message": ""
        }
        
        if not sound_defs_path.exists():
            result["message"] = "No existing sound_definitions.json found. Run /cmusic generate first."
            return result
        
        try:
            with open(sound_defs_path, "r") as f:
                sound_defs = json.load(f)
            
            migrated_count = 0
            definitions = sound_defs.get("sound_definitions", {})
            
            for sound_name, sound_config in definitions.items():
                if sound_config.get("category") == "music":
                    sound_config["category"] = "neutral"
                    migrated_count += 1
            
            if migrated_count > 0:
                # Save the updated definitions
                with open(sound_defs_path, "w") as f:
                    json.dump(sound_defs, f, indent=2)
                
                # Bump version since pack changed
                self._bump_version()
                
                # Update manifest with new version
                manifest_path = pack_dir / "manifest.json"
                if manifest_path.exists():
                    with open(manifest_path, "r") as f:
                        manifest = json.load(f)
                    manifest["header"]["version"] = self.version.copy()
                    manifest["modules"][0]["version"] = self.version.copy()
                    with open(manifest_path, "w") as f:
                        json.dump(manifest, f, indent=2)
                
                result["success"] = True
                result["migrated_count"] = migrated_count
                result["message"] = f"Migrated {migrated_count} sound(s) from 'music' to 'neutral' category."
            else:
                result["success"] = True
                result["message"] = "No sounds needed migration. All sounds already use 'neutral' category."
            
            return result
            
        except Exception as e:
            result["message"] = f"Migration failed: {str(e)}"
            return result
