"""K=5 teacher annotators -> fractional soft BIO labels.

The paper uses an ensemble of LLM annotators; at take-home scale the same
distillation machinery is fed by 5 rule/gazetteer annotators with
deliberately varied boundary conventions (title inclusion, bare-year
dates, over-extended phones, MRN prefix inclusion, a smaller name
gazetteer, "of <city>" LOC over-extension). Where they disagree, the
averaged one-hot votes become fractional — genuine boundary uncertainty
for the focal soft CE to learn from. Annotators never see gold spans.
"""

import re
from dataclasses import dataclass

from faker.providers.person.en_US import Provider as PersonProvider

from app.deid.labels import LABEL_TO_ID, NUM_LABELS

Span = tuple[int, int, str]  # (start, end, PHI type)

_FIRST_NAMES = {n.lower() for n in PersonProvider.first_names}
_LAST_NAMES = {n.lower() for n in PersonProvider.last_names}
# A5's handicap: roughly half the gazetteer.
_FIRST_SMALL = {n for i, n in enumerate(sorted(_FIRST_NAMES)) if i % 2 == 0}
_LAST_SMALL = {n for i, n in enumerate(sorted(_LAST_NAMES)) if i % 2 == 0}

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
)
_TITLE_RE = r"(?:dr|mr|ms|mrs)\.?\s+"
_WORD_RE = re.compile(r"[a-z][a-z'-]*", re.IGNORECASE)

