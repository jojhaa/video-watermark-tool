import os
import sys
import subprocess
import shutil
import glob
import time
import re
import argparse
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# 自动寻找 ffmpeg 可执行文件
def get_ffmpeg_path():
    # 1. 优先从 PyInstaller 打包解压目录 sys._MEIPASS 查找
    if hasattr(sys, '_MEIPASS'):
        meipass_ffmpeg = os.path.join(sys._MEIPASS, "ffmpeg.exe")
        if os.path.isfile(meipass_ffmpeg):
            return meipass_ffmpeg

    # 2. 当前运行程序同级目录或 bin 目录
    script_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    local_paths = [
        os.path.join(script_dir, "ffmpeg.exe"),
        os.path.join(script_dir, "bin", "ffmpeg.exe"),
    ]
    for lp in local_paths:
        if os.path.isfile(lp):
            return lp

    # 3. 系统 PATH 环境变量
    ffmpeg_sys = shutil.which("ffmpeg")
    if ffmpeg_sys:
        return ffmpeg_sys
            
    # 4. 尝试 imageio_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
        
    return None

# 获取默认中文字体路径（优先使用内置免费开源商用的【思源黑体】）
def get_default_font():
    base_dirs = []
    if hasattr(sys, '_MEIPASS'):
        base_dirs.append(sys._MEIPASS)
    base_dirs.append(os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__)))
    
    for bdir in base_dirs:
        local_fonts = [
            os.path.join(bdir, "fonts", "SourceHanSansSC-Regular.ttf"),
            os.path.join(bdir, "fonts", "MiSans-Regular.ttf"),
            os.path.join(bdir, "fonts", "NotoSansSC-Regular.ttf"),
        ]
        for lf in local_fonts:
            if os.path.exists(lf):
                return lf.replace("\\", "/")
                
    win_font_dir = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
    candidates = [
        os.path.join(win_font_dir, "NotoSansSC-VF.ttf"), # 系统思源黑体
        os.path.join(win_font_dir, "msyh.ttc"),         # 微软雅黑
        os.path.join(win_font_dir, "simhei.ttf"),       # 黑体
    ]
    for font_path in candidates:
        if os.path.exists(font_path):
            return font_path.replace("\\", "/")
    return ""

def escape_ffmpeg_path(path):
    """转义 FFmpeg 路径中的特殊字符"""
    path = path.replace("\\", "/")
    path = path.replace(":", "\\:")
    return path

def build_drawtext_filter(text, font_path, font_size, font_color, opacity, mode, speed, stroke_color, stroke_width, preview_time=None):
    """构建 FFmpeg drawtext 动态/静态水印滤镜表达式"""
    if not text:
        return None
        
    escaped_font = escape_ffmpeg_path(font_path) if font_path else ""
    clean_text = text.replace("'", "'\\''").replace(":", "\\:").replace("%", "\\%")
    
    font_color_str = f"{font_color}@{opacity}"
    stroke_color_str = f"{stroke_color}@{opacity}"
    
    # 预览时使用精确的预览时间点进行坐标演算，确保动态轨迹在抓取单帧时精确处于该时间点所在坐标
    t_var = f"({preview_time})" if preview_time is not None else "t"
    
    if mode == "bounce":
        speed_x = speed * 80
        speed_y = speed * 50
        x_expr = f"abs(mod({t_var}*{speed_x}, 2*(w-tw+0.001)) - (w-tw+0.001))"
        y_expr = f"abs(mod({t_var}*{speed_y}, 2*(h-th+0.001)) - (h-th+0.001))"
    elif mode == "scroll":
        speed_x = speed * 120
        x_expr = f"w - mod({t_var}*{speed_x}, w+tw)"
        y_expr = "(h-th)/2"
    elif mode == "diagonal":
        speed_x = speed * 100
        speed_y = speed * 60
        x_expr = f"mod({t_var}*{speed_x}, w+tw) - tw"
        y_expr = f"mod({t_var}*{speed_y}, h+th) - th"
    elif mode == "jump":
        interval = max(1.0, 4.0 / speed)
        x_expr = f"mod(floor({t_var}/{interval})*3571, max(1, w-tw))"
        y_expr = f"mod(floor({t_var}/{interval})*7919, max(1, h-th))"
    elif mode == "static_center":
        x_expr = "(w-tw)/2"
        y_expr = "(h-th)/2"
    elif mode == "static_top_left":
        x_expr = "20"
        y_expr = "20"
    elif mode == "static_bottom_left":
        x_expr = "20"
        y_expr = "h-th-20"
    elif mode == "static_top_right":
        x_expr = "w-tw-20"
        y_expr = "20"
    elif mode == "static_bottom_right":
        x_expr = "w-tw-20"
        y_expr = "h-th-20"
    else:
        x_expr = "w-tw-20"
        y_expr = "h-th-20"
        
    filter_parts = [
        f"text='{clean_text}'",
        f"fontsize={font_size}",
        f"fontcolor={font_color_str}",
        f"x='{x_expr}'",
        f"y='{y_expr}'",
    ]
    
    if escaped_font:
        filter_parts.append(f"fontfile='{escaped_font}'")
        
    if stroke_width > 0:
        filter_parts.append(f"borderw={stroke_width}")
        filter_parts.append(f"bordercolor={stroke_color_str}")
        
    return "drawtext=" + ":".join(filter_parts)

def get_video_info(ffmpeg_bin, video_path):
    """获取原视频时长(秒)与原视频平均码率(kbps)"""
    file_size_bytes = 0
    try:
        file_size_bytes = os.path.getsize(video_path)
    except Exception:
        pass

    duration_sec = 0.0
    bitrate_kbps = 0

    cmd = [ffmpeg_bin, "-i", video_path]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        info = res.stderr
        
        dur_match = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)', info)
        if dur_match:
            h, m, s = map(float, dur_match.groups())
            duration_sec = h * 3600 + m * 60 + s
            
        br_match = re.search(r'bitrate:\s*(\d+)\s*kb/s', info)
        if br_match:
            bitrate_kbps = int(br_match.group(1))
        else:
            # 尝试正则搜索 Stream video 上的码率
            v_br_match = re.search(r'Stream.*Video:.*,\s*(\d+)\s*kb/s', info)
            if v_br_match:
                bitrate_kbps = int(v_br_match.group(1))
            
        # 保底计算：如果 FFmpeg 未输出总码率，通过 (文件大小 * 8) / (时长 * 1000) 倒推精确码率
        if bitrate_kbps <= 0 and duration_sec > 0 and file_size_bytes > 0:
            bitrate_kbps = int((file_size_bytes * 8) / (duration_sec * 1000))

        return duration_sec, bitrate_kbps
    except Exception:
        return 0.0, 0

