# Kiểm toán ALF trong VTM-24.0 và các hook sàng lọc

Ngày: 2026-10-28. Mã nguồn: VTM-24.0, commit `ca331de230f27e0489df9d2fa6c006e2dcd2ed89` (bản import trên GitHub
`Minh10/VVCSoftware_VTM`). Số dòng dưới đây là của tệp **gốc** tại commit đó; hook nằm ở nhánh `vcm-hooks`
(commit `9d0aceb`, mô tả trong `VCM_HOOKS.md` của repo VTM). Repo VTM là riêng tư; toàn bộ thay đổi so với VTM-24.0
có trong [`third_party/vtm_patch/vcm-hooks.patch`](../third_party/vtm_patch/vcm-hooks.patch) (12 tệp, +439/−3,
SHA-256 `16fb47de…`); áp lên VTM-24.0 cho đúng tree `8dd3ddef…` của `vcm-hooks`. Kiểm toán độc lập nên đọc bản vá này:
mọi thay đổi nằm ở bộ mã (`source/App/EncoderApp`, `source/Lib/EncoderLib`), không đụng `DecoderLib`/`CommonLib`.

**Kết luận chính.** Toàn bộ đường đi ALF luma đã được đọc và cài đặt lại trong `tools/vcm/alf/spec.py`; bản
cài đặt lại **khớp bit-exact** với đầu ra ALF của VTM (0 sai khác trên ~167.000 mẫu bị ALF thay đổi, kể cả các hàng
quanh biên ảo). VTM **đã có sẵn** cơ chế Wiener có trọng số cho ALF (WSSD, dành cho HDR), nên O1-B chỉ cần thay
nguồn trọng số; phần mới của nhánh B nằm ở *trọng số gì*, không ở cơ chế.

## 1. Thu thập thống kê

| Câu hỏi | Trả lời | Vị trí |
| --- | --- | --- |
| Nơi tích luỹ hiệp phương sai theo lớp | `getBlkStats` gọi `calcCovariance` cho từng mẫu, cộng vào `m_alfCovariance[comp][shape][ctb][class]` | `EncAdaptiveLoopFilter.cpp:2322–2394`, `2396–2516` |
| Theo CTB hay theo ảnh | Theo CTB, rồi cộng vào `m_alfCovarianceFrame` | `deriveStatsForFiltering`, `:2139–2320` |
| Tất cả 4 mức clipping | Có: thống kê cho mọi tổ hợp (hệ số, clip) — `ELocal[k][b]` | `:2328–2388` |
| Đường SSE có trọng số sẵn có | Có: `weight = m_alfWSSD ? m_lumaLevelToWeightPLUT[orgLuma] : 1.0`, nhân vào cả E, y và `pixAcc` (méo) | `:2357`; bật ở `EncGOP.cpp:252–257` khi LMCS bật và tín hiệu PQ (HDR) |
| Ảnh vào ALF | Ảnh tái tạo sau DBF và SAO (`cs.getRecoBuf()`), mở rộng biên bằng sao chép | `ALFProcess`, `:926–928` |
| Ảnh gốc | `getAlfTrueOrg() ? TrueOrg : Org` | `:924` |

## 2. Hệ số, lượng tử, clipping

| Câu hỏi | Trả lời | Vị trí |
| --- | --- | --- |
| Giải hệ phương trình | Cholesky (`gnsSolveByChol`) trong `deriveCoeffQuant` | `:1847–1913` |
| Lượng tử hệ số | 7 bit phần thập phân (`COEFF_SCALE_BITS`), `roundFiltCoeff` rồi tinh chỉnh nguyên | `:1915`, `:1847` |
| Phạm vi hệ số luma | [−128, 127]; bộ giải mã kiểm tra tương tự cho chroma (`VLCReader.cpp:5227`) | hook kiểm tra cho luma |
| Giá trị clipping | `[1<<bd, 1<<(bd−3), 1<<(bd−5), 1<<(bd−7)]` (bd = bit depth nội bộ) | `AdaptiveLoopFilter.cpp:714–725` |
| Chọn chỉ số clipping | Thử phi tuyến/tuyến tính trong `firstPass`; tìm theo lớp trong `deriveCoeffQuant` | `:1276–1359` (chưa đọc từng dòng phần tìm clip, không cần cho hook) |

