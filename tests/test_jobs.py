"""End-to-end test of the batch runner with fake encoder/decoder binaries."""

import json
import stat
import sys
from pathlib import Path

import pytest

from vcm.jobs import Job, Sequence, decoder_cmd, encoder_cmd, load_sequences, load_variants, plan, run_job

FAKE_ENC = """#!{py}
import sys
a = sys.argv
src, bit, rec = a[a.index('-i') + 1], a[a.index('-b') + 1], a[a.index('-o') + 1]
data = open(src, 'rb').read()
open(rec, 'wb').write(data)
open(bit, 'wb').write(b'BS' + data)
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


def test_run_job_ok_and_resumable(setup):
    tmp, vtm, enc, dec, seq = setup
    job = Job(seq, "ldp", 32, "alf_default")
    m = run_job(job, enc, dec, vtm, tmp / "out")
    assert m["status"] == "ok"
    assert m["bits"] == (2304 + 2) * 8
    assert m["kbps"] == pytest.approx(m["bits"] / (2 / 30.0) / 1000)
    assert not (tmp / "out" / job.job_id / "rec_enc.yuv").exists()
    saved = json.loads((tmp / "out" / job.job_id / "manifest.json").read_text())
    assert saved["recon_md5_encoder"] == saved["recon_md5_decoder"]
    # second call is skipped (manifest ok) even if the binaries disappear
    enc.unlink()
    assert run_job(job, enc, dec, vtm, tmp / "out")["status"] == "ok"


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
