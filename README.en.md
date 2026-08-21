**English** | [中文](README.md)

# FFmpeg Static Build Repo

This repository builds a pinned FFmpeg revision into static libraries for reuse in prpr/Phira-related projects (for example, the main repo can extract to `prpr-avc/static-lib/<target>`).

FFmpeg source is pinned as the `FFmpeg/` git submodule, and CI checks it out automatically.

## Highlights

- Multi-target builds (targets use Rust-style triples)
- Per-target `./configure` flags, compiler setup, and optimizations
- Pinned x264 builds statically linked into the FFmpeg artifacts
- CI matrix builds for each target
- Unified `{target}.tar.gz` artifacts uploaded to Release

## Quick Start

1. To update FFmpeg, move the `FFmpeg` submodule to a new commit
2. Adjust common options in `config/ffmpeg.toml`
3. Configure targets in `config/targets.toml`
4. If you want a local build, initialize the submodule first:

```bash
git submodule update --init FFmpeg
```

5. Build:

```bash
python3 scripts/build-ffmpeg.py <target>
```

Artifacts are written to `dist/<target>.tar.gz`.

## Artifact Layout

Default layout is a flat list of static libraries (`package_layout = "flat"`):

- `libavcodec.a`
- `libx264.a`
- `libavformat.a`
- `libavutil.a`
- `libswresample.a`
- `libswscale.a`

If you need `<target>/lib*.a`, set `package_layout` to `target-dir` in `config/ffmpeg.toml`.

## CI and Releases

- Only targets with `enabled = true` in `config/targets.toml` enter the matrix
- CI checkout automatically initializes the `FFmpeg` submodule
- Pushing any tag triggers builds and uploads `{target}.tar.gz` to the Release

## Requirements

- Python 3.11+ (for TOML support)
- Linux targets need `gcc/g++`, `make`, `pkg-config`, `nasm`, `yasm`, `libvorbis-dev`
- macOS targets need `brew install pkg-config libvorbis`
- macOS/iOS targets require Xcode (Command Line Tools) with `xcrun` available
- iOS targets disable `libvorbis` by default (built-in Vorbis decoder only); enable it only if you provide an iOS libvorbis build
- iOS targets use Xcode SDK paths by default; update `IOS_SDK` / `IOS_SIM_SDK` if needed
- HarmonyOS targets require the OpenHarmony SDK; set `OHOS_SDK` if needed
