# Missing API Endpoints in AISBF

This document lists all API endpoints that are **not yet exposed** but could be added in the future. Endpoints are categorized by modality and priority.

---

## 📋 Legend

- **🟡 Partial** – Capability exists in code (e.g., `_detect_capabilities()` detects it, or provider has support) but no public endpoint
- **🔴 Missing** – No implementation at all, but conceptually useful
- **✅ Priority** – High demand / core functionality worth adding soon

---

## 🎯 Core Missing Endpoints (High Priority)

| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /api/v1/images/edits` | 🟡 | Image-to-image (i2i) detected in capabilities; DALL-E and Stable Diffusion support img2img |
| `POST /api/v1/images/variations` | 🔴 | Image variations standard endpoint (OpenAI-compatible) |
| `POST /api/v1/video/generations` | 🟡 | Text-to-video (t2v) detected; Sora, Runway, Pika keywords present |
| `POST /api/v1/video/animations` | 🟡 | Image-to-video (i2v) detected; Runway, Pika support img2video |
| `POST /api/v1/video/edits` | 🟡 | Video-to-video editing (v2v) detected; Runway video-edit |
| `POST /api/v1/video/descriptions` | 🟡 | Video-to-text (v2t) detected; Video-LLaMA, video-chat |
| `POST /api/v1/video/transcriptions` | 🟡 | Video → subtitles/transcript (combines video + audio transcription logic) |
| `POST /api/v1/video/upscale` | 🔴 | Video upscaling/enhancement (no detection yet) |
| `POST /api/v1/audio/generations` | 🟡 | Audio-to-audio (a2a) detected; MusicGen, Riffusion |
| `POST /api/v1/moderations` | 🔴 | Content moderation (OpenAI-compatible standard endpoint) |

---

## 🖼️ Image-Related

| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /api/v1/images/upscale` | 🔴 | Image upscaling enhancement (ESRGAN, Real-ESRGAN, etc.) |
| `POST /api/v1/images/inpaint` | 🟡 | Inpainting (partial image editing) – Stable Diffusion supports |
| `POST /api/v1/images/outpaint` | 🔴 | Outpainting (extend image borders) |
| `POST /api/v1/images/caption` | 🟡 | Image captioning detected (BLIP, GIT) |
| `POST /api/v1/images/detect` | 🟡 | Object detection (YOLO, R-CNN, DETR detected) |
| `POST /api/v1/images/segment` | 🟡 | Segmentation (SAM, mask detected) |
| `POST /api/v1/images/restore` | 🔴 | Image restoration / denoising / deblurring |
| `POST /api/v1/images/colorize` | 🔴 | Image colorization (B&W → color) |
| `POST /api/v1/images/style-transfer` | 🔴 | Artistic style transfer |
| `POST /api/v1/images/remove-bg` | 🔴 | Background removal |

---

## 🎵 Audio-Related

| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /api/v1/audio/identify` | 🔴 | Music/song identification (Shazam-like) |
| `POST /api/v1/audio/split` | 🔴 | Source separation (vocals vs. instruments) |
| `POST /api/v1/audio/denoise` | 🔴 | Audio denoising / enhancement |
| `POST /api/v1/audio/label` | 🔴 | Audio event tagging / scene detection |
| `POST /api/v1/audio/diarize` | 🔴 | Speaker diarization (who spoke when) |
| `POST /api/v1/audio/translate` | 🔴 | Speech-to-speech translation |

---

## 📝 Text/NLP Tasks

| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /api/v1/translate` | 🟡 | Translation detected (m2m, NLLB models) |
| `POST /api/v1/summarize` | 🟡 | Summarization detected (BART, PEGASUS) |
| `POST /api/v1/classify` | 🟡 | Text classification detected (BERT, RoBERTa) |
| `POST /api/v1/sentiment` | 🟡 | Sentiment analysis detected |
| `POST /api/v1/ner` | 🟡 | Named Entity Recognition detected (SpaCy, NER models) |
| `POST /api/v1/answers` | 🟡 | Question answering detected (SQuAD, QA models) |
| `POST /api/v1/embeddings` | ✅ | **Already exposed** |
| `POST /api/v1/reasoning` | 🟡 | Chain-of-thought reasoning detected (o1, o3 models) |
| `POST /api/v1/search` | 🟡 | Search/RAG detected |
| `POST /api/v1/complete` | ✅ | **Already exposed** (legacy completions) |
| `POST /api/v1/chat/completions` | ✅ | **Already exposed** |
| `POST /api/v1/tools` | 🔴 | Generic tool calling without chat context |
| `POST /api/v1/function-call` | 🔴 | Standalone function invocation |
| `POST /api/v1/parse` | 🔴 | Structured data extraction from text |