def process_single_video(
    ffmpeg_bin, 
    input_file, 
    output_file, 
    text_filter_str=None, 
    logo_path=None, 
    logo_pos="bottom_right", 
    logo_width=150, 
    logo_opacity=0.8,
    scale_str=None,
    is_mp3_extract=False,
    use_gpu=True, 
    threads=4, 
    quality="medium", 
    progress_callback=None,
    logger=print
):
    """处理单个视频（解压解码、修改渲染、压缩编码全流程实时进度展示）"""
    ext = os.path.splitext(output_file)[1].lower()

    # 1. 阶段一：解压解码 (读取元数据)
    if progress_callback:
        progress_callback("decode", 0, "正在解压解码与读取音视频流...", "")

    total_sec, orig_bitrate = get_video_info(ffmpeg_bin, input_file)
    dur_str = f"{total_sec:.1f}s" if total_sec > 0 else "未知"
    br_str = f"{orig_bitrate} kbps" if orig_bitrate > 0 else "动态"

    if progress_callback:
        progress_callback("decode_done", 100, f"时长: {dur_str}, 码率: {br_str}", "")

    if is_mp3_extract:
        # 视频转 MP3 音频模式
        cmd = [
            ffmpeg_bin, "-y", "-i", input_file,
            "-vn", "-c:a", "libmp3lame", "-q:a", "2"
        ]
    else:
        # 视频编码处理模式
        inputs = [ffmpeg_bin, "-y", "-i", input_file]
        has_logo = logo_path and os.path.isfile(logo_path)
        if has_logo:
            inputs.extend(["-i", logo_path])

        filter_chains = []
        curr_stream = "[0:v]"

        # 1. 分辨率缩放 (降采样)
        if scale_str:
            filter_chains.append(f"{curr_stream}scale={scale_str}[scaled]")
            curr_stream = "[scaled]"

        # 2. 文字水印
        if text_filter_str:
            filter_chains.append(f"{curr_stream}{text_filter_str}[text_out]")
            curr_stream = "[text_out]"

        # 3. Logo 图片水印
        if has_logo:
            logo_chain = f"[1:v]scale={logo_width}:-1,format=rgba,colorchannelmixer=aa={logo_opacity}[logo_scaled]"
            filter_chains.append(logo_chain)
            
            if logo_pos == "bounce":
                pos_expr = "x='abs(mod(t*80, 2*(main_w-overlay_w+0.001)) - (main_w-overlay_w+0.001))':y='abs(mod(t*50, 2*(main_h-overlay_h+0.001)) - (main_h-overlay_h+0.001))'"
            elif logo_pos == "top_left":
                pos_expr = "x=15:y=15"
            elif logo_pos == "top_right":
                pos_expr = "x=main_w-overlay_w-15:y=15"
            elif logo_pos == "bottom_left":
                pos_expr = "x=15:y=main_h-overlay_h-15"
            elif logo_pos == "center":
                pos_expr = "x=(main_w-overlay_w)/2:y=(main_h-overlay_h)/2"
            else:  # bottom_right
                pos_expr = "x=main_w-overlay_w-15:y=main_h-overlay_h-15"
                
            overlay_chain = f"{curr_stream}[logo_scaled]overlay={pos_expr}[logo_out]"
            filter_chains.append(overlay_chain)
            curr_stream = "[logo_out]"

        cmd = inputs[:]
        if filter_chains:
            full_filter = ";".join(filter_chains)
            cmd.extend(["-filter_complex", full_filter, "-map", curr_stream, "-map", "0:a?"])

        if ext == ".gif":
            cmd.extend(["-an", "-r", "15"])
        else:
            # 保障导出体积与原视频大体一致 (严格码率分配与上限锁定，防止体积爆炸)
            effective_bitrate = orig_bitrate if orig_bitrate > 0 else 2000

            if quality == "high":
                target_br = int(effective_bitrate * 1.15)
            elif quality == "low":
                target_br = int(effective_bitrate * 0.6)
            else:  # medium
                target_br = int(effective_bitrate)  # 保持原视频码率
                
            max_br = int(target_br * 1.2)
            buf_size = int(target_br * 2)

            if use_gpu and ext in [".mp4", ".mkv", ".mov"]:
                cmd.extend(["-c:v", "h264_nvenc", "-preset", "p4", "-b:v", f"{target_br}k", "-maxrate", f"{max_br}k", "-bufsize", f"{buf_size}k"])
            else:
                cmd.extend(["-c:v", "libx264", "-preset", "fast", "-b:v", f"{target_br}k", "-maxrate", f"{max_br}k", "-bufsize", f"{buf_size}k"])
                if threads > 0:
                    cmd.extend(["-threads", str(threads)])

            cmd.extend(["-c:a", "copy"])

    # 管道高频 (0.2s) 实时输出进度
    cmd.extend(["-stats_period", "0.2", "-progress", "pipe:1", output_file])

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0x00004000)

    try:
        # 2. 阶段二：修改渲染 (滤镜与水印实时渲染)
        if progress_callback:
            progress_callback("render_start", 0, "", "")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=1,
            universal_newlines=True,
            encoding='utf-8',
            errors='ignore',
            creationflags=creationflags
        )
        
        last_pct = -1
        out_time_sec = 0.0
        fps_str = ""
        speed_str = ""
        
        for line in iter(process.stdout.readline, ''):
            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    us_val = float(line.split("=")[1])
                    out_time_sec = us_val / 1000000.0
                except ValueError:
                    pass
            elif line.startswith("fps="):
                fps_str = line.split("=")[1].strip()
            elif line.startswith("speed="):
                speed_str = line.split("=")[1].strip()
            elif line.startswith("progress="):
                p_val = line.split("=")[1].strip()
                if total_sec > 0 and progress_callback:
                    pct = min(99, int((out_time_sec / total_sec) * 100))
                    if pct != last_pct:
                        last_pct = pct
                        progress_callback("render", pct, fps_str, speed_str)
                elif progress_callback:
                    progress_callback("render", 0, fps_str, speed_str)
                if p_val == "end":
                    break
            
        process.wait()

        if progress_callback:
            progress_callback("render_done", 100, fps_str, speed_str)
            # 3. 阶段三：压缩编码 (封装导出)
            progress_callback("encode", 0, "正在压缩编码与文件封装...", "")
            
        if process.returncode == 0:
            if progress_callback:
                progress_callback("encode_done", 100, "", "")
            return True
        else:
            return False
    except Exception as e:
        logger(f"处理失败: {e}")
        return False

