# Evaluation

Every answer key here was written by eye, before the code it scores was tuned. Run each exam from
the repository root. Exams marked "no" score saved answers and cost nothing.

| Exam | Command | Key | Meta calls |
|---|---|---|---|
| Parts and fasteners on 20 photos | `python -m eval.detect_score` | `detect_key.json` | no |
| Fasteners in a real furniture video | `python -m eval.video_score` | `video_key.json` | no |
| The right part on a real phone repair | `python -m eval.part_exam data/jobs/<id> eval/part_key_iphone.json` | `part_key_iphone.json` | only with `--real` |
| A guide's steps and screw counts | `python -m eval.score <guide.json> <expected.json>` | `samples/*.expected.json` | no |
| Whole pipeline on every labelled video | `python -m eval.run_eval --reuse` (or `--confirm-spend`) | `samples/*.expected.json` | only with `--confirm-spend` |
| The Muse Wonder agent | `python -m eval.agent_exam <job_dir> <key.json>` | per job | no |
| The live coach, a frame every 4 s | `python -m eval.coach_exam <video> --real --walk` | `coach_key.json` | yes |
| Close look / live walk on a copy of a job | `python -m eval.close_look …`, `python -m eval.live_trial …` | — | only with `--real` |

The results are in the main [README](../README.md#evaluation).
