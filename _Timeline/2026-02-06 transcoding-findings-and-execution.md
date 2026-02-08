# Camcorder MTS Transcoding Benchmark Results

## Complete Benchmark Results

### File 1: Noisy Content (35s, 68MB source, 0.266 BPP)

| Encoder | Time | Size | Compression | SSIM |
|---------|------|------|-------------|------|
| **libx265 CRF 20** | 97s | 95MB | -40% (larger!) | 0.956 |
| **libx265 CRF 26** | 57s | 19MB | **72%** | 0.916 |
| **VideoToolbox q50** | 6s | 6.6MB | **90%** | 0.897 |

### File 2: Typical Motion (46s, 37MB source)

| Encoder | Time | Size | Compression | SSIM |
|---------|------|------|-------------|------|
| **libx265 CRF 20** | 76s | 59MB | -59% (larger!) | 0.977 |
| **libx265 CRF 26** | 56s | 22MB | **41%** | 0.966 |
| **VideoToolbox q50** | 5s | 16MB | **57%** | 0.955 |

---

## Projections for 462 files (44GB)

| Option | Est. Time | Est. Output | Quality |
|--------|-----------|-------------|---------|
| libx265 CRF 20 | ~19 hours | ~60GB (WORSE) | Excellent (0.96+) |
| **libx265 CRF 26** | **~12 hours** | **~18GB** | Very Good (0.92-0.97) |
| **VideoToolbox** | **~45 min** | **~12GB** | Good (0.90-0.96) |

---

## Key Observations

1. **CRF 26 is the sweet spot** for libx265 — actual compression (40-70%) with very good quality
2. **VideoToolbox** produces smaller files than CRF 26 on the motion video, but struggles more with noisy content
3. **Noisy content** (File 1) loses more quality across all encoders — this is expected
4. **CRF 20 is overkill** — preserves noise as "detail," resulting in bloated files

## Recommendation

For your 462 camcorder files:
- **If time matters:** VideoToolbox (~45 min), quality is good enough for home videos
- **If quality matters:** libx265 CRF 26 (~12 hours), best balance of size/quality (CRF 20, for archive-level quality, actually _increases_ size substantially for many files)
- **Hybrid option:** Add a `--fast` flag to choose VideoToolbox when needed

---

## Implementation: Automatic Encoder Selection

Based on the benchmark results, the camcorder conversion workflow now automatically selects the best encoder per file:

### Noise Detection Algorithm

Uses **bits-per-pixel-per-frame (BPP)** metric:
```
BPP = bitrate / (width × height × fps)
```

| BPP Threshold | Encoder | Rationale |
|---------------|---------|-----------|
| > 0.18 | libx265 CRF 26 | High complexity (noise/grain) needs better encoder |
| ≤ 0.18 | VideoToolbox | Clean content encodes well with hardware |

### Test Results

| File | Resolution | Bitrate | BPP | Detection | Correct? |
|------|------------|---------|-----|-----------|----------|
| 00031.MTS (noisy) | 1920×1080 | 16.4 Mbps | **0.263** | libx265 ✓ | Yes |
| 00059.MTS (clean) | 1440×1080 | 6.7 Mbps | **0.143** | VideoToolbox ✓ | Yes |

### Usage

```bash
# Default: auto-select encoder based on content analysis
python3 workflow_camcorder.py

# Force software encoding for all files
python3 workflow_camcorder.py --force-software

# Dry run to preview encoder selection
python3 workflow_camcorder.py --dry-run
```

### Additional Improvements

1. **Filesystem dates**: Now sets both EXIF metadata AND file modification time for proper Finder display (Created, Modified, Duration, Dimensions, Codecs)

2. **Default CRF changed**: 20 → 26 (actual compression instead of bloating)

3. **Output filename**: `YYYYMMDD_HHMMSS_CAM.h265.mp4` (distinguishes camcorder videos)


## Extended legacy codec conversion of camcorder MTS files:

SkyeWorkBookProM3:~/sandbox/repositories/personal/process-media$ python3 workflow_camcorder.py

======================================================================
Video Codec Conversion (H.264/MPEG-2 → H.265)
======================================================================

Found 462 video file(s) to analyze
Output directory: /Users/skye2k2/sandbox/repositories/personal/process-media/Organized_Videos
Encoding: H.265 (auto-select: VideoToolbox for clean, libx265 CRF 26 for noisy)
Files already in H.265/HEVC/AV1/VP9 will be skipped

⚠️  Original files will be DELETED after successful conversion
Continue? (Y/n): Y

----------------------------------------------------------------------
Building file index for fast lookups...
  Indexed 33460 files with 31764 unique base names
  Conversion index: 0 videos tracked

----------------------------------------------------------------------
Processing files...

  ## Processing: 00000.MTS (19.5 MB)
    Creation date: 2019-03-14 16:54:23 (from exiftool)
    Encoder: libx265 (high complexity (0.269 bpp > 0.17))
frame=  390 fps= 24 q=33.7 Lsize=   11112KiB time=00:00:12.91 bitrate=7049.7kbits/s speed=0.805x elapsed=0:00:16.04
encoded 390 frames in 16.02s (24.34 fps), 6790.63 kb/s, Avg QP:31.83
    **Converted: 10.9 MB (44.3% smaller) in 16.1s**
    Deleted original: 00000.MTS

  ## Processing: 00000.MTS (1100.2 MB)
    Creation date: 2024-05-14 12:16:04 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.157 bpp))
frame=37680 fps=266 q=-0.0 Lsize=  440396KiB time=00:20:57.22 bitrate=2869.6kbits/s speed=8.86x elapsed=0:02:21.83
    **Converted: 430.1 MB (60.9% smaller) in 141.9s**
    Deleted original: 00000.MTS

  ## Processing: 00000.MTS (69.7 MB)
    Creation date: 2016-03-14 12:46:47 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1410 fps= 25 q=33.4 Lsize=   25514KiB time=00:00:46.94 bitrate=4452.1kbits/s speed=0.831x elapsed=0:00:56.52
encoded 1410 frames in 56.51s (24.95 fps), 4239.13 kb/s, Avg QP:31.46
    **Converted: 24.9 MB (64.3% smaller) in 56.6s**
    Deleted original: 00000.MTS

  ## Processing: 00001.MTS (13.4 MB)
    Creation date: 2019-03-14 16:54:42 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame=  270 fps= 18 q=32.8 Lsize=    7562KiB time=00:00:08.90 bitrate=6953.3kbits/s speed=0.604x elapsed=0:00:14.75
encoded 270 frames in 14.74s (18.32 fps), 6669.46 kb/s, Avg QP:31.47
    **Converted: 7.4 MB (44.7% smaller) in 14.8s**
    Deleted original: 00001.MTS

  ## Processing: 00001.MTS (144.1 MB)
    Creation date: 2024-05-14 13:46:34 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.147 bpp))
frame= 5265 fps=263 q=-0.0 Lsize=   47966KiB time=00:02:55.64 bitrate=2237.1kbits/s speed=8.78x elapsed=0:00:19.99
    **Converted: 46.8 MB (67.5% smaller) in 20.1s**
    Deleted original: 00001.MTS

  ## Processing: 00001.MTS (105.1 MB)
    Creation date: 2016-03-14 17:45:52 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame= 2145 fps= 27 q=32.7 Lsize=   29574KiB time=00:01:11.47 bitrate=3389.7kbits/s speed=0.886x elapsed=0:01:20.63
encoded 2145 frames in 80.61s (26.61 fps), 3181.29 kb/s, Avg QP:31.44
    **Converted: 28.9 MB (72.5% smaller) in 80.7s**
    Deleted original: 00001.MTS

  ## Processing: 00002.MTS (85.9 MB)
    Creation date: 2019-03-14 17:13:31 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame= 1755 fps= 20 q=33.4 Lsize=   49325KiB time=00:00:58.45 bitrate=6912.1kbits/s speed=0.663x elapsed=0:01:28.13
encoded 1755 frames in 88.11s (19.92 fps), 6696.30 kb/s, Avg QP:31.47
    **Converted: 48.2 MB (43.9% smaller) in 88.3s**
    Deleted original: 00002.MTS

  ## Processing: 00002.MTS (221.2 MB)
    Creation date: 2024-05-14 13:49:35 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame= 7890 fps=264 q=-0.0 Lsize=   82601KiB time=00:04:23.22 bitrate=2570.6kbits/s speed=8.79x elapsed=0:00:29.93
    **Converted: 80.7 MB (63.5% smaller) in 30.0s**
    Deleted original: 00002.MTS

  ## Processing: 00002.MTS (478.2 MB)
    Creation date: 2016-03-14 19:23:04 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 9705 fps= 24 q=33.5 Lsize=  152802KiB time=00:05:23.72 bitrate=3866.7kbits/s speed=0.807x elapsed=0:06:41.16
encoded 9705 frames in 401.14s (24.19 fps), 3662.66 kb/s, Avg QP:31.46
    **Converted: 149.2 MB (68.8% smaller) in 401.2s**
    Deleted original: 00002.MTS

  ## Processing: 00003.MTS (21.3 MB)
    Creation date: 2019-03-14 20:19:29 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame=  435 fps= 26 q=33.6 Lsize=    4162KiB time=00:00:14.41 bitrate=2365.2kbits/s speed=0.859x elapsed=0:00:16.78
encoded 435 frames in 16.76s (25.95 fps), 2143.32 kb/s, Avg QP:31.19
    **Converted: 4.1 MB (80.9% smaller) in 16.9s**
    Deleted original: 00003.MTS

  ## Processing: 00003.MTS (42.5 MB)
    Creation date: 2024-05-17 17:33:45 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.147 bpp))
frame= 1560 fps=259 q=-0.0 Lsize=   20652KiB time=00:00:52.01 bitrate=3252.3kbits/s speed=8.63x elapsed=0:00:06.02
    **Converted: 20.2 MB (52.6% smaller) in 6.1s**
    Deleted original: 00003.MTS

  ## Processing: 00003.MTS (47.1 MB)
    Creation date: 2016-03-16 12:01:04 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame=  960 fps= 21 q=32.4 Lsize=   16285KiB time=00:00:31.93 bitrate=4177.9kbits/s speed=0.682x elapsed=0:00:46.78
encoded 960 frames in 46.77s (20.53 fps), 3961.02 kb/s, Avg QP:31.23
    **Converted: 15.9 MB (66.2% smaller) in 46.9s**
    Deleted original: 00003.MTS

  ## Processing: 00004.MTS (161.4 MB)
    Creation date: 2019-03-14 20:20:02 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame= 3255 fps= 24 q=32.6 Lsize=   44626KiB time=00:01:48.50 bitrate=3369.1kbits/s speed=0.794x elapsed=0:02:16.62
encoded 3255 frames in 136.61s (23.83 fps), 3162.35 kb/s, Avg QP:31.23
    **Converted: 43.6 MB (73.0% smaller) in 136.7s**
    Deleted original: 00004.MTS

  ## Processing: 00004.MTS (66.4 MB)
    Creation date: 2024-05-17 17:37:21 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.148 bpp))
frame= 2415 fps=259 q=-0.0 Lsize=   28908KiB time=00:01:20.54 bitrate=2940.1kbits/s speed=8.62x elapsed=0:00:09.33
    **Converted: 28.2 MB (57.5% smaller) in 9.4s**
    Deleted original: 00004.MTS

  ## Processing: 00004.MTS (84.2 MB)
    Creation date: 2016-03-16 12:30:54 (from exiftool)
    Encoder: libx265 (high complexity (0.268 bpp > 0.17))
frame= 1695 fps= 25 q=32.0 Lsize=   26711KiB time=00:00:56.45 bitrate=3875.8kbits/s speed=0.822x elapsed=0:01:08.70
encoded 1695 frames in 68.69s (24.68 fps), 3665.57 kb/s, Avg QP:31.41
    **Converted: 26.1 MB (69.0% smaller) in 68.8s**
    Deleted original: 00004.MTS

  ## Processing: 00005.MTS (31.2 MB)
    Creation date: 2019-03-25 18:33:09 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame=  630 fps= 22 q=33.5 Lsize=   23526KiB time=00:00:20.92 bitrate=9212.2kbits/s speed=0.727x elapsed=0:00:28.79
encoded 630 frames in 28.78s (21.89 fps), 8963.41 kb/s, Avg QP:31.71
    **Converted: 23.0 MB (26.5% smaller) in 28.9s**
    Deleted original: 00005.MTS

  ## Processing: 00005.MTS (58.7 MB)
    Creation date: 2024-05-17 17:41:16 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.147 bpp))
frame= 2145 fps=261 q=-0.0 Lsize=   27081KiB time=00:01:11.53 bitrate=3101.1kbits/s speed= 8.7x elapsed=0:00:08.22
    **Converted: 26.4 MB (55.0% smaller) in 8.3s**
    Deleted original: 00005.MTS

  ## Processing: 00005.MTS (246.4 MB)
    Creation date: 2016-03-22 09:50:11 (from exiftool)
    Encoder: libx265 (high complexity (0.263 bpp > 0.17))
frame= 5040 fps= 29 q=32.2 Lsize=   38254KiB time=00:02:48.06 bitrate=1864.6kbits/s speed=0.971x elapsed=0:02:53.02
encoded 5040 frames in 173.01s (29.13 fps), 1660.27 kb/s, Avg QP:31.08
    **Converted: 37.4 MB (84.8% smaller) in 173.1s**
    Deleted original: 00005.MTS

  ## Processing: 00006.MTS (82.0 MB)
    Creation date: 2019-03-25 18:35:43 (from exiftool)
    Encoder: libx265 (high complexity (0.270 bpp > 0.17))
frame= 1635 fps= 19 q=33.5 Lsize=   76005KiB time=00:00:54.45 bitrate=11434.0kbits/s speed=0.624x elapsed=0:01:27.22
encoded 1635 frames in 87.20s (18.75 fps), 11208.49 kb/s, Avg QP:31.86
    **Converted: 74.2 MB (9.5% smaller) in 87.3s**
    Deleted original: 00006.MTS

  ## Processing: 00006.MTS (4.8 MB)
    Creation date: 2024-05-17 17:50:08 (from exiftool)
    Encoder: libx265 (high complexity (0.190 bpp > 0.17))
frame=  135 fps= 20 q=32.9 Lsize=    3958KiB time=00:00:04.40 bitrate=7360.9kbits/s speed=0.667x elapsed=0:00:06.60
encoded 135 frames in 6.59s (20.49 fps), 6987.64 kb/s, Avg QP:31.59
    **Converted: 3.9 MB (19.0% smaller) in 6.7s**
    Deleted original: 00006.MTS

  ## Processing: 00006.MTS (37.5 MB)
    Creation date: 2016-03-22 09:53:13 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame=  765 fps= 30 q=32.1 Lsize=    4946KiB time=00:00:25.42 bitrate=1593.5kbits/s speed=0.981x elapsed=0:00:25.93
encoded 765 frames in 25.91s (29.52 fps), 1383.17 kb/s, Avg QP:31.00
    **Converted: 4.8 MB (87.1% smaller) in 26.0s**
    Deleted original: 00006.MTS

  ## Processing: 00007.MTS (38.2 MB)
    Creation date: 2019-03-25 18:40:02 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame=  750 fps= 15 q=33.1 Lsize=   49727KiB time=00:00:24.92 bitrate=16343.5kbits/s speed=0.511x elapsed=0:00:48.75
encoded 750 frames in 48.74s (15.39 fps), 16072.45 kb/s, Avg QP:31.83
    **Converted: 48.6 MB (-27.3% smaller) in 48.8s**
    Deleted original: 00007.MTS

  ## Processing: 00007.MTS (50.4 MB)
    Creation date: 2024-05-17 17:52:08 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.144 bpp))
frame= 1890 fps=260 q=-0.0 Lsize=   19408KiB time=00:01:03.02 bitrate=2522.5kbits/s speed=8.66x elapsed=0:00:07.27
    **Converted: 19.0 MB (62.4% smaller) in 7.3s**
    Deleted original: 00007.MTS

  ## Processing: 00007.MTS (85.7 MB)
    Creation date: 2016-03-22 17:21:31 (from exiftool)
    Encoder: libx265 (high complexity (0.265 bpp > 0.17))
frame= 1740 fps= 31 q=33.6 Lsize=   20642KiB time=00:00:57.95 bitrate=2917.6kbits/s speed=1.04x elapsed=0:00:55.71
encoded 1740 frames in 55.70s (31.24 fps), 2709.36 kb/s, Avg QP:31.48
    **Converted: 20.2 MB (76.5% smaller) in 55.8s**
    Deleted original: 00007.MTS

  ## Processing: 00008.MTS (22.9 MB)
    Creation date: 2019-03-25 18:53:53 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame=  450 fps= 21 q=34.2 Lsize=   20161KiB time=00:00:14.91 bitrate=11073.5kbits/s speed=0.685x elapsed=0:00:21.76
encoded 450 frames in 21.75s (20.69 fps), 10794.82 kb/s, Avg QP:32.28
    **Converted: 19.7 MB (14.2% smaller) in 21.8s**
    Deleted original: 00008.MTS

  ## Processing: 00008.MTS (37.8 MB)
    Creation date: 2024-05-17 17:58:30 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.144 bpp))
frame= 1410 fps=257 q=-0.0 Lsize=   15478KiB time=00:00:47.01 bitrate=2696.9kbits/s speed=8.58x elapsed=0:00:05.47
    **Converted: 15.1 MB (60.0% smaller) in 5.5s**
    Deleted original: 00008.MTS

  ## Processing: 00008.MTS (182.9 MB)
    Creation date: 2016-03-24 16:04:17 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame= 3735 fps= 32 q=32.0 Lsize=   29521KiB time=00:02:04.52 bitrate=1942.1kbits/s speed=1.05x elapsed=0:01:58.48
encoded 3735 frames in 118.46s (31.53 fps), 1736.36 kb/s, Avg QP:31.38
    **Converted: 28.8 MB (84.2% smaller) in 118.6s**
    Deleted original: 00008.MTS

  ## Processing: 00009.MTS (95.1 MB)
    Creation date: 2019-03-25 19:04:02 (from exiftool)
    Encoder: libx265 (high complexity (0.269 bpp > 0.17))
frame= 1905 fps= 18 q=32.5 Lsize=   76248KiB time=00:01:03.46 bitrate=9842.2kbits/s speed=0.595x elapsed=0:01:46.57
encoded 1905 frames in 106.56s (17.88 fps), 9623.18 kb/s, Avg QP:31.58
    **Converted: 74.5 MB (21.7% smaller) in 106.7s**
    Deleted original: 00009.MTS

  ## Processing: 00009.MTS (40.7 MB)
    Creation date: 2024-05-17 18:03:14 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 1515 fps=258 q=-0.0 Lsize=   16445KiB time=00:00:50.51 bitrate=2666.8kbits/s speed= 8.6x elapsed=0:00:05.87
    **Converted: 16.1 MB (60.5% smaller) in 5.9s**
    Deleted original: 00009.MTS

  ## Processing: 00009.MTS (131.7 MB)
    Creation date: 2016-03-24 16:11:46 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame= 2685 fps= 28 q=33.1 Lsize=   30312KiB time=00:01:29.48 bitrate=2774.8kbits/s speed=0.923x elapsed=0:01:36.93
encoded 2685 frames in 96.92s (27.70 fps), 2567.56 kb/s, Avg QP:31.46
    **Converted: 29.6 MB (77.5% smaller) in 97.0s**
    Deleted original: 00009.MTS

  ## Processing: 00010.MTS (118.1 MB)
    Creation date: 2019-03-25 19:40:36 (from exiftool)
    Encoder: libx265 (high complexity (0.270 bpp > 0.17))
frame= 2355 fps= 16 q=33.2 Lsize=   90188KiB time=00:01:18.47 bitrate=9414.3kbits/s speed=0.524x elapsed=0:02:29.84
encoded 2355 frames in 149.82s (15.72 fps), 9198.46 kb/s, Avg QP:31.66
    **Converted: 88.1 MB (25.5% smaller) in 149.9s**
    Deleted original: 00010.MTS

  ## Processing: 00010.MTS (26.3 MB)
    Creation date: 2024-05-17 18:07:29 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 1005 fps=254 q=-0.0 Lsize=    9887KiB time=00:00:33.50 bitrate=2417.8kbits/s speed=8.46x elapsed=0:00:03.96
    **Converted: 9.7 MB (63.3% smaller) in 4.0s**
    Deleted original: 00010.MTS

  ## Processing: 00010.MTS (504.4 MB)
    Creation date: 2016-03-26 09:22:07 (from exiftool)
    Encoder: libx265 (high complexity (0.269 bpp > 0.17))
frame=10095 fps= 17 q=32.9 Lsize=  428478KiB time=00:05:36.73 bitrate=10423.9kbits/s speed=0.583x elapsed=0:09:37.16
encoded 10095 frames in 577.14s (17.49 fps), 10217.66 kb/s, Avg QP:31.62
    **Converted: 418.4 MB (17.0% smaller) in 577.2s**
    Deleted original: 00010.MTS

  ## Processing: 00011.MTS (55.8 MB)
    Creation date: 2019-03-25 19:42:18 (from exiftool)
    Encoder: libx265 (high complexity (0.271 bpp > 0.17))
frame= 1110 fps= 19 q=33.3 Lsize=   36414KiB time=00:00:36.93 bitrate=8076.1kbits/s speed=0.621x elapsed=0:00:59.49
encoded 1110 frames in 59.48s (18.66 fps), 7849.69 kb/s, Avg QP:31.75
    **Converted: 35.6 MB (36.2% smaller) in 59.6s**
    Deleted original: 00011.MTS

  ## Processing: 00011.MTS (6.9 MB)
    Creation date: 2024-05-17 18:08:19 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame=  255 fps=227 q=-0.0 Lsize=    2740KiB time=00:00:08.47 bitrate=2648.8kbits/s speed=7.53x elapsed=0:00:01.12
    **Converted: 2.7 MB (61.1% smaller) in 1.2s**
    Deleted original: 00011.MTS

  ## Processing: 00011.MTS (180.9 MB)
    Creation date: 2016-03-30 08:38:37 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 3660 fps= 24 q=33.1 Lsize=   47990KiB time=00:02:02.02 bitrate=3221.8kbits/s speed=0.804x elapsed=0:02:31.74
encoded 3660 frames in 151.73s (24.12 fps), 3015.89 kb/s, Avg QP:31.22
    **Converted: 46.9 MB (74.1% smaller) in 151.8s**
    Deleted original: 00011.MTS

  ## Processing: 00012.MTS (17.4 MB)
    Creation date: 2019-03-25 19:43:28 (from exiftool)
    Encoder: libx265 (high complexity (0.271 bpp > 0.17))
frame=  345 fps= 15 q=33.7 Lsize=   17565KiB time=00:00:11.41 bitrate=12609.2kbits/s speed=0.496x elapsed=0:00:23.00
encoded 345 frames in 22.98s (15.01 fps), 12293.65 kb/s, Avg QP:31.76
    **Converted: 17.2 MB (1.4% smaller) in 23.1s**
    Deleted original: 00012.MTS

  ## Processing: 00012.MTS (6.7 MB)
    Creation date: 2024-05-17 18:08:41 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.161 bpp))
frame=  225 fps=221 q=-0.0 Lsize=    4572KiB time=00:00:07.47 bitrate=5011.4kbits/s speed=7.33x elapsed=0:00:01.01
    **Converted: 4.5 MB (33.6% smaller) in 1.1s**
    Deleted original: 00012.MTS

  ## Processing: 00012.MTS (49.4 MB)
    Creation date: 2016-04-03 10:34:34 (from exiftool)
    Encoder: libx265 (high complexity (0.265 bpp > 0.17))
frame= 1005 fps= 24 q=33.2 Lsize=   13270KiB time=00:00:33.43 bitrate=3251.5kbits/s speed=0.782x elapsed=0:00:42.76
encoded 1005 frames in 42.74s (23.51 fps), 3038.64 kb/s, Avg QP:31.35
    **Converted: 13.0 MB (73.8% smaller) in 42.8s**
    Deleted original: 00012.MTS

  ## Processing: 00013.MTS (50.4 MB)
    Creation date: 2019-03-25 19:44:07 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame=  990 fps= 13 q=32.9 Lsize=   84076KiB time=00:00:32.93 bitrate=20913.8kbits/s speed=0.446x elapsed=0:01:13.85
encoded 990 frames in 73.84s (13.41 fps), 20645.24 kb/s, Avg QP:32.19
    **Converted: 82.1 MB (-62.8% smaller) in 73.9s**
    Deleted original: 00013.MTS

  ## Processing: 00013.MTS (37.7 MB)
    Creation date: 2024-05-18 18:36:16 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 1440 fps=258 q=-0.0 Lsize=   10901KiB time=00:00:48.01 bitrate=1859.8kbits/s speed=8.59x elapsed=0:00:05.59
    **Converted: 10.6 MB (71.8% smaller) in 5.7s**
    Deleted original: 00013.MTS

  ## Processing: 00013.MTS (48.9 MB)
    Creation date: 2016-04-26 08:16:46 (from exiftool)
    Encoder: libx265 (high complexity (0.275 bpp > 0.17))
frame=  960 fps= 20 q=29.5 Lsize=   20684KiB time=00:00:31.93 bitrate=5306.4kbits/s speed=0.676x elapsed=0:00:47.24
encoded 960 frames in 47.23s (20.33 fps), 5085.80 kb/s, Avg QP:30.92
    **Converted: 20.2 MB (58.7% smaller) in 47.3s**
    Deleted original: 00013.MTS

  ## Processing: 00014.MTS (9.9 MB)
    Creation date: 2019-03-25 19:44:47 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame=  195 fps= 19 q=33.1 Lsize=    8755KiB time=00:00:06.40 bitrate=11194.9kbits/s speed=0.633x elapsed=0:00:10.12
encoded 195 frames in 10.10s (19.30 fps), 10814.20 kb/s, Avg QP:31.85
    **Converted: 8.5 MB (14.0% smaller) in 10.2s**
    Deleted original: 00014.MTS

  ## Processing: 00014.MTS (5.4 MB)
    Creation date: 2024-05-18 18:42:59 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.148 bpp))
frame=  195 fps=0.0 q=-0.0 Lsize=    1799KiB time=00:00:06.47 bitrate=2276.6kbits/s speed=7.23x elapsed=0:00:00.89
    **Converted: 1.8 MB (67.3% smaller) in 1.0s**
    Deleted original: 00014.MTS

  ## Processing: 00014.MTS (62.5 MB)
    Creation date: 2016-04-26 08:18:08 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 1230 fps= 21 q=32.4 Lsize=   27623KiB time=00:00:40.94 bitrate=5527.2kbits/s speed=0.689x elapsed=0:00:59.40
encoded 1230 frames in 59.39s (20.71 fps), 5310.23 kb/s, Avg QP:30.97
    **Converted: 27.0 MB (56.9% smaller) in 59.5s**
    Deleted original: 00014.MTS

  ## Processing: 00014.MTS (122.0 MB)
    Creation date: 2013-09-08 09:21:12 (from exiftool)
    Encoder: libx265 (high complexity (0.259 bpp > 0.17))
frame= 1905 fps= 18 q=33.2 Lsize=   31647KiB time=00:01:03.46 bitrate=4085.0kbits/s speed=0.589x elapsed=0:01:47.74
encoded 1905 frames in 107.72s (17.68 fps), 3872.62 kb/s, Avg QP:30.88
    **Converted: 30.9 MB (74.7% smaller) in 107.8s**
    Deleted original: 00014.MTS

  ## Processing: 00015.MTS (16.5 MB)
    Creation date: 2019-03-25 19:45:13 (from exiftool)
    Encoder: libx265 (high complexity (0.268 bpp > 0.17))
