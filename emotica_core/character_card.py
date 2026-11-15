"""
Character cards (Tavern / SillyTavern V1, V2 and V3) embedded in PNG files or saved as JSON.

A card PNG is the character's picture with the card JSON in a tEXt chunk, base64 encoded:
"ccv3" for V3 and "chara" for V2 (V3 cards usually carry both). The JSON is either
wrapped ({"spec": "chara_card_v2", "data": {...}}) or flat (V1, and some exporters that
write V2 fields without the wrapper). Only the standard library and Pillow are used.
"""

import base64
import binascii
import dataclasses
import io
import json
import os
import re

from PIL import Image

CARD_CHUNKS = ("ccv3", "chara")
MAX_CARD_BYTES = 4 * 1024 * 1024


@dataclasses.dataclass
class CharacterCard:
    name: str = ""
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_mes: str = ""
    mes_example: str = ""
    creator_notes: str = ""
    system_prompt: str = ""
    tags: list[str] = dataclasses.field(default_factory=list)
    spec: str = "chara_card_v1"

    def _fill(self, text: str) -> str:
        text = re.sub(r"\{\{\s*char\s*\}\}|<BOT>", self.name or "the character", text or "", flags=re.IGNORECASE)
        text = re.sub(r"\{\{\s*user\s*\}\}|<USER>", "the viewer", text, flags=re.IGNORECASE)
        return text.replace("\r\n", "\n").strip()

    def persona(self, limit: int = 4000) -> str:
        """The parts of the card that describe who the character is, with {{char}} and {{user}} filled in."""
        parts = [
            ("Name", self.name),
            ("Description", self.description),
            ("Personality", self.personality),
            ("Scenario", self.scenario),
            ("Tags", ", ".join(self.tags)),
            ("First message", self.first_mes),
        ]
        text = "\n".join(f"{label}: {self._fill(value)}" for label, value in parts if value and value.strip())
        return text[:limit]

    def to_dict(self) -> dict:
        return {**dataclasses.asdict(self), "persona": self.persona()}


def _as_text(value) -> str:
    return value if isinstance(value, str) else ""


def from_json(data) -> CharacterCard | None:
    """A card from its parsed JSON (wrapped V2/V3 or flat V1/V2), or None when it isn't one."""
    if not isinstance(data, dict):
        return None
    spec = data.get("spec") if isinstance(data.get("spec"), str) else "chara_card_v1"
    fields = data.get("data") if isinstance(data.get("data"), dict) else data
    name = _as_text(fields.get("name")) or _as_text(fields.get("char_name"))
    if not name:
        return None
    tags = fields.get("tags") if isinstance(fields.get("tags"), list) else []
    return CharacterCard(
        name=name.strip(),
        description=_as_text(fields.get("description")) or _as_text(fields.get("char_persona")),
        personality=_as_text(fields.get("personality")),
        scenario=_as_text(fields.get("scenario")) or _as_text(fields.get("world_scenario")),
        first_mes=_as_text(fields.get("first_mes")) or _as_text(fields.get("char_greeting")),
        mes_example=_as_text(fields.get("mes_example")) or _as_text(fields.get("example_dialogue")),
        creator_notes=_as_text(fields.get("creator_notes")),
        system_prompt=_as_text(fields.get("system_prompt")),
        tags=[str(tag).strip() for tag in tags if str(tag).strip()][:50],
        spec=spec,
    )


def _decode_chunk(value) -> dict | None:
    if isinstance(value, bytes):
        value = value.decode("latin-1")
    if not isinstance(value, str) or len(value) > MAX_CARD_BYTES * 2:
        return None
    try:
        raw = base64.b64decode(value.strip(), validate=False)
        return json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        try:
            return json.loads(value)  # a few tools write the JSON unencoded
        except ValueError:
            return None


def from_image(image: Image.Image) -> CharacterCard | None:
    """The card embedded in a PNG's text chunks (V3 preferred), or None."""
    info = getattr(image, "text", None) or image.info or {}
    for key in CARD_CHUNKS:
        if key in info:
            card = from_json(_decode_chunk(info[key]))
            if card is not None:
                return card
    return None


def read_card(source) -> CharacterCard | None:
    """
    Read a card from a PIL image, PNG/JSON bytes, a base64 string or data URI, or a file path.

    Returns None when there's no card, so any picture can be passed in.
    """
    if isinstance(source, Image.Image):
        return from_image(source)
    if isinstance(source, str):
        if not source.startswith("data:") and len(source) < 4096 and os.path.isfile(source):
            with open(source, "rb") as handle:
                source = handle.read(MAX_CARD_BYTES * 4)
        else:
            raw = source.split(",", 1)[1] if source.startswith("data:") else source
            try:
                source = base64.b64decode(raw, validate=False)
            except (binascii.Error, ValueError):
                return None
    if not isinstance(source, (bytes, bytearray)):
        return None
    blob = bytes(source)
    if blob[:1] in (b"{", b"["):
        try:
            return from_json(json.loads(blob.decode("utf-8")))
        except (UnicodeDecodeError, ValueError):
            return None
    try:
        with Image.open(io.BytesIO(blob)) as image:
            image.load()  # text chunks after the image data are only read on load
            return from_image(image)
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
