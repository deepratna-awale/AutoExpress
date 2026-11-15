"""
The garment manifest: what a character wears, outermost first, and the undress chain it implies.

A vision language model on the WebUI (Qwen3-VL through ComfyUI's TextGenerate node, see
backend.describe) looks at the picture in up to three passes, then everything else is worked out
in code so the chain is reproducible:

  SEE      the garments that are visible, outermost first, each with a slot, type, colour, how it
           is worn, the body regions it covers, which garments it lies over and a half-worn state;
           the accessories; the visible skin regions; a short character block.
  VERIFY   zoomed crops around each item's box: is an accessory really there (a drawn collarbone is
           not a necklace), the garment's colour and sleeves, and whether its front is open.
  IMAGINE  the inner wear the character would have under what is visible (one inner top, one inner
           bottom, a matching set), a half-worn state for every garment, and whether she is an adult.
  DERIVE   (derive(), no model) the undress order (a topological sort on "worn over", ties by slot
           rank), the states s0..sN, the half states, which states show inner wear (those images are
           named INTERNAL_ and never put in previews) and the layer count. A character without outer
           wear simply gets fewer states and layers.

Accessories and headwear stay on in every state: they are the head's and the picture's own layers.
Without an adult confirmation (the user's, and the model's look at the picture) the chain stops
after the outer layers: nothing that shows the body is drawn.

Only the standard library and Pillow are needed; the model runs on the WebUI.
"""

import json
import re
from collections.abc import Callable

from PIL import Image

from ..images import pil_to_b64

SCHEMA_VERSION = "1.0"

# Vocabularies --------------------------------------------------------------------------------
SLOTS = ["headwear", "outerwear", "waist", "dress", "top", "gloves", "bottom", "footwear", "legwear", "inner_top", "inner_bottom", "accessory"]
# Ties in the undress order are broken by this rank (lower comes off first).
SLOT_RANK = {"headwear": 0, "outerwear": 1, "waist": 2, "dress": 3, "top": 3, "gloves": 4, "bottom": 5, "footwear": 6, "legwear": 7, "inner_top": 8, "inner_bottom": 9, "accessory": 99}
UNDERWEAR_SLOTS = {"inner_top", "inner_bottom"}
# Never taken off: accessories are their own layers, headwear sits on the head, which the chain never edits.
KEPT_SLOTS = {"accessory", "headwear"}
# Slots that get a drawn half-worn variant.
HALF_SLOTS = {"outerwear", "top", "dress", "bottom", "waist"}
REGIONS = ["head", "neck", "shoulders", "upper_arms", "forearms", "hands", "chest", "bust", "back", "midriff", "waist", "hips", "crotch", "buttocks", "thighs", "knees", "shins", "ankles", "feet"]
WORN = ["closed", "open", "unbuttoned_top", "tucked_in", "untucked", "off_shoulder", "sleeves_rolled", "belted", "draped", "tied", "zipped", "half_zipped", "hanging_open", "worn_normally"]
SLEEVES = {"none", "cap", "short", "elbow", "three_quarter", "long"}
LENGTHS = {"cropped", "hip", "thigh", "knee", "calf", "ankle"}
FRONTS = {"open", "closed", "partly_open"}

SYSTEM = (
    "You are a precise costume tagger for a character-illustration pipeline. You look at ONE illustration of ONE character "
    "and describe exactly the clothing that is visible. You answer with a single JSON object and nothing else: no prose, no "
    "markdown fences. You never invent garments or accessories that are not visible. You use only the closed vocabularies "
    "you are given, with the exact spelling."
)

