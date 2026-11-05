"""Lossless typed NBT snapshots for discs kept in custom jukeboxes."""


def encode_tag(tag):
    from endstone import nbt

    name = type(tag).__name__
    if isinstance(tag, nbt.CompoundTag):
        value = {key: encode_tag(child) for key, child in tag.items()}
    elif isinstance(tag, nbt.ListTag):
        value = [encode_tag(tag[index]) for index in range(tag.size())]
    elif name in ("ByteArrayTag", "IntArrayTag", "LongArrayTag"):
        value = list(tag)
    elif name in ("ByteTag", "ShortTag", "IntTag", "LongTag", "FloatTag", "DoubleTag", "StringTag"):
        value = tag.value
    else:
        raise ValueError(f"Unsupported item NBT type: {name}")
    return {"type": name, "value": value}


def decode_tag(record):
    from endstone import nbt

    name, value = record["type"], record["value"]
    if name == "CompoundTag":
        tag = nbt.CompoundTag()
        for key, child in value.items():
            tag[key] = decode_tag(child)
        return tag
    if name == "ListTag":
        tag = nbt.ListTag()
        for child in value:
            tag.append(decode_tag(child))
        return tag
    if name not in ("ByteArrayTag", "IntArrayTag", "LongArrayTag", "ByteTag", "ShortTag", "IntTag", "LongTag", "FloatTag", "DoubleTag", "StringTag"):
        raise ValueError(f"Unsupported saved item NBT type: {name}")
    return getattr(nbt, name)(value)


def encode_item(item):
    data = {"type": str(item.type), "amount": int(item.amount), "data": int(item.data)}
    if item.nbt is not None:
        data["nbt"] = encode_tag(item.nbt)
    return data


def decode_item(data):
    from endstone.inventory import ItemStack

    item = ItemStack(data["type"], int(data["amount"]), int(data.get("data", 0)))
    if "nbt" in data:
        tag = decode_tag(data["nbt"])
        item.nbt = tag
        if encode_tag(item.nbt) != data["nbt"]:
            raise ValueError("Disc NBT did not round-trip through the server API")
    return item
