#!/usr/bin/env python3
import os, argparse, csv, gzip, json, shutil, subprocess, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from afdb_utils import (
    afdb_plddt_threshold,
    api_global_plddt,
    decompress_if_gzip,
    mean_plddt_from_pdb_text,
)


def require(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit("Set %s before running this script" % name)
    return value

def get_env_or(name, default):
    return os.environ.get(name) or default

ROOT = Path(require("STRUCTURE_PRED_ROOT"))
MODELLER_ENV = get_env_or("STRUCTURE_PRED_MODELLER_ENV", "meta")
HOMOLOGY = ROOT / "homology_new/homology_pending_pdb_only.tsv"
QMAP = ROOT / "queries/query_map.tsv"
ALL_FASTA = ROOT / "queries/all.faa"
PDB_TEMPLATE_DIR = ROOT / "homology_templates_pdb"
AFDB_TEMPLATE_DIR = ROOT / "homology_templates_afdb"
WORK = ROOT / "homology_work"
LOG_DIR = ROOT / "homology_logs"
AFDB_MIN_PLDDT = afdb_plddt_threshold()

MODEL_TEMPLATE = r'''
from modeller import *
from modeller.automodel import automodel

log.verbose()
env = environ()
env.io.atom_files_directory = ["{template_dir}"]
aln = alignment(env)
mdl = model(env, file="{template_stem}", model_segment=("FIRST:{chain}", "LAST:{chain}"))
aln.append_model(mdl, align_codes="{template_code}", atom_files="{template_filename}")
aln.append(file="{query_pir}", align_codes="all")
aln.align2d()
aln.write(file="{ali_file}")

a = automodel(env, alnfile="{ali_file}", knowns="{template_code}", sequence="all")
a.starting_model = 1
a.ending_model = 1
a.make()
'''

def parse_fasta(path):
    seqs, name = {}, None
    for line in Path(path).read_text().splitlines():
        if line.startswith(">"):
            name = line[1:].split()[0]
            seqs[name] = []
        elif name:
            seqs[name].append(line.strip())
    return {k: "".join(v) for k, v in seqs.items()}

def build_query_map():
    m = {}
    with open(QMAP) as f:
        for line in f:
            fields = line.rstrip("\n").split("\t")
            if len(fields) >= 3:
                m[fields[2]] = fields[0]
    return m


def is_404(exc):
    return getattr(exc, "code", None) in (404, 403, 400)

def fetch_url(url, out_path, desc, attempts=4):
    if out_path.exists() and out_path.stat().st_size > 1000:
        return True, ""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    last = ""
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HOMD-modeling/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            if not data.startswith((b"ATOM", b"HEADER", b"CRYST1", b"data_", b"loop_", b"#")):
                raise RuntimeError(f"unexpected payload for {desc}")
            tmp = out_path.with_suffix(".pdb.tmp")
            tmp.write_bytes(data)
            shutil.move(str(tmp), out_path)
            return True, ""
        except Exception as exc:
            last = str(exc)
            if is_404(exc):
                break
            time.sleep(min(30, 2 ** i))
    return False, last

def fetch_template(template, source):
    if source == "PDB_HOMOLOGY_TEMPLATE":
        pdb_id = template.split("_")[0]
        chain = template.split("_")[1] if "_" in template else "A"
        # Prefer PDB format, fall back to mmCIF for mmCIF-only entries.
        pdb_path = PDB_TEMPLATE_DIR / f"{pdb_id}.pdb"
        ok, err = fetch_url(f"https://files.rcsb.org/download/{pdb_id}.pdb", pdb_path, pdb_id, attempts=4)
        if ok:
            return True, "", pdb_path, pdb_id, chain, pdb_path.name
        if "404" not in err:
            return False, err, pdb_path, pdb_id, chain, pdb_path.name
        cif_path = PDB_TEMPLATE_DIR / f"{pdb_id}.cif"
        ok_cif, err_cif = fetch_url(f"https://files.rcsb.org/download/{pdb_id}.cif", cif_path, pdb_id, attempts=5)
        if ok_cif:
            return True, "", cif_path, pdb_id, chain, cif_path.name
        return False, f"PDB and CIF download failed: {err} / {err_cif}", cif_path, pdb_id, chain, cif_path.name
    # AFDB source; template like AF-A0A1F1LP39-F1 or AF-0000000008184908.
    entry = template
    entry = entry[len("AFDB:"):] if entry.startswith("AFDB:") else entry
    path = AFDB_TEMPLATE_DIR / f"{entry}.pdb"
    if path.exists() and path.stat().st_size > 1000:
        payload = decompress_if_gzip(path.read_bytes())
        cached_plddt = mean_plddt_from_pdb_text(payload.decode("utf-8", errors="ignore"))
        if cached_plddt is not None and cached_plddt < AFDB_MIN_PLDDT:
            return False, f"AFDB_TEMPLATE_LOW_PLDDT {cached_plddt:.3f}", path, entry, "A", entry
        return True, "", path, entry, "A", entry
    path.parent.mkdir(parents=True, exist_ok=True)
    api_id = entry
    try:
        req = urllib.request.Request(f"https://alphafold.ebi.ac.uk/api/prediction/{api_id}", headers={"User-Agent": "HOMD-modeling/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        pdb_url = data[0].get("pdbUrl", "") if data else ""
        metadata_plddt = api_global_plddt(data[0] if data else {})
        if metadata_plddt is not None and metadata_plddt < AFDB_MIN_PLDDT:
            return False, f"AFDB_TEMPLATE_LOW_PLDDT_API {metadata_plddt:.3f}", path, entry, "A", entry
        if not pdb_url:
            return False, "NO_PDB_URL", path, entry, "A", entry
    except Exception as exc:
        return False, f"AFDB_API_ERROR {exc}", path, entry, "A", entry
    ok, err = fetch_url(pdb_url, path, entry, attempts=5)
    if not ok:
        return False, f"AFDB_DOWNLOAD_ERROR {err}", path, entry, "A", entry
    # The API pdbUrl may be gzip for some release snapshots.
    if path.read_bytes().startswith(b"\x1f\x8b"):
        path.write_bytes(decompress_if_gzip(path.read_bytes()))
    downloaded_plddt = mean_plddt_from_pdb_text(path.read_text(errors="ignore"))
    if downloaded_plddt is None:
        path.unlink(missing_ok=True)
        return False, "AFDB_TEMPLATE_NO_PLDDT_EVIDENCE", path, entry, "A", entry
    if downloaded_plddt < AFDB_MIN_PLDDT:
        path.unlink(missing_ok=True)
        return False, f"AFDB_TEMPLATE_LOW_PLDDT {downloaded_plddt:.3f}", path, entry, "A", entry
    return True, "", path, entry, "A", entry


def model_one(row, query_map, seqs, lock, progress, log_handle):
    qid, protein_file, protein_id, status, source, template_id, quality, pident, qcov, scov, structure_path = row[:11]
    query_id = qid
    seq = seqs.get(query_id or "")
    if not query_id or not seq:
        with lock:
            progress["missing"] += 1
            log_handle.write("\t".join([qid, protein_id, template_id, "SKIP_MISSING_QUERY", "", ""]) + "\n")
            log_handle.flush()
        return
    out_dir = Path(protein_file).parent / "structure"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{protein_id}.pdb"
    if out_path.exists() and out_path.stat().st_size > 1000:
        with lock:
            progress["exists"] += 1
            log_handle.write("\t".join([qid, protein_id, template_id, "EXISTS", str(out_path), ""]) + "\n")
            log_handle.flush()
        return
    ok_t, err_t, tpl_path, template_code, chain, template_filename = fetch_template(template_id, source)
    if not ok_t:
        with lock:
            progress["failed_template"] += 1
            log_handle.write("\t".join([qid, protein_id, template_id, "ERROR_TEMPLATE", "", err_t]) + "\n")
            log_handle.flush()
        return
    job_dir = WORK / qid
    job_dir.mkdir(parents=True, exist_ok=True)
    ali_file = job_dir / "model.ali"
    out_model = job_dir / "all.B99990001.pdb"
    job_query_pir = job_dir / "query.pir"
    with job_query_pir.open("w") as f:
        f.write(f">P1;all\nsequence:all:::::::0.00: 0.00\n{seq}*\n")
    py = job_dir / "mod.py"
    py.write_text(MODEL_TEMPLATE.format(
        template_dir=tpl_path.parent,
        template_stem=tpl_path.stem,
        template_code=template_code,
        template_filename=tpl_path.name,
        chain=chain,
        ali_file=ali_file,
        query_pir=job_query_pir,
        seq=seq,
    ))
    cp = subprocess.run(
        ["conda", "run", "-n", MODELLER_ENV, "python", str(py)],
        cwd=str(job_dir), capture_output=True, text=True,
        timeout=3600,
    )
    if cp.returncode != 0:
        err = (cp.stderr or cp.stdout)[-800:].replace("\n", " ")
        with lock:
            progress["failed_model"] += 1
            log_handle.write("\t".join([qid, protein_id, template_id, "ERROR_MODEL", "", err]) + "\n")
            log_handle.flush()
        return
    if not out_model.exists():
        with lock:
            progress["failed_model"] += 1
            log_handle.write("\t".join([qid, protein_id, template_id, "ERROR_OUTPUT", "", "model pdb not produced"]) + "\n")
            log_handle.flush()
        return
    if out_path.exists() and out_path.stat().st_size > 1000:
        with lock:
            progress["exists"] += 1
            log_handle.write("\t".join([qid, protein_id, template_id, "EXISTS_RACE", str(out_path), ""]) + "\n")
            log_handle.flush()
        out_model.unlink(missing_ok=True)
        return
    shutil.move(str(out_model), out_path)
    with lock:
        progress["saved"] += 1
        log_handle.write("\t".join([qid, protein_id, template_id, "SAVED", str(out_path), ""]) + "\n")
        log_handle.flush()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--from-index", type=int, default=0)
    ap.add_argument("--manifest", default=str(HOMOLOGY))
    args = ap.parse_args()

    rows = []
    with open(args.manifest) as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            rows.append([row["query_id"], row["protein_file"], row["protein_id"], row.get("status", ""),
                         row.get("source", ""), row.get("template_id", ""), row.get("quality", ""),
                         row.get("pident", ""), row.get("qcovhsp", ""), row.get("scovhsp", ""), row.get("structure_path", "")])
    rows.sort()
    if args.from_index:
        rows = rows[args.from_index:]
    if args.limit:
        rows = rows[:args.limit]

    query_map = build_query_map()
    seqs = parse_fasta(ALL_FASTA)
    print("rows", len(rows), "query_map", len(query_map), "seqs", len(seqs), flush=True)
    progress = {"saved":0, "exists":0, "missing":0, "failed_template":0, "failed_model":0}
    lock = threading.Lock()
    log_dir = LOG_DIR; log_dir.mkdir(parents=True, exist_ok=True)
    tag = Path(args.manifest).stem.replace("homology_pending_", "")
    log_path = log_dir / f"homology_modeling_v2_{tag}_from{args.from_index}.log"
    with log_path.open("w") as log_handle:
        with ThreadPoolExecutor(max_workers=args.threads) as ex:
            futs = [ex.submit(model_one, row, query_map, seqs, lock, progress, log_handle) for row in rows]
            done = 0
            for f in as_completed(futs):
                f.result()
                done += 1
                if done % 20 == 0 or done == len(rows):
                    print(f"{done}/{len(rows)} {progress}", flush=True)
                    # save checkpoint
                    (log_dir / f"checkpoint_{args.from_index}_{done}.tsv").write_text("ok\n")
    print("FINAL", progress, flush=True)

if __name__ == "__main__":
    main()
