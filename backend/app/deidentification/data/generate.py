"""Fill templates into documents with gold spans recorded during string
assembly — spans are correct by construction, never re-derived by search."""

import random
import re
from dataclasses import dataclass, field

from faker import Faker

from app.deidentification.data.templates import PHI_FAMILIES, TEMPLATES

SLOT_RE = re.compile(r"\{(name|first|date|phone|mrn|loc|age)(\d*)\}")

_MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]


@dataclass(frozen=True)
class GoldSpan:
    start: int
    end: int
    label: str
    text: str


@dataclass
class Document:
    text: str
    spans: list[GoldSpan]
    families: list[str] = field(default_factory=list)

    @property
    def primary_family(self) -> str:
        return max(set(self.families), key=self.families.count)


def _fill_value(slot: str, faker: Faker, rng: random.Random) -> tuple[str, str]:
    """-> (surface text, PHI label)"""
    match slot:
        case "name":
            return f"{faker.first_name()} {faker.last_name()}", "NAME"
        case "first":
            return faker.first_name(), "NAME"
        case "date":
            d = faker.date_object()
            fmt = rng.randrange(4)
            if fmt == 0:
                value = f"{_MONTHS[d.month - 1]} {d.day}, {d.year}"
            elif fmt == 1:
                value = f"{d.month:02d}/{d.day:02d}/{d.year}"
            elif fmt == 2:
                value = d.isoformat()
            else:
                value = f"{_MONTHS[d.month - 1]} {d.day}"
            return value, "DATE"
        case "phone":
            area, mid, last = (
                rng.randint(200, 989),
                rng.randint(200, 999),
                rng.randint(0, 9999),
            )
            fmt = rng.randrange(3)
            if fmt == 0:
                value = f"{area}-{mid}-{last:04d}"
            elif fmt == 1:
                value = f"({area}) {mid}-{last:04d}"
            else:
                value = f"{area}.{mid}.{last:04d}"
            return value, "PHONE"
        case "mrn":
            digits = rng.randint(1_000_000, 99_999_999)
            return (f"MRN-{digits}" if rng.random() < 0.5 else str(digits)), "MRN"
        case "loc":
            city = faker.city()
            return (
                f"{city}, {faker.state_abbr()}" if rng.random() < 0.35 else city
            ), "LOC"
        case "age":
            return str(rng.randint(18, 97)), "AGE"
    raise ValueError(f"unknown slot {slot}")


def fill_template(
    template: str, faker: Faker, rng: random.Random, base_offset: int = 0
):
    """-> (filled text, spans). Distinct suffixed slots ({name}, {name2})
    get distinct fills; repeated identical slot keys reuse the same fill."""
    fills: dict[str, tuple[str, str]] = {}
    parts: list[str] = []
    spans: list[GoldSpan] = []
    cursor = 0
    offset = base_offset
    for m in SLOT_RE.finditer(template):
        literal = template[cursor : m.start()]
        parts.append(literal)
        offset += len(literal)
        key = m.group(0)
        if key not in fills:
            fills[key] = _fill_value(m.group(1), faker, rng)
        value, label = fills[key]
        parts.append(value)
        spans.append(GoldSpan(offset, offset + len(value), label, value))
        offset += len(value)
        cursor = m.end()
    tail = template[cursor:]
    parts.append(tail)
    return "".join(parts), spans


def make_document(
    faker: Faker, rng: random.Random, *, phi_only: bool = False
) -> Document:
    """A document is 2-5 template instances joined by newlines — shaped like
    a stitched visit transcript."""
    pool = [t for t in TEMPLATES if not phi_only or t[0] in PHI_FAMILIES]
    n = rng.randint(2, 5)
    chosen = [pool[rng.randrange(len(pool))] for _ in range(n)]
    text_parts: list[str] = []
    spans: list[GoldSpan] = []
    families: list[str] = []
    offset = 0
    for family, template in chosen:
        filled, tspans = fill_template(template, faker, rng, base_offset=offset)
        text_parts.append(filled)
        spans.extend(tspans)
        families.append(family)
        offset += len(filled) + 1  # the joining "\n"
    return Document(text="\n".join(text_parts), spans=spans, families=families)


def generate_corpus(n: int, seed: int, *, phi_only: bool = False) -> list[Document]:
    rng = random.Random(seed)
    faker = Faker("en_US")
    faker.seed_instance(seed)
    return [make_document(faker, rng, phi_only=phi_only) for _ in range(n)]


def generate_dense_eval(n: int, seed: int, *, min_per_type: int = 40) -> list[Document]:
    """Entity-dense eval set: PHI templates only, and re-rolled until every
    type has at least `min_per_type` instances so per-type recall means
    something."""
    docs = generate_corpus(n, seed, phi_only=True)
    counts: dict[str, int] = {}
    for doc in docs:
        for span in doc.spans:
            counts[span.label] = counts.get(span.label, 0) + 1
    short = [
        label
        for label in ("NAME", "DATE", "PHONE", "MRN", "LOC", "AGE")
        if counts.get(label, 0) < min_per_type
    ]
    if short:
        raise RuntimeError(f"dense eval set too sparse for {short}: {counts}")
    return docs
