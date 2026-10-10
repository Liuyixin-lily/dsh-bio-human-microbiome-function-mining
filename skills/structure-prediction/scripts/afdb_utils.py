#!/usr/bin/env python3
"""Shared AFDB download-quality validation helpers."""

import gzip
import os


def afdb_plddt_threshold():
    """Return the AFDB quality gate. The default is mean pLDDT >= 60."""
    value = float(os.environ.get("STRUCTURE_PRED_AFDB_MIN_PLDDT", "60.0"))
    if not 0 <= value <= 100:
        raise ValueError("STRUCTURE_PRED_AFDB_MIN_PLDDT must be in the range 0-100")
    return value


def api_global_plddt(record):
    """Read an AFDB API record's global pLDDT, normalizing a 0-1 scale if needed."""
    if not record:
        return None
    try:
        value = float(record["globalMetricValue"])
    except (KeyError, TypeError, ValueError):
        return None
    if 0 <= value <= 1:
        value *= 100.0
    return value


def decompress_if_gzip(raw):
    return gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw


def mean_plddt_from_pdb_text(text):
    """Return mean CA B-factor pLDDT, or None when no CA pLDDT values exist."""
    values = []
    for line in text.splitlines():
        # Standard PDB columns: atom name 13-16, B-factor 61-66.
        if line.startswith("ATOM ") and line[12:16] == " CA ":
            try:
                values.append(float(line[60:66]))
            except ValueError:
                continue
    return sum(values) / len(values) if values else None


def evaluate_afdb_payload(raw, metadata_plddt, threshold):
    """Validate an AFDB coordinate payload against the AFDB pLDDT gate."""
    if metadata_plddt is not None and metadata_plddt < threshold:
        return False, "LOW_PLDDT_API", float(metadata_plddt)

    raw = decompress_if_gzip(raw)
    if not raw.startswith((b"HEADER", b"ATOM", b"CRYST1", b"MODEL")):
        return False, "BAD_CONTENT", None

    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:  # unnecessary in modern Python, but keeps the contract explicit
        return False, "BAD_CONTENT", None

    structure_plddt = mean_plddt_from_pdb_text(text)
    if structure_plddt is None:
        return False, "NO_PLDDT_EVIDENCE", None
    if structure_plddt < threshold:
        return False, "LOW_PLDDT", structure_plddt
    return True, "PASS", structure_plddt

