"""F1 reason seed payloads with verified English and project TC/SC translations.

Codes are project identifiers, not official numeric category codes. Verification
applies to the English source wording, source letter and reference pages only.
The tuple is fixed; seed consumers should copy a payload before changing it.
F2 rejected-questionable reasons belong to the later determination workflow.
"""

from typing import Final, TypedDict


class InvalidReasonSeed(TypedDict):
    code: str
    stage: str
    label_en: str
    label_tc: str
    label_sc: str
    source_english: str
    source_letter: str | None
    reference_page: int | None
    reference_printed_page: int | None
    verified_source: bool
    translation_provenance: str
    is_other: bool
    explanation_required: bool


DEFAULT_INVALID_REASONS: Final[tuple[InvalidReasonSeed, ...]] = (
    {
        "code": "gc-f1-a",
        "stage": "f1",
        "label_en": "Endorsed with the words “重複” and “TENDERED”",
        "label_tc": "註有「重複」及「TENDERED」字樣",
        "label_sc": "注有“重複”及“TENDERED”字样",
        "source_english": "Endorsed with the words “重複” and “TENDERED”",
        "source_letter": "a",
        "reference_page": 114,
        "reference_printed_page": 115,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "gc-f1-b",
        "stage": "f1",
        "label_en": (
            "Endorsed with the words “損壞” and “SPOILT” and has/have been "
            "mistakenly put into the ballot box"
        ),
        "label_tc": "註有「損壞」及「SPOILT」字樣，並被誤放入票箱",
        "label_sc": "注有“損壞”及“SPOILT”字样，并被误放入票箱",
        "source_english": (
            "Endorsed with the words “損壞” and “SPOILT” and has/have been "
            "mistakenly put into the ballot box"
        ),
        "source_letter": "b",
        "reference_page": 114,
        "reference_printed_page": 115,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "gc-f1-c",
        "stage": "f1",
        "label_en": (
            "Endorsed with the words “未用” and “UNUSED” and has/have been "
            "mistakenly put into the ballot box"
        ),
        "label_tc": "註有「未用」及「UNUSED」字樣，並被誤放入票箱",
        "label_sc": "注有“未用”及“UNUSED”字样，并被误放入票箱",
        "source_english": (
            "Endorsed with the words “未用” and “UNUSED” and has/have been "
            "mistakenly put into the ballot box"
        ),
        "source_letter": "c",
        "reference_page": 114,
        "reference_printed_page": 115,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "gc-f1-d",
        "stage": "f1",
        "label_en": "Unmarked",
        "label_tc": "沒有填劃",
        "label_sc": "没有填划",
        "source_english": "Unmarked",
        "source_letter": "d",
        "reference_page": 114,
        "reference_printed_page": 115,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "gc-f1-e",
        "stage": "f1",
        "label_en": "Not marked by the chop provided at the polling station (clearly invalid)",
        "label_tc": "並非用投票站提供的印章填劃（明顯無效）",
        "label_sc": "并非用投票站提供的印章填划（明显无效）",
        "source_english": (
            "Not marked by the chop provided at the polling station (clearly invalid)"
        ),
        "source_letter": "e",
        "reference_page": 114,
        "reference_printed_page": 115,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "gc-f1-f",
        "stage": "f1",
        "label_en": "Contains votes for more than 1 candidate",
        "label_tc": "投票予多於 1 名候選人",
        "label_sc": "投票给超过 1 名候选人",
        "source_english": "Contains votes for more than 1 candidate",
        "source_letter": "f",
        "reference_page": 123,
        "reference_printed_page": 124,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "gc-f1-g",
        "stage": "f1",
        "label_en": "Contains a vote for a candidate whose name thereon is crossed out",
        "label_tc": "投票予選票上姓名已被劃去的候選人",
        "label_sc": "投票给选票上姓名已被划去的候选人",
        "source_english": "Contains a vote for a candidate whose name thereon is crossed out",
        "source_letter": "g",
        "reference_page": 123,
        "reference_printed_page": 124,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "other-f1",
        "stage": "f1",
        "label_en": "Other",
        "label_tc": "其他",
        "label_sc": "其他",
        "source_english": "",
        "source_letter": None,
        "reference_page": None,
        "reference_printed_page": None,
        "verified_source": False,
        "translation_provenance": "project_translation",
        "is_other": True,
        "explanation_required": True,
    },
)
