"""Batch encode/decode with VTM and record one manifest per run.

A job is (sequence, prediction structure, QP, variant). For every job the runner:

1. encodes with EncoderApp and the variant's extra arguments,
2. decodes the bitstream with the unmodified DecoderApp,
3. checks MD5(encoder reconstruction) == MD5(decoder output) — a mismatch fails the job,
4. records bitstream SHA-256, actual bits and kbps in ``<out>/<job_id>/manifest.json``.

The task metric is always computed on the **decoder** output. Jobs whose manifest says ``"status": "ok"`` are
skipped, so an interrupted batch can be resumed.

CLI::

    python -m vcm.jobs --sequences configs/sequences.csv --variants configs/variants.yaml \
        --structure ldp --qps 22 27 32 37 --vtm third_party/VTM --out results/b0 [--split report] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shlex
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

STRUCTURE_CFGS = {
    "ai": "cfg/encoder_intra_vtm.cfg",
    "ldp": "cfg/encoder_lowdelay_P_vtm.cfg",
    "ra": "cfg/encoder_randomaccess_vtm.cfg",
}


@dataclass(frozen=True)
class Sequence:
    name: str
    path: str
    width: int
    height: int
    fps: float
    frames: int
    bitdepth: int = 8
    split: str = "report"
    dataset: str = ""
    annotations: str = ""      # COCO-format ground truth for this sequence (detection)


@dataclass(frozen=True)
class Job:
    sequence: Sequence
    structure: str
    qp: int
    variant: str
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    @property
    def job_id(self) -> str:
        return f"{self.sequence.name}__{self.structure}__qp{self.qp}__{self.variant}"


def load_sequences(path: str | Path) -> list[Sequence]:
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        out.append(Sequence(name=r["name"], path=r["path"], width=int(r["width"]), height=int(r["height"]),
                            fps=float(r["fps"]), frames=int(r["frames"]), bitdepth=int(r.get("bitdepth") or 8),
                            split=r.get("split") or "report", dataset=r.get("dataset") or "",
                            annotations=r.get("annotations") or ""))
    names = [s.name for s in out]
    if len(names) != len(set(names)):
        raise ValueError("duplicate sequence names in sequence table")
    return out


def load_variants(path: str | Path) -> dict[str, tuple[str, ...]]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    variants = data.get("variants", data)
    return {name: tuple(spec.get("args", []) if isinstance(spec, dict) else spec or [])
            for name, spec in variants.items()}


def plan(sequences, structures, qps, variants: dict[str, tuple[str, ...]], split: str | None = None) -> list[Job]:
    return [Job(s, st, int(q), v, args)
            for s in sequences if split is None or s.split == split
            for st in structures for q in qps for v, args in variants.items()]


def encoder_cmd(job: Job, enc: Path, vtm_root: Path, out: Path) -> list[str]:
    s = job.sequence
    return [str(enc), "-c", str(vtm_root / STRUCTURE_CFGS[job.structure]),
            "-i", s.path, "-wdt", str(s.width), "-hgt", str(s.height),
            "-fr", str(int(round(s.fps))), "-f", str(s.frames), "-q", str(job.qp),
            f"--InputBitDepth={s.bitdepth}", f"--OutputBitDepth={s.bitdepth}",
            "-b", str(out / "str.bin"), "-o", str(out / "rec_enc.yuv"), *job.extra_args]


def decoder_cmd(job: Job, dec: Path, out: Path) -> list[str]:
    return [str(dec), "-b", str(out / "str.bin"), "-o", str(out / "rec_dec.yuv"), "-d", str(job.sequence.bitdepth)]


def _digest(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_binary(vtm_root: Path, stem: str) -> Path:
    for p in sorted((vtm_root / "bin").rglob(f"{stem}*")):
        if p.is_file() and p.stat().st_mode & 0o111:
            return p
    raise FileNotFoundError(f"{stem} not found under {vtm_root / 'bin'}; build VTM first")


def run_job(job: Job, enc: Path, dec: Path, vtm_root: Path, out_root: Path, provenance: dict | None = None,
            keep_encoder_recon: bool = False) -> dict:
    out = out_root / job.job_id
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        if old.get("status") == "ok":
            return old
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"job_id": job.job_id, "job": asdict(job), "provenance": provenance or {}, "status": "running"}

    t0 = time.time()
    ecmd = encoder_cmd(job, enc, vtm_root, out)
    with open(out / "enc.log", "w") as log:
        subprocess.run(ecmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    t1 = time.time()
    dcmd = decoder_cmd(job, dec, out)
    with open(out / "dec.log", "w") as log:
        subprocess.run(dcmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    t2 = time.time()

    bits = (out / "str.bin").stat().st_size * 8
    md5_enc = _digest(out / "rec_enc.yuv", "md5")
    md5_dec = _digest(out / "rec_dec.yuv", "md5")
    manifest.update({
        "encoder_cmd": shlex.join(ecmd),
        "decoder_cmd": shlex.join(dcmd),
        "bits": bits,
        "kbps": bits / (job.sequence.frames / job.sequence.fps) / 1000.0,
        "bitstream_sha256": _digest(out / "str.bin", "sha256"),
        "recon_md5_encoder": md5_enc,
        "recon_md5_decoder": md5_dec,
        "encode_seconds": round(t1 - t0, 3),
        "decode_seconds": round(t2 - t1, 3),
        "status": "ok" if md5_enc == md5_dec else "decoder_mismatch",
    })
    if not keep_encoder_recon and md5_enc == md5_dec:
        (out / "rec_enc.yuv").unlink()
    manifest_path.write_text(json.dumps(manifest, indent=2))
    if manifest["status"] != "ok":
        raise RuntimeError(f"{job.job_id}: decoder output differs from encoder reconstruction")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sequences", required=True)
    ap.add_argument("--variants", required=True)
    ap.add_argument("--structure", nargs="+", choices=sorted(STRUCTURE_CFGS), required=True)
    ap.add_argument("--qps", nargs="+", type=int, required=True)
    ap.add_argument("--vtm", default="third_party/VTM")
    ap.add_argument("--out", required=True)
    ap.add_argument("--split", choices=["tune", "report"])
    ap.add_argument("--only-variants", nargs="*")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    variants = load_variants(a.variants)
    if a.only_variants:
        variants = {k: v for k, v in variants.items() if k in a.only_variants}
    jobs = plan(load_sequences(a.sequences), a.structure, a.qps, variants, a.split)
    vtm, out = Path(a.vtm), Path(a.out)
    if a.dry_run:
        for j in jobs:
            print(shlex.join(encoder_cmd(j, Path("EncoderApp"), vtm, out / j.job_id)))
        print(f"# {len(jobs)} jobs")
        return 0

    enc, dec = find_binary(vtm, "EncoderApp"), find_binary(vtm, "DecoderApp")
    commit_file = Path("third_party/VTM_COMMIT")
    provenance = {"vtm_commit": commit_file.read_text().strip() if commit_file.exists() else "unknown",
                  "variants_file": a.variants, "sequences_file": a.sequences}
    failures = 0
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = {pool.submit(run_job, j, enc, dec, vtm, out, provenance): j for j in jobs}
        for f, j in futures.items():
            try:
                m = f.result()
                print(f"ok   {j.job_id}  {m['kbps']:.2f} kbps")
            except Exception as exc:  # report and continue with the rest of the batch
                failures += 1
                print(f"FAIL {j.job_id}: {exc}")
    print(f"# done: {len(jobs) - failures} ok, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
