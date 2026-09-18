# StateAgentHumanBot

Chatbot Telegram nhắn tin theo **nhịp của người thật**: thấy tin rồi mới seen, seen rồi mới
nghĩ, nghĩ xong mới gõ, gõ lâu hay mau tùy độ dài câu trả lời — và đang gõ dở mà bị nhắn
thêm thì bỏ đó, đọc lại từ đầu.

Nội dung câu trả lời do Claude sinh ra, qua **claude-cli** hoặc gọi thẳng **Messages API**.

> **English**: A Telegram userbot that replies with human timing — randomized read receipts,
> think time, typing duration proportional to message length, message splitting, typos with
> corrections, energy/circadian rhythm and sleep hours. Powered by Claude (via the `claude`
> CLI or the Messages API). Docs are in Vietnamese; code and config are self-explanatory.

```
14:06:04 SEEN_DELAY  [1364926983] IDLE -> SEEN_DELAY att=AWAY energy=0.93 engage=0.61 tin=1
14:06:14 THINKING    [1364926983] SEEN_DELAY -> THINKING ~9.5s (LLM chay song song)
14:06:15 TYPING      [1364926983] THINKING -> TYPING doan 1/2 ~21.2s (81 ky tu)
14:06:15 SENDING     [1364926983] TYPING -> SENDING doan 1/2
14:06:16 TYPING      [1364926983] SENDING -> TYPING nghi 643ms truoc doan sau
14:06:17 SENDING     [1364926983] TYPING -> SENDING doan 2/2
14:06:17 SENDING     [1364926983] SENDING -> SENDING sua chinh ta     <- gõ sai rồi nhắn "*nhiêu"
14:06:17 COOLDOWN    [1364926983] SENDING -> COOLDOWN tong luot 23.2s thuc te
```

## Bắt đầu trong 3 bước

```bash
pip install -r requirements.txt
python tools/setup.py
python -m humanbot --time-scale 0.2
```

`tools/setup.py` hỏi vài câu rồi tự sinh `.env`. Bước 3 chat thử ngay trong terminal — không
cần Telegram, không cần API key (chọn backend `mock`). `--time-scale 0.2` rút mọi độ trễ
xuống 1/5 cho đỡ ngồi đợi.

