# Nhật ký quyết định

Mỗi mục: ngày, quyết định, lý do, bằng chứng. Mục mới thêm lên đầu.

## 2026-10-29 — Rà soát PR #1: tự động hoá cổng B-1, đối chứng xáo trộn chính xác, băm toàn bộ đầu vào, preflight

Nguồn: rà soát của ChatGPT trên PR #1. Mọi thay đổi làm trước khi có dữ liệu CTC; tiêu chí B-1 được khoá ở đây.

1. *Cổng B-1 chưa tự động.* → `python -m vcm.alf.gate`: hai so sánh (với `alf_default`, với bản xáo trộn trung bình
   theo seed), mỗi so sánh cần trung bình BD-rate nhiệm vụ < 0, CI 95 % < 0 và p sign-flip Holm < 0,05; kiểm tra hợp
   lệ (nhánh đồng nhất trùng byte, bản đồ xáo trộn đúng phân bố); quyết định GO / NO-GO (không quy được cho căn đối
   tượng) / NO-GO / INVALID. Hệ quả tính được ngay: **cần ≥ 7 chuỗi report** — với 6 chuỗi p chính xác nhỏ nhất là
   1/32, sau Holm 1/16, không thể GO. Cấu trúc quyết định: LDP; AI báo cáo kèm.
2. *Bản xáo trộn cũ không tương đương.* Dời từng hộp độc lập làm đổi chồng lấn giữa các hộp, nên sau khi chặn ở 1 phân
   bố trọng số khác nhánh chính. → Thay bằng **dịch vòng toàn bộ bản đồ liên tục**, một độ dời (bội của 4) cho cả
   chuỗi: là hoán vị điểm ảnh, phân bố trọng số mỗi ảnh giống hệt (kiểm bằng so sánh mảng đã sắp xếp, không dung sai),
   giữ tính liên tục theo thời gian. Chỉ nhận độ dời có chồng lấn ROI ≤ tỉ lệ diện tích ROI (mức ngẫu nhiên).
   **5 seed đặt trước** (0–4); `weights_summary.json` ghi độ dời, chồng lấn, kiểm tra phân bố từng seed.
3. *Fingerprint đầu vào chỉ băm 8 MiB đầu/cuối.* → SHA-256 toàn bộ tệp, nhớ trên đĩa theo (đường dẫn, kích thước,
   mtime, inode); `VCM_HASH_CACHE=off` bắt băm lại (dùng ở lần chạy báo cáo). Phiên bản fingerprint 2: mọi cache cũ bị
   coi là lệch.
4. *Chưa có CI và preflight trên bản sạch.* → `.github/workflows/tests.yml` (pytest, đường bản vá) và
   `scripts/preflight.sh` (clone sạch, pytest, VTM qua bản vá + kiểm tree, build, smoke AI/LDP/RA, trùng byte với
   VTM-24.0 build riêng). CI tìm ra luôn một lỗi: thiếu khai báo phụ thuộc `tabulate` (dùng cho báo cáo Markdown).

**Dừng vòng hạ tầng.** Đồng ý với khuyến nghị: sau preflight này không mở rộng mã nữa cho tới khi có P0, B0 và pilot A
trên dữ liệu SFU thật; chỉ sửa lỗi mà dữ liệu thật làm lộ ra.

## 2026-10-28 (khuya) — Rà soát độc lập lần 3: đổi quần thể chính của A1, đối chứng cho O1-B, khoá bản vá VTM

Nguồn: rà soát của ChatGPT trên commit `9e2994d`. Mọi thay đổi dưới đây làm **trước** khi có dữ liệu CTC.

1. *Quần thể chính của A1 = mọi can thiệp requested* (trước đó: realised). Lý do: bộ phân bổ không biết trước CTU
   nào sẽ realised; chọn theo realised là chọn mẫu theo kết quả sau can thiệp. Realised thành phân tích phụ; báo cáo
   in hiệu số B4 − B3 ở cả hai. Can thiệp `unexplained` không bị loại; chúng vô hiệu hoá phân tích realised tới khi
   được giải thích. Thêm chẩn đoán tỉ lệ realised/effective theo QP, lớp thời gian, phần dư, độ quan trọng, fan-out.
   Lập luận trước đây của tôi (giữ not_realised sẽ thưởng cho dự đoán khả năng xảy ra) vẫn đúng như một rủi ro diễn
   giải — vì vậy hiệu số ở quần thể realised được in cạnh quyết định — nhưng không đủ để chọn nó làm quần thể chính.
