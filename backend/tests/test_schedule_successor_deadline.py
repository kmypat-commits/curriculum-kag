from app.planner.course_scheduling import schedule_courses


class EmptyCatalogue:
    def query(self, *args):
        return self

    def filter(self, *args):
        return self

    def all(self):
        return []


def test_parent_is_placed_before_successors_semantic_deadline():
    courses = [
        {"course_id": 1, "title": "Communication skills", "credits": 5,
         "recommended_semester": 7, "prerequisites": []},
        {"course_id": 2, "title": "Основы коммуникативной культуры", "credits": 4,
         "recommended_semester": 4, "prerequisites": [1]},
    ]
    schedule = schedule_courses(courses, 8, 30, EmptyCatalogue())
    placements = {row["course_id"]: semester for semester, rows in schedule.items() for row in rows}
    assert placements[1] < placements[2] <= 6