## 3. Phân lớp và lọc (đã cài đặt lại, bit-exact)

| Chi tiết | Giá trị trong VTM | Vị trí |
| --- | --- | --- |
| Hướng HV | `sumV > sumH` → hướng 1, ngược lại 3 | `AdaptiveLoopFilter.cpp:974–985` |
| Dịch khi tính độ hoạt động | `(sumV+sumH)·64 >> (bitdepth+4)`; ·96 ở hai hàng khối cạnh biên ảo | `:824`, `:961–969` |
| Lấy mẫu con Laplacian | Vị trí (i+j) chẵn trong cửa sổ [−2, 5] | `:855–905` |
| Biên ảo (VB) | 4 hàng trên đáy mỗi CTU (`vbPos = CTU−4`); phân lớp bỏ một cặp hàng, lọc kẹp độ lệch dọc, dịch 10 thay vì 7 ở 2 hàng sát VB | `:707–710`, `:865–871`, `:936–949`, `:1188–1251` |
| Bảng hoán vị hệ số | 4 bảng theo `transposeIdx` | `:1131–1150` |
| 12 cặp tap hình thoi 7×7 | như `spec.TAPS` | `:1217–1231` |

Hai lỗi trong bản cài đặt ban đầu của tôi (hướng HV đảo, dịch `+3` thay vì `+4`) chỉ được phát hiện nhờ đọc mã VTM —
lý do bước kiểm toán này là bắt buộc.

## 4. Gộp lớp và RDO

- `mergeFiltersAndCost` gộp 25 lớp, chi phí = méo (từ hiệp phương sai) + λ·bit hệ số (`:1544–1629`).
- Méo luôn tính từ hiệp phương sai → khi thống kê có trọng số, **mọi** quyết định (thiết kế, gộp, bật/tắt CTB,
  chọn APS) đều tự động dùng méo có trọng số.
- λ ALF = λ của slice nhân hệ số chỉnh độ chính xác (`:919–923`).

## 5. APS

- Mỗi ảnh: thử bộ lọc mới (APS mới) + các APS cũ hợp lệ + 16 bộ cố định (`alfEncoderCtb`, `:2639–3190`).
- APS cũ hợp lệ: cùng layer, `temporalId ≤` lớp thời gian hiện tại, có bộ lọc luma (`getAvailableApsIdsLuma`,
  `:2570–2615`). Danh sách APS xoá ở IRAP (`:881–898`). ID APS mới quay vòng trong `[ALFAPSIDShift,
  ALFAPSIDShift + MaxNumALFAPS)`.
- Hệ quả cho thí nghiệm: một APS "cho máy" gửi ở ảnh lớp thấp có thể được ảnh lớp cao **tái dùng**.

## 6. Quyết định theo CTB

Với từng CTB: chọn bộ lọc (cố định / APS) có chi phí RD nhỏ nhất, so với tắt (`:2798–2881`). Ánh xạ sang
`AlfMode`: `LUMA_FIXED0..15` = bộ cố định, `LUMA0 (=16)..` = APS theo thứ tự trong slice.

## 7. Hook đã cài đặt (nhánh `vcm-hooks`)