Chạy thật trên Telegram thì thêm 2 bước, xem [mục dưới](#chạy-thật-trên-telegram).

## Máy trạng thái

```
                 ┌──────────────── tin nhắn mới đến bất cứ lúc nào ───────────────┐
                 │                          (ngắt & đọc lại)                      │
                 ▼                                                                │
   [IDLE] ──► [SEEN_DELAY] ──► [THINKING] ──► [TYPING] ──► [SENDING] ──► [COOLDOWN]
              mark read        LLM chạy       phát action   tách đoạn     nghỉ một
              sau n giây       song song      "đang soạn"   nếu quá dài   nhịp → IDLE
```

Mỗi cuộc hội thoại một máy trạng thái riêng, chạy độc lập trên asyncio. Đồ thị chuyển trạng
thái được **ép kiểm tra** — chuyển sai là ném lỗi ngay.

## Tạo persona cho việc của bạn

Đây là phần bạn sẽ sửa nhiều nhất. Mỗi persona là **một file JSON**, không cần đụng code:

```bash
cp config/persona.default.json config/persona.cua-toi.json
python -m humanbot --persona config/persona.cua-toi.json
```

Ba bản mẫu có sẵn để tham khảo cách chỉnh:

| File | Nhân vật | Đặc điểm |
|---|---|---|
| `persona.default.json` | An | trợ lý trung tính, ngắn gọn |
| `persona.sales.json` | Linh | tư vấn bán hàng, thân mật, hay hỏi lại |
| `persona.friend.json` | Mint | bạn thân, gõ nhanh 58 wpm, sai chính tả nhiều, thức tới 2h sáng |

Phần nội dung — quyết định bot **nói gì**:

```jsonc
"name": "An",
"bio":  "Tro ly ca nhan, tra loi ngan gon va thang vao van de.",
"style": [ "mỗi dòng là một luật được đưa vào system prompt" ]
```

Phần nhịp — quyết định bot **nhắn như thế nào**:

| Khóa | Ý nghĩa | Tăng lên thì |
|---|---|---|
| `typing.wpm` | tốc độ gõ (từ/phút) | gõ nhanh hơn, typing indicator ngắn lại |
| `typing.hesitationRate` | xác suất khựng giữa lúc gõ | hay tắt/bật lại "đang soạn tin" |
| `seen.activeMedianMs` | bao lâu thì seen khi đang cầm máy | seen chậm hơn |
| `seen.awayMedianMs` | bao lâu thì seen khi đang bận | tin đầu treo lâu hơn |
| `think.readCps` | tốc độ đọc (ký tự/giây) | nghĩ nhanh hơn |
| `think.burstGraceMs` | chờ đối phương gõ nốt | kiên nhẫn hơn, ít cắt lời |
| `send.splitThreshold` | quá bao nhiêu ký tự thì tách tin | tin dài hơn, ít tin lẻ |
| `send.maxChunks` | tối đa mấy tin một lượt | nhắn dồn nhiều hơn |
| `typo.rate` | xác suất gõ sai một từ | sai nhiều hơn, tự sửa `*từ_đúng` |
| `sleep.startHour/endHour` | khung giờ ngủ | ngủ nhiều hơn, tin đêm để sáng trả lời |
| `sleep.timezoneOffsetMin` | múi giờ (420 = GMT+7) | — |
| `rhythm.*` | tốc độ mất/hồi sức và độ hào hứng | xem mục dưới |

## Mô hình "tâm lý"

Ba biến trạng thái nội tại, cập nhật sau mỗi lượt, lưu trong `data/sessions.json`:

- **energy** (0..1) — độ tỉnh táo. Gõ nhiều thì tụt, nghỉ lâu thì hồi, trần bị giới hạn bởi
  nhịp sinh học theo giờ trong ngày. Energy thấp → gõ chậm, nghĩ lâu hơn.
- **engagement** (0..1) — độ hào hứng. Tăng khi đối phương nhắn liên tục/nhắn dài, giảm dần
  theo thời gian im lặng. Engagement cao → seen nhanh, phản xạ nhanh.
- **attention** — `ACTIVE` (vừa nhắn xong, <2 phút) / `IDLE` (<20 phút) / `AWAY` / `ASLEEP`.
  Quyết định khoảng cách từ lúc tin đến lúc seen: vài giây, vài chục giây, vài phút, hay
  **để sáng mai trả lời**.

Mọi độ trễ bốc từ phân phối **log-normal** chứ không phải `random.uniform`: phần lớn giá trị
quanh median, thỉnh thoảng có đuôi dài — đúng kiểu người bị phân tâm.

Vài chi tiết nhỏ nhưng làm nên khác biệt:

- **Gộp tin nhắn**: đang seen/nghĩ/gõ đoạn đầu mà nhận thêm tin → hủy lượt, gộp hết lại trả
  lời một thể.
- **Chờ gõ nốt**: tin kết thúc lửng (không dấu câu) → nán lại vài giây xem có tin tiếp không.
- **Gõ sai rồi sửa**: xác suất nhỏ gõ sai một từ, vài giây sau nhắn `*từ_đúng`.
- **Chưa kịp gửi**: bị ngắt khi mới gửi được nửa số đoạn thì phần còn lại bị bỏ — và lượt sau
  prompt có thẻ `<chua_gui>` để model biết đối phương **chưa hề đọc** đoạn đó.

## Chạy thật trên Telegram

Dùng **Telethon** (MTProto, đăng nhập bằng tài khoản thật) chứ không phải Bot API, vì chỉ tài
khoản thật mới:

| | Telethon | Bot API |
|---|---|---|
| Đánh dấu **đã xem** | `send_read_acknowledge` ✅ | ❌ không có |
| **Đang soạn tin** | `SetTypingRequest` ✅ | có, nhưng kèm nhãn bot |
| Giao diện phía người nhận | như người thật | luôn hiện "bot" |

```bash
python tools/tg_login.py                  # đăng nhập + in ra id để whitelist
python -m humanbot --adapter telegram
```

`tg_login.py` hỏi số điện thoại rồi mã OTP (mã về trong chính Telegram, không phải SMS), lưu
session vào `data/` — lần sau không hỏi lại. Xong nó liệt kê người và group kèm id.

Điền id được phép vào `.env`:

```
TG_ALLOWED=123456789,@ban_than
TG_ALLOW_GROUPS=true        # trong group chỉ trả lời khi bị @mention hoặc reply
```

> ⚠️ **Đây là userbot chạy trên tài khoản Telegram thật.** Telegram cấm spam và tự động hóa
> gây phiền người khác — tài khoản có thể bị hạn chế hoặc khóa. Chỉ dùng cho tài khoản của
> bạn và những người đã đồng ý.
>
> `TG_ALLOWED` để trống thì bot **không khởi động** — vì để trống nghĩa là trả lời mọi người
> nhắn tới, kể cả bạn bè và khách hàng thật. Muốn vậy thật thì phải khai
> `TG_ALLOW_EVERYONE=true`.

## Các cờ hay dùng

| Cờ | Ý nghĩa |
|---|---|
| `--adapter console\|telegram` | kênh chat (mặc định `console`) |
| `--llm claude\|api\|mock` | backend sinh câu trả lời |
| `--persona <file.json>` | đổi tính cách |
| `--time-scale 0.2` | rút gọn mọi độ trễ để demo/debug |
| `--dry-run` | chỉ in ra màn hình, không seen/typing/gửi thật |
| `--seed 42` | cố định ngẫu nhiên để tái lập được |
| `--log-level debug` | in cả độ trễ đã bốc thăm và id chat bị bỏ qua |

Đóng stdin (Ctrl+D) thì bot trả nốt lượt đang dở rồi mới thoát; Ctrl+C là dừng ngay.

## Hai backend LLM

| | `--llm claude` (claude-cli) | `--llm api` (Messages API) |
|---|---|---|
| Xác thực | dùng đăng nhập sẵn của `claude` | cần `ANTHROPIC_API_KEY` |
| Lịch sử hội thoại | claude-cli tự nhớ qua `--resume` | bot tự giữ, `data/history/<id>.json` |
| Overhead mỗi lượt | ~25.700 token (system + tool của Claude Code) | ~249 token (chỉ system prompt) |
| Phụ thuộc | binary `claude` (~236MB RAM mỗi lần gọi) | chỉ gói `anthropic` |

```bash
python tools/cost_compare.py --turns 10 --per-day 500
```

Hội thoại 10 lượt, sonnet — số của claude-cli là **đo thật**, số của API là ước tính (thêm
`--exact` và một API key thì script đếm token thật qua `count_tokens`):

| backend | lượt đầu | lượt sau | TB/lượt | 500 lượt/ngày |
|---|---|---|---|---|
| claude-cli sonnet | $0.0326 | $0.0122 | $0.0142 | $7.12 |
| API claude-sonnet-5 | $0.0021 | $0.0042 | $0.0032 | $1.58 |
| API claude-haiku-4-5 | $0.0011 | $0.0021 | $0.0016 | $0.79 |

Khoảng cách hẹp lại khi hội thoại dài ra (API phải gửi lại lịch sử, còn claude-cli đọc lịch
sử từ cache với giá 0.1x): 60 lượt thì chỉ còn rẻ hơn 2 lần. Chặn trần bằng
`ANTHROPIC_MAX_HISTORY` (mặc định 40 tin).

## Cấu trúc

```
humanbot/
  __main__.py          điểm chạy: python -m humanbot
  config.py            .env + tham số dòng lệnh + nạp persona
  engine.py            điều phối: mỗi cuộc hội thoại một state machine
  machine.py           ★ state machine: IDLE → SEEN → THINK → TYPE → SEND → COOLDOWN
  humanizer.py         ★ toàn bộ công thức độ trễ (hàm thuần, dễ test)
  chunker.py           tách câu trả lời dài thành nhiều tin, không cắt vào code block
  typo.py              gõ sai + tin nhắn sửa lại
  prompt.py            system prompt từ persona + đóng gói ngữ cảnh thời gian
  store.py             lưu session-id + energy/engagement theo từng người
  states.py            enum trạng thái + đồ thị chuyển hợp lệ (sai là ném lỗi)
  clock.py             đồng hồ tăng tốc được (time_scale)
  llm/claude_cli.py    gọi claude -p --output-format json, tự --resume theo hội thoại
  llm/anthropic_api.py gọi thẳng Messages API, tự giữ lịch sử + tính tiền từng lượt
  adapters/            telethon_adapter.py (thật) · console.py (thử) · base.py (giao diện)
tools/setup.py         trợ lý tạo .env
tools/tg_login.py      đăng nhập Telegram + lấy id để whitelist
tools/cost_compare.py  so chi phí hai backend
```

Thêm kênh chat mới (Messenger, Zalo, Discord...) = viết thêm một adapter với 4 hàm:
`mark_seen`, `set_typing`, `send`, và gọi `on_message` khi có tin tới. Xem `adapters/base.py`.

## Test

```bash
python -m unittest discover -s tests -v
```

49 test, chạy ~4 giây, dùng `MockLlm` + đồng hồ tăng tốc nên không gọi API và không tốn tiền.
Phủ: biên độ trễ, tách đoạn không cắt code block, vòng đời state machine (kể cả ngắt giữa
chừng), backend API, và bộ lọc "ai được bot trả lời".

## Yêu cầu

- Python 3.10+ (đã chạy trên 3.14)
- `pip install -r requirements.txt` — Telethon; `anthropic` chỉ cần nếu dùng `--llm api`
- Claude Code CLI nếu dùng `--llm claude` (`claude --version` để kiểm tra)

MIT License.