frame=  330 fps= 15 q=30.4 Lsize=    9045KiB time=00:00:10.91 bitrate=6791.0kbits/s speed=0.494x elapsed=0:00:22.10
encoded 330 frames in 22.08s (14.94 fps), 6521.54 kb/s, Avg QP:31.18
    **Converted: 8.8 MB (46.4% smaller) in 22.2s**
    Deleted original: 00015.MTS

  ## Processing: 00015.MTS (27.0 MB)
    Creation date: 2024-05-18 18:43:08 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 1005 fps=255 q=-0.0 Lsize=    9700KiB time=00:00:33.50 bitrate=2372.1kbits/s speed=8.49x elapsed=0:00:03.94
    **Converted: 9.5 MB (64.9% smaller) in 4.0s**
    Deleted original: 00015.MTS

  ## Processing: 00015.MTS (80.2 MB)
    Creation date: 2016-04-26 08:19:45 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 1575 fps= 22 q=32.0 Lsize=   29838KiB time=00:00:52.45 bitrate=4660.1kbits/s speed=0.726x elapsed=0:01:12.25
encoded 1575 frames in 72.24s (21.80 fps), 4447.76 kb/s, Avg QP:31.01
    **Converted: 29.1 MB (63.6% smaller) in 72.3s**
    Deleted original: 00015.MTS

  ## Processing: 00015.MTS (78.0 MB)
    Creation date: 2013-09-08 19:35:09 (from exiftool)
    Encoder: libx265 (high complexity (0.259 bpp > 0.17))
frame= 1215 fps= 20 q=32.6 Lsize=   18667KiB time=00:00:40.44 bitrate=3781.4kbits/s speed=0.654x elapsed=0:01:01.83
encoded 1215 frames in 61.82s (19.65 fps), 3567.90 kb/s, Avg QP:31.38
    **Converted: 18.2 MB (76.6% smaller) in 61.9s**
    Deleted original: 00015.MTS

  ## Processing: 00016.MTS (43.4 MB)
    Creation date: 2019-03-25 19:45:35 (from exiftool)
    Encoder: libx265 (high complexity (0.273 bpp > 0.17))
frame=  855 fps= 16 q=34.2 Lsize=   58370KiB time=00:00:28.42 bitrate=16820.0kbits/s speed=0.527x elapsed=0:00:53.99
encoded 855 frames in 53.97s (15.84 fps), 16557.30 kb/s, Avg QP:31.99
    **Converted: 57.0 MB (-31.4% smaller) in 54.1s**
    Deleted original: 00016.MTS

  ## Processing: 00016.MTS (32.1 MB)
    Creation date: 2024-05-18 18:46:32 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.144 bpp))
frame= 1200 fps=257 q=-0.0 Lsize=   10520KiB time=00:00:40.00 bitrate=2154.2kbits/s speed=8.56x elapsed=0:00:04.67
    **Converted: 10.3 MB (68.0% smaller) in 4.7s**
    Deleted original: 00016.MTS

  ## Processing: 00016.MTS (77.1 MB)
    Creation date: 2016-04-26 08:24:07 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 1515 fps= 22 q=32.3 Lsize=   30000KiB time=00:00:50.45 bitrate=4871.4kbits/s speed=0.724x elapsed=0:01:09.72
encoded 1515 frames in 69.70s (21.74 fps), 4658.14 kb/s, Avg QP:31.04
    **Converted: 29.3 MB (62.0% smaller) in 69.8s**
    Deleted original: 00016.MTS

  ## Processing: 00016.MTS (76.8 MB)
    Creation date: 2013-09-08 19:39:34 (from exiftool)
    Encoder: libx265 (high complexity (0.258 bpp > 0.17))
frame= 1200 fps= 20 q=33.4 Lsize=   22129KiB time=00:00:39.93 bitrate=4538.8kbits/s speed=0.657x elapsed=0:01:00.76
encoded 1200 frames in 60.75s (19.75 fps), 4323.97 kb/s, Avg QP:31.35
    **Converted: 21.6 MB (71.9% smaller) in 60.9s**
    Deleted original: 00016.MTS

  ## Processing: 00017.MTS (24.9 MB)
    Creation date: 2019-03-25 19:46:28 (from exiftool)
    Encoder: libx265 (high complexity (0.271 bpp > 0.17))
frame=  495 fps= 16 q=31.2 Lsize=   29836KiB time=00:00:16.41 bitrate=14888.6kbits/s speed=0.544x elapsed=0:00:30.16
encoded 495 frames in 30.15s (16.42 fps), 14592.73 kb/s, Avg QP:32.30
    **Converted: 29.1 MB (-16.9% smaller) in 30.3s**
    Deleted original: 00017.MTS

  ## Processing: 00017.MTS (36.2 MB)
    Creation date: 2024-05-18 18:52:16 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.144 bpp))
frame= 1350 fps=258 q=-0.0 Lsize=   13825KiB time=00:00:45.01 bitrate=2516.1kbits/s speed=8.59x elapsed=0:00:05.23
    **Converted: 13.5 MB (62.7% smaller) in 5.3s**
    Deleted original: 00017.MTS

  ## Processing: 00017.MTS (64.8 MB)
    Creation date: 2016-04-26 08:26:25 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 1275 fps= 21 q=29.4 Lsize=   22488KiB time=00:00:42.44 bitrate=4340.5kbits/s speed=0.689x elapsed=0:01:01.61
encoded 1275 frames in 61.60s (20.70 fps), 4126.27 kb/s, Avg QP:30.86
    **Converted: 22.0 MB (66.1% smaller) in 61.7s**
    Deleted original: 00017.MTS

  ## Processing: 00017.MTS (103.2 MB)
    Creation date: 2013-09-08 19:48:55 (from exiftool)
    Encoder: libx265 (high complexity (0.272 bpp > 0.17))
frame= 1530 fps= 18 q=32.0 Lsize=   26226KiB time=00:00:50.95 bitrate=4216.7kbits/s speed=0.613x elapsed=0:01:23.09
encoded 1530 frames in 83.07s (18.42 fps), 4005.64 kb/s, Avg QP:30.72
    **Converted: 25.6 MB (75.2% smaller) in 83.2s**
    Deleted original: 00017.MTS

  ## Processing: 00018.MTS (45.7 MB)
    Creation date: 2019-03-25 19:47:19 (from exiftool)
    Encoder: libx265 (high complexity (0.273 bpp > 0.17))
frame=  900 fps= 17 q=28.3 Lsize=   51244KiB time=00:00:29.92 bitrate=14025.9kbits/s speed=0.555x elapsed=0:00:53.88
encoded 900 frames in 53.86s (16.71 fps), 13773.90 kb/s, Avg QP:31.96
    **Converted: 50.0 MB (-9.6% smaller) in 54.0s**
    Deleted original: 00018.MTS

  ## Processing: 00018.MTS (29.8 MB)
    Creation date: 2024-05-18 18:55:01 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 1110 fps=256 q=-0.0 Lsize=   11729KiB time=00:00:37.00 bitrate=2596.7kbits/s speed=8.52x elapsed=0:00:04.34
    **Converted: 11.5 MB (61.5% smaller) in 4.4s**
    Deleted original: 00018.MTS

  ## Processing: 00018.MTS (145.7 MB)
    Creation date: 2016-04-26 08:28:49 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 2865 fps= 22 q=32.4 Lsize=   51992KiB time=00:01:35.49 bitrate=4460.1kbits/s speed=0.724x elapsed=0:02:11.89
encoded 2865 frames in 131.87s (21.73 fps), 4251.70 kb/s, Avg QP:30.99
    **Converted: 50.8 MB (65.2% smaller) in 132.0s**
    Deleted original: 00018.MTS

  ## Processing: 00018.MTS (127.6 MB)
    Creation date: 2013-09-10 23:54:04 (from exiftool)
    Encoder: libx265 (high complexity (0.257 bpp > 0.17))
frame= 2010 fps= 23 q=31.2 Lsize=   18612KiB time=00:01:06.96 bitrate=2276.8kbits/s speed=0.779x elapsed=0:01:25.99
encoded 2010 frames in 85.98s (23.38 fps), 2070.04 kb/s, Avg QP:30.83
    **Converted: 18.2 MB (85.8% smaller) in 86.1s**
    Deleted original: 00018.MTS

  ## Processing: 00019.MTS (9.8 MB)
    Creation date: 2019-03-25 19:47:54 (from exiftool)
    Encoder: libx265 (high complexity (0.271 bpp > 0.17))
frame=  195 fps= 18 q=30.9 Lsize=    5991KiB time=00:00:06.40 bitrate=7661.3kbits/s speed=0.581x elapsed=0:00:11.03
encoded 195 frames in 11.01s (17.71 fps), 7324.39 kb/s, Avg QP:31.54
    **Converted: 5.9 MB (40.6% smaller) in 11.1s**
    Deleted original: 00019.MTS

  ## Processing: 00019.MTS (4.2 MB)
    Creation date: 2024-05-18 19:02:49 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame=  150 fps=0.0 q=-0.0 Lsize=    2615KiB time=00:00:04.97 bitrate=4309.4kbits/s speed=6.87x elapsed=0:00:00.72
    **Converted: 2.6 MB (39.2% smaller) in 0.8s**
    Deleted original: 00019.MTS

  ## Processing: 00019.MTS (192.0 MB)
    Creation date: 2016-04-26 08:30:42 (from exiftool)
    Encoder: libx265 (high complexity (0.273 bpp > 0.17))
frame= 3795 fps= 22 q=32.3 Lsize=   66339KiB time=00:02:06.52 bitrate=4295.1kbits/s speed=0.736x elapsed=0:02:51.83
encoded 3795 frames in 171.81s (22.09 fps), 4088.70 kb/s, Avg QP:30.96
    **Converted: 64.8 MB (66.3% smaller) in 171.9s**
    Deleted original: 00019.MTS

  ## Processing: 00019.MTS (181.1 MB)
    Creation date: 2013-09-10 23:59:12 (from exiftool)
    Encoder: libx265 (high complexity (0.260 bpp > 0.17))
frame= 2820 fps= 16 q=31.5 Lsize=   48873KiB time=00:01:33.99 bitrate=4259.5kbits/s speed=0.543x elapsed=0:02:53.00
encoded 2820 frames in 172.98s (16.30 fps), 4052.20 kb/s, Avg QP:31.11
    **Converted: 47.7 MB (73.7% smaller) in 173.1s**
    Deleted original: 00019.MTS

  ## Processing: 00020.MTS (32.1 MB)
    Creation date: 2019-03-25 19:49:10 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame=  630 fps= 20 q=31.5 Lsize=   34152KiB time=00:00:20.92 bitrate=13372.8kbits/s speed=0.672x elapsed=0:00:31.15
encoded 630 frames in 31.13s (20.24 fps), 13104.18 kb/s, Avg QP:32.07
    **Converted: 33.4 MB (-4.0% smaller) in 31.2s**
    Deleted original: 00020.MTS

  ## Processing: 00020.MTS (6.7 MB)
    Creation date: 2024-05-18 19:04:41 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame=  240 fps=225 q=-0.0 Lsize=    3502KiB time=00:00:07.97 bitrate=3597.2kbits/s speed=7.48x elapsed=0:00:01.06
    **Converted: 3.4 MB (49.0% smaller) in 1.1s**
    Deleted original: 00020.MTS

  ## Processing: 00020.MTS (57.6 MB)
    Creation date: 2016-04-28 17:50:35 (from exiftool)
    Encoder: libx265 (high complexity (0.265 bpp > 0.17))
frame= 1170 fps= 22 q=32.8 Lsize=   16316KiB time=00:00:38.93 bitrate=3432.6kbits/s speed=0.724x elapsed=0:00:53.79
encoded 1170 frames in 53.78s (21.76 fps), 3219.52 kb/s, Avg QP:31.18
    **Converted: 15.9 MB (72.4% smaller) in 53.9s**
    Deleted original: 00020.MTS

  ## Processing: 00020.MTS (70.1 MB)
    Creation date: 2013-09-11 00:01:06 (from exiftool)
    Encoder: libx265 (high complexity (0.262 bpp > 0.17))
frame= 1080 fps= 17 q=31.9 Lsize=   16840KiB time=00:00:35.93 bitrate=3838.9kbits/s speed=0.578x elapsed=0:01:02.22
encoded 1080 frames in 62.20s (17.36 fps), 3624.58 kb/s, Avg QP:30.70
    **Converted: 16.4 MB (76.5% smaller) in 62.3s**
    Deleted original: 00020.MTS

  ## Processing: 00021.MTS (87.0 MB)
    Creation date: 2019-03-25 19:51:10 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 1710 fps= 18 q=30.7 Lsize=   83033KiB time=00:00:56.95 bitrate=11942.4kbits/s speed=0.593x elapsed=0:01:36.00
encoded 1710 frames in 95.98s (17.82 fps), 11717.19 kb/s, Avg QP:32.09
    **Converted: 81.1 MB (6.8% smaller) in 96.1s**
    Deleted original: 00021.MTS

  ## Processing: 00021.MTS (6.4 MB)
    Creation date: 2024-05-18 19:04:55 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.152 bpp))
frame=  225 fps=223 q=-0.0 Lsize=    3085KiB time=00:00:07.47 bitrate=3381.0kbits/s speed=7.41x elapsed=0:00:01.00
    **Converted: 3.0 MB (52.7% smaller) in 1.1s**
    Deleted original: 00021.MTS

  ## Processing: 00021.MTS (69.5 MB)
    Creation date: 2016-04-29 08:12:26 (from exiftool)
    Encoder: libx265 (high complexity (0.265 bpp > 0.17))
frame= 1410 fps= 32 q=33.4 Lsize=   13402KiB time=00:00:46.94 bitrate=2338.5kbits/s speed=1.06x elapsed=0:00:44.28
encoded 1410 frames in 44.26s (31.86 fps), 2130.40 kb/s, Avg QP:31.39
    **Converted: 13.1 MB (81.2% smaller) in 44.4s**
    Deleted original: 00021.MTS

  ## Processing: 00021.MTS (118.1 MB)
    Creation date: 2013-09-11 00:27:09 (from exiftool)
    Encoder: libx265 (high complexity (0.257 bpp > 0.17))
frame= 1860 fps= 17 q=33.4 Lsize=   28662KiB time=00:01:01.96 bitrate=3789.4kbits/s speed=0.579x elapsed=0:01:46.98
encoded 1860 frames in 106.97s (17.39 fps), 3579.61 kb/s, Avg QP:31.17
    **Converted: 28.0 MB (76.3% smaller) in 107.1s**
    Deleted original: 00021.MTS

  ## Processing: 00022.MTS (35.5 MB)
    Creation date: 2019-03-25 19:52:47 (from exiftool)
    Encoder: libx265 (high complexity (0.271 bpp > 0.17))
frame=  705 fps= 19 q=30.8 Lsize=   26755KiB time=00:00:23.42 bitrate=9357.3kbits/s speed=0.628x elapsed=0:00:37.30
encoded 705 frames in 37.29s (18.91 fps), 9113.14 kb/s, Avg QP:31.96
    **Converted: 26.1 MB (26.5% smaller) in 37.4s**
    Deleted original: 00022.MTS

  ## Processing: 00022.MTS (37.1 MB)
    Creation date: 2024-05-18 19:21:36 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.142 bpp))
frame= 1410 fps=258 q=-0.0 Lsize=   14454KiB time=00:00:47.01 bitrate=2518.5kbits/s speed=8.59x elapsed=0:00:05.47
    **Converted: 14.1 MB (61.9% smaller) in 5.5s**
    Deleted original: 00022.MTS

  ## Processing: 00022.MTS (64.6 MB)
    Creation date: 2016-04-29 08:13:42 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1305 fps= 25 q=33.1 Lsize=   18615KiB time=00:00:43.44 bitrate=3510.2kbits/s speed=0.847x elapsed=0:00:51.28
encoded 1305 frames in 51.26s (25.46 fps), 3298.34 kb/s, Avg QP:31.29
    **Converted: 18.2 MB (71.8% smaller) in 51.4s**
    Deleted original: 00022.MTS

  ## Processing: 00022.MTS (59.1 MB)
    Creation date: 2013-09-13 17:53:36 (from exiftool)
    Encoder: libx265 (high complexity (0.257 bpp > 0.17))
frame=  930 fps= 22 q=33.0 Lsize=   11131KiB time=00:00:30.93 bitrate=2948.0kbits/s speed=0.716x elapsed=0:00:43.18
encoded 930 frames in 43.16s (21.55 fps), 2734.61 kb/s, Avg QP:31.22
    **Converted: 10.9 MB (81.6% smaller) in 43.3s**
    Deleted original: 00022.MTS

  ## Processing: 00023.MTS (46.4 MB)
    Creation date: 2019-03-25 19:54:17 (from exiftool)
    Encoder: libx265 (high complexity (0.269 bpp > 0.17))
frame=  930 fps= 19 q=33.1 Lsize=   23335KiB time=00:00:30.93 bitrate=6180.2kbits/s speed=0.624x elapsed=0:00:49.54
encoded 930 frames in 49.53s (18.78 fps), 5955.93 kb/s, Avg QP:31.50
    **Converted: 22.8 MB (50.9% smaller) in 49.6s**
    Deleted original: 00023.MTS

  ## Processing: 00023.MTS (155.1 MB)
    Creation date: 2024-05-21 09:19:30 (from exiftool)
    Encoder: libx265 (high complexity (0.216 bpp > 0.17))
frame= 3870 fps= 18 q=33.8 Lsize=  245095KiB time=00:02:09.02 bitrate=15561.0kbits/s speed=0.585x elapsed=0:03:40.42
encoded 3870 frames in 220.41s (17.56 fps), 15345.55 kb/s, Avg QP:32.05
    **Converted: 239.4 MB (-54.3% smaller) in 220.5s**
    Deleted original: 00023.MTS

  ## Processing: 00023.MTS (31.1 MB)
    Creation date: 2016-05-07 17:44:39 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame=  630 fps= 27 q=32.8 Lsize=    5710KiB time=00:00:20.92 bitrate=2235.7kbits/s speed=0.902x elapsed=0:00:23.20
encoded 630 frames in 23.19s (27.17 fps), 2019.85 kb/s, Avg QP:31.27
    **Converted: 5.6 MB (82.1% smaller) in 23.3s**
    Deleted original: 00023.MTS

  ## Processing: 00023.MTS (193.8 MB)
    Creation date: 2013-09-13 18:00:48 (from exiftool)
    Encoder: libx265 (high complexity (0.257 bpp > 0.17))
frame= 3045 fps= 18 q=33.4 Lsize=   65704KiB time=00:01:41.50 bitrate=5302.8kbits/s speed=0.599x elapsed=0:02:49.41
encoded 3045 frames in 169.39s (17.98 fps), 5094.29 kb/s, Avg QP:31.25
    **Converted: 64.2 MB (66.9% smaller) in 169.5s**
    Deleted original: 00023.MTS

  ## Processing: 00024.MTS (136.4 MB)
    Creation date: 2019-03-25 19:55:26 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 2685 fps= 16 q=30.7 Lsize=  149834KiB time=00:01:29.48 bitrate=13716.1kbits/s speed=0.549x elapsed=0:02:42.88
encoded 2685 frames in 162.87s (16.49 fps), 13497.25 kb/s, Avg QP:31.86
    **Converted: 146.3 MB (-7.3% smaller) in 163.0s**
    Deleted original: 00024.MTS

  ## Processing: 00024.MTS (287.9 MB)
    Creation date: 2024-05-21 09:27:35 (from exiftool)
    Encoder: libx265 (high complexity (0.216 bpp > 0.17))
frame= 7185 fps= 16 q=34.1 Lsize=  528410KiB time=00:03:59.63 bitrate=18063.6kbits/s speed=0.527x elapsed=0:07:34.42
encoded 7185 frames in 454.41s (15.81 fps), 17853.14 kb/s, Avg QP:32.18
    **Converted: 516.0 MB (-79.2% smaller) in 454.5s**
    Deleted original: 00024.MTS

  ## Processing: 00024.MTS (99.3 MB)
    Creation date: 2016-05-09 11:31:15 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 2010 fps= 24 q=33.3 Lsize=   36324KiB time=00:01:06.96 bitrate=4443.5kbits/s speed=0.787x elapsed=0:01:25.10
encoded 2010 frames in 85.08s (23.62 fps), 4233.10 kb/s, Avg QP:31.21
    **Converted: 35.5 MB (64.3% smaller) in 85.2s**
    Deleted original: 00024.MTS

  ## Processing: 00024.MTS (109.1 MB)
    Creation date: 2013-09-16 09:06:03 (from exiftool)
    Encoder: libx265 (high complexity (0.260 bpp > 0.17))
frame= 1695 fps= 22 q=32.4 Lsize=   31345KiB time=00:00:56.45 bitrate=4548.3kbits/s speed=0.734x elapsed=0:01:16.96
encoded 1695 frames in 76.94s (22.03 fps), 4336.41 kb/s, Avg QP:31.18
    **Converted: 30.6 MB (71.9% smaller) in 77.1s**
    Deleted original: 00024.MTS

  ## Processing: 00025.MTS (3.9 MB)
    Creation date: 2019-03-25 19:56:57 (from exiftool)
    Encoder: libx265 (high complexity (0.278 bpp > 0.17))
frame=   75 fps= 15 q=30.1 Lsize=    3764KiB time=00:00:02.40 bitrate=12835.4kbits/s speed=0.488x elapsed=0:00:04.92
encoded 75 frames in 4.90s (15.29 fps), 12103.24 kb/s, Avg QP:31.66
    **Converted: 3.7 MB (5.8% smaller) in 5.0s**
    Deleted original: 00025.MTS

  ## Processing: 00025.MTS (28.1 MB)
    Creation date: 2024-06-28 21:32:37 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame= 1005 fps=256 q=-0.0 Lsize=    5377KiB time=00:00:33.50 bitrate=1314.9kbits/s speed=8.52x elapsed=0:00:03.93
    **Converted: 5.3 MB (81.3% smaller) in 4.0s**
    Deleted original: 00025.MTS

  ## Processing: 00025.MTS (81.4 MB)
    Creation date: 2016-05-09 19:00:34 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1650 fps= 27 q=32.0 Lsize=   20851KiB time=00:00:54.95 bitrate=3108.2kbits/s speed=0.905x elapsed=0:01:00.70
encoded 1650 frames in 60.68s (27.19 fps), 2899.57 kb/s, Avg QP:31.36
    **Converted: 20.4 MB (75.0% smaller) in 60.8s**
    Deleted original: 00025.MTS

  ## Processing: 00025.MTS (50.4 MB)
    Creation date: 2013-09-16 18:52:11 (from exiftool)
    Encoder: libx265 (high complexity (0.256 bpp > 0.17))
frame=  795 fps= 19 q=33.0 Lsize=   12348KiB time=00:00:26.42 bitrate=3827.8kbits/s speed=0.628x elapsed=0:00:42.06
encoded 795 frames in 42.04s (18.91 fps), 3609.78 kb/s, Avg QP:31.36
    **Converted: 12.1 MB (76.1% smaller) in 42.2s**
    Deleted original: 00025.MTS

  ## Processing: 00026.MTS (35.1 MB)
    Creation date: 2019-03-25 20:01:09 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame=  690 fps= 18 q=31.1 Lsize=   35711KiB time=00:00:22.92 bitrate=12762.1kbits/s speed=0.613x elapsed=0:00:37.37
encoded 690 frames in 37.36s (18.47 fps), 12502.09 kb/s, Avg QP:31.90
    **Converted: 34.9 MB (0.8% smaller) in 37.5s**
    Deleted original: 00026.MTS

  ## Processing: 00026.MTS (37.3 MB)
    Creation date: 2024-07-05 22:21:45 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.126 bpp))
frame= 1590 fps=257 q=-0.0 Lsize=    4216KiB time=00:00:53.01 bitrate= 651.4kbits/s speed=8.57x elapsed=0:00:06.18
    **Converted: 4.1 MB (89.0% smaller) in 6.3s**
    Deleted original: 00026.MTS

  ## Processing: 00026.MTS (77.2 MB)
    Creation date: 2016-05-12 18:40:04 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame= 1560 fps= 23 q=32.5 Lsize=   19696KiB time=00:00:51.95 bitrate=3105.8kbits/s speed=0.775x elapsed=0:01:07.04
encoded 1560 frames in 67.02s (23.28 fps), 2896.13 kb/s, Avg QP:31.32
    **Converted: 19.2 MB (75.1% smaller) in 67.1s**
    Deleted original: 00026.MTS

  ## Processing: 00026.MTS (265.0 MB)
    Creation date: 2013-09-16 18:52:57 (from exiftool)
    Encoder: libx265 (high complexity (0.256 bpp > 0.17))
frame= 4185 fps= 20 q=33.2 Lsize=   59764KiB time=00:02:19.53 bitrate=3508.6kbits/s speed=0.659x elapsed=0:03:31.87
encoded 4185 frames in 211.86s (19.75 fps), 3303.57 kb/s, Avg QP:31.19
    **Converted: 58.4 MB (78.0% smaller) in 212.0s**
    Deleted original: 00026.MTS

  ## Processing: 00027.MTS (41.7 MB)
    Creation date: 2019-03-26 11:44:31 (from exiftool)
    Encoder: libx265 (high complexity (0.268 bpp > 0.17))
frame=  840 fps= 21 q=33.2 Lsize=   21966KiB time=00:00:27.92 bitrate=6443.2kbits/s speed=0.702x elapsed=0:00:39.79
encoded 840 frames in 39.77s (21.12 fps), 6216.67 kb/s, Avg QP:31.62
    **Converted: 21.5 MB (48.6% smaller) in 39.9s**
    Deleted original: 00027.MTS

  ## Processing: 00027.MTS (20.0 MB)
    Creation date: 2024-07-16 20:26:51 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.130 bpp))
frame=  825 fps=251 q=-0.0 Lsize=    6859KiB time=00:00:27.49 bitrate=2043.8kbits/s speed=8.36x elapsed=0:00:03.28
    **Converted: 6.7 MB (66.5% smaller) in 3.4s**
    Deleted original: 00027.MTS

  ## Processing: 00027.MTS (179.2 MB)
    Creation date: 2016-05-17 19:58:13 (from exiftool)
    Encoder: libx265 (high complexity (0.263 bpp > 0.17))
frame= 3675 fps= 26 q=33.4 Lsize=   56301KiB time=00:02:02.52 bitrate=3764.3kbits/s speed=0.879x elapsed=0:02:19.34
encoded 3675 frames in 139.33s (26.38 fps), 3557.23 kb/s, Avg QP:31.37
    **Converted: 55.0 MB (69.3% smaller) in 139.4s**
    Deleted original: 00027.MTS

  ## Processing: 00027.MTS (34.3 MB)
    Creation date: 2013-09-16 18:58:45 (from exiftool)
    Encoder: libx265 (high complexity (0.256 bpp > 0.17))
frame=  540 fps= 19 q=32.6 Lsize=    7075KiB time=00:00:17.91 bitrate=3234.7kbits/s speed=0.639x elapsed=0:00:28.03
encoded 540 frames in 28.01s (19.28 fps), 3010.51 kb/s, Avg QP:31.20
    **Converted: 6.9 MB (79.8% smaller) in 28.1s**
    Deleted original: 00027.MTS

  ## Processing: 00028.MTS (41.5 MB)
    Creation date: 2019-03-27 14:03:22 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame=  840 fps= 21 q=33.9 Lsize=   29204KiB time=00:00:27.92 bitrate=8566.4kbits/s speed=0.713x elapsed=0:00:39.18
encoded 840 frames in 39.16s (21.45 fps), 8331.60 kb/s, Avg QP:31.62
    **Converted: 28.5 MB (31.3% smaller) in 39.3s**
    Deleted original: 00028.MTS

  ## Processing: 00028.MTS (1132.0 MB)
    Creation date: 2024-07-26 15:07:02 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.155 bpp))
frame=39240 fps=264 q=-0.0 Lsize=  267472KiB time=00:21:49.27 bitrate=1673.5kbits/s speed= 8.8x elapsed=0:02:28.83
    **Converted: 261.2 MB (76.9% smaller) in 148.9s**
    Deleted original: 00028.MTS

  ## Processing: 00028.MTS (98.6 MB)
    Creation date: 2016-05-18 17:40:45 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1995 fps= 25 q=33.2 Lsize=   22210KiB time=00:01:06.46 bitrate=2737.3kbits/s speed=0.84x elapsed=0:01:19.08