| Tuỳ chọn | Vị trí sửa | Ghi chú |
| --- | --- | --- |
| `VCMAlfWeightDir` | `getBlkStats` (thay trọng số WSSD cho luma), nạp ở đầu `ALFProcess` | thiếu tệp = lỗi, không lặng lẽ quay về không trọng số |
| `VCMAlfExternalFile` | `ALFProcess` sau `firstPass(LUMA)`; `alfEncoderCtb` (chỉ nhánh "bộ lọc mới", không APS cũ, không tái thiết kế, mọi CTB = `LUMA0`, không cho tắt) | 25 bộ lọc, không gộp |
| `VCMAlfDumpDir` | `ALFProcess` sau `alfReconstructor` | luma trước/sau ALF, gốc, bộ lọc từng CTB |
| `VCMQpOffsetFile` | `EncModeCtrl::xGetMinMaxQP` (QG lá), `EncCu` (λ qua `updateLambda`), `EncLib` (bật DQP) | nhánh A |
| `VCMTraceFile` | `EncSlice::encodeCtus` sau `compressCtu` | nhánh A |

Không có thay đổi nào ở bộ giải mã, cú pháp, CABAC, ME/MC, biến đổi hay lượng tử hoá.

## 8. Kiểm chứng (clip tổng hợp 416×240, 8 bit đầu vào, nội bộ 10 bit)

| Kiểm tra | Kết quả |
| --- | --- |
| P0 với VTM gốc (LDP, QP 37): decoder chuẩn khớp MD5; hai lần mã hoá trùng byte | Qua |
| Tắt mọi hook: bitstream trùng byte VTM gốc, AI và LDP (QP 27) | Qua (`afefdfbc…`, `d590ceef…`) |
| Sau khi đổi trace (`9d0aceb`): hook tắt và trace bật đều trùng byte VTM gốc, AI/LDP/RA (QP 32, 9 khung, `TemporalSubsampleRatio=1`) | Qua (`a9b58205…`, `8f5afc85…`, `384c93b0…`) |
| Biến thể chỉ ghi (`--VCMAlfDumpDir`, `--VCMTraceFile`) qua `vcm.jobs`: bitstream trùng biến thể gốc | Qua (AI, LDP) |
| `spec.py` vs port nguyên văn vòng lặp C++ (CTU 16, nhiều lần qua VB) | Trùng hoàn toàn (test tự động) |
| `spec.py` vs đầu ra ALF thật của VTM (7 ảnh có ALF, AI + LDP) | 0 sai khác / ~167.000 mẫu bị đổi |
| Hệ số ngoài (Wiener + ngẫu nhiên có clipping phi tuyến): VTM dùng đúng hệ số, mọi CTB = APS mới; decoder gốc khớp MD5; numpy tái tạo bit-exact | Qua |
| Trọng số toàn 1 → bitstream trùng mặc định; trọng số ROI → bitstream khác, giải mã khớp | Qua |
| ΔQP −4 / +3 tại CTU chỉ định → QP CU đổi đúng (21→17, 27→30), CTU kề bên giữ nguyên, decoder khớp | Qua |

## 9. Điều chưa chắc chắn / giới hạn

- Chroma ALF và CC-ALF không thuộc phạm vi; hook không đụng tới chúng.
- Biên ảo của slice/tile/subpicture/PPS không được mô hình hoá (không có trong cấu hình CTC).
- Ở chế độ hệ số ngoài, APS 25 bộ lọc không gộp tốn thêm ~2.600 bit/ảnh trên clip thử (22.568 → 25.176 bit,
  AI QP 27). Ở bitrate thấp, chi phí này có thể lấn át lợi ích → bậc O1-B dùng chính bộ mã ALF của VTM (có gộp
  theo RD) là đối chứng bắt buộc.
- Ảnh không có trong tệp hệ số ngoài vẫn có thể tái dùng APS ngoài đã gửi trước đó (thấy ở POC 7). Thí nghiệm
  O1-A′ phải liệt kê mọi ảnh, hoặc báo cáo việc tái dùng.
- MV trong trace là MV của trường chuyển động tại tâm CU (xấp xỉ tịnh tiến cho affine/GEO/sub-block); độ lệch giữa
  các khối 4×4 (`mv_spread`) và số khối khác tham chiếu (`ref_mixed`) được ghi để đo độ phủ. Phiên bản trước
  (`59054cf`) dùng điểm điều khiển trên-trái của affine và PU đầu của GEO — đã thay.
