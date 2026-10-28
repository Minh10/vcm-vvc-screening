# Đặc tả RAMU-Lite (nhánh A)

Nguồn: bản rà soát khoa học RAMU-Lite (2026-10-27). Tài liệu này chỉ giữ phần cần để cài đặt và đánh giá.

## Phạm vi MVP

Giữ: metadata tham chiếu của VTM, can thiệp QP thật thưa, bộ dự đoán nhẹ, phân bổ QP theo CTU/QG.
Bỏ: Jacobian, GNN, RL, thay đổi GOP, mọi sửa đổi ngoài QP/λ phía bộ mã.

Đồ thị được gọi là **motion/reference-overlap graph**, là biến dự đoán trước can thiệp, không phải đồ thị nhân quả.

## Định nghĩa

Với hành động a = (POC, CTU/QG, ΔQP):

- ΔL_u(a) = L(D(E(X; π₀ ⊕ do(A_u = a)))) − L(D(E(X; π₀)))
- ΔR_u(a) = R(E(X; π₀ ⊕ do(A_u = a))) − R(E(X; π₀))

Bộ dự đoán học riêng (ΔL̂, ΔR̂); bộ phân bổ dùng J = ΔL̂ + λ·ΔR̂. Không học tỉ số −ΔL/ΔR.

## Tệp can thiệp

`poc,ctu_addr,delta_qp` — đọc và kiểm tra bằng `tools/vcm/interventions.py`.

```csv
poc,ctu_addr,delta_qp
12,18,-2
```

## Log bắt buộc cho mỗi CTU/CU được can thiệp

run_id, sequence, coding_order, POC, CTU address, CTU x/y, CU/QG geometry, base QP, requested ΔQP,
effective QP, effective λ, predMode, skip/merge, split, reference list/index/POC, MV, residual energy,
RD cost đã chọn, hash ảnh tái tạo, tổng bit bitstream.

## Thiết kế thí nghiệm

- Cấu hình: LDP trước, rate control tắt, một QP giữa trước rồi ≥ 4 điểm QP.
- Hành động đầu tiên: chỉ ΔQP = −2.
- Pilot: 6 chuỗi, 48–64 khung, ~200 can thiệp hợp lệ mỗi chuỗi (chỉ kiểm tra pipeline).
- Xác nhận: ≥ 12 chuỗi độc lập (tốt hơn 16–20), 150–250 can thiệp mỗi chuỗi.
- Lấy mẫu phân tầng theo: chồng lấn ROI, fan-out tham chiếu, chuyển động, năng lượng phần dư, mode, vị trí thời gian.
- ~100 cặp can thiệp (50 cùng nhánh tham chiếu, 50 khác nhánh) để đo tương tác I^L, I^R.

## Baseline

| Mã | Mô hình |
| --- | --- |
| B0 | Ngẫu nhiên |
| B1 | Chỉ độ quan trọng cục bộ/ROI |
| B2 | Lớp thời gian + fan-out tham chiếu |
| B3 | B1 + thống kê thời gian (baseline mạnh không dùng đồ thị) |
| B4 | B3 + đặc trưng đồ thị tham chiếu thật |
| B5 | B4 với cạnh đồ thị bị xáo trộn |
| B6 | Điểm lan truyền méo không phụ thuộc nhiệm vụ |

B3, B4, B5 dùng cùng họ mô hình, cùng số tham số, cùng ngân sách tinh chỉnh (ridge, gradient-boosted trees hoặc MLP nhỏ).

## Chỉ số

Spearman ρ(ΔL̂, ΔL), MAE/RMSE cho ΔL và ΔR, regret top-k ở ngân sách cố định; sau đó Task-BD-rate.

## Công bằng báo hiệu delta-QP

So sánh luôn là Anchor(DQP bật, ΔQP = 0) với RAMU(DQP bật). Không so anchor không bật DQP với phương pháp có DQP.
