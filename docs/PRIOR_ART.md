# Tiền lệ cần đặt cạnh mỗi nhánh

Tra cứu đến 2026-10-28 là tra cứu nhanh trên web; **chưa** phủ JVET document register và kho MPEG.
Mục "Cần rà soát" phải xong trước khi viết phần tính mới của bất kỳ bài báo nào.

## Nhánh B — ALF/APS

| Công trình | Liên quan | Ranh giới với MAPS-ALF |
| --- | --- | --- |
| [Optimized ALF Based on the Refined APS in H.266/VVC, DCC 2026](https://pure.nwpu.edu.cn/en/publications/optimized-adaptive-loop-filter-based-on-the-refined-adaptation-pa/) (DOI 10.1109/DCC66757.2026.00080) | Thiết kế nội dung ALF APS và quản lý danh sách APS cho chroma ALF/CC-ALF | Tiêu chí Wiener/MSE, không phải nhiệm vụ máy |
| [Meng et al., Optimized ALF in VVC](https://arxiv.org/abs/2607.05737) | Quyết định tham số ALF, độ phức tạp, một phần đã vào VTM | Tối ưu độ phức tạp, không phải tiêu chí |
| [Kim et al., ETRI Journal 2024](https://onlinelibrary.wiley.com/doi/full/10.4218/etrij.2023-0085) | Bật/tắt chọn lọc bộ lọc trong vòng lặp cho VCM; deblocking ảnh hưởng mạnh nhất | Chỉ bật/tắt; là tín hiệu rủi ro cho headroom của ALF |
| [EURASIP JIVP 2024](https://link.springer.com/article/10.1186/s13640-024-00649-w) | Bật/tắt LMCS, IBC… trên VCM-RS; +5,91% BD-rate trung bình trên VCM-RS | Chỉ bật/tắt |
| Thiết kế HDR-PQ của VTM (luma dQP, wPSNR, LMCS từ dQP) — [mô tả](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11451780) | SSE có trọng số, ΔQP = −3·log₂ w, độ dốc LMCS = √w | Cơ chế có trọng số đã có; chỉ nguồn trọng số khác |
| [Nokia US 12542931](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12542931) | Hậu xử lý cho máy dùng phân vùng, mode, thông tin ALF/SAO/DBF | Ngoài phạm vi giai đoạn này |

## Nhánh A — phân bổ bit theo nhiệm vụ và lan truyền thời gian

| Công trình | Liên quan |
| --- | --- |
| [FRDO, Fischer et al.](https://arxiv.org/abs/2203.05890) | Méo đặc trưng trong RDO của VTM, bitstream hợp chuẩn |
| [FP-RDO / IDSE](https://arxiv.org/abs/2504.02216) | Taylor/Jacobian, xấp xỉ theo khối, sketch Jacobian |
| [RL-RC-DoT, CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Gadot_RL-RC-DoT_A_Block-level_RL_agent_for_Task-Aware_Video_Compression_CVPR_2025_paper.html) | QP theo khối, phần thưởng dài hạn |
| [DT-JRD](https://arxiv.org/abs/2411.09308) và các biến thể JRD 2026 | Ngưỡng nhận diện được → bản đồ QP |
| [Guo et al. 2023](https://doi.org/10.1016/j.image.2023.116957) | Temporal dependent RDO, hệ số hiệu ứng méo |
| [Lan truyền méo cho LD-VVC, 2026](https://doi.org/10.1016/j.icte.2026.07.020) | Nhãn bằng nhiễu có kiểm soát trong VTM — overlap lớn nhất |
| [Fischer et al., Saliency-Driven VVC](https://arxiv.org/abs/2203.05944) | QP theo ROI cho máy |

## Cần rà soát

- [ ] JVET document register: "machine", "VCM", "ALF", "task" (2020–2026).
- [ ] Đóng góp MPEG VCM về in-loop filter hoặc tham số inner codec.
- [ ] IEEE Xplore: "adaptive loop filter" AND ("machine vision" OR "object detection").
- [ ] Bảng lượng tử cho DNN (DeepN-JPEG và tương tự) — chỉ khi mở lại hướng scaling list.
