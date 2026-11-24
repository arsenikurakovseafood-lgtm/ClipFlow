# ClipFlow

ClipFlow is an AI Content Autopilot under development. This milestone implements the CPU clip renderer.

Run the media checks from a Codex Cloud checkout or from GitHub Actions. The cloud image must provide Python 3, FFmpeg, FFprobe, libx264, libass, and DejaVu Sans.

```sh
python3 -m unittest discover -s tests -v
python3 -m clipflow source.mp4 clip.mp4 --start 10 --end 30 --captions captions.json
```

Caption input is a JSON array with `start` and `end` in source-relative seconds and a `text` string on each entry. Use authorized media staged on the cloud worker. The command writes an H.264 MP4 to the cloud filesystem and reports duration, dimensions, and bytes.

See [build status](BUILD_STATUS.md) and [architecture](ARCHITECTURE.md).