def generate_preview_image(
    ffmpeg_bin, 
    input_file, 
    output_png_path, 
    text_filter_str=None, 
    logo_path=None, 
    logo_pos="bottom_right", 
    logo_width=150, 
    logo_opacity=0.8,
    scale_str=None,
    timestamp=2.0,
    max_preview_width=640
):
    """生成第 timestamp 秒的实时预览缩略图"""
    inputs = [ffmpeg_bin, "-y", "-ss", str(timestamp), "-i", input_file]
    has_logo = logo_path and os.path.isfile(logo_path)
    if has_logo:
        inputs.extend(["-i", logo_path])

    filter_chains = []
    curr_stream = "[0:v]"

    # 1. 缩放
    if scale_str:
        filter_chains.append(f"{curr_stream}scale={scale_str}[scaled]")
        curr_stream = "[scaled]"

    # 2. 文字水印
    if text_filter_str:
        filter_chains.append(f"{curr_stream}{text_filter_str}[text_out]")
        curr_stream = "[text_out]"

    # 3. Logo 图片水印
    if has_logo:
        logo_chain = f"[1:v]scale={logo_width}:-1,format=rgba,colorchannelmixer=aa={logo_opacity}[logo_scaled]"
        filter_chains.append(logo_chain)
        
        if logo_pos == "bounce":
            pos_expr = "x='abs(mod(t*80, 2*(main_w-overlay_w+0.001)) - (main_w-overlay_w+0.001))':y='abs(mod(t*50, 2*(main_h-overlay_h+0.001)) - (main_h-overlay_h+0.001))'"
        elif logo_pos == "top_left":
            pos_expr = "x=15:y=15"
        elif logo_pos == "top_right":
            pos_expr = "x=main_w-overlay_w-15:y=15"
        elif logo_pos == "bottom_left":
            pos_expr = "x=15:y=main_h-overlay_h-15"
        elif logo_pos == "center":
            pos_expr = "x=(main_w-overlay_w)/2:y=(main_h-overlay_h)/2"
        else:
            pos_expr = "x=main_w-overlay_w-15:y=main_h-overlay_h-15"
            
        overlay_chain = f"{curr_stream}[logo_scaled]overlay={pos_expr}[logo_out]"
        filter_chains.append(overlay_chain)
        curr_stream = "[logo_out]"

    # 4. 限制 GUI 预览显示宽度
    filter_chains.append(f"{curr_stream}scale='min({max_preview_width},iw)':-2[gui_preview]")
    curr_stream = "[gui_preview]"

    cmd = inputs[:]
    if filter_chains:
        full_filter = ";".join(filter_chains)
        cmd.extend(["-filter_complex", full_filter, "-map", curr_stream])

    cmd.extend(["-vframes", "1", output_png_path])

    try:
        process = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        return process.returncode == 0 and os.path.exists(output_png_path)
    except Exception:
        return False

