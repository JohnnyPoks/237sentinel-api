# Demo samples

Sample inputs so a demo never depends on a live upload working first time. Text
samples are ready to paste; for binary modalities (image/audio/video/pdf), drop
your own test files here with the names below and they will be picked up by the
demo script.

| File | Modality | Expected reading |
|---|---|---|
| `scam_momo_fr.txt` | text | UNCONFIRMED — financial request + urgency + PIN loop pattern |
| `scam_scholarship_en.txt` | text | UNCONFIRMED — advance-fee + identity claim (MINESEC) |
| `legit_gov_link.txt` | link | VERIFIED — matches a seeded official domain |
| `typosquat_link.txt` | link | UNCONFIRMED / risk — look-alike domain |
| `forged_communique.pdf` | document | *(add your own)* — tests OCR + embedded-image ELA |
| `voice_note.ogg` | audio | *(add your own)* — tests transcription + synthesis check |

## Quick demo

```bash
# text
curl -s localhost:7860/api/v1/analyze -H 'Content-Type: application/json' \
  -d "{\"text\": \"$(tr -d '\n' < demo/scam_momo_fr.txt)\"}" | python -m json.tool

# a file
curl -s localhost:7860/api/v1/analyze -F 'file=@demo/forged_communique.pdf'
```
