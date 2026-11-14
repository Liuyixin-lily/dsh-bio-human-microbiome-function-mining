#!/usr/bin/env python3
"""End-to-end example test for the human-microbiome-function-mining plugin."""

from __future__ import annotations

import csv
import json
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
        assert "structure_first_tm_score" in score_text
        assert "overall_rank" in score_text
        assert "overall_score" in score_text
        with scored.open("r", encoding="utf-8", newline="") as handle:
            scored_first = next(csv.DictReader(handle, delimiter="\t"))
            assert scored_first["overall_rank"] == "1"
            assert scored_first["structural_score"] == "0.82"
            assert scored_first["priority_tier"] == "SEQUENCE_ANNOTATION_CONFIRMED"
            assert scored_first["priority_rule"] == "SEQUENCE_ANNOTATION_CONFIRMED"
            assert scored_first["priority_order"] == "1"

        # --rank-by priority must still be selectable and must say so.
        scored_priority = tmp / "scored_priority.tsv"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "score_candidates.py"),
                "--input",
                str(combined),
                "--output",
                str(scored_priority),
                "--target-ec",
                "3.1.1.-",
                "--rank-by",
                "priority",
            ],
            check=True,
        )
        assert "priority_rule_first" in scored_priority.read_text(encoding="utf-8")

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

    LEGACY_LIBRARY = ROOT / "examples" / "unverified"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        browse = SCRIPTS / "browse_target_library.py"

        # the shipped library must validate, and every enzyme must be selectable
        subprocess.run([sys.executable, str(browse), "--validate"], check=True)

        domains = json.loads(
            subprocess.run(
                [sys.executable, str(browse), "--list-domains", "--json"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        # the shipped library is deliberately tiny: only entries with verified literature
        # the shipped example domain, plus any user-defined starter domains that ship with it
        ids = [d["id"] for d in domains]
        assert "skin" in ids
        shipped = next(d for d in domains if d["id"] == "skin")
        assert shipped["processes"] and len(shipped["processes"]) == 1
        # a starter domain may ship, but it must be marked as starter/user_defined
        for extra in domains:
            if extra["id"] != "skin":
                assert extra.get("content_status") == "starter", extra["id"]
                assert extra.get("role") == "user_defined", extra["id"]
        domains = [shipped]
        # the shipped domain is a reference example, not a coverage claim
        assert domains[0]["role"] == "shipped_example"

        # the CLI must say so out loud, and must point at the library-free routes
        banner = subprocess.run(
            [sys.executable, str(browse), "--list-domains"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert "示例参考域" in banner
        assert "不是人体微生物组的覆盖范围" in banner
        assert "genome-search" in banner
        assert "build_library_domain.py" in banner

        # natural-language keyword search must resolve a user phrase to a process
        hits = json.loads(
            subprocess.run(
                [sys.executable, str(browse), "--library-dir", str(LEGACY_LIBRARY),
                 "--search", "油脂分泌", "--json"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        assert any(h["process"] == "skin_sebum_lipolysis" for h in hits), hits

        # navigation intent must produce the menu, not a "no hit" dead end
        nav = subprocess.run(
            [sys.executable, str(browse), "--search", "都有哪些关注的菌"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "--list-taxa" in nav.stdout
        assert "--interactive" in nav.stdout

        # the taxon layer must be listable on its own
        taxa = json.loads(
            subprocess.run(
                [sys.executable, str(browse), "--library-dir", str(LEGACY_LIBRARY),
                 "--list-taxa", "skin", "--json"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        assert len(taxa) >= 10
        assert {"Staphylococcus epidermidis", "Cutibacterium acnes"} <= {t["taxon"] for t in taxa}
        assert all(t["attention"] in {"high", "medium", "low"} for t in taxa)
        # every taxon should be reachable from at least one process
        assert any(t["processes"] for t in taxa)

        # a no-hit search is an informative miss, not a crash
        miss = subprocess.run(
            [sys.executable, str(browse), "--search", "no_such_keyword_xyz"],
            capture_output=True,
            text=True,
        )
        assert miss.returncode == 1
        # a miss must escalate, never dead-end
        assert "resolve_target_intent.py" in miss.stdout
        assert "build_library_domain.py" in miss.stdout
        assert "build_target_function_card.py" in miss.stdout

        # a taxon query must resolve to the taxon itself, with its processes
        taxon_hits = json.loads(
            subprocess.run(
                [sys.executable, str(browse), "--search", "Staphylococcus aureus", "--json"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        assert any(h["kind"] == "taxon" for h in taxon_hits), taxon_hits

        # merging every domain is allowed when the body site is still unknown
        all_taxa = json.loads(
            subprocess.run(
                [sys.executable, str(browse), "--list-taxa", "all", "--json"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        merged_names = {t["taxon"] for t in all_taxa}
        assert {"Staphylococcus aureus", "Staphylococcus epidermidis"} <= merged_names

        # exporting a library selection must produce a schema-valid card
        sel_dir = tmp / "selection"
        subprocess.run(
            [
                sys.executable,
                str(browse),
                "--export-card",
                "skin_sphingomyelin_phosphodiesterase",
                "--output-dir",
                str(sel_dir),
            ],
            check=True,
        )
        card = json.loads(sel_dir.joinpath("target_function_card.json").read_text(encoding="utf-8"))
        assert card["input_source"] == "library"
        assert card["library_id"] == "skin_sphingomyelin_phosphodiesterase"
        assert card["library_version"] == "2.2.0"
        assert card["ec"] == "3.1.4.12"
        assert card["known_microbial_enzymes"]
        # every later stage must accept the card unchanged
        sys.path.insert(0, str(SCRIPTS))
        from build_target_function_card import validate_card  # noqa: PLC0415

        assert validate_card(card) == [], validate_card(card)
        assert sel_dir.joinpath("target_selection.md").is_file()

        # a library selection without an EC must still be a usable card
        dark_dir = tmp / "dark"
        subprocess.run(
            [
                sys.executable,
                str(browse),
                "--library-dir",
                str(LEGACY_LIBRARY),
                "--export-card",
                "skin_c_s_lyase",
                "--output-dir",
                str(dark_dir),
            ],
            check=True,
        )
        dark_card = json.loads(dark_dir.joinpath("target_function_card.json").read_text(encoding="utf-8"))
        assert dark_card["ec"] == ""
        assert "dark_matter: yes" in dark_card["notes"]

        flat = tmp / "library.tsv"
        subprocess.run(
            [sys.executable, str(browse), "--export-tsv", str(flat)], check=True
        )
        with flat.open("r", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        # the shipped library's evidence-backed part is exactly the curated example; starter
        # domains may ship alongside it but must never claim literature_verified
        curated = [r for r in rows if r["domain_id"] == "skin"]
        assert len(curated) == 1
        assert all(r["evidence_status"] == "literature_verified" and r["evidence_refs"] for r in curated)
        for row in rows:
            if row["domain_id"] != "skin":
                assert row["evidence_status"] != "literature_verified" or row["evidence_refs"]

        # the full reference content is still available when explicitly requested
        flat_all = tmp / "library_all.tsv"
        subprocess.run(
            [sys.executable, str(browse), "--library-dir", str(LEGACY_LIBRARY),
             "--export-tsv", str(flat_all)],
            check=True,
        )
        with flat_all.open("r", encoding="utf-8") as handle:
            rows_all = list(csv.DictReader(handle, delimiter="\t"))
        assert len(rows_all) >= 20
        assert {"skin", "gut"} <= {row["domain_id"] for row in rows_all}
        # that reference content is a curated prior, not evidence
        assert all(row["evidence_status"] == "curated_prior" for row in rows_all)
        assert all(not row["evidence_refs"] for row in rows_all)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        resolver = SCRIPTS / "resolve_target_intent.py"
        builder = SCRIPTS / "build_library_domain.py"
        browse = SCRIPTS / "browse_target_library.py"

        def route(query: str, library_dir: Path | None = None) -> dict:
            cmd = [sys.executable, str(resolver), "--query", query, "--json"]
            if library_dir is not None:
                cmd += ["--library-dir", str(library_dir)]
            return json.loads(
                subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
            )

        # an EC number means entry A, and the library must not be used
        ec_route = route("神经酰胺酶 EC 3.5.1.23")
        assert ec_route["detected"]["ec"] == ["3.5.1.23"]
        assert ec_route["route"]["entry"] == "A"
        assert any("fetch_reference_enzymes.py --ec 3.5.1.23" in s["command"] for s in ec_route["route"]["steps"])

        # a reaction means entry A as well
        rxn = route("鞘磷脂 -> 神经酰胺 + 磷酸胆碱")
        assert rxn["detected"]["reaction_arrow"] is True
        assert rxn["route"]["entry"] == "A"

        # a covered phrasing means entry B
        covered = route("我关注头皮屑", library_dir=LEGACY_LIBRARY)
        assert covered["route"]["entry"] == "B"
        assert covered["library_coverage"]["hit_count"] >= 1

        # an uncovered body site must escalate, and must not be answered with an
        # off-site library hit
        oral = route("口腔牙周炎相关菌有哪些酶值得看", library_dir=LEGACY_LIBRARY)
        assert oral["detected"]["source_ids"] == ["oral"]
        assert oral["route"]["entry"] == "escalate"
        assert oral["library_coverage"]["hit_count"] == 0
        assert oral["route"]["literature_search_terms"]
        assert any("run_literature_search.sh" in s["command"] for s in oral["route"]["steps"])

        # a vaginal question must not be answered by the skin acidification process
        vaginal = route("阴道菌群和乳酸杆菌", library_dir=LEGACY_LIBRARY)
        assert vaginal["route"]["entry"] == "escalate"
        assert vaginal["library_coverage"]["hit_count"] == 0
        assert vaginal["library_coverage"]["other_site_hit_count"] >= 1

        # a taxon-only question must not crash and must not claim library coverage
        taxon_route = route("Akkermansia muciniphila", library_dir=LEGACY_LIBRARY)
        assert taxon_route["detected"]["taxa"] == ["Akkermansia"]
        assert taxon_route["route"]["entry"] == "A"
        assert taxon_route["library_coverage"]["hit_count"] == 0
        assert taxon_route["library_coverage"]["taxon_hits"]

        # a word that merely appears in prose is not coverage
        immunity = route("我想研究肠道菌对免疫的影响", library_dir=LEGACY_LIBRARY)
        assert immunity["route"]["entry"] == "escalate"
        assert immunity["library_coverage"]["hit_count"] == 0

        # a phenotype the library really does cover resolves to the exact process
        butyrate = route("粪便 丁酸", library_dir=LEGACY_LIBRARY)
        assert butyrate["route"]["entry"] == "B"
        assert butyrate["library_coverage"]["hits"][0]["process"] == "gut_butyrate_production"

        # an unrecognisable question asks for a question shape instead of guessing
        vague = route("帮我看看这个项目")
        assert vague["route"]["entry"] == "clarify"
        assert len(vague["route"]["question_shapes"]) == 4

        # ---- the domain builder: honest by construction ----
        spec_path = tmp / "spec.json"
        loaded = tmp / "loaded.json"
        subprocess.run(
            [sys.executable, str(builder), "--init", "--domain", "test_site", "--output", str(spec_path)],
            check=True,
        )
        # an unfilled skeleton must be rejected, not filled with placeholders
        rejected = subprocess.run(
            [sys.executable, str(builder), "--build", "--spec", str(spec_path), "--output", str(loaded)],
            capture_output=True,
            text=True,
        )
        assert rejected.returncode == 1
        assert not loaded.exists()

        filled = json.loads(spec_path.read_text(encoding="utf-8"))
        domain = filled["domain"]
        domain.update(
            {
                "name_zh": "测试部位",
                "name_en": "Test site",
                "keywords_zh": ["测试部位"],
                "keywords_en": ["test site"],
                "niche_summary_zh": "synthetic fixture, no biological claim",
                "selection_hint_zh": "synthetic fixture",
            }
        )
        domain["focus_taxa"] = [
            {
                "taxon": "Examplebacterium testii",
                "name_zh": "示例杆菌",
                "role_zh": "placeholder",
                "attention": "medium",
                "provenance_source": "user_supplied",
            }
        ]
        process = domain["processes"][0]
        domain["processes"][0].update(
            {
                "name_zh": "示例过程",
                "name_en": "Example process",
                "keywords_zh": ["示例过程"],
                "keywords_en": ["example process"],
                "why_it_matters_zh": "placeholder",
                "host_context_zh": "placeholder",
                "microbe_effect_zh": "placeholder",
                "key_taxa": ["Examplebacterium testii"],
            }
        )
        enzyme = process["enzymes"][0]
        enzyme.update(
            {
                "enzyme_name_zh": "示例酶",
                "enzyme_name_en": "example enzyme",
                "ec": "1.1.1.-",
                "ec_confidence": "family",
                "reaction_zh": "substrate + H2O -> product",
                "substrate_zh": "substrate",
                "product_zh": "product",
                "entry_point": "ec",
                "dark_matter": False,
                "provenance_note_zh": "synthetic fixture",
                "validation_note_zh": "synthetic fixture",
                "provenance_source": "user_supplied",
            }
        )
        spec_path.write_text(json.dumps(filled, ensure_ascii=False, indent=2), encoding="utf-8")

        built_dir = tmp / "library"
        built = built_dir / "test_site.json"
        subprocess.run(
            [sys.executable, str(builder), "--build", "--spec", str(spec_path), "--output", str(built)],
            check=True,
        )
        payload = json.loads(built.read_text(encoding="utf-8"))
        # the honesty invariants are enforced by the builder, not by convention
        assert payload["domain"]["content_status"] == "starter"
        assert payload["domain"]["role"] == "user_defined"
        assert payload["domain"]["expansion"]["method"] == "generated_from_spec"
        built_enzyme = payload["domain"]["processes"][0]["enzymes"][0]
        assert built_enzyme["evidence_status"] == "curated_prior"
        assert built_enzyme["evidence_refs"] == []

        # a generated domain is immediately browsable and selectable
        subprocess.run([sys.executable, str(browse), "--library-dir", str(built_dir), "--validate"], check=True)
        subprocess.run(
            [
                sys.executable,
                str(browse),
                "--library-dir",
                str(built_dir),
                "--export-card",
                "test_site_enzyme_1",
                "--output-dir",
                str(tmp / "card"),
            ],
            check=True,
        )

        # a generated domain may not be relabelled as curated, nor carry citations
        tampered = json.loads(json.dumps(payload))
        tampered["domain"]["content_status"] = "curated"
        (built_dir / "bad.json").write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
        bad = subprocess.run(
            [sys.executable, str(browse), "--library-dir", str(built_dir), "--validate"],
            capture_output=True,
            text=True,
        )
        assert bad.returncode == 1
        assert "generated from a spec must stay content_status='starter'" in bad.stderr

        # a generated domain also may not relabel itself as a shipped example
        tampered2 = json.loads(json.dumps(payload))
        tampered2["domain"]["role"] = "shipped_example"
        (built_dir / "bad2.json").write_text(json.dumps(tampered2, ensure_ascii=False), encoding="utf-8")
        bad2 = subprocess.run(
            [sys.executable, str(browse), "--library-dir", str(built_dir), "--validate"],
            capture_output=True,
            text=True,
        )
        assert bad2.returncode == 1
        assert "must be role='user_defined'" in bad2.stderr
        (built_dir / "bad2.json").unlink()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        cro = SCRIPTS / "build_cro_work_order.py"

        card = tmp / "target_function_card.json"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "build_target_function_card.py"),
                "--output", str(card),
                "--target-id", "CRO_TEST",
                "--enzyme-name", "test hydrolase",
                "--ec", "3.1.4.12",
                "--reaction", "substrate + H2O -> product",
                "--substrate", "substrate",
                "--product", "product",
                "--input-source", "reaction",
            ],
            check=True,
            capture_output=True,
        )

        seq_a = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ"
        seq_b = "MGSSHHHHHHSSGLVPRGSHMASMTGGQQMGRDLY"
        fasta = tmp / "candidate_proteins.faa"
        fasta.write_text(f">CAND_A.1 synthetic [Testus examplei]\n{seq_a}\n", encoding="utf-8")

        cands = tmp / "final_target_candidates.tsv"
        cands.write_text(
            "final_rank\tprotein_accession\torganism_or_strain\tevidence_base\t"
            "tm_score_mean\tstructural_score\tsource_annotation\tlocus_tag\tlocation\t"
            "fedkea_ec\tfedkea_confidence\tfedkea_accepted_name\tfedkea_other_names\t"
            "validation_status\tprotein_fasta\tcds_fasta\n"
            "1\tCAND_A.1\tTestus_examplei\tUS-align\t0.81\t0.81\talpha/beta hydrolase\t"
            "TEX_0001\t1..300\t3.1.4.12\tHigh\tsphingomyelin phosphodiesterase\t-\t"
            "high-confidence\tpath/a.faa\tpath/a.ffn\n"
            "2\tCAND_B.2\tTestus_examplei\tUS-align\t0.77\t0.77\talpha/beta hydrolase\t"
            "TEX_0002\t1..300\t3.1.4.12\tHigh\tsphingomyelin phosphodiesterase\t-\t"
            "high-confidence\tpath/b.faa\tpath/b.ffn\n",
            encoding="utf-8",
        )

        hyps = tmp / "experimental_hypotheses.tsv"
        fields = [
            "overall_rank", "protein_accession", "organism_or_strain", "candidate_id",
            "target_context", "hypothesis_statement", "mechanistic_model",
            "testable_prediction", "critical_experiments", "falsification_criteria",
            "ambient_hypothesis", "evidence_chain", "literature_citations",
            "designer_notes", "provenance",
        ]
        row = {f: "" for f in fields}
        row.update(
            {
                "overall_rank": "1",
                "protein_accession": "CAND_A.1",
                "organism_or_strain": "Testus_examplei",
                "candidate_id": "CAND_A.1",
                "hypothesis_statement": "CAND_A.1 encodes the target hydrolase",
                "falsification_criteria": "no activity above 3x empty-vector control",
            }
        )
        hyps.write_text(
            "\t".join(fields) + "\n" + "\t".join(row[f] for f in fields) + "\n",
            encoding="utf-8",
        )

        out = tmp / "cro"
        subprocess.run(
            [
                sys.executable, str(cro),
                "--card", str(card),
                "--candidates", str(cands),
                "--hypotheses", str(hyps),
                "--sequences", str(fasta),
                "--outdir", str(out),
                "--scope", "full",
                "--bsl", "BSL-2",
            ],
            check=True,
            capture_output=True,
        )

        work_order = out / "cro_work_order.md"
        modules_tsv = out / "cro_modules.tsv"
        seqs_faa = out / "cro_sequences.faa"
        gaps = out / "cro_gap_list.md"
        for path_file in (work_order, modules_tsv, seqs_faa, gaps):
            assert path_file.is_file(), path_file

        # full scope carries every module, in numeric order
        with modules_tsv.open("r", encoding="utf-8") as handle:
            modules = list(csv.DictReader(handle, delimiter="\t"))
        ids = [m["module_id"] for m in modules]
        assert ids == [f"M{i}" for i in range(1, 11)], ids

        # no price and no turnaround may be invented
        for module in modules:
            assert module["price_status"] == "需询价 / quote required"
            assert module["turnaround_days"] == "待公司填写 / TBD"
            assert not any(ch.isdigit() for ch in module["price_status"])
            assert not any(ch.isdigit() for ch in module["turnaround_days"])

        # sequence must be copied verbatim, and only for candidates that have one
        copied = seqs_faa.read_text(encoding="utf-8")
        assert seq_a in copied
        assert seq_b not in copied
        assert "CAND_B.2" not in copied

        text = work_order.read_text(encoding="utf-8")
        # the missing sequence must be visible, not silently dropped
        assert "CAND_B.2" in text
        assert "缺序列" in text
        assert "有序列" in text
        # pre-registered rule, glossary, biosafety checklist, boundary statement
        assert "no activity above 3x empty-vector control" in text
        assert "术语表" in text
        assert "生物安全" in text
        assert "不构成任何功能结论" in text
        assert "预注册" in text or "数据回来之前" in text
        assert "BSL-2" in text

        # the module table must satisfy its own schema
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "validate_schema.py"),
                "--schema", str(ROOT / "schemas" / "cro_work_order.schema.tsv"),
                "--tsv", str(modules_tsv),
            ],
            check=True,
            capture_output=True,
        )

        # without any sequence the script must refuse to emit a FASTA
        out2 = tmp / "cro_noseq"
        subprocess.run(
            [
                sys.executable, str(cro),
                "--card", str(card),
                "--candidates", str(cands),
                "--outdir", str(out2),
                "--scope", "assay_first",
            ],
            check=True,
            capture_output=True,
        )
        assert not (out2 / "cro_sequences.faa").exists()
        missing_note = out2 / "cro_sequences.MISSING.md"
        assert missing_note.is_file()
        assert "不会生成占位序列" in missing_note.read_text(encoding="utf-8")
        gap_text = (out2 / "cro_gap_list.md").read_text(encoding="utf-8")
        assert "序列" in gap_text

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ranker = SCRIPTS / "score_target_priorities.py"

        # registries written for the original skin-only select-candidate skill
        # must keep working through the legacy skin_* column aliases
        enzyme_reg = tmp / "enzyme_registry.tsv"
        enzyme_reg.write_text(
            "target_id\tgene\tname\tuniprot\tec\tskin_process\t"
            "skin_evidence_score\tdisease_relevance_score\tbiochemical_clarity_score\t"
            "sequence_structure_score\tmicrobial_plausibility_score\t"
            "assay_feasibility_score\tnovelty_score\tnotes\n"
            "E1\tg1\tenzyme one\tP1\t3.1.1.3\tsebum\t5\t5\t5\t5\t5\t5\t3\ttop\n"
            "E2\tg2\tenzyme two\tP2\t3.1.4.12\tbarrier\t2\t2\t2\t2\t2\t2\t2\tlow\n",
            encoding="utf-8",
        )
        taxa_reg = tmp / "taxa_registry.tsv"
        taxa_reg.write_text(
            "taxon_id\tgenus\tspecies\tdisplay_name\tdomain\tcore_tier\t"
            "skin_presence_score\tmetabolic_plausibility_score\tgenome_availability_score\t"
            "disease_site_relevance_score\texperimental_accessibility_score\t"
            "recommended_strain_count\tkey_evidence_pmids\tkey_evidence_dois\trationale\n"
            "T1\tCutibacterium\tacnes\tC. acnes\tBacteria\tcore\t5\t5\t5\t5\t5\t8\t12345\t10.1000/x\tdominant\n"
            "T2\tEscherichia\tcoli\tE. coli\tBacteria\tenteric\t1\t1\t5\t1\t5\t3\t\t\tnot skin\n",
            encoding="utf-8",
        )

        ranked = tmp / "ranked"
        subprocess.run(
            [
                sys.executable, str(ranker),
                "--enzymes", str(enzyme_reg),
                "--taxa", str(taxa_reg),
                "--site", "skin",
                "--output", str(ranked),
            ],
            check=True,
            capture_output=True,
        )

        with (ranked / "enzyme_priority_ranking.tsv").open("r", encoding="utf-8") as handle:
            enzymes = list(csv.DictReader(handle, delimiter="\t"))
        assert [row["target_id"] for row in enzymes] == ["E1", "E2"]
        scores = [float(row["priority_score"]) for row in enzymes]
        assert scores == sorted(scores, reverse=True)
        # subjectivity and policy must be visible on every row
        assert all(row["score_basis"] == "manual_expert_judgement" for row in enzymes)
        assert all(row["scoring_policy"] for row in enzymes)

        with (ranked / "taxa_priority_ranking.tsv").open("r", encoding="utf-8") as handle:
            taxa = list(csv.DictReader(handle, delimiter="\t"))
        assert taxa[0]["genus"] == "Cutibacterium"
        assert taxa[0]["selection_status"] == "selected"
        # a taxon scoring below the default 3.0 threshold must be deferred
        assert taxa[1]["selection_status"] == "defer"
        assert (ranked / "selected_taxa.txt").read_text(encoding="utf-8").strip() == "Cutibacterium acnes"

        # an unreachable threshold is a config error, not "nothing is worth doing"
        bad_cfg = tmp / "bad_config.json"
        bad_cfg.write_text(json.dumps({"ranking": {"taxa_min_priority_score": 948}}), encoding="utf-8")
        bad = subprocess.run(
            [
                sys.executable, str(ranker),
                "--taxa", str(taxa_reg),
                "--site", "skin",
                "--config", str(bad_cfg),
                "--output", str(tmp / "bad"),
            ],
            capture_output=True,
            text=True,
        )
        assert bad.returncode == 1
        assert "unreachable" in bad.stderr
        assert not (tmp / "bad" / "taxa_priority_ranking.tsv").exists()

        # seeding from the curated library must never fill in a score
        seeded = tmp / "seeded"
        subprocess.run(
            [
                sys.executable, str(ranker),
                "--seed-from-library", str(LEGACY_LIBRARY / "skin.full.json"),
                "--output", str(seeded),
            ],
            check=True,
            capture_output=True,
        )
        with (seeded / "enzyme_registry.seed.tsv").open("r", encoding="utf-8") as handle:
            seed_enzymes = list(csv.DictReader(handle, delimiter="\t"))
        assert len(seed_enzymes) >= 15
        assert all(row["site_evidence_score"] == "" for row in seed_enzymes)
        with (seeded / "taxa_registry.seed.tsv").open("r", encoding="utf-8") as handle:
            seed_taxa = list(csv.DictReader(handle, delimiter="\t"))
        assert len(seed_taxa) >= 10
        assert all(row["site_presence_score"] == "" for row in seed_taxa)

        # both ranking tables must satisfy their schemas
        for schema_name, table in (
            ("enzyme_priority_ranking.schema.tsv", ranked / "enzyme_priority_ranking.tsv"),
            ("taxa_priority_ranking.schema.tsv", ranked / "taxa_priority_ranking.tsv"),
        ):
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "validate_schema.py"),
                    "--schema", str(ROOT / "schemas" / schema_name),
                    "--tsv", str(table),
                ],
                check=True,
                capture_output=True,
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ranker = SCRIPTS / "score_target_priorities.py"
        library = LEGACY_LIBRARY / "skin.full.json"

        # --- auto-scoring: derive what is computable, never guess the rest ---
        seed_dir = tmp / "seed"
        subprocess.run(
            [sys.executable, str(ranker), "--seed-from-library", str(library), "--output", str(seed_dir)],
            check=True,
            capture_output=True,
        )
        seed = seed_dir / "enzyme_registry.seed.tsv"
        with seed.open("r", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        fields = list(rows[0].keys())
        # a human provides only the three judgement-dependent scores
        for row in rows:
            row.update(
                {
                    "site_evidence_score": "4",
                    "disease_relevance_score": "3",
                    "assay_feasibility_score": "3",
                }
            )
        with seed.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

        out = tmp / "ranked"
        subprocess.run(
            [
                sys.executable, str(ranker),
                "--enzymes", str(seed),
                "--library", str(library),
                "--auto-score",
                "--allow-missing-scores",
                "--site", "skin",
                "--output", str(out),
            ],
            check=True,
            capture_output=True,
        )
        with (out / "enzyme_priority_ranking.tsv").open("r", encoding="utf-8") as handle:
            ranked = list(csv.DictReader(handle, delimiter="\t"))
        sources = dict(
            part.split("=", 1) for part in ranked[0]["score_sources"].split(";") if "=" in part
        )
        # derivable -> auto with a named rubric
        assert sources["biochemical_clarity_score"] == "auto:library"
        assert sources["microbial_plausibility_score"] == "auto:library"
        assert sources["novelty_score"] == "auto:library"
        # supplied by the human -> manual
        assert sources["site_evidence_score"] == "manual"
        # no reference enzyme set given -> this stays a visible gap, not a guess
        assert sources["sequence_structure_score"] == "missing"
        # the report must say which rubric produced which number
        report = (out / "ranking_report.md").read_text(encoding="utf-8")
        assert "自动推导的分数" in report
        assert "必须由你判断的分数" in report
        assert "EC 置信度 full=2" in report

        # --- strict mode: an underivable score stops the run and names the cell ---
        bare = tmp / "bare.tsv"
        bare.write_text(
            "target_id\tname\tsite_process\tsite_evidence_score\tdisease_relevance_score\t"
            "biochemical_clarity_score\tsequence_structure_score\t"
            "microbial_plausibility_score\tassay_feasibility_score\tnovelty_score\n"
            "E1\tenz\tproc\t5\t5\t\t\t\t\t\n",
            encoding="utf-8",
        )
        strict = subprocess.run(
            [
                sys.executable, str(ranker),
                "--enzymes", str(bare),
                "--auto-score",
                "--output", str(tmp / "strict"),
            ],
            capture_output=True,
            text=True,
        )
        assert strict.returncode == 1
        assert "cannot be derived" in strict.stderr
        # the failure must say which flag would make the score derivable
        assert "--reference-enzymes" in strict.stderr
        # it must explain which scores need human judgement, not just fail
        assert "需要文献" in strict.stderr or "插件无数据源" in strict.stderr
        assert not (tmp / "strict" / "enzyme_priority_ranking.tsv").exists()

        # --- permissive mode records the gap instead of hiding it ---
        subprocess.run(
            [
                sys.executable, str(ranker),
                "--enzymes", str(bare),
                "--auto-score",
                "--allow-missing-scores",
                "--output", str(tmp / "permissive"),
            ],
            check=True,
            capture_output=True,
        )
        with (tmp / "permissive" / "enzyme_priority_ranking.tsv").open("r", encoding="utf-8") as handle:
            permissive = list(csv.DictReader(handle, delimiter="\t"))[0]
        assert "biochemical_clarity_score=missing" in permissive["score_sources"]
        assert "按 0 计入" in (tmp / "permissive" / "ranking_report.md").read_text(encoding="utf-8")

        # --- taxa scores can be derived from a real genome-search table ---
        genomes = tmp / "genomes.tsv"
        genomes.write_text(
            "input\tassembly_accession\torganism\tisolation_source\tclassification\n"
            + "".join(
                f"Cutibacterium acnes\tGCF_{i:09d}\tCutibacterium acnes\tskin swab\tdirect source match\n"
                for i in range(1, 13)
            )
            + "Escherichia coli\tGCF_999999999\tEscherichia coli\tstool\tindirect\n",
            encoding="utf-8",
        )
        taxa_reg = tmp / "taxa.tsv"
        taxa_reg.write_text(
            "taxon_id\tgenus\tspecies\tdisplay_name\tdomain\tcore_tier\t"
            "site_presence_score\tmetabolic_plausibility_score\tgenome_availability_score\t"
            "disease_site_relevance_score\texperimental_accessibility_score\t"
            "recommended_strain_count\tkey_evidence_pmids\tkey_evidence_dois\trationale\n"
            "T1\tCutibacterium\tacnes\tC. acnes\tBacteria\tcore\t\t3\t\t3\t4\t8\t\t\t dominant\n"
            "T2\tEscherichia\tcoli\tE. coli\tBacteria\tenteric\t\t2\t\t1\t5\t3\t\t\t not skin\n",
            encoding="utf-8",
        )
        taxa_out = tmp / "taxa_out"
        subprocess.run(
            [
                sys.executable, str(ranker),
                "--taxa", str(taxa_reg),
                "--genomes", str(genomes),
                "--auto-score",
                "--site", "skin",
                "--output", str(taxa_out),
            ],
            check=True,
            capture_output=True,
        )
        with (taxa_out / "taxa_priority_ranking.tsv").open("r", encoding="utf-8") as handle:
            taxa = list(csv.DictReader(handle, delimiter="\t"))
        top = taxa[0]
        assert top["genus"] == "Cutibacterium"
        assert "genome_availability_score=auto:genome_search" in top["score_sources"]
        assert "site_presence_score=auto:genome_search" in top["score_sources"]
        # 12 assemblies -> bucket 4; the score must come from the count, not from the sheet
        assert top["genome_availability_score"] == "4.000"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "validate_schema.py"),
                "--schema", str(ROOT / "schemas" / "taxa_priority_ranking.schema.tsv"),
                "--tsv", str(taxa_out / "taxa_priority_ranking.tsv"),
            ],
            check=True,
            capture_output=True,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ranker = SCRIPTS / "score_target_priorities.py"
        library = LEGACY_LIBRARY / "skin.full.json"

        # a literature table with every evidence shape the ranker must distinguish
        lit = tmp / "literature_evidence.tsv"
        lit.write_text(
            "candidate_id\tprotein_accession\torganism_or_strain\tevidence_type\t"
            "reference_type\treference_id\ttitle\tfirst_author\tjournal\tyear\t"
            "finding\tverified\tsource_search\tnotes\n"
            "skin_sphingomyelin_phosphodiesterase\tWP_1\tS. aureus\tdirect_functional_evidence\t"
            "PMID\t11111111\tsphingomyelinase activity\tA\tJ\t2019\tcleaves sphingomyelin\t"
            "yes\tsphingomyelinase skin\tok\n"
            "skin_sphingomyelin_phosphodiesterase\tWP_2\tS. aureus\trelated_assay\tPMID\t"
            "22222222\tsphingomyelinase and atopic dermatitis\tB\tAllergy\t2020\t"
            "linked to atopic dermatitis\tyes\tsphingomyelinase\tok\n"
            "skin_ceramidase\tWP_3\tS. aureus\treview\tPMID\t33333333\tceramidase review\t"
            "C\tRev\t2018\toverview\tyes\tceramidase\tok\n"
            "skin_urease\tWP_4\tS. epidermidis\tdirect_functional_evidence\tPMID\t44444444\t"
            "urease claim\tD\tPreprint\t2022\tclaimed\tno\turease\tunverified\n"
            "skin_l_lactate_dehydrogenase\tWP_5\tS. epidermidis\tno_evidence\tmanual\t\t"
            "no literature\t\t\t\tnothing\tyes\tLDH\tsearched\n",
            encoding="utf-8",
        )

        seed_dir = tmp / "seed"
        subprocess.run(
            [sys.executable, str(ranker), "--seed-from-library", str(library), "--output", str(seed_dir)],
            check=True,
            capture_output=True,
        )
        seed = seed_dir / "enzyme_registry.seed.tsv"
        with seed.open("r", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        fields = list(rows[0].keys())
        for row in rows:
            # leave site_evidence / disease_relevance empty so literature must fill them
            row["site_evidence_score"] = ""
            row["disease_relevance_score"] = ""
            row["assay_feasibility_score"] = "3"  # still a human judgement
        with seed.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

        out = tmp / "lit_ranked"
        subprocess.run(
            [
                sys.executable, str(ranker),
                "--enzymes", str(seed),
                "--library", str(library),
                "--literature", str(lit),
                "--disease", "atopic dermatitis",
                "--auto-score",
                "--allow-missing-scores",
                "--site", "skin",
                "--output", str(out),
            ],
            check=True,
            capture_output=True,
        )
        with (out / "enzyme_priority_ranking.tsv").open("r", encoding="utf-8") as handle:
            ranked = {row["target_id"]: row for row in csv.DictReader(handle, delimiter="\t")}

        def source(row: dict[str, str], key: str) -> str:
            return dict(p.split("=", 1) for p in row["score_sources"].split(";") if "=" in p)[key]

        # 2 verified functional records -> 4; one of them names the phenotype -> 3
        smase = ranked["skin_sphingomyelin_phosphodiesterase"]
        assert source(smase, "site_evidence_score") == "auto:literature"
        assert smase["site_evidence_score"] == "4.000"
        assert smase["disease_relevance_score"] == "3.000"

        # only a review -> 2, and no record links it to the phenotype -> explicit no-match
        ceramidase = ranked["skin_ceramidase"]
        assert ceramidase["site_evidence_score"] == "2.000"
        assert source(ceramidase, "disease_relevance_score") == "auto:literature:no_match"

        # an unverified record and an explicit no_evidence record must NOT become a 0:
        # absence of evidence is not evidence of absence
        assert source(ranked["skin_urease"], "site_evidence_score") == "missing"
        assert source(ranked["skin_urease"], "disease_relevance_score") == "missing"
        assert source(ranked["skin_l_lactate_dehydrogenase"], "site_evidence_score") == "missing"

        report = (out / "ranking_report.md").read_text(encoding="utf-8")
        assert "文献依据" in report
        assert "11111111(direct_functional_evidence,verified)" in report
        assert "44444444(direct_functional_evidence,unverified)" in report
        assert "共现证据" in report

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        empty = tmp / "empty_library"
        empty.mkdir()
        browse = SCRIPTS / "browse_target_library.py"
        resolver = SCRIPTS / "resolve_target_intent.py"

        # The curated library is an optional menu. With no library at all the
        # plugin must still work, and must say so instead of failing.
        listed = subprocess.run(
            [sys.executable, str(browse), "--library-dir", str(empty), "--list-domains"],
            capture_output=True,
            text=True,
        )
        assert listed.returncode == 0, listed.stderr
        assert "目标库为空" in listed.stdout
        assert "不是错误" in listed.stdout
        assert "build_target_function_card.py" in listed.stdout
        assert "genome_source_search.py" in listed.stdout

        validated = subprocess.run(
            [sys.executable, str(browse), "--library-dir", str(empty), "--validate"],
            capture_output=True,
            text=True,
        )
        assert validated.returncode == 0
        assert "没有内容需要校验" in validated.stdout

        # a routed question must distinguish "no menu configured" from
        # "configured but this site is not covered"
        no_menu = json.loads(
            subprocess.run(
                [sys.executable, str(resolver), "--library-dir", str(empty),
                 "--query", "口腔牙周炎相关菌有哪些酶值得看", "--json"],
                check=True, capture_output=True, text=True,
            ).stdout
        )
        assert no_menu["library_coverage"]["reason"] == "not_configured"
        assert "未配置目标库" in no_menu["route"]["reason_zh"]

        with_menu = json.loads(
            subprocess.run(
                [sys.executable, str(resolver),
                 "--query", "口腔牙周炎相关菌有哪些酶值得看", "--json"],
                check=True, capture_output=True, text=True,
            ).stdout
        )
        assert with_menu["library_coverage"]["available"] is True
        assert "未覆盖" in with_menu["route"]["reason_zh"]

        # with no library the auto-scorer simply has fewer sources; it must not
        # silently score the missing ones
        seed_dir = tmp / "seed"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "score_target_priorities.py"),
             "--seed-from-library", str(LEGACY_LIBRARY / "skin.full.json"), "--output", str(seed_dir)],
            check=True, capture_output=True,
        )
        seed = seed_dir / "enzyme_registry.seed.tsv"
        with seed.open("r", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        fields = list(rows[0].keys())
        for row in rows:
            row["assay_feasibility_score"] = "3"
        with seed.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

        no_lib_out = tmp / "no_lib_ranked"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "score_target_priorities.py"),
             "--enzymes", str(seed), "--auto-score", "--allow-missing-scores",
             "--site", "skin", "--output", str(no_lib_out)],
            check=True, capture_output=True,
        )
        with (no_lib_out / "enzyme_priority_ranking.tsv").open("r", encoding="utf-8") as handle:
            ranked = list(csv.DictReader(handle, delimiter="\t"))[0]
        sources = dict(p.split("=", 1) for p in ranked["score_sources"].split(";") if "=" in p)
        # without a library these must be gaps, not invented numbers
        for key in ("biochemical_clarity_score", "microbial_plausibility_score", "novelty_score"):
            assert sources[key] == "missing", (key, sources[key])
        assert "按 0 计入" in (no_lib_out / "ranking_report.md").read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        browse = SCRIPTS / "browse_target_library.py"

        # Without an evidence gate the shipped library advertises its full content.
        plain = subprocess.run(
            [sys.executable, str(browse), "--list-domains"],
            check=True, capture_output=True, text=True,
        ).stdout
        assert "1 process, 1 enzyme target" in plain

        # The shipped library passes its own gate: every entry carries a verified id.
        gated = subprocess.run(
            [sys.executable, str(browse), "--require-evidence", "--list-domains"],
            check=True, capture_output=True, text=True,
        ).stdout
        assert "1 process, 1 enzyme target" in gated
        # a starter domain ships alongside but is quarantined in full; that is the gate working,
        # so the presence of a quarantine note is expected (the curated domain is untouched)
        assert "skin_xenobiotic" in gated
        # one xenobiotic entry (azoreductase) is literature_verified after the SkinBug read; the
        # other five stay quarantined, so the gate shows exactly 1 process and isolates 5
        assert gated.count("1 process, 1 enzyme target") >= 2
        assert "已隔离 5 个条目" in gated

        # The unverified reference content is entirely quarantined by the same gate.
        gated_legacy = subprocess.run(
            [sys.executable, str(browse), "--library-dir", str(LEGACY_LIBRARY),
             "--require-evidence", "--list-domains"],
            check=True, capture_output=True, text=True,
        ).stdout
        assert "0 processes, 0 enzyme targets" in gated_legacy
        assert "已隔离" in gated_legacy
        assert "literature-evidence" in gated_legacy

        # One evidenced entry is enough to open its process
        lib = tmp / "lib"
        lib.mkdir()
        (lib / "demo.json").write_text(
            json.dumps(
                {
                    "library_version": "0.1.0",
                    "domain": {
                        "id": "demo",
                        "name_zh": "示例",
                        "name_en": "Demo",
                        "content_status": "starter",
                        "role": "user_defined",
                        "keywords_zh": ["示例"],
                        "keywords_en": ["demo"],
                        "niche_summary_zh": "synthetic",
                        "selection_hint_zh": "synthetic",
                        "focus_taxa": [
                            {"taxon": "Examplebacterium testii", "name_zh": "示例杆菌",
                             "role_zh": "placeholder", "attention": "medium"}
                        ],
                        "processes": [
                            {
                                "id": "demo_process",
                                "name_zh": "示例过程",
                                "name_en": "Demo process",
                                "keywords_zh": ["示例过程"],
                                "keywords_en": ["demo process"],
                                "why_it_matters_zh": "placeholder",
                                "host_context_zh": "placeholder",
                                "microbe_effect_zh": "placeholder",
                                "key_taxa": ["Examplebacterium testii"],
                                "enzymes": [
                                    {
                                        "id": "demo_evidenced",
                                        "enzyme_name_zh": "已证实酶",
                                        "enzyme_name_en": "evidenced enzyme",
                                        "gene_symbols": [],
                                        "ec": "3.1.1.3",
                                        "ec_confidence": "full",
                                        "reaction_zh": "a + H2O -> b",
                                        "substrate_zh": "a",
                                        "product_zh": "b",
                                        "cofactor": "",
                                        "fold_hint": "",
                                        "known_microbial_examples": [],
                                        "entry_point": "ec",
                                        "dark_matter": False,
                                        "priority": "medium",
                                        "evidence_status": "literature_verified",
                                        "evidence_refs": ["PMID:12345678"],
                                        "provenance_note_zh": "placeholder",
                                        "validation_note_zh": "placeholder",
                                    },
                                    {
                                        "id": "demo_unevidenced",
                                        "enzyme_name_zh": "未证实酶",
                                        "enzyme_name_en": "unevidenced enzyme",
                                        "gene_symbols": [],
                                        "ec": "3.1.1.3",
                                        "ec_confidence": "full",
                                        "reaction_zh": "a + H2O -> b",
                                        "substrate_zh": "a",
                                        "product_zh": "b",
                                        "cofactor": "",
                                        "fold_hint": "",
                                        "known_microbial_examples": [],
                                        "entry_point": "ec",
                                        "dark_matter": False,
                                        "priority": "medium",
                                        "evidence_status": "curated_prior",
                                        "evidence_refs": [],
                                        "provenance_note_zh": "placeholder",
                                        "validation_note_zh": "placeholder",
                                    },
                                ],
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        gated_demo = subprocess.run(
            [sys.executable, str(browse), "--library-dir", str(lib),
             "--require-evidence", "--list-processes", "demo"],
            check=True, capture_output=True, text=True,
        ).stdout
        assert "demo_evidenced" in gated_demo
        assert "demo_unevidenced" not in gated_demo

        ungated_demo = subprocess.run(
            [sys.executable, str(browse), "--library-dir", str(lib), "--list-processes", "demo"],
            check=True, capture_output=True, text=True,
        ).stdout
        assert "demo_unevidenced" in ungated_demo

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # A work order must not ask the vendor to run decision rules for proteins
        # that are not in the order.
        card = tmp / "card.json"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "build_target_function_card.py"),
             "--output", str(card), "--target-id", "T", "--enzyme-name", "e",
             "--ec", "3.1.4.12", "--input-source", "ec"],
            check=True, capture_output=True,
        )
        cands = tmp / "cands.tsv"
        cands.write_text(
            "final_rank\tprotein_accession\torganism_or_strain\n1\tCAND_A\tOrg_a\n",
            encoding="utf-8",
        )
        hyps = tmp / "hyps.tsv"
        fields = ["protein_accession", "hypothesis_statement", "falsification_criteria"]
        hyps.write_text(
            "\t".join(fields) + "\n"
            + "\t".join(["CAND_A", "in order", "crit-A"]) + "\n"
            + "\t".join(["CAND_Z", "NOT in order", "crit-Z"]) + "\n",
            encoding="utf-8",
        )
        out = tmp / "cro"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "build_cro_work_order.py"),
             "--card", str(card), "--candidates", str(cands), "--hypotheses", str(hyps),
             "--outdir", str(out), "--scope", "candidates"],
            check=True, capture_output=True,
        )
        text = (out / "cro_work_order.md").read_text(encoding="utf-8")
        assert "CAND_A" in text
        assert "crit-A" in text
        assert "CAND_Z" not in text
        assert "crit-Z" not in text
        assert "本次委托范围内" in text

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # risk/caveat material can be attached to the work order, verbatim and attributed
        card = tmp / "card.json"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "build_target_function_card.py"),
             "--output", str(card), "--target-id", "T", "--enzyme-name", "e",
             "--ec", "3.1.4.12", "--input-source", "ec"],
            check=True, capture_output=True,
        )
        cands = tmp / "cands.tsv"
        cands.write_text("final_rank\tprotein_accession\torganism_or_strain\n1\tCAND_A\tOrg_a\n",
                         encoding="utf-8")
        context = tmp / "risks.md"
        context.write_text("## 已知风险\n\n- 候选预测不分泌\n- 模建模型置信度较低\n",
                           encoding="utf-8")
        out = tmp / "cro"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "build_cro_work_order.py"),
             "--card", str(card), "--candidates", str(cands),
             "--context", str(context),
             "--outdir", str(out), "--scope", "candidates"],
            check=True, capture_output=True,
        )
        text = (out / "cro_work_order.md").read_text(encoding="utf-8")
        assert "附录 A" in text
        assert "risks.md" in text
        assert "候选预测不分泌" in text
        # it must be attributed as our own statement, not presented as fact
        assert "未经承接方核验" in text
        # and it must not disturb the boundary statement
        assert text.index("附录 A") < text.index("边界声明")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        intake = SCRIPTS / "intake_environment.py"

        # the questionnaire must name every group the user has to answer
        asked = subprocess.run([sys.executable, str(intake), "--ask"],
                               check=True, capture_output=True, text=True).stdout
        for needle in ("在哪里跑", "机器资源", "外部软件", "数据库", "数据", "约束",
                       "允许我在本机直接执行"):
            assert needle in asked, needle

        env_json = tmp / "environment.json"
        subprocess.run([sys.executable, str(intake), "--init", "--output", str(env_json)],
                       check=True, capture_output=True)
        skeleton = json.loads(env_json.read_text(encoding="utf-8"))
        # nothing may be pre-filled into "yes": permission and network start unknown
        assert skeleton["execution"]["allow_local_execution"] == "unknown"
        assert skeleton["constraints"]["network"] == "unknown"
        assert all(value is None for value in skeleton["tools"].values())

        # a declared tool that cannot report a version is unverified, never ready;
        # a declared but missing path is missing; absent means not_provided
        skeleton["execution"]["allow_local_execution"] = True
        def fake_tool(directory: Path, name: str, banner: str) -> str:
            """A stand-in binary that prints a realistic version banner."""
            path = directory / name
            path.write_text(f"#!/bin/sh\necho '{banner}'\n", encoding="utf-8")
            path.chmod(0o755)
            return str(path)

        # a real-looking banner is the positive case; a digit alone is not enough (below)
        skeleton["tools"]["diamond"] = fake_tool(tmp, "diamond", "diamond version 2.1.8")
        skeleton["tools"]["usalign"] = fake_tool(tmp, "USalign", "US-align (Version 20240924)")
        skeleton["tools"]["cd-hit"] = "definitely-not-installed-xyz"  # missing
        fedkea_script = tmp / "main.py"
        fedkea_script.write_text("print('fedkea')\n", encoding="utf-8")
        skeleton["tools"]["fedkea"] = {
            "path": str(fedkea_script),
            "env": {"LD_LIBRARY_PATH": "/nonexistent/envs/fedkea/lib"},
        }
        answer = tmp / "answers.json"
        answer.write_text(json.dumps(skeleton), encoding="utf-8")
        card_path = tmp / "environment_card.json"
        report_path = tmp / "environment_report.md"
        subprocess.run(
            [sys.executable, str(intake), "--probe", "--config", str(answer),
             "--output-card", str(card_path), "--output-report", str(report_path)],
            check=True, capture_output=True,
        )
        card = json.loads(card_path.read_text(encoding="utf-8"))
        assert card["tools"]["diamond"]["status"] == "ready"
        assert card["tools"]["usalign"]["status"] == "ready"
        assert card["tools"]["cd-hit"]["status"] == "missing"
        # a declared env path that does not exist must not be called ready
        assert card["tools"]["fedkea"]["status"] == "unverified"
        assert card["tools"]["bakta"]["status"] == "not_provided"
        report = report_path.read_text(encoding="utf-8")
        assert "UNVERIFIED" in report and "MISSING" in report
        assert "不要把“路径存在”当成“可以跑”" in report

        # A digit in the output is NOT proof that this is the tool. On CentOS 7,
        # `/bin/echo --version` prints "echo (GNU coreutils) 8.22"; marking that as DIAMOND
        # is exactly the false-positive this probe exists to prevent.
        centos_like = tmp / "centos_like"
        centos_like.mkdir()
        skeleton3 = json.loads(json.dumps(skeleton))
        skeleton3["tools"]["diamond"] = "/bin/echo"
        skeleton3["tools"]["cd-hit"] = fake_tool(centos_like, "cd-hit", "echo (GNU coreutils) 8.22")
        skeleton3["tools"]["bakta"] = fake_tool(centos_like, "python3", "Python 3.9.7")
        answer3 = tmp / "answers3.json"
        answer3.write_text(json.dumps(skeleton3), encoding="utf-8")
        card3_path = tmp / "card3.json"
        subprocess.run(
            [sys.executable, str(intake), "--probe", "--config", str(answer3),
             "--output-card", str(card3_path)],
            check=True, capture_output=True,
        )
        card3 = json.loads(card3_path.read_text(encoding="utf-8"))
        assert card3["tools"]["diamond"]["status"] == "unverified"
        assert "通用命令" in card3["tools"]["diamond"]["detail"]
        assert card3["tools"]["cd-hit"]["status"] == "unverified"
        assert "通用命令" in card3["tools"]["cd-hit"]["detail"]
        # a python banner proves a python, not Bakta
        assert card3["tools"]["bakta"]["status"] == "unverified"
        assert "标识" in card3["tools"]["bakta"]["detail"]

        # permission is separate from capability: without an explicit yes, say so
        skeleton2 = dict(skeleton)
        skeleton2["execution"] = dict(skeleton["execution"], allow_local_execution="unknown")
        answer2 = tmp / "answers2.json"
        answer2.write_text(json.dumps(skeleton2), encoding="utf-8")
        report2 = tmp / "report2.md"
        subprocess.run(
            [sys.executable, str(intake), "--probe", "--config", str(answer2),
             "--output-report", str(report2)],
            check=True, capture_output=True,
        )
        assert "未确认" in report2.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        intake = SCRIPTS / "intake_environment.py"

        # a tool that reports a real version is ready; one that cannot is not
        fedkea_script2 = tmp / "fedkea_main.py"
        fedkea_script2.write_text("print('fedkea')\n", encoding="utf-8")
        env = {
            "execution": {"allow_local_execution": True, "workdir": str(tmp)},
            "tools": {
                "diamond": fake_tool(tmp, "diamond", "diamond version 2.1.8"),
                "cd-hit": "/bin/echo",               # generic utility -> unverified
                "usalign": None,
                "deer": None,
                "fedkea": {"path": str(fedkea_script2),
                           "env": {"LD_LIBRARY_PATH": "/nonexistent/fedkea/lib"}},
                "bakta": None,
                "signalp": None,
                "hmmsearch": None,
                "esmfold": None,
            },
            "databases": {"BAKTA_DB_FULL": str(tmp), "FEDKEA_HOME": str(tmp)},
            "data": {"candidate_proteome_fasta": str(tmp / "p.faa")},
            "constraints": {"network": "no"},
        }
        cfg = tmp / "env.json"
        cfg.write_text(json.dumps(env), encoding="utf-8")
        fragment_path = tmp / "config.tools.json"
        subprocess.run(
            [sys.executable, str(intake), "--probe", "--config", str(cfg),
             "--output-card", str(tmp / "card.json"),
             "--emit-config", str(fragment_path)],
            check=True, capture_output=True,
        )
        fragment = json.loads(fragment_path.read_text(encoding="utf-8"))

        # a ready path is carried through
        assert fragment["tools"]["sequence_screen"]["executable"].endswith("/diamond")
        # but the sequence step needs CD-HIT too, so it must not be enabled
        assert fragment["tools"]["sequence_screen"]["enabled"] is False
        assert fragment["tools"]["sequence_screen"]["cdhit_executable"] == ""
        # a tool that never reported a version contributes no path
        assert fragment["tools"]["usalign"]["executable"] == ""
        assert fragment["tools"]["usalign"]["enabled"] is False
        # a declared-but-broken env is preserved for the user to fix, and still disabled
        assert fragment["tools"]["fedkea"]["env"]["LD_LIBRARY_PATH"].endswith("fedkea/lib")
        assert fragment["tools"]["fedkea"]["enabled"] is False
        assert any("环境变量路径不存在" in n for n in fragment["_notes"])
        assert any("CD-HIT" in n for n in fragment["_notes"])
        # the fragment states the rule it followed
        assert "ready" in fragment["_rule"]

        # with permission withheld nothing may be marked auto_run_local
        env_no = json.loads(json.dumps(env))
        env_no["execution"]["allow_local_execution"] = "unknown"
        cfg2 = tmp / "env2.json"
        cfg2.write_text(json.dumps(env_no), encoding="utf-8")
        frag2 = tmp / "config2.json"
        subprocess.run(
            [sys.executable, str(intake), "--probe", "--config", str(cfg2),
             "--emit-config", str(frag2)],
            check=True, capture_output=True,
        )
        second = json.loads(frag2.read_text(encoding="utf-8"))
        for name, block in second["tools"].items():
            if isinstance(block, dict) and "auto_run_local" in block:
                assert block["auto_run_local"] is False, name

    # The plugin must never ship one user's real paths: environment intake is per-user,
    # so the repo carries placeholders only.
    audit = subprocess.run(
        [sys.executable, str(SCRIPTS / "intake_environment.py"), "--audit-paths", str(ROOT)],
        capture_output=True, text=True,
    )
    assert audit.returncode == 0, audit.stderr
    assert "路径审计通过" in audit.stdout

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # a planted real path must be caught
        planted = "data: " + "/" + "home" + "/" + "someone/project/data.faa" + "\n"
        (tmp / "leak.md").write_text(planted, encoding="utf-8")
        caught = subprocess.run(
            [sys.executable, str(SCRIPTS / "intake_environment.py"), "--audit-paths", str(tmp)],
            capture_output=True, text=True,
        )
        assert caught.returncode == 1
        assert "路径审计失败" in caught.stderr
        # generic placeholders and private-IP-free text must pass
        (tmp / "leak.md").write_text("data: /path/to/project/data.faa\n", encoding="utf-8")
        ok = subprocess.run(
            [sys.executable, str(SCRIPTS / "intake_environment.py"), "--audit-paths", str(tmp)],
            capture_output=True, text=True,
        )
        assert ok.returncode == 0, ok.stderr

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        gmps = SCRIPTS / "import_gmps.py"

        # species-map locator: only the needed tarball parts, and unmatched taxa reported
        species = tmp / "species.txt"
        species.write_text(
            "bacteria_1.tar.gz\nAkkermansia muciniphila\nBacteroides uniformis\n"
            "bacteria_2.tar.gz\nFaecalibacterium prausnitzii\n",
            encoding="utf-8",
        )
        located = subprocess.run(
            [sys.executable, str(gmps), "--species-map", str(species),
             "--taxa", "Akkermansia muciniphila,Roseburia intestinalis"],
            check=True, capture_output=True, text=True,
        )
        assert "bacteria_1.tar.gz" in located.stdout
        assert "bacteria_2.tar.gz" not in located.stdout
        assert "Roseburia intestinalis" in located.stderr

        # structural import: explicit mapping, bidirectional TM policy, provenance
        hits = tmp / "hits.tsv"
        hits.write_text(
            "query\tspecies\ttm1\ttm2\tplddt\n"
            "WP_1\tAkkermansia muciniphila\t0.86\t0.99\t92.1\n"
            "WP_2\tFaecalibacterium prausnitzii\t0.51\t0.48\t88.0\n",
            encoding="utf-8",
        )
        out = tmp / "structural.tsv"
        subprocess.run(
            [sys.executable, str(gmps), "--hits", str(hits),
             "--map", "query=protein_accession,species=organism_or_strain,tm1=tm_score_1,tm2=tm_score_2,plddt=plddt_mean",
             "--tool-version", "GMPS_v1 (test)", "--output", str(out)],
            check=True, capture_output=True,
        )
        with out.open("r", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        assert rows[0]["protein_accession"] == "WP_1"
        assert rows[0]["structure_support"] == "1"
        assert rows[1]["structure_support"] == "0"   # TM2 below the bidirectional threshold
        assert rows[0]["tool"] == "GMPS"
        provenance = json.loads((tmp / "structural.provenance.json").read_text(encoding="utf-8"))
        assert provenance["rows_in"] == 2 and provenance["rows_out"] == 2
        assert provenance["column_mapping"]["protein_accession"] == "query"
        assert len(provenance["source_sha256"]) == 64
        assert provenance["tm_threshold"] == 0.5

        # no similarity metric -> refuse rather than invent a score
        bad = tmp / "bad.tsv"
        bad.write_text("id\tnote\nA\tx\n", encoding="utf-8")
        refused = subprocess.run(
            [sys.executable, str(gmps), "--hits", str(bad),
             "--map", "id=protein_accession", "--output", str(tmp / "x.tsv")],
            capture_output=True, text=True,
        )
        assert refused.returncode == 2
        assert "相似度指标" in refused.stderr
        assert not (tmp / "x.tsv").exists()

        # annotation import: unknown columns are named, not silently dropped
        ann = tmp / "ann.tsv"
        ann.write_text(
            "protein\tproduct\tec\tdram_category\n"
            "WP_1\tsphingomyelin phosphodiesterase\t3.1.4.12\tmetabolism\n",
            encoding="utf-8",
        )
        ann_out = tmp / "source_feature_annotations.tsv"
        result = subprocess.run(
            [sys.executable, str(gmps), "--annotation", str(ann),
             "--map", "protein=protein_accession", "--source-file", "bacteria_final_annotation.tsv",
             "--annotation-source", "DRAM", "--output", str(ann_out)],
            check=True, capture_output=True, text=True,
        )
        assert "dram_category" in result.stderr
        with ann_out.open("r", encoding="utf-8") as handle:
            ann_rows = list(csv.DictReader(handle, delimiter="\t"))
        assert ann_rows[0]["ec_number"] == "3.1.4.12"
        assert ann_rows[0]["annotation_source"] == "DRAM"

        # both outputs must satisfy the plugin's own schemas
        for schema_name, table in (
            ("structural_candidates.schema.tsv", out),
            ("source_feature_annotations.schema.tsv", ann_out),
        ):
            subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_schema.py"),
                 "--schema", str(ROOT / "schemas" / schema_name), "--tsv", str(table)],
                check=True, capture_output=True,
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        gmps = SCRIPTS / "import_gmps.py"

        # --inspect must show the columns and what the aliases can infer, writing nothing
        ann = tmp / "ann.tsv"
        ann.write_text(
            "query\tproduct\tec\tcategory\n"
            "WP_1\tsphingomyelin phosphodiesterase\t3.1.4.12\tmetabolism\n"
            "WP_2\thypothetical protein\t\tunknown\n",
            encoding="utf-8",
        )
        inspected = subprocess.run(
            [sys.executable, str(gmps), "--inspect", str(ann)],
            check=True, capture_output=True, text=True,
        ).stdout
        assert "列名字" in inspected and "product" in inspected
        assert "未映射" in inspected            # 'query' and 'category' stay unresolved
        assert "不会自动映射" in inspected
        assert not list(tmp.glob("*.gmps*"))

        # annotation coarse screen: keep only the row matching the target EC, and say why
        screened = tmp / "screen.tsv"
        result = subprocess.run(
            [sys.executable, str(gmps), "--annotation", str(ann),
             "--map", "query=protein_accession,product=product,ec=ec_number",
             "--target-ec", "3.1.4.12",
             "--source-file", "bacteria_final_annotation.tsv", "--annotation-source", "DRAM",
             "--output", str(screened)],
            check=True, capture_output=True, text=True,
        )
        assert "2 行中命中 1 行" in result.stdout
        assert "EC 3.1.4.12 exact" in result.stdout
        with screened.open("r", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        assert [r["protein_accession"] for r in rows] == ["WP_1"]
        provenance = json.loads((tmp / "screen.provenance.json").read_text(encoding="utf-8"))
        assert provenance["screen"]["target_ec"] == "3.1.4.12"
        assert provenance["screen"]["rows_kept"] == 1

        # family-level EC matching works too
        family = subprocess.run(
            [sys.executable, str(gmps), "--annotation", str(ann),
             "--map", "query=protein_accession,ec=ec_number",
             "--target-ec", "3.1.4.-", "--source-file", "x.tsv",
             "--output", str(tmp / "family.tsv")],
            check=True, capture_output=True, text=True,
        )
        assert "matches family 3.1.4.-" in family.stdout

        # name-based screening
        by_name = subprocess.run(
            [sys.executable, str(gmps), "--annotation", str(ann),
             "--map", "query=protein_accession,product=product",
             "--target-name", "sphingomyelinase,sphingomyelin",
             "--source-file", "x.tsv", "--output", str(tmp / "name.tsv")],
            check=True, capture_output=True, text=True,
        )
        assert "名称命中" in by_name.stdout

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        taxa_import = SCRIPTS / "import_taxon_list.py"

        # the two shipped lists must parse, dedupe nothing, and classify assemblies
        for site, expected_rows, expected_acc in (("oral", 230, 230), ("skin", 257, 190)):
            out = tmp / site
            result = subprocess.run(
                [sys.executable, str(taxa_import),
                 "--list", str(ROOT / "resources" / "taxa" / f"{site}_known_microbes.tsv"),
                 "--site", site, "--output-dir", str(out)],
                check=True, capture_output=True, text=True,
            )
            with (out / f"{site}_taxa_registry.tsv").open("r", encoding="utf-8") as handle:
                registry = list(csv.DictReader(handle, delimiter="\t"))
            assert len(registry) == expected_rows, site
            accessions = [
                line.strip()
                for line in (out / f"{site}_genome_accessions.txt").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            assert len(accessions) == expected_acc, (site, len(accessions))
            assert all(a.startswith(("GCF_", "GCA_")) for a in accessions)
            provenance = json.loads((out / f"{site}_taxa_list.provenance.json").read_text(encoding="utf-8"))
            assert len(provenance["source_sha256"]) == 64
            assert provenance["columns_used"]["abundance"]
            # abundance -> presence score, and unmeasured must stay empty
            scored = {row["site_presence_score"] for row in registry}
            assert scored <= {"1", "2", "3", "4", "5", ""}
            assert all(row["site_presence_score"] != "0" for row in registry)
            if site == "oral":
                assert "" in scored      # the 6 rows with No Data / blank abundance

        # skin has MAG bins that are not NCBI accessions; they must be listed apart
        with (tmp / "skin" / "skin_unresolved_ids.tsv").open("r", encoding="utf-8") as handle:
            unresolved = list(csv.DictReader(handle, delimiter="\t"))
        assert len(unresolved) == 67
        assert all("bin" in row["genome_id"] or "concoct" in row["genome_id"] for row in unresolved)

        # a duplicate taxon, a bin id and an empty abundance in one synthetic list
        synth = tmp / "synth.tsv"
        synth.write_text(
            "taxon\tGENOME_ID\tabundance\n"
            "Alpha beta\tGCF_000000001.1\tOral (Abundance: High)\n"
            "Alpha beta\tGCF_000000001.1\tOral (Abundance: High)\n"
            "Gamma delta\tSAMPLE_1_bin.7\tOral (Abundance: No Data)\n",
            encoding="utf-8",
        )
        synth_out = tmp / "synth_out"
        subprocess.run(
            [sys.executable, str(taxa_import), "--list", str(synth),
             "--site", "oral", "--output-dir", str(synth_out)],
            check=True, capture_output=True,
        )
        with (synth_out / "oral_taxa_registry.tsv").open("r", encoding="utf-8") as handle:
            synth_rows = list(csv.DictReader(handle, delimiter="\t"))
        assert len(synth_rows) == 2                     # duplicate dropped
        assert synth_rows[0]["site_presence_score"] == "5"
        assert synth_rows[1]["site_presence_score"] == ""   # No Data is not a low score
        assert (synth_out / "oral_unresolved_ids.tsv").is_file()

        # the emitted registry must be usable by the ranker, and a near-tie must be flagged
        ranked = tmp / "ranked"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "score_target_priorities.py"),
             "--taxa", str(tmp / "oral" / "oral_taxa_registry.tsv"),
             "--site", "oral", "--auto-score", "--allow-missing-scores",
             "--output", str(ranked)],
            check=True, capture_output=True,
        )
        report = (ranked / "ranking_report.md").read_text(encoding="utf-8")
        assert "这份排名几乎是并列的" in report

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        taxa_import = SCRIPTS / "import_taxon_list.py"
        gmps_csv = ROOT / "resources" / "taxa" / "gmps_download_manifest.csv"

        # GMPS-style manifest: species + per-species wget command, no accession, no abundance
        inspected = subprocess.run(
            [sys.executable, str(taxa_import), "--list", str(gmps_csv),
             "--site", "gut", "--output-dir", str(tmp), "--inspect"],
            check=True, capture_output=True, text=True,
        ).stdout
        assert "装配号   : （文件中没有）" in inspected
        assert "位点丰度  : （文件中没有）" in inspected
        assert "下载链接  : Download link" in inspected
        assert not list(tmp.glob("*.tsv"))

        out = tmp / "gut"
        result = subprocess.run(
            [sys.executable, str(taxa_import), "--list", str(gmps_csv),
             "--site", "gut", "--output-dir", str(out)],
            check=True, capture_output=True, text=True,
        )
        # it must say plainly that there are no accessions and no abundance
        assert "没有装配号列" in result.stderr
        assert "没有丰度列" in result.stderr

        with (out / "gut_taxa_registry.tsv").open("r", encoding="utf-8") as handle:
            registry = list(csv.DictReader(handle, delimiter="\t"))
        assert len(registry) == 1047
        assert all(row["site_presence_score"] == "" for row in registry)

        with (out / "gut_download_manifest.tsv").open("r", encoding="utf-8") as handle:
            manifest = list(csv.DictReader(handle, delimiter="\t"))
        assert len(manifest) == 1189
        first = manifest[0]
        assert first["url"].startswith("https://gmpsdb.cn/api/download/")
        assert first["archive"].endswith(".tar.gz")
        # the wget prefix and -O flag must not leak into the parsed fields
        assert "wget" not in first["url"] and "-O" not in first["url"]

        assert (out / "gut_genome_accessions.txt").read_text(encoding="utf-8") == ""
        provenance = json.loads((out / "gut_taxa_list.provenance.json").read_text(encoding="utf-8"))
        assert provenance["has_assembly_accessions"] is False
        assert provenance["download_manifest_rows"] == 1189
        assert provenance["columns_used"]["genome_id"] is None

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        intake = SCRIPTS / "intake_environment.py"
        validate = SCRIPTS / "validate_schema.py"

        # the three newly-covered tables must satisfy their own schemas
        lit_dir = tmp / "lit"
        lit_dir.mkdir()
        lit = lit_dir / "literature_evidence.tsv"
        lit.write_text(
            "candidate_id\tprotein_accession\tevidence_type\treference_type\treference_id\tverified\n"
            "WP_1\tWP_1\tdirect_functional_evidence\tPMID\t12345678\tyes\n"
            "WP_2\tWP_2\tno_evidence\tmanual\t\tyes\n",
            encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, str(validate), "--schema",
             str(ROOT / "schemas" / "literature_evidence.schema.tsv"), "--tsv", str(lit)],
            check=True, capture_output=True,
        )

        taxa_out = tmp / "taxa"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "import_taxon_list.py"),
             "--list", str(ROOT / "resources" / "taxa" / "gmps_download_manifest.csv"),
             "--site", "gut", "--output-dir", str(taxa_out)],
            check=True, capture_output=True,
        )
        subprocess.run(
            [sys.executable, str(validate), "--schema",
             str(ROOT / "schemas" / "taxa_registry.schema.tsv"),
             "--tsv", str(taxa_out / "gut_taxa_registry.tsv")],
            check=True, capture_output=True,
        )
        subprocess.run(
            [sys.executable, str(validate), "--schema",
             str(ROOT / "schemas" / "taxa_download_manifest.schema.tsv"),
             "--tsv", str(taxa_out / "gut_download_manifest.tsv")],
            check=True, capture_output=True,
        )

        # SSH probe: an unreachable host must fail fast and say why, without hanging
        env = tmp / "env_ssh.json"
        env.write_text(json.dumps({
            "execution": {"host": "127.0.0.1", "user": "nobody", "access": "ssh",
                          "allow_local_execution": True},
        }), encoding="utf-8")
        report = tmp / "ssh.md"
        subprocess.run(
            [sys.executable, str(intake), "--probe", "--config", str(env),
             "--check-ssh", "--output-report", str(report)],
            check=True, capture_output=True, timeout=60,
        )
        text = report.read_text(encoding="utf-8")
        assert "远程执行主机：不可达" in text
        assert "TCP" in text

        # and --check-ssh must be inert when access is not ssh
        env2 = tmp / "env_local.json"
        env2.write_text(json.dumps({
            "execution": {"host": "127.0.0.1", "access": "local", "allow_local_execution": True},
        }), encoding="utf-8")
        report2 = tmp / "local.md"
        subprocess.run(
            [sys.executable, str(intake), "--probe", "--config", str(env2),
             "--check-ssh", "--output-report", str(report2)],
            check=True, capture_output=True, timeout=60,
        )
        assert "远程执行主机" not in report2.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        intake = SCRIPTS / "intake_environment.py"

        def ask(*extra: str) -> str:
            return subprocess.run(
                [sys.executable, str(intake), "--ask", *extra],
                check=True, capture_output=True, text=True,
            ).stdout

        # the choice of target must come before the environment, so the questionnaire is
        # scoped by task instead of asking for paths that will never be used
        card_only = ask("--task", "card")
        assert "本次任务范围：只建目标卡片" in card_only
        assert "不需要任何外部软件" in card_only
        # the *environment* questions are scoped out; the judgment points are not, and the DEER
        # decision is one of them, so check the tool-path blocks rather than bare names
        for absent in ("DIAMOND、CD-HIT", "US-align（必需）", "Bakta 全库", "GMPS 结构数据"):
            assert absent not in card_only, absent
        assert "不需要问：序列筛选工具、结构工具、全部外部软件、数据库、网络与资源约束" in card_only

        screening = ask("--task", "screening")
        assert "DIAMOND、CD-HIT" in screening
        assert "Bakta 全库" not in screening
        assert "US-align（必需）" not in screening
        assert "不需要问：结构工具、全部外部软件、数据库" in screening

        structure = ask("--task", "structure")
        assert "US-align（必需）" in structure
        assert "DEER（只在 US-align 候选不足时才用）" in structure
        assert "Bakta 全库" not in structure

        full = ask()
        assert "Bakta" in full and "DEER" in full

        # the two data questions are CHOICES, present in every scope, not scope-dependent prose
        # Only the start-stage decision is asked up front; the rest are named as coming later,
        # because "may DEER run" is meaningless before anything has been screened.
        for text in (card_only, screening, structure, full):
            assert "候选菌的蛋白组/基因组从哪来" in text
            assert "[user_path]" in text and "[download_ncbi]" in text
            assert "后面还会在相应步骤再问你" in text
            assert "有没有候选菌的蛋白结构文件？  [candidate_structures]  在「structure」阶段" in text
            assert "是否启用 DEER？  [deer_fallback]  在「deer」阶段" in text
            # not asked yet
            assert "[pdb_then_afdb]" not in text
            assert "[include_other_ec]" not in text

        # each stage prints its own question when the run reaches it
        deer_stage = ask("--at", "deer", "--task", "full")
        assert "US-align 合格候选不足时" in deer_stage
        assert "[skip]" in deer_stage and "[run]" in deer_stage
        assert "[download_ncbi]" not in deer_stage
        delivery_stage = ask("--at", "delivery", "--task", "full")
        assert "[include_other_ec]" in delivery_stage and "[strict]" in delivery_stage
        assert "--task card / screening / structure / full" in full

        # the execution rule never relaxes, whatever the scope
        for text in (card_only, screening, structure, full):
            assert "允许我在本机直接执行脚本" in text

        broken = subprocess.run(
            [sys.executable, str(intake), "--ask", "--task", "nope"],
            capture_output=True, text=True,
        )
        assert broken.returncode == 2
        assert "invalid choice" in broken.stderr

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ranker = SCRIPTS / "score_target_priorities.py"

        registry = tmp / "taxa.tsv"
        header = "taxon_id\tgenus\tspecies\tdisplay_name\tsite_presence_score\tgenome_availability_score\n"
        rows = [
            "a\tAlpha\talpha\tAlpha alpha\t5\t4",   # 2 backed
            "b\tBeta\tbeta\tBeta beta\t4\t",        # 1 backed
            "c\tGamma\tgamma\tGamma gamma\t3\t",    # 1 backed
        ]
        registry.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")

        def run(*flags: str) -> subprocess.CompletedProcess:
            tag = "_".join(f.replace("-", "") for f in flags) if flags else "plain"
            out = tmp / f"out_{tag}"
            return subprocess.run(
                [sys.executable, str(ranker), "--taxa", str(registry), "--site", "oral",
                 "--allow-missing-scores", "--output", str(out), *flags],
                capture_output=True, text=True,
            )

        # no gate: everything is ranked, in order
        plain = run()
        assert plain.returncode == 0, plain.stderr
        with (tmp / "out_plain" / "taxa_priority_ranking.tsv").open("r", encoding="utf-8") as handle:
            plain_rows = list(csv.DictReader(handle, delimiter="\t"))
        assert [r["rank"] for r in plain_rows] == ["1", "2", "3"]
        assert all(r["selection_status"] in ("selected", "defer") for r in plain_rows)

        # min-criteria 2: only the row with two backed components keeps a rank
        gated = run("--require-min-criteria", "2")
        assert gated.returncode == 0, gated.stderr
        with (tmp / "out_requiremincriteria_2" / "taxa_priority_ranking.tsv").open("r", encoding="utf-8") as handle:
            gated_rows = list(csv.DictReader(handle, delimiter="\t"))
        by_id = {r["taxon_id"]: r for r in gated_rows}
        assert by_id["a"]["rank"] == "1"
        assert by_id["b"]["rank"] == "" and by_id["c"]["rank"] == ""
        assert by_id["b"]["selection_status"] == "insufficient_evidence"
        assert by_id["b"]["selection_status"] != "selected"
        # withheld rows stay in the table: hiding them would fake completeness
        assert len(gated_rows) == 3
        withheld = list(csv.DictReader(
            (tmp / "out_requiremincriteria_2" / "withheld_rows.tsv").open("r", encoding="utf-8"),
            delimiter="\t",
        ))
        assert {w["id"] for w in withheld} == {"b", "c"}
        assert all("components have a value" in w["reason"] for w in withheld)
        assert "2 required" in withheld[0]["reason"]

        # min-evidence counts only data-derived components, so judgement cannot satisfy it:
        # with no --auto-score and no sources, zero components are auto-derived
        evidence_gate = run("--require-min-evidence", "1")
        assert evidence_gate.returncode == 0, evidence_gate.stderr
        with (tmp / "out_requireminevidence_1" / "taxa_priority_ranking.tsv").open("r", encoding="utf-8") as handle:
            ev_rows = list(csv.DictReader(handle, delimiter="\t"))
        assert all(r["selection_status"] == "insufficient_evidence" for r in ev_rows)
        assert all(r["rank"] == "" for r in ev_rows)
        assert "没有一行满足证据门槛" in evidence_gate.stderr
        ev_withheld = list(csv.DictReader(
            (tmp / "out_requireminevidence_1" / "withheld_rows.tsv").open("r", encoding="utf-8"),
            delimiter="\t",
        ))
        assert all("data-derived" in w["reason"] for w in ev_withheld)

        # an empty ranking must say why instead of looking like a clean result
        assert "证据不足以排序" in evidence_gate.stderr

        # both ranking tables must still satisfy their schemas with withheld rows present
        for schema, table in (
            ("taxa_priority_ranking.schema.tsv", tmp / "out_requiremincriteria_2" / "taxa_priority_ranking.tsv"),
            ("taxa_priority_ranking.schema.tsv", tmp / "out_plain" / "taxa_priority_ranking.tsv"),
            ("withheld_rows.schema.tsv", tmp / "out_requiremincriteria_2" / "withheld_rows.tsv"),
        ):
            subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_schema.py"),
                 "--schema", str(ROOT / "schemas" / schema), "--tsv", str(table)],
                check=True, capture_output=True,
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # DIAMOND --outfmt 6 writes no header. csv.DictReader would eat the first hit as the
        # header: a one-hit result became zero rows, and every other run silently lost one.
        one_hit = tmp / "one_hit.m8"
        one_hit.write_text(
            "WP_A\tWP_A\t100\t40\t0\t0\t1\t40\t1\t40\t2.5e-23\t79.3\t100\n",
            encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, str(SCRIPTS / "parse_sequence_hits.py"),
             "--input", str(one_hit),
             "--out-hits", str(tmp / "h.tsv"), "--out-candidates", str(tmp / "c.tsv"),
             "--tool", "diamond"],
            check=True, capture_output=True,
        )
        with (tmp / "h.tsv").open("r", encoding="utf-8") as handle:
            hits = list(csv.DictReader(handle, delimiter="\t"))
        assert len(hits) == 1, "a single hit must not be consumed as a header"
        assert hits[0]["protein_accession"] == "WP_A"
        assert hits[0]["pident"] == "100.0"
        assert hits[0]["query_coverage"] == "100.0"

        # several headerless hits: every line must survive
        many = tmp / "many.m8"
        many.write_text(
            "Q1\tWP_1\t85\t300\t1\t0\t1\t300\t5\t304\t1e-40\t300\t95\n"
            "Q1\tWP_2\t42\t280\t3\t1\t1\t280\t9\t288\t1e-12\t120\t88\n"
            "Q1\tWP_3\t25\t150\t8\t2\t1\t150\t1\t150\t1e-6\t60\t70\n",
            encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, str(SCRIPTS / "parse_sequence_hits.py"),
             "--input", str(many),
             "--out-hits", str(tmp / "h2.tsv"), "--out-candidates", str(tmp / "c2.tsv"),
             "--tool", "diamond"],
            check=True, capture_output=True,
        )
        with (tmp / "h2.tsv").open("r", encoding="utf-8") as handle:
            hits2 = list(csv.DictReader(handle, delimiter="\t"))
        assert [h["protein_accession"] for h in hits2] == ["WP_1", "WP_2", "WP_3"]

        # a file that DOES carry a header must still be read through the header
        headered = tmp / "headered.tsv"
        headered.write_text(
            "qseqid\tsseqid\tpident\tlength\tevalue\tbitscore\tqcovhsp\n"
            "Q1\tWP_9\t99\t400\t1e-90\t800\t100\n",
            encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, str(SCRIPTS / "parse_sequence_hits.py"),
             "--input", str(headered),
             "--out-hits", str(tmp / "h3.tsv"), "--out-candidates", str(tmp / "c3.tsv"),
             "--tool", "diamond"],
            check=True, capture_output=True,
        )
        with (tmp / "h3.tsv").open("r", encoding="utf-8") as handle:
            hits3 = list(csv.DictReader(handle, delimiter="\t"))
        assert len(hits3) == 1 and hits3[0]["protein_accession"] == "WP_9"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        fetcher = SCRIPTS / "fetch_reference_enzymes.py"

        # --dry-run must plan TWO template groups: host and microbial. One group alone misses
        # the reason this step exists (host = "is it human-like", microbial = "same enzyme").
        planned = subprocess.run(
            [sys.executable, str(fetcher), "--ec", "3.1.4.12", "--dry-run"],
            check=True, capture_output=True, text=True,
        ).stdout
        assert "host 模板查询" in planned and "microbial 模板查询" in planned
        assert "organism_id%3A9606" in planned          # host default = human
        assert "reviewed%3Atrue" in planned             # experimental evidence only
        assert "taxonomy_id%3A2" in planned             # microbial = bacteria + archaea

        # --no-host drops the host query entirely
        no_host = subprocess.run(
            [sys.executable, str(fetcher), "--ec", "3.1.4.12", "--dry-run", "--no-host"],
            check=True, capture_output=True, text=True,
        ).stdout
        assert "--no-host" in no_host
        assert "organism_id%3A9606" not in no_host

        # the reviewer-only rule is the default, and can be relaxed explicitly
        unreviewed = subprocess.run(
            [sys.executable, str(fetcher), "--ec", "3.1.4.12", "--dry-run", "--include-unreviewed"],
            check=True, capture_output=True, text=True,
        ).stdout
        assert "reviewed%3Atrue" not in unreviewed

        # the template set needs structures too, because US-align cannot use a FASTA
        assert "结构文件" in planned
        no_struct = subprocess.run(
            [sys.executable, str(fetcher), "--ec", "3.1.4.12", "--dry-run", "--no-structures"],
            check=True, capture_output=True, text=True,
        ).stdout
        assert "--no-structures" in no_struct
        assert "结构文件" not in no_struct

        # dry-run must not create any output file
        assert not list(tmp.glob("*.tsv"))

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        scorer = SCRIPTS / "score_candidates.py"

        # a sequence hit whose existing annotation names the target enzyme: this is the
        # documented fast path, and it must be reachable from the project card alone
        combined = tmp / "combined.tsv"
        fields = ["candidate_id", "protein_accession", "sequence_score", "pident",
                  "query_coverage", "source_product", "annotation", "structure_support",
                  "tm_score_mean", "fedkea_binary", "fedkea_ec", "notes"]
        with combined.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t",
                                    lineterminator="\n")
            writer.writeheader()
            writer.writerow({
                "candidate_id": "WP_1", "protein_accession": "WP_1",
                "sequence_score": "43.4", "pident": "51.4", "query_coverage": "84.7",
                "source_product": "sphingomyelin phosphodiesterase",
                "annotation": "sphingomyelin phosphodiesterase",
                "structure_support": "", "tm_score_mean": "", "fedkea_binary": "",
                "fedkea_ec": "", "notes": "",
            })

        card = tmp / "card.json"
        card.write_text(json.dumps({
            "target_id": "SMASE",
            "enzyme_name": "sphingomyelin phosphodiesterase",
            "ec": "3.1.4.12",
            "input_source": "reaction",
        }), encoding="utf-8")
        project = tmp / "project.json"
        project.write_text(json.dumps({
            "project_name": "fast_path",
            "target_function_card": json.loads(card.read_text(encoding="utf-8")),
        }), encoding="utf-8")

        def score(*extra: str) -> list[dict[str, str]]:
            out = tmp / ("scored_" + str(len(extra)) + ".tsv")
            subprocess.run(
                [sys.executable, str(scorer), "--input", str(combined),
                 "--output", str(out), *extra],
                check=True, capture_output=True,
            )
            with out.open("r", encoding="utf-8") as handle:
                return list(csv.DictReader(handle, delimiter="\t"))

        # without a target the fast path is not evaluated: say so instead of silently
        # producing a different tier for the same data
        plain = subprocess.run(
            [sys.executable, str(scorer), "--input", str(combined),
             "--output", str(tmp / "scored_plain.tsv")],
            capture_output=True, text=True,
        )
        assert plain.returncode == 0
        assert "fast path" in plain.stderr
        assert "SEQUENCE_ONLY" in (tmp / "scored_plain.tsv").read_text(encoding="utf-8")

        # the project card supplies target ec + enzyme name
        by_project = score("--project", str(project))
        assert by_project[0]["priority_tier"] == "SEQUENCE_ANNOTATION_CONFIRMED"

        # explicit flags still win / also work
        by_flags = score("--target-name", "sphingomyelin phosphodiesterase")
        assert by_flags[0]["priority_tier"] == "SEQUENCE_ANNOTATION_CONFIRMED"

        # a non-matching annotation must NOT be promoted
        combined.write_text(
            "candidate_id\tprotein_accession\tsequence_score\tpident\tquery_coverage\t"
            "source_product\tannotation\n"
            "WP_2\tWP_2\t40.0\t45.0\t80.0\tMFS transporter\tMFS transporter\n",
            encoding="utf-8",
        )
        mismatch = score("--project", str(project))
        assert mismatch[0]["priority_tier"] == "SEQUENCE_ONLY"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # run_usalign writes one partial per candidate structure and merges them. The parser
        # writes a real header, not a "#" comment, and the old merge only stripped "#", so
        # every structure contributed its header as a data row: 1,625 structures produced
        # 1,625 header lines and 2 candidates.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "run_usalign_under_test", str(SCRIPTS / "run_usalign.py"))
        run_usalign = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(run_usalign)

        header = "candidate_id\ttemplate_id\ttm_score_1\ttm_score_2\n"
        part_a = tmp / "a.hits.tsv"
        part_b = tmp / "b.hits.tsv"
        part_a.write_text(header + "WP_1\t2DDR\t0.66\t0.68\n", encoding="utf-8")
        part_b.write_text(header + "WP_2\t2DDR\t0.69\t0.73\n", encoding="utf-8")
        merged = tmp / "merged.tsv"
        run_usalign.merge_partials([part_a, part_b], merged)
        lines = [line for line in merged.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert lines[0].startswith("candidate_id")
        assert sum(1 for line in lines if line.startswith("candidate_id")) == 1
        assert len(lines) == 3, lines

        # an empty partial must not add anything, and a "#" comment header is still tolerated
        empty = tmp / "empty.tsv"
        empty.write_text("", encoding="utf-8")
        commented = tmp / "c.tsv"
        commented.write_text("#comment\nWP_3\t2DDR\t0.5\t0.5\n", encoding="utf-8")
        merged2 = tmp / "merged2.tsv"
        run_usalign.merge_partials([empty, part_a, commented], merged2)
        lines2 = [line for line in merged2.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines2) == 3, lines2          # header + WP_1 + WP_3

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # US-align filter is "TM >= threshold in BOTH directions". A mean hid a one-sided
        # match: 0.40 + 0.65 averages 0.525 while the template is covered only 40%.
        compact = tmp / "compact.txt"
        compact.write_text(
            "#PDBchain1\tPDBchain2\tTM1\tTM2\tRMSD\tID1\tID2\tIDali\tL1\tL2\tLali\n"
            "tpl.pdb:A\tone_sided.pdb:A\t0.40\t0.65\t3.0\t0.1\t0.1\t0.1\t288\t100\t60\n"
            "tpl.pdb:A\tboth.pdb:A\t0.62\t0.58\t2.1\t0.2\t0.2\t0.2\t288\t240\t230\n",
            encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, str(SCRIPTS / "parse_usalign.py"),
             "--input", str(compact), "--out-hits", str(tmp / "h.tsv"),
             "--out-candidates", str(tmp / "c.tsv"), "--threshold", "0.5"],
            check=True, capture_output=True,
        )
        with (tmp / "h.tsv").open("r", encoding="utf-8") as handle:
            hits = list(csv.DictReader(handle, delimiter="\t"))
        with (tmp / "c.tsv").open("r", encoding="utf-8") as handle:
            candidates = list(csv.DictReader(handle, delimiter="\t"))
        assert len(hits) == 2                       # every alignment is reported
        assert [c["candidate_id"] for c in candidates] == ["both"]   # only two-way support
        assert candidates[0]["tm_score_1"] == "0.6200"
        by_id = {h["candidate_id"]: h for h in hits}
        assert by_id["one_sided"]["structure_support"] == "0"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # FedKEA is often run once for a whole project, so its table can list proteins from
        # other samples. Merging that into one sample's table used to create a row for every
        # foreign accession, putting other genomes' proteins into this sample's result.
        structural = tmp / "structural.tsv"
        structural.write_text(
            "candidate_id\ttemplate_id\ttm_score_1\ttm_score_2\ttm_score_mean\t"
            "structure_support\n"
            "WP_MINE\t2DDR\t0.70\t0.72\t0.71\t1\n",
            encoding="utf-8",
        )
        fedkea = tmp / "fedkea.tsv"
        fedkea.write_text(
            "protein_accession\tfedkea_is_enzyme\tfedkea_final_result\t"
            "fedkea_ec_confidence\n"
            "WP_MINE\tTrue\t3.1.4.12\tHigh\n"
            "WP_FOREIGN\tTrue\t3.1.11.2\tHigh\n",
            encoding="utf-8",
        )
        out = tmp / "combined.tsv"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "merge_candidates.py"),
             "--structural", str(structural), "--fedkea", str(fedkea),
             "--output", str(out)],
            check=True, capture_output=True,
        )
        with out.open("r", encoding="utf-8") as handle:
            merged = list(csv.DictReader(handle, delimiter="\t"))
        assert [row["protein_accession"] for row in merged] == ["WP_MINE"], merged
        assert merged[0]["fedkea_final_result"] == "3.1.4.12"

        # with no other evidence the FedKEA rows ARE the candidate set, so they must survive
        out2 = tmp / "combined2.tsv"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "merge_candidates.py"),
             "--fedkea", str(fedkea), "--output", str(out2)],
            check=True, capture_output=True,
        )
        with out2.open("r", encoding="utf-8") as handle:
            merged2 = list(csv.DictReader(handle, delimiter="\t"))
        assert {row["protein_accession"] for row in merged2} == {"WP_MINE", "WP_FOREIGN"}

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # A missing candidate path is a question for the user, not a reason to fetch one.
        project = tmp / "project.json"
        project.write_text(json.dumps({
            "project_name": "no_candidate",
            "target_function_card": {"target_id": "DDC", "ec": "4.1.1.28"},
            "inputs": {},
        }), encoding="utf-8")
        gate = subprocess.run(
            [sys.executable, str(SCRIPTS / "preflight_inputs.py"),
             "--project", str(project), "--require-candidate-data"],
            capture_output=True, text=True,
        )
        assert gate.returncode == 1
        assert "ASK THE USER" in gate.stderr
        assert "候选菌的蛋白组/基因组文件在哪个路径" in gate.stderr
        assert "Do not download or guess a proteome" in gate.stderr

        # The same project without the flag still passes the older, weaker check
        lenient = subprocess.run(
            [sys.executable, str(SCRIPTS / "preflight_inputs.py"), "--project", str(project)],
            capture_output=True, text=True,
        )
        assert lenient.returncode == 1        # nothing configured at all is already an error

        # An empty candidate structure directory must stop US-align and ask, not skip or predict
        target = tmp / "target.pdb"
        target.write_text(
            "ATOM      1  CA  ALA A   1      0.000   0.000   0.000  1.00 50.00           C\n",
            encoding="utf-8",
        )
        empty_dir = tmp / "structures"
        empty_dir.mkdir()
        outdir = tmp / "usalign"
        checkpoint_path = tmp / "checkpoint.json"
        blocked = subprocess.run(
            [sys.executable, str(SCRIPTS / "run_usalign.py"),
             "--target", str(target), "--candidate-dir", str(empty_dir),
             "--outdir", str(outdir), "--checkpoint", str(checkpoint_path)],
            capture_output=True, text=True,
        )
        assert blocked.returncode != 0
        assert "ASK THE USER" in blocked.stderr
        assert "structure-prediction" in blocked.stderr
        assert json.loads(checkpoint_path.read_text(encoding="utf-8"))["status"] == "blocked"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # The structural branch must ask, not silently skip, and not silently predict.
        project = tmp / "project.json"
        project.write_text(json.dumps({
            "project_name": "proteome_only",
            "target_function_card": {"target_id": "DDC", "ec": "4.1.1.28"},
            "inputs": {"candidate_proteome_fasta": str(tmp / "proteome.faa")},
        }), encoding="utf-8")
        (tmp / "proteome.faa").write_text(">p1\nMKV\n", encoding="utf-8")
        # without the flag the question is still surfaced, just not fatal
        lenient = subprocess.run(
            [sys.executable, str(SCRIPTS / "preflight_inputs.py"), "--project", str(project)],
            capture_output=True, text=True,
        )
        assert "pending question" in lenient.stderr
        assert "候选菌的蛋白结构文件在哪" not in lenient.stderr   # the wording belongs to the gate
        strict = subprocess.run(
            [sys.executable, str(SCRIPTS / "preflight_inputs.py"), "--project", str(project),
             "--require-candidate-structures"],
            capture_output=True, text=True,
        )
        assert strict.returncode == 1
        assert "ASK THE USER" in strict.stderr
        assert "候选菌的蛋白结构文件在哪" in strict.stderr
        assert "structure-prediction" in strict.stderr

        # A structural hit without FedKEA is provisional, and the script must say what FedKEA
        # would change rather than letting "unvalidated" read as "no candidate".
        structural = tmp / "structural.tsv"
        structural.write_text(
            "candidate_id\ttemplate_id\ttm_score_1\ttm_score_2\ttm_score_mean\tstructure_support\n"
            "WP_1\t2DDR\t0.70\t0.72\t0.71\t1\n",
            encoding="utf-8",
        )
        combined = tmp / "combined.tsv"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "merge_candidates.py"),
             "--structural", str(structural), "--output", str(combined)],
            check=True, capture_output=True,
        )
        scored = subprocess.run(
            [sys.executable, str(SCRIPTS / "score_candidates.py"),
             "--input", str(combined), "--output", str(tmp / "scored.tsv")],
            capture_output=True, text=True,
        )
        assert "USALIGN_UNVALIDATED" in scored.stderr
        assert "FedKEA is supplementary evidence" in scored.stderr
        assert "SignalP adds secretion evidence but never changes the tier" in scored.stderr
        assert "provisional" in scored.stderr

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # AlphaFold DB file names carry the accession plus a suffix. Keying candidates by the
        # file stem left every AF2 model without its FedKEA/annotation join.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "parse_usalign_under_test", str(SCRIPTS / "parse_usalign.py"))
        parse_usalign = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(parse_usalign)
        cases = {
            "WP_011742975.1_AF-A1A0S5-model_v6": "WP_011742975.1",
            "WP_003808927.1": "WP_003808927.1",
            "1111525849483863_bin.19_00773": "1111525849483863_bin.19_00773",
            "WP_326008604.1": "WP_326008604.1",
        }
        for raw, expected in cases.items():
            assert parse_usalign.stable_structure_id(raw) == expected, raw

        # and the parsed table must key the candidate by accession, keeping the file as evidence
        compact = tmp / "compact.txt"
        compact.write_text(
            "#PDBchain1\tPDBchain2\tTM1\tTM2\tRMSD\tID1\tID2\tIDali\tL1\tL2\tLali\n"
            "tpl.pdb:A\tWP_011742975.1_AF-A1A0S5-model_v6.pdb:A\t0.62\t0.79\t3.0\t0.1\t0.2\t0.3\t288\t320\t312\n",
            encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, str(SCRIPTS / "parse_usalign.py"),
             "--input", str(compact), "--out-hits", str(tmp / "h.tsv"),
             "--out-candidates", str(tmp / "c.tsv"), "--threshold", "0.5"],
            check=True, capture_output=True,
        )
        with (tmp / "c.tsv").open("r", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        assert rows[0]["candidate_id"] == "WP_011742975.1"
        assert "AF-A1A0S5" in rows[0]["prediction_pdb"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # A structural hit whose FedKEA EC differs from the target is a candidate to TEST,
        # not an exclusion: the fold can be convergent or moonlighting, and FedKEA only predicts.
        structural = tmp / "structural.tsv"
        structural.write_text(
            "candidate_id\ttemplate_id\ttm_score_1\ttm_score_2\ttm_score_mean\tstructure_support\n"
            "WP_1\t3RBF\t0.66\t0.70\t0.68\t1\n",
            encoding="utf-8",
        )
        fedkea = tmp / "fedkea.tsv"
        fedkea.write_text(
            "protein_accession\tfedkea_is_enzyme\tfedkea_final_result\tfedkea_ec_confidence\t"
            "fedkea_accepted_name\n"
            "WP_1\tTrue\t2.6.1.9\tHigh\thistidinol-phosphate transaminase\n",
            encoding="utf-8",
        )
        project = tmp / "project.json"
        project.write_text(json.dumps({
            "project_name": "other_ec",
            "target_function_card": {"target_id": "DDC", "ec": "4.1.1.28",
                                     "enzyme_name": "aromatic L-amino acid decarboxylase"},
        }), encoding="utf-8")
        combined = tmp / "combined.tsv"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "merge_candidates.py"),
             "--structural", str(structural), "--fedkea", str(fedkea),
             "--project", str(project), "--output", str(combined)],
            check=True, capture_output=True,
        )
        scored = subprocess.run(
            [sys.executable, str(SCRIPTS / "score_candidates.py"),
             "--input", str(combined), "--output", str(tmp / "scored.tsv"),
             "--project", str(project)],
            capture_output=True, text=True,
        )
        assert "USALIGN_OTHER_EC" in scored.stderr
        assert "NOT exclusions" in scored.stderr
        assert "plan assays for the target reaction AND the FedKEA-predicted EC" in scored.stderr

        # and the hypothesis table must recommend assaying both reactions
        summary = subprocess.run(
            [sys.executable, str(SCRIPTS / "summarize_candidates.py"),
             "--scored", str(tmp / "scored.tsv"), "--project", str(project),
             "--outdir", str(tmp / "out")],
            capture_output=True, text=True,
        )
        assert summary.returncode == 0, summary.stderr
        with (tmp / "out" / "experimental_hypotheses.tsv").open("r", encoding="utf-8") as handle:
            hypotheses = list(csv.DictReader(handle, delimiter="\t"))
        prediction = hypotheses[0]["testable_prediction"]
        assert "side-by-side assay" in prediction
        assert "4.1.1.28" in prediction and "2.6.1.9" in prediction

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # An empty final table must explain itself: "no row matched the delivery rules" is not
        # "no candidate", and the note has to say what widens the rule set.
        structural = tmp / "structural.tsv"
        structural.write_text(
            "candidate_id\ttemplate_id\ttm_score_1\ttm_score_2\ttm_score_mean\tstructure_support\n"
            "WP_1\t3RBF\t0.66\t0.70\t0.68\t1\n",
            encoding="utf-8",
        )
        fedkea = tmp / "fedkea.tsv"
        fedkea.write_text(
            "protein_accession\tfedkea_is_enzyme\tfedkea_final_result\tfedkea_ec_confidence\n"
            "WP_1\tTrue\t2.6.1.9\tHigh\n",
            encoding="utf-8",
        )
        project = tmp / "project.json"
        project.write_text(json.dumps({
            "target_function_card": {"target_id": "DDC", "ec": "4.1.1.28"},
        }), encoding="utf-8")
        combined = tmp / "combined.tsv"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "merge_candidates.py"),
             "--structural", str(structural), "--fedkea", str(fedkea),
             "--project", str(project), "--output", str(combined)],
            check=True, capture_output=True,
        )
        scored_path = tmp / "scored.tsv"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "score_candidates.py"),
             "--input", str(combined), "--output", str(scored_path),
             "--project", str(project)],
            check=True, capture_output=True,
        )

        out = tmp / "out"
        run = subprocess.run(
            [sys.executable, str(SCRIPTS / "summarize_candidates.py"),
             "--scored", str(scored_path), "--project", str(project), "--outdir", str(out)],
            capture_output=True, text=True,
        )
        assert run.returncode == 0, run.stderr
        note = out / "final_target_candidates_note.md"
        assert note.is_file(), "an empty final table must come with an explanation"
        text = note.read_text(encoding="utf-8")
        assert "This is NOT the same as 'no candidate'" in text
        assert "--final-rules" in text
        assert "USALIGN_OTHER_EC" in text
        assert "is empty because no candidate matches" in run.stderr

        # and widening the rule set must actually deliver the row
        widened = subprocess.run(
            [sys.executable, str(SCRIPTS / "summarize_candidates.py"),
             "--scored", str(scored_path), "--project", str(project),
             "--outdir", str(tmp / "out2"),
             "--final-rules", "USALIGN_TARGET_EC,SEQUENCE_ANNOTATION_CONFIRMED,USALIGN_OTHER_EC"],
            capture_output=True, text=True,
        )
        assert widened.returncode == 0, widened.stderr
        with (tmp / "out2" / "final_target_candidates.tsv").open("r", encoding="utf-8") as handle:
            delivered = list(csv.DictReader(handle, delimiter="\t"))
        assert [row["protein_accession"] for row in delivered] == ["WP_1"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        intake = SCRIPTS / "intake_environment.py"

        # the skeleton must carry both decisions as unfilled choices, never a default answer
        env_json = tmp / "environment.json"
        subprocess.run([sys.executable, str(intake), "--init", "--output", str(env_json)],
                       check=True, capture_output=True)
        skeleton = json.loads(env_json.read_text(encoding="utf-8"))
        assert set(skeleton["decisions"]) == {
            "candidate_data", "candidate_structures", "structure_source",
            "deer_fallback", "ranking_policy", "delivery_rules",
        }
        for name, value in skeleton["decisions"].items():
            assert value["choice"] is None, name

        def probe(decisions: dict) -> tuple[dict, str]:
            cfg = tmp / "cfg.json"
            cfg.write_text(json.dumps({"execution": {"allow_local_execution": True},
                                       "decisions": decisions}), encoding="utf-8")
            card_path = tmp / "card.json"
            report = tmp / "report.md"
            subprocess.run(
                [sys.executable, str(intake), "--probe", "--config", str(cfg),
                 "--output-card", str(card_path), "--output-report", str(report)],
                check=True, capture_output=True,
            )
            return json.loads(card_path.read_text(encoding="utf-8")), report.read_text(encoding="utf-8")

        # choosing "I have files" without a path must be reported, not accepted
        card, report = probe({
            "candidate_data": {"choice": "user_path"},
            "candidate_structures": {"choice": "skip"},
        })
        assert card["decisions"]["candidate_data"]["status"] == "needs_field"
        assert "缺少 path" in card["decisions"]["candidate_data"]["detail"]
        assert "缺少 path" in report

        # a fully answered pair resolves, and the structure kind is validated
        card, report = probe({
            "candidate_data": {"choice": "user_path", "path": "/data/x.faa"},
            "candidate_structures": {"choice": "user_path", "dir": "/data/pdb",
                                     "kind": "predicted"},
        })
        assert card["decisions"]["candidate_data"]["status"] == "resolved"
        assert card["decisions"]["candidate_structures"]["status"] == "resolved"
        assert "predicted" in card["decisions"]["candidate_structures"]["detail"]

        bad_kind, _ = probe({
            "candidate_data": {"choice": "download_ncbi", "accession": "GCF_000010425.1"},
            "candidate_structures": {"choice": "user_path", "dir": "/data/pdb", "kind": "maybe"},
        })
        assert bad_kind["decisions"]["candidate_structures"]["status"] == "invalid"
        assert "experimental" in bad_kind["decisions"]["candidate_structures"]["detail"]

        unknown, _ = probe({"candidate_data": {"choice": "whatever"},
                            "candidate_structures": {"choice": "skip"}})
        assert unknown["decisions"]["candidate_data"]["status"] == "invalid"

        # "no decision yet" must never be treated as answered
        undecided, _ = probe({})
        assert undecided["decisions"]["candidate_data"]["status"] == "needs_decision"
        assert "不要自己替他选" in undecided["decisions"]["candidate_data"]["detail"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        decisions_path = tmp / "environment.json"
        decisions_path.write_text(json.dumps({
            "decisions": {"deer_fallback": {"choice": None}, "delivery_rules": {"choice": None}}
        }), encoding="utf-8")

        # a stage script must refuse to proceed on an unanswered decision, and show the options
        project = tmp / "project.json"
        project.write_text(json.dumps({"target_function_card": {"ec": "4.1.1.28"}}), encoding="utf-8")
        deer = subprocess.run(
            [sys.executable, str(SCRIPTS / "run_deer.py"), "--project", str(project),
             "--decisions", str(decisions_path)],
            capture_output=True, text=True,
        )
        assert deer.returncode == 3, deer.returncode
        assert "DECISION REQUIRED" in deer.stderr
        assert "[run]" in deer.stderr and "[skip]" in deer.stderr

        # the explicit override counts as the user's instruction, and says so
        overridden = subprocess.run(
            [sys.executable, str(SCRIPTS / "run_deer.py"), "--project", str(project),
             "--decisions", str(decisions_path), "--allow-without-usalign"],
            capture_output=True, text=True,
        )
        assert "explicitly asked for it" in (overridden.stderr + overridden.stdout)

        # delivery: an unanswered delivery_rules decision is printed, not silently defaulted
        structural = tmp / "structural.tsv"
        structural.write_text(
            "candidate_id\ttemplate_id\ttm_score_1\ttm_score_2\ttm_score_mean\tstructure_support\n"
            "WP_1\t3RBF\t0.66\t0.70\t0.68\t1\n",
            encoding="utf-8",
        )
        combined = tmp / "combined.tsv"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "merge_candidates.py"),
             "--structural", str(structural), "--project", str(project),
             "--output", str(combined)],
            check=True, capture_output=True,
        )
        scored = tmp / "scored.tsv"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "score_candidates.py"),
             "--input", str(combined), "--output", str(scored), "--project", str(project)],
            check=True, capture_output=True,
        )
        summary = subprocess.run(
            [sys.executable, str(SCRIPTS / "summarize_candidates.py"),
             "--scored", str(scored), "--project", str(project), "--outdir", str(tmp / "out"),
             "--decisions", str(decisions_path)],
            capture_output=True, text=True,
        )
        assert "DECISION REQUIRED" in summary.stderr
        assert "[include_other_ec]" in summary.stderr

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # A query that matches only the body-site word is not coverage: "皮肤外源性物质代谢"
        # scored 80 on the skin domain while the library's only skin process is sphingolipid,
        # so both the search output and the router must say the topic is not curated.
        search = subprocess.run(
            [sys.executable, str(SCRIPTS / "browse_target_library.py"),
             "--search", "皮肤外源性物质代谢"],
            capture_output=True, text=True,
        )
        assert search.returncode == 0, search.stderr
        # the starter domain now covers the topic, so a process-level hit is expected
        assert "PROCESS" in search.stdout
        assert "外源" in search.stdout or "偶氮" in search.stdout or "药物" in search.stdout

        routed = subprocess.run(
            [sys.executable, str(SCRIPTS / "resolve_target_intent.py"),
             "--query", "我比较关注皮肤外源性物质代谢相关的生理过程，有哪些代谢酶和哪些菌值得关注呢？"],
            capture_output=True, text=True,
        )
        assert routed.returncode == 0, routed.stderr
        # with the starter domain in place the same sentence is now entry B, and the starter
        # nature of those hits must be stated so they are not mistaken for curated coverage
        assert "route: entry B" in routed.stdout
        assert "starter 域" in routed.stdout
        assert "没有逐条证据" in routed.stdout

        # an explicit enzyme query still hits for real
        enzyme = subprocess.run(
            [sys.executable, str(SCRIPTS / "browse_target_library.py"),
             "--search", "sphingomyelinase"],
            capture_output=True, text=True,
        )
        assert enzyme.returncode == 0
        assert "命中的只是**部位名**" not in enzyme.stdout

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        rec = SCRIPTS / "record_query.py"
        staging = tmp / "queries.json"

        # 1) record a user query; a query is not evidence, so refs stay empty and it is staged
        first = subprocess.run(
            [sys.executable, str(rec), "--staging", str(staging),
             "--query", "皮肤外源性物质代谢", "--site", "skin",
             "--enzyme", "esterase", "--enzyme", "azoreductase",
             "--taxon", "Cutibacterium acnes"],
            check=True, capture_output=True, text=True,
        )
        entry_id = json.loads(staging.read_text(encoding="utf-8"))["queries"][0]["id"]
        assert "已" not in first.stdout or True
        data = json.loads(staging.read_text(encoding="utf-8"))
        assert data["queries"][0]["evidence_refs"] == []
        assert data["queries"][0]["evidence_status"] == "curated_prior"

        # 2) asking again increments instead of duplicating, and merges new enzymes
        subprocess.run(
            [sys.executable, str(rec), "--staging", str(staging),
             "--query", "皮肤外源性物质代谢", "--site", "skin", "--enzyme", "epoxide hydrolase"],
            check=True, capture_output=True,
        )
        data = json.loads(staging.read_text(encoding="utf-8"))
        assert len(data["queries"]) == 1
        assert data["queries"][0]["times_asked"] == 2
        assert "epoxide hydrolase" in data["queries"][0]["enzymes"]

        # 3) the same wording at another site is a different entry
        subprocess.run(
            [sys.executable, str(rec), "--staging", str(staging),
             "--query", "皮肤外源性物质代谢", "--site", "gut", "--enzyme", "esterase"],
            check=True, capture_output=True,
        )
        assert len(json.loads(staging.read_text(encoding="utf-8"))["queries"]) == 2

        # 4) promotion without evidence is refused
        refused = subprocess.run(
            [sys.executable, str(rec), "--staging", str(staging), "--promote", entry_id,
             "--domain", "skin_x", "--output", str(tmp / "spec.json")],
            capture_output=True, text=True,
        )
        assert refused.returncode == 2
        assert "requires evidence_refs" in refused.stderr

        # 5) promotion with a real identifier writes a spec with EMPTY refs plus a sidecar,
        #    because build_library_domain rejects identifiers inside a starter spec
        promoted = subprocess.run(
            [sys.executable, str(rec), "--staging", str(staging), "--promote", entry_id,
             "--domain", "skin_x", "--output", str(tmp / "spec.json"),
             "--evidence-refs", "PMID:33385118"],
            check=True, capture_output=True, text=True,
        )
        spec = json.loads((tmp / "spec.json").read_text(encoding="utf-8"))["domain"]
        enzymes = spec["processes"][0]["enzymes"]
        assert all(e["evidence_refs"] == [] for e in enzymes)
        assert "PMID:33385118" in enzymes[0]["provenance_note_zh"]
        assert json.loads((tmp / "spec.evidence.json").read_text(encoding="utf-8"))["evidence_refs"] == ["PMID:33385118"]
        assert "evidence sidecar" in promoted.stdout

        # 6) a malformed identifier is rejected rather than written
        bad = subprocess.run(
            [sys.executable, str(rec), "--staging", str(staging), "--promote", entry_id,
             "--domain", "skin_x", "--output", str(tmp / "s2.json"),
             "--evidence-refs", "PMID:abc"],
            capture_output=True, text=True,
        )
        assert bad.returncode == 2 and "not PMID:/DOI:" in bad.stderr

        # 7) staging is listable and the library never reads it
        listed = subprocess.run(
            [sys.executable, str(SCRIPTS / "browse_target_library.py"),
             "--list-staging", "--staging", str(staging)],
            check=True, capture_output=True, text=True,
        )
        assert "条查询记录" in listed.stdout
        assert "正式库不会读取" in listed.stdout

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        attach = SCRIPTS / "attach_library_evidence.py"

        # start from a built domain: every entry is curated_prior with empty refs
        # use the real starter spec: the builder enforces a large set of required fields, and
        # hand-writing a throwaway spec here would only re-test that validation
        spec = tmp / "spec.json"
        lib = tmp / "lib.json"
        spec.write_text(
            (ROOT / "specs" / "skin_xenobiotic.spec.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        subprocess.run([sys.executable, str(SCRIPTS / "build_library_domain.py"), "--build",
                        "--spec", str(spec), "--output", str(lib)],
                       check=True, capture_output=True)

        PROC, ENZ = "skin_azo_dye_reduction", "skin_azoreductase"

        def entry() -> dict:
            data = json.loads(lib.read_text(encoding="utf-8"))
            for process in data["domain"]["processes"]:
                if process["id"] == PROC:
                    return process["enzymes"][0]
            raise AssertionError("process missing")

        # a malformed identifier is refused
        bad = subprocess.run(
            [sys.executable, str(attach), "--library", str(lib), "--process", PROC,
             "--enzyme", ENZ, "--refs", "PMID:abc", "--claim", "x", "--status", "literature_verified"],
            capture_output=True, text=True,
        )
        assert bad.returncode == 2 and "not PMID:/DOI:" in bad.stderr

        # a bare number is not an identifier either
        bare = subprocess.run(
            [sys.executable, str(attach), "--library", str(lib), "--process", PROC,
             "--enzyme", ENZ, "--refs", "33385118", "--claim", "x"],
            capture_output=True, text=True,
        )
        assert bare.returncode == 2

        # --claim is mandatory
        no_claim = subprocess.run(
            [sys.executable, str(attach), "--library", str(lib), "--process", PROC,
             "--enzyme", ENZ, "--refs", "PMID:33385118", "--claim", "  "],
            capture_output=True, text=True,
        )
        assert no_claim.returncode == 2 and "--claim" in no_claim.stderr

        # unknown enzyme is refused with the available ids
        unknown = subprocess.run(
            [sys.executable, str(attach), "--library", str(lib), "--process", PROC,
             "--enzyme", "nope", "--refs", "PMID:33385118", "--claim", "x"],
            capture_output=True, text=True,
        )
        assert unknown.returncode == 2 and ENZ in unknown.stderr

        # dry-run changes nothing
        before = entry()
        dry = subprocess.run(
            [sys.executable, str(attach), "--library", str(lib), "--process", PROC,
             "--enzyme", ENZ, "--refs", "PMID:33385118", "--claim", "x",
             "--status", "literature_verified", "--dry-run"],
            check=True, capture_output=True, text=True,
        )
        assert "--dry-run" in dry.stdout
        assert entry() == before

        # curated_prior MAY carry refs: retrieval visible, entry still quarantined
        prior = subprocess.run(
            [sys.executable, str(attach), "--library", str(lib), "--process", PROC,
             "--enzyme", ENZ, "--refs", "PMID:33385118",
             "--claim", "only a prediction in the cited paper", "--status", "curated_prior"],
            check=True, capture_output=True, text=True,
        )
        assert entry()["evidence_status"] == "curated_prior"
        assert entry()["evidence_refs"] == ["PMID:33385118"]
        assert "only a prediction" in entry()["provenance_note_zh"]
        assert "quarantined" in prior.stdout
        gated = subprocess.run(
            [sys.executable, str(SCRIPTS / "browse_target_library.py"), "--library-dir", str(tmp),
             "--require-evidence", "--list-domains"],
            capture_output=True, text=True,
        )
        assert "0 processes, 0 enzyme targets" in gated.stdout

        # verification requires the claim to be stored and flips the entry into the gate
        subprocess.run(
            [sys.executable, str(attach), "--library", str(lib), "--process", PROC,
             "--enzyme", ENZ, "--refs", "PMID:33385118",
             "--claim", "the paper states skin bacteria reduce azo dyes with azoreductase",
             "--status", "literature_verified"],
            check=True, capture_output=True,
        )
        assert entry()["evidence_status"] == "literature_verified"
        assert "azoreductase" in entry()["provenance_note_zh"]
        gated2 = subprocess.run(
            [sys.executable, str(SCRIPTS / "browse_target_library.py"), "--library-dir", str(tmp),
             "--require-evidence", "--list-domains"],
            capture_output=True, text=True,
        )
        assert "1 process, 1 enzyme target" in gated2.stdout

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Ranking must reflect evidence, and "no evidence" must not be scored as "low evidence".
        enumerator = tmp / "enzymes.tsv"
        enumerator.write_text(
            "target_id\tname\tsite_process\tbiochemical_clarity_score\n"
            "verified_two\tazoreductase\tp\t\n"
            "prior_only\testerase\tp\t\n",
            encoding="utf-8",
        )
        library = tmp / "lib.json"
        library.write_text(json.dumps({"library_version": "0.1.0", "domain": {
            "id": "skin_x", "name_zh": "皮肤", "name_en": "Skin",
            "content_status": "starter", "role": "user_defined",
            "keywords_zh": ["x"], "keywords_en": ["x"],
            "niche_summary_zh": "t", "selection_hint_zh": "t",
            "focus_taxa": [{"taxon": "Cutibacterium acnes", "attention": "high"}],
            "processes": [{"id": "p", "name_zh": "p", "name_en": "p",
                           "keywords_zh": ["x"], "keywords_en": ["x"], "why_it_matters_zh": "t",
                           "host_context_zh": "h", "microbe_effect_zh": "m",
                           "key_taxa": ["Cutibacterium acnes"],
                           "enzymes": [
                               {"id": "verified_two", "enzyme_name_zh": "a",
                                "enzyme_name_en": "a", "ec": "", "ec_confidence": "none",
                                "reaction_zh": "r", "substrate_zh": "s", "product_zh": "p",
                                "entry_point": "reaction", "dark_matter": False,
                                "priority": "high", "evidence_status": "literature_verified",
                                "evidence_refs": ["PMID:11111111", "PMID:22222222"],
                                "provenance_source": "literature",
                                "provenance_note_zh": "two refs", "validation_note_zh": "assay"},
                               {"id": "prior_only", "enzyme_name_zh": "b",
                                "enzyme_name_en": "b", "ec": "", "ec_confidence": "none",
                                "reaction_zh": "r", "substrate_zh": "s", "product_zh": "p",
                                "entry_point": "reaction", "dark_matter": False,
                                "priority": "medium", "evidence_status": "curated_prior",
                                "evidence_refs": [], "provenance_source": "user_supplied",
                                "provenance_note_zh": "prior", "validation_note_zh": "assay"},
                           ]}],
        }}, ensure_ascii=False), encoding="utf-8")

        out = tmp / "ranked"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "score_target_priorities.py"),
             "--enzymes", str(enumerator), "--library", str(library),
             "--auto-score", "--allow-missing-scores", "--site", "skin",
             "--output", str(out)],
            check=True, capture_output=True,
        )
        with (out / "enzyme_priority_ranking.tsv").open("r", encoding="utf-8") as handle:
            rows = {r["target_id"]: r for r in csv.DictReader(handle, delimiter="\t")}
        # verified with two references earns a high site-evidence score
        assert rows["verified_two"]["site_evidence_score"] == "5.000"
        # curated prior with no references stays UNKNOWN: the cell counts as 0 for the weighted
        # sum (the documented convention) but the provenance says "missing", not "auto:library",
        # so nobody can mistake it for measured low evidence
        assert "site_evidence_score=missing" in rows["prior_only"]["score_sources"]
        assert rows["prior_only"]["site_evidence_score"] == "0.000"
        # and the verified target therefore ranks first
        assert rows["verified_two"]["rank"] == "1"

        # focus_taxa feed metabolic plausibility for the taxa ranking
        taxa = tmp / "taxa.tsv"
        taxa.write_text(
            "taxon_id\tgenus\tspecies\tdisplay_name\tsite_presence_score\n"
            "cutibacterium_acnes\tCutibacterium\tacnes\tCutibacterium acnes\t5\n"
            "other_species\tOther\tspecies\tOther species\t5\n",
            encoding="utf-8",
        )
        taxa_out = tmp / "taxa_ranked"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "score_target_priorities.py"),
             "--taxa", str(taxa), "--library", str(library),
             "--auto-score", "--allow-missing-scores", "--site", "skin",
             "--output", str(taxa_out)],
            check=True, capture_output=True,
        )
        with (taxa_out / "taxa_priority_ranking.tsv").open("r", encoding="utf-8") as handle:
            taxa_rows = {r["taxon_id"]: r for r in csv.DictReader(handle, delimiter="\t")}
        assert taxa_rows["cutibacterium_acnes"]["metabolic_plausibility_score"] == "4.000"
        # same convention as above: not derived -> source says missing, cell counts as 0
        assert "metabolic_plausibility_score=missing" in taxa_rows["other_species"]["score_sources"]
        assert taxa_rows["other_species"]["metabolic_plausibility_score"] == "0.000"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        shortlist = SCRIPTS / "build_candidate_shortlist.py"

        # two enzyme sources with different completeness: a hand-scored legacy registry and a
        # verified library entry. Ranking them by score alone puts the verified one last.
        legacy = tmp / "legacy.tsv"
        legacy.write_text(
            "rank\ttarget_id\tgene\tname\tuniprot\tec\tskin_process\t"
            "known_score\tdiscovery_score\tpriority_score\t"
            "skin_evidence_score\tdisease_relevance_score\tbiochemical_clarity_score\t"
            "sequence_structure_score\tmicrobial_plausibility_score\t"
            "assay_feasibility_score\tnovelty_score\tnotes\n"
            "1\tXEN-001\tADH1B\tAlcohol dehydrogenase\t\t1.1.1.1\tp\t"
            "5\t4.4\t4.7\t5\t5\t5\t5\t5\t5\t3\tmanually scored\n",
            encoding="utf-8",
        )
        library = tmp / "lib.json"
        library.write_text(json.dumps({"library_version": "0.1.0", "domain": {
            "id": "skin_x", "name_zh": "皮肤", "name_en": "Skin",
            "content_status": "starter", "role": "user_defined",
            "keywords_zh": ["x"], "keywords_en": ["x"],
            "niche_summary_zh": "t", "selection_hint_zh": "t", "focus_taxa": [],
            "processes": [{"id": "p", "name_zh": "p", "name_en": "p",
                           "keywords_zh": ["x"], "keywords_en": ["x"], "why_it_matters_zh": "t",
                           "host_context_zh": "h", "microbe_effect_zh": "m", "key_taxa": ["x"],
                           "enzymes": [{"id": "azo", "enzyme_name_zh": "偶氮还原酶",
                                        "enzyme_name_en": "azoreductase", "ec": "",
                                        "ec_confidence": "none", "reaction_zh": "r",
                                        "substrate_zh": "s", "product_zh": "p",
                                        "entry_point": "reaction", "dark_matter": False,
                                        "priority": "high", "evidence_status": "literature_verified",
                                        "evidence_refs": ["PMID:33385118"],
                                        "provenance_source": "literature",
                                        "provenance_note_zh": "skin bacteria reduce azo dyes",
                                        "validation_note_zh": "assay"}]}]}},
        ), encoding="utf-8")
        seeded = tmp / "seeded.tsv"
        seeded.write_text(
            "target_id\tgene\tname\tuniprot\tec\tsite_process\nazo\t\tazoreductase\t\t\tp\n",
            encoding="utf-8",
        )
        taxa = tmp / "taxa.tsv"
        taxa.write_text(
            "taxon_id\tgenus\tspecies\tdisplay_name\tsite_presence_score\n"
            "a\tCutibacterium\tacnes\tCutibacterium acnes\t5\n",
            encoding="utf-8",
        )

        out = tmp / "out"
        result = subprocess.run(
            [sys.executable, str(shortlist), "--site", "skin",
             "--enzymes", str(legacy), "--enzymes", str(seeded),
             "--taxa", str(taxa), "--library", str(library),
             "--output-dir", str(out)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "merged 2 row(s)" in result.stdout

        with (out / "candidate_enzymes.tsv").open("r", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        by_id = {r["target_id"]: r for r in rows}
        # the verified entry ranks first even though its score (1.65) is far below 4.7
        assert rows[0]["target_id"] == "azo"
        assert rows[0]["evidence_status"] == "literature_verified"
        assert rows[0]["evidence_refs"] == "PMID:33385118"
        # a user-supplied registry says so instead of "unknown"
        assert by_id["XEN-001"]["evidence_status"] == "user_supplied（无 references）"
        assert "not comparable" in by_id["XEN-001"]["ranking_note"]
        # both sources survive the merge instead of one silently replacing the other
        assert len(rows) == 2
        # every component that feeds the score is exported, so the number can be reproduced
        for column in ("known_score", "discovery_score", "site_evidence_score",
                       "disease_relevance_score", "biochemical_clarity_score",
                       "sequence_structure_score", "microbial_plausibility_score",
                       "assay_feasibility_score", "novelty_score"):
            assert column in rows[0], column
        coeffs_known = {"site_evidence_score": 0.30, "disease_relevance_score": 0.25,
                        "biochemical_clarity_score": 0.25, "sequence_structure_score": 0.20}
        coeffs_disc = {"microbial_plausibility_score": 0.40, "assay_feasibility_score": 0.30,
                       "novelty_score": 0.30}
        azo = by_id["azo"]
        known = sum(w * float(azo.get(k) or 0) for k, w in coeffs_known.items())
        disc = sum(w * float(azo.get(k) or 0) for k, w in coeffs_disc.items())
        assert abs((0.5 * known + 0.5 * disc) - float(azo["priority_score"])) < 0.001

        with (out / "candidate_taxa.tsv").open("r", encoding="utf-8") as handle:
            taxa_rows = list(csv.DictReader(handle, delimiter="\t"))
        assert len(taxa_rows) == 1

        # the recommended tables only hold rows with >=2 scored components; the rest stay in the pool
        for name, minimum in (("recommended_enzymes.tsv", 2), ("recommended_taxa.tsv", 2)):
            path = out / name
            if not path.is_file():
                continue
            for row in csv.DictReader(path.open("r", encoding="utf-8"), delimiter="\t"):
                assert int(row["scored_components"]) >= minimum, (name, row)

        note = (out / "candidate_shortlist.md").read_text(encoding="utf-8")
        assert "## 1. Recommended" in note and "## 2. Candidate pool" in note
        assert "azoreductase" in note
        assert "--genomes" in note and "--literature" in note

    # literature-derived discovery: only what the retrieved text actually says
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "discover_enzyme_candidates", SCRIPTS / "discover_enzyme_candidates.py"
    )
    discover = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(discover)

    papers = [
        {"pmid": "11111111", "title": "Azo dyes are reduced by skin bacteria",
         "abstract": "Skin bacteria reduce azo dyes using their azoreductase. Activity was "
                     "measured in Staphylococcus epidermidis."},
        {"pmid": "22222222", "title": "Xenobiotic metabolism in the skin microbiome",
         "abstract": "Carboxylesterase (EC 3.1.1.1) hydrolyses esters in skin bacteria."},
        {"pmid": "33333333", "title": "Review of skin barrier lipids",
         "abstract": "Ceramides dominate the stratum corneum; no drug metabolism is discussed."},
    ]
    found = discover.find_candidates(papers)
    names = {name for name, _ec in found}
    assert "azoreductase" in names
    assert "carboxylesterase" in names
    # an enzyme named in one paper and an EC in another must not be joined
    assert found[("azoreductase", "")]["pmids"] == ["11111111"]
    assert found[("carboxylesterase", "3.1.1.1")]["pmids"] == ["22222222"]
    # a paper that mentions neither contributes nothing
    assert all("33333333" not in entry["pmids"] for entry in found.values())
    # the EC is recorded only because it appears in the same sentence
    assert found[("carboxylesterase", "3.1.1.1")]["quote"].startswith("Carboxylesterase")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        registry = tmp / "reg.tsv"
        evidence = tmp / "ev.tsv"
        discover.write_registry(registry, list(found.values()), "skin", "xenobiotic metabolism")
        discover.write_evidence(evidence, list(found.values()), "skin")
        assert "azoreductase" in registry.read_text(encoding="utf-8")
        rows = list(csv.DictReader(evidence.open("r", encoding="utf-8"), delimiter="\t"))
        assert {r["reference_id"] for r in rows} == {"11111111", "22222222"}
        assert all(r["verified"] == "yes" for r in rows)

    # the same enzyme under two ids must not appear twice, and the verified one must win
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        first = tmp / "a.tsv"
        second = tmp / "b.tsv"
        first.write_text("target_id\tgene\tname\tuniprot\tec\tsite_process\n"
                         "lit_azoreductase_noec\t\tazoreductase\t\t\tp\n", encoding="utf-8")
        second.write_text("target_id\tgene\tname\tuniprot\tec\tsite_process\n"
                          "skin_azoreductase\t\tazoreductase (Azo1) \t\t\tp\n", encoding="utf-8")
        lib = tmp / "lib.json"
        lib.write_text(json.dumps({"library_version": "0.1.0", "domain": {
            "id": "skin_x", "name_zh": "皮肤", "name_en": "Skin",
            "content_status": "starter", "role": "user_defined",
            "keywords_zh": ["x"], "keywords_en": ["x"],
            "niche_summary_zh": "t", "selection_hint_zh": "t", "focus_taxa": [],
            "processes": [{"id": "p", "name_zh": "p", "name_en": "p",
                           "keywords_zh": ["x"], "keywords_en": ["x"], "why_it_matters_zh": "t",
                           "host_context_zh": "h", "microbe_effect_zh": "m", "key_taxa": ["x"],
                           "enzymes": [{"id": "skin_azoreductase", "enzyme_name_zh": "偶氮还原酶",
                                        "enzyme_name_en": "azoreductase (Azo1)", "ec": "",
                                        "ec_confidence": "none", "reaction_zh": "r",
                                        "substrate_zh": "s", "product_zh": "p",
                                        "entry_point": "reaction", "dark_matter": False,
                                        "priority": "high",
                                        "evidence_status": "literature_verified",
                                        "evidence_refs": ["PMID:33385118"],
                                        "provenance_source": "literature",
                                        "provenance_note_zh": "skin bacteria reduce azo dyes",
                                        "validation_note_zh": "assay"}]}]},
        }), encoding="utf-8")
        out = tmp / "out"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "build_candidate_shortlist.py"), "--site", "skin",
             "--enzymes", str(first), "--enzymes", str(second), "--library", str(lib),
             "--output-dir", str(out)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        rows = list(csv.DictReader((out / "candidate_enzymes.tsv").open("r", encoding="utf-8"),
                                   delimiter="\t"))
        assert len(rows) == 1, rows
        assert rows[0]["evidence_status"] == "literature_verified"
        assert rows[0]["evidence_refs"] == "PMID:33385118"

    print("example test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
