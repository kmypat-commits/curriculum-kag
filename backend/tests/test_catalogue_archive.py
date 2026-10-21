from scripts.archive_catalogue_to_snapshot import retained_course_ids, course_references


def test_archive_keeps_historical_manual_and_used_courses_plus_prerequisites():
    courses = [(1, 'EPVO-1'), (2, 'EPVO-2'), (3, 'EPVO-3'),
               (4, 'MANUAL-1'), (5, 'EPVO-5'), (6, 'EPVO-6')]
    keep = retained_course_ids(courses, {'EPVO-1'}, {3}, [(3, 5), (5, 6), (6, 5)])
    assert keep == {1, 3, 4, 5, 6}
    assert {cid for cid, _ in courses} - keep == {2}


def test_course_references_ignore_unrelated_entity_ids():
    assert course_references({'id': 50, 'course_id': 3, 'items': [
        {'course_id': 'EPVO-8'}, {'prerequisites': [9, 'MANUAL-2']},
    ]}, {'EPVO-8': 8, 'MANUAL-2': 2}) == {2, 3, 8, 9}
