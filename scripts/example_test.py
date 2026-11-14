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
        assert [d["id"] for d in domains] == ["skin"]
        assert domains[0]["processes"] and len(domains[0]["processes"]) == 1
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
        # the shipped library is exactly the evidenced set
        assert len(rows) == 1
        assert {row["domain_id"] for row in rows} == {"skin"}
        assert all(row["evidence_status"] == "literature_verified" for row in rows)
        assert all(row["evidence_refs"] for row in rows)

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
        assert "已隔离" not in gated

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
        skeleton["tools"]["diamond"] = "/bin/echo"                    # runs, prints no version
        skeleton["tools"]["cd-hit"] = "definitely-not-installed-xyz"  # missing
        skeleton["tools"]["fedkea"] = {
            "path": "/bin/echo",
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
        assert card["tools"]["diamond"]["status"] == "unverified"
        assert card["tools"]["cd-hit"]["status"] == "missing"
        # a declared env path that does not exist must not be called ready
        assert card["tools"]["fedkea"]["status"] == "unverified"
        assert card["tools"]["bakta"]["status"] == "not_provided"
        report = report_path.read_text(encoding="utf-8")
        assert "UNVERIFIED" in report and "MISSING" in report
        assert "不要把“路径存在”当成“可以跑”" in report

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
        env = {
            "execution": {"allow_local_execution": True, "workdir": str(tmp)},
            "tools": {
                "diamond": "/usr/bin/python3",       # prints "Python 3.x" -> ready
                "cd-hit": "/bin/echo",               # echoes the flag -> unverified
                "usalign": None,
                "deer": None,
                "fedkea": {"path": "/usr/bin/python3",
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
        assert fragment["tools"]["sequence_screen"]["executable"] == "/usr/bin/python3"
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

    print("example test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
