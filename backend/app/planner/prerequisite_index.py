"""Small helpers for loading prerequisite adjacency indexes."""

from collections import defaultdict


def build_prerequisite_index(db, association_table):
    index = defaultdict(list)
    for row in db.execute(association_table.select()).fetchall():
        index[int(row.course_id)].append(int(row.prerequisite_id))
    return dict(index)
