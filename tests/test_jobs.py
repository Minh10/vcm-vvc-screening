"""End-to-end test of the batch runner with fake encoder/decoder binaries."""

import json
import stat
import sys
from pathlib import Path

import pytest

from vcm.jobs import (Job, Sequence, StaleCacheError, check_hook_inputs, decoder_cmd, encoder_cmd, frame_offset,
                      frame_step, load_sequences, load_variants, plan, run_job)

# Fake encoder: honours TemporalSubsampleRatio from the cfg or -ts/--TemporalSubsampleRatio, like VTM.
FAKE_ENC = """#!{py}
import re, sys
a = sys.argv
src, bit, rec = a[a.index('-i') + 1], a[a.index('-b') + 1], a[a.index('-o') + 1]
w, h, n = int(a[a.index('-wdt') + 1]), int(a[a.index('-hgt') + 1]), int(a[a.index('-f') + 1])
m = re.search(r'TemporalSubsampleRatio\\s*:\\s*(\\d+)', open(a[a.index('-c') + 1]).read())
ts = int(m.group(1)) if m else 1
for x in a:
    if x.startswith('--TemporalSubsampleRatio='):
        ts = int(x.split('=')[1])
fb = w * h * 3 // 2
data = open(src, 'rb').read()
frames = [data[k * fb:(k + 1) * fb] for k in range(0, n, ts)]
open(rec, 'wb').write(b''.join(frames))
open(bit, 'wb').write(b'BS' + b''.join(frames))
"""

GOOD_DEC = """#!{py}
import sys
a = sys.argv
bit, out = a[a.index('-b') + 1], a[a.index('-o') + 1]
open(out, 'wb').write(open(bit, 'rb').read()[2:])
"""

BAD_DEC = """#!{py}
import sys
a = sys.argv
open(a[a.index('-o') + 1], 'wb').write(b'not the recon')
"""


