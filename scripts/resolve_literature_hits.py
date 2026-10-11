#!/usr/bin/env python3
"""resolve_literature_hits.py — turn OpenAlex/DOI search hits into verified
PubMed records WITH ABSTRACTS.

Motivation (a real failure this fixes)
-------------------------------------
`academic_search.py` returns OpenAlex metadata: title, authors, journal, DOI.
Triage on titles alone once produced a false "no literature evidence" verdict:
the decisive paper's title ("Commensal Staphylococcus epidermidis contributes
to skin barrier homeostasis by generating protective ceramides") does not
contain the word "sphingomyelinase", while its ABSTRACT does. This script makes
the abstract unavoidable.

What it does
------------
1. Reads OpenAlex `--compact` lines (or any text containing DOIs) from stdin,
   and/or `--doi` values from argv.
2. Batch-converts DOIs -> PMIDs via the NCBI ID Converter.
3. Fetches full PubMed records (esummary + efetch abstract) for every PMID.
4. Emits a TSV with: pmid, doi, year, journal, first_author, title,
   abstract_status, abstract.
5. Prints a coverage summary and lists any hits that could NOT be resolved, so
   unresolved items are visible rather than silently dropped.

Guardrail: never invents a PMID or DOI. Unresolved hits are reported as such.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
IDCONV = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
UA = {"User-Agent": "human-microbiome-function-mining/literature-resolver"}
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s|\]\)\"'<>]+")


def http_get(url: str, timeout: int = 45, retries: int = 3) -> str:
    """GET with retries — transient SSL EOFs from NCBI are common."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as fh:
                return fh.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - retry any transport error
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise last if last else RuntimeError("http_get failed")


def parse_json_hits(text: str) -> list[dict]:
    """Parse `academic_search.py` default JSON output (a list or {results:[...]}).

    Note: this mode ALREADY carries an `abstract` field from OpenAlex, so the
    OpenAlex abstract alone can be enough to triage. We still resolve to PubMed
    so the cited identifier is a verified PMID rather than a preprint/DOI guess.
    """
    try:
        data = json.loads(text)
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("results") or data.get("works") or []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        authors = item.get("authors") or []
        first = ""
        if isinstance(authors, list) and authors:
            first = authors[0] if isinstance(authors[0], str) else str(authors[0])
        out.append({
            "title": item.get("title") or "",
            "first_author": first,
            "journal": item.get("journal") or item.get("host_venue") or "",
            "year": str(item.get("year") or "")[:4],
            "doi": (item.get("doi") or "").strip(),
            "abstract": item.get("abstract") or "",
        })
    return out


def parse_compact_lines(text: str) -> list[dict]:
    """Parse `academic_search.py --compact` output lines.

    Observed shape:
      [2022] TITLE | A1, A2 et al. | JOURNAL | DOI:10.xxxx/yyy | Cited:284
    """
    hits: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "DOI:" not in line:
            continue
        year_m = re.match(r"^\[(\d{4})\]\s*(.*)$", line)
        year = year_m.group(1) if year_m else ""
        body = year_m.group(2) if year_m else line
        parts = [p.strip() for p in body.split("|")]
        title = parts[0] if parts else ""
        authors = parts[1] if len(parts) > 1 else ""
        journal = parts[2] if len(parts) > 2 else ""
        doi = ""
        for p in parts:
            if p.startswith("DOI:"):
                doi = p[4:].strip()
        if doi.lower() in ("none", "null"):
            doi = ""
        hits.append({"title": title, "first_author": authors.split(",")[0].strip(),
                     "journal": journal, "year": year, "doi": doi})
    return hits


def collect_dois(text: str, extra: list[str]) -> list[str]:
    found = []
    for m in DOI_RE.finditer(text):
        d = m.group(0).rstrip(".,;")
        found.append(d)
    found.extend(d.strip() for d in extra)
    seen, out = set(), []
    for d in found:
        if not d:
            continue
        low = d.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(d)
    return out


def doi_to_pmid(dois: list[str]) -> dict[str, str]:
    """Batch DOI -> PMID via the NCBI ID Converter (max 200 ids/request)."""
    mapping: dict[str, str] = {}
    for i in range(0, len(dois), 100):
        chunk = dois[i:i + 100]
        url = (IDCONV + "?ids=" + urllib.parse.quote(",".join(chunk))
               + "&format=json&tool=hmfm&email=agent@example.org")
        try:
            data = json.loads(http_get(url))
        except Exception as exc:  # network hiccup must not silently drop hits
            print(f"WARN idconv failed for chunk starting {chunk[0]}: {exc}",
                  file=sys.stderr)
            continue
        for rec in data.get("records", []):
            doi = (rec.get("doi") or "").lower()
            pmid = rec.get("pmid")
            if doi and pmid:
                mapping[doi] = str(pmid)
    # ID Converter can miss DOIs; fall back to esearch per DOI
    for d in dois:
        if d.lower() in mapping:
            continue
        try:
            url = (f"{EUTILS}/esearch.fcgi?db=pubmed&retmode=json&term="
                   + urllib.parse.quote(f'"{d}"[AID]'))
            data = json.loads(http_get(url))
            ids = data.get("esearchresult", {}).get("idlist", [])
            if ids:
                mapping[d.lower()] = str(ids[0])
        except Exception:
            pass
    return mapping