PASS_SEE = f"""Tag the visible outfit of the character in the image.

Return ONE JSON object with exactly these keys:
{{
  "character": {{"sex": "female|male|ambiguous", "age_look": "adult|young adult|teen|child", "framing": "full body|three-quarter|bust-up",
    "pose": "short description of the pose", "hair": "colour, length, style", "eyes": "colour",
    "skin_tone_words": "pale/fair/light/tan/medium/dark + warm/cool/neutral", "body": "build in a few words", "art_style": "a few words"}},
  "visible_garments_outermost_first": [
    {{"id": "short_snake_case_id", "slot": "one of {SLOTS}", "type": "the garment noun",
      "colour": {{"primary": "colour word(s)", "secondary": "colour word(s) of trims or null"}},
      "material_or_pattern": "plain/wool/sheer/lace/plaid/... or null", "worn": ["one or more of {WORN}"],
      "front": "open|closed|partly_open|n/a", "sleeves": "none|cap|short|elbow|three_quarter|long|n/a",
      "length": "cropped|hip|thigh|knee|calf|ankle|n/a", "covers_regions": ["regions from {REGIONS}"],
      "bbox_2d": [x1, y1, x2, y2], "worn_over": ["ids of the garments this one lies directly on top of"],
      "details": "one short sentence", "half_state": "a natural half-worn pose of this garment or null", "confidence": 0.0}}
  ],
  "accessories_visible": [{{"id": "snake_id", "type": "earrings|necklace|choker|glasses|watch|bracelet|ring|hair_ribbon|hairpin|headband|necktie|bow|belt|badge|other", "colour": "...", "location": "where on the body", "bbox_2d": [x1, y1, x2, y2]}}],
  "figure_bbox_2d": [x1, y1, x2, y2],
  "visible_skin_regions": ["regions from {REGIONS} where bare skin is visible"],
  "notes": "anything ambiguous in one sentence, or null"
}}

Rules:
- Outermost first: a coat or blazer before the shirt under it, then bottoms, footwear, legwear.
- outerwear = jackets, blazers, coats, cardigans, capes, haori, vests worn over another top; top = shirts, blouses, sweaters; dress = one-piece garments; waist = belts, sashes, obi, corsets over other garments; bottom = skirts, shorts, trousers; legwear = tights, stockings, socks; footwear = shoes, boots; gloves = gloves, arm sleeves; inner_top / inner_bottom only when an undergarment is actually visible.
- A pair counts as one item. Hidden underwear that is NOT visible must NOT be listed. If there is no outerwear, do not invent one.
- covers_regions: only regions the garment hides. Only headwear covers the head, only gloves the hands. An open garment does not cover the centre of the chest.
- Accessories: only objects with their own outline; a collarbone line or a button is not a necklace.
- "half_state" is required (not null) for outerwear, top, dress and bottom.
- bbox_2d: the box around that item, in pixels of the image as given.
- JSON only."""

PASS_IMAGINE = """Here is the same image and the JSON of the visible outfit:

%s

Now do the IMAGINATION step of a dress-up layer system. Return ONE JSON object with exactly these keys:
{
  "adult_confirmed": true or false,
  "character_summary": "one sentence: archetype, age look, mood",
  "hidden_items_imagined": [
    {"id": "bra|panties|bandeau|briefs|...", "slot": "inner_top or inner_bottom", "type": "garment noun",
     "colour": {"primary": "...", "secondary": "... or null"}, "material_or_pattern": "...",
     "desc": "one short sentence of how it looks", "under": ["ids of the visible garments it is under"], "reason": "why it fits"}
  ],
  "half_states": [{"garment_id": "id from the visible list", "desc": "a natural half-worn pose that changes the garment's shape without removing it, or null for shoes, legwear, gloves and hats"}],
  "style_rules": ["two or three rules every generated state must follow"]
}

Rules:
- adult_confirmed is true only if the character clearly looks like an adult.
- Imagine exactly the undergarments under the visible layers that are not themselves visible: one inner_top (worn directly on the skin) and one inner_bottom, unless the visible outfit already shows that layer.
- A plain, tasteful matching set in a colour that would not show through the visible garments.
- Do not add jewellery or other new items.
- JSON only."""

VERIFY_SYSTEM = (
    "You are a careful visual inspector. You answer a yes/no question about a zoomed crop of an illustration with a single "
    "JSON object and nothing else. You only say yes when the object is clearly drawn with its own outline."
)

HALF_DEFAULTS = {
    "outerwear": "slipped off both shoulders, hanging at the elbows",
    "top": "unbuttoned and hanging open at the front",
    "top_pullover": "pulled up above the bust",
    "top_sleeveless": "slipped off one shoulder, the neckline pulled down to one side",
    "dress": "slipped off both shoulders, bodice folded down to the waist",
    "bottom_skirt": "hem pulled up to the upper thigh",
    "bottom_trousers": "unzipped and pushed down to the hips",
    "waist": "untied and hanging loose",
}
HALF_ACTION_WORDS = ("slip", "unbutton", "open", "lift", "pull", "hang", "off", "down", "up", "roll", "untie", "loosen", "unzip", "push", "fold", "drop", "hike", "lower", "undone", "half")
CHILD_LOOKS = ("child", "teen", "kid", "loli")

