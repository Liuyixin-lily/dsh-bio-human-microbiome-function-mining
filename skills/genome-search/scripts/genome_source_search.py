#!/usr/bin/env python3
import argparse
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd


EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

SOURCE_SETS = {
    "skin": [
        "skin", "cutaneous", "dermal", "epidermal", "sebaceous",
        "skin swab", "skin scraping", "skin biopsy", "skin lesion",
        "neck skin", "forearm",
    ],
    "oral": [
        "oral cavity", "oral", "mouth", "saliva", "salivary",
        "dental plaque", "supragingival", "subgingival", "gingival",
        "periodontal", "tongue", "buccal", "cheek", "dental", "tooth",
        "teeth", "endodontic", "root canal", "parotid", "dental abscess",
    ],
    "gut": [
        "feces", "faeces", "stool", "fecal", "gut", "intestinal",
        "intestine", "rectal", "colon", "cecum",
    ],
    "respiratory": [
        "nasal", "nares", "nasopharynx", "oropharynx", "throat", "sputum",
        "lung", "bronchial", "airway", "respiratory tract",
    ],
    "urogenital": [
        "vaginal", "urogenital", "urine", "urinary", "urethral", "catheter",
    ],
    "blood": ["blood", "bloodstream", "bacteremia", "septicemia", "plasma"],
    "environment": [
        "soil", "sediment", "water", "marine", "freshwater", "wastewater",
        "sludge", "dust", "air", "rhizosphere",
    ],
}

SOURCE_FIELDS = {
    "isolation_source", "isolation source", "body_site", "body site",
    "host_body_site", "host_body_product", "source_name", "source_type",
    "sample_type", "tissue", "host_tissue", "tissue_lib", "isolationsite",
    "isolation site", "environment", "env_local_scale", "env_medium",
}


def request(url, params=None, retries=6, timeout=60):
    data = urllib.parse.urlencode(params).encode() if params else None
    last_error = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"User-Agent": "genome-search-skill/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"NCBI request failed after {retries} attempts: {last_error}")


def json_request(endpoint, params):
    return json.loads(request(f"{EUTILS}/{endpoint}", params))


def esearch(db, term, retmax=1000):
    result = json_request(
        "esearch.fcgi",
        {"db": db, "term": term, "retmode": "json", "retmax": retmax},
    )
    return result["esearchresult"]


def esummary(db, ids):
    return json_request(
        "esummary.fcgi",
        {"db": db, "id": ",".join(map(str, ids)), "retmode": "json"},
    )


def efetch_xml(db, ids):
    raw = request(
        f"{EUTILS}/efetch.fcgi",
        {"db": db, "id": ",".join(map(str, ids)), "retmode": "xml"},
    )
    return ET.fromstring(raw)


def chunks(values, size):
    for i in range(0, len(values), size):
        yield values[i : i + size]


def sleep_between(sleep):
    time.sleep(sleep)


def read_lines(path):
    return list(dict.fromkeys(line.strip() for line in Path(path).read_text().splitlines() if line.strip()))


def expand_sources(source_args, source_file):
    terms = []
    labels = []
    for value in source_args or []:
        for token in value.split(","):
            token = token.strip()
            if token:
                labels.append(token)
                key = token.lower()
                if key in SOURCE_SETS:
                    terms.extend(SOURCE_SETS[key])
                else:
                    terms.append(token)
    if source_file:
        terms.extend(line.strip() for line in Path(source_file).read_text().splitlines() if line.strip())
    return list(dict.fromkeys(labels)), list(dict.fromkeys(terms))


def find_terms(text, terms):
    text = text.casefold()
    matched = []
    for term in terms:
        pattern = rf"(?<![a-z0-9]){re.escape(term.casefold())}(?![a-z0-9])"
        if re.search(pattern, text):
            matched.append(term)
    return sorted(set(matched), key=lambda x: terms.index(x))


def parse_biosample_metadata(root):
    metadata = {}
    for sample in root.findall(".//BioSample"):
        accession = sample.attrib.get("accession", "")
        title = sample.findtext("./Description/Title", "") or ""
        organism_el = sample.find("./Description/Organism")
        organism = organism_el.attrib.get("taxonomy_name", "") if organism_el is not None else ""
        attributes = []
        for attr in sample.findall("./Attributes/Attribute"):
            name = attr.attrib.get("harmonized_name") or attr.attrib.get("attribute_name") or ""
            value = (attr.text or "").strip()
            if name:
                attributes.append([name, value])
        metadata[accession] = {
            "biosample_accession": accession,
            "biosample_title": title,
            "organism": organism,
            "attributes": attributes,
        }
    return metadata


