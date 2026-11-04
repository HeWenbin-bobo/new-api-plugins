---
name: zaiwen-image-generation
description: Generate new images or edit supplied images through 在问 OneAPI using the gpt-image-2 model. Use when a user asks to create, illustrate, render, or revise images with 在问 API, wants OpenAI-compatible Images API code for 在问, or needs to decode and save its b64_json response.
---

# 在问图片生成

Use the OpenAI-compatible Images API at `https://oneapi.zaiwenai.com/v1`.

## Prerequisites

- Load all runtime connection settings only from `config.local.json` in the directory containing this `SKILL.md`. Never use an environment variable or ask the user to provide, confirm, or configure an API key. Never print, log, include in output, or persist `api_key` elsewhere.
- Copy `config.example.json` to `config.local.json` during local setup. If the file is missing, cannot be parsed, has an empty `api_key`, or still contains `PASTE_YOUR_ZAIWEN_API_KEY_HERE`, stop without making a request and report only that the local 在问 configuration is unavailable.
- Use `config.model` (default `gpt-image-2`) as the model and `config.base_url` as the endpoint.
- Expect one image per call: `n` is currently fixed to `1` and `response_format` is currently fixed to `b64_json`.

Run the following commands from this skill's directory:

```bash
CONFIG="config.local.json"
ZAIWEN_API_KEY=$(python -c "import json;print(json.load(open(r'$CONFIG',encoding='utf-8'))['api_key'])")
BASE_URL=$(python -c "import json;print(json.load(open(r'$CONFIG',encoding='utf-8'))['base_url'].rstrip('/'))")
MODEL=$(python -c "import json;print(json.load(open(r'$CONFIG',encoding='utf-8'))['model'])")
```

## Generate an image

Send `POST /images/generations` with JSON:

```bash
curl "$BASE_URL/images/generations" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ZAIWEN_API_KEY" \
  -d "{
    \"model\": \"$MODEL\",
    \"prompt\": \"<specific image description>\",
    \"n\": 1,
    \"response_format\": \"b64_json\"
  }"
```

Prefer a prompt that names the subject, composition, visual style, lighting, palette, and any required text. Do not claim that size, quality, style, transparency, or URL responses are supported unless the current 在问 documentation confirms them.

## Python

```python
import base64
import json
from pathlib import Path
from openai import OpenAI

config = json.loads(Path("config.local.json").read_text(encoding="utf-8"))

client = OpenAI(
    base_url=config["base_url"].rstrip("/"),
    api_key=config["api_key"],
)

response = client.images.generate(
    model=config.get("model", "gpt-image-2"),
    prompt="<specific image description>",
    n=1,
    response_format="b64_json",
)

image_bytes = base64.b64decode(response.data[0].b64_json)
Path("generated.png").write_bytes(image_bytes)
```

Save the decoded bytes as an image file; `b64_json` is not a public image URL.

## Edit an image

For a supplied local image, send `POST /images/edits` as multipart form data:

```bash
curl "$BASE_URL/images/edits" \
  -H "Authorization: Bearer $ZAIWEN_API_KEY" \
  -F "image=@original.png" \
  -F "model=$MODEL" \
  -F "prompt=<precise edit instruction>" \
  -F "n=1" \
  -F "response_format=b64_json"
```

Use the same Base64 decoding workflow for the response. Preserve the original file and write the result to a distinct output path.

## Response and failure handling

Read the generated content from `response.data[0].b64_json`. The response may also include `created` and token-based `usage` metadata. Report HTTP status and response body safely on failures, but redact authorization values. Treat image generation and editing as billed calls; obtain confirmation before issuing a real request when the user has not explicitly asked to generate or edit an image.
