# Kế hoạch sàng lọc hai nhánh

Trạng thái: công cụ và hook VTM sẵn sàng, đã kiểm chứng trên clip tổng hợp (2026-10-28). Chưa có kết quả trên dữ
liệu CTC. Thời lượng dự kiến 2–3 tuần trên máy chủ nhóm sau khi điền `configs/experiment.yaml`.

Nguyên tắc: mỗi nhánh là một giả thuyết **bác bỏ được**, có cổng Go/No-Go đặt trước. Không nhánh nào được mặc định
là trục chính của luận án trước khi có số liệu. Hai nhánh không được ghép trong cùng một lần chạy.

## Thiết lập dùng chung

- Bộ mã: VTM-24.0 + `vcm-hooks` (`scripts/fetch_vtm.sh`); khi tắt hook, bitstream trùng byte với VTM-24.0
  ([kiểm toán](ALF_CODEC_AUDIT.md), mục 8). Bộ giải mã luôn là `DecoderApp` không sửa.
- Cấu hình AI, LDP (RA ở giai đoạn sau). Dữ liệu: SFU-HW-Objects-v1 (phát hiện), TVD (bám vết) theo VCM CTC;
  UVG-VCM cho tổng quát hoá về sau. Pha 1 chỉ làm **phát hiện trên SFU**; bám vết thêm sau khi pipeline ổn định.
- Một detector cố định theo CTC; bitrate là bit thật; chỉ số nhiệm vụ đo trên đầu ra **bộ giải mã chuẩn**.
- Tách chuỗi `tune` / `report` trước khi xem kết quả. Pilot 2 chuỗi chỉ để kiểm tra pipeline.

## Nhánh A — RAMU-Lite

Chi tiết: [RAMU_LITE_SPEC.md](RAMU_LITE_SPEC.md). Lệnh: `python -m vcm.ramu.runner {sample,run,collect}`, rồi
`python -m vcm.ramu.analysis`.

**H_A1.** Đặc trưng đồ thị tham chiếu *có điều kiện theo nhiệm vụ* (B4) dự đoán ΔL của can thiệp ΔQP = −2 tốt hơn
baseline mạnh B3 (độ quan trọng cục bộ + thống kê codec + **lan truyền nhiều bước không phụ thuộc nhiệm vụ**), và
tốt hơn chính các đặc trưng đó trên đồ thị xáo trộn (B5).

**H_A2.** Thông tin bổ sung đó cải thiện đường rate–task khi dùng để phân bổ QP.

| Cổng | Tiêu chí (ngưỡng thiết kế, đặt trước) | Nếu trượt |
| --- | --- | --- |
| A1 | median(ρ_B4 − ρ_B3) ≥ 0,05, CI 95% bootstrap theo chuỗi > 0; regret top-k của B4 thấp hơn B3 ≥ 10%; B4 > B5 với p Holm < 0,05 | No-Go cho luận điểm "reference-aware" |
| A2 | Rate–task của RAMU-Lite tốt hơn **VTM `--DPF=1`**, **VTM `--BIM=1`** và QP theo độ quan trọng cục bộ; hiệu ứng cặp theo chuỗi có CI không chứa 0 | No-Go cho đóng góp mã hoá |
| Phụ | Lợi ích thời gian ở AI nhỏ hơn hẳn ở LDP | Nếu không, lợi ích đến từ ngữ nghĩa cục bộ |

Phát hiện đã đưa vào thiết kế:
- **B3 phải chứa lan truyền nhiều bước không phụ thuộc nhiệm vụ.** Mô phỏng cho thấy thiếu nó thì B4 thắng B3 và
  B5 có ý nghĩa thống kê ngay cả khi chỉ *số lượng* tham chiếu quan trọng.
- **VTM-24.0 đã có hai công cụ chỉnh QP/λ theo lan truyền tham chiếu**: `DPF` (mã hoá trước, hệ số lan truyền
  méo) và `BIM` (độ quan trọng khối từ MCTF). Cả hai là đối chứng bắt buộc ở A2 (`configs/variants.yaml`).
- **Chỉ CTU có phần dư mới can thiệp được.** `cu_qp_delta` không được gửi khi CU không có phần dư; can thiệp lên
  CTU toàn skip không có hiệu lực. `runner sample` chỉ lấy CTU hợp lệ. Trên clip thử ở QP 27 chỉ 24/48 CTU hợp lệ;
  ở QP cao của CTC tỉ lệ này cần được đo ngay ở pilot vì nó giới hạn không gian hành động.
