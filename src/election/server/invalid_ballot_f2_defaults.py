"""F2 rejection seeds with verified English and project TC/SC translations.

Codes are project identifiers, not official numeric category codes. Verification
applies to English source wording, source letters and reference pages only.
The tuple fixes order and binding; consumers should copy payloads before mutation.
"""

from typing import Final

from election.server.invalid_ballot_defaults import InvalidReasonSeed

DEFAULT_F2_INVALID_REASONS: Final[tuple[InvalidReasonSeed, ...]] = (
    {
        "code": "gc-f2-h",
        "stage": "f2",
        "label_en": "With writing or mark by which the elector can possibly be identified",
        "label_tc": "載有可能識別選民身分的文字或記號",
        "label_sc": "载有可能识别选民身份的文字或记号",
        "source_english": "With writing or mark by which the elector can possibly be identified",
        "source_letter": "h",
        "reference_page": 119,
        "reference_printed_page": 120,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "gc-f2-i",
        "stage": "f2",
        "label_en": (
            "Not marked by the chop provided at the polling station "
            "(determined as invalid upon determination of Q-paper)"
        ),
        "label_tc": "並非用投票站提供的印章填劃（經問題選票判定後確定為無效）",
        "label_sc": "并非用投票站提供的印章填划（经问题选票判定后确定为无效）",
        "source_english": (
            "Not marked by the chop provided at the polling station "
            "(determined as invalid upon determination of Q-paper)"
        ),
        "source_letter": "i",
        "reference_page": 119,
        "reference_printed_page": 120,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "gc-f2-j",
        "stage": "f2",
        "label_en": "Substantially mutilated",
        "label_tc": "嚴重殘缺",
        "label_sc": "严重残缺",
        "source_english": "Substantially mutilated",
        "source_letter": "j",
        "reference_page": 119,
        "reference_printed_page": 120,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "gc-f2-k",
        "stage": "f2",
        "label_en": "Void for uncertainty",
        "label_tc": "因不明確而無效",
        "label_sc": "因不明确而无效",
        "source_english": "Void for uncertainty",
        "source_letter": "k",
        "reference_page": 119,
        "reference_printed_page": 120,
        "verified_source": True,
        "translation_provenance": "project_translation",
        "is_other": False,
        "explanation_required": False,
    },
    {
        "code": "other-f2",
        "stage": "f2",
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
