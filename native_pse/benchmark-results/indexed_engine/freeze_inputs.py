#!/usr/bin/env python3
"""Deterministically regenerate checked-in benchmark input bytes; never time work."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 2026092613


def main():
    engine = []
    for entities in [3, 5, 7, 8]:
        batches = []
        for tick in range(8):
            batches.append([json.dumps({
                "entity": entity, "tick": tick,
                "phase": float(tick % 11) * 0.02,
                "value": float((tick * 17 + entity * 31) % 101) / 101.0,
            }, sort_keys=True, separators=(",", ":")) for entity in range(entities)])
        engine.append({"entities": entities, "batches": batches})
    micro = []
    for n in [3, 5, 7]:
        seed = SEED
        mask = (1 << (n * (n - 1) // 2)) - 1
        words = []
        for _ in range(512):
            seed ^= (seed << 13) & ((1 << 64) - 1)
            seed ^= seed >> 7
            seed ^= (seed << 17) & ((1 << 64) - 1)
            words.append(seed & mask)
        buckets = {}
        collision_pair = None
        collision_slot = None
        for word in range(mask + 1):
            mixed = ((word | (n << 21)) * 0x9e3779b1) & 0xffffffff
            slot = (mixed ^ (mixed >> 16)) & 255
            for previous in buckets.get(slot, []):
                if previous.bit_count() != word.bit_count():
                    collision_pair, collision_slot = [previous, word], slot
                    break
            if collision_pair:
                break
            buckets.setdefault(slot, []).append(word)
        collision_words = collision_pair * 256 if collision_pair else []
        micro.append({"n": n, "fixed_word": mask, "fixed_graph": "complete graph",
                      "collision_words": collision_words, "collision_pair": collision_pair,
                      "collision_slot": collision_slot,
                      "changing_words": words, "changing_distinct_words": len(set(words)),
                      "changing_input_count": len(words), "seed": SEED})
    value = {"schema": 1, "engine": engine, "micro": micro,
             "seed_algorithm": "xorshift64 (13,7,17), wrapping u64, reset same seed for each n",
             "edge_encoding": "undirected edge i<j at bit j*(j-1)/2+i"}
    (HERE / "inputs.json").write_text(json.dumps(value, indent=2) + "\n")


if __name__ == "__main__":
    main()
