import pytest

from vcm.interventions import Intervention, load, num_ctus


def write(tmp_path, text):
    p = tmp_path / "iv.csv"
    p.write_text(text)
    return p


def test_num_ctus_counts_partial_edges():
    assert num_ctus(416, 240, 128) == 4 * 2
    assert num_ctus(1920, 1080, 128) == 15 * 9


def test_load_valid_file(tmp_path):
    p = write(tmp_path, "poc,ctu_addr,delta_qp\n12,5,-2\n13,5,-2\n")
    assert load(p, width=416, height=240, frames=32) == [Intervention(12, 5, -2), Intervention(13, 5, -2)]


@pytest.mark.parametrize("body, msg", [
    ("poc,ctu\n1,2\n", "header"),
    ("poc,ctu_addr,delta_qp\n1,2,x\n", "non-integer"),
    ("poc,ctu_addr,delta_qp\n1,2,0\n", "non-zero"),
    ("poc,ctu_addr,delta_qp\n1,2,-20\n", "non-zero"),
    ("poc,ctu_addr,delta_qp\n1,99,-2\n", "ctu_addr"),
    ("poc,ctu_addr,delta_qp\n40,1,-2\n", "poc"),
    ("poc,ctu_addr,delta_qp\n1,2,-2\n1,2,-1\n", "duplicate"),
])
def test_load_rejects_invalid(tmp_path, body, msg):
    with pytest.raises(ValueError, match=msg):
        load(write(tmp_path, body), width=416, height=240, frames=32)