SLOT_ALIASES = {
    "outer_wear": "outerwear", "outer": "outerwear", "jacket": "outerwear", "coat": "outerwear", "topwear": "top", "upper": "top", "shirt": "top",
    "bottomwear": "bottom", "lower": "bottom", "skirt": "bottom", "shoes": "footwear", "socks": "legwear", "hosiery": "legwear",
    "underwear_top": "inner_top", "underwear_bottom": "inner_bottom", "belt": "waist", "sash": "waist", "obi": "waist", "hat": "headwear",
    "accessories": "accessory", "innerwear": "inner_top", "inner": "inner_top",
}
SLEEVE_REGIONS = {"cap": ["shoulders"], "short": ["shoulders", "upper_arms"], "elbow": ["shoulders", "upper_arms"], "three_quarter": ["shoulders", "upper_arms", "forearms"], "long": ["shoulders", "upper_arms", "forearms"]}
LENGTH_REGIONS = {"hip": ["hips"], "thigh": ["hips", "thighs"], "knee": ["hips", "thighs", "knees"], "calf": ["hips", "thighs", "knees", "shins"], "ankle": ["hips", "thighs", "knees", "shins", "ankles"]}
# Regions a front view doesn't show: a garment that only covered these reveals no skin.
UNSEEN = {"back"}
INNER_REGIONS = {"inner_top": ["bust", "chest"], "inner_bottom": ["crotch", "hips", "buttocks"]}


# Parsing and normalising ---------------------------------------------------------------------
def parse_json(text: str | None) -> dict | None:
    """The JSON object in a model's answer (fences and trailing commas tolerated), or None."""
    if not text:
        return None
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.DOTALL)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < 0:
        return None
    candidate = t[i : j + 1]
    for fix in (lambda s: s, lambda s: re.sub(r",\s*([}\]])", r"\1", s)):
        try:
            value = json.loads(fix(candidate))
        except ValueError:
            continue
        return value if isinstance(value, dict) else None
    return None


def snake(value) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_") or "item"


def _enum(value, allowed, default="n/a") -> str:
    value = snake(value)
    return value if value in allowed else default


def _colour(raw) -> dict:
    if isinstance(raw, str):
        return {"primary": raw, "secondary": None}
    raw = raw if isinstance(raw, dict) else {}
    return {"primary": raw.get("primary"), "secondary": raw.get("secondary")}


