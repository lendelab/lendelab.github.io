"""Shared helpers for the publication scripts: WORK schema, names, HTTP."""

import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ORCID_DIR = DATA / "orcid"
PUB_DIR = DATA / "publications"
EXTRA_DIR = PUB_DIR / "extra"
GROUP_FILE = PUB_DIR / "group.yaml"
REJECTED_FILE = PUB_DIR / "rejected.yaml"
MEMBERS_DIR = DATA / "members"

USER_AGENT = "lendelab-publications/1.0 (+https://lendelab.github.io/)"

FIELDS = ["id", "type", "year", "status", "authors", "editors", "title", "container",
          "volume", "issue", "pages", "publisher", "doi", "url", "lang"]
TYPES = {"article", "chapter", "book", "edited-book", "review", "conference-paper",
         "presentation", "poster", "dataset", "software", "report", "thesis", "other"}
STATUSES = {"published", "in_press", "forthcoming"}

FALLBACK_MEMBERS = [
    ("olga-ivanova", "0000-0002-9657-5380", "Olga", "Ivanova"),
    ("elena-garcia-pinuela", "0009-0008-4274-6835", "Elena", "García Piñuela"),
    ("jordi-just-alcaraz", "0000-0002-7003-5466", "Jordi", "Just Alcaraz"),
    ("emma-machado-de-souza", "0000-0003-4443-9739", "Emma", "Machado de Souza"),
    ("soraya-mendez-sanz", "0000-0002-3804-6587", "Soraya", "Méndez Sanz"),
    ("esther-ochoa-obeso", "0000-0002-9205-2902", "Esther", "Ochoa Obeso"),
    ("ariadna-verges-bonaventura", "0009-0006-0125-0898", "Ariadna", "Vergés Bonaventura"),
    ("montserrat-rangel-vicente", "0000-0001-6891-7921", "Montserrat", "Rangel Vicente"),
]

PARTICLES = {"de", "del", "la", "las", "los", "da", "das", "do", "dos", "van", "von", "der",
             "den", "di", "du", "le", "y", "i"}


def warn(message):
    print(f"::warning::{message}", file=sys.stderr)


def fold(text):
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def norm_title(title):
    text = re.sub(r"<[^>]+>", " ", str(title or ""))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", fold(text)).split())


def norm_doi(doi):
    doi = str(doi or "").strip().lower()
    doi = re.sub(r"^(doi:\s*|https?://(dx\.)?doi\.org/)", "", doi)
    return doi if doi.startswith("10.") else ""


def strip_tags(text):
    text = html.unescape(html.unescape(str(text or "")))
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())


def slugify(text, limit=6):
    words = re.sub(r"[^a-z0-9]+", " ", fold(text)).split()
    return "-".join(words[:limit])


def work_keys(work):
    """Identity keys: DOI, else normalised title plus year."""
    keys = set()
    doi = norm_doi(work.get("doi"))
    wid = str(work.get("id") or "")
    if wid.startswith("doi:"):
        doi = doi or norm_doi(wid[4:])
    if doi:
        keys.add("doi:" + doi)
    title = norm_title(work.get("title"))
    if title:
        keys.add(f"title:{title}|{work.get('year')}")
    return keys


def ordered(work):
    out = {}
    for field in FIELDS:
        if field == "editors" and not work.get("editors"):
            continue
        value = work.get(field)
        if field in ("authors", "editors"):
            value = [{"family": p.get("family", ""), "given": p.get("given", "")} for p in value or []]
        elif field == "year":
            value = value if isinstance(value, int) else None
        elif value is None:
            value = ""
        out[field] = value
    for key in work:
        if key not in out and key not in FIELDS:
            out[key] = work[key]
    return out


def sort_key(work):
    return (-(work.get("year") or 0), norm_title(work.get("title")), str(work.get("id")))


def load_yaml(path):
    path = Path(path)
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class Dumper(yaml.SafeDumper):
    pass


def _str(dumper, value):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


Dumper.add_representer(str, _str)


def dump_yaml(data):
    return yaml.dump(data, Dumper=Dumper, sort_keys=False, allow_unicode=True,
                     default_flow_style=False, width=4096)


