// Cau noi Zalo <-> humanbot.
//
// Zalo khong co thu vien Python nao con song (zlapi da archive tu 11/2024), nen
// phan noi chuyen voi Zalo chay bang Node + zca-js, con bo nao van la Python.
// Hai ben noi chuyen qua stdio, moi dong la mot JSON.
//
//   stdout (bridge -> python):
//     {"ev":"ready","me":{...}}
//     {"ev":"qr","path":"data/zalo-qr.png"}
//     {"ev":"message","conv":"123","type":0,"text":"...","msgId":"...","data":{...}}
//     {"ev":"error","op":"send","message":"..."}
//
//   stdin  (python -> bridge):
//     {"op":"send","conv":"123","type":0,"text":"..."}
//     {"op":"typing","conv":"123","type":0}
//     {"op":"seen","conv":"123","type":0,"data":{...}}
//
// Moi thu danh cho nguoi doc deu di ra stderr de khong lam ban giao thuc.

import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { Zalo, ThreadType } from "zca-js";

const DATA_DIR = process.env.ZALO_DATA_DIR || path.join("..", "data");
const CRED_PATH = process.env.ZALO_CREDENTIALS || path.join(DATA_DIR, "zalo-credentials.json");
const QR_PATH = process.env.ZALO_QR_PATH || path.join(DATA_DIR, "zalo-qr.png");

const out = (obj) => process.stdout.write(JSON.stringify(obj) + "\n");
const note = (msg) => process.stderr.write(msg + "\n");

function loadCredentials() {
    try {
        const raw = JSON.parse(fs.readFileSync(CRED_PATH, "utf-8"));
        return raw.cookie && raw.imei && raw.userAgent ? raw : null;
    } catch {
        return null;
    }
}

function saveCredentials(api) {
    const ctx = api.getContext();
    const credentials = {
        cookie: ctx.cookie.toJSON()?.cookies || [],
        imei: ctx.imei,
        userAgent: ctx.userAgent,
    };
    fs.mkdirSync(path.dirname(CRED_PATH), { recursive: true });
    fs.writeFileSync(CRED_PATH, JSON.stringify(credentials, null, 2), "utf-8");
    note(`[bridge] Da luu dang nhap vao ${CRED_PATH} - lan sau khong can quet QR nua`);
}

async function connect() {
    const zalo = new Zalo();
    const saved = loadCredentials();
    if (saved) {
        note("[bridge] Dang nhap bang phien da luu...");
        return { api: await zalo.login(saved), fresh: false };
    }

    note("[bridge] Chua co phien dang nhap - se tao ma QR de quet");
    fs.mkdirSync(path.dirname(QR_PATH), { recursive: true });
    const api = await zalo.loginQR({ qrPath: QR_PATH }, (event) => {
        // 0 = QRCodeGenerated, 1 = Expired, 2 = Scanned, 3 = Declined, 4 = GotLoginInfo
        if (event.type === 0) {
            note(`[bridge] Mo file ${QR_PATH} roi quet bang Zalo tren dien thoai`);
            out({ ev: "qr", path: QR_PATH });
        } else if (event.type === 1) {
            note("[bridge] Ma QR het han, dang tao lai...");
        } else if (event.type === 2) {
            note("[bridge] Da quet - xac nhan tren dien thoai di");
        } else if (event.type === 3) {
            note("[bridge] Ban da tu choi dang nhap tren dien thoai");
        }
    });
    return { api, fresh: true };
}

const { api, fresh } = await connect();
if (fresh) saveCredentials(api);

let me = null;
try {
    me = await api.fetchAccountInfo();
} catch (e) {
    note(`[bridge] Khong lay duoc thong tin tai khoan: ${e.message}`);
}
out({ ev: "ready", me: me?.profile ? { id: me.profile.userId, name: me.profile.displayName } : null });

// ----------------------------------------------------------- nhan tin nhan
api.listener.on("message", (m) => {
    try {
        if (m.isSelf) return;
        if (typeof m.data?.content !== "string") return;   // anh/sticker/file: chua ho tro
        out({
            ev: "message",
            conv: String(m.threadId),
            type: m.type,
            text: m.data.content,
            msgId: String(m.data.msgId ?? ""),
            data: m.data,                                   // tra lai nguyen si de con gui seen
        });
    } catch (e) {
        out({ ev: "error", op: "recv", message: String(e?.message || e) });
    }
});

api.listener.on("error", (e) => out({ ev: "error", op: "listener", message: String(e?.message || e) }));
api.listener.start();
note("[bridge] Dang lang nghe tin nhan");

// --------------------------------------------------------- nhan lenh tu bot
const rl = readline.createInterface({ input: process.stdin });
for await (const line of rl) {
    if (!line.trim()) continue;
    let op;
    try {
        op = JSON.parse(line);
    } catch {
        continue;
    }
    const type = op.type ?? ThreadType.User;
    try {
        switch (op.op) {
            case "send":
                await api.sendMessage({ msg: op.text }, op.conv, type);
                break;
            case "typing":
                await api.sendTypingEvent(op.conv, type);
                break;
            case "seen":
                await api.sendSeenEvent([op.data], type);
                break;
            case "quit":
                process.exit(0);
                break;
            default:
                out({ ev: "error", op: op.op, message: "lenh khong biet" });
        }
    } catch (e) {
        out({ ev: "error", op: op.op, message: String(e?.message || e) });
    }
}
