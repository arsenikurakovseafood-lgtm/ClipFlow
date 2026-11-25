# ClipFlow

ClipFlow is an AI Content Autopilot under development. This milestone implements the CPU clip renderer.

Run the media checks from a Codex Cloud checkout or from GitHub Actions. The cloud image must provide Python 3, FFmpeg, FFprobe, libx264, libass, and DejaVu Sans.

```sh
python3 -m unittest discover -s tests -v
python3 -m clipflow source.mp4 clip.mp4 --start 10 --end 30 --captions captions.json
```

Caption input is a JSON array with `start` and `end` in source-relative seconds and a `text` string on each entry. Use authorized media staged on the cloud worker. The command writes an H.264 MP4 to the cloud filesystem and reports duration, dimensions, and bytes.

See [build status](BUILD_STATUS.md) and [architecture](ARCHITECTURE.md).

## Private owner demo

Run the following in two processes on Codex Cloud, sharing a Cloud-only state directory with mode `0700`.

```sh
python3 -m clipflow.web /workspace/scratch/clipflow-demo/media
python3 -m clipflow.worker /workspace/scratch/clipflow-demo/media
```

The server defaults to Cloud loopback port 3000. For an owner-only hosted preview, first configure port 3000 under Edit Environment → HTTP Previews and apply it to the chat. Once the authenticated gateway is configured, start the web process with `--bind 0.0.0.0 --authenticated-gateway` and use the URL advertised by the environment. This flag assumes the surrounding network restricts access to the authenticated gateway. The demo has no application login and must never be exposed directly.

Choose an authorized MP4, MOV or WebM, enter the clip range and optionally add a caption. Queue the render, then play it in the library. Downloading requires clicking **Download MP4**.