encoded 1995 frames in 79.06s (25.23 fps), 2529.87 kb/s, Avg QP:31.33
    **Converted: 21.7 MB (78.0% smaller) in 79.2s**
    Deleted original: 00028.MTS

  ## Processing: 00029.MTS (205.0 MB)
    Creation date: 2019-03-27 14:03:59 (from exiftool)
    Encoder: libx265 (high complexity (0.270 bpp > 0.17))
frame= 4095 fps= 16 q=33.2 Lsize=  203470KiB time=00:02:16.53 bitrate=12207.9kbits/s speed=0.532x elapsed=0:04:16.76
encoded 4095 frames in 256.74s (15.95 fps), 11995.17 kb/s, Avg QP:31.87
    **Converted: 198.7 MB (3.1% smaller) in 256.9s**
    Deleted original: 00029.MTS

  ## Processing: 00029.MTS (28.2 MB)
    Creation date: 2024-08-03 21:48:08 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.135 bpp))
frame= 1125 fps=254 q=-0.0 Lsize=    3903KiB time=00:00:37.50 bitrate= 852.5kbits/s speed=8.47x elapsed=0:00:04.42
    **Converted: 3.8 MB (86.5% smaller) in 4.5s**
    Deleted original: 00029.MTS

  ## Processing: 00029.MTS (99.2 MB)
    Creation date: 2016-05-20 20:53:28 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 1950 fps= 20 q=32.0 Lsize=   54264KiB time=00:01:04.96 bitrate=6842.6kbits/s speed=0.652x elapsed=0:01:39.64
encoded 1950 frames in 99.63s (19.57 fps), 6628.24 kb/s, Avg QP:30.94
    **Converted: 53.0 MB (46.6% smaller) in 99.7s**
    Deleted original: 00029.MTS

  ## Processing: 00029.MTS (157.0 MB)
    Creation date: 2013-09-20 19:15:53 (from exiftool)
    Encoder: libx265 (high complexity (0.255 bpp > 0.17))
frame= 2490 fps= 20 q=32.1 Lsize=   37415KiB time=00:01:22.98 bitrate=3693.5kbits/s speed=0.68x elapsed=0:02:02.07
encoded 2490 frames in 122.06s (20.40 fps), 3477.35 kb/s, Avg QP:31.14
    **Converted: 36.5 MB (76.7% smaller) in 122.2s**
    Deleted original: 00029.MTS

  ## Processing: 00030.MTS (94.5 MB)
    Creation date: 2019-03-27 14:06:58 (from exiftool)
    Encoder: libx265 (high complexity (0.271 bpp > 0.17))
frame= 1875 fps= 16 q=33.7 Lsize=  100540KiB time=00:01:02.46 bitrate=13185.9kbits/s speed=0.543x elapsed=0:01:54.95
encoded 1875 frames in 114.93s (16.31 fps), 12960.79 kb/s, Avg QP:31.97
    **Converted: 98.2 MB (-3.9% smaller) in 115.2s**
    Deleted original: 00030.MTS

  ## Processing: 00030.MTS (5.0 MB)
    Creation date: 2024-09-08 18:48:28 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.138 bpp))
frame=  195 fps=0.0 q=-0.0 Lsize=     777KiB time=00:00:06.47 bitrate= 982.8kbits/s speed=7.15x elapsed=0:00:00.90
    **Converted: 0.8 MB (84.9% smaller) in 1.0s**
    Deleted original: 00030.MTS

  ## Processing: 00030.MTS (13.0 MB)
    Creation date: 2016-05-20 20:58:14 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame=  255 fps= 19 q=32.2 Lsize=    7148KiB time=00:00:08.40 bitrate=6964.4kbits/s speed=0.635x elapsed=0:00:13.24
encoded 255 frames in 13.23s (19.28 fps), 6676.22 kb/s, Avg QP:30.91
    **Converted: 7.0 MB (46.2% smaller) in 13.3s**
    Deleted original: 00030.MTS

  ## Processing: 00031.MTS (196.1 MB)
    Creation date: 2019-03-29 20:52:19 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 3855 fps= 22 q=32.2 Lsize=   77419KiB time=00:02:08.52 bitrate=4934.5kbits/s speed=0.727x elapsed=0:02:56.72
encoded 3855 frames in 176.71s (21.82 fps), 4727.93 kb/s, Avg QP:31.16
    **Converted: 75.6 MB (61.4% smaller) in 176.8s**
    Deleted original: 00031.MTS

  ## Processing: 00031.MTS (26.1 MB)
    Creation date: 2024-09-08 18:48:36 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.142 bpp))
frame=  990 fps=253 q=-0.0 Lsize=    7689KiB time=00:00:32.99 bitrate=1908.7kbits/s speed=8.44x elapsed=0:00:03.90
    **Converted: 7.5 MB (71.2% smaller) in 4.0s**
    Deleted original: 00031.MTS

  ## Processing: 00031.MTS (116.0 MB)
    Creation date: 2016-05-20 20:58:36 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 2280 fps= 20 q=32.8 Lsize=   60679KiB time=00:01:15.97 bitrate=6542.6kbits/s speed=0.677x elapsed=0:01:52.22
encoded 2280 frames in 112.21s (20.32 fps), 6329.62 kb/s, Avg QP:30.93
    **Converted: 59.3 MB (48.9% smaller) in 112.3s**
    Deleted original: 00031.MTS

  ## Processing: 00031.MTS (68.3 MB)
    Creation date: 2013-09-22 15:07:30 (from exiftool)
    Encoder: libx265 (high complexity (0.263 bpp > 0.17))
frame= 1050 fps= 19 q=31.9 Lsize=   19714KiB time=00:00:34.93 bitrate=4622.8kbits/s speed=0.634x elapsed=0:00:55.08
encoded 1050 frames in 55.06s (19.07 fps), 4406.52 kb/s, Avg QP:30.81
    **Converted: 19.3 MB (71.8% smaller) in 55.2s**
    Deleted original: 00031.MTS

  ## Processing: 00032.MTS (222.7 MB)
    Creation date: 2019-03-29 20:55:45 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 4380 fps= 24 q=32.2 Lsize=   80060KiB time=00:02:26.04 bitrate=4490.7kbits/s speed=0.807x elapsed=0:03:00.94
encoded 4380 frames in 180.93s (24.21 fps), 4284.70 kb/s, Avg QP:31.18
    **Converted: 78.2 MB (64.9% smaller) in 181.0s**
    Deleted original: 00032.MTS

  ## Processing: 00032.MTS (54.6 MB)
    Creation date: 2024-10-08 19:04:54 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.138 bpp))
frame= 2130 fps=250 q=-0.0 Lsize=    9289KiB time=00:01:11.03 bitrate=1071.2kbits/s speed=8.34x elapsed=0:00:08.51
    **Converted: 9.1 MB (83.4% smaller) in 8.6s**
    Deleted original: 00032.MTS

  ## Processing: 00032.MTS (63.6 MB)
    Creation date: 2016-05-22 17:40:17 (from exiftool)
    Encoder: libx265 (high complexity (0.265 bpp > 0.17))
frame= 1290 fps= 29 q=32.8 Lsize=   12407KiB time=00:00:42.94 bitrate=2366.9kbits/s speed=0.955x elapsed=0:00:44.98
encoded 1290 frames in 44.97s (28.68 fps), 2158.03 kb/s, Avg QP:31.33
    **Converted: 12.1 MB (80.9% smaller) in 45.1s**
    Deleted original: 00032.MTS

  ## Processing: 00032.MTS (104.2 MB)
    Creation date: 2013-09-22 15:08:32 (from exiftool)
    Encoder: libx265 (high complexity (0.262 bpp > 0.17))
frame= 1605 fps= 19 q=32.4 Lsize=   29563KiB time=00:00:53.45 bitrate=4530.6kbits/s speed=0.644x elapsed=0:01:23.04
encoded 1605 frames in 83.02s (19.33 fps), 4318.96 kb/s, Avg QP:30.80
    **Converted: 28.9 MB (72.3% smaller) in 83.1s**
    Deleted original: 00032.MTS

  ## Processing: 00033.MTS (24.4 MB)
    Creation date: 2019-03-29 20:58:13 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame=  480 fps= 24 q=32.7 Lsize=    8830KiB time=00:00:15.91 bitrate=4544.8kbits/s speed=0.79x elapsed=0:00:20.14
encoded 480 frames in 20.12s (23.85 fps), 4311.57 kb/s, Avg QP:31.16
    **Converted: 8.6 MB (64.7% smaller) in 20.2s**
    Deleted original: 00033.MTS

  ## Processing: 00033.MTS (168.2 MB)
    Creation date: 2024-12-19 14:27:56 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.149 bpp))
frame= 6090 fps=263 q=-0.0 Lsize=  100153KiB time=00:03:23.16 bitrate=4038.3kbits/s speed=8.77x elapsed=0:00:23.17
    **Converted: 97.8 MB (41.9% smaller) in 23.3s**
    Deleted original: 00033.MTS

  ## Processing: 00033.MTS (212.7 MB)
    Creation date: 2016-05-24 10:50:34 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 4185 fps= 14 q=31.3 Lsize=  241976KiB time=00:02:19.53 bitrate=14205.8kbits/s speed=0.463x elapsed=0:05:01.28
encoded 4185 frames in 301.26s (13.89 fps), 13990.37 kb/s, Avg QP:31.85
    **Converted: 236.3 MB (-11.1% smaller) in 301.4s**
    Deleted original: 00033.MTS

  ## Processing: 00033.MTS (213.0 MB)
    Creation date: 2013-09-29 09:49:32 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame= 3225 fps= 17 q=32.2 Lsize=  110277KiB time=00:01:47.50 bitrate=8403.0kbits/s speed=0.578x elapsed=0:03:06.11
encoded 3225 frames in 186.10s (17.33 fps), 8190.89 kb/s, Avg QP:31.32
    **Converted: 107.7 MB (49.4% smaller) in 186.2s**
    Deleted original: 00033.MTS

  ## Processing: 00034.MTS (78.4 MB)
    Creation date: 2019-04-12 19:48:27 (from exiftool)
    Encoder: libx265 (high complexity (0.260 bpp > 0.17))
frame= 1620 fps= 28 q=32.4 Lsize=   21496KiB time=00:00:53.95 bitrate=3263.8kbits/s speed=0.935x elapsed=0:00:57.71
encoded 1620 frames in 57.70s (28.08 fps), 3054.65 kb/s, Avg QP:30.91
    **Converted: 21.0 MB (73.2% smaller) in 57.8s**
    Deleted original: 00034.MTS

  ## Processing: 00034.MTS (131.8 MB)
    Creation date: 2024-12-19 14:53:18 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.152 bpp))
frame= 4680 fps=262 q=-0.0 Lsize=   87837KiB time=00:02:36.12 bitrate=4608.9kbits/s speed=8.74x elapsed=0:00:17.85
    **Converted: 85.8 MB (34.9% smaller) in 17.9s**
    Deleted original: 00034.MTS

  ## Processing: 00034.MTS (185.9 MB)
    Creation date: 2016-05-25 11:27:08 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 3660 fps= 20 q=32.7 Lsize=  101686KiB time=00:02:02.02 bitrate=6826.8kbits/s speed=0.654x elapsed=0:03:06.66
encoded 3660 frames in 186.65s (19.61 fps), 6618.17 kb/s, Avg QP:31.72
    **Converted: 99.3 MB (46.6% smaller) in 186.8s**
    Deleted original: 00034.MTS

  ## Processing: 00035.MTS (35.4 MB)
    Creation date: 2019-04-22 16:42:10 (from exiftool)
    Encoder: libx265 (high complexity (0.265 bpp > 0.17))
frame=  720 fps= 30 q=32.8 Lsize=    6052KiB time=00:00:23.92 bitrate=2072.3kbits/s speed=1.01x elapsed=0:00:23.76
encoded 720 frames in 23.75s (30.31 fps), 1860.03 kb/s, Avg QP:31.32
    **Converted: 5.9 MB (83.3% smaller) in 23.8s**
    Deleted original: 00035.MTS

  ## Processing: 00035.MTS (130.9 MB)
    Creation date: 2024-12-25 08:23:53 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.147 bpp))
frame= 4800 fps=263 q=-0.0 Lsize=   30018KiB time=00:02:40.12 bitrate=1535.7kbits/s speed=8.78x elapsed=0:00:18.24
    **Converted: 29.3 MB (77.6% smaller) in 18.3s**
    Deleted original: 00035.MTS

  ## Processing: 00035.MTS (282.2 MB)
    Creation date: 2016-05-25 11:29:41 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 5550 fps= 17 q=31.9 Lsize=  176571KiB time=00:03:05.08 bitrate=7815.2kbits/s speed=0.579x elapsed=0:05:19.78
encoded 5550 frames in 319.76s (17.36 fps), 7606.98 kb/s, Avg QP:31.56
    **Converted: 172.4 MB (38.9% smaller) in 319.9s**
    Deleted original: 00035.MTS

  ## Processing: 00036.MTS (12.7 MB)
    Creation date: 2019-04-22 16:43:07 (from exiftool)
    Encoder: libx265 (high complexity (0.268 bpp > 0.17))
frame=  255 fps= 25 q=32.2 Lsize=    2434KiB time=00:00:08.40 bitrate=2371.3kbits/s speed=0.826x elapsed=0:00:10.17
encoded 255 frames in 10.16s (25.10 fps), 2137.17 kb/s, Avg QP:31.17
    **Converted: 2.4 MB (81.3% smaller) in 10.3s**
    Deleted original: 00036.MTS

  ## Processing: 00036.MTS (102.6 MB)
    Creation date: 2024-12-25 08:27:51 (from exiftool)
    Encoder: libx265 (high complexity (0.193 bpp > 0.17))
frame= 2865 fps= 25 q=33.1 Lsize=   55928KiB time=00:01:35.49 bitrate=4797.8kbits/s speed=0.83x elapsed=0:01:55.02
encoded 2865 frames in 115.01s (24.91 fps), 4587.71 kb/s, Avg QP:31.33
    **Converted: 54.6 MB (46.8% smaller) in 115.1s**
    Deleted original: 00036.MTS

  ## Processing: 00036.MTS (348.6 MB)
    Creation date: 2016-05-25 11:33:17 (from exiftool)
    Encoder: libx265 (high complexity (0.273 bpp > 0.17))
frame= 6870 fps= 20 q=33.0 Lsize=  194841KiB time=00:03:49.12 bitrate=6966.1kbits/s speed=0.672x elapsed=0:05:41.21
encoded 6870 frames in 341.19s (20.14 fps), 6759.61 kb/s, Avg QP:31.57
    **Converted: 190.3 MB (45.4% smaller) in 341.3s**
    Deleted original: 00036.MTS

  ## Processing: 00037.MTS (57.1 MB)
    Creation date: 2019-05-01 11:41:51 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1155 fps= 25 q=32.7 Lsize=   13898KiB time=00:00:38.43 bitrate=2961.9kbits/s speed=0.826x elapsed=0:00:46.55
encoded 1155 frames in 46.53s (24.82 fps), 2750.64 kb/s, Avg QP:31.28
    **Converted: 13.6 MB (76.2% smaller) in 46.6s**
    Deleted original: 00037.MTS

  ## Processing: 00037.MTS (42.9 MB)
    Creation date: 2024-12-25 08:33:10 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.157 bpp))
frame= 1470 fps=258 q=-0.0 Lsize=    8573KiB time=00:00:49.01 bitrate=1432.8kbits/s speed= 8.6x elapsed=0:00:05.69
    **Converted: 8.4 MB (80.5% smaller) in 5.8s**
    Deleted original: 00037.MTS

  ## Processing: 00037.MTS (184.5 MB)
    Creation date: 2016-05-25 11:37:36 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 3630 fps= 19 q=32.6 Lsize=  101049KiB time=00:02:01.02 bitrate=6840.1kbits/s speed=0.641x elapsed=0:03:08.69
encoded 3630 frames in 188.68s (19.24 fps), 6631.70 kb/s, Avg QP:31.48
    **Converted: 98.7 MB (46.5% smaller) in 188.8s**
    Deleted original: 00037.MTS

  ## Processing: 00038.MTS (97.9 MB)
    Creation date: 2019-05-01 11:44:00 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1980 fps= 27 q=32.6 Lsize=   24370KiB time=00:01:05.96 bitrate=3026.3kbits/s speed=0.887x elapsed=0:01:14.41
encoded 1980 frames in 74.39s (26.62 fps), 2818.23 kb/s, Avg QP:31.47
    **Converted: 23.8 MB (75.7% smaller) in 74.5s**
    Deleted original: 00038.MTS

  ## Processing: 00038.MTS (31.4 MB)
    Creation date: 2025-02-03 21:03:45 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.125 bpp))
frame= 1350 fps=255 q=-0.0 Lsize=    3004KiB time=00:00:45.01 bitrate= 546.7kbits/s speed= 8.5x elapsed=0:00:05.29
    **Converted: 2.9 MB (90.7% smaller) in 5.4s**
    Deleted original: 00038.MTS

  ## Processing: 00038.MTS (96.9 MB)
    Creation date: 2016-05-25 11:40:14 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 1905 fps= 17 q=32.6 Lsize=   60552KiB time=00:01:03.46 bitrate=7816.1kbits/s speed=0.581x elapsed=0:01:49.17
encoded 1905 frames in 109.16s (17.45 fps), 7599.43 kb/s, Avg QP:31.55
    **Converted: 59.1 MB (39.0% smaller) in 109.3s**
    Deleted original: 00038.MTS

  ## Processing: 00039.MTS (74.1 MB)
    Creation date: 2019-05-01 11:48:22 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1500 fps= 28 q=33.2 Lsize=   16659KiB time=00:00:49.94 bitrate=2732.2kbits/s speed=0.916x elapsed=0:00:54.52
encoded 1500 frames in 54.51s (27.52 fps), 2522.37 kb/s, Avg QP:31.50
    **Converted: 16.3 MB (78.0% smaller) in 54.6s**
    Deleted original: 00039.MTS

  ## Processing: 00039.MTS (48.5 MB)
    Creation date: 2025-02-12 20:37:07 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.138 bpp))
frame= 1890 fps=259 q=-0.0 Lsize=   12327KiB time=00:01:03.02 bitrate=1602.2kbits/s speed=8.63x elapsed=0:00:07.30
    **Converted: 12.0 MB (75.2% smaller) in 7.4s**
    Deleted original: 00039.MTS

  ## Processing: 00039.MTS (37.5 MB)
    Creation date: 2016-05-25 11:42:03 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame=  735 fps= 20 q=29.9 Lsize=   23677KiB time=00:00:24.42 bitrate=7941.2kbits/s speed=0.666x elapsed=0:00:36.66
encoded 735 frames in 36.65s (20.06 fps), 7703.31 kb/s, Avg QP:31.75
    **Converted: 23.1 MB (38.3% smaller) in 36.8s**
    Deleted original: 00039.MTS

  ## Processing: 00039.MTS (9.1 MB)
    Creation date: 2013-10-22 13:10:08 (from exiftool)
    Encoder: libx265 (high complexity (0.272 bpp > 0.17))
frame=  135 fps= 16 q=32.3 Lsize=    3386KiB time=00:00:04.40 bitrate=6297.3kbits/s speed=0.53x elapsed=0:00:08.31
encoded 135 frames in 8.29s (16.28 fps), 5944.82 kb/s, Avg QP:30.81
    **Converted: 3.3 MB (63.7% smaller) in 8.4s**
    Deleted original: 00039.MTS

  ## Processing: 00040.MTS (13.3 MB)
    Creation date: 2019-05-01 11:50:02 (from exiftool)
    Encoder: libx265 (high complexity (0.265 bpp > 0.17))
frame=  270 fps= 26 q=32.0 Lsize=    2403KiB time=00:00:08.90 bitrate=2210.0kbits/s speed=0.864x elapsed=0:00:10.31
encoded 270 frames in 10.29s (26.23 fps), 1977.67 kb/s, Avg QP:30.94
    **Converted: 2.3 MB (82.4% smaller) in 10.4s**
    Deleted original: 00040.MTS

  ## Processing: 00040.MTS (3.6 MB)
    Creation date: 2025-02-14 12:09:03 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.160 bpp))
frame=  120 fps=0.0 q=-0.0 Lsize=    1444KiB time=00:00:03.97 bitrate=2978.3kbits/s speed=6.37x elapsed=0:00:00.62
    **Converted: 1.4 MB (60.6% smaller) in 0.7s**
    Deleted original: 00040.MTS

  ## Processing: 00040.MTS (52.0 MB)
    Creation date: 2016-05-25 11:42:35 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 1020 fps= 21 q=32.9 Lsize=   31720KiB time=00:00:33.93 bitrate=7657.5kbits/s speed=0.696x elapsed=0:00:48.75
encoded 1020 frames in 48.74s (20.93 fps), 7430.94 kb/s, Avg QP:31.65
    **Converted: 31.0 MB (40.4% smaller) in 48.8s**
    Deleted original: 00040.MTS

  ## Processing: 00040.MTS (96.2 MB)
    Creation date: 2013-10-22 13:10:15 (from exiftool)
    Encoder: libx265 (high complexity (0.273 bpp > 0.17))
frame= 1425 fps= 17 q=32.1 Lsize=   33318KiB time=00:00:47.44 bitrate=5752.5kbits/s speed=0.568x elapsed=0:01:23.60
encoded 1425 frames in 83.58s (17.05 fps), 5536.35 kb/s, Avg QP:30.81
    **Converted: 32.5 MB (66.2% smaller) in 83.7s**
    Deleted original: 00040.MTS

  ## Processing: 00041.MTS (102.1 MB)
    Creation date: 2019-05-03 19:04:49 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame= 2085 fps= 24 q=32.7 Lsize=   30954KiB time=00:01:09.46 bitrate=3650.1kbits/s speed=0.809x elapsed=0:01:25.86
encoded 2085 frames in 85.85s (24.29 fps), 3440.29 kb/s, Avg QP:31.01
    **Converted: 30.2 MB (70.4% smaller) in 85.9s**
    Deleted original: 00041.MTS

  ## Processing: 00041.MTS (6.4 MB)
    Creation date: 2025-02-14 12:09:21 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.152 bpp))
frame=  225 fps=220 q=-0.0 Lsize=    3063KiB time=00:00:07.47 bitrate=3357.1kbits/s speed=7.31x elapsed=0:00:01.02
    **Converted: 3.0 MB (53.0% smaller) in 1.1s**
    Deleted original: 00041.MTS

  ## Processing: 00041.MTS (263.0 MB)
    Creation date: 2016-05-25 11:43:18 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 5175 fps= 18 q=30.7 Lsize=  152778KiB time=00:02:52.57 bitrate=7252.4kbits/s speed=0.614x elapsed=0:04:41.05
encoded 5175 frames in 281.04s (18.41 fps), 7044.99 kb/s, Avg QP:31.52
    **Converted: 149.2 MB (43.3% smaller) in 281.1s**
    Deleted original: 00041.MTS

  ## Processing: 00041.MTS (127.9 MB)
    Creation date: 2013-10-23 08:58:07 (from exiftool)
    Encoder: libx265 (high complexity (0.257 bpp > 0.17))
frame= 2010 fps= 24 q=33.2 Lsize=   14759KiB time=00:01:06.96 bitrate=1805.5kbits/s speed=0.816x elapsed=0:01:22.08
encoded 2010 frames in 82.06s (24.49 fps), 1598.26 kb/s, Avg QP:31.19
    **Converted: 14.4 MB (88.7% smaller) in 82.2s**
    Deleted original: 00041.MTS

  ## Processing: 00042.MTS (247.9 MB)
    Creation date: 2019-05-04 09:40:56 (from exiftool)
    Encoder: libx265 (high complexity (0.269 bpp > 0.17))
frame= 4965 fps= 26 q=33.4 Lsize=   78604KiB time=00:02:45.56 bitrate=3889.2kbits/s speed=0.875x elapsed=0:03:09.27
encoded 4965 frames in 189.26s (26.23 fps), 3683.31 kb/s, Avg QP:31.49
    **Converted: 76.8 MB (69.0% smaller) in 189.4s**
    Deleted original: 00042.MTS

  ## Processing: 00042.MTS (14.6 MB)
    Creation date: 2025-02-14 12:10:11 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame=  525 fps=243 q=-0.0 Lsize=    6618KiB time=00:00:17.48 bitrate=3100.6kbits/s speed=8.11x elapsed=0:00:02.15
    **Converted: 6.5 MB (55.7% smaller) in 2.2s**
    Deleted original: 00042.MTS

  ## Processing: 00042.MTS (63.4 MB)
    Creation date: 2016-05-28 19:17:14 (from exiftool)
    Encoder: libx265 (high complexity (0.259 bpp > 0.17))
frame= 1320 fps= 28 q=33.4 Lsize=   17573KiB time=00:00:43.94 bitrate=3276.0kbits/s speed=0.941x elapsed=0:00:46.71
encoded 1320 frames in 46.70s (28.27 fps), 3063.46 kb/s, Avg QP:31.15
    **Converted: 17.2 MB (72.9% smaller) in 46.8s**
    Deleted original: 00042.MTS

  ## Processing: 00042.MTS (24.8 MB)
    Creation date: 2013-10-23 09:00:17 (from exiftool)
    Encoder: libx265 (high complexity (0.256 bpp > 0.17))
frame=  390 fps= 23 q=32.5 Lsize=    3260KiB time=00:00:12.91 bitrate=2068.1kbits/s speed=0.746x elapsed=0:00:17.30
encoded 390 frames in 17.28s (22.57 fps), 1846.30 kb/s, Avg QP:31.07
    **Converted: 3.2 MB (87.1% smaller) in 17.4s**
    Deleted original: 00042.MTS

  ## Processing: 00043.MTS (118.5 MB)
    Creation date: 2019-05-04 09:44:03 (from exiftool)
    Encoder: libx265 (high complexity (0.268 bpp > 0.17))
frame= 2385 fps= 26 q=32.4 Lsize=   31041KiB time=00:01:19.47 bitrate=3199.4kbits/s speed=0.857x elapsed=0:01:32.77
encoded 2385 frames in 92.75s (25.71 fps), 2992.16 kb/s, Avg QP:31.32
    **Converted: 30.3 MB (74.4% smaller) in 92.9s**
    Deleted original: 00043.MTS

  ## Processing: 00043.MTS (7.7 MB)
    Creation date: 2025-02-14 12:29:11 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.153 bpp))
frame=  270 fps=228 q=-0.0 Lsize=    4802KiB time=00:00:08.97 bitrate=4382.6kbits/s speed=7.57x elapsed=0:00:01.18
    **Converted: 4.7 MB (38.8% smaller) in 1.3s**
    Deleted original: 00043.MTS

  ## Processing: 00043.MTS (103.9 MB)
    Creation date: 2016-06-01 10:43:05 (from exiftool)
    Encoder: libx265 (high complexity (0.265 bpp > 0.17))
frame= 2115 fps= 30 q=32.3 Lsize=   25005KiB time=00:01:10.47 bitrate=2906.8kbits/s speed=   1x elapsed=0:01:10.43
encoded 2115 frames in 70.42s (30.03 fps), 2699.25 kb/s, Avg QP:31.23
    **Converted: 24.4 MB (76.5% smaller) in 70.5s**
    Deleted original: 00043.MTS

  ## Processing: 00043.MTS (300.2 MB)
    Creation date: 2013-10-27 14:52:33 (from exiftool)
    Encoder: libx265 (high complexity (0.256 bpp > 0.17))
frame= 4740 fps= 23 q=32.2 Lsize=   41901KiB time=00:02:38.05 bitrate=2171.7kbits/s speed=0.779x elapsed=0:03:22.83
encoded 4740 frames in 202.81s (23.37 fps), 1966.57 kb/s, Avg QP:30.97
    **Converted: 40.9 MB (86.4% smaller) in 202.9s**
    Deleted original: 00043.MTS

  ## Processing: 00044.MTS (30.6 MB)
    Creation date: 2019-05-04 09:45:40 (from exiftool)
    Encoder: libx265 (high complexity (0.268 bpp > 0.17))
