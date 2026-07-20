# BalanceDocket voice-over recording guide

Record the eight numbered sections in `balancedocket_voiceover.txt` as separate
takes. The picture is already locked to 2 minutes 52 seconds; do not rush to
fill every frame. A calm, clear controller walkthrough is better than an
advertising read.

## Before recording

- Record in a quiet, soft-furnished room. Put the microphone 15–20 cm from your
  mouth and slightly off-axis so breath noise does not hit it directly.
- Prefer mono 48 kHz WAV, 24-bit if your recorder offers it. M4A is acceptable
  if WAV is unavailable; keep the original file and it can be converted later.
- Turn off music, automatic voice effects, aggressive noise reduction, and
  artificial reverb. Aim for peaks between -12 and -6 dBFS.
- Leave 250–500 ms of room tone before and after every take. If you make a
  mistake, pause, restart the sentence, and keep recording rather than cutting
  mid-word.

## Delivery targets

| File | Picture window | Target read |
| --- | --- | --- |
| `01_problem.wav` | 0:00–0:15 | 15 seconds |
| `02_baseline.wav` | 0:15–0:34 | 19 seconds |
| `03_controls.wav` | 0:34–1:02 | 28 seconds |
| `04_codex.wav` | 1:02–1:36 | 34 seconds |
| `05_advisory.wav` | 1:36–2:00 | 24 seconds |
| `06_decision.wav` | 2:00–2:25 | 25 seconds |
| `07_workpaper.wav` | 2:25–2:42 | 17 seconds |
| `08_close.wav` | 2:42–2:52 | 10 seconds |

It is fine to finish roughly half a second early. Do not speed up a take to
make it fit; record a clean natural version and the captions will be aligned to
your real delivery.

## Pronunciation notes

- BalanceDocket: “BAL-ance dock-it”
- Codex: “CODE-ex”
- GPT-5.6: “G-P-T five point six”
- GPT-5.6 Sol: “G-P-T five point six sol”
- API: “A-P-I”
- ERP: “E-R-P”

## Performance notes

- Section 1: measured and problem-focused.
- Sections 2–4: precise, with a small pause after “without an API key.”
- Sections 5–7: emphasize the safety boundary and human authority.
- Section 8: warm and confident, without becoming promotional.

Send the eight original takes without mastering them. The final edit will use
short fades, light cleanup only where necessary, approximately -16 LUFS
integrated loudness, and a true peak no higher than -1 dBTP.

## Verified assembly path

From the repository root, validate the original takes and build one
timeline-aligned Final Cut track:

```bash
voice_dir="$HOME/Movies/BalanceDocket Build Week 2026 Media/Voiceover"
python3 scripts/verify_balancedocket_voiceover.py "$voice_dir"
python3 scripts/build_balancedocket_voiceover_track.py \
  "$voice_dir" \
  "$voice_dir/BalanceDocket_voiceover_track.wav"
```

The builder never changes the original takes and refuses to replace an existing
output unless `--force` is explicit. It rejects missing, invalid, silent,
clipped, or over-window takes; accepts verified 16-bit and 24-bit PCM WAV,
including `WAVE_FORMAT_EXTENSIBLE`; places the takes at 0:00, 0:15, 0:34,
1:02, 1:36, 2:00, 2:25, and 2:42; applies short edge fades; and performs
two-pass normalization. The resulting 172.005167-second, 48 kHz mono 24-bit
WAV must pass the built-in -18 to -14 LUFS and -1 dBTP release bounds before it
is written. Import it at `00:00:00:00`, then align captions to the actual words
and listen through the complete timeline before export.
