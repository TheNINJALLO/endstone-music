# Endstone Custom Music Plugin

A powerful custom music plugin for Endstone Bedrock servers that allows operators to trigger custom sounds when players interact with blocks or items.

## Features

- **Custom Sound Triggers**: Three trigger modes:
  - **Item + Block**: Sound when specific item is used on specific block
  - **Item Only**: Sound when clicking anywhere with specific item (follows player)
  - **Block Only**: Sound when clicking specific block with any item
- **Automated Resource Pack Generation**: 
  - Drop `.ogg`, `.mp3`, or `.wav` files into the `uploads` folder
  - Automatic conversion to Bedrock-compatible format (Stereo, 44.1kHz)
  - Auto-installs to your world's resource_packs folder
  - Version auto-bumps on each generation
- **In-Game Configuration UI**: Add, view, and delete triggers via forms
- **Distance-Based Audio**: Configure audible range (100 - 1,000,000 blocks)
- **Broadcast Mode**: Play sounds to all nearby players
- **Stops Overlapping Sounds**: New triggers automatically stop previous sounds

## Installation

1. Build or download the plugin wheel
2. Place in your Endstone `plugins` folder
3. Start the server

## Commands

| Command | Description |
|---------|-------------|
| `/cmusic` | Open the in-game configuration menu |
| `/cmusic generate` | Generate resource pack from uploaded audio |
| `/cmusic reload` | Reload config without restart |

## Usage

### Adding Custom Sounds

1. **Upload audio** to `plugins/endstone_music/uploads/`
   - Supports: `.ogg`, `.mp3`, `.wav`
   - MP3/WAV auto-convert and delete after conversion

2. **Generate pack**: `/cmusic generate`

3. **Restart server** to apply the resource pack

### Adding Triggers (In-Game)

1. Run `/cmusic` → **Add New Trigger**
2. Configure:
   - **Trigger Mode**: Item+Block, Item Only, or Block Only
   - **Item/Block**: Minecraft IDs
   - **Sound**: Select from dropdown
   - **Volume/Pitch**: Adjust playback
   - **Distance**: Audible range (100 - 1,000,000 blocks)
   - **Broadcast**: Play to all nearby players
   - **Loop**: Loop the sound (saved for future use)
   - **Message**: Optional chat message

### Managing Triggers

1. Run `/cmusic` → **Manage Triggers**
2. Select a trigger to view details
3. Delete triggers you no longer need

## Configuration

Edit `plugins/endstone_music/config.json`:

```json
{
  "pack_name": "My Server Music",
  "target_world_name": "Bedrock level",
  "triggers": [
    {
      "mode": "block_only",
      "item": "minecraft:stick",
      "block": "minecraft:jukebox",
      "sound": "custom.mysong",
      "volume": 1.0,
      "pitch": 1.0,
      "distance": 1000,
      "broadcast": true,
      "loop": false,
      "message": "§aNow playing: My Song"
    }
  ]
}
```

## Sound Naming

- `mysong.ogg` → `custom.mysong`
- `epic_battle.mp3` → `custom.epic_battle`

## Dependencies

- **pydub**: Audio processing
- **static-ffmpeg**: Bundled FFmpeg (no system install needed)

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Pack not loading | Check `target_world_name` matches your world folder |
| No sound in-game | Ensure clients downloaded the pack |
| Triggers not working | Run `/cmusic reload` |
