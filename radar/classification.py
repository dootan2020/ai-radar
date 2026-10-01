"""Feed-only model release detection; a model mention is not a launch."""

import re

# Match model identities, not branded applications such as Claude Code,
# Grok Business, or Mistral AI Studio. Display text is never modified.
_VERSION = r"\d+(?:\.\d+)*(?:[a-z])?"
_SUFFIX = r"(?:[ -](?:flash|lite|cyber|live|extended|thinking|argon|astra|sol|luna|fast|beta|heavy|tts|objects|body|text-to-speech|\d+(?:\.\d+)*))*"
_NAME = (
    rf"(?:gpt[ -]?{_VERSION}|(?:claude\s+)?(?:sonnet|opus|haiku|fable|mythos)\s+{_VERSION}"
    rf"|gemini\s+(?:(?:robotics\s+(?:er\s+)?)?{_VERSION}|omni(?:\s+{_VERSION})?)"
    rf"|grok\s+(?:(?:code fast|voice think fast)\s+)?{_VERSION}"
    rf"|mistral\s+(?:(?:small|medium|large|ocr)\s+)?{_VERSION}"
    rf"|(?:devstral|codestral|voxtral|magistral|leanstral)(?:\s+{_VERSION})?"
    rf"|(?:llama|qwen|deepseek|weathernext|lyria|veo|imagen)[ -]?{_VERSION}"
    rf"|muse\s+(?:spark|image|video)(?:\s+{_VERSION})?|nano banana\s+{_VERSION}"
    rf"|sam\s+(?:{_VERSION}d?|audio)|dino\s*v{_VERSION}|tribe\s+v{_VERSION}"
    rf"|grok imagine){_SUFFIX}\b"
)
_ANNOUNCE = r"(?:introduc(?:ing|es?|ed)|announc(?:ing|es?|ed)|launch(?:ing|es|ed)?|releas(?:ing|es?|ed)|unveil(?:ing|s|ed)?|redeploy(?:ing|s|ed)?|meet)"
_MODIFIERS = r"(?:(?:a|an|the|our|two|new|first|most|advanced|accurate|breakthrough|state-of-the-art|open[ -](?:source|weights)|frontier|multimodal|foundation|speech|understanding|suite|family|of)\s+)*"


def _announcement(text):
    # Match a first-party announcement clause, not negated/future plans or a
    # tutorial about someone releasing models with an unrelated tool.
    start = rf"(?:^|\bwe(?:'re|’re| are)?\s+(?:(?:thrilled|excited) to\s+)?|\bthis release\s+|^(?:google|openai|anthropic|meta|mistral ai|xai)\s+)(?P<verb>{_ANNOUNCE})\s*:?\s+"
    for match in re.finditer(start, text):
        obj = text[match.end():]
        named = re.match(rf"(?:the\s+|new\s+|an? (?:early )?preview of\s+)?{_NAME}", obj)
        if named:
            tail = obj[named.end():].strip()
            # A trailing noun ('safeguards') changes the announcement's object.
            if not tail or tail[0] in ",.:;!?" or re.match(r"and\b", tail):
                return True
            if re.match(r"with\s+(?!our\b|their\b|your\b)", tail):
                return True
            if match['verb'].startswith(('launch', 'releas')) and re.match(r"in\b", tail):
                return True
        generic = re.match(rf"{_MODIFIERS}models?\b(?P<tail>.*)", obj)
        if generic and re.match(r"\s*(?:$|[,:;.!?]|that\b|which\b|for\b|providing\b|powering\b)", generic['tail']):
            return True
        # Unknown named releases describe their identity in an apposition:
        # 'introducing X, our breakthrough model' or 'X: an open source model'.
        if re.match(rf"[^.!?:,]{{1,120}}[,:]\s*{_MODIFIERS}models?\b", obj):
            if not re.search(r"\b(?:system|platform|tool|program|standard|benchmark|framework)\b", obj.split(',', 1)[0].split(':', 1)[0]):
                return True
    return False


def _model_release(title, summary):
    title = re.sub(r"[\u2010-\u2014]", "-", title.lower())
    summary = re.sub(r"[\u2010-\u2014]", "-", summary.lower())
    if any(_announcement(sentence.strip()) for copy in (title, summary)
           for sentence in re.split(r"[.!?](?:\s|$)", copy)):
        return True
    if re.search(rf"^{_NAME}\s+(?:is|are)\s+(?:now\s+)?available\b", summary):
        return True
    if re.search(rf"^start building with\s+{_NAME}", title):
        return True
    if re.search(rf"^upgrading\b.*\bnew\s+{_NAME}\s+models\b", title):
        return True
    # Identity-only and model-name: descriptor headlines are common launch
    # conventions, independently checked against original model announcements.
    if re.fullmatch(_NAME + r"\.?", title):
        return True
    if re.fullmatch(_NAME + r" and .+ api", title):
        return True
    if re.match(rf"^{_NAME}:\s+(?:our next era|self-supervised|faster and more accessible|open-source foundation)\b", title):
        return True
    if re.search(rf"^{_NAME}\s+says hello\b", title):
        return True
    if re.fullmatch(r"grok (?:imagine|speech to text and text to speech|voice agent) apis?", title):
        return True
    if title == "bringing grok to everyone" and "available to everyone" in summary:
        return True
    if re.match(r"^voxtral tts:", summary) and re.search(r"\bopen-weights\b.*\bmodel\b", summary):
        return True
    if re.match(r"^now you can get\b", summary) and re.search(rf"\bwith\s+{_NAME}", summary):
        return True
    return False


def classify(title, summary=""):
    if _model_release(title, summary):
        return "model"
    text = (title + " " + summary).lower()
    if re.search(r"\b(research|paper|benchmarks?|study|alignment|interpretability|evaluations?)\b", text):
        return "research"
    if re.search(r"\b(launch|introduc|release|app|api|product|agent|tool|chatgpt|copilot|workbench|feature)", text):
        return "product"
    return "other"
