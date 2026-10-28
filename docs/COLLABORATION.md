# Phối hợp: máy chủ nhóm (Cursor) và phiên Claude

## Ai làm gì

| Nơi | Có gì | Làm gì |
| --- | --- | --- |
| Máy chủ nhóm, mở bằng Cursor (Remote-SSH hoặc clone trực tiếp) | Dữ liệu SFU/TVD, trọng số detector CTC, nhiều CPU/GPU | P0, B0, pilot A, các lần chạy báo cáo; xuất bản tóm tắt kết quả |
| Phiên Claude (đám mây) | Bản sao repo, VTM đã build, clip tổng hợp; **không** truy cập được máy chủ hay dữ liệu CTC | Sửa và kiểm thử mã, kiểm toán, phân tích các bản tóm tắt được đẩy lên, cập nhật tài liệu |

Cầu nối duy nhất giữa hai bên là GitHub. Claude chỉ thấy những gì được push (hoặc đính kèm vào cuộc trò chuyện).

## Lấy mã trên máy chủ

```bash
git clone https://github.com/Minh10/vcm-vvc-screening.git && cd vcm-vvc-screening
pip install -r requirements.txt            # + torch/torchvision, detectron2 theo nhu cầu
scripts/fetch_vtm.sh                       # nhánh vcm-hooks (cần quyền vào kho riêng) hoặc VTM-24.0 + bản vá
JOBS=$(nproc) scripts/build_vtm.sh
pytest -q && scripts/smoke_test.sh ldp
```

`fetch_vtm.sh` clone kho riêng `Minh10/VVCSoftware_VTM` nếu máy chủ có quyền (đăng nhập GitHub/SSH key của chủ
kho). Nếu không, nó tải VTM-24.0 từ máy chủ JVET (`vcgit.hhi.fraunhofer.de`) và áp
`third_party/vtm_patch/vcm-hooks.patch`. Cả hai đường phải ra cùng tree trong `third_party/vtm_patch/EXPECTED_TREE`,
nếu không script dừng. Nếu máy chủ không ra được internet tới JVET: `VTM_OFFICIAL=<đường dẫn clone VTM có sẵn>`.

Cursor đọc `AGENTS.md` ở gốc repo (quy tắc giống CLAUDE.md), nên agent của Cursor chịu cùng ranh giới.

## Nhánh git

- `main`: chỉ nhận qua pull request; `pytest -q` phải qua.
- `claude/<chủ đề>`: thay đổi mã/tài liệu từ phiên Claude, mở PR vào `main`.
- `team/<chủ đề>`: thay đổi từ máy chủ hoặc Cursor (sửa cấu hình, script chạy).
- `results/<run_id>`: chỉ chứa `results/summary/<run_id>/` (xem dưới) và ghi chú trong DECISIONS nếu có quyết định.

Không sửa cùng một tệp ở hai nhánh song song; nếu cần, báo trước trong mô tả PR. `configs/experiment.yaml` và
`configs/sequences.csv` do máy chủ sở hữu (đường dẫn dữ liệu là của máy chủ).

## Chia sẻ kết quả

```bash
python -m vcm.export --results results/b0 --out results/summary/2026-11-03_b0_pilot
git checkout -b results/2026-11-03_b0_pilot
git add results/summary/2026-11-03_b0_pilot && git commit -m "B0 pilot summary" && git push -u origin HEAD
```

`vcm.export` chỉ chép manifest, task metrics, CSV/JSON/Markdown tổng hợp (bỏ YUV, bitstream, dump, trọng số, trace,
detections, log, tệp > 5 MB). Từ các tệp này Claude dựng lại được đường cong, BD-rate, kiểm định theo chuỗi và cổng A1,
và kiểm được fingerprint, commit/tree VTM, số khung, căn khung. Với lỗi cần xem dữ liệu thô (ví dụ can thiệp
`unexplained`), đẩy riêng trace hoặc log liên quan, hoặc đính kèm vào cuộc trò chuyện.

## Thứ tự công việc hiện tại

1. Máy chủ: P0 đầy đủ (docs/P0_REPRODUCIBILITY.md) trên SFU thật, AI và LDP, detector đúng phiên bản CTC.
2. Máy chủ: B0 + pilot A (2–6 chuỗi `tune`), xuất tóm tắt; Claude kiểm tỉ lệ realised/effective, căn khung, đối chứng.
3. Khoá protocol A1 và B-1 cho tập `report` (ghi vào DECISIONS) trước khi chạy tập `report`.
4. Chạy tập `report`; quyết định Go/No-Go theo cổng đã khoá.
