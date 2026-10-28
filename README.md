# vcm-vvc-screening

Thí nghiệm sàng lọc cho luận án *Nghiên cứu cải tiến hiệu năng mã hoá video cho các ứng dụng thị giác máy*.
Mục tiêu: quyết định dựa trên bằng chứng hướng nào khai thác được bộ mã chuẩn VVC cho thị giác máy, **trước khi**
chọn trục chính của luận án. Mọi thí nghiệm giữ bitstream VVC hợp chuẩn và **không sửa bộ giải mã**.

## Trạng thái (2026-10-28)

| Hạng mục | Trạng thái |
| --- | --- |
| Bộ mã VTM-24.0 + hook sàng lọc (nhánh `vcm-hooks` của kho riêng `Minh10/VVCSoftware_VTM`; bản vá công khai để kiểm toán: [`third_party/vtm_patch/vcm-hooks.patch`](third_party/vtm_patch/vcm-hooks.patch)) | Xong; tắt hook = trùng byte VTM gốc (AI, LDP, RA) |
| ALF offline (`tools/vcm/alf`) | Xong; **bit-exact** với đầu ra ALF của VTM |
| Driver nhánh A và B, đánh giá, thống kê | Xong; 97 test tự động |
| Độ tin cậy pipeline (căn khung AI, fingerprint cache, pseudo-variant, requested/realised/effective, độ phủ đồ thị, khoá tree VTM) | Xong sau hai vòng rà soát độc lập ([DECISIONS](docs/DECISIONS.md), 2026-10-28 tối, khuya) |
| Đối chứng O1-B (ROI nhị phân, xáo trộn, đồng nhất) | Xong; nhánh đồng nhất trùng byte ALF mặc định |
| Bộ phân bổ QP cho cổng A2 | **Chưa** — chỉ cài khi A1 = GO |
| Kiểm toán ALF ([docs/ALF_CODEC_AUDIT.md](docs/ALF_CODEC_AUDIT.md)) | Xong |
| P0 trên máy chủ nhóm, dữ liệu CTC, detector CTC | **Chưa** — cần dữ liệu và tài nguyên của nhóm ([RUNBOOK](docs/RUNBOOK.md)) |
| Kết quả Go/No-Go của hai nhánh | **Chưa có** |

Mọi con số hiện có đến từ clip tổng hợp hoặc mô phỏng và chỉ dùng để kiểm chứng công cụ; chúng không phải kết quả
nghiên cứu.

## Hai giả thuyết đang được kiểm chứng song song

| Nhánh | Tầng codec | Câu hỏi | Điều kiện đi tiếp |
| --- | --- | --- | --- |
| **A — RAMU-Lite** | Phân bổ bit (QP theo CTU) | Cấu trúc tham chiếu *có điều kiện theo nhiệm vụ* có dự đoán tác động của một can thiệp ΔQP tốt hơn baseline mạnh (gồm cả lan truyền không phụ thuộc nhiệm vụ) không, và có vượt `--DPF`/`--BIM` sẵn có của VTM về rate–task không? | Cổng A1 rồi A2 |
| **B — MAPS-ALF** | Bộ lọc trong vòng lặp (ALF APS) | Thiết kế ALF theo méo nhiệm vụ có cải thiện rate–task so với ALF mặc định, ở bitrate thật, sau decoder chuẩn không? | B-0 (O1-A, chẩn đoán) rồi B-1 (O1-B, quyết định) |

Chi tiết: [docs/RESEARCH_PLAN.md](docs/RESEARCH_PLAN.md). Các phát hiện đã làm thay đổi thiết kế:
[docs/DECISIONS.md](docs/DECISIONS.md). Ngoài phạm vi giai đoạn này: scaling list, LMCS, hậu xử lý/NNPF,
tích hợp VCM-RS, Gauss–Newton sketch.

## Cấu trúc

```
configs/            cấu hình thí nghiệm, biến thể bộ mã, mẫu bảng chuỗi và đầu vào phân tích
docs/               kế hoạch, runbook, kiểm toán ALF, đặc tả RAMU-Lite, nhật ký quyết định, tiền lệ
scripts/            tải/build VTM, smoke test
tools/vcm/          jobs (mã hoá hàng loạt + manifest), evaluate (mAP, nhãn giả), curves (BD theo chuỗi), export,
                    stats (kiểm định theo chuỗi), bd_rate, yuv, detect
tools/vcm/ramu/     nhánh A: đồ thị tham chiếu, đặc trưng B1–B6, cổng A1, mô phỏng, runner can thiệp
tools/vcm/alf/      nhánh B: ALF chuẩn VVC (bit-exact), Wiener có trọng số, chiếu hệ số, oracle O1-A, driver
tests/              97 test
third_party/        VTM, VTM_COMMIT, VTM_PROVENANCE (sinh khi tải, không commit); vtm_patch/: bản vá công khai + EXPECTED_TREE (mốc ghim)
results/            kết quả tổng hợp (dữ liệu thô không commit)
```

## Bắt đầu

```bash
pip install -r requirements.txt
pytest -q
scripts/fetch_vtm.sh && scripts/build_vtm.sh && scripts/smoke_test.sh ldp
```

Sau đó làm theo [docs/RUNBOOK.md](docs/RUNBOOK.md). Phối hợp giữa máy chủ nhóm (Cursor) và phiên Claude:
[docs/COLLABORATION.md](docs/COLLABORATION.md); quy tắc cho mọi agent: [AGENTS.md](AGENTS.md).

## Quy tắc đánh giá (mọi nhánh)

- Đơn vị thống kê là **chuỗi video**, không phải CTU hay khung.
- BD-rate trên **đoạn đơn điệu chung**, luôn kèm đường cong gốc.
- Anchor bật cùng công cụ báo hiệu với phương pháp (ví dụ DQP với ΔQP = 0: biến thể `dqp_anchor`).
- Tham số chỉnh được chọn trên chuỗi `tune`; tối ưu dùng nhãn giả từ khung gốc, không dùng nhãn thật của tập thử.
- Mọi bitstream giải mã bằng `DecoderApp` không sửa; MD5 ảnh tái tạo của bộ mã và bộ giải mã phải khớp; số khung giải mã phải đúng số khung mã hoá.
- Khung giải mã được ghép với nhãn qua khung **nguồn** (`TemporalSubsampleRatio`, `FrameSkip`), không theo thứ tự.
- Kết quả cache chỉ dùng lại khi fingerprint khớp; pseudo-variant (oracle) không bao giờ được báo như kết quả mã hoá.
