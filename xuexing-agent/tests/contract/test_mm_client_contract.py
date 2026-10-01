"""契约：mm_client —— 多模态客户端（chat/vision/tts/asr 四能力）。

夹具自封闭、**全 mock 零网络**：传输一律注入 MockTransport，DNS 一律注入解析
桩；冒烟用例 env-gated（XX_MM_SMOKE=1 且环境含 key 才真调，默认 skip）。
端点/模型/voice 常量的冻结值以 docs/multimodal-api.md（2026-09-29 阶跃 API
实测矩阵）为事实来源。闭式字节均实测于 CPython 3.12.10 x64。
key 一律用哨兵值 "sk-SENTINEL-1"，并验证任何错误消息不回显它。
"""
import base64
import copy
import ipaddress
import json
import math
import os
import struct
import urllib.parse
import zlib

import pytest

from xuexing.mm_client import (
    ALLOWED_HOST,
    BASE_URL,
    BOUNDARY,
    DEFAULT_TIMEOUT,
    ENDPOINTS,
    IMAGE_MIME,
    JSON_CONTENT_TYPE,
    KEY_ENV_VARS,
    MODEL_ASR,
    MODEL_CHAT,
    MODEL_TTS,
    MULTIPART_CONTENT_TYPE,
    TTS_FORMAT,
    TTS_VOICE,
    LLMError,
    MMClient,
    MockTransport,
    api_key,
    check_url,
    data_url,
    multipart_body,
    vision_content,
)

_KEY = "sk-SENTINEL-1"
_ENV = {"XX_LLM_API_KEY": _KEY}
_PUBLIC = ["93.184.216.34"]          # 桩解析：公网 v4
_RESOLVE_OK = lambda host: _PUBLIC   # noqa: E731


def _client(**kw):
    kw.setdefault("env", _ENV)
    kw.setdefault("resolve", _RESOLVE_OK)
    transport = kw.pop("transport", None) or MockTransport()
    return MMClient(transport, **kw), transport


# ---------- I1 常量冻结 ----------

def test_frozen_constants():
    assert BASE_URL == "https://api.stepfun.com"
    assert ALLOWED_HOST == "api.stepfun.com"
    assert ENDPOINTS == {
        "chat": "https://api.stepfun.com/step_plan/v1/chat/completions",
        "tts": "https://api.stepfun.com/step_plan/v1/audio/speech",
        "asr": "https://api.stepfun.com/v1/audio/transcriptions",  # 不在 step_plan 路径下
    }
    assert (MODEL_CHAT, MODEL_TTS, MODEL_ASR) == (
        "step-5-preview", "stepaudio-2.5-tts", "stepaudio-2.5-asr")
    assert TTS_VOICE == "linjiajiejie" and TTS_FORMAT == "mp3"
    assert KEY_ENV_VARS == ("XX_LLM_API_KEY", "STEPFUN_API_KEY")
    assert DEFAULT_TIMEOUT == 60.0
    assert isinstance(BOUNDARY, str) and BOUNDARY and not BOUNDARY.startswith("--")
    assert JSON_CONTENT_TYPE == "application/json"
    assert MULTIPART_CONTENT_TYPE == "multipart/form-data; boundary=" + BOUNDARY
    assert IMAGE_MIME == {"png": "image/png", "jpg": "image/jpeg",
                          "jpeg": "image/jpeg", "webp": "image/webp",
                          "gif": "image/gif"}
    assert issubclass(LLMError, RuntimeError)


def test_endpoints_pass_own_whitelist():
    for url in ENDPOINTS.values():
        assert check_url(url, resolve=_RESOLVE_OK) is None
        assert url.startswith("https://" + ALLOWED_HOST)


# ---------- I4 key 纪律 ----------

def test_api_key_priority_strip_and_missing():
    assert api_key({"XX_LLM_API_KEY": " k1 ", "STEPFUN_API_KEY": "k2"}) == "k1"  # 优先序
    assert api_key({"XX_LLM_API_KEY": "  ", "STEPFUN_API_KEY": " k2 "}) == "k2"  # 空白跳过
    assert api_key({"XX_LLM_API_KEY": None, "STEPFUN_API_KEY": "k2"}) == "k2"    # 非 str 跳过
    assert api_key({"STEPFUN_API_KEY": "sk-b"}) == "sk-b"
    with pytest.raises(LLMError) as ei:
        api_key({})
    assert "not set" in str(ei.value)
    assert "XX_LLM_API_KEY" in str(ei.value) and "STEPFUN_API_KEY" in str(ei.value)
    assert "k1" not in str(ei.value)  # 错误不回显任何候选值