def fetch_records(pmids: list[str]) -> dict[str, dict]:
    """Fetch bibliographic fields and ABSTRACTS.

    Abstracts are read from PubMed XML so that each record is delimited
    properly. An earlier text/regex implementation bled the tail of one record
    into the next record's abstract, which can mislead evidence triage.
    """
    out: dict[str, dict] = {}
    for i in range(0, len(pmids), 100):
        chunk = pmids[i:i + 100]
        ids = ",".join(chunk)
        try:
            s = json.loads(http_get(
                f"{EUTILS}/esummary.fcgi?db=pubmed&retmode=json&id={ids}"))
            res = s.get("result", {})
            for pid in res.get("uids", []):
                v = res[pid]
                out.setdefault(pid, {})["title"] = v.get("title", "")
                out[pid]["journal"] = v.get("source", "")
                out[pid]["year"] = (v.get("pubdate", "") or "")[:4]
                out[pid]["first_author"] = v.get("sortfirstauthor", "")
        except Exception as exc:
            print(f"WARN esummary failed: {exc}", file=sys.stderr)
        # abstracts via XML (structured, per-record delimited)
        try:
            xml_txt = http_get(
                f"{EUTILS}/efetch.fcgi?db=pubmed&retmode=xml&id={ids}")
            root = ET.fromstring(xml_txt)
            for art in root.iter("PubmedArticle"):
                pid_el = art.find(".//PMID")
                if pid_el is None or not pid_el.text:
                    continue
                pid = pid_el.text.strip()
                pieces: list[str] = []
                for at in art.iter("AbstractText"):
                    label = at.get("Label")
                    body = "".join(at.itertext()).strip()
                    if not body:
                        continue
                    pieces.append(f"{label}: {body}" if label else body)
                # also capture the article title as a fallback
                if not out.get(pid, {}).get("title"):
                    t = art.find(".//ArticleTitle")
                    if t is not None:
                        out.setdefault(pid, {})["title"] = "".join(t.itertext()).strip()
                out.setdefault(pid, {})["abstract"] = " ".join(pieces)
                # objective year / journal fallback from XML
                if not out[pid].get("year"):
                    y = art.find(".//PubDate/Year")
                    if y is not None and y.text:
                        out[pid]["year"] = y.text.strip()
                if not out[pid].get("journal"):
                    j = art.find(".//Journal/Title")
                    if j is not None and j.text:
                        out[pid]["journal"] = j.text.strip()
        except Exception as exc:
            print(f"WARN efetch(xml) failed: {exc}", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doi", action="append", default=[],
                    help="Resolve this DOI directly (repeatable).")
    ap.add_argument("--max-abstract-chars", type=int, default=1200)
    ap.add_argument("--tsv", help="Write the full table to this TSV path.")
    args = ap.parse_args()

    text = "" if sys.stdin.isatty() else sys.stdin.read()
    # `academic_search.py` emits JSON by default and compact text with --compact.
    hits = parse_json_hits(text)
    if not hits:
        hits = parse_compact_lines(text)
    dois = collect_dois(text, args.doi)
    # also pick up DOIs that appear only in the structured hits
    for h in hits:
        if h.get("doi"):
            dois.append(h["doi"])
    seen: set[str] = set()
    deduped: list[str] = []
    for d in dois:
        if d and d.lower() not in seen:
            seen.add(d.lower())
            deduped.append(d)
    dois = deduped

    if not dois:
        print("No DOIs found in input.", file=sys.stderr)
        return 1

    doi2pmid = doi_to_pmid(dois)
    pmids = [doi2pmid[d.lower()] for d in dois if d.lower() in doi2pmid]
    recs = fetch_records(sorted(set(pmids))) if pmids else {}

    rows = []
    unresolved = []
    for h in hits:
        doi = h.get("doi", "")
        pmid = doi2pmid.get(doi.lower(), "")
        rec = recs.get(pmid, {}) if pmid else {}
        if doi and not pmid:
            unresolved.append((doi, h.get("title", "")))
        rows.append({
            "pmid": pmid, "doi": doi,
            "year": rec.get("year") or h.get("year", ""),
            "journal": rec.get("journal") or h.get("journal", ""),
            "first_author": rec.get("first_author") or h.get("first_author", ""),
            "title": rec.get("title") or h.get("title", ""),
            "abstract": (rec.get("abstract") or "")[:args.max_abstract_chars],
        })
    for d in args.doi:
        if not any(r["doi"].lower() == d.lower() for r in rows):
            pmid = doi2pmid.get(d.lower(), "")
            rec = recs.get(pmid, {}) if pmid else {}
            if not pmid:
                unresolved.append((d, ""))
            rows.append({"pmid": pmid, "doi": d,
                         "year": rec.get("year", ""), "journal": rec.get("journal", ""),
                         "first_author": rec.get("first_author", ""),
                         "title": rec.get("title", ""),
                         "abstract": (rec.get("abstract") or "")[:args.max_abstract_chars]})

    hdr = ["pmid", "doi", "year", "journal", "first_author", "title", "abstract"]
    lines = ["\t".join(hdr)]
    for r in rows:
        lines.append("\t".join(str(r[c]).replace("\t", " ").replace("\n", " ")
                               for c in hdr))
    table = "\n".join(lines)
    print(table)

    if args.tsv:
        with open(args.tsv, "w", encoding="utf-8") as fh:
            fh.write(table + "\n")

    n_abs = sum(1 for r in rows if r["abstract"])
    print(f"\n--- resolution summary ---", file=sys.stderr)
    print(f"hits parsed     : {len(rows)}", file=sys.stderr)
    print(f"PMIDs resolved  : {sum(1 for r in rows if r['pmid'])}", file=sys.stderr)
    print(f"abstracts found : {n_abs}", file=sys.stderr)
    if unresolved:
        print(f"UNRESOLVED ({len(unresolved)}) - inspect manually, do NOT drop silently:",
              file=sys.stderr)
        for d, t in unresolved:
            print(f"  {d}  {t[:70]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
