# Models — real benchmarks and honest limits

This file is a **credibility asset**. Published accuracies below were measured on
clean, curated datasets. They **do not transfer** to WhatsApp-quality audio
recorded in a noisy market, screenshots re-compressed five times, or documents
photographed at an angle. In the field, accuracy is unknown and will be lower.
That is why 237Sentinel reports confidence **bands** and says *"we cannot
confirm"* rather than a percentage — and why a registry match, not a classifier
score, is what earns a VERIFIED verdict.

All model IDs are pinned in `app/config.py::Models`. None were invented; each was
verified to resolve on the Hugging Face Hub.

| Modality | Model ID | Type / size | Published figure (lab) | Honest limitation |
|---|---|---|---|---|
| Link | `CrabInHoney/urlbert-tiny-v4-malicious-url-classifier` | tiny BERT, ~15 MB, 4-class | High on curated URL sets | URL strings age fast; new phishing domains look benign until reported. Paired with WHOIS age + typosquatting. |
| Link (fallback) | `CrabInHoney/urlbert-tiny-v4-phishing-classifier` | binary, ~15 MB | — | Binary only. |
| Text | `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` | zero-shot NLI, multilingual, ~560 MB | Strong XNLI zero-shot | EN/FR only here. **No Pidgin/Camfranglais.** Zero-shot label scores are soft evidence, not proof. |
| Image | `Wvolf/ViT_Deepfake_Detection` | ViT-base | ~high on FaceForensics-style data | Trained on face deepfakes; weak on document forgery and non-face synthesis. ELA and OCR complement it. |
| Image (alt) | `prithivMLmods/deepfake-detector-model-v1` | SigLIP-base | — | Alternate backbone. |
| Audio | `MelodyMachine/Deepfake-audio-detection-V2` | wav2vec2, 94.6M, Apache-2.0 | ~94.6% (reported) | Lab figure on clean audio. Market noise, codec artefacts and short clips degrade it sharply. |
| Audio (fallback) | `mo-thecreator/Deepfake-audio-detection` | wav2vec2, Apache-2.0 | — | Fallback. |
| Transcription | `faster-whisper` `base` | ASR | — | `base`, not `large` (memory). Accented / code-switched speech and heavy noise reduce transcript quality, which then weakens the downstream text read. |

## Error Level Analysis (ELA)

ELA is **not a model** and **not a headline**. It resaves an image at 95% JPEG,
diffs, and looks for localized compression spikes (a pasted stamp compresses
differently from the page it sits on). It is genuinely useful for the
forged-communiqué case, but it is **unreliable alone** on modern re-encoded
images — every social-media image is already re-compressed, which muddies the
signal. Accordingly:

- ELA is weighted at `0.35` vs `0.65` for the deep-learning classifiers.
- A lone high ELA reading **can never** produce an ALTERED verdict; it needs a
  corroborating forensic signal. This is enforced in `services/verification.py`
  and covered by a unit test.

## The registry beats the classifier

The most reliable positive signal is not any model — it is a match against a
known official channel. "VERIFIED" is earned by a registry match plus the absence
of strong manipulation, not by a high model score. Classifier scores mainly help
distinguish UNCONFIRMED from ALTERED.
