import operator
from typing import Annotated, Any, Dict, List, TypedDict


class AgentState(TypedDict):
    specifications: str
    current_search_query: str
    job_listings: List[dict]
    job_listings_with_content: List[dict]
    valid_results: Annotated[List[dict], operator.add]
    critique: str
    iterations: int


class NodeConfig(TypedDict, total=False):
    id: str
    type: str
    prompt: str
    output_key: str
    output_mapping: Dict[str, str]
    input_key: str


class ConditionConfig(TypedDict):
    source: str
    condition: str
    mapping: Dict[str, str]


class WorkflowConfig(TypedDict):
    entry_point: str
    nodes: List[NodeConfig]
    edges: List[List[str]]
    conditional_edges: List[ConditionConfig]


StateUpdate = Dict[str, Any]