frame=  615 fps= 24 q=32.8 Lsize=    8706KiB time=00:00:20.42 bitrate=3492.6kbits/s speed=0.788x elapsed=0:00:25.92
encoded 615 frames in 25.91s (23.74 fps), 3270.94 kb/s, Avg QP:31.39
    **Converted: 8.5 MB (72.2% smaller) in 26.0s**
    Deleted original: 00044.MTS

  ## Processing: 00044.MTS (7.2 MB)
    Creation date: 2025-02-14 12:29:31 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.152 bpp))
frame=  255 fps=227 q=-0.0 Lsize=    4549KiB time=00:00:08.47 bitrate=4397.1kbits/s speed=7.53x elapsed=0:00:01.12
    **Converted: 4.4 MB (38.1% smaller) in 1.2s**
    Deleted original: 00044.MTS

  ## Processing: 00045.MTS (94.5 MB)
    Creation date: 2019-05-04 10:12:20 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame= 1905 fps= 25 q=32.8 Lsize=   25652KiB time=00:01:03.46 bitrate=3311.2kbits/s speed=0.834x elapsed=0:01:16.07
encoded 1905 frames in 76.06s (25.05 fps), 3102.97 kb/s, Avg QP:31.32
    **Converted: 25.1 MB (73.5% smaller) in 76.2s**
    Deleted original: 00045.MTS

  ## Processing: 00045.MTS (17.0 MB)
    Creation date: 2025-02-14 12:51:11 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.146 bpp))
frame=  630 fps=234 q=-0.0 Lsize=    8179KiB time=00:00:20.98 bitrate=3192.4kbits/s speed=7.81x elapsed=0:00:02.68
    **Converted: 8.0 MB (53.1% smaller) in 2.8s**
    Deleted original: 00045.MTS

  ## Processing: 00045.MTS (207.8 MB)
    Creation date: 2016-06-05 19:00:00 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame= 4200 fps= 32 q=33.4 Lsize=   45464KiB time=00:02:20.03 bitrate=2659.5kbits/s speed=1.06x elapsed=0:02:12.35
encoded 4200 frames in 132.33s (31.74 fps), 2454.81 kb/s, Avg QP:31.49
    **Converted: 44.4 MB (78.6% smaller) in 132.4s**
    Deleted original: 00045.MTS

  ## Processing: 00045.MTS (213.4 MB)
    Creation date: 2013-11-15 19:38:02 (from exiftool)
    Encoder: libx265 (high complexity (0.257 bpp > 0.17))
frame= 3360 fps= 21 q=32.1 Lsize=   33866KiB time=00:01:52.01 bitrate=2476.8kbits/s speed=0.708x elapsed=0:02:38.30
encoded 3360 frames in 158.28s (21.23 fps), 2270.56 kb/s, Avg QP:31.02
    **Converted: 33.1 MB (84.5% smaller) in 158.4s**
    Deleted original: 00045.MTS

  ## Processing: 00046.MTS (50.3 MB)
    Creation date: 2019-05-04 10:14:13 (from exiftool)
    Encoder: libx265 (high complexity (0.270 bpp > 0.17))
frame= 1005 fps= 24 q=32.7 Lsize=   18415KiB time=00:00:33.43 bitrate=4512.1kbits/s speed=0.787x elapsed=0:00:42.47
encoded 1005 frames in 42.46s (23.67 fps), 4295.10 kb/s, Avg QP:31.38
    **Converted: 18.0 MB (64.2% smaller) in 42.6s**
    Deleted original: 00046.MTS

  ## Processing: 00046.MTS (19.6 MB)
    Creation date: 2025-02-14 13:13:51 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame=  750 fps=249 q=-0.0 Lsize=    6270KiB time=00:00:24.99 bitrate=2055.3kbits/s speed=8.31x elapsed=0:00:03.00
    **Converted: 6.1 MB (68.8% smaller) in 3.1s**
    Deleted original: 00046.MTS

  ## Processing: 00046.MTS (178.5 MB)
    Creation date: 2016-06-05 19:12:06 (from exiftool)
    Encoder: libx265 (high complexity (0.265 bpp > 0.17))
frame= 3630 fps= 24 q=32.0 Lsize=   59207KiB time=00:02:01.02 bitrate=4007.8kbits/s speed=0.809x elapsed=0:02:29.64
encoded 3630 frames in 149.63s (24.26 fps), 3800.84 kb/s, Avg QP:31.24
    **Converted: 57.8 MB (67.6% smaller) in 149.7s**
    Deleted original: 00046.MTS

  ## Processing: 00046.MTS (71.3 MB)
    Creation date: 2013-11-15 19:40:19 (from exiftool)
    Encoder: libx265 (high complexity (0.256 bpp > 0.17))
frame= 1125 fps= 20 q=31.8 Lsize=   10696KiB time=00:00:37.43 bitrate=2340.4kbits/s speed=0.676x elapsed=0:00:55.36
encoded 1125 frames in 55.34s (20.33 fps), 2127.73 kb/s, Avg QP:30.91
    **Converted: 10.4 MB (85.3% smaller) in 55.5s**
    Deleted original: 00046.MTS

  ## Processing: 00047.MTS (111.6 MB)
    Creation date: 2019-05-04 10:17:09 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame= 2250 fps= 27 q=32.6 Lsize=   25829KiB time=00:01:14.97 bitrate=2822.1kbits/s speed=0.911x elapsed=0:01:22.30
encoded 2250 frames in 82.29s (27.34 fps), 2615.33 kb/s, Avg QP:31.33
    **Converted: 25.2 MB (77.4% smaller) in 82.4s**
    Deleted original: 00047.MTS

  ## Processing: 00047.MTS (25.4 MB)
    Creation date: 2025-02-14 13:20:28 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.140 bpp))
frame=  975 fps=253 q=-0.0 Lsize=    8192KiB time=00:00:32.49 bitrate=2064.9kbits/s speed=8.44x elapsed=0:00:03.85
    **Converted: 8.0 MB (68.5% smaller) in 3.9s**
    Deleted original: 00047.MTS

  ## Processing: 00047.MTS (153.5 MB)
    Creation date: 2016-06-11 17:33:16 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 3105 fps= 31 q=33.3 Lsize=   24616KiB time=00:01:43.50 bitrate=1948.3kbits/s speed=1.02x elapsed=0:01:41.28
encoded 3105 frames in 101.27s (30.66 fps), 1743.47 kb/s, Avg QP:31.29
    **Converted: 24.0 MB (84.3% smaller) in 101.4s**
    Deleted original: 00047.MTS

  ## Processing: 00047.MTS (216.5 MB)
    Creation date: 2013-11-16 10:30:22 (from exiftool)
    Encoder: libx265 (high complexity (0.273 bpp > 0.17))
frame= 3210 fps= 18 q=32.1 Lsize=   66262KiB time=00:01:47.00 bitrate=5072.7kbits/s speed=0.605x elapsed=0:02:56.88
encoded 3210 frames in 176.86s (18.15 fps), 4863.14 kb/s, Avg QP:30.77
    **Converted: 64.7 MB (70.1% smaller) in 177.0s**
    Deleted original: 00047.MTS

  ## Processing: 00048.MTS (17.2 MB)
    Creation date: 2019-05-04 10:18:48 (from exiftool)
    Encoder: libx265 (high complexity (0.269 bpp > 0.17))
frame=  345 fps= 23 q=33.3 Lsize=    4992KiB time=00:00:11.41 bitrate=3584.0kbits/s speed=0.775x elapsed=0:00:14.72
encoded 345 frames in 14.70s (23.46 fps), 3347.86 kb/s, Avg QP:31.35
    **Converted: 4.9 MB (71.7% smaller) in 14.8s**
    Deleted original: 00048.MTS

  ## Processing: 00048.MTS (33.4 MB)
    Creation date: 2025-02-14 13:50:56 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.138 bpp))
frame= 1305 fps=257 q=-0.0 Lsize=   10856KiB time=00:00:43.51 bitrate=2044.0kbits/s speed=8.56x elapsed=0:00:05.08
    **Converted: 10.6 MB (68.3% smaller) in 5.2s**
    Deleted original: 00048.MTS

  ## Processing: 00048.MTS (422.8 MB)
    Creation date: 2016-06-26 17:45:05 (from exiftool)
    Encoder: libx265 (high complexity (0.270 bpp > 0.17))
frame= 8445 fps= 24 q=33.3 Lsize=  170793KiB time=00:04:41.68 bitrate=4967.1kbits/s speed=0.785x elapsed=0:05:58.63
encoded 8445 frames in 358.62s (23.55 fps), 4758.62 kb/s, Avg QP:31.26
    **Converted: 166.8 MB (60.6% smaller) in 358.7s**
    Deleted original: 00048.MTS

  ## Processing: 00048.MTS (52.5 MB)
    Creation date: 2013-11-20 18:53:26 (from exiftool)
    Encoder: libx265 (high complexity (0.257 bpp > 0.17))
frame=  825 fps= 24 q=33.2 Lsize=    6017KiB time=00:00:27.42 bitrate=1797.2kbits/s speed=0.811x elapsed=0:00:33.82
encoded 825 frames in 33.80s (24.41 fps), 1586.22 kb/s, Avg QP:31.21
    **Converted: 5.9 MB (88.8% smaller) in 33.9s**
    Deleted original: 00048.MTS

  ## Processing: 00049.MTS (221.3 MB)
    Creation date: 2019-05-28 10:55:08 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 4350 fps= 16 q=33.5 Lsize=  272650KiB time=00:02:25.04 bitrate=15399.0kbits/s speed=0.537x elapsed=0:04:30.30
encoded 4350 frames in 270.28s (16.09 fps), 15185.25 kb/s, Avg QP:31.81
    **Converted: 266.3 MB (-20.3% smaller) in 270.4s**
    Deleted original: 00049.MTS

  ## Processing: 00049.MTS (25.6 MB)
    Creation date: 2025-02-19 21:09:47 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.142 bpp))
frame=  975 fps=254 q=-0.0 Lsize=    2589KiB time=00:00:32.49 bitrate= 652.6kbits/s speed=8.47x elapsed=0:00:03.83
    **Converted: 2.5 MB (90.1% smaller) in 3.9s**
    Deleted original: 00049.MTS

  ## Processing: 00049.MTS (121.3 MB)
    Creation date: 2016-07-04 21:50:51 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame= 2475 fps= 21 q=32.3 Lsize=   31993KiB time=00:01:22.48 bitrate=3177.5kbits/s speed=0.714x elapsed=0:01:55.55
encoded 2475 frames in 115.54s (21.42 fps), 2969.84 kb/s, Avg QP:30.58
    **Converted: 31.2 MB (74.3% smaller) in 115.6s**
    Deleted original: 00049.MTS

  ## Processing: 00049.MTS (111.9 MB)
    Creation date: 2013-11-21 11:06:22 (from exiftool)
    Encoder: libx265 (high complexity (0.272 bpp > 0.17))
frame= 1665 fps= 17 q=31.8 Lsize=   32003KiB time=00:00:55.45 bitrate=4727.6kbits/s speed=0.577x elapsed=0:01:36.15
encoded 1665 frames in 96.14s (17.32 fps), 4515.71 kb/s, Avg QP:30.77
    **Converted: 31.3 MB (72.1% smaller) in 96.3s**
    Deleted original: 00049.MTS

  ## Processing: 00050.MTS (58.6 MB)
    Creation date: 2019-08-10 09:38:25 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1185 fps= 33 q=33.3 Lsize=   11936KiB time=00:00:39.43 bitrate=2479.2kbits/s speed=1.11x elapsed=0:00:35.64
encoded 1185 frames in 35.63s (33.26 fps), 2269.63 kb/s, Avg QP:31.76
    **Converted: 11.7 MB (80.1% smaller) in 35.7s**
    Deleted original: 00050.MTS

  ## Processing: 00050.MTS (24.6 MB)
    Creation date: 2025-02-19 21:10:47 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.147 bpp))
frame=  900 fps=253 q=-0.0 Lsize=    2675KiB time=00:00:29.99 bitrate= 730.7kbits/s speed=8.43x elapsed=0:00:03.55
    **Converted: 2.6 MB (89.4% smaller) in 3.6s**
    Deleted original: 00050.MTS

  ## Processing: 00050.MTS (15.8 MB)
    Creation date: 2016-07-04 21:52:18 (from exiftool)
    Encoder: libx265 (high complexity (0.257 bpp > 0.17))
frame=  330 fps= 24 q=28.7 Lsize=    3175KiB time=00:00:10.91 bitrate=2384.0kbits/s speed=0.782x elapsed=0:00:13.95
encoded 330 frames in 13.94s (23.68 fps), 2156.52 kb/s, Avg QP:30.39
    **Converted: 3.1 MB (80.3% smaller) in 14.0s**
    Deleted original: 00050.MTS

  ## Processing: 00050.MTS (28.4 MB)
    Creation date: 2013-11-21 11:07:24 (from exiftool)
    Encoder: libx265 (high complexity (0.273 bpp > 0.17))
frame=  420 fps= 14 q=32.5 Lsize=   10946KiB time=00:00:13.91 bitrate=6444.5kbits/s speed=0.46x elapsed=0:00:30.21
encoded 420 frames in 30.19s (13.91 fps), 6193.19 kb/s, Avg QP:30.85
    **Converted: 10.7 MB (62.4% smaller) in 30.3s**
    Deleted original: 00050.MTS

  ## Processing: 00051.MTS (42.9 MB)
    Creation date: 2019-09-07 16:47:04 (from exiftool)
    Encoder: libx265 (high complexity (0.265 bpp > 0.17))
frame=  870 fps= 21 q=32.5 Lsize=   14600KiB time=00:00:28.92 bitrate=4134.4kbits/s speed=0.702x elapsed=0:00:41.19
encoded 870 frames in 41.18s (21.13 fps), 3915.45 kb/s, Avg QP:31.36
    **Converted: 14.3 MB (66.7% smaller) in 41.3s**
    Deleted original: 00051.MTS

  ## Processing: 00051.MTS (50.5 MB)
    Creation date: 2016-07-04 21:53:06 (from exiftool)
    Encoder: libx265 (high complexity (0.263 bpp > 0.17))
frame= 1035 fps= 28 q=32.1 Lsize=    6372KiB time=00:00:34.43 bitrate=1516.0kbits/s speed=0.935x elapsed=0:00:36.83
encoded 1035 frames in 36.81s (28.11 fps), 1306.21 kb/s, Avg QP:30.67
    **Converted: 6.2 MB (87.7% smaller) in 36.9s**
    Deleted original: 00051.MTS

  ## Processing: 00051.MTS (143.1 MB)
    Creation date: 2013-11-22 22:41:05 (from exiftool)
    Encoder: libx265 (high complexity (0.257 bpp > 0.17))
frame= 2250 fps= 22 q=32.6 Lsize=   37566KiB time=00:01:14.97 bitrate=4104.6kbits/s speed=0.726x elapsed=0:01:43.30
encoded 2250 frames in 103.28s (21.78 fps), 3895.44 kb/s, Avg QP:31.17
    **Converted: 36.7 MB (74.4% smaller) in 103.4s**
    Deleted original: 00051.MTS

  ## Processing: 00052.MTS (46.4 MB)
    Creation date: 2019-12-25 09:12:12 (from exiftool)
    Encoder: libx265 (high complexity (0.273 bpp > 0.17))
frame=  915 fps= 19 q=32.3 Lsize=   17204KiB time=00:00:30.43 bitrate=4631.4kbits/s speed=0.635x elapsed=0:00:47.93
encoded 915 frames in 47.91s (19.10 fps), 4411.07 kb/s, Avg QP:31.20
    **Converted: 16.8 MB (63.8% smaller) in 48.0s**
    Deleted original: 00052.MTS

  ## Processing: 00052.MTS (25.9 MB)
    Creation date: 2025-02-28 22:39:23 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.124 bpp))
frame= 1125 fps=253 q=-0.0 Lsize=    2117KiB time=00:00:37.50 bitrate= 462.3kbits/s speed=8.43x elapsed=0:00:04.44
    **Converted: 2.1 MB (92.0% smaller) in 4.5s**
    Deleted original: 00052.MTS

  ## Processing: 00052.MTS (162.3 MB)
    Creation date: 2016-07-08 16:13:50 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame= 3315 fps= 29 q=33.0 Lsize=   18099KiB time=00:01:50.51 bitrate=1341.6kbits/s speed=0.983x elapsed=0:01:52.47
encoded 3315 frames in 112.46s (29.48 fps), 1135.67 kb/s, Avg QP:31.15
    **Converted: 17.7 MB (89.1% smaller) in 112.6s**
    Deleted original: 00052.MTS

  ## Processing: 00052.MTS (21.8 MB)
    Creation date: 2013-11-23 12:45:22 (from exiftool)
    Encoder: libx265 (high complexity (0.256 bpp > 0.17))
frame=  345 fps= 20 q=32.7 Lsize=    4540KiB time=00:00:11.41 bitrate=3258.9kbits/s speed=0.673x elapsed=0:00:16.95
encoded 345 frames in 16.93s (20.38 fps), 3025.63 kb/s, Avg QP:31.21
    **Converted: 4.4 MB (79.7% smaller) in 17.0s**
    Deleted original: 00052.MTS

  ## Processing: 00053.MTS (121.7 MB)
    Creation date: 2019-12-25 11:12:40 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 2460 fps= 23 q=32.8 Lsize=   39256KiB time=00:01:21.98 bitrate=3922.6kbits/s speed=0.764x elapsed=0:01:47.26
encoded 2460 frames in 107.25s (22.94 fps), 3712.44 kb/s, Avg QP:31.21
    **Converted: 38.3 MB (68.5% smaller) in 107.4s**
    Deleted original: 00053.MTS

  ## Processing: 00053.MTS (8.1 MB)
    Creation date: 2025-03-07 16:48:20 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.154 bpp))
frame=  285 fps=232 q=-0.0 Lsize=    4262KiB time=00:00:09.47 bitrate=3684.4kbits/s speed=7.71x elapsed=0:00:01.22
    **Converted: 4.2 MB (48.9% smaller) in 1.3s**
    Deleted original: 00053.MTS

  ## Processing: 00053.MTS (91.9 MB)
    Creation date: 2016-07-18 18:59:57 (from exiftool)
    Encoder: libx265 (high complexity (0.270 bpp > 0.17))
frame= 1830 fps= 22 q=31.6 Lsize=   20658KiB time=00:01:00.96 bitrate=2776.1kbits/s speed=0.725x elapsed=0:01:24.07
encoded 1830 frames in 84.05s (21.77 fps), 2568.61 kb/s, Avg QP:30.82
    **Converted: 20.2 MB (78.0% smaller) in 84.1s**
    Deleted original: 00053.MTS

  ## Processing: 00053.MTS (225.1 MB)
    Creation date: 2013-11-23 12:45:49 (from exiftool)
    Encoder: libx265 (high complexity (0.258 bpp > 0.17))
frame= 3525 fps= 25 q=32.5 Lsize=   18706KiB time=00:01:57.51 bitrate=1304.0kbits/s speed=0.822x elapsed=0:02:22.99
encoded 3525 frames in 142.97s (24.66 fps), 1100.53 kb/s, Avg QP:31.35
    **Converted: 18.3 MB (91.9% smaller) in 143.1s**
    Deleted original: 00053.MTS

  ## Processing: 00054.MTS (53.7 MB)
    Creation date: 2020-09-08 19:10:20 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.146 bpp))
frame= 1980 fps=261 q=-0.0 Lsize=   15533KiB time=00:01:06.03 bitrate=1927.0kbits/s speed=8.69x elapsed=0:00:07.59
    **Converted: 15.2 MB (71.8% smaller) in 7.7s**
    Deleted original: 00054.MTS

  ## Processing: 00054.MTS (6.3 MB)
    Creation date: 2025-03-07 16:48:47 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  225 fps=225 q=-0.0 Lsize=    2944KiB time=00:00:07.47 bitrate=3226.5kbits/s speed=7.47x elapsed=0:00:01.00
    **Converted: 2.9 MB (54.4% smaller) in 1.1s**
    Deleted original: 00054.MTS

  ## Processing: 00054.MTS (45.0 MB)
    Creation date: 2016-07-18 19:11:52 (from exiftool)
    Encoder: libx265 (high complexity (0.265 bpp > 0.17))
frame=  915 fps= 21 q=32.3 Lsize=   12724KiB time=00:00:30.43 bitrate=3425.4kbits/s speed=0.695x elapsed=0:00:43.75
encoded 915 frames in 43.74s (20.92 fps), 3207.75 kb/s, Avg QP:30.92
    **Converted: 12.4 MB (72.4% smaller) in 43.8s**
    Deleted original: 00054.MTS

  ## Processing: 00055.MTS (673.0 MB)
    Creation date: 2020-11-29 13:45:56 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.155 bpp))
frame=23460 fps=264 q=-0.0 Lsize=  187869KiB time=00:13:02.74 bitrate=1966.2kbits/s speed=8.82x elapsed=0:01:28.74
    **Converted: 183.5 MB (72.7% smaller) in 88.8s**
    Deleted original: 00055.MTS

  ## Processing: 00055.MTS (12.9 MB)
    Creation date: 2025-03-07 16:56:58 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.155 bpp))
frame=  450 fps=244 q=-0.0 Lsize=    7019KiB time=00:00:14.98 bitrate=3837.9kbits/s speed=8.11x elapsed=0:00:01.84
    **Converted: 6.9 MB (47.0% smaller) in 1.9s**
    Deleted original: 00055.MTS

  ## Processing: 00055.MTS (45.5 MB)
    Creation date: 2016-07-18 19:20:28 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame=  930 fps= 26 q=32.9 Lsize=   16251KiB time=00:00:30.93 bitrate=4304.1kbits/s speed=0.875x elapsed=0:00:35.35
encoded 930 frames in 35.34s (26.32 fps), 4086.23 kb/s, Avg QP:31.31
    **Converted: 15.9 MB (65.1% smaller) in 35.4s**
    Deleted original: 00055.MTS

  ## Processing: 00055.MTS (67.3 MB)
    Creation date: 2013-11-23 12:48:50 (from exiftool)
    Encoder: libx265 (high complexity (0.255 bpp > 0.17))
frame= 1065 fps= 20 q=32.7 Lsize=   17237KiB time=00:00:35.43 bitrate=3984.9kbits/s speed=0.679x elapsed=0:00:52.21
encoded 1065 frames in 52.19s (20.41 fps), 3769.93 kb/s, Avg QP:31.36
    **Converted: 16.8 MB (75.0% smaller) in 52.3s**
    Deleted original: 00055.MTS

  ## Processing: 00056.MTS (185.8 MB)
    Creation date: 2020-12-25 08:18:58 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.156 bpp))
frame= 6435 fps=264 q=-0.0 Lsize=   42663KiB time=00:03:34.68 bitrate=1628.0kbits/s speed=8.81x elapsed=0:00:24.35
    **Converted: 41.7 MB (77.6% smaller) in 24.4s**
    Deleted original: 00056.MTS

  ## Processing: 00056.MTS (14.3 MB)
    Creation date: 2025-03-07 17:02:04 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.152 bpp))
frame=  510 fps=247 q=-0.0 Lsize=    7053KiB time=00:00:16.98 bitrate=3402.2kbits/s speed=8.23x elapsed=0:00:02.06
    **Converted: 6.9 MB (52.0% smaller) in 2.1s**
    Deleted original: 00056.MTS

  ## Processing: 00056.MTS (16.9 MB)
    Creation date: 2016-07-18 19:21:00 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame=  345 fps= 24 q=32.2 Lsize=    6591KiB time=00:00:11.41 bitrate=4731.2kbits/s speed=0.794x elapsed=0:00:14.37
encoded 345 frames in 14.36s (24.03 fps), 4484.65 kb/s, Avg QP:31.34
    **Converted: 6.4 MB (61.9% smaller) in 14.5s**
    Deleted original: 00056.MTS

  ## Processing: 00057.MTS (50.1 MB)
    Creation date: 2021-02-12 20:26:44 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame= 1890 fps=260 q=-0.0 Lsize=   13114KiB time=00:01:03.02 bitrate=1704.4kbits/s speed=8.66x elapsed=0:00:07.27
    **Converted: 12.8 MB (74.4% smaller) in 7.3s**
    Deleted original: 00057.MTS

  ## Processing: 00057.MTS (22.8 MB)
    Creation date: 2025-03-07 17:07:21 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  810 fps=253 q=-0.0 Lsize=   11943KiB time=00:00:26.99 bitrate=3624.4kbits/s speed=8.44x elapsed=0:00:03.19
    **Converted: 11.7 MB (48.8% smaller) in 3.3s**
    Deleted original: 00057.MTS

  ## Processing: 00057.MTS (64.5 MB)
    Creation date: 2016-07-19 12:10:25 (from exiftool)
    Encoder: libx265 (high complexity (0.263 bpp > 0.17))
frame= 1320 fps= 22 q=32.6 Lsize=   25740KiB time=00:00:43.94 bitrate=4798.5kbits/s speed=0.732x elapsed=0:00:59.99
encoded 1320 frames in 59.98s (22.01 fps), 4581.16 kb/s, Avg QP:31.18
    **Converted: 25.1 MB (61.1% smaller) in 60.1s**
    Deleted original: 00057.MTS

  ## Processing: 00058.MTS (47.8 MB)
    Creation date: 2021-03-12 08:43:00 (from exiftool)
    Encoder: libx265 (high complexity (0.177 bpp > 0.17))
frame= 1455 fps= 20 q=32.5 Lsize=   24663KiB time=00:00:48.44 bitrate=4170.3kbits/s speed=0.668x elapsed=0:01:12.52
encoded 1455 frames in 72.50s (20.07 fps), 3958.30 kb/s, Avg QP:30.94
    **Converted: 24.1 MB (49.6% smaller) in 72.8s**
    Deleted original: 00058.MTS

  ## Processing: 00058.MTS (24.8 MB)
    Creation date: 2025-03-07 17:13:02 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  885 fps=254 q=-0.0 Lsize=   12151KiB time=00:00:29.49 bitrate=3374.7kbits/s speed=8.45x elapsed=0:00:03.49
    **Converted: 11.9 MB (52.1% smaller) in 3.6s**
    Deleted original: 00058.MTS

  ## Processing: 00058.MTS (81.7 MB)
    Creation date: 2016-07-20 10:01:52 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame= 1665 fps= 31 q=31.8 Lsize=   16610KiB time=00:00:55.45 bitrate=2453.7kbits/s speed=1.02x elapsed=0:00:54.47
encoded 1665 frames in 54.45s (30.58 fps), 2244.19 kb/s, Avg QP:31.18
    **Converted: 16.2 MB (80.1% smaller) in 54.5s**
    Deleted original: 00058.MTS

  ## Processing: 00059.MTS (27.0 MB)
    Creation date: 2021-03-12 10:57:02 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.147 bpp))
frame=  990 fps=255 q=-0.0 Lsize=   12897KiB time=00:00:32.99 bitrate=3201.7kbits/s speed=8.48x elapsed=0:00:03.88
    **Converted: 12.6 MB (53.3% smaller) in 4.0s**
    Deleted original: 00059.MTS

  ## Processing: 00059.MTS (36.7 MB)
    Creation date: 2025-03-07 17:22:41 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame= 1380 fps=258 q=-0.0 Lsize=   16352KiB time=00:00:46.01 bitrate=2911.2kbits/s speed=8.61x elapsed=0:00:05.34
    **Converted: 16.0 MB (56.5% smaller) in 5.4s**
    Deleted original: 00059.MTS

  ## Processing: 00059.MTS (191.5 MB)
    Creation date: 2016-07-20 10:03:12 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame= 3915 fps= 27 q=31.4 Lsize=   34714KiB time=00:02:10.53 bitrate=2178.6kbits/s speed= 0.9x elapsed=0:02:24.97