def _script(path: Path, body: str) -> Path:
    path.write_text(body.format(py=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def setup(tmp_path):
    vtm = tmp_path / "VTM"
    (vtm / "bin").mkdir(parents=True)
    (vtm / "cfg").mkdir()
    (vtm / "cfg" / "encoder_lowdelay_P_vtm.cfg").write_text("IntraPeriod : -1\n")
    (vtm / "cfg" / "encoder_intra_vtm.cfg").write_text("IntraPeriod : 1\nTemporalSubsampleRatio : 8\n")
    enc = _script(vtm / "bin" / "EncoderAppStatic", FAKE_ENC)
    dec = _script(vtm / "bin" / "DecoderAppStatic", GOOD_DEC)
    yuv = tmp_path / "seq.yuv"
    yuv.write_bytes(bytes(range(256)) * 9)  # 2304 bytes = 2 frames of 32x24 @ 8 bit
    seq = Sequence("s1", str(yuv), 32, 24, 30.0, 2)
    return tmp_path, vtm, enc, dec, seq


def test_plan_filters_split_and_expands():
    a = Sequence("a", "a.yuv", 32, 24, 30, 2, split="tune")
    b = Sequence("b", "b.yuv", 32, 24, 30, 2, split="report")
    jobs = plan([a, b], ["ldp", "ai"], [22, 37], {"x": (), "y": ("--ALF=0",)}, split="report")
    assert len(jobs) == 2 * 2 * 2
    assert {j.sequence.name for j in jobs} == {"b"}
    assert jobs[0].job_id == "b__ldp__qp22__x"


def test_commands_contain_required_arguments(setup):
    tmp, vtm, enc, dec, seq = setup
    job = Job(seq, "ldp", 32, "alf_off", ("--ALF=0",))
    cmd = encoder_cmd(job, enc, vtm, tmp / "o")
    assert cmd[cmd.index("-q") + 1] == "32"
    assert cmd[-1] == "--ALF=0"
    assert cmd[cmd.index("-c") + 1].endswith("encoder_lowdelay_P_vtm.cfg")
    assert decoder_cmd(job, dec, tmp / "o")[-2:] == ["-d", "8"]


def test_run_job_ok_and_cached_by_fingerprint(setup):
    tmp, vtm, enc, dec, seq = setup
    job = Job(seq, "ldp", 32, "alf_default")
    m = run_job(job, enc, dec, vtm, tmp / "out")
    assert m["status"] == "ok"
    assert m["bits"] == (2304 + 2) * 8
    assert m["kbps"] == pytest.approx(m["bits"] / (2 / 30.0) / 1000)
    assert (m["frame_step"], m["coded_frames"], m["decoded_frames"]) == (1, 2, 2)
    assert not (tmp / "out" / job.job_id / "rec_enc.yuv").exists()
    saved = json.loads((tmp / "out" / job.job_id / "manifest.json").read_text())
    assert saved["recon_md5_encoder"] == saved["recon_md5_decoder"]
    assert saved["fingerprint"]["hash"] == m["fingerprint"]["hash"]
    log = tmp / "out" / job.job_id / "enc.log"
    stamp = log.stat().st_mtime_ns
    assert run_job(job, enc, dec, vtm, tmp / "out")["fingerprint"] == m["fingerprint"]
    assert log.stat().st_mtime_ns == stamp                      # same fingerprint -> cached, not re-encoded


@pytest.mark.parametrize("change", ["cfg", "input", "encoder", "commit"])
def test_stale_cache_is_rerun_or_rejected(setup, change):
    tmp, vtm, enc, dec, seq = setup
    job = Job(seq, "ldp", 32, "alf_default")
    first = run_job(job, enc, dec, vtm, tmp / "out", {"vtm_commit": "a"})
    (tmp / "out" / job.job_id / "task_metrics.json").write_text("{}")
    commit = "a"
    if change == "cfg":
        (vtm / "cfg" / "encoder_lowdelay_P_vtm.cfg").write_text("IntraPeriod : -1\nQP : 30\n")
    elif change == "input":
        Path(seq.path).write_bytes(bytes(reversed(range(256))) * 9)
    elif change == "encoder":
        enc.write_text(enc.read_text() + "\n# rebuilt\n")
    else:
        commit = "b"
    with pytest.raises(StaleCacheError):
        run_job(job, enc, dec, vtm, tmp / "out", {"vtm_commit": commit}, strict_cache=True)
    again = run_job(job, enc, dec, vtm, tmp / "out", {"vtm_commit": commit})
    assert again["fingerprint"]["hash"] != first["fingerprint"]["hash"]
    assert not (tmp / "out" / job.job_id / "task_metrics.json").exists()   # stale metrics removed


def test_hook_inputs_are_fingerprinted_and_checked(setup):
    tmp, vtm, enc, dec, seq = setup
    qp = tmp / "qp.csv"
    job = Job(seq, "ldp", 32, "dqp", (f"--VCMQpOffsetFile={qp}",))
    with pytest.raises(FileNotFoundError, match="hook input"):
        check_hook_inputs(job)
    with pytest.raises(FileNotFoundError):
        run_job(job, enc, dec, vtm, tmp / "out")
    assert not (tmp / "out" / job.job_id / "str.bin").exists()   # failed before encoding
    qp.write_text("poc,ctu,dqp\n")
    h1 = run_job(job, enc, dec, vtm, tmp / "out")["fingerprint"]["hash"]
    qp.write_text("poc,ctu,dqp\n0,0,4\n")
    h2 = run_job(job, enc, dec, vtm, tmp / "out")["fingerprint"]["hash"]
    assert h1 != h2


def test_ai_subsampling_recorded_and_frame_count_checked(setup):
    tmp, vtm, enc, dec, seq = setup
    yuv = tmp / "long.yuv"
    yuv.write_bytes(bytes(range(256)) * 9 * 9)            # 18 frames
    long = Sequence("s2", str(yuv), 32, 24, 30.0, 17)
    m = run_job(Job(long, "ai", 22, "alf_default"), enc, dec, vtm, tmp / "out")
    assert (m["frame_step"], m["coded_frames"], m["decoded_frames"]) == (8, 3, 3)   # source frames 0, 8, 16
    m1 = run_job(Job(long, "ai", 22, "all", ("--TemporalSubsampleRatio=1",)), enc, dec, vtm, tmp / "out")
    assert (m1["frame_step"], m1["coded_frames"]) == (1, 17)
    assert frame_step(Job(long, "ai", 22, "x", ("-ts", "4")), vtm) == 4
    assert frame_offset(Job(long, "ai", 22, "x", ("--FrameSkip=3",)), vtm) == 3
    # encoder writes fewer frames than expected -> rejected
    short_enc = _script(vtm / "bin" / "EncoderAppShort", FAKE_ENC.replace("range(0, n, ts)", "range(0, n - 8, ts)"))
    with pytest.raises(RuntimeError, match="expected 3"):
        run_job(Job(long, "ai", 22, "short"), short_enc, dec, vtm, tmp / "out")


def test_variant_placeholders_resolved_per_job():
    a = Sequence("a", "a.yuv", 32, 24, 30, 2)
    jobs = plan([a], ["ldp"], [27], {"w": ("--VCMAlfWeightDir=results/w/{sequence}/{structure}_{qp}",)})
    assert jobs[0].extra_args == ("--VCMAlfWeightDir=results/w/a/ldp_27",)
    with pytest.raises(ValueError, match="placeholder"):
        plan([a], ["ldp"], [27], {"w": ("--X={nope}",)})


def test_run_job_detects_decoder_mismatch(setup):
    tmp, vtm, enc, _, seq = setup
    bad = _script(vtm / "bin" / "DecoderAppBad", BAD_DEC)
    job = Job(seq, "ldp", 32, "alf_default")
    with pytest.raises(RuntimeError, match="differs"):
        run_job(job, enc, bad, vtm, tmp / "out")
    saved = json.loads((tmp / "out" / job.job_id / "manifest.json").read_text())
    assert saved["status"] == "decoder_mismatch"


def test_load_tables(tmp_path):
    csv_path = tmp_path / "s.csv"
    csv_path.write_text("name,path,width,height,fps,frames,bitdepth,split,dataset\n"
                        "a,a.yuv,832,480,50,64,8,tune,sfu\n")
    assert load_sequences(csv_path)[0] == Sequence("a", "a.yuv", 832, 480, 50.0, 64, 8, "tune", "sfu")
    v = tmp_path / "v.yaml"
    v.write_text("variants:\n  alf_default: {args: []}\n  alf_off: {args: ['--ALF=0']}\n")
    assert load_variants(v) == {"alf_default": (), "alf_off": ("--ALF=0",)}
    dup = tmp_path / "d.csv"
    dup.write_text("name,path,width,height,fps,frames\na,x,2,2,1,1\na,y,2,2,1,1\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_sequences(dup)