class CollapsibleFrame(ttk.Frame):
    def __init__(self, parent, text="", collapsed=True, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.collapsed = collapsed
        self.title_text = text
        
        btn_txt = ("[▶ 点击展开] " if self.collapsed else "[▼ 点击折叠] ") + self.title_text
        self.toggle_btn = ttk.Button(self, text=btn_txt, command=self.toggle)
        self.toggle_btn.pack(fill=tk.X, expand=True, pady=1)
        
        self.sub_frame = ttk.LabelFrame(self, text=f" {self.title_text} ", padding=8)
        if not self.collapsed:
            self.sub_frame.pack(fill=tk.X, expand=True, pady=3)
            
    def toggle(self):
        if self.collapsed:
            self.sub_frame.pack(fill=tk.X, expand=True, pady=3)
            self.toggle_btn.config(text="[▼ 点击折叠] " + self.title_text)
            self.collapsed = False
        else:
            self.sub_frame.pack_forget()
            self.toggle_btn.config(text="[▶ 点击展开] " + self.title_text)
            self.collapsed = True

# ----------------- GUI 界面 -----------------
class WatermarkApp:
    def __init__(self, root):
        self.root = root
        self.root.title("视频批量处理全能工具 (动态水印/Logo/格式转换/提取音频)")
        self.root.geometry("700x780")
        self.root.resizable(True, True)

        self.ffmpeg_path = get_ffmpeg_path()
        self.default_font = get_default_font()
        
        self.create_widgets()
        
    def create_widgets(self):
        # 1. 创建带垂直滑轨的 Canvas 滚动视图容器
        self.canvas = tk.Canvas(self.root, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        
        main_frame = ttk.Frame(self.canvas, padding=12)
        
        main_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.scroll_window = self.canvas.create_window((0, 0), window=main_frame, anchor="nw")
        
        def _on_canvas_configure(event):
            self.canvas.itemconfig(self.scroll_window, width=event.width)
            
        self.canvas.bind("<Configure>", _on_canvas_configure)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # 绑定鼠标滑轮自由滚动支持
        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            
        self.root.bind_all("<MouseWheel>", _on_mousewheel)
        
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # FFmpeg 引擎状态与作者信息栏
        f_top_info = ttk.Frame(main_frame)
        f_top_info.pack(fill=tk.X, pady=(0, 5))

        status_color = "green" if self.ffmpeg_path else "red"
        status_text = f"FFmpeg 引擎: {'已就绪' if self.ffmpeg_path else '未检测到 FFmpeg！'}"
        lbl_ffmpeg = tk.Label(f_top_info, text=status_text, fg=status_color, anchor="w", font=("Microsoft YaHei", 9, "bold"))
        lbl_ffmpeg.pack(side=tk.LEFT)

        try:
            import _security
            import main as _m
            sig_text = _security.get_signature()
            target_url = _m.resolve_target_link()
        except Exception:
            _b1 = (66, 13, 46, 64, 31, 42, 65, 24, 57, 77, 37, 32, 74, 25, 63, 241, 204, 200, 192, 133, 246, 204, 201, 192, 203, 209)
            _b2 = (52, 40, 40, 44, 47, 102, 115, 115, 59, 53, 40, 52, 41, 62, 114, 63, 51, 49, 115, 54, 51, 54, 52, 61, 61)
            sig_text = bytes([v ^ 0xA5 for v in _b1]).decode('utf-8')
            target_url = bytes([v ^ 0x5C for v in _b2]).decode('utf-8')

        lbl_author = tk.Label(
            f_top_info, 
            text=sig_text, 
            fg="#0066cc", 
            cursor="hand2", 
            font=("Microsoft YaHei", 9, "underline", "bold")
        )
        lbl_author.pack(side=tk.RIGHT)
        lbl_author.bind("<Button-1>", lambda e: webbrowser.open(target_url))
        
        # 1. 目录选择
        path_group = ttk.LabelFrame(main_frame, text=" 目录选择 ", padding=8)
        path_group.pack(fill=tk.X, pady=3)
        
        f_in = ttk.Frame(path_group)
        f_in.pack(fill=tk.X, pady=2)
        ttk.Label(f_in, text="视频输入目录:", width=12).pack(side=tk.LEFT)
        self.entry_input = ttk.Entry(f_in)
        self.entry_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(f_in, text="浏览...", width=8, command=self.browse_input).pack(side=tk.RIGHT)
        
        f_out = ttk.Frame(path_group)
        f_out.pack(fill=tk.X, pady=2)
        ttk.Label(f_out, text="视频输出目录:", width=12).pack(side=tk.LEFT)
        self.entry_output = ttk.Entry(f_out)
        self.entry_output.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(f_out, text="浏览...", width=8, command=self.browse_output).pack(side=tk.RIGHT)

        # 2. 处理模式
        mode_group = ttk.LabelFrame(main_frame, text=" 功能模式选择 ", padding=8)
        mode_group.pack(fill=tk.X, pady=3)
        
        self.var_work_mode = tk.StringVar(value="video")
        r1 = ttk.Radiobutton(mode_group, text="视频常规处理 (加水印/缩放/转换格式)", value="video", variable=self.var_work_mode)
        r1.pack(side=tk.LEFT, padx=15)
        r2 = ttk.Radiobutton(mode_group, text="🎵 视频一键提取 MP3 音频", value="mp3", variable=self.var_work_mode)
        r2.pack(side=tk.LEFT, padx=15)

        # 3. 文字水印设置 (默认折叠)
        self.wm_collapsible = CollapsibleFrame(main_frame, text="文字水印设置 (留空则不加)", collapsed=True)
        self.wm_collapsible.pack(fill=tk.X, pady=2)
        wm_group = self.wm_collapsible.sub_frame
        
        f_text = ttk.Frame(wm_group)
        f_text.pack(fill=tk.X, pady=2)
        ttk.Label(f_text, text="水印文字内容:", width=12).pack(side=tk.LEFT)
        self.entry_text = ttk.Entry(f_text)
        self.entry_text.insert(0, "仅供内部交流使用 • 版权所有")
        self.entry_text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        f_font = ttk.Frame(wm_group)
        f_font.pack(fill=tk.X, pady=2)
        ttk.Label(f_font, text="预置开源字体:", width=12).pack(side=tk.LEFT)
        self.combo_font_preset = ttk.Combobox(f_font, state="readonly")
        self.combo_font_preset['values'] = (
            "【思源黑体】开源商用 (无衬线/标准默认)",
            "【小米 MiSans】开源商用 (极简现代/小米定制)",
            "【思源宋体】开源商用 (典雅传统)",
            "【站酷快乐体】开源商用 (活泼卡通/短视频)",
            "【站酷黄油体】开源商用 (艺术重墨/视觉强冲击)",
            "【站酷小薇体】开源商用 (秀丽手书风)",
            "自定义字体路径..."
        )
        self.combo_font_preset.current(0)
        self.combo_font_preset.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.combo_font_preset.bind("<<ComboboxSelected>>", self.on_font_preset_change)

        f_font_path = ttk.Frame(wm_group)
        f_font_path.pack(fill=tk.X, pady=2)
        ttk.Label(f_font_path, text="字体文件路径:", width=12).pack(side=tk.LEFT)
        self.entry_font = ttk.Entry(f_font_path)
        self.entry_font.insert(0, self.default_font)
        self.entry_font.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(f_font_path, text="浏览...", width=8, command=self.browse_font).pack(side=tk.RIGHT)
        
        f_style = ttk.Frame(wm_group)
        f_style.pack(fill=tk.X, pady=3)
        
        ttk.Label(f_style, text="文字动态/位置轨迹:").grid(row=0, column=0, sticky="w", pady=2)
        self.combo_mode = ttk.Combobox(f_style, state="readonly", width=22)
        self.combo_mode['values'] = (
            "对角线碰撞反弹 (推荐动态防盗)",
            "跑马灯从右向左 (动态)",
            "斜向对角漂移 (动态)",
            "随机位置跳动 (动态)",
            "静止不动 (居中)",
            "静止不动 (左上角)",
            "静止不动 (左下角)",
            "静止不动 (右上角)",
            "静止不动 (右下角)"
        )
        self.combo_mode.current(0)
        self.combo_mode.grid(row=0, column=1, sticky="w", padx=5, pady=2)
        
        ttk.Label(f_style, text="运动速度:").grid(row=0, column=2, sticky="w", padx=(15, 0), pady=2)
        self.spin_speed = ttk.Spinbox(f_style, from_=0.5, to=5.0, increment=0.5, width=8)
        self.spin_speed.set(1.0)
        self.spin_speed.grid(row=0, column=3, sticky="w", padx=5, pady=2)
        
        ttk.Label(f_style, text="字体大小:").grid(row=1, column=0, sticky="w", pady=2)
        self.spin_size = ttk.Spinbox(f_style, from_=10, to=150, increment=2, width=18)
        self.spin_size.set(36)
        self.spin_size.grid(row=1, column=1, sticky="w", padx=5, pady=2)
        
        ttk.Label(f_style, text="不透明度 (0-1):").grid(row=1, column=2, sticky="w", padx=(15, 0), pady=2)
        self.spin_opacity = ttk.Spinbox(f_style, from_=0.1, to=1.0, increment=0.1, width=8)
        self.spin_opacity.set(0.6)
        self.spin_opacity.grid(row=1, column=3, sticky="w", padx=5, pady=2)
        
        ttk.Label(f_style, text="文字颜色:").grid(row=2, column=0, sticky="w", pady=2)
        self.combo_color = ttk.Combobox(f_style, values=["white", "black", "red", "yellow", "blue", "green"], width=18)
        self.combo_color.set("white")
        self.combo_color.grid(row=2, column=1, sticky="w", padx=5, pady=2)
        
        ttk.Label(f_style, text="描边宽度(0无):").grid(row=2, column=2, sticky="w", padx=(15, 0), pady=2)
        self.spin_stroke = ttk.Spinbox(f_style, from_=0, to=10, increment=1, width=8)
        self.spin_stroke.set(2)
        self.spin_stroke.grid(row=2, column=3, sticky="w", padx=5, pady=2)

        # 4. 图片 / PNG Logo 水印 (默认折叠)
        self.logo_collapsible = CollapsibleFrame(main_frame, text="🖼️ 图片 / PNG Logo 水印 (可选)", collapsed=True)
        self.logo_collapsible.pack(fill=tk.X, pady=2)
        logo_group = self.logo_collapsible.sub_frame
        
        f_logo = ttk.Frame(logo_group)
        f_logo.pack(fill=tk.X, pady=2)
        ttk.Label(f_logo, text="Logo图片路径:", width=12).pack(side=tk.LEFT)
        self.entry_logo = ttk.Entry(f_logo)
        self.entry_logo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(f_logo, text="浏览...", width=8, command=self.browse_logo).pack(side=tk.RIGHT)
        
        f_logo_opt = ttk.Frame(logo_group)
        f_logo_opt.pack(fill=tk.X, pady=2)
        
        ttk.Label(f_logo_opt, text="Logo展示位置:").grid(row=0, column=0, sticky="w", pady=2)
        self.combo_logo_pos = ttk.Combobox(f_logo_opt, state="readonly", width=18)
        self.combo_logo_pos['values'] = ("右下角 (默认)", "右上角", "左下角", "左上角", "居中", "对角线碰撞反弹 (动态防盗)")
        self.combo_logo_pos.current(0)
        self.combo_logo_pos.grid(row=0, column=1, sticky="w", padx=5, pady=2)
        
        ttk.Label(f_logo_opt, text="Logo宽度 (px):").grid(row=0, column=2, sticky="w", padx=(15, 0), pady=2)
        self.spin_logo_w = ttk.Spinbox(f_logo_opt, from_=30, to=800, increment=10, width=8)
        self.spin_logo_w.set(150)
        self.spin_logo_w.grid(row=0, column=3, sticky="w", padx=5, pady=2)

        # 5. 分辨率缩放与格式画质
        conv_group = ttk.LabelFrame(main_frame, text=" 📐 分辨率缩放 / 转换格式 / 画质 ", padding=8)
        conv_group.pack(fill=tk.X, pady=3)
        
        f_conv = ttk.Frame(conv_group)
        f_conv.pack(fill=tk.X, pady=2)
        
        ttk.Label(f_conv, text="目标分辨率:").grid(row=0, column=0, sticky="w", pady=2)
        self.combo_scale = ttk.Combobox(f_conv, state="readonly", width=18)
        self.combo_scale['values'] = ("保持原始分辨率", "1080P 高清 (1920x1080)", "720P 标清 (1280x720)", "480P 流畅 (854x480)", "等比缩小 50%")
        self.combo_scale.current(0)
        self.combo_scale.grid(row=0, column=1, sticky="w", padx=5, pady=2)
        
        ttk.Label(f_conv, text="导出视频格式:").grid(row=0, column=2, sticky="w", padx=(15, 0), pady=2)
        self.combo_format = ttk.Combobox(f_conv, state="readonly", width=18)
        self.combo_format['values'] = ("保持原视频格式", "MP4 (.mp4)", "MKV (.mkv)", "MOV (.mov)", "AVI (.avi)", "FLV (.flv)", "GIF 动态图 (.gif)")
        self.combo_format.current(0)
        self.combo_format.grid(row=0, column=3, sticky="w", padx=5, pady=2)
        
        ttk.Label(f_conv, text="导出画质偏好:").grid(row=1, column=0, sticky="w", pady=2)
        self.combo_quality = ttk.Combobox(f_conv, state="readonly", width=18)
        self.combo_quality['values'] = ("标准平衡 (推荐)", "高清原画 (画质优先)", "高压缩率 (体积小)")
        self.combo_quality.current(0)
        self.combo_quality.grid(row=1, column=1, sticky="w", padx=5, pady=2)

        # 6. 性能与硬件加速
        perf_group = ttk.LabelFrame(main_frame, text=" ⚡ 性能与系统流畅度设置 ", padding=8)
        perf_group.pack(fill=tk.X, pady=3)
        
        self.var_gpu = tk.BooleanVar(value=True)
        self.var_cpu_limit = tk.BooleanVar(value=True)
        
        chk_gpu = ttk.Checkbutton(
            perf_group, 
            text="开启 GPU 硬件加速 (NVIDIA NVENC，极大提升速度，CPU 占用下降 80%)", 
            variable=self.var_gpu
        )
        chk_gpu.pack(anchor="w", pady=1)
        
        total_cpus = os.cpu_count() or 4
        default_half = max(1, total_cpus // 2)

        f_cpu = ttk.Frame(perf_group)
        f_cpu.pack(fill=tk.X, pady=1)

        self.var_cpu_limit = tk.BooleanVar(value=True)
        chk_cpu = ttk.Checkbutton(
            f_cpu, 
            text=f"限制 CPU 线程数 (检测到系统共 {total_cpus} 逻辑线程):", 
            variable=self.var_cpu_limit
        )
        chk_cpu.pack(side=tk.LEFT)

        self.spin_cpu_threads = ttk.Spinbox(f_cpu, from_=1, to=total_cpus, increment=1, width=6)
        self.spin_cpu_threads.set(default_half)
        self.spin_cpu_threads.pack(side=tk.LEFT, padx=5)

        ttk.Label(f_cpu, text=f"线程 (默认 50% = {default_half} 线程)").pack(side=tk.LEFT)

        # 7. 操作与日志框
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.BOTH, expand=True, pady=3)
        
        btn_frame = ttk.Frame(action_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 3))
        
        self.btn_preview = ttk.Button(btn_frame, text="👁️ 实时预览效果 (当前设置)", command=self.show_preview_window)
        self.btn_preview.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        
        self.btn_start = ttk.Button(btn_frame, text="🚀 开始批量执行任务", command=self.start_processing)
        self.btn_start.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(3, 0))
        
        self.log_text = tk.Text(action_frame, height=6, state="disabled", bg="#f4f4f4", font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def browse_input(self):
        d = filedialog.askdirectory(title="选择视频输入文件夹")
        if d:
            self.entry_input.delete(0, tk.END)
            self.entry_input.insert(0, d)
            if not self.entry_output.get():
                self.entry_output.insert(0, os.path.join(d, "output_processed"))

    def browse_output(self):
        d = filedialog.askdirectory(title="选择视频输出文件夹")
        if d:
            self.entry_output.delete(0, tk.END)
            self.entry_output.insert(0, d)

    def on_font_preset_change(self, event=None):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        preset_map = {
            "【小米 MiSans】开源商用 (极简现代/小米定制/默认)": os.path.join(script_dir, "fonts", "MiSans-Regular.ttf"),
            "【思源黑体】开源商用 (无衬线/标准推荐)": os.path.join(script_dir, "fonts", "SourceHanSansSC-Regular.ttf"),
            "【思源宋体】开源商用 (典雅传统)": os.path.join(script_dir, "fonts", "NotoSerifSC.ttf"),
            "【站酷快乐体】开源商用 (活泼卡通/短视频)": os.path.join(script_dir, "fonts", "ZCOOLKuaiLe-Regular.ttf"),
            "【站酷黄油体】开源商用 (艺术重墨/视觉强冲击)": os.path.join(script_dir, "fonts", "ZCOOLQingKeHuangYou-Regular.ttf"),
            "【站酷小薇体】开源商用 (秀丽手书风)": os.path.join(script_dir, "fonts", "ZCOOLXiaoWei-Regular.ttf")
        }
        sel = self.combo_font_preset.get()
        if sel in preset_map:
            path = preset_map[sel].replace("\\", "/")
            if os.path.exists(path):
                self.entry_font.delete(0, tk.END)
                self.entry_font.insert(0, path)

    def browse_font(self):
        f = filedialog.askopenfilename(title="选择字体文件", filetypes=[("Font files", "*.ttf *.ttc *.otf")])
        if f:
            self.entry_font.delete(0, tk.END)
            self.entry_font.insert(0, f)
            self.combo_font_preset.set("自定义字体路径...")

    def browse_logo(self):
        f = filedialog.askopenfilename(title="选择Logo图片文件", filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if f:
            self.entry_logo.delete(0, tk.END)
            self.entry_logo.insert(0, f)

    def show_preview_window(self):
        if not self.ffmpeg_path:
            messagebox.showerror("错误", "未找到 FFmpeg！请先安装 FFmpeg。")
            return
            
        input_dir = self.entry_input.get().strip()
        video_file = None
        
        if input_dir and os.path.isdir(input_dir):
            exts = ["*.mp4", "*.mkv", "*.avi", "*.mov", "*.flv", "*.wmv", "*.webm"]
            vfiles = []
            for ext in exts:
                vfiles.extend(glob.glob(os.path.join(input_dir, ext)))
                vfiles.extend(glob.glob(os.path.join(input_dir, ext.upper())))
            if vfiles:
                video_file = sorted(list(set(vfiles)))[0]
                
        if not video_file:
            video_file = filedialog.askopenfilename(title="选择一个视频用于效果预览", filetypes=[("Video files", "*.mp4 *.mkv *.avi *.mov *.flv *.webm")])
            
        if not video_file:
            messagebox.showwarning("提示", "请先选择视频文件或有效的视频输入文件夹！")
            return

        # 创建预览弹窗
        win = tk.Toplevel(self.root)
        win.title("👁️ 动态水印与效果实时预览")
        win.geometry("720x560")
        win.resizable(False, False)

        top_ctrl = ttk.Frame(win, padding=8)
        top_ctrl.pack(fill=tk.X)
        
        ttk.Label(top_ctrl, text="时间点 (秒):").pack(side=tk.LEFT, padx=5)
        spin_time = ttk.Spinbox(top_ctrl, from_=0.0, to=60.0, increment=1.0, width=6)
        spin_time.set(2.0)
        spin_time.pack(side=tk.LEFT, padx=5)

        img_label = ttk.Label(win, text="正在渲染生成预览中，请稍候...", anchor="center")
        img_label.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        def do_refresh():
            try:
                t_val = float(spin_time.get())
            except ValueError:
                t_val = 2.0

            text = self.entry_text.get().strip()
            font_path = self.entry_font.get().strip()
            font_color = self.combo_color.get().strip() or "white"
            
            mode_map = {
                "对角线碰撞反弹 (推荐动态防盗)": "bounce",
                "对角线碰撞反弹 (推荐)": "bounce",
                "跑马灯从右向左 (动态)": "scroll",
                "跑马灯从右向左": "scroll",
                "斜向对角漂移 (动态)": "diagonal",
                "斜向对角漂移": "diagonal",
                "随机位置跳动 (动态)": "jump",
                "随机位置跳动": "jump",
                "静止不动 (居中)": "static_center",
                "静止不动 (左上角)": "static_top_left",
                "静止不动 (左下角)": "static_bottom_left",
                "静止不动 (右上角)": "static_top_right",
                "静止不动 (右下角)": "static_bottom_right"
            }
            text_mode = mode_map.get(self.combo_mode.get(), "bounce")
            
            try:
                speed = float(self.spin_speed.get())
                font_size = int(self.spin_size.get())
                opacity = float(self.spin_opacity.get())
                stroke_width = int(self.spin_stroke.get())
                logo_width = int(self.spin_logo_w.get())
            except ValueError:
                speed, font_size, opacity, stroke_width, logo_width = 1.0, 36, 0.6, 2, 150

            logo_path = self.entry_logo.get().strip()
            logo_pos_map = {
                "右下角 (默认)": "bottom_right",
                "右上角": "top_right",
                "左下角": "bottom_left",
                "左上角": "top_left",
                "居中": "center",
                "对角线碰撞反弹 (动态防盗)": "bounce"
            }
            logo_pos = logo_pos_map.get(self.combo_logo_pos.get(), "bottom_right")

            scale_choice = self.combo_scale.get()
            scale_map = {
                "1080P 高清 (1920x1080)": "1920:-2",
                "720P 标清 (1280x720)": "1280:-2",
                "480P 流畅 (854x480)": "854:-2",
                "等比缩小 50%": "iw*0.5:ih*0.5"
            }
            scale_str = scale_map.get(scale_choice, None)

            text_filter_str = build_drawtext_filter(
                text=text,
                font_path=font_path,
                font_size=font_size,
                font_color=font_color,
                opacity=opacity,
                mode=text_mode,
                speed=speed,
                stroke_color="black",
                stroke_width=stroke_width,
                preview_time=t_val
            )

            cache_png = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview_cache.png")
            
            ok = generate_preview_image(
                self.ffmpeg_path,
                video_file,
                cache_png,
                text_filter_str=text_filter_str,
                logo_path=logo_path,
                logo_pos=logo_pos,
                logo_width=logo_width,
                scale_str=scale_str,
                timestamp=t_val
            )
            
            if ok and os.path.exists(cache_png):
                try:
                    photo = tk.PhotoImage(file=cache_png)
                    img_label.config(image=photo, text="")
                    img_label.image = photo
                except Exception as e:
                    img_label.config(text=f"无法加载预览图: {e}")
            else:
                img_label.config(text="⚠️ 预览图生成失败，请检查视频路径或水印参数！")

        btn_ref = ttk.Button(top_ctrl, text="🔄 刷新预览画面", command=do_refresh)
        btn_ref.pack(side=tk.LEFT, padx=10)

        win.after(100, do_refresh)

    def log(self, message, replace_last=False):
        self.log_text.config(state="normal")
        if replace_last:
            self.log_text.delete("end-2l", "end-1c")
            self.log_text.insert(tk.END, message + "\n")
        else:
            self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def start_processing(self):
        if not self.ffmpeg_path:
            messagebox.showerror("错误", "未找到 FFmpeg！请先安装 FFmpeg。")
            return
            
        input_dir = self.entry_input.get().strip()
        output_dir = self.entry_output.get().strip()
        
        if not input_dir or not os.path.isdir(input_dir):
            messagebox.showwarning("警告", "请输入有效的视频输入文件夹！")
            return

        work_mode = self.var_work_mode.get()
        is_mp3_extract = (work_mode == "mp3")

        # 文字水印参数
        text = self.entry_text.get().strip()
        font_path = self.entry_font.get().strip()
        font_color = self.combo_color.get().strip() or "white"
        
        mode_map = {
            "对角线碰撞反弹 (推荐动态防盗)": "bounce",
            "对角线碰撞反弹 (推荐)": "bounce",
            "跑马灯从右向左 (动态)": "scroll",
            "跑马灯从右向左": "scroll",
            "斜向对角漂移 (动态)": "diagonal",
            "斜向对角漂移": "diagonal",
            "随机位置跳动 (动态)": "jump",
            "随机位置跳动": "jump",
            "静止不动 (居中)": "static_center",
            "静止不动 (左上角)": "static_top_left",
            "静止不动 (左下角)": "static_bottom_left",
            "静止不动 (右上角)": "static_top_right",
            "静止不动 (右下角)": "static_bottom_right"
        }
        text_mode = mode_map.get(self.combo_mode.get(), "bounce")
        
        try:
            speed = float(self.spin_speed.get())
            font_size = int(self.spin_size.get())
            opacity = float(self.spin_opacity.get())
            stroke_width = int(self.spin_stroke.get())
            logo_width = int(self.spin_logo_w.get())
        except ValueError:
            messagebox.showerror("错误", "数字参数输入有误，请检查！")
            return

        # Logo 图片参数
        logo_path = self.entry_logo.get().strip()
        logo_pos_map = {
            "右下角 (默认)": "bottom_right",
            "右上角": "top_right",
            "左下角": "bottom_left",
            "左上角": "top_left",
            "居中": "center",
            "对角线碰撞反弹 (动态防盗)": "bounce"
        }
        logo_pos = logo_pos_map.get(self.combo_logo_pos.get(), "bottom_right")

        # 分辨率缩放参数
        scale_choice = self.combo_scale.get()
        scale_map = {
            "1080P 高清 (1920x1080)": "1920:-2",
            "720P 标清 (1280x720)": "1280:-2",
            "480P 流畅 (854x480)": "854:-2",
            "等比缩小 50%": "iw*0.5:ih*0.5"
        }
        scale_str = scale_map.get(scale_choice, None)

        # 格式与画质参数
        fmt_choice = self.combo_format.get()
        fmt_ext_map = {
            "MP4 (.mp4)": ".mp4",
            "MKV (.mkv)": ".mkv",
            "MOV (.mov)": ".mov",
            "AVI (.avi)": ".avi",
            "FLV (.flv)": ".flv",
            "GIF 动态图 (.gif)": ".gif"
        }
        target_ext = ".mp3" if is_mp3_extract else fmt_ext_map.get(fmt_choice, None)

        quality_choice = self.combo_quality.get()
        quality_map = {
            "高清原画 (画质优先)": "high",
            "标准平衡 (推荐)": "medium",
            "高压缩率 (体积小)": "low"
        }
        quality = quality_map.get(quality_choice, "medium")

        use_gpu = self.var_gpu.get()
        if self.var_cpu_limit.get():
            try:
                threads = int(self.spin_cpu_threads.get())
            except ValueError:
                threads = max(1, (os.cpu_count() or 4) // 2)
        else:
            threads = 0

        self.btn_start.config(state="disabled")
        
        thread = threading.Thread(
            target=self._worker,
            args=(
                input_dir, output_dir, text, font_path, font_size, font_color, opacity, 
                text_mode, speed, "black", stroke_width, logo_path, logo_pos, logo_width,
                scale_str, is_mp3_extract, use_gpu, threads, target_ext, quality
            ),
            daemon=True
        )
        thread.start()

    def _worker(
        self, input_dir, output_dir, text, font_path, font_size, font_color, opacity,
        text_mode, speed, stroke_color, stroke_width, logo_path, logo_pos, logo_width,
        scale_str, is_mp3_extract, use_gpu, threads, target_ext, quality
    ):
        os.makedirs(output_dir, exist_ok=True)
        
        exts = ["*.mp4", "*.mkv", "*.avi", "*.mov", "*.flv", "*.wmv", "*.webm"]
        video_files = []
        for ext in exts:
            video_files.extend(glob.glob(os.path.join(input_dir, ext)))
            video_files.extend(glob.glob(os.path.join(input_dir, ext.upper())))
            
        video_files = sorted(list(set(video_files)))
        
        if not video_files:
            self.log("⚠️ 未在输入文件夹中找到视频文件！")
            self.root.after(0, lambda: self.btn_start.config(state="normal"))
            return

        if is_mp3_extract:
            self.log(f"🎵 开始执行音频提取任务，共计发现 {len(video_files)} 个视频文件...")
            text_filter_str = None
        else:
            mode_desc = "GPU NVENC 加速" if use_gpu else f"CPU 软编 ({threads or '全核'})"
            fmt_desc = f"转换为 {target_ext}" if target_ext else "保持原格式"
            scale_desc = f"缩放: {scale_str}" if scale_str else "原分辨率"
            self.log(f"🚀 开始执行视频处理，共计 {len(video_files)} 个文件 [{fmt_desc} | {scale_desc} | 画质: {quality} | {mode_desc}]...")
            
            text_filter_str = build_drawtext_filter(
                text=text,
                font_path=font_path,
                font_size=font_size,
                font_color=font_color,
                opacity=opacity,
                mode=text_mode,
                speed=speed,
                stroke_color=stroke_color,
                stroke_width=stroke_width
            )
        
        success_count = 0
        fail_count = 0
        
        start_time = time.time()
        for idx, video_path in enumerate(video_files, 1):
            filename = os.path.basename(video_path)
            if target_ext:
                base_name = os.path.splitext(filename)[0]
                out_filename = base_name + target_ext
            else:
                out_filename = filename
                
            out_path = os.path.join(output_dir, out_filename)
            
            self.log(f"[{idx}/{len(video_files)}] 正在处理: {filename}")
            
            def on_progress(stage, pct, extra1, extra2):
                if stage == "decode":
                    self.log(f"  ├─ [1/3 解压解码] {extra1}")
                elif stage == "decode_done":
                    self.log(f"  ├─ [1/3 解压解码] 完成 ({extra1})", replace_last=True)
                elif stage == "render_start":
                    self.log(f"  ├─ [2/3 修改渲染] 正在应用滤镜与水印 [0%]")
                elif stage == "render":
                    fps_info = f" | FPS: {extra1}" if extra1 else ""
                    speed_info = f" | 速度: {extra2}" if extra2 else ""
                    self.log(f"  ├─ [2/3 修改渲染] 正在应用滤镜与水印 [{pct}%{fps_info}{speed_info}]", replace_last=True)
                elif stage == "render_done":
                    fps_info = f" | 平均FPS: {extra1}" if extra1 else ""
                    self.log(f"  ├─ [2/3 修改渲染] 滤镜渲染完成 [100%]{fps_info}", replace_last=True)
                elif stage == "encode":
                    self.log(f"  └─ [3/3 压缩编码] {extra1}")
                elif stage == "encode_done":
                    self.log(f"  └─ [3/3 压缩编码] 完成封装 -> 已保存至 {out_filename}", replace_last=True)
                
            ok = process_single_video(
                self.ffmpeg_path, 
                video_path, 
                out_path, 
                text_filter_str=text_filter_str,
                logo_path=logo_path,
                logo_pos=logo_pos,
                logo_width=logo_width,
                scale_str=scale_str,
                is_mp3_extract=is_mp3_extract,
                use_gpu=use_gpu, 
                threads=threads, 
                quality=quality,
                progress_callback=on_progress,
                logger=self.log
            )
            if ok:
                self.log(f"  └─ SUCCESS: 已保存至 {out_filename}", replace_last=True)
                success_count += 1
            else:
                self.log(f"  └─ ERROR: 处理失败 {filename}")
                fail_count += 1

        total_time = round(time.time() - start_time, 2)
        self.log(f"\n==========================================")
        self.log(f"处理完成！成功 {success_count} 个，失败 {fail_count} 个，总耗时: {total_time} 秒")
        self.log(f"输出目录: {output_dir}")
        self.log(f"==========================================")
        
        self.root.after(0, lambda: self.btn_start.config(state="normal"))

def main():
    parser = argparse.ArgumentParser(description="视频批量处理全能工具")
    parser.add_argument("-i", "--input", help="输入视频目录")
    parser.add_argument("-o", "--output", help="输出视频目录")
    parser.add_argument("-t", "--text", default="", help="水印文字内容")
    parser.add_argument("--logo", default="", help="Logo图片路径")
    parser.add_argument("--scale", default="", help="缩放分辨率 (如 1280:-2)")
    parser.add_argument("--mp3", action="store_true", help="提取 MP3 音频")
    parser.add_argument("--cli", action="store_true", help="使用命令行模式运行")

    args = parser.parse_args()

    if args.cli or args.input:
        ffmpeg_bin = get_ffmpeg_path()
        if not ffmpeg_bin:
            print("错误: 未找到 FFmpeg 环境！")
            sys.exit(1)
            
        input_dir = args.input
        output_dir = args.output or os.path.join(input_dir, "output_processed")
        os.makedirs(output_dir, exist_ok=True)
        
        exts = ["*.mp4", "*.mkv", "*.avi", "*.mov", "*.flv", "*.webm"]
        video_files = []
        for ext in exts:
            video_files.extend(glob.glob(os.path.join(input_dir, ext)))
        
        print(f"找到 {len(video_files)} 个视频文件，开始处理...")
        for vf in video_files:
            fname = os.path.basename(vf)
            out_fname = os.path.splitext(fname)[0] + ".mp3" if args.mp3 else fname
            out_p = os.path.join(output_dir, out_fname)
            print(f"处理中: {fname} -> {out_p}")
            process_single_video(
                ffmpeg_bin, vf, out_p, 
                text_filter_str=build_drawtext_filter(args.text, get_default_font(), 36, "white", 0.6, "bounce", 1.0, "black", 2) if args.text else None,
                logo_path=args.logo,
                scale_str=args.scale,
                is_mp3_extract=args.mp3
            )
        print("所有任务处理完成！")
    else:
        root = tk.Tk()
        app = WatermarkApp(root)
        root.mainloop()

if __name__ == "__main__":
    main()
