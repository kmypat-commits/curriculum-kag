"""Reusable admission policy for project-domain course selection."""

def is_course_in_project_domain(course, *, excluded_course_ids, education_level,
    project_domains, declared_secondary_domain, interdisciplinary_professional,
    cyber_forensics_program, match_max_by_course, education_level_check,
    domain_match, domain_label_match, title_relevant, curriculum_role):
    if course.id in excluded_course_ids or not education_level_check(course, education_level):
        return False
    course_domain = str(course.domain or '').casefold()
    project_text = ' '.join(project_domains).casefold()
    medical = any(t in course_domain for t in ('medicine','medical','health','медицин','здрав','clinical'))
    medical_project = any(t in project_text for t in ('medicine','medical','health','медицин','здрав','clinical'))
    agriculture = any(t in f'{declared_secondary_domain} {project_text}' for t in ('agri','agro','farm','сельск','аграр','агроном','ауыл'))
    declared_medical = any(t in declared_secondary_domain for t in ('medicine','medical','health','медицин','здрав','clinical'))
    if medical and agriculture and not declared_medical:
        return False
    if not (domain_match(course, project_domains) or domain_label_match(course.domain, project_domains)):
        if medical_project and any(t in project_text for t in ('it','информ','computer','цифр')) and title_relevant(course, project_domains):
            return True
        return False
    if cyber_forensics_program:
        return curriculum_role(course, project_domains) == 'core'
    if interdisciplinary_professional and curriculum_role(course, project_domains) == 'general':
        return match_max_by_course.get(course.id, 0.0) >= 0.55
    return True