def smart_case(name):
    name = str(name or "").replace("\u2010", "-").replace("\u2011", "-")
    if not name or not name.isupper() or len(name) < 3:
        return name
    parts = re.split(r"(\s+|-)", name.lower())
    return "".join(p if p.lower() in PARTICLES else p[:1].upper() + p[1:] for p in parts)


def _tokens(full):
    raw = full.split()
    out, buffer = [], []
    for index, token in enumerate(raw):
        if token.lower() in PARTICLES and index < len(raw) - 1:
            buffer.append(token)
            continue
        out.append(" ".join(buffer + [token]))
        buffer = []
    return out


def split_name(full, members=()):
    """Split a credit name into family and given names."""
    full = smart_case(" ".join(str(full or "").split()))
    if not full:
        return {"family": "", "given": ""}
    folded = fold(full).replace("-", " ")
    for member in members:
        for form in member["name_forms"]:
            if folded == form:
                return {"family": member["family"], "given": member["given"]}
    if "," in full:
        family, given = full.split(",", 1)
        return {"family": family.strip(), "given": given.strip()}
    tokens = _tokens(full)
    if len(tokens) == 1:
        return {"family": tokens[0], "given": ""}
    if len(tokens) > 2 and "-" in tokens[-1]:
        return {"family": tokens[-1], "given": " ".join(tokens[:-1])}
    given = [tokens[0]]
    rest = tokens[1:]
    while len(rest) > 1 and re.fullmatch(r"[A-ZÀ-Ý]\.?(-[A-ZÀ-Ý]\.?)?", rest[0]):
        given.append(rest.pop(0))
    if len(rest) > 2:
        given += rest[:-2]
        rest = rest[-2:]
    return {"family": " ".join(rest), "given": " ".join(given)}


def load_members():
    members = []
    files = sorted(MEMBERS_DIR.glob("*.yaml")) if MEMBERS_DIR.exists() else []
    for path in files:
        data = load_yaml(path) or {}
        slug = data.get("slug") or path.stem
        members.append({
            "slug": slug,
            "orcid": str(data.get("orcid") or "").strip(),
            "given": str(data.get("given") or "").strip(),
            "family": str(data.get("family") or "").strip(),
            "citation_names": [str(n) for n in data.get("citation_names") or []],
        })
    if not members:
        members = [{"slug": s, "orcid": o, "given": g, "family": f, "citation_names": []}
                   for s, o, g, f in FALLBACK_MEMBERS]
    for member in members:
        forms = {fold(f"{member['given']} {member['family']}").replace("-", " ")}
        for name in member["citation_names"]:
            if "," in name:
                family, given = name.split(",", 1)
                name = f"{given.strip()} {family.strip()}"
            forms.add(fold(name).replace("-", " "))
        member["name_forms"] = {" ".join(f.split()) for f in forms if f.strip()}
    return members


LANG3 = {"spa": "es", "eng": "en", "fra": "fr", "fre": "fr", "por": "pt", "ita": "it", "deu": "de",
         "ger": "de", "cat": "ca", "glg": "gl", "rus": "ru", "ukr": "uk"}


def norm_lang(code):
    code = str(code or "").strip().lower().replace("_", "-").split("-")[0]
    return LANG3.get(code, code if len(code) == 2 else "")


def canonical(person, members):
    """A member's own name in the member's preferred split."""
    full = " ".join(fold(f"{person.get('given', '')} {person.get('family', '')}").replace("-", " ").split())
    for member in members:
        if full in member["name_forms"]:
            return {"family": member["family"], "given": member["given"]}
    return person


def _family_tokens(family):
    return [t for t in re.split(r"[\s-]+", fold(family)) if t and t not in PARTICLES]


def is_member(person, member):
    """A person matches a member when the first family token and given initial agree."""
    fam = _family_tokens(person.get("family"))
    given = fold(person.get("given")).strip()
    mfam = _family_tokens(member["family"])
    mgiven = fold(member["given"]).strip()
    if not fam or not mfam or fam[0] != mfam[0]:
        return False
    if len(fam) > 1 and len(mfam) > 1 and fam[1] != mfam[1]:
        return False
    return bool(given) and given[0] == mgiven[0]


