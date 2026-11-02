"""GPU side of Claimdesk on Modal: LoRA fine-tuning and an OpenAI-compatible vLLM server.

    uv run modal run modal_app.py::finetune --run v1          # train adapter v1 on the train split, returns losses
    uv run modal deploy modal_app.py                          # serve base model + every adapter in the volume

The server registers each trained adapter as its own model name (claimdesk-v1, claimdesk-v2, ...), so the canary router
switches versions by name, without a redeploy. It scales to zero when idle.
"""

import json
import os
import subprocess
from pathlib import Path

import modal

BASE = "Qwen/Qwen3-4B-Instruct-2507"  # Apache-2.0, multilingual (incl. Hungarian), no thinking mode
VOL = Path("/vol")
app = modal.App("claimdesk")
volume = modal.Volume.from_name("claimdesk", create_if_missing=True)
env = {"HF_HOME": "/vol/hf", "HF_XET_HIGH_PERFORMANCE": "1"}

train_image = (modal.Image.debian_slim(python_version="3.12")
               .uv_pip_install("torch==2.15.0", "transformers==5.22.1", "trl==1.17.1", "peft==0.21.2", "accelerate==1.15.0",
                               "datasets==5.1.0")
               .env(env))
vllm_image = (modal.Image.debian_slim(python_version="3.12").uv_pip_install("vllm==0.33.0")
              .env(env | {"VLLM_USE_FLASHINFER_SAMPLER": "0"}))  # its JIT sampler needs nvcc, which a slim image lacks


@app.function(image=train_image, gpu="L40S", volumes={VOL: volume}, timeout=3 * 3600)
def train(rows: list[dict], run: str, epochs: float = 2, lr: float = 2e-4, rank: int = 16) -> dict:
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    out = VOL / "adapters" / run
    args = SFTConfig(output_dir=f"/tmp/{run}", num_train_epochs=epochs, learning_rate=lr, lr_scheduler_type="cosine", warmup_steps=0.05,
                     per_device_train_batch_size=4, gradient_accumulation_steps=4, max_length=3072, bf16=True, logging_steps=10,
                     eval_strategy="epoch", save_strategy="no", report_to=[], gradient_checkpointing=True)  # before the 8 GB download
    tok = AutoTokenizer.from_pretrained(BASE)
    model = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16)
    train_ds = Dataset.from_list([r for r in rows if r["split"] == "train"]).remove_columns("split")
    val_ds = Dataset.from_list([r for r in rows if r["split"] == "val"]).remove_columns("split")
    lora = LoraConfig(r=rank, lora_alpha=2 * rank, lora_dropout=0.05, target_modules="all-linear", task_type="CAUSAL_LM")
    trainer = SFTTrainer(model=model, args=args, train_dataset=train_ds, eval_dataset=val_ds, processing_class=tok, peft_config=lora)
    result = trainer.train()
    trainer.model.save_pretrained(out)  # adapter only (~tens of MB); the base stays shared
    tok.save_pretrained(out)
    metrics = {"train_loss": result.training_loss, "eval_loss": trainer.evaluate()["eval_loss"], "train_docs": len(train_ds),
               "val_docs": len(val_ds), "runtime_s": result.metrics["train_runtime"]}
    (out / "train_metrics.json").write_text(json.dumps(metrics | {"base": BASE, "epochs": epochs, "lr": lr, "rank": rank}))
    volume.commit()
    return metrics


@app.function(image=vllm_image, gpu=["L4", "A10G", "L40S"], volumes={VOL: volume}, scaledown_window=300, timeout=24 * 3600,
              secrets=[modal.Secret.from_name("claimdesk-vllm")])
@modal.concurrent(max_inputs=64)
@modal.web_server(port=8000, startup_timeout=900)
def serve() -> None:
    volume.reload()
    adapters = sorted(p.name for p in (VOL / "adapters").iterdir()) if (VOL / "adapters").exists() else []
    cmd = ["vllm", "serve", BASE, "--served-model-name", "qwen3-4b", "--host", "0.0.0.0", "--port", "8000",
           "--max-model-len", "4096", "--gpu-memory-utilization", "0.9", "--api-key", os.environ["VLLM_API_KEY"]]
    if adapters:
        cmd += ["--enable-lora", "--max-lora-rank", "64", "--lora-modules",
                *[f"claimdesk-{a}={VOL / 'adapters' / a}" for a in adapters]]
    subprocess.Popen(cmd)


@app.local_entrypoint()
def finetune(run: str, epochs: float = 2, lr: float = 2e-4, rank: int = 16) -> None:
    """Build supervised pairs from the corpus (prompt = the same short instruction the server gets) and train remotely."""
    from claimdesk import dataset, extract
    from claimdesk.schemas import SCHEMAS

    rows = [{"split": r["split"],
             "prompt": [{"role": "system", "content": extract.system_prompt(r["type"], short=True)}, {"role": "user", "content": r["text"]}],
             "completion": [{"role": "assistant", "content": json.dumps(SCHEMAS[r["type"]].model_validate(r["fields"]).model_dump(),
                                                                        ensure_ascii=False)}]}
            for r in dataset.load() if r["split"] in ("train", "val")]
    print(f"training {run} on {sum(r['split'] == 'train' for r in rows)} docs …")
    metrics = train.remote(rows, run, epochs, lr, rank)
    print(json.dumps(metrics, indent=1))
    register(run, metrics, {"base": BASE, "epochs": epochs, "lr": lr, "rank": rank})


def register(run: str, metrics: dict, params: dict) -> None:
    """MLflow registry entry for the adapter: the weights stay on the Modal volume, the registry holds lineage and metrics."""
    import mlflow
    from mlflow import MlflowClient

    from claimdesk.config import settings

    mlflow.set_tracking_uri(settings().mlflow_tracking_uri)
    mlflow.set_experiment("finetune")
    with mlflow.start_run(run_name=f"lora-{run}") as r:
        mlflow.log_params(params | {"run": run})
        mlflow.log_metrics(metrics)
        mlflow.log_text(f"modal-volume://claimdesk/adapters/{run}\nserved as claimdesk-{run}\n", "adapter/uri.txt")
    client = MlflowClient()
    if not client.search_registered_models("name = 'claimdesk-extractor'"):
        client.create_registered_model("claimdesk-extractor", description=f"LoRA adapters on {BASE} for claim document extraction")
    v = client.create_model_version("claimdesk-extractor", source=f"{r.info.artifact_uri}/adapter", run_id=r.info.run_id,
                                    tags={"served_as": f"claimdesk-{run}"})
    client.set_registered_model_alias("claimdesk-extractor", "candidate", v.version)
    print(f"registered claimdesk-extractor v{v.version} (alias: candidate)")
