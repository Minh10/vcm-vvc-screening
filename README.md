# vcm-vvc-screening

Thí nghiệm sàng lọc cho luận án *Nghiên cứu cải tiến hiệu năng mã hoá video cho các ứng dụng thị giác máy*.
Mục tiêu: quyết định dựa trên bằng chứng xem hướng nào khai thác được bộ mã chuẩn VVC cho thị giác máy,
**trước khi** chọn trục chính của luận án.

Mọi thí nghiệm giữ bitstream VVC hợp chuẩn và **không sửa bộ giải mã**.

## Hai giả thuyết đang được kiểm chứng song song

| Nhánh | Tầng codec | Câu hỏi | Điều kiện đi tiếp |
| --- | --- | --- | --- |
| **A — RAMU-Lite** | Phân bổ bit (QP theo CTU/QG) | Đồ thị tham chiếu của VTM có dự đoán tác động nhiệm vụ của một can thiệp ΔQP tốt hơn thông tin ROI + thời gian thông thường không, và điều đó có thành lợi ích rate–task không? | B4 > B3 và B4 > B5 (đồ thị xáo trộn) trên chuỗi chưa thấy; sau đó cải thiện đường rate–task |
| **B — MAPS-ALF** | Bộ lọc trong vòng lặp (ALF APS) | Thiết kế lại hệ số và lựa chọn ALF theo méo nhiệm vụ máy có cải thiện rate–task so với ALF mặc định, ở bitrate thực, với bộ giải mã chuẩn không? | Cải thiện nhất quán so với ALF mặc định, vượt biến thiên giữa các chuỗi |

Hai nhánh **không được ghép** cho tới khi mỗi nhánh tự qua cổng của mình. Chi tiết: [docs/RESEARCH_PLAN.md](docs/RESEARCH_PLAN.md).

Ngoài phạm vi giai đoạn này: scaling list, LMCS, hậu xử lý/NNPF, tích hợp VCM-RS, Gauss–Newton sketch.
Lý do ghi ở [docs/DECISIONS.md](docs/DECISIONS.md).

## Thứ tự công việc

1. **P0 — Tái lập được** ([docs/P0_REPRODUCIBILITY.md](docs/P0_REPRODUCIBILITY.md)): ghim VTM-24.0, build, anchor, kiểm tra tính tất định, smoke test bộ giải mã chuẩn. Chưa xong P0 thì chưa chạy thí nghiệm nào.
2. **Kiểm toán ALF** ([docs/ALF_CODEC_AUDIT_SPEC.md](docs/ALF_CODEC_AUDIT_SPEC.md)): viết `ALF_CODEC_AUDIT.md` trước khi sửa bất kỳ dòng nào trong ALF của VTM.
3. **Đặc tả can thiệp QP** cho RAMU-Lite ([docs/RAMU_LITE_SPEC.md](docs/RAMU_LITE_SPEC.md)).
4. Sàng lọc hai nhánh (2–3 tuần, tuỳ thời gian chạy VTM).

## Cấu trúc

```
configs/            cấu hình thí nghiệm dùng chung cho cả hai nhánh
docs/               kế hoạch, đặc tả, nhật ký quyết định, tiền lệ
scripts/            tải, build VTM; smoke test
tools/vcm/          công cụ Python: BD-rate, thống kê theo chuỗi, đọc file can thiệp
tests/              kiểm thử cho tools/vcm
third_party/        VTM được tải vào đây (không commit)
results/            kết quả; dữ liệu thô không commit
```

## Bắt đầu

```bash
pip install -r requirements.txt
pytest -q                      # kiểm tra công cụ đánh giá
scripts/fetch_vtm.sh           # tải VTM-24.0, ghi lại commit
scripts/build_vtm.sh           # build Release
scripts/smoke_test.sh          # mã hoá vài khung, giải mã bằng decoder chuẩn, so MD5
```

## Quy tắc đánh giá (áp dụng cho mọi nhánh)

- Đơn vị thống kê là **chuỗi video**, không phải CTU hay khung.
- BD-rate tính trên **đoạn đơn điệu chung**; luôn kèm đường cong gốc.
- Anchor phải bật cùng công cụ báo hiệu với phương pháp (ví dụ `cu_qp_delta` với ΔQP = 0).
- Tham số chỉnh được chọn trên chuỗi tách riêng khỏi chuỗi báo cáo; không dùng nhãn tập thử để tối ưu.
- Mọi bitstream giải mã bằng bộ giải mã tham chiếu không sửa; so MD5 ảnh tái tạo giữa bộ mã và bộ giải mã.