def members_in(work, members):
    people = list(work.get("authors") or []) + list(work.get("editors") or [])
    return sorted({m["slug"] for m in members for p in people if is_member(p, m)})


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


_last_call = {}


def get_json(url, headers=None, min_interval=0.25, attempts=4, timeout=40):
    host = urllib.parse.urlsplit(url).netloc
    request_headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    delay = 2.0
    for attempt in range(1, attempts + 1):
        wait = _last_call.get(host, 0) + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()
        try:
            request = urllib.request.Request(url, headers=request_headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < attempts:
                retry = error.headers.get("Retry-After") if error.headers else None
                time.sleep(float(retry) if retry and retry.isdigit() else delay)
                delay *= 2
                continue
            raise HttpError(error.code, f"HTTP {error.code} for {url}") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            if attempt < attempts:
                time.sleep(delay)
                delay *= 2
                continue
            raise HttpError(0, f"{type(error).__name__} for {url}: {error}") from None
    raise HttpError(0, f"no response for {url}")


def initials(given):
    out = []
    for part in str(given or "").replace(".", ". ").split():
        if part.lower() in PARTICLES:
            continue
        if "-" in part:
            out.append("-".join(p[:1].upper() + "." for p in part.split("-") if p))
        else:
            out.append(part[:1].upper() + ".")
    return " ".join(out)


def apa_person(person, inverted=True):
    family, given = person.get("family", ""), initials(person.get("given"))
    if not given:
        return family
    return f"{family}, {given}" if inverted else f"{given} {family}"


def apa_names(people, inverted=True):
    names = [apa_person(p, inverted) for p in people or []]
    if len(names) > 20:
        names = names[:19] + ["..."] + names[-1:]
        return ", ".join(names[:-1]) + " " + names[-1]
    if len(names) <= 1:
        return "".join(names)
    conj = "e" if re.match(r"h?i(?![aeiou])", fold(names[-1])) else "y"
    return ", ".join(names[:-1]) + f" {conj} " + names[-1]


def apa_es(work):
    """One reference in APA 7 with Spanish conventions, Markdown italics."""
    kind = work.get("type")
    editors = work.get("editors") or []
    authors = work.get("authors") or []
    pages = str(work.get("pages") or "").replace("-", "–")
    when = "en prensa" if work.get("status") in ("in_press", "forthcoming") else str(work.get("year") or "s. f.")
    title = str(work.get("title") or "").rstrip(".")
    end = "" if title[-1:] in "?!" else "."
    container = work.get("container") or ""
    publisher = work.get("publisher") or ""
    if editors and not authors:
        head = f"{apa_names(editors)} ({'Ed.' if len(editors) == 1 else 'Eds.'}). ({when})."
    else:
        head = f"{apa_names(authors)} ({when})."
    label = {"dataset": "Conjunto de datos", "software": "Software", "presentation": "Comunicación",
             "poster": "Póster"}.get(kind)
    if kind in ("book", "edited-book", "report", "dataset", "software", "presentation", "poster", "thesis"):
        body = f"*{title}*" + (f" [{label}]" if label else "") + "."
        tail = [container if kind in ("presentation", "poster") else "", publisher]
    elif kind in ("chapter", "conference-paper"):
        eds = ""
        if editors:
            eds = f"{apa_names(editors, inverted=False)} ({'Ed.' if len(editors) == 1 else 'Eds.'}), "
        span = f" (pp. {pages})" if pages else ""
        body = f"{title}{end} En {eds}*{container}*{span}."
        tail = [publisher]
    else:
        body = f"{title}{end}"
        if container:
            vol = f", *{work['volume']}*" if work.get("volume") else ""
            iss = f"({work['issue']})" if work.get("issue") else ""
            if iss and not vol:
                iss = ", " + iss
            pp = f", {pages}" if pages else ""
            body += f" *{container}*{vol}{iss}{pp}."
        tail = [publisher if not container else ""]
    parts = [head, body] + [f"{t}." for t in tail if t]
    if work.get("doi"):
        parts.append(f"https://doi.org/{work['doi']}")
    elif work.get("url"):
        parts.append(work["url"])
    return " ".join(parts).replace("..", ".")