def norm_garment(g: dict, index: int) -> dict:
    """A visible garment from the model, on the closed vocabularies, with the obvious mistakes fixed."""
    slot = SLOT_ALIASES.get(str(g.get("slot", "")).lower().strip(), str(g.get("slot", "")).lower().strip())
    if slot not in SLOTS:
        slot = "accessory"
    worn = g.get("worn") or []
    worn = [snake(w) for w in ([worn] if isinstance(worn, str) else worn)]
    if slot not in ("top", "dress", "inner_top"):
        worn = [w for w in worn if w not in ("tucked_in", "untucked")]  # only a top is tucked in
    covers = [snake(r) for r in (g.get("covers_regions") or []) if snake(r) in REGIONS]
    if slot != "headwear":
        covers = [r for r in covers if r != "head"]
    if slot != "gloves":
        covers = [r for r in covers if r != "hands"]
    if slot not in ("footwear", "legwear"):
        covers = [r for r in covers if r != "feet"]
    half = g.get("half_state")
    if not isinstance(half, str) or half.strip().lower() in ("", "null", "none", "n/a"):
        half = None
    try:
        confidence = float(g.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    kind = snake(g.get("type") or g.get("id") or "garment")
    gid = snake(g.get("id") or kind)
    if gid in SLOTS or gid in ("inner", "outer", "bottoms", "tops", "garment", "item"):
        gid = kind if kind not in SLOTS else f"{slot}_{index}"
    return {
        "id": gid,
        "slot": slot,
        "type": kind,
        "colour": _colour(g.get("colour") or g.get("color")),
        "material_or_pattern": g.get("material_or_pattern"),
        "worn": worn or ["worn_normally"],
        "front": _enum(g.get("front"), FRONTS),
        "sleeves": _enum(g.get("sleeves"), SLEEVES),
        "length": _enum(g.get("length"), LENGTHS),
        "covers_regions": covers,
        "worn_over": [snake(x) for x in (g.get("worn_over") or [])],
        "details": g.get("details"),
        "half_state": half,
        "half_state_source": "model" if half else None,
        "confidence": round(confidence, 2),
        "bbox_2d_model": g.get("bbox_2d"),
        "bbox_2d_source": None,
        "visible": True,
        "verified": {},
    }


def norm_hidden(h: dict, index: int) -> dict:
    """An imagined undergarment from the model."""
    slot = str(h.get("slot", "")).lower().strip()
    if slot not in UNDERWEAR_SLOTS:
        name = snake(h.get("type") or h.get("id") or "")
        slot = "inner_top" if any(k in name for k in ("bra", "top", "cami", "sarashi", "bandeau")) else "inner_bottom"
    return {
        "id": snake(h.get("id") or h.get("type") or f"hidden_{index}"),
        "slot": slot,
        "type": snake(h.get("type") or h.get("id") or slot),
        "colour": _colour(h.get("colour") or h.get("color")),
        "material_or_pattern": h.get("material_or_pattern"),
        "worn": ["worn_normally"],
        "front": "n/a",
        "sleeves": "n/a",
        "length": "n/a",
        "covers_regions": list(INNER_REGIONS[slot]),
        "worn_over": [],
        "details": h.get("desc"),
        "half_state": None,
        "half_state_source": None,
        "confidence": None,
        "visible": False,
        "under": [snake(x) for x in (h.get("under") or [])],
        "reason": h.get("reason"),
    }


def unique_ids(items: list[dict]) -> list[dict]:
    """Two "shirt"s become shirt and shirt_2."""
    seen: dict[str, int] = {}
    for item in items:
        n = seen.get(item["id"], 0) + 1
        seen[item["id"]] = n
        if n > 1:
            item["id"] = f"{item['id']}_{n}"
    return items


def plausible_half_state(text) -> bool:
    """A half state describes a change (slipped off, unbuttoned, lifted ...), not the garment as worn."""
    t = (text or "").lower().strip() if isinstance(text, str) else ""
    if not t or any(k in t for k in ("worn normally", "as worn", "buttoned up", "closed and", "tucked into", "fully", "no half")):
        return False
    if snake(t) in WORN or snake(t) in ("open", "closed", "partly_open", "n_a", "none", "null") or len(t) < 12:
        return False
    return any(k in t for k in HALF_ACTION_WORDS)


def default_half_state(g: dict) -> str | None:
    slot, kind = g["slot"], g["type"]
    if slot == "outerwear":
        return HALF_DEFAULTS["outerwear"]
    if slot == "top":
        if g.get("sleeves") in ("none", "cap") or any(k in kind for k in ("tank", "camisole", "tube", "halter", "sleeveless")):
            return HALF_DEFAULTS["top_sleeveless"]
        pullover = any(k in kind for k in ("sweater", "pullover", "t_shirt", "tshirt", "turtleneck", "hoodie"))
        return HALF_DEFAULTS["top_pullover" if pullover else "top"]
    if slot == "dress":
        return HALF_DEFAULTS["dress"]
    if slot == "bottom":
        trousers = any(k in kind for k in ("trouser", "pant", "jean", "short", "slack"))
        return HALF_DEFAULTS["bottom_trousers" if trousers else "bottom_skirt"]
    if slot == "waist":
        return HALF_DEFAULTS["waist"]
    return None


def settle_half_states(visible: list[dict], from_imagine: dict | None = None) -> list[dict]:
    """Every garment that can be half worn gets a plausible half state: the model's, then the second pass's, then the library's."""
    from_imagine = from_imagine or {}
    for g in visible:
        if not plausible_half_state(g.get("half_state")):
            g["half_state"], g["half_state_source"] = None, None
        second = from_imagine.get(g["id"])
        if g["half_state"] is None and plausible_half_state(second):
            g["half_state"], g["half_state_source"] = second, "model_pass2"
        if g["half_state"] is None and g["slot"] in HALF_SLOTS and default_half_state(g):
            g["half_state"], g["half_state_source"] = default_half_state(g), "library"
        if g["slot"] not in HALF_SLOTS:
            g["half_state"], g["half_state_source"] = None, None
    return visible


def complete_coverage(g: dict) -> dict:
    """The structured fields say what covers_regions often forgets: sleeves cover arms, a hem covers down to it."""
    cover = list(g.get("covers_regions") or [])
    if g["slot"] in ("outerwear", "top", "dress") and g.get("sleeves") in SLEEVE_REGIONS:
        cover += SLEEVE_REGIONS[g["sleeves"]]
    if g["slot"] in ("bottom", "dress") and g.get("length") in LENGTH_REGIONS:
        cover += LENGTH_REGIONS[g["length"]]
    if g["slot"] == "bottom":
        cover += ["crotch", "buttocks"]
    if g["slot"] == "legwear" and g["type"] in ("tights", "pantyhose", "leggings"):
        cover += ["hips", "thighs", "knees", "shins", "ankles", "feet", "crotch", "buttocks"]
    if g["slot"] == "footwear":
        cover += ["feet"]
    g["covers_regions"] = [r for r in REGIONS if r in set(cover)]
    return g


# Deriving the chain ----------------------------------------------------------------------------
def internal_name(name: str, internal: bool) -> str:
    """The file name of a state or layer image: INTERNAL_ in front when it shows inner wear or less."""
    return f"INTERNAL_{name}" if internal else name


def derive(visible: list[dict], hidden: list[dict], adult: bool) -> dict:
    """
    The undress order, the states, the half states and the layer count: a pure function of the
    tagged lists (see the module docstring). A state "shows_inner_wear" when an inner garment is
    still on and no longer fully covered by the outer clothes; such states, and every state after
    the inner wear starts coming off, are internal (their images are named INTERNAL_).
    """
    garments_visible = [complete_coverage(dict(g)) for g in visible if g["slot"] not in KEPT_SLOTS]
    garments = garments_visible + [dict(h) for h in hidden]
    by_id = {g["id"]: g for g in garments}
    # The model's worn_over edges are kept only when they agree with the slot ranking (an 8B model
    # sometimes says "tights over skirt"); the ranking adds an edge wherever two garments share a region.
    over: dict[str, set] = {g["id"]: set() for g in garments}
    for a in garments_visible:
        for b_id in a["worn_over"]:
            b = by_id.get(b_id)
            if b is not None and b is not a and SLOT_RANK[a["slot"]] <= SLOT_RANK[b["slot"]]:
                over[a["id"]].add(b_id)
    for a in garments_visible:
        for b in garments_visible:
            if a is not b and set(a["covers_regions"]) & set(b["covers_regions"]) and SLOT_RANK[a["slot"]] < SLOT_RANK[b["slot"]]:
                over[a["id"]].add(b["id"])
    for h in garments[len(garments_visible) :]:
        under = [u for u in h.get("under", []) if u in by_id and by_id[u]["visible"]]
        under = under or [v["id"] for v in garments_visible if set(v["covers_regions"]) & set(h["covers_regions"])]
        for u in under:
            over[u].add(h["id"])
    # Topological order: a garment comes off only when nothing still worn lies over it.
    remaining = [g["id"] for g in garments]
    position = {gid: i for i, gid in enumerate(remaining)}
    order = []
    while remaining:
        free = [gid for gid in remaining if not any(gid in over[o] for o in remaining if o != gid)] or remaining[:]
        free.sort(key=lambda gid: (SLOT_RANK[by_id[gid]["slot"]], position[gid]))
        order.append(free[0])
        remaining.remove(free[0])

    def covered(ids, inner=None) -> set:
        sets = [set(by_id[i]["covers_regions"]) for i in ids if inner is None or (by_id[i]["slot"] in UNDERWEAR_SLOTS) == inner]
        return set().union(*sets) if sets else set()

    def shows_inner(worn: list) -> bool:
        inner = [i for i in worn if by_id[i]["slot"] in UNDERWEAR_SLOTS]
        return any(set(by_id[i]["covers_regions"]) - covered(worn, inner=False) for i in inner)

    states = [{
        "name": "s0_full", "removed": None, "wearing": list(order), "reveals_skin_regions": [], "shows": [],
        "shows_inner_wear": shows_inner(order), "player": True, "internal": shows_inner(order), "image": "the picture itself, untouched",
    }]
    worn = list(order)
    inner_coming_off = False
    for k, gid in enumerate(order, 1):
        before = covered(worn)
        worn = [w for w in worn if w != gid]
        after = covered(worn)
        removing_inner = by_id[gid]["slot"] in UNDERWEAR_SLOTS
        inner_coming_off = inner_coming_off or removing_inner
        visible_inner = shows_inner(worn)
        states.append({
            "name": f"s{k}_no_{gid}", "removed": gid, "wearing": list(worn),
            "reveals_skin_regions": sorted(before - after - UNSEEN),
            "shows": sorted(w for w in worn if w in over[gid]),
            "shows_inner_wear": visible_inner,
            "player": not removing_inner,
            "internal": visible_inner or inner_coming_off,
        })
    blocked = None
    if not adult:
        # Without an adult confirmation only outer layers may come off: nothing that shows the body.
        blocked = "No adult confirmation: the chain stops after the outer layers; no inner wear or skin states."
        keep = [states[0]]
        for state in states[1:]:
            if state["internal"] or state["reveals_skin_regions"] or by_id[state["removed"]]["slot"] in UNDERWEAR_SLOTS:
                break
            keep.append(state)
        states = keep
        order = [s["removed"] for s in states[1:]]
    for state in states:
        state["file"] = internal_name(state["name"], state["internal"]) + ".png"
    lowest = next((s["name"] for s in states[1:] if not s["internal"] and not s["shows_inner_wear"] and all(by_id[w]["slot"] in UNDERWEAR_SLOTS for w in s["wearing"])), None)
    player_states = [s for s in states if s["player"]]
    # Half states: drawn from the state in which the garment is outermost (the one before its removal),
    # kept as garment-only pixels over the next state.
    halves = []
    for k, gid in enumerate(order):
        g = by_id[gid]
        if g.get("half_state") and g["slot"] in HALF_SLOTS:
            internal = states[k + 1]["internal"] if k + 1 < len(states) else True
            halves.append({
                "name": f"{gid}_half", "garment": gid, "slot": g["slot"], "desc": g["half_state"], "source": g.get("half_state_source"),
                "from": states[k]["name"], "over": states[k + 1]["name"], "internal": internal,
                "file": internal_name(f"half_{gid}", internal) + ".png",
            })
    accessories = [g for g in visible if g["slot"] in KEPT_SLOTS]
    removed = [by_id[gid] for gid in order]
    layer_count = {
        "garments_visible": sum(1 for g in removed if g["visible"]),
        "garments_hidden": sum(1 for g in removed if not g["visible"]),
        "half_variants": len(halves),
        "body": 1 if states and states[-1]["removed"] and not blocked else 0,
        "kept_on": len(accessories),
        "edits": max(0, len(states) - 1) + len(halves),
        "player_states": len(player_states),
        "internal_states": sum(1 for s in states if s["internal"]),
    }
    layer_count["total_body_group"] = layer_count["garments_visible"] + layer_count["garments_hidden"] + layer_count["half_variants"] + layer_count["body"] + layer_count["kept_on"]
    for g in garments:
        g["worn_over_resolved"] = sorted(over[g["id"]])
    return {
        "undress_order": order,
        "states": states,
        "half_states": halves,
        "lowest_player_state": lowest or player_states[-1]["name"],
        "layer_count": layer_count,
        "blocked": blocked,
        "garments": {g["id"]: g for g in garments},
    }


def visible_skin(visible: list[dict]) -> list[str]:
    covers = [set(complete_coverage(dict(g))["covers_regions"]) for g in visible]
    return sorted(set(REGIONS) - set().union(*covers) - {"back", "buttocks", "crotch"}) if covers else list(REGIONS)


def build_manifest(see: dict, imagine: dict | None, adult_allowed: bool, name: str = "", source: dict | None = None, tagged_by: dict | None = None) -> dict:
    """
    The garment manifest from the SEE and IMAGINE answers (dicts as the model returned them, the
    VERIFY corrections already applied to see's garments when there were any). adult_allowed is the
    user's confirmation (outfits.check); the model must also see an adult.
    """
    imagine = imagine or {}
    visible = unique_ids([norm_garment(g, i) for i, g in enumerate(see.get("visible_garments_outermost_first") or []) if isinstance(g, dict)])
    hidden = []
    taken = {g["slot"] for g in visible if g["slot"] in UNDERWEAR_SLOTS}
    for i, h in enumerate(imagine.get("hidden_items_imagined") or []):
        if not isinstance(h, dict):
            continue
        item = norm_hidden(h, i)
        if item["slot"] in taken:
            continue  # the picture already shows the innermost layer of that slot
        taken.add(item["slot"])
        hidden.append(item)
    unique_ids(visible + hidden)
    second = {snake(x.get("garment_id")): x.get("desc") for x in (imagine.get("half_states") or []) if isinstance(x, dict)}
    settle_half_states(visible, second)
    character = dict(see.get("character") or {})
    age = str(character.get("age_look", "")).lower()
    adult = bool(adult_allowed) and bool(imagine.get("adult_confirmed", False)) and not any(k in age for k in CHILD_LOOKS)
    if not adult:
        hidden = []  # nothing under the clothes is imagined for a character not confirmed adult
    derived = derive(visible, hidden, adult)
    character["summary"] = imagine.get("character_summary")
    character["adult_confirmed"] = adult
    character["skin"] = {"words": character.pop("skin_tone_words", None), "note": "measured from the face by the chain (lit skin, Lab)"}
    if name:
        character["name"] = name
    accessories = [g for g in visible if g["slot"] in KEPT_SLOTS]
    for i, acc in enumerate(see.get("accessories_visible") or []):
        if isinstance(acc, dict):
            accessories.append({"id": snake(acc.get("id") or acc.get("type") or f"acc_{i}"), "slot": "accessory", "type": snake(acc.get("type")), "colour": acc.get("colour"), "location": acc.get("location")})
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source or {},
        "tagged_by": tagged_by or {},
        "character": character,
        "visible_garments_outermost_first": [g for g in visible if g["slot"] not in KEPT_SLOTS],
        "accessories_visible": accessories,
        "visible_skin_regions": visible_skin([g for g in visible if g["slot"] not in KEPT_SLOTS]),
        "hidden_items_imagined": hidden,
        "style_rules": [str(r) for r in (imagine.get("style_rules") or []) if r][:5],
        "undress_order": derived["undress_order"],
        "states": derived["states"],
        "lowest_player_state": derived["lowest_player_state"],
        "half_states": derived["half_states"],
        "layer_count": derived["layer_count"],
        "blocked": derived["blocked"],
        "layers_from_states": "layer(garment) = the pixels of the state before its removal inside its matte; outside the removed garment's region every pixel is copied from the previous state",
        "notes": see.get("notes"),
    }


