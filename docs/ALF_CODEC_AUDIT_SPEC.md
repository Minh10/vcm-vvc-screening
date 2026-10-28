# Đặc tả: ALF_CODEC_AUDIT.md

Nhiệm vụ cho Claude Code ở nhánh B. Đầu ra là tệp `docs/ALF_CODEC_AUDIT.md` mô tả chính xác đường đi của ALF
trong VTM-24.0 đã ghim. **Không sửa mã nguồn ALF cho tới khi tài liệu này được duyệt.**

Mọi khẳng định trong tài liệu phải kèm vị trí mã: `đường dẫn tệp:dòng` và tên hàm, theo đúng commit trong
`third_party/VTM_COMMIT`. Không suy từ trí nhớ hoặc từ tài liệu của phiên bản VTM khác.

## Những gì tài liệu phải trả lời

### 1. Thu thập thống kê
- Hàm nào tích luỹ ma trận tự tương quan và vector tương quan chéo cho từng lớp ALF (luma, chroma, CC-ALF)?
- Thống kê được tích luỹ theo CTU rồi gộp, hay theo cả ảnh?
- Có đường SSE có trọng số sẵn có không (ví dụ cho HDR/wPSNR)? Nếu có: trọng số lấy từ đâu, áp vào bước nào,
  bật bằng cờ nào.

### 2. Tính và lượng tử hệ số
- Giải hệ phương trình chuẩn ở đâu; xử lý ma trận suy biến thế nào.
- Lượng tử hệ số về số nguyên ở đâu; độ chính xác; ràng buộc phạm vi theo chuẩn.
- Chọn chỉ số clipping thế nào (tìm kiếm, tiêu chí).

### 3. Gộp lớp và RDO
- Thuật toán gộp 25 lớp luma; tiêu chí RD; λ dùng là gì.
- Hàm méo dùng trong RDO của ALF (SSE trên miền nào, trước hay sau LMCS).

### 4. APS
- Bộ mã quyết định tạo APS mới hay tái dùng APS cũ thế nào.
- APS ID được tái dùng qua các ảnh và **các lớp thời gian** ra sao; ảnh nào được phép tham chiếu APS nào.
- Số APS tối đa thực tế VTM dùng cho luma, chroma, CC-ALF.

### 5. Quyết định theo CTB
- Cờ bật/tắt và chỉ số bộ lọc (APS / bộ cố định / bộ thay thế chroma) theo CTB được chọn ở đâu, theo tiêu chí gì.

### 6. Điểm móc (hook) đề xuất
- Vị trí **gọn nhất** để thêm:
  - (a) một hook nạp hệ số ALF từ tệp ngoài, bỏ qua bước giải Wiener, nhưng vẫn đi qua lượng tử, clipping,
    báo hiệu APS và quyết định CTB của VTM — dùng cho O1-A′;
  - (b) một hook nhân trọng số theo điểm ảnh khi tích luỹ thống kê và khi tính méo RDO — dùng cho O1-B.
- Với mỗi hook: tệp, hàm, số dòng thay đổi ước tính, và lý do khi tắt hook bitstream trùng từng byte với VTM gốc.

### 7. Smoke test
- Lệnh mã hoá vài khung với ALF bật; giải mã bằng `DecoderApp` không sửa; MD5 ảnh tái tạo khớp.
- Ghi log số APS ALF đã gửi, số bit APS, tỉ lệ CTB bật ALF theo thành phần màu.

## Định dạng tệp hệ số ngoài (đề xuất, chốt sau kiểm toán)

```json
{
  "poc": 8,
  "component": "luma",
  "filters": [
    {"class_ids": [0, 1, 2], "coeff": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "clip_idx": null}
  ]
}
```

`coeff` là hệ số số thực theo thứ tự hệ số của ALF luma trong VTM; hook chịu trách nhiệm lượng tử theo đúng
quy tắc của chuẩn. `clip_idx = null` nghĩa là để VTM tự chọn clipping.

## Tiêu chí hoàn thành

- [ ] Mỗi mục 1–7 có câu trả lời kèm vị trí mã.
- [ ] Smoke test chạy được và kết quả MD5 được ghi lại.
- [ ] Liệt kê rõ những gì **chưa** chắc chắn và cách kiểm tra.
