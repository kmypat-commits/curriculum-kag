from app.services import content_evaluation


def test_old_description_prefix_does_not_validate_an_edited_course():
    assert not content_evaluation.description_cache_matches(
        'Изучает методы управления.',
        'Изучает методы управления. Дополнительно изучает биоинформатику.',
    )


def test_description_cache_accepts_only_complete_normalised_content():
    assert content_evaluation.description_cache_matches('  Полное описание  ', 'Полное описание')
    assert not content_evaluation.description_cache_matches('', '')
