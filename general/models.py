import datetime

from pydantic import BaseModel

class Choice(BaseModel):
    """Used when a list of choices is needed. 'id' is a unique identifier for the choice."""
    label: str
    id: int

class Version(BaseModel):
    """Gives version information for the application"""
    version: str
    version_date: datetime.datetime
