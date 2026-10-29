# P0 — Tái lập được

Không thí nghiệm nào chạy trước khi mọi mục dưới đây được đánh dấu xong và ghi vào `results/p0/manifest.json`.

## Danh sách kiểm tra

Các mục đánh dấu ✔ đã qua trong môi trường phát triển (2026-10-28, gcc 13.3, Xeon 2,8 GHz, clip tổng hợp
416×240); phải chạy lại trên máy chủ nhóm và ghi vào `results/p0/manifest.json`.

- [ ] `scripts/preflight.sh <nhánh>` qua (`"pass": true`) trên máy chủ.
- [ ] Tải VTM bằng `scripts/fetch_vtm.sh`; ghi commit, tree và hash bản vá vào `third_party/VTM_COMMIT`, `VTM_PROVENANCE`; cây mã khớp VTM-24.0 + `vcm-hooks.patch`. ✔ dev: `f1b3119`, tree `0a28da51…`; đường bản vá cho cùng tree.
- [ ] Build Release bằng `scripts/build_vtm.sh`; ghi phiên bản compiler, cờ build, CPU. ✔ dev.
- [ ] `scripts/smoke_test.sh` qua: bitstream giải mã được bằng `DecoderApp` không sửa, MD5 ảnh tái tạo của bộ mã khớp bộ giải mã. ✔ dev (LDP).
- [ ] Tính tất định: mã hoá cùng đầu vào hai lần, bitstream trùng từng byte (ghi SHA-256). ✔ dev.
- [ ] Tắt mọi hook: bitstream trùng byte với VTM-24.0 gốc ở AI, LDP và RA. ✔ dev ([kiểm toán](ALF_CODEC_AUDIT.md), mục 8).
- [ ] Căn khung với GT thật: với một chuỗi SFU ở AI (step 8) và LDP (step 1), kiểm tay 3 khung rằng hộp GT chồng lên
  đối tượng trên ảnh giải mã; `task_metrics.json → alignment` cho số ảnh GT được chấm đúng `ceil(frames/step)`.
- [ ] Cache: chạy lại toàn bộ lệnh B0 với `--strict-cache` không mã hoá lại job nào; đổi một tệp cfg → mọi job liên
  quan bị coi là lệch.
- [ ] Đối chứng nhánh A có hiệu lực ở độ dài chuỗi của CTC: `vtm_dpf`, `vtm_bim` cho bitstream khác `dqp_anchor`
  (dòng "identical to anchor" của `vcm.curves` trống).
- [ ] Ghim phiên bản VCM CTC đang dùng; sao chép danh sách chuỗi, QP, số khung vào `configs/experiment.yaml`.
- [ ] Ghim detector: tên mô hình, checkpoint (SHA-256), framework, phiên bản, ngưỡng, tiền xử lý.
- [ ] Tái lập anchor VTM trên ít nhất SFU lớp C, D: sai lệch mAP và bitrate so với anchor công bố < 1%.
- [ ] Ghi thời gian mã hoá trung bình mỗi khung theo lớp chuỗi và thời gian detector (`detector_seconds`), để ước lượng ngân sách tính toán và chi phí tiền phân tích của hai nhánh.
- [ ] Phân chuỗi `tune` / `report` và ghi vào `configs/experiment.yaml` trước khi xem kết quả nào.

## Manifest tối thiểu cho mỗi lần chạy

```json
{
  "run_id": "",
  "date": "",
  "vtm_commit": "",
  "vtm_tree": "",
  "vtm_patch_sha256": "",
  "vtm_build": {"compiler": "", "flags": "", "cpu": ""},
  "encoder_cfg": "",
  "extra_args": [],
  "sequence": "",
  "frames": 0,
  "frame_step": 1,
  "coded_frames": 0,
  "fingerprint": {"hash": ""},
  "qp": 0,
  "bitstream_sha256": "",
  "recon_md5_encoder": "",
  "recon_md5_decoder": "",
  "detector": {"name": "", "checkpoint_sha256": "", "framework": "", "fingerprint": ""},
  "notes": ""
}
```
