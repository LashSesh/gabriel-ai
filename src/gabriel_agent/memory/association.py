"""Associative retrieval layer (ADR-20): the native engine's walk over the co-citation graph.

Association history is what the system itself has established: every claim the memory holds
with the assessment status ``supported`` cites a set of observations, and the source keys of
those observations were cited together in a verified deliverable. Those sets, in chain order,
are the observation batches of the engine; the resulting co-observation graph (ADR-18, ADR-19)
is the association structure. A retrieval with the declared association profile seeds the walk
on the lexically matching sources, reads out the regional mass at every candidate source at
the declared time and ranks a candidate by the larger of its lexical and its structural score.

Everything is declared and retained: the profile, the executable digest, the digest of the
batches, the entities, the seeds, the snapshot identity and the masses. Authorization, the
revision rule, revocation and the frontier are applied before any association is computed, so
the walk can only re-rank sources the principal could retrieve anyway; it never adds one. Mass
is a model readout of the conditioned walk, not a relevance probability.

Bounds (ADR-25): the engine walks at most ``CAPS["max_batches"]`` batches over at most
``max_entities`` entities. A longer history is reduced to the batches that touch a seed, beyond
the batch cap to the latest of those in chain order, and beyond the entity cap to the latest of
those whose entities fit; the record's ``window`` retains the caps, how many batches were
available, how many the walk saw and the rule (``whole history`` when nothing was cut), and
``batches_sha256`` covers the walked batches, so a reproduction recomputes the same window. Only
a single batch wider than the entity cap is ``capacity_exceeded``.

Erosion (ADR-23): the history a retrieval walks over is projected onto that retrieval's own
candidates. A supported claim contributes the source keys of its supporting observations that
the retrieval could admit (at its frontier, for its principal, under its access policy revision,
revision rule and source kinds) and nothing else; a claim keeps contributing only while at least
two of its keys remain, because a single key says nothing about co-citation. What was removed
and why is retained in the record (``erosion``), and the claims themselves are read as of the
frontier from the chain, so a retained manifest reproduces from the chain however the memory
moved on afterwards (``MemoryService.reproduce``).
"""
from __future__ import annotations

import math

from ..adapters import native_graph
from ..contracts.codec import canonical, sha256_hex

PROFILE = {"schema": "gabriel.association-profile/1", "profile_id": "co-citation-walk-v1", "time_bits": native_graph.bits(1.0), "backend": "auto_region",
           "max_seeds": 8, "max_entities": native_graph.CAPS["max_nodes"], "seed_min_score_milli": 1, "combination": "max"}
STATUSES = ("computed", "no_history", "no_seeds", "no_seeds_in_history", "capacity_exceeded", "unavailable", "eroded")
EROSION_REASONS = ("revoked", "out_of_scope", "kind_not_allowed", "contested", "unresolved_revision", "not_at_frontier")
MIN_BATCH_KEYS = 2
# ADR-25: the engine admits at most CAPS["max_batches"] observation batches and max_entities entities per job; the walk
# over a longer history sees the batches that touch a seed, of those the latest in chain order within the batch cap, and
# of those the latest whose entities fit the entity cap; the record retains what was available, what was used and the rule
WINDOW_RULE = "batches touching a seed, the latest in chain order, within the engine's caps"
WHOLE_HISTORY = "whole history"


def milli(mass: float) -> int:
    return int(math.floor(1000.0 * mass + 0.5))


def _memory_sequence(frontier) -> int:
    return int(frontier.memory_sequence if hasattr(frontier, "memory_sequence") else frontier["memory_sequence"])


def supported_claims(service, frontier) -> list:
    """The claims whose latest record at or before the frontier carries the assessment
    ``supported``, in the chain order of that record. Read from the chain, not from the current
    claim table: a reassessment after the frontier (a retraction, a later verifier) never changes
    what a retrieval at that frontier saw, so the retrieval stays reproducible (ADR-23)."""
    latest = {}
    for seq, sha in service._db.execute("SELECT seq, record_sha FROM entries WHERE kind = 'claim' AND seq <= ? ORDER BY seq", (_memory_sequence(frontier),)).fetchall():
        record = service._load(sha)
        latest[record["claim_id"]] = (seq, record)
    return [record for _, record in sorted(latest.values(), key=lambda pair: pair[0]) if record["assessment_status"] == "supported"]


