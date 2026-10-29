"""Batch encode/decode with VTM and record one manifest per run.

A job is (sequence, prediction structure, QP, variant). For every job the runner:

1. checks that every file/directory referenced by a hook option exists (fail before encoding),
2. encodes with EncoderApp and the variant's extra arguments,
3. decodes the bitstream with the unmodified DecoderApp,
4. checks MD5(encoder reconstruction) == MD5(decoder output) and that the decoded file holds the expected number
   of coded frames — any mismatch fails the job,
5. records bits, kbps, hashes, the temporal subsampling (``frame_step``) and a **fingerprint** of everything that
   determines the result in ``<out>/<job_id>/manifest.json``.

Caching: an existing manifest is reused only if its status is ``ok`` **and** its fingerprint equals the current one
(command, cfg content, encoder/decoder binaries, full SHA-256 of the input, hook input files, VTM tree). Hashes are
memoised on disk by (path, size, mtime, inode); ``VCM_HASH_CACHE=off`` forces re-hashing (use it for report runs). A stale result is
re-run (or rejected with ``--strict-cache``).

Variant arguments may use placeholders resolved per job: ``{sequence}``, ``{structure}``, ``{qp}``, ``{variant}``,
``{dataset}``; e.g. ``--VCMAlfWeightDir=results/weights/{sequence}``.

Frame alignment: decoded frame k is source frame ``frame_offset + k * frame_step``; both come from the cfg
(``FrameSkip``, ``TemporalSubsampleRatio``) unless overridden in the variant arguments (``--FrameSkip``/``-fs``,
``--TemporalSubsampleRatio``/``-ts``). ``kbps`` is computed over the
duration of the *source* frames read, as VTM does.

CLI::

    python -m vcm.jobs --sequences configs/sequences.csv --variants configs/variants.yaml \
        --structure ldp --qps 22 27 32 37 --vtm third_party/VTM --out results/b0 [--split report] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import functools
import hashlib
import json
import os
import re
import shlex
import subprocess
import threading
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
HOOK_PATH_OPTIONS = ("--VCMQpOffsetFile", "--VCMAlfWeightDir", "--VCMAlfExternalFile")   # inputs (must exist)
HOOK_OUTPUT_OPTIONS = ("--VCMTraceFile", "--VCMAlfDumpDir")                                # outputs
FINGERPRINT_VERSION = 2          # v2: full-content input hash


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


@dataclass(frozen=True)
class VariantSpec:
    args: tuple[str, ...] = ()
    branch: str = "anchor"                 # "A", "B" or "anchor"; A and B are never run in one invocation
    structures: tuple[str, ...] = ()       # empty = all structures
    same_bitstream_as: str = ""            # output-only hooks: bitstream must equal this variant's, byte for byte


def load_variant_specs(path: str | Path) -> dict[str, VariantSpec]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    variants = data.get("variants", data)
    out = {}
    for name, spec in variants.items():
        if not isinstance(spec, dict):
            spec = {"args": spec or []}
        unknown = set(spec) - {"args", "branch", "structures", "same_bitstream_as", "note"}
        if unknown:
            raise ValueError(f"variant {name!r}: unknown keys {sorted(unknown)}")
        branch = str(spec.get("branch", "anchor"))
        if branch not in ("A", "B", "anchor"):
            raise ValueError(f"variant {name!r}: branch must be A, B or anchor")
        out[name] = VariantSpec(tuple(spec.get("args", [])), branch, tuple(spec.get("structures", [])),
                                spec.get("same_bitstream_as", ""))
    for name, v in out.items():
        if v.same_bitstream_as and v.same_bitstream_as not in out:
            raise ValueError(f"variant {name!r}: same_bitstream_as refers to unknown variant")
    return out


def load_variants(path: str | Path) -> dict[str, tuple[str, ...]]:
    return {k: v.args for k, v in load_variant_specs(path).items()}


def check_branch_separation(specs: dict[str, VariantSpec]) -> None:
    """docs/CLAUDE.md: branch A (QP/lambda) and branch B (ALF) interventions are never combined in one run."""
    branches = {v.branch for v in specs.values()} - {"anchor"}
    if len(branches) > 1:
        raise ValueError(f"variants of branches {sorted(branches)} selected together; run them separately "
                         f"(--only-variants): {sorted(specs)}")


def resolve_args(args: tuple[str, ...], seq: Sequence, structure: str, qp: int, variant: str) -> tuple[str, ...]:
    values = {"sequence": seq.name, "structure": structure, "qp": qp, "variant": variant, "dataset": seq.dataset}
    try:
        return tuple(a.format(**values) for a in args)
    except KeyError as exc:
        raise ValueError(f"variant {variant!r}: unknown placeholder {exc} in {args}") from exc


def plan(sequences, structures, qps, variants: dict, split: str | None = None) -> list[Job]:
    """``variants``: name -> args tuple or VariantSpec (a spec's ``structures`` restricts where it runs)."""
    specs = {k: v if isinstance(v, VariantSpec) else VariantSpec(tuple(v)) for k, v in variants.items()}
    return [Job(s, st, int(q), v, resolve_args(sp.args, s, st, int(q), v))
            for s in sequences if split is None or s.split == split
            for st in structures for q in qps for v, sp in specs.items()
            if not sp.structures or st in sp.structures]


def _option_values(args, names) -> list[str]:
    out = []
    for a in args:
        for n in names:
            if a.startswith(n + "="):
                out.append(a.split("=", 1)[1])
    return out


def check_hook_inputs(job: Job) -> None:
    missing = [p for p in _option_values(job.extra_args, HOOK_PATH_OPTIONS) if not Path(p).exists()]
    if missing:
        raise FileNotFoundError(f"{job.job_id}: hook input(s) not found: {missing}")


def _arg_value(args: tuple[str, ...], long: str, short: str) -> str | None:
    """Last value of a VTM option given as ``--Long=v``, ``--Long v``, ``-short v`` or ``-short=v``."""
    val = None
    for i, a in enumerate(args):
        for flag in (f"--{long}", f"-{short}"):
            if a == flag and i + 1 < len(args):
                val = args[i + 1]
            elif a.startswith(flag + "="):
                val = a.split("=", 1)[1]
    return val


def _cfg_value(vtm_root: Path, structure: str, key: str) -> str | None:
    cfg = vtm_root / STRUCTURE_CFGS[structure]
    if cfg.exists():
        m = re.search(rf"^\s*{key}\s*:\s*(\S+)", cfg.read_text(), re.MULTILINE)
        if m:
            return m.group(1)
    return None


def frame_step(job: Job, vtm_root: Path) -> int:
    """Encoder temporal subsampling: decoded frame k is source frame ``frame_offset + k * frame_step``."""
    v = _arg_value(job.extra_args, "TemporalSubsampleRatio", "ts") or \
        _cfg_value(vtm_root, job.structure, "TemporalSubsampleRatio")
    return int(v) if v else 1


def frame_offset(job: Job, vtm_root: Path) -> int:
    v = _arg_value(job.extra_args, "FrameSkip", "fs") or _cfg_value(vtm_root, job.structure, "FrameSkip")
    return int(v) if v else 0


def coded_frames(job: Job, step: int) -> int:
    """VTM: FramesToBeEncoded = ceil(-f / TemporalSubsampleRatio) (EncAppCfg.cpp)."""
    return -(-job.sequence.frames // step)


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


_HASH_LOCK = threading.Lock()


def _hash_cache_path() -> Path | None:
    """Persistent SHA-256 cache (VCM_HASH_CACHE=off disables it, e.g. for the final report run)."""
    v = os.environ.get("VCM_HASH_CACHE", "")
    if v.lower() == "off":
        return None
    return Path(v) if v else Path.home() / ".cache" / "vcm-vvc-screening" / "sha256.json"


@functools.lru_cache(maxsize=256)
def _file_sha(path: str, size: int, mtime_ns: int, inode: int) -> str:
    """Full-content SHA-256, memoised in memory and on disk by (path, size, mtime, inode). A file rewritten in
    place with its mtime restored would be missed by the disk cache; disable it for the report run."""
    key = f"{path}|{size}|{mtime_ns}|{inode}"
    cache_path = _hash_cache_path()
    if cache_path is not None and cache_path.exists():
        with _HASH_LOCK:
            try:
                hit = json.loads(cache_path.read_text()).get(key)
            except (OSError, ValueError):
                hit = None
        if hit:
            return hit
    digest = _digest(Path(path), "sha256")
    if cache_path is not None:
        with _HASH_LOCK:
            try:
                data = json.loads(cache_path.read_text()) if cache_path.exists() else {}
            except (OSError, ValueError):
                data = {}
            data[key] = digest
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, cache_path)
    return digest


def _sha_file(p: Path) -> str:
    st = p.stat()
    return _file_sha(str(p.resolve()), st.st_size, st.st_mtime_ns, st.st_ino)


def _path_sha(p: Path) -> str:
    if p.is_dir():
        h = hashlib.sha256()
        for f in sorted(x for x in p.rglob("*") if x.is_file()):
            h.update(str(f.relative_to(p)).encode())
            h.update(_sha_file(f).encode())
        return h.hexdigest()
    return _sha_file(p)


def fingerprint(job: Job, enc: Path, dec: Path, vtm_root: Path, vtm_commit: str = "") -> dict:
    cmd = encoder_cmd(job, Path("ENC"), vtm_root, Path("OUT"))
    fp = {
        "version": FINGERPRINT_VERSION,
        "encoder_cmd": shlex.join(cmd[1:]),
        "cfg_sha256": _sha_file(vtm_root / STRUCTURE_CFGS[job.structure]),
        "encoder_sha256": _sha_file(enc),
        "decoder_sha256": _sha_file(dec),
        "input_sha256": _sha_file(Path(job.sequence.path)),          # full content, every byte
        "hook_inputs": {v: _path_sha(Path(v)) for v in _option_values(job.extra_args, HOOK_PATH_OPTIONS)},
        "vtm_commit": vtm_commit,
    }
    fp["hash"] = hashlib.sha256(json.dumps(fp, sort_keys=True).encode()).hexdigest()
    return fp


def find_binary(vtm_root: Path, stem: str) -> Path:
    for p in sorted((vtm_root / "bin").rglob(f"{stem}*")):
        if p.is_file() and p.stat().st_mode & 0o111:
            return p
    raise FileNotFoundError(f"{stem} not found under {vtm_root / 'bin'}; build VTM first")


def vtm_provenance(root: Path = Path("third_party")) -> dict:
    """Commit, tree and patch hash written by scripts/fetch_vtm.sh."""
    out = {"vtm_commit": "unknown"}
    if (root / "VTM_COMMIT").exists():
        out["vtm_commit"] = (root / "VTM_COMMIT").read_text().strip()
    if (root / "VTM_PROVENANCE").exists():
        for line in (root / "VTM_PROVENANCE").read_text().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                out[f"vtm_{k.strip()}"] = v.strip()
    return out


class StaleCacheError(RuntimeError):
    pass


def run_job(job: Job, enc: Path, dec: Path, vtm_root: Path, out_root: Path, provenance: dict | None = None,
            keep_encoder_recon: bool = False, strict_cache: bool = False) -> dict:
    out = out_root / job.job_id
    manifest_path = out / "manifest.json"
    check_hook_inputs(job)
    prov = provenance or {}
    # the source tree identifies the encoder independently of how it was obtained (branch clone or patch)
    fp = fingerprint(job, enc, dec, vtm_root, prov.get("vtm_tree") or prov.get("vtm_commit", ""))
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        if old.get("status") == "ok" and old.get("fingerprint", {}).get("hash") == fp["hash"]:
            return old
        if old.get("status") == "ok" and strict_cache:
            raise StaleCacheError(f"{job.job_id}: cached result has a different fingerprint")
    out.mkdir(parents=True, exist_ok=True)
    for opt in HOOK_OUTPUT_OPTIONS:                    # VTM writes into these but does not create them
        for v in _option_values(job.extra_args, (opt,)):
            (Path(v) if opt.endswith("Dir") else Path(v).parent).mkdir(parents=True, exist_ok=True)
    for stale in ("task_metrics.json", "detections.json"):
        (out / stale).unlink(missing_ok=True)          # never pair new bitstreams with old metrics
    step = frame_step(job, vtm_root)
    manifest = {"job_id": job.job_id, "job": asdict(job), "provenance": provenance or {}, "fingerprint": fp,
                "frame_step": step, "frame_offset": frame_offset(job, vtm_root),
                "coded_frames": coded_frames(job, step), "status": "running"}

    t0 = time.time()
    ecmd = encoder_cmd(job, enc, vtm_root, out)
    with open(out / "enc.log", "w") as log:
        subprocess.run(ecmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    t1 = time.time()
    dcmd = decoder_cmd(job, dec, out)
    with open(out / "dec.log", "w") as log:
        subprocess.run(dcmd, stdout=log, stderr=subprocess.STDOUT, check=True)
    t2 = time.time()

    s = job.sequence
    frame_bytes = s.width * s.height * 3 // 2 * (1 if s.bitdepth == 8 else 2)
    decoded = os.path.getsize(out / "rec_dec.yuv") // frame_bytes
    bits = (out / "str.bin").stat().st_size * 8
    md5_enc = _digest(out / "rec_enc.yuv", "md5")
    md5_dec = _digest(out / "rec_dec.yuv", "md5")
    status = "ok"
    if md5_enc != md5_dec:
        status = "decoder_mismatch"
    elif decoded != manifest["coded_frames"]:
        status = "frame_count_mismatch"
    manifest.update({
        "encoder_cmd": shlex.join(ecmd),
        "decoder_cmd": shlex.join(dcmd),
        "decoded_frames": decoded,
        "bits": bits,
        "kbps": bits / (s.frames / s.fps) / 1000.0,
        "bitstream_sha256": _digest(out / "str.bin", "sha256"),
        "recon_md5_encoder": md5_enc,
        "recon_md5_decoder": md5_dec,
        "encode_seconds": round(t1 - t0, 3),
        "decode_seconds": round(t2 - t1, 3),
        "status": status,
    })
    if not keep_encoder_recon and md5_enc == md5_dec:
        (out / "rec_enc.yuv").unlink()
    manifest_path.write_text(json.dumps(manifest, indent=2))
    if status == "decoder_mismatch":
        raise RuntimeError(f"{job.job_id}: decoder output differs from encoder reconstruction")
    if status == "frame_count_mismatch":
        raise RuntimeError(f"{job.job_id}: decoded {decoded} frames, expected {manifest['coded_frames']}")
    return manifest


def with_references(jobs: list[Job], specs: dict[str, VariantSpec]) -> list[Job]:
    """Add the reference job of every output-only variant (``same_bitstream_as``) that is not already planned, so
    the bitstream-identity check can never be skipped by running the output-only variant on its own."""
    have = {j.job_id for j in jobs}
    out = list(jobs)
    for j in jobs:
        ref = specs.get(j.variant, VariantSpec()).same_bitstream_as
        if not ref:
            continue
        r = Job(j.sequence, j.structure, j.qp, ref, resolve_args(specs[ref].args, j.sequence, j.structure, j.qp, ref))
        if r.job_id not in have:
            have.add(r.job_id)
            out.append(r)
    return out


def check_same_bitstreams(jobs: list[Job], specs: dict[str, VariantSpec], done: dict[str, dict]) -> list[str]:
    """Variants that only add output hooks (trace, dump) must not change the bitstream. A missing or failed
    reference job is itself a failure (the check could not be made)."""
    bad = []
    for j in jobs:
        ref = specs.get(j.variant, VariantSpec()).same_bitstream_as
        if not ref or j.job_id not in done:
            continue
        ref_id = Job(j.sequence, j.structure, j.qp, ref).job_id
        if ref_id not in done:
            bad.append(j.job_id)
            print(f"FAIL {j.job_id}: reference {ref_id} unavailable, bitstream identity not verified")
        elif done[ref_id]["bitstream_sha256"] != done[j.job_id]["bitstream_sha256"]:
            bad.append(j.job_id)
            print(f"FAIL {j.job_id}: bitstream differs from {ref_id} (output-only hook changed the encoding)")
    return bad


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
    ap.add_argument("--strict-cache", action="store_true", help="fail instead of re-running stale cached jobs")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    all_specs = variants = load_variant_specs(a.variants)
    if a.only_variants:
        unknown = set(a.only_variants) - set(variants)
        if unknown:
            raise SystemExit(f"unknown variants: {sorted(unknown)}")
        variants = {k: v for k, v in variants.items() if k in a.only_variants}
    jobs = with_references(plan(load_sequences(a.sequences), a.structure, a.qps, variants, a.split), all_specs)
    variants = {k: all_specs[k] for k in sorted({j.variant for j in jobs})}
    try:
        check_branch_separation(variants)
    except ValueError as exc:
        raise SystemExit(str(exc))
    vtm, out = Path(a.vtm), Path(a.out)
    if a.dry_run:
        for j in jobs:
            print(shlex.join(encoder_cmd(j, Path("EncoderApp"), vtm, out / j.job_id)))
        print(f"# {len(jobs)} jobs")
        return 0

    enc, dec = find_binary(vtm, "EncoderApp"), find_binary(vtm, "DecoderApp")
    for path in sorted({j.sequence.path for j in jobs}):     # hash each input once, before the parallel jobs
        _sha_file(Path(path))
    provenance = {**vtm_provenance(), "variants_file": a.variants, "sequences_file": a.sequences}
    failures = 0
    done: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = {pool.submit(run_job, j, enc, dec, vtm, out, provenance, False, a.strict_cache): j for j in jobs}
        for f, j in futures.items():
            try:
                m = f.result()
                done[j.job_id] = m
                print(f"ok   {j.job_id}  {m['kbps']:.2f} kbps")
            except Exception as exc:  # report and continue with the rest of the batch
                failures += 1
                print(f"FAIL {j.job_id}: {exc}")
    failures += len(check_same_bitstreams(jobs, variants, done))
    print(f"# done: {len(jobs) - failures} ok, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
