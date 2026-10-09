#!/usr/bin/env python3
"""GigE camera browser preview driven by MVS software triggers."""

import argparse
import ctypes
import json
import os
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


SDK_ROOT = Path(os.environ.get("MVCAM_SDK_PATH", "/opt/MVS"))
os.environ.setdefault("MVCAM_COMMON_RUNENV", str(SDK_ROOT / "lib"))
sys.path.insert(0, str(SDK_ROOT / "Samples/64/Python/MvImport"))

try:
    from MvCameraControl_class import (  # noqa: E402
        MV_ACCESS_Exclusive,
        MV_CC_DEVICE_INFO,
        MV_CC_DEVICE_INFO_LIST,
        MV_FRAME_OUT,
        MV_GIGE_DEVICE,
        MV_Image_Jpeg,
        MV_NETTRANS_INFO,
        MV_SAVE_IMAGE_PARAM_EX3,
        MV_TRIGGER_MODE_ON,
        MVCC_ENUMVALUE,
        MVCC_INTVALUE,
        MvCamera,
        PixelType_Gvsp_BayerRG8,
    )
except (ImportError, OSError, TypeError) as exc:
    raise SystemExit(
        f"无法加载海康 MVS SDK：{exc}\n"
        "请确认 /opt/MVS 已安装，并设置 LD_LIBRARY_PATH=/opt/MVS/lib/64"
    ) from exc


PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>海康工业相机实时采集</title>
<style>
  :root{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#e9edf7;background:#10141d}
  *{box-sizing:border-box}body{margin:0}.wrap{max-width:1440px;margin:auto;padding:24px}
  h1{font-size:1.45rem;margin:0 0 8px}.muted{color:#aab5c9}.head{display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap}
  .pill{border-radius:100px;background:#293141;padding:7px 13px;font-size:.9rem}
  .panel{background:#1a2230;border:1px solid #303c50;border-radius:14px;padding:16px;margin-top:18px}
  .controls{display:flex;gap:12px;align-items:center;flex-wrap:wrap}button{border:0;border-radius:9px;padding:10px 17px;cursor:pointer;background:#3d8df5;color:white;font-size:1rem}
  button.secondary{background:#3b475b}button:disabled{opacity:.5;cursor:wait}
  input[type=range]{width:220px;accent-color:#5aa5ff}input[type=number],select{border:1px solid #536078;border-radius:7px;background:#111923;color:white;padding:7px;font:inherit}input[type=number]{width:64px}
  .preview{display:grid;place-items:center;min-height:55vh;background:#07090d;border-radius:10px;overflow:hidden}
  .preview img{display:block;max-width:100%;max-height:75vh;object-fit:contain}.stats{display:flex;gap:20px;flex-wrap:wrap;margin-top:12px;color:#b8c5d9;font-size:.92rem}
  #error{color:#ff9d9d;min-height:1.2em;margin-top:9px;white-space:pre-wrap}
</style></head><body><div class="wrap">
<div class="head"><div><h1>海康工业相机 · 软件触发采集</h1><div class="muted">MV-CU060-10GC · <span id="camera-ip"></span></div></div><div id="state" class="pill">连接中…</div></div>
<div class="panel controls"><button id="toggle">暂停采集</button><button id="shot" class="secondary">单次触发</button><label for="fps">目标帧率</label><input id="fps" type="range" min="1" max="20" value="5"><input id="fps-number" type="number" min="1" max="20" value="5"><span>帧/秒</span><label for="decimation">相机 Decimation</label><select id="decimation"><option value="1">1× 原始</option><option value="2">2×（数据约 1/4）</option><option value="4">4×（数据约 1/16）</option></select></div>
<div class="panel"><div class="preview"><img id="image" src="/stream" alt="等待相机图像"></div><div class="stats"><span>实际帧率：<b id="actual">0</b> FPS</span><span>相机接收带宽：<b id="bandwidth">0</b> Mb/s（<b id="bandwidth-percent">0</b>% 千兆网口）</span><span>图像尺寸：<b id="size">—</b></span><span>帧号：<b id="frame">—</b></span></div><div id="error"></div></div>
</div><script>
const $=id=>document.getElementById(id); let running=true;
async function control(data){try{const r=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const result=await r.json();if(!r.ok)throw Error(result.error||'操作失败');update(result)}catch(e){$('error').textContent=e.message}}
function update(s){running=s.running;$('state').textContent=s.error?'相机错误':(running?'采集中':'已暂停');$('toggle').textContent=running?'暂停采集':'开始采集';$('camera-ip').textContent=s.ip;$('actual').textContent=s.actual_fps.toFixed(1);$('bandwidth').textContent=s.bandwidth_mbps.toFixed(1);$('bandwidth-percent').textContent=s.bandwidth_percent.toFixed(1);$('size').textContent=s.width?`${s.width} × ${s.height}`:'—';$('frame').textContent=s.frame_number??'—';$('error').textContent=s.error||'';if(document.activeElement!==$('fps-number'))$('fps-number').value=s.fps;$('fps').value=s.fps;if(!$('decimation').disabled)$('decimation').value=s.decimation}
$('toggle').onclick=()=>control({running:!running});$('shot').onclick=()=>control({trigger:true});
$('fps').oninput=()=>{$('fps-number').value=$('fps').value};$('fps').onchange=()=>control({fps:Number($('fps').value)});
$('fps-number').onchange=()=>{let n=Math.max(1,Math.min(20,Number($('fps-number').value)||1));$('fps').value=n;control({fps:n})};
$('decimation').onchange=async()=>{const el=$('decimation');el.disabled=true;await control({decimation:Number(el.value)});el.disabled=false};
setInterval(async()=>{try{const r=await fetch('/api/status');update(await r.json())}catch(e){$('state').textContent='服务断开'}},600);
fetch('/api/status').then(r=>r.json()).then(update);
</script></body></html>"""


def check(ret, operation):
    if ret != 0:
        raise RuntimeError(f"{operation} 失败，SDK 错误码 0x{ret:08x}")


class Camera:
    def __init__(self, ip, fps, width, height, exposure_us, decimation):
        self.ip = ip
        self.fps = fps
        self.capture_width = width
        self.capture_height = height
        self.exposure_us = exposure_us
        self.decimation = decimation
        self.running = True
        self.manual_pending = 0
        self.error = ""
        self.width = 0
        self.height = 0
        self.frame_number = None
        self.jpeg = None
        self.sequence = 0
        self.timestamps = deque()
        self.net_samples = deque()
        self.config_requests = deque()
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.thread = None
        self.cam = None
        self._initialized = False
        self._created = False
        self._opened = False
        self._grabbing = False
        self._jpeg_buffer = None

    def open(self):
        check(MvCamera.MV_CC_Initialize(), "初始化 SDK")
        self._initialized = True
        devices = MV_CC_DEVICE_INFO_LIST()
        check(MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE, devices), "枚举相机")
        target_ip = tuple(int(part) for part in self.ip.split("."))
        chosen = None
        for index in range(devices.nDeviceNum):
            info = ctypes.cast(devices.pDeviceInfo[index], ctypes.POINTER(MV_CC_DEVICE_INFO)).contents
            raw_ip = info.SpecialInfo.stGigEInfo.nCurrentIp
            found_ip = tuple((raw_ip >> shift) & 255 for shift in (24, 16, 8, 0))
            if found_ip == target_ip:
                chosen = info
                model = bytes(info.SpecialInfo.stGigEInfo.chModelName).split(b"\0", 1)[0].decode("ascii", "replace")
                print(f"找到相机 {model} @ {self.ip}", flush=True)
                break
        if chosen is None:
            raise RuntimeError(f"未发现 {self.ip} 的 GigE 相机；请检查网卡地址和 MVS 中的设备状态")

        self.cam = MvCamera()
        check(self.cam.MV_CC_CreateHandle(chosen), "创建相机句柄")
        self._created = True
        check(self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0), "打开相机")
        self._opened = True
        packet_size = self.cam.MV_CC_GetOptimalPacketSize()
        if packet_size > 0:
            ret = self.cam.MV_CC_SetIntValue("GevSCPSPacketSize", packet_size)
            if ret != 0:
                print(f"警告：设置网络包大小失败：0x{ret:08x}", file=sys.stderr)
        # 先回到 1× 配置 ROI；之后由相机对完整 ROI 做硬件降采样。
        check(self.cam.MV_CC_SetEnumValue("DecimationHorizontal", 1), "重置降采样")
        check(self.cam.MV_CC_SetIntValue("Width", self.capture_width), "设置图像宽度")
        check(self.cam.MV_CC_SetIntValue("Height", self.capture_height), "设置图像高度")
        check(self.cam.MV_CC_SetEnumValue("DecimationHorizontal", self.decimation), "设置降采样")
        self._verify_decimation(self.decimation)
        check(self.cam.MV_CC_SetEnumValue("PixelFormat", PixelType_Gvsp_BayerRG8), "设置 BayerRG8 像素格式")
        check(self.cam.MV_CC_SetEnumValueByString("ExposureAuto", "Off"), "关闭自动曝光")
        check(self.cam.MV_CC_SetFloatValue("ExposureTime", float(self.exposure_us)), "设置曝光时间")
        check(self.cam.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", False), "关闭相机内部帧率限制")
        # 这台相机的 TriggerSelector 只支持 FrameBurstStart，出厂突发帧数为 10。
        # 每次软件触发只采一帧，避免触发积压造成取流超时。
        check(self.cam.MV_CC_SetIntValue("AcquisitionBurstFrameCount", 1), "设置每次触发一帧")
        check(self.cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_ON), "开启触发模式")
        check(self.cam.MV_CC_SetEnumValueByString("TriggerSource", "Software"), "设置软件触发源")
        check(self.cam.MV_CC_StartGrabbing(), "开始取流")
        self._grabbing = True
        time.sleep(0.2)
        self.thread = threading.Thread(target=self._capture_loop, name="camera-capture", daemon=True)
        self.thread.start()

    def _read_dimension(self, name):
        value = MVCC_INTVALUE()
        check(self.cam.MV_CC_GetIntValue(name, value), f"读取 {name}")
        return value.nCurValue

    def _verify_decimation(self, factor):
        for name in ("DecimationHorizontal", "DecimationVertical"):
            value = MVCC_ENUMVALUE()
            check(self.cam.MV_CC_GetEnumValue(name, value), f"读取 {name}")
            if value.nCurValue != factor:
                raise RuntimeError(f"相机的 {name} 未切换到 {factor}×")

    def _change_decimation(self, factor):
        previous = self.decimation
        check(self.cam.MV_CC_StopGrabbing(), "暂停取流以调整降采样")
        self._grabbing = False
        try:
            check(self.cam.MV_CC_SetEnumValue("DecimationHorizontal", factor), "切换降采样")
            self._verify_decimation(factor)
            width = self._read_dimension("Width")
            height = self._read_dimension("Height")
            check(self.cam.MV_CC_StartGrabbing(), "重新开始取流")
            self._grabbing = True
            with self.condition:
                self.decimation = factor
                self.width, self.height = width, height
                self.frame_number = None
                self.timestamps.clear()
                self.net_samples.clear()
                self.jpeg = None
                self.sequence += 1
                self.condition.notify_all()
        except Exception:
            self.cam.MV_CC_SetEnumValue("DecimationHorizontal", previous)
            if not self._grabbing and self.cam.MV_CC_StartGrabbing() == 0:
                self._grabbing = True
            raise

    def _capture_loop(self):
        next_trigger = time.monotonic()
        while not self.stop_event.is_set():
            with self.condition:
                request = self.config_requests.popleft() if self.config_requests else None
                running = self.running
                fps = self.fps
                manual = self.manual_pending > 0
                if manual and request is None:
                    self.manual_pending -= 1
            if request is not None:
                try:
                    self._change_decimation(request["factor"])
                    with self.condition:
                        self.error = ""
                except Exception as exc:
                    request["error"] = str(exc)
                    with self.condition:
                        self.error = str(exc)
                    print(f"降采样切换错误：{exc}", file=sys.stderr, flush=True)
                finally:
                    request["event"].set()
                next_trigger = time.monotonic()
                continue
            now = time.monotonic()
            if not running and not manual:
                self.stop_event.wait(0.05)
                next_trigger = time.monotonic()
                continue
            if running and not manual and now < next_trigger:
                self.stop_event.wait(min(next_trigger - now, 0.05))
                continue
            if running:
                next_trigger = time.monotonic() + 1.0 / fps
            try:
                check(self.cam.MV_CC_SetCommandValue("TriggerSoftware"), "发送软件触发")
                frame = MV_FRAME_OUT()
                ret = self.cam.MV_CC_GetImageBuffer(frame, 1500)
                if ret != 0:
                    raise RuntimeError(f"等待图像超时或取流失败：0x{ret:08x}")
                try:
                    jpeg = self._encode_jpeg(frame)
                    info = frame.stFrameInfo
                    width, height, frame_number = info.nWidth, info.nHeight, info.nFrameNum
                finally:
                    check(self.cam.MV_CC_FreeImageBuffer(frame), "释放图像缓存")
                now = time.monotonic()
                net_info = MV_NETTRANS_INFO()
                net_ret = self.cam.MV_GIGE_GetNetTransInfo(net_info)
                with self.condition:
                    self.jpeg = jpeg
                    self.width, self.height, self.frame_number = width, height, frame_number
                    self.timestamps.append(now)
                    while self.timestamps and now - self.timestamps[0] > 2.0:
                        self.timestamps.popleft()
                    if net_ret == 0:
                        self.net_samples.append((now, net_info.nReceiveDataSize))
                        while self.net_samples and now - self.net_samples[0][0] > 2.0:
                            self.net_samples.popleft()
                    self.error = ""
                    self.sequence += 1
                    self.condition.notify_all()
            except Exception as exc:
                with self.condition:
                    self.error = str(exc)
                    self.condition.notify_all()
                print(f"采集错误：{exc}", file=sys.stderr, flush=True)
                self.stop_event.wait(0.5)

    def _encode_jpeg(self, frame):
        info = frame.stFrameInfo
        capacity = info.nWidth * info.nHeight * 4 + 4096
        if self._jpeg_buffer is None or len(self._jpeg_buffer) < capacity:
            self._jpeg_buffer = (ctypes.c_ubyte * capacity)()
        params = MV_SAVE_IMAGE_PARAM_EX3()
        params.pData = frame.pBufAddr
        params.nDataLen = info.nFrameLen
        params.enPixelType = info.enPixelType
        params.nWidth = info.nWidth
        params.nHeight = info.nHeight
        params.pImageBuffer = self._jpeg_buffer
        params.nBufferSize = len(self._jpeg_buffer)
        params.enImageType = MV_Image_Jpeg
        params.nJpgQuality = 80
        params.iMethodValue = 1
        check(self.cam.MV_CC_SaveImageEx3(params), "JPEG 编码")
        return ctypes.string_at(self._jpeg_buffer, params.nImageLen)

    def status(self):
        with self.condition:
            now = time.monotonic()
            while self.timestamps and now - self.timestamps[0] > 2.0:
                self.timestamps.popleft()
            times = list(self.timestamps)
            actual_fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 else 0.0
            while self.net_samples and now - self.net_samples[0][0] > 2.0:
                self.net_samples.popleft()
            samples = list(self.net_samples)
            bandwidth_mbps = (8 * (samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0]) / 1_000_000
                              if len(samples) > 1 and samples[-1][0] > samples[0][0] else 0.0)
            return {"ip": self.ip, "fps": self.fps, "running": self.running,
                    "actual_fps": actual_fps, "width": self.width, "height": self.height,
                    "frame_number": self.frame_number, "error": self.error,
                    "decimation": self.decimation, "bandwidth_mbps": bandwidth_mbps,
                    "bandwidth_percent": bandwidth_mbps / 10.0}

    def control(self, data):
        if not isinstance(data, dict) or not set(data).issubset({"fps", "running", "trigger", "decimation"}):
            raise ValueError("无效的控制参数")
        if "fps" in data and (type(data["fps"]) is not int or not 1 <= data["fps"] <= 20):
            raise ValueError("帧率必须是 1 到 20 的整数")
        if "running" in data and type(data["running"]) is not bool:
            raise ValueError("running 必须是布尔值")
        if "trigger" in data and type(data["trigger"]) is not bool:
            raise ValueError("trigger 必须是布尔值")
        if "decimation" in data and (type(data["decimation"]) is not int or data["decimation"] not in (1, 2, 4)):
            raise ValueError("Decimation 只能是 1、2 或 4")
        request = None
        with self.condition:
            if "fps" in data:
                self.fps = data["fps"]
            if "running" in data:
                self.running = data["running"]
            if data.get("trigger"):
                self.manual_pending += 1
            if "decimation" in data and data["decimation"] != self.decimation:
                request = {"factor": data["decimation"], "event": threading.Event(), "error": None}
                self.config_requests.append(request)
        if request is not None:
            if not request["event"].wait(timeout=6):
                raise RuntimeError("切换 Decimation 超时")
            if request["error"]:
                raise RuntimeError(request["error"])
        return self.status()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
        if self.cam:
            if self._grabbing:
                self.cam.MV_CC_StopGrabbing()
            if self._opened:
                self.cam.MV_CC_CloseDevice()
            if self._created:
                self.cam.MV_CC_DestroyHandle()
        if self._initialized:
            MvCamera.MV_CC_Finalize()


class Handler(BaseHTTPRequestHandler):
    camera = None

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            self._send_bytes(PAGE.encode(), "text/html; charset=utf-8")
        elif path == "/api/status":
            self._json(self.camera.status())
        elif path == "/stream":
            self._stream()
        else:
            self.send_error(404)

    def do_POST(self):
        if urlsplit(self.path).path != "/api/control":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("请求体大小无效")
            data = json.loads(self.rfile.read(length))
            self._json(self.camera.control(data))
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except RuntimeError as exc:
            self._json({"error": str(exc)}, 503)

    def _json(self, value, status=200):
        self._send_bytes(json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

    def _send_bytes(self, data, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        sequence = -1
        try:
            while not self.camera.stop_event.is_set():
                with self.camera.condition:
                    self.camera.condition.wait_for(lambda: self.camera.sequence != sequence or self.camera.stop_event.is_set(), timeout=2)
                    if self.camera.sequence == sequence or self.camera.jpeg is None:
                        continue
                    sequence = self.camera.sequence
                    jpeg = self.camera.jpeg
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n")
                self.wfile.write(jpeg + b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def log_message(self, format, *args):
        if not self.path.startswith("/api/status"):
            super().log_message(format, *args)


def main():
    parser = argparse.ArgumentParser(description="海康 GigE 软件触发实时网页预览")
    parser.add_argument("--ip", default="192.168.3.13", help="相机 IP 地址")
    parser.add_argument("--fps", type=int, default=5, help="启动帧率，范围 1–20")
    parser.add_argument("--width", type=int, default=3072, help="采集宽度，默认 3072")
    parser.add_argument("--height", type=int, default=2048, help="采集高度，默认 2048")
    parser.add_argument("--exposure-us", type=int, default=20000, help="曝光时间（微秒），默认 10000")
    parser.add_argument("--decimation", type=int, choices=(1, 2, 4), default=1, help="每轴硬件降采样倍数，默认 1")
    parser.add_argument("--host", default="127.0.0.1", help="网页监听地址")
    parser.add_argument("--port", type=int, default=8005, help="网页端口")
    args = parser.parse_args()
    if not 1 <= args.fps <= 20:
        parser.error("--fps 必须在 1 到 20 之间")
    if args.width <= 0 or args.height <= 0 or args.exposure_us <= 0:
        parser.error("宽、高和曝光时间必须为正整数")
    camera = Camera(args.ip, args.fps, args.width, args.height, args.exposure_us, args.decimation)
    try:
        camera.open()
        Handler.camera = camera
        with ThreadingHTTPServer((args.host, args.port), Handler) as server:
            print(f"打开 http://{args.host}:{args.port} ；按 Ctrl+C 停止", flush=True)
            try:
                server.serve_forever(poll_interval=0.2)
            except KeyboardInterrupt:
                pass
    finally:
        camera.close()


if __name__ == "__main__":
    main()
