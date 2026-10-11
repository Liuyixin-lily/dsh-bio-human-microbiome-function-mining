#!/usr/bin/env python3
"""Generate final candidate summaries from a scored candidate table.

Reads `scored_candidates_full.tsv`, optional `candidate_gene_evidence.tsv`, and
an optional project JSON that records `candidate_sequences.candidates` source
genome paths. Writes two deterministic artifacts:

- high_confidence_candidate_summary.tsv: every scored row with a short
  human-readable validation status and a machine-readable verdict.
- final_target_candidates.tsv: only the priority rules configured by
  --final-rules, defaulting to `USALIGN_TARGET_EC,SEQUENCE_ANNOTATION_CONFIRMED`.
- experimental_hypotheses.tsv: one explict falsifiable hypothesis per scored
  candidate, with mechanistic model, testable prediction, critical
  experiments, falsification criteria, ambient/alternative hypothesis,
  evidence chain, and optional literature citations.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


SUMMARY_FIELDS = [
    "overall_rank",
    "protein_accession",
    "organism_or_strain",
    "evidence_base",
    "tm_score_mean",
    "structural_score",
    "deer_distance",
    "deer_rank",
    "source_annotation",
    "gene_metadata",
    "fedkea_ec",
    "fedkea_confidence",
    "validation_status",
    "verdict",
]

FINAL_FIELDS = [
    "final_rank",
    "protein_accession",
    "organism_or_strain",
    "evidence_base",
    "tm_score_mean",
    "structural_score",
    "source_annotation",
    "locus_tag",
    "location",
    "fedkea_ec",
    "fedkea_confidence",
    "fedkea_accepted_name",
    "fedkea_other_names",
    "validation_status",
    "protein_fasta",
    "cds_fasta",
    "gene_fasta",
    "gene_source",
    "signalp_prediction",
    "is_secreted",
    "mature_protein_fasta",
]

HYPOTHESIS_FIELDS = [
    "overall_rank",
    "protein_accession",
    "organism_or_strain",
    "candidate_id",
    "target_context",
    "hypothesis_statement",
    "mechanistic_model",
    "testable_prediction",
    "critical_experiments",
    "falsification_criteria",
    "ambient_hypothesis",
    "evidence_chain",
    "literature_citations",
    "designer_notes",
    "provenance",
]


def read_tsv(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle, delimiter="\t") if row and any(row.values())]
    return rows


def load_candidate_paths(project_path: str | None) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Return candidate metadata and genome metadata from a project JSON."""
    candidates: dict[str, dict[str, str]] = {}
    genomes: dict[str, dict[str, str]] = {}
    if not project_path:
        return candidates, genomes
    project = json.loads(Path(project_path).read_text(encoding="utf-8"))
    cs = project.get("candidate_sequences") or {}
    genomes = {name: dict(info) for name, info in (cs.get("genomes") or {}).items()}
    for accession, info in (cs.get("candidates") or {}).items():
        candidates[accession.strip()] = dict(info)
    return candidates, genomes


def evidence_base(row: dict[str, str]) -> str:
    rule = row.get("priority_rule", row.get("priority_tier", ""))
    if rule == "SEQUENCE_ANNOTATION_CONFIRMED":
        return "sequence+annotation"
    if row.get("deer_distance", "").strip() or row.get("deer_rank", "").strip():
        return "DEER"
    if row.get("structural_score", "").strip() or row.get("tm_score_mean", "").strip():
        return "US-align"
    if row.get("sequence_score", "").strip():
        return "sequence"
    return "annotation"