---

## 🔢 Numerical/Code Tasks

| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /api/v1/code/generate` | 🟡 | Code generation detected (Codex, StarCoder, CodeLlama, DeepSeek-Coder) |
| `POST /api/v1/code/complete` | 🟡 | Code completion detected |
| `POST /api/v1/code/explain` | 🔴 | Code explanation / docstring generation |
| `POST /api/v1/code/refactor` | 🔴 | Code refactoring |
| `POST /api/v1/code/review` | 🔴 | Code review / bug detection |
| `POST /api/v1/code/test` | 🔴 | Unit test generation |
| `POST /api/v1/math` | 🔴 | Mathematical problem solving (dedicated) |
| `POST /api/v1/reason` | 🔴 | Dedicated reasoning endpoint (separate from chat) |

---

## 🎨 Multimodal / Vision

| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /api/v1/vision/describe` | 🟡 | Vision/image understanding detected (GPT-4V, Claude 3, Gemini 1.5+, LLaVA, BLIP) |
| `POST /api/v1/vision/ocr` | 🟡 | OCR detected (Tesseract, PaddleOCR, EasyOCR) |
| `POST /api/v1/vision/analyze` | 🔴 | Comprehensive image analysis (objects, text, scene) |
| `POST /api/v1/vision/detect` | 🟡 | Already detected as object detection |
| `POST /api/v1/depth` | 🔴 | Depth estimation from image |
| `POST /api/v1/pose` | 🔴 | Human pose estimation |

---

## 🎬 3D & Advanced

| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /api/v1/3d/generate` | 🟡 | 3D generation detected (NeRF, Gaussian Splatting, mesh) |
| `POST /api/v1/3d/convert` | 🔴 | 2D image → 3D conversion |
| `POST /api/v1/animate` | 🟡 | Animation generation detected (motion, pose) |
| `POST /api/v1/avatar` | 🔴 | Talking avatar generation (lip-sync) |
| `POST /api/v1/face-swap` | 🔴 | Face swapping / deepfake |
| `POST /api/v1/face-restore` | 🔴 | Face restoration / enhancement |

---

## 🔧 Configuration & Management

| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /api/v1/fine-tunes` | 🔴 | List fine-tuning jobs |
| `POST /api/v1/fine-tunes` | 🔴 | Create fine-tuning job |
| `GET /api/v1/fine-tunes/{id}` | 🔴 | Get fine-tuning job status |
| `POST /api/v1/fine-tunes/{id}/cancel` | 🔴 | Cancel fine-tuning |
| `GET /api/v1/files` | 🔴 | List uploaded files |
| `POST /api/v1/files` | 🔴 | Upload file for fine-tuning / assistant |
| `DELETE /api/v1/files/{id}` | 🔴 | Delete file |
| `GET /api/v1/assistants` | 🔴 | List assistants (OpenAI Assistants API) |
| `POST /api/v1/assistants` | 🔴 | Create assistant |
| `DELETE /api/v1/assistants/{id}` | 🔴 | Delete assistant |
| `GET /api/v1/threads` | 🔴 | List threads |
| `POST /api/v1/threads` | 🔴 | Create thread |
| `POST /api/v1/threads/{id}/runs` | 🔴 | Create run (assistant execution) |
| `GET /api/v1/vector-stores` | 🔴 | List vector stores (RAG) |
| `POST /api/v1/vector-stores` | 🔴 | Create vector store |
| `POST /api/v1/batch` | 🔴 | Batch API requests |
| `GET /api/v1/batch/{id}` | 🔴 | Get batch status |

---

## 📊 Analytics & Monitoring

| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /api/v1/usage` | 🔴 | Get usage statistics |
| `GET /api/v1/usage/costs` | 🔴 | Get cost breakdown |
| `GET /api/v1/providers/health` | 🔴 | Provider health status |
| `GET /api/v1/cache/stats` | 🔴 | Cache hit/miss statistics |

---

## 🔄 Streaming Variants

All non-streaming endpoints should ideally have streaming equivalents:

| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /api/v1/images/generations` | ✅ | Already non-streaming; consider streaming for progressive generation |
| `POST /api/v1/audio/transcriptions` | ✅ | Streaming file upload; response is non-streaming |
| `POST /api/v1/video/generations` | 🔴 | Streaming would be valuable for long video generation |
| `POST /api/v1/translate` | 🔴 | Streaming translation for long texts |
| `POST /api/v1/summarize` | 🔴 | Streaming summary generation |

---

## 🏷️ Standard Compatibility

These follow OpenAI / Anthropic / industry standard endpoint patterns:

