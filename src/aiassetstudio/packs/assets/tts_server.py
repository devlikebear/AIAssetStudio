"""The speech pack's server. Runs in the pack's own Python, so it imports nothing from aiassetstudio.

The backend starts it for narration jobs and ends it when the GPU is wanted elsewhere. It has no login, so it listens on
this PC only and answers only its own host names. Closing stdin ends it: if the backend dies, nothing keeps the speech
model on the GPU.
"""

import argparse
import os
import sys
import threading
import time
from contextlib import asynccontextmanager

import numpy as np
import soundfile as sf
import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel
from qwen_tts import Qwen3TTSModel

HOST = "127.0.0.1"


class Speak(BaseModel):
    text: str
    speaker: str
    instruct: str
    language: str
    seed: int
    out_path: str  # the WAV to write; the backend owns the folder


def end_with_parent() -> None:
    sys.stdin.buffer.read()
    os._exit(0)


def create_app(model_dir: str) -> FastAPI:
    state: dict = {"model": None}
    generating = threading.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        def load() -> None:
            state["model"] = Qwen3TTSModel.from_pretrained(
                model_dir, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa"
            )

        threading.Thread(target=load, daemon=True).start()
        yield

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[HOST, "localhost"])

    @app.get("/health")
    def health() -> dict:
        return {"ready": state["model"] is not None}

    @app.post("/speak")
    def speak(body: Speak) -> dict:
        model = state["model"]
        if model is None:
            raise HTTPException(503, "the model is still loading")
        with generating:
            torch.manual_seed(body.seed)
            torch.cuda.reset_peak_memory_stats()
            started = time.monotonic()
            wavs, rate = model.generate_custom_voice(
                text=body.text, language=body.language, speaker=body.speaker, instruct=body.instruct
            )
            took = time.monotonic() - started
            wav = np.asarray(wavs[0])
            sf.write(body.out_path, wav, rate, subtype="PCM_16")
            return {
                "duration_s": round(len(wav) / rate, 3),
                "sample_rate": rate,
                "generate_s": round(took, 2),
                "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
            }

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    threading.Thread(target=end_with_parent, daemon=True).start()
    uvicorn.run(create_app(args.model), host=HOST, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