def validation_status(row: dict[str, str]) -> str:
    rule = row.get("priority_rule", row.get("priority_tier", ""))
    if rule == "SEQUENCE_ANNOTATION_CONFIRMED":
        return "high-confidence: DIAMOND sequence hit with matching existing source annotation; structure screening skipped"
    if rule == "USALIGN_TARGET_EC":
        return "high-confidence: US-align near-native + FedKEA target EC " + row.get("fedkea_final_result", "")
    if rule == "DEER_FEDKEA_CONFIRMED":
        return "medium: DEER fallback candidate confirmed as enzyme by FedKEA"
    if rule == "USALIGN_OTHER_EC":
        return "medium: US-align near-native but FedKEA non-target EC " + row.get("fedkea_final_result", "")
    if rule == "USALIGN_NOT_ENZYME":
        return "low: US-align evidence but FedKEA predicts not an enzyme"
    if rule == "USALIGN_UNVALIDATED":
        return "medium: US-align near-native but no FedKEA validation yet"
    if rule == "DEER_FALLBACK":
        prob = row.get("fedkea_enzyme_probability", "").strip()
        if row.get("fedkea_is_enzyme", "").strip().lower() in ("false", "0", "no", ""):
            extra = " and FedKEA predicts not an enzyme" + (f", probability {prob}" if prob else "")
        elif prob:
            extra = f"; FedKEA probability {prob}"
        else:
            extra = ""
        return "low: DEER-only candidate" + extra
    if rule == "SEQUENCE_ONLY":
        return "sequence-only candidate; no structural validation"
    return "annotation-only candidate; no screening evidence"


def verdict(row: dict[str, str]) -> str:
    rule = row.get("priority_rule", row.get("priority_tier", ""))
    if rule == "SEQUENCE_ANNOTATION_CONFIRMED":
        return "high:sequence+annotation"
    if rule == "USALIGN_TARGET_EC":
        return "high:US-align+target_EC"
    if rule == "DEER_FEDKEA_CONFIRMED":
        return "medium:deer_fedkea_enzyme"
    if rule == "USALIGN_OTHER_EC":
        return "medium:US-align+non_target_EC"
    if rule == "USALIGN_NOT_ENZYME":
        return "low:US-align+not_enzyme"
    if rule == "USALIGN_UNVALIDATED":
        return "medium:US-align+unvalidated"
    if rule == "DEER_FALLBACK":
        return "low:deer_only"
    if rule == "SEQUENCE_ONLY":
        return "low:sequence_only"
    return "low:annotation_only"


def fetch_source_annotation(row: dict[str, str]) -> str:
    for key in ("annotation", "source_description", "existing_annotation"):
        value = (row.get(key) or "").strip()
        if value:
            return value
    return ""


def target_context(project: dict[str, Any]) -> str:
    card = project.get("target_function_card") or {}
    pieces = []
    if card.get("enzyme_name"):
        pieces.append(card["enzyme_name"])
    if card.get("ec"):
        pieces.append(f"EC {card['ec']}")
    if card.get("reaction"):
        pieces.append(f"reaction: {card['reaction']}")
    elif card.get("substrate") and card.get("product"):
        pieces.append(f"{card['substrate']} -> {card['product']}")
    return " | ".join(pieces)


def hypothesis_statement(row: dict[str, str], project: dict[str, Any], target: str) -> str:
    acc = row.get("protein_accession") or row.get("candidate_id") or ""
    organism = row.get("organism_or_strain") or ""
    rule = row.get("priority_rule", row.get("priority_tier", ""))
    if rule == "SEQUENCE_ANNOTATION_CONFIRMED":
        basis = "strong DIAMOND sequence similarity and existing source annotation matching the target function"
    elif rule == "USALIGN_TARGET_EC":
        basis = "high structural similarity to the reference enzyme and FedKEA-predicted target EC"
    elif rule == "USALIGN_OTHER_EC":
        basis = "high structural similarity to the reference enzyme, although FedKEA predicts a different EC"
    elif rule == "USALIGN_NOT_ENZYME":
        basis = "high structural similarity to the reference enzyme but FedKEA predicts no enzyme activity"
    elif rule == "DEER_FEDKEA_CONFIRMED":
        basis = "DEER fallback activity and FedKEA-predicted enzyme activity"
    elif rule == "DEER_FALLBACK":
        basis = "DEER fallback structural resemblance without independent functional validation"
    elif rule == "SEQUENCE_ONLY":
        basis = "DIAMOND sequence similarity without resolved structural validation"
    else:
        basis = "source genome annotation alone"
    target_short = card_summary(project) or "the requested human-microbiome metabolic function"
    return (
        f"{organism} encodes the candidate protein {acc} that carries out {target_short}, "
        f"supported by {basis}."
    )


def card_summary(project: dict[str, Any]) -> str:
    card = project.get("target_function_card") or {}
    if card.get("enzyme_name"):
        return card["enzyme_name"]
    if card.get("ec"):
        return f"the EC {card['ec']} enzyme"
    if card.get("reaction"):
        return f"the {card['reaction']} reaction"
    return ""


