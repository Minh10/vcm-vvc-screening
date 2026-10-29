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

## Trace và log

Hook `--VCMTraceFile` (chỉ ghi, không đổi bitstream — đã kiểm ở AI, LDP, RA) ghi mỗi CU luma cuối cùng một dòng:
`poc,coding_order,temporal_id,x,y,w,h,qp,mode,ref_poc0,mv0x,mv0y,ref_poc1,mv1x,mv1y,resid_energy,flags,mv_spread,ref_mixed`

- `qp`: QP cuối cùng của CU đúng như bộ giải mã suy ra; `mode` ∈ intra/inter/skip; `resid_energy` = tổng |hệ số| luma.
- MV (mẫu luma) đọc từ trường chuyển động đã lưu tại **tâm CU**: chính xác với CU tịnh tiến, là xấp xỉ tịnh tiến với
  affine/GEO/sub-block.
- `flags`: `affine4`, `affine6`, `geo`, `ciip`, `mmvd`, `ibc`, `plt`; `mv_spread`: độ lệch lớn nhất (L∞) giữa MV của
  các khối 4×4 trong CU và MV tâm; `ref_mixed`: số khối 4×4 có tham chiếu/danh sách khác tâm (GEO hai tham chiếu).

Manifest mỗi lần chạy (`vcm.jobs`) ghi lệnh, commit/tree VTM, hash bản vá, fingerprint đầu vào, bit, hash bitstream,
MD5 ảnh giải mã, số khung mã hoá. λ hiệu dụng và RD cost chưa được ghi (không cần cho cổng A1).

## Độ phủ của mô hình đồ thị

Đồ thị chồng lấn chỉ chính xác (bỏ qua tap nội suy) với CU tịnh tiến. CU **xấp xỉ** = GEO, `mv_spread` > 0,25 mẫu
(affine có chuyển động không đều, SbTMVP) hoặc `ref_mixed` > 0. `graph.coverage` báo tỉ lệ diện tích inter theo loại;
`analysis` ghi `coverage.json` và chạy phân tích độ nhạy loại CU xấp xỉ (bỏ cạnh của chúng và bỏ CTU có
`approx_frac` > `max_approx_frac`). Trên clip tổng hợp 9 khung (QP 32): 5,9 % diện tích inter là xấp xỉ ở LDP,
7,3 % ở RA (có GEO); affine chiếm ~30 % diện tích inter nhưng phần lớn có MV đồng nhất.

## Requested / realised / effective

Một can thiệp ΔQP được **yêu cầu** (requested) không có nghĩa là nó **xảy ra**. Phân biệt ba mức, đo trên trace riêng
của từng lần chạy so với trace anchor:

| Mức | Định nghĩa | Đo bằng |
| --- | --- | --- |
| requested | Tệp offset yêu cầu ΔQP ở CTU đích | mọi dòng `candidates.csv` |
| realised | Trong CTU đích, QP cuối của ít nhất một CU **hoặc** quyết định mã hoá (phân hoạch, mode, công cụ, tham chiếu, MV) khác anchor | `qp_realised`, `decision_changed_target` |
| effective | Bitstream khác anchor; ΔR, ΔL đo tác động | `bitstream_changed`, `delta_bits`, `delta_loss` |

`status` ∈ `not_realised`, `realised_no_effect`, `effective`, `unexplained` (bitstream đổi nhưng trace CTU đích không
đổi — có thể là lỗ hổng của trace, phải điều tra). `ctus_changed` đếm số CTU có quyết định thay đổi ở mọi
ảnh (phạm vi lan toả).

**Không lọc theo phần dư.** Hook ép QP *và* λ của CTU đích; λ đổi có thể đổi quyết định RD (ví dụ biến CU skip thành
CU có phần dư) dù anchor không có phần dư. `runner sample` lấy mẫu trên mọi CTU, ghi `resid_in_anchor`;
`--require-residual` chỉ là tuỳ chọn độ nhạy. Kiểm chứng trên clip tổng hợp (LDP, QP 37, 12 can thiệp ΔQP = −2):
4/4 CTU có phần dư và **3/8 CTU không có phần dư** là effective (2 trong 3 chỉ qua thay đổi quyết định, QP cuối không
đổi); 5 can thiệp not_realised đều cho bitstream trùng byte với anchor; 0 unexplained.

