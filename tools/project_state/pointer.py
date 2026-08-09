def json_pointer(*segments: str | int) -> str:
    escaped = (
        str(segment).replace("~", "~0").replace("/", "~1") for segment in segments
    )
    return "$" + "".join(f"/{segment}" for segment in escaped)
