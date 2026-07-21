import uuid
from datetime import datetime

from pydantic import BaseModel

from demosense.models.aggregate import Aggregate
from demosense.services.rollup import MIN_RESPONDENTS_FOR_DETAIL


class AggregateRead(BaseModel):
    question_id: uuid.UUID
    respondent_n: int
    stats: dict | None
    suppressed: bool
    computed_at: datetime

    @classmethod
    def from_aggregate(cls, aggregate: Aggregate) -> "AggregateRead":
        suppressed = aggregate.respondent_n < MIN_RESPONDENTS_FOR_DETAIL
        return cls(
            question_id=aggregate.question_id,
            respondent_n=aggregate.respondent_n,
            stats=None if suppressed else aggregate.stats,
            suppressed=suppressed,
            computed_at=aggregate.computed_at,
        )