def garment_by_id(manifest: dict) -> dict:
    return {g["id"]: g for g in manifest.get("visible_garments_outermost_first", []) + manifest.get("hidden_items_imagined", [])}


def garment_words(g: dict) -> str:
    """'tan blazer', for prompts and segmentation."""
    colour = (g.get("colour") or {}).get("primary") or ""
    return " ".join(f"{colour} {g['type'].replace('_', ' ')}".split())


# Boxes -----------------------------------------------------------------------------------------
def figure_box(image: Image.Image) -> list[int]:
    """The box of the non-background pixels (white or transparent background)."""
    import numpy as np

    a = np.asarray(image.convert("RGBA")).astype(int)
    fg = (a[..., 3] > 16) & ((a[..., :3].sum(-1) < 735) | (a[..., 3] < 250))
    ys, xs = np.nonzero(fg)
    if not len(xs):
        return [0, 0, image.width, image.height]
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def box_mode(model_box, true_box, size) -> tuple[str | None, float]:
    """Qwen-VL boxes are either pixels of the image or normalised to 0..1000: whichever fits the figure."""
    try:
        mb = [float(v) for v in model_box]
    except (TypeError, ValueError):
        return None, 0.0
    if len(mb) != 4:
        return None, 0.0
    w, h = size
    candidates = {"abs": mb, "norm1000": [mb[0] * w / 1000, mb[1] * h / 1000, mb[2] * w / 1000, mb[3] * h / 1000]}
    best = max(candidates, key=lambda k: iou(candidates[k], true_box))
    return best, iou(candidates[best], true_box)