def cocitation_history(service, frontier, retrievable: dict | None = None) -> tuple:
    """Every supported claim available at the frontier, in chain order, with the source keys its
    supporting observations cite and its provenance (the claim and the task whose verified run
    established it), so a carried source can say why it is there (ADR-21).

    ADR-23: with ``retrievable`` (source key -> None when the key is a candidate of the retrieval,
    else the reason it is not) each claim is projected onto its retrievable keys, a claim with
    fewer than ``MIN_BATCH_KEYS`` remaining keys contributes nothing, and the second value says
    what eroded: claims available, claims contributing, keys removed and the reasons. Without
    ``retrievable`` the raw history of the chain is returned (nothing removed)."""
    history = []
    erosion = {"claims_available": 0, "claims_contributing": 0, "keys_removed": 0, "removed_by": {}}
    for record in supported_claims(service, frontier):
        erosion["claims_available"] += 1
        keys, seen = [], set()
        for observation_id in record["supporting_observation_ids"]:
            row = service._db.execute("SELECT source_key FROM observations WHERE observation_id = ?", (observation_id,)).fetchone()
            if row is None or row[0] in seen:
                continue
            seen.add(row[0])
            reason = None if retrievable is None else retrievable.get(row[0], "not_at_frontier")
            if reason is not None:
                erosion["keys_removed"] += 1
                erosion["removed_by"][reason] = erosion["removed_by"].get(reason, 0) + 1
                continue
            keys.append(row[0])
        if len(keys) >= MIN_BATCH_KEYS:
            erosion["claims_contributing"] += 1
            history.append({"claim_id": record["claim_id"], "task_id": record["task_id"], "keys": sorted(keys)})
    return history, erosion


def cocitation_batches(service, frontier, retrievable: dict | None = None) -> list:
    """Source keys cited together by every supported claim available at the frontier, in chain order."""
    return [entry["keys"] for entry in cocitation_history(service, frontier, retrievable)[0]]


def links(history: list, seeds: list, carried: list, limit: int = 8) -> dict:
    """ADR-21: for every carried key (mass from the walk, not a seed itself) the seeds it was cited
    together with, and the claims and tasks of the verified runs that cited them together. A key
    reached only through other keys has no direct seed; its claims are those that cite it at all."""
    out = {}
    for key in carried:
        citing = [entry for entry in history if key in entry["keys"]]
        with_seed = [entry for entry in citing if any(seed in entry["keys"] for seed in seeds)]
        direct = []
        for entry in with_seed:
            for seed in seeds:
                if seed in entry["keys"] and seed not in direct:
                    direct.append(seed)
        claims, tasks = [], []
        for entry in (with_seed or citing):
            if entry["claim_id"] is not None and entry["claim_id"] not in claims:
                claims.append(entry["claim_id"])
            if entry["task_id"] is not None and entry["task_id"] not in tasks:
                tasks.append(entry["task_id"])
        out[key] = {"direct": bool(direct), "seeds": direct[:limit], "claims": claims[:limit], "task_ids": tasks[:limit]}
    return out


def _entities(batches: list) -> list:
    order = []
    for batch in batches:
        for key in batch:
            if key not in order:
                order.append(key)
    return order