2. *O1-B là SSE điểm ảnh có trọng số ROI, không phải tối ưu trực tiếp méo nhiệm vụ.* Đóng góp tương ứng gọi là
   Task-Guided ALF Parameter Optimization. Thêm ba nhánh đối chứng: ROI nhị phân, ROI xáo trộn (cùng hộp, cùng ngân
   sách trọng số, vị trí ngẫu nhiên không chồng lên hộp thật), và đồng nhất (trọng số 1 — kiểm tra hợp lệ). Cổng B-1
   nay đòi `alf_weighted` thắng cả `alf_default` lẫn bản xáo trộn [cách xáo trộn đã thay ở mục 2026-10-29]. Trên clip thử (LDP, QP 32): nhánh
   đồng nhất trùng byte `alf_default`; tỉ trọng trọng số trong ROI 0,66 (liên tục), 0,68 (nhị phân), 0,07 (xáo trộn).
3. *`fetch_vtm.sh` đường bản vá bị lỗi.* `git commit -a` không đưa tệp mới `VCM_HOOKS.md` vào commit, và sai khác chỉ
   cảnh báo. Đã sửa: `git apply --index`; tree phải bằng `third_party/vtm_patch/EXPECTED_TREE` ở **mọi** đường (clone
   nhánh, áp bản vá, bản có sẵn), sai thì dừng (exit 1). Đã thử: đường bản vá và đường nhánh cho cùng tree
   `0a28da51…`; sửa một ký tự trong bản vá → script dừng. Fingerprint cache dùng tree thay cho commit, nên hai đường
   cho cùng cache.
4. *Hook trọng số ALF chấp nhận `+Inf`.* Đã sửa (`std::isfinite`), thêm kiểm tra tệp lớn hơn kích thước ảnh (VTM
   `f1b3119`). Trọng số hợp lệ cho bitstream không đổi; tắt hook vẫn trùng byte VTM gốc.
5. *Kiểm tra trùng bitstream của biến thể chỉ ghi có thể bị bỏ qua* khi chạy riêng biến thể đó. Đã sửa: `vcm.jobs`
   tự thêm job tham chiếu; thiếu tham chiếu là lỗi.
6. *Chênh lệch AI–LDP không phải phép tách hiệu ứng trong vòng lặp* (hai cấu hình khác nhau ở nhiều yếu tố). Đổi
   vai trò các hàng "Phụ" thành mô tả; bằng chứng về lan truyền của nhánh A là B4 > B3/B5 trong cùng LDP.

## 2026-10-28 (tối) — Sửa độ tin cậy của pipeline theo rà soát độc lập; đính chính hai phát biểu

Nguồn: rà soát của ChatGPT trên commit `6bd8dd9` (sáu vấn đề, lưu ý requested/realised/effective, chi phí ngoại
tuyến). Vẫn chưa có kết quả trên dữ liệu CTC; các con số dưới đây từ clip tổng hợp, chỉ kiểm chứng công cụ.

**Đính chính.**
1. *Mục 4 của nhật ký chiều nay ("can thiệp QP chỉ có hiệu lực khi CU có phần dư") sai ở dạng đã viết.* Không gửi
   `cu_qp_delta` không có nghĩa can thiệp vô hiệu: hook ép cả QP lẫn λ, và λ đổi có thể đổi quyết định RD. Đo lại
   (LDP, QP 37, 12 can thiệp ΔQP = −2 trên clip 416×240): 3/8 CTU không có phần dư ở anchor vẫn làm bitstream thay
   đổi, 2 trong 3 chỉ qua quyết định (QP cuối không đổi). → Bỏ bộ lọc phần dư khi lấy mẫu; phân loại từng can thiệp
   requested/realised/effective bằng trace riêng của mỗi lần chạy; phân tích chính trên can thiệp realised [đã đổi ở mục khuya: chính = mọi requested], độ nhạy
   trên mọi can thiệp requested (RAMU_LITE_SPEC.md). Nhận định "24/48 CTU hợp lệ" trước đây đo khả năng *có phần dư*,
   không phải khả năng *can thiệp được*.
2. *O1-A không phải upper bound.* Nó nới lỏng codec (số thực, không APS, không hiệu ứng tham chiếu) nhưng cũng hạn
   chế (một bộ lọc mỗi ảnh cho mọi CTB, không bật/tắt CTB, không chọn APS) và tối ưu cục bộ, nên có thể thua ALF thật
   của anchor. → Gọi là oracle nới lỏng/xấp xỉ; pseudo-variant đổi tên `o1a_relaxed_oracle`, có cờ `pseudo_variant`;
   báo cáo `beats_anchor_actual` theo ảnh. Cổng B-0 không còn là điều kiện dừng nhánh B: nếu trượt chỉ hạ ưu tiên,
   O1-B (bằng chứng quyết định, rẻ) vẫn chạy trên pilot. Thay đổi cổng này làm **trước** khi có bất kỳ dữ liệu nào.

