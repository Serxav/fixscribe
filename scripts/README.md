# Scripts

Run them from the repository root with `.venv/bin/python`.

| Script | What it does | Meta calls |
|---|---|---|
| `run_video.py samples/<name>.mp4` | Runs the whole pipeline on one local video and prints the job id and its cost; scores it if `samples/<name>.expected.json` exists | yes |
| `demo_job.py` | Builds a guide with the real pipeline and a fake Meta client, to try the web app with no key | no |
| `pack_demo.py data/jobs/<id>` (`python -m scripts.pack_demo`) | Copies a finished job into `demo/<id>` as the read-only sample guide, leaving out the original upload and private files, and shrinks a video GitHub would refuse | no |
| `get_voice.py` (`python -m scripts.get_voice`) | Downloads Meta's open MMS-TTS English voice (CC-BY-NC 4.0) for the film and the coach | no |
| `review_profiles.py list` | Lists the new words the learn stage suggests for the domain profiles, and applies the ones you accept | no |
| `make_photos.py` | Makes the landing photos with Meta models and marks them with the real pipeline | yes |
| `draw_art.py`, `draw_live.py`, `draw_mosaic.py`, `draw_screens.py` | Draw the landing's illustrations from the photos and their real marks | no |
