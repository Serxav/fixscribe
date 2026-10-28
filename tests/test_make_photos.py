from scripts.make_photos import merge, repeated, split_query


def test_split_query_one_kind_per_query():
    assert split_query("the graphics card and each RAM stick") == [
        "the graphics card",
        "each RAM stick",
    ]
    assert split_query("the rear derailleur and the cassette") == [
        "the rear derailleur",
        "the cassette",
    ]


def test_split_query_keeps_and_inside_a_name():
    assert split_query("the nuts and bolts tray") == ["the nuts and bolts tray"]


def test_repeated():
    assert repeated("each lug nut")
    assert not repeated("the drill chuck")


def test_merge_drops_the_same_part_found_twice():
    first = {"cut_box": [0, 0, 100, 100]}
    same = {"cut_box": [5, 5, 95, 95]}
    other = {"cut_box": [500, 500, 600, 600]}
    assert merge([first], [same, other]) == [first, other]
