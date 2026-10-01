# upstream/2026-10-01-phase2 — 二期协议面上游原文归档（worker-B 夜班 2026-10-01）

本轮实现的三个协议面的上游实读原文，全部于 2026-10-01 在 anolis-gpu-01 经 jsdelivr CDN
（GitHub）与 datatracker/rfc-editor 实拉；拉取时逐份核对内容非占位。用途：后续 AU 式
复核与测试锚定溯源（各 src 文件头注的"上游实读依据"即指向本目录）。

| 文件 | 来源 | 支撑的协议面 |
|---|---|---|
| disco.go | tailscale main `disco/disco.go`（jsdelivr） | packages/disco（wrapper 布局 / Ping / Pong / CallMeMaybe / 类型码表） |
| key-disco.go | tailscale main `types/key/disco.go`（jsdelivr） | disco 共享密钥 = box.Precompute（naclboxSharedKey 同构造） |
| stun.go | tailscale main `net/stun/stun.go`（jsdelivr） | packages/netcheck（Binding Request/Response、属性表、SOFTWARE/FINGERPRINT） |
| wg-device-cookie.go | wireguard-go master `device/cookie.go`（jsdelivr） | wireguard Cookie Reply：CreateReply/ConsumeReply/CheckMAC2 语义 |
| wg-device-noise-protocol.go | wireguard-go master `device/noise-protocol.go`（jsdelivr） | MessageCookieReply 64B 布局与 marshal（:112 起） |
| wg-device-constants.go | wireguard-go master `device/constants.go`（jsdelivr） | CookieRefreshTime = 120s |
| draft-irtf-cfrg-xchacha-03.txt | datatracker.ietf.org | crypto XChaCha20-Poly1305 / HChaCha20（§2.2.1 向量 + 附录 A.1 KAT） |
| rfc5769.txt | rfc-editor.org | netcheck STUN：XOR-MAPPED-ADDRESS 官方向量（§2.2/§2.3） |

未归档但已核对：wireguard-go `device/cookie_test.go`（CreateReply→ConsumeReply 行为
测试，本轮 cookie-reply.test.ts 的端到端用例与之同构）；tailscale `conn.go` 的
sendDiscoMessage 封装侧（wrapper 布局以 disco.go 文件头注为准）。