encoded 3915 frames in 144.95s (27.01 fps), 1973.25 kb/s, Avg QP:30.89
    **Converted: 33.9 MB (82.3% smaller) in 145.0s**
    Deleted original: 00059.MTS

  ## Processing: 00060.MTS (79.0 MB)
    Creation date: 2021-05-09 13:05:06 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame= 2970 fps=262 q=-0.0 Lsize=   26868KiB time=00:01:39.06 bitrate=2221.8kbits/s speed=8.74x elapsed=0:00:11.33
    **Converted: 26.2 MB (66.8% smaller) in 11.4s**
    Deleted original: 00060.MTS

  ## Processing: 00060.MTS (45.1 MB)
    Creation date: 2025-03-07 17:53:59 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.169 bpp))
frame= 1440 fps=259 q=-0.0 Lsize=   29353KiB time=00:00:48.01 bitrate=5008.0kbits/s speed=8.63x elapsed=0:00:05.56
    **Converted: 28.7 MB (36.5% smaller) in 5.6s**
    Deleted original: 00060.MTS

  ## Processing: 00060.MTS (29.7 MB)
    Creation date: 2016-07-20 10:06:13 (from exiftool)
    Encoder: libx265 (high complexity (0.260 bpp > 0.17))
frame=  615 fps= 22 q=32.4 Lsize=   10080KiB time=00:00:20.42 bitrate=4043.8kbits/s speed=0.718x elapsed=0:00:28.44
encoded 615 frames in 28.43s (21.63 fps), 3819.42 kb/s, Avg QP:30.90
    **Converted: 9.8 MB (66.9% smaller) in 28.5s**
    Deleted original: 00060.MTS

  ## Processing: 00061.MTS (142.4 MB)
    Creation date: 2021-05-11 18:37:52 (from exiftool)
    Encoder: libx265 (high complexity (0.207 bpp > 0.17))
frame= 3705 fps= 18 q=31.2 Lsize=  227022KiB time=00:02:03.52 bitrate=15056.0kbits/s speed=0.605x elapsed=0:03:24.17
encoded 3705 frames in 204.16s (18.15 fps), 14840.34 kb/s, Avg QP:31.65
    **Converted: 221.7 MB (-55.7% smaller) in 204.2s**
    Deleted original: 00061.MTS

  ## Processing: 00061.MTS (36.5 MB)
    Creation date: 2025-03-14 15:28:06 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 1395 fps=259 q=-0.0 Lsize=   11819KiB time=00:00:46.51 bitrate=2081.7kbits/s speed=8.62x elapsed=0:00:05.39
    **Converted: 11.5 MB (68.4% smaller) in 5.5s**
    Deleted original: 00061.MTS

  ## Processing: 00061.MTS (52.4 MB)
    Creation date: 2016-07-22 15:40:33 (from exiftool)
    Encoder: libx265 (high complexity (0.261 bpp > 0.17))
frame= 1080 fps= 27 q=32.4 Lsize=   16239KiB time=00:00:35.93 bitrate=3701.8kbits/s speed=0.903x elapsed=0:00:39.78
encoded 1080 frames in 39.77s (27.16 fps), 3485.43 kb/s, Avg QP:31.18
    **Converted: 15.9 MB (69.7% smaller) in 39.9s**
    Deleted original: 00061.MTS

  ## Processing: 00062.MTS (51.4 MB)
    Creation date: 2021-05-11 18:44:05 (from exiftool)
    Encoder: libx265 (high complexity (0.173 bpp > 0.17))
frame= 1605 fps= 23 q=33.6 Lsize=   61058KiB time=00:00:53.45 bitrate=9357.4kbits/s speed=0.76x elapsed=0:01:10.33
encoded 1605 frames in 70.32s (22.82 fps), 9136.74 kb/s, Avg QP:31.50
    **Converted: 59.6 MB (-15.9% smaller) in 70.4s**
    Deleted original: 00062.MTS

  ## Processing: 00062.MTS (5.6 MB)
    Creation date: 2025-03-20 09:11:20 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame=  210 fps=195 q=-0.0 Lsize=    2766KiB time=00:00:06.97 bitrate=3249.4kbits/s speed=6.47x elapsed=0:00:01.07
    **Converted: 2.7 MB (52.2% smaller) in 1.1s**
    Deleted original: 00062.MTS

  ## Processing: 00062.MTS (87.3 MB)
    Creation date: 2016-07-22 21:16:46 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1770 fps= 33 q=33.1 Lsize=   11160KiB time=00:00:58.95 bitrate=1550.6kbits/s speed= 1.1x elapsed=0:00:53.77
encoded 1770 frames in 53.76s (32.92 fps), 1345.21 kb/s, Avg QP:31.29
    **Converted: 10.9 MB (87.5% smaller) in 53.9s**
    Deleted original: 00062.MTS

  ## Processing: 00063.MTS (58.3 MB)
    Creation date: 2021-05-11 18:50:29 (from exiftool)
    Encoder: libx265 (high complexity (0.196 bpp > 0.17))
frame= 1605 fps= 16 q=33.5 Lsize=  107850KiB time=00:00:53.45 bitrate=16528.6kbits/s speed=0.521x elapsed=0:01:42.56
encoded 1605 frames in 102.56s (15.65 fps), 16290.61 kb/s, Avg QP:31.72
    **Converted: 105.3 MB (-80.7% smaller) in 102.6s**
    Deleted original: 00063.MTS

  ## Processing: 00063.MTS (6.6 MB)
    Creation date: 2025-03-20 09:14:59 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.148 bpp))
frame=  240 fps=226 q=-0.0 Lsize=    3275KiB time=00:00:07.97 bitrate=3364.4kbits/s speed=7.51x elapsed=0:00:01.06
    **Converted: 3.2 MB (51.5% smaller) in 1.1s**
    Deleted original: 00063.MTS

  ## Processing: 00063.MTS (153.8 MB)
    Creation date: 2016-07-31 16:15:13 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame= 3135 fps= 30 q=33.3 Lsize=   37329KiB time=00:01:44.50 bitrate=2926.2kbits/s speed=0.996x elapsed=0:01:44.93
encoded 3135 frames in 104.92s (29.88 fps), 2718.78 kb/s, Avg QP:31.23
    **Converted: 36.5 MB (76.3% smaller) in 105.0s**
    Deleted original: 00063.MTS

  ## Processing: 00063.MTS (219.7 MB)
    Creation date: 2013-12-14 22:16:44 (from exiftool)
    Encoder: libx265 (high complexity (0.256 bpp > 0.17))
frame= 3465 fps= 28 q=32.7 Lsize=   19598KiB time=00:01:55.51 bitrate=1389.8kbits/s speed=0.942x elapsed=0:02:02.58
encoded 3465 frames in 122.56s (28.27 fps), 1185.37 kb/s, Avg QP:31.47
    **Converted: 19.1 MB (91.3% smaller) in 122.7s**
    Deleted original: 00063.MTS

  ## Processing: 00064.MTS (70.7 MB)
    Creation date: 2021-05-11 19:16:18 (from exiftool)
    Encoder: libx265 (high complexity (0.213 bpp > 0.17))
frame= 1785 fps= 20 q=33.7 Lsize=   87856KiB time=00:00:59.45 bitrate=12104.3kbits/s speed=0.666x elapsed=0:01:29.27
encoded 1785 frames in 89.26s (20.00 fps), 11879.83 kb/s, Avg QP:31.61
    **Converted: 85.8 MB (-21.3% smaller) in 89.4s**
    Deleted original: 00064.MTS

  ## Processing: 00064.MTS (6.9 MB)
    Creation date: 2025-03-20 09:15:20 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame=  255 fps=229 q=-0.0 Lsize=    3470KiB time=00:00:08.47 bitrate=3353.6kbits/s speed= 7.6x elapsed=0:00:01.11
    **Converted: 3.4 MB (50.7% smaller) in 1.2s**
    Deleted original: 00064.MTS

  ## Processing: 00064.MTS (33.7 MB)
    Creation date: 2016-08-07 18:12:25 (from exiftool)
    Encoder: libx265 (high complexity (0.263 bpp > 0.17))
frame=  690 fps= 35 q=33.6 Lsize=    6285KiB time=00:00:22.92 bitrate=2246.2kbits/s speed=1.16x elapsed=0:00:19.77
encoded 690 frames in 19.75s (34.93 fps), 2032.46 kb/s, Avg QP:31.47
    **Converted: 6.1 MB (81.8% smaller) in 19.8s**
    Deleted original: 00064.MTS

  ## Processing: 00064.MTS (163.5 MB)
    Creation date: 2013-12-18 18:52:07 (from exiftool)
    Encoder: libx265 (high complexity (0.258 bpp > 0.17))
frame= 2565 fps= 21 q=33.0 Lsize=   30367KiB time=00:01:25.48 bitrate=2910.1kbits/s speed=0.687x elapsed=0:02:04.46
encoded 2565 frames in 124.44s (20.61 fps), 2702.66 kb/s, Avg QP:31.16
    **Converted: 29.7 MB (81.9% smaller) in 124.6s**
    Deleted original: 00064.MTS

  ## Processing: 00065.MTS (48.5 MB)
    Creation date: 2021-05-13 10:37:02 (from exiftool)
    Encoder: libx265 (high complexity (0.268 bpp > 0.17))
frame=  975 fps= 24 q=32.8 Lsize=   16754KiB time=00:00:32.43 bitrate=4231.9kbits/s speed=0.783x elapsed=0:00:41.42
encoded 975 frames in 41.41s (23.55 fps), 4014.84 kb/s, Avg QP:31.53
    **Converted: 16.4 MB (66.3% smaller) in 41.5s**
    Deleted original: 00065.MTS

  ## Processing: 00065.MTS (13.8 MB)
    Creation date: 2025-03-20 09:37:22 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.155 bpp))
frame=  480 fps=244 q=-0.0 Lsize=    7129KiB time=00:00:15.98 bitrate=3653.8kbits/s speed=8.11x elapsed=0:00:01.97
    **Converted: 7.0 MB (49.6% smaller) in 2.0s**
    Deleted original: 00065.MTS

  ## Processing: 00065.MTS (54.0 MB)
    Creation date: 2016-09-08 17:27:45 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1095 fps= 25 q=33.7 Lsize=   22610KiB time=00:00:36.43 bitrate=5083.5kbits/s speed=0.822x elapsed=0:00:44.32
encoded 1095 frames in 44.31s (24.71 fps), 4861.95 kb/s, Avg QP:31.50
    **Converted: 22.1 MB (59.1% smaller) in 44.4s**
    Deleted original: 00065.MTS

  ## Processing: 00065.MTS (230.0 MB)
    Creation date: 2013-12-24 22:29:19 (from exiftool)
    Encoder: libx265 (high complexity (0.263 bpp > 0.17))
frame= 3540 fps= 19 q=32.6 Lsize=   60997KiB time=00:01:58.01 bitrate=4234.0kbits/s speed=0.626x elapsed=0:03:08.65
encoded 3540 frames in 188.63s (18.77 fps), 4027.50 kb/s, Avg QP:30.79
    **Converted: 59.6 MB (74.1% smaller) in 188.8s**
    Deleted original: 00065.MTS

  ## Processing: 00066.MTS (76.4 MB)
    Creation date: 2021-05-13 10:41:03 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1545 fps= 31 q=33.1 Lsize=   14062KiB time=00:00:51.45 bitrate=2239.0kbits/s speed=1.02x elapsed=0:00:50.35
encoded 1545 frames in 50.33s (30.70 fps), 2030.47 kb/s, Avg QP:31.39
    **Converted: 13.7 MB (82.0% smaller) in 50.4s**
    Deleted original: 00066.MTS

  ## Processing: 00066.MTS (15.3 MB)
    Creation date: 2025-03-20 09:43:08 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.152 bpp))
frame=  540 fps=246 q=-0.0 Lsize=    8283KiB time=00:00:17.98 bitrate=3772.7kbits/s speed=8.18x elapsed=0:00:02.19
    **Converted: 8.1 MB (47.1% smaller) in 2.3s**
    Deleted original: 00066.MTS

  ## Processing: 00066.MTS (192.7 MB)
    Creation date: 2016-09-08 17:29:37 (from exiftool)
    Encoder: libx265 (high complexity (0.265 bpp > 0.17))
frame= 3915 fps= 25 q=33.0 Lsize=   72554KiB time=00:02:10.53 bitrate=4553.5kbits/s speed=0.818x elapsed=0:02:39.58
encoded 3915 frames in 159.56s (24.54 fps), 4344.16 kb/s, Avg QP:31.42
    **Converted: 70.9 MB (63.2% smaller) in 159.7s**
    Deleted original: 00066.MTS

  ## Processing: 00067.MTS (66.0 MB)
    Creation date: 2021-05-13 10:43:56 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1335 fps= 29 q=33.4 Lsize=   16012KiB time=00:00:44.44 bitrate=2951.2kbits/s speed=0.978x elapsed=0:00:45.46
encoded 1335 frames in 45.45s (29.37 fps), 2739.93 kb/s, Avg QP:31.58
    **Converted: 15.6 MB (76.3% smaller) in 45.5s**
    Deleted original: 00067.MTS

  ## Processing: 00067.MTS (30.0 MB)
    Creation date: 2025-03-20 09:59:43 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.152 bpp))
frame= 1065 fps=256 q=-0.0 Lsize=   11734KiB time=00:00:35.50 bitrate=2707.5kbits/s speed=8.53x elapsed=0:00:04.16
    **Converted: 11.5 MB (61.8% smaller) in 4.2s**
    Deleted original: 00067.MTS

  ## Processing: 00067.MTS (160.6 MB)
    Creation date: 2016-09-08 17:32:12 (from exiftool)
    Encoder: libx265 (high complexity (0.268 bpp > 0.17))
frame= 3225 fps= 24 q=30.5 Lsize=   70903KiB time=00:01:47.50 bitrate=5402.8kbits/s speed=0.79x elapsed=0:02:16.05
encoded 3225 frames in 136.03s (23.71 fps), 5192.33 kb/s, Avg QP:31.43
    **Converted: 69.2 MB (56.9% smaller) in 136.1s**
    Deleted original: 00067.MTS

  ## Processing: 00068.MTS (66.6 MB)
    Creation date: 2021-05-13 10:48:47 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1350 fps= 32 q=29.5 Lsize=   10500KiB time=00:00:44.94 bitrate=1913.8kbits/s speed=1.08x elapsed=0:00:41.71
encoded 1350 frames in 41.69s (32.38 fps), 1705.54 kb/s, Avg QP:31.41
    **Converted: 10.3 MB (84.6% smaller) in 41.8s**
    Deleted original: 00068.MTS

  ## Processing: 00068.MTS (34.9 MB)
    Creation date: 2025-03-20 10:48:41 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 1335 fps=257 q=-0.0 Lsize=   11305KiB time=00:00:44.51 bitrate=2080.6kbits/s speed=8.56x elapsed=0:00:05.20
    **Converted: 11.0 MB (68.3% smaller) in 5.3s**
    Deleted original: 00068.MTS

  ## Processing: 00068.MTS (141.8 MB)
    Creation date: 2016-09-08 19:53:26 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame= 2865 fps= 25 q=32.8 Lsize=   35117KiB time=00:01:35.49 bitrate=3012.5kbits/s speed=0.844x elapsed=0:01:53.11
encoded 2865 frames in 113.10s (25.33 fps), 2805.44 kb/s, Avg QP:31.32
    **Converted: 34.3 MB (75.8% smaller) in 113.2s**
    Deleted original: 00068.MTS

  ## Processing: 00069.MTS (48.5 MB)
    Creation date: 2021-05-13 10:56:13 (from exiftool)
    Encoder: libx265 (high complexity (0.268 bpp > 0.17))
frame=  975 fps= 25 q=33.6 Lsize=   16954KiB time=00:00:32.43 bitrate=4282.3kbits/s speed=0.825x elapsed=0:00:39.29
encoded 975 frames in 39.27s (24.83 fps), 4064.42 kb/s, Avg QP:31.44
    **Converted: 16.6 MB (65.9% smaller) in 39.4s**
    Deleted original: 00069.MTS

  ## Processing: 00069.MTS (32.9 MB)
    Creation date: 2025-03-29 12:13:02 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.133 bpp))
frame= 1335 fps=256 q=-0.0 Lsize=    8035KiB time=00:00:44.51 bitrate=1478.7kbits/s speed=8.55x elapsed=0:00:05.20
    **Converted: 7.8 MB (76.2% smaller) in 5.3s**
    Deleted original: 00069.MTS

  ## Processing: 00069.MTS (21.6 MB)
    Creation date: 2016-09-08 19:58:22 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame=  435 fps= 26 q=33.0 Lsize=    5889KiB time=00:00:14.41 bitrate=3346.7kbits/s speed=0.857x elapsed=0:00:16.82
encoded 435 frames in 16.81s (25.88 fps), 3118.50 kb/s, Avg QP:31.45
    **Converted: 5.8 MB (73.4% smaller) in 16.9s**
    Deleted original: 00069.MTS

  ## Processing: 00070.MTS (67.6 MB)
    Creation date: 2021-05-13 16:22:00 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame= 1365 fps= 31 q=32.7 Lsize=   14216KiB time=00:00:45.44 bitrate=2562.5kbits/s speed=1.02x elapsed=0:00:44.74
encoded 1365 frames in 44.72s (30.52 fps), 2353.30 kb/s, Avg QP:31.42
    **Converted: 13.9 MB (79.5% smaller) in 44.8s**
    Deleted original: 00070.MTS

  ## Processing: 00070.MTS (6.0 MB)
    Creation date: 2025-03-29 12:22:54 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame=  225 fps=224 q=-0.0 Lsize=    1938KiB time=00:00:07.47 bitrate=2124.6kbits/s speed=7.43x elapsed=0:00:01.00
    **Converted: 1.9 MB (68.3% smaller) in 1.1s**
    Deleted original: 00070.MTS

  ## Processing: 00070.MTS (77.9 MB)
    Creation date: 2016-09-12 19:51:18 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame= 1590 fps= 26 q=31.4 Lsize=   11771KiB time=00:00:52.95 bitrate=1821.0kbits/s speed=0.854x elapsed=0:01:02.02
encoded 1590 frames in 62.01s (25.64 fps), 1614.25 kb/s, Avg QP:30.84
    **Converted: 11.5 MB (85.2% smaller) in 62.1s**
    Deleted original: 00070.MTS

  ## Processing: 00071.MTS (42.6 MB)
    Creation date: 2021-05-13 16:27:45 (from exiftool)
    Encoder: libx265 (high complexity (0.268 bpp > 0.17))
frame=  855 fps= 22 q=32.7 Lsize=   13948KiB time=00:00:28.42 bitrate=4019.4kbits/s speed=0.72x elapsed=0:00:39.49
encoded 855 frames in 39.47s (21.66 fps), 3801.56 kb/s, Avg QP:31.32
    **Converted: 13.6 MB (68.0% smaller) in 39.6s**
    Deleted original: 00071.MTS

  ## Processing: 00071.MTS (11.6 MB)
    Creation date: 2025-03-29 12:25:19 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.139 bpp))
frame=  450 fps=225 q=-0.0 Lsize=    3408KiB time=00:00:14.98 bitrate=1863.7kbits/s speed= 7.5x elapsed=0:00:01.99
    **Converted: 3.3 MB (71.4% smaller) in 2.1s**
    Deleted original: 00071.MTS

  ## Processing: 00071.MTS (168.8 MB)
    Creation date: 2016-10-02 18:59:26 (from exiftool)
    Encoder: libx265 (high complexity (0.268 bpp > 0.17))
frame= 3390 fps= 25 q=31.8 Lsize=   35210KiB time=00:01:53.01 bitrate=2552.3kbits/s speed=0.834x elapsed=0:02:15.50
encoded 3390 frames in 135.49s (25.02 fps), 2347.14 kb/s, Avg QP:31.42
    **Converted: 34.4 MB (79.6% smaller) in 135.6s**
    Deleted original: 00071.MTS

  ## Processing: 00072.MTS (46.0 MB)
    Creation date: 2021-05-13 16:34:27 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame=  930 fps= 23 q=32.6 Lsize=   13036KiB time=00:00:30.93 bitrate=3452.4kbits/s speed=0.779x elapsed=0:00:39.69
encoded 930 frames in 39.68s (23.44 fps), 3233.77 kb/s, Avg QP:31.30
    **Converted: 12.7 MB (72.4% smaller) in 39.8s**
    Deleted original: 00072.MTS

  ## Processing: 00072.MTS (8.1 MB)
    Creation date: 2025-03-29 12:25:45 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.139 bpp))
frame=  315 fps=236 q=-0.0 Lsize=    2763KiB time=00:00:10.47 bitrate=2160.4kbits/s speed=7.84x elapsed=0:00:01.33
    **Converted: 2.7 MB (66.8% smaller) in 1.4s**
    Deleted original: 00072.MTS

  ## Processing: 00072.MTS (32.1 MB)
    Creation date: 2016-10-03 15:58:57 (from exiftool)
    Encoder: libx265 (high complexity (0.275 bpp > 0.17))
frame=  630 fps= 24 q=33.3 Lsize=   16858KiB time=00:00:20.92 bitrate=6601.0kbits/s speed=0.807x elapsed=0:00:25.93
encoded 630 frames in 25.91s (24.31 fps), 6363.27 kb/s, Avg QP:31.37
    **Converted: 16.5 MB (48.7% smaller) in 26.0s**
    Deleted original: 00072.MTS

  ## Processing: 00073.MTS (76.0 MB)
    Creation date: 2021-05-13 16:39:03 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame= 1530 fps= 27 q=32.5 Lsize=   17909KiB time=00:00:50.95 bitrate=2879.4kbits/s speed=0.906x elapsed=0:00:56.24
encoded 1530 frames in 56.23s (27.21 fps), 2669.58 kb/s, Avg QP:31.35
    **Converted: 17.5 MB (77.0% smaller) in 56.3s**
    Deleted original: 00073.MTS

  ## Processing: 00073.MTS (14.8 MB)
    Creation date: 2025-03-29 12:45:20 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.152 bpp))
frame=  525 fps=246 q=-0.0 Lsize=    7006KiB time=00:00:17.48 bitrate=3282.4kbits/s speed= 8.2x elapsed=0:00:02.13
    **Converted: 6.8 MB (53.9% smaller) in 2.2s**
    Deleted original: 00073.MTS

  ## Processing: 00073.MTS (249.5 MB)
    Creation date: 2016-10-03 15:59:25 (from exiftool)
    Encoder: libx265 (high complexity (0.273 bpp > 0.17))
frame= 4920 fps= 24 q=33.1 Lsize=  117301KiB time=00:02:44.06 bitrate=5857.1kbits/s speed=0.81x elapsed=0:03:22.49
encoded 4920 frames in 202.47s (24.30 fps), 5648.93 kb/s, Avg QP:31.43
    **Converted: 114.6 MB (54.1% smaller) in 202.6s**
    Deleted original: 00073.MTS

  ## Processing: 00074.MTS (18.6 MB)
    Creation date: 2021-09-08 19:15:51 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame=  375 fps= 34 q=33.3 Lsize=    2913KiB time=00:00:12.41 bitrate=1922.7kbits/s speed=1.11x elapsed=0:00:11.17
encoded 375 frames in 11.16s (33.61 fps), 1699.47 kb/s, Avg QP:31.32
    **Converted: 2.8 MB (84.7% smaller) in 11.3s**
    Deleted original: 00074.MTS

  ## Processing: 00074.MTS (28.6 MB)
    Creation date: 2025-03-29 13:04:03 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.139 bpp))
frame= 1110 fps=255 q=-0.0 Lsize=   10283KiB time=00:00:37.00 bitrate=2276.6kbits/s speed=8.51x elapsed=0:00:04.34
    **Converted: 10.0 MB (64.9% smaller) in 4.4s**
    Deleted original: 00074.MTS

  ## Processing: 00074.MTS (120.4 MB)
    Creation date: 2016-10-15 13:04:45 (from exiftool)
    Encoder: libx265 (high complexity (0.265 bpp > 0.17))
frame= 2445 fps= 27 q=32.1 Lsize=   21253KiB time=00:01:21.48 bitrate=2136.7kbits/s speed=0.906x elapsed=0:01:29.89
encoded 2445 frames in 89.88s (27.20 fps), 1930.07 kb/s, Avg QP:31.37
    **Converted: 20.8 MB (82.8% smaller) in 90.0s**
    Deleted original: 00074.MTS

  ## Processing: 00075.MTS (90.5 MB)
    Creation date: 2021-09-08 19:16:08 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1830 fps= 26 q=32.1 Lsize=   21986KiB time=00:01:00.96 bitrate=2954.5kbits/s speed=0.857x elapsed=0:01:11.12
encoded 1830 frames in 71.11s (25.74 fps), 2746.33 kb/s, Avg QP:31.23
    **Converted: 21.5 MB (76.3% smaller) in 71.2s**
    Deleted original: 00075.MTS

  ## Processing: 00075.MTS (839.6 MB)
    Creation date: 2025-04-30 18:07:27 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.155 bpp))
frame=29100 fps=265 q=-0.0 Lsize=  306310KiB time=00:16:10.93 bitrate=2584.4kbits/s speed=8.85x elapsed=0:01:49.76
    **Converted: 299.1 MB (64.4% smaller) in 109.8s**
    Deleted original: 00075.MTS

  ## Processing: 00076.MTS (138.5 MB)
    Creation date: 2021-12-16 00:17:27 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.157 bpp))
frame= 4755 fps=264 q=-0.0 Lsize=   84672KiB time=00:02:38.62 bitrate=4372.8kbits/s speed=8.79x elapsed=0:00:18.04
    **Converted: 82.7 MB (40.3% smaller) in 18.1s**
    Deleted original: 00076.MTS

  ## Processing: 00076.MTS (60.4 MB)
    Creation date: 2025-05-16 17:43:08 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.149 bpp))
frame= 2190 fps=261 q=-0.0 Lsize=   27830KiB time=00:01:13.03 bitrate=3121.4kbits/s speed= 8.7x elapsed=0:00:08.39
    **Converted: 27.2 MB (55.0% smaller) in 8.5s**
    Deleted original: 00076.MTS

  ## Processing: 00076.MTS (76.6 MB)
    Creation date: 2016-10-20 17:03:54 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame= 1558 fps= 34 q=32.5 Lsize=    7448KiB time=00:00:51.98 bitrate=1173.6kbits/s speed=1.13x elapsed=0:00:45.83
encoded 1558 frames in 45.82s (34.00 fps), 970.12 kb/s, Avg QP:31.77
    **Converted: 7.3 MB (90.5% smaller) in 45.9s**
    Deleted original: 00076.MTS

  ## Processing: 00077.MTS (162.6 MB)
    Creation date: 2021-12-16 00:38:35 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.166 bpp))
frame= 5280 fps=264 q=-0.0 Lsize=  104596KiB time=00:02:56.14 bitrate=4864.5kbits/s speed= 8.8x elapsed=0:00:20.02
    **Converted: 102.1 MB (37.2% smaller) in 20.1s**
    Deleted original: 00077.MTS

  ## Processing: 00077.MTS (61.5 MB)
    Creation date: 2025-05-16 17:44:22 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.144 bpp))
frame= 2295 fps=261 q=-0.0 Lsize=   26815KiB time=00:01:16.54 bitrate=2869.9kbits/s speed=8.71x elapsed=0:00:08.79
    **Converted: 26.2 MB (57.4% smaller) in 8.9s**
    Deleted original: 00077.MTS

  ## Processing: 00077.MTS (51.0 MB)
    Creation date: 2016-11-03 19:27:51 (from exiftool)
    Encoder: libx265 (high complexity (0.258 bpp > 0.17))
frame= 1065 fps= 26 q=32.4 Lsize=    9905KiB time=00:00:35.43 bitrate=2289.9kbits/s speed=0.869x elapsed=0:00:40.77
encoded 1065 frames in 40.76s (26.13 fps), 2080.32 kb/s, Avg QP:30.76
    **Converted: 9.7 MB (81.0% smaller) in 40.9s**
    Deleted original: 00077.MTS

  ## Processing: 00078.MTS (99.0 MB)
    Creation date: 2021-12-16 00:41:58 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.153 bpp))
