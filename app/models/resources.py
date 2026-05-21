from datetime import datetime
from typing import List

from pydantic import BaseModel


class ResearchReport(BaseModel):
    """미래에셋 리서치(당사) 메타데이터 — research_crawler 가 생성."""
    report_id: str
    title: str
    date: datetime
    author: str
    report_type: str
    source_url: str
    attachment_urls: List[str] = []
    normalized_text: str = ""
    tags: List[str] = []
    asset_class_tags: List[str] = []
    region_tags: List[str] = []
    sector_tags: List[str] = []
    company_tags: List[str] = []
    time_horizon: str = ""
    risk_conditions: str = ""