- **Cỡ mẫu.** Mô phỏng (`vcm.ramu.simulate`, 15 lần mỗi kịch bản, 12 chuỗi): tỉ lệ GO 11/15 (73%) khi có hiệu ứng
  vừa phải, 0/15 khi null. Độ nhạy 73% là thấp; bước xác nhận dùng **16–20 chuỗi**.

## Nhánh B — MAPS-ALF

Chi tiết cài đặt: [ALF_CODEC_AUDIT.md](ALF_CODEC_AUDIT.md). Lệnh: `python -m vcm.alf.experiments
{weights,wiener,oracle}` + các biến thể trong `configs/variants.yaml`.

**H_B.** Thiết kế ALF theo méo nhiệm vụ máy cải thiện rate–task so với ALF mặc định của VTM, ở bitrate thực, sau
bộ giải mã chuẩn.

| Bậc | Thí nghiệm | Cách chạy | Vai trò |
| --- | --- | --- | --- |
| B0 | ALF bật vs tắt, cùng bitrate | biến thể `alf_default` vs `alf_off` | Chặn trên thô cho cả nhánh |
| O1-A | Hệ số số thực tối ưu bằng gradient qua loss nhiệm vụ, xuất phát từ chính bộ lọc của anchor | `experiments oracle --variant-dir` | **Upper bound**, cùng bitrate với anchor, không tính APS và tham chiếu |
| O1-A′ | Hệ số O1-A chiếu về cú pháp hợp lệ, ép vào mọi CTB qua `--VCMAlfExternalFile` | `oracle` → biến thể `alf_external` | Tổn thất do chuẩn hoá (lượng tử, APS 25 bộ lọc, tham chiếu) |
| O1-B | Wiener có trọng số nhiệm vụ **trong** bộ mã ALF của VTM (thiết kế, gộp lớp, bật/tắt CTB, chọn APS theo RD có trọng số) | `experiments weights` → `--VCMAlfWeightDir` | **Bằng chứng quyết định** |
| O1-B-ép | Wiener có trọng số thiết kế offline, ép mọi CTB | `experiments wiener --weights` → `alf_external` | Tách "tiêu chí" khỏi "cơ chế chọn của VTM" |
| Phụ | O1-A′ và O1-B ở cả AI và LDP | — | Chênh lệch AI–LDP = hiệu ứng trong vòng lặp |

Mục tiêu tối ưu dùng đầu ra detector trên khung gốc (nhãn giả); mAP báo cáo theo nhãn thật của CTC.

| Cổng | Tiêu chí | Nếu trượt |
| --- | --- | --- |
| B-0 | O1-A cải thiện mAP vượt biến thiên giữa các chuỗi ở QP giữa | Dừng nhánh B sớm |
| B-1 | O1-B cải thiện nhất quán so với `alf_default`, hiệu ứng cặp theo chuỗi có CI không chứa 0 | No-Go; ghi kết quả âm, dồn lực cho nhánh A |

Phát hiện đã đưa vào thiết kế:
- VTM đã có Wiener có trọng số cho ALF (WSSD cho HDR). O1-B chỉ thay nguồn trọng số; phần mới là trọng số theo nhiệm
  vụ, không phải cơ chế.
- APS 25 bộ lọc không gộp tốn ~2.600 bit/ảnh trên clip thử. O1-A′ vì vậy có thể thua ở bitrate thấp ngay cả khi
  O1-A có headroom; O1-B (có gộp theo RD) là bậc quyết định.
- Rủi ro biết trước: Kim et al. (ETRI Journal 2024) thấy deblocking ảnh hưởng tới nhiệm vụ máy nhiều hơn ALF.

## Thống kê

- Đơn vị: chuỗi. Mỗi chuỗi một hiệu số cặp. Kiểm định chính: hoán vị dấu cặp; CI 95%: bootstrap theo chuỗi,
  10.000 lần; Holm cho các giả thuyết chính trong cùng nhánh (`tools/vcm/stats.py`).
- BD-rate trên đoạn đơn điệu chung, kèm đường cong gốc; chuỗi có BD không xác định được liệt kê rõ
  (`tools/vcm/curves.py`).

## Sau sàng lọc

| Kết quả | Hướng đi |
| --- | --- |
| A qua, B trượt | Trục luận án là phân bổ bit tham chiếu theo nhiệm vụ; B thành một mục kết quả âm |
| B qua, A trượt | Trục là "Machine-Task-Aware ALF Design for Standard-Compliant VVC" |
| Cả hai qua | Phát triển riêng, sau đó mới đo tính cộng dồn bằng ablation 2×2 |
| Cả hai trượt | Quay lại rà soát; không tăng độ phức tạp để cứu giả thuyết |
