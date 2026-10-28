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
`configs/sequences.csv` theo `configs/sequences.example.csv` (cột `annotations` = GT dạng COCO; mỗi ảnh có
`frame_index` = chỉ số khung **trong tệp YUV nguồn**, bắt đầu từ 0, được phép thưa). Hoàn tất danh sách trong
[P0_REPRODUCIBILITY.md](P0_REPRODUCIBILITY.md).

`scripts/fetch_vtm.sh` lấy nhánh `vcm-hooks`; nếu kho đó không truy cập được, nó tải VTM-24.0 chính thức và áp
`third_party/vtm_patch/vcm-hooks.patch`, rồi kiểm cây mã nguồn và ghi `third_party/VTM_COMMIT`, `VTM_PROVENANCE`.

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

**Căn khung.** `encoder_intra_vtm.cfg` đặt `TemporalSubsampleRatio : 8`: khung giải mã k là khung nguồn 8k.
`vcm.jobs` ghi `frame_step`, `frame_offset` (`FrameSkip`) và `coded_frames` vào manifest; `vcm.evaluate` dùng chúng
để ghép khung giải mã → khung nguồn → ảnh GT, chỉ chấm GT của khung đã mã hoá và từ chối tệp giải mã sai số khung.
Không cần GT riêng cho AI. Các driver nhánh B đọc step từ `--anchor-job` (hoặc `--poc-step`, phải khớp manifest).

**Cache.** Mọi lệnh có thể chạy lại: kết quả chỉ được dùng lại khi fingerprint khớp (xem RESEARCH_PLAN, "Độ tin cậy
của pipeline"). Thêm `--strict-cache` vào `vcm.jobs` ở lần chạy báo cáo để cache lệch là lỗi thay vì chạy lại.

## 1. Điểm tham chiếu chung

```bash
# detector trên khung gốc: tham chiếu + nhãn giả (dùng cho cả hai nhánh)
python -m vcm.evaluate --original --out results/original --sequences configs/sequences.csv --config configs/experiment.yaml
```

## 2. Nhánh B

```bash
# B0: ALF bật/tắt (+ anchor có dump ALF, trùng byte alf_default, đầu vào cho O1-A)
python -m vcm.jobs --sequences configs/sequences.csv --variants configs/variants.yaml --structure ldp ai \
  --qps <QPs> --only-variants alf_default alf_off alf_default_dump --out results/b0 --workers <N>
python -m vcm.evaluate --results results/b0 --pseudo results/original --sequences configs/sequences.csv --config configs/experiment.yaml
python -m vcm.curves --results results/b0 --anchor alf_default --test alf_off --structure ldp --metric map --split report --md results/b0/ldp.md

# O1-A (oracle nới lỏng, KHÔNG phải upper bound) và O1-A' (hệ số chiếu, mã hoá thật)
J=<seq>__ldp__qp<Q>
python -m vcm.alf.experiments oracle --dump results/b1/dump/$J --decoded results/b0/${J}__alf_default_dump/rec_dec.yuv \
  --source <seq.yuv> --weights-file <detector_state_dict.pt> --loss detection \
  --detections results/original/<seq>/detections.json --gt <annotations.json> \
  --out results/b1/external/$J.txt --variant-dir results/b1/${J}__o1a_relaxed_oracle \
  --anchor-job results/b0/${J}__alf_default_dump
#   báo cáo: results/b1/external/$J.report.json (beats_anchor_actual theo ảnh)
#   O1-A': biến thể alf_external đọc đúng results/b1/external/{sequence}__{structure}__qp{qp}.txt
#   so pseudo-variant: vcm.curves ... --test o1a_relaxed_oracle --allow-pseudo (báo cáo mang nhãn chẩn đoán)

# O1-B (bằng chứng quyết định): bản đồ trọng số -> ALF encoder của chính VTM
python -m vcm.alf.experiments weights --detections results/original/<seq>/detections.json --gt <annotations.json> \
  --width <W> --height <H> --pocs <coded_frames> --anchor-job results/b0/<seq>__<st>__qp<Q>__alf_default \
  --out results/b1/weights/<seq>__<st>
python -m vcm.jobs ... --only-variants alf_default alf_weighted alf_external --out results/b1
#   so với alf_default bằng vcm.curves
```

## 3. Nhánh A

```bash
# anchor bật DQP, có trace (mọi lần chạy can thiệp cũng có trace riêng trong runs/traces/)
python -m vcm.ramu.runner run --candidates results/ramu/<seq>/cand --sequences configs/sequences.csv \
  --sequence <seq> --structure ldp --qp <Q> --out results/ramu/<seq>/runs --anchor-only
# hộp của detector trên khung gốc -> CSV poc,x0,y0,x1,y1,score (từ results/original/<seq>/detections.json)
# lấy mẫu trên mọi CTU (resid_in_anchor được ghi lại; --require-residual chỉ cho phân tích độ nhạy)
python -m vcm.ramu.runner sample --trace results/ramu/<seq>/runs/traces/dqp_anchor.csv --boxes <boxes.csv> \
  --width <W> --height <H> --n 200 --pairs 100 --out results/ramu/<seq>/cand
python -m vcm.ramu.runner run --candidates results/ramu/<seq>/cand --sequences configs/sequences.csv \
  --sequence <seq> --structure ldp --qp <Q> --out results/ramu/<seq>/runs --workers <N>
python -m vcm.evaluate --results results/ramu/<seq>/runs --pseudo results/original --sequences configs/sequences.csv --config configs/experiment.yaml
python -m vcm.ramu.runner collect --runs results/ramu/<seq>/runs --candidates results/ramu/<seq>/cand \
  --sequence <seq> --structure ldp --qp <Q> --out results/ramu/<seq>/cand
#   -> interventions.csv (status: not_realised | realised_no_effect | effective | unexplained), realisation.json
#   "unexplained" > 0: dừng và điều tra trước khi phân tích

# cổng A1 trên mọi chuỗi report (configs/ramu_inputs.example.yaml)
# quyết định: gate_a1.json (can thiệp realised); độ nhạy: gate_a1_sensitivity.json; độ phủ: coverage.json
python -m vcm.ramu.analysis --inputs configs/ramu_inputs.yaml --out results/ramu/a1
```

Cổng A2 (chỉ khi A1 = GO; **bộ phân bổ QP của RAMU-Lite chưa được cài đặt**): mã hoá rate–task với `dqp_anchor`,
`vtm_dpf`, `vtm_bim`, QP theo độ quan trọng cục bộ và RAMU-Lite; so bằng `vcm.curves`. Kiểm tra dòng "Test bitstream
identical to anchor" trong báo cáo: DPF/BIM không có tác dụng trên chuỗi quá ngắn.

## 4. Ghi kết quả

Mỗi quyết định Go/No-Go, kể cả kết quả âm, ghi vào [DECISIONS.md](DECISIONS.md) kèm đường dẫn tới
`report.md`/`gate_a1.json` và commit VTM.