def to_box(box, mode: str | None, size) -> list[int] | None:
    """A model box in pixels of the image it was given, or None."""
    if mode is None:
        return None
    try:
        b = [float(v) for v in box]
    except (TypeError, ValueError):
        return None
    if len(b) != 4:
        return None
    if mode == "norm1000":
        w, h = size
        b = [b[0] * w / 1000, b[1] * h / 1000, b[2] * w / 1000, b[3] * h / 1000]
    if b[2] <= b[0] or b[3] <= b[1]:
        return None
    return [round(v) for v in b]


def crop_for_check(image: Image.Image, box, margin: float = 0.35, max_side: int = 768, min_side: int = 256) -> Image.Image:
    w, h = image.size
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    mx, my = max(bw * margin, (min_side - bw) / 2, 8), max(bh * margin, (min_side - bh) / 2, 8)
    crop = image.crop((max(0, int(x1 - mx)), max(0, int(y1 - my)), min(w, int(x2 + mx)), min(h, int(y2 + my))))
    longest = max(crop.size)
    if longest > max_side or longest < min_side:
        f = (max_side if longest > max_side else min_side) / longest
        crop = crop.resize((max(1, round(crop.width * f)), max(1, round(crop.height * f))), Image.Resampling.LANCZOS)
    return crop


