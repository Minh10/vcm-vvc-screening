# Runbook: chạy sàng lọc trên máy chủ nhóm

Mọi lệnh chạy từ gốc repo, với `PYTHONPATH=tools` (hoặc `pip install -e .`). Thay `<...>` bằng giá trị thật.
Ước lượng thời gian: một lần mã hoá VTM 1080p LDP mất cỡ phút/khung trên một lõi; hãy đo ở P0 trước khi lên lịch.

## 0. Chuẩn bị (một lần)

```bash
pip install -r requirements.txt            # + torch/torchvision nếu chạy oracle O1-A; detectron2 nếu dùng detector CTC
scripts/fetch_vtm.sh && JOBS=$(nproc) scripts/build_vtm.sh
scripts/smoke_test.sh ldp && scripts/smoke_test.sh ai
pytest -q
```

Điền `configs/experiment.yaml` (phiên bản CTC, QP, detector, phân chuỗi `tune`/`report`) và tạo
`configs/sequences.csv` theo `configs/sequences.example.csv` (cột `annotations` = GT dạng COCO, ảnh có
`frame_index`). Hoàn tất danh sách trong [P0_REPRODUCIBILITY.md](P0_REPRODUCIBILITY.md).

Phần `detector` của `configs/experiment.yaml`, ví dụ với Detectron2 theo CTC:

```yaml
detector:
  kind: detectron2
  config_file: /models/faster_rcnn_X_101_32x8d_FPN_3x.yaml
  weights: /models/model_final_68b088.pkl
  score_threshold: 0.05
  pseudo_label_threshold: 0.5
  class_map: {}            # model class -> GT category id, nếu khác nhau
```

**Lưu ý cấu hình AI.** `encoder_intra_vtm.cfg` đặt `TemporalSubsampleRatio : 8`: khung thứ k của video giải mã là
khung 8k của bản gốc, trong khi `vcm.evaluate` ghép khung giải mã với nhãn theo chỉ số. Khi chạy AI, hoặc thêm
`--TemporalSubsampleRatio=1` vào biến thể (đánh giá mọi khung), hoặc dùng tệp GT chỉ chứa các khung 0, 8, 16, …
với `frame_index` = 0, 1, 2, …; các driver nhánh B nhận `--poc-step 8` cho trường hợp này.

## 1. Điểm tham chiếu chung

```bash
# detector trên khung gốc: tham chiếu + nhãn giả (dùng cho cả hai nhánh)
python -m vcm.evaluate --original --out results/original --sequences configs/sequences.csv --config configs/experiment.yaml
```

## 2. Nhánh B

```bash
# B0: ALF bật/tắt
python -m vcm.jobs --sequences configs/sequences.csv --variants configs/variants.yaml --structure ldp ai \
  --qps <QPs> --only-variants alf_default alf_off --out results/b0 --workers <N>
python -m vcm.evaluate --results results/b0 --pseudo results/original --sequences configs/sequences.csv --config configs/experiment.yaml
python -m vcm.curves --results results/b0 --anchor alf_default --test alf_off --structure ldp --metric map --split report --md results/b0/ldp.md

# Anchor có ghi ALF (một lần mỗi chuỗi/QP): thêm --VCMAlfDumpDir=<dir> vào biến thể alf_default
# O1-A (upper bound) và O1-A' (hệ số chiếu, mã hoá thật)
python -m vcm.alf.experiments oracle --dump <dump_dir> --decoded <anchor>/rec_dec.yuv --source <seq.yuv> \
  --weights-file <detector_state_dict.pt> --loss detection --detections results/original/<seq>/detections.json \
  --gt <annotations.json> --out <o1a.txt> --variant-dir results/b1/<seq>__ldp__qp<Q>__o1a_oracle_upper_bound \
  --anchor-job results/b0/<seq>__ldp__qp<Q>__alf_default
#   rồi chạy biến thể alf_external với --VCMAlfExternalFile=<o1a.txt>

# O1-B (bằng chứng quyết định): bản đồ trọng số -> ALF encoder của chính VTM
python -m vcm.alf.experiments weights --detections results/original/<seq>/detections.json --gt <annotations.json> \
  --width <W> --height <H> --pocs <frames> --out <weights_dir>
#   rồi chạy biến thể alf_weighted với --VCMAlfWeightDir=<weights_dir>; so với alf_default bằng vcm.curves
```

## 3. Nhánh A

```bash
# anchor bật DQP, có trace
python -m vcm.ramu.runner run --candidates results/ramu/<seq>/cand --sequences configs/sequences.csv \
  --sequence <seq> --structure ldp --qp <Q> --out results/ramu/<seq>/runs --anchor-only
# hộp của detector trên khung gốc -> CSV poc,x0,y0,x1,y1,score (từ results/original/<seq>/detections.json)
python -m vcm.ramu.runner sample --trace results/ramu/<seq>/runs/anchor_trace.csv --boxes <boxes.csv> \
  --width <W> --height <H> --n 200 --pairs 8 --out results/ramu/<seq>/cand
python -m vcm.ramu.runner run --candidates results/ramu/<seq>/cand --sequences configs/sequences.csv \
  --sequence <seq> --structure ldp --qp <Q> --out results/ramu/<seq>/runs --workers <N>
python -m vcm.evaluate --results results/ramu/<seq>/runs --pseudo results/original --sequences configs/sequences.csv --config configs/experiment.yaml
python -m vcm.ramu.runner collect --runs results/ramu/<seq>/runs --candidates results/ramu/<seq>/cand \
  --sequence <seq> --structure ldp --qp <Q> --out results/ramu/<seq>/cand

# cổng A1 trên mọi chuỗi report (configs/ramu_inputs.example.yaml)
python -m vcm.ramu.analysis --inputs configs/ramu_inputs.yaml --out results/ramu/a1
```

Cổng A2 (chỉ khi A1 = GO): mã hoá rate–task với `dqp_anchor`, `vtm_dpf`, `vtm_bim`, QP theo độ quan trọng cục bộ
và RAMU-Lite; so bằng `vcm.curves`.

## 4. Ghi kết quả

Mỗi quyết định Go/No-Go, kể cả kết quả âm, ghi vào [DECISIONS.md](DECISIONS.md) kèm đường dẫn tới
`report.md`/`gate_a1.json` và commit VTM.