def mechanistic_model(row: dict[str, str], project: dict[str, Any]) -> str:
    source = fetch_source_annotation(row)
    rule = row.get("priority_rule", row.get("priority_tier", ""))
    model = "The protein is a divergent homolog of the target enzyme family."
    if source:
        model += f" The source annotation describes it as: {source}."
    if rule in ("USALIGN_TARGET_EC", "USALIGN_OTHER_EC", "DEER_FEDKEA_CONFIRMED"):
        model += " Structural and/or functional prediction support an enzyme active site that can accommodate the target substrate."
    elif rule == "SEQUENCE_ANNOTATION_CONFIRMED":
        model += " Existing functional annotation and sequence similarity together support enzyme activity; structural validation was not required."
    elif rule == "SEQUENCE_ONLY":
        model += " Sequence similarity supports an evolutionary relationship, but the active site geometry is unverified."
    return model


def testable_prediction(row: dict[str, str]) -> str:
    rule = row.get("priority_rule", row.get("priority_tier", ""))
    if rule in ("SEQUENCE_ANNOTATION_CONFIRMED", "USALIGN_TARGET_EC"):
        return "Purified recombinant protein will catalyze the target reaction in vitro with detectable substrate depletion and product formation."
    if rule in ("USALIGN_OTHER_EC", "DEER_FEDKEA_CONFIRMED"):
        return "Purified recombinant protein will show enzyme activity in vitro; the EC assignment will be reconciled by substrate/product assays."
    if rule == "SEQUENCE_ONLY":
        return "Purified recombinant protein will fold into the predicted structure and will either support the target reaction or bind the target substrate."
    if rule in ("USALIGN_UNVALIDATED", "DEER_FALLBACK"):
        return "Purified recombinant protein will show measurable activity in at least one compatible enzyme assay when tested under the conditions specified in the study."
    return "Purified recombinant protein will show no catalytic activity specific to the target reaction in the primary assay."


def critical_experiments(row: dict[str, str]) -> str:
    acc = row.get("protein_accession") or row.get("candidate_id") or ""
    parts = [
        f"Heterologous expression: clone and express {acc} in E. coli, purify the recombinant protein, and run an in vitro target-substrate assay with product detection controls.",
        "Knockout/complement: delete or knock down the native gene in the source organism and show loss of the predicted phenotype, then restore activity with a complementation construct.",
        "Specificity controls: include a catalytically dead mutant or unrelated enzyme as a negative control and a characterized ortholog as a positive control.",
    ]
    return "\n".join(parts)


def falsification_criteria(row: dict[str, str]) -> str:
    rule = row.get("priority_rule", row.get("priority_tier", ""))
    if rule == "SEQUENCE_ANNOTATION_CONFIRMED":
        return "No substrate conversion above the negative-control limit after at least three biological replicates, or the existing annotation fails to reproduce in the source organism, would falsify the hypothesis."
    if rule == "USALIGN_TARGET_EC":
        return "No substrate conversion above the negative-control limit after at least three biological replicates, or a catalytically dead mutant retains full activity, would falsify the hypothesis."
    if rule in ("DEER_FEDKEA_CONFIRMED", "USALIGN_OTHER_EC"):
        return "No enzyme activity in the primary assay and no alternative substrate conversion in orthogonal assays would lower priority and require reinterpretation of the structural/functional evidence."
    if rule == "SEQUENCE_ONLY":
        return "Failure to express, failure to fold into the predicted domain, or lack of detectable binding/activity would reject the hypothesis as a functional homolog."
    return "No phenotype change after knockout, or no in vitro activity after heterologous expression, would falsify the functional claim."


def ambient_hypothesis(row: dict[str, str]) -> str:
    source = fetch_source_annotation(row)
    if source:
        return f"Alternative: the protein has the function recorded in its current annotation ({source}), rather than the target enzyme activity."
    return "Alternative: the protein is a structural paralog without the target enzyme activity, or the observed evidence is an artifact of domain similarity."