| Endpoint | Standard | Notes |
|----------|----------|-------|
| `POST /api/v1/images/edits` | OpenAI | OpenAIs `images/edits` endpoint for inpainting/variations |
| `POST /api/v1/images/variations` | OpenAI | OpenAI's `images/variations` for similar images |
| `POST /api/v1/audio/translations` | OpenAI | Speech translation (not just transcription) |
| `POST /api/v1/moderations` | OpenAI | Content moderation endpoint |
| `POST /api/v1/engines/{engine}/embeddings` | Legacy | Legacy embeddings format (before v1) |
| `POST /api/v1/answers` | Legacy | Legacy answers endpoint (deprecated but sometimes used) |
| `POST /api/v1/search` | Legacy | Legacy search endpoint |

---

## 📱 MCP Tools (Already Available via MCP)

These exist as **MCP tools** already (in `aisbf/mcp.py`) but could also be HTTP endpoints:

| MCP Tool | Possible HTTP Endpoint | Status |
|----------|----------------------|--------|
| `chat_completion` | Already via `/api/.../chat/completions` | ✅ |
| `list_models` | `/api/v1/models` | ✅ |
| `list_rotations` | `/api/rotations` | ✅ (partial) |
| `list_autoselect` | `/api/autoselect` | ✅ (partial) |
| `get_autoselect_config` | `/api/autoselect/{id}` | 🔴 |
| `get_rotation_config` | `/api/rotations/{id}` | 🔴 |
| `get_providers_config` | `/api/providers` | 🔴 (admin only) |
| `set_provider_config` | `PUT /api/providers/{id}` | 🔴 |
| `set_rotation_config` | `PUT /api/rotations/{id}` | 🔴 |
| `set_autoselect_config` | `PUT /api/autoselect/{id}` | 🔴 |

**Note:** MCP already provides these via `/mcp` SSE and `/mcp/tools/call` POST endpoints.

---

## 🗺️ Proposed Implementation Roadmap

### Phase 1 – Core Gaps (Week 1-2)
1. `POST /api/v1/images/edits` – Image editing (img2img)
2. `POST /api/v1/moderations` – Content safety
3. `POST /api/v1/translate` – Text translation
4. `POST /api/v1/summarize` – Text summarization

### Phase 2 – Video Foundation (Week 3-4)
5. `POST /api/v1/video/generations` – Text-to-video
6. `POST /api/v1/video/descriptions` – Video transcription for subtitles
7. `POST /api/v1/video/edits` – Video editing (basic)
8. `POST /api/v1/video/upscale` – Video upscaling

### Phase 3 – Multimodal Expansion (Week 5-6)
9. `POST /api/v1/audio/generations` – Music/audio generation
10. `POST /api/v1/vision/describe` – Detailed image analysis
11. `POST /api/v1/ocr` – Optical character recognition
12. `POST /api/v1/images/caption` – Image captioning

### Phase 4 – NLP Tasks (Week 7-8)
13. `POST /api/v1/classify` – Text classification
14. `POST /api/v1/sentiment` – Sentiment analysis
15. `POST /api/v1/ner` – Named entity recognition
16. `POST /api/v1/answers` – Q&A

### Phase 5 – Advanced (Future)
17. `POST /api/v1/3d/generate` – 3D model generation
18. `POST /api/v1/animate` – Animation
19. `POST /api/v1/vision/depth` – Depth estimation
20. Full OpenAI Assistants API compatibility

---

## 🎯 Quick Wins (Low Effort, High Value)

These are easy to add by routing to existing chat/completions with proper prompt engineering:

| Endpoint | Implementation |
|----------|----------------|
| `POST /api/v1/translate` | Use chat with system prompt: "Translate the following text to {target_lang}..." |
| `POST /api/v1/summarize` | Use chat with system prompt: "Summarize the following text..." |
| `POST /api/v1/classify` | Use chat with system prompt + list of classes |
| `POST /api/v1/sentiment` | Use chat with sentiment analysis prompt |
| `POST /api/v1/ner` | Use chat with NER extraction prompt |

These can reuse the existing `handle_chat_completion` infrastructure with auto-generated system prompts, requiring only new route definitions and thin wrappers.

---

## 📝 Notes

- All new endpoints should follow the existing pattern:
  1. Parse model as `provider/model` format
  2. Support rotations (`rotation/{name}`) and autoselect (`autoselect/{name}`)
  3. Validate kiro credentials
  4. Delegate to appropriate `handler.handle_*()` method
  5. Return OpenAI-compatible responses where applicable
- Streaming support should be considered for long-running generations (video, long summaries, etc.)
- MCP tools already expose many config management functions; HTTP endpoints for those are optional and likely admin-only.
