"""Master-to-camera audio segment alignment."""

from .dtw import DtwError, DtwPath, align_feature_sequences
from .features import FeatureError, FeatureSequence, extract_features
from .matcher import SegmentMatcher
from .models import (
    AlignmentCandidate,
    AlignmentError,
    AlignmentSettings,
    BlockerCode,
    CandidateMatch,
    EmptyCandidatesError,
    MatchDiagnostics,
    MatchMethod,
    MatchStatus,
    SegmentMatch,
    SegmentRequest,
)

__all__ = [
    "AlignmentCandidate",
    "AlignmentError",
    "AlignmentSettings",
    "BlockerCode",
    "CandidateMatch",
    "DtwError",
    "DtwPath",
    "EmptyCandidatesError",
    "FeatureError",
    "FeatureSequence",
    "MatchDiagnostics",
    "MatchMethod",
    "MatchStatus",
    "SegmentMatch",
    "SegmentMatcher",
    "SegmentRequest",
    "align_feature_sequences",
    "extract_features",
]