**Quần thể phân tích** (cố định trước khi có kết quả; sửa ngày 2026-10-28 theo rà soát, trước mọi dữ liệu):
- **chính — mọi can thiệp requested.** Bộ phân bổ thực tế không biết trước CTU nào sẽ realised, nên câu hỏi gắn với
  chính sách là dự đoán trên mọi hành động nó có thể yêu cầu (can thiệp not_realised có ΔL = ΔR = 0 và vẫn được
  tính). Chọn theo realised là chọn mẫu theo kết quả sau can thiệp. Quyết định A1 chỉ dựa trên quần thể này
  (`gate_a1.json`).
- phụ — can thiệp realised: khả năng xếp hạng các hành động *thực sự* đổi bitstream. Nếu B4 thắng B3 ở đây mà không
  thắng ở quần thể chính, đồ thị có giá trị phân tích nhưng chưa chứng minh phân bổ bit tốt hơn. Báo cáo in cả hai
  hiệu số median ρ.
- độ nhạy — quần thể chính, chỉ CTU tịnh tiến (xem mục độ phủ).
- chẩn đoán — tỉ lệ realised/effective/unexplained theo chuỗi, QP, cấu trúc, lớp thời gian, phần dư anchor và tam
  phân vị của độ quan trọng, fan-out, chuyển động, lan truyền (`realisation_diagnostics.csv`).

Can thiệp `unexplained` không bao giờ bị loại tự động: chúng ở lại quần thể chính, được liệt kê trong báo cáo, và
làm phân tích realised mất hiệu lực (`valid: false` trong `gate_a1_secondary.json`) tới khi được giải thích — chúng
có thể cho thấy trace chưa ghi đủ thay đổi do λ gây ra.

## Thiết kế thí nghiệm

- Cấu hình: LDP trước, rate control tắt, một QP giữa trước rồi ≥ 4 điểm QP.
- Hành động đầu tiên: chỉ ΔQP = −2.
- Pilot: 6 chuỗi, 48–64 khung, ~200 can thiệp mỗi chuỗi (chỉ kiểm tra pipeline; đo tỉ lệ realised).
- Xác nhận: ≥ 12 chuỗi độc lập (tốt hơn 16–20), 150–250 can thiệp mỗi chuỗi.
- Lấy mẫu phân tầng theo: chồng lấn ROI, fan-out tham chiếu, chuyển động, năng lượng phần dư, mode, vị trí thời gian.
- ~100 cặp can thiệp (50 cùng nhánh tham chiếu, 50 khác nhánh) để đo tương tác I^L, I^R.

## Baseline

| Mã | Mô hình |
| --- | --- |
| B0 | Ngẫu nhiên |
| B1 | Chỉ độ quan trọng cục bộ/ROI |
| B2 | Lớp thời gian + fan-out tham chiếu |
| B3 | B1 + B2 + thống kê codec cục bộ + lan truyền nhiều bước **không phụ thuộc nhiệm vụ** (`infl`, `depth`) |
| B4 | B3 + đặc trưng đồ thị có trọng số độ quan trọng (`fanout_imp1`, `infl_imp`) |
| B5 | B3 + các đặc trưng của B4 tính trên đồ thị xáo trộn (giữ fan-out nguồn) |
| B6 | Chỉ điểm lan truyền không phụ thuộc nhiệm vụ (`infl`) |

Ở cổng A2 (mã hoá thật), đối chứng không phụ thuộc nhiệm vụ là **VTM `--DPF=1` và `--BIM=1`**, có sẵn trong VTM-24.0.
Hai công cụ này cần đủ khung để có tác dụng: trên clip 6 khung cả hai cho bitstream **trùng byte** với
`dqp_anchor`; trên một clip tổng hợp khác dài 33 khung chúng đổi bitrate (+17 % và −32 % ở QP 27). `vcm.curves` liệt kê chuỗi mà biến thể thử
trùng byte anchor ở mọi QP. `--BIM` không chạy với `TemporalSubsampleRatio` ≠ 1 (cấu hình AI).

**Bộ phân bổ QP cho A2 chưa được cài đặt** và chỉ được cài sau khi A1 = GO.

B3, B4, B5 dùng cùng họ mô hình, cùng số tham số, cùng ngân sách tinh chỉnh (ridge, gradient-boosted trees hoặc MLP nhỏ).

## Chỉ số

Spearman ρ(ΔL̂, ΔL), MAE/RMSE cho ΔL và ΔR, regret top-k ở ngân sách cố định; sau đó Task-BD-rate.

## Công bằng báo hiệu delta-QP

So sánh luôn là Anchor(DQP bật, ΔQP = 0) với RAMU(DQP bật). Không so anchor không bật DQP với phương pháp có DQP.
