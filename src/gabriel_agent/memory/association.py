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
"""
from __future__ import annotations

import math

from ..adapters import native_graph
from ..contracts.codec import canonical, loads, sha256_hex

PROFILE = {"schema": "gabriel.association-profile/1", "profile_id": "co-citation-walk-v1", "time_bits": native_graph.bits(1.0), "backend": "auto_region",
           "max_seeds": 8, "max_entities": native_graph.CAPS["max_nodes"], "seed_min_score_milli": 1, "combination": "max"}
STATUSES = ("computed", "no_history", "no_seeds", "no_seeds_in_history", "capacity_exceeded", "unavailable")


def milli(mass: float) -> int:
    return int(math.floor(1000.0 * mass + 0.5))


def cocitation_history(service, frontier) -> list:
    """Every supported claim available at the frontier, in chain order, with the source keys its
    supporting observations cite: the association history together with its provenance (the claim
    and the task whose verified run established it), so a carried source can say why it is there."""
    history = []
    rows = service._db.execute("SELECT seq, claim_id, task_id, supporting FROM claims WHERE status = 'supported' AND seq <= ? ORDER BY seq",
                               (int(frontier.memory_sequence),)).fetchall()
    for _, claim_id, task_id, supporting in rows:
        keys = []
        for observation_id in loads(supporting.encode("ascii")):
            row = service._db.execute("SELECT source_key FROM observations WHERE observation_id = ?", (observation_id,)).fetchone()
            if row is not None and row[0] not in keys:
                keys.append(row[0])
        if keys:
            history.append({"claim_id": claim_id, "task_id": task_id, "keys": sorted(keys)})
    return history


def cocitation_batches(service, frontier) -> list:
    """Source keys cited together by every supported claim available at the frontier, in chain order."""
    return [entry["keys"] for entry in cocitation_history(service, frontier)]


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


def structural_scores(batches: list, seeds: list, candidates: list, profile: dict, binaries: dict | None = None, history: list | None = None) -> tuple:
    """Masses per candidate source key and the retained association record. ``batches``: co-citation
    batches (source keys); ``seeds``: lexically matching keys in rank order; ``candidates``: the
    keys of every retrievable item; ``history``: the batches with their provenance (ADR-21), from
    which the record's ``links`` name why every carried key carries. Keys outside the history get
    no mass."""
    record = {"schema": "gabriel.association-record/1", "profile": dict(profile), "status": "computed", "executable_sha256": None,
              "batches_sha256": sha256_hex(canonical(batches)), "entities": [], "seeds": [], "snapshot_identity": None, "masses_milli": {}, "links": {}}
    if not batches:
        return {}, dict(record, status="no_history")
    if not seeds:
        return {}, dict(record, status="no_seeds")
    entities = _entities(batches)
    seeds_in = [key for key in seeds if key in entities][: int(profile["max_seeds"])]
    if not seeds_in:
        return {}, dict(record, status="no_seeds_in_history", entities=entities[: int(profile["max_entities"])])
    if len(entities) > int(profile["max_entities"]):
        # the walk is bounded: keep the batches that touch a seed (one hop); beyond the cap the association is declared unavailable
        batches = [batch for batch in batches if any(key in batch for key in seeds_in)]
        entities = _entities(batches)
        record["batches_sha256"] = sha256_hex(canonical(batches))
        if len(entities) > int(profile["max_entities"]):
            return {}, dict(record, status="capacity_exceeded", seeds=seeds_in)
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
