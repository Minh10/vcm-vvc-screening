# Kế hoạch sàng lọc hai nhánh

Trạng thái: công cụ và hook VTM sẵn sàng, đã kiểm chứng trên clip tổng hợp; lỗi độ tin cậy của pipeline do rà soát
độc lập chỉ ra đã sửa (2026-10-28, tối). Chưa có kết quả trên dữ
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
| Phụ | Lợi ích ở AI nhỏ hơn hẳn ở LDP | Chỉ là dấu hiệu, không phải phép tách: AI và LDP khác nhau ở nhiều thứ ngoài tham chiếu thời gian (công cụ dự đoán, phân bố bitrate, QP offset theo lớp). Bằng chứng về lan truyền là B4 > B3/B5 trong **cùng** cấu hình LDP |

Phát hiện đã đưa vào thiết kế:
- **B3 phải chứa lan truyền nhiều bước không phụ thuộc nhiệm vụ.** Mô phỏng cho thấy thiếu nó thì B4 thắng B3 và
  B5 có ý nghĩa thống kê ngay cả khi chỉ *số lượng* tham chiếu quan trọng.
- **VTM-24.0 đã có hai công cụ chỉnh QP/λ theo lan truyền tham chiếu**: `DPF` (mã hoá trước, hệ số lan truyền
  méo) và `BIM` (độ quan trọng khối từ MCTF). Cả hai là đối chứng bắt buộc ở A2 (`configs/variants.yaml`).
- **Requested ≠ realised ≠ effective.** Mỗi lần chạy can thiệp có trace riêng; `runner collect` phân loại từng can
  thiệp (không xảy ra / xảy ra nhưng không đổi bitstream / có tác động / không giải thích được). **Phân tích chính
  (quyết định A1) dùng mọi can thiệp requested**, vì bộ phân bổ không biết trước CTU nào sẽ realised; chọn theo
  realised là chọn mẫu theo kết quả sau can thiệp. Can thiệp realised là phân tích phụ; nếu B4 chỉ thắng B3 ở đó,
  đồ thị có giá trị phân tích nhưng chưa chứng minh phân bổ bit tốt hơn. Tỉ lệ realised/effective được chẩn đoán
  theo chuỗi, QP, lớp thời gian, phần dư anchor, độ quan trọng, fan-out. Can thiệp `unexplained` không bị loại: giữ
  trong phân tích chính, liệt kê trong báo cáo và làm phân tích realised mất hiệu lực tới khi được giải thích.
  Không lọc trước theo phần dư (3/8 CTU không có phần dư vẫn có tác động trên clip thử).
- **Độ phủ của đồ thị.** Mô hình chồng lấn chỉ chính xác với CU tịnh tiến; tỉ lệ CU xấp xỉ (affine không đều, GEO,
  sub-block) được báo cáo theo chuỗi và có phân tích độ nhạy loại chúng ([RAMU_LITE_SPEC.md](RAMU_LITE_SPEC.md)).
- **Bộ phân bổ QP của A2 chưa được cài đặt.** Chỉ cài sau khi A1 = GO; trước đó A2 không được coi là sẵn sàng.
- **Cỡ mẫu.** Mô phỏng (`vcm.ramu.simulate`, 15 lần mỗi kịch bản, 12 chuỗi): tỉ lệ GO 11/15 (73%) khi có hiệu ứng
  vừa phải, 0/15 khi null. Độ nhạy 73% là thấp; bước xác nhận dùng **16–20 chuỗi**.

## Nhánh B — MAPS-ALF

Chi tiết cài đặt: [ALF_CODEC_AUDIT.md](ALF_CODEC_AUDIT.md). Lệnh: `python -m vcm.alf.experiments
{weights,wiener,oracle}` + các biến thể trong `configs/variants.yaml`.

**H_B.** Thiết kế ALF *có hướng dẫn bởi nhiệm vụ* (task-guided) cải thiện rate–task so với ALF mặc định của VTM, ở
bitrate thực, sau bộ giải mã chuẩn.

