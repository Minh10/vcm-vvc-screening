# Hướng dẫn cho Claude Code trong repo này

Đọc README.md và docs/RESEARCH_PLAN.md trước khi làm bất cứ việc gì.

## Ưu tiên

1. P0 (docs/P0_REPRODUCIBILITY.md) phải xong trước mọi thí nghiệm.
2. Với nhánh B: hoàn thành `ALF_CODEC_AUDIT.md` theo docs/ALF_CODEC_AUDIT_SPEC.md **trước khi** sửa mã ALF của VTM.
3. Không mở rộng phạm vi (scaling list, LMCS, post-filter, VCM-RS) nếu chưa có ghi nhận mới trong docs/DECISIONS.md.

## Ranh giới không được vượt

- Không sửa bộ giải mã, cú pháp, CABAC, ME/MC, biến đổi, lượng tử hoá.
- Nhánh A chỉ đổi QP/λ phía bộ mã. Nhánh B chỉ đổi cách bộ mã chọn nội dung ALF APS và quyết định CTB.
- Mọi thay đổi VTM nằm sau macro/cờ cấu hình, mặc định tắt; khi tắt, bitstream phải trùng từng byte với VTM gốc.
- Không ghép hai nhánh trong cùng một lần chạy.

## Kỷ luật thực nghiệm

- Ghi commit VTM, cấu hình, checkpoint detector, seed vào mỗi thư mục kết quả (`results/<run_id>/manifest.json`).
- Đơn vị thống kê là chuỗi; dùng `tools/vcm/stats.py`. Không chạy t-test trên CTU.
- BD-rate dùng `tools/vcm/bd_rate.py` (đoạn đơn điệu chung). Báo cáo đường cong gốc cùng con số BD.
- Kết quả âm được ghi vào docs/DECISIONS.md như kết quả, không bị bỏ qua.

## Quy ước

- Tài liệu viết tiếng Việt, thuật ngữ kỹ thuật giữ tiếng Anh khi cần. Mã và chú thích trong mã viết tiếng Anh.
- Dữ liệu lớn (YUV, bitstream, ảnh tái tạo) không commit; chỉ commit CSV/JSON tổng hợp.
