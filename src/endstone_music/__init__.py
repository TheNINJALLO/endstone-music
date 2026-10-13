"""Endstone plugin entry point; pack utilities can also run without the server."""
__all__ = ["EndstoneMusicPlugin"]


def __getattr__(name):
    if name == "EndstoneMusicPlugin":
        from endstone_music.plugin import EndstoneMusicPlugin
        return EndstoneMusicPlugin
    raise AttributeError(name)
