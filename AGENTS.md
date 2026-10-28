# Hướng dẫn cho mọi agent lập trình (Cursor, Claude, Codex, …)

Nguồn quy tắc chính là [CLAUDE.md](CLAUDE.md); tệp này lặp lại phần bắt buộc để agent nào cũng đọc được. Nếu hai tệp
khác nhau, CLAUDE.md thắng. Quy trình phối hợp: [docs/COLLABORATION.md](docs/COLLABORATION.md).

Đọc trước khi làm: README.md, docs/RESEARCH_PLAN.md, docs/DECISIONS.md (mục mới nhất ở đầu).

## Ranh giới không được vượt

- Không sửa bộ giải mã, cú pháp, CABAC, ME/MC, biến đổi, lượng tử hoá của VTM.
- Nhánh A chỉ đổi QP/λ phía bộ mã; nhánh B chỉ đổi cách bộ mã chọn nội dung ALF APS và quyết định CTB.
- Mọi thay đổi VTM nằm sau tuỳ chọn, mặc định tắt; khi tắt, bitstream trùng từng byte với VTM-24.0. Sau khi sửa VTM:
  cập nhật `third_party/vtm_patch/vcm-hooks.patch` và `EXPECTED_TREE`, kiểm lại trùng byte ở AI/LDP/RA.
- Không ghép hai nhánh trong cùng một lần chạy (`vcm.jobs` từ chối).
- Không mở rộng phạm vi (scaling list, LMCS, post-filter, VCM-RS) nếu chưa có ghi nhận mới trong docs/DECISIONS.md.
- Không đổi tiêu chí cổng (A1, A2, B-0, B-1) hay quần thể phân tích sau khi đã xem kết quả của tập `report`.

## Kỷ luật thực nghiệm

- Chạy thí nghiệm qua `python -m vcm.jobs` / `vcm.ramu.runner` / `vcm.alf.experiments`, không gọi EncoderApp tay
  cho kết quả báo cáo (mất manifest và fingerprint). Lần chạy báo cáo dùng `--strict-cache`.
- Đơn vị thống kê là chuỗi (`tools/vcm/stats.py`); BD-rate bằng `tools/vcm/bd_rate.py`; báo cáo kèm đường cong gốc.
- Kết quả âm được ghi vào docs/DECISIONS.md như kết quả.
- Không commit YUV, bitstream, dump, bản đồ trọng số, trace, detections; chia sẻ kết quả bằng
  `python -m vcm.export --results <dir> --out results/summary/<run_id>`.
- `pytest -q` phải qua trước khi push.

## Quy ước

Tài liệu viết tiếng Việt, thuật ngữ kỹ thuật giữ tiếng Anh khi cần; mã và chú thích trong mã viết tiếng Anh.
