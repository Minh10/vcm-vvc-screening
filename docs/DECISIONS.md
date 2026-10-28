# Nhật ký quyết định

Mỗi mục: ngày, quyết định, lý do, bằng chứng. Mục mới thêm lên đầu.

## 2026-10-28 (chiều) — Công cụ và hook VTM hoàn tất; các phát hiện thay đổi thiết kế

Chưa có kết quả trên dữ liệu CTC: môi trường phát triển không truy cập được dữ liệu SFU/TVD, trọng số detector CTC
và chỉ có 2 CPU. Mọi con số dưới đây đến từ clip tổng hợp hoặc mô phỏng, chỉ dùng để kiểm chứng công cụ.

**Đã có.** VTM-24.0 + nhánh `vcm-hooks` (5 tuỳ chọn, tắt = trùng byte VTM gốc, AI và LDP); ALF offline bit-exact với
VTM; driver cho mọi bậc của hai nhánh; 74 test tự động.

**Phát hiện và quyết định kèm theo.**
1. *VTM-24.0 đã có `--DPF` và `--BIM`* — chỉnh QP/λ theo CTU dựa trên lan truyền tham chiếu, không phụ thuộc nhiệm
   vụ. → Đối chứng bắt buộc ở cổng A2. Luận điểm của RAMU-Lite chỉ còn ở phần *có điều kiện theo nhiệm vụ*.
2. *Mô phỏng phát hiện lỗi thiết kế baseline*: nếu B3 thiếu lan truyền nhiều bước không phụ thuộc nhiệm vụ, B4 thắng
   có ý nghĩa thống kê ngay cả khi chỉ số lượng tham chiếu quan trọng. → B3 nay chứa `infl`, `depth`; B4/B5 chỉ khác
   ở đặc trưng có trọng số độ quan trọng.
3. *Độ nhạy của cổng A1* với 12 chuỗi: GO 11/15 lần khi có hiệu ứng, 0/15 khi null. → Bước xác nhận dùng 16–20 chuỗi.
4. *Can thiệp QP chỉ có hiệu lực khi CU có phần dư* (chuẩn VVC không gửi `cu_qp_delta` khi không có phần dư). → Lấy
   mẫu chỉ trên CTU hợp lệ; đo tỉ lệ CTU hợp lệ ở QP của CTC trong pilot.
5. *VTM đã có Wiener có trọng số cho ALF (WSSD, HDR).* → O1-B thay nguồn trọng số; không tuyên bố cơ chế là mới.
6. *APS 25 bộ lọc không gộp tốn ~2.600 bit/ảnh* (clip thử, AI QP 27). → O1-B trong bộ mã ALF của VTM (có gộp lớp)
   là bậc quyết định; O1-A′ chỉ để đo tổn thất do chuẩn hoá.
7. *Oracle O1-A xuất phát từ bộ lọc của anchor và trả về bước tốt nhất*, nên không bao giờ tệ hơn điểm xuất phát
   trên loss tối ưu. Phiên bản đầu (khởi tạo 0, bỏ clipping) làm loss tăng — đã sửa.

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
