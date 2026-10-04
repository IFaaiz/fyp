"""Train and evaluate the shared compact MailEx extraction baseline."""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import torch
from mailex_extraction.compact import (CompactExtractor, AutoTokenizer, canonical_rows,
    encode_features, inventory, make_targets, positive_weights, predict, read_rows,
    set_seed, sha256, write_jsonl, categorical_targets)
from mailex_extraction.metrics import score_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", required=True)
    parser.add_argument("--dev", required=True)
    parser.add_argument("--encoder", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--head-lr", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--patience", type=int, default=2)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()
    torch.set_num_threads(4)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    set_seed(args.seed)
    train, dev = canonical_rows(read_rows(args.train)), canonical_rows(read_rows(args.dev))
    types, roles = inventory(train)
    tokenizer = AutoTokenizer.from_pretrained(args.encoder, local_files_only=True, use_fast=True)
    train_features = [encode_features(row, tokenizer) for row in train]
    dev_features = [encode_features(row, tokenizer) for row in dev]
    model = CompactExtractor(args.encoder, types, roles).to(args.device)
    model.encoder.gradient_checkpointing_enable()
    t_weight, a_weight = [weight.to(args.device) for weight in positive_weights(train, model)]
    type_weights = torch.cat((torch.ones((len(types), 1), device=args.device), t_weight.reshape(len(types), 2).sqrt()), dim=1)
    role_weights = torch.cat((torch.ones(1, device=args.device), a_weight.sqrt())).clamp_max(8)
    argument_loss = torch.nn.CrossEntropyLoss(weight=role_weights)
    heads = [parameter for name, parameter in model.named_parameters() if not name.startswith("encoder.")]
    optimizer = torch.optim.AdamW([{"params": model.encoder.parameters(), "lr": args.lr},
                                  {"params": heads, "lr": args.head_lr}], weight_decay=0.01)
    config = {**vars(args), "event_types": types, "role_keys": roles,
              "train_sha256": sha256(args.train), "dev_sha256": sha256(args.dev),
              "encoder_revision": "12040accade4e8a0f71eabdb258fecc2e7e948be",
              "max_length": 512, "stride": 128, "positive_weight_cap": 50,
              "selection_metric": "argument_records.role_exact.micro.f1", "complete_message_windows": True,
              "empty_token_policy": "remove zero-width tokens from model view only; retain exact reconstructed text",
              "torch_cpu_threads": 4, "cuda_training_autocast": "bfloat16",
              "loss_family": "categorical_bio", "class_weight_policy": "sqrt TRAIN negative/positive ratio, original ratio capped50; Oweight1",
              "trigger_conditioning_dropout": 0.2, "relative_distance_embedding": "signed log2 buckets, plus no-trigger bucket",
              "same_type_trigger_target_collision": "B precedence, full native gold retained",
              "categorical_decode": "argmax including O, then probability threshold",
              "decoder_bio_conflict_policy": "choose larger B/I score before applying threshold; B wins exact ties",
              "decoder_orphan_i_policy": "start_span", "discontinuous_trigger_grouping": "not_supported",
              "gold_type_oracle": "one slot per gold instance, type supplied, zero trigger vector"}
    (output / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    best, stale, history = -1, 0, []
    for epoch in range(1, args.epochs + 1):
        model.train()
        order = list(range(len(train)))
        random.shuffle(order)
        total_loss, steps = 0.0, 0
        started = time.perf_counter()
        for start in range(0, len(order), args.batch_size):
            selected = [i for i in order[start:start + args.batch_size] if train[i]["tokens"]]
            if not selected:
                continue
            rows = [train[i] for i in selected]
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=args.device.startswith("cuda")):
                vectors = model.encode(rows, [train_features[i] for i in selected], args.device)
                losses = []
                for row, words in zip(rows, vectors):
                    target, events = categorical_targets(row, model, args.device)
                    logits = model.trigger(model.dropout(words)).reshape(len(words), len(types), 3)
                    raw_loss = torch.nn.functional.cross_entropy(logits.reshape(-1, 3), target.reshape(-1), reduction="none").reshape_as(target)
                    weights = type_weights[torch.arange(len(types), device=args.device)[None, :], target]
                    loss = (raw_loss * weights).sum() / weights.sum()
                    if events:
                        loss = loss + torch.stack([argument_loss(model.argument_logits(words, index, [] if random.random() < 0.2 else indices), target)
                                                  for index, indices, target in events]).mean()
                    losses.append(loss)
                loss = torch.stack(losses).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += float(loss.detach())
            steps += 1
            if steps % 100 == 0:
                print(json.dumps({"epoch": epoch, "steps": steps, "loss": total_loss / steps}), flush=True)
        predictions = predict(model, dev, dev_features, args.device, args.threshold)
        metrics = score_rows(dev, predictions)
        score = metrics["argument_records"]["role_exact"]["micro"]["f1"] or 0.0
        result = {"epoch": epoch, "loss": total_loss / max(1, steps), "seconds": time.perf_counter() - started,
                  "selection_score": score, "metrics": metrics}
        history.append(result)
        (output / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
        print(json.dumps({"epoch": epoch, "seconds": result["seconds"], "selection_score": score}), flush=True)
        if score > best:
            best, stale = score, 0
            torch.save(model.state_dict(), output / "model.pt")
            write_jsonl(output / "dev_predictions.jsonl", predictions)
            (output / "dev_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
            (output / "selected_epoch.json").write_text(json.dumps({"epoch": epoch, "score": score}), encoding="utf-8")
        else:
            stale += 1
        if stale >= args.patience:
            break
    model.load_state_dict(torch.load(output / "model.pt", map_location=args.device, weights_only=True))
    for mode in ("gold_type", "gold_type_trigger"):
        predictions = predict(model, dev, dev_features, args.device, args.threshold, mode=mode)
        write_jsonl(output / f"dev_{mode}_predictions.jsonl", predictions)
        metrics = score_rows(dev, predictions)
        (output / f"dev_{mode}_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (output / "checkpoint_sha256.txt").write_text(sha256(output / "model.pt") + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