def get_biosample_by_uids(uids, cache_dir, sleep=0.35):
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "biosample_by_uid.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    todo = [uid for uid in uids if str(uid) not in cache]
    for index, batch in enumerate(chunks(todo, 90), 1):
        root = efetch_xml("biosample", batch)
        parsed = parse_biosample_metadata(root)
        for sample in parsed.values():
            uid = None
            for el in root.findall(".//BioSample"):
                if el.attrib.get("accession") == sample["biosample_accession"]:
                    uid = el.attrib.get("id")
                    break
            # efetch returns id in the XML; use it where available.
            if uid:
                cache[str(uid)] = sample
        print(f"[biosample-uids] batch {index} | cached={len(cache)}/{len(cache) + len(todo)}", flush=True)
        sleep_between(sleep)
        path.write_text(json.dumps(cache, ensure_ascii=False))
    return cache


def get_biosample_by_accessions(accessions, cache_dir, sleep=0.35):
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "biosample_by_accession.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    todo = [acc for acc in accessions if acc and acc not in cache]
    for index, batch in enumerate(chunks(todo, 80), 1):
        term = " OR ".join(f'"{acc}"[Accession]' for acc in batch)
        result = esearch("biosample", term)
        uids = result.get("idlist", [])
        if uids:
            root = efetch_xml("biosample", uids)
            for sample in parse_biosample_metadata(root).values():
                cache[sample["biosample_accession"]] = sample
        print(f"[biosample] batch {index} | cached={len(cache)}/{len(cache) + len(todo)}", flush=True)
        sleep_between(sleep)
        path.write_text(json.dumps(cache, ensure_ascii=False))
    return cache


def get_assembly_by_accessions(accessions, cache_dir, sleep=0.35):
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "assembly_by_accession.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    todo = [acc for acc in accessions if acc and acc not in cache]
    for index, batch in enumerate(chunks(todo, 100), 1):
        term = " OR ".join(f'"{acc}"[Assembly Accession]' for acc in batch)
        result = esearch("assembly", term)
        uids = result.get("idlist", [])
        if uids:
            summary = esummary("assembly", uids)["result"]
            for uid in summary.get("uids", []):
                item = summary[uid]
                accession = item.get("assemblyaccession", "")
                if accession:
                    cache[accession] = item
        print(f"[assembly-accessions] batch {index} | cached={len(cache)}/{len(cache) + len(todo)}", flush=True)
        sleep_between(sleep)
        path.write_text(json.dumps(cache, ensure_ascii=False))
    return cache


def get_assembly_by_biosamples(biosample_accessions, cache_dir, sleep=0.35):
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "assembly_by_biosample.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    todo = [acc for acc in biosample_accessions if acc and acc not in cache]
    for index, batch in enumerate(chunks(todo, 50), 1):
        term = " OR ".join(f'"{acc}"[BioSample Accession]' for acc in batch)
        result = esearch("assembly", term)
        uids = result.get("idlist", [])
        if uids:
            summary = esummary("assembly", uids)["result"]
            for uid in summary.get("uids", []):
                item = summary[uid]
                biosample = item.get("biosampleaccn", "")
                if biosample:
                    cache.setdefault(biosample, []).append(item)
        print(f"[assembly-biosamples] batch {index} | cached={len(cache)}/{len(cache) + len(todo)}", flush=True)
        sleep_between(sleep)
        path.write_text(json.dumps(cache, ensure_ascii=False))
    return {acc: cache.get(acc, []) for acc in biosample_accessions}


def attr_value(attributes, *names):
    wanted = {name.casefold() for name in names}
    for name, value in attributes:
        if name.casefold() in wanted and value:
            return value
    return ""


def source_text_for(assembly, biosample):
    parts = []
    if biosample:
        wanted = {name.casefold() for name in SOURCE_FIELDS}
        parts.extend(value for name, value in biosample.get("attributes", []) if name.casefold() in wanted and value)
        if biosample.get("biosample_title"):
            parts.append(biosample["biosample_title"])
    if assembly:
        isolate = assembly.get("biosource", {}).get("isolate", "")
        if isolate:
            parts.append(isolate)
        title = assembly.get("assemblytitle", "")
        if title:
            parts.append(title)
    return "; ".join(dict.fromkeys(part for part in parts if part))