def evidence_chain(row: dict[str, str]) -> str:
    parts = []
    if row.get("sequence_score", "").strip():
        parts.append(f"DIAMOND sequence evidence={row['sequence_score']}")
    if row.get("tm_score_mean", "").strip():
        parts.append(f"US-align TM={row['tm_score_mean']}")
    if row.get("deer_distance", "").strip():
        parts.append(f"DEER distance={row['deer_distance']}")
    if row.get("fedkea_final_result", "").strip():
        parts.append(f"FedKEA EC={row['fedkea_final_result']}")
    source = fetch_source_annotation(row)
    if source:
        parts.append(f"source_annotation={source}")
    return " -> ".join(parts) if parts else "no machine-generated screening evidence recorded"


def literature_citations(row: dict[str, str], literature_rows: list[dict[str, str]]) -> str:
    acc = row.get("protein_accession") or row.get("candidate_id") or ""
    organism = row.get("organism_or_strain") or ""
    matches = [
        lit for lit in literature_rows
        if (lit.get("protein_accession") or "") == acc
        or ((lit.get("candidate_id") or "") and (row.get("candidate_id") or "") and lit["candidate_id"] == row["candidate_id"])
        or ((lit.get("organism_or_strain") or "") and (organism or "") and lit["organism_or_strain"] == organism)
    ]
    refs = []
    for lit in matches:
        ref_type = lit.get("reference_type", "")
        ref_id = lit.get("reference_id", "")
        finding = lit.get("finding", "")
        if lit.get("verified", "").lower() not in ("yes", "true", "1"):
            continue
        if ref_id:
            refs.append(ref_id + (f" ({finding})" if finding else ""))
        elif finding:
            refs.append(finding)
    return "; ".join(refs)


def designer_notes(row: dict[str, str]) -> str:
    note = row.get("source_annotation_note", "")
    if note:
        return f"Start from the existing annotation note: {note}"
    return "Generate from sequencing/genome annotation and screening evidence; do not fabricate wet-lab data."


def provenance() -> str:
    return "plugin:summarize_candidates:v2:hypotheses"