**Phát biểu chính xác của cơ chế O1-B.** Detector trên khung gốc → bản đồ trọng số ROI → thống kê Wiener có trọng số
và quyết định RD có trọng số trong bộ mã ALF của VTM → APS/bitstream VVC hợp chuẩn. Đây là **SSE điểm ảnh có trọng
số ROI**, không phải tối thiểu hoá trực tiếp méo đặc trưng hay loss phát hiện. Tên đóng góp tương ứng là
*Task-Guided ALF Parameter Optimization*; không được ngụ ý tối ưu trực tiếp méo nhiệm vụ. Thay nguồn trọng số (từ
độ sáng/HDR sang ROI) tự nó chưa phải đóng góp lý thuyết mạnh; một tiêu chí thay thế *dự đoán được* thay đổi
feature/task loss, tích hợp vào chọn hệ số, gộp lớp hoặc bật/tắt CTB, là hướng sâu hơn — chỉ nghiên cứu sau khi
O1-B cho thấy headroom thật.

| Bậc | Thí nghiệm | Cách chạy | Vai trò |
| --- | --- | --- | --- |
| B0 | ALF bật vs tắt | biến thể `alf_default` vs `alf_off` | ALF có tác động tới nhiệm vụ không (đường rate–task, không phải cùng bitrate) |
| O1-A | Oracle **nới lỏng, xấp xỉ**: một bộ hệ số số thực mỗi ảnh, áp cho mọi CTB, tối ưu cục bộ bằng gradient qua loss nhiệm vụ, xuất phát từ bộ lọc dùng nhiều nhất của anchor | `experiments oracle --variant-dir` | Chẩn đoán headroom. **Không** phải chặn trên bảo đảm: bỏ APS, lượng tử, hiệu ứng tham chiếu nhưng cũng bỏ bật/tắt theo CTB và lựa chọn APS của anchor; có thể thua ALF thật của anchor. Pseudo-variant `o1a_relaxed_oracle`, bitrate chép từ anchor |
| O1-A′ | Hệ số O1-A chiếu về cú pháp hợp lệ, ép vào mọi CTB qua `--VCMAlfExternalFile` | `oracle` → biến thể `alf_external` | Tổn thất do chuẩn hoá (lượng tử, APS 25 bộ lọc, tham chiếu) |
| O1-B | Wiener có trọng số ROI liên tục (độ phủ điểm số detector) **trong** bộ mã ALF của VTM (thiết kế, gộp lớp, bật/tắt CTB, chọn APS theo RD có trọng số) | `experiments weights` → `alf_weighted` | **Bằng chứng quyết định** |
| O1-B-nhị phân | Cùng cơ chế, trọng số 1 trong mọi hộp, `bg` ngoài hộp | `alf_weighted_binary` | Điểm số detector có ích không |
| O1-B-xáo trộn | Cùng hộp (cùng kích thước, điểm số, ngân sách trọng số) dời tới vị trí ngẫu nhiên | `alf_weighted_shuffled` | Lợi ích có đến từ **căn với đối tượng** hay chỉ từ việc đổi trọng số nói chung |
| O1-B-đồng nhất | Trọng số toàn 1 | `alf_weighted_uniform` | Kiểm tra hợp lệ: phải trùng byte `alf_default` (đã qua trên clip thử) |
| O1-B-ép | Wiener có trọng số thiết kế offline, ép mọi CTB | `experiments wiener --weights` → `alf_external` | Tách "tiêu chí" khỏi "cơ chế chọn của VTM" |
| Phụ | O1-A′ và O1-B ở cả AI và LDP | — | Mô tả. Chênh lệch AI–LDP **không** quy hết cho hiệu ứng qua khung tham chiếu (hai cấu hình khác nhau ở công cụ dự đoán, bitrate, QP offset); muốn tách phải có đối chứng riêng, ví dụ trong LDP chỉ áp trọng số ở ảnh không được tham chiếu so với ở mọi ảnh |

Mục tiêu tối ưu dùng đầu ra detector trên khung gốc (nhãn giả); mAP báo cáo theo nhãn thật của CTC.

| Cổng | Tiêu chí | Nếu trượt |
| --- | --- | --- |
| B-0 | O1-A cải thiện mAP vượt biến thiên giữa các chuỗi ở QP giữa, và loss nhiệm vụ của O1-A thấp hơn ALF thật của anchor trên đa số ảnh | Hạ ưu tiên: chỉ chạy O1-B trên pilot, không chạy O1-A′/mở rộng. Không kết luận "không có headroom" vì O1-A không phải chặn trên |
| B-1 | `alf_weighted` tốt hơn `alf_default` **và** tốt hơn `alf_weighted_shuffled` (BD-rate theo nhiệm vụ, hiệu số cặp theo chuỗi, CI 95 % không chứa 0, Holm cho hai so sánh); `alf_weighted_uniform` trùng byte `alf_default` ở mọi điểm | Thắng `alf_default` nhưng không thắng bản xáo trộn → lợi ích không do căn với đối tượng: No-Go cho luận điểm task-guided. Thua cả hai → No-Go; ghi kết quả âm, dồn lực cho nhánh A |

