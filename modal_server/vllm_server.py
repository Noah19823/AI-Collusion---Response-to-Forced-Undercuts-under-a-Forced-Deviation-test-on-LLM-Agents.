"""Serve an open-weight model on Modal with vLLM, behind an OpenAI-compatible API.

The experiment harness talks to it with --provider vllm, using VLLM_BASE_URL
(the URL Modal prints after deploy) and VLLM_API_KEY (the same value stored
in the Modal secret below). vLLM honours per-request seeds, which the harness
uses so the cut and no-cut copies of a fork draw the same samples until the
cut changes what an agent sees.

Deploy:   modal deploy modal_server/vllm_server.py
Stop:     modal app stop collusion-vllm
"""
import modal

MODEL_NAME = "Qwen/Qwen3-32B-FP8"   # change here and in --model if switching models
VLLM_VERSION = "0.30.0"
GPU = "H100"
PORT = 8000
MINUTES = 60

image = (
    modal.Image.from_registry("nvidia/cuda:12.8.1-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .uv_pip_install(f"vllm=={VLLM_VERSION}", "huggingface_hub[hf_transfer]")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

hf_cache = modal.Volume.from_name("collusion-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("collusion-vllm-cache", create_if_missing=True)

app = modal.App("collusion-vllm")


@app.function(
    image=image,
    gpu=GPU,
    # Shut the GPU down after 10 idle minutes so credits aren't burned overnight.
    scaledown_window=10 * MINUTES,
    timeout=24 * 60 * MINUTES,
    max_containers=1,
    volumes={"/root/.cache/huggingface": hf_cache, "/root/.cache/vllm": vllm_cache},
    secrets=[modal.Secret.from_name("collusion-vllm-key")],
)
@modal.concurrent(max_inputs=48)
@modal.web_server(port=PORT, startup_timeout=30 * MINUTES)
def serve():
    import os
    import subprocess

    cmd = [
        "vllm", "serve", MODEL_NAME,
        "--served-model-name", MODEL_NAME,
        "--host", "0.0.0.0",
        "--port", str(PORT),
        "--api-key", os.environ["VLLM_API_KEY"],
        "--max-model-len", "16384",
        "--gpu-memory-utilization", "0.92",
        "--enable-prefix-caching",
    ]
    subprocess.Popen(cmd)
