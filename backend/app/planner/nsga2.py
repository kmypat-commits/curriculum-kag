"""Deterministic NSGA-II course selection for Curriculum-KAG T6."""
from __future__ import annotations

import math
import random
from typing import Dict, List

import numpy as np
from sqlalchemy.orm import Session

from app.models.course import Course
from app.models.embedding import MatchScore
from app.models.project import ProjectVersion
from app.kag.knowledge_graph import _build_course_vectors


def optimize_variants(
    version: ProjectVersion,
    db: Session,
    seed_course_ids: List[int],
    target_credits: int,
    maximum_credits: int,
    population_size: int = 100,
    generations: int = 200,
    crossover_probability: float = 0.9,
    mutation_probability: float = 0.1,
    random_seed: int | None = None,
) -> Dict[str, List[Dict]]:
    """Return three distinct Pareto-informed plan variants.

    Objectives follow T6: maximize bounded LO coverage, minimize mean cosine
    redundancy, and maximize credit-weighted domain entropy. Credit and
    prerequisite closure are repaired as hard constraints before evaluation.
    """
    all_courses = {course.id: course for course in db.query(Course).all()}
    domains = [
        (version.project.domain1 or "").lower().strip(),
        (version.project.domain2 or "").lower().strip(),
    ]
    constraints = version.project.constraints_json or {}
    program_type = str(constraints.get("program_type") or "standard").lower()
    interdisciplinary = program_type in {"interdisciplinary", "joint"} and bool(domains[1])
    min_domain_share = [
        max(0.0, min(1.0, float(constraints.get("min_domain1_percent") or 0) / 100.0)),
        max(0.0, min(1.0, float(constraints.get("min_domain2_percent") or 0) / 100.0)) if interdisciplinary else 0.0,
    ]

    def in_domain(course: Course) -> bool:
        domain = (course.domain or "").lower().strip()
        return bool(domain) and any(d and (d in domain or domain in d) for d in domains)

    closure_cache: Dict[int, set[int] | None] = {}

    def closure(course_id: int, visiting=None):
        if course_id in closure_cache:
            return closure_cache[course_id]
        visiting = visiting or set()
        course = all_courses.get(course_id)
        if course is None or course_id in visiting or not in_domain(course):
            return None
        result = {course_id}
        for prerequisite in course.prerequisites:
            nested = closure(prerequisite.id, visiting | {course_id})
            if nested is None:
                closure_cache[course_id] = None
                return None
            result.update(nested)
        closure_cache[course_id] = result
        return result

    root_ids = []
    universe = set()
    for course_id in seed_course_ids:
        chain = closure(course_id)
        if chain:
            root_ids.append(course_id)
            universe.update(chain)
    course_ids = sorted(universe)
    if not root_ids or sum((all_courses[cid].credits or 5) for cid in course_ids) < target_credits:
        return {}

    index = {course_id: i for i, course_id in enumerate(course_ids)}
    root_indices = [index[cid] for cid in root_ids]
    closure_indices = {
        index[cid]: {index[item] for item in closure(cid) or {cid} if item in index}
        for cid in root_ids
    }
    credits = np.array([all_courses[cid].credits or 5 for cid in course_ids], dtype=np.int32)
    lo_ids = [lo.id for lo in version.learning_outcomes]
    lo_index = {lo_id: i for i, lo_id in enumerate(lo_ids)}
    coverage = np.zeros((len(course_ids), len(lo_ids)), dtype=np.float32)
    for score in db.query(MatchScore).filter(
        MatchScore.project_version_id == version.id,
        MatchScore.course_id.in_(course_ids),
    ).all():
        if score.lo_id in lo_index:
            coverage[index[score.course_id], lo_index[score.lo_id]] = max(0.0, min(1.0, score.score))

    vectors = _build_course_vectors([all_courses[cid] for cid in course_ids], db)
    vector_matrix = np.zeros((len(course_ids), 1), dtype=np.float32)
    available_vectors = [vectors[cid] for cid in course_ids if cid in vectors]
    if available_vectors:
        dimension = len(available_vectors[0])
        vector_matrix = np.zeros((len(course_ids), dimension), dtype=np.float32)
        for cid, vector in vectors.items():
            if cid in index:
                norm = np.linalg.norm(vector)
                if norm > 1e-9:
                    vector_matrix[index[cid]] = vector / norm
    similarity = vector_matrix @ vector_matrix.T

    domain_index = np.array([
        0 if domains[0] and domains[0] in (all_courses[cid].domain or "").lower() else 1
        for cid in course_ids
    ], dtype=np.int8)
    prerequisite_counts = np.array([len(all_courses[cid].prerequisites) for cid in course_ids], dtype=np.int16)
    rng = random.Random(random_seed if random_seed is not None else version.id * 1009 + len(course_ids))

    def expand(genome: np.ndarray) -> np.ndarray:
        expanded = genome.copy()
        for root_index in root_indices:
            if genome[root_index]:
                for prerequisite_index in closure_indices[root_index]:
                    expanded[prerequisite_index] = True
        return expanded

    relevance = coverage.sum(axis=1)

    def repair(genome: np.ndarray) -> np.ndarray:
        genome = genome.copy()
        selectable = root_indices.copy()
        rng.shuffle(selectable)
        selected = expand(genome)
        attempts = 0
        while int(credits[selected].sum()) > maximum_credits and attempts < len(selectable) * 2:
            chosen_roots = [i for i in selectable if genome[i]]
            if not chosen_roots:
                break
            remove_index = min(chosen_roots, key=lambda i: (relevance[i] / max(credits[i], 1), rng.random()))
            genome[remove_index] = False
            selected = expand(genome)
            attempts += 1
        attempts = 0
        while int(credits[selected].sum()) < target_credits and attempts < len(selectable) * 3:
            current_credits = int(credits[selected].sum())
            candidates = []
            for candidate in selectable:
                if genome[candidate]:
                    continue
                trial = genome.copy(); trial[candidate] = True
                expanded = expand(trial)
                trial_credits = int(credits[expanded].sum())
                if trial_credits <= maximum_credits:
                    candidates.append((candidate, trial, expanded, trial_credits))
            if not candidates:
                break
            candidates.sort(key=lambda item: (
                min(item[3] - current_credits, target_credits - current_credits),
                relevance[item[0]],
                rng.random(),
            ), reverse=True)
            _, genome, selected, _ = candidates[0]
            attempts += 1
        return expand(genome)

    def objectives(genome: np.ndarray):
        selected = np.flatnonzero(genome)
        total = int(credits[selected].sum()) if len(selected) else 0
        penalty = abs(target_credits - total) if total < target_credits else max(0, total - maximum_credits)
        bounded_coverage = np.minimum(1.0, coverage[selected].sum(axis=0)) if len(selected) else np.zeros(len(lo_ids))
        coverage_objective = float(bounded_coverage.mean()) if len(bounded_coverage) else 0.0
        if len(selected) > 1:
            pairwise = similarity[np.ix_(selected, selected)]
            redundancy = float((pairwise.sum() - len(selected)) / (len(selected) * (len(selected) - 1)))
        else:
            redundancy = 0.0
        domain_credits = [int(credits[selected[domain_index[selected] == d]].sum()) for d in (0, 1)] if len(selected) else [0, 0]
        domain_total = max(sum(domain_credits), 1)
        proportions = [value / domain_total for value in domain_credits if value]
        entropy = -sum(value * math.log(value) for value in proportions)
        quota_penalty = sum(
            max(0.0, min_domain_share[index] - (domain_credits[index] / domain_total))
            for index in (0, 1)
        )
        prerequisite_burden = int(prerequisite_counts[selected].sum()) if len(selected) else 0
        return (coverage_objective, -redundancy, -quota_penalty, entropy, -float(penalty), -float(prerequisite_burden))

    def dominates(left, right):
        return all(a >= b for a, b in zip(left, right)) and any(a > b for a, b in zip(left, right))

    def rank_population(scores):
        domination_count = [0] * len(scores)
        dominated = [[] for _ in scores]
        fronts = [[]]
        for i, left in enumerate(scores):
            for j, right in enumerate(scores):
                if i == j:
                    continue
                if dominates(left, right): dominated[i].append(j)
                elif dominates(right, left): domination_count[i] += 1
            if domination_count[i] == 0: fronts[0].append(i)
        rank = [0] * len(scores)
        level = 0
        while level < len(fronts) and fronts[level]:
            next_front = []
            for i in fronts[level]:
                rank[i] = level
                for j in dominated[i]:
                    domination_count[j] -= 1
                    if domination_count[j] == 0: next_front.append(j)
            if next_front: fronts.append(next_front)
            level += 1
        crowding = [0.0] * len(scores)
        for front in fronts:
            if len(front) <= 2:
                for i in front: crowding[i] = float("inf")
                continue
            for objective_index in range(len(scores[0])):
                ordered = sorted(front, key=lambda i: scores[i][objective_index])
                crowding[ordered[0]] = crowding[ordered[-1]] = float("inf")
                span = scores[ordered[-1]][objective_index] - scores[ordered[0]][objective_index]
                if abs(span) < 1e-12: continue
                for position in range(1, len(ordered) - 1):
                    crowding[ordered[position]] += (
                        scores[ordered[position + 1]][objective_index] - scores[ordered[position - 1]][objective_index]
                    ) / span
        return fronts, rank, crowding

    def initial_genome():
        genome = np.zeros(len(course_ids), dtype=bool)
        shuffled = root_indices.copy(); rng.shuffle(shuffled)
        for candidate in shuffled:
            if rng.random() < 0.55:
                genome[candidate] = True
        return repair(genome)

    population = [initial_genome() for _ in range(population_size)]
    for _ in range(generations):
        scores = [objectives(genome) for genome in population]
        _, ranks, crowding = rank_population(scores)

        def tournament():
            a, b = rng.randrange(len(population)), rng.randrange(len(population))
            if ranks[a] != ranks[b]: return population[a if ranks[a] < ranks[b] else b]
            return population[a if crowding[a] >= crowding[b] else b]

        offspring = []
        while len(offspring) < population_size:
            left, right = tournament().copy(), tournament().copy()
            if rng.random() < crossover_probability:
                mask = np.array([rng.random() < 0.5 for _ in course_ids], dtype=bool)
                child = np.where(mask, left, right)
            else:
                child = left
            if rng.random() < mutation_probability:
                mutation_index = rng.choice(root_indices)
                child[mutation_index] = ~child[mutation_index]
            offspring.append(repair(child))
        combined = population + offspring
        combined_scores = [objectives(genome) for genome in combined]
        fronts, _, crowding = rank_population(combined_scores)
        population = []
        for front in fronts:
            if len(population) + len(front) <= population_size:
                population.extend(combined[i] for i in front)
            else:
                ordered = sorted(front, key=lambda i: crowding[i], reverse=True)
                population.extend(combined[i] for i in ordered[:population_size - len(population)])
                break

    unique = {}
    for genome in population:
        key = tuple(np.flatnonzero(genome))
        unique.setdefault(key, (genome, objectives(genome)))
    feasible = [item for item in unique.values() if item[1][3] == 0]
    if len(feasible) < 3:
        return {}

    chosen = {}
    remaining = feasible.copy()
    selectors = {
        "A": lambda item: (item[1][0], item[1][1], item[1][2]),
        "B": lambda item: (item[1][4], item[1][0], item[1][1]),
        "C": lambda item: (item[1][1], item[1][2], item[1][0]),
    }
    for variant in ("A", "B", "C"):
        best_index = max(
            range(len(remaining)),
            key=lambda index: selectors[variant](remaining[index]),
        )
        best = remaining.pop(best_index)
        chosen[variant] = best[0]

    result = {}
    for variant, genome in chosen.items():
        result[variant] = [
            {
                "course_id": course.id,
                "title": course.title,
                "domain": course.domain,
                "credits": course.credits or 5,
                "recommended_semester": course.recommended_semester,
                "prerequisites": [prerequisite.id for prerequisite in course.prerequisites],
                "type": course.cycle_component or "mandatory",
                "selection_method": "nsga2",
            }
            for index_value, course_id in enumerate(course_ids)
            if genome[index_value]
            for course in [all_courses[course_id]]
        ]
    return result