frame= 3480 fps=263 q=-0.0 Lsize=   56148KiB time=00:01:56.08 bitrate=3962.4kbits/s speed=8.77x elapsed=0:00:13.24
    **Converted: 54.8 MB (44.6% smaller) in 13.3s**
    Deleted original: 00078.MTS

  ## Processing: 00078.MTS (33.8 MB)
    Creation date: 2025-05-16 17:58:37 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 1290 fps=258 q=-0.0 Lsize=   10211KiB time=00:00:43.00 bitrate=1944.8kbits/s speed= 8.6x elapsed=0:00:05.00
    **Converted: 10.0 MB (70.5% smaller) in 5.1s**
    Deleted original: 00078.MTS

  ## Processing: 00078.MTS (34.4 MB)
    Creation date: 2016-11-03 19:28:36 (from exiftool)
    Encoder: libx265 (high complexity (0.263 bpp > 0.17))
frame=  705 fps= 27 q=31.8 Lsize=    7186KiB time=00:00:23.42 bitrate=2513.0kbits/s speed=0.909x elapsed=0:00:25.76
encoded 705 frames in 25.74s (27.39 fps), 2298.28 kb/s, Avg QP:30.83
    **Converted: 7.0 MB (79.6% smaller) in 25.8s**
    Deleted original: 00078.MTS

  ## Processing: 00079.MTS (265.7 MB)
    Creation date: 2021-12-24 19:08:38 (from exiftool)
    Encoder: libx265 (high complexity (0.176 bpp > 0.17))
frame= 8145 fps= 24 q=32.4 Lsize=  129793KiB time=00:04:31.67 bitrate=3913.8kbits/s speed=0.792x elapsed=0:05:43.16
encoded 8145 frames in 343.15s (23.74 fps), 3709.18 kb/s, Avg QP:31.37
    **Converted: 126.8 MB (52.3% smaller) in 343.2s**
    Deleted original: 00079.MTS

  ## Processing: 00079.MTS (44.8 MB)
    Creation date: 2025-05-16 18:02:02 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 1710 fps=259 q=-0.0 Lsize=   14147KiB time=00:00:57.02 bitrate=2032.4kbits/s speed=8.64x elapsed=0:00:06.59
    **Converted: 13.8 MB (69.1% smaller) in 6.7s**
    Deleted original: 00079.MTS

  ## Processing: 00079.MTS (51.2 MB)
    Creation date: 2016-11-06 17:55:32 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1035 fps= 35 q=32.7 Lsize=    6079KiB time=00:00:34.43 bitrate=1446.3kbits/s speed=1.15x elapsed=0:00:29.94
encoded 1035 frames in 29.93s (34.59 fps), 1237.18 kb/s, Avg QP:31.20
    **Converted: 5.9 MB (88.4% smaller) in 30.0s**
    Deleted original: 00079.MTS

  ## Processing: 00080.MTS (40.6 MB)
    Creation date: 2021-12-24 20:07:26 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.142 bpp))
frame= 1545 fps=259 q=-0.0 Lsize=    7065KiB time=00:00:51.51 bitrate=1123.4kbits/s speed=8.62x elapsed=0:00:05.97
    **Converted: 6.9 MB (83.0% smaller) in 6.0s**
    Deleted original: 00080.MTS

  ## Processing: 00080.MTS (5.5 MB)
    Creation date: 2025-05-16 18:16:17 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.142 bpp))
frame=  210 fps=0.0 q=-0.0 Lsize=    1972KiB time=00:00:06.97 bitrate=2316.9kbits/s speed=7.42x elapsed=0:00:00.93
    **Converted: 1.9 MB (65.3% smaller) in 1.0s**
    Deleted original: 00080.MTS

  ## Processing: 00080.MTS (63.9 MB)
    Creation date: 2016-11-19 15:02:00 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame= 1290 fps= 30 q=33.7 Lsize=   14321KiB time=00:00:42.94 bitrate=2732.0kbits/s speed=0.993x elapsed=0:00:43.23
encoded 1290 frames in 43.21s (29.85 fps), 2522.03 kb/s, Avg QP:31.67
    **Converted: 14.0 MB (78.1% smaller) in 43.3s**
    Deleted original: 00080.MTS

  ## Processing: 00081.MTS (82.9 MB)
    Creation date: 2021-12-25 19:50:51 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.158 bpp))
frame= 2835 fps=262 q=-0.0 Lsize=   21570KiB time=00:01:34.56 bitrate=1868.6kbits/s speed=8.75x elapsed=0:00:10.80
    **Converted: 21.1 MB (74.6% smaller) in 10.9s**
    Deleted original: 00081.MTS

  ## Processing: 00081.MTS (6.4 MB)
    Creation date: 2025-05-17 16:43:20 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame=  240 fps=228 q=-0.0 Lsize=    2768KiB time=00:00:07.97 bitrate=2843.2kbits/s speed=7.57x elapsed=0:00:01.05
    **Converted: 2.7 MB (57.8% smaller) in 1.1s**
    Deleted original: 00081.MTS

  ## Processing: 00081.MTS (43.0 MB)
    Creation date: 2016-11-19 15:03:40 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame=  870 fps= 23 q=32.6 Lsize=   13883KiB time=00:00:28.92 bitrate=3931.4kbits/s speed=0.779x elapsed=0:00:37.12
encoded 870 frames in 37.10s (23.45 fps), 3713.70 kb/s, Avg QP:31.53
    **Converted: 13.6 MB (68.5% smaller) in 37.2s**
    Deleted original: 00081.MTS

  ## Processing: 00082.MTS (93.6 MB)
    Creation date: 2022-01-27 23:02:09 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.142 bpp))
frame= 3540 fps=263 q=-0.0 Lsize=   15240KiB time=00:01:58.08 bitrate=1057.2kbits/s speed=8.76x elapsed=0:00:13.48
    **Converted: 14.9 MB (84.1% smaller) in 13.5s**
    Deleted original: 00082.MTS

  ## Processing: 00082.MTS (37.4 MB)
    Creation date: 2025-05-17 16:47:30 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 1425 fps=259 q=-0.0 Lsize=   13633KiB time=00:00:47.51 bitrate=2350.5kbits/s speed=8.63x elapsed=0:00:05.50
    **Converted: 13.3 MB (64.4% smaller) in 5.6s**
    Deleted original: 00082.MTS

  ## Processing: 00082.MTS (186.2 MB)
    Creation date: 2016-12-08 17:34:54 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 3660 fps= 28 q=32.9 Lsize=   46874KiB time=00:02:02.02 bitrate=3146.9kbits/s speed=0.929x elapsed=0:02:11.37
encoded 3660 frames in 131.35s (27.86 fps), 2941.39 kb/s, Avg QP:31.38
    **Converted: 45.8 MB (75.4% smaller) in 131.5s**
    Deleted original: 00082.MTS

  ## Processing: 00083.MTS (30.4 MB)
    Creation date: 2022-02-11 23:52:02 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 1125 fps=256 q=-0.0 Lsize=   22721KiB time=00:00:37.50 bitrate=4962.8kbits/s speed=8.53x elapsed=0:00:04.39
    **Converted: 22.2 MB (27.0% smaller) in 4.5s**
    Deleted original: 00083.MTS

  ## Processing: 00083.MTS (32.1 MB)
    Creation date: 2025-05-17 16:55:46 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame= 1155 fps=257 q=-0.0 Lsize=   13348KiB time=00:00:38.50 bitrate=2839.9kbits/s speed=8.57x elapsed=0:00:04.49
    **Converted: 13.0 MB (59.4% smaller) in 4.6s**
    Deleted original: 00083.MTS

  ## Processing: 00083.MTS (91.1 MB)
    Creation date: 2016-12-12 20:26:51 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 1845 fps= 28 q=32.0 Lsize=   17211KiB time=00:01:01.46 bitrate=2293.9kbits/s speed=0.945x elapsed=0:01:05.03
encoded 1845 frames in 65.01s (28.38 fps), 2081.32 kb/s, Avg QP:31.32
    **Converted: 16.8 MB (81.5% smaller) in 65.1s**
    Deleted original: 00083.MTS

  ## Processing: 00084.MTS (9.9 MB)
    Creation date: 2022-05-10 22:52:11 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.155 bpp))
frame=  345 fps=237 q=-0.0 Lsize=    4882KiB time=00:00:11.47 bitrate=3484.3kbits/s speed=7.87x elapsed=0:00:01.45
    **Converted: 4.8 MB (52.1% smaller) in 1.5s**
    Deleted original: 00084.MTS

  ## Processing: 00084.MTS (11.6 MB)
    Creation date: 2025-05-17 16:59:57 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame=  435 fps=243 q=-0.0 Lsize=    3750KiB time=00:00:14.48 bitrate=2121.1kbits/s speed=8.09x elapsed=0:00:01.78
    **Converted: 3.7 MB (68.4% smaller) in 1.9s**
    Deleted original: 00084.MTS

  ## Processing: 00084.MTS (226.7 MB)
    Creation date: 2016-12-17 10:37:20 (from exiftool)
    Encoder: libx265 (high complexity (0.264 bpp > 0.17))
frame= 4620 fps= 26 q=33.2 Lsize=   64168KiB time=00:02:34.05 bitrate=3412.2kbits/s speed=0.857x elapsed=0:02:59.71
encoded 4620 frames in 179.70s (25.71 fps), 3206.66 kb/s, Avg QP:31.23
    **Converted: 62.7 MB (72.4% smaller) in 179.8s**
    Deleted original: 00084.MTS

  ## Processing: 00085.MTS (41.7 MB)
    Creation date: 2025-05-17 17:03:35 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame= 1575 fps=259 q=-0.0 Lsize=   12952KiB time=00:00:52.51 bitrate=2020.2kbits/s speed=8.63x elapsed=0:00:06.08
    **Converted: 12.6 MB (69.7% smaller) in 6.2s**
    Deleted original: 00085.MTS

  ## Processing: 00085.MTS (313.2 MB)
    Creation date: 2016-12-22 15:09:42 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame= 6315 fps= 19 q=32.6 Lsize=  117974KiB time=00:03:30.61 bitrate=4588.8kbits/s speed=0.626x elapsed=0:05:36.60
encoded 6315 frames in 336.59s (18.76 fps), 4383.61 kb/s, Avg QP:31.24
    **Converted: 115.2 MB (63.2% smaller) in 336.7s**
    Deleted original: 00085.MTS

  ## Processing: 00086.MTS (65.3 MB)
    Creation date: 2022-05-10 22:53:32 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.160 bpp))
frame= 2205 fps=261 q=-0.0 Lsize=   26156KiB time=00:01:13.54 bitrate=2913.6kbits/s speed=8.71x elapsed=0:00:08.44
    **Converted: 25.5 MB (60.9% smaller) in 8.5s**
    Deleted original: 00086.MTS

  ## Processing: 00086.MTS (16.6 MB)
    Creation date: 2025-05-17 17:11:58 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame=  615 fps=250 q=-0.0 Lsize=    7080KiB time=00:00:20.48 bitrate=2830.9kbits/s speed=8.32x elapsed=0:00:02.46
    **Converted: 6.9 MB (58.3% smaller) in 2.5s**
    Deleted original: 00086.MTS

  ## Processing: 00086.MTS (70.1 MB)
    Creation date: 2016-12-24 20:34:01 (from exiftool)
    Encoder: libx265 (high complexity (0.268 bpp > 0.17))
frame= 1410 fps= 21 q=32.5 Lsize=   21748KiB time=00:00:46.94 bitrate=3794.9kbits/s speed=0.683x elapsed=0:01:08.73
encoded 1410 frames in 68.71s (20.52 fps), 3583.56 kb/s, Avg QP:31.31
    **Converted: 21.2 MB (69.7% smaller) in 68.8s**
    Deleted original: 00086.MTS

  ## Processing: 00087.MTS (16.8 MB)
    Creation date: 2022-05-10 23:00:51 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.155 bpp))
frame=  585 fps=249 q=-0.0 Lsize=    8352KiB time=00:00:19.48 bitrate=3511.2kbits/s speed= 8.3x elapsed=0:00:02.34
    **Converted: 8.2 MB (51.6% smaller) in 2.4s**
    Deleted original: 00087.MTS

  ## Processing: 00087.MTS (26.8 MB)
    Creation date: 2025-05-17 17:22:58 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.148 bpp))
frame=  975 fps=256 q=-0.0 Lsize=   11269KiB time=00:00:32.49 bitrate=2840.5kbits/s speed=8.52x elapsed=0:00:03.81
    **Converted: 11.0 MB (58.9% smaller) in 3.9s**
    Deleted original: 00087.MTS

  ## Processing: 00087.MTS (328.6 MB)
    Creation date: 2016-12-24 20:35:37 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 6645 fps= 25 q=32.8 Lsize=   83864KiB time=00:03:41.62 bitrate=3099.9kbits/s speed=0.836x elapsed=0:04:25.23
encoded 6645 frames in 265.22s (25.05 fps), 2895.37 kb/s, Avg QP:31.35
    **Converted: 81.9 MB (75.1% smaller) in 265.3s**
    Deleted original: 00087.MTS

  ## Processing: 00088.MTS (33.9 MB)
    Creation date: 2025-05-17 17:24:35 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.152 bpp))
frame= 1200 fps=257 q=-0.0 Lsize=   15850KiB time=00:00:40.00 bitrate=3245.5kbits/s speed=8.56x elapsed=0:00:04.67
    **Converted: 15.5 MB (54.3% smaller) in 4.7s**
    Deleted original: 00088.MTS

  ## Processing: 00088.MTS (133.8 MB)
    Creation date: 2016-12-24 20:40:02 (from exiftool)
    Encoder: libx265 (high complexity (0.267 bpp > 0.17))
frame= 2700 fps= 24 q=30.3 Lsize=   35622KiB time=00:01:29.98 bitrate=3242.8kbits/s speed=0.791x elapsed=0:01:53.80
encoded 2700 frames in 113.79s (23.73 fps), 3036.16 kb/s, Avg QP:31.33
    **Converted: 34.8 MB (74.0% smaller) in 113.9s**
    Deleted original: 00088.MTS

  ## Processing: 00089.MTS (14.7 MB)
    Creation date: 2022-05-10 23:04:33 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.165 bpp))
frame=  480 fps=244 q=-0.0 Lsize=    8114KiB time=00:00:15.98 bitrate=4158.7kbits/s speed=8.12x elapsed=0:00:01.96
    **Converted: 7.9 MB (46.1% smaller) in 2.0s**
    Deleted original: 00089.MTS

  ## Processing: 00089.MTS (239.0 MB)
    Creation date: 2025-05-20 09:42:46 (from exiftool)
    Encoder: libx265 (high complexity (0.207 bpp > 0.17))
frame= 6210 fps= 17 q=33.9 Lsize=  306259KiB time=00:03:27.10 bitrate=12113.9kbits/s speed=0.579x elapsed=0:05:57.79
encoded 6210 frames in 357.78s (17.36 fps), 11904.64 kb/s, Avg QP:31.85
    **Converted: 299.1 MB (-25.2% smaller) in 357.9s**
    Deleted original: 00089.MTS

  ## Processing: 00089.MTS (258.7 MB)
    Creation date: 2016-12-24 20:42:23 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 5235 fps= 26 q=32.5 Lsize=   70416KiB time=00:02:54.57 bitrate=3304.3kbits/s speed=0.864x elapsed=0:03:22.04
encoded 5235 frames in 202.03s (25.91 fps), 3099.57 kb/s, Avg QP:31.39
    **Converted: 68.8 MB (73.4% smaller) in 202.1s**
    Deleted original: 00089.MTS

  ## Processing: 00090.MTS (56.7 MB)
    Creation date: 2022-05-10 23:05:40 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.155 bpp))
frame= 1965 fps=260 q=-0.0 Lsize=   30453KiB time=00:01:05.53 bitrate=3806.9kbits/s speed=8.66x elapsed=0:00:07.57
    **Converted: 29.7 MB (47.5% smaller) in 7.6s**
    Deleted original: 00090.MTS

  ## Processing: 00090.MTS (197.5 MB)
    Creation date: 2025-05-20 09:52:29 (from exiftool)
    Encoder: libx265 (high complexity (0.204 bpp > 0.17))
frame= 5205 fps= 19 q=33.3 Lsize=  229717KiB time=00:02:53.57 bitrate=10841.8kbits/s speed=0.644x elapsed=0:04:29.50
encoded 5205 frames in 269.49s (19.31 fps), 10630.79 kb/s, Avg QP:31.72
    **Converted: 224.3 MB (-13.6% smaller) in 269.6s**
    Deleted original: 00090.MTS

  ## Processing: 00090.MTS (233.4 MB)
    Creation date: 2016-12-24 20:45:23 (from exiftool)
    Encoder: libx265 (high complexity (0.268 bpp > 0.17))
frame= 4695 fps= 23 q=33.0 Lsize=   77264KiB time=00:02:36.55 bitrate=4042.9kbits/s speed=0.752x elapsed=0:03:28.15
encoded 4695 frames in 208.13s (22.56 fps), 3836.49 kb/s, Avg QP:31.40
    **Converted: 75.5 MB (67.7% smaller) in 208.2s**
    Deleted original: 00090.MTS

  ## Processing: 00091.MTS (39.4 MB)
    Creation date: 2022-05-19 16:13:46 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame= 1485 fps=258 q=-0.0 Lsize=   12991KiB time=00:00:49.51 bitrate=2149.3kbits/s speed=8.62x elapsed=0:00:05.74
    **Converted: 12.7 MB (67.8% smaller) in 5.8s**
    Deleted original: 00091.MTS

  ## Processing: 00091.MTS (1096.8 MB)
    Creation date: 2025-07-11 16:11:51 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.156 bpp))
frame=37845 fps=264 q=-0.0 Lsize=  414839KiB time=00:21:02.72 bitrate=2691.3kbits/s speed=8.81x elapsed=0:02:23.26
    **Converted: 405.1 MB (63.1% smaller) in 143.3s**
    Deleted original: 00091.MTS

  ## Processing: 00091.MTS (228.8 MB)
    Creation date: 2016-12-25 08:40:29 (from exiftool)
    Encoder: libx265 (high complexity (0.266 bpp > 0.17))
frame= 4635 fps= 21 q=33.3 Lsize=   76946KiB time=00:02:34.55 bitrate=4078.4kbits/s speed=0.716x elapsed=0:03:35.78
encoded 4635 frames in 215.76s (21.48 fps), 3870.40 kb/s, Avg QP:31.38
    **Converted: 75.1 MB (67.2% smaller) in 215.9s**
    Deleted original: 00091.MTS

  ## Processing: 00092.MTS (9.6 MB)
    Creation date: 2022-05-19 16:32:22 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.144 bpp))
frame=  360 fps=239 q=-0.0 Lsize=    3801KiB time=00:00:11.97 bitrate=2599.1kbits/s speed=7.94x elapsed=0:00:01.50
    **Converted: 3.7 MB (61.5% smaller) in 1.6s**
    Deleted original: 00092.MTS

  ## Processing: 00092.MTS (831.4 MB)
    Creation date: 2025-12-05 17:09:43 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.156 bpp))
frame=28785 fps=265 q=-0.0 Lsize=  305017KiB time=00:16:00.42 bitrate=2601.7kbits/s speed=8.85x elapsed=0:01:48.49
    **Converted: 297.9 MB (64.2% smaller) in 108.6s**
    Deleted original: 00092.MTS

  ## Processing: 00092.MTS (249.5 MB)
    Creation date: 2016-12-25 08:51:12 (from exiftool)
    Encoder: libx265 (high complexity (0.270 bpp > 0.17))
frame= 4980 fps= 25 q=31.6 Lsize=   59131KiB time=00:02:46.06 bitrate=2916.9kbits/s speed=0.835x elapsed=0:03:19.00
encoded 4980 frames in 198.98s (25.03 fps), 2711.58 kb/s, Avg QP:31.13
    **Converted: 57.7 MB (76.9% smaller) in 199.1s**
    Deleted original: 00092.MTS

  ## Processing: 00093.MTS (11.4 MB)
    Creation date: 2022-05-19 16:39:42 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  405 fps=242 q=-0.0 Lsize=    3489KiB time=00:00:13.48 bitrate=2120.5kbits/s speed=8.05x elapsed=0:00:01.67
    **Converted: 3.4 MB (70.0% smaller) in 1.7s**
    Deleted original: 00093.MTS

  ## Processing: 00093.MTS (807.8 MB)
    Creation date: 2025-12-05 17:29:03 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.156 bpp))
frame=27975 fps=266 q=-0.0 Lsize=  319168KiB time=00:15:33.39 bitrate=2801.2kbits/s speed=8.86x elapsed=0:01:45.36
    **Converted: 311.7 MB (61.4% smaller) in 105.4s**
    Deleted original: 00093.MTS

  ## Processing: 00093.MTS (64.3 MB)
    Creation date: 2016-12-28 20:10:42 (from exiftool)
    Encoder: libx265 (high complexity (0.269 bpp > 0.17))
frame= 1290 fps= 19 q=31.8 Lsize=   17974KiB time=00:00:42.94 bitrate=3428.8kbits/s speed=0.629x elapsed=0:01:08.26
encoded 1290 frames in 68.24s (18.90 fps), 3217.44 kb/s, Avg QP:30.73
    **Converted: 17.6 MB (72.7% smaller) in 68.3s**
    Deleted original: 00093.MTS

  ## Processing: 00094.MTS (33.5 MB)
    Creation date: 2022-05-19 16:39:58 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame= 1260 fps=257 q=-0.0 Lsize=   12042KiB time=00:00:42.00 bitrate=2348.4kbits/s speed=8.57x elapsed=0:00:04.90
    **Converted: 11.8 MB (64.9% smaller) in 5.0s**
    Deleted original: 00094.MTS

  ## Processing: 00094.MTS (906.4 MB)
    Creation date: 2025-12-05 20:05:15 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.156 bpp))
frame=31350 fps=265 q=-0.0 Lsize=  311910KiB time=00:17:26.01 bitrate=2442.8kbits/s speed=8.84x elapsed=0:01:58.28
    **Converted: 304.6 MB (66.4% smaller) in 118.3s**
    Deleted original: 00094.MTS

  ## Processing: 00094.MTS (109.0 MB)
    Creation date: 2017-01-03 15:28:37 (from exiftool)
    Encoder: libx265 (high complexity (0.274 bpp > 0.17))
frame= 2145 fps= 18 q=33.7 Lsize=   62187KiB time=00:01:11.47 bitrate=7127.9kbits/s speed=0.607x elapsed=0:01:57.81
encoded 2145 frames in 117.80s (18.21 fps), 6914.49 kb/s, Avg QP:31.03
    **Converted: 60.7 MB (44.3% smaller) in 117.9s**
    Deleted original: 00094.MTS

  ## Processing: 00095.MTS (11.5 MB)
    Creation date: 2022-05-19 16:46:09 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.148 bpp))
frame=  420 fps=243 q=-0.0 Lsize=    4559KiB time=00:00:13.98 bitrate=2671.6kbits/s speed=8.08x elapsed=0:00:01.73
    **Converted: 4.5 MB (61.4% smaller) in 1.8s**
    Deleted original: 00095.MTS

  ## Processing: 00095.MTS (991.6 MB)
    Creation date: 2025-12-05 20:22:43 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.156 bpp))
frame=34260 fps=265 q=-0.0 Lsize=  372298KiB time=00:19:03.10 bitrate=2668.0kbits/s speed=8.86x elapsed=0:02:09.09
    **Converted: 363.6 MB (63.3% smaller) in 129.2s**
    Deleted original: 00095.MTS

  ## Processing: 00096.MTS (25.0 MB)
    Creation date: 2022-05-19 16:51:14 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.142 bpp))
frame=  945 fps=254 q=-0.0 Lsize=    7853KiB time=00:00:31.49 bitrate=2042.4kbits/s speed=8.47x elapsed=0:00:03.71
    **Converted: 7.7 MB (69.3% smaller) in 3.9s**
    Deleted original: 00096.MTS

  ## Processing: 00096.MTS (928.1 MB)
    Creation date: 2025-12-05 20:50:10 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.156 bpp))
frame=32085 fps=265 q=-0.0 Lsize=  340069KiB time=00:17:50.53 bitrate=2602.3kbits/s speed=8.85x elapsed=0:02:00.99
    **Converted: 332.1 MB (64.2% smaller) in 121.1s**
    Deleted original: 00096.MTS

  ## Processing: 00097.MTS (66.9 MB)
    Creation date: 2022-05-19 17:17:27 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 2550 fps=262 q=-0.0 Lsize=   14745KiB time=00:01:25.05 bitrate=1420.2kbits/s speed=8.72x elapsed=0:00:09.74
    **Converted: 14.4 MB (78.5% smaller) in 9.8s**
    Deleted original: 00097.MTS

  ## Processing: 00097.MTS (1174.6 MB)
    Creation date: 2025-12-05 21:09:09 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.156 bpp))
frame=40515 fps=265 q=-0.0 Lsize=  434726KiB time=00:22:31.81 bitrate=2634.4kbits/s speed=8.85x elapsed=0:02:32.80
    **Converted: 424.5 MB (63.9% smaller) in 152.9s**
    Deleted original: 00097.MTS

  ## Processing: 00098.MTS (90.8 MB)
    Creation date: 2022-05-19 17:49:54 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.152 bpp))
frame= 3225 fps=262 q=-0.0 Lsize=   44506KiB time=00:01:47.57 bitrate=3389.2kbits/s speed=8.75x elapsed=0:00:12.28
    **Converted: 43.5 MB (52.1% smaller) in 12.4s**
    Deleted original: 00098.MTS

  ## Processing: 00099.MTS (102.9 MB)
    Creation date: 2022-05-19 18:08:50 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.144 bpp))
frame= 3840 fps=263 q=-0.0 Lsize=   40941KiB time=00:02:08.09 bitrate=2618.3kbits/s speed=8.78x elapsed=0:00:14.59
    **Converted: 40.0 MB (61.2% smaller) in 14.7s**
    Deleted original: 00099.MTS

  ## Processing: 00099.MTS (21.0 MB)
    Creation date: 2025-12-18 10:09:18 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
[vist#0:0/h264 @ 0xaa0c0c300] [dec:h264 @ 0xaa0c14500] Decoding error: Invalid data found when processing input
frame=  750 fps=253 q=-0.0 Lsize=   10678KiB time=00:00:24.99 bitrate=3500.3kbits/s speed=8.42x elapsed=0:00:02.96
    **Converted: 10.4 MB (50.3% smaller) in 3.0s**
    Deleted original: 00099.MTS

  ## Processing: 00100.MTS (106.5 MB)
    Creation date: 2022-05-19 18:34:59 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.148 bpp))
frame= 3870 fps=263 q=-0.0 Lsize=   46272KiB time=00:02:09.09 bitrate=2936.3kbits/s speed=8.78x elapsed=0:00:14.70
    **Converted: 45.2 MB (57.6% smaller) in 14.8s**
    Deleted original: 00100.MTS

  ## Processing: 00100.MTS (82.6 MB)
    Creation date: 2025-12-18 10:52:53 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 3165 fps=262 q=-0.0 Lsize=   15014KiB time=00:01:45.57 bitrate=1165.1kbits/s speed=8.73x elapsed=0:00:12.09
    **Converted: 14.7 MB (82.3% smaller) in 12.2s**
    Deleted original: 00100.MTS

  ## Processing: 00101.MTS (79.5 MB)
    Creation date: 2022-05-19 19:03:24 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.146 bpp))
frame= 2925 fps=262 q=-0.0 Lsize=   34037KiB time=00:01:37.56 bitrate=2858.0kbits/s speed=8.75x elapsed=0:00:11.15
    **Converted: 33.2 MB (58.2% smaller) in 11.2s**
    Deleted original: 00101.MTS

  ## Processing: 00101.MTS (76.0 MB)
    Creation date: 2025-12-18 10:54:54 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.139 bpp))