def test_api_key_reads_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("XX_LLM_API_KEY", " sk-env ")
    monkeypatch.delenv("STEPFUN_API_KEY", raising=False)
    assert api_key() == "sk-env"
    monkeypatch.delenv("XX_LLM_API_KEY", raising=False)
    monkeypatch.setenv("STEPFUN_API_KEY", "sk-fallback")
    assert api_key() == "sk-fallback"
    monkeypatch.delenv("STEPFUN_API_KEY", raising=False)
    with pytest.raises(LLMError):
        api_key()


# ---------- I2/I3 白名单六重门 ----------

def test_check_url_accepts_public_v4_v6_and_case_insensitive_host():
    assert check_url("https://api.stepfun.com/x", resolve=lambda h: ["8.8.8.8"]) is None
    assert check_url("https://API.STEPFUN.COM/v1/a", resolve=lambda h: ["2606:4700::1111"]) is None
    assert check_url("https://api.stepfun.com:443/x", resolve=lambda h: ["8.8.8.8"]) is None  # 显式 443 合法


def test_check_url_rejects_scheme_host_port_userinfo_and_garbage():
    def blocked(url, ips=_PUBLIC):
        with pytest.raises(LLMError):
            check_url(url, resolve=lambda h: ips)

    blocked("http://api.stepfun.com/x")                       # scheme
    blocked("ftp://api.stepfun.com/x")                        # scheme
    blocked("https://evil.com/x")                             # host
    blocked("https://api.stepfun.com.evil.com/x")             # host 后缀伪装
    blocked("https://api.stepfun.com:8443/x")                 # 显式非 443 端口
    blocked("https://user:pass@api.stepfun.com/x")            # userinfo
    blocked("https://u@api.stepfun.com/x")                    # 仅 username
    blocked("not a url")                                      # 垃圾输入
    blocked("")                                               # 空串
    blocked(42)                                               # 非 str
    blocked(None)


def test_check_url_blocks_private_address_families():
    bad = ["10.0.0.5", "127.0.0.1", "169.254.1.9", "198.51.100.23", "172.16.0.9",
           "fe80::1", "::1", "0.0.0.0", "224.0.0.1", "240.0.0.1", "255.255.255.255",
           "fc00::9"]
    for ip in bad:  # 每个私网族成员单独即拒
        assert ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_loopback \
            or ipaddress.ip_address(ip).is_link_local or ipaddress.ip_address(ip).is_reserved \
            or ipaddress.ip_address(ip).is_multicast or ipaddress.ip_address(ip).is_unspecified
        with pytest.raises(LLMError):
            check_url("https://api.stepfun.com/x", resolve=lambda h, _ip=ip: [_ip])
    with pytest.raises(LLMError):  # 公私混合：任一坏即全拒
        check_url("https://api.stepfun.com/x",
                  resolve=lambda h: ["8.8.8.8", "10.0.0.5"])
    assert check_url("https://api.stepfun.com/x",
                     resolve=lambda h: ["8.8.8.8", "2606:4700::1111"]) is None  # 全公网过


def test_check_url_resolver_failures():
    def boom(host):
        raise OSError("dns down")

    with pytest.raises(LLMError) as ei:
        check_url("https://api.stepfun.com/x", resolve=boom)
    assert "resolve failed" in str(ei.value)
    for bad_out in ([], ["not-an-ip"], [b"8.8.8.8"], ["8.8.8.8", ""]):
        with pytest.raises(LLMError):
            check_url("https://api.stepfun.com/x", resolve=lambda h, o=bad_out: o)


# ---------- I7 构造纯函数：data_url / vision_content / multipart_body ----------

def test_data_url_closed_forms_and_guards():
    assert data_url(b"\x00", "png") == "data:image/png;base64,AA=="
    assert data_url(b"abc", "jpeg") == "data:image/jpeg;base64,YWJj"
    assert data_url(b"abc", "jpg") == "data:image/jpeg;base64,YWJj"  # 别名同 mime
    assert data_url(b"\x89PNG\r\n\x1a\n", "png") == "data:image/png;base64,iVBORw0KGgo="
    for bad in (("", "png"), (None, "png"), (5, "png")):
        with pytest.raises(LLMError):
            data_url(*bad)
    for fmt in ("bmp", "", "PNG", None, 5):  # 大小写敏感、白名单外
        with pytest.raises(LLMError):
            data_url(b"x", fmt)
    with pytest.raises(LLMError):
        data_url(b"", "png")  # 空 bytes


