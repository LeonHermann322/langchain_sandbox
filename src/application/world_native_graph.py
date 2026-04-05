"""Native LangGraph world-building workflow definition (code-first)."""

from __future__ import annotations

import importlib
import json
import uuid
from typing import Any, Dict, TypedDict

from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph

from core.settings import WorkflowSettings

try:
    from langgraph.checkpoint.memory import MemorySaver
except Exception:  # pragma: no cover - version compatibility fallback
    MemorySaver = None


class _SafeFormatDict(dict):
    def __missing__(self, key):
        return ""


class WorldState(TypedDict, total=False):
    world_specification: str
    detailed_world: str
    world_qa_ok: bool
    world_qa_feedback: str
    desired_character_count: int
    characters: list[dict]
    character_count: int
    story_arcs: list[dict]
    current_story_arc: dict
    mentioned_characters: list[str]
    character_creation_plan: str
    act1_qa_ok: bool
    act1_qa_feedback: str
    story_qa_ok: bool
    story_qa_feedback: str
    story_arc_count: int
    final_story: str
    iterations: int


class WorldBuildingNativeWorkflow:
    """Code-first world-building graph using LangGraph native API."""

    def __init__(
        self, settings: WorkflowSettings | None = None, llm: Any | None = None
    ):
        self.settings = settings or WorkflowSettings.from_env()
        self.llm = llm or ChatOllama(
            model=self.settings.model_name,
            temperature=self.settings.model_temperature,
        )
        self.json_llm = self.llm.bind(format="json")
        self._app = None
        self._checkpointer = self._create_checkpointer()

    def _create_checkpointer(self):
        backend = (self.settings.checkpoint_backend or "memory").lower()

        if backend == "sqlite":
            try:
                sqlite_mod = importlib.import_module("langgraph.checkpoint.sqlite")
                SqliteSaver = getattr(sqlite_mod, "SqliteSaver")
            except Exception:
                SqliteSaver = None

            if not SqliteSaver:
                print("[!] SqliteSaver unavailable, falling back to MemorySaver.")
            else:
                sqlite_path = self.settings.checkpoint_sqlite_path
                try:
                    if hasattr(SqliteSaver, "from_conn_string"):
                        return SqliteSaver.from_conn_string(sqlite_path)
                    import sqlite3

                    conn = sqlite3.connect(sqlite_path, check_same_thread=False)
                    return SqliteSaver(conn)
                except Exception as exc:
                    print(f"[!] Failed to initialize sqlite checkpointer: {exc}")
                    print("[!] Falling back to MemorySaver.")

        if MemorySaver:
            return MemorySaver()

        return None

    def _invoke(
        self, prompt: str, temperature: float | None = None, json_mode: bool = False
    ):
        model = self.json_llm if json_mode else self.llm
        if temperature is None:
            return model.invoke(prompt)
        try:
            return model.bind(temperature=temperature).invoke(prompt)
        except TypeError:
            return model.bind(options={"temperature": temperature}).invoke(prompt)

    @staticmethod
    def _json_or_empty(content: Any) -> Dict[str, Any]:
        try:
            return json.loads(content) if isinstance(content, str) else dict(content)
        except Exception:
            return {}

    def _world_builder(self, state: WorldState) -> Dict[str, Any]:
        prompt = (
            "You are a highly creative world-building agent.\n\n"
            "Initial specification:\n{world_specification}\n\n"
            "Previous QA feedback:\n{world_qa_feedback}\n\n"
            "Task:\n"
            "Create or refine an intricate world description that remains faithful to the initial specification. "
            "Expand details across geography, culture, governance, conflict, economy, technology or magic system, and daily life.\n\n"
            "Return only the world description text."
        ).format_map(_SafeFormatDict(state))

        response = self._invoke(prompt, temperature=1.0, json_mode=False)
        return {
            "detailed_world": str(response.content).strip().replace('"', ""),
            "iterations": int(state.get("iterations", 0)) + 1,
        }

    def _world_qa(self, state: WorldState) -> Dict[str, Any]:
        prompt = (
            "You are a strict but practical QA agent for narrative consistency.\n\n"
            "Initial specification:\n{world_specification}\n\n"
            "Candidate world:\n{detailed_world}\n\n"
            "Evaluate alignment and coherence.\n\n"
            "Decision policy:\n"
            "- Set world_qa_ok = false ONLY for hard failures (major contradiction with specification, broken world logic, "
            "or insufficient detail to support an Act 1 draft and character generation).\n"
            "- If issues are minor or polish-level, set world_qa_ok = true and provide a short improvement note.\n\n"
            "Output JSON only:\n"
            '{{"world_qa_ok": true/false, "world_qa_feedback": "brief actionable note; if accepted, this is optional improvement guidance"}}'
        ).format_map(_SafeFormatDict(state))

        data = self._json_or_empty(
            self._invoke(prompt, temperature=0.1, json_mode=True).content
        )
        return {
            "world_qa_ok": bool(data.get("world_qa_ok", False)),
            "world_qa_feedback": data.get(
                "world_qa_feedback", "No QA feedback returned."
            ),
        }

    def _act1_builder(self, state: WorldState) -> Dict[str, Any]:
        prompt = (
            "You are a creative story architect drafting Act 1 for a larger narrative.\n\n"
            "World:\n{detailed_world}\n\n"
            "Existing characters already defined:\n{characters}\n\n"
            "Current Act 1 draft:\n{current_story_arc}\n\n"
            "Act 1 QA feedback:\n{act1_qa_feedback}\n\n"
            "Task:\n"
            "Create or refine exactly ONE Act 1 draft that establishes the setting tension, core conflict vector, and clear hooks for later arcs.\n"
            "You MAY mention or introduce main characters needed by the act.\n"
            "If characters already exist, integrate them meaningfully.\n\n"
            "Constraints:\n"
            "1. Keep continuity with world logic and social/technical constraints.\n"
            "2. Include morally ambiguous pressure points.\n"
            "3. Mention a concrete set of main characters needed for this act (at least 2, usually 3-5).\n"
            "4. Output only an arc draft (not full story).\n\n"
            "Important: Do not use literal '...' placeholders in any field; provide concrete content.\n\n"
            "Output JSON only:\n"
            '{{"current_story_arc": {{"arc_number": 1, "title": "Act title", "premise": "Concrete premise", "key_events": ["Event 1", "Event 2"], "character_focus": ["Character A", "Character B"], "mentioned_characters": ["Name A", "Name B"], "moral_tension": "Specific dilemma", "ending_hook": "Specific hook"}}}}'
        ).format_map(_SafeFormatDict(state))

        data = self._json_or_empty(
            self._invoke(prompt, temperature=0.9, json_mode=True).content
        )
        return {
            "current_story_arc": data.get(
                "current_story_arc", state.get("current_story_arc", {})
            ),
            "iterations": int(state.get("iterations", 0)) + 1,
        }

    def _act1_character_planner(self, state: WorldState) -> Dict[str, Any]:
        prompt = (
            "You are a cast-planning and character-creation assistant.\n\n"
            "World:\n{detailed_world}\n\n"
            "Act 1 draft:\n{current_story_arc}\n\n"
            "Previously created characters:\n{characters}\n\n"
            "Task:\n"
            "1. Extract the intended main characters from current_story_arc.\n"
            "2. Set desired_character_count to the number of intended main characters (minimum 2, maximum 5).\n"
            "3. Set mentioned_characters to the canonical list of intended names.\n"
            "4. Create a complete characters roster that covers the mentioned main cast (no duplicates).\n"
            "5. Set character_count to the length of the characters list.\n"
            "6. Provide concise character_creation_plan as a short summary of cast-role coverage.\n\n"
            "Character constraints:\n"
            "- Keep all characters world-consistent and distinct.\n"
            "- Use concrete motivations, conflicts, skills, and flaws.\n"
            "- Do not invent extra main characters beyond the needed cast size.\n\n"
            "Output JSON only:\n"
            '{{"desired_character_count": 0, "mentioned_characters": ["..."], "character_creation_plan": "...", '
            '"characters": [{{"name":"...","role":"...","origin":"...","core_motivation":"...",'
            '"conflict":"...","skills":["..."],"flaws":["..."],"world_link":"..."}}], "character_count": 0}}'
        ).format_map(_SafeFormatDict(state))

        data = self._json_or_empty(
            self._invoke(prompt, temperature=0.6, json_mode=True).content
        )
        desired = data.get(
            "desired_character_count", state.get("desired_character_count", 2)
        )
        if not isinstance(desired, int):
            desired = 2
        desired = max(2, min(5, desired))
        chars = data.get("characters", state.get("characters", []))
        count = data.get(
            "character_count", len(chars) if isinstance(chars, list) else 0
        )
        if not isinstance(count, int):
            count = len(chars) if isinstance(chars, list) else 0

        return {
            "desired_character_count": desired,
            "mentioned_characters": data.get(
                "mentioned_characters", state.get("mentioned_characters", [])
            ),
            "character_creation_plan": data.get(
                "character_creation_plan", state.get("character_creation_plan", "")
            ),
            "characters": (
                chars if isinstance(chars, list) else state.get("characters", [])
            ),
            "character_count": count,
        }

    def _act1_qa(self, state: WorldState) -> Dict[str, Any]:
        prompt = (
            "You are a strict but practical QA editor for Act 1 drafts.\n\n"
            "World:\n{detailed_world}\n\n"
            "Candidate Act 1:\n{current_story_arc}\n\n"
            "Mentioned characters for this act:\n{mentioned_characters}\n\n"
            "Created character roster:\n{characters}\n\n"
            "Current accepted arcs list (Act 1 should be index 0 if present):\n{story_arcs}\n\n"
            "Task:\n"
            "1. Validate world consistency and narrative coherence.\n"
            "2. Validate that the created character roster adequately covers the characters required by Act 1.\n"
            "3. Reject only for hard failures (continuity breaks, impossible events, severe mismatch between act and cast).\n"
            "4. If accepted, set story_arcs to a single-element list containing the accepted Act 1 and set story_arc_count to 1.\n"
            "5. If rejected, keep story_arcs and story_arc_count unchanged.\n"
            "6. ALWAYS provide non-empty act1_qa_feedback.\n\n"
            "Output JSON only:\n"
            '{{"act1_qa_ok": true/false, "act1_qa_feedback": "...", "story_arcs": [...], "story_arc_count": 0}}'
        ).format_map(_SafeFormatDict(state))

        data = self._json_or_empty(
            self._invoke(prompt, temperature=0.2, json_mode=True).content
        )
        act1_ok = bool(data.get("act1_qa_ok", False))
        current_arc = state.get("current_story_arc", {})
        if act1_ok and isinstance(current_arc, dict) and current_arc:
            # Use the canonical draft from state to avoid QA-side truncation/placeholder rewrites.
            story_arcs = [current_arc]
            story_arc_count = 1
        else:
            story_arcs = data.get("story_arcs", state.get("story_arcs", []))
            story_arc_count = data.get(
                "story_arc_count", state.get("story_arc_count", 0)
            )

        return {
            "act1_qa_ok": act1_ok,
            "act1_qa_feedback": data.get(
                "act1_qa_feedback", "No QA feedback returned."
            ),
            "story_arcs": story_arcs,
            "story_arc_count": story_arc_count,
        }

    def _story_builder(self, state: WorldState) -> Dict[str, Any]:
        prompt = (
            "You are a creative long-form story architect.\n\n"
            "World:\n{detailed_world}\n\n"
            "Canonical characters (fixed main cast; do not introduce additional main characters):\n{characters}\n\n"
            "Existing accepted arcs (Act 1 already included):\n{story_arcs}\n\n"
            "Story QA feedback:\n{story_qa_feedback}\n\n"
            "Task:\n"
            "Write exactly ONE NEW additional story arc (Act 2 or Act 3) that builds on the existing arcs.\n\n"
            "Constraints:\n"
            "1. Do not add new main characters.\n"
            "2. This arc must be distinct from prior arcs in tone/conflict focus.\n"
            "3. Raise stakes compared to prior arcs.\n"
            "4. Include morally ambiguous choices (no simple good/evil framing).\n"
            "5. Keep continuity with world physics and character motivations.\n\n"
            "Important: Do not use literal '...' placeholders in any field; provide concrete content.\n\n"
            "Output JSON only:\n"
            '{{"current_story_arc": {{"arc_number": 0, "title": "Act title", "premise": "Concrete premise", "key_events": ["Event 1", "Event 2"], "character_focus": ["Character A", "Character B"], "moral_tension": "Specific dilemma", "ending_hook": "Specific hook"}}}}'
        ).format_map(_SafeFormatDict(state))

        data = self._json_or_empty(
            self._invoke(prompt, temperature=0.9, json_mode=True).content
        )
        return {
            "current_story_arc": data.get(
                "current_story_arc", state.get("current_story_arc", {})
            ),
            "iterations": int(state.get("iterations", 0)) + 1,
        }

    def _story_qa(self, state: WorldState) -> Dict[str, Any]:
        prompt = (
            "You are a strict but practical story QA editor for additional arcs.\n\n"
            "World:\n{detailed_world}\n\n"
            "Characters:\n{characters}\n\n"
            "Existing accepted arcs:\n{story_arcs}\n\n"
            "Candidate arc:\n{current_story_arc}\n\n"
            "Task:\n"
            "1. Validate world consistency, character consistency, novelty vs prior arcs, and narrative quality.\n"
            "2. If accepted, append candidate arc to story_arcs and increment story_arc_count.\n"
            "3. If rejected, keep story_arcs unchanged and provide concise correction feedback.\n"
            "4. ALWAYS output non-empty story_qa_feedback.\n"
            "5. When story_arc_count reaches 3 after acceptance (Act 1 + two additional arcs), also produce final_story that ties all arcs together with a thought-provoking morally grey climax.\n\n"
            "Decision policy:\n"
            "- Reject only for clear continuity/consistency/duplication failures.\n"
            "- Accept if issues are minor and can be refined later.\n\n"
            "Output JSON only:\n"
            '{{"story_qa_ok": true/false, "story_qa_feedback": "...", "story_arcs": [...], "story_arc_count": 0, "final_story": "...or empty if fewer than 3 accepted arcs"}}'
        ).format_map(_SafeFormatDict(state))

        data = self._json_or_empty(
            self._invoke(prompt, temperature=0.2, json_mode=True).content
        )
        story_ok = bool(data.get("story_qa_ok", False))
        existing_arcs = state.get("story_arcs", [])
        current_arc = state.get("current_story_arc", {})

        if (
            story_ok
            and isinstance(existing_arcs, list)
            and isinstance(current_arc, dict)
            and current_arc
        ):
            story_arcs = [
                dict(arc) if isinstance(arc, dict) else arc for arc in existing_arcs
            ]
            current_arc_number = current_arc.get("arc_number")
            replaced = False
            if current_arc_number is not None:
                for idx, arc in enumerate(story_arcs):
                    if (
                        isinstance(arc, dict)
                        and arc.get("arc_number") == current_arc_number
                    ):
                        story_arcs[idx] = current_arc
                        replaced = True
                        break
            if not replaced:
                story_arcs.append(current_arc)
            story_arc_count = len([arc for arc in story_arcs if isinstance(arc, dict)])
        else:
            story_arcs = data.get("story_arcs", state.get("story_arcs", []))
            story_arc_count = data.get(
                "story_arc_count", state.get("story_arc_count", 0)
            )

        return {
            "story_qa_ok": story_ok,
            "story_qa_feedback": data.get(
                "story_qa_feedback", "No QA feedback returned."
            ),
            "story_arcs": story_arcs,
            "story_arc_count": story_arc_count,
            "final_story": data.get("final_story", state.get("final_story", "")),
        }

    @staticmethod
    def _route_world_qa(state: WorldState) -> str:
        return (
            "to_act1"
            if bool(state.get("world_qa_ok")) or int(state.get("iterations", 0)) >= 8
            else "retry_world"
        )

    @staticmethod
    def _route_character_planner(state: WorldState) -> str:
        count = int(state.get("character_count", 0) or 0)
        desired = int(state.get("desired_character_count", 0) or 0)
        return "to_act1_qa" if count >= desired and desired >= 2 else "retry_planner"

    @staticmethod
    def _route_act1_qa(state: WorldState) -> str:
        return "to_story" if bool(state.get("act1_qa_ok")) else "retry_act1"

    @staticmethod
    def _route_story_qa(state: WorldState) -> str:
        return (
            "done"
            if int(state.get("story_arc_count", 0)) >= 3
            or int(state.get("iterations", 0)) >= 90
            else "next_story"
        )

    def compile(self):
        builder = StateGraph(WorldState)

        builder.add_node("world_builder", self._world_builder)
        builder.add_node("world_qa", self._world_qa)
        builder.add_node("act1_builder", self._act1_builder)
        builder.add_node("act1_character_planner", self._act1_character_planner)
        builder.add_node("act1_qa", self._act1_qa)
        builder.add_node("story_builder", self._story_builder)
        builder.add_node("story_qa", self._story_qa)

        builder.add_edge("world_builder", "world_qa")
        builder.add_conditional_edges(
            "world_qa",
            self._route_world_qa,
            {"to_act1": "act1_builder", "retry_world": "world_builder"},
        )

        builder.add_edge("act1_builder", "act1_character_planner")
        builder.add_conditional_edges(
            "act1_character_planner",
            self._route_character_planner,
            {"to_act1_qa": "act1_qa", "retry_planner": "act1_character_planner"},
        )

        builder.add_conditional_edges(
            "act1_qa",
            self._route_act1_qa,
            {"to_story": "story_builder", "retry_act1": "act1_builder"},
        )

        builder.add_edge("story_builder", "story_qa")
        builder.add_conditional_edges(
            "story_qa",
            self._route_story_qa,
            {"done": END, "next_story": "story_builder"},
        )

        builder.set_entry_point("world_builder")

        if self._checkpointer is not None:
            return builder.compile(checkpointer=self._checkpointer)
        return builder.compile()

    def run(
        self, initial_state: Dict[str, Any], thread_id: str | None = None
    ) -> Dict[str, Any]:
        app = self.compile() if self._app is None else self._app
        self._app = app

        if thread_id is None:
            thread_id = str(initial_state.get("thread_id") or uuid.uuid4())

        config = {"configurable": {"thread_id": thread_id}}
        return app.invoke(initial_state, config=config)
