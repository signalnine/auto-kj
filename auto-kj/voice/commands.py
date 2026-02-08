import re


def parse_command(text: str) -> tuple[str, str | None]:
    t = text.strip().lower()

    # Skip / Next
    if re.match(r"^(skip|next(\s+song)?)\s*$", t):
        return ("skip", None)

    # Pause / Stop
    if re.match(r"^(pause|stop)\s*$", t):
        return ("pause", None)

    # Resume / Continue / Go
    if re.match(r"^(resume|continue|go)\s*$", t):
        return ("resume", None)

    # Queue
    if re.match(r"^(what'?s\s+next|show\s+queue|queue)\s*$", t):
        return ("queue", None)

    # Volume
    if re.search(r"(volume\s+up|louder|turn\s+(it\s+)?up)", t):
        return ("volume_up", None)
    if re.search(r"(volume\s+down|quieter|softer|turn\s+(it\s+)?down)", t):
        return ("volume_down", None)

    # Cancel
    if re.match(r"^(cancel|never\s*mind|nevermind)\s*$", t):
        return ("cancel", None)

    # Play / Sing / Add — extract song name
    m = re.match(
        r"^(?:play|sing|add|put\s+on|i\s+want\s+to\s+(?:hear|sing))\s+(.+?)(?:\s+to\s+the\s+queue)?\s*$",
        t,
    )
    if m:
        # Restore original casing from input
        orig = text.strip()
        for prefix in [
            "play ", "sing ", "add ", "put on ",
            "i want to hear ", "i want to sing ",
        ]:
            if orig.lower().startswith(prefix):
                song = orig[len(prefix):].strip()
                song = re.sub(r"\s+to\s+the\s+queue\s*$", "", song, flags=re.IGNORECASE)
                return ("play", song)

    return ("unknown", None)
