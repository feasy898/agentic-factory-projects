# 小红书创作助手 (RedBook Creator)

> Claude Code Skill for creating Xiaohongshu (小红书) posts with auto video editing, subtitles, BGM, AI narration, and one-click upload.

## Features

- **Content Analysis** - Analyze images/videos/text to determine post direction
- **Trending Research** - Search for viral Xiaohongshu posts as reference
- **Title & Copy Generation** - Generate catchy titles and engaging copy with emoji and hashtags
- **Auto Video Editing** - Merge multiple videos with crossfade transitions (720x1280 vertical)
- **AI Narration** - Natural Chinese voiceover via Microsoft Edge TTS (6 voice options)
- **BGM Generation** - Auto-generate background music (4 styles: energetic/chill/upbeat/emotional)
- **Subtitle Burn-in** - Xiaohongshu-style subtitles with outline or background bar
- **Auto Upload** - Selenium-based auto-upload to Xiaohongshu Creator Platform
- **Local Preview** - Generate phone-frame HTML preview

## Installation

```bash
# Clone to Claude Code skills directory
git clone https://github.com/BoomSky0416/redbook-creator.git ~/.claude/skills/redbook-creator

# Install dependencies
pip3 install edge-tts selenium
brew install ffmpeg  # if not already installed
```

## Usage

In Claude Code, use any of these trigger phrases:

- `小红书创作` / `小红书` / `红书`
- `create redbook`
- `笔记创作` / `帖子创作`

Then provide your content (images, videos, or text).

## Workflow

```
素材 → 分析 → 爆款研究 → 标题/文案 → 视频剪辑 → 字幕+BGM+解说 → 上传 → 预览
```

## Scripts

| Script | Description |
|--------|-------------|
| `scripts/generate_preview.py` | Generate local HTML preview |
| `scripts/upload_redbook.py` | Auto-upload to Xiaohongshu |
| `scripts/generate_bgm.py` | Generate background music |
| `scripts/burn_subtitles.py` | Burn subtitles onto video |

## AI Voice Options

| Voice | Style | Best For |
|-------|-------|----------|
| YunxiNeural | Young male, natural | Fitness, tech, vlog (default) |
| YunjianNeural | Mature male | Knowledge sharing |
| YunyangNeural | Broadcast male | News-style |
| XiaoxiaoNeural | Young female | Beauty, fashion, food |
| XiaoyiNeural | Lively female | Pets, lifestyle |

## Requirements

- macOS / Linux
- Python 3.9+
- ffmpeg
- Claude Code

## License

MIT
