from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class CollectionMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    collection_id: str
    story_id: str
    story_title: str
    story_version: int
    sequence_order: int
    role_in_flow: str  # entry_point | intermediate | terminal
    test_cases_count: int = 0
    test_set_status: str = "draft"


class StoryCollectionBase(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    description: str | None = None
    collection_type: str = "dag_journey"


class StoryCollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    code: str | None = None
    description: str | None = None
    story_ids: list[str] = Field(default_factory=list)


class StoryCollectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    execution_order: list[str] | None = None


class StoryCollectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    description: str | None = None
    collection_type: str
    execution_order: list[str] = Field(default_factory=list)
    health_status: str
    metadata_info: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    members: list[CollectionMemberRead] = Field(default_factory=list)
    total_stories: int = 0
    total_test_cases: int = 0


class CollectionDiscoveryResult(BaseModel):
    discovered_collections_count: int
    synced_collections: list[StoryCollectionRead]