frame= 2940 fps=261 q=-0.0 Lsize=   10590KiB time=00:01:38.06 bitrate= 884.7kbits/s speed= 8.7x elapsed=0:00:11.26
    **Converted: 10.3 MB (86.4% smaller) in 11.3s**
    Deleted original: 00101.MTS

  ## Processing: 00102.MTS (56.1 MB)
    Creation date: 2022-05-19 19:23:57 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 2085 fps=261 q=-0.0 Lsize=   22788KiB time=00:01:09.53 bitrate=2684.6kbits/s speed= 8.7x elapsed=0:00:07.98
    **Converted: 22.3 MB (60.3% smaller) in 8.1s**
    Deleted original: 00102.MTS

  ## Processing: 00102.MTS (74.0 MB)
    Creation date: 2025-12-18 10:57:44 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.162 bpp))
frame= 2460 fps=262 q=-0.0 Lsize=   12452KiB time=00:01:22.04 bitrate=1243.3kbits/s speed=8.74x elapsed=0:00:09.39
    **Converted: 12.2 MB (83.6% smaller) in 9.5s**
    Deleted original: 00102.MTS

  ## Processing: 00103.MTS (49.3 MB)
    Creation date: 2022-05-20 16:48:44 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.148 bpp))
frame= 1800 fps=260 q=-0.0 Lsize=   16834KiB time=00:01:00.02 bitrate=2297.4kbits/s speed=8.66x elapsed=0:00:06.93
    **Converted: 16.4 MB (66.7% smaller) in 7.0s**
    Deleted original: 00103.MTS

  ## Processing: 00103.MTS (124.5 MB)
    Creation date: 2025-12-18 14:08:36 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.149 bpp))
frame= 4515 fps=263 q=-0.0 Lsize=   70788KiB time=00:02:30.61 bitrate=3850.1kbits/s speed=8.79x elapsed=0:00:17.14
    **Converted: 69.1 MB (44.5% smaller) in 17.2s**
    Deleted original: 00103.MTS

  ## Processing: 00104.MTS (29.0 MB)
    Creation date: 2022-05-20 16:58:06 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 1080 fps=257 q=-0.0 Lsize=    9103KiB time=00:00:36.00 bitrate=2071.2kbits/s speed=8.57x elapsed=0:00:04.20
    **Converted: 8.9 MB (69.4% smaller) in 4.3s**
    Deleted original: 00104.MTS

  ## Processing: 00104.MTS (121.5 MB)
    Creation date: 2025-12-18 14:18:56 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.149 bpp))
frame= 4380 fps=263 q=-0.0 Lsize=   46357KiB time=00:02:26.11 bitrate=2599.1kbits/s speed=8.79x elapsed=0:00:16.62
    **Converted: 45.3 MB (62.7% smaller) in 16.7s**
    Deleted original: 00104.MTS

  ## Processing: 00105.MTS (21.0 MB)
    Creation date: 2022-05-20 17:03:36 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.154 bpp))
frame=  735 fps=252 q=-0.0 Lsize=    7138KiB time=00:00:24.49 bitrate=2387.6kbits/s speed=8.41x elapsed=0:00:02.91
    **Converted: 7.0 MB (66.8% smaller) in 3.0s**
    Deleted original: 00105.MTS

  ## Processing: 00105.MTS (121.6 MB)
    Creation date: 2025-12-25 08:56:26 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.156 bpp))
frame= 4200 fps=264 q=-0.0 Lsize=   33954KiB time=00:02:20.10 bitrate=1985.3kbits/s speed=8.79x elapsed=0:00:15.93
    **Converted: 33.2 MB (72.7% smaller) in 16.0s**
    Deleted original: 00105.MTS

  ## Processing: 00106.MTS (39.3 MB)
    Creation date: 2022-05-20 17:09:22 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.147 bpp))
frame= 1440 fps=259 q=-0.0 Lsize=   18127KiB time=00:00:48.01 bitrate=3092.7kbits/s speed=8.63x elapsed=0:00:05.56
    **Converted: 17.7 MB (54.9% smaller) in 5.6s**
    Deleted original: 00106.MTS

  ## Processing: 00107.MTS (21.1 MB)
    Creation date: 2022-05-21 11:05:59 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame=  795 fps=254 q=-0.0 Lsize=    4448KiB time=00:00:26.49 bitrate=1375.2kbits/s speed=8.45x elapsed=0:00:03.13
    **Converted: 4.3 MB (79.4% smaller) in 3.2s**
    Deleted original: 00107.MTS

  ## Processing: 00107.MTS (41.2 MB)
    Creation date: 2026-01-23 20:59:08 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.138 bpp))
frame= 1605 fps=257 q=-0.0 Lsize=    3468KiB time=00:00:53.52 bitrate= 530.8kbits/s speed=8.58x elapsed=0:00:06.23
    **Converted: 3.4 MB (91.8% smaller) in 6.3s**
    Deleted original: 00107.MTS

  ## Processing: 00108.MTS (17.4 MB)
    Creation date: 2022-05-21 11:06:42 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.142 bpp))
frame=  660 fps=251 q=-0.0 Lsize=    4889KiB time=00:00:21.98 bitrate=1821.4kbits/s speed=8.36x elapsed=0:00:02.63
    **Converted: 4.8 MB (72.6% smaller) in 2.7s**
    Deleted original: 00108.MTS

  ## Processing: 00108.MTS (477.2 MB)
    Creation date: 2026-01-31 14:54:05 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.154 bpp))
frame=16665 fps=264 q=-0.0 Lsize=  170585KiB time=00:09:16.02 bitrate=2513.3kbits/s speed=8.81x elapsed=0:01:03.13
    **Converted: 166.6 MB (65.1% smaller) in 63.2s**
    Deleted original: 00108.MTS

  ## Processing: 00109.MTS (169.1 MB)
    Creation date: 2022-05-22 10:03:46 (from exiftool)
    Encoder: libx265 (high complexity (0.176 bpp > 0.17))
frame= 5190 fps= 19 q=33.5 Lsize=  208529KiB time=00:02:53.07 bitrate=9870.2kbits/s speed=0.645x elapsed=0:04:28.33
encoded 5190 frames in 268.32s (19.34 fps), 9660.65 kb/s, Avg QP:31.59
    **Converted: 203.6 MB (-20.5% smaller) in 268.4s**
    Deleted original: 00109.MTS

  ## Processing: 00109.MTS (209.5 MB)
    Creation date: 2026-01-31 15:08:47 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame= 7500 fps=264 q=-0.0 Lsize=   95593KiB time=00:04:10.21 bitrate=3129.7kbits/s speed=8.82x elapsed=0:00:28.37
    **Converted: 93.4 MB (55.4% smaller) in 28.4s**
    Deleted original: 00109.MTS

  ## Processing: 00111.MTS (177.1 MB)
    Creation date: 2022-05-22 10:21:17 (from exiftool)
    Encoder: libx265 (high complexity (0.209 bpp > 0.17))
frame= 4575 fps= 19 q=33.6 Lsize=  210392KiB time=00:02:32.55 bitrate=11298.0kbits/s speed=0.618x elapsed=0:04:06.93
encoded 4575 frames in 246.92s (18.53 fps), 11087.39 kb/s, Avg QP:32.10
    **Converted: 205.5 MB (-16.0% smaller) in 247.0s**
    Deleted original: 00111.MTS

  ## Processing: 00112.MTS (285.1 MB)
    Creation date: 2022-05-22 10:31:13 (from exiftool)
    Encoder: libx265 (high complexity (0.211 bpp > 0.17))
frame= 7275 fps= 17 q=33.6 Lsize=  410823KiB time=00:04:02.64 bitrate=13870.0kbits/s speed=0.557x elapsed=0:07:15.37
encoded 7275 frames in 435.36s (16.71 fps), 13658.31 kb/s, Avg QP:31.98
    **Converted: 401.2 MB (-40.7% smaller) in 435.5s**
    Deleted original: 00112.MTS

  ## Processing: 00113.MTS (47.9 MB)
    Creation date: 2022-05-23 09:10:25 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.142 bpp))
frame= 1815 fps=259 q=-0.0 Lsize=   14266KiB time=00:01:00.52 bitrate=1930.8kbits/s speed=8.65x elapsed=0:00:07.00
    **Converted: 13.9 MB (70.9% smaller) in 7.1s**
    Deleted original: 00113.MTS

  ## Processing: 00114.MTS (144.4 MB)
    Creation date: 2022-05-23 09:12:44 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.147 bpp))
frame= 5280 fps=264 q=-0.0 Lsize=   42251KiB time=00:02:56.14 bitrate=1965.0kbits/s speed=8.79x elapsed=0:00:20.02
    **Converted: 41.3 MB (71.4% smaller) in 20.1s**
    Deleted original: 00114.MTS

  ## Processing: 00115.MTS (8.5 MB)
    Creation date: 2022-05-23 09:20:51 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.153 bpp))
frame=  300 fps=235 q=-0.0 Lsize=    4684KiB time=00:00:09.97 bitrate=3846.1kbits/s speed=7.83x elapsed=0:00:01.27
    **Converted: 4.6 MB (46.2% smaller) in 1.3s**
    Deleted original: 00115.MTS

  ## Processing: 00116.MTS (56.1 MB)
    Creation date: 2022-05-23 09:22:16 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.142 bpp))
frame= 2130 fps=261 q=-0.0 Lsize=   20418KiB time=00:01:11.03 bitrate=2354.6kbits/s speed=8.69x elapsed=0:00:08.17
    **Converted: 19.9 MB (64.4% smaller) in 8.2s**
    Deleted original: 00116.MTS

  ## Processing: 00117.MTS (134.7 MB)
    Creation date: 2022-05-23 09:28:22 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.147 bpp))
frame= 4950 fps=261 q=-0.0 Lsize=   43072KiB time=00:02:45.13 bitrate=2136.7kbits/s speed=8.72x elapsed=0:00:18.94
    **Converted: 42.1 MB (68.8% smaller) in 19.0s**
    Deleted original: 00117.MTS

  ## Processing: 00118.MTS (10.7 MB)
    Creation date: 2022-05-23 09:35:45 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.142 bpp))
frame=  405 fps=242 q=-0.0 Lsize=    3559KiB time=00:00:13.48 bitrate=2162.5kbits/s speed=8.07x elapsed=0:00:01.67
    **Converted: 3.5 MB (67.5% smaller) in 1.7s**
    Deleted original: 00118.MTS

  ## Processing: 00119.MTS (44.5 MB)
    Creation date: 2022-09-07 19:30:07 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 1650 fps=259 q=-0.0 Lsize=   15936KiB time=00:00:55.02 bitrate=2372.7kbits/s speed=8.65x elapsed=0:00:06.35
    **Converted: 15.6 MB (65.0% smaller) in 6.4s**
    Deleted original: 00119.MTS

  ## Processing: 00120.MTS (51.4 MB)
    Creation date: 2022-09-09 15:23:44 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame= 1935 fps=260 q=-0.0 Lsize=   16477KiB time=00:01:04.53 bitrate=2091.7kbits/s speed=8.67x elapsed=0:00:07.44
    **Converted: 16.1 MB (68.7% smaller) in 7.5s**
    Deleted original: 00120.MTS

  ## Processing: 00121.MTS (10.5 MB)
    Creation date: 2022-09-09 15:43:17 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame=  375 fps=240 q=-0.0 Lsize=    4406KiB time=00:00:12.47 bitrate=2892.3kbits/s speed=   8x elapsed=0:00:01.56
    **Converted: 4.3 MB (59.0% smaller) in 1.6s**
    Deleted original: 00121.MTS

  ## Processing: 00122.MTS (9.0 MB)
    Creation date: 2022-09-09 15:43:52 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.147 bpp))
frame=  330 fps=238 q=-0.0 Lsize=    3629KiB time=00:00:10.97 bitrate=2708.2kbits/s speed=7.92x elapsed=0:00:01.38
    **Converted: 3.5 MB (60.6% smaller) in 1.5s**
    Deleted original: 00122.MTS

  ## Processing: 00123.MTS (17.7 MB)
    Creation date: 2022-09-09 16:01:11 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  630 fps=250 q=-0.0 Lsize=    6806KiB time=00:00:20.98 bitrate=2656.6kbits/s speed=8.33x elapsed=0:00:02.51
    **Converted: 6.6 MB (62.4% smaller) in 2.6s**
    Deleted original: 00123.MTS

  ## Processing: 00124.MTS (32.8 MB)
    Creation date: 2022-09-09 16:17:47 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.142 bpp))
frame= 1245 fps=257 q=-0.0 Lsize=    9171KiB time=00:00:41.50 bitrate=1809.9kbits/s speed=8.57x elapsed=0:00:04.84
    **Converted: 9.0 MB (72.7% smaller) in 4.9s**
    Deleted original: 00124.MTS

  ## Processing: 00125.MTS (7.9 MB)
    Creation date: 2022-09-23 15:15:59 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame=  285 fps=233 q=-0.0 Lsize=    3272KiB time=00:00:09.47 bitrate=2828.9kbits/s speed=7.74x elapsed=0:00:01.22
    **Converted: 3.2 MB (59.8% smaller) in 1.3s**
    Deleted original: 00125.MTS

  ## Processing: 00126.MTS (21.3 MB)
    Creation date: 2022-09-23 15:19:54 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.153 bpp))
frame=  750 fps=252 q=-0.0 Lsize=   11001KiB time=00:00:24.99 bitrate=3605.9kbits/s speed=8.41x elapsed=0:00:02.97
    **Converted: 10.7 MB (49.5% smaller) in 3.0s**
    Deleted original: 00126.MTS

  ## Processing: 00127.MTS (7.0 MB)
    Creation date: 2022-09-23 15:32:24 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.148 bpp))
frame=  255 fps=230 q=-0.0 Lsize=    2953KiB time=00:00:08.47 bitrate=2854.0kbits/s speed=7.64x elapsed=0:00:01.11
    **Converted: 2.9 MB (58.8% smaller) in 1.2s**
    Deleted original: 00127.MTS

  ## Processing: 00128.MTS (6.5 MB)
    Creation date: 2022-09-23 15:32:48 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.146 bpp))
frame=  240 fps=229 q=-0.0 Lsize=    2634KiB time=00:00:07.97 bitrate=2706.1kbits/s speed= 7.6x elapsed=0:00:01.04
    **Converted: 2.6 MB (60.4% smaller) in 1.1s**
    Deleted original: 00128.MTS

  ## Processing: 00129.MTS (36.1 MB)
    Creation date: 2022-09-23 15:42:50 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 1380 fps=259 q=-0.0 Lsize=   10666KiB time=00:00:46.01 bitrate=1899.0kbits/s speed=8.63x elapsed=0:00:05.33
    **Converted: 10.4 MB (71.1% smaller) in 5.4s**
    Deleted original: 00129.MTS

  ## Processing: 00130.MTS (42.2 MB)
    Creation date: 2022-09-23 16:01:02 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.140 bpp))
frame= 1620 fps=258 q=-0.0 Lsize=    9060KiB time=00:00:54.02 bitrate=1374.0kbits/s speed=8.61x elapsed=0:00:06.27
    **Converted: 8.8 MB (79.0% smaller) in 6.3s**
    Deleted original: 00130.MTS

  ## Processing: 00131.MTS (3.0 MB)
    Creation date: 2022-10-21 15:20:23 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.153 bpp))
frame=  105 fps=0.0 q=-0.0 Lsize=    1234KiB time=00:00:03.47 bitrate=2913.4kbits/s speed=6.35x elapsed=0:00:00.54
    **Converted: 1.2 MB (59.7% smaller) in 0.6s**
    Deleted original: 00131.MTS

  ## Processing: 00132.MTS (24.4 MB)
    Creation date: 2022-10-21 15:20:47 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  870 fps=254 q=-0.0 Lsize=    9158KiB time=00:00:28.99 bitrate=2587.2kbits/s speed=8.45x elapsed=0:00:03.43
    **Converted: 8.9 MB (63.3% smaller) in 3.5s**
    Deleted original: 00132.MTS

  ## Processing: 00133.MTS (8.0 MB)
    Creation date: 2022-10-21 15:37:29 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  285 fps=232 q=-0.0 Lsize=    3898KiB time=00:00:09.47 bitrate=3370.0kbits/s speed=7.73x elapsed=0:00:01.22
    **Converted: 3.8 MB (52.6% smaller) in 1.3s**
    Deleted original: 00133.MTS

  ## Processing: 00134.MTS (6.8 MB)
    Creation date: 2022-10-21 15:38:00 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  240 fps=227 q=-0.0 Lsize=    3638KiB time=00:00:07.97 bitrate=3736.8kbits/s speed=7.56x elapsed=0:00:01.05
    **Converted: 3.6 MB (47.5% smaller) in 1.1s**
    Deleted original: 00134.MTS

  ## Processing: 00135.MTS (44.2 MB)
    Creation date: 2022-10-21 15:51:02 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.133 bpp))
frame= 1785 fps=260 q=-0.0 Lsize=    6925KiB time=00:00:59.52 bitrate= 953.0kbits/s speed=8.66x elapsed=0:00:06.87
    **Converted: 6.8 MB (84.7% smaller) in 6.9s**
    Deleted original: 00135.MTS

  ## Processing: 00136.MTS (39.6 MB)
    Creation date: 2022-10-21 16:06:47 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 1470 fps=259 q=-0.0 Lsize=   12760KiB time=00:00:49.01 bitrate=2132.5kbits/s speed=8.63x elapsed=0:00:05.67
    **Converted: 12.5 MB (68.5% smaller) in 5.8s**
    Deleted original: 00136.MTS

  ## Processing: 00137.MTS (29.5 MB)
    Creation date: 2022-11-11 14:08:37 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame= 1110 fps=257 q=-0.0 Lsize=    9209KiB time=00:00:37.00 bitrate=2038.7kbits/s speed=8.55x elapsed=0:00:04.32
    **Converted: 9.0 MB (69.5% smaller) in 4.4s**
    Deleted original: 00137.MTS

  ## Processing: 00138.MTS (35.7 MB)
    Creation date: 2022-11-11 14:17:02 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.144 bpp))
frame= 1335 fps=258 q=-0.0 Lsize=   13828KiB time=00:00:44.51 bitrate=2545.0kbits/s speed= 8.6x elapsed=0:00:05.17
    **Converted: 13.5 MB (62.2% smaller) in 5.2s**
    Deleted original: 00138.MTS

  ## Processing: 00139.MTS (6.1 MB)
    Creation date: 2022-11-11 14:35:39 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.146 bpp))
frame=  225 fps=224 q=-0.0 Lsize=    3291KiB time=00:00:07.47 bitrate=3607.2kbits/s speed=7.45x elapsed=0:00:01.00
    **Converted: 3.2 MB (47.5% smaller) in 1.1s**
    Deleted original: 00139.MTS

  ## Processing: 00140.MTS (19.9 MB)
    Creation date: 2022-11-11 14:35:52 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.146 bpp))
frame=  735 fps=251 q=-0.0 Lsize=    9346KiB time=00:00:24.49 bitrate=3126.2kbits/s speed=8.38x elapsed=0:00:02.92
    **Converted: 9.1 MB (54.2% smaller) in 3.0s**
    Deleted original: 00140.MTS

  ## Processing: 00141.MTS (13.8 MB)
    Creation date: 2022-11-11 14:40:43 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame=  495 fps=246 q=-0.0 Lsize=    5769KiB time=00:00:16.48 bitrate=2867.4kbits/s speed=8.19x elapsed=0:00:02.01
    **Converted: 5.6 MB (59.3% smaller) in 2.1s**
    Deleted original: 00141.MTS

  ## Processing: 00142.MTS (4.6 MB)
    Creation date: 2022-11-11 16:35:39 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  165 fps=0.0 q=-0.0 Lsize=    2177KiB time=00:00:05.47 bitrate=3258.4kbits/s speed=7.06x elapsed=0:00:00.77
    **Converted: 2.1 MB (54.3% smaller) in 0.8s**
    Deleted original: 00142.MTS

  ## Processing: 00143.MTS (7.9 MB)
    Creation date: 2022-11-11 16:37:51 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.148 bpp))
frame=  285 fps=231 q=-0.0 Lsize=    3722KiB time=00:00:09.47 bitrate=3218.0kbits/s speed=7.68x elapsed=0:00:01.23
    **Converted: 3.6 MB (53.7% smaller) in 1.3s**
    Deleted original: 00143.MTS

  ## Processing: 00144.MTS (29.4 MB)
    Creation date: 2022-11-11 16:40:03 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.149 bpp))
frame= 1065 fps=256 q=-0.0 Lsize=   14151KiB time=00:00:35.50 bitrate=3265.3kbits/s speed=8.54x elapsed=0:00:04.15
    **Converted: 13.8 MB (53.1% smaller) in 4.2s**
    Deleted original: 00144.MTS

  ## Processing: 00145.MTS (9.6 MB)
    Creation date: 2022-11-11 16:40:47 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame=  345 fps=238 q=-0.0 Lsize=    4235KiB time=00:00:11.47 bitrate=3022.7kbits/s speed=7.93x elapsed=0:00:01.44
    **Converted: 4.1 MB (56.8% smaller) in 1.5s**
    Deleted original: 00145.MTS

  ## Processing: 00146.MTS (21.5 MB)
    Creation date: 2022-11-11 16:53:07 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame=  810 fps=252 q=-0.0 Lsize=    7695KiB time=00:00:26.99 bitrate=2335.3kbits/s speed=8.41x elapsed=0:00:03.20
    **Converted: 7.5 MB (65.0% smaller) in 3.3s**
    Deleted original: 00146.MTS

  ## Processing: 00147.MTS (25.8 MB)
    Creation date: 2022-11-11 16:55:54 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame=  975 fps=255 q=-0.0 Lsize=    8529KiB time=00:00:32.49 bitrate=2149.8kbits/s speed=8.49x elapsed=0:00:03.82
    **Converted: 8.3 MB (67.7% smaller) in 3.9s**
    Deleted original: 00147.MTS

  ## Processing: 00148.MTS (66.4 MB)
    Creation date: 2022-11-11 17:06:11 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.138 bpp))
frame= 2595 fps=261 q=-0.0 Lsize=   14032KiB time=00:01:26.55 bitrate=1328.1kbits/s speed=8.71x elapsed=0:00:09.93
    **Converted: 13.7 MB (79.4% smaller) in 10.0s**
    Deleted original: 00148.MTS

  ## Processing: 00149.MTS (88.7 MB)
    Creation date: 2022-11-11 17:11:04 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.142 bpp))
frame= 3375 fps=263 q=-0.0 Lsize=   19368KiB time=00:01:52.57 bitrate=1409.4kbits/s speed=8.76x elapsed=0:00:12.85
    **Converted: 18.9 MB (78.7% smaller) in 12.9s**
    Deleted original: 00149.MTS

  ## Processing: 00150.MTS (38.5 MB)
    Creation date: 2022-11-11 17:30:41 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 1425 fps=258 q=-0.0 Lsize=   17005KiB time=00:00:47.51 bitrate=2931.9kbits/s speed=8.61x elapsed=0:00:05.51
    **Converted: 16.6 MB (56.8% smaller) in 5.6s**
    Deleted original: 00150.MTS

  ## Processing: 00151.MTS (4.6 MB)
    Creation date: 2022-11-11 18:29:28 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.149 bpp))
frame=  165 fps=0.0 q=-0.0 Lsize=    1876KiB time=00:00:05.47 bitrate=2807.9kbits/s speed=7.04x elapsed=0:00:00.77
    **Converted: 1.8 MB (60.1% smaller) in 0.8s**
    Deleted original: 00151.MTS

  ## Processing: 00152.MTS (128.3 MB)
    Creation date: 2022-12-14 14:16:27 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.146 bpp))
frame= 4725 fps=264 q=-0.0 Lsize=   66504KiB time=00:02:37.62 bitrate=3456.3kbits/s speed=8.79x elapsed=0:00:17.92
    **Converted: 64.9 MB (49.4% smaller) in 18.0s**
    Deleted original: 00152.MTS

  ## Processing: 00153.MTS (127.9 MB)
    Creation date: 2022-12-14 14:29:06 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.147 bpp))
frame= 4680 fps=264 q=-0.0 Lsize=   56949KiB time=00:02:36.12 bitrate=2988.2kbits/s speed= 8.8x elapsed=0:00:17.74
    **Converted: 55.6 MB (56.5% smaller) in 17.8s**
    Deleted original: 00153.MTS

  ## Processing: 00154.MTS (245.2 MB)
    Creation date: 2022-12-24 08:16:46 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.153 bpp))
frame= 8625 fps=265 q=-0.0 Lsize=   72552KiB time=00:04:47.75 bitrate=2065.5kbits/s speed=8.83x elapsed=0:00:32.59
    **Converted: 70.9 MB (71.1% smaller) in 32.7s**
    Deleted original: 00154.MTS

  ## Processing: 00157.MTS (29.8 MB)
    Creation date: 2023-02-03 14:08:08 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.139 bpp))
frame= 1155 fps=256 q=-0.0 Lsize=    9677KiB time=00:00:38.50 bitrate=2058.8kbits/s speed=8.53x elapsed=0:00:04.51
    **Converted: 9.5 MB (68.3% smaller) in 4.6s**
    Deleted original: 00157.MTS

  ## Processing: 00158.MTS (56.6 MB)
    Creation date: 2023-02-03 14:13:15 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.149 bpp))
frame= 2040 fps=260 q=-0.0 Lsize=   32396KiB time=00:01:08.03 bitrate=3900.8kbits/s speed=8.66x elapsed=0:00:07.85
    **Converted: 31.6 MB (44.1% smaller) in 7.9s**
    Deleted original: 00158.MTS

  ## Processing: 00159.MTS (14.3 MB)
    Creation date: 2023-02-03 14:16:11 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.155 bpp))
frame=  495 fps=244 q=-0.0 Lsize=    9667KiB time=00:00:16.48 bitrate=4804.4kbits/s speed=8.11x elapsed=0:00:02.03
    **Converted: 9.4 MB (33.9% smaller) in 2.1s**
    Deleted original: 00159.MTS

  ## Processing: 00160.MTS (103.4 MB)
    Creation date: 2023-02-03 14:28:46 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.148 bpp))
frame= 3765 fps=263 q=-0.0 Lsize=   47461KiB time=00:02:05.59 bitrate=3095.7kbits/s speed=8.76x elapsed=0:00:14.34
    **Converted: 46.3 MB (55.2% smaller) in 14.4s**
    Deleted original: 00160.MTS

  ## Processing: 00161.MTS (56.1 MB)
    Creation date: 2023-02-03 14:34:40 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.144 bpp))
frame= 2100 fps=260 q=-0.0 Lsize=   35494KiB time=00:01:10.03 bitrate=4151.6kbits/s speed=8.67x elapsed=0:00:08.07
    **Converted: 34.7 MB (38.3% smaller) in 8.1s**
    Deleted original: 00161.MTS

  ## Processing: 00162.MTS (51.0 MB)
    Creation date: 2023-02-03 14:36:05 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.154 bpp))
frame= 1785 fps=259 q=-0.0 Lsize=   32577KiB time=00:00:59.52 bitrate=4483.2kbits/s speed=8.65x elapsed=0:00:06.88
    **Converted: 31.8 MB (37.6% smaller) in 7.0s**
    Deleted original: 00162.MTS

  ## Processing: 00163.MTS (85.2 MB)
    Creation date: 2023-02-03 14:44:30 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 3165 fps=262 q=-0.0 Lsize=   52795KiB time=00:01:45.57 bitrate=4096.7kbits/s speed=8.74x elapsed=0:00:12.08
    **Converted: 51.6 MB (39.5% smaller) in 12.1s**
    Deleted original: 00163.MTS

  ## Processing: 00165.MTS (14.0 MB)
    Creation date: 2023-02-03 14:50:26 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.148 bpp))