Phát hiện đã đưa vào thiết kế:
- VTM đã có Wiener có trọng số cho ALF (WSSD cho HDR). O1-B chỉ thay nguồn trọng số; phần mới là trọng số theo nhiệm
  vụ, không phải cơ chế, và bản xáo trộn là đối chứng bắt buộc cho phần mới đó.
- APS 25 bộ lọc không gộp tốn ~2.600 bit/ảnh trên clip thử. O1-A′ vì vậy có thể thua ở bitrate thấp ngay cả khi
  O1-A có headroom; O1-B (có gộp theo RD) là bậc quyết định.
- Rủi ro biết trước: Kim et al. (ETRI Journal 2024) thấy deblocking ảnh hưởng tới nhiệm vụ máy nhiều hơn ALF.

## Độ tin cậy của pipeline (bắt buộc trước P0)

- **Căn khung.** Khung giải mã k = khung nguồn `FrameSkip + k·TemporalSubsampleRatio` (đọc từ cfg và tham số biến
  thể, ghi vào manifest). Nhãn GT có `frame_index` = chỉ số khung **nguồn** (cho phép thưa). Chỉ chấm các ảnh GT của
  khung đã mã hoá; khung không mã hoá bị loại khỏi GT, không bị tính là bỏ sót. Số khung giải mã phải đúng
  `ceil(frames / step)`. Cấu hình AI của VTM dùng step 8.
- **Fingerprint.** Kết quả mã hoá chỉ được dùng lại khi trùng fingerprint: lệnh, nội dung cfg, SHA-256 bộ mã và bộ
  giải mã, chữ ký đầu vào, nội dung mọi tệp/thư mục hook đầu vào, commit VTM. Chỉ số nhiệm vụ chỉ được dùng lại khi
  trùng detector (spec + nội dung tệp trọng số), MD5 ảnh giải mã, GT, step và nguồn nhãn giả. `--strict-cache` biến
  cache lệch thành lỗi.
- **Hook đầu vào** phải tồn tại trước khi mã hoá; biến thể có tham số `{sequence}`, `{structure}`, `{qp}`.
- **Biến thể chỉ ghi** (trace, dump) phải cho bitstream trùng byte với biến thể gốc (`same_bitstream_as`).
- **Tách nhánh** được kiểm tra bằng mã: `vcm.jobs` từ chối chạy chung biến thể nhánh A và B.
- **Pseudo-variant** (O1-A) bị `vcm.curves` từ chối nếu không có `--allow-pseudo`; báo cáo khi đó mang nhãn "không
  phải kết quả mã hoá". Không so các dòng do detector khác nhau chấm.
- **Kiểm toán độc lập bản vá VTM.** Kho VTM của nhóm là riêng tư; toàn bộ thay đổi (12 tệp, +442/−3 dòng) được xuất
  thành `third_party/vtm_patch/vcm-hooks.patch` trong kho công khai này. Áp bản vá lên VTM-24.0 chính thức cho đúng
  cây (tree) của nhánh `vcm-hooks` (`third_party/vtm_patch/EXPECTED_TREE`); `scripts/fetch_vtm.sh` dừng nếu tree khác,
  ở mọi đường lấy mã.

## Chi phí triển khai

Cả hai nhánh hiện là tối ưu **ngoại tuyến**: nhánh A cần một lượt mã hoá anchor để lấy đồ thị (≥ 2 lần mã hoá cho
mỗi bitstream đầu ra), `--DPF` cũng cần mã hoá trước; nhánh B chạy detector trên khung gốc ở phía bộ mã. Mọi tuyên
bố về khả năng triển khai (thiết bị biên, độ trễ) phải kèm: số lần mã hoá trên một bitstream, thời gian tiền phân
tích (detector, lượt anchor, tính trọng số), thời gian mã hoá (`encode_seconds` trong manifest), thời gian detector
(`detector_seconds` trong `task_metrics.json`) và độ trễ cấu trúc (lookahead). Các con số này được báo cùng kết quả
A2/B-1; phương pháp nào cần lookahead dài hơn đối chứng phải được so ở cùng độ trễ hoặc nêu rõ chênh lệch.

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