def classify_row(assembly, biosample, terms):
    text = source_text_for(assembly, biosample)
    matched = find_terms(text, terms)
    if matched:
        classification = "Direct source match"
        evidence = "Requested source terms occur in Assembly/BioSample source metadata"
    elif biosample and any(value for _, value in biosample.get("attributes", []) if _.casefold() in {x.casefold() for x in SOURCE_FIELDS}):
        classification = "Source metadata present, no match"
        evidence = "BioSample has source metadata but none of the requested terms"
    elif assembly and (assembly.get("biosource", {}).get("isolate") or assembly.get("assemblytitle")):
        classification = "Source metadata present, no match"
        evidence = "Assembly has source-like metadata but none of the requested terms"
    elif biosample:
        classification = "No source metadata"
        evidence = "No usable source field was returned"
    else:
        classification = "BioSample not found"
        evidence = "No BioSample metadata was returned"
    return text, matched, classification, evidence


def base_row(input_value, assembly, biosample):
    assembly = assembly or {}
    biosample = biosample or {}
    projects = []
    for key in ("gb_bioprojects", "rs_bioprojects"):
        projects.extend(item.get("bioprojectaccn", "") for item in assembly.get(key, []) if item.get("bioprojectaccn"))
    attributes = biosample.get("attributes", [])
    return {
        "input": input_value,
        "assembly_accession": assembly.get("assemblyaccession", ""),
        "assembly_name": assembly.get("assemblyname", ""),
        "assembly_status": assembly.get("assemblystatus", ""),
        "organism": assembly.get("organism", "") or biosample.get("organism", ""),
        "taxid": assembly.get("taxid", ""),
        "biosample": biosample.get("biosample_accession", assembly.get("biosampleaccn", "")),
        "bioproject": "; ".join(dict.fromkeys(projects)),
        "submitter": assembly.get("submitterorganization", ""),
        "assembly_url": assembly.get("ftppath_refseq", "") or assembly.get("ftppath_genbank", ""),
        "isolation_source": attr_value(attributes, "isolation_source", "isolation source"),
        "body_site": attr_value(attributes, "body_site", "body site", "host_body_site", "host_body_product"),
        "source_name": attr_value(attributes, "source_name", "source_type", "sample_type", "tissue", "host_tissue"),
        "host": attr_value(attributes, "host", "host_name"),
        "host_disease": attr_value(attributes, "host_disease", "host disease"),
        "biosample_title": biosample.get("biosample_title", ""),
    }


def write_outputs(rows, out_xlsx, out_tsv, terms):
    out_xlsx = Path(out_xlsx)
    out_tsv = Path(out_tsv) if out_tsv else None
    df = pd.DataFrame(rows)
    for column in ("matched_terms", "source_text", "classification", "evidence"):
        if column not in df:
            df[column] = ""
    counts = df["classification"].value_counts().reset_index()
    counts.columns = ["classification", "n"]
    counts["percent"] = counts["n"] / max(len(df), 1) * 100
    organism_counts = (
        df.groupby(["classification", "organism"]).size().reset_index(name="n")
        .sort_values(["classification", "n"], ascending=[True, False])
    )
    direct = df[df["classification"].eq("Direct source match")]
    missing = df[df["classification"].eq("Assembly not found")]
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="All assemblies", index=False)
        counts.to_excel(writer, sheet_name="Summary", index=False)
        organism_counts.to_excel(writer, sheet_name="Class_by_organism", index=False)
        direct.to_excel(writer, sheet_name="Direct_source_matches", index=False)
        pd.DataFrame({"source_term": terms}).to_excel(writer, sheet_name="Source_terms", index=False)
        if not missing.empty:
            missing.to_excel(writer, sheet_name="Missing_assemblies", index=False)
    if out_tsv:
        out_tsv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_tsv, sep="\t", index=False)
    print("[done]", len(df), "rows")
    print(counts.to_string(index=False))
    print("[write]", out_xlsx)
    if out_tsv:
        print("[write]", out_tsv)


