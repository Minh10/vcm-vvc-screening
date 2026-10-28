# Kế hoạch sàng lọc hai nhánh

Trạng thái: đề xuất, ngày 2026-10-28. Thời lượng dự kiến 2–3 tuần sau khi P0 xong, tuỳ thời gian chạy VTM.

Nguyên tắc: mỗi nhánh là một giả thuyết **bác bỏ được**, có cổng Go/No-Go đặt trước. Không nhánh nào được
mặc định là trục chính của luận án trước khi có số liệu.

## Thiết lập dùng chung

Cả hai nhánh phải dùng chung các mục sau (định nghĩa trong `configs/experiment.yaml`):

- VTM-24.0 ghim theo commit; cấu hình AI, LDP (và RA ở giai đoạn sau).
- Dữ liệu: SFU-HW-Objects-v1 (phát hiện), TVD (bám vết) theo VCM CTC; UVG-VCM để kiểm tra tổng quát hoá về sau.
- Một detector cố định (checkpoint, tiền xử lý, ngưỡng) theo CTC.
- Bitrate là số bit thực của bitstream; chỉ số nhiệm vụ đo trên ảnh do **bộ giải mã chuẩn** tái tạo.
- Tách chuỗi: `tune` (chọn tham số) và `report` (báo cáo) không giao nhau.

Pilot 2 chuỗi chỉ để kiểm tra pipeline. Quyết định Go/No-Go chạy trên toàn bộ chuỗi `report`.

## Nhánh A — RAMU-Lite

Chi tiết: [RAMU_LITE_SPEC.md](RAMU_LITE_SPEC.md).

**H_A1.** Đặc trưng đồ thị tham chiếu thật (B4) dự đoán ΔL_task của can thiệp ΔQP = −2 tốt hơn baseline mạnh
không dùng đồ thị (B3: độ quan trọng cục bộ + thống kê thời gian), và tốt hơn đồ thị bị xáo trộn (B5).

**H_A2.** Phần thông tin bổ sung đó cải thiện đường rate–task khi dùng để phân bổ QP.

| Cổng | Tiêu chí (ngưỡng thiết kế, đặt trước) | Nếu trượt |
| --- | --- | --- |
| A1 | median(ρ_B4 − ρ_B3) ≥ 0,05, CI 95% bootstrap theo chuỗi nằm trên 0; regret top-k của B4 thấp hơn B3 ≥ 10%; B4 > B5 | No-Go cho luận điểm "reference-aware" |
| A2 | Đường rate–task của RAMU-Lite dịch lên-trái so với QP theo độ quan trọng cục bộ, hiệu ứng cặp theo chuỗi có CI không chứa 0 | No-Go cho đóng góp mã hoá; kết quả dự đoán vẫn có thể công bố |
| Kiểm chứng phụ | Lợi ích thời gian ở AI nhỏ hơn hẳn ở LDP | Nếu không, lợi ích đến từ ngữ nghĩa cục bộ, không phải tham chiếu |

## Nhánh B — MAPS-ALF

Chi tiết cài đặt: [ALF_CODEC_AUDIT_SPEC.md](ALF_CODEC_AUDIT_SPEC.md).

**H_B.** Thiết kế lại hệ số ALF (và lựa chọn bộ lọc theo CTB) theo méo nhiệm vụ máy cải thiện rate–task so với
ALF mặc định của VTM, ở bitrate thực, sau bộ giải mã chuẩn.

Bậc thang thí nghiệm. Mỗi bậc trả lời một câu hỏi khác nhau, nên kết quả âm diễn giải được:

| Bậc | Thí nghiệm | Đo cái gì | Vai trò |
| --- | --- | --- | --- |
| B0 | ALF bật vs tắt, cùng bitrate | ALF ảnh hưởng tới mAP bao nhiêu | Chặn trên thô: nếu gần 0, cả nhánh khó có headroom |
| O1-A | Bộ lọc hình thoi 7×7 kiểu ALF, hệ số số thực, tối ưu bằng gradient qua loss khả vi của detector | Headroom ngoài codec | **Chỉ là upper bound**, không báo cáo như kết quả codec |
| O1-A′ | Lấy hệ số O1-A, chiếu về cú pháp ALF hợp lệ (hệ số nguyên 7-bit phần thập phân, clipping, gộp lớp), nạp thẳng vào APS của VTM | Tổn thất do chuẩn hoá | Tách "kênh ALF quá hẹp" khỏi "bộ tối ưu kém" |
| O1-B | Ứng viên ALF hợp lệ do bộ mã tự sinh: Wiener có trọng số (task weighting) | Lợi ích của phương pháp triển khai được | **Bằng chứng quyết định** |
| Phụ | Chạy O1-A′ và O1-B ở cả AI và LDP | Chênh lệch AI–LDP = hiệu ứng trong vòng lặp qua tham chiếu | Trả lời "ALF hướng máy có giúp khung sau không" |

Đối chứng bắt buộc trong O1-B: ALF tắt, ALF mặc định, ALF Wiener có trọng số. Gauss–Newton sketch chỉ được thêm
nếu O1-B có khoảng cách đáng kể tới O1-A′.

Mục tiêu tối ưu dùng **đầu ra của detector trên khung gốc** (nhãn giả), không dùng nhãn thật của tập thử.
mAP báo cáo vẫn tính theo nhãn thật của CTC.

| Cổng | Tiêu chí | Nếu trượt |
| --- | --- | --- |
| B-0 | O1-A cho cải thiện mAP vượt biến thiên giữa các chuỗi ở QP giữa | Dừng nhánh B sớm |
| B-1 | O1-B cải thiện nhất quán so với ALF mặc định ở bitrate tương đương, hiệu ứng cặp theo chuỗi có CI không chứa 0 | No-Go; ghi kết quả âm, dồn lực cho nhánh A |

Rủi ro đã biết trước: Kim et al. (ETRI Journal 2024) thấy deblocking ảnh hưởng tới nhiệm vụ máy nhiều hơn ALF.
Nếu B0 cho thấy ALF gần như không đổi mAP, đây là lời giải thích đầu tiên cần kiểm tra.

## Thống kê

- Đơn vị: chuỗi. Với mỗi chuỗi tính một hiệu số cặp (phương pháp − đối chứng).
- Kiểm định chính: hoán vị dấu cặp theo chuỗi. CI 95%: bootstrap theo chuỗi, 10.000 lần lấy mẫu lại.
- Hai giả thuyết chính trong cùng nhánh: hiệu chỉnh Holm.
- Công cụ: `tools/vcm/stats.py`, `tools/vcm/bd_rate.py`.

## Sau sàng lọc

| Kết quả | Hướng đi |
| --- | --- |
| A qua, B trượt | Trục luận án là phân bổ bit tham chiếu; B thành một mục kết quả âm |
| B qua, A trượt | Trục là "Machine-Task-Aware ALF Design for Standard-Compliant VVC" |
| Cả hai qua | Phát triển riêng, sau đó mới đo tính cộng dồn bằng ablation 2×2 |
| Cả hai trượt | Quay lại rà soát; không tăng độ phức tạp để cứu giả thuyết |