frame=  510 fps=245 q=-0.0 Lsize=    7423KiB time=00:00:16.98 bitrate=3580.2kbits/s speed=8.16x elapsed=0:00:02.08
    **Converted: 7.2 MB (48.3% smaller) in 2.2s**
    Deleted original: 00165.MTS

  ## Processing: 00166.MTS (200.3 MB)
    Creation date: 2023-02-03 14:50:49 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.153 bpp))
frame= 7035 fps=264 q=-0.0 Lsize=  133135KiB time=00:03:54.70 bitrate=4646.9kbits/s speed=8.82x elapsed=0:00:26.61
    **Converted: 130.0 MB (35.1% smaller) in 26.7s**
    Deleted original: 00166.MTS

  ## Processing: 00167.MTS (117.4 MB)
    Creation date: 2023-02-03 15:01:20 (from exiftool)
    Encoder: libx265 (high complexity (0.186 bpp > 0.17))
frame= 3405 fps= 19 q=34.0 Lsize=  131214KiB time=00:01:53.51 bitrate=9469.4kbits/s speed=0.626x elapsed=0:03:01.35
encoded 3405 frames in 181.34s (18.78 fps), 9255.36 kb/s, Avg QP:31.81
    **Converted: 128.1 MB (-9.1% smaller) in 181.4s**
    Deleted original: 00167.MTS

  ## Processing: 00168.MTS (34.9 MB)
    Creation date: 2023-02-11 19:22:52 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.149 bpp))
frame= 1260 fps=258 q=-0.0 Lsize=   11020KiB time=00:00:42.00 bitrate=2149.0kbits/s speed=8.59x elapsed=0:00:04.88
    **Converted: 10.8 MB (69.2% smaller) in 5.0s**
    Deleted original: 00168.MTS

  ## Processing: 00169.MTS (25.5 MB)
    Creation date: 2023-03-12 20:11:54 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.155 bpp))
frame=  885 fps=255 q=-0.0 Lsize=    7232KiB time=00:00:29.49 bitrate=2008.6kbits/s speed=8.48x elapsed=0:00:03.47
    **Converted: 7.1 MB (72.3% smaller) in 3.5s**
    Deleted original: 00169.MTS

  ## Processing: 00170.MTS (99.9 MB)
    Creation date: 2023-05-18 16:07:14 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.146 bpp))
frame= 3675 fps=263 q=-0.0 Lsize=   30753KiB time=00:02:02.58 bitrate=2055.1kbits/s speed=8.78x elapsed=0:00:13.95
    **Converted: 30.0 MB (69.9% smaller) in 14.0s**
    Deleted original: 00170.MTS

  ## Processing: 00171.MTS (134.8 MB)
    Creation date: 2023-05-18 16:10:16 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.147 bpp))
frame= 4950 fps=264 q=-0.0 Lsize=   50075KiB time=00:02:45.13 bitrate=2484.2kbits/s speed= 8.8x elapsed=0:00:18.75
    **Converted: 48.9 MB (63.7% smaller) in 18.8s**
    Deleted original: 00171.MTS

  ## Processing: 00172.MTS (10.1 MB)
    Creation date: 2023-05-18 17:38:03 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame=  360 fps=239 q=-0.0 Lsize=    3058KiB time=00:00:11.97 bitrate=2091.1kbits/s speed=7.94x elapsed=0:00:01.50
    **Converted: 3.0 MB (70.3% smaller) in 1.6s**
    Deleted original: 00172.MTS

  ## Processing: 00173.MTS (51.2 MB)
    Creation date: 2023-05-18 17:44:31 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 1905 fps=260 q=-0.0 Lsize=   22249KiB time=00:01:03.53 bitrate=2868.9kbits/s speed=8.68x elapsed=0:00:07.32
    **Converted: 21.7 MB (57.6% smaller) in 7.4s**
    Deleted original: 00173.MTS

  ## Processing: 00174.MTS (69.5 MB)
    Creation date: 2023-05-18 17:50:52 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.144 bpp))
frame= 2610 fps=261 q=-0.0 Lsize=   27593KiB time=00:01:27.05 bitrate=2596.6kbits/s speed=8.71x elapsed=0:00:09.99
    **Converted: 26.9 MB (61.2% smaller) in 10.1s**
    Deleted original: 00174.MTS

  ## Processing: 00175.MTS (36.0 MB)
    Creation date: 2023-05-18 17:59:53 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 1335 fps=258 q=-0.0 Lsize=   15135KiB time=00:00:44.51 bitrate=2785.5kbits/s speed= 8.6x elapsed=0:00:05.17
    **Converted: 14.8 MB (58.9% smaller) in 5.2s**
    Deleted original: 00175.MTS

  ## Processing: 00176.MTS (29.9 MB)
    Creation date: 2023-05-18 18:02:54 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 1110 fps=257 q=-0.0 Lsize=   12139KiB time=00:00:37.00 bitrate=2687.3kbits/s speed=8.56x elapsed=0:00:04.32
    **Converted: 11.9 MB (60.4% smaller) in 4.4s**
    Deleted original: 00176.MTS

  ## Processing: 00177.MTS (50.1 MB)
    Creation date: 2023-05-19 12:35:48 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.147 bpp))
frame= 1830 fps=260 q=-0.0 Lsize=   21260KiB time=00:01:01.02 bitrate=2853.8kbits/s speed=8.68x elapsed=0:00:07.02
    **Converted: 20.8 MB (58.5% smaller) in 7.1s**
    Deleted original: 00177.MTS

  ## Processing: 00178.MTS (22.2 MB)
    Creation date: 2023-05-19 18:42:37 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame=  825 fps=253 q=-0.0 Lsize=    8902KiB time=00:00:27.49 bitrate=2652.3kbits/s speed=8.43x elapsed=0:00:03.25
    **Converted: 8.7 MB (60.9% smaller) in 3.3s**
    Deleted original: 00178.MTS

  ## Processing: 00179.MTS (38.5 MB)
    Creation date: 2023-05-19 18:53:43 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 1425 fps=259 q=-0.0 Lsize=   14162KiB time=00:00:47.51 bitrate=2441.7kbits/s speed=8.62x elapsed=0:00:05.51
    **Converted: 13.8 MB (64.0% smaller) in 5.6s**
    Deleted original: 00179.MTS

  ## Processing: 00180.MTS (18.1 MB)
    Creation date: 2023-05-19 19:01:57 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  645 fps=250 q=-0.0 Lsize=    9074KiB time=00:00:21.48 bitrate=3459.2kbits/s speed=8.34x elapsed=0:00:02.57
    **Converted: 8.9 MB (51.0% smaller) in 2.6s**
    Deleted original: 00180.MTS

  ## Processing: 00181.MTS (28.0 MB)
    Creation date: 2023-05-19 19:13:40 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.148 bpp))
frame= 1020 fps=256 q=-0.0 Lsize=   11018KiB time=00:00:34.00 bitrate=2654.7kbits/s speed=8.54x elapsed=0:00:03.98
    **Converted: 10.8 MB (61.5% smaller) in 4.1s**
    Deleted original: 00181.MTS

  ## Processing: 00182.MTS (112.1 MB)
    Creation date: 2023-05-22 09:22:38 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame= 4035 fps=263 q=-0.0 Lsize=   61635KiB time=00:02:14.60 bitrate=3751.2kbits/s speed=8.77x elapsed=0:00:15.34
    **Converted: 60.2 MB (46.3% smaller) in 15.4s**
    Deleted original: 00182.MTS

  ## Processing: 00183.MTS (122.4 MB)
    Creation date: 2023-05-22 09:33:19 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.167 bpp))
frame= 3960 fps=263 q=-0.0 Lsize=   87705KiB time=00:02:12.09 bitrate=5438.9kbits/s speed=8.77x elapsed=0:00:15.06
    **Converted: 85.6 MB (30.1% smaller) in 15.1s**
    Deleted original: 00183.MTS

  ## Processing: 00184.MTS (4.6 MB)
    Creation date: 2023-06-22 16:12:05 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.136 bpp))
frame=  180 fps=0.0 q=-0.0 Lsize=    1971KiB time=00:00:05.97 bitrate=2703.9kbits/s speed=7.09x elapsed=0:00:00.84
    **Converted: 1.9 MB (57.8% smaller) in 0.9s**
    Deleted original: 00184.MTS

  ## Processing: 00185.MTS (17.4 MB)
    Creation date: 2023-06-22 16:13:26 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.133 bpp))
frame=  705 fps=250 q=-0.0 Lsize=    6066KiB time=00:00:23.49 bitrate=2115.5kbits/s speed=8.33x elapsed=0:00:02.81
    **Converted: 5.9 MB (66.0% smaller) in 2.9s**
    Deleted original: 00185.MTS

  ## Processing: 00186.MTS (28.6 MB)
    Creation date: 2023-06-22 16:14:35 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.137 bpp))
frame= 1125 fps=256 q=-0.0 Lsize=   10461KiB time=00:00:37.50 bitrate=2285.1kbits/s speed=8.54x elapsed=0:00:04.39
    **Converted: 10.2 MB (64.2% smaller) in 4.5s**
    Deleted original: 00186.MTS

  ## Processing: 00187.MTS (95.4 MB)
    Creation date: 2023-06-22 16:16:30 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.146 bpp))
frame= 3525 fps=262 q=-0.0 Lsize=   46153KiB time=00:01:57.58 bitrate=3215.5kbits/s speed=8.76x elapsed=0:00:13.43
    **Converted: 45.1 MB (52.8% smaller) in 13.5s**
    Deleted original: 00187.MTS

  ## Processing: 00188.MTS (70.3 MB)
    Creation date: 2023-06-22 16:18:55 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame= 2655 fps=262 q=-0.0 Lsize=   32485KiB time=00:01:28.55 bitrate=3005.1kbits/s speed=8.73x elapsed=0:00:10.14
    **Converted: 31.7 MB (54.9% smaller) in 10.2s**
    Deleted original: 00188.MTS

  ## Processing: 00189.MTS (65.1 MB)
    Creation date: 2023-06-22 16:21:09 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame= 2415 fps=262 q=-0.0 Lsize=   31623KiB time=00:01:20.54 bitrate=3216.2kbits/s speed=8.73x elapsed=0:00:09.22
    **Converted: 30.9 MB (52.5% smaller) in 9.3s**
    Deleted original: 00189.MTS

  ## Processing: 00190.MTS (56.7 MB)
    Creation date: 2023-06-22 16:22:41 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.153 bpp))
frame= 1995 fps=256 q=-0.0 Lsize=   28530KiB time=00:01:06.53 bitrate=3512.8kbits/s speed=8.53x elapsed=0:00:07.80
    **Converted: 27.9 MB (50.8% smaller) in 7.9s**
    Deleted original: 00190.MTS

  ## Processing: 00191.MTS (3.7 MB)
    Creation date: 2023-09-22 13:31:10 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.146 bpp))
frame=  135 fps=0.0 q=-0.0 Lsize=    1576KiB time=00:00:04.47 bitrate=2886.9kbits/s speed= 6.8x elapsed=0:00:00.65
    **Converted: 1.5 MB (57.9% smaller) in 0.7s**
    Deleted original: 00191.MTS

  ## Processing: 00192.MTS (43.7 MB)
    Creation date: 2023-09-22 13:43:32 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.144 bpp))
frame= 1635 fps=260 q=-0.0 Lsize=   18406KiB time=00:00:54.52 bitrate=2765.6kbits/s speed=8.66x elapsed=0:00:06.29
    **Converted: 18.0 MB (58.9% smaller) in 6.4s**
    Deleted original: 00192.MTS

  ## Processing: 00193.MTS (7.5 MB)
    Creation date: 2023-09-22 15:28:18 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame=  270 fps=232 q=-0.0 Lsize=    3112KiB time=00:00:08.97 bitrate=2840.1kbits/s speed=7.71x elapsed=0:00:01.16
    **Converted: 3.0 MB (59.5% smaller) in 1.2s**
    Deleted original: 00193.MTS

  ## Processing: 00194.MTS (12.9 MB)
    Creation date: 2023-09-22 15:30:49 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.145 bpp))
frame=  480 fps=245 q=-0.0 Lsize=    4861KiB time=00:00:15.98 bitrate=2491.4kbits/s speed=8.17x elapsed=0:00:01.95
    **Converted: 4.7 MB (63.3% smaller) in 2.0s**
    Deleted original: 00194.MTS

  ## Processing: 00195.MTS (42.9 MB)
    Creation date: 2023-09-22 15:44:39 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame= 1530 fps=259 q=-0.0 Lsize=   17037KiB time=00:00:51.01 bitrate=2735.6kbits/s speed=8.65x elapsed=0:00:05.89
    **Converted: 16.6 MB (61.2% smaller) in 6.0s**
    Deleted original: 00195.MTS

  ## Processing: 00196.MTS (34.6 MB)
    Creation date: 2023-09-22 15:57:01 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 1320 fps=258 q=-0.0 Lsize=    7718KiB time=00:00:44.01 bitrate=1436.6kbits/s speed= 8.6x elapsed=0:00:05.11
    **Converted: 7.5 MB (78.2% smaller) in 5.2s**
    Deleted original: 00196.MTS

  ## Processing: 00197.MTS (36.2 MB)
    Creation date: 2023-09-22 16:02:47 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 1380 fps=258 q=-0.0 Lsize=    8815KiB time=00:00:46.01 bitrate=1569.4kbits/s speed= 8.6x elapsed=0:00:05.34
    **Converted: 8.6 MB (76.2% smaller) in 5.4s**
    Deleted original: 00197.MTS

  ## Processing: 00198.MTS (18.6 MB)
    Creation date: 2023-09-22 16:11:51 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.149 bpp))
frame=  675 fps=252 q=-0.0 Lsize=    7170KiB time=00:00:22.48 bitrate=2611.6kbits/s speed=8.39x elapsed=0:00:02.68
    **Converted: 7.0 MB (62.4% smaller) in 2.8s**
    Deleted original: 00198.MTS

  ## Processing: 00199.MTS (19.4 MB)
    Creation date: 2023-09-22 16:15:02 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  690 fps=251 q=-0.0 Lsize=    7576KiB time=00:00:22.98 bitrate=2699.7kbits/s speed=8.37x elapsed=0:00:02.74
    **Converted: 7.4 MB (61.9% smaller) in 2.8s**
    Deleted original: 00199.MTS

  ## Processing: 00200.MTS (17.1 MB)
    Creation date: 2023-10-10 20:24:22 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame=  645 fps=250 q=-0.0 Lsize=    2500KiB time=00:00:21.48 bitrate= 953.2kbits/s speed=8.33x elapsed=0:00:02.57
    **Converted: 2.4 MB (85.8% smaller) in 2.6s**
    Deleted original: 00200.MTS

  ## Processing: 00201.MTS (32.4 MB)
    Creation date: 2023-10-13 15:40:14 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.144 bpp))
frame= 1215 fps=257 q=-0.0 Lsize=    9542KiB time=00:00:40.50 bitrate=1929.8kbits/s speed=8.58x elapsed=0:00:04.72
    **Converted: 9.3 MB (71.3% smaller) in 4.8s**
    Deleted original: 00201.MTS

  ## Processing: 00202.MTS (21.9 MB)
    Creation date: 2023-10-13 15:53:36 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  780 fps=253 q=-0.0 Lsize=    9383KiB time=00:00:25.99 bitrate=2957.3kbits/s speed=8.44x elapsed=0:00:03.07
    **Converted: 9.2 MB (58.1% smaller) in 3.1s**
    Deleted original: 00202.MTS

  ## Processing: 00203.MTS (23.8 MB)
    Creation date: 2023-10-13 15:57:52 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame=  855 fps=254 q=-0.0 Lsize=   11254KiB time=00:00:28.49 bitrate=3235.4kbits/s speed=8.48x elapsed=0:00:03.36
    **Converted: 11.0 MB (53.9% smaller) in 3.4s**
    Deleted original: 00203.MTS

  ## Processing: 00204.MTS (83.6 MB)
    Creation date: 2023-10-13 16:11:05 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 3195 fps=263 q=-0.0 Lsize=   19831KiB time=00:01:46.57 bitrate=1524.4kbits/s speed=8.76x elapsed=0:00:12.16
    **Converted: 19.4 MB (76.8% smaller) in 12.2s**
    Deleted original: 00204.MTS

  ## Processing: 00205.MTS (37.1 MB)
    Creation date: 2023-10-13 16:16:11 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.140 bpp))
frame= 1425 fps=259 q=-0.0 Lsize=    8608KiB time=00:00:47.51 bitrate=1484.1kbits/s speed=8.64x elapsed=0:00:05.49
    **Converted: 8.4 MB (77.4% smaller) in 5.6s**
    Deleted original: 00205.MTS

  ## Processing: 00206.MTS (5.2 MB)
    Creation date: 2023-11-03 15:39:03 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.157 bpp))
frame=  180 fps=0.0 q=-0.0 Lsize=    3060KiB time=00:00:05.97 bitrate=4197.3kbits/s speed=7.21x elapsed=0:00:00.82
    **Converted: 3.0 MB (43.0% smaller) in 0.9s**
    Deleted original: 00206.MTS

  ## Processing: 00207.MTS (6.3 MB)
    Creation date: 2023-11-03 15:40:48 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  225 fps=0.0 q=-0.0 Lsize=    3178KiB time=00:00:07.47 bitrate=3483.7kbits/s speed=7.51x elapsed=0:00:00.99
    **Converted: 3.1 MB (51.0% smaller) in 1.1s**
    Deleted original: 00207.MTS

  ## Processing: 00208.MTS (9.3 MB)
    Creation date: 2023-11-03 15:41:05 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  330 fps=238 q=-0.0 Lsize=    5066KiB time=00:00:10.97 bitrate=3780.7kbits/s speed= 7.9x elapsed=0:00:01.38
    **Converted: 4.9 MB (46.7% smaller) in 1.5s**
    Deleted original: 00208.MTS

  ## Processing: 00209.MTS (34.3 MB)
    Creation date: 2023-11-03 16:05:20 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame= 1290 fps=258 q=-0.0 Lsize=   11120KiB time=00:00:43.00 bitrate=2118.0kbits/s speed=8.61x elapsed=0:00:04.99
    **Converted: 10.9 MB (68.3% smaller) in 5.1s**
    Deleted original: 00209.MTS

  ## Processing: 00210.MTS (48.6 MB)
    Creation date: 2023-11-03 16:19:32 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 1860 fps=261 q=-0.0 Lsize=   11779KiB time=00:01:02.02 bitrate=1555.6kbits/s speed=8.69x elapsed=0:00:07.13
    **Converted: 11.5 MB (76.3% smaller) in 7.2s**
    Deleted original: 00210.MTS

  ## Processing: 00211.MTS (35.3 MB)
    Creation date: 2023-11-03 16:22:11 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 1350 fps=258 q=-0.0 Lsize=    8626KiB time=00:00:45.01 bitrate=1569.9kbits/s speed=8.62x elapsed=0:00:05.22
    **Converted: 8.4 MB (76.2% smaller) in 5.3s**
    Deleted original: 00211.MTS

  ## Processing: 00212.MTS (20.8 MB)
    Creation date: 2023-11-03 16:34:01 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.152 bpp))
frame=  735 fps=253 q=-0.0 Lsize=    8845KiB time=00:00:24.49 bitrate=2958.7kbits/s speed=8.41x elapsed=0:00:02.91
    **Converted: 8.6 MB (58.4% smaller) in 3.0s**
    Deleted original: 00212.MTS

  ## Processing: 00213.MTS (20.0 MB)
    Creation date: 2023-11-03 16:36:04 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.153 bpp))
frame=  705 fps=251 q=-0.0 Lsize=    8734KiB time=00:00:23.49 bitrate=3046.1kbits/s speed=8.37x elapsed=0:00:02.80
    **Converted: 8.5 MB (57.4% smaller) in 2.9s**
    Deleted original: 00213.MTS

  ## Processing: 00214.MTS (110.2 MB)
    Creation date: 2023-12-19 14:38:50 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.149 bpp))
frame= 3975 fps=263 q=-0.0 Lsize=   60680KiB time=00:02:12.59 bitrate=3748.8kbits/s speed=8.79x elapsed=0:00:15.08
    **Converted: 59.3 MB (46.2% smaller) in 15.2s**
    Deleted original: 00214.MTS

  ## Processing: 00215.MTS (158.5 MB)
    Creation date: 2023-12-19 14:50:16 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.148 bpp))
frame= 5760 fps=264 q=-0.0 Lsize=   56800KiB time=00:03:12.15 bitrate=2421.5kbits/s speed=8.81x elapsed=0:00:21.80
    **Converted: 55.5 MB (65.0% smaller) in 21.9s**
    Deleted original: 00215.MTS

  ## Processing: 00216.MTS (486.9 MB)
    Creation date: 2023-12-24 08:39:29 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.162 bpp))
frame=16170 fps=266 q=-0.0 Lsize=  124688KiB time=00:08:59.50 bitrate=1893.3kbits/s speed=8.86x elapsed=0:01:00.88
    **Converted: 121.8 MB (75.0% smaller) in 61.0s**
    Deleted original: 00216.MTS

  ## Processing: 00217.MTS (12.6 MB)
    Creation date: 2024-02-08 16:32:23 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  450 fps=242 q=-0.0 Lsize=    6831KiB time=00:00:14.98 bitrate=3734.9kbits/s speed=8.07x elapsed=0:00:01.85
    **Converted: 6.7 MB (47.2% smaller) in 1.9s**
    Deleted original: 00217.MTS

  ## Processing: 00218.MTS (16.0 MB)
    Creation date: 2024-02-08 16:37:37 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.151 bpp))
frame=  570 fps=248 q=-0.0 Lsize=    7387KiB time=00:00:18.98 bitrate=3187.3kbits/s speed=8.27x elapsed=0:00:02.29
    **Converted: 7.2 MB (54.9% smaller) in 2.4s**
    Deleted original: 00218.MTS

  ## Processing: 00219.MTS (32.2 MB)
    Creation date: 2024-02-08 17:13:26 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.143 bpp))
frame= 1215 fps=258 q=-0.0 Lsize=    9561KiB time=00:00:40.50 bitrate=1933.5kbits/s speed=8.59x elapsed=0:00:04.71
    **Converted: 9.3 MB (71.0% smaller) in 4.8s**
    Deleted original: 00219.MTS

  ## Processing: 00220.MTS (36.3 MB)
    Creation date: 2024-02-08 17:27:06 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame= 1305 fps=258 q=-0.0 Lsize=   13907KiB time=00:00:43.51 bitrate=2618.5kbits/s speed=8.61x elapsed=0:00:05.05
    **Converted: 13.6 MB (62.6% smaller) in 5.1s**
    Deleted original: 00220.MTS

  ## Processing: 00221.MTS (4.8 MB)
    Creation date: 2024-02-08 17:40:48 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.155 bpp))
frame=  165 fps=0.0 q=-0.0 Lsize=    2412KiB time=00:00:05.47 bitrate=3611.5kbits/s speed= 7.1x elapsed=0:00:00.77
    **Converted: 2.4 MB (50.5% smaller) in 0.8s**
    Deleted original: 00221.MTS

  ## Processing: 00222.MTS (5.5 MB)
    Creation date: 2024-02-08 17:44:36 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.153 bpp))
frame=  195 fps=0.0 q=-0.0 Lsize=    2580KiB time=00:00:06.47 bitrate=3265.0kbits/s speed=7.31x elapsed=0:00:00.88
    **Converted: 2.5 MB (54.5% smaller) in 1.0s**
    Deleted original: 00222.MTS

  ## Processing: 00223.MTS (4.7 MB)
    Creation date: 2024-02-08 17:44:53 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.154 bpp))
frame=  165 fps=0.0 q=-0.0 Lsize=    2081KiB time=00:00:05.47 bitrate=3115.5kbits/s speed=7.03x elapsed=0:00:00.77
    **Converted: 2.0 MB (57.0% smaller) in 0.8s**
    Deleted original: 00223.MTS

  ## Processing: 00224.MTS (27.9 MB)
    Creation date: 2024-02-10 20:27:35 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.141 bpp))
frame= 1065 fps=256 q=-0.0 Lsize=    6235KiB time=00:00:35.50 bitrate=1438.8kbits/s speed=8.53x elapsed=0:00:04.16
    **Converted: 6.1 MB (78.2% smaller) in 4.2s**
    Deleted original: 00224.MTS

  ## Processing: 00225.MTS (29.1 MB)
    Creation date: 2024-02-28 14:34:51 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.132 bpp))
frame= 1185 fps=256 q=-0.0 Lsize=    6545KiB time=00:00:39.50 bitrate=1357.1kbits/s speed=8.55x elapsed=0:00:04.62
    **Converted: 6.4 MB (78.0% smaller) in 4.7s**
    Deleted original: 00225.MTS

  ## Processing: 00226.MTS (22.8 MB)
    Creation date: 2024-02-28 14:50:05 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.144 bpp))
frame=  855 fps=254 q=-0.0 Lsize=    8959KiB time=00:00:28.49 bitrate=2575.5kbits/s speed=8.47x elapsed=0:00:03.36
    **Converted: 8.7 MB (61.7% smaller) in 3.4s**
    Deleted original: 00226.MTS

  ## Processing: 00227.MTS (11.7 MB)
    Creation date: 2024-02-28 14:56:29 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame=  420 fps=242 q=-0.0 Lsize=    4996KiB time=00:00:13.98 bitrate=2927.2kbits/s speed=8.07x elapsed=0:00:01.73
    **Converted: 4.9 MB (58.2% smaller) in 1.8s**
    Deleted original: 00227.MTS

  ## Processing: 00228.MTS (21.1 MB)
    Creation date: 2024-02-28 15:09:00 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.152 bpp))
frame=  750 fps=252 q=-0.0 Lsize=   10295KiB time=00:00:24.99 bitrate=3374.7kbits/s speed=8.39x elapsed=0:00:02.97
    **Converted: 10.1 MB (52.4% smaller) in 3.0s**
    Deleted original: 00228.MTS

  ## Processing: 00229.MTS (46.7 MB)
    Creation date: 2024-02-28 15:28:26 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.150 bpp))
frame= 1680 fps=259 q=-0.0 Lsize=   18499KiB time=00:00:56.02 bitrate=2705.1kbits/s speed=8.64x elapsed=0:00:06.48
    **Converted: 18.1 MB (61.3% smaller) in 6.6s**
    Deleted original: 00229.MTS

  ## Processing: 00230.MTS (30.9 MB)
    Creation date: 2024-02-28 15:41:23 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.134 bpp))
frame= 1245 fps=257 q=-0.0 Lsize=    7197KiB time=00:00:41.50 bitrate=1420.4kbits/s speed=8.56x elapsed=0:00:04.84
    **Converted: 7.0 MB (77.3% smaller) in 4.9s**
    Deleted original: 00230.MTS

  ## Processing: 00231.MTS (30.6 MB)
    Creation date: 2024-02-28 15:51:24 (from exiftool)
    Encoder: VideoToolbox (normal complexity (0.137 bpp))
frame= 1200 fps=257 q=-0.0 Lsize=    7952KiB time=00:00:40.00 bitrate=1628.3kbits/s speed=8.56x elapsed=0:00:04.67
    **Converted: 7.8 MB (74.6% smaller) in 4.7s**
    Deleted original: 00231.MTS

======================================================================
Summary
======================================================================

  Converted:          462
  Skipped (codec):    0
  Skipped (indexed):  0
  Skipped (exists):   0
  Failed:             0

----------------------------------------
  Encoder Selection:
    libx265 (noisy):      210 files, 15471s video
    VideoToolbox (clean): 252 files, 25859s video

  Estimated conversion time:
    libx265 portion:      413 min
    VideoToolbox portion: 52 min
    Total:                7h 44m

  Complexity (bits-per-pixel):
    Min: 0.124, Median: 0.156, Max: 0.278
    Threshold: 0.17 (above = noisy → libx265)

  Original:   44.03 GB (45091 MB)
  Converted:  18.05 GB (18486 MB)
  Savings:    25.98 GB (59.0%)

  Total time:       6h 50m