def gene_metadata(row: dict[str, str], evidence_by_id: dict[str, dict[str, str]]) -> str:
    candidate_id = row.get("candidate_id") or row.get("protein_accession") or ""
    ev = evidence_by_id.get(candidate_id, {})
    pieces = []
    locus = ev.get("locus_tag") or row.get("source_locus_tag") or ""
    if locus:
        pieces.append(locus)
    location = ev.get("location") or ""
    if location:
        pieces.append(location)
    note = row.get("source_annotation_note") or ""
    if note and note not in pieces:
        pieces.append(note)
    return ";".join(pieces)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", type=Path, required=True, help="scored_candidates_full.tsv.")
    parser.add_argument("--gene-evidence", type=Path, help="candidate_gene_evidence.tsv.")
    parser.add_argument("--literature", type=Path, help="Optional verified literature_evidence.tsv.")
    parser.add_argument("--project", type=Path, help="Project JSON with candidate_sequences metadata.")
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("."),
        help="Directory to write final artifacts. Defaults to the current directory.",
    )
    parser.add_argument(
        "--final-rules",
        default="USALIGN_TARGET_EC,SEQUENCE_ANNOTATION_CONFIRMED",
        help="Comma-separated priority rules included in final_target_candidates.tsv.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = read_tsv(args.scored)
    if not rows:
        print(f"error: no candidate rows in {args.scored}", file=sys.stderr)
        return 2
    evidence_rows = read_tsv(args.gene_evidence) if args.gene_evidence else []
    evidence_by_id = {row.get("candidate_id") or row.get("protein_accession") or "": row for row in evidence_rows if row}
    literature_rows = read_tsv(args.literature) if args.literature else []
    candidates, genomes = load_candidate_paths(str(args.project) if args.project else None)
    project = {}
    if args.project and Path(args.project).is_file():
        try:
            project = json.loads(Path(args.project).read_text(encoding="utf-8"))
        except Exception:
            project = {}
    final_rules = {rule.strip() for rule in args.final_rules.split(",") if rule.strip()}

    summary_rows: list[dict[str, str]] = []
    final_rows: list[dict[str, str]] = []
    hypothesis_rows: list[dict[str, str]] = []
    for row in rows:
        acc = row.get("protein_accession") or row.get("candidate_id") or ""
        candidate_id = row.get("candidate_id") or acc
        meta = candidates.get(acc, {})
        organism = row.get("organism_or_strain") or meta.get("source_genome", "")
        summary = {
            "overall_rank": row.get("overall_rank", ""),
            "protein_accession": acc,
            "organism_or_strain": organism,
            "evidence_base": evidence_base(row),
            "tm_score_mean": row.get("tm_score_mean", ""),
            "structural_score": row.get("structural_score", ""),
            "deer_distance": row.get("deer_distance", ""),
            "deer_rank": row.get("deer_rank", ""),
            "source_annotation": fetch_source_annotation(row),
            "gene_metadata": gene_metadata(row, evidence_by_id),
            "fedkea_ec": row.get("fedkea_final_result", ""),
            "fedkea_confidence": row.get("fedkea_ec_confidence", ""),
            "validation_status": validation_status(row),
            "verdict": verdict(row),
        }
        summary_rows.append(summary)

        hyp_ctx = target_context(project)
        if not hyp_ctx:
            hyp_ctx = "human-microbiome metabolic function specified in the project target card"
        hyp_rank = row.get("overall_rank", "")
        hypothesis_rows.append(
            {
                "overall_rank": hyp_rank,
                "protein_accession": acc,
                "organism_or_strain": organism,
                "candidate_id": candidate_id,
                "target_context": hyp_ctx,
                "hypothesis_statement": hypothesis_statement(row, project, hyp_ctx),
                "mechanistic_model": mechanistic_model(row, project),
                "testable_prediction": testable_prediction(row),
                "critical_experiments": critical_experiments(row),
                "falsification_criteria": falsification_criteria(row),
                "ambient_hypothesis": ambient_hypothesis(row),
                "evidence_chain": evidence_chain(row),
                "literature_citations": literature_citations(row, literature_rows),
                "designer_notes": designer_notes(row),
                "provenance": provenance(),
            }
        )

        rule = row.get("priority_rule", row.get("priority_tier", ""))
        if rule in final_rules:
            protein_fasta = meta.get("protein_fasta") or ""
            cds_fasta = meta.get("cds_fasta") or ""
            if not protein_fasta and organism in genomes:
                protein_fasta = (genomes[organism] or {}).get("protein_fasta", "")
            if not cds_fasta and organism in genomes:
                cds_fasta = (genomes[organism] or {}).get("cds_fasta", "")
            ev = evidence_by_id.get(acc, {})
            gene_fasta = meta.get("gene_fasta") or ""
            if not gene_fasta:
                gene_fasta = "outputs/task/candidate_sequences/candidate_gene_sequences.fna"
            mature_fasta = "outputs/task/candidate_sequences/candidate_mature_proteins.faa"
            final_rows.append(
                {
                    "final_rank": str(len(final_rows) + 1),
                    "protein_accession": acc,
                    "organism_or_strain": organism,
                    "evidence_base": evidence_base(row),
                    "tm_score_mean": row.get("tm_score_mean", ""),
                    "structural_score": row.get("structural_score", ""),
                    "source_annotation": fetch_source_annotation(row),
                    "locus_tag": ev.get("locus_tag", ""),
                    "location": ev.get("location", ""),
                    "fedkea_ec": row.get("fedkea_final_result", ""),
                    "fedkea_confidence": row.get("fedkea_ec_confidence", ""),
                    "fedkea_accepted_name": row.get("fedkea_accepted_name", ""),
                    "fedkea_other_names": row.get("fedkea_other_names", ""),
                    "validation_status": validation_status(row),
                    "protein_fasta": protein_fasta,
                    "cds_fasta": cds_fasta,
                    "gene_fasta": gene_fasta,
                    "gene_source": ev.get("gene_seq_source", ""),
                    "signalp_prediction": ev.get("signalp_prediction", ""),
                    "is_secreted": ev.get("is_secreted", ""),
                    "mature_protein_fasta": mature_fasta if ev.get("is_secreted") == "Yes" else "",
                }
            )

    summary_path = args.outdir / "high_confidence_candidate_summary.tsv"
    final_path = args.outdir / "final_target_candidates.tsv"
    hypotheses_path = args.outdir / "experimental_hypotheses.tsv"
    write_tsv(summary_path, SUMMARY_FIELDS, summary_rows)
    write_tsv(final_path, FINAL_FIELDS, final_rows)
    write_tsv(hypotheses_path, HYPOTHESIS_FIELDS, hypothesis_rows)
    print(f"wrote {summary_path} ({len(summary_rows)} rows)")
    print(f"wrote {final_path} ({len(final_rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
