"""Fine-tune SBERT with programme-wise multi-positive listwise ranking.

Every training group contains one LO, all sampled expert-positive courses and
unlinked courses from the same programme. Unlike binary/in-batch training, a
second valid course is never treated as a negative for the same LO.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

import torch
import torch.nn.functional as functional
from sentence_transformers import SentenceTransformer


LANGUAGES = ("ru", "kz", "en")
TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def localized(value: dict, language: str) -> str:
    order = (language, *(item for item in LANGUAGES if item != language))
    return next((str(value.get(item) or "").strip() for item in order if value.get(item)), "")


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def token_overlap(left: str, right: str) -> float:
    """Return a deterministic lexical hardness score for an unlinked course."""
    left_tokens = set(TOKEN_RE.findall(normalize(left)))
    right_tokens = set(TOKEN_RE.findall(normalize(right)))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def course_text(course: dict, language: str) -> str:
    return " | ".join(filter(None, (
        localized(course.get("title") or {}, language),
        localized(course.get("description") or {}, language),
    )))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def build_groups(
    path: Path,
    limit: int,
    candidates: int,
    max_positives: int,
    seed: int,
    language: str,
    min_expert_score: float,
    negative_strategy: str,
) -> tuple[list[dict], dict]:
    rng = random.Random(seed)
    reservoir: list[dict] = []
    eligible = 0
    stats = {"train_programmes": 0, "eligible_groups": 0, "selected_groups": 0, "positives": 0, "negatives": 0}
    with path.open(encoding="utf-8") as source:
        for line in source:
            program = json.loads(line)
            if program.get("split") != "train":
                continue
            stats["train_programmes"] += 1
            courses = {str(row["id"]): row for row in program.get("courses") or []}
            outcomes = {str(row["id"]): row for row in program.get("outcomes") or []}
            expert_scores = {
                (str(edge.get("course_id")), str(edge.get("lo_id"))): float(edge.get("score") or 0.0)
                for edge in program.get("expert_edges") or []
                if edge.get("course_id") is not None and edge.get("lo_id") is not None
            }
            edges_by_lo: dict[str, set[str]] = {}
            for course_id, lo_id in program.get("positive_edges") or []:
                if (
                    str(course_id) in courses
                    and str(lo_id) in outcomes
                    and expert_scores.get((str(course_id), str(lo_id)), 1.0) >= min_expert_score
                ):
                    edges_by_lo.setdefault(str(lo_id), set()).add(str(course_id))
            for lo_id, positive_ids in edges_by_lo.items():
                query = localized(outcomes[lo_id].get("text") or {}, language)
                positive_ids = list(positive_ids)
                negative_ids = [course_id for course_id in courses if course_id not in set(positive_ids)]
                if not query or not positive_ids or not negative_ids:
                    continue
                rng.shuffle(positive_ids)
                if negative_strategy == "lexical":
                    negative_ids.sort(
                        key=lambda course_id: token_overlap(
                            query, course_text(courses[course_id], language)
                        ),
                        reverse=True,
                    )
                else:
                    rng.shuffle(negative_ids)
                positive_ids = positive_ids[:max_positives]
                negative_ids = negative_ids[:max(1, candidates - len(positive_ids))]
                docs = [course_text(courses[course_id], language) for course_id in positive_ids + negative_ids]
                if not docs or any(not text for text in docs):
                    continue
                group = {
                    "query": query,
                    "documents": docs,
                    "positive_count": len(positive_ids),
                    "program_id": str(program.get("program_id") or ""),
                    "lo_id": lo_id,
                }
                eligible += 1
                if len(reservoir) < limit:
                    reservoir.append(group)
                else:
                    position = rng.randrange(eligible)
                    if position < limit:
                        reservoir[position] = group
    rng.shuffle(reservoir)
    stats["eligible_groups"] = eligible
    stats["selected_groups"] = len(reservoir)
    stats["positives"] = sum(row["positive_count"] for row in reservoir)
    stats["negatives"] = sum(len(row["documents"]) - row["positive_count"] for row in reservoir)
    return reservoir, stats


def embed(model: SentenceTransformer, texts: list[str], device: str) -> torch.Tensor:
    # Recent sentence-transformers versions include non-tensor metadata in the
    # feature dictionary. Only tensors belong on CUDA; the model still needs
    # the metadata unchanged.
    features = {
        key: value.to(device) if hasattr(value, "to") else value
        for key, value in model.tokenize(texts).items()
    }
    return functional.normalize(model(features)["sentence_embedding"], p=2, dim=1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="experiment-results/epvo-link-context-dataset/programs.jsonl")
    parser.add_argument("--model", default="models/epvo-sbert-finetuned-40k")
    parser.add_argument("--output", default="models/epvo-sbert-multipositive-listwise-4k")
    parser.add_argument("--groups", type=int, default=4000)
    parser.add_argument("--candidates", type=int, default=16)
    parser.add_argument("--max-positives", type=int, default=8)
    parser.add_argument("--batch-groups", type=int, default=3)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=3e-7)
    parser.add_argument("--temperature", type=float, default=0.07)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--language", choices=LANGUAGES, default="ru")
    parser.add_argument("--min-expert-score", type=float, default=0.5)
    parser.add_argument("--negative-strategy", choices=("random", "lexical"), default="random")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    progress = output.with_name(output.name + "-progress.json")
    groups, stats = build_groups(
        Path(args.input), args.groups, args.candidates, args.max_positives, args.seed,
        args.language, args.min_expert_score, args.negative_strategy
    )
    common = {
        "status": "prepared",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "output": args.output,
        "objective": "multi_positive_listwise_softmax",
        "temperature": args.temperature,
        "sampling": stats,
        "min_expert_score": args.min_expert_score,
        "negative_strategy": args.negative_strategy,
    }
    write_json(progress, common)
    if args.dry_run:
        print(json.dumps(common, ensure_ascii=False, indent=2))
        return
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if not groups:
        raise RuntimeError("No training groups were produced")

    torch.manual_seed(args.seed)
    model = SentenceTransformer(args.model, device="cuda", local_files_only=True)
    model.max_seq_length = 192
    transformer = model[0].auto_model
    transformer.gradient_checkpointing_enable()
    if hasattr(transformer, "embeddings"):
        for parameter in transformer.embeddings.parameters():
            parameter.requires_grad = False
    layers = list(getattr(getattr(transformer, "encoder", None), "layer", []))
    for layer in layers[:6]:
        for parameter in layer.parameters():
            parameter.requires_grad = False
    optimizer = torch.optim.AdamW(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=args.learning_rate,
        weight_decay=0.01,
    )
    scaler = torch.amp.GradScaler("cuda")
    losses = []
    model.train()
    for epoch in range(args.epochs):
        for start in range(0, len(groups), args.batch_groups):
            batch = groups[start:start + args.batch_groups]
            queries = [row["query"] for row in batch]
            documents = [text for row in batch for text in row["documents"]]
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda"):
                query_embeddings = embed(model, queries, "cuda")
                document_embeddings = embed(model, documents, "cuda")
                offset = 0
                group_losses = []
                for index, row in enumerate(batch):
                    size = len(row["documents"])
                    logits = document_embeddings[offset:offset + size] @ query_embeddings[index] / args.temperature
                    log_probs = functional.log_softmax(logits, dim=0)
                    group_losses.append(-log_probs[:row["positive_count"]].mean())
                    offset += size
                loss = torch.stack(group_losses).mean()
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            losses.append(float(loss.detach().cpu()))
            step = start // args.batch_groups + 1
            if step % 100 == 0:
                write_json(progress, {**common, "status": "training", "epoch": epoch + 1, "step": step, "mean_loss": sum(losses[-100:]) / min(100, len(losses))})
    model.save(str(output))
    result = {
        **common,
        "status": "complete",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "steps": len(losses),
        "mean_loss": sum(losses) / len(losses),
        "cuda": torch.cuda.get_device_name(0),
    }
    write_json(progress, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
