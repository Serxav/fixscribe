import pytest
from pydantic import ValidationError

from app.schemas import Box, Guide, ScrewMap, Step


def make_step(index=1, start_s=0.0, end_s=10.0, **extra):
    return Step(
        index=index,
        title="Remove cover",
        instruction="Unscrew the back cover.",
        start_s=start_s,
        end_s=end_s,
        **extra,
    )


def test_valid_step_with_screws():
    step = make_step(
        keyframe_s=4.5,
        screws=ScrewMap(
            count=2,
            boxes=[
                Box(number=1, x=0.1, y=0.1, w=0.05, h=0.05),
                Box(number=2, x=0.8, y=0.1, w=0.05, h=0.05),
            ],
        ),
    )
    assert step.screws.count == 2
    assert step.review == "auto"


def test_end_before_start_fails():
    with pytest.raises(ValidationError, match="end_s must be after start_s"):
        make_step(start_s=12.0, end_s=10.0)


def test_keyframe_outside_step_fails():
    with pytest.raises(ValidationError, match="keyframe_s"):
        make_step(keyframe_s=11.0)


def test_negative_seconds_fail():
    with pytest.raises(ValidationError):
        make_step(start_s=-1.0)


def test_depends_on_later_step_fails():
    with pytest.raises(ValidationError, match="earlier steps"):
        make_step(index=2, start_s=10.0, end_s=20.0, depends_on=[3])


def test_box_outside_image_fails():
    with pytest.raises(ValidationError, match="outside the image"):
        Box(number=1, x=0.9, y=0.1, w=0.2, h=0.1)


def test_duplicate_screw_numbers_fail():
    box = Box(number=1, x=0.1, y=0.1, w=0.1, h=0.1)
    with pytest.raises(ValidationError, match="unique"):
        ScrewMap(count=2, boxes=[box, box])


def test_unknown_field_fails():
    with pytest.raises(ValidationError):
        make_step(colour="red")


def test_valid_guide():
    guide = Guide(
        title="Replace battery",
        device="Phone X",
        mode="narrated",
        duration_s=30.0,
        steps=[make_step(), make_step(index=2, start_s=10.0, end_s=25.0)],
    )
    assert len(guide.steps) == 2


def test_guide_step_after_video_end_fails():
    with pytest.raises(ValidationError, match="ends after the video"):
        Guide(title="t", device="d", mode="silent", duration_s=8.0, steps=[make_step()])


def test_guide_steps_out_of_order_fail():
    with pytest.raises(ValidationError, match="ordered by start_s"):
        Guide(
            title="t",
            device="d",
            mode="silent",
            steps=[
                make_step(start_s=10.0, end_s=20.0),
                make_step(index=2, start_s=0.0, end_s=5.0),
            ],
        )


def test_guide_bad_indexes_fail():
    with pytest.raises(ValidationError, match="indexes"):
        Guide(title="t", device="d", mode="silent", steps=[make_step(index=2)])