_DATE_RES = [
    re.compile(rf"\b(?:{_MONTHS})\s+\d{{1,2}}(?:,\s*\d{{4}})?\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
]
_BARE_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_PHONE_RE = re.compile(r"\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")
_MRN_PREFIXED_RE = re.compile(r"\b(?:mrn)[-:\s]*(\d{6,9})\b", re.IGNORECASE)
_MRN_BARE_RE = re.compile(r"\b\d{7,8}\b")
_AGE_RE = re.compile(r"\b(\d{1,3})([-\s]year[-\s]old)\b", re.IGNORECASE)
_AGE_CTX_RE = re.compile(r"\b(?:age[d:]?|turned)\s+(\d{1,3})\b", re.IGNORECASE)
_LOC_CTX_RE = re.compile(
    r"\b(of|in|from|to)\s+([A-Z][a-z'-]+(?:\s[A-Z][a-z'-]+)?)(,\s*[A-Z]{2})?"
)


@dataclass(frozen=True)
class AnnotatorConfig:
    include_titles: bool = False      # NAME span swallows "dr. " etc.
    bare_years: bool = False          # tags 1985 alone as DATE
    extend_phone: bool = False        # phone span swallows trailing period
    mrn_include_prefix: bool = False  # span covers "MRN-1234567" vs digits
    mrn_bare_digits: bool = True      # 7-8 bare digits are MRN
    small_gazetteer: bool = False     # misses ~half of names
    loc_include_prep: bool = False    # "of boston" instead of "boston"
    age_include_suffix: bool = False  # "47-year-old" vs "47"


CONFIGS: list[AnnotatorConfig] = [
    AnnotatorConfig(),  # A1: conservative baseline
    AnnotatorConfig(include_titles=True, mrn_include_prefix=True),           # A2
    AnnotatorConfig(bare_years=True, age_include_suffix=True),               # A3
    AnnotatorConfig(extend_phone=True, age_include_suffix=True,
                    mrn_bare_digits=False),                                  # A4
    AnnotatorConfig(small_gazetteer=True, loc_include_prep=True),            # A5
]
K = len(CONFIGS)


def _names(text: str, cfg: AnnotatorConfig) -> list[Span]:
    firsts = _FIRST_SMALL if cfg.small_gazetteer else _FIRST_NAMES
    lasts = _LAST_SMALL if cfg.small_gazetteer else _LAST_NAMES
    spans: list[Span] = []
    words = list(_WORD_RE.finditer(text))
    used: set[int] = set()
    for i, w in enumerate(words[:-1]):
        nxt = words[i + 1]
        gap = text[w.end() : nxt.start()]
        if gap.strip() == "" and w.group().lower() in firsts and nxt.group().lower() in lasts:
            start = w.start()
            if cfg.include_titles:
                m = re.search(_TITLE_RE + r"$", text[: w.start()], re.IGNORECASE)
                if m:
                    start = m.start()
            spans.append((start, nxt.end(), "NAME"))
            used.update((i, i + 1))
    # Lone first names, only with a conversational/title cue right before.
    cue = re.compile(r"(?:morning|afternoon|thanks,?|so|daughter|with)\s+$", re.IGNORECASE)
    for i, w in enumerate(words):
        if i in used or w.group().lower() not in firsts:
            continue
        if cue.search(text[: w.start()]) or re.search(_TITLE_RE + r"$", text[: w.start()], re.IGNORECASE):
            spans.append((w.start(), w.end(), "NAME"))
    return spans


def _dates(text: str, cfg: AnnotatorConfig) -> list[Span]:
    spans = [(m.start(), m.end(), "DATE") for rx in _DATE_RES for m in rx.finditer(text)]
    if cfg.bare_years:
        covered = [(s, e) for s, e, _ in spans]
        for m in _BARE_YEAR_RE.finditer(text):
            if not any(s <= m.start() < e for s, e in covered):
                spans.append((m.start(), m.end(), "DATE"))
    return spans


def _phones(text: str, cfg: AnnotatorConfig) -> list[Span]:
    spans = []
    for m in _PHONE_RE.finditer(text):
        end = m.end()
        if cfg.extend_phone and end < len(text) and text[end] in ".,":
            end += 1  # over-extension: swallows trailing punctuation
        spans.append((m.start(), end, "PHONE"))
    return spans


def _mrns(text: str, cfg: AnnotatorConfig, taken: list[Span]) -> list[Span]:
    spans = []
    for m in _MRN_PREFIXED_RE.finditer(text):
        if cfg.mrn_include_prefix:
            spans.append((m.start(), m.end(), "MRN"))
        else:
            spans.append((m.start(1), m.end(1), "MRN"))
    if cfg.mrn_bare_digits:
        occupied = [(s, e) for s, e, _ in spans + taken]
        for m in _MRN_BARE_RE.finditer(text):
            if not any(s <= m.start() < e or s < m.end() <= e for s, e in occupied):
                spans.append((m.start(), m.end(), "MRN"))
    return spans


def _locs(text: str, cfg: AnnotatorConfig) -> list[Span]:
    spans = []
    for m in _LOC_CTX_RE.finditer(text):
        start = m.start() if cfg.loc_include_prep else m.start(2)
        end = m.end(3) if m.group(3) else m.end(2)
        spans.append((start, end, "LOC"))
    return spans


def _ages(text: str, cfg: AnnotatorConfig) -> list[Span]:
    spans = []
    for m in _AGE_RE.finditer(text):
        end = m.end(2) if cfg.age_include_suffix else m.end(1)
        spans.append((m.start(1), end, "AGE"))
    for m in _AGE_CTX_RE.finditer(text):
        spans.append((m.start(1), m.end(1), "AGE"))
    return spans


def annotate(text: str, cfg: AnnotatorConfig) -> list[Span]:
    """One annotator's spans, first-claim-wins de-overlapped (NAME > DATE >
    PHONE > MRN > LOC > AGE priority)."""
    date_phone = _dates(text, cfg) + _phones(text, cfg)
    raw = (
        _names(text, cfg)
        + date_phone
        + _mrns(text, cfg, taken=date_phone)
        + _locs(text, cfg)
        + _ages(text, cfg)
    )
    priority = {"NAME": 0, "DATE": 1, "PHONE": 2, "MRN": 3, "LOC": 4, "AGE": 5}
    raw.sort(key=lambda s: (priority[s[2]], s[0]))
    kept: list[Span] = []
    for span in raw:
        if not any(span[0] < e and s < span[1] for s, e, _ in kept):
            kept.append(span)
    return sorted(kept)


def annotate_ensemble(text: str) -> list[list[Span]]:
    return [annotate(text, cfg) for cfg in CONFIGS]


def spans_to_bio_ids(spans: list[Span], offsets: list[tuple[int, int]]) -> list[int]:
    """Char spans -> per-token BIO label ids for one annotator."""
    labels = [LABEL_TO_ID["O"]] * len(offsets)
    for start, end, phi in spans:
        first = True
        for i, (ts, te) in enumerate(offsets):
            if ts == te:  # special token
                continue
            if ts < end and start < te:  # any char overlap
                prefix = "B" if first else "I"
                labels[i] = LABEL_TO_ID[f"{prefix}-{phi}"]
                first = False
    return labels


def soft_labels(text: str, offsets: list[tuple[int, int]]) -> list[list[float]]:
    """[T, 13] fractional teacher distribution: mean of K one-hot votes."""
    votes = [spans_to_bio_ids(spans, offsets) for spans in annotate_ensemble(text)]
    n_tokens = len(offsets)
    dist = [[0.0] * NUM_LABELS for _ in range(n_tokens)]
    for annotator in votes:
        for t, label_id in enumerate(annotator):
            dist[t][label_id] += 1.0 / K
    return dist