def run_taxa(args, labels, terms):
    taxa = read_lines(args.input)
    print(f"[load] {len(taxa)} taxa", flush=True)
    source_query = " OR ".join(f'"{term}"[All Fields]' for term in terms)
    rows = []
    for index, taxon in enumerate(taxa, 1):
        term = f'"{taxon}"[Organism] AND ({source_query})'
        search = esearch("biosample", term, retmax=args.retmax)
        uids = search.get("idlist", [])
        if not uids:
            rows.append({**base_row(taxon, {}, {}), "classification": "No matching BioSample", "evidence": "NCBI BioSample search returned no source-matched samples", "matched_terms": "", "source_text": ""})
            print(f"[taxon {index}/{len(taxa)}] {taxon}: 0 BioSample hits", flush=True)
            sleep_between(args.sleep)
            continue
        root = efetch_xml("biosample", uids)
        samples = list(parse_biosample_metadata(root).values())
        biosample_accessions = [sample["biosample_accession"] for sample in samples]
        by_biosample = get_assembly_by_biosamples(
            biosample_accessions,
            args.cache_dir,
            sleep=args.sleep,
        )
        biosample_by_accession = {sample["biosample_accession"]: sample for sample in samples}
        hit_count = 0
        for biosample_accession, assemblies in by_biosample.items():
            biosample = biosample_by_accession.get(biosample_accession, {})
            for assembly in assemblies:
                row = base_row(taxon, assembly, biosample)
                source_text, matched, classification, evidence = classify_row(assembly, biosample, terms)
                row.update(
                    {
                        "matched_terms": "; ".join(matched),
                        "source_text": source_text,
                        "classification": classification,
                        "evidence": evidence,
                    }
                )
                rows.append(row)
                hit_count += 1
        print(f"[taxon {index}/{len(taxa)}] {taxon}: {len(uids)} BioSample hits, {hit_count} assembly rows", flush=True)
        sleep_between(args.sleep)
    write_outputs(rows, args.out_xlsx, args.out_tsv, terms)


def run_accessions(args, labels, terms):
    accessions = read_lines(args.input)
    print(f"[load] {len(accessions)} accessions", flush=True)
    assemblies = get_assembly_by_accessions(accessions, args.cache_dir, sleep=args.sleep)
    biosample_accessions = sorted(
        {item.get("biosampleaccn", "") for item in assemblies.values() if item.get("biosampleaccn")}
    )
    biosamples = get_biosample_by_accessions(biosample_accessions, args.cache_dir, sleep=args.sleep)
    rows = []
    for accession in accessions:
        assembly = assemblies.get(accession)
        biosample = biosamples.get(assembly.get("biosampleaccn", ""), {}) if assembly else {}
        row = base_row(accession, assembly, biosample)
        if assembly is None:
            row.update(
                {
                    "matched_terms": "",
                    "source_text": "",
                    "classification": "Assembly not found",
                    "evidence": "NCBI Assembly search did not return this exact accession",
                }
            )
        else:
            source_text, matched, classification, evidence = classify_row(assembly, biosample, terms)
            row.update(
                {
                    "matched_terms": "; ".join(matched),
                    "source_text": source_text,
                    "classification": classification,
                    "evidence": evidence,
                }
            )
        rows.append(row)
    write_outputs(rows, args.out_xlsx, args.out_tsv, terms)


def main():
    parser = argparse.ArgumentParser(description="Search or audit NCBI GCF/GCA genomes by source metadata.")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    taxa = subparsers.add_parser("taxa", help="Find source-matched assemblies from taxon names")
    taxa.add_argument("--input", required=True, help="Text file with one taxon name per line")
    taxa.add_argument("--source", action="append", help="Built-in source name or comma-separated custom terms")
    taxa.add_argument("--source-file", help="Text file with one source term per line")
    taxa.add_argument("--retmax", type=int, default=1000)
    taxa.add_argument("--sleep", type=float, default=0.35)

    accessions = subparsers.add_parser("accessions", help="Audit a GCF/GCA list for source metadata")
    accessions.add_argument("--input", required=True, help="Text file with one GCF/GCA accession per line")
    accessions.add_argument("--source", action="append", help="Built-in source name or comma-separated custom terms")
    accessions.add_argument("--source-file", help="Text file with one source term per line")
    accessions.add_argument("--sleep", type=float, default=0.35)

    for subparser in (taxa, accessions):
        subparser.add_argument("--out-xlsx", required=True)
        subparser.add_argument("--out-tsv")
        subparser.add_argument("--cache-dir", type=Path, default=Path("work/genome_search_cache"))

    args = parser.parse_args()
    labels, terms = expand_sources(args.source, args.source_file)
    if not terms:
        parser.error("Specify --source and/or --source-file")
    print("[source]", "; ".join(labels) if labels else "custom")
    print("[terms]", "; ".join(terms), flush=True)
    if args.mode == "taxa":
        run_taxa(args, labels, terms)
    else:
        run_accessions(args, labels, terms)


if __name__ == "__main__":
    main()
