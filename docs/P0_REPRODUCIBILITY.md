# P0 — Tái lập được

Không thí nghiệm nào chạy trước khi mọi mục dưới đây được đánh dấu xong và ghi vào `results/p0/manifest.json`.

## Danh sách kiểm tra

Các mục đánh dấu ✔ đã qua trong môi trường phát triển (2026-10-28, gcc 13.3, Xeon 2,8 GHz, clip tổng hợp
416×240); phải chạy lại trên máy chủ nhóm và ghi vào `results/p0/manifest.json`.

- [ ] Tải VTM bằng `scripts/fetch_vtm.sh`; ghi commit hash vào `third_party/VTM_COMMIT`. ✔ dev: `vcm-hooks` trên VTM-24.0 `ca331de`.
- [ ] Build Release bằng `scripts/build_vtm.sh`; ghi phiên bản compiler, cờ build, CPU. ✔ dev.
- [ ] `scripts/smoke_test.sh` qua: bitstream giải mã được bằng `DecoderApp` không sửa, MD5 ảnh tái tạo của bộ mã khớp bộ giải mã. ✔ dev (LDP).
- [ ] Tính tất định: mã hoá cùng đầu vào hai lần, bitstream trùng từng byte (ghi SHA-256). ✔ dev.
- [ ] Tắt mọi hook: bitstream trùng byte với VTM-24.0 gốc ở AI và LDP. ✔ dev ([kiểm toán](ALF_CODEC_AUDIT.md), mục 8).
- [ ] Ghim phiên bản VCM CTC đang dùng; sao chép danh sách chuỗi, QP, số khung vào `configs/experiment.yaml`.
- [ ] Ghim detector: tên mô hình, checkpoint (SHA-256), framework, phiên bản, ngưỡng, tiền xử lý.
- [ ] Tái lập anchor VTM trên ít nhất SFU lớp C, D: sai lệch mAP và bitrate so với anchor công bố < 1%.
- [ ] Ghi thời gian mã hoá trung bình mỗi khung theo lớp chuỗi, để ước lượng ngân sách tính toán cho hai nhánh.
- [ ] Phân chuỗi `tune` / `report` và ghi vào `configs/experiment.yaml` trước khi xem kết quả nào.

## Manifest tối thiểu cho mỗi lần chạy

```json
{
  "run_id": "",
  "date": "",
  "vtm_commit": "",
  "vtm_build": {"compiler": "", "flags": "", "cpu": ""},
  "encoder_cfg": "",
  "extra_args": [],
  "sequence": "",
  "frames": 0,
  "qp": 0,
  "bitstream_sha256": "",
  "recon_md5_encoder": "",
  "recon_md5_decoder": "",
  "detector": {"name": "", "checkpoint_sha256": "", "framework": ""},
  "notes": ""
}
```
