# P0 — Tái lập được

Không thí nghiệm nào chạy trước khi mọi mục dưới đây được đánh dấu xong và ghi vào `results/p0/manifest.json`.

## Danh sách kiểm tra

- [ ] Tải VTM-24.0 bằng `scripts/fetch_vtm.sh`; ghi commit hash vào `third_party/VTM_COMMIT`.
- [ ] Build Release bằng `scripts/build_vtm.sh`; ghi phiên bản compiler, cờ build, CPU.
- [ ] `scripts/smoke_test.sh` qua: bitstream giải mã được bằng `DecoderApp` không sửa, MD5 ảnh tái tạo của bộ mã khớp bộ giải mã.
- [ ] Tính tất định: mã hoá cùng đầu vào hai lần, bitstream trùng từng byte (ghi SHA-256).
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