# Talking to the model -----------------------------------------------------------------------------
def _describe(backend, image: Image.Image, prompt: str, max_length: int):
    describe = getattr(backend, "describe", None)
    if describe is None:
        return None
    b64 = pil_to_b64(image.convert("RGB"))
    try:
        return describe(b64, prompt, max_length=max_length)
    except TypeError:  # a backend whose describe takes no length
        return describe(b64, prompt)


def ask(backend, image: Image.Image, prompt: str, system: str = SYSTEM, max_length: int = 2048, tries: int = 3) -> dict | None:
    """The model's JSON answer about image (asked again while it isn't parsable), or None."""
    for _ in range(tries):
        answer = _describe(backend, image, f"{system}\n\n{prompt}", max_length)
        found = parse_json(answer)
        if found is not None:
            return found
    return None


def _yes(value) -> bool:
    return str(value).strip().lower() in ("true", "yes", "1")


def verify(backend, picture: Image.Image, see: dict, size, log: Callable[[str], None] = lambda _: None) -> dict:
    """The VERIFY pass: accessories checked on a zoomed crop, garment colour, sleeves and front from crops. Changes see in place."""
    mode, fit = box_mode(see.get("figure_bbox_2d"), figure_box(picture), size)
    if mode is None or fit < 0.5:
        see.setdefault("_verify", "skipped: the model's boxes don't fit the figure")
        return see
    kept = []
    for acc in see.get("accessories_visible") or []:
        if not isinstance(acc, dict):
            continue
        box = to_box(acc.get("bbox_2d"), mode, size)
        if box is None:
            continue
        kind = str(acc.get("type") or "accessory").replace("_", " ")
        answer = ask(backend, crop_for_check(picture, box), f"This is a zoomed crop around the character's {acc.get('location') or 'body'}. Is there a {kind} (a real object with its own outline, not a line of the body or the clothes) drawn here? "
                     'Answer with ONE JSON object: {"present": true or false, "what_is_there": "a few words"}. JSON only.', VERIFY_SYSTEM, 160, 2)
        if answer and _yes(answer.get("present")):
            kept.append(acc)
        else:
            log(f"Accessory {kind} not confirmed on a close look; dropped.")
    see["accessories_visible"] = kept
    for g in see.get("visible_garments_outermost_first") or []:
        if not isinstance(g, dict):
            continue
        box = to_box(g.get("bbox_2d"), mode, size)
        if box is None:
            continue
        kind = str(g.get("type") or "garment").replace("_", " ")
        answer = ask(backend, crop_for_check(picture, box), f"This is a zoomed crop of the character's {kind}. "
                     'Answer with ONE JSON object: {"main_colour": "one or two plain colour words for the garment itself", '
                     '"front": "open|closed|partly_open|n/a"}. JSON only.', VERIFY_SYSTEM, 160, 2) or {}
        g.setdefault("verified", {}).update(answer)
        front = _enum(answer.get("front"), FRONTS)
        slot = SLOT_ALIASES.get(str(g.get("slot", "")).lower(), str(g.get("slot", "")).lower())
        if slot in ("outerwear", "top", "dress") and front != "n/a":
            g["front"] = front
    see["_verify"] = f"done ({mode} boxes)"
    return see


