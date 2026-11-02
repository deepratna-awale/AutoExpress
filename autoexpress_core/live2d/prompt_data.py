"""
The prompt a picture was made with, read from its PNG metadata, and the clothing it names.

WebUIs write the prompt into the PNG: A1111, Forge and SD.Next as "parameters" (the infotext),
ComfyUI as "prompt" (the API graph) and "workflow", InvokeAI as "invokeai_metadata", NovelAI as
"Description" or "Comment". The kit uses the clothing words in it as the outfit and inner wear
when the user didn't type them, and checks the whole prompt with the rest of the description.

Only the standard library and Pillow are needed.
"""

import json
import re

from PIL import Image

# Clothing words, booru tags and plain English. Inner wear first: "lace bra" is inner, not outer.
INNER_WORDS = (
    "bra", "brassiere", "bralette", "sports bra", "panties", "panty", "briefs", "boxers", "boxer briefs", "underwear",
    "lingerie", "thong", "g-string", "knickers", "camisole", "chemise", "negligee", "bustier", "garter belt",
    "garter", "undershirt", "loincloth", "fundoshi", "bikini", "swimsuit", "one-piece swimsuit", "leotard", "bodysuit",
)
OUTER_WORDS = (
    "shirt", "t-shirt", "blouse", "top", "crop top", "tank top", "sweater", "hoodie", "cardigan", "jacket", "blazer",
    "coat", "vest", "waistcoat", "suit", "uniform", "dress", "gown", "sundress", "kimono", "yukata", "hakama", "robe",
    "cloak", "cape", "apron", "skirt", "miniskirt", "pleated skirt", "pencil skirt", "shorts", "pants", "trousers",
    "jeans", "leggings", "overalls", "jumpsuit", "armor", "armour", "serafuku", "sailor collar", "necktie", "tie",
    "bowtie", "bow tie", "ribbon", "scarf", "thighhighs", "thigh highs", "stockings", "pantyhose", "tights", "socks",
    "kneehighs", "boots", "shoes", "high heels", "heels", "sneakers", "sandals", "loafers", "gloves", "belt",
)

def prompt_of(image: Image.Image) -> str:
    """The positive prompt stored in the picture's metadata ("" when there is none)."""
    info = getattr(image, "info", None) or {}
    text = info.get("parameters")
    if isinstance(text, str) and text.strip():
        return text.split("\nNegative prompt:")[0].strip()
    for key in ("Description", "prompt_text"):
        if isinstance(info.get(key), str) and info[key].strip():
            return info[key].strip()
    comment = info.get("Comment")
    if isinstance(comment, str):
        try:
            data = json.loads(comment)
            if isinstance(data, dict) and isinstance(data.get("prompt"), str):
                return data["prompt"].strip()
        except ValueError:
            pass
    invoke = info.get("invokeai_metadata")
    if isinstance(invoke, str):
        try:
            data = json.loads(invoke)
            prompt = data.get("positive_prompt") or data.get("prompt")
            if isinstance(prompt, str):
                return prompt.strip()
        except (ValueError, AttributeError):
            pass
    graph = info.get("prompt")
    if isinstance(graph, str):
        return _comfy_prompt(graph)
    return ""


def _comfy_prompt(graph: str) -> str:
    """The positive prompt of a ComfyUI API graph: the text encoders on the sampler's positive input."""
    try:
        nodes = json.loads(graph)
    except ValueError:
        return ""
    if not isinstance(nodes, dict):
        return ""

    def text_of(ref, depth=0) -> str:
        if depth > 6 or not isinstance(ref, list) or not ref:
            return ""
        node = nodes.get(str(ref[0]))
        if not isinstance(node, dict):
            return ""
        inputs = node.get("inputs") or {}
        for key in ("text", "text_g", "prompt", "positive"):
            value = inputs.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                found = text_of(value, depth + 1)
                if found:
                    return found
        for value in inputs.values():
            if isinstance(value, list):
                found = text_of(value, depth + 1)
                if found:
                    return found
        return ""

    for node in nodes.values():
        if isinstance(node, dict) and "sampler" in str(node.get("class_type", "")).lower():
            found = text_of((node.get("inputs") or {}).get("positive"))
            if found:
                return found.strip()
    texts = [n.get("inputs", {}).get("text") for n in nodes.values() if isinstance(n, dict) and n.get("class_type") == "CLIPTextEncode"]
    texts = [t for t in texts if isinstance(t, str) and t.strip()]
    return max(texts, key=len).strip() if texts else ""


def _terms(prompt: str) -> list[str]:
    """The prompt's comma-separated terms, without weights, brackets, LoRA tags or underscores."""
    prompt = re.sub(r"<[^>]*>", " ", prompt or "")
    prompt = re.sub(r":\s*-?\d+(\.\d+)?", "", prompt)
    prompt = re.sub(r"[()\[\]{}]", " ", prompt).replace("_", " ")
    return [" ".join(t.split()).lower() for t in re.split(r"[,\n|]", prompt) if t.strip()]


def _matches(term: str, words) -> bool:
    return any(re.search(r"(?<![a-z])" + re.escape(word) + r"(?:s|es)?(?![a-z])", term) for word in words)


def clothing(prompt: str) -> tuple[str, str]:
    """(outer clothes, inner wear) the prompt names, as short comma-separated phrases ("" for none)."""
    outer, inner = [], []
    for term in _terms(prompt):
        if len(term) > 60 or term.startswith(("no ", "without ")):
            continue
        if re.search(r"(?<![a-z])(nude|naked|topless|bottomless|undressing|underboob|sideboob)(?![a-z])", term):
            continue
        if _matches(term, INNER_WORDS):
            inner.append(term)
        elif _matches(term, OUTER_WORDS):
            outer.append(term)
    unique = lambda items: ", ".join(dict.fromkeys(items))
    return unique(outer)[:300], unique(inner)[:200]
