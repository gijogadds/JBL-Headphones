from typing import Optional, Sequence


EQ_PRESET_NAMES = (
    "Jazz",
    "Vocal",
    "Bass",
    "Extreme Bass",
    "Club",
    "Studio",
    "Pop",
    "Personalizado",
)

EQ_PRESET_GAINS = {
    0: [4.0, 2.0, 1.0, 2.5, -1.5, -1.5, 0.0, 1.0, 2.0, 4.0],
    1: [-1.5, -3.0, -3.0, 1.0, 3.5, 3.5, 3.0, 1.5, 0.0, -1.5],
    2: [6.0, 3.0, 3.0, 2.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0],
    3: [4.0, 3.0, 5.0, 3.5, -1.0, 0.0, 0.0, 2.0, 2.0, 0.0],
    4: [1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0],
    5: [-2.0, -1.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    6: [2.0, 2.0, 2.0, -2.0, 2.0, 0.0, 1.0, 2.0, 0.0, -3.0],
}

_PRESET_INDEX_BY_CATEGORY = {
    1: 0,
    2: 1,
    3: 2,
    9: 3,
    6: 4,
    7: 5,
    13: 6,
    103: 7,
}


def identify_eq_preset(
    category: Optional[int],
    gains: Sequence[float],
) -> int:
    if category in _PRESET_INDEX_BY_CATEGORY:
        return _PRESET_INDEX_BY_CATEGORY[category]

    for preset_index, preset_gains in EQ_PRESET_GAINS.items():
        if len(gains) == len(preset_gains) and all(
            abs(actual - expected) <= 0.05
            for actual, expected in zip(gains, preset_gains)
        ):
            return preset_index
    return 7