def tag_garments(
    backend,
    picture: Image.Image,
    adult_allowed: bool,
    name: str = "",
    max_side: int = 1536,
    check: bool = True,
    log: Callable[[str], None] = lambda _: None,
) -> dict | None:
    """
    The garment manifest for picture from the backend's vision language model, or None when the
    backend has none or never answers with JSON. adult_allowed: the user's adult confirmation passed
    (outfits.check); without it nothing under the clothes is imagined.
    """
    if getattr(backend, "describe", None) is None:
        return None
    rgba = picture.convert("RGBA")
    flat = Image.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    scale = min(1.0, max_side / max(flat.size))
    sent = flat if scale >= 1.0 else flat.resize((round(flat.width * scale), round(flat.height * scale)), Image.Resampling.LANCZOS)
    log("Tagging the clothes (vision model, pass 1: what is visible).")
    see = ask(backend, sent, PASS_SEE, max_length=2560)
    if see is None:
        return None
    passes = ["see"]
    if check:
        log("Checking the tags on close-ups (pass 2).")
        verify(backend, sent, see, sent.size, log)
        passes.append("verify")
    imagine = None
    if adult_allowed:
        slim = {"character": see.get("character"), "visible_garments_outermost_first": see.get("visible_garments_outermost_first"), "visible_skin_regions": see.get("visible_skin_regions")}
        log("Imagining what is under the clothes (pass 3).")
        imagine = ask(backend, sent, PASS_IMAGINE % json.dumps(slim, ensure_ascii=False), max_length=1536)
        passes.append("imagine")
    manifest = build_manifest(
        see, imagine, adult_allowed, name,
        source={"size": list(picture.size)},
        tagged_by={"node": "TextGenerate (ComfyUI)", "decoding": "greedy", "passes": passes, "sent_size": list(sent.size), "verify": see.get("_verify")},
    )
    log(f"Undress order: {', '.join(manifest['undress_order']) or 'nothing comes off'}; {len(manifest['states'])} states, {len(manifest['half_states'])} half states.")
    return manifest
