#!/usr/bin/env python3
"""End-to-end example test for the human-microbiome-function-mining plugin."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        card_json = tmp / "target_function_card.json"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "build_target_function_card.py"),
                "--output",
                str(card_json),
                "--target-id",
                "TEST_ENZ",
                "--enzyme-name",
                "test enzyme",
                "--ec",
                "3.1.1.-",
                "--sequence-file",
                "inputs/target.faa",
            ],
            check=True,
        )
        assert card_json.is_file()

        diamond = tmp / "diamond_hits.tsv"
        write_text(
            diamond,
            "\t".join(
                [
                    "qseqid",
                    "sseqid",
                    "pident",
                    "length",
                    "evalue",
                    "bitscore",
                    "qcovhsp",
                    "assembly_accession",
                    "organism_or_strain",
                    "annotation",
                ]
            )
            + "\n"
            + "\t".join(
                [
                    "q1",
                    "prot1",
                    "45.5",
                    "120",
                    "1e-30",
                    "220.1",
                    "0.85",
                    "GCF_1",
                    "Strain A",
                    "hypothetical",
                ]
            )
            + "\n"
            + "\t".join(
                [
                    "q2",
                    "prot2",
                    "80.0",
                    "150",
                    "1e-80",
                    "420.0",
                    "0.95",
                    "GCF_2",
                    "Strain B",
                    "hypothetical",
                ]
            )
            + "\n",
        )
        seq_hits = tmp / "sequence_hits.tsv"
        seq_candidates = tmp / "sequence_candidates.tsv"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "parse_sequence_hits.py"),
                "--input",
                str(diamond),
                "--out-hits",
                str(seq_hits),
                "--out-candidates",
                str(seq_candidates),
                "--tool",
                "diamond",
                "--tool-version",
                "2.1.8",
            ],
            check=True,
        )
        assert "prot1" in seq_hits.read_text(encoding="utf-8")

        usalign = tmp / "usalign.txt"
        write_text(
            usalign,
            "Template Name: target.pdb\n"
            "TM-score: 0.82\n"
            "RMSD: 1.2\n"
            "IDen: 40.0\n"
            "Aligned_length: 200\n"
            "Seq_identity: 40.0\n",
        )
        struct_hits = tmp / "structural_hits.tsv"
        struct_candidates = tmp / "structural_candidates.tsv"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "parse_usalign.py"),
                "--input",
                str(usalign),
                "--out-hits",
                str(struct_hits),
                "--out-candidates",
                str(struct_candidates),
                "--candidate-id",
                "prot1",
            ],
            check=True,
        )
        assert "0.82" in struct_candidates.read_text(encoding="utf-8")

        binary = tmp / "binary_result.txt"
        write_text(binary, "Accession\tIsEnzyme\tProbability\nprot1\tTrue\t0.98\n")
        conf = tmp / "enzyme_result_with_confidence.csv"
        write_text(
            conf,
            "Accession,FinalResult,confidence,accepted_name,other_names\n"
            "prot1,3.1.1.-,High,esterase,none\n",
        )
        fedkea = tmp / "fedkea_results.tsv"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "parse_fedkea.py"),
                "--binary-result",
                str(binary),
                "--confidence-csv",
                str(conf),
                "--output",
                str(fedkea),
                "--tool-version",
                "github-main",
            ],
            check=True,
        )
        assert "prot1" in fedkea.read_text(encoding="utf-8")

        faa = tmp / "candidate_annotations.faa"
        write_text(
            faa,
            ">prot1 [gene=estP] product=alpha_beta_hydrolase EC_number=3.1.1.- Pfam=PF12697 hypothetical\n"
            "MLAKCGT\n",
        )
        source_annotations = tmp / "source_feature_annotations.tsv"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "parse_source_annotations.py"),
                "--faa",
                str(faa),
                "--output",
                str(source_annotations),
            ],
            check=True,
        )
        assert "prot1" in source_annotations.read_text(encoding="utf-8")

        # SignalP + candidate sequence extraction with genomic .fna locus
        protein_fasta = tmp / "source_proteins.faa"
        write_text(
            protein_fasta,
            ">lcl|NZ_ABC123_cds_WP_prot1_1 [location=complement(100..300)] "
            "[protein_id=prot1] [gene=estP] [protein=test_esterase]\n"
            "MLAKCGTMNP\n",
        )
        cds_fasta = tmp / "source_cds.ffn"
        write_text(
            cds_fasta,
            ">lcl|NZ_ABC123_cds_WP_prot1_1 [location=complement(100..300)] "
            "[protein_id=prot1] [gene=estP]\n"
            "ATGCTGGCAAAATGCGGTAC\n",
        )
        genomic_fna = tmp / "source_genome.fna"
        # location=complement(100..300) extracts and reverse-complements fna[99:300]
        fna_seq = "A" * 99 + "CCTTTG" + "G" * 200
        write_text(genomic_fna, ">NZ_ABC123\n" + "\n".join(fna_seq[i : i + 60] for i in range(0, len(fna_seq), 60)) + "\n")

        signalp_gff = tmp / "signalp.gff3"
        write_text(
            signalp_gff,
            "prot1\tSignalP\tsig_peptide\t1\t2\t.\t+\t.\tID=prot1;Prediction=SP\n",
        )
        signalp_summary = tmp / "signalp_summary.txt"
        write_text(
            signalp_summary,
            "prot1\tProtein\tSP\tCS pos: 2-3\n",
        )
        parsed_signalp = tmp / "parsed_signalp.tsv"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "parse_signalp.py"),
                "--gff3",
                str(signalp_gff),
                "--summary",
                str(signalp_summary),
                "--output",
                str(parsed_signalp),
            ],
            check=True,
        )
        parsed_text = parsed_signalp.read_text(encoding="utf-8")
        assert "2|3" in parsed_text
        assert "SP" in parsed_text

        signalp_tsv = tmp / "candidate_signal_peptides.tsv"
        write_text(
            signalp_tsv,
            "\t".join(
                [
                    "candidate_id",
                    "signalp_prediction",
                    "signal_peptide_start",
                    "signal_peptide_end",
                    "mature_start",
                    "mature_end",
                    "cleavage_site",
                    "source_file",
                    "tool_version",
                ]
            )
            + "\n"
            + "\t".join(["prot1", "SP", "1", "2", "3", "10", "2|3", "signalp.gff3", "SignalP 6.0"])
            + "\n",
        )
        project_json = tmp / "project.json"
        write_text(
            project_json,
            (
                "{\n"
                f'  "candidate_sequences": {{\n'
                f'    "candidates": {{\n'
                f'      "prot1": {{\n'
                f'        "source_genome": "G1",\n'
                f'        "protein_fasta": "{protein_fasta}",\n'
                f'        "cds_fasta": "{cds_fasta}",\n'
                f'        "fna": "{genomic_fna}"\n'
                f"      }}\n"
                f"    }}\n"
                f"  }}\n"
                f"}}\n"
            ),
        )
        extracted = tmp / "extracted"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "extract_candidate_sequences.py"),
                "--candidates",
                str(struct_candidates),
                "--project",
                str(project_json),
                "--outdir",
                str(extracted),
                "--signalp-tsv",
                str(signalp_tsv),
            ],
            check=True,
        )
        gene_text = extracted.joinpath("candidate_gene_sequences.fna").read_text(encoding="utf-8")
        assert "CAAAGG" in gene_text
        mature_text = extracted.joinpath("candidate_mature_proteins.faa").read_text(encoding="utf-8")
        assert "AKCGTMNP" in mature_text
        evidence_text = extracted.joinpath("candidate_gene_evidence.tsv").read_text(encoding="utf-8")
        assert "signalp_prediction" in evidence_text
        assert "is_secreted" in evidence_text

        combined = tmp / "combined_candidates.tsv"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "merge_candidates.py"),
                "--sequence",
                str(seq_candidates),
                "--structural",
                str(struct_candidates),
                "--fedkea",
                str(fedkea),
                "--source-annotations",
                str(source_annotations),
                "--output",
                str(combined),
            ],
            check=True,
        )
        assert "prot1" in combined.read_text(encoding="utf-8")
        assert "fedkea_tool_version" in combined.read_text(encoding="utf-8")

        with combined.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            first = next(reader)
            assert first["tm_score_mean"] == "0.8200"
        assert first["sequence_rank"] == "2"
        assert first["structural_rank"] == "1"
        assert first["priority_tier"] == ""
        assert first["fedkea_is_enzyme"] == "True"
        assert first["source_product"] == "alpha_beta_hydrolase"
        assert first["source_ec_number"] == "3.1.1.-"
        assert "fedkea_results" in first["provenance"]
        assert "source_feature_annotations" in first["provenance"]

        scored = tmp / "scored_candidates.tsv"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "score_candidates.py"),
                "--input",
                str(combined),
                "--output",
                str(scored),
                "--target-ec",
                "3.1.1.-",
            ],
            check=True,
        )
        score_text = scored.read_text(encoding="utf-8")
        assert "sequence_annotation_fast_path" in score_text
        assert "overall_rank" in score_text
        with scored.open("r", encoding="utf-8", newline="") as handle:
            scored_first = next(csv.DictReader(handle, delimiter="\t"))
            assert scored_first["overall_rank"] == "1"
            assert scored_first["structural_score"] == "0.82"
            assert scored_first["priority_tier"] == "SEQUENCE_ANNOTATION_CONFIRMED"
            assert scored_first["priority_rule"] == "SEQUENCE_ANNOTATION_CONFIRMED"
            assert scored_first["priority_order"] == "1"

        summary_dir = tmp / "summary"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "summarize_candidates.py"),
                "--scored",
                str(scored),
                "--project",
                str(card_json),
                "--outdir",
                str(summary_dir),
            ],
            check=True,
        )
        assert summary_dir.joinpath("high_confidence_candidate_summary.tsv").is_file()
        assert summary_dir.joinpath("final_target_candidates.tsv").is_file()
        hypotheses = summary_dir.joinpath("experimental_hypotheses.tsv")
        assert hypotheses.is_file()
        hyp_text = hypotheses.read_text(encoding="utf-8")
        assert "hypothesis_statement" in hyp_text
        assert "falsification_criteria" in hyp_text
        assert "critical_experiments" in hyp_text

    print("example test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