def structural_scores(batches: list, seeds: list, candidates: list, profile: dict, binaries: dict | None = None, history: list | None = None,
                      erosion: dict | None = None) -> tuple:
    """Masses per candidate source key and the retained association record. ``batches``: co-citation
    batches (source keys); ``seeds``: lexically matching keys in rank order; ``candidates``: the
    keys of every retrievable item; ``history``: the batches with their provenance (ADR-21), from
    which the record's ``links`` name why every carried key carries; ``erosion``: the projection
    summary of ADR-23, retained as computed. Keys outside the history get no mass. A history whose
    every claim eroded is reported as ``eroded``, not as ``no_history``."""
    record = {"schema": "gabriel.association-record/1", "profile": dict(profile), "status": "computed", "executable_sha256": None,
              "batches_sha256": sha256_hex(canonical(batches)), "entities": [], "seeds": [], "snapshot_identity": None, "masses_milli": {}, "links": {}}
    if erosion is not None:
        record["erosion"] = dict(erosion)
    if not batches:
        eroded = erosion is not None and int(erosion.get("claims_available", 0)) > 0
        return {}, dict(record, status="eroded" if eroded else "no_history")
    if not seeds:
        return {}, dict(record, status="no_seeds")
    entities = _entities(batches)
    seeds_in = [key for key in seeds if key in entities][: int(profile["max_seeds"])]
    if not seeds_in:
        return {}, dict(record, status="no_seeds_in_history", entities=entities[: int(profile["max_entities"])])
    max_batches, max_entities = int(native_graph.CAPS["max_batches"]), int(profile["max_entities"])
    available = len(batches)
    window = {"max_batches": max_batches, "max_entities": max_entities, "available": available, "used": available, "rule": WHOLE_HISTORY}
    if len(entities) > max_entities or len(batches) > max_batches:
        # the walk is bounded (ADR-20, ADR-25): keep the batches that touch a seed (one hop), of those the latest in chain
        # order up to the engine's batch cap, and of those the latest whose entities fit the entity cap; a single batch
        # beyond the entity cap cannot be walked and the association is declared capacity_exceeded
        keep = [position for position in range(len(batches)) if any(key in batches[position] for key in seeds_in)]
        if len(keep) > max_batches:
            keep = keep[-max_batches:]
        while keep and len(_entities([batches[position] for position in keep])) > max_entities:
            keep = keep[1:]
        batches = [batches[position] for position in keep]
        if history is not None:
            history = [history[position] for position in keep]
        entities = _entities(batches)
        record["batches_sha256"] = sha256_hex(canonical(batches))
        window = dict(window, used=len(batches), rule=WINDOW_RULE)
        if not batches:
            # the seeds are the ones the history held; no batch was walked
            return {}, dict(record, status="capacity_exceeded", seeds=seeds_in, window=window)
        seeds_in = [key for key in seeds_in if key in entities]  # every kept batch touches a seed, so at least one remains
    record["window"] = window
    binaries = binaries if binaries is not None else native_graph.binaries()
    observer = binaries.get("engine_observer")
    if observer is None:
        return {}, dict(record, status="unavailable", entities=entities, seeds=seeds_in)
    index = {key: position for position, key in enumerate(entities)}
    candidates_in = [key for key in candidates if key in index]
    source = [{"entity": position, "re_bits": native_graph.bits(1.0 if entities[position] in seeds_in else 0.0), "im_bits": native_graph.bits(0.0)}
              for position in range(len(entities))]
    queries = [{"source": source, "targets": [index[key]], "times_bits": [profile["time_bits"]], "threshold_bits": native_graph.bits(0.0),
                "deadband_bits": native_graph.bits(0.0)} for key in candidates_in]
    job = {"schema": native_graph.OBSERVER_SCHEMA, "backend": profile["backend"], "batches": [[index[key] for key in batch] for batch in batches], "queries": queries}
    masses = {}
    if candidates_in:
        response = native_graph.invoke(observer["path"], observer["sha256"], job)
        native_graph.validate_observer_response(response, job)
        for key, result in zip(candidates_in, response["query_results"]):
            masses[key] = native_graph.number(result["values"][0]["mass_bits"])
        record["snapshot_identity"] = response["snapshot"]["identity"]
    carried = [key for key in candidates_in if key not in seeds_in and milli(masses.get(key, 0.0)) > 0]
    record.update(executable_sha256=observer["sha256"], entities=entities, seeds=seeds_in, masses_milli={key: milli(mass) for key, mass in masses.items()},
                  links=links(history if history is not None else [{"claim_id": None, "task_id": None, "keys": batch} for batch in batches], seeds_in, carried))
    return masses, record
