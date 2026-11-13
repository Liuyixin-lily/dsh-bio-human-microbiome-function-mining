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
        assert {d["id"] for d in domains} >= {"skin", "gut"}

        # natural-language keyword search must resolve a user phrase to a process
        hits = json.loads(
            subprocess.run(
                [sys.executable, str(browse), "--search", "油脂分泌", "--json"],
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
                [sys.executable, str(browse), "--list-taxa", "skin", "--json"],
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
                [sys.executable, str(browse), "--search", "Cutibacterium acnes", "--json"],
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
        assert {"Staphylococcus epidermidis", "Akkermansia muciniphila"} <= merged_names

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
        assert card["library_version"] == "1.0.0"
        assert card["ec"] == "3.1.4.12"
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
        assert len(rows) >= 20
        assert {"skin", "gut"} <= {row["domain_id"] for row in rows}
        # the library is a curated prior: nothing may claim to be literature-verified yet
        assert all(row["evidence_status"] == "curated_prior" for row in rows)
        assert all(not row["evidence_refs"] for row in rows)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        resolver = SCRIPTS / "resolve_target_intent.py"
        builder = SCRIPTS / "build_library_domain.py"
        browse = SCRIPTS / "browse_target_library.py"

        def route(query: str) -> dict:
            return json.loads(
                subprocess.run(
                    [sys.executable, str(resolver), "--query", query, "--json"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
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
        covered = route("我关注头皮屑")
        assert covered["route"]["entry"] == "B"
        assert covered["library_coverage"]["hit_count"] >= 1

        # an uncovered body site must escalate, and must not be answered with an
        # off-site library hit
        oral = route("口腔牙周炎相关菌有哪些酶值得看")
        assert oral["detected"]["source_ids"] == ["oral"]
        assert oral["route"]["entry"] == "escalate"
        assert oral["library_coverage"]["hit_count"] == 0
        assert oral["route"]["literature_search_terms"]
        assert any("run_literature_search.sh" in s["command"] for s in oral["route"]["steps"])

        # a vaginal question must not be answered by the skin acidification process
        vaginal = route("阴道菌群和乳酸杆菌")
        assert vaginal["route"]["entry"] == "escalate"
        assert vaginal["library_coverage"]["hit_count"] == 0
        assert vaginal["library_coverage"]["other_site_hit_count"] >= 1

        # a taxon-only question must not crash and must not claim library coverage
        taxon_route = route("Akkermansia muciniphila")
        assert taxon_route["detected"]["taxa"] == ["Akkermansia"]
        assert taxon_route["route"]["entry"] == "A"
        assert taxon_route["library_coverage"]["hit_count"] == 0
        assert taxon_route["library_coverage"]["taxon_hits"]

        # a word that merely appears in prose is not coverage
        immunity = route("我想研究肠道菌对免疫的影响")
        assert immunity["route"]["entry"] == "escalate"
        assert immunity["library_coverage"]["hit_count"] == 0

        # a phenotype the library really does cover resolves to the exact process
        butyrate = route("粪便 丁酸")
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

    print("example test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