**Sửa lỗi pipeline.**
3. *Căn khung AI.* `evaluate` ghép khung giải mã với GT theo thứ tự liên tiếp; với `TemporalSubsampleRatio = 8` của
   cấu hình AI, khung giải mã 1 (nguồn 8) bị chấm với nhãn khung 1. → Ánh xạ khung giải mã k → khung nguồn
   `FrameSkip + k·step` → ảnh GT theo `frame_index` của khung nguồn; chỉ chấm GT của khung đã mã hoá; kiểm số khung
   giải mã. Test: ở AI step 8 cách ghép cũ cho mAP < 50 trên dữ liệu mà cách đúng cho 100.
4. *Cache không có fingerprint.* → Fingerprint cho mã hoá (lệnh, cfg, binary, đầu vào, tệp hook, commit) và cho chỉ
   số nhiệm vụ (detector + trọng số, MD5 ảnh giải mã, GT, step, nguồn nhãn giả); metric cũ bị xoá khi mã hoá lại;
   `curves` bỏ metric không khớp ảnh giải mã và từ chối trộn detector.
5. *Biến thể có tham số.* `alf_weighted`, `alf_external`, `alf_default_dump`, `dqp_anchor_trace` nay chạy được qua
   `vcm.jobs` với `{sequence}`, `{structure}`, `{qp}`; tệp hook thiếu → lỗi trước khi mã hoá. Chạy thật với VTM:
   10 biến thể nhánh B (AI + LDP) và 7 biến thể nhánh A; dump/trace trùng byte biến thể gốc.
6. *Tách nhánh bằng mã.* `vcm.jobs` từ chối chạy chung biến thể nhánh A và B.
7. *Đồ thị và mode không tịnh tiến.* Trace mới (VTM `9d0aceb`) lấy MV tại tâm CU từ trường chuyển động, ghi cờ
   affine/GEO/CIIP/MMVD, `mv_spread`, `ref_mixed`; `graph.coverage` báo độ phủ, `analysis` chạy độ nhạy loại CU xấp
   xỉ. Clip tổng hợp: 5,9 % (LDP) và 7,3 % (RA) diện tích inter là xấp xỉ. Bitstream có/không trace và hook tắt so
   với VTM gốc trùng byte ở AI, LDP, RA.
8. *Kiểm toán độc lập bản vá VTM.* Kho `Minh10/VVCSoftware_VTM` là riêng tư (nguyên nhân lỗi 404 của người rà soát).
   → Xuất `third_party/vtm_patch/vcm-hooks.patch` (12 tệp, +439/−3) vào kho công khai; áp lên VTM-24.0 cho đúng tree
   `8dd3dde…` của `vcm-hooks`; `fetch_vtm.sh` dùng bản vá khi không clone được kho riêng và tự kiểm. Đồng thời sửa
   `VTM_COMMIT`: trước đây ghi commit gốc `ca331de` dù binary có hook; nay ghi commit có hook kèm tree và hash bản vá.

**Phát hiện mới.**
9. *`--DPF` và `--BIM` có thể không làm gì trên chuỗi ngắn.* Clip 6 khung: cả hai cho bitstream trùng byte với
   `dqp_anchor`; clip 33 khung: +17 % và −32 % bitrate ở QP 27. → `curves` liệt kê chuỗi có bitstream thử trùng
   anchor ở mọi QP; số khung của A2 phải đủ để đối chứng có hiệu lực. `--BIM` không chạy ở AI (step ≠ 1).
10. *Bộ phân bổ QP của A2 chưa được cài.* Chỉ cài sau A1 = GO (không coi A2 là sẵn sàng).
11. *Chi phí ngoại tuyến* là điều kiện báo cáo: số lần mã hoá/bitstream, thời gian detector và mã hoá, lookahead
    (RESEARCH_PLAN.md, "Chi phí triển khai").

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
4. **[Đã đính chính — xem mục 2026-10-28 (tối), 1]** *Can thiệp QP chỉ có hiệu lực khi CU có phần dư* (chuẩn VVC không gửi `cu_qp_delta` khi không có phần dư). → Lấy
   mẫu chỉ trên CTU hợp lệ; đo tỉ lệ CTU hợp lệ ở QP của CTC trong pilot.
5. *VTM đã có Wiener có trọng số cho ALF (WSSD, HDR).* → O1-B thay nguồn trọng số; không tuyên bố cơ chế là mới.
6. *APS 25 bộ lọc không gộp tốn ~2.600 bit/ảnh* (clip thử, AI QP 27). → O1-B trong bộ mã ALF của VTM (có gộp lớp)
   là bậc quyết định; O1-A′ chỉ để đo tổn thất do chuẩn hoá.
7. **[Bổ sung — xem mục 2026-10-28 (tối), 2: không phải upper bound]** *Oracle O1-A xuất phát từ bộ lọc của anchor và trả về bước tốt nhất*, nên không bao giờ tệ hơn điểm xuất phát
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
