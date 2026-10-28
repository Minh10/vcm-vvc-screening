# Nhật ký quyết định

Mỗi mục: ngày, quyết định, lý do, bằng chứng. Mục mới thêm lên đầu.

## 2026-10-28 — Tách hai nhánh sàng lọc, chưa đổi trục luận án

**Quyết định.** Kiểm chứng song song RAMU-Lite (nhánh A) và MAPS-ALF (nhánh B) bằng thí nghiệm bác bỏ tối thiểu.
Không đổi tên hoặc trục luận án sang MAPS-VVC trước khi có số liệu. Không ghép hai nhánh.

**Ngoài phạm vi giai đoạn này:** scaling list, LMCS, hậu xử lý/NNPF/SEI, tích hợp VCM-RS, Gauss–Newton sketch,
đánh giá đa mô hình.

**Lý do.**
- Tối ưu nội dung ALF APS theo tiêu chí truyền thống đã có công trình (DCC 2026, quản lý danh sách APS cho chroma
  ALF/CC-ALF). Phần có thể mới chỉ là **tiêu chí méo nhiệm vụ máy**, phải phát biểu như giả thuyết.
- Oracle hệ số số thực ngoài codec không đủ làm cổng: thiếu lượng tử hệ số, clipping, gộp lớp, chi phí APS và
  hiệu ứng tham chiếu. Bổ sung bậc O1-A′ (chiếu hệ số về cú pháp hợp lệ, nạp vào VTM) và O1-B (phương pháp
  triển khai được) làm bằng chứng quyết định.
- All-Intra không đo được hiệu ứng trong vòng lặp; chạy song song AI và LDP.
- Không đặt mục tiêu % BD-rate khi chưa có thí nghiệm.

**Nguồn.** Phản hồi của ChatGPT và rà soát của Claude ngày 2026-10-27.

## 2026-10-27 — Rà soát MSD-VVC v1.0

**Kết luận.** Khả thi nhưng đóng góp trung tâm không mới:
- Luật căn bậc hai, ΔQP = −3·log₂(w), độ dốc LMCS ∝ √w trùng thiết kế HDR-PQ của VTM (luma dQP, wPSNR).
- MSM qua Jacobian + chiếu ngẫu nhiên trùng FP-RDO/IDSE (Fernández-Menduiña et al.).
- Kênh ngầm cho hậu xử lý trùng bằng sáng chế Nokia US 12542931.
- Ngân sách 31–54% BD-rate dựa trên cộng nhân tính các con số "tới", lấy từ ảnh, khác anchor — không dùng.

**Phần còn giá trị.** Thiết kế ALF theo nhiệm vụ máy (chưa thấy tiền lệ trực tiếp trong tra cứu nhanh; cần rà
soát JVET/MPEG trước khi khẳng định).

## 2026-10-27 — RAMU-Lite thu hẹp thành thí nghiệm bác bỏ

**Kết luận.** Go cho thí nghiệm bác bỏ tối thiểu; No-Go cho RAMU-RDO đầy đủ cho tới khi đồ thị chứng minh
giá trị dự đoán bổ sung và lợi ích mã hoá thực. Overlap lớn nhất: mô hình lan truyền méo cho VVC 2026 (tạo
nhãn bằng nhiễu có kiểm soát trong VTM) — khác biệt phải nằm ở đích là méo **nhiệm vụ máy** và hiệu ứng
theo hành động.