def test_vision_content_shape_and_guards():
    img = b"\x01\x02"
    assert vision_content("看图", [img, "data:image/png;base64,AAA"]) == [
        {"type": "text", "text": "看图"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AQI="}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
    ]  # text 在前、bytes 编码、data URL 透传、按入参序
    assert vision_content("看图", [img], image_format="jpeg")[1][
        "image_url"]["url"] == "data:image/jpeg;base64,AQI="
    for prompt in ("", "  ", None, 5):
        with pytest.raises(LLMError):
            vision_content(prompt, [img])
    for images in ([], (), "abc", None, 5, [""], ["http://x/y.png"], ["data:text/html,x"],
                   [b""], [5], ["data:image/png;base64,AAA", 42]):
        with pytest.raises(LLMError):
            vision_content("看图", images)
    with pytest.raises(LLMError):
        vision_content("看图", [img], image_format="bmp")


def test_multipart_body_closed_form_and_collision_guards():
    body, content_type = multipart_body(
        {"model": "stepaudio-2.5-asr"}, "file", "answer.wav", b"RIFFMOCKWAV")
    assert body == (
        b"--xuexing-mm-boundary-v1\r\n"
        b'Content-Disposition: form-data; name="model"\r\n'
        b"\r\n"
        b"stepaudio-2.5-asr\r\n"
        b"--xuexing-mm-boundary-v1\r\n"
        b'Content-Disposition: form-data; name="file"; filename="answer.wav"\r\n'
        b"Content-Type: application/octet-stream\r\n"
        b"\r\n"
        b"RIFFMOCKWAV"
        b"\r\n--xuexing-mm-boundary-v1--\r\n")
    assert content_type == MULTIPART_CONTENT_TYPE
    assert multipart_body({"m": "x"}, "f", "a.wav", b"z") == multipart_body(
        {"m": "x"}, "f", "a.wav", b"z")  # 同输入同字节
    with pytest.raises(LLMError):
        multipart_body({"m": BOUNDARY}, "f", "a.wav", b"z")      # 字段值碰撞
    with pytest.raises(LLMError):
        multipart_body({"m": "x"}, "f", "a.wav", b"--" + BOUNDARY.encode())  # 文件体碰撞
    with pytest.raises(LLMError):
        multipart_body({"m": "x"}, "f", BOUNDARY + ".wav", b"z")  # filename 碰撞
    for args in (({"m": "x"}, "f", "a.wav", b""),                 # 空文件
                 ({"m": "x"}, "", "a.wav", b"z"),                 # 空 file_field
                 ({"m": "x"}, "f", "", b"z"),                     # 空 filename
                 ("not-a-mapping", "f", "a.wav", b"z"),           # fields 非映射
                 ({"m": "x"}, "f", "a.wav", "str-not-bytes")):    # 文件非 bytes
        with pytest.raises(LLMError):
            multipart_body(*args)
    with pytest.raises(LLMError):
        multipart_body({"m": "x"}, "f", "a.wav", b"z", boundary="")  # 空边界
    with pytest.raises(LLMError):
        multipart_body({5: "x"}, "f", "a.wav", b"z")             # 非 str 键


# ---------- I10 MockTransport 确定性 ----------

def test_mock_transport_defaults_recording_and_unknown_url():
    mt = MockTransport()
    url = ENDPOINTS["chat"]
    status, body = mt.post(url, headers={"Authorization": "Bearer k"},
                           body=b"x", content_type="application/json", timeout=1.5)
    assert (status, body) == (200, MockTransport.DEFAULT_REPLIES["chat"][1])
    assert json.loads(body)["choices"][0]["message"]["content"] == "模拟回答"
    assert len(mt.calls) == 1
    assert mt.calls[0] == {"url": url, "headers": {"Authorization": "Bearer k"},
                           "body": b"x", "content_type": "application/json",
                           "timeout": 1.5}
    s2, b2 = mt.post("https://api.stepfun.com/other", headers={}, body=b"",
                     content_type="application/json", timeout=1.0)
    assert (s2, b2) == (404, b'{"error":"mock: unknown url"}')  # 未知 URL
    assert json.loads(MockTransport.DEFAULT_REPLIES["asr"][1])["text"] == "模拟转写"
    assert MockTransport.DEFAULT_REPLIES["tts"] == (200, b"ID3MOCKMP3")
    over = MockTransport(replies={"tts": (500, b"boom")})       # 覆盖生效且不改默认表
    assert over.replies["tts"] == (500, b"boom")
    assert MockTransport.DEFAULT_REPLIES["tts"] == (200, b"ID3MOCKMP3")


# ---------- 构造守卫 ----------

def test_client_construction_guards_fail_fast():
    class _NoPost:
        pass

    with pytest.raises(LLMError):
        MMClient(_NoPost(), env=_ENV, resolve=_RESOLVE_OK)       # transport 无 post
    for env in ({}, {"XX_LLM_API_KEY": "  "}):
        with pytest.raises(LLMError):                            # key 缺失在构造期
            MMClient(MockTransport(), env=env, resolve=_RESOLVE_OK)
    good = MockTransport()
    for kw in (dict(model=""), dict(model="  "), dict(tts_model=None),
               dict(asr_model=5), dict(voice="")):
        with pytest.raises(LLMError):
            MMClient(good, env=_ENV, resolve=_RESOLVE_OK, **kw)
    for timeout in (0, -1, 0.0, float("inf"), float("nan"), True, "5", None):
        with pytest.raises(LLMError):
            MMClient(good, env=_ENV, resolve=_RESOLVE_OK, timeout=timeout)


def test_client_defaults_and_attributes():
    client, _ = _client()
    assert (client.model, client.tts_model, client.asr_model, client.voice,
            client.timeout) == (MODEL_CHAT, MODEL_TTS, MODEL_ASR, TTS_VOICE,
                                DEFAULT_TIMEOUT)
    custom, _ = _client(model="step-3.7-flash", timeout=5)
    assert custom.model == "step-3.7-flash" and custom.timeout == 5.0
    assert isinstance(custom.timeout, float)


# ---------- I5/I6 chat ----------

def test_client_chat_closed_form_request_and_reply():
    client, mt = _client()
    assert client.chat("你好") == "模拟回答"
    assert len(mt.calls) == 1
    call = mt.calls[0]
    assert call["url"] == ENDPOINTS["chat"]
    assert call["headers"] == {"Authorization": f"Bearer {_KEY}",
                               "Content-Type": "application/json"}
    assert call["content_type"] == "application/json"
    assert call["timeout"] == 60.0
    assert json.loads(call["body"]) == {
        "model": MODEL_CHAT, "messages": [{"role": "user", "content": "你好"}]}
    assert call["body"] == json.dumps(  # 字节级闭式（CPython 3.12 默认分隔符）
        {"model": "step-5-preview",
         "messages": [{"role": "user", "content": "你好"}]},
        ensure_ascii=False).encode("utf-8")


def test_client_chat_system_message_and_determinism():
    client, mt = _client()
    client.chat("你好", system="你是数学老师")
    payload = json.loads(mt.calls[-1]["body"])
    assert payload["messages"] == [{"role": "system", "content": "你是数学老师"},
                                   {"role": "user", "content": "你好"}]
    client.chat("你好")  # 无 system：不含 system 条目
    assert json.loads(mt.calls[-1]["body"])["messages"] == [
        {"role": "user", "content": "你好"}]
    body1 = mt.calls[-2]["body"]
    client.chat("你好", system="你是数学老师")
    assert mt.calls[-1]["body"] == body1  # 同输入同字节（I5）
    assert mt.calls[-2]["headers"] == mt.calls[-1]["headers"]


def test_client_chat_guards_no_transport_call():
    client, mt = _client()
    for text in ("", "  ", None, 5):
        with pytest.raises(LLMError):
            client.chat(text)
    for system in ("", "  ", 5):
        with pytest.raises(LLMError):
            client.chat("你好", system=system)
    assert mt.calls == []  # 守卫失败零出网


# ---------- I7 vision ----------

def test_client_vision_payload_and_shared_endpoint():
    client, mt = _client()
    png_header = b"\x89PNG\r\n\x1a\n"
    assert client.vision("图里是什么颜色？", [png_header]) == "模拟回答"
    call = mt.calls[-1]
    assert call["url"] == ENDPOINTS["chat"]  # vision 与 chat 同端点
    payload = json.loads(call["body"])
    assert payload["model"] == MODEL_CHAT
    assert payload["messages"] == [{"role": "user", "content": [
        {"type": "text", "text": "图里是什么颜色？"},
        {"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(png_header).decode("ascii")}},
    ]}]
    client.vision("多图", [png_header, "data:image/jpeg;base64,YWJj"], image_format="jpg")
    content = json.loads(mt.calls[-1]["body"])["messages"][0]["content"]
    assert [seg["image_url"]["url"] for seg in content[1:]] == [
        "data:image/jpeg;base64,iVBORw0KGgo=",  # image_format 按次生效：jpg -> image/jpeg
        "data:image/jpeg;base64,YWJj",          # data URL 原样透传，不受 format 影响
    ]


def test_client_vision_guards_no_transport_call():
    client, mt = _client()
    for args in (("", [b"x"]), ("  ", [b"x"]), (None, [b"x"]),
                 ("看图", []), ("看图", "abc"), ("看图", [b""]),
                 ("看图", ["http://x/y.png"]), ("看图", [42])):
        with pytest.raises(LLMError):
            client.vision(*args)
    with pytest.raises(LLMError):
        client.vision("看图", [b"x"], image_format="bmp")
    assert mt.calls == []


# ---------- I8 tts ----------

def test_client_tts_closed_form_request_and_raw_reply():
    client, mt = _client()
    assert client.tts("九九乘法表") == b"ID3MOCKMP3"
    call = mt.calls[-1]
    assert call["url"] == ENDPOINTS["tts"]
    assert call["headers"] == {"Authorization": f"Bearer {_KEY}",
                               "Content-Type": "application/json"}
    payload = json.loads(call["body"])
    assert payload == {"model": MODEL_TTS, "input": "九九乘法表",
                       "voice": TTS_VOICE, "response_format": TTS_FORMAT}
    assert call["body"] == json.dumps(payload, ensure_ascii=False).encode("utf-8")
    client.tts("短句", voice="other-voice", response_format="wav")
    assert json.loads(mt.calls[-1]["body"]) == {
        "model": MODEL_TTS, "input": "短句", "voice": "other-voice",
        "response_format": "wav"}


def test_client_tts_returns_200_body_verbatim():
    client, _ = _client(transport=MockTransport(replies={"tts": (200, b'{"not":"audio"}')}))
    assert client.tts("任意") == b'{"not":"audio"}'  # 唯一宽容点：字节原样，不解析


def test_client_tts_guards_no_transport_call():
    client, mt = _client()
    for text in ("", " ", None, 5):
        with pytest.raises(LLMError):
            client.tts(text)
    with pytest.raises(LLMError):
        client.tts("文本", voice="")
    with pytest.raises(LLMError):
        client.tts("文本", voice="  ")
    with pytest.raises(LLMError):
        client.tts("文本", response_format="")
    with pytest.raises(LLMError):
        client.tts("文本", response_format=None)
    assert mt.calls == []


# ---------- I9 asr ----------

def test_client_asr_closed_form_request_and_reply():
    client, mt = _client()
    assert client.asr(b"RIFFMOCKWAV", filename="answer.wav") == "模拟转写"
    call = mt.calls[-1]
    assert call["url"] == ENDPOINTS["asr"]
    assert call["headers"] == {"Authorization": f"Bearer {_KEY}",
                               "Content-Type": MULTIPART_CONTENT_TYPE}
    assert call["content_type"] == MULTIPART_CONTENT_TYPE
    assert call["body"] == (                               # 与 multipart_body 同字节
        multipart_body({"model": MODEL_ASR}, "file", "answer.wav",
                       b"RIFFMOCKWAV")[0])
    assert client.asr(b"x") == "模拟转写"                   # 默认 filename=audio.wav
    assert b'filename="audio.wav"' in mt.calls[-1]["body"]


def test_client_asr_guards_no_transport_call():
    client, mt = _client()
    for audio in (b"", None, "", 5):
        with pytest.raises(LLMError):
            client.asr(audio)
    with pytest.raises(LLMError):
        client.asr(b"x", filename="")
    with pytest.raises(LLMError):
        client.asr(b"x", filename="  ")
    assert mt.calls == []


# ---------- I11 错误归族 + key 不回显 ----------

def test_client_http_and_shape_errors_never_leak_key():
    client, mt = _client(transport=MockTransport(replies={
        "chat": (500, b"boom"), "tts": (503, b"busy"), "asr": (401, b"denied")}))
    with pytest.raises(LLMError) as ei:
        client.chat("你好")
    assert "500" in str(ei.value) and _KEY not in str(ei.value)
    with pytest.raises(LLMError) as ei:
        client.tts("文本")
    assert "503" in str(ei.value) and _KEY not in str(ei.value)
    with pytest.raises(LLMError) as ei:
        client.asr(b"x")
    assert "401" in str(ei.value) and _KEY not in str(ei.value)
    assert len(mt.calls) == 3  # 请求确实发出过（错误来自响应侧）


def test_client_bad_response_bodies():
    for bad_body in (b"not json", b"[1,2]", b'{"choices": []}',
                     b'{"choices": [{}]}', b'{"choices": [{"message": {}}]}',
                     b'{"choices": [{"message": {"content": 42}}]}',
                     b'{"choices": [{"message": {"content": null}}]}'):
        client, _ = _client(transport=MockTransport(replies={"chat": (200, bad_body)}))
        with pytest.raises(LLMError) as ei:
            client.chat("你好")
        assert "bad chat response" in str(ei.value)
        with pytest.raises(LLMError) as ei:
            client.vision("看图", [b"x"])
        assert "bad chat response" in str(ei.value)
    for bad_body in (b"not json", b'{"nope": 1}', b'{"text": 5}', b'[]'):
        client, _ = _client(transport=MockTransport(replies={"asr": (200, bad_body)}))
        with pytest.raises(LLMError) as ei:
            client.asr(b"x")
        assert "bad asr response" in str(ei.value)


def test_client_env_priority_in_authorization_header():
    client, mt = _client(env={"XX_LLM_API_KEY": " sk-A ", "STEPFUN_API_KEY": "sk-B"})
    client.chat("你好")
    assert mt.calls[-1]["headers"]["Authorization"] == "Bearer sk-A"  # XX 优先 + strip
    client2, mt2 = _client(env={"STEPFUN_API_KEY": " sk-B "})
    client2.chat("你好")
    assert mt2.calls[-1]["headers"]["Authorization"] == "Bearer sk-B"  # 回落


# ---------- I12 纯函数性 ----------

def test_inputs_not_mutated_across_all_four_capabilities():
    client, mt = _client()
    text, prompt, images = "文本输入", "图里是什么？", [b"\x01\x02", "data:image/png;base64,AAA"]
    audio, filename = b"RIFFMOCKWAV", "answer.wav"
    snap = (text, prompt, copy.deepcopy(images), audio, filename)
    client.chat(text, system="s")
    client.vision(prompt, images)
    client.tts(text)
    client.asr(audio, filename=filename)
    assert (text, prompt, images, audio, filename) == snap  # 入参深对比不变
    assert len(mt.calls) == 4


# ---------- I13 冒烟门（env-gated；默认 skip，契约套件零网络） ----------

def _tiny_red_png() -> bytes:
    """确定性生成 1×1 纯红 PNG（stdlib struct+zlib，仅冒烟用例使用）。"""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1、8bit、RGB
    idat = zlib.compress(b"\x00\xff\x00\x00")            # filter 0 + 红像素
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _smoke_enabled() -> bool:
    if os.environ.get("XX_MM_SMOKE") != "1":
        return False
    try:
        api_key()
    except LLMError:
        return False
    return True


@pytest.mark.skipif(not _smoke_enabled(),
                    reason="冒烟默认关闭：需 XX_MM_SMOKE=1 且环境含 XX_LLM_API_KEY/STEPFUN_API_KEY")
def test_smoke_real_stepfun_api():
    from xuexing.mm_client import HttpTransport  # 仅参考生产传输（唯一网络豁免）

    client = MMClient(HttpTransport())  # key/解析走真实环境（默认缺省参数）
    text = client.chat("只回复两个字：在线")
    assert isinstance(text, str) and text.strip()
    color = client.vision("这张纯色图是什么颜色？只回复一个颜色词。", [_tiny_red_png()])
    assert isinstance(color, str)
    audio = client.tts("一加一等于二。")
    assert isinstance(audio, bytes) and len(audio) > 0
    heard = client.asr(audio, filename="smoke.mp3")  # TTS->ASR 回环
    assert isinstance(heard, str)
