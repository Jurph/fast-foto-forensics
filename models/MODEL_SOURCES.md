# Model Sources

## Current Model-Backed Path

The default CLI path uses filename heuristics for vision. The model-backed path
in the tracked code uses Ollama, both for `--vision-backend ollama` and for the
default Ollama synthesis backend.

## Ollama (recommended local runtime)

The recommended way to run local models for this project is via Ollama. No
manual weight downloads or GPU configuration required; Ollama handles it.

```bash
ollama pull qwen2.5vl:7b
```

The `OllamaVisionBackend` in `src/fast_foto_forensics/vision.py` connects to
the local Ollama server automatically. Install the Python client with:

```bash
uv sync --extra vision_ollama
```

Or standalone:

```bash
pip install ollama>=0.4.0
```

Use Ollama with commands such as:

```bash
uv run --locked --extra dev --extra vision_ollama fast-foto-forensics scan path/to/images --vision-backend ollama
uv run --locked --extra dev --extra search_ddgs --extra vision_ollama fast-foto-forensics run path/to/images --output runs --vision-backend ollama
```

The raw GGUF and Florence-2 notes below are reference material for alternative
runtime experiments. The current CLI does not load those assets directly.

---

Model weights on disk live on `X:\models\fast-foto-forensics\` and are not
checked into git. This section documents where each model came from and how to
re-download it.

## Florence-2-base (Microsoft)

- **HuggingFace ID:** `microsoft/Florence-2-base`
- **Parameters:** 0.23B
- **Disk size:** ~0.9 GB
- **License:** MIT
- **Local path:** `X:\models\fast-foto-forensics\florence-2-base\`
- **Use case:** Fast OCR with bounding-box localization. Supports `<OCR>` and
  `<OCR_WITH_REGION>` task prompts. Runs on CPU. Good as a first-pass text
  detector to find where serial numbers, labels, and markings appear in a
  photo.

Download:

```bash
pip install huggingface_hub
python -c "
from huggingface_hub import snapshot_download
snapshot_download(
    'microsoft/Florence-2-base',
    local_dir='X:/models/fast-foto-forensics/florence-2-base',
    local_dir_use_symlinks=False,
)
"
```

## Qwen2.5-VL-7B-Instruct Q4_K_M (GGUF, via Unsloth)

- **HuggingFace ID:** `unsloth/Qwen2.5-VL-7B-Instruct-GGUF`
- **Original model:** `Qwen/Qwen2.5-VL-7B-Instruct`
- **Parameters:** 7B (4-bit quantized)
- **Disk size:** ~4.7 GB (language) + ~1.4 GB (vision encoder) = ~6.1 GB total
- **License:** Apache 2.0
- **Local path:** `X:\models\fast-foto-forensics\qwen2.5-vl-7b-gguf\`
- **Files needed:**
  - `Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf` (language model)
  - `mmproj-BF16.gguf` (vision encoder / multimodal projector)
- **Use case:** High-accuracy OCR and image understanding. Instruction-tuned,
  so you can prompt it with natural language like "extract all serial numbers
  from this image" and get structured output. Runs via llama.cpp or
  llama-cpp-python.

Download:

```bash
pip install huggingface_hub
python -c "
from huggingface_hub import hf_hub_download
hf_hub_download(
    'unsloth/Qwen2.5-VL-7B-Instruct-GGUF',
    filename='Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf',
    local_dir='X:/models/fast-foto-forensics/qwen2.5-vl-7b-gguf',
    local_dir_use_symlinks=False,
)
hf_hub_download(
    'unsloth/Qwen2.5-VL-7B-Instruct-GGUF',
    filename='mmproj-BF16.gguf',
    local_dir='X:/models/fast-foto-forensics/qwen2.5-vl-7b-gguf',
    local_dir_use_symlinks=False,
)
"
```

## Architecture Note

Today, the codebase uses filename heuristics by default and Ollama/Qwen for the
explicit model-backed path. Florence-2 and standalone GGUF assets remain useful
reference points if the repo grows a non-Ollama backend later.
