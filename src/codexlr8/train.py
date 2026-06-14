"""TSDAE fine-tuning — adapt an embedding model to a codebase."""

from __future__ import annotations

import os
import random
import time

from .scanner import scan_project
from .config import load_config


def _check_training_deps():
    """Lazy-import training deps. Raises ImportError if missing."""
    try:
        from sentence_transformers import SentenceTransformer, InputExample, losses
        from torch.utils.data import DataLoader  # noqa: F401
        return SentenceTransformer, InputExample, losses
    except ImportError:
        raise ImportError(
            "Training requires 'pip install codexlr8[embeddings]' "
            "(installs sentence-transformers + torch)"
        )


def _corrupt_text(text: str, ratio: float = 0.3) -> str:
    """Randomly mask tokens for TSDAE training."""
    tokens = text.split()
    if len(tokens) < 4:
        return text  # too short to corrupt
    n_mask = max(1, int(len(tokens) * ratio))
    positions = random.sample(range(len(tokens)), n_mask)
    for p in positions:
        tokens[p] = "[MASK]"
    return " ".join(tokens)


def _collect_texts(project_path: str) -> list[str]:
    """Collect file content texts for training. Combines path + summary + content."""
    config = load_config(project_path)
    files_data = scan_project(
        project_path,
        extensions=config.get("extensions"),
        ignore_dirs=config.get("ignore_dirs"),
        include=config.get("include"),
        exclude=config.get("exclude"),
    )
    texts = []
    for entry in files_data:
        text = f"{entry['path']} {entry['content'][:2000]}"
        texts.append(text)
    return texts


def recommend_model(project_path: str) -> dict:
    """Analyze codebase size and suggest the best model for fine-tuning.

    Returns: {model, param_count, estimated_train_time, quality_gain}
    """
    texts = _collect_texts(project_path)
    total_chars = sum(len(t) for t in texts)
    num_files = len(texts)

    # Heuristic: total tokens ≈ total_chars / 4 (avg 4 chars per token)
    est_tokens = total_chars // 4

    suggestion = {
        "num_files": num_files,
        "est_tokens": est_tokens,
        "model": "all-MiniLM-L6-v2",
        "param_count": "23M",
    }

    if est_tokens > 2_000_000:
        suggestion["model"] = "all-mpnet-base-v2"
        suggestion["param_count"] = "110M"
        suggestion["quality_gain"] = "+10-18% MRR"
    elif est_tokens > 500_000:
        suggestion["model"] = "all-MiniLM-L6-v2"
        suggestion["param_count"] = "23M"
        suggestion["quality_gain"] = "+7-12% MRR"
    else:
        suggestion["model"] = "all-MiniLM-L6-v2"
        suggestion["param_count"] = "23M"
        suggestion["quality_gain"] = "+5-8% MRR"

    # Estimate training time: ~50ms per example per epoch on CPU (rough)
    est_sec = num_files * 0.05 * 3  # 3 epochs
    if est_sec < 60:
        suggestion["est_training_time"] = f"{int(est_sec)}s"
    elif est_sec < 3600:
        suggestion["est_training_time"] = f"{est_sec / 60:.0f}m"
    else:
        suggestion["est_training_time"] = f"{est_sec / 3600:.1f}h"

    return suggestion


def train_model(
    project_path: str,
    model_name: str = "all-MiniLM-L6-v2",
    epochs: int = 3,
    incremental: bool = False,
    output_dir: str | None = None,
) -> dict:
    """Fine-tune an embedding model on the codebase using TSDAE.

    Returns training stats: {epochs, loss, model_path, duration_sec, num_examples}
    """
    SentenceTransformer, InputExample, losses = _check_training_deps()
    from torch.utils.data import DataLoader

    if output_dir is None:
        output_dir = os.path.join(project_path, ".codexlr8_model")

    model = SentenceTransformer(model_name)
    texts = _collect_texts(project_path)

    if len(texts) < 10:
        raise ValueError(
            f"Not enough files to train: {len(texts)} found. Need at least 10."
        )

    # Generate TSDAE examples: (corrupted, original) pairs
    print(f"  Preparing {len(texts)} training examples...")
    examples = []
    for text in texts:
        corrupted = _corrupt_text(text)
        examples.append(InputExample(texts=[corrupted, text]))

    # Train
    batch_size = min(8, len(texts))
    dataloader = DataLoader(examples, batch_size=batch_size, shuffle=True)
    loss = losses.DenoisingAutoEncoderLoss(model, tie_encoder_decoder=True)

    warmup = max(10, len(dataloader) // 10)

    start = time.time()
    model.fit(
        train_objectives=[(dataloader, loss)],
        epochs=epochs,
        warmup_steps=warmup,
        output_path=output_dir,
        show_progress_bar=False,
    )
    duration = time.time() - start

    # Write config snippet
    config_path = os.path.join(project_path, ".codexlr8.yaml")
    _update_config_for_model(config_path, output_dir)

    return {
        "model_path": output_dir,
        "num_examples": len(examples),
        "epochs": epochs,
        "duration_sec": int(duration),
    }


def _update_config_for_model(config_path: str, model_dir: str):
    """Update .codexlr8.yaml to point embeddings.model at the fine-tuned model."""
    import yaml

    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}

    if "embeddings" not in config:
        config["embeddings"] = {}
    config["embeddings"]["enabled"] = True
    config["embeddings"]["model"] = model_dir

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False)
